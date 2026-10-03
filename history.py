"""
Kalıcı gezinme geçmişi.

bookmarks.json / gem_downloads.json ile aynı desen: basit bir JSON dosyası,
gem_browser config dizininde saklanıyor. Eskiden `session_history` sadece
bellekte tutuluyordu ve uygulama kapanınca kayboluyordu; artık disk
üzerinde kalıcı, tarih/başlıkla birlikte tutuluyor.

Gizlilik notu: gizli (incognito) pencerelerden hiçbir zaman buraya yazım
yapılmaz — bu çağıran taraf (window.py) tarafından garanti edilir.
"""

import json
import os
import time

from gem_browser.paths import config_path, secure_chmod

HISTORY_FILE = config_path("gem_history.json")

# Sınırsız büyümesin diye üst sınır. 10.000 girdi (url+başlık+zaman damgası)
# bile birkaç MB'ı geçmez, günlük kullanım için fazlasıyla yeterli.
MAX_HISTORY_ENTRIES = 10_000


def load_history() -> list:
    """Diskteki geçmişi, en eskiden en yeniye sıralı liste olarak döndürür."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    # Bozuk/elle düzenlenmiş dosyada add_entry'in
                    # entries[-1].get(...) çağrısı AttributeError ile
                    # çökmesin; yalnızca geçerli girdileri kabul et.
                    return [e for e in data
                            if isinstance(e, dict) and isinstance(e.get("url"), str) and e["url"]]
        except Exception:
            pass
    return []


def save_history(entries: list) -> None:
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        secure_chmod(HISTORY_FILE)
    except Exception:
        pass


def add_entry(entries: list, url: str, title: str = "", save: bool = True) -> list:
    """
    Verilen listeye (bellekteki güncel geçmiş) yeni bir ziyareti ekler;
    save=True ise diske yazar. Hızlı gezinmede her yüklemede tüm geçmiş
    dosyasını yazmamak için arayüz save=False geçirip gecikmeli olarak
    save_history() çağırabilir (bkz. window.py _flush_history).
    Aynı sayfada art arda gelen güncellemeler (ör. sekme başlığı sayfa
    yüklendikten sonra değişirse) yeni bir satır açmak yerine son satırı
    günceller. Güncellenmiş listeyi döndürür.
    """
    if entries and entries[-1].get("url") == url:
        entries[-1]["title"] = title or entries[-1].get("title", "")
        entries[-1]["timestamp"] = time.time()
    else:
        entries.append({"url": url, "title": title or url, "timestamp": time.time()})

    if len(entries) > MAX_HISTORY_ENTRIES:
        entries = entries[-MAX_HISTORY_ENTRIES:]

    if save:
        save_history(entries)
    return entries


def clear_history() -> list:
    save_history([])
    return []
