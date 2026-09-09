from PyQt6.QtCore import QUrl
import urllib.parse

def resolve_url(input_text: str) -> QUrl:
    """
    Kullanıcının girdiği metni analiz edip geçerli bir QUrl nesnesine dönüştürür.
    - Eğer '://' içeriyorsa doğrudan URL olarak kabul eder.
    - Boşluk içermiyor ve '.' barındırıyorsa başına 'https://' ekler.
    - Aksi takdirde DuckDuckGo arama motoru sorgusuna dönüştürür.
    """
    text = input_text.strip()
    if not text:
        return QUrl("")

    if "://" in text:
        return QUrl(text)

    if " " not in text and "." in text:
        return QUrl(f"https://{text}")

    encoded_query = urllib.parse.quote_plus(text)
    return QUrl(f"https://search.brave.com/search?q={encoded_query}")
