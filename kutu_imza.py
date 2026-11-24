"""kutu kimlik doğrulaması: ajan başına gizli anahtar + HMAC-SHA256 imza.

Yalnız standart kütüphane. ``kimden`` etiketi tek başına taklit edilebilir; bu modül
kaydın değişmez alanlarını (id, ts, kimden, kime, konu, metin) göndericinin gizli
anahtarıyla imzalar ve doğrular.

Sınır (dürüst): anahtarlar aynı kullanıcı hesabındaki bir dizindedir. Anahtar dizinini
okuyabilen bir süreç herhangi bir ajan adına imza atabilir. Bu önlem, etiketi taklit eden
bir ajanı/istemi ve kayıt dosyasına elle satır ekleyeni durdurur; yerel kullanıcı
düzeyinde bir saldırganı durdurmaz.
"""
from __future__ import annotations

import hmac
import hashlib
import os
import re
import secrets
from pathlib import Path

ALG = "hmac-sha256"
IMZALI_ALANLAR = ("id", "ts", "kimden", "kime", "konu", "metin")
AD_DESENI = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
ANAHTAR_BAYT = 32

# doğrulama durumları
GECERLI = "gecerli"
IMZASIZ = "imzasiz"
ANAHTAR_YOK = "anahtar-yok"
GECERSIZ = "gecersiz"


def anahtar_dizini() -> Path:
    """Öncelik: KUTU_ANAHTAR_DIZIN, yoksa bu dosyanın yanındaki ``.anahtar/`` (gitignore'da)."""
    env = os.environ.get("KUTU_ANAHTAR_DIZIN")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / ".anahtar"


def gecerli_ad(ad: str) -> bool:
    """Yol kaçışını (``..``, ``/``, ``\\``) engellemek için dar bir ad kümesi."""
    return isinstance(ad, str) and bool(AD_DESENI.match(ad))


def anahtar_yolu(ad: str, dizin: Path | None = None) -> Path:
    if not gecerli_ad(ad):
        raise ValueError(f"geçersiz ajan adı: {ad!r} (küçük harf/rakam/-/_ ve en çok 32 karakter)")
    return (dizin or anahtar_dizini()) / f"{ad}.key"


def anahtar_uret(ad: str, dizin: Path | None = None, yenile: bool = False) -> tuple[Path, bool]:
    """(yol, yeni_mi). Var olan anahtarı ``yenile`` olmadan ezmez; değeri hiçbir yere basmaz."""
    yol = anahtar_yolu(ad, dizin)
    yol.parent.mkdir(parents=True, exist_ok=True)
    if yol.exists() and not yenile:
        return yol, False
    yol.write_text(secrets.token_hex(ANAHTAR_BAYT) + "\n", encoding="ascii")
    try:
        os.chmod(yol, 0o600)
    except OSError:
        pass
    return yol, True


def anahtar_oku(ad: str, dizin: Path | None = None) -> bytes | None:
    try:
        yol = anahtar_yolu(ad, dizin)
        metin = yol.read_text(encoding="ascii").strip()
        return bytes.fromhex(metin) if metin else None
    except (OSError, ValueError):
        return None


def kanonik(kayit: dict) -> bytes:
    """İmzalanan baytlar: yalnız IMZALI_ALANLAR, sıralı anahtarlı sıkı JSON (UTF-8)."""
    import json
    govde = {a: ("" if kayit.get(a) is None else str(kayit.get(a))) for a in IMZALI_ALANLAR}
    return json.dumps(govde, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def imza_hesapla(kayit: dict, anahtar: bytes) -> str:
    return hmac.new(anahtar, kanonik(kayit), hashlib.sha256).hexdigest()


def imzala(kayit: dict, dizin: Path | None = None) -> dict:
    """Kaydı ``kimden`` adının anahtarıyla imzalar (yerinde). Anahtar yoksa KeyError."""
    anahtar = anahtar_oku(str(kayit.get("kimden", "")), dizin)
    if anahtar is None:
        raise KeyError(f"'{kayit.get('kimden')}' için anahtar yok; önce: kutu anahtar-uret --ad {kayit.get('kimden')}")
    kayit["imza_alg"] = ALG
    kayit["imza"] = imza_hesapla(kayit, anahtar)
    return kayit


def dogrula(kayit: dict, dizin: Path | None = None) -> tuple[str, str]:
    """(durum, açıklama). Yalnız ``gecerli`` kabul edilir."""
    imza = kayit.get("imza")
    if not imza:
        return IMZASIZ, "kayıtta imza yok"
    if kayit.get("imza_alg", ALG) != ALG:
        return GECERSIZ, f"desteklenmeyen algoritma: {kayit.get('imza_alg')!r}"
    kimden = str(kayit.get("kimden", ""))
    if not gecerli_ad(kimden):
        return GECERSIZ, f"geçersiz gönderici adı: {kimden!r}"
    anahtar = anahtar_oku(kimden, dizin)
    if anahtar is None:
        return ANAHTAR_YOK, f"'{kimden}' için anahtar bulunamadı"
    beklenen = imza_hesapla(kayit, anahtar)
    if not hmac.compare_digest(str(imza), beklenen):
        return GECERSIZ, "imza uyuşmuyor (içerik ya da gönderici değişmiş / başka anahtarla imzalı)"
    return GECERLI, "imza geçerli"
