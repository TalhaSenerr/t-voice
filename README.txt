T-VOICE 1.2 — Windows için çevrimdışı dikte
========================================

Fn + F10 → KONUŞ → Fn + F10
1. Masaüstündeki T-Voice kısayolunu bir kez aç.
2. Yazmak istediğin uygulamadaki metin alanına tıkla.
3. Fn + F10'a bas, konuş. Bitince tekrar Fn + F10'a bas.
4. Çözümleme tamamlandığında metin seçtiğin alana yazılır.

Etkin alana yazma yeni kurulumda ve önceki sürümden ilk geçişte açıktır.
İstersen Ayarlar'dan kapatabilirsin; sonraki açılışlarda tercihin korunur.
Sonuç gelene kadar hedef alanı değiştirme. Uygulama içindeki kayıt düğmesiyle
başlayan kayıtlarda sonuç önce T-Voice içinde gösterilir.

Huawei: Fn ışığı kapalı olmalı. Fn kilidi açıkken doğrudan F10 çalışabilir.
Fn + F10 başka bir Huawei işlevini açıyorsa Fn ışığını kapat veya Huawei PC
Yöneticisi > Ayarlar > Erişilebilirlik/Sistem ayarları bölümünden
Kısayol tuşlarına öncelik ver seçeneğini kullan. Klavye bu durumda Fn + F10'u
Windows'a F10 olarak iletir. Fn, uygulamada ayrı bir değiştirici olarak
algılanmaz; fiziksel tuş birleşimi bu bilgisayarda kullanıcıyla doğrulanmalıdır.

Pencerenin X düğmesi uygulamayı bildirim alanına küçültür; Fn + F10 çalışmaya devam
eder. Kayıt sırasında X'e basarsan o kayıt iptal edilir.
Tamamen kapatmak için saatin yanındaki T-Voice simgesine sağ tıkla ve
Çıkış'ı seç. Pencereyi yeniden göstermek için tepsideki simgeye tıkla.
Çıkış yaptıktan sonra masaüstü kısayolundan yeniden başlatabilirsin.
Fn + F10 için T-Voice'un çalışıyor olması gerekir. Başka uygulama F10'u kullanıyorsa
durum mesajını kontrol et ve kayıt düğmesini kullan.

HIZ VE DOĞRULUK
• Açılışta seçili yerel model hazırlanır; mikrofon yalnızca kayıt başlatınca açılır.
• Türkçe + İngilizce varsayılandır. Önerilen model, Intel ekran kartında çalışan
  OpenVINO Whisper large-v3-turbo INT8'dir. Daha az bellek isteyen kullanım
  için Small seçilebilir. Turbo'nun doğruluğu
  her konuşmada garanti değildir; hız donanıma ve kayıt uzunluğuna bağlıdır.
  Gerçek ölçümler ve sınırları TEST-SONUCLARI.txt içindedir.
• Sessiz kayıtlar elenir; konuşma varsa kaydın tamamı modele verilir.
  Böylece Türkçe içinde söylenen İngilizce kelimeler ses parçalama sırasında
  kesilmez. Sözlük yine özel isimler ve tercih edilen yazımlar için kullanılabilir.
• GPU modeli ilk kullanımda hazırlanırken sonraki açılışları hızlandırmak için
  %LOCALAPPDATA%\T-Voice\cache\openvino konumunda model önbelleği oluşturulur.
  Bu önbellek derlenmiş model dosyalarıdır; ses/metin geçmişi değildir.
  GPU modeli açılamazsa Ayarlar'dan Small seçilebilir.
• Metin kayıt bittikten sonra oluşur; bu sürümde canlı akan metin yoktur.
• “Eee”, “hmm”, “umm” gibi dolgu sesleri temizlenir. “Şey”, “yani”, “like” ve
  “well” gibi anlamlı olabilen kelimeler otomatik silinmez.
• Yabancı terimler için sözlüğe tercih edilen yazımı ve alternatifleri ekle:
  GitHub / git hap, git hub. Değişiklik sonraki çözümlemede uygulanır.
• Gerekirse ham metni incele, sonucu düzenle, kopyala veya .txt kaydet.
• Kayıt/dosya çözümlemesi en fazla 10 dakika; ses dosyası en fazla 150 MB.

YAZMA DAVRANIŞI
Otomatik yazma, Fn + F10 ile başlatılan kayıtlarda kullanılır. Aynı pencere içindeki
alan değişimleri her zaman izlenemez. Yönetici yetkili bazı uygulamalar girişi
reddedebilir. Metin hedefe yazılamazsa sonucu T-Voice'tan alabilirsin.

GİZLİLİK
Konuşma cihazda, RAM içinde çözümlenir; ses/metin geçmişi oluşturulmaz.
Uygulama sesi buluta göndermez, kullanım analitiği toplamaz. ONNX Runtime
telemetrisi API ile kapatılır; Windows bu çağrıdan önce başlangıç ETW tanı
olayları kaydedebilir. Bu olaylar işletim sisteminin denetimindedir.
Ayarlar ve sözlük Windows hesabına bağlı DPAPI şifrelemesiyle saklanır:
  %LOCALAPPDATA%\T-Voice\preferences.dpapi
Eski Duru tercihleri varsa ilk açılışta taşınır; eski dosya korunur.
Kopyalanan metin Windows panosuna gider; pano geçmişi/eşitlemesi metni
saklayabilir veya aktarabilir. Kaydettiğin .txt dosyası ayrıca şifrelenmez.
İşletim sistemi takas/çökme dosyaları, zararlı yazılım ve aynı hesaba erişim bu
korumanın dışındadır. %100 güvenlik veya kusursuz tanıma garantisi yoktur.

TAŞIMA VE KAYNAKTAN ÇALIŞTIRMA
Hazır paket Python kurulumu gerektirmez. dist\T-Voice klasörünü bütün olarak
koru; T-Voice.exe tek başına yeterli değildir. OpenVINO Whisper Turbo ve Small
yerel modelleri paket içindedir. GPU modeli Intel grafik sürücüsünü kullanır.
Kaynak klasöründeki Baslat.cmd de hazır paketi, yoksa yerel Python'u başlatır.
Geliştirici ortamı için uv kurulu PowerShell'de:
  .\Kurulum.ps1
  .\Baslat.cmd
Kurulum bağımlılıkları indirirken internet kullanır. Paket oluşturmak için
  .\Derle.ps1
Kaynak uygulama kodu uyumluluk için duru\ paketinde tutulur.

Hazır pakette model indirmene gerek yoktur. Ayrı bir kaynak kurulumu için
isteğe bağlı model indirme komutu:
  .\.venv\Scripts\python.exe scripts\install_model.py turbo-ov
Aynı komutta small veya medium da kullanılabilir. Bu ayrı kurulum işlemi yalnızca model
indirir; uygulama kullanım sırasında eksik modeli kendiliğinden indirmez.

KAYNAKLAR VE SINIRLAR
Kişisel uygulama kaynaklarını değiştirebilir ve geliştirebilirsin. Kütüphane
ve modellerin kendi lisansları geçerlidir: THIRD_PARTY_LICENSES.txt.
Bu kişisel Windows paketi imzasızdır. Kendi mikrofonunla doğruluk ve VoiceInk'e
karşı hız/doğruluk üstünlüğü ölçülmüş değildir.

Huawei Fn tuşu açıklaması:
  https://consumer.huawei.com/tr/support/content/tr-tr00729419/
Windows genel kısayol API'si:
  https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey

KULLANIM.html       Kullanım ve gizlilik kılavuzu
PLAN.txt           Sürüm kapsamı ve geliştirme notları
TEST-SONUCLARI.txt  Gerçek doğrulama sonuçları ve sınırları

KİŞİSEL KISAYOL
Ayarlar > Kayıt kısayolu alanından her Windows kullanıcısı kendi genel
kısayolunu seçebilir. Bir tuşla yalnızca F1–F24; harf ve rakamlarla Ctrl,
Alt, Shift veya Windows değiştiricilerinden en az biri kullanılır. Örneğin
Ctrl + Alt + F10. Ayar Windows hesabına bağlı şifreli tercihlerde saklanır;
bu nedenle aynı depoyu kullanan arkadaşlar kendi tuşlarını ayrı seçebilir.
