"""
Kullanıcıya özel, kalıcı ve izinleri kısıtlı config/veri dizini.

GEM_BROWSER_CONFIG_DIR ortam değişkeni set edilirse config/veri dizini
oraya taşınır. Bu, testlerin ve geliştirme denemelerinin GERÇEK kullanıcı
verisine (~/.config/gem_browser) asla dokunmaması içindir — 2026-09'da
testlerin gerçek dizine karşı koşup kullanıcı favorilerini/ayarlarını
silmesi sonucu bu geçiş eklendi. Testler şöyle çalıştırılmalıdır:
    GEM_BROWSER_CONFIG_DIR=$(mktemp -d) python3 ...
"""

import os

CONFIG_DIR = os.environ.get("GEM_BROWSER_CONFIG_DIR") or os.path.join(
    os.path.expanduser("~"), ".config", "gem_browser"
)


def ensure_config_dir() -> str:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except Exception:
        pass
    return CONFIG_DIR


def secure_chmod(path: str, mode: int = 0o600) -> None:
    try:
        os.chmod(path, mode)
    except Exception:
        pass


def config_path(filename: str) -> str:
    ensure_config_dir()
    return os.path.join(CONFIG_DIR, filename)
