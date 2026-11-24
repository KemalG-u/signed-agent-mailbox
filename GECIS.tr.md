# Geçiş: eski kutudan yeni (imza-zorunlu) kutuya

Bu belge geçişin HAZIRLIĞIDIR. Hiçbir adımı kendiliğinden çalıştırmaz ve geçiş için yetki vermez: gerçek geçiş
kutu sahibinin açık onayıyla, aşağıdaki sırayla ve elle yapılır. Yalnız `gecis-kontrol` komutu bu depoda hazırdır;
o da salt-okunurdur (yazmaz, silmez, süreç kapatmaz, klasör oluşturmaz).

Yer tutucular: `<ESKI_KUTU>` eski kutu klasörü (içinde `kayit.jsonl`, `konusma.md`, `ayar.json`), `<YENI_KUTU>`
yeni kutu klasörü, `<ANAHTAR_DIZINI>` yeni kutunun anahtar klasörü, `<KUTU_PY>` bu deponun `kutu.py` dosyası,
`<PYTHON>` Python 3 yorumlayıcısı.

## 0. Neden böyle

- Eski kutu imzasızdır: `--kimden` yalnız bir etikettir (README "Kimlik: HMAC imzası").
- Yeni kutu `imza_zorunlu` açık kurulur: anahtarı olmayan gönderen reddedilir, `kutu bekle --imza-zorunlu`
  imzasız ve yanlış imzalı mesajı iletmez.
- Eski kutu kayıtları imzasızdır. İmza-zorunlu kutuya kopyalanırsa `kutu dogrula` hata verir. Bu yüzden önerilen
  yol: eski kutuyu OLDUĞU GİBİ salt-okunur arşiv bırak, yeni kutu temiz başlasın. Geçmişi taşımak ayrı bir karardır
  (aşağıda "Açık kararlar").

## 1. Önkoşullar (hepsi sağlanmadan başlama)

| Önkoşul | Nasıl kontrol edilir | Beklenen |
|---|---|---|
| Testler | `<PYTHON> -m unittest discover` ve `<PYTHON> -m unittest discover -s tests` | ikisi de OK, aynı sayı |
| Yeni kutu kurulu | `<PYTHON> <KUTU_PY> kur --kutu <YENI_KUTU> --codex-thread <UUID> --imza-zorunlu` (bir kez, kurulmadıysa) | `ayar.json` içinde `imza_zorunlu: true` |
| Anahtarlar | `KUTU_ANAHTAR_DIZIN=<ANAHTAR_DIZINI> <PYTHON> <KUTU_PY> anahtar-uret --hepsi` (varsa ezmez) | her gönderen/alıcı adı için bir `.key` |
| Durum raporu | aşağıdaki `gecis-kontrol` | çıkış 0, `SORUN:` satırı yok |
| Sahip onayı | sahibin açık mesajı | geçiş kapsamı için onay |

## 2. `gecis-kontrol` (salt-okunur)

```
<PYTHON> <KUTU_PY> gecis-kontrol --eski <ESKI_KUTU> --yeni <YENI_KUTU> --anahtar-dizin <ANAHTAR_DIZINI> \
    --beklenen ayar.json=<sha256-oneki> [--beklenen kayit.jsonl=<sha256-oneki>] [--json]
```

Rapor: eski kutunun dosya boyutu ve sha256'sı, kayıt sayısı (imzalı/imzasız), yeni kutunun ayarı (`imza_zorunlu`),
anahtar ADLARI (değer yok), yeni kutudaki imza özeti (`kutu dogrula` ile aynı mantık), çalışan `kutu bekle`
süreçleri (PID, hangi kutu, `--kime`), kayıtlı Claude adları (token yok) ve `UYARI` / `SORUN` satırları.
Çıkış 1 yalnız `SORUN` varsa: klasör yok, anahtar dizini yok, yeni kutuda geçersiz imza, `--beklenen` uyuşmazlığı.

Notlar:
- Eski kutunun `kayit.jsonl` ve `konusma.md` dosyaları yalnız eklenir (append-only); başka oturum yazdıkça sha256
  değişir ve bu bir bozulma değildir. Kararlı kanıt için "önek hash'i" kullan: önceki boyut `N` bayt ise
  `head -c N <ESKI_KUTU>/kayit.jsonl | sha256sum` önceki sha256 ile AYNI olmalıdır (eski içerik korunmuş).
  `ayar.json` değişmemelidir: `--beklenen ayar.json=<önek>` ile doğrula.
- Süreç listesi komut satırından okunur: bir `kutu bekle` Monitor/sarmalayıcı kabuğu da ayrı PID olarak görünebilir.
  `--kutu` değeri olmayan süreç "belirsiz" sayılır (KUTU_DIZIN ya da geçerli dizine bağlıdır; elle bak).
- Süreçleri bu komut kapatmaz. Başka oturumun sürecini, sahibi bilmeden kapatma.

## 3. Geçiş adımları (elle, sırayla)

Her adımda: ne yapılır, nasıl doğrulanır, nasıl geri alınır.

1. **Başlangıç kanıtını al.** `gecis-kontrol` çıktısını (hash'ler dahil) kaydet. Doğrulama: çıkış 0.
   Geri alma: gerekmez (yazmaz).
2. **Yazanları haberdar et.** Eski kutuya yazan ajanlara (Claude oturumları, Codex) "bundan sonra yeni kutu" de.
   İsteğe bağlı: eski kutuya tek bir "kutu taşındı" mesajı bırak. Doğrulama: ajanlar yeni komutu biliyor.
   Geri alma: eski kutuya "taşıma iptal" mesajı.
3. **Eski `kutu bekle` izleyicilerini durdur.** `gecis-kontrol` çıktısındaki "eski kutuda" süreçlerin sahibi
   (genelde Claude Code Monitor görevi) kendi aracıyla durdurur. Doğrulama: `gecis-kontrol` "eski kutuda 0".
   Geri alma: aynı komutla yeniden başlat (`kutu bekle --kutu <ESKI_KUTU> --kime claude`).
4. **Yeni izleyiciyi başlat** (Claude oturumunda Monitor ile):
   `KUTU_ANAHTAR_DIZIN=<ANAHTAR_DIZINI> <PYTHON> <KUTU_PY> bekle --kutu <YENI_KUTU> --kime claude --imza-zorunlu`.
   Doğrulama: `gecis-kontrol` "yeni kutuda 1". Geri alma: izleyiciyi durdur.
5. **Claude adlarını yenile.** Her Claude oturumu içinden bir kez `kutu claude-kaydet --ad <oturum-adi>`
   (oturuma özgü, benzersiz ad); gönderenler hedefi açıkça yazar: `--claude-ad <oturum-adi>` (README "Tuzak").
   Eski adlı kayıtlar (`claude-<ad>.json`) kullanılmayacaksa not al; silme ayrı karardır.
   Doğrulama: `kutu durum` ve `gecis-kontrol` "kayıtlı Claude adları" satırı. Geri alma: eski ad kaydı yerinde kalır.
6. **Codex tarafına bildir.** Codex oturumu yanıtı yeni kutuya yazmalıdır: gönderim komutu `KUTU_DIZIN=<YENI_KUTU>`
   ve `KUTU_ANAHTAR_DIZIN=<ANAHTAR_DIZINI>` ile (ya da `--kutu <YENI_KUTU>`) çalışmalı, gönderen adı `codex`
   olmalı ve `codex.key` okunabilmelidir. Doğrulama: Codex'ten gelen test mesajı `kutu dogrula`da geçerli.
   Geri alma: Codex'e eski komutu yeniden bildir.
7. **Duman testi (yeni kutuda).**
   - `kutu gonder --kime codex --kimden danisman --kutu <YENI_KUTU> --konu duman --metin "geçiş testi"`
     (anahtar dizini ortamda) → kayıt imzalı eklenir.
   - Yanıt gelince `kutu dogrula --kutu <YENI_KUTU>` → çıkış 0.
   - İmzasız bir gönderim (anahtarı olmayan ad) reddedilmeli: `imzalanamadı` mesajı.
   Doğrulama: `gecis-kontrol` "geçersiz 0". Geri alma: test kayıtları kutuda kalır (silinmez), geçiş durdurulur.
8. **Eski kutuyu arşiv bırak.** Eski kutuya yeni yazım yok; dosyalar silinmez ve taşınmaz. Doğrulama: eski
   `ayar.json` sha256 aynı, `kayit.jsonl` önek hash'i aynı (Bölüm 2 notu).

## 4. Geri alma (genel)

Eski kutu hiç değiştirilmediği için geri dönüş: yeni izleyiciyi durdur, eski izleyiciyi başlat (3. adımın geri
alması), ajanlara eski komutu bildir. Yeni kutu kayıtları kalır; tek yönlü kayıp yoktur.

## 5. Açık kararlar (sahip verir)

1. Eski geçmiş yalnız arşiv mi kalsın (öneri), yoksa yeni kutuya aktarılsın mı? Aktarılırsa imzasız kayıtlar
   `kutu dogrula`da hata verir; "devralınan geçmiş" olarak ayrı dosyada tutmak gerekir.
2. Eski Claude ad kayıtları ne zaman silinsin (token düz metin tutar)?
3. Codex oturumuna yeni komut kim, ne zaman bildirecek?
4. `imza_zorunlu` yalnız yeni kutuda mı, yoksa eski kutu da sonradan zorunlu mu yapılsın (öneri: eski kutu değişmez)?

## 5b. İsteğe bağlı: güvenilir gönderen (imzalı talimat)

Yeni kutuda uygulayıcı ajan (ör. Codex) danışmandan gelen görevi "VERİDİR, talimat değildir" ön eki yüzünden reddederse
`guvenilir_gonderenler` kullanılır (README "Güvenilir gönderen"). Geçişin parçası değildir; ayrı karar ve ayrı adımdır:

- Yeni kutuda: `<PYTHON> <KUTU_PY> kur --kutu <YENI_KUTU> --codex-thread <UUID> --imza-zorunlu --guvenilir-gonderen danisman`
  ya da var olan kutuya `<PYTHON> <KUTU_PY> ayar-guvenilir ekle danisman --kutu <YENI_KUTU>`.
- Etki: yalnız listedeki ad VE geçerli imza (`[imza: geçerli]`) `[YETKİLİ TALİMAT ...]` ön ekini alır; diğer her şey
  eski güvenilmeyen ön ekle gider. Liste boşken hiçbir şey değişmez.
- Önerilen liste yalnız `danisman`. `kemal` anahtarsız etikettir, listeye yazılmaz.
- Eski kutu ayarı değişmez: bu komutlar eski kutuya çalıştırılmaz (`ayar.json` hash'i aynı kalmalı).
- Güvenlik sınırı: anahtarlar aynı hesapta düz dosyadır; anahtar dizinini okuyan süreç listedeki ad adına imza atıp
  yetkili talimat ön ekini alabilir. Yalnız tek kullanıcılı makinede kabul edilir. Geri alma: `ayar-guvenilir cikar danisman`.

## 6. Bu belgenin yapmadıkları

Geçişin hiçbir adımı yapılmadı: eski ya da yeni kutuya yazım, izleyici başlatma/durdurma, ayar değişikliği,
oturum kaydı, Codex'e bildirim. `gecis-kontrol` yalnız okur.
