"""
Adres çubuğu (url_bar) için diğer tarayıcılardaki gibi yazarken açılan
öneri listesi.

Üç kaynaktan öneri toplanır:
  1) Favoriler (bookmarks.json)               -> isim/URL alt-dize eşleşmesi.
  2) Bu oturumun gezinme geçmişi (session_history) -> URL alt-dize eşleşmesi.
  3) Arama motoru canlı önerileri              -> Brave Search'ün herkese
     açık, anahtar (API key) gerektirmeyen "autocomplete" uç noktası
     (search.brave.com/api/suggest — Brave'in kendi OpenSearch tanımında
     yayınladığı, diğer tarayıcıların da Brave'i arama motoru olarak
     eklerken kullandığı aynı uç nokta). Gerçek arama sorguları da zaten
     Brave Search'e gittiği için (bkz. router.py) öneriler artık aynı
     motordan geliyor — ayrı bir üçüncü tarafa (eskiden DuckDuckGo)
     sorgu sızdırılmıyor.

ÖNEMLİ (gizlilik): 3. madde, kullanıcı yazdıkça Brave Search'e SADECE o an
yazılan metni içeren bir istek gönderir (başka hiçbir kişisel veri
gönderilmez). Yine de bir üçüncü tarafa ağ isteği olduğu için
`settings.py`'deki "search_suggestions" anahtarıyla kapatılabilir.

Ağ isteği her tuş vuruşunda değil, kısa bir "debounce" (150ms) süresinden
sonra ve varsa önceki bitmemiş istek iptal edilerek yapılır.
"""

import html
import json

from PyQt6.QtCore import Qt, QObject, QTimer, QUrl, QSize, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QGraphicsDropShadowEffect, QFrame
)
from PyQt6.QtGui import QColor

from gem_browser import icons as gem_icons

MAX_LOCAL_SUGGESTIONS = 4
MAX_REMOTE_SUGGESTIONS = 4
DEBOUNCE_MS = 150
# Brave Search'ün herkese açık, anahtarsız öneri uç noktası. Firefox/Opera/
# Vivaldi gibi tarayıcılar da Brave'i arama motoru olarak eklerken bu aynı
# "suggest_url"ü kullanıyor (search.brave.com'un kendi OpenSearch tanımı).
SUGGEST_ENDPOINT = "https://search.brave.com/api/suggest?q="


# ---------------------------------------------------------------- yerel ----

def gather_local_suggestions(text: str, bookmarks: list, history: list) -> list:
    """
    Favoriler ve oturum geçmişinden basit alt-dize eşleşmesiyle öneri
    toplar. Dönen her öge: {"kind": "bookmark"|"history", "title": str,
    "subtitle": str, "url": str}
    """
    text_l = text.strip().lower()
    if not text_l:
        return []

    results = []
    seen_urls = set()

    for bm in bookmarks:
        name, url = bm.get("name", ""), bm.get("url", "")
        if text_l in name.lower() or text_l in url.lower():
            if url not in seen_urls:
                results.append({"kind": "bookmark", "title": name or url, "subtitle": url, "url": url})
                seen_urls.add(url)
        if len(results) >= MAX_LOCAL_SUGGESTIONS:
            return results

    # En son ziyaret edilenler önce gösterilsin diye ters sırada geziliyor.
    for url in reversed(history):
        if url in seen_urls:
            continue
        if text_l in url.lower():
            results.append({"kind": "history", "title": url, "subtitle": "Geçmiş", "url": url})
            seen_urls.add(url)
        if len(results) >= MAX_LOCAL_SUGGESTIONS:
            break

    return results


# --------------------------------------------------------------- uzak -----

class RemoteSuggester(QObject):
    """
    DuckDuckGo autocomplete uç noktasından öneri çeker. Her yeni `request()`
    çağrısı önceki debounce/isteği iptal eder — böylece yalnızca en son
    yazılan metnin sonucu işlenir, geç gelen eski cevaplar güncel metnin
    üzerine yazmaz.
    """

    suggestions_ready = pyqtSignal(str, list)  # (query, [str, ...])

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        self._reply = None
        self._pending_query = ""
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._fire_request)

    def request(self, query: str):
        self._pending_query = query
        self._debounce.start()

    def cancel(self):
        self._debounce.stop()
        if self._reply is not None:
            self._reply.abort()
            self._reply = None

    def _fire_request(self):
        query = self._pending_query
        if not query.strip():
            return
        if self._reply is not None:
            self._reply.abort()
            self._reply = None

        encoded = QUrl.toPercentEncoding(query).data().decode("ascii")
        req = QNetworkRequest(QUrl(SUGGEST_ENDPOINT + encoded))
        # Brave'in öneri uç noktası, tarayıcı olmayan/UA'sız isteklere karşı
        # daha seçici davranabiliyor; gerçek bir tarayıcıdan geldiğini
        # belirtmek için standart bir User-Agent ve Referer ekleniyor.
        req.setRawHeader(b"User-Agent", b"Mozilla/5.0 (X11; Linux x86_64) GEM-Browser/1.0")
        req.setRawHeader(b"Referer", b"https://search.brave.com/")
        req.setRawHeader(b"Accept", b"application/json")
        self._reply = self._manager.get(req)
        self._reply.finished.connect(lambda q=query: self._on_finished(q))

    def _on_finished(self, query: str):
        reply = self._reply
        self._reply = None
        if reply is None:
            return
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                raw = bytes(reply.readAll())
                data = json.loads(raw.decode("utf-8", errors="ignore"))
                # Brave'in "suggest" uç noktası standart OpenSearch
                # autocomplete biçimini döndürür: ["sorgu", ["öneri1", ...]]
                items = data[1] if isinstance(data, list) and len(data) > 1 else []
                items = [s for s in items if isinstance(s, str)]
                self.suggestions_ready.emit(query, items[:MAX_REMOTE_SUGGESTIONS])
        except Exception:
            pass
        finally:
            reply.deleteLater()


# --------------------------------------------------------------- arayüz ---

_DARK = {
    "bg": "#242424", "border": "rgba(255, 255, 255, 0.08)", "text": "#ffffff",
    "muted": "#909090", "hover": "rgba(255, 255, 255, 0.06)",
    "sel": "rgba(61, 174, 233, 0.20)", "accent": "#3daee9",
}
_LIGHT = {
    "bg": "#ffffff", "border": "rgba(0, 0, 0, 0.08)", "text": "#1a1a1a",
    "muted": "#707070", "hover": "rgba(0, 0, 0, 0.05)",
    "sel": "rgba(0, 120, 215, 0.14)", "accent": "#0078d7",
}

# Satır simgeleri artık emoji değil, toolbar/menüde de kullanılan aynı ince
# çizgili SVG ikon seti (bkz. icons.py) — böylece adres çubuğu önerileri de
# geri kalan arayüzle (renk/kalınlık/DPI netliği açısından) birebir tutarlı
# görünür. "search" (öneriler ve doğrudan arama satırı) vurgu rengiyle,
# "bookmark" (favori) da vurgu rengiyle, "history" (geçmiş) ise soluk/muted
# renkle çizilir.
_KIND_ICON_NAME = {"bookmark": "star", "history": "history", "search": "search"}
_KIND_ICON_ACCENTED = {"bookmark": True, "history": False, "search": False}


def _highlight_match(text: str, query: str) -> str:
    """
    Google/Chrome tarzı: satırdaki metin içinde, kullanıcının o an yazdığı
    sorguyla eşleşen kısım KALIN, geri kalanı normal ağırlıkta gösterilir.
    Eşleşme bulunamazsa tüm metin normal ağırlıkta (kaçışlanmış) döner.
    Basit bir alt-dize araması (büyük/küçük harf duyarsız) yeterli; öneri
    motorları zaten sorguyu bir yerde içeren metinler döndürüyor.
    """
    query = (query or "").strip()
    if not query:
        return html.escape(text)

    idx = text.lower().find(query.lower())
    if idx < 0:
        return html.escape(text)

    before = html.escape(text[:idx])
    match = html.escape(text[idx:idx + len(query)])
    after = html.escape(text[idx + len(query):])
    return f"{before}<b>{match}</b>{after}"


def _elide(text: str, font, max_width: int) -> str:
    """Etiket genişliğini asla aşmayan, sonu "…" ile kesilen düz metin.
    Kalınlaştırma (_highlight_match) bu kırpılmış metin ÜZERİNDE çalışır,
    böylece hem taşma/kesilme olmaz hem de <b> etiketleri bozulmaz."""
    if max_width <= 0:
        return text
    from PyQt6.QtGui import QFontMetrics
    fm = QFontMetrics(font)
    return fm.elidedText(text, Qt.TextElideMode.ElideRight, max_width)


class SuggestionPopup(QWidget):
    """
    Adres çubuğunun hemen altına açılan, tıklanabilir/ok tuşlarıyla
    gezilebilir öneri listesi. Odağı (focus) ASLA url_bar'dan çalmaz —
    kullanıcı yazmaya devam edebilirken liste güncellenir.
    """

    ICON_W = 18
    ROW_SPACING = 10
    ROW_MARGIN_H = 10

    item_chosen = pyqtSignal(str, str)  # (kind, value)

    def __init__(self, parent, theme: str = "dark"):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._colors = _LIGHT if theme == "light" else _DARK
        self._entries = []  # [(kind, value)]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame(self)
        card.setObjectName("suggestCard")
        outer.addWidget(card)
        card.setStyleSheet(f"""
            QFrame#suggestCard {{
                background-color: {self._colors['bg']};
                border: 1px solid {self._colors['border']};
                border-radius: 14px;
            }}
            QListWidget {{ background: transparent; border: none; outline: none; padding: 4px 0px; }}
            QListWidget::item {{ border: none; margin: 0px; padding: 0px; }}
            QListWidget::item:hover {{ background-color: {self._colors['hover']}; }}
            QListWidget::item:selected {{ background-color: {self._colors['sel']}; }}
        """)
        # Chrome'daki gibi satırlar birbirine yapışık (aralarında boşluk
        # yok); tekil yuvarlatma/kenar boşluğu yalnızca dış karttan gelir.

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 4, 0, 4)

        self.list_widget = QListWidget(card)
        self.list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list_widget.setMouseTracking(True)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        card_layout.addWidget(self.list_widget)

        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(28)
        shadow.setXOffset(0)
        shadow.setYOffset(6)
        shadow.setColor(QColor(0, 0, 0, 130))
        card.setGraphicsEffect(shadow)

    def _kind_icon_pixmap(self, kind: str, primary: bool) -> "QPixmap":
        colors = self._colors
        name = _KIND_ICON_NAME.get(kind, "search")
        accented = primary or _KIND_ICON_ACCENTED.get(kind, False)
        color = colors["accent"] if accented else colors["muted"]
        return gem_icons.get_icon(name, color, size=16).pixmap(QSize(16, 16))

    def set_entries(self, entries: list, query: str = ""):
        """entries: [{"kind":..., "title":..., "subtitle":..., "value":...,
        "primary": bool (opsiyonel)}]. `query`, o an adres çubuğunda yazan
        metindir; satırlardaki eşleşen kısmı KALIN göstermek için kullanılır
        (bkz. _highlight_match) — Google/Chrome'daki öneri listesiyle aynı
        okunabilirlik mantığı.

        ÖNEMLİ: bu çağrıdan ÖNCE `position_below()` ile popup'ın gerçek
        genişliği ayarlanmış olmalı (bkz. window.py._show_suggestions).
        Aksi halde satırlar henüz doğru genişlik bilinmeden kurulur ve metin
        yanlış (dar) bir alana sıkışıp kırpılır/üst üste biner.
        """
        self.list_widget.clear()
        self._entries = []
        colors = self._colors

        # Etiketlerin taşmaması için kullanılabilir metin genişliği: popup
        # genişliği - kart kenar boşlukları - satır kenar boşlukları - ikon
        # - ikon/metin arası boşluk - küçük bir güvenlik payı.
        popup_width = self.width() if self.width() > 40 else 380
        avail_text_w = max(
            popup_width - 8 - (2 * self.ROW_MARGIN_H) - self.ICON_W - self.ROW_SPACING - 12,
            60,
        )

        title_font = self.font()
        title_font.setPointSize(max(title_font.pointSize(), 10))
        sub_font = self.font()

        for e in entries:
            is_primary = bool(e.get("primary"))

            item = QListWidgetItem(self.list_widget)
            row = QWidget()
            row.setObjectName("primaryRow" if is_primary else "suggestRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(self.ROW_MARGIN_H, 7, self.ROW_MARGIN_H, 7)
            row_layout.setSpacing(self.ROW_SPACING)
            if is_primary:
                # Diğer satırlarla aynı yapışık/köşesiz düzende kalır, sadece
                # arka plan rengiyle (hover beklemeden) hafifçe öne çıkar —
                # Google'ın "sorguyu ara" satırı gibi ama Chrome'daki gibi
                # kesintisiz/boşluksuz.
                row.setStyleSheet(
                    f"QWidget#primaryRow {{ background-color: {colors['sel']}; }}"
                )

            icon_lbl = QLabel()
            icon_lbl.setPixmap(self._kind_icon_pixmap(e["kind"], is_primary))
            icon_lbl.setFixedSize(self.ICON_W, 18)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setStyleSheet("background: transparent;")
            row_layout.addWidget(icon_lbl)

            text_col = QVBoxLayout()
            text_col.setSpacing(0)

            elided_title = _elide(e["title"], title_font, avail_text_w)
            title_html = _highlight_match(elided_title, query)
            title_lbl = QLabel(title_html)
            title_lbl.setTextFormat(Qt.TextFormat.RichText)
            title_lbl.setWordWrap(False)
            title_lbl.setStyleSheet(f"color: {colors['text']}; font-size: 13px; background: transparent;")
            title_lbl.setContentsMargins(0, 0, 0, 0)
            text_col.addWidget(title_lbl)

            # "search" türü satırlarda (öneriler ve "ara" satırı) Google'daki
            # gibi tek satır yeterli; favoriler/geçmişte hedefi (URL/etiket)
            # göstermek için ikinci, soluk bir alt satır kalır.
            if e.get("subtitle") and e["kind"] != "search":
                elided_sub = _elide(e["subtitle"], sub_font, avail_text_w)
                sub_lbl = QLabel(elided_sub)
                sub_lbl.setWordWrap(False)
                sub_lbl.setStyleSheet(f"color: {colors['muted']}; font-size: 11px; background: transparent;")
                text_col.addWidget(sub_lbl)
            row_layout.addLayout(text_col, 1)

            row_h = row.sizeHint().height()
            item.setSizeHint(QSize(10, row_h))
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, row)
            self._entries.append((e["kind"], e["value"]))

        self.list_widget.setCurrentRow(-1)
        row_h = self.list_widget.sizeHintForRow(0) if self.list_widget.count() else 0
        total_h = min(row_h * self.list_widget.count() + 15, 360)
        self.setFixedHeight(max(total_h, 1))
        self.adjustSize()

    def _on_item_clicked(self, item):
        idx = self.list_widget.row(item)
        if 0 <= idx < len(self._entries):
            kind, value = self._entries[idx]
            self.item_chosen.emit(kind, value)

    def move_selection(self, delta: int):
        count = self.list_widget.count()
        if count == 0:
            return
        row = self.list_widget.currentRow()
        row = (row + delta) if row >= 0 else (0 if delta > 0 else count - 1)
        row = max(0, min(count - 1, row))
        self.list_widget.setCurrentRow(row)

    def current_entry(self):
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def position_below(self, anchor_widget):
        bottom_left = anchor_widget.mapToGlobal(anchor_widget.rect().bottomLeft())
        self.setFixedWidth(anchor_widget.width())
        self.move(bottom_left.x(), bottom_left.y() + 6)
