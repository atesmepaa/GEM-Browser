from PyQt6.QtCore import QUrl
import os
import urllib.parse

# Yerleşik arama motorları: anahtar -> (görünen ad, ?q= eklenmiş URL öneki).
# "custom" burada YOK: kullanıcı Ayarlar'dan kendi URL'ini girer (bkz.
# build_search_url).
SEARCH_ENGINES = {
    "brave": ("Brave Search", "https://search.brave.com/search?q="),
    "duckduckgo": ("DuckDuckGo", "https://duckduckgo.com/?q="),
    "startpage": ("Startpage", "https://www.startpage.com/sp/search?query="),
    "google": ("Google", "https://www.google.com/search?q="),
}


def search_engine_label(engine: str, lang: str = "tr") -> str:
    """Motor anahtarının kullanıcıya görünen adı."""
    if engine == "custom":
        return "Özel Arama" if lang == "tr" else "Custom Search"
    return SEARCH_ENGINES.get(engine, SEARCH_ENGINES["brave"])[0]


def build_search_url(query: str, engine: str = "brave", custom_url: str = "") -> str:
    """Verilen sorguyu seçili arama motorunun URL'ine dönüştürür.

    Özel motorda custom_url "{q}" yer tutucusu içerebilir (ör.
    "https://site.arama/?q={q}"); içermiyorsa URL sonuna sorgu eklenir.
    """
    encoded = urllib.parse.quote_plus(query)
    if engine == "custom":
        base = (custom_url or "").strip()
        if not base:
            return SEARCH_ENGINES["brave"][1] + encoded
        if "{q}" in base:
            return base.replace("{q}", encoded)
        return base + encoded
    prefix = SEARCH_ENGINES.get(engine, SEARCH_ENGINES["brave"])[1]
    return prefix + encoded


def resolve_url(input_text: str, engine: str = "brave", custom_url: str = "") -> QUrl:
    """
    Kullanıcının girdiği metni analiz edip geçerli bir QUrl nesnesine dönüştürür.
    - Eğer '://' içeriyorsa doğrudan URL olarak kabul eder (javascript:/
      data:/vbscript: gibi betik şemaları güvenlik nedeniyle reddedilir).
    - Boşluk içermiyor ve '.' barındırıyorsa başına 'https://' ekler.
    - Aksi takdirde seçili arama motorunun sorgusuna dönüştürür.
    """
    text = input_text.strip()
    if not text:
        return QUrl("")

    lowered = text.lower()
    # Güvenlik: adres çubuğundan betik şemalarıyla gezinme, sayfada
    # rastgele JS çalıştırma kapısıdır (self-XSS). Kontrol "://" kontrolünden
    # ÖNCE yapılır — "javascript:alert(1)" biçiminde şema "://" içermez.
    if lowered.startswith(("javascript:", "data:", "vbscript:")):
        return QUrl("")

    if "://" in text:
        return QUrl(text)

    # Yerel dosya yolu? Dosya yöneticisinden/başka uygulamadan
    # "/home/kullanici/belge.pdf" biçiminde gelen yollar ve adres çubuğuna
    # yazılan mevcut yollar (veya ~/ ile başlayanlar) file:// olarak
    # açılır — eskiden bu girdiler "https:///home/..." diye bozuk bir
    # https adresine dönüşüyordu ve hiçbir şey açılmıyordu. Yalnızca
    # GERÇEKTEN var olan yollar sayfa sayılır; aksi halde "example.com"
    # gibi bir adres yanlışlıkla yol sanılamaz.
    if text.startswith("/") or text.startswith("~"):
        expanded = os.path.expanduser(text)
        if os.path.exists(expanded):
            return QUrl.fromLocalFile(os.path.abspath(expanded))

    if " " not in text and "." in text:
        return QUrl(f"https://{text}")

    return QUrl(build_search_url(text, engine, custom_url))
