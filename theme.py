"""
Uygulama genelinde kullanılan "vurgu" (accent) rengini tek bir yerden
hesaplayan yardımcı modül.

Öncesinde bu renk (#3daee9 koyu temada, #0078d7 açık temada) window.py,
permissions.py, modern_popup.py, password_manager.py, new_tab.py gibi
birçok dosyaya tek tek sabit kodlanmıştı. Artık kullanıcı Ayarlar'dan
kendi rengini seçebildiği için hepsi bu modülden okuyor — böylece renk
her yerde tutarlı kalıyor ve "Varsayılana Döndür" tek bir yerde
(BrowserSettings.current["accent_color"] = "") yönetiliyor.
"""

DEFAULT_ACCENT_DARK = "#3daee9"
DEFAULT_ACCENT_LIGHT = "#0078d7"


def default_accent_for_theme(ui_theme: str) -> str:
    return DEFAULT_ACCENT_LIGHT if ui_theme == "light" else DEFAULT_ACCENT_DARK


def get_accent_color(settings_dict: dict) -> str:
    """`settings_dict`, tipik olarak `BrowserSettings().current` sözlüğüdür.
    Kullanıcı özel bir renk seçmediyse (alan boş/None ise) aktif temaya göre
    varsayılana döner — "Varsayılana Döndür" butonu sadece bu alanı
    boşaltmak kadar basit hale gelir."""
    settings_dict = settings_dict or {}
    custom = (settings_dict.get("accent_color") or "").strip()
    if _is_valid_hex_color(custom):
        return custom
    return default_accent_for_theme(settings_dict.get("ui_theme", "dark"))


def is_valid_hex_color(value: str) -> bool:
    if not value or not value.startswith("#") or len(value) != 7:
        return False
    try:
        int(value[1:], 16)
        return True
    except ValueError:
        return False


# Geri uyumluluk / modül içi kullanım için.
_is_valid_hex_color = is_valid_hex_color


def _rgb(hex_color: str):
    hex_color = (hex_color or "").lstrip("#")
    if len(hex_color) != 6:
        return None
    try:
        return int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    except ValueError:
        return None


def _clamp(v: int) -> int:
    return max(0, min(255, v))


def lighten(hex_color: str, amount: float = 0.18) -> str:
    """Hover durumları için basit hex renk açma (amount: 0..1)."""
    rgb = _rgb(hex_color)
    if rgb is None:
        return "#4dbef9"
    r, g, b = rgb
    r = _clamp(int(r + (255 - r) * amount))
    g = _clamp(int(g + (255 - g) * amount))
    b = _clamp(int(b + (255 - b) * amount))
    return f"#{r:02x}{g:02x}{b:02x}"


def to_rgba(hex_color: str, alpha: float) -> str:
    """CSS `rgba(...)` string'i — new_tab.py'deki "glow" efekti gibi
    yerlerde kullanılıyor."""
    rgb = _rgb(hex_color)
    if rgb is None:
        return f"rgba(61, 174, 233, {alpha})"
    r, g, b = rgb
    return f"rgba({r}, {g}, {b}, {alpha})"


def readable_text_color(hex_color: str) -> str:
    """Kullanıcı çok açık bir vurgu rengi seçerse (ör. açık sarı) üzerine
    varsayılan beyaz metin okunmaz hale gelir; parlaklığa göre otomatik
    olarak siyah/beyaz metin seçer."""
    rgb = _rgb(hex_color)
    if rgb is None:
        return "#ffffff"
    r, g, b = rgb
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#1a1a1a" if luminance > 0.6 else "#ffffff"
