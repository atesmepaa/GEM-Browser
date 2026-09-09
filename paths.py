"""
Kullanıcıya özel, kalıcı ve izinleri kısıtlı config/veri dizini.
"""

import os

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "gem_browser")


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
