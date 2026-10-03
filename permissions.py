"""
Site izin istekleri (kamera, mikrofon, konum, bildirim...) için Chrome
tarzı kompakt flyout kart.

MİMARİ NOT: Bu kart bir QDialog DEĞİL, ana pencerenin içine yerleşen bir
child overlay widget'tır. Neden: Wayland'da (KDE/GNOME varsayılı) uygulamalar
kendi top-level pencerelerini EKRAN ÜZERİNDE KONUMLANDIRAMAZ — QDialog
yaklaşımı pencere yöneticisi tarafından ortalanıyordu. Child overlay ise
ana pencere koordinatlarında piksel piksel yerleştirilir; X11/Wayland
farkı gözetmez.

Konum: adres çubuğunun hemen altı, sol kilit simgesinin hizası (Chrome
izin baloncuğu gibi). Dikey modda sekme çubuğu gizliyken pencere köşesine
düşer. Birden çok istek stack_index ile aşağı yığınlanır.

Davranış: NON-MODAL ve bloklamaz — kart yalnızca kendi dikdörtgeni
üzerindeki tıklamaları alır; sayfada gezinme/tıklama/yazma kesilmez.
Sekme başka bir origin'e gezinirse bekleyen kartlar otomatik reddedilir
(bkz. browser_tab._dismiss_stale_permission_popups).
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics
from PyQt6.QtWebEngineCore import QWebEnginePage

from gem_browser import theme as gem_theme

UI_FONT_FAMILY = "Segoe UI"

_FEATURE_LABELS = {
    QWebEnginePage.Feature.Geolocation: {
        "tr": "konumunuzu kullanmak istiyor",
        "en": "wants to use your location",
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
        "tr": "bildirim göndermek istiyor",
        "en": "wants to send notifications",
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


class PermissionPopup(QWidget):
    """Tek bir izin isteğini gösteren, Chrome tarzı kompakt flyout.

    Child overlay olarak çalışır; completed(bool) sinyali kullanıcının
    kararını bildirir (True = İzin Ver). dismiss() dışarıdan reddetmek
    için kullanılır (gezinti, suspend, temizlik akışları).
    """

    completed = pyqtSignal(bool)  # granted

    def __init__(self, origin_host: str, feature, lang: str = "tr", parent=None, accent: str = None):
        super().__init__(parent)
        self.origin_host = origin_host or ""
        self.feature = feature
        self.lang = lang

        # Child overlay: sayfanın ÜZERİNDE çizilmesi için saydam arka plan
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        accent = accent or gem_theme.DEFAULT_ACCENT_DARK
        accent_hover = gem_theme.lighten(accent)
        accent_text = gem_theme.readable_text_color(accent)

        icon_char = feature_icon(feature)
        label_text = feature_label(feature, lang)
        host = self.origin_host or ("bu site" if lang == "tr" else "this site")

        # --- dinamik genişlik: içeriğe sığar, üst sınır 380px ---
        origin_font = QFont(UI_FONT_FAMILY, 10)
        origin_font.setBold(True)
        origin_w = QFontMetrics(origin_font).horizontalAdvance(host)
        self.setFixedWidth(max(260, min(origin_w + 34 + 24, 380)))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QWidget(self)
        card.setObjectName("permCard")
        root.addWidget(card)
        card.setStyleSheet(
            "QWidget#permCard { background-color: #242424; border: 1px solid rgba(255, 255, 255, 0.10); "
            "border-radius: 12px; } "
            f"QLabel {{ background: transparent; color: #ffffff; font-family: '{UI_FONT_FAMILY}'; }}"
            "QLabel#permHost { font-size: 12px; font-weight: 600; } "
            "QLabel#permDesc { font-size: 12px; color: #b8b8c0; } "
            "QLabel#permIcon { font-size: 16px; background: transparent; } "
            "QPushButton { background-color: transparent; color: #b0b0b0; border: 1px solid rgba(255, 255, 255, 0.12); "
            f"font-family: '{UI_FONT_FAMILY}'; font-size: 12px; font-weight: 500; "
            "padding: 5px 14px; border-radius: 14px; } "
            "QPushButton:hover { background-color: rgba(255, 255, 255, 0.06); color: #ffffff; } "
            "QPushButton#allowBtn { background-color: " + accent + "; color: " + accent_text + "; border: 1px solid " + accent + "; } "
            "QPushButton#allowBtn:hover { background-color: " + accent_hover + "; border: 1px solid " + accent_hover + "; }"
        )

        content = QVBoxLayout(card)
        content.setContentsMargins(12, 10, 12, 10)
        content.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        icon_lbl = QLabel(icon_char)
        icon_lbl.setObjectName("permIcon")
        icon_lbl.setFixedSize(20, 20)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        top_row.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        host_lbl = QLabel(host)
        host_lbl.setObjectName("permHost")
        host_lbl.setWordWrap(True)
        desc_lbl = QLabel(label_text)
        desc_lbl.setObjectName("permDesc")
        desc_lbl.setWordWrap(True)
        text_col.addWidget(host_lbl)
        text_col.addWidget(desc_lbl)
        top_row.addLayout(text_col, 1)
        content.addLayout(top_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.addStretch()
        deny_btn = QPushButton("Reddet" if lang == "tr" else "Deny")
        allow_btn = QPushButton("İzin Ver" if lang == "tr" else "Allow")
        allow_btn.setObjectName("allowBtn")
        deny_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        allow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addWidget(deny_btn)
        btn_row.addWidget(allow_btn)
        content.addLayout(btn_row)

        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(24)
        shadow.setXOffset(0)
        shadow.setYOffset(4)
        shadow.setColor(QColor(0, 0, 0, 120))
        card.setGraphicsEffect(shadow)

        self.deny_btn = deny_btn
        self.allow_btn = allow_btn
        deny_btn.clicked.connect(self.reject)
        allow_btn.clicked.connect(self.accept)

    def position_at_url_bar(self, anchor_widget, stack_index: int = 0):
        """Adres çubuğunun hemen altına, sol kilit simgesinin altına
        hizalar. Child overlay olduğu için konum ANA PENCERE
        koordinatlarındadır — Wayland dahil her yerde birebir çalışır."""
        self.adjustSize()
        parent = self.parentWidget()
        if anchor_widget is not None and parent is not None:
            tl = anchor_widget.mapTo(parent, anchor_widget.rect().topLeft())
            bl = anchor_widget.mapTo(parent, anchor_widget.rect().bottomLeft())
            x = tl.x() + 34  # adres çubuğunun sol simgesinin altı
            y = bl.y() + 6 + stack_index * (self.height() + 8)
        else:
            x, y = 40, 96
        self.move(x, y)

    def show_at(self, anchor_widget, stack_index: int = 0):
        """Konumlandır + göster + sayfa içeriğinin üstüne taşı."""
        self.position_at_url_bar(anchor_widget, stack_index)
        self.show()
        self.raise_()

    def accept(self):
        self.completed.emit(True)
        self.hide()
        self.deleteLater()

    def reject(self):
        self.completed.emit(False)
        self.hide()
        self.deleteLater()

    def dismiss(self):
        """Dışarıdan reddetme (gezinti, suspend, sekme kapanışı)."""
        self.reject()
