#!/usr/bin/env python3
"""Tek komutla uçtan uca sınama (yalnız standart kütüphane).

    python uctan-uca.py [--hizli] [--arac AD ...] [--agmsg-kaynak YOL] [--sonuc-dizini YOL]

Sırayla:
  1. birim testler (sayılarla),
  2. makinede hangi araç kurulu (kurmaz),
  3. kurulu her adaptör için GEÇİCİ yeni oturumla gerçek "merhaba" (komut -> çıktı kanıtı),
  4. imza: doğru imza kabul, yanlış/imzasız/taklit reddedilir (dogrula + çalışan `bekle` süreci),
  5. agmsg (yabancı depo) yalnız izole WSL "kutu" dağıtımında a1<->a2 gönder/al (--hizli ile atlanır),
  6. temizlik denetimi (açık süreç, geçici dosya, agy/hermes oturum kalıntısı, canlı kutu, özgün repo).
Sonuç: kanit/uctan-uca-sonuc.md ve .json. Canlı kutuya ve özgün repoya yazmaz.

Makineye özgü yollar ortam değişkeniyle verilir; verilmezse ilgili adım ATLANDI olur:
  KUTU_KORUNAN_DIZIN  dokunulmaması gereken mevcut kutu (yalnız okunur, sha256 karşılaştırılır)
  KUTU_OZGUN_REPO     koşu sonunda `git status` temiz mi bakılacak depo
  KUTU_AGMSG_KAYNAK   agmsg kaynak klasörü (PARÇA A; --agmsg-kaynak ile de verilir)
  KUTU_CIKTI_KOKU     WSL kutu çıktı kökü (yalnız bu koşunun çıktı klasörü silinir)
  KUTU_WSL_BETIGI     WSL "kutu" sarmalayıcısı (varsayılan ~/.agents/scripts/kutu)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

KOK = Path(__file__).resolve().parent
sys.path.insert(0, str(KOK))
import kutu_adaptor as ka  # noqa: E402
import kutu_imza  # noqa: E402

PY = sys.executable
CALISTI, CALISMADI, KURULU_DEGIL, ATLANDI = "CALISTI", "CALISMADI", "KURULU DEGIL", "ATLANDI"



def _ortam_yolu(ad: str) -> Path | None:
    """Ortam değişkeni doluysa yol, yoksa None (ilgili adım ATLANDI olur; makineye özgü varsayılan yol yok)."""
    d = os.environ.get(ad, "").strip()
    return Path(d) if d else None


CANLI_KUTU = _ortam_yolu("KUTU_KORUNAN_DIZIN")     # dokunulmaması gereken mevcut kutu (yalnız okunur, karşılaştırılır)
OZGUN_REPO = _ortam_yolu("KUTU_OZGUN_REPO")        # koşu sonunda `git status` temiz mi bakılacak depo
KUTU_BETIGI = _ortam_yolu("KUTU_WSL_BETIGI") or Path.home() / ".agents" / "scripts" / "kutu"   # WSL "kutu" kum havuzu sarmalayıcısı
AGMSG_KAYNAK = _ortam_yolu("KUTU_AGMSG_KAYNAK")    # agmsg kaynak klasörü (PARÇA A)
KUTU_CIKTI_KOKU = _ortam_yolu("KUTU_CIKTI_KOKU")   # WSL kutu çıktı kökü (yalnız bu koşunun klasörü silinir)
AGY_KOK = Path.home() / ".gemini" / "antigravity-cli"

SONUCLAR: list[dict] = []


def kayit(madde: str, durum: str, kanit: str = "", kok_neden: str = "", cozum: str = "", yeniden: str = "") -> dict:
    s = {"madde": madde, "durum": durum, "kanit": " / ".join(x.strip() for x in kanit.strip().splitlines() if x.strip()), "kok_neden": kok_neden, "cozum": cozum,
         "yeniden_sinama": yeniden}
    SONUCLAR.append(s)
    isaret = {CALISTI: "[OK]", CALISMADI: "[!!]", KURULU_DEGIL: "[--]", ATLANDI: "[..]"}[durum]
    print(f"{isaret} {madde}: {durum}" + (f"  | {kok_neden}" if kok_neden else ""), flush=True)
    return s


def calistir(komut: list[str], zaman_asimi: int = 120, girdi: str | None = None, env: dict | None = None,
             cwd: Path | None = None) -> tuple[int, str]:
    """(çıkış, stdout+stderr). Zaman aşımında yalnız kendi süreç ağacını öldürür."""
    ortam = dict(os.environ, **(env or {}))
    ortam["PYTHONUTF8"] = "1"
    p = subprocess.Popen(komut, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         cwd=cwd or KOK, env=ortam)
    try:
        out, _ = p.communicate(girdi.encode("utf-8") if girdi else None, timeout=zaman_asimi)
    except subprocess.TimeoutExpired:
        ka._agaci_oldur(p)
        return 124, f"[zaman aşımı {zaman_asimi} sn]"
    return p.returncode, out.decode("utf-8", "replace")


def kisalt(metin: str, n: int = 700) -> str:
    metin = metin.strip()
    return metin if len(metin) <= n else metin[:n] + " ..."


def sha(yol: Path) -> str:
    return hashlib.sha256(yol.read_bytes()).hexdigest() if yol.is_file() else "(yok)"


def canli_ozet() -> dict:
    """Canlı kutu dosyaları: {ad: (boyut, sha256)} + öncekini sonradan prefix olarak karşılaştırmak için içerik boyu."""
    sonuc = {}
    if CANLI_KUTU is not None and CANLI_KUTU.is_dir():
        for a in sorted(CANLI_KUTU.glob("*")):
            if a.is_file():
                b = a.read_bytes()
                sonuc[a.name] = (len(b), hashlib.sha256(b).hexdigest())
    return sonuc


def canli_degisim(once: dict) -> tuple[list[str], list[str]]:
    """(bozulan, eklenen_satirlar). Canlı kutuda başkalarının yeni satır EKLEMESİ normaldir (append-only);
    eski içeriğin değişmesi ya da bu koşunun izini taşıyan satır (adaptör adı/gönderen/konu 'merhaba') sorundur."""
    bozulan, eklenen = [], []
    for ad, (boyut, ozet) in once.items():
        yol = CANLI_KUTU / ad
        if not yol.is_file():
            bozulan.append(f"{ad}: silinmiş")
            continue
        b = yol.read_bytes()
        if hashlib.sha256(b[:boyut]).hexdigest() != ozet:
            bozulan.append(f"{ad}: eski içerik değişmiş")
        elif ad == "kayit.jsonl" and len(b) > boyut:
            for satir in b[boyut:].decode("utf-8", "replace").splitlines():
                try:
                    k = json.loads(satir)
                except ValueError:
                    continue
                eklenen.append(f"{k.get('ts', '?')[11:19]} {k.get('kimden')}->{k.get('kime')}")
                if k.get("kimden") in ka.ADAPTORLER or k.get("kime") in ka.ADAPTORLER or k.get("konu") == "merhaba":
                    bozulan.append(f"kayit.jsonl: bu koşunun izini taşıyan satır: {k.get('id')}")
    return bozulan, eklenen


def git_durum(repo: Path) -> str:
    rc, out = calistir(["git", "-C", str(repo), "status", "--short"], 30)
    return out.strip() if rc == 0 else f"(git hatası: {out.strip()[:100]})"


def agy_konusmalari() -> set[str]:
    k = AGY_KOK / "conversations"
    return {p.name.split(".")[0] for p in k.glob("*")} if k.is_dir() else set()


def kutu_cmd(calisma: Path, *argv: str, zaman_asimi: int = 120, env: dict | None = None) -> tuple[int, str]:
    ortam = dict(env or {}, KUTU_DIZIN=str(calisma / "kutu"), KUTU_CALISMA_DIZIN=str(calisma / "oturum"))
    return calistir([PY, "-X", "utf8", str(KOK / "kutu.py"), *argv], zaman_asimi, env=ortam)


# ----------------------------------------------------------------- adımlar ----

def adim_birim() -> None:
    rc, out = calistir([PY, "-X", "utf8", "-m", "unittest", "discover", "-s", "tests"], 300)
    m = re.search(r"Ran (\d+) tests? in ([\d.]+)s", out)
    ok = rc == 0 and "OK" in out.splitlines()[-1] if out.strip() else False
    kayit("birim testler (unittest discover -s tests)", CALISTI if ok else CALISMADI,
          f"$ python -m unittest discover -s tests -> çıkış {rc}; "
          + (f"{m.group(1)} test, {m.group(2)} sn; son satır: {out.strip().splitlines()[-1]}" if m else kisalt(out)),
          "" if ok else "birim test başarısız: " + kisalt(out, 300))


def adim_araclar(calisma: Path) -> dict:
    rc, out = kutu_cmd(calisma, "araclar", "--json", zaman_asimi=180)
    try:
        liste = json.loads(out[out.index("["):])
    except ValueError:
        kayit("araç tespiti (kutu araclar)", CALISMADI, kisalt(out), "araclar çıktısı ayrıştırılamadı")
        return {}
    ozet = "; ".join(f"{s['adaptor']}={'KURULU ' + s['surum'].split(' · ')[0] if s['kurulu'] else 'kurulu değil'}"
                     for s in liste)
    kayit("araç tespiti (kutu araclar --json)", CALISTI, f"$ kutu.py araclar --json -> {ozet}")
    return {s["adaptor"]: s for s in liste}


def hermes_http_sonda() -> tuple[bool, str]:
    url = (os.environ.get("KUTU_HERMES_URL") or ka.HERMES_VARSAYILAN_URL).rstrip("/") + "/health"
    try:
        with urlrequest.urlopen(url, timeout=5) as y:
            return True, f"GET {url} -> {y.status}"
    except urlerror.HTTPError as h:
        return True, f"GET {url} -> HTTP {h.code} (sunucu açık)"
    except (urlerror.URLError, OSError) as h:
        return False, f"GET {url} -> {type(getattr(h, 'reason', h)).__name__}: bağlantı kurulamadı"


KOK_NEDEN = {
    "hermes-http": ("Hermes API sunucusu bu makinede kapalı: kullanıcının çalışan gateway'inde 127.0.0.1:8642 dinlenmiyor ve "
                    "API_SERVER_KEY tanımlı değil (.env ve config.yaml'da api_server yok). /v1/runs yalnız "
                    "API sunucusu platformu açıksa vardır.",
                    "Araştırma: <HERMES_KAYNAK>/gateway/platforms/api_server.py ve api_server_runs.py (POST /v1/runs {input, "
                    "session_id} -> 202 {run_id}; GET /v1/runs/{id} -> status completed/failed/cancelled + output; Bearer "
                    "API_SERVER_KEY, anahtar güçlü değilse sunucu açılmayı reddeder). Açmak için ~/.hermes .env'e API_SERVER_ENABLED=true "
                    "ve güçlü API_SERVER_KEY yazıp GATEWAY'İ YENİDEN BAŞLATMAK gerekir: prod servis restart'ı ve ayar değişikliği "
                    "ayrı yetki gerektirir, bu yüzden UYGULANMADI. Uygulanan çözüm: aynı arayüz için `hermes -z` adaptörü "
                    "(belgeli tek atımlık mod) ve /v1/runs istemcisi sahte sunucuya karşı birim testli (tests/test_adaptor.py). "
                    "Gerçek sunucu açılırsa: KUTU_HERMES_ANAHTAR=<anahtar> python uctan-uca.py --arac hermes-http"),
}


def adim_merhaba(calisma: Path, araclar: dict, secilen: list[str] | None) -> None:
    kutu_dizini = calisma / "kutu"
    for ad, a in ka.ADAPTORLER.items():
        if secilen and ad not in secilen:
            continue
        madde = f"gerçek 'merhaba': {ad}"
        bilgi = araclar.get(ad, {})
        if not bilgi.get("kurulu"):
            kayit(madde, KURULU_DEGIL, f"kutu araclar -> {ad}: kurulu değil ({a.belge})",
                  f"{a.arac} PATH'te, bilinen kurulum yollarında ve ~/.agents/arac-yollari.json'da yok; kurulmadı (kural: kurulu olmayanı kurma)")
            continue
        if ad == "hermes-http":
            acik, sonda = hermes_http_sonda()
            if not (acik and os.environ.get("KUTU_HERMES_ANAHTAR")):
                neden, cozum = KOK_NEDEN["hermes-http"]
                kayit(madde, CALISMADI, f"{sonda}; KUTU_HERMES_ANAHTAR "
                      + ("tanımlı" if os.environ.get("KUTU_HERMES_ANAHTAR") else "tanımlı değil"), neden, cozum,
                      "yeniden sınama: sunucu yok -> adaptör sahte sunucuya karşı geçti (birim testler); gerçek sunucu SINANMADI")
                continue
        metin = "Merhaba! Bu bir bağlantı sınamasıdır; bana kısaca merhaba de."
        rc, out = kutu_cmd(calisma, "gonder", "--kime", ad, "--kimden", "danisman", "--konu", "merhaba",
                           "--metin", metin, "--imza-zorunlu", "--zaman-asimi", "170", zaman_asimi=200)
        kayitlar = _kayitlar(kutu_dizini)
        giden = next((k for k in reversed(kayitlar) if k.get("kimden") == "danisman" and k.get("kime") == ad), None)
        cevap = next((k for k in reversed(kayitlar) if k.get("kimden") == ad and k.get("kime") == "danisman"), None)
        komut = f"$ kutu.py gonder --kime {ad} --kimden danisman --konu merhaba --metin '{metin}' --imza-zorunlu"
        if rc == 0 and cevap and giden:
            gecerli = kutu_imza.dogrula(cevap)[0] == kutu_imza.GECERLI
            kimlik_var = giden["id"] in cevap["metin"]        # yanıt BU mesaja ait (benzersiz kimlik yankılandı)
            durum = CALISTI if (gecerli and kimlik_var) else CALISMADI
            kayit(madde, durum,
                  f"{komut} -> çıkış {rc}; teslim kimliği {giden['id']} / yanıt kaydı: {cevap['id']} "
                  f"(imza {'geçerli' if gecerli else 'GEÇERSİZ'}, mesaj kimliği yanıtta yankılandı: {'evet' if kimlik_var else 'hayır'}) "
                  f"/ yanıt metni: {kisalt(cevap['metin'], 200)}",
                  "" if durum == CALISTI else ("yanıt imzası doğrulanamadı" if not gecerli else "yanıt geldi ama kutu kimliği yankılanmadı"))
        else:
            kayit(madde, CALISMADI, f"{komut} -> çıkış {rc}; {kisalt(out, 500)}",
                  _kok_neden_tahmin(ad, out))


def _kok_neden_tahmin(ad: str, out: str) -> str:
    o = out.lower()
    if "dönmedi" in o:
        return "zaman aşımı: araç yanıt vermedi (kimlik doğrulama/ağ/model kotası olabilir); çıktıdaki ayrıntıya bakın"
    if "kurulu değil" in o:
        return "araç bulunamadı"
    return "adaptör hata verdi; çıktıya bakın: " + kisalt(out, 200)


def _kayitlar(kutu_dizini: Path) -> list[dict]:
    yol = kutu_dizini / "kayit.jsonl"
    if not yol.is_file():
        return []
    sonuc = []
    for satir in yol.read_text(encoding="utf-8").splitlines():
        try:
            sonuc.append(json.loads(satir))
        except ValueError:
            pass
    return sonuc


def adim_imza(calisma: Path) -> None:
    """Gerçek `dogrula` ve ÇALIŞAN `bekle --imza-zorunlu` süreci: iyi kabul, kötü reddedilir."""
    kutu_dizini = calisma / "imza-kutu"
    kutu_dizini.mkdir(parents=True, exist_ok=True)
    ortam = {"KUTU_DIZIN": str(kutu_dizini)}
    kutu_imza.anahtar_uret("danisman")
    kutu_imza.anahtar_uret("codex")

    def imzali(kimden, **ek):
        k = {"id": "uu-" + secrets.token_hex(4), "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
             "kimden": kimden, "kime": "claude", "konu": "", "metin": "metin", "durum": "gonderildi"}
        k.update(ek)
        return kutu_imza.imzala(k)

    iyi = imzali("codex", id="uu-iyi", metin="DOGRU-IMZALI-METIN")
    bozuk = imzali("codex", id="uu-bozuk", metin="ilk")
    bozuk["metin"] = "DEGISTIRILMIS-ZEHIRLI-METIN"
    taklit = imzali("codex", id="uu-taklit", metin="x")
    taklit["kimden"] = "kemal"
    yanlis_anahtar = {"id": "uu-yanlis", "ts": iyi["ts"], "kimden": "codex", "kime": "claude", "konu": "",
                      "metin": "YANLIS-ANAHTARLI-METIN", "durum": "gonderildi", "imza_alg": kutu_imza.ALG}
    yanlis_anahtar["imza"] = kutu_imza.imza_hesapla(yanlis_anahtar, kutu_imza.anahtar_oku("danisman"))
    imzasiz = {"id": "uu-imzasiz", "ts": iyi["ts"], "kimden": "codex", "kime": "claude", "konu": "",
               "metin": "IMZASIZ-METIN", "durum": "gonderildi"}
    yol = kutu_dizini / "kayit.jsonl"
    yol.write_text("", encoding="utf-8")

    cmd = [PY, "-X", "utf8", str(KOK / "kutu.py"), "bekle", "--kutu", str(kutu_dizini), "--kime", "claude",
           "--aralik", "0.2", "--imza-zorunlu"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=KOK,
                         env=dict(os.environ, PYTHONUTF8="1", **ortam))
    try:
        time.sleep(1.2)
        with yol.open("a", encoding="utf-8", newline="\n") as f:
            for k in (iyi, bozuk, taklit, yanlis_anahtar, imzasiz):
                f.write(json.dumps(k, ensure_ascii=False) + "\n")
        time.sleep(2.5)
    finally:
        ham_out, _ = ka._agaci_oldur(p)          # yalnız kendi `bekle` sürecimiz kapatılır; çıktısı alınır
    out = (ham_out or b"").decode("utf-8", "replace")

    kabul = "DOGRU-IMZALI-METIN" in out and "[imza: geçerli]" in out
    sizan = [m for m in ("DEGISTIRILMIS-ZEHIRLI-METIN", "YANLIS-ANAHTARLI-METIN", "IMZASIZ-METIN") if m in out]
    reddedilen = [i for i in ("uu-bozuk", "uu-taklit", "uu-yanlis", "uu-imzasiz") if f"[KUTU-RED {i}]" in out]
    ok = kabul and not sizan and len(reddedilen) == 4
    kayit("imza: çalışan `bekle --imza-zorunlu` -- doğru kabul, 4 sahte reddedildi", CALISTI if ok else CALISMADI,
          f"$ kutu.py bekle --kutu <gecici> --kime claude --imza-zorunlu; 5 kayıt eklendi -> kabul edilen: "
          f"{'DOGRU-IMZALI-METIN (imza geçerli)' if kabul else 'YOK'}; reddedilen: {reddedilen}; "
          f"reddedilen metin çıktıya sızdı mı: {sizan or 'hayır'}",
          "" if ok else "bekle çıktısı beklenenden farklı: " + kisalt(out, 400))

    rc, dout = calistir([PY, "-X", "utf8", str(KOK / "kutu.py"), "dogrula", "--kutu", str(kutu_dizini)], 60, env=ortam)
    ozet = [s for s in dout.splitlines() if s.startswith("özet:")]
    ok2 = rc == 1 and ozet and "1 geçerli" in ozet[0] and "1 imzasız" in ozet[0] and "3 geçersiz" in ozet[0]
    kayit("imza: `kutu dogrula` toplu denetim (1 geçerli, 1 imzasız, 3 geçersiz -> çıkış 1)",
          CALISTI if ok2 else CALISMADI,
          f"$ kutu.py dogrula --kutu <gecici> -> çıkış {rc}; {ozet[0] if ozet else kisalt(dout)}",
          "" if ok2 else "dogrula çıktısı beklenenden farklı: " + kisalt(dout, 300))


def adim_agmsg(calisma: Path, kaynak: Path, sonuc_dizini: Path) -> None:
    madde = "PARÇA A: agmsg izole WSL 'kutu' içinde a1<->a2 gönder/al"
    if kaynak is None or not kaynak.is_dir():
        kayit(madde, ATLANDI, "agmsg kaynağı yok (KUTU_AGMSG_KAYNAK ya da --agmsg-kaynak verilmedi)")
        return
    if not KUTU_BETIGI.is_file():
        kayit(madde, KURULU_DEGIL, "WSL kutu betiği yok (KUTU_WSL_BETIGI)", "WSL kutu sarmalayıcısı bu makinede kurulu değil")
        return
    sh = shutil.which("sh") or "C:/Program Files/Git/usr/bin/sh.exe"
    girdi = calisma / "agmsg-girdi"
    shutil.copytree(kaynak, girdi / "agmsg", ignore=shutil.ignore_patterns(".git", "app", "server", "site", "docs"))
    shutil.copy2(KOK / "agmsg-kutu" / "agmsg-e2e.sh", girdi / "agmsg-e2e.sh")
    t0 = time.time()
    rc, out = calistir([sh, str(KUTU_BETIGI).replace("\\", "/"), "calistir", "--ag", "--sure", "600",
                        str(girdi), "--", "bash", "agmsg-e2e.sh"], 700)
    (sonuc_dizini / "agmsg-kutu-log.txt").write_text(out, encoding="utf-8", newline="\n")
    ciktilar = re.findall(r"çıktı klasörü: (\S+)", out)
    beklenen = {
        "yalıtım: /mnt/c yok": "ls: cannot access '/mnt/c'",
        "yalıtım: mnt boş": "mnt girdi sayisi: 0",
        "kurulum çıkış 0": "Installed to",
        "a1->a2 gönderildi": "Sent to a2 in team t1",
        "a2 aldı": "1 new message(s)",
        "okundu işaretlendi": "No new messages.",
        "yanıt a2->a1": "yanit a1, mesaj alindi",
        "kayıtsız alıcı reddedildi": "to agent 'yok' is not registered",
        "kayıtsız gönderen reddedildi": "from agent 'sahte' is not registered",
    }
    eksik = [ad for ad, iz in beklenen.items() if iz not in out]
    taklit = "ben a2 degilim ama a2 diyorum" in out and "Sent to a1 in team t1" in out
    ok = rc == 0 and not eksik
    kayit(madde, CALISTI if ok else CALISMADI,
          f"$ kutu calistir --ag --sure 600 <agmsg-girdi> -- bash agmsg-e2e.sh -> çıkış {rc}, {time.time() - t0:.0f} sn; "
          f"doğrulanan {len(beklenen) - len(eksik)}/{len(beklenen)} iz; log: kanit/agmsg-kutu-log.txt. "
          f"Bulgu: agmsg gönderen kimliğini DOĞRULAMAZ (kayıtlı bir üye başka üye adına gönderebildi: "
          f"{'evet' if taklit else 'sınanamadı'}). Ağ: --ag ile yalnız genel IPv4; /mnt yok.",
          "" if ok else f"eksik izler: {eksik}; çıktı: " + kisalt(out[-600:], 400))
    # kutu kendi çıktı klasörünü bıraktı: yalnız bu koşunun klasörünü sil (kanıt log'a kopyalandı)
    for c in ciktilar:
        p = Path(c)
        if KUTU_CIKTI_KOKU is not None and p.parent == KUTU_CIKTI_KOKU and re.fullmatch(r"\d{8}-\d{6}", p.name) and p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


def adim_temizlik_ve_durum(oncesi: dict) -> None:
    # açık süreçler: kutu bekle / agy / hermes -z / codex exec çocuklarımız
    rc, tl = calistir(["tasklist", "/FO", "CSV", "/NH"], 30)
    kalan = [s for s in tl.splitlines() if re.search(r'"(agy|claude|codex)\.exe"', s, re.I)]
    yeni_surec = len(kalan) - oncesi["surec"]
    kayit("temizlik: bu koşunun açtığı süreç kalmadı (agy/claude/codex; kullanıcıların kendi süreçleri sayılmaz)",
          CALISTI if yeni_surec <= 0 else CALISMADI,
          f"$ tasklist | agy/claude/codex -> koşu başında {oncesi['surec']}, şimdi {len(kalan)} eşleşme; "
          "kendi çocuklarımız Popen.communicate/taskkill /T ile kapatıldı",
          "" if yeni_surec <= 0 else f"{yeni_surec} fazla süreç var (başka oturum da açmış olabilir; PID'leri elle bakın)")
    # agy oturum kalıntısı
    yeni = agy_konusmalari() - oncesi["agy"]
    kayit("temizlik: agy konuşma kalıntısı", CALISTI if not yeni else CALISMADI,
          f"<AGY_KOK>/conversations -> koşu öncesine göre yeni konuşma: {len(yeni)}",
          "" if not yeni else f"adaptör temizleyemedi: {sorted(yeni)[:3]}")
    # hermes oturum kalıntısı
    hermes = ka.arac_bul("hermes")
    if hermes:
        rc, out = calistir([hermes, "sessions", "list", "--workspace", "kutu-oturum-", "--limit", "20"], 60)
        kalan_h = [s for s in out.splitlines() if "kutu-oturum-" in s]
        kayit("temizlik: hermes oturum kalıntısı", CALISTI if not kalan_h else CALISMADI,
              f"$ hermes sessions list --workspace kutu-oturum- -> {len(kalan_h)} satır",
              "" if not kalan_h else "kalan oturum: " + kisalt(kalan_h[0], 150))
    # canlı kutu ve özgün repo
    if CANLI_KUTU is None:
        kayit("canlı kutu dokunulmadı", ATLANDI, "KUTU_KORUNAN_DIZIN verilmedi")
    else:
        bozulan, eklenen = canli_degisim(oncesi["canli"])
        kayit("canlı kutu dokunulmadı (eski içerik sha256 aynı, bu koşunun izi yok)", CALISTI if not bozulan else CALISMADI,
              f"<KORUNAN_KUTU>: {len(oncesi['canli'])} dosya; eski içerik korunmuş: {'evet' if not bozulan else 'HAYIR'}; "
              f"başkalarının eklediği yeni satır: {len(eklenen)} {eklenen[:3] or ''} (betik canlı kutuya yazmaz, yalnız okur)",
              "" if not bozulan else "; ".join(bozulan))
    if OZGUN_REPO is None:
        kayit("özgün repo git status temiz", ATLANDI, "KUTU_OZGUN_REPO verilmedi")
    else:
        gd = git_durum(OZGUN_REPO)
        kayit("özgün repo git status temiz", CALISTI if gd == "" else CALISMADI,
              f"$ git -C <OZGUN_REPO> status --short -> {gd or '(boş)'}", "" if gd == "" else "özgün repoda değişiklik var")


def markdown(baslangic: str) -> str:
    sayim = {d: sum(1 for s in SONUCLAR if s["durum"] == d) for d in (CALISTI, CALISMADI, KURULU_DEGIL, ATLANDI)}
    satir = [f"# Uçtan uca sonuç ({baslangic})", "",
             f"CALISTI: {sayim[CALISTI]} | CALISMADI: {sayim[CALISMADI]} | KURULU DEGIL: {sayim[KURULU_DEGIL]} | ATLANDI: {sayim[ATLANDI]}",
             "", "| Madde | Durum |", "|---|---|"]
    satir += [f"| {s['madde']} | {s['durum']} |" for s in SONUCLAR]
    satir.append("")
    for s in SONUCLAR:
        satir += [f"## {s['madde']} -- {s['durum']}", "", f"- Kanıt: {s['kanit'] or '-'}"]
        if s["kok_neden"]:
            satir.append(f"- Kök neden / not: {s['kok_neden']}")
        if s["cozum"]:
            satir.append(f"- Araştırılan/uygulanan çözüm: {s['cozum']}")
        if s["yeniden_sinama"]:
            satir.append(f"- Yeniden sınama: {s['yeniden_sinama']}")
        satir.append("")
    return "\n".join(satir)


def main() -> int:
    ap = argparse.ArgumentParser(description="kutu uçtan uca sınama")
    ap.add_argument("--hizli", action="store_true", help="agmsg (WSL kutu) adımını atla")
    ap.add_argument("--arac", nargs="*", help="yalnız bu adaptörlere 'merhaba' gönder")
    ap.add_argument("--agmsg-kaynak", default=str(AGMSG_KAYNAK) if AGMSG_KAYNAK else "")
    ap.add_argument("--sonuc-dizini", default=str(KOK / "kanit"))
    a = ap.parse_args()
    sonuc_dizini = Path(a.sonuc_dizini)
    sonuc_dizini.mkdir(parents=True, exist_ok=True)
    baslangic = datetime.now().astimezone().isoformat(timespec="seconds")
    calisma_koku = KOK / ".calisma"
    calisma_koku.mkdir(exist_ok=True)
    calisma = Path(tempfile.mkdtemp(prefix="uu-", dir=calisma_koku))
    rc, tl = calistir(["tasklist", "/FO", "CSV", "/NH"], 30)
    oncesi = {"canli": canli_ozet(), "agy": agy_konusmalari(),
              "surec": len([s for s in tl.splitlines() if re.search(r'"(agy|claude|codex)\.exe"', s, re.I)])}
    try:
        adim_birim()
        araclar = adim_araclar(calisma)
        rc, out = kutu_cmd(calisma, "anahtar-uret", "--hepsi")
        kayit("kimlik: ajan başına anahtar dosyaları (.anahtar/, gitignore'da)", CALISTI if rc == 0 else CALISMADI,
              f"$ kutu.py anahtar-uret --hepsi -> çıkış {rc}; {len(out.splitlines())} satır, değerler basılmadı")
        adim_merhaba(calisma, araclar, a.arac)
        adim_imza(calisma)
        if a.hizli:
            kayit("PARÇA A: agmsg izole WSL 'kutu'", ATLANDI, "--hizli verildi")
        else:
            adim_agmsg(calisma, Path(a.agmsg_kaynak) if a.agmsg_kaynak else None, sonuc_dizini)
        # gönderilen/alınan kutu kaydını kanıt olarak sakla (anahtarsız, yalnız kayit.jsonl)
        kj = calisma / "kutu" / "kayit.jsonl"
        if kj.is_file():
            shutil.copy2(kj, sonuc_dizini / "merhaba-kayit.jsonl")
    finally:
        shutil.rmtree(calisma, ignore_errors=True)       # kendi geçici klasörümüz
        adim_temizlik_ve_durum(oncesi)
    (sonuc_dizini / "uctan-uca-sonuc.md").write_text(markdown(baslangic), encoding="utf-8", newline="\n")
    (sonuc_dizini / "uctan-uca-sonuc.json").write_text(json.dumps(SONUCLAR, ensure_ascii=False, indent=2),
                                                       encoding="utf-8", newline="\n")
    kotu = [s for s in SONUCLAR if s["durum"] == CALISMADI and not s["madde"].endswith("hermes-http")]
    print(f"\nsonuç: {sonuc_dizini / 'uctan-uca-sonuc.md'}")
    return 1 if kotu else 0


if __name__ == "__main__":
    sys.exit(main())
