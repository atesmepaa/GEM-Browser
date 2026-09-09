import os
import json
import shutil
import subprocess
from PyQt6.QtNetwork import QNetworkProxy
from urllib.parse import parse_qs, urlparse, quote_plus
from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QTabBar, QVBoxLayout, QWidget,
    QLineEdit, QToolBar, QToolButton, QMenu, QDialog,
    QListWidget, QListWidgetItem, QLabel, QCheckBox, QPushButton, QHBoxLayout, QComboBox,
    QStyle, QProxyStyle, QColorDialog, QFileDialog, QApplication,
    QScrollArea, QFrame
)
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineScript, QWebEngineSettings, QWebEnginePage
from PyQt6.QtCore import QUrl, Qt, QTimer, QThread, pyqtSignal, QSize, QPoint, QVariantAnimation, QEasingCurve, QEvent
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QPainter, QColor, QPixmap

from gem_browser import icons as gem_icons
from gem_browser.tor_vpn import TorVpnManager
from gem_browser.url_suggestions import gather_local_suggestions, RemoteSuggester, SuggestionPopup
from gem_browser.browser_tab import BrowserTab
from gem_browser.router import resolve_url
from gem_browser.new_tab import get_new_tab_url, load_bookmarks, save_bookmarks
from gem_browser.adblock import AdblockInterceptor
from gem_browser import filter_lists
from gem_browser.password_manager import (
    PasswordVault, PasswordManagerDialog, MasterPasswordDialog,
    WrongMasterPassword, vault_exists
)
from gem_browser.settings import BrowserSettings
from gem_browser.downloads import DownloadManager
from gem_browser.downloads_dialog import DownloadsDialog
from gem_browser import paths as gem_paths
from gem_browser.modern_popup import show_modern_info, show_modern_confirm
from gem_browser import history as gem_history
from gem_browser import default_browser as gem_default_browser
from gem_browser import theme as gem_theme
from gem_browser import session as gem_session

_active_windows = []
_startup_session_checked = False
_normal_profile = None

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
        menu.addSeparator()
        close_action = menu.addAction("Sekmeyi Kapat" if lang == "tr" else "Close Tab")

        chosen = menu.exec(event.globalPos())
        if chosen == pin_action: self.pin_toggle_requested.emit(widget)
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
        self.setFixedWidth(self._collapsed_width)
        self.setMouseTracking(True)
        
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(120)
        self.anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.anim.valueChanged.connect(self.setFixedWidth)

    def enterEvent(self, event):
        self.anim.stop()
        self.anim.setStartValue(self.width())
        self.anim.setEndValue(self._expanded_width)
        self.anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.anim.stop()
        self.anim.setStartValue(self.width())
        self.anim.setEndValue(self._collapsed_width)
        self.anim.start()
        super().leaveEvent(event)

class _SidebarTabRow(QWidget):
    activated = pyqtSignal()
    close_requested = pyqtSignal()
    pin_toggle_requested = pyqtSignal()

    def __init__(self, tab, title: str, icon, pinned: bool, selected: bool, is_light: bool, lang: str = "tr", parent=None):
        super().__init__(parent)
        self._tab = tab
        self._title = title
        self._pinned = pinned
        self._lang = lang
        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 6, 4)
        layout.setSpacing(8)

        icon_label = QLabel(self)
        icon_label.setFixedSize(16, 16)
        if icon is not None and not icon.isNull():
            icon_label.setPixmap(icon.pixmap(16, 16))
        layout.addWidget(icon_label)

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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: self.activated.emit()
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        pin_action = menu.addAction(("Sabitlemeyi Kaldır" if self._pinned else "Sekmeyi Sabitle") if self._lang == "tr" else ("Unpin Tab" if self._pinned else "Pin Tab"))
        menu.addSeparator()
        close_action = menu.addAction("Sekmeyi Kapat" if self._lang == "tr" else "Close Tab")
        chosen = menu.exec(event.globalPos())
        if chosen == pin_action: self.pin_toggle_requested.emit()
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

class HistoryDialog(QDialog):
    def __init__(self, history_entries, lang="tr", parent=None):
        super().__init__(parent)
        self.lang = lang
        self.parent_window = parent
        self.setWindowTitle("Geçmiş" if lang == "tr" else "History")
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Ziyaret edilen siteler (çift tıkla: aç):" if lang == "tr" else "Visited sites (double-click to open):"))
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._open_selected)
        self._populate(history_entries)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Geçmişi Temizle" if lang == "tr" else "Clear History")
        clear_btn.clicked.connect(self._clear_history)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        close_btn = QPushButton("Kapat" if lang == "tr" else "Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _populate(self, history_entries):
        self.list_widget.clear()
        if not history_entries:
            self.list_widget.addItem("Henüz gezinme geçmişi yok." if self.lang == "tr" else "No browsing history yet.")
            return
        for entry in reversed(history_entries):
            url, title = entry.get("url", ""), entry.get("title") or entry.get("url", "")
            display = url if title == url else f"{title}  —  {url}"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, url)
            self.list_widget.addItem(item)

    def _open_selected(self, item):
        url = item.data(Qt.ItemDataRole.UserRole)
        if url and self.parent_window is not None:
            self.parent_window.add_new_tab(QUrl(url))
        self.accept()

    def _clear_history(self):
        msg = "Tüm gezinme geçmişi kalıcı olarak silinsin mi?" if self.lang == "tr" else "Permanently delete all browsing history?"
        title = "Geçmişi Temizle" if self.lang == "tr" else "Clear History"
        if show_modern_confirm(self, msg, title=title, lang=self.lang, danger=True):
            gem_history.clear_history()
            if self.parent_window is not None:
                self.parent_window.persistent_history = []
                self.parent_window.session_history = []
            self._populate([])

class SettingsDialog(QDialog):
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        lang = self.settings_manager.current["language"]

        self._pending_accent = self.settings_manager.current.get("accent_color", "")
        self._pending_bg_path = self.settings_manager.current.get("new_tab_background", "")

        self.setWindowTitle("Ayarlar" if lang == "tr" else "Settings")
        self.resize(480, 580)
        self.setMinimumSize(460, 320)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer_layout.addWidget(scroll_area, 1)

        scroll_content = QWidget()
        scroll_area.setWidget(scroll_content)
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(12, 12, 12, 12)
        
        lang_layout = QHBoxLayout()
        lang_layout.addWidget(QLabel("Dil:" if lang == "tr" else "Language:"))
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["Türkçe", "English"])
        self.combo_lang.setCurrentIndex(0 if lang == "tr" else 1)
        lang_layout.addWidget(self.combo_lang)
        layout.addLayout(lang_layout)

        theme_layout = QHBoxLayout()
        theme_layout.addWidget(QLabel("Tema:" if lang == "tr" else "Theme:"))
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["Koyu", "Açık"] if lang == "tr" else ["Dark", "Light"])
        self.combo_theme.setCurrentIndex(1 if self.settings_manager.current["ui_theme"] == "light" else 0)
        theme_layout.addWidget(self.combo_theme)
        layout.addLayout(theme_layout)

        accent_layout = QHBoxLayout()
        accent_layout.addWidget(QLabel("Vurgu Rengi:" if lang == "tr" else "Accent Color:"))
        self.accent_swatch_btn = QPushButton()
        self.accent_swatch_btn.setFixedSize(28, 28)
        self.accent_swatch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.accent_swatch_btn.clicked.connect(self._pick_accent_color)
        accent_layout.addWidget(self.accent_swatch_btn)
        
        accent_reset_btn = QPushButton("Varsayılana Döndür" if lang == "tr" else "Reset to Default")
        accent_reset_btn.clicked.connect(self._reset_accent_color)
        accent_layout.addWidget(accent_reset_btn)
        accent_layout.addStretch()
        layout.addLayout(accent_layout)
        self._refresh_accent_swatch()
        self.combo_theme.currentIndexChanged.connect(self._refresh_accent_swatch)

        bg_layout = QHBoxLayout()
        bg_layout.addWidget(QLabel("Yeni Sekme Arkaplanı:" if lang == "tr" else "New Tab Background:"))
        bg_pick_btn = QPushButton("Resim Seç..." if lang == "tr" else "Choose Image...")
        bg_pick_btn.clicked.connect(self._pick_new_tab_background)
        bg_layout.addWidget(bg_pick_btn)
        
        bg_reset_btn = QPushButton("Varsayılana Döndür" if lang == "tr" else "Reset to Default")
        bg_reset_btn.clicked.connect(self._reset_new_tab_background)
        bg_layout.addWidget(bg_reset_btn)
        bg_layout.addStretch()
        layout.addLayout(bg_layout)

        self.bg_status_label = QLabel()
        self.bg_status_label.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(self.bg_status_label)
        self._refresh_bg_status_label()

        self.chk_force_dark = QCheckBox("Koyu Temaya Zorla" if lang == "tr" else "Force Dark Mode")
        self.chk_force_dark.setChecked(self.settings_manager.current["force_dark_web"])
        layout.addWidget(self.chk_force_dark)

        self.chk_adblock = QCheckBox("Reklam Engelleyici" if lang == "tr" else "AdBlocker")
        self.chk_adblock.setChecked(self.settings_manager.current["adblock_enabled"])
        layout.addWidget(self.chk_adblock)

        self.chk_js = QCheckBox("JavaScript İzni" if lang == "tr" else "Enable JavaScript")
        self.chk_js.setChecked(self.settings_manager.current["js_enabled"])
        layout.addWidget(self.chk_js)
        
        self.chk_img = QCheckBox("Resimleri Yükle" if lang == "tr" else "Load Images")
        self.chk_img.setChecked(self.settings_manager.current["load_images"])
        layout.addWidget(self.chk_img)

        self.chk_suggestions = QCheckBox("Adres Çubuğunda Arama Önerileri" if lang == "tr" else "Search Suggestions in Address Bar")
        self.chk_suggestions.setChecked(self.settings_manager.current.get("search_suggestions", True))
        layout.addWidget(self.chk_suggestions)

        self.chk_auto_restore = QCheckBox("Sekmeleri Sormadan Otomatik Geri Yükle" if lang == "tr" else "Automatically Restore Tabs Without Asking")
        self.chk_auto_restore.setChecked(self.settings_manager.current.get("auto_restore_tabs", False))
        layout.addWidget(self.chk_auto_restore)
        auto_restore_hint = QLabel(
            "Açık iken, önceki oturumdan kalan sekmeler açılışta hiç sorulmadan otomatik geri yüklenir. Kapalıyken (varsayılan), her seferinde onay istenir."
            if lang == "tr" else
            "When on, tabs left open from the previous session are restored automatically on startup without asking. When off (default), you'll be asked each time."
        )
        auto_restore_hint.setWordWrap(True)
        auto_restore_hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(auto_restore_hint)

        self.chk_hw_accel = QCheckBox("Donanım Hızlandırmayı Kullan (GPU)" if lang == "tr" else "Use Hardware Acceleration (GPU)")
        self.chk_hw_accel.setChecked(self.settings_manager.current.get("hardware_acceleration", True))
        layout.addWidget(self.chk_hw_accel)
        hw_hint = QLabel("Kapatmak RAM kullanımını azaltabilir ama sayfa render'ını yavaşlatabilir. Yeniden başlatma gerektirir." if lang == "tr" else "Turning this off may reduce RAM usage but slow rendering. Requires restart.")
        hw_hint.setWordWrap(True)
        hw_hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(hw_hint)

        self.chk_low_ram = QCheckBox("Düşük RAM Modu (Agresif Tasarruf)" if lang == "tr" else "Low RAM Mode (Aggressive Savings)")
        self.chk_low_ram.setChecked(self.settings_manager.current.get("low_ram_mode", False))
        layout.addWidget(self.chk_low_ram)
        
        low_ram_hint = QLabel("RAM tüketimini 300MB'a çeker ancak çoklu sekme hızını düşürebilir. Yeniden başlatma gerektirir." if lang == "tr" else "Reduces RAM to ~300MB but may degrade multi-tab speed. Requires restart.")
        low_ram_hint.setWordWrap(True)
        low_ram_hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(low_ram_hint)
        
        # --- VPN AYARLARI ---
        # Açıksa ve host/port boşsa: otomatik olarak resmi Tor ağına bağlanır
        # (Brave/Opera'nın tek tıkla VPN deneyiminin ücretsiz eşdeğeri —
        # detay için gem_browser/tor_vpn.py). Host/port doldurulursa,
        # kullanıcının kendi SOCKS5 proxy'si (ör. ücretli bir VPN
        # sağlayıcısının SOCKS adresi) kullanılır.
        self.chk_vpn = QCheckBox("Yerleşik VPN (Tor — tek tıkla)" if lang == "tr" else "Built-in VPN (Tor — one click)")
        self.chk_vpn.setChecked(self.settings_manager.current.get("vpn_enabled", False))
        layout.addWidget(self.chk_vpn)

        vpn_hint = QLabel(
            "Alanları boş bırakırsanız otomatik olarak Tor ağı kullanılır "
            "(bilgisayarınızda 'tor' kurulu olmalı). Kendi SOCKS5 proxy "
            "adresinizi kullanmak isterseniz aşağıya girin."
            if lang == "tr" else
            "Leave the fields empty to automatically use the Tor network "
            "('tor' must be installed). Enter your own SOCKS5 proxy address "
            "below if you'd rather use that instead."
        )
        vpn_hint.setWordWrap(True)
        vpn_hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(vpn_hint)

        vpn_layout = QHBoxLayout()
        self.vpn_host_input = QLineEdit()
        self.vpn_host_input.setPlaceholderText("Gelişmiş: kendi SOCKS5 host'unuz (opsiyonel)" if lang == "tr" else "Advanced: your own SOCKS5 host (optional)")
        self.vpn_host_input.setText(self.settings_manager.current.get("vpn_host", ""))

        self.vpn_port_input = QLineEdit()
        self.vpn_port_input.setPlaceholderText("Port (örn: 9050)")
        self.vpn_port_input.setText(str(self.settings_manager.current.get("vpn_port", 9050)))

        vpn_layout.addWidget(self.vpn_host_input)
        vpn_layout.addWidget(self.vpn_port_input)
        layout.addLayout(vpn_layout)

        layout.addStretch()

        save_btn = QPushButton("Kaydet" if lang == "tr" else "Save")
        save_btn.setContentsMargins(0, 0, 0, 0)
        save_btn.clicked.connect(self._save_and_close)
        save_btn_wrapper = QWidget(self)
        save_btn_layout = QVBoxLayout(save_btn_wrapper)
        save_btn_layout.setContentsMargins(12, 10, 12, 12)
        save_btn_layout.addWidget(save_btn)
        outer_layout.addWidget(save_btn_wrapper, 0)

    def _current_lang(self) -> str:
        return self.settings_manager.current["language"]

    def _refresh_accent_swatch(self):
        preview = self._pending_accent or gem_theme.default_accent_for_theme("light" if self.combo_theme.currentIndex() == 1 else "dark")
        self.accent_swatch_btn.setStyleSheet(f"QPushButton {{ background-color: {preview}; border: 1px solid rgba(128,128,128,0.4); border-radius: 6px; }}")

    def _refresh_bg_status_label(self):
        lang = self._current_lang()
        if self._pending_bg_path and os.path.exists(self._pending_bg_path):
            self.bg_status_label.setText(f"Seçili görsel: {os.path.basename(self._pending_bg_path)}" if lang == "tr" else f"Selected image: {os.path.basename(self._pending_bg_path)}")
        else:
            self.bg_status_label.setText("Varsayılan gradyan kullanılıyor." if lang == "tr" else "Using default gradient.")

    def _pick_accent_color(self):
        current = QColor(self._pending_accent or gem_theme.default_accent_for_theme("light" if self.combo_theme.currentIndex() == 1 else "dark"))
        color = QColorDialog.getColor(current, self, "Vurgu Rengi Seç" if self._current_lang() == "tr" else "Choose Accent Color")
        if color.isValid():
            self._pending_accent = color.name()
            self._refresh_accent_swatch()

    def _reset_accent_color(self):
        self._pending_accent = ""
        self._refresh_accent_swatch()

    def _pick_new_tab_background(self):
        lang = self._current_lang()
        filter_str = "Görseller (*.png *.jpg *.jpeg *.webp *.bmp)" if lang == "tr" else "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        file_path, _ = QFileDialog.getOpenFileName(self, "Arkaplan Görseli Seç" if lang == "tr" else "Choose Background Image", os.path.expanduser("~"), filter_str)
        if file_path:
            try:
                ext = os.path.splitext(file_path)[1].lower() or ".png"
                dest_path = gem_paths.config_path(f"gem_new_tab_background{ext}")
                shutil.copyfile(file_path, dest_path)
                gem_paths.secure_chmod(dest_path, 0o600)
                self._pending_bg_path = dest_path
                self._refresh_bg_status_label()
            except Exception as exc:
                show_modern_info(self, f"Görsel kopyalanamadı: {exc}" if lang == "tr" else f"Could not copy image: {exc}", lang=lang, warning=True)

    def _reset_new_tab_background(self):
        self._pending_bg_path = ""
        self._refresh_bg_status_label()

    def _save_and_close(self):
        self.settings_manager.current["language"] = "tr" if self.combo_lang.currentIndex() == 0 else "en"
        self.settings_manager.current["ui_theme"] = "light" if self.combo_theme.currentIndex() == 1 else "dark"
        self.settings_manager.current["accent_color"] = self._pending_accent
        self.settings_manager.current["new_tab_background"] = self._pending_bg_path
        self.settings_manager.current["force_dark_web"] = self.chk_force_dark.isChecked()
        self.settings_manager.current["adblock_enabled"] = self.chk_adblock.isChecked()
        self.settings_manager.current["js_enabled"] = self.chk_js.isChecked()
        self.settings_manager.current["load_images"] = self.chk_img.isChecked()
        self.settings_manager.current["search_suggestions"] = self.chk_suggestions.isChecked()
        self.settings_manager.current["auto_restore_tabs"] = self.chk_auto_restore.isChecked()

        old_hw = self.settings_manager.current.get("hardware_acceleration", True)
        old_ram = self.settings_manager.current.get("low_ram_mode", False)
        
        self.settings_manager.current["hardware_acceleration"] = self.chk_hw_accel.isChecked()
        self.settings_manager.current["low_ram_mode"] = self.chk_low_ram.isChecked()
        self.settings_manager.current["vpn_enabled"] = self.chk_vpn.isChecked()
        self.settings_manager.current["vpn_host"] = self.vpn_host_input.text().strip()
        try:
            self.settings_manager.current["vpn_port"] = int(self.vpn_port_input.text().strip())
        except ValueError:
            self.settings_manager.current["vpn_port"] = 9050
        self.settings_manager.save()

        if old_hw != self.chk_hw_accel.isChecked() or old_ram != self.chk_low_ram.isChecked():
            lang = self._current_lang()
            msg = "Ayarın etkili olması için GEM Browser'ı kapatıp yeniden açmanız gerekiyor." if lang == "tr" else "You need to close and reopen GEM Browser to take effect."
            show_modern_info(self, msg, lang=lang)
        self.accept()

class MainWindow(QMainWindow):
    def __init__(self, profile=None):
        super().__init__()
        self.settings = BrowserSettings()
        self.lang = self.settings.current["language"]
        self._preview_popup = None
        
        if profile is None:
            self.shared_profile = _get_shared_normal_profile()
            self.is_incognito = False
            self.setWindowTitle("GEM Browser")
        else:
            self.shared_profile = profile
            self.is_incognito = True
            self.setWindowTitle("GEM Browser 🕵️ (Gizli)" if self.lang == "tr" else "GEM Browser 🕵️ (Incognito)")

        self.resize(1024, 768)
        self.setWindowIcon(self._app_icon())

        self.vault = None
        self.vault_lock_timer = QTimer(self)
        self.vault_lock_timer.setInterval(10 * 60 * 1000)
        self.vault_lock_timer.setSingleShot(True)
        self.vault_lock_timer.timeout.connect(self._lock_vault)

        self.download_manager = DownloadManager(self)
        self.shared_profile.downloadRequested.connect(self.download_manager.handle_download)
        
        self.persistent_history = [] if self.is_incognito else gem_history.load_history()
        self.session_history = [entry.get("url", "") for entry in self.persistent_history]
        self.closed_tabs_stack = []
        self.tab_timers = {}
        
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
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self._setup_toolbar()
        self._setup_tabs()
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
        Yerleşik VPN.

        Brave/Opera'nın "tek tıkla VPN" özelliği, kendi işlettikleri ya da
        anlaşmalı oldukları ÖZEL VE ÜCRETLİ sunucu altyapısına dayanır
        (Opera -> SurfEasy sunucuları, Brave VPN -> Guardian/WireGuard
        ortaklığı). Açık kaynaklı bir tarayıcının bunu ücretsiz sunması
        mümkün değil. Eski implementasyon bunun yerine internetten rastgele
        "ücretsiz public proxy" çekiyordu — bunların çoğu zaten çökmüş
        olduğundan "site açılmıyor / aşırı yavaş" şikayetine yol açıyordu.

        Bu yüzden iki gerçekçi ve dürüst seçenek sunuyoruz:
          1) Kullanıcı Ayarlar'da kendi SOCKS5 proxy'sinin (kendi VPN
             sağlayıcısı, kendi Tor kurulumu vb.) host/port'unu girerse
             doğrudan onu kullanırız.
          2) Host boş bırakılırsa, Brave/Opera'nın deneyimine en yakın
             ÜCRETSİZ ve gerçek eşdeğer olan resmi Tor ağına otomatik
             bağlanırız (bkz. gem_browser/tor_vpn.py). Bootstrap
             tamamlanınca (`connected` sinyali) proxy otomatik uygulanır.
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
            print(f"Yerleşik VPN (manuel SOCKS5): {host}:{port}")
        else:
            # 2) Otomatik mod: Tor ağı.
            self.tor_vpn.connect()

    def _on_vpn_status_changed(self, status: str, pct: int):
        if status == "connected" and self.tor_vpn.socks_port:
            proxy = QNetworkProxy()
            proxy.setType(QNetworkProxy.ProxyType.Socks5Proxy)
            proxy.setHostName("127.0.0.1")
            proxy.setPort(self.tor_vpn.socks_port)
            QNetworkProxy.setApplicationProxy(proxy)
            print(f"Yerleşik VPN (Tor) bağlandı: 127.0.0.1:{self.tor_vpn.socks_port}")
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
            if url_str and not (url_str.startswith("file://") and "gem_browser_new_tab" in url_str):
                urls.append(url_str)
        return urls

    def _restore_session_or_new_tab(self):
        global _startup_session_checked
        if self.is_incognito or _startup_session_checked:
            self.add_new_tab()
            return

        _startup_session_checked = True
        tab_urls = gem_session.load_session()
        gem_session.clear_session()

        if not tab_urls:
            self.add_new_tab()
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
                self.add_new_tab(QUrl(url_str), switch_to=(index == 0))
        else:
            self.add_new_tab()

    def _new_tab_url(self) -> str:
        return get_new_tab_url(
            self.settings.current["ui_theme"], self.lang,
            accent_color=gem_theme.get_accent_color(self.settings.current),
            background_image=self.settings.current.get("new_tab_background") or None,
        )

    def _refresh_new_tab_page(self, tab: BrowserTab) -> None:
        if tab.view is not None:
            tab.view.page().runJavaScript(f"window.location.replace({json.dumps(self._new_tab_url())});")
        
    def _update_desktop_icon(self, accent_color: str):
        user_icon_dir = os.path.expanduser("~/.local/share/icons/hicolor/256x256/apps")
        os.makedirs(user_icon_dir, exist_ok=True)
        target_path = os.path.join(user_icon_dir, "gem-browser.png")
        pixmap = gem_icons.tinted_logo_pixmap(accent_color, 256)
        if not pixmap.isNull():
            pixmap.save(target_path, "PNG")
            try:
                subprocess.run(["gtk-update-icon-cache", "-f", os.path.expanduser("~/.local/share/icons/hicolor")], stderr=subprocess.DEVNULL)
            except Exception: pass

    def _apply_settings_to_browser(self):
        self.lang = self.settings.current["language"]
        accent = gem_theme.get_accent_color(self.settings.current)
        base_style = LIGHT_STYLE if self.settings.current["ui_theme"] == "light" else DARK_STYLE
        self.setStyleSheet(base_style.replace("ACCENT_PLACEHOLDER", accent).replace("ACCENT_TEXT_PLACEHOLDER", gem_theme.readable_text_color(accent)))
        
        self.shared_profile.setUrlRequestInterceptor(self.adblock_interceptor if self.settings.current["adblock_enabled"] else None)

        web_settings = self.shared_profile.settings()
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, self.settings.current["js_enabled"])
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, self.settings.current["load_images"])
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

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
        self._suggestion_popup = None
        self._suggestion_popup_theme = None
        self._current_url_text = ""
        self._current_local_entries = []
        self._remote_suggester = RemoteSuggester(self)
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

        self._menu_action_icons = {
            self.action_new_tab: "plus", self.action_reopen_tab: "undo", self.action_new_win: "window",
            self.action_incognito: "incognito", self.action_downloads: "download", self.action_history: "history",
            self.action_pwd: "lock", self.action_update_blocklist: "shield", self.action_set_default_browser: "star",
            self.action_settings: "settings", self.action_zoom_in: "zoom-in", self.action_zoom_out: "zoom-out",
            self.action_zoom_reset: "zoom-reset",
        }

        self.main_menu.addActions([self.action_new_tab, self.action_reopen_tab, self.action_new_win, self.action_incognito])
        self.main_menu.addSeparator()
        self.main_menu.addActions([self.action_downloads, self.action_history, self.action_pwd, self.action_update_blocklist])
        self.main_menu.addSeparator()
        self.main_menu.addActions([self.action_zoom_in, self.action_zoom_out, self.action_zoom_reset])
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
        self._update_desktop_icon(accent)
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
                    if url_str.startswith("file://") and "gem_browser_new_tab" in url_str:
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
        entries.append({"kind": "search", "title": f'“{text}” için ara' if self.lang == "tr" else f'Search for “{text}”', "subtitle": "Brave Search", "value": text, "primary": True})
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
        if self._suggestion_popup is None or self._suggestion_popup_theme != theme:
            if self._suggestion_popup is not None:
                self._suggestion_popup.hide()
                self._suggestion_popup.deleteLater()
            self._suggestion_popup = SuggestionPopup(self, theme=theme)
            self._suggestion_popup.item_chosen.connect(self._on_suggestion_chosen)
            self._suggestion_popup_theme = theme
            
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

        if kind in ("bookmark", "history"):
            self._set_url_bar_text(value)
            tab.view.setUrl(QUrl(value))
        else:
            self._set_url_bar_text(value)
            tab.view.setUrl(QUrl(f"https://search.brave.com/search?q={quote_plus(value)}"))
        self.url_bar.clearFocus()

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
            new_win = MainWindow(profile=self.shared_profile) if self.is_incognito else MainWindow()
            _active_windows.append(new_win)
            new_win.show()
            return new_win.add_new_tab(QUrl("about:blank")).web_page
        else:
            return self.add_new_tab(QUrl("about:blank"), switch_to=(window_type != QWebEnginePage.WebWindowType.WebBrowserBackgroundTab)).web_page

    def _open_downloads_dialog(self): DownloadsDialog(self).exec()
    def _open_history(self): HistoryDialog(self.persistent_history, self.lang, self).exec()
    def _open_settings(self):
        if SettingsDialog(self.settings, self).exec(): self._apply_settings_to_browser()

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
        
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(12, 0, 0, 0)
        btn_layout.addWidget(self._sidebar_new_tab_btn)
        btn_layout.addStretch()
        
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

    def _toggle_vertical_tabs(self):
        self._vertical_mode = not self._vertical_mode
        self.settings.current["vertical_tabs"] = self._vertical_mode
        self.settings.save()
        self._apply_tab_layout_mode()

    def _rebuild_vertical_sidebar(self):
        if not getattr(self, "_vertical_mode", False):
            return
            
        # Sabit obje sayımız 3'e çıktığı için (Yeni Sekme, Boşluk, Alt İkonlar) 
        # burayı > 3 yapıyoruz ki aradaki boşluğu (Stretch) silmesin.
        while self._sidebar_layout.count() > 3:
            item = self._sidebar_layout.takeAt(1)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        current = self.current_tab()
        pinned_rows, normal_rows = [], []
        is_light = self.settings.current["ui_theme"] == "light"
        
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if not isinstance(tab, BrowserTab):
                continue
            pinned = bool(tab.property("pinned"))
            title = getattr(tab, "_gem_full_title", None) or self.tab_widget.tabText(i) or ("Yeni Sekme" if self.lang == "tr" else "New Tab")
            row = _SidebarTabRow(
                tab=tab, title=title, icon=self.tab_widget.tabIcon(i),
                pinned=pinned, selected=(tab is current), is_light=is_light, lang=self.lang,
            )
            row.activated.connect(lambda t=tab: self._activate_tab_from_sidebar(t))
            row.close_requested.connect(lambda t=tab: self.close_tab(self.tab_widget.indexOf(t)))
            row.pin_toggle_requested.connect(lambda t=tab: self._toggle_pin_tab(t))
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
        return False

    def _reset_vault_lock_timer(self):
        if self.vault is not None: self.vault_lock_timer.start()

    def _lock_vault(self):
        if self.vault is not None: self.vault = None

    def _open_password_manager(self):
        if self.is_incognito or not self._ensure_vault_unlocked(): return
        PasswordManagerDialog(self.vault, self).exec()
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
        
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval((2 if self.settings.current.get("low_ram_mode", False) else 4) * 60 * 1000)
        timer.timeout.connect(lambda t=tab: self._auto_suspend_tab(t))
        self.tab_timers[tab] = timer

        tab.title_changed.connect(lambda title, t=tab: self._update_tab_title(t, title))
        tab.url_changed.connect(lambda u, t=tab: self._update_tab_url(t, u))
        tab.gem_action_triggered.connect(lambda u, t=tab: self._handle_gem_action(t, u))
        tab.icon_changed.connect(lambda icon, t=tab: self._update_tab_icon(t, icon))
        tab.load_finished.connect(lambda ok, t=tab: self._attempt_autofill(t) if ok else None)
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

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Find):
            tab = self.current_tab()
            if tab and not tab.is_suspended: tab.show_find_bar()
        elif event.key() == Qt.Key.Key_F5 or event.matches(QKeySequence.StandardKey.Refresh):
            self._reload_page()
        else:
            super().keyPressEvent(event)

    def _auto_suspend_tab(self, tab):
        if tab.is_suspended or tab == self.current_tab(): return
        if tab.view is not None and tab.web_page is not None and tab.web_page.recentlyAudible():
            if tab in self.tab_timers: self.tab_timers[tab].start()
            return
        tab.suspend()
        index = self.tab_widget.indexOf(tab)
        if index != -1:
            self.tab_widget.setTabIcon(index, gem_icons.get_icon("moon", "#8a8a8a"))
        self._update_sleep_status()
        self._rebuild_vertical_sidebar()

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
            if tab.view.url().toString().startswith("file://") and "gem_browser_new_tab" in tab.view.url().toString(): icon = self._app_icon()
            self.tab_widget.setTabIcon(index, icon)
            self._rebuild_vertical_sidebar()

    def _attempt_autofill(self, tab: BrowserTab):
        if tab.is_suspended or tab.view is None or self.is_incognito or self.vault is None: return
        if tab.view.url().scheme() not in ("http", "https"): return
        creds = self.vault.get_credentials_for_url(tab.view.url().toString())
        if creds:
            tab.web_page.runJavaScript(f"(function() {{ var pwdInputs = document.querySelectorAll('input[type=\"password\"]'); if (pwdInputs.length > 0) {{ var p = pwdInputs[0]; p.value = {json.dumps(creds['password'])}; var allInputs = document.querySelectorAll('input:not([type=\"hidden\"])'); for (var i = 0; i < allInputs.length; i++) {{ if (allInputs[i] === p && i > 0) {{ allInputs[i - 1].value = {json.dumps(creds['username'])}; break; }} }} }} }})();")
            self._reset_vault_lock_timer()

    def close_tab(self, index: int):
        if self.tab_widget.count() > 1:
            widget = self.tab_widget.widget(index)
            def _do_remove(widget=widget):
                if isinstance(widget, BrowserTab):
                    url_str = widget.saved_url.toString() if widget.is_suspended else widget.view.url().toString()
                    if url_str and not (url_str.startswith("file://") and "gem_browser_new_tab" in url_str):
                        self.closed_tabs_stack.append(url_str)
                        del self.closed_tabs_stack[:-20]
                if widget in self.tab_timers:
                    self.tab_timers[widget].stop()
                    del self.tab_timers[widget]
                bar2 = self.tab_widget.tabBar()
                if isinstance(bar2, ProgressTabBar): bar2.set_progress(widget, None)
                current_index = self.tab_widget.indexOf(widget)
                if current_index != -1: self.tab_widget.removeTab(current_index)
                if isinstance(widget, BrowserTab):
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

        current_url = current_tab.saved_url.toString() if current_tab.is_suspended else current_tab.view.url().toString()
        if current_url.startswith("file://") and "gem_browser_new_tab" in current_url: self.url_bar.clear()
        else: self._set_url_bar_text(current_url)
        self._update_nav_buttons()
        if woke_up: self._update_sleep_status()
        self._rebuild_vertical_sidebar()

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
        self._rebuild_vertical_sidebar()

    def _update_tab_url(self, tab: BrowserTab, url: QUrl):
        if tab == self.current_tab() and not (url.toString().startswith("file://") and "gem_browser_new_tab" in url.toString()):
            self._set_url_bar_text(url.toString())

    def _record_history(self, tab: BrowserTab):
        if self.is_incognito or tab.is_suspended or tab.view is None: return
        url_str = tab.view.url().toString()
        if not url_str or tab.view.url().scheme() not in ("http", "https") or (url_str.startswith("file://") and "gem_browser_new_tab" in url_str): return
        self.persistent_history = gem_history.add_entry(self.persistent_history, url_str, tab.view.title() or url_str)
        if not self.session_history or self.session_history[-1] != url_str:
            self.session_history.append(url_str)
            if len(self.session_history) > 500: self.session_history = self.session_history[-500:]

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
                tab.view.setUrl(resolve_url(input_text))

    def closeEvent(self, event):
        self.vault_lock_timer.stop()
        if getattr(self, "tor_vpn", None) is not None and self.tor_vpn.is_active:
            self.tor_vpn.disconnect()
        if self._blocklist_thread is not None and self._blocklist_thread.isRunning():
            try:
                self._blocklist_thread.finished_ok.disconnect()
                self._blocklist_thread.finished_err.disconnect()
            except TypeError: pass
            if not [w for w in _active_windows if w is not self]: self._blocklist_thread.wait(3000)
        
        if self.is_incognito: self.shared_profile.cookieStore().deleteAllCookies()
        else:
            if not [w for w in _active_windows if w is not self]:
                tab_urls = self._collect_session_tab_urls()
                gem_session.save_session(tab_urls) if tab_urls else gem_session.clear_session()
        
        if self in _active_windows: _active_windows.remove(self)
        event.accept()
