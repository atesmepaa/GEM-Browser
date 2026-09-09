"""
Siteler kamera, mikrofon, konum, bildirim gibi izin istediğinde beliren,
kullanıcı karar verene kadar duran küçük onay kartı.

Konumlandırma: artık pencerenin sol üst köşesine değil, sekme barının
hemen ALTINA, sol kenara hizalı olarak açılıyor — böylece toolbar/sekme
barının üzerini kapatmıyor ve hangi sekmeyle ilgili olduğu daha açık
oluyor (indirme bildirimlerinin sağ üstte çıkmasıyla simetrik bir
karşı köşe yerine, artık tarayıcının "içerik" alanının hemen başına
oturuyor).
"""

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QApplication, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWebEngineCore import QWebEnginePage

from gem_browser import theme as gem_theme

POPUP_MARGIN = 16
POPUP_SPACING = 10

# URL çubuğuyla (bkz. window.py QLineEdit stili) aynı yazı ailesi, tutarlı
# bir görünüm için burada da kullanılıyor.
UI_FONT_FAMILY = "'Segoe UI', 'Ubuntu', sans-serif"

_FEATURE_LABELS = {
    QWebEnginePage.Feature.Geolocation: {
        "tr": "konumunuza erişmek istiyor",
        "en": "wants to access your location",
    },
    QWebEnginePage.Feature.MediaAudioCapture: {
        "tr": "mikrofonunuzu kullanmak istiyor",
        "en": "wants to use your microphone",
    },
    QWebEnginePage.Feature.MediaVideoCapture: {
        "tr": "kameranızı kullanmak istiyor",
        "en": "wants to use your camera",
    },
    QWebEnginePage.Feature.MediaAudioVideoCapture: {
        "tr": "kamera ve mikrofonunuzu kullanmak istiyor",
        "en": "wants to use your camera and microphone",
    },
    QWebEnginePage.Feature.Notifications: {
        "tr": "size bildirim göndermek istiyor",
        "en": "wants to send you notifications",
    },
    QWebEnginePage.Feature.MouseLock: {
        "tr": "fare imlecinizi kilitlemek istiyor",
        "en": "wants to lock your mouse cursor",
    },
    QWebEnginePage.Feature.DesktopVideoCapture: {
        "tr": "ekranınızı paylaşmak istiyor",
        "en": "wants to capture your screen",
    },
    QWebEnginePage.Feature.DesktopAudioVideoCapture: {
        "tr": "ekranınızı ve sesinizi paylaşmak istiyor",
        "en": "wants to capture your screen and audio",
    },
}

# Her özellik için küçük bir rozet ikonu — kartı taramak (scan) kolaylaşsın
# diye salt metnin önüne görsel bir ipucu ekliyor.
_FEATURE_ICONS = {
    QWebEnginePage.Feature.Geolocation: "📍",
    QWebEnginePage.Feature.MediaAudioCapture: "🎤",
    QWebEnginePage.Feature.MediaVideoCapture: "🎥",
    QWebEnginePage.Feature.MediaAudioVideoCapture: "🎥",
    QWebEnginePage.Feature.Notifications: "🔔",
    QWebEnginePage.Feature.MouseLock: "🖱️",
    QWebEnginePage.Feature.DesktopVideoCapture: "🖥️",
    QWebEnginePage.Feature.DesktopAudioVideoCapture: "🖥️",
}


def feature_label(feature, lang="tr") -> str:
    entry = _FEATURE_LABELS.get(feature)
    if entry:
        return entry.get(lang, entry["tr"])
    return "bir izin istiyor" if lang == "tr" else "is requesting a permission"


def feature_icon(feature) -> str:
    return _FEATURE_ICONS.get(feature, "🔒")


class _CardContainer(QWidget):
    """Gerçek kartın çizildiği iç widget. Dış QDialog şeffaf tutulup
    (WA_TranslucentBackground) yuvarlak köşelerin dışına taşan piksel
    olmaması için tüm görsel stil bu iç widget üzerinde uygulanıyor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("permCard")


class PermissionPopup(QDialog):
    """
    Reddet/İzin Ver butonlarıyla tek bir izin isteğini gösterir. Modal
    DEĞİLDİR — kullanıcı sayfayla etkileşime devam edebilirken karar
    verene kadar ekranda kalır. Sonuç `finished` sinyali (Accepted/Rejected)
    üzerinden okunur.
    """

    def __init__(self, origin_host: str, feature, lang: str = "tr", parent=None, accent: str = None):
        super().__init__(parent)
        self.lang = lang
        self.feature = feature
        accent = accent or gem_theme.DEFAULT_ACCENT_DARK
        accent_hover = gem_theme.lighten(accent)
        accent_text = gem_theme.readable_text_color(accent)

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(340)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        self._card_widget = _CardContainer(self)
        outer_layout.addWidget(self._card_widget)

        self._card_widget.setStyleSheet(
            "QWidget#permCard { background-color: #242424; border: 1px solid rgba(255, 255, 255, 0.08); "
            "border-radius: 14px; } "
            f"QLabel {{ background: transparent; color: #ffffff; font-family: {UI_FONT_FAMILY}; font-size: 13px; }} "
            "QLabel#permHost { font-weight: 600; } "
            "QLabel#permIcon { font-size: 22px; } "
            "QPushButton { background-color: transparent; color: #b0b0b0; border: 1px solid rgba(255, 255, 255, 0.12); "
            f"font-family: {UI_FONT_FAMILY}; font-size: 13px; font-weight: 500; "
            "padding: 7px 16px; border-radius: 16px; } "
            "QPushButton:hover { background-color: rgba(255, 255, 255, 0.06); color: #ffffff; } "
            "QPushButton#allowBtn { background-color: " + accent + "; color: " + accent_text + "; border: 1px solid " + accent + "; } "
            "QPushButton#allowBtn:hover { background-color: " + accent_hover + "; border: 1px solid " + accent_hover + "; }"
        )

        content = QVBoxLayout(self._card_widget)
        content.setContentsMargins(16, 14, 16, 14)
        content.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        icon_lbl = QLabel(feature_icon(feature))
        icon_lbl.setObjectName("permIcon")
        icon_lbl.setFixedWidth(28)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        top_row.addWidget(icon_lbl)

        host = origin_host or ("bu site" if lang == "tr" else "this site")
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        host_lbl = QLabel(host)
        host_lbl.setObjectName("permHost")
        host_lbl.setWordWrap(True)
        desc_lbl = QLabel(feature_label(feature, lang))
        desc_lbl.setWordWrap(True)
        text_col.addWidget(host_lbl)
        text_col.addWidget(desc_lbl)
        top_row.addLayout(text_col, 1)

        content.addLayout(top_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        self.deny_btn = QPushButton("Reddet" if lang == "tr" else "Deny")
        self.allow_btn = QPushButton("İzin Ver" if lang == "tr" else "Allow")
        self.allow_btn.setObjectName("allowBtn")
        self.deny_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.allow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addWidget(self.deny_btn)
        btn_row.addWidget(self.allow_btn)
        content.addLayout(btn_row)

        self.deny_btn.clicked.connect(self.reject)
        self.allow_btn.clicked.connect(self.accept)

        shadow = QGraphicsDropShadowEffect(self._card_widget)
        shadow.setBlurRadius(28)
        shadow.setXOffset(0)
        shadow.setYOffset(6)
        shadow.setColor(QColor(0, 0, 0, 140))
        self._card_widget.setGraphicsEffect(shadow)

    def position_below_tab_bar(self, anchor_widget=None, stack_index: int = 0):
        """
        Popup'ı verilen `anchor_widget`'ın (tipik olarak sekme barının)
        SOL ALT köşesinin hemen altına, sol kenara hizalı şekilde konumlar.
        `anchor_widget` verilmez/görünür değilse ekranın sol üstüne düşer.
        """
        self.adjustSize()
        if anchor_widget is not None and anchor_widget.isVisible():
            bottom_left = anchor_widget.mapToGlobal(anchor_widget.rect().bottomLeft())
            x = bottom_left.x() + POPUP_MARGIN
            y = bottom_left.y() + POPUP_SPACING + stack_index * (self.height() + POPUP_SPACING)
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.x() + POPUP_MARGIN
            y = screen.y() + POPUP_MARGIN + stack_index * (self.height() + POPUP_SPACING)
        self.move(x, y)

    # Geriye dönük uyumluluk: eski isimle çağrılırsa da artık sekme barının
    # altına hizalar (eski davranış pencere köşesine hizalıyordu). `parent`
    # bir MainWindow ise `tab_widget.tabBar()` otomatik bulunur.
    def position_top_left(self, parent=None, stack_index: int = 0):
        anchor = None
        if parent is not None:
            tab_widget = getattr(parent, "tab_widget", None)
            if tab_widget is not None:
                anchor = tab_widget.tabBar()
        self.position_below_tab_bar(anchor, stack_index=stack_index)
