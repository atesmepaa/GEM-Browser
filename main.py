import os
import sys

# ÖNEMLİ: QTWEBENGINE_CHROMIUM_FLAGS, QApplication (dolayısıyla QtWebEngine)
# ilk kez initialize edilmeden ÖNCE ortam değişkeni olarak set edilmiş
# olmalı — bu yüzden bu blok, PyQt importlarından bile önce, dosyanın en
# başında duruyor. Kullanıcı Ayarlar'dan bu seçeneği sonradan değiştirirse
# (settings.py: "hardware_acceleration") etkisi ancak bir sonraki açılışta
# görülür; window.py bu durumu kullanıcıya "yeniden başlatma gerekiyor"
# şeklinde açıkça belirtir.
from gem_browser.settings import BrowserSettings

_startup_settings = BrowserSettings()
chromium_flags = []

# Donanım hızlandırma kapalıysa eklenecekler
if not _startup_settings.current.get("hardware_acceleration", True):
    chromium_flags.append("--disable-gpu --disable-gpu-compositing --disable-software-rasterizer")

# Düşük RAM Modu açıksa eklenecekler (Falkon Optimizasyonları)
if _startup_settings.current.get("low_ram_mode", False):
    falkon_flags = [
        "--disable-site-isolation-trials",
        "--enable-low-end-device-mode",
        "--process-per-site",
        "--renderer-process-limit=3",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--disable-extensions",
        "--disable-speech-api",
        "--disable-breakpad",
        "--disable-client-side-phishing-detection"
    ]
    chromium_flags.extend(falkon_flags)

# Eğer listemizde flag varsa bunları işletim sistemine bildir
if chromium_flags:
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(chromium_flags)

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication
from gem_browser.window import MainWindow, _active_windows
from gem_browser.router import resolve_url

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("GEM Browser")

    window = MainWindow()
    _active_windows.append(window)
    
    # EĞER DIŞARIDAN BİR URL İLE BAŞLATILDIYSA (Varsayılan tarayıcı olarak çalışıyorsa)
    if len(sys.argv) > 1:
        # sys.argv[1] genelde dışarıdan gönderilen linktir
        target_url = sys.argv[1]
        
        # MainWindow varsayılan olarak boş bir sekme açar, biz o sekmeyi dışarıdan 
        # gelen linke yönlendiriyoruz:
        tab = window.current_tab()
        if tab:
            tab.view.setUrl(resolve_url(target_url))

    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
