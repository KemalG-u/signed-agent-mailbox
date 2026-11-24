"""kutu gecis-kontrol: eski kutudan yeni (imza-zorunlu) kutuya geçişten önce SALT-OKUNUR durum raporu.

Hiçbir şey yazmaz, silmez, kapatmaz, oluşturmaz: dosyalar yalnız okunur, süreçler yalnız listelenir.
Rapor: eski kutunun dosya özetleri (boyut, sha256, kayıt sayısı), yeni kutunun durumu (ayar, anahtar adları,
imza doğrulama özeti), çalışan ``kutu bekle`` süreçleri ve kayıtlı Claude adları. Token ve anahtar DEĞERİ asla yazılmaz.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import kutu_imza

DOSYALAR = ("kayit.jsonl", "konusma.md", "ayar.json")
_BEKLE_DESENI = re.compile(r"""(?:^|[\s"'\\/])kutu(?:\.py|\.cmd)?["']?\s+bekle(?:\s|$)""")
_KUTU_ARG = re.compile(r"""--kutu(?:=|\s+)("[^"]+"|'[^']+'|\S+)""")
_KIME_ARG = re.compile(r"""--kime(?:=|\s+)(\S+)""")


def _sha256(yol: Path) -> str:
    h = hashlib.sha256()
    with yol.open("rb") as f:
        for parca in iter(lambda: f.read(65536), b""):
            h.update(parca)
    return h.hexdigest()


def _satirlar(yol: Path) -> list[dict]:
    """kayit.jsonl'u okur (yazmaz); bozuk satırı atlar."""
    sonuc: list[dict] = []
    if not yol.is_file():
        return sonuc
    with yol.open(encoding="utf-8") as f:
        for satir in f:
            try:
                k = json.loads(satir)
            except ValueError:
                continue
            if isinstance(k, dict):
                sonuc.append(k)
    return sonuc


def _ayar(kutu: Path) -> dict:
    yol = kutu / "ayar.json"
    try:
        veri = json.loads(yol.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return veri if isinstance(veri, dict) else {}


def kutu_ozeti(kutu: Path) -> dict:
    """Bir kutunun salt-okunur özeti (değer yok: yalnız var/yok, sayı, sha256)."""
    ozet: dict = {"var": kutu.is_dir(), "dosyalar": {}, "kayit": {}, "ayar": {}}
    if not ozet["var"]:
        return ozet
    for ad in DOSYALAR:
        yol = kutu / ad
        ozet["dosyalar"][ad] = ({"boyut": yol.stat().st_size, "sha256": _sha256(yol)} if yol.is_file() else None)
    kayitlar = _satirlar(kutu / "kayit.jsonl")
    ozet["kayit"] = {
        "toplam": len(kayitlar),
        "imzali": sum(1 for k in kayitlar if k.get("imza")),
        "imzasiz": sum(1 for k in kayitlar if not k.get("imza")),
        "son_ts": str(kayitlar[-1].get("ts", "")) if kayitlar else "",
    }
    a = _ayar(kutu)
    ozet["ayar"] = {"codex_thread_var": bool(a.get("codex_thread")), "codex_home_var": bool(a.get("codex_home")),
                    "imza_zorunlu": bool(a.get("imza_zorunlu"))}
    ozet["_codex_thread"] = str(a.get("codex_thread") or "")
    return ozet


def imza_ozeti(kutu: Path, anahtar_dizin: Path | None) -> dict:
    """Kayıtların imza durumu (kutu_imza.dogrula ile); anahtar dizini yoksa doğrulama yapılamaz."""
    sayim = {kutu_imza.GECERLI: 0, kutu_imza.IMZASIZ: 0, kutu_imza.ANAHTAR_YOK: 0, kutu_imza.GECERSIZ: 0}
    for k in _satirlar(kutu / "kayit.jsonl"):
        durum, _ = kutu_imza.dogrula(k, anahtar_dizin)
        sayim[durum] = sayim.get(durum, 0) + 1
    return sayim


def anahtar_adlari(anahtar_dizin: Path | None) -> list[str] | None:
    """Anahtar dosyalarının ADLARI (içerik okunmaz); dizin yoksa None."""
    if anahtar_dizin is None or not anahtar_dizin.is_dir():
        return None
    return sorted(p.stem for p in anahtar_dizin.glob("*.key"))


def claude_adlari(kayit_klasoru: Path) -> list[dict]:
    """Kayıtlı Claude adları ve kayıt zamanı; token/socket okunmaz-yazılmaz."""
    sonuc = []
    for yol in sorted(kayit_klasoru.glob("claude-*.json")):
        ad, ts = yol.stem[len("claude-"):], "?"
        try:
            veri = json.loads(yol.read_text(encoding="utf-8"))
            ad, ts = str(veri.get("ad") or ad), str(veri.get("kayit_ts") or "?")
        except (OSError, ValueError):
            ts = "okunamadı"
        sonuc.append({"ad": ad, "kayit_ts": ts})
    return sonuc


def surec_listesi() -> list[tuple[int, str]]:
    """(pid, komut satırı) listesi; yalnız okur. Alınamazsa RuntimeError."""
    try:
        if os.name == "nt":
            komut = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                     "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'bekle' } | "
                     "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"]
            cikti = subprocess.run(komut, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   timeout=30).stdout.strip()
            if not cikti:
                return []
            veri = json.loads(cikti)
            veri = veri if isinstance(veri, list) else [veri]
            return [(int(v["ProcessId"]), str(v.get("CommandLine") or "")) for v in veri]
        cikti = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True, errors="replace",
                               timeout=30).stdout
        sonuc = []
        for satir in cikti.splitlines():
            parca = satir.strip().split(None, 1)
            if len(parca) == 2 and parca[0].isdigit():
                sonuc.append((int(parca[0]), parca[1]))
        return sonuc
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as hata:
        raise RuntimeError(f"süreç listesi alınamadı: {type(hata).__name__}") from hata


def _norm(yol: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(yol.strip().strip("\"'"))).replace("\\", "/").rstrip("/")
    except (OSError, ValueError):
        return yol


def bekle_surecleri(eski: Path, yeni: Path, liste=None) -> dict:
    """Çalışan `kutu bekle` süreçleri; her biri eski/yeni/belirtilmemiş/başka kutuya ayrılır. Kendi pid hariç."""
    liste = surec_listesi() if liste is None else liste
    eski_n, yeni_n = _norm(str(eski)), _norm(str(yeni))
    sonuc = {"eski": [], "yeni": [], "belirsiz": [], "diger": []}
    for pid, komut in liste:
        if pid == os.getpid() or not _BEKLE_DESENI.search(komut):
            continue
        m = _KUTU_ARG.search(komut)
        k = _KIME_ARG.search(komut)
        girdi = {"pid": pid, "kime": k.group(1) if k else "claude", "imza_zorunlu": "--imza-zorunlu" in komut}
        if not m:
            sonuc["belirsiz"].append(girdi)       # --kutu yok: KUTU_DIZIN ya da geçerli dizin; buradan bilinemez
            continue
        hedef = _norm(m.group(1))
        sonuc["eski" if hedef == eski_n else "yeni" if hedef == yeni_n else "diger"].append(girdi)
    return sonuc


def rapor_uret(eski: Path, yeni: Path, anahtar_dizin: Path | None, beklenen: dict[str, str],
               kayit_klasoru: Path, surecler: dict | None = None) -> dict:
    """Tüm rapor (sözlük) + `sorunlar` (geçişi engeller) ve `uyarilar` (bilgi). Salt-okunur."""
    sorunlar: list[str] = []
    uyarilar: list[str] = []
    o_eski, o_yeni = kutu_ozeti(eski), kutu_ozeti(yeni)
    if not o_eski["var"]:
        sorunlar.append("eski kutu klasörü yok")
    if not o_yeni["var"]:
        sorunlar.append("yeni kutu klasörü yok")
    kontrol = {}
    for ad, onek in beklenen.items():
        d = o_eski["dosyalar"].get(ad)
        gercek = d["sha256"] if d else ""
        uyumlu = bool(gercek) and gercek.startswith(onek.lower())
        kontrol[ad] = {"beklenen_onek": onek, "uyumlu": uyumlu}
        if not uyumlu:
            sorunlar.append(f"eski kutu {ad} sha256 beklenenle uyuşmuyor ({onek}...)" if gercek
                            else f"eski kutu {ad} yok; beklenen sha256 doğrulanamadı")
    if o_yeni["var"]:
        if not o_yeni["ayar"].get("imza_zorunlu"):
            uyarilar.append("yeni kutu ayar.json imza_zorunlu açık değil (öneri: kutu kur --imza-zorunlu)")
        if not o_yeni["ayar"].get("codex_thread_var"):
            uyarilar.append("yeni kutuda codex_thread yok (kutu kur --codex-thread)")
    anahtarlar = anahtar_adlari(anahtar_dizin)
    if anahtar_dizin is None:
        uyarilar.append("anahtar dizini verilmedi (--anahtar-dizin ya da KUTU_ANAHTAR_DIZIN): imzalar doğrulanamadı")
    elif anahtarlar is None:
        sorunlar.append("anahtar dizini yok")
    yeni_imza = imza_ozeti(yeni, anahtar_dizin) if o_yeni["var"] and anahtarlar is not None else {}
    if yeni_imza.get(kutu_imza.GECERSIZ):
        sorunlar.append(f"yeni kutuda {yeni_imza[kutu_imza.GECERSIZ]} geçersiz imzalı kayıt var")
    if yeni_imza.get(kutu_imza.ANAHTAR_YOK):
        uyarilar.append(f"yeni kutuda {yeni_imza[kutu_imza.ANAHTAR_YOK]} kaydın göndericisi için anahtar yok")
    if o_eski["var"] and o_eski["kayit"].get("imzasiz"):
        uyarilar.append(f"eski kutunun {o_eski['kayit']['imzasiz']} kaydı imzasız: imza-zorunlu kutuya kopyalanırsa "
                        "kutu dogrula hata verir (geçmişi arşiv olarak eski kutuda bırakmak daha temiz)")
    ayni_thread = bool(o_eski.get("_codex_thread")) and o_eski.get("_codex_thread") == o_yeni.get("_codex_thread")
    try:
        sur = bekle_surecleri(eski, yeni) if surecler is None else surecler
        sur_hata = ""
    except RuntimeError as hata:
        sur, sur_hata = {"eski": [], "yeni": [], "belirsiz": [], "diger": []}, str(hata)
        uyarilar.append(sur_hata)
    if sur["eski"]:
        uyarilar.append(f"eski kutuyu izleyen {len(sur['eski'])} `kutu bekle` süreci çalışıyor (geçişte yenisine taşınmalı)")
    if sur["belirsiz"]:
        uyarilar.append(f"{len(sur['belirsiz'])} `kutu bekle` sürecinin --kutu değeri yok (KUTU_DIZIN/geçerli dizin; elle kontrol)")
    claude = claude_adlari(kayit_klasoru)
    if len(claude) > 1:
        uyarilar.append(f"{len(claude)} Claude kaydı var: gönderimde --claude-ad açıkça verilmeli")
    for o in (o_eski, o_yeni):
        o.pop("_codex_thread", None)
    return {"eski": o_eski, "yeni": o_yeni, "beklenen_hash": kontrol, "ayni_codex_thread": ayni_thread,
            "anahtar_adlari": anahtarlar, "yeni_imza": yeni_imza, "bekle_surecleri": sur,
            "claude_adlari": claude, "sorunlar": sorunlar, "uyarilar": uyarilar}


def metin_rapor(r: dict) -> list[str]:
    s: list[str] = []
    for baslik, o in (("ESKİ kutu", r["eski"]), ("YENİ kutu", r["yeni"])):
        s.append(f"== {baslik}: {'var' if o['var'] else 'YOK'}")
        for ad, d in o["dosyalar"].items():
            s.append(f"  {ad:<12} " + (f"{d['boyut']:>8} bayt  sha256 {d['sha256']}" if d else "(yok)"))
        if o["var"]:
            k, a = o["kayit"], o["ayar"]
            s.append(f"  kayıt: {k['toplam']} (imzalı {k['imzali']}, imzasız {k['imzasiz']}); son: {k['son_ts'] or '-'}")
            s.append(f"  ayar : codex_thread {'var' if a['codex_thread_var'] else 'yok'}, codex_home "
                     f"{'var' if a['codex_home_var'] else 'yok'}, imza_zorunlu {'EVET' if a['imza_zorunlu'] else 'hayır'}")
    s.append(f"== codex_thread eski ve yeni kutuda aynı mı: {'evet' if r['ayni_codex_thread'] else 'hayır/bilinmiyor'}")
    for ad, k in r["beklenen_hash"].items():
        s.append(f"== beklenen sha256 {ad}: {k['beklenen_onek']}... -> {'AYNI' if k['uyumlu'] else 'FARKLI'}")
    an = r["anahtar_adlari"]
    s.append("== anahtar adları (değer basılmaz): " + (", ".join(an) if an else "(yok)" if an is not None else "(dizin yok/verilmedi)"))
    if r["yeni_imza"]:
        y = r["yeni_imza"]
        s.append(f"== yeni kutu imza özeti: geçerli {y.get(kutu_imza.GECERLI, 0)}, imzasız {y.get(kutu_imza.IMZASIZ, 0)}, "
                 f"anahtar-yok {y.get(kutu_imza.ANAHTAR_YOK, 0)}, geçersiz {y.get(kutu_imza.GECERSIZ, 0)}")
    sur = r["bekle_surecleri"]
    s.append(f"== çalışan `kutu bekle`: eski kutuda {len(sur['eski'])}, yeni kutuda {len(sur['yeni'])}, "
             f"--kutu belirsiz {len(sur['belirsiz'])}, başka kutuda {len(sur['diger'])}")
    for grup in ("eski", "yeni", "belirsiz", "diger"):
        for p in sur[grup]:
            s.append(f"  pid {p['pid']}  [{grup}] --kime {p['kime']}" + ("  --imza-zorunlu" if p["imza_zorunlu"] else ""))
    c = r["claude_adlari"]
    s.append("== kayıtlı Claude adları (token yok): " + (", ".join(f"{x['ad']} ({x['kayit_ts']})" for x in c) if c else "(yok)"))
    for u in r["uyarilar"]:
        s.append(f"UYARI: {u}")
    for p in r["sorunlar"]:
        s.append(f"SORUN: {p}")
    s.append("sonuç: " + ("geçişe engel SORUN var" if r["sorunlar"] else "engel yok (UYARI satırlarını okuyun)")
             + "; bu komut hiçbir şeyi değiştirmedi")
    return s
