"""
Bir önceki oturumda açık kalan sekmelerin (normal/gizli olmayan pencere
için) kaydedilip bir sonraki açılışta kullanıcıya "geri yükle" olarak
teklif edilmesini sağlayan küçük bir modül.

Akış:
- MainWindow.closeEvent -> uygulamanın SON penceresi kapanıyorsa (gizli
  pencereler hiç dahil edilmez) o pencerede o an açık olan, anlamlı
  (boş "yeni sekme" sayfası olmayan) sekmelerin URL'leri `save_session()`
  ile diske yazılır. Açık anlamlı sekme yoksa dosya temizlenir.
- Bir sonraki açılışta window.py, `load_session()` ile bu listeyi okur;
  liste doluysa kullanıcıya modern bir onay kartı gösterilir. "Evet"
  denirse sekmeler geri yüklenir, "Hayır" denirse (ya da liste boşsa)
  hiçbir şey yapılmaz ve normal boş sekmeyle devam edilir. Kullanıcı ne
  cevap verirse versin, dosya hemen tüketilir (silinir) — böylece aynı
  oturum içinde "Yeni Pencere" ile açılan ek pencerelerde tekrar tekrar
  sorulmaz ve bir sonraki kapanışta eski kayıt karışmaz.
"""

import json
import os

from gem_browser.paths import config_path, secure_chmod

SESSION_FILE = config_path("gem_session.json")


def save_session(urls: list) -> None:
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump({"tabs": urls}, f, indent=2, ensure_ascii=False)
        secure_chmod(SESSION_FILE)
    except Exception:
        pass


def load_session() -> list:
    if not os.path.exists(SESSION_FILE):
        return []
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        tabs = data.get("tabs", []) if isinstance(data, dict) else []
        return [t for t in tabs if isinstance(t, str) and t]
    except Exception:
        return []


def clear_session() -> None:
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
    except Exception:
        pass
