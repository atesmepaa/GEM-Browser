"""
Sekme çubuğu ve yardımcı sekme arayüzü parçaları: özel sekme çubuğu
(ilerleme çubuğu, sabitleme, hover önizleme, açılış/kapanış animasyonu),
dikey kenar çubuğu, hover önizleme kartı, + düğmesi, sekme arama ve
favori diyaloğu. (window.py'den ayrıldı — bkz. 2026-09 modülerleşmesi.)
"""

from PyQt6.QtCore import Qt, QTimer, QSize, QPoint, QEvent, pyqtSignal, QVariantAnimation, QEasingCurve
from PyQt6.QtWidgets import (
    QWidget, QTabBar, QVBoxLayout, QHBoxLayout, QLabel,
    QToolButton, QScrollArea, QMenu, QDialog, QLineEdit, QPushButton,
    QApplication, QFrame, QListWidget, QListWidgetItem, QProxyStyle
)
from PyQt6.QtGui import QPainter, QColor, QPixmap

from gem_browser.browser_tab import BrowserTab


class _LeftAlignedTabStyle(QProxyStyle):
    def drawItemText(self, painter, rect, flags, pal, enabled, text, textRole=None):
        flags &= ~int(Qt.AlignmentFlag.AlignHCenter)
        flags &= ~int(Qt.AlignmentFlag.AlignRight)
        flags |= int(Qt.AlignmentFlag.AlignLeft)
        if textRole is None: super().drawItemText(painter, rect, flags, pal, enabled, text)
        else: super().drawItemText(painter, rect, flags, pal, enabled, text, textRole)


class _PlusToolButton(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._plus_color = QColor("#3daee9")

    def setPlusColor(self, color: str):
        self._plus_color = QColor(color)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = painter.pen()
        pen.setColor(self._plus_color)
        pen.setWidthF(2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        half = 5.0
        painter.drawLine(int(cx - half), int(cy), int(cx + half), int(cy))
        painter.drawLine(int(cx), int(cy - half), int(cx), int(cy + half))
        painter.end()

_PREVIEW_THUMB_W = 220
_PREVIEW_THUMB_H = 124


class _TabPreviewPopup(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._card = QWidget(self)
        self._card.setObjectName("gemTabPreviewCard")
        self._card.setStyleSheet(
            "#gemTabPreviewCard { background-color: #242424; border: 1px solid #3a3a3a; border-radius: 8px; }"
        )
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(8, 8, 8, 10)
        card_layout.setSpacing(6)

        self._thumb_label = QLabel(self._card)
        self._thumb_label.setFixedSize(_PREVIEW_THUMB_W, _PREVIEW_THUMB_H)
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setWordWrap(True)
        self._thumb_label.setStyleSheet(
            "background-color: #1a1a1a; border: 1px solid #333333; border-radius: 6px; color: #777777; font-size: 11px;"
        )

        self._title_label = QLabel(self._card)
        self._title_label.setStyleSheet("color: #eeeeee; font-size: 13px; font-weight: 500; background: transparent;")

        self._status_label = QLabel(self._card)
        self._status_label.setStyleSheet("color: #a0a0a0; font-size: 11px; font-style: italic; background: transparent;")
        self._status_label.hide()

        # YENİ: Başlık ve durum yazısını yan yana dizmek için yatay layout
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(6)
        title_layout.addWidget(self._title_label)
        title_layout.addWidget(self._status_label)
        title_layout.addStretch() # Sola yasla

        card_layout.addWidget(self._thumb_label)
        card_layout.addLayout(title_layout) # Alt alta yerine yan yana layout'u ekle
        outer.addWidget(self._card)

    def show_for(self, tab, title: str, anchor_global_pos: QPoint, is_sidebar: bool = False):
        lang = getattr(tab, "lang", "tr") if tab is not None else "tr"
        is_suspended = bool(getattr(tab, "is_suspended", False))
        thumbnail = tab.get_thumbnail() if tab is not None and hasattr(tab, "get_thumbnail") else None

        # Önizleme Görselini Ayarlama (Kırpma düzeltmesi dahil)
        if thumbnail is not None and not thumbnail.isNull():
            scaled = thumbnail.scaled(
                _PREVIEW_THUMB_W, _PREVIEW_THUMB_H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            x = max(0, (scaled.width() - _PREVIEW_THUMB_W) // 2)
            y = 0
            self._thumb_label.setPixmap(scaled.copy(x, y, _PREVIEW_THUMB_W, _PREVIEW_THUMB_H))
        else:
            self._thumb_label.setPixmap(QPixmap())
            if is_suspended:
                self._thumb_label.setText("💤 " + ("Uykuda" if lang == "tr" else "Sleeping"))
            elif tab is not None and hasattr(tab, "is_page_loading") and tab.is_page_loading():
                self._thumb_label.setText("Yükleniyor..." if lang == "tr" else "Loading...")
            else:
                self._thumb_label.setText("Önizleme yok" if lang == "tr" else "No preview yet")

        # Durum Yazısını Güncelleme ve Başlık Genişliğini Ayarlama
        if is_suspended and thumbnail is not None and not thumbnail.isNull():
            self._status_label.setText("💤 " + ("Uykuda" if lang == "tr" else "Sleeping"))
            self._status_label.show()
            available_w = _PREVIEW_THUMB_W - 65 # Uykuda yazısı için boşluk bırak
        else:
            self._status_label.hide()
            available_w = _PREVIEW_THUMB_W - 4

        fm = self._title_label.fontMetrics()
        self._title_label.setText(fm.elidedText(title or "", Qt.TextElideMode.ElideRight, available_w))

        self.adjustSize()

        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else self.screen().availableGeometry()

        if is_sidebar:
            x = anchor_global_pos.x() + 8
            y = anchor_global_pos.y() - self.height() // 2
        else:
            x = anchor_global_pos.x() - self.width() // 2
            y = anchor_global_pos.y()

        x = max(geo.left() + 4, min(x, geo.right() - self.width() - 4))
        if y + self.height() > geo.bottom():
            y = anchor_global_pos.y() - self.height() - 40

        self.move(max(0, x), max(0, y))
        self.show()


class ProgressTabBar(QTabBar):
    _ANIM_IN_MS = 170
    _ANIM_OUT_MS = 130
    _MIN_TAB_WIDTH = 84
    _MAX_TAB_WIDTH = 200
    _PINNED_TAB_WIDTH = 40
    _BTN_RESERVED = 34
    pin_toggle_requested = pyqtSignal(object)

    def __init__(self, tab_widget, parent=None):
        super().__init__(parent)
        self.tab_widget_ref = tab_widget
        self.progress_map = {}
        self.accent_color = "#3daee9"
        self._anim_scale = {}
        self._anims = {}
        self.tabMoved.connect(lambda *_: self._update_btn_pos())

        self.setMouseTracking(True)
        self._hover_index = -1
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(450)
        self._hover_timer.timeout.connect(self._show_hover_preview)

    def set_accent_color(self, color: str):
        self.accent_color = color or "#3daee9"
        self.update()

    def set_progress(self, widget, value):
        if value is None: self.progress_map.pop(widget, None)
        else: self.progress_map[widget] = value
        self.update()

    def tabSizeHint(self, index):
        size = super().tabSizeHint(index)
        widget = self.tab_widget_ref.widget(index)
        scale = self._anim_scale.get(widget, 1.0)
        pinned = bool(widget.property("pinned")) if widget is not None else False

        count = self.count()
        if pinned:
            width = self._PINNED_TAB_WIDTH
        elif count > 0 and self.width() > 0:
            pinned_count = sum(1 for i in range(count) if bool(self.tab_widget_ref.widget(i).property("pinned")))
            normal_count = max(1, count - pinned_count)
            reserved = self._BTN_RESERVED + pinned_count * self._PINNED_TAB_WIDTH
            available = max(0, self.width() - reserved)
            ideal = available // normal_count
            width = max(self._MIN_TAB_WIDTH, min(self._MAX_TAB_WIDTH, ideal))
        else:
            width = size.width()

        if scale < 1.0:
            width = max(1, int(width * scale))
        return QSize(width, size.height())

    def _relayout(self):
        app = QApplication.instance()
        if app is not None: app.sendEvent(self, QEvent(QEvent.Type.StyleChange))
        else: self.update()
        self._update_btn_pos()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_btn_pos()

    def tabLayoutChange(self):
        super().tabLayoutChange()
        self._update_btn_pos()

    def _update_btn_pos(self):
        if not (hasattr(self, 'new_tab_btn') and self.new_tab_btn): return
        btn_w, btn_h = self.new_tab_btn.width(), self.new_tab_btn.height()
        if self.count() > 0:
            rect = self.tabRect(self.count() - 1)
            y = rect.top() + (rect.height() - btn_h) // 2
            x = rect.right() + 6
        else:
            x, y = 6, (self.height() - btn_h) // 2
        max_x = max(0, self.width() - btn_w - 6)
        self.new_tab_btn.move(min(x, max_x), max(0, y))
        self.new_tab_btn.raise_()

    def animate_tab_in(self, widget):
        old = self._anims.pop(widget, None)
        if old is not None: old.stop()
        self._anim_scale[widget] = 0.0
        self._relayout()

        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(self._ANIM_IN_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _step(value, w=widget):
            self._anim_scale[w] = value
            self._relayout()
        def _done(w=widget):
            self._anim_scale.pop(w, None)
            self._anims.pop(w, None)
            self._relayout()

        anim.valueChanged.connect(_step)
        anim.finished.connect(_done)
        self._anims[widget] = anim
        anim.start()

    def animate_tab_out(self, widget, on_finished):
        old = self._anims.pop(widget, None)
        if old is not None: old.stop()

        anim = QVariantAnimation(self)
        anim.setStartValue(self._anim_scale.get(widget, 1.0))
        anim.setEndValue(0.0)
        anim.setDuration(self._ANIM_OUT_MS)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)

        def _step(value, w=widget):
            self._anim_scale[w] = value
            self._relayout()
        def _done(w=widget):
            self._anim_scale.pop(w, None)
            self._anims.pop(w, None)
            on_finished()

        anim.valueChanged.connect(_step)
        anim.finished.connect(_done)
        self._anims[widget] = anim
        anim.start()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.tabAt(pos)
        if index != self._hover_index:
            self._hover_index = index
            self._hide_hover_preview()
            if index != -1: self._hover_timer.start()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._hover_index = -1
        self._hover_timer.stop()
        self._hide_hover_preview()

    def mousePressEvent(self, event):
        self._hover_timer.stop()
        self._hide_hover_preview()
        super().mousePressEvent(event)

    def _show_hover_preview(self):
        if self._hover_index == -1 or self._hover_index >= self.count(): return

        # YENİ EKLENEN SATIR: Eğer üzerine gelinen sekme zaten açık olan (aktif) sekme ise hiçbir şey yapma
        if self._hover_index == self.currentIndex(): return

        widget = self.tab_widget_ref.widget(self._hover_index)
        main_win = self.tab_widget_ref.window()
        if widget is None or not hasattr(main_win, "show_hover_preview"): return

        title = getattr(widget, "_gem_full_title", None) or self.tabToolTip(self._hover_index) or self.tabText(self._hover_index)
        rect = self.tabRect(self._hover_index)
        anchor = self.mapToGlobal(QPoint(rect.center().x(), rect.bottom() + 8))
        main_win.show_hover_preview(widget, title, anchor, is_sidebar=False)

    def _hide_hover_preview(self):
        main_win = self.tab_widget_ref.window()
        if hasattr(main_win, "hide_hover_preview"):
            main_win.hide_hover_preview()

    def contextMenuEvent(self, event):
        index = self.tabAt(event.pos())
        if index == -1: return
        widget = self.tab_widget_ref.widget(index)
        main_win = self.tab_widget_ref.window()
        lang = getattr(main_win, "lang", "tr")
        pinned = bool(widget.property("pinned")) if widget is not None else False

        menu = QMenu(self)
        pin_action = menu.addAction(("Sabitlemeyi Kaldır" if pinned else "Sekmeyi Sabitle") if lang == "tr" else ("Unpin Tab" if pinned else "Pin Tab"))
        muted = bool(getattr(widget, "_muted", False))
        mute_action = menu.addAction(("Sesi Aç" if muted else "Sesi Kapat") if lang == "tr" else ("Unmute Tab" if muted else "Mute Tab"))
        dup_action = menu.addAction("Sekmeyi Çoğalt" if lang == "tr" else "Duplicate Tab")
        menu.addSeparator()
        close_action = menu.addAction("Sekmeyi Kapat" if lang == "tr" else "Close Tab")

        chosen = menu.exec(event.globalPos())
        if chosen == pin_action: self.pin_toggle_requested.emit(widget)
        elif chosen == mute_action and hasattr(main_win, "_toggle_tab_mute"): main_win._toggle_tab_mute(widget)
        elif chosen == dup_action and hasattr(main_win, "_duplicate_tab"): main_win._duplicate_tab(widget)
        elif chosen == close_action and hasattr(main_win, "close_tab"): main_win.close_tab(index)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.progress_map: return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar_color = QColor(self.accent_color)
        bar_height = 3

        for index in range(self.count()):
            widget = self.tab_widget_ref.widget(index)
            pct = self.progress_map.get(widget)
            if pct is not None:
                rect = self.tabRect(index)
                bar_y = rect.bottom() - bar_height
                bar_width = max(2, int(rect.width() * (pct / 100.0)))
                painter.fillRect(rect.x(), bar_y, bar_width, bar_height, bar_color)
        painter.end()


class _CollapsibleSidebar(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._expanded_width = 230
        self._collapsed_width = 10
        self._pinned = False  # sabitlenince hover'a bağlı açılma/kapanma durur
        self.setFixedWidth(self._collapsed_width)
        self.setMouseTracking(True)

        self.anim = QVariantAnimation(self)
        self.anim.setDuration(120)
        self.anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.anim.valueChanged.connect(self.setFixedWidth)

    def set_pinned(self, pinned: bool):
        """Sidebarı sabitler (açık kalır) veya hover moduna döndürür."""
        self._pinned = bool(pinned)
        self.anim.stop()
        target = self._expanded_width if self._pinned else (
            self._expanded_width if self.underMouse() else self._collapsed_width)
        self.anim.setStartValue(self.width())
        self.anim.setEndValue(target)
        self.anim.start()

    def enterEvent(self, event):
        if not self._pinned:
            self.anim.stop()
            self.anim.setStartValue(self.width())
            self.anim.setEndValue(self._expanded_width)
            self.anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._pinned:
            self.anim.stop()
            self.anim.setStartValue(self.width())
            self.anim.setEndValue(self._collapsed_width)
            self.anim.start()
        super().leaveEvent(event)


class _SidebarTabRow(QWidget):
    activated = pyqtSignal()
    close_requested = pyqtSignal()
    pin_toggle_requested = pyqtSignal()

    def __init__(self, tab, title: str, icon, pinned: bool, selected: bool, is_light: bool,
                 lang: str = "tr", accent: str = "#3daee9", parent=None):
        super().__init__(parent)
        self._tab = tab
        self._title = title
        self._pinned = pinned
        self._lang = lang
        self._accent = accent or "#3daee9"
        self._progress = None  # yükleme çizgisi: 0..100 veya None
        self._is_light = is_light
        self._title_label = None
        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 6, 4)
        layout.setSpacing(8)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(16, 16)
        if icon is not None and not icon.isNull():
            self.icon_label.setPixmap(icon.pixmap(16, 16))
        layout.addWidget(self.icon_label)

        if not pinned:
            title_label = QLabel(self)
            text_col = ("#000000" if is_light else "#ffffff") if selected else ("#666666" if is_light else "#a0a0a0")
            title_label.setStyleSheet(
                f"color: {text_col}; font-size: 13px; "
                f"font-weight: {'600' if selected else '500'}; background: transparent;"
            )
            fm = title_label.fontMetrics()
            title_label.setText(fm.elidedText(title or "", Qt.TextElideMode.ElideRight, 125))
            layout.addWidget(title_label, 1)
            self._title_label = title_label

            close_btn = QToolButton(self)
            close_btn.setText("×")
            close_btn.setFixedSize(20, 20)
            close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            close_btn.setStyleSheet(
                "QToolButton { background: transparent; border: none; border-radius: 6px; "
                "color: #888888; font-size: 14px; } "
                "QToolButton:hover { background-color: rgba(255, 85, 85, 0.18); color: #ff5555; }"
            )
            close_btn.clicked.connect(self.close_requested.emit)
            layout.addWidget(close_btn)
        else:
            layout.addStretch(1)

        bg = ("#e6e6e6" if is_light else "#3b3b3b") if selected else "transparent"
        self.setObjectName("gemSidebarRow")
        self.setStyleSheet(f"#gemSidebarRow {{ background-color: {bg}; border-radius: 8px; }}")

    def set_progress(self, value):
        """Yükleme çizgisi durumu (0..100); None = yükleme yok. Yatay
        sekme çubuğundaki göstergenin birebir karşılığıdır."""
        if self._progress != value:
            self._progress = value
            self.update()

    def set_title(self, title: str):
        """Başlığı tüm sidebar'ı yeniden kurmadan yerinde günceller."""
        self._title = title
        if self._title_label is not None:
            fm = self._title_label.fontMetrics()
            self._title_label.setText(fm.elidedText(title or "", Qt.TextElideMode.ElideRight, 125))

    def set_selected(self, selected: bool):
        """Seçim vurgusunu yerinde günceller (arka plan + başlık rengi)."""
        bg = ("#e6e6e6" if self._is_light else "#3b3b3b") if selected else "transparent"
        self.setStyleSheet(f"#gemSidebarRow {{ background-color: {bg}; border-radius: 8px; }}")
        if self._title_label is not None:
            text_col = ("#000000" if self._is_light else "#ffffff") if selected else ("#666666" if self._is_light else "#a0a0a0")
            self._title_label.setStyleSheet(
                f"color: {text_col}; font-size: 13px; "
                f"font-weight: {'600' if selected else '500'}; background: transparent;"
            )

    def set_icon(self, icon):
        """Ses durumu değiştiğinde satır ikonunu yeniden çizmeden güncelle."""
        if icon is not None and not icon.isNull():
            self.icon_label.setPixmap(icon.pixmap(16, 16))

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._progress is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        bar_height = 3
        bar_width = max(2, int(rect.width() * (self._progress / 100.0)))
        painter.fillRect(rect.x(), rect.bottom() - bar_height + 1,
                         bar_width, bar_height, QColor(self._accent))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: self.activated.emit()
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        pin_action = menu.addAction(("Sabitlemeyi Kaldır" if self._pinned else "Sekmeyi Sabitle") if self._lang == "tr" else ("Unpin Tab" if self._pinned else "Pin Tab"))
        # Sesi Kapat/Aç: sekmenin GÜNCEL durumuna göre dinamik etiket
        muted = bool(getattr(self._tab, "_muted", False))
        mute_action = menu.addAction(("Sesi Aç" if muted else "Sesi Kapat") if self._lang == "tr" else ("Unmute Tab" if muted else "Mute Tab"))
        dup_action = menu.addAction("Sekmeyi Çoğalt" if self._lang == "tr" else "Duplicate Tab")
        menu.addSeparator()
        close_action = menu.addAction("Sekmeyi Kapat" if self._lang == "tr" else "Close Tab")
        chosen = menu.exec(event.globalPos())
        main_win = self.window()
        if chosen == pin_action: self.pin_toggle_requested.emit()
        elif chosen == mute_action and hasattr(main_win, "_toggle_tab_mute"):
            main_win._toggle_tab_mute(self._tab)
        elif chosen == dup_action and hasattr(main_win, "_duplicate_tab"):
            main_win._duplicate_tab(self._tab)
        elif chosen == close_action: self.close_requested.emit()

    def enterEvent(self, event):
        main_win = self.window()

        if hasattr(main_win, "current_tab") and main_win.current_tab() == self._tab:
            super().enterEvent(event)
            return

        if hasattr(main_win, "show_hover_preview"):
            rect = self.rect()
            pos = self.mapToGlobal(QPoint(rect.right() + 4, rect.center().y()))
            main_win.show_hover_preview(self._tab, self._title, pos, is_sidebar=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        main_win = self.window()
        if hasattr(main_win, "hide_hover_preview"):
            main_win.hide_hover_preview()
        super().leaveEvent(event)


class BookmarkDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        lang = parent.lang if parent else "tr"
        self.setWindowTitle("Favori Ekle" if lang == "tr" else "Add Bookmark")
        self.resize(320, 160)
        layout = QVBoxLayout(self)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Site Adı" if lang == "tr" else "Site Name")
        layout.addWidget(self.name_input)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("URL (örn: https://...)" if lang == "tr" else "URL (e.g. https://...)")
        layout.addWidget(self.url_input)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Ekle" if lang == "tr" else "Add")
        add_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("İptal" if lang == "tr" else "Cancel")
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def get_data(self):
        return self.name_input.text().strip(), self.url_input.text().strip()


class TabSearchDialog(QDialog):
    """Ctrl+Shift+A: açık sekmeler arasında başlık/URL araması."""

    def __init__(self, mainwin):
        super().__init__(mainwin)
        self.mainwin = mainwin
        lang = getattr(mainwin, "lang", "tr")
        self.lang = lang
        self.setWindowTitle("Sekme Ara" if lang == "tr" else "Search Tabs")
        self.resize(560, 420)
        layout = QVBoxLayout(self)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Sekme başlığı veya URL ara..." if lang == "tr" else "Search tab title or URL...")
        self.search_input.textChanged.connect(self._filter)
        self.search_input.returnPressed.connect(self._activate_current)
        layout.addWidget(self.search_input)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._activate)
        self.list_widget.itemActivated.connect(self._activate)
        layout.addWidget(self.list_widget)

        hint = QLabel("Enter: geç / çift tık: geç" if lang == "tr" else "Enter: switch / double-click: switch")
        hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(hint)

        self._populate()
        self.search_input.setFocus()

    def _populate(self):
        self.list_widget.clear()
        mw = self.mainwin
        for i in range(mw.tab_widget.count()):
            tab = mw.tab_widget.widget(i)
            if not isinstance(tab, BrowserTab):
                continue
            title = getattr(tab, "_gem_full_title", None) or mw.tab_widget.tabText(i)
            if tab.is_suspended:
                url = tab.saved_url.toString()
            elif tab.view is not None:
                url = tab.view.url().toString()
            else:
                url = ""
            prefix = "🌙 " if tab.is_suspended else ""
            item = QListWidgetItem(f"{prefix}{title}  —  {url}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.list_widget.addItem(item)
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)

    def _filter(self, text):
        text = text.strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())

    def _activate_current(self):
        item = self.list_widget.currentItem()
        if item is not None and not item.isHidden():
            self._activate(item)

    def _activate(self, item):
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is not None and index < self.mainwin.tab_widget.count():
            self.mainwin.tab_widget.setCurrentIndex(index)
        self.accept()
