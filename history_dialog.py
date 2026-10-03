"""Geçmiş penceresi (window.py'den ayrıldı)."""

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem
)
from gem_browser import history as gem_history
from gem_browser.modern_popup import show_modern_confirm


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
