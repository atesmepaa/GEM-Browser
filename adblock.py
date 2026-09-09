from urllib.parse import urlparse
from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInterceptor


class AdblockInterceptor(QWebEngineUrlRequestInterceptor):
    """
    Domain tabanlı reklam/izleyici engelleyici.

    Asıl kural kaynağı `filter_lists.py` üzerinden indirilip önbelleğe
    alınan harici bir liste (StevenBlack/hosts — onbinlerce domain).
    Aşağıdaki FALLBACK_DOMAINS ise yalnızca ilk açılışta/internet yokken,
    dış liste henüz hiç indirilememişse devreye giren küçük bir güvenlik
    ağıdır; `set_domains()` çağrıldığında (indirilen liste yüklendiğinde)
    onunla birleştirilir.

    Performans notu: engelleme kümesi on binlerce girdi içerebileceğinden,
    her istekte tüm kümede "endswith" ile gezmek (eski yaklaşım) O(n) olup
    her ağ isteğinde gözle görülür bir gecikmeye yol açar. Bunun yerine
    istek host'unun üst domain'leri tek tek (O(derinlik), tipik olarak 2-4
    adım) kümede aranır — bu O(1) küme üyelik testleriyle çalışır.
    """

    FALLBACK_DOMAINS = {
        "doubleclick.net", "googlesyndication.com", "googleadservices.com",
        "google-analytics.com", "googletagmanager.com", "adnxs.com",
        "adsrvr.org", "adroll.com", "criteo.com", "criteo.net",
        "outbrain.com", "taboola.com", "pubmatic.com", "rubiconproject.com",
        "openx.net", "smartadserver.com", "media.net", "advertising.com",
        "amazon-adsystem.com", "scorecardresearch.com", "quantserve.com",
        "hotjar.com", "mixpanel.com", "segment.io", "amplitude.com",
        "connect.facebook.net", "adsafeprotected.com", "doubleverify.com",
        "moatads.com", "adjust.com", "appsflyer.com", "branch.io",
        "taboola.com", "yieldmo.com", "casalemedia.com", "sovrn.com",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.block_domains = set(self.FALLBACK_DOMAINS)

    def set_domains(self, domains) -> None:
        """
        Aktif engelleme kümesini değiştirir. `filter_lists.update_blocklist()`
        ile indirilen büyük listeyle, güvenlik ağı olarak her zaman
        FALLBACK_DOMAINS birleştirilir.
        """
        self.block_domains = set(domains) | self.FALLBACK_DOMAINS

    @staticmethod
    def _extract_host(url: str) -> str:
        try:
            host = urlparse(url).netloc.lower()
            return host.split(":")[0] if host else ""
        except Exception:
            return ""

    def _is_blocked(self, host: str) -> bool:
        block_domains = self.block_domains
        parts = host.split(".")
        # "a.b.tracker.com" -> sırasıyla "a.b.tracker.com", "b.tracker.com",
        # "tracker.com", "com" denenir; her adım O(1) küme üyelik testi.
        for i in range(len(parts) - 1):
            candidate = ".".join(parts[i:])
            if candidate in block_domains:
                return True
        return False

    def interceptRequest(self, info):
        host = self._extract_host(info.requestUrl().toString())
        if not host:
            return
        if self._is_blocked(host):
            info.block(True)
