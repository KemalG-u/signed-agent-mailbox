"""kutu adaptörleri: bir mesajı bir ajan aracına GEÇİCİ yeni oturumla teslim eder, yanıtı alır.

Yalnız standart kütüphane. Her adaptör ``gonder(mesaj) -> Sonuc`` verir; araç kurulu değilse
``Sonuc(False, "kurulu değil ...")`` döner, hiçbir şey kurulmaz. Kullanıcının açık
oturumlarına yazılmaz: her teslim kendi oturumunu açar ve iş bitince kapatır/temizler.

Mesajın nasıl sarıldığı (veri, talimat değil) kutu.py'de yapılır; burası yalnız taşır.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ZAMAN_ASIMI = 180
HERMES_VARSAYILAN_URL = "http://127.0.0.1:8642"
HERMES_BITIS = ("completed", "failed", "cancelled", "stopped")


@dataclass
class Sonuc:
    tamam: bool
    ayrinti: str
    yanit: str = ""


# ------------------------------------------------------------- bulma ----

def _yerel() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))


# Araç adı -> (PATH'te aranacak adlar, bilinen kurulum yolları).
ARAC_ADAYLARI: dict[str, tuple[tuple[str, ...], Callable[[], list[Path]]]] = {
    "claude": (("claude",), lambda: []),
    "codex": (("codex",), lambda: []),
    "agy": (("agy",), lambda: [_yerel() / "agy" / "bin" / "agy.exe"]),
    "hermes": (("hermes",), lambda: [Path.home() / ".local" / "bin" / "hermes.exe"]),
    "opencode": (("opencode",), lambda: [Path.home() / ".opencode" / "bin" / "opencode.exe",
                                         Path.home() / ".local" / "bin" / "opencode.exe"]),
    "gemini": (("gemini",), lambda: []),
    "copilot": (("copilot",), lambda: []),
    "cursor-agent": (("cursor-agent",), lambda: [_yerel() / "cursor-agent" / "cursor-agent.exe"]),
}


def _kayit_adaylari(ad: str) -> list[Path]:
    """İsteğe bağlı ``~/.agents/arac-yollari.json`` (bu makinedeki tek kaynak araç kaydı)."""
    yol = Path.home() / ".agents" / "arac-yollari.json"
    try:
        veri = json.loads(yol.read_text(encoding="utf-8-sig"))
        return [Path(a) for a in veri.get("araclar", {}).get(ad, {}).get("adaylar", []) if "*" not in a]
    except (OSError, ValueError, AttributeError):
        return []


def shim_coz(yol: str) -> str:
    """npm ``.cmd`` sarmalayıcısını gösterdiği gerçek ``.exe``'ye çevirir (cmd.exe argümanı bozar)."""
    if not yol.lower().endswith((".cmd", ".bat")):
        return yol
    try:
        metin = Path(yol).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return yol
    m = re.search(r'"%dp0%\\([^"]+?\.exe)"', metin, re.IGNORECASE)
    if m:
        aday = Path(yol).parent / m.group(1).replace("\\", os.sep)
        if aday.is_file():
            return str(aday)
    return yol


def arac_bul(ad: str) -> str | None:
    """Öncelik: KUTU_ARAC_<AD> ortam değişkeni, PATH, bilinen yollar, arac-yollari.json."""
    env = os.environ.get("KUTU_ARAC_" + ad.upper().replace("-", "_"))
    if env and Path(env).is_file():
        return shim_coz(env)
    pathler, ek = ARAC_ADAYLARI.get(ad, ((ad,), lambda: []))
    for p in pathler:
        bulunan = shutil.which(p)
        if bulunan:
            return shim_coz(bulunan)
    for aday in [*ek(), *_kayit_adaylari(ad)]:
        if aday.is_file():
            return shim_coz(str(aday))
    return None


def surum(yol: str, bayrak: str = "--version", zaman_asimi: int = 30) -> str:
    try:
        s = subprocess.run([yol, bayrak], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=zaman_asimi, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as hata:
        return f"(çalıştırılamadı: {type(hata).__name__})"
    satirlar = (s.stdout.strip() or s.stderr.strip()).splitlines()
    return satirlar[0] if satirlar else f"(çıkış {s.returncode})"


# ----------------------------------------------------------- çalıştırma ----

def calisma_dizini() -> Path:
    """Geçici oturumların çalışma kökü: KUTU_CALISMA_DIZIN ya da sistem geçicisi."""
    env = os.environ.get("KUTU_CALISMA_DIZIN")
    kok = Path(env) if env else Path(tempfile.gettempdir())
    kok.mkdir(parents=True, exist_ok=True)
    return kok


def _calis(komut: list[str], girdi: str | None, zaman_asimi: int,
           env: dict | None = None, ad_ver: list | None = None) -> tuple[int, str, str, str]:
    """(çıkış, stdout, stderr, hata). Geçici cwd'de çalışır, sonunda siler. Zaman aşımında süreç ağacı öldürülür.

    ``ad_ver`` verilirse geçici klasörün adı ona eklenir (aracın oturumunu bulup temizlemek için).
    """
    gecici = Path(tempfile.mkdtemp(prefix="kutu-oturum-", dir=calisma_dizini()))
    if ad_ver is not None:
        ad_ver.append(gecici.name)
    try:
        proc = subprocess.Popen(
            komut, cwd=gecici, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        try:
            out, err = proc.communicate(girdi.encode("utf-8") if girdi is not None else None,
                                        timeout=zaman_asimi)
        except subprocess.TimeoutExpired:
            _agaci_oldur(proc)
            return 124, "", "", f"{zaman_asimi} sn içinde dönmedi (süreç kapatıldı)"
        return (proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), "")
    except OSError as hata:
        return 127, "", "", f"başlatılamadı: {type(hata).__name__}: {hata}"
    finally:
        shutil.rmtree(gecici, ignore_errors=True)


def hermes_oturum_temizle(yol: str, calisma_adi: str, zaman_asimi: int = 60) -> int:
    """``hermes -z`` oturumu çalışma klasörü adıyla (benzersiz ``kutu-oturum-*``) bulup siler; silinen sayısı."""
    if not re.fullmatch(r"kutu-oturum-[A-Za-z0-9_]+", calisma_adi or ""):
        return 0
    try:
        liste = subprocess.run([yol, "sessions", "list", "--workspace", calisma_adi, "--limit", "5"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=zaman_asimi, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    silinen = 0
    for satir in liste.stdout.splitlines():
        # Çalışma alanı sütunu 16 karaktere kısaltılır (kutu-oturum-7pwr); süzgeç (--workspace) zaten tam adla çalışır.
        if calisma_adi[:16] not in satir:
            continue
        m = re.search(r"\b(local-[0-9a-f]{16,})\s*$", satir.strip())
        if not m:
            continue
        try:
            s = subprocess.run([yol, "sessions", "delete", "--yes", m.group(1)], capture_output=True,
                               timeout=zaman_asimi, stdin=subprocess.DEVNULL)
            silinen += 1 if s.returncode == 0 else 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    return silinen


def _agaci_oldur(proc: subprocess.Popen) -> tuple:
    """Yalnız kendi açtığımız süreci (ve çocuklarını) kapatır; (stdout, stderr) baytlarını döndürür."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=20)
        else:
            proc.kill()
        return proc.communicate(timeout=10)
    except Exception:  # noqa: BLE001 - temizlik en iyi çaba
        return (b"", b"")


def _son_satir(metin: str) -> str:
    satirlar = [s for s in metin.strip().splitlines() if s.strip()]
    return satirlar[-1] if satirlar else ""


def _hata_ozeti(rc: int, err: str, out: str) -> str:
    ayrinti = _son_satir(err) or _son_satir(out)
    return f"çıkış kodu {rc}" + (f": {ayrinti[:300]}" if ayrinti else "")


# ----------------------------------------------------------- adaptörler ----

def kurulu_degil(arac: str) -> Sonuc:
    return Sonuc(False, f"kurulu değil: {arac} (PATH, bilinen yollar ve arac-yollari.json'da yok)")


def gonder_claude_p(mesaj: str, zaman_asimi: int = ZAMAN_ASIMI) -> Sonuc:
    """``claude -p``: oturumsuz (kaydedilmez), araçsız, kullanıcı ayarı/kancası okunmaz; istem stdin'den."""
    yol = arac_bul("claude")
    if not yol:
        return kurulu_degil("claude")
    komut = [yol, "-p", "--no-session-persistence", "--model", os.environ.get("KUTU_CLAUDE_MODEL", "haiku"),
             "--tools", "", "--setting-sources", "project", "--disable-slash-commands"]
    rc, out, err, hata = _calis(komut, mesaj, zaman_asimi)
    if hata:
        return Sonuc(False, f"claude: {hata}")
    if rc != 0:
        return Sonuc(False, "claude: " + _hata_ozeti(rc, err, out))
    return Sonuc(True, "claude -p yanıt verdi (oturum kaydedilmedi)", out.strip())


def gonder_codex_exec(mesaj: str, zaman_asimi: int = ZAMAN_ASIMI) -> Sonuc:
    """``codex exec --ephemeral``: oturum diske yazılmaz, salt-okunur sandbox; son mesaj dosyadan alınır."""
    yol = arac_bul("codex")
    if not yol:
        return kurulu_degil("codex")
    onek = [yol]
    if yol.lower().endswith((".cmd", ".bat")):  # codex.js'i doğrudan node ile çalıştır (cmd argümanı bozar)
        klasor = Path(yol).parent
        js = klasor / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        node = klasor / "node.exe"
        node_yolu = str(node) if node.is_file() else shutil.which("node")
        if not (js.is_file() and node_yolu):
            return Sonuc(False, "codex: codex.js/node bulunamadı")
        onek = [node_yolu, str(js)]
    cikti = Path(tempfile.mkdtemp(prefix="kutu-codex-", dir=calisma_dizini()))
    try:
        son = cikti / "son-mesaj.txt"
        komut = [*onek, "exec", "--ephemeral", "--skip-git-repo-check", "-s", "read-only",
                 "-o", str(son), "-"]
        rc, out, err, hata = _calis(komut, mesaj, zaman_asimi)
        if hata:
            return Sonuc(False, f"codex: {hata}")
        if rc != 0:
            return Sonuc(False, "codex: " + _hata_ozeti(rc, err, out))
        yanit = son.read_text(encoding="utf-8", errors="replace").strip() if son.is_file() else ""
        return Sonuc(True, "codex exec --ephemeral yanıt verdi (oturum kaydedilmedi)", yanit or _son_satir(out))
    finally:
        shutil.rmtree(cikti, ignore_errors=True)


def agy_oturum_temizle(conversation_id: str, kok: Path | None = None) -> list[str]:
    """Yalnız verilen (kendi açtığımız) agy konuşmasının kalıntılarını siler; silinen yolları döndürür."""
    if not re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", conversation_id or ""):
        return []
    kok = kok or (Path.home() / ".gemini" / "antigravity-cli")
    silinen: list[str] = []
    for alt in ("conversations", "annotations", "presence", "brain"):
        klasor = kok / alt
        if not klasor.is_dir():
            continue
        for oge in klasor.glob(conversation_id + "*"):
            try:
                if oge.is_dir():
                    shutil.rmtree(oge)
                else:
                    oge.unlink()
                silinen.append(str(oge))
            except OSError:
                pass
    return silinen


def agy_akis_ayikla(stdout: str) -> tuple[str, str, str]:
    """stream-json çıktısından (durum, yanıt, conversation_id) çıkarır."""
    durum, yanit, konusma = "", "", ""
    for satir in stdout.splitlines():
        try:
            olay = json.loads(satir)
        except ValueError:
            continue
        if not isinstance(olay, dict):
            continue
        if olay.get("event") == "init":
            konusma = str((olay.get("init") or {}).get("conversation_id", konusma))
        elif olay.get("event") == "result":
            sonuc = olay.get("result") or {}
            durum = str(sonuc.get("status", ""))
            yanit = str(sonuc.get("response", ""))
            konusma = str(sonuc.get("conversation_id", konusma))
            if sonuc.get("error"):
                yanit = yanit or str(sonuc["error"])
    return durum, yanit.strip(), konusma


def gonder_agy(mesaj: str, zaman_asimi: int = ZAMAN_ASIMI, temizle: bool = True) -> Sonuc:
    """``agy -p= --input-format stream-json --output-format stream-json`` (plan kipi: araç eylemi yok).

    Girdi satırı ölçülen biçim: {"event":"user","message":{"content":...}}. ``-p`` değeri
    ``-p=`` biçiminde bitişik verilmelidir, yoksa sonraki bayrağı istem sanar.
    """
    yol = arac_bul("agy")
    if not yol:
        return kurulu_degil("agy")
    komut = [yol, "--input-format", "stream-json", "--output-format", "stream-json", "--mode", "plan",
             "--print-timeout", f"{max(int(zaman_asimi) - 10, 10)}s", "-p="]
    girdi = json.dumps({"event": "user", "message": {"content": mesaj}}, ensure_ascii=False) + "\n"
    rc, out, err, hata = _calis(komut, girdi, zaman_asimi)
    durum, yanit, konusma = agy_akis_ayikla(out)
    temizlenen = agy_oturum_temizle(konusma) if temizle else []
    if hata:
        return Sonuc(False, f"agy: {hata}")
    if rc != 0 or durum != "SUCCESS":
        return Sonuc(False, f"agy: durum={durum or '?'} " + _hata_ozeti(rc, err, yanit or out))
    ek = f", {len(temizlenen)} oturum kalıntısı temizlendi" if temizle else ""
    return Sonuc(True, f"agy stream-json yanıt verdi (konuşma {konusma[:8]}{ek})", yanit)


def gonder_hermes_z(mesaj: str, zaman_asimi: int = ZAMAN_ASIMI, temizle: bool = True) -> Sonuc:
    """``hermes -z``: tek atımlık mod, yalnız son yanıt metni stdout'a yazılır (yeni oturum)."""
    yol = arac_bul("hermes")
    if not yol:
        return kurulu_degil("hermes")
    adlar: list[str] = []
    rc, out, err, hata = _calis([yol, "-z", mesaj, "--ignore-rules"], None, zaman_asimi, ad_ver=adlar)
    silinen = hermes_oturum_temizle(yol, adlar[0]) if (temizle and adlar) else 0
    if hata:
        return Sonuc(False, f"hermes: {hata}")
    if rc != 0:
        return Sonuc(False, "hermes: " + _hata_ozeti(rc, err, out))
    ek = f" ({silinen} oturum silindi)" if temizle else ""
    return Sonuc(True, "hermes -z yanıt verdi" + ek, out.strip())


def _http(yontem: str, url: str, anahtar: str, govde: dict | None, zaman_asimi: int):
    veri = json.dumps(govde).encode("utf-8") if govde is not None else None
    istek = urllib.request.Request(url, data=veri, method=yontem, headers={
        "Authorization": f"Bearer {anahtar}", "Content-Type": "application/json"})
    with urllib.request.urlopen(istek, timeout=zaman_asimi) as yanit:
        return yanit.status, json.loads(yanit.read().decode("utf-8", "replace") or "{}")


def gonder_hermes_http(mesaj: str, zaman_asimi: int = ZAMAN_ASIMI, url: str | None = None,
                       anahtar: str | None = None, aralik: float = 1.0) -> Sonuc:
    """Hermes API sunucusu: POST /v1/runs {input, session_id} -> GET /v1/runs/{id} (bitene dek yoklar).

    Yalnız API sunucusu AÇIKSA çalışır (API_SERVER_ENABLED + API_SERVER_KEY, varsayılan 127.0.0.1:8642).
    Adres ``KUTU_HERMES_URL``, anahtar ``KUTU_HERMES_ANAHTAR`` ortam değişkeninden gelir.
    """
    url = (url or os.environ.get("KUTU_HERMES_URL") or HERMES_VARSAYILAN_URL).rstrip("/")
    anahtar = anahtar or os.environ.get("KUTU_HERMES_ANAHTAR") or ""
    if not anahtar:
        return Sonuc(False, "hermes-http: KUTU_HERMES_ANAHTAR (API_SERVER_KEY) tanımlı değil")
    oturum = "kutu-" + uuid.uuid4().hex[:12]
    bitis = time.monotonic() + zaman_asimi
    try:
        kod, govde = _http("POST", url + "/v1/runs", anahtar, {"input": mesaj, "session_id": oturum}, 30)
        run_id = govde.get("run_id")
        if kod not in (200, 201, 202) or not run_id:
            return Sonuc(False, f"hermes-http: beklenmeyen yanıt {kod}")
        durum: dict = {}
        while time.monotonic() < bitis:
            _, durum = _http("GET", f"{url}/v1/runs/{run_id}", anahtar, None, 30)
            if durum.get("status") in HERMES_BITIS:
                break
            time.sleep(aralik)
        else:
            return Sonuc(False, f"hermes-http: {zaman_asimi} sn içinde bitmedi (run {run_id[:12]})")
    except urllib.error.HTTPError as hata:
        return Sonuc(False, f"hermes-http: HTTP {hata.code} ({'anahtar reddedildi' if hata.code in (401, 403) else hata.reason})")
    except (urllib.error.URLError, OSError, ValueError) as hata:
        neden = getattr(hata, "reason", hata)
        return Sonuc(False, f"hermes-http: sunucuya ulaşılamadı ({type(neden).__name__}); API sunucusu kapalı olabilir")
    if durum.get("status") != "completed":
        return Sonuc(False, f"hermes-http: run {durum.get('status')}: {str(durum.get('error', ''))[:200]}")
    cikti = durum.get("output", "")
    return Sonuc(True, f"hermes /v1/runs tamamlandı (run {run_id[:12]})",
                 cikti if isinstance(cikti, str) else json.dumps(cikti, ensure_ascii=False))


def _genel_cli(arac: str, komut_sablon: Callable[[str, str], tuple[list[str], str | None]]):
    """Belgeli tek-atımlık komutu olan, bu makinede kurulu OLMAYAN araçlar için ince sarmalayıcı."""
    def gonder(mesaj: str, zaman_asimi: int = ZAMAN_ASIMI) -> Sonuc:
        yol = arac_bul(arac)
        if not yol:
            return kurulu_degil(arac)
        komut, girdi = komut_sablon(yol, mesaj)
        rc, out, err, hata = _calis(komut, girdi, zaman_asimi)
        if hata:
            return Sonuc(False, f"{arac}: {hata}")
        if rc != 0:
            return Sonuc(False, f"{arac}: " + _hata_ozeti(rc, err, out))
        return Sonuc(True, f"{arac} yanıt verdi (DENENMEDİ: bu makinede kurulu değildi)", out.strip())
    return gonder


gonder_opencode = _genel_cli("opencode", lambda y, m: ([y, "run", m], None))             # opencode run "<istem>"
gonder_gemini = _genel_cli("gemini", lambda y, m: ([y, "-p", m], None))                  # gemini -p "<istem>"
gonder_copilot = _genel_cli("copilot", lambda y, m: ([y, "-p", m], None))                # copilot -p "<istem>"
gonder_cursor = _genel_cli("cursor-agent", lambda y, m: ([y, "-p", m], None))            # cursor-agent -p "<istem>"


@dataclass
class Adaptor:
    ad: str
    arac: str                       # arac_bul adı
    gonder: Callable[..., Sonuc]
    belge: str                      # belgeli yol (tek satır)
    surum_bayragi: str = "--version"


ADAPTOR_ONEKI = ("Bu mesaj bir ajan kutusundan geliyor. Araç çalıştırma, dosya okuma ya da yazma yapma; "
                 "yalnızca metinle yanıt ver. Yanıtının ilk satırında, mesaj başlığındaki kutu kimliğini "
                 "([KUTU ...] içindeki kimlik) aynen yaz, sonra kısa yanıtını ver.\n\n")


def oneki() -> str:
    """Güvenilir (bizim) ön söz; KUTU_ADAPTOR_ONEK ortam değişkeniyle değiştirilir ya da '' ile kapatılır.

    Başsız araçlar izin sorulamadığı için araç çağırınca yanıtsız kalır (agy: 'denied_actions', boş response);
    ön söz bunu önler. Mesajın kendisi (güvenilmeyen girdi) ön sözden SONRA gelir.
    """
    env = os.environ.get("KUTU_ADAPTOR_ONEK")
    return ADAPTOR_ONEKI if env is None else env


def _onekli(f: Callable[..., Sonuc]) -> Callable[..., Sonuc]:
    def gonder(mesaj: str, *a, **k) -> Sonuc:
        return f(oneki() + mesaj, *a, **k)
    gonder.__name__ = getattr(f, "__name__", "gonder")
    return gonder


_HAM = tuple((

    Adaptor("claude-p", "claude", gonder_claude_p, "claude -p --no-session-persistence (istem stdin)"),
    Adaptor("codex-exec", "codex", gonder_codex_exec, "codex exec --ephemeral -s read-only -o <dosya> -"),
    Adaptor("agy", "agy", gonder_agy, "agy -p= --input-format stream-json --output-format stream-json"),
    Adaptor("hermes", "hermes", gonder_hermes_z, "hermes -z <istem>"),
    Adaptor("hermes-http", "hermes", gonder_hermes_http, "POST /v1/runs + GET /v1/runs/{id}"),
    Adaptor("opencode", "opencode", gonder_opencode, "opencode run <istem>  (belgeli; denenmedi)"),
    Adaptor("gemini", "gemini", gonder_gemini, "gemini -p <istem>  (belgeli; denenmedi)"),
    Adaptor("copilot", "copilot", gonder_copilot, "copilot -p <istem>  (belgeli; denenmedi)"),
    Adaptor("cursor", "cursor-agent", gonder_cursor, "cursor-agent -p <istem>  (belgeli; denenmedi)"),
))
ADAPTORLER: dict[str, Adaptor] = {a.ad: Adaptor(a.ad, a.arac, _onekli(a.gonder), a.belge, a.surum_bayragi) for a in _HAM}


def adaptor_adlari() -> tuple[str, ...]:
    return tuple(ADAPTORLER)


def kurulu_mu(ad: str) -> str | None:
    """Adaptörün aracının yolunu döndürür (kurulu değilse None). hermes-http için araç değil sunucu gerekir."""
    return arac_bul(ADAPTORLER[ad].arac)
