import os
import sys

# ÖNEMLİ: QTWEBENGINE_CHROMIUM_FLAGS, QApplication (dolayısıyla QtWebEngine)
# ilk kez initialize edilmeden ÖNCE ortam değişkeni olarak set edilmiş
# olmalı — bu yüzden bu blok, PyQt importlarından bile önce, dosyanın en
# başında duruyor. Kullanıcı Ayarlar'dan bu seçenekleri sonradan değiştirirse
# (settings.py: "hardware_acceleration", "low_ram_mode", VPN ayarları) etki
# ancak bir sonraki açılışta görülür; window.py bu durumu kullanıcıya
# "yeniden başlatma gerekiyor" şeklinde açıkça belirtir.
from gem_browser.settings import BrowserSettings
from gem_browser.paths import config_path

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

# VPN NOTU: QtWebEngine'de sayfa trafiği için QNetworkProxy KULLANILIR;
# window.py:_apply_vpn, Tor bağlandığında (veya manuel SOCKS5 girildiğinde)
# setApplicationProxy ile proxy'yi ÇALIŞMA ANINDA uygular — yeniden başlatma
# gerekmez. (Chromium'a --proxy-server bayrağı geçmek YANLIŞ olurdu: bayrak
# başlangıçta sabitlenir, VPN kapatıldığında geri alınamaz ve sayfalar ölü
# proxy'e takılırdı.)

# VPN/Tor etkinse WebRTC IP sızıntısını kapat: Chromium'un WebRTC
# ip-handling policy'sini "disable_non_proxied_udp"e sabitle — WebRTC,
# proxy'yi atlayarak doğrudan UDP üzerinden gerçek IP'yi sızdıramaz.
# (Bu bayrak ancak yeniden başlatmada etkin olur; çalışma anı anahtarı
# için window.py'deki WebRTCPublicInterfacesOnly özniteliğine bak.)
if _startup_settings.current.get("vpn_enabled", False):
    chromium_flags.append("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")

# --- Medya/GPU: TikTok tarzı medya-ağır siteler için ---
if _startup_settings.current.get("hardware_acceleration", True):
    # GPU rasterleştirme + zero-copy: kaydırma/video compositing'i GPU'ya
    # indirir; smooth scrolling ile birlikte akıcılığı artırır.
    chromium_flags.append("--enable-gpu-rasterization")
    chromium_flags.append("--enable-zero-copy")
    chromium_flags.append("--enable-smooth-scrolling")
    # Videolar tıklama beklemeden otomatik oynasın (TikTok/Instagram akışları)
    chromium_flags.append("--autoplay-policy=no-user-gesture-required")
    # Bilinen renderer çökmesi hafifletmesi: /dev/shm dolu olduğu durumda
    # paylaşılan bellek segmenti çökmelere yol açabiliyor.
    chromium_flags.append("--disable-dev-shm-usage")

# --- DRM (Widevine): CDM varsa QtWebEngine'e bildir ---
def _find_widevine_cdm():
    """Sistemdeki olası Widevine CDM kütüphanelerini tarar (Chrome/Chromium
    standart konumları + uygulama yapılandırma dizini). Bulunursa yol,
    bulunamazsa None döner."""
    import glob
    patterns = (
        "/usr/lib/chromium/libwidevinecdm.so",
        "/usr/lib/chromium-browser/libwidevinecdm.so",
        "/opt/google/chrome/libwidevinecdm.so",
        "/usr/lib/qt6/libexec/libwidevinecdm.so",
        "/usr/lib/widevine/libwidevinecdm.so",
        os.path.join(config_path("widevine"), "libwidevinecdm.so"),
    )
    for pattern in patterns:
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[0]
    return None

_widevine_cdm = _find_widevine_cdm()
if _widevine_cdm:
    # CDM kütüphanesinin bulunduğu dizini Chromium'a bildir — QtWebEngine
    # Widevine'ı buradan yükler (DRM içerik: Netflix/Spotify/Disney+ tarzı).
    chromium_flags.append(f"--widevine-path={os.path.dirname(_widevine_cdm)}")

# Eğer listemizde flag varsa bunları işletim sistemine bildir
if chromium_flags:
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(chromium_flags)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from gem_browser.window import MainWindow, _active_windows
from gem_browser.router import resolve_url

# Tek örnek (single instance) anahtarı: varsayılan tarayıcı olarak çalışırken
# her dış bağlantı tıklaması yeni bir process başlatıyordu; ikinci örnek hem
# aynı QtWebEngine profil dizinine erişip Chromium profil kilidi sorunlarına
# yol açıyor hem de gereksiz yere "oturum geri yüklensin mi?" soruyordu.
# Artık ikinci örnek, URL'yi çalışan örneğe iletip sessizce kapanır.
_INSTANCE_KEY = "gem_browser_single_instance"


def _forward_to_running_instance(url_text: str) -> bool:
    """Çalışan bir GEM Browser örneği varsa URL'yi ona iletir; True dönerse
    bu süreç hiç pencere açmadan çıkmalıdır."""
    sock = QLocalSocket()
    sock.connectToServer(_INSTANCE_KEY)
    if not sock.waitForConnected(300):
        return False
    sock.write((url_text or "").encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    if sock.state() == QLocalSocket.LocalSocketState.ConnectedState:
        sock.waitForDisconnected(300)
    return True


def _start_instance_server(app: QApplication) -> None:
    """Bu süreç 'birincil' örnek olarak dinlemeye başlar; sonraki örneklerden
    gelen URL'ler son pencerede yeni sekme olarak açılır."""
    server = QLocalServer()
    QLocalServer.removeServer(_INSTANCE_KEY)  # çökmüş örneğin artığı varsa temizle
    if not server.listen(_INSTANCE_KEY):
        return
    buffers = {}

    def _handle_message(text: str):
        windows = list(_active_windows)
        win = windows[-1] if windows else None
        if win is None:
            return
        if text:
            win.add_new_tab(resolve_url(text))
        win.show()
        win.raise_()
        win.activateWindow()

    def _on_new_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return
        buffers[conn] = bytearray()

        def _ready_read(c=conn):
            buffers[c].extend(bytes(c.readAll()))

        def _on_disconnected(c=conn):
            text = bytes(buffers.pop(c, bytearray())).decode("utf-8", errors="ignore").strip()
            c.deleteLater()
            _handle_message(text)

        conn.readyRead.connect(_ready_read)
        conn.disconnected.connect(_on_disconnected)

    server.newConnection.connect(_on_new_connection)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("GEM Browser")
    app.setDesktopFileName("gem-browser")

    # EĞER DIŞARIDAN BİR URL İLE BAŞLATILDIYSA (Varsayılan tarayıcı olarak çalışıyorsa)
    target_url = sys.argv[1] if len(sys.argv) > 1 else ""

    # Zaten çalışan bir örnek varsa: URL'yi ona devret ve çık.
    if _forward_to_running_instance(target_url):
        sys.exit(0)

    _start_instance_server(app)

    window = MainWindow()
    _active_windows.append(window)

    # MainWindow varsayılan olarak boş bir sekme açar, biz o sekmeyi dışarıdan
    # gelen linke yönlendiriyoruz:
    if target_url:
        tab = window.current_tab()
        if tab is not None and getattr(tab, "view", None) is not None:
            tab.view.setUrl(resolve_url(target_url))

    # Kullanıcı son kapatışta maksimize bıraktıysa tam ekran boyutunda
    # (maximized) aç; aksi halde kayıtlı normal pencere boyutu zaten
    # __init__ içinde uygulanır. Kayıt yoksa normal pencere (tam ekran DEĞİL).
    if window.settings.current.get("win_maximized", False):
        window.showMaximized()
    else:
        window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
