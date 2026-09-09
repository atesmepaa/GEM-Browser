import os
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QLineEdit, QDialog
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtCore import QUrl, pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QIcon, QPixmap

from gem_browser.permissions import PermissionPopup
from gem_browser import theme as gem_theme

ZOOM_MIN = 0.25
ZOOM_MAX = 3.0
ZOOM_STEP = 0.1

_WEB_CONTEXT_MENU_TR = {
    "back": "Geri",
    "forward": "İleri",
    "reload": "Yenile",
    "reload and bypass cache": "Yenile (önbelleği atla)",
    "stop": "Durdur",
    "save page as...": "Sayfayı farklı kaydet...",
    "save page": "Sayfayı kaydet",
    "print page": "Sayfayı yazdır",
    "view page source": "Sayfa kaynağını görüntüle",
    "cut": "Kes",
    "copy": "Kopyala",
    "paste": "Yapıştır",
    "paste and match style": "Yapıştır ve biçimi eşleştir",
    "undo": "Geri al",
    "redo": "Yinele",
    "delete": "Sil",
    "select all": "Tümünü seç",
    "copy link address": "Bağlantı adresini kopyala",
    "save link": "Bağlantıyı kaydet",
    "save link as...": "Bağlantıyı farklı kaydet...",
    "open link in new tab": "Bağlantıyı yeni sekmede aç",
    "open link in new window": "Bağlantıyı yeni pencerede aç",
    "open link in new background tab": "Bağlantıyı arka planda yeni sekmede aç",
    "copy image": "Görseli kopyala",
    "copy image address": "Görsel adresini kopyala",
    "save image": "Görseli kaydet",
    "save image as...": "Görseli farklı kaydet...",
    "open image in new tab": "Görseli yeni sekmede aç",
    "copy media address": "Ortam adresini kopyala",
    "save media as...": "Ortamı farklı kaydet...",
    "toggle play/pause": "Oynat / duraklat",
    "toggle mute": "Sesi kapat / aç",
    "toggle loop": "Döngüyü aç / kapat",
    "toggle controls": "Denetimleri göster / gizle",
    "toggle fullscreen": "Tam ekranı aç / kapat",
    "exit full screen": "Tam ekrandan çık",
    "inspect": "İncele",
    "inspect element": "Öğeyi incele",
    "no spelling suggestions found": "Yazım önerisi bulunamadı",
    "add to dictionary": "Sözlüğe ekle",
    "spelling and grammar": "Yazım ve dilbilgisi",
    "check spelling while typing": "Yazarken yazımı denetle",
    "download": "İndir",
    "download link": "Bağlantıyı indir",
    "download image": "Görseli indir",
    "download media": "Ortamı indir",
}


def _translate_web_context_menu(menu, lang: str) -> None:
    if lang != "tr":
        return
    for action in menu.actions():
        if action.isSeparator():
            continue
        raw_text = action.text().replace("&", "").strip()
        translated = _WEB_CONTEXT_MENU_TR.get(raw_text.lower())
        if translated:
            action.setText(translated)
        sub_menu = action.menu()
        if sub_menu is not None:
            _translate_web_context_menu(sub_menu, lang)


class CustomWebPage(QWebEnginePage):
    def __init__(self, profile, parent=None, action_callback=None, new_page_callback=None):
        super().__init__(profile, parent)
        self.action_callback = action_callback
        self.new_page_callback = new_page_callback

    def acceptNavigationRequest(self, url: QUrl, type: QWebEnginePage.NavigationType, isMainFrame: bool) -> bool:
        url_str = url.toString()
        if "gemaction://" in url_str:
            if self.action_callback:
                self.action_callback(url)
            return False 
        return super().acceptNavigationRequest(url, type, isMainFrame)

    def createWindow(self, window_type: QWebEnginePage.WebWindowType) -> QWebEnginePage:
        if self.new_page_callback:
            page = self.new_page_callback(window_type)
            if page is not None:
                return page
        return super().createWindow(window_type)


class ZoomableWebView(QWebEngineView):
    def __init__(self, parent=None, browser_tab=None):
        super().__init__(parent)
        self._browser_tab = browser_tab

    def wheelEvent(self, event):
        if self._browser_tab is not None and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self._browser_tab.zoom_in()
            elif event.angleDelta().y() < 0:
                self._browser_tab.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def contextMenuEvent(self, event):
        page = self.page()
        if page is None:
            super().contextMenuEvent(event)
            return

        menu = page.createStandardContextMenu()
        lang = getattr(self._browser_tab, "lang", "tr") if self._browser_tab is not None else "tr"
        _translate_web_context_menu(menu, lang)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(event.globalPos())



class BrowserTab(QWidget):
    title_changed = pyqtSignal(str)
    url_changed = pyqtSignal(QUrl)
    icon_changed = pyqtSignal(QIcon)
    load_finished = pyqtSignal(bool)
    load_progress = pyqtSignal(int)
    gem_action_triggered = pyqtSignal(QUrl)

    def __init__(self, profile, initial_url: QUrl, parent=None, download_manager=None, lang="tr", new_page_callback=None):
        super().__init__(parent)
        self.profile = profile
        self.initial_url = initial_url
        self.download_manager = download_manager
        self.lang = lang
        self.new_page_callback = new_page_callback
        self.is_suspended = False
        self._active_permission_popups = []
        self.zoom_factor = 1.0
        self._thumbnail = None
        self._page_loading = False
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.find_bar = QWidget(self)
        self.find_bar.setStyleSheet("background-color: #242424; border-bottom: 1px solid #333333; padding: 4px;")
        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(6, 2, 6, 2)
        
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Sayfada ara..." if self.lang == "tr" else "Find in page...")
        self.find_input.textChanged.connect(self._do_find)
        self.find_input.returnPressed.connect(self._do_find_next)
        
        find_close = QPushButton("✕")
        find_close.setFixedWidth(24)
        find_close.clicked.connect(self.hide_find_bar)
        
        find_layout.addWidget(self.find_input)
        find_layout.addWidget(find_close)
        self.find_bar.hide()
        
        self.layout.addWidget(self.find_bar)
        
        self.suspend_widget = None
        self._create_web_view()

    def _create_web_view(self):
        self.view = ZoomableWebView(self, browser_tab=self)
        self.web_page = CustomWebPage(
            self.profile,
            self.view,
            action_callback=self.gem_action_triggered.emit,
            new_page_callback=self.new_page_callback
        )
        
        self.view.setPage(self.web_page)
        self.web_page.titleChanged.connect(self.title_changed.emit)
        self.web_page.urlChanged.connect(self.url_changed.emit)
        self.web_page.iconChanged.connect(self.icon_changed.emit)
        self.web_page.loadFinished.connect(self.load_finished.emit)
        self.web_page.loadProgress.connect(self.load_progress.emit)
        self.web_page.featurePermissionRequested.connect(self._handle_permission_request)
        self.web_page.loadStarted.connect(self._on_load_started)
        self.web_page.loadFinished.connect(self._on_load_finished)
        
        self.view.setUrl(self.initial_url)
        self.view.setZoomFactor(self.zoom_factor)
        self.layout.addWidget(self.view)

    def _on_load_started(self):
        self._page_loading = True
        
    def _on_load_finished(self, ok: bool):
        self._page_loading = False
        if ok:
            # SPA sitelerin DOM'u tamamen çizmesi için 150ms yerine 800ms bekliyoruz.
            QTimer.singleShot(800, self._capture_thumbnail)

    def _capture_thumbnail(self):
        if self.is_suspended or self.view is None:
            return
        
        # ÖNEMLİ: Sekme ekranda görünmüyorsa (arka plandaysa) grab() işlemi yapma!
        # Aksi takdirde boş veya siyah ekran kaydeder.
        if not self.isVisible():
            return
            
        try:
            pixmap = self.view.grab()
        except RuntimeError:
            return
        if pixmap is not None and not pixmap.isNull() and pixmap.width() > 0 and pixmap.height() > 0:
            self._thumbnail = pixmap

    # Kullanıcı sekme değiştirdiğinde, sekme arka plana atılmadan hemen ÖNCE son görüntüyü yakala
    def hideEvent(self, event):
        self._capture_thumbnail()
        super().hideEvent(event)

    def get_thumbnail(self) -> QPixmap:
        """Returns the last successfully captured screenshot of this tab's
        page, or None if the tab hasn't finished loading a page yet."""
        return self._thumbnail

    def is_page_loading(self) -> bool:
        return self._page_loading

    def zoom_in(self):
        self._set_zoom(self.zoom_factor + ZOOM_STEP)

    def zoom_out(self):
        self._set_zoom(self.zoom_factor - ZOOM_STEP)

    def zoom_reset(self):
        self._set_zoom(1.0)

    def _set_zoom(self, factor: float):
        factor = max(ZOOM_MIN, min(ZOOM_MAX, round(factor, 2)))
        self.zoom_factor = factor
        if self.view is not None:
            self.view.setZoomFactor(factor)

    def _handle_permission_request(self, origin: QUrl, feature):
        host = origin.host() or origin.toString()
        main_window = self.window()
        anchor = None
        tab_widget = getattr(main_window, "tab_widget", None)
        if tab_widget is not None:
            anchor = tab_widget.tabBar()
        main_settings = getattr(main_window, "settings", None)
        accent = gem_theme.get_accent_color(getattr(main_settings, "current", None)) if main_settings else None
        popup = PermissionPopup(host, feature, lang=self.lang, parent=main_window, accent=accent)
        popup.position_below_tab_bar(anchor, stack_index=len(self._active_permission_popups))
        self._active_permission_popups.append(popup)

        def _on_finished(result):
            if popup in self._active_permission_popups:
                self._active_permission_popups.remove(popup)
            granted = result == QDialog.DialogCode.Accepted
            policy = (
                QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
                if granted else
                QWebEnginePage.PermissionPolicy.PermissionDeniedByUser
            )
            if self.web_page is not None:
                self.web_page.setFeaturePermission(origin, feature, policy)

        popup.finished.connect(_on_finished)
        popup.show()
        popup.raise_()
        popup.activateWindow()

    def _close_all_permission_popups(self):
        for popup in list(self._active_permission_popups):
            popup.reject()

    def show_find_bar(self):
        self.find_bar.show()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def hide_find_bar(self):
        self.find_bar.hide()
        if self.view: self.view.page().findText("")

    def _do_find(self, text):
        if self.view and text: self.view.page().findText(text)

    def _do_find_next(self):
        text = self.find_input.text()
        if self.view and text: self.view.page().findText(text, QWebEnginePage.FindFlag.FindCaseSensitively)

    def suspend(self):
        if self.is_suspended or not self.view: return
        self._close_all_permission_popups()
        self._capture_thumbnail()
        self.saved_url = self.view.url()
        self.layout.removeWidget(self.view)
        self.view.deleteLater()
        self.view = None
        
        self.suspend_widget = QWidget(self)
        s_layout = QVBoxLayout(self.suspend_widget)
        msg = "💤 Bu sekme RAM tasarrufu için uyutuldu.\n\nUykudan uyandırmak için sekmenize tıklamanız yeterlidir." if self.lang == "tr" else "💤 This tab is sleeping to save RAM.\n\nClick anywhere to wake it up."
        lbl = QLabel(msg)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: #888888; font-size: 14px;")
        s_layout.addWidget(lbl)
        
        self.layout.addWidget(self.suspend_widget)
        self.is_suspended = True

    def restore(self):
        if not self.is_suspended: return
        self.layout.removeWidget(self.suspend_widget)
        self.suspend_widget.deleteLater()
        self.suspend_widget = None
        self._create_web_view()
        self.view.setUrl(self.saved_url)
        self.is_suspended = False

    def cleanup(self):
        self._close_all_permission_popups()
        if self.web_page is not None:
            self.web_page.setUrl(QUrl("about:blank")) 
            self.web_page.deleteLater()
            self.web_page = None
        if self.view is not None:
            self.view.setPage(None)
            self.view.deleteLater()
            self.view = None
