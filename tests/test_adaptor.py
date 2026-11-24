"""Adaptör testleri: gerçek araç ÇAĞRILMAZ (alt süreç ve ağ taklit edilir); gerçek 'merhaba' için uctan-uca.py."""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

import kutu
import kutu_adaptor as ka
import kutu_imza
from test_kutu import KutuTestBase, calistir

AGY_CIKTI = "\n".join(json.dumps(o, ensure_ascii=False) for o in (
    {"event": "init", "init": {"conversation_id": "00000000-0000-4000-8000-000000000001", "tools": ["x"]}},
    {"event": "step_update", "step_update": {"state": "ACTIVE", "text_delta": "akis-kanit"}},
    {"event": "result", "result": {"conversation_id": "00000000-0000-4000-8000-000000000001",
                                   "status": "SUCCESS", "response": "akis-kanit\n"}},
))


class AracBulmaTesti(unittest.TestCase):
    def test_ortam_degiskeni_oncelikli(self):
        with mock.patch.dict(os.environ, {"KUTU_ARAC_AGY": __file__}):
            self.assertEqual(ka.arac_bul("agy"), __file__)

    def test_olmayan_arac_none(self):
        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(ka.shutil, "which", return_value=None), \
                mock.patch.object(ka, "_kayit_adaylari", return_value=[]), \
                mock.patch.dict(ka.ARAC_ADAYLARI, {"opencode": (("opencode",), lambda: [])}):
            os.environ.pop("KUTU_ARAC_OPENCODE", None)
            self.assertIsNone(ka.arac_bul("opencode"))

    def test_shim_cmd_gercek_exe_cozulur(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            kok = Path(t)
            exe = kok / "node_modules" / "p" / "bin" / "x.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"MZ")
            cmd = kok / "x.cmd"
            cmd.write_text('@echo off\n"%dp0%\\node_modules\\p\\bin\\x.exe"   %*\n', encoding="utf-8")
            self.assertEqual(Path(ka.shim_coz(str(cmd))), exe)
            # exe yoksa sarmalayıcı olduğu gibi kalır
            exe.unlink()
            self.assertEqual(ka.shim_coz(str(cmd)), str(cmd))
        self.assertEqual(ka.shim_coz("C:/a/b.exe"), "C:/a/b.exe")


class SarmalayiciTesti(unittest.TestCase):
    def calis_sahte(self, rc=0, out="", err="", hata=""):
        return mock.patch.object(ka, "_calis", return_value=(rc, out, err, hata))

    def test_kurulu_degil_mesaji(self):
        with mock.patch.object(ka, "arac_bul", return_value=None):
            for ad in ka.ADAPTORLER:
                if ad == "hermes-http":
                    continue
                s = ka.ADAPTORLER[ad].gonder("m")
                self.assertFalse(s.tamam, ad)
                self.assertIn("kurulu değil", s.ayrinti, ad)

    def test_claude_p_istem_stdinden_ve_kayitsiz(self):
        with mock.patch.object(ka, "arac_bul", return_value="C:/x/claude.exe"), \
                self.calis_sahte(out="claude-kanit\n") as c:
            s = ka.gonder_claude_p("selam\nçok satırlı")
        komut, girdi = c.call_args.args[0], c.call_args.args[1]
        self.assertTrue(s.tamam)
        self.assertEqual(s.yanit, "claude-kanit")
        self.assertIn("--no-session-persistence", komut)
        self.assertEqual(komut[komut.index("--tools") + 1], "")       # araçsız
        self.assertEqual(girdi, "selam\nçok satırlı")                 # istem argümanda değil stdin'de

    def test_claude_p_hata_ve_zaman_asimi(self):
        with mock.patch.object(ka, "arac_bul", return_value="x"):
            with self.calis_sahte(rc=1, err="boom\nson hata"):
                s = ka.gonder_claude_p("m")
            self.assertFalse(s.tamam)
            self.assertIn("son hata", s.ayrinti)
            with self.calis_sahte(rc=124, hata="180 sn içinde dönmedi (süreç kapatıldı)"):
                s = ka.gonder_claude_p("m")
            self.assertIn("dönmedi", s.ayrinti)

    def test_agy_akis_ayiklama(self):
        durum, yanit, konusma = ka.agy_akis_ayikla(AGY_CIKTI + "\nbozuk satir\n")
        self.assertEqual((durum, yanit, konusma), ("SUCCESS", "akis-kanit", "00000000-0000-4000-8000-000000000001"))

    def test_agy_stream_json_komutu_ve_girdisi(self):
        with mock.patch.object(ka, "arac_bul", return_value="agy.exe"), \
                mock.patch.object(ka, "agy_oturum_temizle", return_value=["a", "b"]) as tem, \
                self.calis_sahte(out=AGY_CIKTI) as c:
            s = ka.gonder_agy("merhaba")
        komut, girdi = c.call_args.args[0], c.call_args.args[1]
        self.assertTrue(s.tamam)
        self.assertEqual(s.yanit, "akis-kanit")
        self.assertEqual(komut[-1], "-p=")                            # bitişik değer: yoksa --input-format istem sanılır
        self.assertEqual(json.loads(girdi), {"event": "user", "message": {"content": "merhaba"}})
        self.assertIn("plan", komut)                                  # araç eylemi yapmayan kip
        tem.assert_called_once_with("00000000-0000-4000-8000-000000000001")
        self.assertIn("temizlendi", s.ayrinti)

    def test_agy_hata_durumu(self):
        hata = json.dumps({"event": "result", "result": {"status": "ERROR", "response": "",
                                                         "error": "stream input message is missing the \"event\" field"}})
        with mock.patch.object(ka, "arac_bul", return_value="agy.exe"), self.calis_sahte(out=hata):
            s = ka.gonder_agy("m")
        self.assertFalse(s.tamam)
        self.assertIn("ERROR", s.ayrinti)

    def test_agy_temizle_yalniz_kendi_konusmasini_siler(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            kok = Path(t)
            benim = "00000000-0000-4000-8000-000000000001"
            baska = "00000000-0000-4000-8000-000000000002"
            for alt, ad in (("conversations", f"{benim}.db"), ("conversations", f"{baska}.db"),
                            ("annotations", f"{benim}.pbtxt"), ("presence", f"{benim}.lock")):
                (kok / alt).mkdir(exist_ok=True)
                (kok / alt / ad).write_text("x")
            (kok / "brain" / benim).mkdir(parents=True)
            (kok / "brain" / benim / "f.txt").write_text("x")
            (kok / "brain" / baska).mkdir()
            silinen = ka.agy_oturum_temizle(benim, kok)
            self.assertEqual(len(silinen), 4)
            self.assertTrue((kok / "conversations" / f"{baska}.db").exists())
            self.assertTrue((kok / "brain" / baska).exists())
            self.assertFalse((kok / "brain" / benim).exists())
            # geçersiz kimlik (yol kaçışı / joker) hiçbir şey silmez
            for kotu in ("..", "*", "../conversations", "", "d214e516"):
                self.assertEqual(ka.agy_oturum_temizle(kotu, kok), [], kotu)
            self.assertTrue((kok / "conversations" / f"{baska}.db").exists())

    def test_hermes_z(self):
        with mock.patch.object(ka, "arac_bul", return_value="hermes.exe"), self.calis_sahte(out="hermes-kanit\n") as c:
            s = ka.gonder_hermes_z("selam")
        self.assertTrue(s.tamam)
        self.assertEqual(s.yanit, "hermes-kanit")
        self.assertEqual(c.call_args.args[0][:3], ["hermes.exe", "-z", "selam"])

    def test_hermes_oturum_temizle_yalniz_kendi_calisma_adini_siler(self):
        ad = "kutu-oturum-ab12cd"
        kimlik = "local-" + "a1" * 32
        liste = ("Title    Workspace   Last Active   ID\n------\n"
                 f"hermes-kanit ile yanit   {ad[:16]}   1m ago   {kimlik}\n"       # sütun 16 karaktere kısalır
                 "Baska oturum   kullanici   3h ago   local-" + "b2" * 32 + "\n")
        cagrilar = []

        def sahte(komut, **kw):
            cagrilar.append(komut)
            if "list" in komut:
                return mock.Mock(stdout=liste, returncode=0)
            return mock.Mock(stdout="", returncode=0)
        with mock.patch.object(ka.subprocess, "run", side_effect=sahte):
            self.assertEqual(ka.hermes_oturum_temizle("hermes.exe", ad), 1)
        silme = [c for c in cagrilar if "delete" in c]
        self.assertEqual(len(silme), 1)
        self.assertEqual(silme[0][-1], kimlik)                    # yalnız kendi oturumu
        # geçersiz ad hiçbir komut çalıştırmaz
        cagrilar.clear()
        with mock.patch.object(ka.subprocess, "run", side_effect=sahte):
            self.assertEqual(ka.hermes_oturum_temizle("hermes.exe", "kullanici"), 0)
        self.assertEqual(cagrilar, [])

    def test_codex_exec_ephemeral_ve_son_mesaj_dosyasi(self):
        def sahte(komut, girdi, zaman, env=None):
            Path(komut[komut.index("-o") + 1]).write_text("codex-kanit\n", encoding="utf-8")
            return 0, "hook gürültüsü\n", "", ""
        with mock.patch.object(ka, "arac_bul", return_value="C:/x/codex.exe"), \
                mock.patch.object(ka, "_calis", side_effect=sahte) as c:
            s = ka.gonder_codex_exec("selam")
        komut = c.call_args.args[0]
        self.assertTrue(s.tamam)
        self.assertEqual(s.yanit, "codex-kanit")                        # stdout gürültüsü değil son mesaj
        self.assertIn("--ephemeral", komut)
        self.assertEqual(komut[komut.index("-s") + 1], "read-only")
        self.assertEqual(komut[-1], "-")                                 # istem stdin'den


class _SahteHermes(BaseHTTPRequestHandler):
    """Hermes /v1/runs sözleşmesinin yeterli bölümünü taklit eder."""
    kayit: dict = {}

    def log_message(self, *a):  # sessiz
        pass

    def _yaz(self, kod, govde):
        veri = json.dumps(govde).encode()
        self.send_response(kod)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(veri)))
        self.end_headers()
        self.wfile.write(veri)

    def _yetkili(self):
        if self.headers.get("Authorization") != "Bearer dogru-anahtar":
            self._yaz(401, {"error": {"message": "Invalid gateway API key"}})
            return False
        return True

    def do_POST(self):
        if not self._yetkili():
            return
        govde = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).kayit["post"] = govde
        self._yaz(202, {"run_id": "run_abc123def456", "status": "queued"})

    def do_GET(self):
        if not self._yetkili():
            return
        type(self).kayit["get"] = type(self).kayit.get("get", 0) + 1
        durum = "running" if type(self).kayit["get"] < 2 else "completed"
        self._yaz(200, {"object": "hermes.run", "run_id": "run_abc123def456", "status": durum,
                        "output": "hermes-http-kanit" if durum == "completed" else ""})


class HermesHttpTesti(unittest.TestCase):
    def setUp(self):
        _SahteHermes.kayit = {}
        self.sunucu = HTTPServer(("127.0.0.1", 0), _SahteHermes)
        self.url = f"http://127.0.0.1:{self.sunucu.server_address[1]}"
        self.is_parcacigi = threading.Thread(target=self.sunucu.serve_forever, daemon=True)
        self.is_parcacigi.start()
        self.addCleanup(self.durdur)

    def durdur(self):
        self.sunucu.shutdown()
        self.sunucu.server_close()
        self.is_parcacigi.join(5)

    def test_run_baslatir_yoklar_ve_ciktiyi_alir(self):
        s = ka.gonder_hermes_http("selam", zaman_asimi=20, url=self.url, anahtar="dogru-anahtar", aralik=0.01)
        self.assertTrue(s.tamam, s.ayrinti)
        self.assertEqual(s.yanit, "hermes-http-kanit")
        gonderilen = _SahteHermes.kayit["post"]
        self.assertEqual(gonderilen["input"], "selam")
        self.assertTrue(gonderilen["session_id"].startswith("kutu-"))   # her teslim yeni oturum
        self.assertGreaterEqual(_SahteHermes.kayit["get"], 2)           # bitene dek yoklandı

    def test_yanlis_anahtar_reddedilir(self):
        s = ka.gonder_hermes_http("selam", zaman_asimi=5, url=self.url, anahtar="yanlis")
        self.assertFalse(s.tamam)
        self.assertIn("401", s.ayrinti)

    def test_anahtar_tanimsizsa_gonderilmez(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KUTU_HERMES_ANAHTAR", None)
            s = ka.gonder_hermes_http("selam", url=self.url, anahtar="")
        self.assertFalse(s.tamam)
        self.assertIn("KUTU_HERMES_ANAHTAR", s.ayrinti)
        self.assertNotIn("post", _SahteHermes.kayit)

    def test_sunucu_kapaliysa_acik_hata(self):
        self.durdur()
        s = ka.gonder_hermes_http("selam", zaman_asimi=5, url=self.url, anahtar="dogru-anahtar")
        self.assertFalse(s.tamam)
        self.assertIn("ulaşılamadı", s.ayrinti)


class OnekTesti(unittest.TestCase):
    """Kayıtlı adaptörler güvenilir bir ön sözü mesajdan ÖNCE koyar (başsız araç izin sorup yanıtsız kalmasın)."""

    def test_kayitli_adaptor_oneki_mesajin_onune_koyar(self):
        alinan = []
        ham = ka.ADAPTORLER["agy"]
        with mock.patch.object(ka, "gonder_agy", side_effect=lambda m, *a, **k: alinan.append(m) or ka.Sonuc(True, "ok", "y")):
            # registry import anında bağlandı; _onekli ile yeniden sar
            sarili = ka._onekli(ka.gonder_agy)
            sarili("MESAJ")
        self.assertTrue(alinan[0].endswith("MESAJ"))
        self.assertIn("Araç çalıştırma", alinan[0])
        self.assertLess(alinan[0].index("Araç çalıştırma"), alinan[0].index("MESAJ"))

    def test_env_ile_kapatilir_ya_da_degistirilir(self):
        with mock.patch.dict(os.environ, {"KUTU_ADAPTOR_ONEK": ""}):
            self.assertEqual(ka.oneki(), "")
        with mock.patch.dict(os.environ, {"KUTU_ADAPTOR_ONEK": "ÖZEL\n"}):
            self.assertEqual(ka.oneki(), "ÖZEL\n")

    def test_registry_gercekten_sarili(self):
        with mock.patch.object(ka, "arac_bul", return_value="hermes.exe"), \
                mock.patch.object(ka, "_calis", return_value=(0, "y", "", "")) as c:
            ka.ADAPTORLER["hermes"].gonder("SELAM")
        self.assertTrue(c.call_args.args[0][2].endswith("SELAM"))
        self.assertIn("Araç çalıştırma", c.call_args.args[0][2])


class AdaptorKomutTesti(KutuTestBase):
    """kutu gonder --kime <adaptör>: giden kayıt + imzalı yanıt kaydı."""

    def sahte_adaptor(self, ad, sonuc):
        eski = ka.ADAPTORLER[ad]
        yeni = ka.Adaptor(ad, eski.arac, lambda mesaj, zaman_asimi=0: sonuc, eski.belge)
        return mock.patch.dict(ka.ADAPTORLER, {ad: yeni})

    def test_yanit_imzali_kayit_olur(self):
        calistir("anahtar-uret", "--hepsi")
        with self.sahte_adaptor("agy", ka.Sonuc(True, "agy stream-json yanıt verdi", "selam geri")):
            kod, out, _ = calistir("gonder", "--kime", "agy", "--kimden", "danisman", "--konu", "t",
                                   "--metin", "merhaba", "--kutu", str(self.kutu), "--imza-zorunlu")
        self.assertEqual(kod, 0, out)
        giden, cevap = kutu.kayit_oku(self.kutu)
        self.assertTrue(giden["durum"].startswith("teslim edildi"))
        self.assertEqual((cevap["kimden"], cevap["kime"], cevap["metin"], cevap["durum"]),
                         ("agy", "danisman", "selam geri", "yanit"))
        for k in (giden, cevap):
            self.assertEqual(kutu_imza.dogrula(k)[0], kutu_imza.GECERLI)

    def test_zorunlu_kipte_adaptor_anahtari_yoksa_yanit_kaydedilmez(self):
        calistir("anahtar-uret", "--ad", "danisman")
        with self.sahte_adaptor("agy", ka.Sonuc(True, "ok", "gizli yanıt")):
            kod, out, err = calistir("gonder", "--kime", "agy", "--kimden", "danisman",
                                     "--metin", "m", "--kutu", str(self.kutu), "--imza-zorunlu")
        self.assertEqual(kod, 1)
        self.assertIn("yanıt kaydedilmedi", err)
        kayitlar = kutu.kayit_oku(self.kutu)
        self.assertEqual(len(kayitlar), 1)                                # yalnız giden kayıt
        self.assertEqual(kayitlar[0]["kime"], "agy")

    def test_adaptor_hatasi_kayda_hata_olarak_girer(self):
        with self.sahte_adaptor("hermes", ka.Sonuc(False, "kurulu değil: hermes")):
            kod, _, err = calistir("gonder", "--kime", "hermes", "--kimden", "danisman",
                                   "--metin", "m", "--kutu", str(self.kutu))
        self.assertEqual(kod, 1)
        self.assertIn("kurulu değil", err)
        self.assertTrue(kutu.kayit_oku(self.kutu)[0]["durum"].startswith("hata:"))

    def test_kuru_calistirmaz_ve_kaydetmez(self):
        with mock.patch.object(ka, "arac_bul", return_value=None):
            kod, out, _ = calistir("gonder", "--kime", "opencode", "--kimden", "danisman",
                                   "--metin", "m", "--kutu", str(self.kutu), "--kuru")
        self.assertEqual(kod, 0)
        self.assertIn("kurulu değil", out)
        self.assertIn("talimat değildir", out)
        self.assertEqual(kutu.kayit_oku(self.kutu), [])

    def test_araclar_komutu_kurulu_ve_degil(self):
        def sahte_bul(ad):
            return "C:/x/agy.exe" if ad == "agy" else None
        with mock.patch.object(ka, "arac_bul", side_effect=sahte_bul), \
                mock.patch.object(ka, "surum", return_value="1.4.3"):
            kod, out, _ = calistir("araclar", "--json")
        veri = {s["adaptor"]: s for s in json.loads(out)}
        self.assertEqual(kod, 0)
        self.assertTrue(veri["agy"]["kurulu"])
        self.assertEqual(veri["agy"]["surum"], "1.4.3")
        self.assertFalse(veri["opencode"]["kurulu"])
        self.assertFalse(veri["gemini"]["kurulu"])


if __name__ == "__main__":
    unittest.main()
