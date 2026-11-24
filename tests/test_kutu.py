"""kutu birim testleri: yalnız standart kütüphane, gerçek codex/boru kullanılmaz."""
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import kutu


def calistir(*argv):
    """main'i çalıştırır; (çıkış kodu, stdout, stderr) döndürür."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        kod = kutu.main(list(argv))
    return kod, out.getvalue(), err.getvalue()


class KutuTestBase(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        self.addCleanup(self.gecici.cleanup)
        self.kok = Path(self.gecici.name)
        self.kutu = self.kok / "kutu"
        self.kayit_dizin = self.kok / "kayitlar"
        env = mock.patch.dict(os.environ, {"KUTU_KAYIT_DIZIN": str(self.kayit_dizin),
                                           "KUTU_ANAHTAR_DIZIN": str(self.kok / "anahtarlar")})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("KUTU_DIZIN", None)
        os.environ.pop("CODEX_HOME", None)  # gerçek ortam testi etkilemesin (patch.dict geri yükler)
        # Güvenlik ağı: test yanlışlıkla gerçek boruya yazmasın (bireysel testler üzerine mock koyar).
        koruma = mock.patch.object(kutu, "boruya_yaz", side_effect=AssertionError("testte gerçek boru yazımı"))
        koruma.start()
        self.addCleanup(koruma.stop)


class KayitTesti(KutuTestBase):
    def test_kayit_ve_konusma_yazilir(self):
        with mock.patch.object(kutu, "codex_gonder", return_value=(True, "tamam")):
            kod, _, _ = calistir("gonder", "--kime", "codex", "--kimden", "danisman",
                                 "--konu", "deneme", "--metin", "merhaba dünya",
                                 "--kutu", str(self.kutu), "--thread", "T-1")
        self.assertEqual(kod, 0)
        satirlar = kutu.kayit_oku(self.kutu)
        self.assertEqual(len(satirlar), 1)
        k = satirlar[0]
        for alan in ("id", "ts", "kimden", "kime", "konu", "metin", "durum"):
            self.assertIn(alan, k)
        self.assertEqual((k["kimden"], k["kime"], k["konu"], k["durum"]),
                         ("danisman", "codex", "deneme", "gonderildi"))
        self.assertEqual(k["metin"], "merhaba dünya")
        self.assertRegex(k["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        md = (self.kutu / "konusma.md").read_text(encoding="utf-8")
        self.assertIn("→ codex: deneme", md)
        self.assertIn("danisman →", md)
        self.assertIn("merhaba dünya", md)

    def test_hata_durumu_kaydedilir(self):
        with mock.patch.object(kutu, "codex_gonder", return_value=(False, "kötü")):
            kod, _, _ = calistir("gonder", "--kime", "codex", "--kimden", "kemal",
                                 "--metin", "x", "--kutu", str(self.kutu), "--thread", "T")
        self.assertEqual(kod, 1)
        self.assertEqual(kutu.kayit_oku(self.kutu)[0]["durum"], "hata: kötü")

    def test_id_benzersiz(self):
        idler = {kutu.id_uret() for _ in range(500)}
        self.assertEqual(len(idler), 500)
        self.assertRegex(next(iter(idler)), r"^\d{8}-\d{6}-[0-9a-f]{8}$")

    def test_bozuk_satir_atlanir(self):
        self.kutu.mkdir()
        (self.kutu / "kayit.jsonl").write_text('{"id": "a"}\n{yarım\n\n{"id": "b"}\n', encoding="utf-8")
        self.assertEqual([k["id"] for k in kutu.kayit_oku(self.kutu)], ["a", "b"])

    def test_bos_metin_reddedilir(self):
        kod, _, hata = calistir("gonder", "--kime", "codex", "--kimden", "kemal",
                                "--metin", "  ", "--kutu", str(self.kutu), "--thread", "T")
        self.assertEqual(kod, 2)
        self.assertIn("boş", hata)


class UzunMetinTesti(unittest.TestCase):
    def test_kisa_metin_aynen(self):
        self.assertEqual(kutu.iletilecek_metin("a" * 8000, "ID", Path("k.md")), "a" * 8000)

    def test_uzun_metin_kisaltilir(self):
        sonuc = kutu.iletilecek_metin("b" * 9000, "ID1", Path("/x/konusma.md"))
        self.assertTrue(sonuc.startswith("b" * 1500))
        self.assertNotIn("b" * 1501, sonuc)
        self.assertIn("tamamı:", sonuc)
        self.assertIn("#ID1", sonuc)

    def test_uzun_metin_kayitta_tam_kalir(self):
        metin = "uzun " * 3000
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(kutu, "codex_gonder", return_value=(True, "ok")) as g:
            calistir("gonder", "--kime", "codex", "--kimden", "kemal", "--metin", metin,
                     "--kutu", d, "--thread", "T")
            self.assertEqual(kutu.kayit_oku(Path(d))[0]["metin"], metin)
            iletilen = g.call_args.args[1]
            self.assertLess(len(iletilen), len(metin))
            self.assertIn("konusma.md", iletilen)


class AyarTesti(KutuTestBase):
    def test_kur_ayar_json_yazar_ve_okur(self):
        kod, _, _ = calistir("kur", "--kutu", str(self.kutu), "--codex-thread", "uuid-123")
        self.assertEqual(kod, 0)
        self.assertEqual(kutu.ayar_oku(self.kutu), {"codex_thread": "uuid-123"})

    def test_ayar_yoksa_veya_bozuksa_bos(self):
        self.assertEqual(kutu.ayar_oku(self.kutu), {})
        self.kutu.mkdir()
        (self.kutu / "ayar.json").write_text("{bozuk", encoding="utf-8")
        self.assertEqual(kutu.ayar_oku(self.kutu), {})

    def test_kutu_dizin_onceligi(self):
        self.assertEqual(kutu.kutu_dizini("a"), Path("a"))
        with mock.patch.dict(os.environ, {"KUTU_DIZIN": "env-dizin"}):
            self.assertEqual(kutu.kutu_dizini(None), Path("env-dizin"))
        self.assertEqual(kutu.kutu_dizini(None), Path.cwd() / ".kutu")

    def test_thread_ayardan_gelir(self):
        kutu_yolu = str(self.kutu)
        calistir("kur", "--kutu", kutu_yolu, "--codex-thread", "AYAR-T")
        with mock.patch.object(kutu, "codex_gonder", return_value=(True, "ok")) as g:
            calistir("gonder", "--kime", "codex", "--kimden", "kemal", "--metin", "x", "--kutu", kutu_yolu)
        self.assertEqual(g.call_args.args[0], "AYAR-T")

    def test_thread_yoksa_hata(self):
        kod, _, hata = calistir("gonder", "--kime", "codex", "--kimden", "kemal",
                                "--metin", "x", "--kutu", str(self.kutu))
        self.assertEqual(kod, 2)
        self.assertIn("thread", hata)


class CodexHomeTesti(KutuTestBase):
    def _gonder(self, *ek):
        sahte = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(kutu, "codex_onek", return_value=["codex"]), \
                mock.patch.object(kutu.subprocess, "run", return_value=sahte) as run:
            kod, _, _ = calistir("gonder", "--kime", "codex", "--kimden", "danisman",
                                 "--metin", "x", "--kutu", str(self.kutu), *ek)
        self.assertEqual(kod, 0)
        return run.call_args.kwargs["env"]

    def test_kur_codex_home_yazar(self):
        calistir("kur", "--kutu", str(self.kutu), "--codex-thread", "T", "--codex-home", "X:/ayar-home")
        self.assertEqual(kutu.ayar_oku(self.kutu), {"codex_thread": "T", "codex_home": "X:/ayar-home"})

    def test_kur_verilmezse_ortamdaki_kaydedilir(self):
        with mock.patch.dict(os.environ, {"CODEX_HOME": "X:/ortam-home"}):
            calistir("kur", "--kutu", str(self.kutu), "--codex-thread", "T")
        self.assertEqual(kutu.ayar_oku(self.kutu)["codex_home"], "X:/ortam-home")

    def test_kur_arguman_ortamdan_once(self):
        with mock.patch.dict(os.environ, {"CODEX_HOME": "X:/ortam-home"}):
            calistir("kur", "--kutu", str(self.kutu), "--codex-thread", "T", "--codex-home", "X:/arg")
        self.assertEqual(kutu.ayar_oku(self.kutu)["codex_home"], "X:/arg")

    def test_kur_hicbiri_yoksa_alan_yazilmaz(self):
        calistir("kur", "--kutu", str(self.kutu), "--codex-thread", "T")
        self.assertNotIn("codex_home", kutu.ayar_oku(self.kutu))

    def test_ayardaki_codex_home_alt_surece_gecer(self):
        calistir("kur", "--kutu", str(self.kutu), "--codex-thread", "T", "--codex-home", "X:/ayar-home")
        env = self._gonder()
        self.assertEqual(env["CODEX_HOME"], "X:/ayar-home")
        self.assertNotIn("CODEX_HOME", os.environ)  # global ortam değişmedi

    def test_ortam_ayardan_onceliklidir(self):
        calistir("kur", "--kutu", str(self.kutu), "--codex-thread", "T", "--codex-home", "X:/ayar-home")
        with mock.patch.dict(os.environ, {"CODEX_HOME": "X:/ortam-home"}):
            env = self._gonder()
        self.assertEqual(env["CODEX_HOME"], "X:/ortam-home")

    def test_hicbiri_yoksa_dokunulmaz(self):
        calistir("kur", "--kutu", str(self.kutu), "--codex-thread", "T")
        self.assertNotIn("CODEX_HOME", self._gonder())

    def test_rollout_hatasinda_ipucu(self):
        sahte = subprocess.CompletedProcess([], 1, stdout="",
                                            stderr="Error: no rollout found for thread id 01a1e9ae-x")
        with mock.patch.object(kutu, "codex_onek", return_value=["codex"]), \
                mock.patch.object(kutu.subprocess, "run", return_value=sahte):
            kod, _, hata = calistir("gonder", "--kime", "codex", "--kimden", "danisman",
                                    "--metin", "x", "--kutu", str(self.kutu), "--thread", "THR")
        self.assertEqual(kod, 1)
        self.assertIn("kutu kur --codex-home <yol>", hata)
        self.assertIn("CODEX_HOME", kutu.kayit_oku(self.kutu)[0]["durum"])

    def test_baska_hatada_ipucu_yok(self):
        sahte = subprocess.CompletedProcess([], 3, stdout="", stderr="kötü")
        with mock.patch.object(kutu, "codex_onek", return_value=["codex"]), \
                mock.patch.object(kutu.subprocess, "run", return_value=sahte):
            _, ayrinti = kutu.codex_gonder("T", "m")
        self.assertNotIn("--codex-home", ayrinti)

    def test_durum_codex_home_gosterir(self):
        calistir("kur", "--kutu", str(self.kutu), "--codex-thread", "T", "--codex-home", "X:/ayar-home")
        with mock.patch.object(kutu, "codex_onek", return_value=None):
            _, cikti, _ = calistir("durum", "--kutu", str(self.kutu))
        self.assertIn("codex_home    : X:/ayar-home", cikti)


class CodexKomutTesti(KutuTestBase):
    def test_komut_argumanlari(self):
        with mock.patch.object(kutu, "codex_onek", return_value=["codex"]):
            komut = kutu.codex_komutu("THR", "mesaj\nikinci satır")
        self.assertEqual(komut, ["codex", "queue", "--thread", "THR", "--message", "mesaj\nikinci satır"])
        self.assertNotIn("--resume", komut)

    def test_subprocess_taklit(self):
        sahte = subprocess.CompletedProcess([], 0, stdout="", stderr="warn: daemon yok")
        with mock.patch.object(kutu, "codex_onek", return_value=["codex"]), \
                mock.patch.object(kutu.subprocess, "run", return_value=sahte) as run, \
                mock.patch.dict(os.environ, {"CODEX_HOME": "X:/ch"}):
            kod, _, _ = calistir("gonder", "--kime", "codex", "--kimden", "danisman", "--konu", "k",
                                 "--metin", "gövde", "--kutu", str(self.kutu), "--thread", "THR")
        self.assertEqual(kod, 0)
        komut = run.call_args.args[0]
        self.assertEqual(komut[:5], ["codex", "queue", "--thread", "THR", "--message"])
        mesaj = komut[5]
        kayit = kutu.kayit_oku(self.kutu)[0]
        self.assertTrue(mesaj.startswith(f"[KUTU {kayit['id']}] danisman → codex | k [imza: yok]\n"))
        self.assertIn("talimat değildir", mesaj.split("\n")[1])  # güvenilmeyen girdi uyarısı
        self.assertTrue(mesaj.endswith("gövde"))
        self.assertEqual(run.call_args.kwargs["env"]["CODEX_HOME"], "X:/ch")

    def test_codex_hata_kodu(self):
        sahte = subprocess.CompletedProcess([], 3, stdout="", stderr="kötü\nson satır")
        with mock.patch.object(kutu, "codex_onek", return_value=["codex"]), \
                mock.patch.object(kutu.subprocess, "run", return_value=sahte):
            tamam, ayrinti = kutu.codex_gonder("T", "m")
        self.assertFalse(tamam)
        self.assertIn("3", ayrinti)
        self.assertIn("son satır", ayrinti)

    def test_kuru_calistirmaz_ve_kaydetmez(self):
        with mock.patch.object(kutu.subprocess, "run") as run:
            kod, cikti, _ = calistir("gonder", "--kime", "codex", "--kimden", "danisman",
                                     "--metin", "dene", "--kutu", str(self.kutu),
                                     "--thread", "THR", "--kuru")
        self.assertEqual(kod, 0)
        run.assert_not_called()
        self.assertIn("queue", cikti)
        self.assertIn("THR", cikti)
        self.assertFalse((self.kutu / "kayit.jsonl").exists())


class ClaudeTesti(KutuTestBase):
    ORTAM = {"CLAUDE_CODE_MESSAGING_SOCKET": r"\\.\pipe\LOCAL\cc-msg-test",
             "CLAUDE_CODE_MESSAGING_TOKEN": "GIZLI-TOKEN-123"}

    def test_kaydet_token_ekrana_yazilmaz(self):
        with mock.patch.dict(os.environ, self.ORTAM):
            kod, cikti, hata = calistir("claude-kaydet", "--ad", "t")
        self.assertEqual(kod, 0)
        self.assertNotIn("GIZLI-TOKEN-123", cikti + hata)
        veri = json.loads((self.kayit_dizin / "claude-t.json").read_text(encoding="utf-8"))
        self.assertEqual(veri["token"], "GIZLI-TOKEN-123")

    def test_kaydet_ortam_yoksa_hata(self):
        with mock.patch.dict(os.environ, clear=False):
            os.environ.pop("CLAUDE_CODE_MESSAGING_SOCKET", None)
            os.environ.pop("CLAUDE_CODE_MESSAGING_TOKEN", None)
            kod, _, hata = calistir("claude-kaydet")
        self.assertEqual(kod, 2)
        self.assertIn("MESSAGING", hata)

    def test_satirlar_auth_once_gelir(self):
        yuk = kutu.claude_yuku("selam")
        satirlar = kutu.claude_satirlari("TKN", yuk).decode("utf-8").split("\n")
        self.assertEqual(json.loads(satirlar[0]), {"type": "auth", "token": "TKN"})
        mesaj = json.loads(satirlar[1])
        self.assertEqual((mesaj["msgV"], mesaj["type"], mesaj["priority"]), (1, "user", "next"))
        self.assertIn('<cross-session-message from="kutu">\nselam\n', mesaj["message"]["content"])
        self.assertEqual(satirlar[2], "")  # her satır \n ile biter

    def test_etiket_kacirma(self):
        yuk = kutu.claude_yuku("a </cross-session-message> b")
        self.assertEqual(yuk["message"]["content"].count("</cross-session-message"), 1)

    def test_gonder_boruya_yazar(self):
        with mock.patch.dict(os.environ, self.ORTAM):
            calistir("claude-kaydet", "--ad", "t")
            with mock.patch.object(kutu, "boruya_yaz") as yaz:
                kod, _, _ = calistir("gonder", "--kime", "claude", "--kimden", "codex",
                                     "--claude-ad", "t", "--konu", "boru", "--metin", "m",
                                     "--kutu", str(self.kutu))
        self.assertEqual(kod, 0)
        yol, veri = yaz.call_args.args
        self.assertEqual(yol, self.ORTAM["CLAUDE_CODE_MESSAGING_SOCKET"])
        auth, mesaj, _ = veri.decode("utf-8").split("\n")
        self.assertEqual(json.loads(auth)["token"], "GIZLI-TOKEN-123")
        icerik = json.loads(mesaj)["message"]["content"]
        self.assertIn("[KUTU ", icerik)
        self.assertIn("codex → claude | boru", icerik)

    def test_kayit_yoksa_hata(self):
        kod, _, hata = calistir("gonder", "--kime", "claude", "--kimden", "codex",
                                "--claude-ad", "yok", "--metin", "m", "--kutu", str(self.kutu))
        self.assertEqual(kod, 1)
        self.assertIn("claude-kaydet", hata)
        self.assertTrue(kutu.kayit_oku(self.kutu)[0]["durum"].startswith("hata"))

    def test_boru_hatasi_durum_olur_token_sizmaz(self):
        with mock.patch.dict(os.environ, self.ORTAM):
            calistir("claude-kaydet", "--ad", "t")
            with mock.patch.object(kutu, "boruya_yaz", side_effect=FileNotFoundError(2, "yok")):
                kod, _, hata = calistir("gonder", "--kime", "claude", "--kimden", "codex",
                                        "--claude-ad", "t", "--metin", "m", "--kutu", str(self.kutu))
        self.assertEqual(kod, 1)
        self.assertNotIn("GIZLI-TOKEN-123", hata)
        self.assertNotIn("GIZLI-TOKEN-123", (self.kutu / "kayit.jsonl").read_text(encoding="utf-8"))

    def test_kuru_tokeni_gizler(self):
        with mock.patch.dict(os.environ, self.ORTAM):
            calistir("claude-kaydet", "--ad", "danisman")
            kod, cikti, _ = calistir("gonder", "--kime", "claude", "--kimden", "codex",
                                     "--metin", "m", "--kutu", str(self.kutu), "--kuru")
        self.assertEqual(kod, 0)
        self.assertNotIn("GIZLI-TOKEN-123", cikti)


class ClaudeAdUyariTesti(KutuTestBase):
    """--claude-ad verilmeden birden çok kayıt varsa uyarı; varsayılan davranış ('danisman') değişmez."""
    SOCKET_DANISMAN = r"\\.\pipe\LOCAL\cc-msg-danisman"
    SOCKET_DIGER = r"\\.\pipe\LOCAL\cc-msg-diger"

    def kaydet(self, ad, socket):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_MESSAGING_SOCKET": socket,
                                          "CLAUDE_CODE_MESSAGING_TOKEN": "GIZLI-TOKEN-" + ad}):
            self.assertEqual(calistir("claude-kaydet", "--ad", ad)[0], 0)

    def gonder(self, *ek):
        with mock.patch.object(kutu, "boruya_yaz") as yaz:
            kod, cikti, hata = calistir("gonder", "--kime", "claude", "--kimden", "codex", "--metin", "m",
                                        "--kutu", str(self.kutu), *ek)
        return kod, cikti, hata, yaz

    def test_ad_verilmedi_ve_birden_cok_kayit_uyarir(self):
        self.kaydet("danisman", self.SOCKET_DANISMAN)
        self.kaydet("diger", self.SOCKET_DIGER)
        kod, _, hata, yaz = self.gonder()
        self.assertEqual(kod, 0)
        self.assertIn("uyarı: --claude-ad verilmedi", hata)
        self.assertIn("'danisman'", hata)
        self.assertIn("danisman, diger", hata)
        self.assertIn("--claude-ad <ad>", hata)
        self.assertNotIn("GIZLI-TOKEN", hata)

    def test_varsayilan_davranis_korunur_danisman_kaydina_yazar(self):
        self.kaydet("danisman", self.SOCKET_DANISMAN)
        self.kaydet("diger", self.SOCKET_DIGER)
        kod, _, _, yaz = self.gonder()
        self.assertEqual(kod, 0)
        self.assertEqual(yaz.call_args.args[0], self.SOCKET_DANISMAN)

    def test_acik_ad_uyari_vermez_ve_o_kayda_yazar(self):
        self.kaydet("danisman", self.SOCKET_DANISMAN)
        self.kaydet("diger", self.SOCKET_DIGER)
        kod, _, hata, yaz = self.gonder("--claude-ad", "diger")
        self.assertEqual(kod, 0)
        self.assertEqual(hata, "")
        self.assertEqual(yaz.call_args.args[0], self.SOCKET_DIGER)

    def test_tek_kayit_uyari_vermez(self):
        self.kaydet("danisman", self.SOCKET_DANISMAN)
        kod, _, hata, _ = self.gonder()
        self.assertEqual(kod, 0)
        self.assertEqual(hata, "")

    def test_kuru_kipte_de_uyarir_ve_token_basmaz(self):
        self.kaydet("danisman", self.SOCKET_DANISMAN)
        self.kaydet("diger", self.SOCKET_DIGER)
        kod, cikti, hata, yaz = self.gonder("--kuru")
        self.assertEqual(kod, 0)
        self.assertIn("uyarı: --claude-ad verilmedi", hata)
        self.assertNotIn("GIZLI-TOKEN", cikti + hata)
        yaz.assert_not_called()

    def test_codex_hedefinde_claude_uyarisi_yok(self):
        self.kaydet("danisman", self.SOCKET_DANISMAN)
        self.kaydet("diger", self.SOCKET_DIGER)
        with mock.patch.object(kutu, "codex_gonder", return_value=(True, "tamam")):
            kod, _, hata = calistir("gonder", "--kime", "codex", "--kimden", "danisman", "--metin", "m",
                                    "--kutu", str(self.kutu), "--thread", "T-1")
        self.assertEqual(kod, 0)
        self.assertEqual(hata, "")


class HtmlTesti(KutuTestBase):
    def kayit(self, kimden, metin, kime="codex", durum="gonderildi", konu=""):
        return {"id": "i", "ts": "2026-11-18T10:04:00+03:00", "kimden": kimden, "kime": kime,
                "konu": konu, "metin": metin, "durum": durum}

    def test_html_icerik_ve_kacis(self):
        sayfa = kutu.html_uret([self.kayit("danisman", "<script>alert(1)</script>", konu="k & l"),
                                self.kayit("codex", "yanıt", kime="claude", durum="hata: x"),
                                self.kayit("kemal", "not")])
        self.assertNotIn("<script", sayfa)
        self.assertIn("&lt;script&gt;", sayfa)
        self.assertIn("k &amp; l", sayfa)
        self.assertIn('class="satir danisman"', sayfa)
        self.assertIn('class="satir codex"', sayfa)
        self.assertIn('class="satir kemal"', sayfa)
        self.assertIn("prefers-color-scheme:dark", sayfa)
        self.assertIn("10:04", sayfa)
        self.assertIn("hata: x", sayfa)
        self.assertIn('lang="tr"', sayfa)

    def test_bos_kutu(self):
        self.assertIn("Henüz mesaj yok", kutu.html_uret([]))

    def test_sayfa_komutu_dosya_yazar(self):
        kutu.kayit_ekle(self.kutu, self.kayit("kemal", "merhaba"))
        kod, cikti, _ = calistir("sayfa", "--kutu", str(self.kutu))
        self.assertEqual(kod, 0)
        yol = self.kutu / "konusma.html"
        self.assertTrue(yol.is_file())
        self.assertIn("merhaba", yol.read_text(encoding="utf-8"))
        self.assertIn("konusma.html", cikti)


class IzleDurumTesti(KutuTestBase):
    def test_izle_son_n(self):
        for i in range(5):
            kutu.kayit_ekle(self.kutu, {"id": f"i{i}", "ts": f"2026-11-18T10:0{i}:00+03:00",
                                        "kimden": "kemal", "kime": "codex", "konu": f"k{i}",
                                        "metin": f"satır {i}\nikinci", "durum": "gonderildi"})
        _, cikti, _ = calistir("izle", "--son", "2", "--kutu", str(self.kutu))
        self.assertEqual(len(cikti.strip().splitlines()), 2)
        self.assertIn("satır 4", cikti)
        self.assertNotIn("ikinci", cikti)

    def test_durum_token_gostermez(self):
        with mock.patch.dict(os.environ, ClaudeTesti.ORTAM):
            calistir("claude-kaydet", "--ad", "t")
        with mock.patch.object(kutu, "codex_onek", return_value=None):
            _, cikti, _ = calistir("durum", "--kutu", str(self.kutu))
        self.assertIn("t (kayıt", cikti)
        self.assertNotIn("GIZLI-TOKEN-123", cikti)
        self.assertIn("bulunamadı", cikti)


class BoruIzinTesti(KutuTestBase):
    def _gonder(self, hata):
        with mock.patch.dict(os.environ, ClaudeTesti.ORTAM):
            calistir("claude-kaydet", "--ad", "t")
            with mock.patch.object(kutu, "boruya_yaz", side_effect=hata):
                return calistir("gonder", "--kime", "claude", "--kimden", "codex",
                                "--claude-ad", "t", "--metin", "m", "--kutu", str(self.kutu))

    def test_izin_hatasi_kayitta_durumu_ve_kod_0(self):
        kod, cikti, hata = self._gonder(PermissionError(13, "Permission denied"))
        self.assertEqual(kod, 0)
        durum = kutu.kayit_oku(self.kutu)[0]["durum"]
        self.assertEqual(durum, "kayitta: boru erisilemedi (PermissionError 13), izleyici alir")
        self.assertNotIn("hata", durum)
        self.assertIn("kayda yazıldı; danışman tarafındaki izleyici alacak, tekrar gönderme", cikti)
        self.assertEqual(hata, "")
        self.assertNotIn("GIZLI-TOKEN-123", durum + cikti)

    def test_erisim_reddi_winerror_5_izin_sayilir(self):
        e = OSError(13, "Access denied")
        e.winerror = 5
        kod, _, _ = self._gonder(e)
        self.assertEqual(kod, 0)
        self.assertTrue(kutu.kayit_oku(self.kutu)[0]["durum"].startswith("kayitta:"))

    def test_diger_boru_hatalari_eskisi_gibi(self):
        kod, _, hata = self._gonder(FileNotFoundError(2, "yok"))
        self.assertEqual(kod, 1)
        self.assertEqual(kutu.kayit_oku(self.kutu)[0]["durum"], "hata: boru yazılamadı: FileNotFoundError 2")
        self.assertIn("boru yazılamadı", hata)

    def test_html_kayitta_durumu_hata_rozeti_almaz(self):
        self._gonder(PermissionError(13, "x"))
        self.assertNotIn('class="hata"', kutu.html_uret(kutu.kayit_oku(self.kutu)))


class BekleTesti(KutuTestBase):
    def setUp(self):
        super().setUp()
        self.kutu.mkdir()
        self.yol = self.kutu / "kayit.jsonl"

    def ekle(self, *kayitlar, ham=None):
        with self.yol.open("ab") as f:
            for k in kayitlar:
                f.write((json.dumps(k, ensure_ascii=False) + "\n").encode("utf-8"))
            if ham:
                f.write(ham)

    @staticmethod
    def kayit(i, kime="claude", kimden="codex", metin="m", konu=""):
        return {"id": i, "ts": "2026-11-18T10:00:00+03:00", "kimden": kimden,
                "kime": kime, "konu": konu, "metin": metin, "durum": "gonderildi"}

    def test_eski_satirlari_atlar_yalniz_eslesen_doner(self):
        self.ekle(self.kayit("eski"))
        t = kutu.KayitTakipci(self.yol, kime="claude")
        self.assertEqual(t.tur(), [])
        self.ekle(self.kayit("a"), self.kayit("b", kime="codex"), self.kayit("c"))
        self.assertEqual([k["id"] for k in t.tur()], ["a", "c"])
        self.assertEqual(t.tur(), [])  # aynı satır ikinci kez gelmez

    def test_kimden_haric(self):
        t = kutu.KayitTakipci(self.yol, kime="claude", kimden_haric="kemal")
        self.ekle(self.kayit("a", kimden="kemal"), self.kayit("b", kimden="codex"))
        self.assertEqual([k["id"] for k in t.tur()], ["b"])

    def test_yarim_satir_sonraki_tura_kalir(self):
        t = kutu.KayitTakipci(self.yol, kime="claude")
        tam = json.dumps(self.kayit("y", metin="şğü"), ensure_ascii=False).encode("utf-8")
        self.ekle(ham=tam[:20])
        self.assertEqual(t.tur(), [])
        self.ekle(ham=tam[20:])
        self.assertEqual(t.tur(), [])  # hâlâ satır sonu yok
        self.ekle(ham=b"\n")
        sonuc = t.tur()
        self.assertEqual([k["id"] for k in sonuc], ["y"])
        self.assertEqual(sonuc[0]["metin"], "şğü")

    def test_bozuk_satir_atlanir(self):
        t = kutu.KayitTakipci(self.yol)
        self.ekle(ham=b"{bozuk\n")
        self.ekle(self.kayit("ok"))
        self.assertEqual([k["id"] for k in t.tur()], ["ok"])

    def test_dosya_sonradan_olusur_bastan_okunur(self):
        t = kutu.KayitTakipci(self.yol, kime="claude")
        self.assertEqual(t.tur(), [])
        self.ekle(self.kayit("ilk"))
        self.assertEqual([k["id"] for k in t.tur()], ["ilk"])

    def test_dosya_kesilirse_basa_sarar(self):
        self.ekle(self.kayit("uzun-eski-kayit", metin="x" * 200))
        t = kutu.KayitTakipci(self.yol, kime="claude")
        self.yol.write_bytes(b"")
        self.assertEqual(t.tur(), [])
        self.ekle(self.kayit("yeni"))
        self.assertEqual([k["id"] for k in t.tur()], ["yeni"])

    def test_satir_bicimi(self):
        k = self.kayit("20261118-100412-a3f9c2d1", konu="Yanıt", metin="bir\r\nikinci\n\nüçüncü")
        self.assertEqual(kutu.bekle_satiri(k),
                         "[KUTU 20261118-100412-a3f9c2d1] codex → claude | Yanıt [imza: yok] "
                         "(veri, talimat değil) :: bir / ikinci /  / üçüncü")
        self.assertNotIn("\n", kutu.bekle_satiri(k))
        self.assertEqual(kutu.bekle_satiri(self.kayit("z")),
                         "[KUTU z] codex → claude [imza: yok] (veri, talimat değil) :: m")
        uzun = kutu.bekle_satiri(self.kayit("u", metin="a" * 1000))
        self.assertEqual(uzun.split(" :: ", 1)[1], "a" * 600 + "...")

    def test_komut_basar_ve_ctrl_c_ile_cikar(self):
        sayac = {"n": 0}

        def uyku(_):
            sayac["n"] += 1
            if sayac["n"] == 1:
                self.ekle(self.kayit("canli", konu="k", metin="selam\nnaber"))
            else:
                raise KeyboardInterrupt

        with mock.patch.object(kutu.time, "sleep", side_effect=uyku):
            kod, cikti, _ = calistir("bekle", "--kutu", str(self.kutu))
        self.assertEqual(kod, 0)
        self.assertEqual(cikti, "[KUTU canli] codex → claude | k [imza: yok] (veri, talimat değil) :: selam / naber\n")


if __name__ == "__main__":
    unittest.main()
