import base64
import json
import secrets
import sqlite3
import csv
import os
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QInputDialog, QFileDialog, QHeaderView, QMenu,
    QLineEdit, QLabel
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from gem_browser.settings import BrowserSettings
from gem_browser.modern_popup import show_modern_info, show_modern_confirm
from gem_browser.paths import config_path, secure_chmod

DB_FILE = config_path("gem_passwords.db")
# Şifreleme anahtarının kendisi ARTIK diske yazılmıyor (eskiden DB ile aynı
# dizinde duruyordu, bu da şifrelemenin amacını geçersiz kılıyordu). Bunun
# yerine burada sadece anahtarı bir ana paroladan türetmek için gereken KDF
# parametreleri (salt) ve parolayı doğrulamak için bir "canary" (kontrol
# değeri) tutuluyor. Bu iki bilgi tek başına şifreleri çözmeye yetmez.
META_FILE = config_path("gem_vault_meta.json")

PBKDF2_ITERATIONS = 480_000
_CANARY = b"GEM_BROWSER_VAULT_OK"


class WrongMasterPassword(Exception):
    """Girilen ana parola, kasanın kilidini açmak için yanlış."""
    pass


def vault_exists() -> bool:
    """Daha önce bir ana parola ile kasa oluşturulmuş mu?"""
    return os.path.exists(META_FILE)


def _derive_key(master_password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode("utf-8")))


def verify_master_password(master_password: str) -> bool:
    """
    Kasayı tam olarak yeniden açmadan (yeni bir SQLite bağlantısı kurmadan),
    yalnızca meta dosyasındaki "canary" değerini kontrol ederek verilen
    parolanın doğru ana parola olup olmadığını söyler. Şifre yöneticisi
    zaten açıkken hassas bir işlemi (site/kullanıcı adı/şifre değişikliği)
    onaylatmak için kullanılır — kasa açık olsa bile bu tür değişiklikler
    ana parolanın tekrar girilmesini gerektirir.
    """
    if not master_password or not os.path.exists(META_FILE):
        return False
    try:
        with open(META_FILE, "r", encoding="utf-8") as f:
            meta = json.load(f)
        salt = base64.b64decode(meta["salt"])
        key = _derive_key(master_password, salt)
        cipher = Fernet(key)
        cipher.decrypt(base64.b64decode(meta["check"]))
        return True
    except Exception:
        return False


class PasswordVault:
    """
    Şifre kasası artık bir ANA PAROLA olmadan açılamaz. Şifreleme anahtarı
    hiçbir zaman diske yazılmaz; her seferinde ana paroladan + rastgele bir
    salt'tan (PBKDF2 ile) türetilir. Böylece sadece veritabanı dosyasına
    erişen biri (yedekleme, senkronizasyon, vs.) şifreleri çözemez.
    """

    def __init__(self, master_password: str):
        if not master_password:
            raise ValueError("master_password boş olamaz")

        if os.path.exists(META_FILE):
            with open(META_FILE, "r", encoding="utf-8") as f:
                meta = json.load(f)
            salt = base64.b64decode(meta["salt"])
            key = _derive_key(master_password, salt)
            cipher = Fernet(key)
            try:
                cipher.decrypt(base64.b64decode(meta["check"]))
            except InvalidToken:
                raise WrongMasterPassword()
        else:
            # İlk kurulum: yeni salt üret, canary'i şifreleyip kaydet.
            salt = secrets.token_bytes(16)
            key = _derive_key(master_password, salt)
            cipher = Fernet(key)
            meta = {
                "salt": base64.b64encode(salt).decode(),
                "check": base64.b64encode(cipher.encrypt(_CANARY)).decode(),
            }
            with open(META_FILE, "w", encoding="utf-8") as f:
                json.dump(meta, f)
            secure_chmod(META_FILE)

        self.cipher = cipher
        self._init_db()

    def _init_db(self):
        self.conn = sqlite3.connect(DB_FILE)
        self.cursor = self.conn.cursor()
        self.cursor.execute("CREATE TABLE IF NOT EXISTS passwords (id INTEGER PRIMARY KEY AUTOINCREMENT, site TEXT NOT NULL, username TEXT NOT NULL, password TEXT NOT NULL)")
        self.conn.commit()
        secure_chmod(DB_FILE)

    def get_all_entries(self):
        self.cursor.execute("SELECT id, site, username, password FROM passwords")
        rows = self.cursor.fetchall()
        entries = []
        for row in rows:
            try:
                decrypted_pwd = self.cipher.decrypt(row[3].encode()).decode()
            except:
                decrypted_pwd = "Error"
            entries.append({"id": row[0], "site": row[1], "username": row[2], "password": decrypted_pwd})
        return entries

    def add_entry(self, site, username, password):
        encrypted_pwd = self.cipher.encrypt(password.encode()).decode()
        self.cursor.execute("INSERT INTO passwords (site, username, password) VALUES (?, ?, ?)", (site, username, encrypted_pwd))
        self.conn.commit()

    def add_entries_bulk(self, entries_list):
        data = [(s, u, self.cipher.encrypt(p.encode()).decode()) for s, u, p in entries_list]
        self.cursor.executemany("INSERT INTO passwords (site, username, password) VALUES (?, ?, ?)", data)
        self.conn.commit()

    def remove_entry(self, entry_id):
        self.cursor.execute("DELETE FROM passwords WHERE id = ?", (entry_id,))
        self.conn.commit()

    def update_entry(self, entry_id, site=None, username=None, password=None):
        """
        Var olan bir kaydı kısmen günceller (yalnızca None olmayan alanlar
        değiştirilir). Şifre verilmişse, kaydedilmeden önce yeniden
        şifrelenir — düz metin asla diske yazılmaz.
        """
        fields, values = [], []
        if site is not None:
            fields.append("site = ?")
            values.append(site)
        if username is not None:
            fields.append("username = ?")
            values.append(username)
        if password is not None:
            fields.append("password = ?")
            values.append(self.cipher.encrypt(password.encode()).decode())
        if not fields:
            return
        values.append(entry_id)
        self.cursor.execute(f"UPDATE passwords SET {', '.join(fields)} WHERE id = ?", values)
        self.conn.commit()

    @staticmethod
    def _netloc(value: str) -> str:
        """'site' alanını (şema olsun olmasın) normalize edilmiş bir domain'e çevirir."""
        value = (value or "").strip().lower()
        if not value:
            return ""
        if "://" not in value:
            value = "https://" + value
        netloc = urlparse(value).netloc
        return netloc.split(":")[0] if netloc else value

    def get_credentials_for_url(self, url):
        """
        Kayıtlı 'site' alanı ile ziyaret edilen sayfanın domain'ini TAM ya da
        alt-domain olarak karşılaştırır (eskiden substring aramasıydı, bu
        phishing sitelerine kimlik bilgisi sızdırma riski taşıyordu).
        """
        target = self._netloc(urlparse(url).netloc or url)
        if not target:
            return None
        for entry in self.get_all_entries():
            site_netloc = self._netloc(entry.get("site", ""))
            if not site_netloc:
                continue
            if target == site_netloc or target.endswith("." + site_netloc):
                return entry
        return None


class MasterPasswordDialog(QDialog):
    """
    Kasa ilk kez oluşturuluyorsa yeni bir ana parola belirlemeyi, zaten
    varsa kilidini açmak için parolayı sormayı sağlar. Girilen parola hiçbir
    yere yazılmaz; sadece anahtar türetmek için anlık olarak kullanılır.
    """

    def __init__(self, mode="unlock", lang="tr", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.lang = lang
        self._password = ""
        create = mode == "create"

        if create:
            title = "Ana Parola Oluştur" if lang == "tr" else "Create Master Password"
        else:
            title = "Ana Parola" if lang == "tr" else "Master Password"
        self.setWindowTitle(title)
        self.setStyleSheet(
            "QDialog { background-color: #1a1a1a; color: #ffffff; } "
            "QLineEdit { background-color: #242424; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px; } "
            "QPushButton { background-color: #2a2a2a; color: #ffffff; border: 1px solid #333333; padding: 6px 12px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #3b3b3b; border: 1px solid #3daee9; } "
            "QLabel { color: #d4d4d4; }"
        )

        layout = QVBoxLayout(self)

        if create:
            info = ("Şifre yöneticinizi korumak için bir ana parola belirleyin.\n"
                     "Bu parolayı unutursanız kayıtlı şifreleriniz kurtarılamaz.") if lang == "tr" else \
                    ("Set a master password to protect your password manager.\n"
                     "If you forget it, saved passwords cannot be recovered.")
        else:
            info = "Şifre yöneticisinin kilidini açmak için ana parolanızı girin:" if lang == "tr" \
                else "Enter your master password to unlock the password manager:"
        info_lbl = QLabel(info)
        info_lbl.setWordWrap(True)
        layout.addWidget(info_lbl)

        self.pwd_input = QLineEdit()
        self.pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd_input.setPlaceholderText("Ana Parola" if lang == "tr" else "Master Password")
        layout.addWidget(self.pwd_input)

        self.confirm_input = None
        if create:
            self.confirm_input = QLineEdit()
            self.confirm_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirm_input.setPlaceholderText("Parolayı Onayla" if lang == "tr" else "Confirm Password")
            layout.addWidget(self.confirm_input)

        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("color: #ff5555;")
        self.error_lbl.setWordWrap(True)
        layout.addWidget(self.error_lbl)

        btn_row = QHBoxLayout()
        if create:
            ok_text = "Oluştur" if lang == "tr" else "Create"
        else:
            ok_text = "Aç" if lang == "tr" else "Unlock"
        ok_btn = QPushButton(ok_text)
        ok_btn.clicked.connect(self._on_accept)
        cancel_btn = QPushButton("İptal" if lang == "tr" else "Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self.pwd_input.returnPressed.connect(self._on_accept)

    def _on_accept(self):
        pwd = self.pwd_input.text()
        if not pwd:
            self.error_lbl.setText("Parola boş olamaz." if self.lang == "tr" else "Password cannot be empty.")
            return
        if self.mode == "create":
            if len(pwd) < 6:
                self.error_lbl.setText(
                    "Parola en az 6 karakter olmalı." if self.lang == "tr" else "Password must be at least 6 characters.")
                return
            if pwd != self.confirm_input.text():
                self.error_lbl.setText("Parolalar eşleşmiyor." if self.lang == "tr" else "Passwords do not match.")
                return
        self._password = pwd
        self.accept()

    def get_password(self) -> str:
        return self._password


class PasswordManagerDialog(QDialog):
    def __init__(self, vault: "PasswordVault", parent=None):
        super().__init__(parent)
        self.settings = BrowserSettings().current
        self.lang = self.settings.get("language", "tr")
        self.vault = vault
        
        self.setWindowTitle("Şifre Yöneticisi" if self.lang == "tr" else "Password Manager")
        self.resize(650, 400)
        self.setStyleSheet("QDialog { background-color: #1a1a1a; color: #ffffff; } QTableWidget { background-color: #242424; color: #ffffff; border: 1px solid #333333; } QHeaderView::section { background-color: #2a2a2a; color: #3daee9; padding: 4px; border: 1px solid #333333; } QPushButton { background-color: #2a2a2a; color: #ffffff; border: 1px solid #333333; padding: 6px 12px; border-radius: 4px; } QPushButton:hover { background-color: #3b3b3b; border: 1px solid #3daee9; } QMenu { background-color: #242424; color: #ffffff; border: 1px solid #333333; } QMenu::item:selected { background-color: #3daee9; }")

        self.layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 3)
        headers = ["Site / Domain", "Kullanıcı Adı", "Şifre"] if self.lang == "tr" else ["Site / Domain", "Username", "Password"]
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self._populating = False
        self.table.itemChanged.connect(self._on_item_changed)
        self.layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("Yeni Ekle" if self.lang == "tr" else "Add New")
        self.btn_add.clicked.connect(self.add_password)
        self.btn_del = QPushButton("Seçileni Sil" if self.lang == "tr" else "Delete Selected")
        self.btn_del.clicked.connect(self.delete_password)
        self.btn_import = QPushButton("CSV İçe Aktar" if self.lang == "tr" else "Import CSV")
        self.btn_import.clicked.connect(self.import_csv)
        self.btn_export = QPushButton("CSV Dışa Aktar" if self.lang == "tr" else "Export CSV")
        self.btn_export.clicked.connect(self.export_csv)

        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_del)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_import)
        btn_layout.addWidget(self.btn_export)
        self.layout.addLayout(btn_layout)
        self.refresh_table()

    def refresh_table(self):
        # itemChanged, setItem() çağrıları sırasında da tetiklenir; bu
        # programatik doldurmayı kullanıcı düzenlemesiyle karıştırmamak
        # için _populating bayrağıyla bastırılıyor.
        self._populating = True
        self.table.setRowCount(0)
        self.entries = self.vault.get_all_entries()
        display_entries = self.entries[:500]
        self.table.setRowCount(len(display_entries))
        for i, entry in enumerate(display_entries):
            pwd_item = QTableWidgetItem("********")
            # Şifre sütunu asla gerçek değeri göstermiyor (sadece maske);
            # buraya doğrudan yazmak anlamsız olurdu, bu yüzden düzenleme
            # devre dışı — şifre değiştirme sağ tık menüsündeki ayrı,
            # ana parola onaylı akıştan yapılır.
            pwd_item.setFlags(pwd_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.table.setItem(i, 0, QTableWidgetItem(entry["site"]))
            self.table.setItem(i, 1, QTableWidgetItem(entry["username"]))
            self.table.setItem(i, 2, pwd_item)
        self._populating = False

    def _on_item_changed(self, item):
        """
        Kullanıcı Site/Domain ya da Kullanıcı Adı hücresini doğrudan
        tabloda düzenleyip Enter'a bastığında (veya hücreden çıktığında)
        tetiklenir. Değişikliği kalıcı kılmadan önce ana parolayı tekrar
        sorar; onaylanmazsa hücre eski değerine geri döner.
        """
        if self._populating:
            return

        row, col = item.row(), item.column()
        if row >= len(self.entries) or col not in (0, 1):
            return

        entry = self.entries[row]
        field = "site" if col == 0 else "username"
        old_value = entry[field]
        new_value = item.text()
        if new_value == old_value:
            return

        if not self._confirm_master_password():
            self._populating = True
            item.setText(old_value)
            self._populating = False
            msg = "Değişiklik iptal edildi." if self.lang == "tr" else "Change cancelled."
            show_modern_info(self, msg, lang=self.lang)
            return

        self.vault.update_entry(entry["id"], **{field: new_value})
        self.refresh_table()

    def _confirm_master_password(self, attempts: int = 3) -> bool:
        """
        Hassas bir değişikliği (site/kullanıcı adı/şifre) kaydetmeden önce
        ana parolayı yeniden ister. Kasa zaten açık olsa bile bu ekstra
        doğrulama, ekranı açık bırakılmış bir Şifre Yöneticisi'nin başkası
        tarafından kayıtları sessizce değiştirmesini zorlaştırır.
        """
        title = "Ana Parolayı Onayla" if self.lang == "tr" else "Confirm Master Password"
        for _ in range(attempts):
            dlg = MasterPasswordDialog(mode="unlock", lang=self.lang, parent=self)
            dlg.setWindowTitle(title)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return False
            if verify_master_password(dlg.get_password()):
                return True
            msg = "Yanlış ana parola." if self.lang == "tr" else "Wrong master password."
            show_modern_info(self, msg, lang=self.lang, warning=True)
        return False

    def _show_context_menu(self, position):
        row = self.table.currentRow()
        if row >= 0:
            menu = QMenu(self)
            txt = "👁 Şifreyi Göster" if self.lang == "tr" else "👁 Show Password"
            show_pwd_action = QAction(txt, self)
            show_pwd_action.triggered.connect(lambda: self._reveal_password(row))
            menu.addAction(show_pwd_action)

            change_txt = "🔑 Şifreyi Değiştir" if self.lang == "tr" else "🔑 Change Password"
            change_pwd_action = QAction(change_txt, self)
            change_pwd_action.triggered.connect(lambda: self._change_password(row))
            menu.addAction(change_pwd_action)

            menu.exec(self.table.viewport().mapToGlobal(position))

    def _reveal_password(self, row):
        if not (0 <= row < len(self.entries)):
            return
        # Ekranı açık bırakılmış bir Şifre Yöneticisi'nin yanından geçen biri
        # doğrudan sağ tık > "Şifreyi Göster" ile şifreyi görebiliyordu; artık
        # site/kullanıcı adı değişikliği ve şifre değiştirmeyle aynı ekstra
        # onayı (ana parolayı tekrar isteme) gerektiriyor.
        if not self._confirm_master_password():
            return
        entry = self.entries[row]
        # Pencere başlığı olarak sadece site adını kullanıyoruz; "Şifre
        # Detayı — çok-uzun-bir-domain.com" gibi uzun başlıklar bazı
        # pencere yöneticilerinde kesilip anlaşılmaz hale geliyordu.
        title = entry["site"] or ("Şifre Detayı" if self.lang == "tr" else "Password Details")
        u_txt = "Kullanıcı Adı" if self.lang == "tr" else "Username"
        p_txt = "Şifre" if self.lang == "tr" else "Password"
        show_modern_info(self, f"{u_txt}: {entry['username']}\n{p_txt}: {entry['password']}", title=title, lang=self.lang)

    def _change_password(self, row):
        if not (0 <= row < len(self.entries)):
            return
        if not self._confirm_master_password():
            return
        p_txt = "Yeni Şifre:" if self.lang == "tr" else "New Password:"
        new_pwd, ok = QInputDialog.getText(
            self, "Şifreyi Değiştir" if self.lang == "tr" else "Change Password", p_txt,
            QLineEdit.EchoMode.Password
        )
        if ok and new_pwd:
            self.vault.update_entry(self.entries[row]["id"], password=new_pwd)
            self.refresh_table()

    def add_password(self):
        site, ok1 = QInputDialog.getText(self, "Ekle" if self.lang == "tr" else "Add", "Site:")
        if ok1 and site:
            u_txt = "Kullanıcı Adı:" if self.lang == "tr" else "Username:"
            user, ok2 = QInputDialog.getText(self, "Ekle" if self.lang == "tr" else "Add", u_txt)
            if ok2 and user:
                p_txt = "Şifre:" if self.lang == "tr" else "Password:"
                # ÖNEMLİ: echo modu belirtilmezse QInputDialog varsayılan olarak
                # düz metin (Normal) gösterir; şifre yazılırken ekranda açıkça
                # görünür hale gelirdi. Password echo modu ile maskeleniyor.
                pwd, ok3 = QInputDialog.getText(
                    self, "Ekle" if self.lang == "tr" else "Add", p_txt,
                    QLineEdit.EchoMode.Password
                )
                if ok3 and pwd:
                    self.vault.add_entry(site, user, pwd)
                    self.refresh_table()

    def delete_password(self):
        row = self.table.currentRow()
        if row >= 0:
            self.vault.remove_entry(self.entries[row]["id"])
            self.refresh_table()

    def export_csv(self):
        # CSV, şifreleri DÜZ METİN olarak diske yazar (kasadaki gibi
        # şifrelenmiş değil) — kullanıcı bunu bilmeden bir CSV'yi bulut
        # yedeğine/e-postaya/paylaşılan bir klasöre koyabilir. Bu yüzden
        # dosya oluşturulmadan önce ne olduğunu açıkça belirten, "danger"
        # (kırmızı) bir onay isteniyor; ayrıca ana parola da tekrar
        # sorulup doğrulanıyor — kasa açık bırakılmışsa bile rastgele
        # birinin tüm şifreleri tek CSV dosyası halinde dışa aktarmasını
        # zorlaştırır.
        warn = (
            "Bu dosya TÜM şifrelerinizi ŞİFRELENMEMİŞ (düz metin) olarak "
            "içerecek. Bulut yedeği, e-posta veya paylaşılan bir klasöre "
            "koymayın. Yine de devam etmek istiyor musunuz?"
        ) if self.lang == "tr" else (
            "This file will contain ALL your passwords UNENCRYPTED "
            "(plain text). Do not put it in a cloud backup, email, or a "
            "shared folder. Do you still want to continue?"
        )
        title = "Şifreler Şifrelenmemiş Olacak" if self.lang == "tr" else "Passwords Will Be Unencrypted"
        if not show_modern_confirm(self, warn, title=title, lang=self.lang, danger=True):
            return
        if not self._confirm_master_password():
            return

        path, _ = QFileDialog.getSaveFileName(self, "CSV Olarak Kaydet" if self.lang == "tr" else "Save as CSV", "", "CSV Files (*.csv)")
        if path:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["site", "username", "password"])
                for entry in self.entries:
                    writer.writerow([entry["site"], entry["username"], entry["password"]])
            secure_chmod(path)
            done = "Dışa aktarma tamamlandı. Bu dosyayı güvenli bir yerde saklayın." if self.lang == "tr" \
                else "Export complete. Keep this file somewhere secure."
            show_modern_info(self, done, lang=self.lang, warning=True)

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "CSV Seç" if self.lang == "tr" else "Select CSV", "", "CSV Files (*.csv)")
        if path:
            batch_data = []
            with open(path, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    site, user, pwd = row.get("site", "").strip(), row.get("username", "").strip(), row.get("password", "").strip()
                    if site and user: batch_data.append((site, user, pwd))
            if batch_data:
                self.vault.add_entries_bulk(batch_data)
                self.refresh_table()
