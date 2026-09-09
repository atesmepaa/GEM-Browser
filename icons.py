"""
Toolbar ve ana menü için, sistem temasından (ikon fontu vb.) bağımsız,
her zaman aynı görünen; ince çizgili (stroke-based), tek renkli SVG ikonlar.

Neden bu yaklaşım: metin karakterleriyle (←, →, ↻, ⋮) çizilen "ikonlar"
platforma/fonta göre kalınlık ve hizalama farkı gösterir, yüksek DPI
ekranlarda pikselli görünebilir. Burada üretilen ikonlar vektörel
(QSvgRenderer ile render edilir) olduğu için her boyutta net kalır ve
rengi (açık/koyu tema vurgu rengiyle birebir eşleşecek şekilde) kod
tarafında ayarlanabilir.

Her ikon normal ve "disabled" (soluk) olmak üzere iki pixmap ile QIcon'a
eklenir; Qt bir QAction/QToolButton devre dışı bırakıldığında otomatik
olarak disabled pixmap'i kullanır (ör. geri/ileri gidilecek geçmiş yokken).
"""

import os

from PyQt6.QtCore import Qt, QByteArray, QSize
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtSvg import QSvgRenderer

_STROKE_HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
)
_FILL_HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="currentColor" stroke="none">'
)
_TAIL = "</svg>"

_ICONS = {
    "back": _STROKE_HEAD + '<polyline points="15 5 8 12 15 19"/>' + _TAIL,
    "forward": _STROKE_HEAD + '<polyline points="9 5 16 12 9 19"/>' + _TAIL,
    "reload": _STROKE_HEAD + (
        '<path d="M4 12a8 8 0 0 1 14.5-4.5"/>'
        '<polyline points="19 3 19 8 14 8"/>'
        '<path d="M20 12a8 8 0 0 1-14.5 4.5"/>'
        '<polyline points="5 21 5 16 10 16"/>'
    ) + _TAIL,
    "dots": _FILL_HEAD + (
        '<circle cx="12" cy="5" r="2"/>'
        '<circle cx="12" cy="12" r="2"/>'
        '<circle cx="12" cy="19" r="2"/>'
    ) + _TAIL,
    "plus": _STROKE_HEAD + (
        '<line x1="12" y1="5" x2="12" y2="19"/>'
        '<line x1="5" y1="12" x2="19" y2="12"/>'
    ) + _TAIL,
    "undo": _STROKE_HEAD + (
        '<polyline points="9 14 4 9 9 4"/>'
        '<path d="M4 9h10a6 6 0 0 1 0 12h-3"/>'
    ) + _TAIL,
    "window": _STROKE_HEAD + (
        '<rect x="3" y="4" width="18" height="16" rx="2"/>'
        '<line x1="3" y1="9" x2="21" y2="9"/>'
    ) + _TAIL,
    "incognito": _STROKE_HEAD + (
        '<circle cx="7" cy="13" r="3"/>'
        '<circle cx="17" cy="13" r="3"/>'
        '<line x1="10" y1="13" x2="14" y2="13"/>'
        '<path d="M4 13l-1.5-4"/>'
        '<path d="M20 13l1.5-4"/>'
        '<path d="M8 8h8"/>'
    ) + _TAIL,
    "download": _STROKE_HEAD + (
        '<path d="M12 3v12"/>'
        '<polyline points="7 10 12 15 17 10"/>'
        '<line x1="5" y1="21" x2="19" y2="21"/>'
    ) + _TAIL,
    "history": _STROKE_HEAD + (
        '<circle cx="12" cy="12" r="9"/>'
        '<polyline points="12 7 12 12 16 14"/>'
    ) + _TAIL,
    "lock": _STROKE_HEAD + (
        '<rect x="5" y="11" width="14" height="9" rx="2"/>'
        '<path d="M8 11V7a4 4 0 0 1 8 0v4"/>'
    ) + _TAIL,
    "shield": _STROKE_HEAD + (
        '<path d="M12 3l7 3v6c0 5-3.2 8.5-7 9.5-3.8-1-7-4.5-7-9.5V6l7-3z"/>'
    ) + _TAIL,
    "search": _STROKE_HEAD + (
        '<circle cx="10.5" cy="10.5" r="6.5"/>'
        '<line x1="20.5" y1="20.5" x2="15.3" y2="15.3"/>'
    ) + _TAIL,
    "star": _FILL_HEAD + (
        '<polygon points="12 2.5 14.9 8.6 21.7 9.4 16.8 14.1 18 20.8 '
        '12 17.5 6 20.8 7.2 14.1 2.3 9.4 9.1 8.6"/>'
    ) + _TAIL,
    "zoom-in": _STROKE_HEAD + (
        '<circle cx="11" cy="11" r="8"/>'
        '<line x1="21" y1="21" x2="16.65" y2="16.65"/>'
        '<line x1="11" y1="8" x2="11" y2="14"/>'
        '<line x1="8" y1="11" x2="14" y2="11"/>'
    ) + _TAIL,
    "zoom-out": _STROKE_HEAD + (
        '<circle cx="11" cy="11" r="8"/>'
        '<line x1="21" y1="21" x2="16.65" y2="16.65"/>'
        '<line x1="8" y1="11" x2="14" y2="11"/>'
    ) + _TAIL,
    "zoom-reset": _STROKE_HEAD + (
        '<rect x="3" y="3" width="18" height="18" rx="2"/>'
        '<text x="12" y="16" font-size="10" text-anchor="middle" font-family="sans-serif" fill="currentColor" stroke="none">1:1</text>'
    ) + _TAIL,
    "settings": _STROKE_HEAD + (
        '<circle cx="12" cy="12" r="3.2"/>'
        '<line x1="12" y1="2.5" x2="12" y2="5.5"/>'
        '<line x1="12" y1="18.5" x2="12" y2="21.5"/>'
        '<line x1="2.5" y1="12" x2="5.5" y2="12"/>'
        '<line x1="18.5" y1="12" x2="21.5" y2="12"/>'
        '<line x1="5.1" y1="5.1" x2="7.2" y2="7.2"/>'
        '<line x1="16.8" y1="16.8" x2="18.9" y2="18.9"/>'
        '<line x1="5.1" y1="18.9" x2="7.2" y2="16.8"/>'
        '<line x1="16.8" y1="7.2" x2="18.9" y2="5.1"/>'
    ) + _TAIL,
    "pin": _STROKE_HEAD + (
        '<path d="M12 17v5"/>'
        '<path d="M8 3h8l-1 6 3 3v2H6v-2l3-3-1-6z"/>'
    ) + _TAIL,
    "sidebar": _STROKE_HEAD + (
        '<rect x="3" y="4" width="18" height="16" rx="2"/>'
        '<line x1="9" y1="4" x2="9" y2="20"/>'
    ) + _TAIL,
    "pip": _STROKE_HEAD + (
        '<rect x="3" y="4" width="18" height="16" rx="2"/>'
        '<rect x="12" y="12" width="7" height="5" rx="1" fill="currentColor" stroke="none"/>'
    ) + _TAIL,
    "moon": _FILL_HEAD + (
        '<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/>'
    ) + _TAIL,
    "globe": _STROKE_HEAD + (
        '<circle cx="12" cy="12" r="10"/>'
        '<line x1="2" y1="12" x2="22" y2="12"/>'
        '<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>'
    ) + _TAIL,
}

_pixmap_cache = {}


def _render_pixmap(name: str, size: int, color: str) -> QPixmap:
    cache_key = (name, size, color)
    cached = _pixmap_cache.get(cache_key)
    if cached is not None:
        return cached

    svg = _ICONS[name].replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))

    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    _pixmap_cache[cache_key] = pixmap
    return pixmap


def get_icon(name: str, color: str, disabled_color: str = None, size: int = 20) -> QIcon:
    """
    `name`: yukarıdaki _ICONS anahtarlarından biri (ör. "back", "settings").
    `color`: normal (etkin) durumdaki çizgi/dolgu rengi, tema vurgu rengiyle
    eşleşmesi için çağıran taraf (window.py) mevcut temaya göre seçer.
    `disabled_color`: verilirse, QAction/QToolButton devre dışı bırakıldığında
    Qt'nin otomatik kullanacağı soluk pixmap için kullanılır (ör. geri/ileri
    gidilecek geçmiş yokken).
    """
    icon = QIcon()
    icon.addPixmap(_render_pixmap(name, size, color), QIcon.Mode.Normal)
    if disabled_color:
        icon.addPixmap(_render_pixmap(name, size, disabled_color), QIcon.Mode.Disabled)
    return icon


# ---------------------------------------------------------------------------
# Marka logosu (logo.png) — kullanıcının Ayarlar'dan seçtiği vurgu rengine
# göre yeniden boyanması.
#
# logo.png, saydam arkaplanlı tek-renkli (siluet) bir işaret olarak
# tasarlandı. Bu yüzden her yerde AYNI dosyayı kullanıp yalnızca dolu
# (saydam olmayan) piksellerini QPainter'ın SourceIn birleşim modüyle
# vurgu rengine boyuyoruz — şeklin kendisi ve saydamlığı hiç değişmez,
# sadece rengi değişir. Kullanıcı Ayarlar'dan farklı bir renk seçtiğinde
# pencere ikonu, sekme ikonu ve yeni sekme sayfasındaki logo hepsi aynı
# anda o renge döner.
# ---------------------------------------------------------------------------

_LOGO_ICON_SIZES = (16, 20, 24, 32, 48, 64, 128, 256)
_tinted_logo_pixmap_cache = {}


def _logo_source_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")


def tinted_logo_pixmap(color: str, size: int = None) -> QPixmap:
    """`logo.png`'nin, saydamlığı korunmuş, tüm dolu pikselleri `color` ile
    boyanmış halini döndürür. `size` verilirse önce o boyuta (oranı koruyarak,
    yumuşak ölçekleme ile) küçültülür. Sonuçlar (renk, boyut) başına
    önbelleklenir. Kaynak logo dosyası yoksa boş bir QPixmap döner."""
    cache_key = (color, size)
    cached = _tinted_logo_pixmap_cache.get(cache_key)
    if cached is not None:
        return cached

    source_path = _logo_source_path()
    if not os.path.exists(source_path):
        return QPixmap()

    source = QPixmap(source_path)
    if source.isNull():
        return QPixmap()

    if size:
        source = source.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    tinted = QPixmap(source.size())
    tinted.fill(Qt.GlobalColor.transparent)

    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, source)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor(color))
    painter.end()

    _tinted_logo_pixmap_cache[cache_key] = tinted
    return tinted


def tinted_logo_icon(color: str, sizes=_LOGO_ICON_SIZES) -> QIcon:
    """Pencere/sekme ikonu olarak kullanılmak üzere, verilen renge boyanmış
    logonun birden çok çözünürlükte QIcon'unu döndürür (bkz. tinted_logo_pixmap)."""
    icon = QIcon()
    for size in sizes:
        pixmap = tinted_logo_pixmap(color, size)
        if not pixmap.isNull():
            icon.addPixmap(pixmap)
    return icon


def tinted_logo_file(color: str, size: int = 128) -> str:
    """Boyanmış logoyu PNG olarak diske yazıp dosya yolunu döndürür — HTML
    <img> etiketi (file:// URL) gibi bir dosya yolu gerektiren yerler için
    (bkz. gem_browser/new_tab.py). Aynı renk/boyut için tekrar tekrar diske
    yazmamak adına gem_browser config dizininde önbelleklenir. Kaynak logo
    yoksa/boşsa "" döner."""
    from gem_browser.paths import config_path

    pixmap = tinted_logo_pixmap(color, size)
    if pixmap.isNull():
        return ""

    safe_color = (color or "").lstrip("#").lower() or "default"
    file_path = config_path(f"gem_logo_tinted_{safe_color}_{size}.png")
    if not os.path.exists(file_path):
        pixmap.save(file_path, "PNG")
    return file_path
