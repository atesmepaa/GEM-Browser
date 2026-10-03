from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QLineEdit, QDialog, QGraphicsDropShadowEffect, QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtCore import QUrl, pyqtSignal, Qt, QTimer, QEvent
from PyQt6.QtGui import QIcon, QPixmap, QColor, QDesktopServices

# Web/iç şemalar: bunlar tarayıcı içinde işlenir. Bu listede OLMAYAN bir
# şema (spotify://, mailto:, tg://, zoommtg:// vb.) harici protokoldür ve
# işletim sisteminin varsayılan işleyicisine devredilir (QDesktopServices).
# Spotify/Zoom/Discord gibi uygulamaların OAuth geri dönüşleri ve masaüstü
# uygulaması başlatma bağlantıları bu sayede çalışır.
_WEB_SCHEMES = (
    "http", "https", "file", "about", "data", "blob", "view-source",
    "javascript", "gemaction", "chrome", "qrc",
)

from gem_browser.permissions import PermissionPopup
from gem_browser import theme as gem_theme
from gem_browser import pdf_viewer

ZOOM_MIN = 0.25
ZOOM_MAX = 3.0
ZOOM_STEP = 0.1

# Sekme küçük resimleri (hover önizlemeleri) bellekte BU boyutta saklanır:
# önizleme kutusunun (220x124) 2 katı — hidpi ekranlarda netlik için.
# Tam çözünürlüklü grab (~4 MB, 4K'da ~14 MB / sekme) saklamak, 20+ sekmeli
# kullanımda yüzlerce MB RAM yiyordu; önizleme bunun yalnızca ~%1'i.
_THUMB_STORE_W = 440
_THUMB_STORE_H = 248

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


def _safe_load(view, url: QUrl):
    """Gecikmeli load: 0ms singleShot penceresinde view silinmiş olabilir."""
    try:
        view.load(url)
    except RuntimeError:
        pass


class CustomWebPage(QWebEnginePage):
    def __init__(self, profile, parent=None, action_callback=None, new_page_callback=None,
                 pdf_open_callback=None):
        super().__init__(profile, parent)
        self.action_callback = action_callback
        self.new_page_callback = new_page_callback
        self.pdf_open_callback = pdf_open_callback
        # PyQt6'da QWebEnginePage.view() yok; kurucu parent'ı görünüm olarak
        # saklarız (PDF görüntüleyiciye yönlendirmede kullanılır).
        self._gem_view = parent

    def acceptNavigationRequest(self, url: QUrl, type: QWebEnginePage.NavigationType, isMainFrame: bool) -> bool:
        url_str = url.toString()
        if "gemaction://" in url_str:
            if self.action_callback:
                self.action_callback(url)
            return False
        # PDF'leri sekme içinde PDF.js görüntüleyicide aç (bkz. pdf_viewer.py):
        # bu sistemdeki QtWebEngine paketi yerleşik PDF görüntüleyici
        # kaynakları olmadan derlendiği için Chromium PDF'leri indirmeye
        # çevirir. Karar verilmadan ÖNCE, ana çerçeve .pdf gezinmelerini
        # burada yakalayıp yerel görüntüleyici sayfasına yönlendiriyoruz.
        # (URL interceptor katmanı da denendi; Chromium'un indir-kararı
        # ondan SONRA gelip yönlendirmeyi geçersiz kılıyor — doğrusu bu
        # sayfa düzeyi politika noktası.)
        # Harici protokol (spotify://, mailto:, zoommtg://...): ana çerçeve
        # gezinmesiyse işletim sistemi işleyicisine devret ve tarayıcıda
        # gezinme olarak değerlendirme (False → boş sayfa/stuck olmaz).
        scheme = url.scheme().lower()
        if isMainFrame and scheme and scheme not in _WEB_SCHEMES:
            QDesktopServices.openUrl(url)
            return False
        if isMainFrame and pdf_viewer.should_redirect_to_viewer(url):
            if url.scheme() in ("http", "https"):
                # Uzak PDF: Qt tarafında sessiz indirilip yerel kopyadan
                # açılacak (CORS'a takılmamak için; bkz. pdf_viewer.py).
                # Karar burada verilir, akış MainWindow'da yürütülür.
                if self.pdf_open_callback:
                    self.pdf_open_callback(url)
                return False
            target = pdf_viewer.build_viewer_url(url_str)
            if target:
                view = self._gem_view
                if view is not None:
                    QTimer.singleShot(0, lambda v=view, t=target: _safe_load(v, t))
                    return False
        return super().acceptNavigationRequest(url, type, isMainFrame)

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        # new tab sayfası ile uygulama arasındaki eylem kanalı: sayfa
        # console.log("gemaction:...") ile istek gönderir, burada yakalanıp
        # action_callback'a (gemaction://...) dönüştürülerek iletilir.
        # NEDEN BURASI: Qt 6.11'de bilinmeyen bir şemaya location.href
        # gezinmesi Chromium tarafından sessizce düşürülüyor (hiçbir
        # acceptNavigationRequest üretilmiyor); console kanalı ise sürümden
        # bağımsız ve sekme başına çalışır.
        # GÜVENLİK: yalnızca KENDİ ürettiğimiz sayfalardan (yeni sekme,
        # PDF görüntüleyici) gelen mesajlar kabul edilir — source_id, mesajın
        # geldiği betiğin URL'idir ve dış siteler bunu taklit edemez. Aksi
        # halde herhangi bir web sitesi console.log ile favori diyaloğu
        # spam'leyebilirdi.
        source_ok = bool(source_id) and (
            "gem_browser_new_tab" in source_id or "gem_pdf_viewer_" in source_id)
        if source_ok and message.startswith("gemaction:"):
            rest = message[len("gemaction:"):].strip()
            # Biçim: "eylem_adi" ya da "eylem_adi <encodeURIComponent'li veri>".
            # Veri QUrl'e ?url= sorgusu olarak eklenir (boşluk/QUrl geçersizliği
            # olmasın diye ayraç olarak boşluk kullanılsa bile veri URL'in
            # GÖVDESİNE değil SORGUSUNA gider; encodeURIComponent boşlukları
            # zaten %20 yapar).
            if " " in rest:
                action, _, data = rest.partition(" ")
                url = QUrl(f"gemaction://{action}?url={data}")
            else:
                url = QUrl(f"gemaction://{rest}")
            if self.action_callback and not url.isEmpty():
                self.action_callback(url)
            return None
        return super().javaScriptConsoleMessage(level, message, line_number, source_id)

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

        # ÖNEMLİ: createStandardContextMenu() Qt6'da QWebEnginePage'den
        # QWebEngineView'e taşındı (bkz. Qt WebEngine değişiklik notları).
        # Eskiden page.createStandardContextMenu() çağrılıyordu; bu Qt6'da
        # "'CustomWebPage' object has no attribute 'createStandardContextMenu'"
        # AttributeError'ına ve uygulamanın çökmesine (SIGABRT) yol açıyordu.
        # Doğrusu view (self) üzerinden çağırmak.
        menu = self.createStandardContextMenu()
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
    # Uzak PDF açma isteği (MainWindow Qt tarafında indirip görüntüleyiciyi
    # açar; bkz. window._open_pdf_flow)
    pdf_open_requested = pyqtSignal(QUrl)
    # (muted, audible) — sekme ikonunu güncellemek için
    audio_state_changed = pyqtSignal(bool, bool)

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
        self._muted = False
        self._gem_base_icon = None
        self._devtools_win = None
        self._devtools_page = None
        self._devtools_view = None
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self._build_find_bar()

        self.suspend_widget = None
        self._create_web_view()

    def _build_find_bar(self):
        # ÖNEMLİ: find_bar bilerek self.layout'a EKLENMİYOR. Layout'a eklenen
        # bir bar sayfa içeriğini aşağı iter (eski davranış). Chrome/Zen
        # tarzı davranış için find_bar, self'in (BrowserTab) doğrudan çocuğu
        # olarak absolute konumlandırılıyor ve web view'in ÜZERİNDE, sağ üst
        # köşede yüzen küçük bir kutu olarak gösteriliyor (bkz.
        # _position_find_bar / resizeEvent).
        self.find_bar = QWidget(self)
        self.find_bar.setObjectName("findBar")
        self.find_bar.setStyleSheet("""
            QWidget#findBar {
                background-color: rgba(30, 30, 30, 235);
                border: 1px solid #3a3a3a;
                border-radius: 10px;
            }
            QLineEdit {
                background-color: transparent;
                border: none;
                color: #f2f2f2;
                font-size: 13px;
                font-family: 'Segoe UI', 'Ubuntu', sans-serif;
                padding: 2px 2px;
                margin: 0px;
            }
            QLabel#findCount {
                color: #8a8a8a;
                font-size: 12px;
                padding: 0px 6px;
                min-width: 34px;
            }
            QPushButton#findNavBtn, QPushButton#findCloseBtn {
                background-color: transparent;
                border: none;
                color: #a8a8a8;
                font-size: 12px;
                border-radius: 6px;
            }
            QPushButton#findNavBtn:hover, QPushButton#findCloseBtn:hover {
                background-color: #3c3c3c;
                color: #ffffff;
            }
            QPushButton#findNavBtn:disabled {
                color: #4a4a4a;
            }
        """)

        shadow = QGraphicsDropShadowEffect(self.find_bar)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 170))
        self.find_bar.setGraphicsEffect(shadow)

        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(10, 6, 6, 6)
        find_layout.setSpacing(2)

        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Sayfada ara..." if self.lang == "tr" else "Find in page...")
        self.find_input.setFixedWidth(170)
        self.find_input.textChanged.connect(self._do_find)
        self.find_input.returnPressed.connect(self._do_find_next)
        self.find_input.installEventFilter(self)

        self.find_count_label = QLabel("")
        self.find_count_label.setObjectName("findCount")
        self.find_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        find_prev = QPushButton("\u2191")
        find_prev.setObjectName("findNavBtn")
        find_prev.setFixedSize(24, 24)
        find_prev.setToolTip("Önceki" if self.lang == "tr" else "Previous")
        find_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        find_prev.clicked.connect(self._do_find_prev)

        find_next = QPushButton("\u2193")
        find_next.setObjectName("findNavBtn")
        find_next.setFixedSize(24, 24)
        find_next.setToolTip("Sonraki" if self.lang == "tr" else "Next")
        find_next.setCursor(Qt.CursorShape.PointingHandCursor)
        find_next.clicked.connect(self._do_find_next)

        find_close = QPushButton("\u2715")
        find_close.setObjectName("findCloseBtn")
        find_close.setFixedSize(24, 24)
        find_close.setToolTip("Kapat" if self.lang == "tr" else "Close")
        find_close.setCursor(Qt.CursorShape.PointingHandCursor)
        find_close.clicked.connect(self.hide_find_bar)

        find_layout.addWidget(self.find_input)
        find_layout.addWidget(self.find_count_label)
        find_layout.addWidget(find_prev)
        find_layout.addWidget(find_next)
        find_layout.addWidget(find_close)

        self.find_bar.adjustSize()
        self.find_bar.hide()

    def _position_find_bar(self):
        # Sağ üst köşeye, kenardan küçük bir boşluk bırakarak yerleştiriyoruz
        # (Chrome/Zen'deki find-in-page konumuna karşılık gelir).
        if not hasattr(self, "find_bar") or self.find_bar is None:
            return
        margin_right = 14
        margin_top = 8
        self.find_bar.adjustSize()
        x = max(0, self.width() - self.find_bar.width() - margin_right)
        self.find_bar.move(x, margin_top)
        self.find_bar.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_find_bar()

    def _create_web_view(self):
        self.view = ZoomableWebView(self, browser_tab=self)
        self.web_page = CustomWebPage(
            self.profile,
            self.view,
            action_callback=self.gem_action_triggered.emit,
            new_page_callback=self.new_page_callback,
            pdf_open_callback=lambda u: self.pdf_open_requested.emit(u),
        )
        
        self.view.setPage(self.web_page)
        self.web_page.titleChanged.connect(self.title_changed.emit)
        self.web_page.urlChanged.connect(self.url_changed.emit)
        self.web_page.iconChanged.connect(self.icon_changed.emit)
        self.web_page.loadFinished.connect(self.load_finished.emit)
        self.web_page.loadProgress.connect(self.load_progress.emit)
        self.web_page.featurePermissionRequested.connect(self._handle_permission_request)
        self.web_page.loadStarted.connect(self._on_load_started)
        self.web_page.urlChanged.connect(self._dismiss_stale_permission_popups)
        self.web_page.loadFinished.connect(self._on_load_finished)
        # HTML5 tam ekran (ör. YouTube'un tam ekran düğmesi): bu sinyal
        # bağlanmazsa sayfanın tam ekran isteği HİÇ işlenmez ve düğme
        # işlevsiz kalır.
        self.web_page.fullScreenRequested.connect(self._handle_fullscreen_request)
        # Ses durumu (sekme ikonu + sessize alma göstergesi)
        self.web_page.audioMutedChanged.connect(self._emit_audio_state)
        self.web_page.recentlyAudibleChanged.connect(self._emit_audio_state)

        # Video tam ekran durumunda view, layout'tan çıkartılıp bağımsız
        # tam ekran pencere yapıldığından bu bayrak restore/reparent
        # kararlarında kullanılıyor.
        self._is_fullscreen_view = False

        self.view.setUrl(self.initial_url)
        self.view.setZoomFactor(self.zoom_factor)
        self.layout.addWidget(self.view)
        # Suspend/restore sonrası sessize alma durumunu koru.
        if self._muted and self.web_page is not None:
            self.web_page.setAudioMuted(True)

    def _emit_audio_state(self, _changed=False):
        if self.web_page is not None:
            self._muted = self.web_page.isAudioMuted()
            self.audio_state_changed.emit(
                self._muted, self.web_page.recentlyAudible())

    def is_muted(self) -> bool:
        return self._muted

    def set_muted(self, muted: bool):
        self._muted = bool(muted)
        if self.web_page is not None:
            self.web_page.setAudioMuted(self._muted)

    def toggle_devtools(self) -> bool:
        """F12: sayfanın geliştirici araçlarını ayrı pencerede aç/kapat."""
        if self._devtools_win is not None:
            self.close_devtools()
            return False
        if self.web_page is None or self.view is None:
            return False
        dev_page = QWebEnginePage(self.profile)
        dev_view = QWebEngineView()
        dev_view.setPage(dev_page)
        win = QDialog(self, Qt.WindowType.Window)
        win.setWindowTitle("Geliştirici Araçları" if self.lang == "tr" else "Developer Tools")
        lay = QVBoxLayout(win)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(dev_view)
        win.resize(980, 660)
        self.web_page.setDevToolsPage(dev_page)
        self._devtools_win, self._devtools_page, self._devtools_view = win, dev_page, dev_view
        win.show()
        return True

    def close_devtools(self):
        if self._devtools_win is None:
            return
        try:
            if self.web_page is not None:
                self.web_page.setDevToolsPage(None)
        except RuntimeError:
            pass
        try:
            self._devtools_page.deleteLater()
            self._devtools_view.deleteLater()
            self._devtools_win.deleteLater()
        except RuntimeError:
            pass
        self._devtools_win = self._devtools_page = self._devtools_view = None

    def _handle_fullscreen_request(self, request):
        request.accept()
        if request.toggleOn():
            self._enter_view_fullscreen()
        else:
            self._exit_view_fullscreen()

    def _enter_view_fullscreen(self):
        """Sayfanın (video) tam ekran isteği: view'i sekme layout'undan
        ayırıp kendi başına tam ekran bir pencere yap."""
        if self._is_fullscreen_view or self.view is None:
            return
        self._is_fullscreen_view = True
        self.layout.removeWidget(self.view)
        self.view.setParent(None)
        self.view.setWindowFlags(Qt.WindowType.Window)
        self.view.showFullScreen()
        self.view.raise_()
        # ESC ile çıkışı kendimiz yönetiyoruz (bkz. eventFilter): bağımsız
        # pencere yapılmış view'de Chromium'un otomatik ESC davranışı
        # güvenilir değil.
        self.view.installEventFilter(self)

    def _exit_view_fullscreen(self):
        if not self._is_fullscreen_view or self.view is None:
            return
        self._is_fullscreen_view = False
        self.view.removeEventFilter(self)
        self.view.showNormal()
        self.view.setWindowFlags(Qt.WindowType.Widget)
        self.layout.addWidget(self.view)  # tekrar sekme içine yerleşir
        self.view.show()

    def _on_load_started(self):
        self._page_loading = True
        
    def _on_load_finished(self, ok: bool):
        self._page_loading = False
        if ok:
            # SPA sitelerin DOM'u tamamen çizmesi için 150ms yerine 800ms bekliyoruz.
            QTimer.singleShot(800, self._capture_thumbnail)

    @staticmethod
    def _pixmap_has_content(pixmap: QPixmap) -> bool:
        """Grab sonucu gerçek sayfa içeriği mi, yoksa düz tek renk (gri/siyah
        boşluk) mu? Gizlenmekte olan bir QWebEngineView'in grab()'ı bazen
        yalnızca sayfa arka plan rengini üretir; böyle 'boş' görüntülerin
        ÖNCEKİ geçerli küçük resmin üzerine yazılıp hover önizlemesini
        griye bozmasını engellemek için küçültülmüş kopyada renk
        çeşitliliği aranır."""
        if pixmap is None or pixmap.isNull() or pixmap.width() < 2 or pixmap.height() < 2:
            return False
        small = pixmap.scaled(24, 24, Qt.AspectRatioMode.IgnoreAspectRatio,
                              Qt.TransformationMode.FastTransformation)
        image = small.toImage()
        if image.isNull():
            return False
        first = image.pixelColor(0, 0)
        first_rgb = first.rgb() & 0xFFFFFF
        # Alfa < >%95 opak olmayan tek örnek: tamamen şeffaf da "boş" sayılır.
        if first.alpha() < 243:
            return False
        for y in range(image.height()):
            for x in range(image.width()):
                c = image.pixelColor(x, y)
                if (c.rgb() & 0xFFFFFF) != first_rgb:
                    return True
        return False

    def _capture_thumbnail(self, force: bool = False):
        if self.is_suspended or self.view is None:
            return

        # ÖNEMLİ: Sekme ekranda görünmüyorsa (arka plandaysa) grab() işlemi
        # yapma — aksi takdirde boş veya siyah ekran kaydeder. TEK istisna
        # force=True: hideEvent/suspend akışında widget TAM O ANA gizlenmektedir
        # ve Qt'da hideEvent içinde isVisible() daima False döner; sekme
        # değişimindeki "son görüntüyü yakala" mantığı bu kontrol yüzünden
        # hiçbir zaman çalışmıyordu. force=True çağrılarında grab
        # denenir; ama düz-renk/boş sonuç _pixmap_has_content ile elenip
        # eski geçerli küçük resim korunur.
        if not force and not self.isVisible():
            return

        try:
            pixmap = self.view.grab()
        except RuntimeError:
            return
        if self._pixmap_has_content(pixmap):
            # İçerik doğrulaması tam boy grab üzerinde yapılır; saklanan
            # kopya önizleme boyutunda (cover-scaled) tutulur — hover
            # popup'ı zaten bunu 220x124'e ölçekleyip kırparak gösteriyor.
            # NOT: sabitler modül düzeyindedir; self. ile erişilemez.
            self._thumbnail = pixmap.scaled(
                _THUMB_STORE_W, _THUMB_STORE_H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )

    # Kullanıcı sekme değiştirdiğinde, sekme arka plana atılmadan hemen ÖNCE son görüntüyü yakala
    def hideEvent(self, event):
        self._capture_thumbnail(force=True)
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        # Sekme görünür hale geldikten kısa süre sonra (sayfa compositing'i
        # hazır olunca) güncel görüntüyü yakala. hideEvent'teki grab bazen
        # düz renk döndürebildiğinden, görünür durumdayken yapılan bu
        # yakalama önizlemelerin güvenilir kaynağıdır.
        QTimer.singleShot(600, self._capture_thumbnail)

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
        # Chrome tarzı konum: kart, ana pencere içine yerleşen CHILD
        # OVERLAY olarak adres çubuğunun hemen altında, sol kilit
        # simgesinin hizasında açılır (Wayland dahil konum garantili).
        anchor = getattr(main_window, "url_bar", None)
        main_settings = getattr(main_window, "settings", None)
        accent = gem_theme.get_accent_color(getattr(main_settings, "current", None)) if main_settings else None
        popup = PermissionPopup(host, feature, lang=self.lang, parent=main_window, accent=accent)
        # completed → kararı uygula + listeyi güncelle (popup deleteLater
        # edilir; referansı listede kalmışsa silinmiş nesneye erişim çökerdi)
        popup.completed.connect(
            lambda granted, p=popup, o=origin, f=feature:
            self._on_permission_completed(p, o, f, granted))
        # stack_index: BANA dahil olmayan mevcut kart sayısı — append'ten
        # ÖNCE hesaplanır (aksi halde kart kendi yüksekliği kadar aşağı kayar)
        stack = len(self._active_permission_popups)
        self._active_permission_popups.append(popup)
        popup.show_at(anchor, stack_index=stack)
        popup.raise_()
        # NOT: odak çalmaz — kullanıcı arkadaki sayfada yazmaya/tıklamaya
        # devam edebilir (non-modal child overlay).

    def _on_permission_completed(self, popup, origin: QUrl, feature, granted: bool):
        if popup in self._active_permission_popups:
            self._active_permission_popups.remove(popup)
        policy = (
            QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
            if granted else
            QWebEnginePage.PermissionPolicy.PermissionDeniedByUser
        )
        if self.web_page is not None:
            self.web_page.setFeaturePermission(origin, feature, policy)

    def _dismiss_stale_permission_popups(self, url: QUrl):
        """Sekme başka bir origin'e gezinirse bekleyen izin kartlarını
        otomatik reddet (Chrome davranışı: gezinme isteği düşer)."""
        host = url.host()
        for popup in list(self._active_permission_popups):
            if getattr(popup, "origin_host", "") and popup.origin_host != host:
                popup.reject()

    def _close_all_permission_popups(self):
        for popup in list(self._active_permission_popups):
            popup.reject()

    def show_find_bar(self):
        self._position_find_bar()
        self.find_bar.show()
        self.find_bar.raise_()
        self.find_input.setFocus()
        self.find_input.selectAll()
        # Find bar açıkken, bulunduğu widget hiyerarşisi dışında herhangi bir
        # widget'a odak geçerse (kullanıcı sayfaya veya başka bir yere
        # tıklarsa) bar'ı otomatik kapatmak için uygulama genelindeki odak
        # değişikliklerini dinliyoruz.
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_app_focus_changed)

    def hide_find_bar(self):
        self.find_bar.hide()
        self.find_count_label.setText("")
        if self.view: self.view.page().findText("")
        app = QApplication.instance()
        if app is not None:
            try:
                app.focusChanged.disconnect(self._on_app_focus_changed)
            except TypeError:
                pass

    def _on_app_focus_changed(self, old, new):
        # Yeni odaklanan widget find_bar'ın kendisi ya da bir çocuğu değilse
        # (örn. web sayfasına, adres çubuğuna vb. tıklandıysa) find_bar'ı kapat.
        if not self.find_bar.isVisible():
            return
        if new is not None and (new is self.find_bar or self.find_bar.isAncestorOf(new)):
            return
        self.hide_find_bar()

    def eventFilter(self, obj, event):
        if obj is self.find_input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.hide_find_bar()
                return True
        # Video tam ekranındayken ESC (diğer tarayıcılardaki gibi):
        # 1) Sayfanın fullscreen durumu JS exitFullscreen() ile düzgün
        #    sıfırlanır (triggerAction yerine JS tercih edildi: native
        #    aksiyon, sayfa tam ekranda değilken bazı Qt sürümlerinde
        #    kararsız davranıyor).
        # 2) Düzen hemen normale döner (sinyal beklemeden; sayfa çıkışı
        #    fullScreenRequested(toggleOff) sinyali üretirse işleyici
        #    korumalı/no-op olur).
        # ÖNEMLİ: getattr ile eriş — bu filtre _build_find_bar sırasında
        # find_input'a da takılıdır ve o anda self.view HENÜZ yoktur;
        # doğrudan self.view erişimi AttributeError -> PyQt qFatal/abort
        # ile süreci çökertirdi.
        if (obj is getattr(self, "view", None)
                and getattr(self, "_is_fullscreen_view", False)
                and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape):
            try:
                self.web_page.runJavaScript(
                    "if(document.fullscreenElement){document.exitFullscreen();}")
            except RuntimeError:
                pass
            self._exit_view_fullscreen()
            return True
        return super().eventFilter(obj, event)

    def _do_find(self, text):
        if not self.view:
            return
        if not text:
            self.find_count_label.setText("")
            self.view.page().findText("")
            return
        self.view.page().findText(text, resultCallback=self._on_find_result)

    def _do_find_next(self):
        text = self.find_input.text()
        if self.view and text:
            self.view.page().findText(text, resultCallback=self._on_find_result)

    def _do_find_prev(self):
        text = self.find_input.text()
        if self.view and text:
            self.view.page().findText(
                text, QWebEnginePage.FindFlag.FindBackward, resultCallback=self._on_find_result
            )

    def _on_find_result(self, result):
        # QWebEngineFindTextResult: Qt >= 5.14. Chrome/Zen'deki "3/17" tarzı
        # göstergeyi burada üretiyoruz.
        try:
            total = result.numberOfMatches()
            active = result.activeMatch()
        except AttributeError:
            return
        if not self.find_input.text():
            self.find_count_label.setText("")
        elif total == 0:
            self.find_count_label.setText("0/0")
        else:
            self.find_count_label.setText(f"{active}/{total}")

    def suspend(self):
        if self.is_suspended or not self.view: return
        # Video tam ekranındaysa önce normale dön: view bağımsız bir tam
        # ekran pencere iken uyutulursa pencere yüzen boş bir tam ekran
        # olarak kalırdı.
        if getattr(self, "_is_fullscreen_view", False):
            self._exit_view_fullscreen()
        # Geliştirici araçları view'e bağlı; sayfa yok edilmeden kapat.
        self.close_devtools()
        self._close_all_permission_popups()
        # Widget hâlâ görünürken (uyutma işleminin başında) son görüntüyü
        # yakala; view yok edilmeden önce grab edilmesi gerekir.
        self._capture_thumbnail(force=True)
        self.saved_url = self.view.url()
        self.layout.removeWidget(self.view)
        self.view.deleteLater()
        self.view = None
        # ÖNEMLİ: web_page, view'in çocuğu (parent) olduğu için view
        # deleteLater() ile silinince web_page de C++ tarafında yok
        # edilecek. Ama self.web_page referansını None'a çekmezsek elimizde
        # "zombi" bir nesne kalır: Python tarafında hâlâ dolu (not None)
        # görünür ama altındaki C++ nesnesi ölüdür. Bu da örneğin cleanup()
        # içindeki "if self.web_page is not None" kontrolünü yanıltıp
        # uyuyan bir sekme kapatıldığında silinmiş bir nesne üzerinde
        # .setUrl() çağrılmasına (RuntimeError / çökme) ya da belleğin
        # düzgün serbest bırakılmamasına yol açıyordu.
        self.web_page = None

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
        # _create_web_view() initial_url'i yükler; initial_url'i kayıtlı
        # adrese çevirmeden eski "restore sonrası setUrl" yaklaşımı, önce
        # orijinal yeni-sekme sayfasını sonra hedefi YÜKLEYECEĞİ için uyuyan
        # sekmelerde çifte yükleme/yeni-sekme sayfasının yanıp sönmesine yol
        # açıyordu. Tek yükleme: initial_url'i baştan doğru ver.
        self.initial_url = QUrl(getattr(self, "saved_url", self.initial_url))
        self._create_web_view()
        self.is_suspended = False

    def cleanup(self):
        self._close_all_permission_popups()
        self.close_devtools()
        if self.web_page is not None:
            self.web_page.setUrl(QUrl("about:blank")) 
            self.web_page.deleteLater()
            self.web_page = None
        if self.view is not None:
            self.view.setPage(None)
            self.view.deleteLater()
            self.view = None
