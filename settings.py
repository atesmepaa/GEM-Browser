import json
import os

from gem_browser.paths import config_path, secure_chmod

SETTINGS_FILE = config_path("gem_settings.json")


class BrowserSettings:
    def __init__(self):
        self.default_settings = {
            "ui_theme": "dark",
            "force_dark_web": False,
            "adblock_enabled": True,
            "js_enabled": True,
            "load_images": True,
            "search_suggestions": True,
            # Kapatılırsa QtWebEngine'in GPU sürecini devre dışı bırakan
            # Chromium bayrakları uygulanır (bkz. main.py). Zayıf/entegre
            # ekran kartlı sistemlerde RAM tüketimini belirgin şekilde
            # düşürür; güçlü ekran kartı olan kullanıcılarda KAPATILMASI
            # önerilmez (yazılımsal render daha yavaş olabilir). Bu yüzden
            # varsayılan AÇIK (True) — kullanıcı bilinçli olarak kapatmalı.
            # NOT: main.py bu değeri QApplication oluşturulmadan ÖNCE okur;
            # bu yüzden değişiklik ancak uygulama yeniden başlatılınca
            # etkili olur (window.py Ayarlar'da bunu kullanıcıya belirtir).
            "hardware_acceleration": True,
            "low_ram_mode": False,  # BÜTÜN BU OPTİMİZASYONLARI TETİKLEYECEK AYAR
            "language": "tr",
            # Boş string = "varsayılan" anlamına gelir (bkz. gem_browser/theme.py
            # get_accent_color). Kullanıcı Ayarlar'dan bir renk seçerse buraya
            # "#rrggbb" formatında yazılır; "Varsayılana Döndür" bu alanı
            # tekrar boşaltır.
            "accent_color": "",
            # Boş string = varsayılan gradyan arkaplan. Kullanıcı bir görsel
            # seçerse, görsel gem_browser config dizinine kopyalanır ve o
            # kopyanın tam yolu buraya yazılır (bkz. window.py
            # _pick_new_tab_background). "Varsayılana Döndür" bu alanı
            # tekrar boşaltır.
            "new_tab_background": "",
            # Sekme çubuğunu pencerenin solunda dikey liste olarak gösterir
            # (bkz. window.py _apply_tab_layout_mode / vertical sidebar).
            "vertical_tabs": False,
            # Açılışta önceki oturumdan kalan sekmeler bulunduğunda
            # (bkz. window.py _restore_session_or_new_tab):
            #   False (varsayılan) -> kullanıcıya "geri yüklensin mi?" diye
            #                         sorulur (mevcut/eski davranış).
            #   True               -> hiç sorulmadan sekmeler otomatik
            #                         olarak geri yüklenir.
            "auto_restore_tabs": False,
            "vpn_enabled": False,
            # Boş string = otomatik mod: "vpn_enabled" açıldığında sistemde
            # kurulu Tor ağına otomatik bağlanılır (bkz. gem_browser/tor_vpn.py
            # ve window.py:_apply_vpn — Brave/Opera'nın tek tıkla VPN'ine en
            # yakın ücretsiz ve gerçek eşdeğer). Kullanıcı burayı doldurursa
            # (ör. kendi VPN sağlayıcısının SOCKS5 adresi) Tor devre dışı
            # kalır ve doğrudan o adrese bağlanılır.
            "vpn_host": "",
            "vpn_port": 9050,
        }
        self.current = self.load()

    def load(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    merged = self.default_settings.copy()
                    merged.update(data)
                    return merged
            except Exception:
                return self.default_settings.copy()
        return self.default_settings.copy()

    def save(self):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.current, f, indent=4)
        secure_chmod(SETTINGS_FILE)
