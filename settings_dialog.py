"""Ayarlar ve tarama verileri temizleme pencereleri (window.py'den ayrıldı)."""

import os
import shutil

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPushButton,
    QComboBox, QLineEdit, QScrollArea, QFrame, QFileDialog, QWidget,
    QColorDialog
)
from PyQt6.QtGui import QColor
from gem_browser import theme as gem_theme
from gem_browser import paths as gem_paths
from gem_browser.modern_popup import show_modern_info
from gem_browser.router import search_engine_label


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

        # --- Arama motoru ---
        se_layout = QHBoxLayout()
        se_layout.addWidget(QLabel("Arama Motoru:" if lang == "tr" else "Search Engine:"))
        self.combo_engine = QComboBox()
        for key in ("brave", "duckduckgo", "startpage", "google", "custom"):
            self.combo_engine.addItem(search_engine_label(key, lang), userData=key)
        self.combo_engine.setCurrentIndex(max(0, self.combo_engine.findData(
            self.settings_manager.current.get("search_engine", "brave"))))
        se_layout.addWidget(self.combo_engine)
        layout.addLayout(se_layout)

        self.custom_engine_input = QLineEdit()
        self.custom_engine_input.setPlaceholderText(
            "Özel arama URL'i ({q} sorgu yer tutucusu, ör: https://site/?q={q})"
            if lang == "tr" else
            "Custom search URL ({q} placeholder, e.g.: https://site/?q={q})")
        self.custom_engine_input.setText(self.settings_manager.current.get("custom_search_url", ""))
        layout.addWidget(self.custom_engine_input)
        self.custom_engine_hint = QLabel(
            "'Özel Arama' seçiliyken kullanılır. {q} yazdığınız sorguyla değiştirilir; yer tutucu yoksa sorgu URL'nin sonuna eklenir."
            if lang == "tr" else
            "Used when 'Custom Search' is selected. {q} is replaced by your query; without the placeholder the query is appended."
        )
        self.custom_engine_hint.setWordWrap(True)
        self.custom_engine_hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(self.custom_engine_hint)
        self.combo_engine.currentIndexChanged.connect(self._refresh_custom_engine_visibility)
        self._refresh_custom_engine_visibility()

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

        # --- RAM: arka plan sekmesini uyutma süresi ---
        suspend_layout = QHBoxLayout()
        suspend_layout.addWidget(QLabel("Arka Plan Sekmesini Uyut:" if lang == "tr" else "Suspend Background Tab After:"))
        self.combo_suspend = QComboBox()
        for text, value in (
            (("Asla uyutma" if lang == "tr" else "Never"), 0.0),
            (("30 saniye" if lang == "tr" else "30 seconds"), 0.5),
            (("1 dakika" if lang == "tr" else "1 minute"), 1.0),
            (("2 dakika" if lang == "tr" else "2 minutes"), 2.0),
            (("4 dakika (önerilen)" if lang == "tr" else "4 minutes (recommended)"), 4.0),
        ):
            self.combo_suspend.addItem(text, userData=value)
        try:
            _cur_mins = float(self.settings_manager.current.get("tab_suspend_minutes", 4.0))
        except (TypeError, ValueError):
            _cur_mins = 4.0
        _idx = self.combo_suspend.findData(_cur_mins)
        self.combo_suspend.setCurrentIndex(_idx if _idx != -1 else 4)
        suspend_layout.addWidget(self.combo_suspend)
        layout.addLayout(suspend_layout)
        suspend_hint = QLabel(
            "Arka planda bu kadar süre hareketsiz kalan sekme RAM tasarrufu için uyutulur; sekme tıklanınca yeniden yüklenir. Düşük RAM modu açıkken süre yarıya iner."
            if lang == "tr" else
            "Background tabs idle for this long are suspended to save RAM; clicking the tab reloads it. Low RAM Mode halves this duration."
        )
        suspend_hint.setWordWrap(True)
        suspend_hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(suspend_hint)

        # --- RAM: canlı sekme sınırı ---
        maxlive_layout = QHBoxLayout()
        maxlive_layout.addWidget(QLabel("Canlı Sekme Sınırı:" if lang == "tr" else "Live Tab Limit:"))
        self.combo_maxlive = QComboBox()
        for text, value in (
            (("Sınırsız" if lang == "tr" else "Unlimited"), 0),
            ("5", 5), ("8", 8), ("10", 10), ("15", 15), ("20", 20),
        ):
            self.combo_maxlive.addItem(text, userData=value)
        try:
            _cur_max = int(self.settings_manager.current.get("max_live_tabs", 0))
        except (TypeError, ValueError):
            _cur_max = 0
        _idx = self.combo_maxlive.findData(_cur_max)
        self.combo_maxlive.setCurrentIndex(_idx if _idx != -1 else 0)
        maxlive_layout.addWidget(self.combo_maxlive)
        layout.addLayout(maxlive_layout)
        maxlive_hint = QLabel(
            "Bu sayıyı aşınca en eski arka plan sekmeleri anında uyutulur; böylece RAM kullanımı sabit bantta kalır. Video/ses oynatan sekmeler uyutulmaz."
            if lang == "tr" else
            "When exceeded, the oldest background tabs are suspended immediately, keeping RAM within a fixed band. Tabs playing audio/video are not suspended."
        )
        maxlive_hint.setWordWrap(True)
        maxlive_hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(maxlive_hint)

        # --- Şifre kasası ---
        layout.addWidget(QLabel("Şifre Kasası:" if lang == "tr" else "Password Vault:"))
        self.chk_vault_session = QCheckBox(
            "Şifre kasası oturum boyunca açık kalsın" if lang == "tr"
            else "Keep the password vault unlocked for the session")
        self.chk_vault_session.setChecked(bool(settings_manager.current.get("vault_session_unlock", False)))
        layout.addWidget(self.chk_vault_session)
        vault_hint = QLabel(
            "Kapalıyken (önerilen) kasa 10 dakika kullanılmadığında kendini "
            "kilitler ve otomatik doldurma için ana parola tekrar sorulur. "
            "Açıkken kilitleme yoktur ve tarayıcı kapatılınca iner — açık "
            "bilgisayarda başkaları kayıtlı şifrelerinize erişebilir."
            if lang == "tr" else
            "When off (recommended), the vault self-locks after 10 idle "
            "minutes and the master password is asked again for autofill. "
            "When on, there is no auto-lock and it unlocks only when the "
            "browser closes — anyone using the open computer can access "
            "your saved passwords."
        )
        vault_hint.setWordWrap(True)
        vault_hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(vault_hint)

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
            "adresinizi kullanmak isterseniz aşağıya girin. VPN açıkken "
            "WebRTC IP sızıntısı engellenir."
            if lang == "tr" else
            "Leave the fields empty to automatically use the Tor network "
            "('tor' must be installed). Enter your own SOCKS5 proxy address "
            "below if you'd rather use that instead. While the VPN is on, "
            "WebRTC IP leaks are blocked."
        )
        vpn_hint.setWordWrap(True)
        vpn_hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(vpn_hint)

        vpn_honest_note = QLabel(
            "Dürüst not: Bu özellik Tor ağını kullansa da Tor Browser kadar "
            "anonim DEĞİLDİR — tarayıcı parmak izi, WebRTC/DNS'in kenar "
            "durumları ve davranışsal izleme korunur. Yüksek riskli "
            "kullanım için resmi Tor Browser'ı tercih edin."
            if lang == "tr" else
            "Honest note: Although this feature uses the Tor network, it is "
            "NOT as anonymous as Tor Browser — browser fingerprinting, "
            "WebRTC/DNS edge cases and behavioral tracking remain. For "
            "high-risk use, prefer the official Tor Browser."
        )
        vpn_honest_note.setWordWrap(True)
        vpn_honest_note.setStyleSheet("color: #b08040; font-size: 11px;")
        layout.addWidget(vpn_honest_note)

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

    def _refresh_custom_engine_visibility(self):
        custom = self.combo_engine.currentData() == "custom"
        self.custom_engine_input.setVisible(custom)
        self.custom_engine_hint.setVisible(custom)

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
        # Yeniden başlatma gerektiren ayarların ESKİ değerlerini üzerine
        # yazmadan önce yakala.
        old_hw = self.settings_manager.current.get("hardware_acceleration", True)
        old_ram = self.settings_manager.current.get("low_ram_mode", False)
        old_bg = self.settings_manager.current.get("new_tab_background", "")

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
        self.settings_manager.current["tab_suspend_minutes"] = float(self.combo_suspend.currentData())
        self.settings_manager.current["max_live_tabs"] = int(self.combo_maxlive.currentData())
        self.settings_manager.current["search_engine"] = self.combo_engine.currentData()
        self.settings_manager.current["custom_search_url"] = self.custom_engine_input.text().strip()
        self.settings_manager.current["vault_session_unlock"] = self.chk_vault_session.isChecked()

        self.settings_manager.current["hardware_acceleration"] = self.chk_hw_accel.isChecked()
        self.settings_manager.current["low_ram_mode"] = self.chk_low_ram.isChecked()
        self.settings_manager.current["vpn_enabled"] = self.chk_vpn.isChecked()
        self.settings_manager.current["vpn_host"] = self.vpn_host_input.text().strip()
        try:
            new_port = int(self.vpn_port_input.text().strip())
        except ValueError:
            new_port = 9050
        self.settings_manager.current["vpn_port"] = new_port
        self.settings_manager.save()

        # Eski arkaplan görseli, kullanıcı config dizinine kopyalanan bir
        # dosyaysa ve artık kullanılmıyorsa diskte birikmesin.
        if (self._pending_bg_path != old_bg and old_bg
                and os.path.dirname(old_bg) == gem_paths.CONFIG_DIR):
            try:
                os.remove(old_bg)
            except OSError:
                pass

        needs_restart = (
            old_hw != self.chk_hw_accel.isChecked()
            or old_ram != self.chk_low_ram.isChecked()
            # VPN BURADA DEĞİL: sayfa trafiği QtWebEngine'de
            # QNetworkProxy::setApplicationProxy() ile ÇALIŞMA ANINDA
            # yönlendirilir (bkz. _apply_vpn) — yeniden başlatma gerekmez.
        )
        if needs_restart:
            lang = self._current_lang()
            msg = "Ayarın etkili olması için GEM Browser'ı kapatıp yeniden açmanız gerekiyor." if lang == "tr" else "You need to close and reopen GEM Browser to take effect."
            show_modern_info(self, msg, lang=lang)
        self.accept()


class ClearDataDialog(QDialog):
    """Ctrl+Shift+Delete: çerezler / önbellek / geçmiş / indirme listesi
    temizleme penceresi. Zaman aralığı yalnızca GEÇMİŞ için geçerlidir
    (çerez ve önbellek API'si Qt'te tümüyle temizleme yapar)."""

    def __init__(self, settings_manager, mainwin=None):
        super().__init__(mainwin)
        self.settings_manager = settings_manager
        lang = settings_manager.current.get("language", "tr")
        self.lang = lang
        self.setWindowTitle("Tarama Verilerini Temizle" if lang == "tr" else "Clear Browsing Data")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "Temizlenecek verileri seçin:" if lang == "tr" else "Select data to clear:"))

        self.chk_cookies = QCheckBox("Çerezler" if lang == "tr" else "Cookies")
        self.chk_cookies.setChecked(True)
        layout.addWidget(self.chk_cookies)

        self.chk_cache = QCheckBox("Önbellek (web cache)" if lang == "tr" else "Cached files")
        self.chk_cache.setChecked(True)
        layout.addWidget(self.chk_cache)

        self.chk_history = QCheckBox("Gezinme geçmişi" if lang == "tr" else "Browsing history")
        layout.addWidget(self.chk_history)

        self.chk_downloads = QCheckBox("İndirme listesi" if lang == "tr" else "Download list")
        layout.addWidget(self.chk_downloads)

        # gizli pencerede geçmiş/indirme kaydı tutulmaz
        if mainwin is not None and getattr(mainwin, "is_incognito", False):
            self.chk_history.setEnabled(False)
            self.chk_downloads.setEnabled(False)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Geçmiş zaman aralığı:" if lang == "tr" else "History time range:"))
        self.combo_range = QComboBox()
        for text, hours in (
            (("Tüm zamanlar" if lang == "tr" else "All time"), 0),
            (("Son 1 saat" if lang == "tr" else "Last hour"), 1),
            (("Son 24 saat" if lang == "tr" else "Last 24 hours"), 24),
            (("Son 7 gün" if lang == "tr" else "Last 7 days"), 24 * 7),
        ):
            self.combo_range.addItem(text, userData=hours)
        self.combo_range.setCurrentIndex(max(0, self.combo_range.findData(0)))
        time_row.addWidget(self.combo_range)
        time_row.addStretch()
        layout.addLayout(time_row)

        self.chk_on_exit = QCheckBox(
            "Kapanışta çerezleri ve önbelleği temizle" if lang == "tr"
            else "Clear cookies and cache on exit")
        self.chk_on_exit.setChecked(bool(settings_manager.current.get("clear_data_on_exit", False)))
        layout.addWidget(self.chk_on_exit)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Temizle" if lang == "tr" else "Clear")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("İptal" if lang == "tr" else "Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def get_selection(self) -> dict:
        return {
            "cookies": self.chk_cookies.isChecked(),
            "cache": self.chk_cache.isChecked(),
            "history": self.chk_history.isChecked(),
            "downloads": self.chk_downloads.isChecked(),
            "history_hours": self.combo_range.currentData(),
            "on_exit": self.chk_on_exit.isChecked(),
        }
