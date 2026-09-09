"""
GEM Browser'ı varsayılan web tarayıcısı olarak ayarlar. Linux (XDG uyumlu
masaüstleri) ve Windows (10/11) ayrı ayrı desteklenir; macOS şu an
desteklenmiyor (proje zaten "Linux odaklı" olarak tasarlandı, Windows
desteği ek olarak istendiği için eklendi).

ÖNEMLİ — kullanıcı onayı: Bu modüldeki fonksiyonlar HİÇBİR ZAMAN kendiliğinden
çağrılmaz; yalnızca kullanıcı menüden "Varsayılan Tarayıcı Yap" deyip
window.py'deki onay penceresinde "Evet" dedikten SONRA çalıştırılır.

Linux: kullanıcının uygulama dizinine (~/.local/share/applications) bir
.desktop dosyası yazılır; `xdg-mime` ile http/https şema işleyicisi,
`xdg-settings` ile de "varsayılan tarayıcı" olarak bu dosya kaydedilir. Bu
işlem tamamen sessiz/otomatik yapılabilir.

Windows: Windows 8'den beri hiçbir uygulama kendini SESSİZCE varsayılan
yapamaz (bu, tarayıcı ele geçirme/hijacking saldırılarını önlemek için
Microsoft'un bilinçli bir güvenlik kararı). Yapılabilecek en fazla şey:
uygulamayı Windows'un "Varsayılan Uygulamalar" listesinde bir aday olarak
kayıt (registry) etmek, ardından o ekranı otomatik açmaktır — son seçimi
kullanıcının kendisinin tıklaması gerekir. Bu yüzden Windows'ta
`set_as_default_browser()` başarıyla dönse bile GEM Browser'ın gerçekten
varsayılan olması, kullanıcının açılan pencerede onu seçmesine bağlıdır.
"""

import os
import shutil
import subprocess
import sys

APP_NAME = "GEM Browser"

# --------------------------------------------------------------- ortak ----

class DefaultBrowserError(Exception):
    """Varsayılan tarayıcı ayarlanamadığında (platform desteklenmiyor, araç
    eksik, komut başarısız oldu vb.) fırlatılır. Çağıran taraf (window.py)
    bunu kullanıcıya açık bir mesajla gösterir — sessizce yutulmaz."""
    pass


def _resolve_icon_path() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(current_dir, "logo.png")
    return icon_path if os.path.exists(icon_path) else ""


def set_as_default_browser() -> None:
    """Platforma göre doğru uygulamayı çağırır. Desteklenmeyen platformda
    (ör. macOS) DefaultBrowserError fırlatır."""
    if sys.platform.startswith("linux"):
        _linux_set_default_browser()
    elif sys.platform.startswith("win"):
        _windows_set_default_browser()
    else:
        raise DefaultBrowserError(
            "Bu özellik şu an yalnızca Windows ve Linux'ta destekleniyor."
        )


def is_default_browser() -> bool:
    """Mevcut durumu (varsa) sorgular; belirlenemezse False döner. Bir hata
    göstermek için değil, sadece bilgi amaçlı (menüde durum göstermek gibi)
    kullanılmak üzere var — istisna fırlatmaz."""
    try:
        if sys.platform.startswith("linux"):
            return _linux_is_default_browser()
        elif sys.platform.startswith("win"):
            return _windows_is_default_browser()
    except Exception:
        pass
    return False


# -------------------------------------------------------------- linux -----

_DESKTOP_FILE_ID = "gem-browser.desktop"
_LINUX_APP_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "applications")
_LINUX_DESKTOP_FILE_PATH = os.path.join(_LINUX_APP_DIR, _DESKTOP_FILE_ID)

_LINUX_MIME_TYPES = (
    "text/html",
    "text/xml",
    "application/xhtml+xml",
    "x-scheme-handler/http",
    "x-scheme-handler/https",
)


def _linux_resolve_launch_command() -> str:
    # Paketlenmiş (ör. RPM ile kurulmuş) bir kurulumda PATH üzerinde
    # doğrudan "gem-browser" adlı bir çalıştırılabilir bulunur (bkz.
    # pyproject.toml [project.scripts]) — bu durumda Exec satırı doğrudan
    # onu kullanmalı. Paketlenmemiş/geliştirme ortamında (proje kaynak
    # koddan `python main.py` ile çalıştırılıyorsa) ise Exec komutu, o an
    # çalışan Python yorumlayıcısı + betik yoluna göre üretilir.
    installed = shutil.which("gem-browser")
    if installed:
        return f'"{installed}" %u'

    exe = sys.executable
    script = os.path.abspath(sys.argv[0])
    return f'"{exe}" "{script}" %u'


def _linux_write_desktop_file() -> None:
    os.makedirs(_LINUX_APP_DIR, exist_ok=True)
    icon = _resolve_icon_path() or "web-browser"
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Exec={_linux_resolve_launch_command()}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Network;WebBrowser;\n"
        f"MimeType={';'.join(_LINUX_MIME_TYPES)};\n"
    )
    with open(_LINUX_DESKTOP_FILE_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        os.chmod(_LINUX_DESKTOP_FILE_PATH, 0o755)
    except Exception:
        pass


def _linux_set_default_browser() -> None:
    if shutil.which("xdg-settings") is None or shutil.which("xdg-mime") is None:
        raise DefaultBrowserError(
            "xdg-utils bulunamadı (xdg-settings / xdg-mime komutları). "
            "Dağıtımınızın paket yöneticisiyle 'xdg-utils' paketini kurup "
            "tekrar deneyin."
        )

    _linux_write_desktop_file()

    commands = [
        ["xdg-mime", "default", _DESKTOP_FILE_ID, "x-scheme-handler/http"],
        ["xdg-mime", "default", _DESKTOP_FILE_ID, "x-scheme-handler/https"],
        ["xdg-settings", "set", "default-web-browser", _DESKTOP_FILE_ID],
    ]
    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except Exception as exc:
            raise DefaultBrowserError(f"'{' '.join(cmd)}' çalıştırılamadı: {exc}")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise DefaultBrowserError(f"'{' '.join(cmd)}' başarısız oldu: {detail}")


def _linux_is_default_browser() -> bool:
    if shutil.which("xdg-settings") is None:
        return False
    result = subprocess.run(
        ["xdg-settings", "get", "default-web-browser"],
        capture_output=True, text=True, timeout=5,
    )
    return result.returncode == 0 and result.stdout.strip() == _DESKTOP_FILE_ID


# ------------------------------------------------------------- windows ----

_WIN_PROG_ID = "GEMBrowserHTML"
_WIN_START_MENU_KEY = r"Software\Clients\StartMenuInternet\GEMBrowser"


def _windows_resolve_command() -> str:
    exe = sys.executable
    script = os.path.abspath(sys.argv[0])
    return f'"{exe}" "{script}" "%1"'


def _windows_register() -> None:
    """
    Windows'un "Varsayılan Uygulamalar" ekranında GEM Browser'ı bir aday
    olarak listelemesi için gereken standart registry yapısı. Sadece
    HKEY_CURRENT_USER altına yazılır — yönetici izni gerektirmez.
    """
    import winreg  # yalnızca Windows'ta mevcut

    command = _windows_resolve_command()
    icon = _resolve_icon_path()
    icon_value = f"{icon},0" if icon else f'"{sys.executable}",0'

    def _set(path: str, name, value: str):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    # 1) ProgID: http(s)/html dosyalarının hangi komutla açılacağı.
    _set(rf"Software\Classes\{_WIN_PROG_ID}\shell\open\command", None, command)
    _set(rf"Software\Classes\{_WIN_PROG_ID}\DefaultIcon", None, icon_value)

    # 2) StartMenuInternet girişi — "Varsayılan Uygulamalar" listesinde
    #    görünen tarayıcı adı ve komutu.
    _set(_WIN_START_MENU_KEY, None, APP_NAME)
    _set(rf"{_WIN_START_MENU_KEY}\shell\open\command", None, command)

    capabilities = rf"{_WIN_START_MENU_KEY}\Capabilities"
    _set(capabilities, "ApplicationName", APP_NAME)
    _set(capabilities, "ApplicationDescription", "GEM Browser — minimalist, Linux odaklı masaüstü tarayıcı")
    _set(rf"{capabilities}\URLAssociations", "http", _WIN_PROG_ID)
    _set(rf"{capabilities}\URLAssociations", "https", _WIN_PROG_ID)
    _set(rf"{capabilities}\FileAssociations", ".htm", _WIN_PROG_ID)
    _set(rf"{capabilities}\FileAssociations", ".html", _WIN_PROG_ID)

    # 3) Windows'un uygulamayı "Varsayılan Uygulamalar" listesinde bulması
    #    için bu kayıt şart.
    _set(r"Software\RegisteredApplications", APP_NAME, capabilities)


def _windows_set_default_browser() -> None:
    try:
        _windows_register()
    except ImportError:
        raise DefaultBrowserError("winreg modülü bulunamadı (bu yalnızca Windows'ta çalışır).")
    except OSError as exc:
        raise DefaultBrowserError(f"Registry'ye yazılamadı: {exc}")

    # Windows 8+ güvenlik kısıtlaması: hiçbir uygulama kendini sessizce
    # varsayılan yapamaz. Kayıt tamamlandıktan sonra yapılabilecek en iyi
    # şey, kullanıcının son onayı vereceği sistem ekranını açmaktır.
    try:
        os.startfile("ms-settings:defaultapps")
    except Exception as exc:
        raise DefaultBrowserError(
            f"Kayıt tamamlandı ama Ayarlar penceresi açılamadı ({exc}). "
            "Ayarlar > Uygulamalar > Varsayılan Uygulamalar'ı elle açıp "
            f"web tarayıcısı olarak '{APP_NAME}' seçebilirsiniz."
        )


def _windows_is_default_browser() -> bool:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        ) as key:
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")
            return prog_id == _WIN_PROG_ID
    except OSError:
        return False
