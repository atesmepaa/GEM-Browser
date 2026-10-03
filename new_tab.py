import os
import json
import tempfile
import hashlib
import glob
from urllib.parse import urlparse, quote

from gem_browser.paths import config_path, secure_chmod
from gem_browser import theme as gem_theme
from gem_browser import icons as gem_icons
from gem_browser.router import build_search_url

BOOKMARKS_FILE = config_path("bookmarks.json")

# Bellek içi favori önbelleği: adres çubuğu önerileri ve yıldız her URL
# değişiminde load_bookmarks() çağırdığından her seferinde disk okunuyordu.
# Değişiklik yalnızca save_bookmarks() üzerinden olur; dışsal dosya
# değişimi (elle düzenleme) ancak uygulama yeniden başlatınca görünür —
# kabul edilebilir takas.
_BOOKMARK_CACHE = None


def load_bookmarks():
    global _BOOKMARK_CACHE
    if _BOOKMARK_CACHE is not None:
        return list(_BOOKMARK_CACHE)  # çağıranın listeyi değiştirmesi önbelleği bozmasın
    loaded = None
    if os.path.exists(BOOKMARKS_FILE):
        try:
            with open(BOOKMARKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                # Bozuk/elle düzenlenmiş dosyada KeyError/AttributeError
                # yerine geçerli girdileri süz.
                loaded = [b for b in data if isinstance(b, dict)
                          and isinstance(b.get("url"), str) and b["url"].strip()]
        except Exception:
            loaded = None
    if loaded is None:
        loaded = [
            {"name": "GitHub", "url": "https://github.com"},
            {"name": "DuckDuckGo", "url": "https://duckduckgo.com"},
            {"name": "YouTube", "url": "https://youtube.com"}
        ]
    _BOOKMARK_CACHE = loaded
    return list(loaded)


def save_bookmarks(bookmarks):
    global _BOOKMARK_CACHE
    # Önbelleği kaydedilen kopyayla güncelle (sonraki load disk okumaz).
    _BOOKMARK_CACHE = [dict(b) for b in bookmarks]
    try:
        with open(BOOKMARKS_FILE, "w", encoding="utf-8") as f:
            json.dump(bookmarks, f, indent=4, ensure_ascii=False)
        secure_chmod(BOOKMARKS_FILE)
    except OSError:
        pass

NEW_TAB_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>NEW_TAB_TITLE</title>
    <style>
        :root {
            --bg-center: BG_CENTER_PLACEHOLDER;
            --bg-edge: BG_EDGE_PLACEHOLDER;
            --text-main: TEXT_MAIN_PLACEHOLDER;
            --text-muted: TEXT_MUTED_PLACEHOLDER;
            --accent-color: ACCENT_COLOR_PLACEHOLDER;
            --accent-glow: ACCENT_GLOW_PLACEHOLDER;
            --input-bg: INPUT_BG_PLACEHOLDER;
            --input-border: INPUT_BORDER_PLACEHOLDER;
            --tile-bg: TILE_BG_PLACEHOLDER;
            --tile-hover: TILE_HOVER_PLACEHOLDER;
        }

        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: BODY_BACKGROUND_PLACEHOLDER;
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
            color: var(--text-main);
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            padding-bottom: 8vh;
            box-sizing: border-box;
            overflow: hidden;
        }

        /* Sekme açılışında tek seferlik, hafif giriş animasyonu.
           Sadece transform + opacity kullanılıyor (GPU tarafından
           compositor katmanında oynatılır, layout/paint tetiklemez),
           bu yüzden CPU/GPU üzerinde neredeyse hiç yük oluşturmaz ve
           animasyon bitince (fill-mode: both + kaldırılan will-change)
           tamamen durur. Kullanıcı sistem düzeyinde "hareketi azalt"
           tercihi yaptıysa (prefers-reduced-motion) tamamen devre dışı
           bırakılır. */
        @keyframes gemFadeSlideUp {
            from { opacity: 0; transform: translateY(14px); }
            to   { opacity: 1; transform: translateY(0); }
        }

        .logo-container, .search-container, .bookmarks-grid {
            animation: gemFadeSlideUp 0.5s cubic-bezier(0.19, 1, 0.22, 1) both;
        }
        .logo-container { animation-delay: 0s; }
        .search-container { animation-delay: 0.08s; }
        .bookmarks-grid { animation-delay: 0.16s; }

        @media (prefers-reduced-motion: reduce) {
            .logo-container, .search-container, .bookmarks-grid {
                animation: none;
            }
        }

        .logo-container {
            margin-bottom: 25px;
            text-align: center;
            user-select: none;
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        .logo-container img { width: 100px; height: auto; margin-bottom: 10px; filter: drop-shadow(0 0 15px var(--accent-glow)); }
        .brand-title { font-size: 1.4rem; font-weight: 300; letter-spacing: 6px; margin: 0; color: var(--text-main); }
        .search-container { width: 100%; max-width: 600px; }
        .search-wrapper { position: relative; width: 100%; }

        .search-icon {
            position: absolute; left: 20px; top: 50%; transform: translateY(-50%); width: 20px; height: 20px; fill: var(--text-muted); pointer-events: none;
        }

        input[type="text"] {
            width: 100%; box-sizing: border-box; background-color: var(--input-bg); color: var(--text-main);
            border: 1px solid var(--input-border); border-radius: 30px; padding: 16px 20px 16px 52px;
            font-family: 'Segoe UI', 'Ubuntu', system-ui, -apple-system, sans-serif;
            font-size: 1.02rem; font-weight: 400; letter-spacing: 0.1px;
            outline: none; backdrop-filter: blur(10px); transition: all 0.3s ease;
        }

        input[type="text"]:focus { border-color: var(--accent-color); box-shadow: 0 0 20px var(--accent-glow); }

        .bookmarks-grid {
            display: flex; flex-wrap: wrap; gap: 12px; justify-content: center; max-width: 680px; margin-top: 28px;
        }

        .bookmark-tile {
            background-color: var(--tile-bg); border: 1px solid var(--input-border); padding: 8px 16px 8px 8px;
            border-radius: 999px; color: var(--text-main); text-decoration: none; font-size: 0.9rem; font-weight: 500;
            display: flex; align-items: center; gap: 10px; backdrop-filter: blur(6px);
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.18);
            transition: transform 0.18s ease, background-color 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
        }

        .bookmark-tile:hover {
            background-color: var(--tile-hover); border-color: var(--accent-color); transform: translateY(-3px);
            box-shadow: 0 10px 20px rgba(0, 0, 0, 0.28), 0 0 0 1px var(--accent-glow);
        }

        .bookmark-icon-wrap {
            width: 26px; height: 26px; border-radius: 50%; flex-shrink: 0; overflow: hidden;
            background: rgba(128, 128, 128, 0.18);
            display: flex; align-items: center; justify-content: center;
        }

        .bookmark-icon { width: 16px; height: 16px; object-fit: contain; }

        .bookmark-fallback {
            width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
            font-size: 12px; font-weight: 700; color: #ffffff; user-select: none;
        }

        .add-tile {
            background: transparent; border: 1.5px dashed var(--text-muted); color: var(--text-muted);
            cursor: pointer; font-weight: 600; padding: 9px 20px; box-shadow: none;
        }
        .add-tile:hover {
            color: var(--accent-color); border-color: var(--accent-color); background-color: var(--tile-bg);
            transform: translateY(-3px); box-shadow: 0 10px 20px rgba(0, 0, 0, 0.22);
        }

        .del-btn {
            background: transparent; border: none; color: var(--text-muted); font-size: 15px; cursor: pointer;
            line-height: 1; padding: 0; width: 18px; height: 18px; border-radius: 50%; flex-shrink: 0;
            display: flex; align-items: center; justify-content: center; transition: all 0.15s ease;
        }
        .del-btn:hover { color: #ff5555; background: rgba(255, 85, 85, 0.15); }
    </style>
    <script>
        function handleSearch(event) {
            event.preventDefault();
            var query = document.getElementById('searchInput').value.trim();
            if (!query) return;
            // Güvenlik: betik şemalarını adres/sorgu olarak asla gezinme.
            var lower = query.toLowerCase();
            if (lower.indexOf('javascript:') === 0 || lower.indexOf('data:') === 0 || lower.indexOf('vbscript:') === 0) return;
            if (query.includes('://')) window.location.href = query;
            else if (query.includes('.') && !query.includes(' ')) window.location.href = 'https://' + query;
            else window.location.href = 'SEARCH_URL_PREFIX_PLACEHOLDER' + encodeURIComponent(query);
        }

        function addBookmark() {
            // Qt 6.11 bilinmeyen şemalara location.href gezinmesini düşürdüğü
            // için uygulama eylemleri console kanalından iletilir
            // (browser_tab.javaScriptConsoleMessage yakalar).
            console.log("gemaction:request_add_bookmark");
        }

        function removeBookmark(url) {
            console.log("gemaction:request_remove_bookmark " + encodeURIComponent(url));
        }

        // Favicon indirilemediğinde (ör. bağlantı yok, site favicon sunmuyor)
        // kırık resim ikonu yerine, site adının baş harfini gösteren yuvarlak
        // ve markanın mavi tonlarından birine boyanmış küçük bir rozet gösterir.
        function gemFaviconFallback(img) {
            var wrap = img.parentElement;
            var name = wrap.getAttribute('data-name') || '?';
            var colors = ['#3daee9', '#2f8fc4', '#1f6fa5', '#4dbef9', '#1c5a82', '#59c3f0'];
            var sum = 0;
            for (var i = 0; i < name.length; i++) sum += name.charCodeAt(i);
            var color = colors[sum % colors.length];
            img.remove();
            var fb = document.createElement('div');
            fb.className = 'bookmark-fallback';
            fb.style.backgroundColor = color;
            fb.textContent = name.charAt(0).toUpperCase();
            wrap.appendChild(fb);
        }
    </script>
</head>
<body>
    <div class="logo-container">
        <img src="LOGO_URL_PLACEHOLDER" alt="GEM Logo" style="display: LOGO_DISPLAY_PLACEHOLDER;">
        <div class="brand-title">GEM BROWSER</div>
    </div>

    <div class="search-container">
        <form onsubmit="handleSearch(event)">
            <div class="search-wrapper">
                <input type="text" id="searchInput" placeholder="SEARCH_PLACEHOLDER" autofocus autocomplete="off">
                <svg class="search-icon" viewBox="0 0 24 24"><path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
            </div>
        </form>

        <div class="bookmarks-grid">
            BOOKMARKS_HTML_PLACEHOLDER
            <button class="bookmark-tile add-tile" onclick="addBookmark()">ADD_BTN_PLACEHOLDER</button>
        </div>
    </div>
</body>
</html>
"""

def get_new_tab_url(theme="dark", lang="tr", accent_color=None, background_image=None,
                    search_engine="brave", custom_search_url="") -> str:
    """
    `accent_color`: "#rrggbb" formatında, None/boş ise temaya göre varsayılan
    kullanılır (bkz. gem_browser/theme.py).
    `background_image`: kullanıcının Ayarlar'dan seçip config dizinine
    kopyalattığı görselin tam disk yolu. None/boş veya dosya artık yoksa
    (silinmiş/taşınmışsa) sessizce varsayılan gradyan arkaplana düşülür.
    `search_engine`/`custom_search_url`: sayfadaki arama kutusunun gideceği
    motor (bkz. router.build_search_url).
    """
    bookmarks = load_bookmarks()

    accent = accent_color if gem_theme._is_valid_hex_color(accent_color or "") else gem_theme.default_accent_for_theme(theme)

    # Arama kutusu JS'ine gömülecek URL öneki. Özel motorda "{q}" yer
    # tutucusu varsa önek kısmı (ilk "{q}"den önceki bölüm) alınır.
    custom = (custom_search_url or "").strip()
    if custom and "{q}" in custom:
        search_prefix = custom.split("{q}", 1)[0]
    else:
        search_prefix = build_search_url("", search_engine, custom)
    # JS tek tırnaklı string içine gömülecek: kaçış.
    search_prefix_js = search_prefix.replace("\\", "\\\\").replace("'", "\\'")

    bg_url = ""
    if background_image and os.path.exists(background_image):
        bg_path = os.path.abspath(background_image).replace("\\", "/")
        if not bg_path.startswith('/'):
            bg_path = '/' + bg_path
        # Yol boşluk veya Türkçe/aksanlı karakterler içerebilir (ör.
        # "/home/Ahmet Yılmaz/Masaüstü/foo.jpg"). file:// URL'leri
        # ham (encode edilmemiş) haliyle geçersiz/bozuk sayılabilir ve
        # QtWebEngine görseli hiç yüklemez — görsel "kayboluyormuş" gibi
        # görünür ama aslında hiç geçerli bir URL olmamıştır. quote()
        # ile path segmentlerini encode ediyoruz, '/' ayıracını koruyoruz.
        bg_url = f"file://{quote(bg_path)}"

    # Arkaplan görseli, tema ve dil dışında ARTIK vurgu rengine ve arkaplan
    # görseline göre de değişebildiği için önbellek anahtarına ikisi de
    # dahil edildi — aksi halde renk/görsel değiştirildiğinde eski
    # önbellekteki HTML gösterilmeye devam ederdi.
    #
    # NOT: burada Python'un yerleşik hash() fonksiyonu YERİNE hashlib
    # kullanılıyor. hash(str) süreçten sürece rastgele bir tuz (hash
    # randomization / PYTHONHASHSEED) ile hesaplanır; yani uygulama her
    # yeniden başlatıldığında AYNI arkaplan için FARKLI bir cache_key
    # üretilir. Bu hem gereksiz yere temp klasöründe eski HTML dosyalarının
    # sonsuza dek birikmesine (hiç silinmeden) yol açar, hem de teorik
    # olarak temp dizini/disk kotası dolduğunda aşağıdaki dosya yazımının
    # sessizce patlamasına zemin hazırlar. hashlib ile deterministik bir
    # anahtar üretilir.
    bg_hash = hashlib.md5(bg_url.encode("utf-8")).hexdigest()[:10]
    # Arama motoru da önbellek anahtarına dahil — aksi halde motor
    # değiştirilince eski önbellekteki HTML (eski motorla) gösterilirdi.
    engine_part = f"{search_engine}_{hashlib.md5(custom.encode('utf-8')).hexdigest()[:8] if custom else ''}"
    cache_key = f"{theme}_{lang}_{len(bookmarks)}_{accent.lstrip('#')}_{bg_hash}_{engine_part}"

    # Bu belirli state (tema/dil/yer imi sayısı/renk/arkaplan) için üretilen
    # HTML dosyası dışındaki eski "gem_browser_new_tab_*.html" dosyalarını
    # best-effort temizle. Aksi halde her farklı ayar kombinasyonu temp
    # dizininde kalıcı bir dosya biriktirir; bu hem gereksiz disk kullanımı
    # hem de (nadir de olsa) dizinin dolup yeni dosya yazımını
    # başarısız kılma riski demektir. Silme başarısız olursa (ör. dosya
    # o an başka bir sekme tarafından kullanılıyor) sessizce geçilir.
    try:
        current_name = f"gem_browser_new_tab_{cache_key}.html"
        for old_file in glob.glob(os.path.join(tempfile.gettempdir(), "gem_browser_new_tab_*.html")):
            if os.path.basename(old_file) != current_name:
                try:
                    os.remove(old_file)
                except OSError:
                    pass
    except OSError:
        pass

    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Logo, statik logo.png yerine artık aktif vurgu rengine boyanmış
    # (bkz. gem_browser/icons.py -> tinted_logo_file) bir kopyası olarak
    # gösteriliyor; böylece kullanıcı Ayarlar'dan farklı bir renk seçtiğinde
    # yeni sekme sayfasındaki logo da otomatik olarak o renge döner.
    tinted_path = gem_icons.tinted_logo_file(accent, size=128)
    if tinted_path and os.path.exists(tinted_path):
        logo_path = tinted_path.replace("\\", "/")
    else:
        # Boyama başarısız olursa (ör. kaynak logo.png bulunamadıysa)
        # sessizce orijinal statik dosyaya düş.
        logo_path = os.path.join(current_dir, "logo.png").replace("\\", "/")

    if os.path.exists(logo_path):
        if not logo_path.startswith('/'):
            logo_path = '/' + logo_path
        # bg_url ile aynı gerekçe: encode edilmemiş bir file:// URL,
        # kullanıcı adında/config dizininde boşluk ya da Türkçe karakter
        # varsa tarayıcı tarafında sessizce yüklenemeyebilir ve logo hiç
        # görünmez. quote() ile güvenli hale getiriyoruz.
        logo_url = f"file://{quote(logo_path)}"
    else:
        logo_url = ""

    logo_display = "block" if logo_url else "none"

    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, f"gem_browser_new_tab_{cache_key}.html")

    final_html = NEW_TAB_HTML.replace("LOGO_URL_PLACEHOLDER", logo_url)
    final_html = final_html.replace("LOGO_DISPLAY_PLACEHOLDER", logo_display)

    final_html = final_html.replace("ACCENT_COLOR_PLACEHOLDER", accent)
    final_html = final_html.replace("ACCENT_GLOW_PLACEHOLDER", gem_theme.to_rgba(accent, 0.4))

    if bg_url:
        # Kullanıcının seçtiği görsel, altındaki metin/arama kutusu her
        # zaman okunur kalsın diye üzerine hafif karartan bir katman
        # (scrim) ile birlikte gösteriliyor — tema ne olursa olsun.
        body_background = f"linear-gradient(rgba(0, 0, 0, 0.45), rgba(0, 0, 0, 0.45)), url('{bg_url}')"
    else:
        body_background = "radial-gradient(circle at center, var(--bg-center) 0%, var(--bg-edge) 100%)"
    final_html = final_html.replace("BODY_BACKGROUND_PLACEHOLDER", body_background)

    placeholder = "Web'de arayın veya bir URL girin..." if lang == "tr" else "Search the web or enter a URL..."
    title = "Yeni Sekme" if lang == "tr" else "New Tab"
    add_btn_text = "+ EKLE" if lang == "tr" else "+ ADD"

    final_html = final_html.replace("SEARCH_PLACEHOLDER", placeholder)
    final_html = final_html.replace("SEARCH_URL_PREFIX_PLACEHOLDER", search_prefix_js)
    final_html = final_html.replace("NEW_TAB_TITLE", title)
    final_html = final_html.replace("ADD_BTN_PLACEHOLDER", add_btn_text)

    def _esc(s):
        return (s or "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")

    def _js_str(s):
        # JS tek tırnaklı string içine gömme için: ters bölü, tırnak ve
        # satır sonlarını kaçır.
        return (s or "").replace("\\", "\\\\").replace("'", "\\'").replace("\r", "").replace("\n", "\\n")

    bm_html = ""
    for bm in bookmarks:
        # Daha güvenilir favicon çekimi için DuckDuckGo Icon API kullanımı
        parsed_url = urlparse(bm["url"])
        domain = parsed_url.netloc
        if not domain:
            domain = bm["url"].replace('https://', '').replace('http://', '').split('/')[0]

        icon_url = f"https://icons.duckduckgo.com/ip3/{quote(domain, safe='')}.ico"
        safe_name = _esc(bm["name"])
        # GÜVENLİK: URL, href özniteliğine VE onclick JS string'ine gömülür;
        # kaçış yapılmayan bir URL (' " < > içererek) HTML'i bozar/JS
        # enjekte ederdi. Önce JS-string kaçışı, ardından HTML öznitelik
        # kaçışı uygulanır (HTML ayrıştırıcı &quot; decode edip JS'e düz
        # " olarak iletir; JS string'i tek tırnaklı olduğu için güvenli).
        safe_href = _esc(bm["url"])
        safe_js_url = _esc(_js_str(bm["url"]))

        bm_html += (
            f'<a href="{safe_href}" class="bookmark-tile">'
            f'<span class="bookmark-icon-wrap" data-name="{safe_name}">'
            f'<img src="{icon_url}" class="bookmark-icon" alt="" onerror="gemFaviconFallback(this)">'
            f'</span>'
            f'{safe_name}'
            f'<span class="del-btn" onclick="event.preventDefault(); removeBookmark(\'{safe_js_url}\')">×</span>'
            f'</a>'
        )

    final_html = final_html.replace("BOOKMARKS_HTML_PLACEHOLDER", bm_html)

    if theme == "light":
        final_html = final_html.replace("BG_CENTER_PLACEHOLDER", "#ffffff").replace("BG_EDGE_PLACEHOLDER", "#e6e6e6")
        final_html = final_html.replace("TEXT_MAIN_PLACEHOLDER", "#1a1a1a").replace("TEXT_MUTED_PLACEHOLDER", "#666666")
        final_html = final_html.replace("INPUT_BG_PLACEHOLDER", "rgba(0, 0, 0, 0.03)").replace("INPUT_BORDER_PLACEHOLDER", "rgba(0, 0, 0, 0.1)")
        final_html = final_html.replace("TILE_BG_PLACEHOLDER", "rgba(0, 0, 0, 0.04)").replace("TILE_HOVER_PLACEHOLDER", "rgba(0, 0, 0, 0.08)")
    else:
        final_html = final_html.replace("BG_CENTER_PLACEHOLDER", "#23232b").replace("BG_EDGE_PLACEHOLDER", "#121214")
        final_html = final_html.replace("TEXT_MAIN_PLACEHOLDER", "#ffffff").replace("TEXT_MUTED_PLACEHOLDER", "#6b6b76")
        final_html = final_html.replace("INPUT_BG_PLACEHOLDER", "rgba(255, 255, 255, 0.03)").replace("INPUT_BORDER_PLACEHOLDER", "rgba(255, 255, 255, 0.08)")
        final_html = final_html.replace("TILE_BG_PLACEHOLDER", "rgba(255, 255, 255, 0.04)").replace("TILE_HOVER_PLACEHOLDER", "rgba(255, 255, 255, 0.08)")

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(final_html)
    except OSError:
        # Disk dolu/izin hatası: temp HTML yazılamazsa bozuk bir dosya
        # göstermek yerine boş sayfaya düş (çağıran taraf sekme açar).
        return "about:blank"

    # Temp dizini yolu da (Windows'ta "AppData\Local\Temp\Ahmet Yılmaz\..."
    # gibi) boşluk/Türkçe karakter içerebileceğinden, sekmeye yüklenecek
    # asıl HTML sayfasının URL'sini de encode ediyoruz.
    return f"file://{quote(file_path.replace(os.sep, '/'))}"
