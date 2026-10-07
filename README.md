# T-Voice

Windows için Türkçe ve İngilizce konuşmayı cihaz üzerinde yazıya çeviren masaüstü uygulaması.

## Özellikler

- Konuşmayı yerel Whisper modelleriyle çözümler; ses ve metin geçmişini uygulama olarak saklamaz.
- Sonucu kopyalar, metin dosyasına kaydeder veya istenirse etkin yazı alanına yazar.
- Her Windows kullanıcısı **Ayarlar → Kayıt kısayolu** bölümünden kendi genel kısayolunu seçebilir. F10 varsayılandır. Harf ve rakamlar Ctrl, Alt, Shift veya Windows tuşlarından en az biriyle kullanılabilir; tek başına F1–F24 tuşları da kullanılabilir.
- Tercihler Windows hesabına bağlı DPAPI korumasıyla yerel olarak saklanır. Kısayol ayarı depoya gönderilmez; arkadaşlarınız kendi kısayollarını belirler.

## Kaynaktan çalıştırma

Windows ve Python 3.12 gerekir. PowerShell'de:

```powershell
.\Kurulum.ps1
.\Baslat.cmd
```

Uygulama hazır paket olarak `dist\T-Voice` altında oluşturulabilir:

```powershell
.\Derle.ps1
```

İlk kurulum ve model indirme adımları için [README.txt](README.txt), kullanım ve gizlilik için [KULLANIM.html](KULLANIM.html) dosyasına bakın. Üçüncü taraf bağımlılıkların lisansları [THIRD_PARTY_LICENSES.txt](THIRD_PARTY_LICENSES.txt) ve `licenses/` klasöründedir.
