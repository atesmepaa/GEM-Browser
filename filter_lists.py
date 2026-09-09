"""
Harici, düzenli güncellenen bir engelleme listesini (StevenBlack/hosts —
AdAway, MVPS, çeşitli EasyList türevleri gibi birçok kaynağı birleştiren bir
"hosts" dosyası) indirip yerelde önbelleğe alır.

Neden "hosts" formatı: AdblockInterceptor tamamen host (domain) bazlı çalışıyor
(URL deseni/CSS seçici gibi EasyList'e özgü kuralları desteklemiyor), bu yüzden
saf domain listesi üreten bir kaynak mimariyle birebir örtüşüyor ve yanlış
ayrıştırma riski taşımıyor.
"""

import json
import os
import ssl
import tempfile
import time
import urllib.error
import urllib.request

import certifi

from gem_browser.paths import config_path, secure_chmod

# StevenBlack/hosts: MIT lisanslı, düzenli güncellenen, ~80.000 domain
# içeren birleşik bir reklam/izleyici/kötü amaçlı yazılım host listesi.
SOURCE_URL = "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts"

CACHE_FILE = config_path("gem_blocklist_domains.txt")
META_FILE = config_path("gem_blocklist_meta.json")

REQUEST_TIMEOUT = 25
UPDATE_MAX_AGE_DAYS = 7


class BlocklistUpdateInProgress(Exception):
    """
    Bir güncelleme zaten sürerken ikinci bir update_blocklist() çağrısı
    yapılırsa fırlatılır. ÖNEMLİ: Bu daha önce yanlışlıkla düz bir bool
    (`= False`) olarak tanımlanmıştı; `except filter_lists.BlocklistUpdateInProgress`
    gibi bir except bloğunda bunu yakalamaya çalışmak Python'da
    "catching classes that do not inherit from BaseException is not allowed"
    TypeError'ına yol açıyordu ve asıl fırlatılan (ör. SSL sertifika) hatasını
    maskeleyip uygulamanın çökmesine sebep oluyordu. Artık gerçek bir
    Exception alt sınıfı.
    """
    pass


# hosts dosyalarında engelleme amacı taşımayan, sistemsel satırlar.
_SKIP_HOSTS = {
    "localhost", "localhost.localdomain", "local", "broadcasthost",
    "ip6-localhost", "ip6-loopback", "ip6-localnet", "ip6-mcastprefix",
    "ip6-allnodes", "ip6-allrouters", "ip6-allhosts", "0.0.0.0",
}


def _parse_hosts_text(text: str) -> set:
    domains = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        ip, domain = parts[0], parts[1].lower()
        if ip not in ("0.0.0.0", "127.0.0.1"):
            continue
        if domain in _SKIP_HOSTS or "." not in domain:
            continue
        domains.add(domain)
    return domains


def _download(url: str = SOURCE_URL) -> str:
    """
    AppImage gibi kendi Python/OpenSSL'ini taşıyan paketleme biçimlerinde
    (özellikle Fedora'da) sistemin CA sertifika deposu bulunamayabiliyor ve
    urllib varsayılan SSL context'iyle "CERTIFICATE_VERIFY_FAILED" hatası
    veriyordu. Bunu önlemek için sertifika doğrulaması, uygulamayla birlikte
    paketlenen `certifi` kütüphanesinin CA paketine göre yapılan bir SSL
    context ile açıkça yapılıyor.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "GEM-Browser-Adblock-Updater/1.0"},
    )
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=ctx) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="ignore")


def update_blocklist(source_url: str = SOURCE_URL) -> int:
    """
    Listeyi indirir, ayrıştırır ve diske yazar. Ağ/parse hatasında istisna
    fırlatır (çağıran taraf — arka plan thread'i — bunu yakalayıp kullanıcıya
    sessizce ya da bir uyarıyla iletir). Başarılı olursa domain sayısını
    döndürür.

    Diske yazım atomik yapılır (önce geçici dosyaya, sonra os.replace ile
    taşınır) — böylece güncelleme yarıda kesilirse (uygulama kapanması,
    ağ kopması vb.) önceki geçerli önbellek bozulmaz.
    """
    text = _download(source_url)
    domains = _parse_hosts_text(text)
    if not domains:
        raise ValueError("İndirilen listeden hiç domain ayrıştırılamadı.")

    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(CACHE_FILE))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(domains)))
        os.replace(tmp_path, CACHE_FILE)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    secure_chmod(CACHE_FILE, 0o600)

    meta = {
        "source": source_url,
        "domain_count": len(domains),
        "updated_at": time.time(),
    }
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    secure_chmod(META_FILE, 0o600)

    return len(domains)


def load_cached_domains():
    """Önbellekteki listeyi bir set olarak döndürür; yoksa None."""
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except OSError:
        return None


def get_meta():
    if not os.path.exists(META_FILE):
        return None
    try:
        with open(META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def needs_update(max_age_days: int = UPDATE_MAX_AGE_DAYS) -> bool:
    meta = get_meta()
    if not meta:
        return True
    age_seconds = time.time() - meta.get("updated_at", 0)
    return age_seconds > max_age_days * 86400
