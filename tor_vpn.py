"""
Gerçek ve sürdürülebilir bir "Yerleşik VPN" (Brave/Opera'daki tek tıkla
VPN'e eşdeğer, ücretsiz sürüm).

ÖNCE NEDEN ESKİ YÖNTEM (rastgele public proxy listesi) ÇALIŞMIYORDU:
Brave VPN ve Opera VPN, kendi işlettikleri ya da anlaşmalı oldukları ÖZEL,
BAKIMLI ve ÜCRETLİ sunucu altyapılarına dayanır (Opera -> SurfEasy'nin
kendi sunucuları; Brave VPN -> Guardian ortaklığıyla WireGuard sunucuları).
Bunlar sürekli izlenen, kapasitesi yönetilen gerçek VPN hizmetleridir.

Açık kaynaklı/hobi bir tarayıcının bu tür ücretli altyapıyı ücretsiz
sunması mümkün değil. İnternetten "ücretsiz public SOCKS5 proxy listesi"
çekip rastgele birine bağlanmak (eski davranış) ise gerçek bir VPN hizmeti
DEĞİLDİR — bu listelerdeki sunucuların büyük kısmı zaten çökmüş, kalanlar
da bakımsız ve aşırı yüklüdür; bu yüzden "site açılmıyor / aşırı yavaş"
şikayetine yol açıyordu.

BU MODÜLÜN YAKLAŞIMI:
Tor Project'in resmi, ücretsiz, dünya çapında binlerce gönüllü röleden
oluşan ve düzenli olarak bakımı yapılan ağını kullanıyoruz — Tor Browser'ın
kendisi de aynı ağı kullanır. Sistemde kurulu `tor` çalıştırılabilir
dosyasını arka planda, kendi geçici veri dizini ve rastgele boş bir yerel
SOCKS5 portuyla başlatıp; devre (circuit) kurulumu tamamlanınca
(bootstrap %100) o yerel SOCKS5 proxy'sini uygulamaya bağlıyoruz. Bu,
gerçekten çalışan ve sürdürülebilir, dürüst bir "ücretsiz VPN" sağlar.

Sınırlama: Tor, ticari bir VPN kadar hızlı değildir (birden çok röle
üzerinden yönlendirme yaptığı için gecikme daha yüksektir) ama gerçek,
canlı ve güvenilir bir ağdır — rastgele ölü/aşırı yüklü public proxy'lerin
tam tersi.

DÜRÜST ANONİMLİK NOTU: Bu entegrasyon Tor Browser kadar anonim DEĞİLDİR —
tor daemon'ı üzerinden giden trafiğin kendisi Tor ağıdır, ama tarayıcı
parmak izi, WebRTC/DNS kenar durumları ve davranışsal izleme korunmaz.
(VPN açıkken WebRTC IP sızıntısı uygulama tarafında engellenir; bkz.
main.py --force-webrtc-ip-handling-policy ve window.py'deki
WebRTCPublicInterfacesOnly.) Yüksek riskli kullanım için resmi
Tor Browser tercih edilmelidir. Kullanıcı isterse (Ayarlar'da host/port doldurarak) kendi
ücretli VPN sağlayıcısının SOCKS5 adresini de girebilir; bu durumda bu
modül hiç devreye girmez (bkz. window.py:_apply_vpn).
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile

from PyQt6.QtCore import QObject, QThread, pyqtSignal


def find_tor_binary() -> str:
    """Sistemde kurulu `tor` çalıştırılabilirini arar (Linux'ta paket
    yöneticisiyle -ör. `sudo apt install tor`-, macOS'ta `brew install tor`,
    Windows'ta Tor Expert Bundle ile kurulmuş olabilir). Bulunamazsa boş
    string döner; çağıran taraf bunu kullanıcıya açıkça bildirmelidir."""
    return shutil.which("tor") or ""


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _TorWorker(QObject):
    """Tor sürecini ayrı bir iş parçacığında çalıştırır; stdout'taki
    'Bootstrapped NN%' satırlarını okuyup ilerlemeyi/bağlantıyı sinyallerle
    bildirir. Doğrudan örneklenmez — bkz. TorVpnManager."""

    progress = pyqtSignal(int)      # bootstrap yüzdesi
    connected = pyqtSignal(int)     # hazır olan SOCKS5 port numarası
    failed = pyqtSignal(str)        # kullanıcıya gösterilecek hata mesajı
    stopped = pyqtSignal()

    def __init__(self, tor_path: str):
        super().__init__()
        self.tor_path = tor_path
        self._process = None
        self._stop_requested = False
        self._data_dir = None

    def start(self):
        try:
            # Rastgele boş bir yerel SOCKS5 portu; window.py, connected
            # sinyaliyle bu portu QNetworkProxy'ye uyguladığı için portun
            # önceden bilinmesi gerekmez.
            socks_port = _free_tcp_port()
            self._data_dir = tempfile.mkdtemp(prefix="gem_tor_")

            # ÖNEMLİ: Tor varsayılan olarak /etc/tor/torrc'yi okur; dağıtım
            # torrc'lerindeki "User tor" satırı, root OLMAYAN bir kullanıcı
            # olarak çalıştırıldığında "Failed to parse/validate config"
            # hatasıyla (çıkış kodu 1) anında ölmesine yol açıyordu. Kendi
            # BOŞ konfigürasyon dosyamızı vererek sistem torrc'sini tamamen
            # bypass ediyoruz.
            torrc_path = os.path.join(self._data_dir, "torrc")
            with open(torrc_path, "w", encoding="utf-8") as f:
                f.write("")

            cmd = [
                self.tor_path,
                "-f", torrc_path,
                "--SocksPort", str(socks_port),
                "--DataDirectory", self._data_dir,
                "--ControlPort", "0",
                "--Log", "notice stdout",
            ]
            popen_kwargs = {}
            if sys.platform.startswith("win"):
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                **popen_kwargs,
            )
        except Exception as exc:
            self.failed.emit(f"Tor başlatılamadı: {exc}")
            self._cleanup_process()
            self.stopped.emit()
            return

        already_connected = False
        last_warning = ""
        try:
            for line in self._process.stdout:
                if self._stop_requested:
                    break
                line = line.strip()
                if not line:
                    continue
                if "Bootstrapped" in line:
                    try:
                        pct = int(line.split("Bootstrapped")[1].split("%")[0].strip())
                    except (ValueError, IndexError):
                        pct = 0
                    self.progress.emit(pct)
                    if pct >= 100 and not already_connected:
                        already_connected = True
                        self.connected.emit(socks_port)
                elif "[warn]" in line.lower() or "[err]" in line.lower():
                    # Kullanıcıya gösterilecek en güncel Tor uyarısı/hatası
                    # (zaman damgası kısmı atılır).
                    tail = line.split("] ", 1)[-1]
                    last_warning = tail[:160]
        finally:
            self._cleanup_process()

        if not self._stop_requested:
            code = self._process.poll() if self._process else None
            if not already_connected:
                detail = f" (çıkış kodu: {code})" if code not in (None, 0) else ""
                if last_warning:
                    self.failed.emit(f"Tor devresi kurulamadı{detail}. Tor: {last_warning}")
                else:
                    self.failed.emit(f"Tor devresi kurulamadı{detail}.")
            elif code not in (None, 0):
                # Bağlıyken süreç beklenmedik şekilde kapandı.
                self.failed.emit(f"Tor beklenmedik şekilde kapandı (kod {code}).")

        self.stopped.emit()

    def _cleanup_process(self):
        """Sürecin tam olarak kapanmasını bekle ve geçici veri dizinini
        sil. Bilinçli olarak yalnızca İŞÇİ THREAD'inden çağrılır —
        beklemeler (wait/kill) UI thread'ini bloklamasın."""
        if self._process is not None:
            if self._process.poll() is None:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=5)
                except Exception:
                    try:
                        self._process.kill()
                        self._process.wait(timeout=3)
                    except Exception:
                        pass
        if self._data_dir and os.path.isdir(self._data_dir):
            shutil.rmtree(self._data_dir, ignore_errors=True)
            self._data_dir = None

    def stop(self):
        # UI thread'inden çağrılabilir; hızlı geri döner. Sürecin
        # kapanmasını bekleme/rmtree işi, stdout okuma döngüsü sona erdikten
        # sonra _cleanup_process() tarafından işçi thread'inde yapılır.
        self._stop_requested = True
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
            except Exception:
                pass


class TorVpnManager(QObject):
    """
    window.py tarafından kullanılan, MainWindow başına bir tane olan
    yönetici. Tor sürecinin thread yaşam döngüsünü sarmalar; UI tarafı
    sadece connect()/disconnect() çağırır ve status_changed/error
    sinyallerini dinler.
    """

    # status: "connecting" | "connected" | "error" | "disconnected"
    status_changed = pyqtSignal(str, int)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None
        # disconnect() sırasında hâlâ kapanmakta olan thread'ler: Python
        # referansı düşerse C++ tarafı çalışırken silinip çökmesin.
        self._dying_threads = []
        self.socks_port = None
        self.is_connected = False
        self._connecting = False

    def is_available(self) -> bool:
        return bool(find_tor_binary())

    @property
    def is_active(self) -> bool:
        """True if a Tor process is running or currently connecting."""
        return self._thread is not None or self.is_connected

    def connect(self):
        if self._connecting or self.is_connected or self._thread is not None:
            return  # zaten bağlanıyor ya da bağlı

        tor_path = find_tor_binary()
        if not tor_path:
            self.error.emit(
                "Tor bulunamadı. Otomatik VPN için 'tor' paketini kurup "
                "tekrar deneyin (ör. Debian/Ubuntu: sudo apt install tor)."
            )
            self.status_changed.emit("error", 0)
            return

        self._connecting = True
        self._thread = QThread()
        self._worker = _TorWorker(tor_path)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.start)
        self._worker.progress.connect(self._on_progress)
        self._worker.connected.connect(self._on_connected)
        self._worker.failed.connect(self._on_failed)
        self._worker.stopped.connect(self._thread.quit)
        # Thread bittiğinde referansları temizle: aksi halde başarısız bir
        # denemeden sonra _thread dolu kalır ve connect() sonsuza dek "zaten
        # bağlı" sanıp erken dönerdi — kullanıcı VPN'i yeniden açamazdı.
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_worker_thread_finished)

        self.status_changed.emit("connecting", 0)
        self._thread.start()

    def _on_worker_thread_finished(self):
        sender = self.sender()
        if isinstance(sender, QThread) and sender in self._dying_threads:
            self._dying_threads.remove(sender)
        if sender is self._thread:
            self._thread = None
            self._worker = None

    def _on_progress(self, pct):
        if self._connecting:
            self.status_changed.emit("connecting", pct)

    def _on_connected(self, socks_port):
        self._connecting = False
        self.socks_port = socks_port
        self.is_connected = True
        self.status_changed.emit("connected", 100)

    def _on_failed(self, message):
        self._connecting = False
        self.is_connected = False
        self.socks_port = None
        self.error.emit(message)
        self.status_changed.emit("error", 0)

    def disconnect(self):
        worker = self._worker
        thread = self._thread
        if worker:
            worker.stop()  # artık bloklamayan çağrı; beklemeyi işçi yapar
        if thread:
            thread.quit()
            if not thread.wait(3000):
                # Hâlâ kapanmadıysa referansı tut; bittiğinde kendini
                # temizler (bkz. _on_worker_thread_finished).
                self._dying_threads.append(thread)
        self._thread = None
        self._worker = None
        self.socks_port = None
        self.is_connected = False
        self._connecting = False
        self.status_changed.emit("disconnected", 0)
