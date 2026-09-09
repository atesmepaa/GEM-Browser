import os
import json
import time
from PyQt6.QtCore import QObject, Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar
)
from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest

from gem_browser.paths import config_path, secure_chmod

HISTORY_FILE = config_path("gem_downloads.json")

POPUP_MARGIN = 16
POPUP_SPACING = 10


class DownloadPopup(QDialog):
    """
    Sağ üst köşede beliren, kapatılsa bile indirmeyi durdurmayan küçük
    indirme bildirimi. Pencereyi kapatmak (X) sadece popup'ı gizler;
    indirme yalnızca "İptal" butonuna basılınca durur.
    """

    def __init__(self, file_name, lang="tr", parent=None):
        super().__init__(parent)
        self.lang = lang
        self._allow_close = False

        self.setWindowTitle("İndiriliyor" if lang == "tr" else "Downloading")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setFixedWidth(340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)

        starting = "Başlatılıyor..." if lang == "tr" else "Starting..."
        self.label = QLabel(f"{file_name}\n{starting}")
        layout.addWidget(self.label)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        layout.addWidget(self.bar)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.cancel_btn = QPushButton("İptal Et" if lang == "tr" else "Cancel")
        btn_row.addWidget(self.cancel_btn)
        layout.addLayout(btn_row)

    def closeEvent(self, event):
        # Kullanıcı pencereyi (X) kapatırsa: sadece gizle, indirmeye dokunma.
        if self._allow_close:
            event.accept()
        else:
            event.ignore()
            self.hide()

    def finish_and_close(self):
        self._allow_close = True
        self.close()

    def position_top_right(self, parent=None, stack_index=0):
        self.adjustSize()
        if parent is not None and parent.isVisible():
            geo = parent.frameGeometry()
            x = geo.x() + geo.width() - self.width() - POPUP_MARGIN
            y = geo.y() + POPUP_MARGIN + stack_index * (self.height() + POPUP_SPACING)
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.x() + screen.width() - self.width() - POPUP_MARGIN
            y = screen.y() + POPUP_MARGIN + stack_index * (self.height() + POPUP_SPACING)
        self.move(x, y)


class DownloadManager(QObject):
    # Bir indirme her eklendiğinde / güncellendiğinde bu sinyal tetiklenir,
    # açık olan İndirmeler penceresi anlık güncellenebilsin diye.
    history_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.active_downloads = {}
        self.history = self._load_history()

    # ---------------- Kalıcı geçmiş (JSON) ----------------
    def _load_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save_history(self):
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=4, ensure_ascii=False)
            secure_chmod(HISTORY_FILE)
        except Exception:
            pass

    def get_history(self):
        return sorted(self.history, key=lambda d: d.get("timestamp", 0), reverse=True)

    def _add_history_entry(self, req_id, file_name, full_path, status):
        entry = {
            "id": req_id,
            "name": file_name,
            "path": full_path,
            "status": status,
            "timestamp": time.time(),
        }
        self.history.insert(0, entry)
        self._save_history()
        self.history_changed.emit()
        return entry

    def _update_history_entry(self, req_id, **kwargs):
        for entry in self.history:
            if entry.get("id") == req_id:
                entry.update(kwargs)
                break
        self._save_history()
        self.history_changed.emit()

    # ---------------- İndirme akışı ----------------
    def handle_download(self, download_request):
        lang = getattr(self.parent, "lang", "tr") if self.parent else "tr"
        default_name = download_request.downloadFileName()
        default_dir = os.path.join(os.path.expanduser("~"), "Downloads")

        try:
            os.makedirs(default_dir, exist_ok=True)
        except Exception:
            pass

        default_path = os.path.join(default_dir, default_name)
        title = "Dosyayı Kaydet" if lang == "tr" else "Save File"

        if self.parent:
            self.parent.show()
            self.parent.raise_()
            self.parent.activateWindow()

        dialog = QFileDialog(self.parent, title, default_path)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

        result = dialog.exec()
        file_path = dialog.selectedFiles()[0] if (result and dialog.selectedFiles()) else ""

        if file_path:
            directory = os.path.dirname(file_path)
            file_name = os.path.basename(file_path)

            download_request.setDownloadDirectory(directory)
            download_request.setDownloadFileName(file_name)

            popup = DownloadPopup(file_name, lang=lang, parent=self.parent)
            popup.position_top_right(self.parent, stack_index=len(self.active_downloads))
            popup.show()
            popup.raise_()
            popup.activateWindow()

            req_id = download_request.id()
            self.active_downloads[req_id] = {
                "popup": popup,
                "request": download_request,
                "start_time": time.time(),
                "name": file_name,
                "lang": lang
            }

            status_label = "İndiriliyor" if lang == "tr" else "Downloading"
            self._add_history_entry(req_id, file_name, file_path, status_label)

            # Sadece "İptal Et" butonu indirmeyi gerçekten durdurur.
            popup.cancel_btn.clicked.connect(download_request.cancel)
            download_request.receivedBytesChanged.connect(lambda: self.update_progress(req_id))
            download_request.stateChanged.connect(lambda state: self.state_changed(req_id, state))

            download_request.accept()
        else:
            download_request.cancel()

    def update_progress(self, req_id):
        if req_id not in self.active_downloads:
            return

        data = self.active_downloads[req_id]
        request = data["request"]
        popup = data["popup"]

        received = request.receivedBytes()
        total = request.totalBytes()

        elapsed = time.time() - data["start_time"]
        speed_mbps = (received / elapsed) / (1024 * 1024) if elapsed > 0 else 0
        rec_mb = received / (1024 * 1024)

        if total > 0:
            pct = int((received / total) * 100)
            popup.bar.setRange(0, 100)
            popup.bar.setValue(pct)
            size_mb = total / (1024 * 1024)

            if data["lang"] == "tr":
                text = f"{data['name']}\n{rec_mb:.1f} MB / {size_mb:.1f} MB  —  Hız: {speed_mbps:.1f} MB/s"
            else:
                text = f"{data['name']}\n{rec_mb:.1f} MB / {size_mb:.1f} MB  —  Speed: {speed_mbps:.1f} MB/s"
            popup.label.setText(text)
        else:
            popup.bar.setRange(0, 0)
            if data["lang"] == "tr":
                text = f"{data['name']}\nİndirilen: {rec_mb:.1f} MB  —  Hız: {speed_mbps:.1f} MB/s"
            else:
                text = f"{data['name']}\nDownloaded: {rec_mb:.1f} MB  —  Speed: {speed_mbps:.1f} MB/s"
            popup.label.setText(text)

    def state_changed(self, req_id, state):
        if req_id not in self.active_downloads:
            return

        data = self.active_downloads[req_id]
        lang = data["lang"]
        popup = data["popup"]

        if state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            self._update_history_entry(req_id, status=("Tamamlandı" if lang == "tr" else "Completed"))
            done_text = "Tamamlandı ✓" if lang == "tr" else "Completed ✓"
            popup.label.setText(f"{data['name']}\n{done_text}")
            popup.bar.setRange(0, 100)
            popup.bar.setValue(100)
            popup.cancel_btn.setText("Kapat" if lang == "tr" else "Close")
            try:
                popup.cancel_btn.clicked.disconnect()
            except TypeError:
                pass
            popup.cancel_btn.clicked.connect(popup.finish_and_close)
            # Birkaç saniye sonra kendiliğinden kapansın.
            QTimer.singleShot(4000, popup.finish_and_close)
            self._cleanup_active(req_id, close_popup=False)
            return

        elif state == QWebEngineDownloadRequest.DownloadState.DownloadCancelled:
            self._update_history_entry(req_id, status=("İptal edildi" if lang == "tr" else "Cancelled"))
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
            self._update_history_entry(req_id, status=("Başarısız" if lang == "tr" else "Failed"))
        else:
            return

        popup.finish_and_close()
        self._cleanup_active(req_id, close_popup=False)

    def _cleanup_active(self, req_id, close_popup=True):
        if req_id in self.active_downloads:
            if close_popup:
                self.active_downloads[req_id]["popup"].finish_and_close()
            del self.active_downloads[req_id]
