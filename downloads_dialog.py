import os
import subprocess
import sys
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QLabel, QPushButton, QListWidgetItem, QHBoxLayout
from gem_browser.modern_popup import show_modern_info


class DownloadsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        lang = getattr(parent, "lang", "tr") if parent else "tr"
        self.lang = lang

        self.download_manager = getattr(parent, "download_manager", None) if parent else None

        self.setWindowTitle("İndirmeler" if lang == "tr" else "Downloads")
        self.resize(520, 380)

        self.layout = QVBoxLayout(self)

        lbl_text = "İndirilen dosyalar:" if lang == "tr" else "Downloaded files:"
        self.layout.addWidget(QLabel(lbl_text))

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._open_selected)
        self.layout.addWidget(self.list_widget)

        self._populate()

        # İndirme sırasında/tamamlandığında pencere açıksa listeyi anlık güncelle
        if self.download_manager:
            self.download_manager.history_changed.connect(self._populate)

        btn_row = QHBoxLayout()

        open_btn_text = "Dosyayı Aç" if lang == "tr" else "Open File"
        self.open_btn = QPushButton(open_btn_text)
        self.open_btn.clicked.connect(self._open_selected)
        btn_row.addWidget(self.open_btn)

        folder_btn_text = "Klasörde Göster" if lang == "tr" else "Show in Folder"
        self.folder_btn = QPushButton(folder_btn_text)
        self.folder_btn.clicked.connect(self._show_in_folder)
        btn_row.addWidget(self.folder_btn)

        btn_row.addStretch()

        close_btn_text = "Kapat" if lang == "tr" else "Close"
        close_btn = QPushButton(close_btn_text)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        self.layout.addLayout(btn_row)

    def _populate(self):
        self.list_widget.clear()

        if self.download_manager:
            history = self.download_manager.get_history()
            if not history:
                empty_text = "Henüz indirilen dosya yok." if self.lang == "tr" else "No downloads yet."
                self.list_widget.addItem(empty_text)
                return

            for entry in history:
                name = entry.get("name", "?")
                status = entry.get("status", "")
                path = entry.get("path", "")

                size_txt = ""
                if path and os.path.exists(path):
                    try:
                        size_mb = os.path.getsize(path) / (1024 * 1024)
                        size_txt = f"  ({size_mb:.1f} MB)"
                    except Exception:
                        pass

                display = f"{name}{size_txt}  —  {status}"
                item = QListWidgetItem(display)
                item.setData(Qt.ItemDataRole.UserRole, path)
                self.list_widget.addItem(item)
        else:
            # Yedek yol: download_manager bulunamazsa eski davranışa (disk taraması) düş.
            downloads_path = os.path.join(os.path.expanduser("~"), "Downloads")
            if os.path.exists(downloads_path):
                files = []
                for f in os.listdir(downloads_path):
                    full_path = os.path.join(downloads_path, f)
                    if os.path.isfile(full_path):
                        files.append((full_path, f, os.path.getmtime(full_path)))
                files.sort(key=lambda x: x[2], reverse=True)
                for full_p, f, _ in files[:50]:
                    size_mb = os.path.getsize(full_p) / (1024 * 1024)
                    item = QListWidgetItem(f"{f}  ({size_mb:.1f} MB)")
                    item.setData(Qt.ItemDataRole.UserRole, full_p)
                    self.list_widget.addItem(item)

    def _selected_path(self):
        item = self.list_widget.currentItem()
        if not item:
            return None
        path = item.data(Qt.ItemDataRole.UserRole)
        return path if path else None

    def _open_selected(self):
        path = self._selected_path()
        if not path or not os.path.exists(path):
            msg = "Dosya bulunamadı." if self.lang == "tr" else "File not found."
            show_modern_info(self, msg, lang=self.lang, warning=True)
            return
        self._open_path(path)

    def _show_in_folder(self):
        path = self._selected_path()
        if not path or not os.path.exists(path):
            msg = "Dosya bulunamadı." if self.lang == "tr" else "File not found."
            show_modern_info(self, msg, lang=self.lang, warning=True)
            return
        self._open_path(os.path.dirname(path))

    def _open_path(self, path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass
