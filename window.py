import os
import json
import subprocess
from PyQt6.QtNetwork import QNetworkProxy
from urllib.parse import parse_qs, urlparse
from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QTabBar, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QLineEdit, QToolBar, QToolButton, QMenu, QDialog, QApplication,
    QFileDialog
)
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineScript, QWebEngineSettings, QWebEnginePage
from PyQt6.QtCore import QUrl, Qt, QTimer, QThread, pyqtSignal, QSize, QEvent
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QColor, QPixmap
try:
    from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
except ImportError:
    QPrinter = QPrintDialog = None  # çok nadir: QtPrintSupport paketi yok

from gem_browser import icons as gem_icons
from gem_browser.tor_vpn import TorVpnManager
from gem_browser.url_suggestions import gather_local_suggestions, RemoteSuggester, SuggestionPopup
from gem_browser.browser_tab import BrowserTab
from gem_browser.router import resolve_url, build_search_url, search_engine_label
from gem_browser.new_tab import get_new_tab_url, load_bookmarks, save_bookmarks
from gem_browser.adblock import AdblockInterceptor
from gem_browser import filter_lists
from gem_browser.password_manager import (
    PasswordVault, PasswordManagerDialog, MasterPasswordDialog,
    WrongMasterPassword, CorruptVault, vault_exists
)
from gem_browser.settings import BrowserSettings
from gem_browser.downloads import DownloadManager
from gem_browser.downloads_dialog import DownloadsDialog
from gem_browser import paths as gem_paths
from gem_browser import pdf_viewer
from gem_browser.modern_popup import show_modern_info, show_modern_confirm
from gem_browser import history as gem_history
from gem_browser import default_browser as gem_default_browser
from gem_browser import theme as gem_theme
from gem_browser import session as gem_session
from gem_browser.tab_widgets import (
    _LeftAlignedTabStyle, _PlusToolButton, _TabPreviewPopup, ProgressTabBar,
    _CollapsibleSidebar, _SidebarTabRow, BookmarkDialog, TabSearchDialog,
)
from gem_browser.settings_dialog import SettingsDialog, ClearDataDialog
from gem_browser.history_dialog import HistoryDialog

_active_windows = []
# downloadRequested sinyalinin bağlandığı profiller: aynı paylaşılan profile
# N pencere de bağlanırsa tek indirme isteği N kez işlenir ve N ayrı "Dosyayı
# Kaydet" diyaloğu açılır. Her profile yalnızca İLK pencere bağlanır; o
# pencere kapanırsa (bkz. closeEvent) bağlantı aynı profili kullanan başka
# bir pencereye devredilir.
_download_connected_profiles = []
_startup_session_checked = False
_normal_profile = None


def _is_gem_internal_page(url_str: str) -> bool:
    """Uygulamanın kendi ürettiği geçici sayfalar (yeni sekme sayfası,
    PDF.js görüntüleyici). Bunlar oturuma/geçmişe yazılmaz, adres
    çubuğunda gösterilmez, favorilenemez."""
    if not url_str.startswith("file://"):
        return False
    return ("gem_browser_new_tab" in url_str) or ("gem_pdf_viewer_" in url_str)


def _transparent_icon(w: int, h: int) -> QIcon:
    """Şeffaf dolgu ikonu: QLineEdit aksiyon ikonları alana yapışık
    çizildiğinden, kenarlardan içeride durmaları için boşluk aksiyonu."""
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    icon = QIcon()
    icon.addPixmap(pm)
    return icon

def _get_shared_normal_profile() -> QWebEngineProfile:
    global _normal_profile
    if _normal_profile is None:
        profile = QWebEngineProfile("gem_browser_profile")
        profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        storage_dir = gem_paths.config_path("webprofile")
        cache_dir = gem_paths.config_path("webcache")
        os.makedirs(storage_dir, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)
        profile.setPersistentStoragePath(storage_dir)
        profile.setCachePath(cache_dir)
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        profile.setHttpCacheMaximumSize(100 * 1024 * 1024)
        _normal_profile = profile
    return _normal_profile

_ICON_SIZES = (16, 20, 24, 32, 48, 64, 128, 256)
_logo_icon_cache = {}

def _load_app_icon(accent_color: str = None) -> QIcon:
    global _logo_icon_cache
    cache_key = accent_color or ""
    cached = _logo_icon_cache.get(cache_key)
    if cached is not None: return cached

    if accent_color:
        icon = gem_icons.tinted_logo_icon(accent_color)
    else:
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
        icon = QIcon()
        if os.path.exists(logo_path):
            source = QPixmap(logo_path)
            if not source.isNull():
                for size in _ICON_SIZES:
                    icon.addPixmap(source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    # Only cache a successfully produced icon. If the logo couldn't be
    # loaded/tinted this time (e.g. file not ready yet, transient I/O
    # error), leave the cache empty so the NEXT call retries from scratch
    # instead of permanently freezing an empty QIcon for this accent color.
    if not icon.isNull():
        _logo_icon_cache[cache_key] = icon
    return icon

DARK_STYLE = """
    QMainWindow { background-color: #1a1a1a; }
    QMainWindow::separator { width: 0px; height: 0px; border: none; }
    QWidget { background-color: #1a1a1a; color: #d4d4d4; }
    QWidget#tabsContainer { background-color: #1a1a1a; }
    QScrollArea { background-color: #1a1a1a; border: none; }
    QToolBar { background-color: #1a1a1a; border: none; border-bottom: 1px solid #262626; padding: 6px 8px; spacing: 4px; }
    QToolBar QToolButton { background-color: transparent; border: none; border-radius: 8px; padding: 6px 10px; color: ACCENT_PLACEHOLDER; font-size: 16px; font-weight: bold; }
    QToolBar QToolButton:hover { background-color: #2a2a2a; }
    QToolBar QToolButton:pressed { background-color: #333333; }
    QLineEdit { background-color: #242424; color: #ffffff; border: 1px solid #333333; border-radius: 16px; padding: 8px 16px; font-size: 13px; font-family: 'Segoe UI', 'Ubuntu', sans-serif; margin: 0px 10px; selection-background-color: ACCENT_PLACEHOLDER; }
    QLineEdit:focus { border: 1px solid ACCENT_PLACEHOLDER; background-color: #2a2a2a; }
    QTabWidget::pane { border: none; background: #1a1a1a; }
    QTabBar { qproperty-drawBase: 0; border: none; background: transparent; padding: 12px 8px 12px 12px; }
    QTabBar::tab { background: #242424; color: #909090; padding: 9px 14px; border-radius: 10px; margin-right: 6px; border: none; min-width: 60px; max-width: 200px; font-family: 'Segoe UI', 'Ubuntu', sans-serif; font-weight: 500; letter-spacing: 0.2px; }
    QTabBar::tab:selected { background: #3b3b3b; color: #ffffff; font-weight: 600; }
    QTabBar::tab:hover:!selected { background: #2c2c2c; color: #cfcfcf; }
    QMenu { background-color: #242424; color: #ffffff; border: 1px solid #333333; border-radius: 10px; padding: 6px; }
    QMenu::item { padding: 8px 22px; border-radius: 6px; }
    QMenu::item:selected { background-color: ACCENT_PLACEHOLDER; color: ACCENT_TEXT_PLACEHOLDER; }
    QMenu::separator { height: 1px; background: #333333; margin: 6px 8px; }
    QDialog, QListWidget, QComboBox { background-color: #242424; color: #ffffff; border: 1px solid #333333; }
    QDialog { border-radius: 10px; }
    QListWidget { border-radius: 8px; }
    QListWidget::item { padding: 6px; border-radius: 4px; }
    QListWidget::item:selected { background-color: ACCENT_PLACEHOLDER; color: ACCENT_TEXT_PLACEHOLDER; }
    QComboBox { border-radius: 6px; padding: 6px 10px; }
    QPushButton { background-color: #2a2a2a; color: #ffffff; border: 1px solid #333333; padding: 8px 16px; border-radius: 8px; font-weight: 500; }
    QPushButton:hover { background-color: #3b3b3b; border: 1px solid ACCENT_PLACEHOLDER; }
    QPushButton:pressed { background-color: ACCENT_PLACEHOLDER; color: ACCENT_TEXT_PLACEHOLDER; }
    QCheckBox { spacing: 8px; }
    QCheckBox::indicator { width: 15px; height: 15px; border-radius: 4px; border: 1px solid #444444; background: #242424; }
    QCheckBox::indicator:checked { background: ACCENT_PLACEHOLDER; border: 1px solid ACCENT_PLACEHOLDER; }
    QScrollBar:vertical { background: #1a1a1a; width: 10px; margin: 0; }
    QScrollBar::handle:vertical { background: #3a3a3a; border-radius: 5px; min-height: 24px; }
    QScrollBar::handle:vertical:hover { background: #4a4a4a; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    QHeaderView::section { background-color: #2a2a2a; color: ACCENT_PLACEHOLDER; padding: 6px; border: none; border-bottom: 1px solid #333333; }
    QTableWidget { gridline-color: #2e2e2e; border-radius: 8px; }
"""

LIGHT_STYLE = """
    QMainWindow { background-color: #f5f5f5; }
    QMainWindow::separator { width: 0px; height: 0px; border: none; }
    QWidget { background-color: #f5f5f5; color: #222222; }
    QWidget#tabsContainer { background-color: #f5f5f5; }
    QScrollArea { background-color: #f5f5f5; border: none; }
    QToolBar { background-color: #f5f5f5; border: none; border-bottom: 1px solid #e6e6e6; padding: 6px 8px; spacing: 4px; }
    QToolBar QToolButton { background-color: transparent; border: none; border-radius: 8px; padding: 6px 10px; color: ACCENT_PLACEHOLDER; font-size: 16px; font-weight: bold; }
    QToolBar QToolButton:hover { background-color: #e0e0e0; }
    QToolBar QToolButton:pressed { background-color: #d0d0d0; }
    QLineEdit { background-color: #ffffff; color: #000000; border: 1px solid #cccccc; border-radius: 16px; padding: 8px 16px; font-size: 13px; font-family: 'Segoe UI', 'Ubuntu', sans-serif; margin: 0px 10px; selection-background-color: ACCENT_PLACEHOLDER; }
    QLineEdit:focus { border: 1px solid ACCENT_PLACEHOLDER; background-color: #ffffff; }
    QTabWidget::pane { border: none; background: #f5f5f5; }
    QTabBar { qproperty-drawBase: 0; border: none; background: transparent; padding: 12px 8px 12px 12px; }
    QTabBar::tab { background: #e6e6e6; color: #666666; padding: 9px 14px; border-radius: 10px; margin-right: 6px; border: none; min-width: 60px; max-width: 200px; font-family: 'Segoe UI', 'Ubuntu', sans-serif; font-weight: 500; letter-spacing: 0.2px; }
    QTabBar::tab:selected { background: #ffffff; color: #000000; font-weight: 600; }
    QTabBar::tab:hover:!selected { background: #d6d6d6; color: #222222; }
    QMenu { background-color: #ffffff; color: #000000; border: 1px solid #cccccc; border-radius: 10px; padding: 6px; }
    QMenu::item { padding: 8px 22px; border-radius: 6px; }
    QMenu::item:selected { background-color: ACCENT_PLACEHOLDER; color: ACCENT_TEXT_PLACEHOLDER; }
    QMenu::separator { height: 1px; background: #e0e0e0; margin: 6px 8px; }
    QDialog, QListWidget, QComboBox { background-color: #ffffff; color: #000000; border: 1px solid #cccccc; }
    QDialog { border-radius: 10px; }
    QListWidget { border-radius: 8px; }
    QListWidget::item { padding: 6px; border-radius: 4px; }
    QListWidget::item:selected { background-color: ACCENT_PLACEHOLDER; color: ACCENT_TEXT_PLACEHOLDER; }
    QComboBox { border-radius: 6px; padding: 6px 10px; }
    QPushButton { background-color: #e0e0e0; color: #000000; border: 1px solid #cccccc; padding: 8px 16px; border-radius: 8px; font-weight: 500; }
    QPushButton:hover { background-color: #d0d0d0; border: 1px solid ACCENT_PLACEHOLDER; }
    QPushButton:pressed { background-color: ACCENT_PLACEHOLDER; color: ACCENT_TEXT_PLACEHOLDER; }
    QCheckBox { spacing: 8px; }
    QCheckBox::indicator { width: 15px; height: 15px; border-radius: 4px; border: 1px solid #bbbbbb; background: #ffffff; }
    QCheckBox::indicator:checked { background: ACCENT_PLACEHOLDER; border: 1px solid ACCENT_PLACEHOLDER; }
    QScrollBar:vertical { background: #f5f5f5; width: 10px; margin: 0; }
    QScrollBar::handle:vertical { background: #cccccc; border-radius: 5px; min-height: 24px; }
    QScrollBar::handle:vertical:hover { background: #bbbbbb; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    QHeaderView::section { background-color: #e0e0e0; color: ACCENT_PLACEHOLDER; padding: 6px; border: none; border-bottom: 1px solid #cccccc; }
    QTableWidget { gridline-color: #e0e0e0; border-radius: 8px; }
"""

class BlocklistUpdateThread(QThread):
    finished_ok = pyqtSignal(int)
    finished_err = pyqtSignal(str)
    def run(self):
        try:
            self.finished_ok.emit(filter_lists.update_blocklist())
        except filter_lists.BlocklistUpdateInProgress:
            self.finished_err.emit("__IN_PROGRESS__")
        except Exception as e:
            self.finished_err.emit(str(e))

class PdfFetchThread(QThread):
    """Uzak PDF'i Qt tarafında (CORS'suz) sessizce indirip yerel kopyanın
    yolunu bildirir; görüntüleyici file:// üzerinden açar."""
    done_ok = pyqtSignal(str, str)  # kaynak url, yerel yol
    done_err = pyqtSignal(str, str)  # kaynak url, hata

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url

    def run(self):
        try:
            path = pdf_viewer.fetch_pdf_to_temp(self._url)
            self.done_ok.emit(self._url, path)
        except Exception as exc:
            self.done_err.emit(self._url, str(exc))














class MainWindow(QMainWindow):
    def __init__(self, profile=None, initial_url: QUrl = None):
        super().__init__()
        self.settings = BrowserSettings()
        self.lang = self.settings.current["language"]
        self._preview_popup = None
        # Açılıştaki masaüstü ikonu yazımı ertelenir (bkz.
        # _update_desktop_icon); ilk _refresh_toolbar_icons senkron
        # PNG yazımı + gtk-update-icon-cache subprocess'i yapmasın.
        self._last_desktop_icon_accent = gem_theme.get_accent_color(self.settings.current)
        self._desktop_icon_written = False
        # "_create_page_for_new_window" ile açılan pencereler kurucudan
        # about:blank sekmesiyle çıkar; aksi halde kurucunun otomatik
        # "Yeni Sekme"si + hedef sayfa sekmesi olmak üzere iki sekme birikirdi.
        self._startup_initial_url = initial_url

        if profile is None:
            self.shared_profile = _get_shared_normal_profile()
            self.is_incognito = False
            self._base_title = "GEM Browser"
        else:
            self.shared_profile = profile
            self.is_incognito = True
            self._base_title = "GEM Browser 🕵️ (Gizli)" if self.lang == "tr" else "GEM Browser 🕵️ (Incognito)"
        # ÖNEMLİ: setWindowTitle burada SABİT bir kere değil, aktif sekme
        # değiştikçe / sayfa başlığı değiştikçe _update_window_title() ile
        # tekrar tekrar çağrılır. Bu sayede Alt+Tab / görev çubuğu
        # önizlemesinde "python3" ya da düz "GEM Browser" değil, diğer
        # tarayıcılarda olduğu gibi "Sayfa Başlığı - GEM Browser" görünür.
        self.setWindowTitle(self._base_title)

        # Pencere durumunu geri yükle: kullanıcı en son nasıl bıraktıysa
        # (boyut/konum/maksimize) aynı şekilde başlar. Kayıt yoksa veya
        # geçersizse varsayılan 1024x768 normal pencere (tam ekran DEĞİL).
        s = self.settings.current
        try:
            w = int(s.get("win_w", 1024)); h = int(s.get("win_h", 768))
            if w >= 400 and h >= 300:
                self.resize(w, h)
            x = int(s.get("win_x", -1)); y = int(s.get("win_y", -1))
            if x != -1 and y != -1:
                self.move(x, y)
        except (TypeError, ValueError):
            pass
        self.setWindowIcon(self._app_icon())

        self.vault = None
        self.vault_lock_timer = QTimer(self)
        self.vault_lock_timer.setInterval(10 * 60 * 1000)
        self.vault_lock_timer.setSingleShot(True)
        self.vault_lock_timer.timeout.connect(self._lock_vault)

        self.download_manager = DownloadManager(self)
        if not any(p is self.shared_profile for p in _download_connected_profiles):
            _download_connected_profiles.append(self.shared_profile)
            self._owns_download_signal = True
            self.shared_profile.downloadRequested.connect(self.download_manager.handle_download)

        self.persistent_history = [] if self.is_incognito else gem_history.load_history()
        self.session_history = [entry.get("url", "") for entry in self.persistent_history]
        self.closed_tabs_stack = []
        self.tab_timers = {}
        # Dikey sidebar satırları (tab -> _SidebarTabRow): yükleme çizgisi ve
        # ses ikonunu yeniden kurmadan güncellemek için.
        self._sidebar_rows = {}

        self.adblock_interceptor = AdblockInterceptor(self)
        self._blocklist_thread = None
        self._load_and_maybe_update_blocklist()
        self._inject_cookie_banner_hider()

        # Yerleşik VPN (Tor tabanlı) — bkz. gem_browser/tor_vpn.py için
        # neden "ücretsiz public proxy" yerine Tor kullanıldığının detaylı
        # açıklaması.
        self.tor_vpn = TorVpnManager(self)
        self.tor_vpn.status_changed.connect(self._on_vpn_status_changed)
        self.tor_vpn.error.connect(self._on_vpn_error)

        self.central_widget = QWidget(self)
        self.setCentralWidget(self.central_widget)
        # Sürükle-bırak: PDF/dosya/url'yı pencereye bırakıp açma
        self.setAcceptDrops(True)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self._setup_toolbar()
        self._setup_tabs()
        # Uygulama genelinde tuş filtresi (bkz. eventFilter): QtWebEngine
        # F5/Ctrl+R/ESC gibi tarayıcı rezerve tuşlarını ShortcutOverride ile
        # kendine aldığı için QAction kısayolları bu tuşlarda tetiklenmiyor.
        # QApplication seviyesindeki filtre, tuş teslimatının en erken
        # noktasında bunları yakalar.
        _app = QApplication.instance()
        if _app is not None:
            _app.installEventFilter(self)
        self._apply_settings_to_browser()
        self._restore_session_or_new_tab()

    def show_hover_preview(self, tab, title, pos, is_sidebar=False):
        if self._preview_popup is None:
            self._preview_popup = _TabPreviewPopup()
        self._preview_popup.show_for(tab, title, pos, is_sidebar=is_sidebar)

    def hide_hover_preview(self):
        if self._preview_popup is not None:
            self._preview_popup.hide()

    def _apply_vpn(self):
        """
        Yerleşik VPN — çalışma anında uygulanır, yeniden başlatma GEREKMEZ.

        QtWebEngine, Qt'nin uygulama geneli proxy'sini (QNetworkProxy::
        setApplicationProxy) sayfa trafiğine yansıtır; VPN açılıp kapandıkça
        proxy burada güncellenir.

        İki mod:
          1) Kullanıcı Ayarlar'da kendi SOCKS5 proxy'sinin host/port'unu
             girdiyse doğrudan onu kullanırız.
          2) Host boşsa resmi Tor ağına bağlanırız (tor_vpn.py); bootstrap
             tamamlanınca (`connected` sinyali) yerel SOCKS5 portu proxy
             olarak ayarlanır.
        """
        enabled = self.settings.current.get("vpn_enabled", False)

        if not enabled:
            if self.tor_vpn.is_active:
                self.tor_vpn.disconnect()
            QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
            return

        host = (self.settings.current.get("vpn_host") or "").strip()
        port = self.settings.current.get("vpn_port", 9050)
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = 9050

        if host:
            # 1) Manuel/gelişmiş mod: kullanıcının kendi SOCKS5 adresi.
            if self.tor_vpn.is_active:
                self.tor_vpn.disconnect()
            proxy = QNetworkProxy()
            proxy.setType(QNetworkProxy.ProxyType.Socks5Proxy)
            proxy.setHostName(host)
            proxy.setPort(port)
            QNetworkProxy.setApplicationProxy(proxy)
        else:
            # 2) Otomatik mod: Tor ağı (sabit SOCKS portıyla).
            self.tor_vpn.connect()

    def _on_vpn_status_changed(self, status: str, pct: int):
        # Tor bootstrap tamamlandığında yerel SOCKS5 portunu uygulama geneli
        # proxy olarak ayarla (QtWebEngine sayfa trafiğini de bundan geçirir).
        if status == "connected" and self.tor_vpn.socks_port:
            proxy = QNetworkProxy()
            proxy.setType(QNetworkProxy.ProxyType.Socks5Proxy)
            proxy.setHostName("127.0.0.1")
            proxy.setPort(self.tor_vpn.socks_port)
            QNetworkProxy.setApplicationProxy(proxy)
        elif status in ("disconnected", "error"):
            QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))

    def _on_vpn_error(self, message: str):
        show_modern_info(self, message, lang=self.lang, warning=True)
        # Kullanıcıyı yanıltmamak için ayarlardaki "etkin" durumunu geri al —
        # aksi halde VPN "açık" görünüp aslında hiçbir koruma sağlamaz.
        self.settings.current["vpn_enabled"] = False
        self.settings.save()

    def _collect_session_tab_urls(self) -> list:
        urls = []
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if not isinstance(tab, BrowserTab): continue
            url_str = tab.saved_url.toString() if tab.is_suspended else tab.view.url().toString()
            if url_str and not (_is_gem_internal_page(url_str)):
                urls.append(url_str)
        return urls

    def _restore_session_or_new_tab(self):
        global _startup_session_checked
        initial = getattr(self, "_startup_initial_url", None)
        if self.is_incognito or _startup_session_checked:
            self.add_new_tab(initial) if initial is not None else self.add_new_tab()
            return

        _startup_session_checked = True
        tab_urls = gem_session.load_session()
        gem_session.clear_session()

        if not tab_urls:
            self.add_new_tab(initial) if initial is not None else self.add_new_tab()
            return

        # "auto_restore_tabs" açıksa, kullanıcıya hiç sormadan sekmeleri
        # doğrudan geri yükle. Kapalıysa (varsayılan) eski davranış gibi
        # önce onay iste.
        if self.settings.current.get("auto_restore_tabs", False):
            should_restore = True
        else:
            msg = (f"Önceki oturumdan kalan {len(tab_urls)} açık sekme bulundu. Geri yüklensin mi?" if self.lang == "tr"
                   else f"Found {len(tab_urls)} tabs left open from your previous session. Restore them?")
            should_restore = show_modern_confirm(self, msg, title="Sekmeleri Geri Yükle" if self.lang == "tr" else "Restore Tabs", lang=self.lang)

        if should_restore:
            for index, url_str in enumerate(tab_urls):
                self.add_new_tab(QUrl(url_str), switch_to=(index == 0 and initial is None))
            if initial is not None:
                self.add_new_tab(initial)
        else:
            self.add_new_tab(initial) if initial is not None else self.add_new_tab()

    def _new_tab_url(self) -> str:
        return get_new_tab_url(
            self.settings.current["ui_theme"], self.lang,
            accent_color=gem_theme.get_accent_color(self.settings.current),
            background_image=self.settings.current.get("new_tab_background") or None,
            search_engine=self.settings.current.get("search_engine", "brave"),
            custom_search_url=self.settings.current.get("custom_search_url", ""),
        )

    def _refresh_new_tab_page(self, tab: BrowserTab) -> None:
        if tab.view is not None:
            tab.view.page().runJavaScript(f"window.location.replace({json.dumps(self._new_tab_url())});")

    def _update_desktop_icon(self, accent_color: str, refresh_cache: bool = True):
        user_icon_dir = os.path.expanduser("~/.local/share/icons/hicolor/256x256/apps")
        os.makedirs(user_icon_dir, exist_ok=True)
        target_path = os.path.join(user_icon_dir, "gem-browser.png")
        pixmap = gem_icons.tinted_logo_pixmap(accent_color, 256)
        if not pixmap.isNull():
            pixmap.save(target_path, "PNG")
            if refresh_cache:
                # gtk-update-icon-cache pahalıdır; yalnızca vurgu rengi
                # GERÇEKTEN değiştiğinde çalıştırılır.
                try:
                    subprocess.run(["gtk-update-icon-cache", "-f", os.path.expanduser("~/.local/share/icons/hicolor")], stderr=subprocess.DEVNULL)
                except Exception: pass

    def _apply_settings_to_browser(self):
        self.lang = self.settings.current["language"]
        accent = gem_theme.get_accent_color(self.settings.current)
        base_style = LIGHT_STYLE if self.settings.current["ui_theme"] == "light" else DARK_STYLE
        self.setStyleSheet(base_style.replace("ACCENT_PLACEHOLDER", accent).replace("ACCENT_TEXT_PLACEHOLDER", gem_theme.readable_text_color(accent)))

        # Interceptor HER ZAMAN takılı: PDF → görüntüleyici yönlendirmesi
        # buradan geçer; reklam engelleme kapalıysa interceptor kendi
        # içindeki enabled bayrağıyla yalnızca engellemeyi kapatır.
        self.shared_profile.setUrlRequestInterceptor(self.adblock_interceptor)
        self.adblock_interceptor.set_enabled(self.settings.current["adblock_enabled"])

        web_settings = self.shared_profile.settings()
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, self.settings.current["js_enabled"])
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, self.settings.current["load_images"])
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        # PDF.js görüntüleyici (file:// sayfası) yerel kaynaklara (indirilmiş
        # ya da file:// yolu verilen PDF'lere) erişebilsin.
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        # HTML5 tam ekran (YouTube vb.) QtWebEngine'de VARSAYILAN OLARAK
        # KAPALI gelir; bu öznitelik açık olmadan sayfaların
        # requestFullscreen() çağrısı "Fullscreen is not supported" ile
        # reddedilir ve fullScreenRequested sinyali hiç üretilmez.
        # (browser_tab.py'deki _handle_fullscreen_request işleyicisi bu
        # sinyali alıp view'i tam ekran yapar.)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        # VPN/Tor açıkken WebRTC sızıntısına karşı çalışma anı anahtarı:
        # WebRTC yalnızca genel arayüzlerle sınırlanır (yerel IP adayları
        # engellenir). Tam koruma (--force-webrtc-ip-handling-policy=
        # disable_non_proxied_udp, proxy üzerinden zorlama) için yeniden
        # başlatma gerekir — bkz. main.py.
        vpn_on = bool(self.settings.current.get("vpn_enabled", False))
        try:
            web_settings.setAttribute(
                QWebEngineSettings.WebAttribute.WebRTCPublicInterfacesOnly, vpn_on)
        except AttributeError:
            pass  # eski Qt: öznitelik yok
        # PDF'ler indirme olarak değil, Chrome'daki gibi SEKME İÇİNDE
        # Qt'nin yerleşik görüntüleyicisiyle açılsın.
        try:
            web_settings.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, True)
        except AttributeError:
            pass  # eski Qt sürümü (6.4 öncesi): öznitelik yok

        scripts = self.shared_profile.scripts()
        for s in scripts.toList():
            if s.name() == "ForceDarkMode": scripts.remove(s)

        if self.settings.current["force_dark_web"]:
            dark_script = QWebEngineScript()
            dark_script.setSourceCode("(function() { if(window.location.href.indexOf('gem_browser_new_tab') !== -1) return; var css = 'html {-webkit-filter: invert(100%) hue-rotate(180deg) !important; filter: invert(100%) hue-rotate(180deg) !important; background: black;} img, video, iframe, canvas {-webkit-filter: invert(100%) hue-rotate(180deg) !important; filter: invert(100%) hue-rotate(180deg) !important;}'; var style = document.createElement('style'); style.type = 'text/css'; style.appendChild(document.createTextNode(css)); document.head.appendChild(style); })();")
            dark_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
            dark_script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
            dark_script.setName("ForceDarkMode")
            scripts.insert(dark_script)

        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if isinstance(tab, BrowserTab) and not tab.is_suspended:
                if tab.view.url().toString().startswith("file://") and "gem_browser_new_tab" in tab.view.url().toString():
                    self._refresh_new_tab_page(tab)
                else: tab.view.reload()

        self._refresh_close_buttons()
        self._refresh_toolbar_icons()
        self._rebuild_vertical_sidebar()
        # Askıya alma süresi/canlı sekme sınırı ayarları anında uygulansın.
        self._update_suspend_timers()
        self._enforce_max_live_tabs()

        self.url_bar.setPlaceholderText("Web'de arayın veya bir URL girin..." if self.lang == "tr" else "Search the web or enter URL...")
        self.action_new_tab.setText("Yeni Sekme" if self.lang == "tr" else "New Tab")
        self.action_reopen_tab.setText("Kapatılan Sekmeyi Aç" if self.lang == "tr" else "Reopen Closed Tab")
        self.action_new_win.setText("Yeni Pencere" if self.lang == "tr" else "New Window")
        self.action_incognito.setText("Yeni Gizli Pencere" if self.lang == "tr" else "New Incognito")
        self.action_downloads.setText("İndirmeler" if self.lang == "tr" else "Downloads")
        self.action_history.setText("Geçmiş" if self.lang == "tr" else "History")
        self.action_pwd.setText("Şifre Yöneticisi" if self.lang == "tr" else "Password Manager")
        self.action_update_blocklist.setText("İzleyici Listesini Güncelle" if self.lang == "tr" else "Update Tracker List")
        self.action_zoom_in.setText("Yakınlaştır" if self.lang == "tr" else "Zoom In")
        self.action_zoom_out.setText("Uzaklaştır" if self.lang == "tr" else "Zoom Out")
        self.action_zoom_reset.setText("Yakınlaştırmayı Sıfırla" if self.lang == "tr" else "Reset Zoom")
        if hasattr(self, "vertical_tabs_btn"):
            self.vertical_tabs_btn.setToolTip("Dikey Sekme Çubuğu" if self.lang == "tr" else "Vertical Tab Bar")
        self.action_set_default_browser.setText("Varsayılan Tarayıcı Yap" if self.lang == "tr" else "Set as Default Browser")
        self.action_settings.setText("Ayarlar" if self.lang == "tr" else "Settings")
        self.action_find.setText("Sayfada Ara" if self.lang == "tr" else "Find in Page")
        self.action_open_file.setText("Dosya Aç" if self.lang == "tr" else "Open File")
        self.action_fullscreen.setText("Tam Ekran (F11)" if self.lang == "tr" else "Full Screen (F11)")
        self.action_clear_data.setText("Tarama Verilerini Temizle" if self.lang == "tr" else "Clear Browsing Data")
        self.action_print.setText("Yazdır" if self.lang == "tr" else "Print")
        self.action_save_pdf.setText("PDF Olarak Kaydet" if self.lang == "tr" else "Save as PDF")
        self.action_save_page.setText("Sayfayı Kaydet" if self.lang == "tr" else "Save Page")
        self.action_view_source.setText("Sayfa Kaynağını Görüntüle" if self.lang == "tr" else "View Page Source")
        self.action_devtools.setText("Geliştirici Araçları (F12)" if self.lang == "tr" else "Developer Tools (F12)")
        self.action_dup_tab.setText("Sekmeyi Çoğalt" if self.lang == "tr" else "Duplicate Tab")
        self.action_mute_tab.setText("Sesi Kapat / Aç" if self.lang == "tr" else "Mute / Unmute Tab")
        self.action_tab_search.setText("Sekme Ara" if self.lang == "tr" else "Search Tabs")
        # Arama motoru değişmiş olabilir: öneri uç noktasını güncelle.
        self._remote_suggester.set_engine(self.settings.current.get("search_engine", "brave"))
        self._update_url_extras()
        if self.settings.current.get("vault_session_unlock", False):
            self.vault_lock_timer.stop()
        self._apply_vpn()

    def _load_and_maybe_update_blocklist(self):
        cached = filter_lists.load_cached_domains()
        if cached: self.adblock_interceptor.set_domains(cached)
        if cached is None or filter_lists.needs_update(): self._start_blocklist_update(silent=True)

    def _start_blocklist_update(self, silent: bool = True):
        if self._blocklist_thread is not None and self._blocklist_thread.isRunning():
            if not silent: show_modern_info(self, "Liste zaten güncelleniyor..." if self.lang == "tr" else "Update already in progress...", lang=self.lang)
            return
        self._blocklist_thread = BlocklistUpdateThread(self)
        self._blocklist_thread.finished_ok.connect(lambda n: self._on_blocklist_updated(n, silent))
        self._blocklist_thread.finished_err.connect(lambda err: self._on_blocklist_update_failed(err, silent))
        self._blocklist_thread.start()

    def _on_blocklist_updated(self, count: int, silent: bool):
        domains = filter_lists.load_cached_domains()
        if domains:
            self.adblock_interceptor.set_domains(domains)
            for win in _active_windows:
                if win is not self and hasattr(win, "adblock_interceptor"): win.adblock_interceptor.set_domains(domains)
        if not silent: show_modern_info(self, f"Engelleme listesi güncellendi: {count} domain." if self.lang == "tr" else f"Block list updated: {count} domains.", lang=self.lang)

    def _on_blocklist_update_failed(self, err: str, silent: bool):
        if err == "__IN_PROGRESS__":
            if not silent: show_modern_info(self, "Liste zaten başka bir pencerede güncelleniyor, lütfen biraz bekleyin." if self.lang == "tr" else "The list is already being updated in another window.", lang=self.lang)
            return
        if not silent: show_modern_info(self, ("Liste güncellenemedi: " if self.lang == "tr" else "Update failed: ") + err, lang=self.lang, warning=True)

    def _inject_cookie_banner_hider(self):
        # Bu metod her MainWindow kuruluşunda çağrılır; paylaşılan profile
        # aynı isimli script defalarca eklenip her sayfada N kez
        # enjekte edilmesin diye isim kontrolü yapıyoruz.
        scripts = self.shared_profile.scripts()
        if any(s.name() == "CookieBannerHider" for s in scripts.toList()):
            return
        script = QWebEngineScript()
        script.setSourceCode("(function() { var style = document.createElement('style'); style.textContent = '#cookie-notice, .cc-window, .cookie-banner, #onetrust-consent-sdk, #cmpbox, .CybotCookiebotDialog, #ez-cookie-dialog, .qc-cmp2-container { display: none !important; }'; document.head.appendChild(style); })();")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
        script.setName("CookieBannerHider")
        self.shared_profile.scripts().insert(script)

    def _setup_toolbar(self):
        self.toolbar = QToolBar("Navigation", self)
        self.toolbar.setMovable(False)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(self.toolbar)

        self.back_btn = QToolButton(self)
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.setIconSize(QSize(18, 18))
        self.back_btn.clicked.connect(self._navigate_back)

        self.forward_btn = QToolButton(self)
        self.forward_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.forward_btn.setIconSize(QSize(18, 18))
        self.forward_btn.clicked.connect(self._navigate_forward)

        self.reload_btn = QToolButton(self)
        self.reload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reload_btn.setIconSize(QSize(17, 17))
        self.reload_btn.clicked.connect(self._reload_page)

        self.nav_group = QWidget(self)
        self.nav_group.setObjectName("navGroup")
        nav_layout = QHBoxLayout(self.nav_group)
        nav_layout.setContentsMargins(4, 2, 4, 2)
        nav_layout.setSpacing(0)
        for btn in (self.back_btn, self.forward_btn, self.reload_btn):
            btn.setAutoRaise(True)
            nav_layout.addWidget(btn)
        self.toolbar.addWidget(self.nav_group)

        self.url_bar = QLineEdit(self)
        self.url_bar.returnPressed.connect(self._load_url_from_bar)

        # Adres çubuğu aksiyonları: BAŞTA güvenlik göstergesi (kilit),
        # SONDA favori yıldızı. QLineEdit aksiyon ikonlarını alanın en
        # ucuna YAPIŞIK çizer (pixmap'e padding gömmek, ikon ölçeklendiği
        # için görünmez) — bu yüzden kenarlardan içeride tutan ŞEFFAF
        # dolgu aksiyonları kullanılıyor.
        self._pad_action_left = QAction(self)
        self._pad_action_left.setIcon(_transparent_icon(8, 14))
        self.url_bar.addAction(self._pad_action_left, QLineEdit.ActionPosition.LeadingPosition)

        self.security_action = QAction(self)
        self.security_action.setVisible(False)
        self.security_action.triggered.connect(self._show_security_info)
        self.url_bar.addAction(self.security_action, QLineEdit.ActionPosition.LeadingPosition)

        # NOT: TrailingPosition aksiyonları EKLEME SIRASININ TERSİ dizilir;
        # yıldızın sağına dolgu düşmesi için dolgu aksiyonu ÖNCE eklenir.
        self._pad_action_right = QAction(self)
        self._pad_action_right.setIcon(_transparent_icon(8, 14))
        self.url_bar.addAction(self._pad_action_right, QLineEdit.ActionPosition.TrailingPosition)

        self.star_action = QAction(self)
        self.star_action.setVisible(False)
        self.star_action.triggered.connect(self._toggle_bookmark)
        self.url_bar.addAction(self.star_action, QLineEdit.ActionPosition.TrailingPosition)

        self._suggestion_popup = None
        self._suggestion_popup_theme = None
        self._current_url_text = ""
        self._current_local_entries = []
        self._remote_suggester = RemoteSuggester(self, engine=self.settings.current.get("search_engine", "brave"))
        self._remote_suggester.suggestions_ready.connect(self._on_remote_suggestions)
        self.url_bar.textEdited.connect(self._on_url_text_edited)
        self.url_bar.installEventFilter(self)
        self.toolbar.addWidget(self.url_bar)

        self.sleep_status_label = QLabel(self)
        self.sleep_status_label.setStyleSheet("QLabel { padding: 4px 8px; font-size: 12px; color: #888888; background: transparent; }")
        self.sleep_status_label.hide()
        self.toolbar.addWidget(self.sleep_status_label)

        self.vertical_tabs_btn = QToolButton(self)
        self.vertical_tabs_btn.setIconSize(QSize(18, 18))
        self.vertical_tabs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.vertical_tabs_btn.setAutoRaise(True)
        self.vertical_tabs_btn.clicked.connect(self._toggle_vertical_tabs)
        self.toolbar.addWidget(self.vertical_tabs_btn)

        self.menu_btn = QToolButton(self)
        self.menu_btn.setIconSize(QSize(18, 18))
        self.menu_btn.setStyleSheet("QToolButton { padding: 6px 10px; border: none; border-radius: 8px; background: transparent; } QToolButton::menu-indicator { image: none; } QToolButton:hover { background: rgba(128, 128, 128, 0.2); }")

        self.main_menu = QMenu(self)
        self.action_new_tab = QAction("", self)
        self.action_new_tab.setShortcut("Ctrl+T")
        self.action_new_tab.triggered.connect(lambda: self.add_new_tab())

        self.action_reopen_tab = QAction("", self)
        self.action_reopen_tab.setShortcut("Ctrl+Shift+T")
        self.action_reopen_tab.triggered.connect(self._reopen_closed_tab)

        self.action_new_win = QAction("", self)
        self.action_new_win.setShortcut("Ctrl+N")
        self.action_new_win.triggered.connect(self._open_new_window)

        self.action_incognito = QAction("", self)
        self.action_incognito.setShortcut("Ctrl+Shift+N")
        self.action_incognito.triggered.connect(self._open_incognito_window)

        self.action_downloads = QAction("", self)
        self.action_downloads.setShortcut("Ctrl+J")
        self.action_downloads.triggered.connect(self._open_downloads_dialog)

        self.action_history = QAction("", self)
        self.action_history.setShortcut("Ctrl+H")
        self.action_history.triggered.connect(self._open_history)

        self.action_pwd = QAction("", self)
        self.action_pwd.triggered.connect(self._open_password_manager)

        self.action_update_blocklist = QAction("", self)
        self.action_update_blocklist.triggered.connect(lambda: self._start_blocklist_update(silent=False))

        self.action_zoom_in = QAction("", self)
        self.action_zoom_in.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
        self.action_zoom_in.triggered.connect(self._zoom_in)

        self.action_zoom_out = QAction("", self)
        self.action_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        self.action_zoom_out.triggered.connect(self._zoom_out)

        self.action_zoom_reset = QAction("", self)
        self.action_zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        self.action_zoom_reset.triggered.connect(self._zoom_reset)

        self.action_set_default_browser = QAction("", self)
        self.action_set_default_browser.triggered.connect(self._set_as_default_browser)

        self.action_settings = QAction("", self)
        self.action_settings.triggered.connect(self._open_settings)

        # Ctrl+F (sayfada ara) ve F5/Ctrl+R (yenile) QAction kısayolu olarak
        # tanımlanır: keyPressEvent'e koyulan kısayollar, odak web
        # görünümündeyken Chromium tarafından tüketildiği için HİÇ
        # tetiklenmezdi; QAction shortcut'ları Qt'nin ShortcutOverride
        # mekanizmasıyla bu durumda da çalışır.
        self.action_find = QAction("", self)
        self.action_find.setShortcut(QKeySequence.StandardKey.Find)
        self.action_find.triggered.connect(self._find_in_page)

        self.action_full_reload = QAction(self)
        # StandardKey.Refresh platforma/masaüstüne göre farklı tanımlanabilir;
        # F5'in HER ORTAMDA çalışması için kısayolları açıkça listeliyoruz.
        self.action_full_reload.setShortcuts([QKeySequence("F5"), QKeySequence("Ctrl+R")])
        self.action_full_reload.triggered.connect(self._reload_page)

        # F11: pencere genelinde tam ekran. Eskiden hiçbir kısayol/aksiyon
        # tanımlı olmadığı için F11 hiçbir şey yapmıyordu.
        self.action_fullscreen = QAction("", self)
        self.action_fullscreen.setShortcut(QKeySequence("F11"))
        self.action_fullscreen.triggered.connect(self._toggle_window_fullscreen)

        # --- Klavye kısayol paketi (Chrome/Firefox standartları) ---
        # NOT: Bu tuşlardan Chromium'un ShortcutOverride ile rezerve
        # ettikleri (Ctrl+W, Ctrl+Tab, Ctrl+1..9, Alt+Yön) QAction üzerinden
        # tetiklenmeyebilir; hepsinin karşılığı app-level eventFilter'da da
        # vardır (bkz. eventFilter) — ikisi birbirini tamamlar, çifte
        # tetiklenme olmaz (kısayol tüketilirse KeyPress teslim edilmez).
        self.action_focus_url = QAction(self)
        self.action_focus_url.setShortcut(QKeySequence("Ctrl+L"))
        self.action_focus_url.triggered.connect(self._focus_url_bar)

        self.action_open_file = QAction("", self)
        self.action_open_file.setShortcut(QKeySequence("Ctrl+O"))
        self.action_open_file.triggered.connect(self._open_file_dialog)

        # --- Sayfa ve sekme eylemleri ---
        self.action_print = QAction("", self)
        self.action_print.setShortcut(QKeySequence("Ctrl+P"))
        self.action_print.triggered.connect(self._print_page)

        self.action_save_pdf = QAction("", self)
        self.action_save_pdf.triggered.connect(self._save_page_as_pdf)

        self.action_save_page = QAction("", self)
        self.action_save_page.setShortcut(QKeySequence("Ctrl+S"))
        self.action_save_page.triggered.connect(self._save_page)

        self.action_view_source = QAction("", self)
        self.action_view_source.setShortcut(QKeySequence("Ctrl+U"))
        self.action_view_source.triggered.connect(self._view_source)

        self.action_devtools = QAction("", self)
        self.action_devtools.setShortcut(QKeySequence("F12"))
        self.action_devtools.triggered.connect(self._toggle_devtools)

        self.action_dup_tab = QAction("", self)
        self.action_dup_tab.triggered.connect(lambda: self._duplicate_tab())

        self.action_mute_tab = QAction("", self)
        self.action_mute_tab.setShortcut(QKeySequence("Ctrl+M"))
        self.action_mute_tab.triggered.connect(lambda: self._toggle_tab_mute())

        self.action_tab_search = QAction("", self)
        self.action_tab_search.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self.action_tab_search.triggered.connect(self._tab_search)

        self.action_clear_data = QAction("", self)
        self.action_clear_data.setShortcut(QKeySequence("Ctrl+Shift+Delete"))
        self.action_clear_data.triggered.connect(self._open_clear_data)

        self.action_close_tab_ks = QAction(self)
        self.action_close_tab_ks.setShortcut(QKeySequence("Ctrl+W"))
        self.action_close_tab_ks.triggered.connect(
            lambda: self.close_tab(self.tab_widget.currentIndex()))

        self.action_next_tab = QAction(self)
        self.action_next_tab.setShortcut(QKeySequence("Ctrl+Tab"))
        self.action_next_tab.triggered.connect(lambda: self._cycle_tab(1))

        self.action_prev_tab = QAction(self)
        self.action_prev_tab.setShortcut(QKeySequence("Ctrl+Shift+Tab"))
        self.action_prev_tab.triggered.connect(lambda: self._cycle_tab(-1))

        self.action_alt_back = QAction(self)
        self.action_alt_back.setShortcut(QKeySequence("Alt+Left"))
        self.action_alt_back.triggered.connect(self._navigate_back)

        self.action_alt_forward = QAction(self)
        self.action_alt_forward.setShortcut(QKeySequence("Alt+Right"))
        self.action_alt_forward.triggered.connect(self._navigate_forward)

        self._tab_number_actions = []
        for n in range(1, 10):
            act = QAction(self)
            act.setShortcut(QKeySequence(f"Ctrl+{n}"))
            act.triggered.connect(lambda checked=False, num=n: self._goto_tab_number(num))
            self._tab_number_actions.append(act)

        self._menu_action_icons = {
            self.action_new_tab: "plus", self.action_reopen_tab: "undo", self.action_new_win: "window",
            self.action_incognito: "incognito", self.action_downloads: "download", self.action_history: "history",
            self.action_pwd: "lock", self.action_update_blocklist: "shield", self.action_set_default_browser: "star",
            self.action_settings: "settings", self.action_zoom_in: "zoom-in", self.action_zoom_out: "zoom-out",
            self.action_zoom_reset: "zoom-reset", self.action_fullscreen: "window",
            self.action_clear_data: "shield", self.action_print: "printer",
            self.action_save_pdf: "download", self.action_save_page: "download",
            self.action_view_source: "globe", self.action_devtools: "pip",
            self.action_dup_tab: "window", self.action_mute_tab: "volume-off",
            self.action_tab_search: "search",
        }

        self.main_menu.addActions([self.action_new_tab, self.action_reopen_tab, self.action_new_win, self.action_incognito])
        self.main_menu.addSeparator()
        self.main_menu.addActions([self.action_downloads, self.action_history, self.action_pwd, self.action_update_blocklist])
        self.main_menu.addAction(self.action_clear_data)
        self.main_menu.addSeparator()
        self.main_menu.addActions([self.action_print, self.action_save_pdf, self.action_save_page,
                                   self.action_view_source, self.action_devtools])
        self.main_menu.addSeparator()
        self.main_menu.addActions([self.action_dup_tab, self.action_mute_tab, self.action_tab_search])
        self.main_menu.addSeparator()
        self.main_menu.addActions([self.action_zoom_in, self.action_zoom_out, self.action_zoom_reset])
        self.main_menu.addAction(self.action_fullscreen)
        self.main_menu.addSeparator()
        self.main_menu.addActions([self.action_set_default_browser, self.action_settings])

        self.menu_btn.setMenu(self.main_menu)
        self.menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar.addWidget(self.menu_btn)
        self._refresh_toolbar_icons()

    def _app_icon(self) -> QIcon:
        return _load_app_icon(gem_theme.get_accent_color(self.settings.current))

    def _theme_colors(self) -> dict:
        accent = gem_theme.get_accent_color(self.settings.current)
        return {"accent": accent, "disabled": "#c2c2c2" if self.settings.current["ui_theme"] == "light" else "#4a4a4a"}

    def _refresh_toolbar_icons(self):
        colors = self._theme_colors()
        accent, disabled = colors["accent"], colors["disabled"]
        # _update_desktop_icon diske PNG yazar + gtk-update-icon-cache
        # çalıştırır; her tazelemede (ve her yeni sekmede) tekrarlanmasın
        # diye yalnızca vurgu rengi gerçekten değiştiğinde çağrılıyor.
        # AÇILIŞTA: yazım ertelenir (pencere gösterildikten ~2 sn sonra,
        # arka planda) — gtk-update-icon-cache açılışı geciktirmesin.
        if accent != getattr(self, "_last_desktop_icon_accent", None):
            self._last_desktop_icon_accent = accent
            self._update_desktop_icon(accent, refresh_cache=True)
        elif not getattr(self, "_desktop_icon_written", False):
            self._desktop_icon_written = True
            QTimer.singleShot(2000, lambda: self._update_desktop_icon(accent, refresh_cache=False))
        self.back_btn.setIcon(gem_icons.get_icon("back", accent, disabled, size=18))
        self.forward_btn.setIcon(gem_icons.get_icon("forward", accent, disabled, size=18))
        self.reload_btn.setIcon(gem_icons.get_icon("reload", accent, disabled, size=17))
        self.menu_btn.setIcon(gem_icons.get_icon("dots", accent, size=18))
        if hasattr(self, "vertical_tabs_btn"):
            self.vertical_tabs_btn.setIcon(gem_icons.get_icon("sidebar", accent, size=18))

        for action, icon_name in self._menu_action_icons.items():
            action.setIcon(gem_icons.get_icon(icon_name, accent, size=16))

        is_light = self.settings.current["ui_theme"] == "light"
        bg_color = "#f5f5f5" if is_light else "#1a1a1a"
        hover_bg = "#e0e0e0" if is_light else "#2a2a2a"

        if hasattr(self, "new_tab_btn"):
            self.new_tab_btn.setStyleSheet(
                f"QToolButton {{ background-color: {bg_color}; "
                "padding: 0px; margin: 0px; border: none; border-radius: 8px; } "
                f"QToolButton:hover {{ background-color: {hover_bg}; }}"
            )
            self.new_tab_btn.setPlusColor(accent)

        if hasattr(self, "_sidebar_new_tab_btn"):
            self._sidebar_new_tab_btn.setStyleSheet(
                f"QToolButton {{ background-color: {bg_color}; "
                "padding: 0px; margin: 0px; border: none; border-radius: 8px; } "
                f"QToolButton:hover {{ background-color: {hover_bg}; }}"
            )
            self._sidebar_new_tab_btn.setPlusColor(accent)

        # Alt dock ikonlarını vurgu rengiyle (accent) güncelle
        if hasattr(self, "sidebar_dl_btn"):
            dock_btn_style = "QToolButton { border: none; background: transparent; border-radius: 6px; } QToolButton:hover { background: rgba(128,128,128,0.2); }"
        if hasattr(self, "sidebar_pin_btn"):
            self._update_sidebar_pin_button()

            self.sidebar_dl_btn.setIcon(gem_icons.get_icon("download", accent, size=18))
            self.sidebar_dl_btn.setStyleSheet(dock_btn_style)

            self.sidebar_hist_btn.setIcon(gem_icons.get_icon("history", accent, size=18))
            self.sidebar_hist_btn.setStyleSheet(dock_btn_style)

            self.sidebar_set_btn.setIcon(gem_icons.get_icon("settings", accent, size=18))
            self.sidebar_set_btn.setStyleSheet(dock_btn_style)

        tab_bar = self.tab_widget.tabBar() if hasattr(self, "tab_widget") else None
        if tab_bar is not None and hasattr(tab_bar, "set_accent_color"):
            tab_bar.set_accent_color(accent)

        app_icon = self._app_icon()
        self.setWindowIcon(app_icon)
        if hasattr(self, "tab_widget"):
            for i in range(self.tab_widget.count()):
                tab = self.tab_widget.widget(i)
                if isinstance(tab, BrowserTab):
                    url_str = tab.saved_url.toString() if tab.is_suspended else (tab.view.url().toString() if tab.view is not None else "")
                    if _is_gem_internal_page(url_str):
                        self.tab_widget.setTabIcon(i, app_icon)

        group_bg = "rgba(0, 0, 0, 0.035)" if is_light else "rgba(255, 255, 255, 0.04)"
        group_hover = "rgba(0, 0, 0, 0.05)" if is_light else "rgba(255, 255, 255, 0.06)"
        self.nav_group.setStyleSheet(
            f"QWidget#navGroup {{ background-color: {group_bg}; border-radius: 16px; margin: 0px 4px; }} "
            "QWidget#navGroup QToolButton { background: transparent; border: none; border-radius: 12px; padding: 5px; } "
            f"QWidget#navGroup QToolButton:hover {{ background-color: {group_hover}; }} "
            "QWidget#navGroup QToolButton:disabled { background: transparent; }"
        )
        self._update_nav_buttons()

    def _update_nav_buttons(self):
        tab_widget = getattr(self, "tab_widget", None)
        if tab_widget is None: return
        tab = self.current_tab()
        if tab is None or tab.is_suspended or tab.view is None:
            self.back_btn.setEnabled(False)
            self.forward_btn.setEnabled(False)
            return
        history = tab.view.history()
        self.back_btn.setEnabled(history.canGoBack())
        self.forward_btn.setEnabled(history.canGoForward())

    def _on_url_text_edited(self, text: str):
        text = text.strip()
        self._current_url_text = text
        if not text:
            self._hide_suggestions()
            self._remote_suggester.cancel()
            return
        local = gather_local_suggestions(text, load_bookmarks(), self.session_history)
        self._current_local_entries = [{"kind": e["kind"], "title": e["title"], "subtitle": e["subtitle"], "value": e["url"]} for e in local]
        self._render_suggestions(text, remote_items=[])
        if self.settings.current.get("search_suggestions", True): self._remote_suggester.request(text)
        else: self._remote_suggester.cancel()

    def _on_remote_suggestions(self, query: str, items: list):
        if query == self._current_url_text:
            self._render_suggestions(query, items)

    def _render_suggestions(self, text: str, remote_items: list):
        entries = []
        seen_values = set()
        engine_label = search_engine_label(
            self.settings.current.get("search_engine", "brave"), self.lang)
        entries.append({"kind": "search", "title": f'“{text}” için ara' if self.lang == "tr" else f'Search for “{text}”', "subtitle": engine_label, "value": text, "primary": True})
        seen_values.add(text.lower())
        for e in self._current_local_entries:
            if e["value"].lower() not in seen_values:
                entries.append(e)
                seen_values.add(e["value"].lower())
        for s in remote_items:
            if s.lower() not in seen_values:
                entries.append({"kind": "search", "value": s, "title": s, "subtitle": "Arama önerisi" if self.lang == "tr" else "Search suggestion"})
                seen_values.add(s.lower())
        self._show_suggestions(entries, query=text)

    def _show_suggestions(self, entries: list, query: str = ""):
        theme = "light" if self.settings.current["ui_theme"] == "light" else "dark"
        accent = gem_theme.get_accent_color(self.settings.current)
        popup_key = (theme, accent)
        # Tema VEYA vurgu rengi değiştiyse popup'ı yeniden kur — satır
        # vurguları vurgu renginden türetildiği için sadece tema takibi
        # yetmezdi (renk değişince eski renkli popup ekranda kalırdı).
        if self._suggestion_popup is None or getattr(self, "_suggestion_popup_key", None) != popup_key:
            if self._suggestion_popup is not None:
                self._suggestion_popup.hide()
                self._suggestion_popup.deleteLater()
            self._suggestion_popup = SuggestionPopup(self, theme=theme, accent=accent)
            self._suggestion_popup.item_chosen.connect(self._on_suggestion_chosen)
            self._suggestion_popup_key = popup_key

            hl_bg = "rgba(255, 255, 255, 0.15)" if theme == "dark" else "rgba(0, 0, 0, 0.1)"
            self._suggestion_popup.setStyleSheet(f"""
                QListWidget::item:selected {{ background-color: {hl_bg}; border-radius: 6px; font-weight: bold; }}
                *[selected="true"] {{ background-color: {hl_bg}; border-radius: 6px; font-weight: bold; }}
            """)

        self._suggestion_popup.set_entries(entries, query=query)
        self._suggestion_popup.position_below(self.url_bar)
        self._suggestion_popup.show()

    def _hide_suggestions(self):
        if self._suggestion_popup is not None: self._suggestion_popup.hide()

    def _on_suggestion_chosen(self, kind: str, value: str):
        self._hide_suggestions()
        self._remote_suggester.cancel()
        tab = self.current_tab()
        if not tab: return
        if tab.is_suspended: tab.restore()
        self._enforce_max_live_tabs()

        if kind in ("bookmark", "history"):
            self._set_url_bar_text(value)
            tab.view.setUrl(QUrl(value))
        else:
            self._set_url_bar_text(value)
            tab.view.setUrl(QUrl(build_search_url(
                value,
                self.settings.current.get("search_engine", "brave"),
                self.settings.current.get("custom_search_url", ""),
            )))
        self.url_bar.clearFocus()

    def _fullscreen_view_tab(self):
        """Video tam ekranında olan (view'i bağımsız pencere yapılmış) sekmeyi
        döndürür; yoksa None."""
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if isinstance(tab, BrowserTab) and getattr(tab, "_is_fullscreen_view", False):
                return tab
        return None

    def eventFilter(self, obj, event):
        if obj is self.url_bar and self._suggestion_popup is not None and self._suggestion_popup.isVisible():
            if event.type() == event.Type.KeyPress:
                key = event.key()
                if key == Qt.Key.Key_Down:
                    self._suggestion_popup.move_selection(1)
                    return True
                if key == Qt.Key.Key_Up:
                    self._suggestion_popup.move_selection(-1)
                    return True
                if key == Qt.Key.Key_Escape:
                    self._hide_suggestions()
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    entry = self._suggestion_popup.current_entry()
                    if entry is not None:
                        self._on_suggestion_chosen(entry[0], entry[1])
                        return True
            elif event.type() == event.Type.FocusOut:
                QTimer.singleShot(150, self._hide_suggestions)

        # --- Uygulama genelinde tuş yakalama (bkz. __init__ notu) ---
        # QAction kısayolları, Chromium'un ShortcutOverride ile rezerve
        # ettiği tuşlarda (F5/Ctrl+R/ESC) çalışmaz; bu tuşlar burada,
        # teslimatın en erken noktasında yakalanır. F5 QAction'ı bilerek
        # duruyor: odak web görünümünde DEĞİLken (ör. araç çubuğu) yine
        # QAction üzerinden çalışır; ikisi asla çifte tetiklenmez (kısayol
        # tüketilirse KeyPress teslim edilmez; teslim edilirse QAction
        # zaten ateşlenmemiştir).
        #
        # Çoklu pencere notu: her MainWindow bu filtreyi kurar; yalnızca
        # OLAYIN ait olduğu pencere işlemeli. F5/Ctrl+F için "aktif pencere
        # benim"; ESC için ek olarak "aktif pencere, benim sekmemin
        # bağımsız tam ekran görüntüleyicisi" durumu da geçerlidir (video
        # tam ekranındayken aktif pencere MainWindow değil, view'in
        # kendisidir).
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            mods = event.modifiers()
            ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
            shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            tab_fs = self._fullscreen_view_tab()
            fs_window_active = (
                tab_fs is not None
                and QApplication.activeWindow() is tab_fs.view
            )
            window_active = self.isActiveWindow()

            if key == Qt.Key.Key_F5 or (ctrl and key == Qt.Key.Key_R):
                if window_active or fs_window_active:
                    self._reload_page()
                    return True
            elif key == Qt.Key.Key_Escape:
                if tab_fs is not None and (window_active or fs_window_active):
                    # Sayfa tarafının fullscreen durumunu da düzgün kapat.
                    if tab_fs.web_page is not None:
                        try:
                            tab_fs.web_page.runJavaScript(
                                "if(document.fullscreenElement){document.exitFullscreen();}")
                        except RuntimeError:
                            pass
                    tab_fs._exit_view_fullscreen()
                    return True
            elif ctrl and key == Qt.Key.Key_F:
                if window_active or fs_window_active:
                    self._find_in_page()
                    return True
            elif key == Qt.Key.Key_F12:
                if window_active or fs_window_active:
                    self._toggle_devtools()
                    return True
            elif ctrl and key == Qt.Key.Key_P:
                if window_active:
                    self._print_page()
                    return True
            elif ctrl and key == Qt.Key.Key_D:
                if window_active:
                    self._toggle_bookmark()
                    return True
            elif ctrl and key == Qt.Key.Key_S:
                if window_active:
                    self._save_page()
                    return True
            elif ctrl and key == Qt.Key.Key_U:
                if window_active:
                    self._view_source()
                    return True
            elif ctrl and key == Qt.Key.Key_M:
                if window_active:
                    self._toggle_tab_mute()
                    return True
            elif ctrl and key == Qt.Key.Key_A and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                if window_active:
                    self._tab_search()
                    return True
            elif ctrl and key == Qt.Key.Key_Delete and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                if window_active:
                    self._open_clear_data()
                    return True
            elif ctrl and key == Qt.Key.Key_W:
                if window_active:
                    self.close_tab(self.tab_widget.currentIndex())
                    return True
            elif ctrl and key == Qt.Key.Key_L:
                if window_active:
                    self._focus_url_bar()
                    return True
            elif ctrl and key == Qt.Key.Key_Tab:
                if window_active:
                    self._cycle_tab(1)
                    return True
            elif ctrl and key == Qt.Key.Key_Backtab:
                if window_active:
                    self._cycle_tab(-1)
                    return True
            elif key == Qt.Key.Key_Left and event.modifiers() & Qt.KeyboardModifier.AltModifier:
                if window_active or fs_window_active:
                    self._navigate_back()
                    return True
            elif key == Qt.Key.Key_Right and event.modifiers() & Qt.KeyboardModifier.AltModifier:
                if window_active or fs_window_active:
                    self._navigate_forward()
                    return True
            elif ctrl and Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
                if window_active:
                    self._goto_tab_number(key - Qt.Key.Key_0)
                    return True
        return super().eventFilter(obj, event)

    def _open_new_window(self):
        new_win = MainWindow()
        _active_windows.append(new_win)
        new_win.show()

    def _open_incognito_window(self):
        new_win = MainWindow(profile=QWebEngineProfile())
        _active_windows.append(new_win)
        new_win.show()

    def _create_page_for_new_window(self, window_type):
        if window_type in (QWebEnginePage.WebWindowType.WebBrowserWindow, QWebEnginePage.WebWindowType.WebDialog):
            # MainWindow, kurucudaki _startup_initial_url sayesinde zaten TEK
            # bir about:blank sekmesiyle açılır; eskiden hem kurucu hem de
            # aşağıdaki add_new_tab birer sekme açtığı için her popup/target=
            # _blank penceresi fazladan bir "Yeni Sekme" ile gelirdi.
            blank = QUrl("about:blank")
            new_win = (MainWindow(profile=self.shared_profile, initial_url=blank)
                       if self.is_incognito else MainWindow(initial_url=blank))
            _active_windows.append(new_win)
            new_win.show()
            tab = new_win.current_tab()
            return tab.web_page if tab is not None else new_win.add_new_tab(blank).web_page
        else:
            return self.add_new_tab(QUrl("about:blank"), switch_to=(window_type != QWebEnginePage.WebWindowType.WebBrowserBackgroundTab)).web_page

    def _open_downloads_dialog(self):
        dlg = DownloadsDialog(self)
        # exec() kapandıktan sonra C++ nesnesi parent'a child olarak takılı
        # kalıyordu (history_changed bağlantısıyla birlikte sızıyordu);
        # WA_DeleteOnClose ile kapanır kapanmaz silinir.
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.exec()

    def _open_history(self):
        dlg = HistoryDialog(self.persistent_history, self.lang, self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.exec()

    def _open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        if dlg.exec():
            self._apply_settings_to_browser()

    def _zoom_in(self): tab = self.current_tab(); (tab.zoom_in() if isinstance(tab, BrowserTab) and not tab.is_suspended else None)
    def _zoom_out(self): tab = self.current_tab(); (tab.zoom_out() if isinstance(tab, BrowserTab) and not tab.is_suspended else None)
    def _zoom_reset(self): tab = self.current_tab(); (tab.zoom_reset() if isinstance(tab, BrowserTab) and not tab.is_suspended else None)

    def _set_as_default_browser(self):
        try: gem_default_browser.set_as_default_browser()
        except gem_default_browser.DefaultBrowserError as exc:
            show_modern_info(self, str(exc), lang=self.lang, warning=True)
            return
        show_modern_info(self, "GEM Browser varsayılan tarayıcı olarak ayarlandı." if self.lang == "tr" else "GEM Browser is now set as the default browser.", lang=self.lang)

    def _setup_tabs(self):
        self.tab_widget = QTabWidget(self)
        self.tab_widget.setTabBar(ProgressTabBar(self.tab_widget, self.tab_widget))
        self._tab_left_align_style = _LeftAlignedTabStyle()
        self.tab_widget.tabBar().setStyle(self._tab_left_align_style)
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self.tab_widget.tabBar().pin_toggle_requested.connect(self._toggle_pin_tab)

        self.new_tab_btn = _PlusToolButton(self.tab_widget.tabBar())
        self.tab_widget.tabBar().new_tab_btn = self.new_tab_btn
        self.new_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_tab_btn.setFixedSize(28, 28)

        self.new_tab_btn.clicked.connect(lambda: self.add_new_tab())
        self.tab_widget.tabBar()._update_btn_pos()

        self._vertical_mode = bool(self.settings.current.get("vertical_tabs", False))

        self.tabs_container = QWidget(self)
        self.tabs_container.setObjectName("tabsContainer")
        container_layout = QHBoxLayout(self.tabs_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        self.vertical_sidebar = _CollapsibleSidebar(self.tabs_container)

        self._sidebar_content = QWidget()
        self._sidebar_content.setMinimumWidth(220)
        self._sidebar_layout = QVBoxLayout(self._sidebar_content)
        self._sidebar_layout.setContentsMargins(6, 8, 6, 8)
        self._sidebar_layout.setSpacing(2)

        self._sidebar_new_tab_btn = _PlusToolButton(self._sidebar_content)
        self._sidebar_new_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sidebar_new_tab_btn.setFixedSize(28, 28)
        self._sidebar_new_tab_btn.clicked.connect(lambda: self.add_new_tab())

        # Sidebarı sabitleme butonu (+ ikonunun bulunduğu üst sıranın sağında)
        self.sidebar_pin_btn = QToolButton(self._sidebar_content)
        self.sidebar_pin_btn.setFixedSize(28, 28)
        self.sidebar_pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sidebar_pin_btn.setToolTip("Sidebarı Sabitle" if self.lang == "tr" else "Pin Sidebar")
        self.sidebar_pin_btn.clicked.connect(self._toggle_sidebar_pin)
        self._sidebar_pinned = False

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(12, 0, 8, 0)
        btn_layout.addWidget(self._sidebar_new_tab_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.sidebar_pin_btn)

        self._sidebar_layout.addLayout(btn_layout)
        self._sidebar_layout.addStretch(1)

        # Alt İkonlar İçin Responsive Dock Widget
        self._sidebar_dock = QWidget(self._sidebar_content)
        dock_layout = QHBoxLayout(self._sidebar_dock)
        dock_layout.setContentsMargins(12, 10, 12, 10)
        dock_layout.setSpacing(12)

        self.sidebar_dl_btn = QToolButton(self._sidebar_dock)
        self.sidebar_dl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sidebar_dl_btn.setFixedSize(28, 28)
        self.sidebar_dl_btn.clicked.connect(self._open_downloads_dialog)

        self.sidebar_hist_btn = QToolButton(self._sidebar_dock)
        self.sidebar_hist_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sidebar_hist_btn.setFixedSize(28, 28)
        self.sidebar_hist_btn.clicked.connect(self._open_history)

        self.sidebar_set_btn = QToolButton(self._sidebar_dock)
        self.sidebar_set_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sidebar_set_btn.setFixedSize(28, 28)
        self.sidebar_set_btn.clicked.connect(self._open_settings)

        dock_layout.addWidget(self.sidebar_dl_btn)
        dock_layout.addWidget(self.sidebar_hist_btn)
        dock_layout.addWidget(self.sidebar_set_btn)
        dock_layout.addStretch()

        self._sidebar_layout.addWidget(self._sidebar_dock)

        self.vertical_sidebar.setWidget(self._sidebar_content)
        self.vertical_sidebar.hide()

        container_layout.addWidget(self.vertical_sidebar)
        container_layout.addWidget(self.tab_widget, 1)
        self.main_layout.addWidget(self.tabs_container)

        self._apply_tab_layout_mode()

    def _apply_tab_layout_mode(self):
        if self._vertical_mode:
            self.tab_widget.tabBar().hide()
            self.vertical_sidebar.show()
            self._rebuild_vertical_sidebar()
        else:
            self.tab_widget.tabBar().show()
            self.vertical_sidebar.hide()
        if hasattr(self, "vertical_tabs_btn"):
            active_bg = "rgba(128, 128, 128, 0.28)" if self._vertical_mode else "transparent"
            self.vertical_tabs_btn.setStyleSheet(
                "QToolButton { padding: 6px 10px; border: none; border-radius: 8px; "
                f"background: {active_bg}; }} "
                "QToolButton:hover { background: rgba(128, 128, 128, 0.2); }"
            )

    def _toggle_sidebar_pin(self):
        self._sidebar_pinned = not self._sidebar_pinned
        self.vertical_sidebar.set_pinned(self._sidebar_pinned)
        self._update_sidebar_pin_button()

    def _update_sidebar_pin_button(self):
        if not hasattr(self, "sidebar_pin_btn"):
            return
        accent = gem_theme.get_accent_color(self.settings.current)
        if self._sidebar_pinned:
            self.sidebar_pin_btn.setIcon(gem_icons.get_icon("pin", accent, size=16))
            self.sidebar_pin_btn.setToolTip(
                "Sidebarı Sabitini Kaldır" if self.lang == "tr" else "Unpin Sidebar")
        else:
            muted = "#777777" if self.settings.current["ui_theme"] == "light" else "#888888"
            self.sidebar_pin_btn.setIcon(gem_icons.get_icon("pin", muted, size=16))
            self.sidebar_pin_btn.setToolTip(
                "Sidebarı Sabitle" if self.lang == "tr" else "Pin Sidebar")

    def _toggle_vertical_tabs(self):
        self._vertical_mode = not self._vertical_mode
        self.settings.current["vertical_tabs"] = self._vertical_mode
        self.settings.save()
        self._apply_tab_layout_mode()

    def _rebuild_vertical_sidebar(self):
        if not getattr(self, "_vertical_mode", False):
            self._sidebar_rows = {}
            return

        # Sabit obje sayımız 3'e çıktığı için (Yeni Sekme, Boşluk, Alt İkonlar)
        # burayı > 3 yapıyoruz ki aradaki boşluğu (Stretch) silmesin.
        while self._sidebar_layout.count() > 3:
            item = self._sidebar_layout.takeAt(1)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        self._sidebar_rows = {}
        current = self.current_tab()
        pinned_rows, normal_rows = [], []
        is_light = self.settings.current["ui_theme"] == "light"
        accent = gem_theme.get_accent_color(self.settings.current)
        bar = self.tab_widget.tabBar()
        progress_map = bar.progress_map if isinstance(bar, ProgressTabBar) else {}

        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if not isinstance(tab, BrowserTab):
                continue
            pinned = bool(tab.property("pinned"))
            title = getattr(tab, "_gem_full_title", None) or self.tab_widget.tabText(i) or ("Yeni Sekme" if self.lang == "tr" else "New Tab")
            row = _SidebarTabRow(
                tab=tab, title=title, icon=self.tab_widget.tabIcon(i),
                pinned=pinned, selected=(tab is current), is_light=is_light, lang=self.lang,
                accent=accent,
            )
            # Yeniden kurulum yükleme ortasında olsa bile çizgi kaybolmasın
            row.set_progress(progress_map.get(tab))
            row.activated.connect(lambda t=tab: self._activate_tab_from_sidebar(t))
            row.close_requested.connect(lambda t=tab: self.close_tab(self.tab_widget.indexOf(t)))
            row.pin_toggle_requested.connect(lambda t=tab: self._toggle_pin_tab(t))
            self._sidebar_rows[tab] = row
            (pinned_rows if pinned else normal_rows).append(row)

        insert_at = 1
        for row in pinned_rows + normal_rows:
            self._sidebar_layout.insertWidget(insert_at, row)
            insert_at += 1

    def _activate_tab_from_sidebar(self, tab):
        index = self.tab_widget.indexOf(tab)
        if index != -1:
            self.tab_widget.setCurrentIndex(index)

    def _toggle_pin_tab(self, tab):
        if tab is None:
            return
        bar = self.tab_widget.tabBar()
        pinned_now = not bool(tab.property("pinned"))
        tab.setProperty("pinned", pinned_now)
        index = self.tab_widget.indexOf(tab)
        if index == -1:
            return

        pinned_count = sum(
            1 for i in range(self.tab_widget.count())
            if bool(self.tab_widget.widget(i).property("pinned"))
        )
        if pinned_now:
            bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
            target = pinned_count - 1
            if index != target:
                bar.moveTab(index, target)
        else:
            bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, self._make_close_button(tab))
            cur_index = self.tab_widget.indexOf(tab)
            if cur_index < pinned_count:
                bar.moveTab(cur_index, pinned_count)

        index = self.tab_widget.indexOf(tab)
        title = getattr(tab, "_gem_full_title", None) or self.tab_widget.tabText(index) or self.tab_widget.tabToolTip(index)
        self._update_tab_title(tab, title)

        bar.updateGeometry()
        bar._update_btn_pos()
        bar.update()
        self._rebuild_vertical_sidebar()

    def _ensure_vault_unlocked(self) -> bool:
        if self.is_incognito: return False
        if self.vault is not None: return True

        mode = "unlock" if vault_exists() else "create"
        attempts = 3
        while attempts > 0:
            dlg = MasterPasswordDialog(mode=mode, lang=self.lang, parent=self)
            if dlg.exec() != QDialog.DialogCode.Accepted: return False
            try:
                self.vault = PasswordVault(dlg.get_password())
                self._reset_vault_lock_timer()
                return True
            except WrongMasterPassword:
                attempts -= 1
                mode = "unlock"
                show_modern_info(self, "Yanlış ana parola." if self.lang == "tr" else "Wrong master password.", lang=self.lang, warning=True)
            except CorruptVault as exc:
                # Bozuk meta dosyası: parolayı tekrar sormak çözüm değil,
                # yakalanmayan istisna da uygulamayı çökertiyordu.
                msg = ("Şifre kasası meta dosyası bozuk; kasa açılamadı. Detay: " if self.lang == "tr"
                       else "The vault metadata file is corrupt; the vault cannot be opened. Detail: ") + str(exc)
                show_modern_info(self, msg, lang=self.lang, warning=True)
                return False
        return False

    def _reset_vault_lock_timer(self):
        # "Oturum boyunca açık kalsın" seçiliyken otomatik kilitleme yok:
        # kasa yalnızca tarayıcı kapatılınca iner.
        if self.vault is not None and not self.settings.current.get("vault_session_unlock", False):
            self.vault_lock_timer.start()

    def _lock_vault(self):
        if self.vault is not None: self.vault = None

    def _open_password_manager(self):
        if self.is_incognito or not self._ensure_vault_unlocked(): return
        dlg = PasswordManagerDialog(self.vault, self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.exec()
        self._reset_vault_lock_timer()

    def add_new_tab(self, url: QUrl = None, switch_to: bool = True):
        tab = BrowserTab(
            profile=self.shared_profile,
            initial_url=url or QUrl(self._new_tab_url()),
            parent=self.tab_widget,
            download_manager=self.download_manager,
            lang=self.lang,
            new_page_callback=self._create_page_for_new_window
        )

        bg_col = QColor("#f5f5f5" if self.settings.current["ui_theme"] == "light" else "#1a1a1a")
        if getattr(tab, "view", None) and tab.view.page():
            tab.view.page().setBackgroundColor(bg_col)

        index = self.tab_widget.addTab(tab, "Yeni Sekme" if self.lang == "tr" else "New Tab")
        bar = self.tab_widget.tabBar()
        if isinstance(bar, ProgressTabBar): bar.animate_tab_in(tab)

        interval_ms = self._suspend_interval_ms()
        if interval_ms > 0:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(interval_ms)
            timer.timeout.connect(lambda t=tab: self._auto_suspend_tab(t))
            self.tab_timers[tab] = timer

        tab.title_changed.connect(lambda title, t=tab: self._update_tab_title(t, title))
        tab.url_changed.connect(lambda u, t=tab: self._update_tab_url(t, u))
        tab.gem_action_triggered.connect(lambda u, t=tab: self._handle_gem_action(t, u))
        tab.pdf_open_requested.connect(lambda u, t=tab: self._open_pdf_flow(t, u))
        tab.audio_state_changed.connect(lambda m, a, t=tab: self._update_tab_audio(t, m, a))
        tab.icon_changed.connect(lambda icon, t=tab: self._update_tab_icon(t, icon))
        tab.load_finished.connect(lambda ok, t=tab: self._schedule_autofill_check(t, ok))
        tab.load_finished.connect(lambda ok, t=tab: self._update_tab_progress(t, None))
        tab.load_finished.connect(lambda ok, t=tab: self._record_history(t) if ok else None)
        tab.load_progress.connect(lambda val, t=tab: self._update_tab_progress(t, val))
        tab.url_changed.connect(lambda u, t=tab: self._update_nav_buttons() if t == self.current_tab() else None)
        tab.load_finished.connect(lambda ok, t=tab: self._update_nav_buttons() if t == self.current_tab() else None)

        self.tab_widget.setTabIcon(index, self._app_icon())
        self.tab_widget.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, self._make_close_button(tab))

        if switch_to:
            self.tab_widget.setCurrentIndex(index)
            self._update_nav_buttons()
        self._rebuild_vertical_sidebar()
        self._enforce_max_live_tabs()
        return tab

    def _make_close_button(self, tab: BrowserTab) -> QToolButton:
        normal_color = "#777777" if self.settings.current["ui_theme"] == "light" else "#888888"
        btn = QToolButton()
        btn.setText("×")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedSize(33, 18)
        btn.setStyleSheet(
            "QToolButton { background: transparent; border: none; border-radius: 9px; "
            f"color: {normal_color}; font-size: 15px; font-weight: bold; padding: 0px; margin: 0px 15px 0px 0px; }} "
            "QToolButton:hover { background-color: rgba(255, 85, 85, 0.18); color: #ff5555; }"
        )
        btn.clicked.connect(lambda: self.close_tab(self.tab_widget.indexOf(tab)))
        return btn

    def _refresh_close_buttons(self):
        normal_color = "#777777" if self.settings.current["ui_theme"] == "light" else "#888888"
        bar = self.tab_widget.tabBar()
        for i in range(self.tab_widget.count()):
            btn = bar.tabButton(i, QTabBar.ButtonPosition.RightSide)
            if isinstance(btn, QToolButton):
                btn.setStyleSheet(
                    "QToolButton { background: transparent; border: none; border-radius: 9px; "
                    f"color: {normal_color}; font-size: 15px; font-weight: bold; padding: 0px; margin: 0px 15px 0px 0px; }} "
                    "QToolButton:hover { background-color: rgba(255, 85, 85, 0.18); color: #ff5555; }"
                )

    def _update_tab_progress(self, tab: BrowserTab, value):
        bar = self.tab_widget.tabBar()
        if isinstance(bar, ProgressTabBar):
            bar.set_progress(tab, None if value is not None and value >= 100 else value)
        # Dikey sidebar'daki yükleme çizgisi: yatay bar ile birebir aynı değer
        row = self._sidebar_rows.get(tab)
        if row is not None:
            try:
                row.set_progress(None if value is not None and value >= 100 else value)
            except RuntimeError:
                # satır az önce deleteLater edilmiş olabilir
                self._sidebar_rows.pop(tab, None)

    def _open_pdf_flow(self, tab, url: QUrl):
        """PDF gezinmesi: yerel dosya doğrudan görüntüleyicide; uzak PDF
        Qt tarafında sessizce indirilip (CORS'suz) yerel kopyadan açılır.
        (tab, url) — pdf_open_requested sinyalinden gelir."""
        if self.tab_widget.indexOf(tab) == -1:
            return
        if tab.is_suspended:
            tab.restore()
        if tab.view is None:
            return

        if url.scheme() == "file":
            local = url.toLocalFile()
            if not local or not os.path.exists(local):
                show_modern_info(
                    self,
                    "Dosya bulunamadı." if self.lang == "tr" else "File not found.",
                    lang=self.lang, warning=True)
                return
            target = pdf_viewer.build_viewer_url(url.toString())
            if target:
                tab.view.load(QUrl(target))
            return

        # http/https: arka planda indir. Bekleyen istek işareti: indirme
        # sürerken kullanıcı başka sayfaya giderse, indirme bitince
        # görüntüleyici yeni sayfanın ÜSTÜNE yüklenmesin.
        tab._gem_pdf_pending = url.toString()
        tab._gem_pdf_fetching = True
        if not hasattr(self, "_pdf_fetch_threads"):
            self._pdf_fetch_threads = []
        # bitenleri temizle (referans birikmesin)
        self._pdf_fetch_threads = [t for t in self._pdf_fetch_threads if t.isRunning()]
        thread = PdfFetchThread(url.toString(), self)
        self._pdf_fetch_threads.append(thread)
        thread.done_ok.connect(
            lambda src, path, t=tab: self._on_pdf_fetched(t, src, path))
        thread.done_err.connect(
            lambda src, err, t=tab: self._on_pdf_fetch_failed(t, src, err))
        thread.start()

    def _on_pdf_fetched(self, tab, source_url: str, local_path: str):
        if self.tab_widget.indexOf(tab) == -1:
            return
        tab._gem_pdf_fetching = False
        if getattr(tab, "_gem_pdf_pending", None) != source_url:
            return  # kullanıcı bu isteği beklemiyor artık (baska sayfaya gitti)
        tab._gem_pdf_pending = None
        if tab.is_suspended:
            tab.restore()
        if tab.view is None:
            return
        from urllib.parse import unquote as _unquote
        display = _unquote(os.path.basename(QUrl(source_url).path())) or "belge.pdf"
        target = pdf_viewer.build_viewer_url(
            QUrl.fromLocalFile(local_path).toString(), display_name=display,
            download_url=source_url)
        if target:
            tab.view.load(QUrl(target))

    def _on_pdf_fetch_failed(self, tab, source_url: str, error: str):
        if self.tab_widget.indexOf(tab) == -1:
            return
        tab._gem_pdf_fetching = False
        if getattr(tab, "_gem_pdf_pending", None) == source_url:
            tab._gem_pdf_pending = None
        msg = ("PDF indirilemedi: " if self.lang == "tr" else "Could not download the PDF: ") + error
        show_modern_info(self, msg, lang=self.lang, warning=True)

    def _handle_gem_action(self, tab, url):
        url_str = url.toString()
        if "gemaction://" in url_str:
            bookmarks = load_bookmarks()
            if "request_add_bookmark" in url_str:
                dlg = BookmarkDialog(self)
                if dlg.exec():
                    name, b_url = dlg.get_data()
                    if name and b_url:
                        bookmarks.append({"name": name, "url": b_url if b_url.startswith("http") else f"https://{b_url}"})
                        save_bookmarks(bookmarks)
                        self._refresh_new_tab_page(tab)
            elif "request_remove_bookmark" in url_str:
                b_url = parse_qs(urlparse(url_str).query).get("url", [""])[0]
                if b_url and show_modern_confirm(self, "Bu favoriyi silmek istiyor musunuz?" if self.lang == "tr" else "Do you want to delete this bookmark?", title="Favoriyi Sil" if self.lang == "tr" else "Delete Bookmark", lang=self.lang, danger=True):
                    save_bookmarks([b for b in bookmarks if b["url"] != b_url])
                    self._refresh_new_tab_page(tab)

    def _find_in_page(self):
        tab = self.current_tab()
        if isinstance(tab, BrowserTab) and not tab.is_suspended:
            tab.show_find_bar()

    def _toggle_window_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            # Tam ekrana geçmeden önce ekranı kaplıyorsa o haline dön.
            if getattr(self, "_was_maximized", False):
                self.showMaximized()
        else:
            self._was_maximized = self.isMaximized()
            self.showFullScreen()

    def _suspend_interval_ms(self) -> int:
        """Ayarlanan uyutma süresinin milisaniye karşılığı; 0 = asla
        uyutma. Düşük RAM modu süreyi yarıya indirir (4 dk -> 2 dk,
        eski davranışla uyumlu)."""
        try:
            mins = float(self.settings.current.get("tab_suspend_minutes", 4.0))
        except (TypeError, ValueError):
            mins = 4.0
        if mins <= 0:
            return 0
        if self.settings.current.get("low_ram_mode", False):
            mins /= 2.0
        return int(mins * 60 * 1000)

    def _update_suspend_timers(self):
        """Ayar değişince mevcut sekmelerin uyutma zamanlayıcılarını
        (yeni süreye güncelle / tamamen kaldır / eksikse oluştur)."""
        interval_ms = self._suspend_interval_ms()
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if not isinstance(tab, BrowserTab):
                continue
            timer = self.tab_timers.get(tab)
            if interval_ms <= 0:
                if timer is not None:
                    timer.stop()
                    del self.tab_timers[tab]
            else:
                if timer is None:
                    timer = QTimer(self)
                    timer.setSingleShot(True)
                    timer.timeout.connect(lambda t=tab: self._auto_suspend_tab(t))
                    self.tab_timers[tab] = timer
                timer.setInterval(interval_ms)

    def _enforce_max_live_tabs(self):
        """Canlı sekme sınırı: sınır aşılırsa EN ESKİ arka plan sekmeleri
        anında uyutulur. Video oynatan sekmeler _auto_suspend_tab
        tarafından atlanır. Adaylar sekme çubuğu sırasından okunur —
        tab_timers'a BAKMA: 'asla uyutma' modunda zamanlayıcı hiç
        oluşturulmaz ve sınır mekanizması aday bulamazdı."""
        try:
            limit = int(self.settings.current.get("max_live_tabs", 0))
        except (TypeError, ValueError):
            limit = 0
        if limit <= 0:
            return
        current = self.current_tab()
        bg_live = []
        for i in range(self.tab_widget.count()):
            t = self.tab_widget.widget(i)
            if (isinstance(t, BrowserTab) and t is not current
                    and not t.is_suspended and t.view is not None):
                bg_live.append(t)
        total_live = len(bg_live) + (1 if isinstance(current, BrowserTab) and not current.is_suspended else 0)
        while total_live > limit and bg_live:
            victim = bg_live.pop(0)
            if self._auto_suspend_tab(victim):
                total_live -= 1

    def _auto_suspend_tab(self, tab) -> bool:
        if tab.is_suspended or tab == self.current_tab():
            return False
        if tab.view is not None and tab.web_page is not None and tab.web_page.recentlyAudible():
            if tab in self.tab_timers: self.tab_timers[tab].start()
            return False
        tab.suspend()
        index = self.tab_widget.indexOf(tab)
        if index != -1:
            self.tab_widget.setTabIcon(index, gem_icons.get_icon("moon", "#8a8a8a"))
        self._update_sleep_status()
        self._rebuild_vertical_sidebar()
        return True

    def _update_sleep_status(self):
        if not hasattr(self, "tab_widget") or not hasattr(self, "sleep_status_label"):
            return
        total = 0
        sleeping = 0
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if isinstance(tab, BrowserTab):
                total += 1
                if tab.is_suspended:
                    sleeping += 1
        if sleeping > 0:
            self.sleep_status_label.setText(f"🌙 {sleeping}/{total}")
            self.sleep_status_label.setToolTip(
                f"{sleeping} sekme RAM tasarrufu için uykuda. Uyandırmak için sekmeye tıklayın." if self.lang == "tr"
                else f"{sleeping} tab(s) sleeping to save RAM. Click a tab to wake it up."
            )
            self.sleep_status_label.show()
        else:
            self.sleep_status_label.hide()

    def _update_tab_icon(self, tab: BrowserTab, icon: QIcon):
        index = self.tab_widget.indexOf(tab)
        if index != -1:
            # Sıra dışı durumlarda (suspend/cleanup sonrası gelen kuyruktaki
            # sinyal) view None olabilir; silinmiş nesneye dokunma.
            url_str = tab.saved_url.toString() if tab.is_suspended else (tab.view.url().toString() if tab.view is not None else "")
            if _is_gem_internal_page(url_str):
                icon = self._app_icon()
            elif icon is None or icon.isNull():
                # favicon'suz harici sayfa: boş ikon yerine soluk küre
                muted_col = "#777777" if self.settings.current["ui_theme"] == "light" else "#999999"
                icon = gem_icons.get_icon("globe", muted_col, size=16)
            # Ses göstergesi kapalıyken geri dönülebilsin diye son "normal"
            # ikonu sakla.
            tab._gem_base_icon = QIcon(icon)
            self.tab_widget.setTabIcon(index, icon)
            row = self._sidebar_rows.get(tab)
            if row is not None:
                try:
                    row.set_icon(icon)
                except RuntimeError:
                    self._sidebar_rows.pop(tab, None)
                    self._rebuild_vertical_sidebar()

    # ---------------- Otomatik doldurma (teklif tabanlı) ----------------

    def _tab_is_live(self, tab) -> bool:
        """Zamanlanmış yoklama/gecikme penceresi içinde sekme kapatılmış
        olabilir: silinmiş C++ nesnesine dokunmadan yaşadığını doğrula.
        (Kapatılan sekmenin 400/2000/5000 ms'lik doldurma yoklamaları
        ateşlenmeye devam ediyordu ve silinmiş BrowserTab'a erişim
        RuntimeError -> qFatal ile uygulamayı düşürüyordu.)"""
        try:
            return (isinstance(tab, BrowserTab)
                    and self.tab_widget.indexOf(tab) != -1
                    and not tab.is_suspended
                    and tab.view is not None)
        except RuntimeError:
            return False

    def _schedule_autofill_check(self, tab: BrowserTab, ok: bool):
        """Sayfa yüklendiğinde şifre alanlarını birkaç aşamada yokla:
        SPA'larda form sayfa yüklendikten SONRA DOM'a ekleniyor; tek deneme
        kaçırıyordu. Her yeni yükleme teklif hakkını sıfırlar."""
        if not ok or tab.is_suspended or tab.view is None:
            return
        url_str = tab.view.url().toString()
        if not (url_str.startswith("http://") or url_str.startswith("https://")):
            return
        tab._gem_autofill_offered_url = None
        for delay in (400, 2000, 5000):
            QTimer.singleShot(delay, lambda t=tab, u=url_str: self._autofill_probe(t, u))

    def _autofill_probe(self, tab: BrowserTab, expected_url: str):
        if not self._tab_is_live(tab):
            return  # sekme bu süreçte kapatılmış/gecikmiş
        try:
            if tab.view.url().toString() != expected_url:
                return  # kullanıcı bu sırada başka yere gitti
            tab.view.page().runJavaScript(
                "document.querySelectorAll('input[type=password]').length",
                lambda n: self._autofill_password_fields_found(tab, expected_url, n))
        except RuntimeError:
            pass  # sekme ara olayda silindiyse sessizce çık

    def _autofill_password_fields_found(self, tab: BrowserTab, url: str, count):
        try:
            count = int(count) if count is not None else 0
        except (TypeError, ValueError):
            return
        if count <= 0 or not self._tab_is_live(tab):
            return
        try:
            if tab.view.url().toString() != url:
                return
        except RuntimeError:
            return  # sekme ara olayda silindi
        if getattr(tab, "_gem_autofill_offered_url", None) == url:
            return  # bu yükleme için teklif gösterildi
        if self.is_incognito:
            return
        # Kasa kilitliyse (normalde 10 dk sonra kilitlenir) açılmasını TEKLİF ET
        if self.vault is None:
            if not vault_exists():
                return
            ok = show_modern_confirm(
                self,
                "Bu sayfada bir oturum formu algılandı. Kayıtlı şifreniz "
                "kasada saklı olabilir; doldurmak için kasanın kilidini açın."
                if self.lang == "tr" else
                "A login form was detected on this page. Your saved password "
                "may be in the vault; unlock the vault to fill it.",
                title="Şifre Otomatik Doldurma" if self.lang == "tr" else "Autofill Password",
                lang=self.lang)
            if not ok:
                tab._gem_autofill_offered_url = url
                return
            if not self._ensure_vault_unlocked():
                tab._gem_autofill_offered_url = url
                return

        creds = self.vault.get_credentials_for_url(url)
        if not creds:
            return  # bu site için kayıt yok: sessizce geç

        tab._gem_autofill_offered_url = url
        accepted = show_modern_confirm(
            self,
            (f"{creds['username']} hesabı için kayıtlı şifre bulundu.\n"
             "Bu sayfadaki oturum formuna doldurulsun mu?")
            if self.lang == "tr" else
            (f"A saved password was found for {creds['username']}.\n"
             "Fill it into the login form on this page?"),
            title="Şifre Otomatik Doldurma" if self.lang == "tr" else "Autofill Password",
            lang=self.lang)
        if not accepted:
            return
        self._fill_login_form(tab, creds["username"], creds["password"])
        self._reset_vault_lock_timer()

    def _fill_login_form(self, tab: BrowserTab, username: str, password: str):
        """Şifreyi + kullanıcı adını doldurur. input/change olaylarını da
        tetikler (React/Vue gibi framework'ler value atamasını yok sayar)."""
        if not self._tab_is_live(tab):
            return
        try:
            tab.view.page().runJavaScript(f"""(function() {{
            function setVal(el, v) {{
                el.value = v;
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
            }}
            var pw = document.querySelector('input[type=password]');
            if (!pw) return;
            setVal(pw, {json.dumps(password)});
            var user = null;
            var form = pw.closest('form');
            if (form) {{
                user = form.querySelector('input[type=email], input[type=text], input[type=tel], input:not([type])');
            }}
            if (!user) {{
                var els = document.querySelectorAll('input[type=email], input[type=text], input:not([type])');
                for (var i = 0; i < els.length; i++) {{
                    if (els[i].type === 'hidden') continue;
                    // DOM sırasında şifre alanından ÖNCE gelen son uygun alan
                    if (els[i].compareDocumentPosition(pw) & Node.DOCUMENT_POSITION_FOLLOWING) user = els[i];
                }}
            }}
            if (user) setVal(user, {json.dumps(username)});
        }})();""")
        except RuntimeError:
            pass

    def close_tab(self, index: int):
        if self.tab_widget.count() <= 1:
            # --- SON SEKME ---
            widget = (self.tab_widget.widget(index)
                      if index != -1 else self.tab_widget.currentWidget())
            if widget is None:
                widget = self.tab_widget.currentWidget()
            url_str = ""
            if isinstance(widget, BrowserTab):
                url_str = (widget.saved_url.toString() if widget.is_suspended
                           else (widget.view.url().toString() if widget.view is not None else ""))
            is_new_tab_page = "gem_browser_new_tab" in url_str
            if isinstance(widget, BrowserTab) and not is_new_tab_page:
                # Son sekme İÇERİK sekmesi: tarayıcıyı KAPATMA — yerine boş
                # bir yeni sekme aç ve onu kapat (Chrome davranışı).
                self.add_new_tab()  # switch_to=True: yeni sekme öne gelir
                old_index = self.tab_widget.indexOf(widget)
                if old_index != -1:
                    self.close_tab(old_index)  # artık çoklu-sekme yoluyla sorunsuz kapanır
                return
            # Son sekme zaten "Yeni Sekme": kapatma uyarısı BURADA çıkar.
            if show_modern_confirm(
                    self,
                    "Bu sekmeyi kapatırsanız tarayıcı da kapanacaktır. Emin misiniz?"
                    if self.lang == "tr" else
                    "Closing this tab will also close the browser. Are you sure?",
                    title="Son sekmeyi kapat" if self.lang == "tr" else "Close last tab",
                    lang=self.lang, danger=True):
                self.close()
            return
        if self.tab_widget.count() > 1:
            widget = self.tab_widget.widget(index)
            def _do_remove(widget=widget):
                # Animasyonlu kapatmada hızlı çift tık, ilk animasyonun
                # stop() edilip finished sinyalinin HEMEN yayılmasına yol
                # açar; _do_remove iki kez tetiklenirse ikinci çağrı silinmiş
                # C++ nesnesi üzerinde indexOf/removeTab yapıp RuntimeError
                # ile çöker. Bu yüzden sekme gerçekten hâlâ listedeyken
                # işle, temizliği de yalnızca bir kez yap.
                current_index = self.tab_widget.indexOf(widget)
                if current_index != -1:
                    if isinstance(widget, BrowserTab):
                        url_str = widget.saved_url.toString() if widget.is_suspended else widget.view.url().toString()
                        if url_str and not (_is_gem_internal_page(url_str)):
                            self.closed_tabs_stack.append(url_str)
                            del self.closed_tabs_stack[:-20]
                    if widget in self.tab_timers:
                        self.tab_timers[widget].stop()
                        del self.tab_timers[widget]
                    bar2 = self.tab_widget.tabBar()
                    if isinstance(bar2, ProgressTabBar): bar2.set_progress(widget, None)
                    self.tab_widget.removeTab(current_index)
                if isinstance(widget, BrowserTab) and not getattr(widget, "_gem_cleaned", False):
                    widget._gem_cleaned = True
                    widget.cleanup()
                    widget.deleteLater()
                self._update_sleep_status()
                self._rebuild_vertical_sidebar()
            bar = self.tab_widget.tabBar()
            if isinstance(bar, ProgressTabBar): bar.animate_tab_out(widget, _do_remove)
            else: _do_remove()
        else:
            if show_modern_confirm(self, "Bu sekmeyi kapatırsanız tarayıcı da kapanacaktır. Emin misiniz?" if self.lang == "tr" else "Closing this tab will also close the browser. Are you sure?", title="Son sekmeyi kapat" if self.lang == "tr" else "Close last tab", lang=self.lang, danger=True):
                self.close()

    def _reopen_closed_tab(self):
        if self.closed_tabs_stack: self.add_new_tab(QUrl(self.closed_tabs_stack.pop()))

    def _on_tab_changed(self, index: int):
        self._reset_vault_lock_timer()
        self._hide_suggestions()
        current_tab = self.current_tab()
        if not current_tab: return
        woke_up = False
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if isinstance(tab, BrowserTab):
                timer = self.tab_timers.get(tab)
                if tab == current_tab:
                    if timer: timer.stop()
                    if tab.is_suspended:
                        tab.restore()
                        woke_up = True
                else:
                    if not tab.is_suspended and timer and not timer.isActive(): timer.start()

        current_url = current_tab.saved_url.toString() if current_tab.is_suspended else (current_tab.view.url().toString() if current_tab.view is not None else "")
        if _is_gem_internal_page(current_url): self.url_bar.clear()
        else: self._set_url_bar_text(current_url)
        self._update_nav_buttons()
        if woke_up: self._update_sleep_status()
        self._rebuild_vertical_sidebar()

        current_full_title = getattr(current_tab, "_gem_full_title", None)
        is_new_tab = _is_gem_internal_page(current_url)
        self._update_window_title(None if is_new_tab else current_full_title)
        self._update_url_extras()
        # Uyuyan sekme uyandırıldıysa canlı sayısı arttı; sınırı uygula.
        self._enforce_max_live_tabs()
        # Seçim vurgusunu satırlarda yerinde güncelle (sekme değişiminde tüm
        # sidebar'ı yeniden kurmak gereksizdi).
        for t, row in self._sidebar_rows.items():
            try:
                row.set_selected(t is current_tab)
            except RuntimeError:
                pass
        # Eski sekmelerde bekleyen izin kartları: sekme değişince reddet
        # (Chrome davranışı — baloncuk yalnızca kendi sekmesinde yaşar).
        for i in range(self.tab_widget.count()):
            t = self.tab_widget.widget(i)
            if isinstance(t, BrowserTab) and t is not current_tab:
                t._close_all_permission_popups()

    def _update_window_title(self, title: str = None):
        # Görev çubuğu / Alt+Tab önizlemesinde aktif sekmenin sayfa başlığı
        # görünsün diye, sabit "GEM Browser" yerine "Sayfa Başlığı - GEM
        # Browser" formatını kullanıyoruz (diğer tarayıcılardaki standart
        # davranış budur). Başlık yoksa (örn. yeni sekme) sadece uygulama
        # adına dönüyoruz.
        self.setWindowTitle(f"{title} - {self._base_title}" if title else self._base_title)

    def _update_tab_title(self, tab: BrowserTab, title: str):
        index = self.tab_widget.indexOf(tab)
        if index == -1: return
        default_title = "Yeni Sekme" if self.lang == "tr" else "New Tab"
        full_title = title or default_title
        short_title = (title[:25] + "..." if len(title) > 25 else title) or default_title
        tab._gem_full_title = full_title

        self.tab_widget.setTabToolTip(index, "")

        pinned = bool(tab.property("pinned"))
        self.tab_widget.setTabText(index, "" if pinned else short_title)
        # Dikey sidebar: tam yeniden kurulum yerine satırda yerinde başlık
        # güncelle (her başlık değişiminde tüm satır widget'ları yeniden
        # yaratılıyordu — dikey moddaki en büyük takılma kaynağıydı).
        row = self._sidebar_rows.get(tab)
        if row is not None:
            try:
                row.set_title(full_title)
            except RuntimeError:
                self._sidebar_rows.pop(tab, None)
                self._rebuild_vertical_sidebar()
        else:
            self._rebuild_vertical_sidebar()

        if tab == self.current_tab():
            self._update_window_title(full_title)

    def _update_tab_url(self, tab: BrowserTab, url: QUrl):
        # Bekleyen uzak-PDF isteği varken BAŞKA bir sayfaya gezinildi:
        # indirme bitse bile görüntüleyici o sayfanın üstüne yüklenmesin.
        # DİKKAT: urlChanged, acceptNavigationRequest ile ENGELLENMİŞ pdf
        # gezinmesi için de ateşlenir — bekleyen URL'in kendisi geldiğinde
        # işareti SİLME (aksi halde indirme bitince görüntüleyici hiç
        # yüklenmezdi).
        pending = getattr(tab, "_gem_pdf_pending", None)
        if pending and url.toString() != pending and not _is_gem_internal_page(url.toString()):
            # Koşuldaki internal-page muafiyeti: engellenen pdf gezinmesi
            # sonrası Chromium önceki sayfaya dönerken de urlChanged yayılır
            # (dahili sayfa) — bu geri-dönüş olayı bekleyen isteği SİLMEMELİ.
            tab._gem_pdf_pending = None
        # Otomatik doldurma teklifi: farklı bir adrese gezinildiğinde hakkı
        # sıfırlanır (kullanıcı çıkış yapıp aynı login sayfasına dönerse
        # tekrar teklif edilebilsin).
        offered = getattr(tab, "_gem_autofill_offered_url", None)
        if offered and url.toString() != offered:
            tab._gem_autofill_offered_url = None
        # İç sayfalara (yeni sekme / PDF görüntüleyici) dönüşte favicon
        # GERİ GELMEZ (favicon'suz sayfa) — Qt'nin boş iconChanged'i
        # urlChanged'den önce geldiğinde ikon boşalıp öyle kalıyordu.
        # urlChanged, sıralamada en sonda gelen güvenilir noktadır: ikonu
        # burada kesin olarak uygulama ikonuna döndür.
        if _is_gem_internal_page(url.toString()) and not tab.is_suspended:
            index = self.tab_widget.indexOf(tab)
            if index != -1:
                if getattr(tab, "_muted", False):
                    icon = gem_icons.get_icon("volume-off", "#e67e22", size=16)
                else:
                    icon = self._app_icon()
                tab._gem_base_icon = QIcon(icon)
                self.tab_widget.setTabIcon(index, icon)
                row = self._sidebar_rows.get(tab)
                if row is not None:
                    try:
                        row.set_icon(icon)
                    except RuntimeError:
                        self._sidebar_rows.pop(tab, None)
        if tab == self.current_tab() and not (_is_gem_internal_page(url.toString())):
            self._set_url_bar_text(url.toString())
        if tab == self.current_tab():
            self._update_url_extras()

    def _current_page_url(self) -> QUrl:
        """Aktif sekmenin URL'si; askıdaysa kayıtlı adresi, yoksa boş QUrl."""
        tab = self.current_tab()
        if not isinstance(tab, BrowserTab):
            return QUrl("")
        if tab.is_suspended:
            return QUrl(getattr(tab, "saved_url", QUrl("")))
        if tab.view is not None:
            return tab.view.url()
        return QUrl("")

    def _update_url_extras(self):
        """Adres çubuğunun güvenlik göstergesini (kilit) ve favori
        yıldızını, o anki sayfaya göre günceller."""
        url = self._current_page_url()
        url_str = url.toString()
        is_new_tab_page = _is_gem_internal_page(url_str)
        is_page = bool(url_str) and url_str != "about:blank" and not is_new_tab_page
        accent = gem_theme.get_accent_color(self.settings.current)
        is_light = self.settings.current["ui_theme"] == "light"

        scheme = url.scheme()
        if is_page and scheme in ("http", "https"):
            self.security_action.setVisible(True)
            if scheme == "https":
                # left_pad: ikon alanın en soluna yapışık durmasın, içeride
                # nefes alan bir konumda dursun (kullanıcı isteği).
                self.security_action.setIcon(gem_icons.get_icon("lock", accent, size=14))
                self.security_action.setToolTip(
                    "Güvenli bağlantı (HTTPS)" if self.lang == "tr" else "Secure connection (HTTPS)")
            else:
                self.security_action.setIcon(gem_icons.get_icon("lock", "#e67e22", size=14))
                self.security_action.setToolTip(
                    "Güvensiz bağlantı (HTTP)" if self.lang == "tr" else "Not secure (HTTP)")
        else:
            self.security_action.setVisible(False)

        if is_page:
            self.star_action.setVisible(True)
            bookmarks = load_bookmarks()
            is_bookmarked = any(b.get("url") == url_str for b in bookmarks)
            if is_bookmarked:
                self.star_action.setIcon(gem_icons.get_icon("star", accent, size=16))
                self.star_action.setToolTip(
                    "Favorilerden kaldır" if self.lang == "tr" else "Remove from bookmarks")
            else:
                muted = "#777777" if is_light else "#888888"
                self.star_action.setIcon(gem_icons.get_icon("star", muted, size=16))
                self.star_action.setToolTip(
                    "Favorilere ekle" if self.lang == "tr" else "Add to bookmarks")
        else:
            self.star_action.setVisible(False)

    def _toggle_bookmark(self):
        """Adres çubuğundaki yıldız: o anki sayfayı favorilere ekler/kaldırır."""
        url = self._current_page_url()
        url_str = url.toString()
        if not url_str or url_str == "about:blank":
            return
        bookmarks = load_bookmarks()
        if any(b.get("url") == url_str for b in bookmarks):
            bookmarks = [b for b in bookmarks if b.get("url") != url_str]
        else:
            tab = self.current_tab()
            title = ""
            if isinstance(tab, BrowserTab):
                title = getattr(tab, "_gem_full_title", "") or (tab.view.title() if tab.view is not None else "")
            bookmarks.append({"name": title or url_str, "url": url_str})
        save_bookmarks(bookmarks)
        self._update_url_extras()
        # Açık olan yeni sekme sayfaları güncel favorileri görsün.
        for i in range(self.tab_widget.count()):
            t = self.tab_widget.widget(i)
            if isinstance(t, BrowserTab) and not t.is_suspended and t.view is not None:
                cur = t.view.url().toString()
                if cur.startswith("file://") and "gem_browser_new_tab" in cur:
                    self._refresh_new_tab_page(t)

    def _show_security_info(self):
        url = self._current_page_url()
        host = url.host() or (url.toString()[:40] if url.toString() else "")
        if url.scheme() == "https":
            msg = (f"{host} güvenli bir HTTPS bağlantısı üzerinden yükleniyor. "
                   "Sitenin kimliği doğrulanır ve trafik şifrelenir.") if self.lang == "tr" else \
                  (f"{host} is loaded over a secure HTTPS connection. "
                   "Its identity is verified and traffic is encrypted.")
            title = "Güvenli Bağlantı" if self.lang == "tr" else "Secure Connection"
        else:
            msg = (f"{host} şifrelenmemiş bir HTTP bağlantısı üzerinden yükleniyor. "
                   "Verileriniz ağ üzerinde düz metin taşınabilir; gizli bilgilerinizi girmeyin.") if self.lang == "tr" else \
                  (f"{host} is loaded over an unencrypted HTTP connection. "
                   "Your data travels in plain text; avoid entering sensitive information.")
            title = "Güvensiz Bağlantı" if self.lang == "tr" else "Not Secure"
        show_modern_info(self, msg, title=title, lang=self.lang, warning=(url.scheme() != "https"))

    def _open_file_dialog(self):
        """Ctrl+O: yerel dosya seçip sekmede aç (PDF'ler görüntüleyicide)."""
        lang = self.lang
        filter_str = ("PDF (*.pdf);;HTML (*.htm *.html);;Tüm Dosyalar (*)"
                      if lang == "tr" else
                      "PDF (*.pdf);;HTML (*.htm *.html);;All Files (*)")
        path, _ = QFileDialog.getOpenFileName(
            self, "Dosya Aç" if lang == "tr" else "Open File",
            os.path.expanduser("~"), filter_str)
        if path:
            self._open_local_path(path)

    def _open_local_path(self, path: str, tab=None):
        """Yerel dosyayı sekmede aç: PDF'ler görüntüleyicide, diğerleri
        doğrudan (file://) gezinilir."""
        if tab is None:
            tab = self.current_tab()
        if not isinstance(tab, BrowserTab):
            tab = self.add_new_tab(QUrl("about:blank"))
        if tab.is_suspended:
            tab.restore()
        if tab.view is None:
            return
        if path.lower().endswith(".pdf"):
            target = pdf_viewer.build_viewer_url(QUrl.fromLocalFile(path).toString())
            if target:
                tab.view.load(QUrl(target))
                return
        tab.view.setUrl(QUrl.fromLocalFile(path))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls:
            return super().dropEvent(event)
        first = True
        for u in urls:
            local = u.toLocalFile()
            if local:
                if first:
                    # İlk dosya geçerli sekmede, kalanlar yeni sekmelerde
                    self._open_local_path(local)
                    first = False
                else:
                    new_tab = self.add_new_tab(QUrl("about:blank"))
                    self._open_local_path(local, tab=new_tab)
            elif u.toString().startswith(("http://", "https://")):
                tab = self.current_tab()
                if isinstance(tab, BrowserTab) and tab.view is not None:
                    tab.view.setUrl(u)
        event.acceptProposedAction()

    # ---------------- Sayfa/sekme eylemleri ----------------

    def _active_page_tab(self):
        """Eylemlerin uygulanacağı (görünür, askıda olmayan) sekmeyi döndürür."""
        tab = self.current_tab()
        if isinstance(tab, BrowserTab) and not tab.is_suspended and tab.view is not None:
            return tab
        return None

    def _toggle_devtools(self):
        tab = self._active_page_tab()
        if tab is not None:
            tab.toggle_devtools()

    def _print_page(self):
        if QPrinter is None:
            show_modern_info(self, "Yazdırma modülü (QtPrintSupport) kurulu değil.",
                             lang=self.lang, warning=True)
            return
        tab = self._active_page_tab()
        if tab is None:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dlg = QPrintDialog(printer, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            tab.view.page().print(printer)

    def _save_page_as_pdf(self):
        tab = self._active_page_tab()
        if tab is None:
            return
        lang = self.lang
        title = getattr(tab, "_gem_full_title", "") or "sayfa"
        safe = "".join(c for c in title if c not in '\\/:*?"<>|').strip() or "sayfa"
        default_path = os.path.join(os.path.expanduser("~"), f"{safe}.pdf")
        path, _ = QFileDialog.getSaveFileName(
            self, "PDF Olarak Kaydet" if lang == "tr" else "Save as PDF",
            default_path, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        tab.web_page.printToPdf(path)
        show_modern_info(
            self,
            "PDF kaydedildi: " + path if lang == "tr" else "PDF saved: " + path,
            lang=lang)

    def _save_page(self):
        tab = self._active_page_tab()
        if tab is not None and tab.web_page is not None:
            tab.web_page.triggerAction(QWebEnginePage.WebAction.SavePage)

    def _view_source(self):
        import base64 as _b64
        tab = self._active_page_tab()
        if tab is None or tab.web_page is None:
            return

        def _show(html):
            if html is None:
                return
            data = "data:text/html;charset=utf-8;base64," + _b64.b64encode(
                html.encode("utf-8", errors="replace")).decode("ascii")
            self.add_new_tab(QUrl(data))

        tab.web_page.toHtml(_show)

    def _duplicate_tab(self, tab=None):
        tab = tab or self.current_tab()
        if not isinstance(tab, BrowserTab):
            return
        if tab.is_suspended:
            url = QUrl(getattr(tab, "saved_url", QUrl("")))
        elif tab.view is not None:
            url = tab.view.url()
        else:
            return
        if not url.toString() or _is_gem_internal_page(url.toString()):
            return
        self.add_new_tab(QUrl(url))

    def _toggle_tab_mute(self, tab=None):
        tab = tab or self.current_tab()
        if isinstance(tab, BrowserTab):
            tab.set_muted(not tab.is_muted())

    def _update_tab_audio(self, tab, muted: bool, audible: bool):
        """Ses durumuna göre sekme ikonu: susturulmuş → çizgili hoparlör,
        ses çıkarıyor → hoparlör, değilse normal favicon."""
        index = self.tab_widget.indexOf(tab)
        if index == -1:
            return
        accent = gem_theme.get_accent_color(self.settings.current)
        if muted:
            icon = gem_icons.get_icon("volume-off", "#e67e22", size=16)
        elif audible:
            icon = gem_icons.get_icon("volume", accent, size=16)
        else:
            base = getattr(tab, "_gem_base_icon", None)
            icon = base if base is not None else self._app_icon()
        self.tab_widget.setTabIcon(index, icon)
        # Sidebar satırının ikonunu yerinde güncelle (ses durumu anında
        # yansısın; context menü etiketi de tab._muted'dan okur)
        row = self._sidebar_rows.get(tab)
        if row is not None:
            try:
                row.set_icon(icon)
            except RuntimeError:
                self._sidebar_rows.pop(tab, None)

    def _tab_search(self):
        dlg = TabSearchDialog(self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.exec()

    def _open_clear_data(self):
        dlg = ClearDataDialog(self.settings, self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sel = dlg.get_selection()
        self.settings.current["clear_data_on_exit"] = sel["on_exit"]
        self.settings.save()

        if sel["cookies"]:
            self.shared_profile.cookieStore().deleteAllCookies()
        if sel["cache"]:
            try:
                self.shared_profile.clearHttpCache()
            except AttributeError:
                pass  # eski Qt: profil seviyesinde önbellek temizleme yok
        if sel["history"] and not self.is_incognito:
            import time as _time
            hours = sel["history_hours"] or 0
            cutoff = (_time.time() - hours * 3600) if hours else 0
            if cutoff:
                self.persistent_history = [e for e in self.persistent_history
                                           if e.get("timestamp", 0) >= cutoff]
            else:
                self.persistent_history = []
            gem_history.save_history(self.persistent_history)
            self.session_history = [e.get("url", "") for e in self.persistent_history][-500:]
        if sel["downloads"]:
            dm = self.download_manager
            dm.history = []
            dm._save_history()
            dm.history_changed.emit()
        show_modern_info(
            self,
            "Seçili tarama verileri temizlendi." if self.lang == "tr"
            else "Selected browsing data cleared.",
            lang=self.lang)

    def _focus_url_bar(self):
        self._hide_suggestions()
        self.url_bar.setFocus()
        self.url_bar.selectAll()

    def _cycle_tab(self, delta: int):
        count = self.tab_widget.count()
        if count <= 1:
            return
        idx = (self.tab_widget.currentIndex() + delta) % count
        self.tab_widget.setCurrentIndex(idx)

    def _goto_tab_number(self, number: int):
        """Ctrl+1..8 -> o sıradaki sekme; Ctrl+9 -> SON sekme (Chrome gibi)."""
        count = self.tab_widget.count()
        if count == 0:
            return
        index = count - 1 if number == 9 else number - 1
        if 0 <= index < count:
            self.tab_widget.setCurrentIndex(index)

    def _flush_history(self):
        if getattr(self, "_history_dirty", False):
            self._history_dirty = False
            gem_history.save_history(self.persistent_history)

    def _record_history(self, tab: BrowserTab):
        if self.is_incognito or tab.is_suspended or tab.view is None: return
        url_str = tab.view.url().toString()
        if not url_str or tab.view.url().scheme() not in ("http", "https") or (_is_gem_internal_page(url_str)): return
        self.persistent_history = gem_history.add_entry(
            self.persistent_history, url_str, tab.view.title() or url_str, save=False)
        if not self.session_history or self.session_history[-1] != url_str:
            self.session_history.append(url_str)
            if len(self.session_history) > 500: self.session_history = self.session_history[-500:]
        # Diske yazımı geciktir: her sayfa yüklemesinde tüm geçmiş dosyasını
        # yazmak yerine 3 sn'de bir (ve kapanışta) yaz.
        self._history_dirty = True
        if not hasattr(self, "_history_flush_timer"):
            self._history_flush_timer = QTimer(self)
            self._history_flush_timer.setSingleShot(True)
            self._history_flush_timer.setInterval(3000)
            self._history_flush_timer.timeout.connect(self._flush_history)
        if not self._history_flush_timer.isActive():
            self._history_flush_timer.start()

    def current_tab(self) -> BrowserTab: return self.tab_widget.currentWidget()
    def _navigate_back(self): tab = self.current_tab(); (tab.view.back() if tab and not tab.is_suspended else None)
    def _navigate_forward(self): tab = self.current_tab(); (tab.view.forward() if tab and not tab.is_suspended else None)
    def _reload_page(self): tab = self.current_tab(); (tab.view.reload() if tab and not tab.is_suspended else None)

    def _set_url_bar_text(self, text: str) -> None:
        self.url_bar.setText(text)
        self.url_bar.setCursorPosition(0)

    def _load_url_from_bar(self):
        self._reset_vault_lock_timer()
        self._hide_suggestions()
        self._remote_suggester.cancel()
        input_text = self.url_bar.text().strip()
        if input_text:
            tab = self.current_tab()
            if tab:
                if tab.is_suspended: tab.restore()
                self._enforce_max_live_tabs()
                tab.view.setUrl(resolve_url(
                    input_text,
                    engine=self.settings.current.get("search_engine", "brave"),
                    custom_url=self.settings.current.get("custom_search_url", ""),
                ))

    def closeEvent(self, event):
        self.vault_lock_timer.stop()
        # Pencere durumunu kaydet (minimize durumundaysa son bilinen boyut).
        s = self.settings.current
        if self.windowState() & Qt.WindowState.WindowMinimized:
            pass  # minimize edilmişse mevcut değerleri koru
        elif self.windowState() & Qt.WindowState.WindowMaximized:
            s["win_maximized"] = True
        else:
            s["win_maximized"] = False
            s["win_x"] = self.x(); s["win_y"] = self.y()
            s["win_w"] = self.width(); s["win_h"] = self.height()
        self.settings.save()
        # Calisan PDF indirme thread'leri varsa kapanmadan bekle — aksi halde
        # "QThread: Destroyed while thread is still running" ile cokebilir.
        for t in list(getattr(self, "_pdf_fetch_threads", [])):
            if t.isRunning():
                t.wait(10000)
        # Açık geliştirici araçlarını kapat (sayfalar yok edilmeden).
        for i in range(self.tab_widget.count()):
            t = self.tab_widget.widget(i)
            if isinstance(t, BrowserTab):
                t.close_devtools()
        # Bekleyen geçmiş yazımını diske boşalt.
        self._flush_history()
        # "Kapanışta temizle" ayarı işaretliyse çerezler + önbellek.
        if self.settings.current.get("clear_data_on_exit", False):
            self.shared_profile.cookieStore().deleteAllCookies()
            try:
                self.shared_profile.clearHttpCache()
            except AttributeError:
                pass
        if getattr(self, "tor_vpn", None) is not None and self.tor_vpn.is_active:
            self.tor_vpn.disconnect()
        if self._blocklist_thread is not None and self._blocklist_thread.isRunning():
            try:
                self._blocklist_thread.finished_ok.disconnect()
                self._blocklist_thread.finished_err.disconnect()
            except TypeError: pass
            if not [w for w in _active_windows if w is not self]: self._blocklist_thread.wait(3000)

        # İndirme sinyali sahipliğini, aynı profili kullanan başka bir
        # pencere varsa devret — aksi halde bu pencere kapanınca indirmeler
        # artık hiç diyaloğa bağlanmaz.
        if getattr(self, "_owns_download_signal", False):
            self._owns_download_signal = False
            try:
                self.shared_profile.downloadRequested.disconnect(self.download_manager.handle_download)
            except TypeError:
                pass
            if self.shared_profile in _download_connected_profiles:
                _download_connected_profiles.remove(self.shared_profile)
            successor = next(
                (w for w in _active_windows if w is not self and w.shared_profile is self.shared_profile),
                None,
            )
            if successor is not None:
                _download_connected_profiles.append(self.shared_profile)
                successor._owns_download_signal = True
                self.shared_profile.downloadRequested.connect(successor.download_manager.handle_download)

        if self.is_incognito: self.shared_profile.cookieStore().deleteAllCookies()
        else:
            if not [w for w in _active_windows if w is not self]:
                tab_urls = self._collect_session_tab_urls()
                gem_session.save_session(tab_urls) if tab_urls else gem_session.clear_session()

        if self in _active_windows: _active_windows.remove(self)
        event.accept()
