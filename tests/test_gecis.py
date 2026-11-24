"""gecis-kontrol testleri: salt-okunur olduğu, hash/süreç/Claude adı raporu, engel durumunda çıkış 1."""
import hashlib
import json
import os
import unittest
from unittest import mock

import kutu
import kutu_gecis
import kutu_imza
from test_kutu import KutuTestBase, calistir


def kayit(id_, kimden="danisman", kime="codex", **ek):
    k = {"id": id_, "ts": "2026-11-18T12:00:00+03:00", "kimden": kimden, "kime": kime, "konu": "k",
         "metin": "m", "durum": "gonderildi"}
    k.update(ek)
    return k


class GecisTesti(KutuTestBase):
    def setUp(self):
        super().setUp()
        self.eski = self.kok / "eski"
        self.yeni = self.kok / "yeni" / "kutu"
        self.anahtar = self.kok / "yeni" / ".anahtar"
        kutu_imza.anahtar_uret("danisman", self.anahtar)
        kutu_imza.anahtar_uret("codex", self.anahtar)
        # eski kutu: imzasız iki kayıt
        for k in (kayit("e1"), kayit("e2", kimden="codex", kime="claude")):
            kutu.kayit_ekle(self.eski, k)
        (self.eski / "ayar.json").write_text(json.dumps({"codex_thread": "T-1", "codex_home": "H"}), encoding="utf-8")
        # yeni kutu: bir imzalı kayıt, imza zorunlu
        kutu.kayit_ekle(self.yeni, kutu_imza.imzala(kayit("y1"), self.anahtar))
        (self.yeni / "ayar.json").write_text(json.dumps({"codex_thread": "T-1", "imza_zorunlu": True}), encoding="utf-8")
        self.sur = mock.patch.object(kutu_gecis, "surec_listesi", return_value=[])
        self.sur.start()
        self.addCleanup(self.sur.stop)

    def gk(self, *ek):
        return calistir("gecis-kontrol", "--eski", str(self.eski), "--yeni", str(self.yeni),
                        "--anahtar-dizin", str(self.anahtar), *ek)

    def anlik(self):
        """Tüm dosyaların (yol, boyut, mtime_ns, sha256) görüntüsü: salt-okunurluk kanıtı."""
        goruntu = {}
        for kok in (self.eski, self.yeni, self.anahtar, self.kayit_dizin):
            for yol in sorted(kok.rglob("*")) if kok.exists() else []:
                if yol.is_file():
                    st = yol.stat()
                    goruntu[str(yol)] = (st.st_size, st.st_mtime_ns, hashlib.sha256(yol.read_bytes()).hexdigest())
        return goruntu

    def test_rapor_hash_sayi_ve_anahtar_adlari(self):
        kod, cikti, hata = self.gk()
        self.assertEqual(kod, 0, cikti + hata)
        sha = hashlib.sha256((self.eski / "kayit.jsonl").read_bytes()).hexdigest()
        self.assertIn(sha, cikti)
        self.assertIn("kayıt: 2 (imzalı 0, imzasız 2)", cikti)       # eski
        self.assertIn("kayıt: 1 (imzalı 1, imzasız 0)", cikti)       # yeni
        self.assertIn("imza_zorunlu EVET", cikti)
        self.assertIn("anahtar adları (değer basılmaz): codex, danisman", cikti)
        self.assertIn("geçerli 1", cikti)
        self.assertIn("codex_thread eski ve yeni kutuda aynı mı: evet", cikti)
        self.assertIn("UYARI: eski kutunun 2 kaydı imzasız", cikti)
        self.assertIn("bu komut hiçbir şeyi değiştirmedi", cikti)

    def test_salt_okunur_hicbir_dosya_degismez(self):
        once = self.anlik()
        kod, _, _ = self.gk("--beklenen", "kayit.jsonl=" + hashlib.sha256(
            (self.eski / "kayit.jsonl").read_bytes()).hexdigest()[:8])
        self.assertEqual(kod, 0)
        self.gk("--json")
        self.assertEqual(self.anlik(), once)

    def test_olmayan_yeni_kutu_olusturulmaz_ve_sorundur(self):
        yok = self.kok / "yok" / "kutu"
        kod, cikti, _ = calistir("gecis-kontrol", "--eski", str(self.eski), "--yeni", str(yok))
        self.assertEqual(kod, 1)
        self.assertIn("SORUN: yeni kutu klasörü yok", cikti)
        self.assertFalse(yok.exists())
        self.assertFalse(yok.parent.exists())

    def test_beklenen_hash_uyar_ve_uyumsuzsa_cikis_1(self):
        sha = hashlib.sha256((self.eski / "kayit.jsonl").read_bytes()).hexdigest()
        kod, cikti, _ = self.gk("--beklenen", f"kayit.jsonl={sha[:8]}")
        self.assertEqual(kod, 0)
        self.assertIn("-> AYNI", cikti)
        kod, cikti, _ = self.gk("--beklenen", "kayit.jsonl=00000000")
        self.assertEqual(kod, 1)
        self.assertIn("FARKLI", cikti)
        self.assertIn("SORUN: eski kutu kayit.jsonl sha256 beklenenle uyuşmuyor", cikti)

    def test_beklenen_bicimi_hatali(self):
        kod, _, hata = self.gk("--beklenen", "kayit.jsonl=xyz")
        self.assertEqual(kod, 2)
        self.assertIn("--beklenen biçimi", hata)

    def test_yeni_kutuda_gecersiz_imza_sorundur(self):
        bozuk = kutu_imza.imzala(kayit("y2"), self.anahtar)
        bozuk["metin"] = "DEGISTIRILDI"
        kutu.kayit_ekle(self.yeni, bozuk)
        kod, cikti, _ = self.gk()
        self.assertEqual(kod, 1)
        self.assertIn("SORUN: yeni kutuda 1 geçersiz imzalı kayıt var", cikti)

    def test_bekle_surecleri_eski_yeni_ayrilir_kendi_pid_haric(self):
        py = "python"
        liste = [
            (111, f'{py} "X:/ajan/kutu.py" bekle --kutu "{self.eski}" --kime claude'),
            (222, f'{py} X:/ajan/kutu.py bekle --kutu {self.yeni} --kime claude --imza-zorunlu'),
            (333, f'{py} X:/ajan/kutu.py bekle --kime claude'),
            (444, f'{py} X:/ajan/kutu.py bekle --kutu X:/baska/kutu'),
            (os.getpid(), f'{py} X:/ajan/kutu.py bekle --kutu {self.eski}'),
            (555, f'{py} X:/ajan/baska.py bekle --kutu {self.eski}'),          # kutu bekle değil
        ]
        s = kutu_gecis.bekle_surecleri(self.eski, self.yeni, liste)
        self.assertEqual([p["pid"] for p in s["eski"]], [111])
        self.assertEqual([p["pid"] for p in s["yeni"]], [222])
        self.assertTrue(s["yeni"][0]["imza_zorunlu"])
        self.assertEqual([p["pid"] for p in s["belirsiz"]], [333])
        self.assertEqual([p["pid"] for p in s["diger"]], [444])

    def test_raporda_bekle_sureci_ve_claude_adlari_token_yok(self):
        liste = [(111, f'python X:/ajan/kutu.py bekle --kutu {self.eski} --kime claude')]
        ortam = {"CLAUDE_CODE_MESSAGING_SOCKET": r"\\.\pipe\LOCAL\cc-msg-x", "CLAUDE_CODE_MESSAGING_TOKEN": "GIZLI-TOKEN-9"}
        with mock.patch.dict(os.environ, ortam):
            calistir("claude-kaydet", "--ad", "ilk")
            calistir("claude-kaydet", "--ad", "ikinci")
        with mock.patch.object(kutu_gecis, "surec_listesi", return_value=liste):
            kod, cikti, hata = self.gk()
        self.assertEqual(kod, 0)
        self.assertIn("eski kutuda 1, yeni kutuda 0", cikti)
        self.assertIn("pid 111  [eski]", cikti)
        self.assertIn("ilk (", cikti)
        self.assertIn("ikinci (", cikti)
        self.assertIn("2 Claude kaydı var: gönderimde --claude-ad açıkça verilmeli", cikti)
        self.assertNotIn("GIZLI-TOKEN-9", cikti + hata)
        self.assertNotIn("cc-msg-x", cikti + hata)

    def test_surec_listesi_alinamazsa_uyari_cikis_0(self):
        with mock.patch.object(kutu_gecis, "surec_listesi", side_effect=RuntimeError("süreç listesi alınamadı: OSError")):
            kod, cikti, _ = self.gk()
        self.assertEqual(kod, 0)
        self.assertIn("UYARI: süreç listesi alınamadı", cikti)

    def test_json_cikti_gecerli_ve_anahtar_degeri_yok(self):
        kod, cikti, _ = self.gk("--json")
        self.assertEqual(kod, 0)
        rapor = json.loads(cikti)
        self.assertEqual(rapor["anahtar_adlari"], ["codex", "danisman"])
        self.assertEqual(rapor["sorunlar"], [])
        deger = (self.anahtar / "danisman.key").read_text(encoding="ascii").strip()
        self.assertNotIn(deger, cikti)
        self.assertNotIn("T-1", cikti)                      # codex_thread değeri rapora girmez

    def test_anahtar_dizini_verilmezse_yenin_yanindaki_kullanilir(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("KUTU_ANAHTAR_DIZIN", None)
            kod, cikti, _ = calistir("gecis-kontrol", "--eski", str(self.eski), "--yeni", str(self.yeni))
        self.assertEqual(kod, 0)
        self.assertIn("anahtar adları (değer basılmaz): codex, danisman", cikti)


if __name__ == "__main__":
    unittest.main()
