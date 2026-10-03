"""
Uygulama genelinde kullanılan modern bildirim/onay kartları.

İKİ YOLLU MİMARİ:
- OverlayPopup: ana pencere içine yerleşen CHILD OVERLAY widget. Ana
  pencereden (url_bar + tab_widget sahibi) çağrılan tüm bilgi/onay
  pop-up'ları bu yapıyı kullanır: Chrome'daki gibi adres çubuğunun hemen
  altında, sol kilit simgesinin hizasında açılır; NON-MODAL ve bloklamaz
  (Wayland'da top-level pencere konumlandırılamadığı için QDialog yaklaşımı
  ortada açılıyordu — bkz. 1.0.1 sonrası yeniden yapılandırma).
- ModernPopup (QDialog): diyalog içi bağlamlar (Ayarlar, Şifre
  Yöneticisi...) için kalıcı modal kart olarak korunur.

show_modern_confirm/show_modern_info, ebeveyne göre OTOMATİK yol seçer;
dönüş değeri (onay = bool) QEventLoop ile senkron korunur — mevcut tüm
çağrılar değişmeden çalışır.
"""

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGraphicsDropShadowEffect, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QEventLoop, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics

from gem_browser import theme as gem_theme

_DARK_POPUP_COLORS = {
    "bg": "#242424", "border": "rgba(255, 255, 255, 0.08)",
    "text": "#ffffff", "muted": "#b0b0b0", "hover": "rgba(255, 255, 255, 0.06)",
}
_LIGHT_POPUP_COLORS = {
    "bg": "#ffffff", "border": "rgba(0, 0, 0, 0.08)",
    "text": "#1a1a1a", "muted": "#666666", "hover": "rgba(0, 0, 0, 0.05)",
}
_POPUP_FONT = "'Segoe UI', 'Ubuntu', sans-serif"


def _popup_theme(widget) -> str:
    """
    Açık/koyu temayı üç farklı çağıran şekli için de doğru tespit eder:
    - MainWindow: `self.settings` bir BrowserSettings nesnesi (`.current` dict'i var).
    - PasswordManagerDialog: `self.settings` zaten doğrudan dict'in kendisi.
    - DownloadsDialog: `self.settings` hiç yok, sadece `self.parent_window` (MainWindow) var.
    """
    settings = getattr(widget, "settings", None)
    if settings is None:
        candidate = getattr(widget, "parent_window", None)
        if candidate is None and hasattr(widget, "window"):
            candidate = widget.window()
        settings = getattr(candidate, "settings", None)

    current = getattr(settings, "current", settings) if settings is not None else None
    if isinstance(current, dict) and current.get("ui_theme") == "light":
        return "light"
    return "dark"


def _popup_accent(widget) -> str:
    """`_popup_theme` ile aynı ebeveyn-zinciri mantığıyla en yakın
    `settings` kaynağını bulup oradaki (varsa) özel vurgu rengini,
    yoksa temaya göre varsayılanı döndürür."""
    settings = getattr(widget, "settings", None)
    if settings is None:
        candidate = getattr(widget, "parent_window", None)
        if candidate is None and hasattr(widget, "window"):
            candidate = widget.window()
        settings = getattr(candidate, "settings", None)

    current = getattr(settings, "current", settings) if settings is not None else None
    if isinstance(current, dict):
        return gem_theme.get_accent_color(current)
    return gem_theme.default_accent_for_theme(_popup_theme(widget))


def _make_card(parent, title, message, buttons, icon_glyph="", theme="dark", accent=None):
    """ModernPopup ve OverlayPopup'ın paylaştığı kart inşası.
    (card, button_widgets) döndürür — layout'a eklenmesi çağıranın işi."""
    colors = _LIGHT_POPUP_COLORS if theme == "light" else _DARK_POPUP_COLORS
    accent = accent or gem_theme.default_accent_for_theme(theme)
    accent_hover = gem_theme.lighten(accent)
    accent_text = gem_theme.readable_text_color(accent)

    card = QWidget(parent)
    card.setObjectName("modernPopupCard")
    card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    card.setStyleSheet(f"""
        QWidget#modernPopupCard {{
            background-color: {colors['bg']};
            border: 1px solid {colors['border']};
            border-radius: 14px;
        }}
        QLabel {{
            background: transparent;
            color: {colors['text']};
            font-family: {_POPUP_FONT};
            font-size: 13px;
        }}
        QLabel#popupTitle {{ font-size: 15px; font-weight: 600; }}
        QLabel#popupIcon {{ font-size: 24px; background: transparent; }}
        QPushButton {{
            background-color: transparent;
            color: {colors['muted']};
            border: 1px solid {colors['border']};
            font-family: {_POPUP_FONT};
            font-size: 12px;
            font-weight: 500;
            padding: 6px 16px;
            border-radius: 14px;
        }}
        QPushButton:hover {{ background-color: {colors['hover']}; color: {colors['text']}; }}
        QPushButton#primaryBtn {{ background-color: {accent}; color: {accent_text}; border: 1px solid {accent}; }}
        QPushButton#primaryBtn:hover {{ background-color: {accent_hover}; border: 1px solid {accent_hover}; }}
        QPushButton#dangerBtn {{ background-color: #e74c3c; color: #ffffff; border: 1px solid #e74c3c; }}
        QPushButton#dangerBtn:hover {{ background-color: #f1604f; border: 1px solid #f1604f; }}
    """)

    content = QVBoxLayout(card)
    content.setContentsMargins(14, 12, 14, 12)
    content.setSpacing(8)

    top_row = QHBoxLayout()
    top_row.setSpacing(10)
    if icon_glyph:
        icon_lbl = QLabel(icon_glyph)
        icon_lbl.setObjectName("popupIcon")
        icon_lbl.setFixedSize(26, 26)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        top_row.addWidget(icon_lbl)

    text_col = QVBoxLayout()
    text_col.setSpacing(3)
    if title:
        title_lbl = QLabel(title)
        title_lbl.setObjectName("popupTitle")
        title_lbl.setWordWrap(True)
        text_col.addWidget(title_lbl)
    msg_lbl = QLabel(message)
    msg_lbl.setWordWrap(True)
    # ÖNEMLİ: msg_lbl, iç içe QHBoxLayout (top_row) -> QVBoxLayout
    # (text_col) içinde. Qt'nin layout sistemi, wordWrap açık bir
    # QLabel'ın "heightForWidth" bilgisini bu tür iç içe kutu
    # layout'lar üzerinden dış layout'a doğru iletmiyor (bilinen bir
    # sınırlama) — gereken yüksekliği QFontMetrics ile elle hesaplıyoruz.
    icon_col_width = 26 + 10 if icon_glyph else 0
    wrap_width = 360 - 28 - icon_col_width
    metrics = QFontMetrics(msg_lbl.font())
    text_rect = metrics.boundingRect(
        QRect(0, 0, wrap_width, 10000),
        Qt.TextFlag.TextWordWrap,
        message,
    )
    msg_lbl.setMinimumHeight(text_rect.height() + 4)
    text_col.addWidget(msg_lbl)
    top_row.addLayout(text_col, 1)
    content.addLayout(top_row)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(6)
    btn_row.addStretch()
    for text, role in buttons:
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addWidget(btn)
    content.addLayout(btn_row)

    shadow = QGraphicsDropShadowEffect(card)
    shadow.setBlurRadius(28)
    shadow.setXOffset(0)
    shadow.setYOffset(5)
    shadow.setColor(QColor(0, 0, 0, 140))
    card.setGraphicsEffect(shadow)

    return card


class OverlayPopup(QWidget):
    """Ana pencere içine yerleşen, adres çubuğu altına ankrajlanan
    non-modal bilgi/onay kartı. complete(role) ile kapanır; completed(role)
    kararı bildirir. Wayland dahil konum garantilidir (child widget)."""

    completed = pyqtSignal(str)

    def __init__(self, parent, title, message, buttons, icon_glyph="", theme="dark", accent=None):
        super().__init__(parent)
        self._done = False
        self._completed_role = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # dinamik genişlik: içerik metnine sığar (260–380 px bandı)
        fm = QFontMetrics(QFont("Segoe UI", 10))
        msg_w = fm.horizontalAdvance(message)
        title_w = fm.horizontalAdvance(title) if title else 0
        self.setFixedWidth(max(260, min(max(msg_w, title_w) + 44, 380)))

        card = _make_card(self, title, message, buttons, icon_glyph, theme, accent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

        for text, role in buttons:
            btn = self._button_for(text)
            btn.clicked.connect(lambda checked=False, r=role: self.complete(r))

    def _button_for(self, text):
        from PyQt6.QtWidgets import QPushButton
        for b in self.findChildren(QPushButton):
            if b.text() == text:
                return b
        return None

    def complete(self, role: str):
        if self._done:
            return
        self._done = True
        self._completed_role = role
        self.completed.emit(role)
        self.hide()
        self.deleteLater()

    def position_at_url_bar(self, anchor_widget, stack_index: int = 0):
        """Adres çubuğunun hemen altına, sol kilit simgesinin altına
        hizalar (ana pencere koordinatları — Wayland dahil garantili)."""
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
        self.position_at_url_bar(anchor_widget, stack_index)
        self.show()
        self.raise_()


def _uses_overlay(parent) -> bool:
    """Ana pencere bağlamı mı? (url_bar + tab_widget sahibi) — öyleyse
    pop-up'lar child overlay olarak adres çubuğu altında açılır."""
    return parent is not None and hasattr(parent, "url_bar") and hasattr(parent, "tab_widget")


def _run_overlay(parent, title, message, buttons, icon_glyph, auto_close_ms=None):
    """Overlay pop-up'ı gösterip karar kullanıcıdan gelene kadar (veya
    otomatik kapanana kadar) senkron bekler — mevcut çağrılar değişmeden
    çalışır, ama artık BLOKLAMAZ: bekleme sırasında tarayıcı kullanılabilir.
    Dönen değer: tıklanan butonun rolü ('primary'/'danger'/'secondary'/None)."""
    theme = _popup_theme(parent)
    accent = _popup_accent(parent)
    overlay = OverlayPopup(parent, title, message, buttons, icon_glyph, theme, accent)

    stack = len([c for c in parent.findChildren(OverlayPopup) if c.isVisible()])
    overlay.show_at(parent.url_bar, stack_index=stack)

    loop = QEventLoop()
    overlay.completed.connect(loop.quit)
    overlay.destroyed.connect(loop.quit)  # pencere kapanırsa kilitlenmesin
    if auto_close_ms:
        auto_role = buttons[0][1] if buttons else "primary"
        QTimer.singleShot(auto_close_ms, lambda: overlay.complete(auto_role))
    loop.exec()
    return getattr(overlay, "_completed_role", None)


class ModernPopup(QDialog):
    """Diyalog içi bağlamlar için modal kart (Ayarlar, Şifre Yöneticisi...).
    Ana pencere pop-up'ları artık OverlayPopup kullanır."""

    def __init__(self, parent, title, message, buttons, icon_glyph="", theme="dark", accent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedWidth(360)
        self._result_role = None

        card = _make_card(self, title, message, buttons, icon_glyph, theme, accent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        for text, role in buttons:
            btn = self._button_for(text)
            btn.clicked.connect(lambda checked=False, r=role: self._on_button(r))

        self.adjustSize()

    def _button_for(self, text):
        from PyQt6.QtWidgets import QPushButton
        for b in self.findChildren(QPushButton):
            if b.text() == text:
                return b
        return None

    def _on_button(self, role):
        self._result_role = role
        self.accept()

    def result_role(self):
        return self._result_role


def show_modern_info(parent, message: str, title: str = "", lang: str = "tr", warning: bool = False):
    """Bilgi kartı — ana pencerede NON-BLOKLAYAN overlay (5 sn sonra
    kendiliğinden kapanır), diyaloğun içindeyse modal kart."""
    icon = "⚠️" if warning else "ℹ️"
    ok_text = "Tamam" if lang == "tr" else "OK"
    if _uses_overlay(parent):
        _run_overlay(parent, title, message, [(ok_text, "primary")], icon, auto_close_ms=5000)
        return None
    dlg = ModernPopup(
        parent, title, message,
        buttons=[(ok_text, "primary")],
        icon_glyph=icon, theme=_popup_theme(parent), accent=_popup_accent(parent),
    )
    dlg.exec()
    return None


def show_modern_confirm(parent, message: str, title: str = "", lang: str = "tr", danger: bool = False) -> bool:
    """Evet/Hayır onay kartı. Ana pencerede NON-BLOKLAYAN overlay olarak
    açılır (dönüş QEventLoop ile senkron); diyaloğun içindeyse modal."""
    yes_text = "Evet" if lang == "tr" else "Yes"
    no_text = "Hayır" if lang == "tr" else "No"
    buttons = [(no_text, "secondary"), (yes_text, "danger" if danger else "primary")]
    if _uses_overlay(parent):
        role = _run_overlay(parent, title, message, buttons, "❔")
        return role in ("primary", "danger")
    dlg = ModernPopup(
        parent, title, message,
        buttons=buttons,
        icon_glyph="❔", theme=_popup_theme(parent), accent=_popup_accent(parent),
    )
    dlg.exec()
    return dlg.result_role() in ("primary", "danger")
