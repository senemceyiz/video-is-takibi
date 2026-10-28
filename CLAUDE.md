# Video İş Takibi — proje notları

## Kullanıcı ve amaç
- Kullanıcı yazılımcı değil. Açıklamalar **sade Türkçe**, teknik terimler kısaca açıklanır, her adımda çalışan bir şey gösterilir.
- Amaç: uluslararası (İngilizce) pazarda uzaktan video düzenleme işleriyle ek gelir.
- Kullanıcı **şu an video düzenlemiyor**. İlan takibi ilk aşamada başvuru için değil, pazarı tanımak ve öğrenme planını beslemek için.
- Bu depo **herkese açıktır**; buraya kişisel bilgi yazılmaz. Bu proje kullanıcının diğer projelerinden bağımsızdır; başka proje klasörlerine dokunulmaz.

## Kesin kurallar
- Asistan kullanıcı adına **başvuru göndermez, hesap açmaz, şifre girmez**; yalnızca taslak hazırlar. Başvuruyu kullanıcı kendisi gönderir.
- Giriş gerektiren sitelere (Upwork, LinkedIn, Fiverr vb.) girilmez, kazınmaz.
- Kaynakların kullanım koşullarına uyulur:
  - Remote OK ve Remotive: her ilan kendi sayfasına bağlanır, kaynak adı yazılır. Remotive günde en çok 4 istek önerir.
  - Reddit: yalnızca herkese açık RSS, açıklayıcı User-Agent, seyrek istek (kaynaklar arası bekleme var).
- Daha önce görülen ilan tekrar gösterilmez (`data/goruldu.json`).

## Yol haritası
1. **Pazar keşfi** (şu an burada): bulutta günlük tarama, haftalık özet sayfası, iyi giriş seviyesi ilanda telefona bildirim.
2. **Öğrenme planı:** verilere göre ücretsiz program (DaVinci Resolve ya da CapCut) ve 4–6 haftalık, haftalık görevli plan.
3. **Portfolyo:** telifsiz görüntülerle 3–5 örnek iş.
4. **Başvuru dönemi:** uygun ilanlar + her biri için kullanıcıya göre başvuru taslakları.

## Dosyalar
- `tara.py` — tarayıcı. Yalnızca Python standart kütüphanesi (ek kurulum yok). `python tara.py`
  - Kaynaklar: Remote OK API, We Work Remotely RSS, Remotive API, Himalayas API, Reddit r/forhire ([Hiring] + video) ve r/VideoEditingRequests RSS.
  - Reddit'te kendi hizmetini sunanlar, ücretsiz/karşılıksız istekler ve sorular elenir.
  - Her ilana iş türü, program, ücret ve "giriş puanı" verilir. `giris_uygun` = puan ≥ 3 ve konum Türkiye'ye açık (boş/Worldwide/Europe vb.).
  - Bir kaynak hata verirse diğerleri devam eder; hata rapor sayfasında "Tarama durumu" bölümünde görünür.
- `data/ilanlar.jsonl` — her satır bir ilan (ilk görülme tarihiyle). `data/goruldu.json` — görülen ilan kimlikleri.
- `rapor/index.html` — son 7 günün özet sayfası (iş türleri, programlar, ücret aralıkları, yeni başlayana uygunlar).
- Telefon bildirimi: `NTFY_KONU` ortam değişkeni ayarlıysa ntfy.sh üzerinden gönderilir (hesap gerekmez; telefona ntfy uygulaması kurulup aynı konuya abone olunur). İlk taramada bildirim atılmaz.

## Bulut kurulumu
- `.github/workflows/tara.yml`: GitHub Actions her gün 06:00 UTC'de (09:00 TR) `tara.py`'yi çalıştırır, `data/` ve `rapor/` değişikliklerini depoya kaydeder, `rapor/` klasörünü GitHub Pages'te yayınlar. Depodaki "Actions" sekmesinden "Run workflow" ile elle de çalıştırılabilir.
- Gerekli ayarlar (kullanıcı GitHub'da kendisi yapar): Settings → Pages → Source: "GitHub Actions"; Settings → Secrets and variables → Actions → `NTFY_KONU` gizli değeri.
- Bilgisayarda `gh` yok; GitHub'a gönderme Git Credential Manager ile (tarayıcıda kullanıcı kendisi giriş yapar).
- Claude kullanımı harcamaz. Yorum gerektiren haftalık analiz/öğrenme planı güncellemesi için ileride bir Claude routine eklenebilir.
- GitHub, 60 gün hiç etkinlik olmayan depolarda zamanlanmış görevi kapatabilir; günlük kayıtlar bunu genelde önler. Kapanırsa Actions sekmesinden yeniden açılır.
- Bilinen risk: Reddit, bulut sunucularından gelen istekleri sık engeller (403/429). Engellenirse Reddit kaynakları rapor sayfasında hata olarak görünür; diğer kaynaklar çalışmaya devam eder.

## Bilinen sınırlamalar
- Ücretler ilan metninden kaba kurallarla çıkarılır; kesin değildir.
- Himalayas ilanlarının çoğu belirli ülkelere kısıtlı (Filipinler, ABD vb.); bunlar istatistiğe girer ama "uygun" sayılmaz.
