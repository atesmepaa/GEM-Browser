"""
Uygulama genelinde (ana pencere, şifre yöneticisi, indirmeler penceresi)
kullanılan; varsayılan QMessageBox'ın keskin köşeli, ikonun arkasında
çirkin/koyu bir plaka barındıran sistem görünümü yerine geçen; temayla
(açık/koyu) uyumlu, tamamen yuvarlak köşeli ve hafif gölgeli modern
bildirim/onay kartı.

Diğer modüllerin (password_manager.py, downloads_dialog.py, window.py)
döngüsel import'a girmeden ortak kullanabilmesi için ayrı bir dosyada.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QPushButton,
    QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QFontMetrics

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


class ModernPopup(QDialog):
    """
    Varsayılan QMessageBox'ın yerini alan; kenarları keskin, ikonun
    arkasında çirkin/koyu bir plaka barındıran sistem görünümü yerine
    kullanılan, temayla (açık/koyu) uyumlu, tamamen yuvarlak köşeli ve
    hafif gölgeli bir bildirim/onay kartı. İkon salt bir emoji/karakter
    olarak, ARKASINDA HİÇBİR ZEMİN OLMADAN çiziliyor.
    """

    def __init__(self, parent, title, message, buttons, icon_glyph="", theme="dark", accent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedWidth(360)
        self._result_role = None

        colors = _LIGHT_POPUP_COLORS if theme == "light" else _DARK_POPUP_COLORS
        accent = accent or gem_theme.default_accent_for_theme(theme)
        accent_hover = gem_theme.lighten(accent)
        accent_text = gem_theme.readable_text_color(accent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QWidget(self)
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setObjectName("modernPopupCard")
        outer.addWidget(card)
        card.setStyleSheet(f"""
            QWidget#modernPopupCard {{
                background-color: {colors['bg']};
                border: 1px solid {colors['border']};
                border-radius: 18px;
            }}
            QLabel {{
                background: transparent;
                color: {colors['text']};
                font-family: {_POPUP_FONT};
                font-size: 13px;
            }}
            QLabel#popupTitle {{ font-size: 15px; font-weight: 600; }}
            QLabel#popupIcon {{ font-size: 28px; background: transparent; border: none; }}
            QPushButton {{
                background-color: transparent;
                color: {colors['muted']};
                border: 1px solid {colors['border']};
                font-family: {_POPUP_FONT};
                font-size: 13px;
                font-weight: 500;
                padding: 8px 18px;
                border-radius: 18px;
            }}
            QPushButton:hover {{ background-color: {colors['hover']}; color: {colors['text']}; }}
            QPushButton#primaryBtn {{ background-color: {accent}; color: {accent_text}; border: 1px solid {accent}; }}
            QPushButton#primaryBtn:hover {{ background-color: {accent_hover}; border: 1px solid {accent_hover}; }}
            QPushButton#dangerBtn {{ background-color: #e74c3c; color: #ffffff; border: 1px solid #e74c3c; }}
            QPushButton#dangerBtn:hover {{ background-color: #f1604f; border: 1px solid #f1604f; }}
        """)

        content = QVBoxLayout(card)
        content.setContentsMargins(20, 18, 20, 16)
        content.setSpacing(14)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        if icon_glyph:
            icon_lbl = QLabel(icon_glyph)
            icon_lbl.setObjectName("popupIcon")
            icon_lbl.setFixedWidth(32)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            top_row.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
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
        # sınırlama) — bu yüzden dialog, metin gerçekten sarmadan ÖNCEKİ
        # (yanlış/eksik) yüksekliğe göre boyutlanıp metnin alt satırları
        # butonla üst üste biniyordu. Çözüm: gereken yüksekliği kendimiz
        # QFontMetrics ile hesaplayıp etikete doğrudan uyguluyoruz —
        # layout'un otomatik hesaplamasına güvenmiyoruz.
        icon_col_width = 32 + 12 if icon_glyph else 0  # icon_lbl genişliği + top_row spacing
        content_margins = 20 + 20  # content.setContentsMargins(20, 18, 20, 16)
        wrap_width = 360 - content_margins - icon_col_width
        metrics = QFontMetrics(msg_lbl.font())
        text_rect = metrics.boundingRect(
            QRect(0, 0, wrap_width, 10000),
            Qt.TextFlag.TextWordWrap,
            message,
        )
        msg_lbl.setMinimumHeight(text_rect.height() + 4)  # küçük bir pay
        text_col.addWidget(msg_lbl)
        top_row.addLayout(text_col, 1)
        content.addLayout(top_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        for text, role in buttons:
            btn = QPushButton(text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if role == "primary":
                btn.setObjectName("primaryBtn")
            elif role == "danger":
                btn.setObjectName("dangerBtn")
            btn.clicked.connect(lambda checked=False, r=role: self._on_button(r))
            btn_row.addWidget(btn)
        content.addLayout(btn_row)

        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(32)
        shadow.setXOffset(0)
        shadow.setYOffset(8)
        shadow.setColor(QColor(0, 0, 0, 150))
        card.setGraphicsEffect(shadow)

        # Etiketin gerçek yüksekliği yukarıda elle set edildi; dialog'un
        # da buna göre yeniden boyutlanması için son bir adjustSize.
        self.adjustSize()

    def _on_button(self, role):
        self._result_role = role
        self.accept()

    def result_role(self):
        return self._result_role


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


def show_modern_info(parent, message: str, title: str = "", lang: str = "tr", warning: bool = False):
    """Tek butonlu (Tamam) modern bilgi/uyarı kartı — QMessageBox.information/warning yerine."""
    icon = "⚠️" if warning else "ℹ️"
    ok_text = "Tamam" if lang == "tr" else "OK"
    dlg = ModernPopup(
        parent, title, message,
        buttons=[(ok_text, "primary")],
        icon_glyph=icon, theme=_popup_theme(parent), accent=_popup_accent(parent),
    )
    dlg.exec()


def show_modern_confirm(parent, message: str, title: str = "", lang: str = "tr", danger: bool = False) -> bool:
    """Evet/Hayır modern onay kartı — QMessageBox.question yerine. True = onaylandı."""
    yes_text = "Evet" if lang == "tr" else "Yes"
    no_text = "Hayır" if lang == "tr" else "No"
    dlg = ModernPopup(
        parent, title, message,
        buttons=[(no_text, "secondary"), (yes_text, "danger" if danger else "primary")],
        icon_glyph="❔", theme=_popup_theme(parent), accent=_popup_accent(parent),
    )
    dlg.exec()
    return dlg.result_role() in ("primary", "danger")
