"""
Sekme içinde PDF görüntüleme (Mozilla PDF.js tabanlı).

NEDEN GEREKLİ: Bu sistemdeki qt6-webengine paketi, Chromium'un yerleşik PDF
görüntüleyicisinin kaynakları ÇIKARTILMIŞ halde dağıtılıyor (resources.pak
içinde PDF uzantısı yok) — PdfViewerEnabled ayarı bu yüzden etkisiz ve
PDF'ler indirmeye düşüyor. Çözüm: Mozilla'nın PDF.js'i (Apache-2.0) pakete
vendor edip KENDİ görüntüleyici sayfamızı üretmek.

AKIŞ:
- AdblockInterceptor (profil genelinde URL interceptor), ana/alt çerçeve
  .pdf gezinmelerini build_viewer_url()'in ürettiği yerel görüntüleyici
  sayfasına YÖNLENDİRİR (bkz. adblock.py).
- Görüntüleyici sayfası (file://) PDF'i fetch ile çeker: yerel sayfaların
  uzak/yerel kaynaklara erişimi window.py'deki LocalContentCanAccessRemoteUrls
  ve LocalContentCanAccessFileUrls ayarlarıyla serbesttir.
- fetch/indirme bağlantıları '_gemview=1' işaret parametresi taşır;
  interceptor bu parametreyi görürse YÖNLENDİRMEZ (sonsuz döngüyü engeller).

Dosyalar anahtar (PDF URL'inin md5'i) başına temp dizininde önbelleklenir;
en eski _KEEP_FILES dosya dışı temizlenir. interceptRequest IO thread'inden
çağrılabileceği için buradaki işlemler saf dosya IO'sudur (Qt nesnesine
dokunulmaz) ve _LOCK ile korunur.
"""

import glob
import hashlib
import json
import os
import ssl
import tempfile
import threading
import urllib.request
from urllib.parse import quote, unquote, urlparse

import certifi

from PyQt6.QtCore import QUrl

# Vendor edilmiş PDF.js (bkz. gem_browser/pdfjs/LICENSE — Apache-2.0)
_PDFJS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdfjs")
_PDF_MJS = os.path.join(_PDFJS_DIR, "pdf.min.mjs")
_WORKER_MJS = os.path.join(_PDFJS_DIR, "pdf.worker.min.mjs")

_MARKER = "_gemview=1"
_KEEP_FILES = 12

_LOCK = threading.Lock()


def _file_url(path: str) -> str:
    p = os.path.abspath(path).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return f"file://{quote(p)}"


def _source_filename(source: str) -> str:
    try:
        if "://" in source:
            name = os.path.basename(unquote(urlparse(source).path))
        else:
            name = os.path.basename(source)
        return name or "belge.pdf"
    except Exception:
        return "belge.pdf"


def _marker_url(source: str) -> str:
    """Kaynak URL'e _gemview=1 ekler (interceptor bu işaretli isteklere
    dokunmaz). file:// URL'lerde parametre anlamsızdır ama zarar da
    vermez; yine de yalnızca http(s) için ekleyelim."""
    if source.startswith("file://"):
        return source
    return source + ("&" if "?" in source else "?") + _MARKER


_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  html, body { margin: 0; padding: 0; height: 100%; background: #1e1e22; }
  #toolbar {
    position: fixed; top: 0; left: 0; right: 0; height: 42px; z-index: 10;
    display: flex; align-items: center; gap: 6px; padding: 0 12px;
    background: #242429; color: #d8d8de; border-bottom: 1px solid #333338;
    font-family: 'Segoe UI', 'Ubuntu', sans-serif; font-size: 13px;
    user-select: none;
  }
  #toolbar button {
    background: #33333a; color: #d8d8de; border: 1px solid #43434a;
    border-radius: 6px; min-width: 30px; height: 28px; cursor: pointer;
    font-size: 14px; line-height: 1; padding: 0 8px;
  }
  #toolbar button:hover { background: #43434c; }
  #toolbar .sep { width: 1px; height: 20px; background: #43434a; margin: 0 4px; }
  #toolbar a#dl {
    background: #33333a; color: #d8d8de; border: 1px solid #43434a;
    border-radius: 6px; height: 28px; display: inline-flex; align-items: center;
    padding: 0 10px; cursor: pointer; text-decoration: none;
  }
  #toolbar a#dl:hover { background: #43434c; }
  #pnum { min-width: 70px; text-align: center; }
  #status { margin-left: auto; color: #8a8a94; font-size: 12px; }
  #pages { padding: 54px 0 30px; }
  .pageWrap { position: relative; margin: 10px auto; width: fit-content;
              box-shadow: 0 2px 14px rgba(0,0,0,.55); background: #52525c; }
  .pageWrap canvas { display: block; }
  .pageNumTag {
    position: absolute; top: -22px; left: 0; color: #8a8a94; font-size: 11px;
    font-family: 'Segoe UI', 'Ubuntu', sans-serif;
  }
  #err {
    margin: 80px auto; max-width: 480px; color: #e8e8ee; text-align: center;
    font-family: 'Segoe UI', 'Ubuntu', sans-serif; font-size: 14px; white-space: pre-line;
  }
</style>
</head>
<body>
<div id="toolbar">
  <button id="prev" title="Önceki sayfa">‹</button>
  <span id="pnum">– / –</span>
  <button id="next" title="Sonraki sayfa">›</button>
  <span class="sep"></span>
  <button id="zoomout" title="Uzaklaştır">−</button>
  <button id="zoomin" title="Yakınlaştır">+</button>
  <button id="fit" title="Genişliğe sığdır">Sığdır</button>
  <span class="sep"></span>
  <a id="dl" style="__DL_HIDE__" title="İndir" href="__DL_HREF__">⬇ İndir</a>
  <span id="status"></span>
</div>
<div id="pages"></div>
<script type="module">
import * as pdfjsLib from '__PDF_MJS__';
pdfjsLib.GlobalWorkerOptions.workerSrc = '__WORKER_MJS__';

const SRC = __SRC_JSON__;
const pagesEl = document.getElementById('pages');
const pnumEl = document.getElementById('pnum');
const statusEl = document.getElementById('status');

let pdfDoc = null;
let scale = 0;            // 0 => ilk ölçümde genişliğe sığdır
let placeholders = [];
let pending = new Set();

function fmtErr(e) {
  const s = String(e && (e.message || e));
  if (s.toLowerCase().includes('password')) {
    return 'Bu PDF parola korumalı.\\nŞifreli belgeler bu görüntüleyicide açılamıyor.';
  }
  return 'PDF yüklenemedi:\\n' + s;
}

async function init() {
  try {
    pdfDoc = await pdfjsLib.getDocument({
      url: SRC,
      disableRange: true,   // file:// ve bazı sunucularda range sorunlarını önle
      disableStream: true,
      isEvalSupported: false,
    }).promise;
  } catch (e) {
    const err = document.createElement('div');
    err.id = 'err'; err.textContent = fmtErr(e);
    pagesEl.replaceWith(err);
    statusEl.textContent = '';
    return;
  }
  window.PDF_VIEWER_READY = true;
  window.NUM_PAGES = pdfDoc.numPages;
  await buildPages();
}

async function buildPages() {
  pagesEl.innerHTML = '';
  placeholders = [];
  // İlk sayfayı ölç ve başlangıç ölçeğini (genişliğe sığdır) hesapla
  const p1 = await pdfDoc.getPage(1);
  const vp1 = p1.getViewport({ scale: 1 });
  const avail = Math.max(240, window.innerWidth - 36);
  if (!scale || scale <= 0) scale = avail / vp1.width;
  scale = Math.min(4, Math.max(0.25, scale));

  for (let i = 1; i <= pdfDoc.numPages; i++) {
    const wrap = document.createElement('div');
    wrap.className = 'pageWrap';
    wrap.dataset.page = String(i);
    const tag = document.createElement('div');
    tag.className = 'pageNumTag';
    tag.textContent = String(i) + ' / ' + pdfDoc.numPages;
    const canvas = document.createElement('canvas');
    canvas.style.display = 'none';
    wrap.appendChild(tag);
    wrap.appendChild(canvas);
    pagesEl.appendChild(wrap);
    placeholders.push({
      i, wrap, canvas,
      baseW: Math.floor(vp1.width), baseH: Math.floor(vp1.height),
      w: Math.floor(vp1.width * scale), h: Math.floor(vp1.height * scale),
      renderedAtScale: 0,
    });
  }
  for (const ph of placeholders) {
    ph.wrap.style.width = ph.w + 'px';
    ph.wrap.style.height = ph.h + 'px';
  }
  renderVisible();
}

async function renderPage(ph) {
  if (pending.has(ph.i)) return;
  if (ph.canvas.width > 0 && ph.renderedAtScale === scale) return;
  pending.add(ph.i);
  try {
    const page = await pdfDoc.getPage(ph.i);
    const vpUnit = page.getViewport({ scale: 1 });
    // Sayfa boyutları değişken olabilir: gerçek orana göre yer tutucuyu düzelt
    ph.w = Math.floor(vpUnit.width * scale);
    ph.h = Math.floor(vpUnit.height * scale);
    ph.wrap.style.width = ph.w + 'px';
    ph.wrap.style.height = ph.h + 'px';

    const dpr = window.devicePixelRatio || 1;
    const vp = page.getViewport({ scale: scale * dpr });
    ph.canvas.width = Math.floor(vp.width);
    ph.canvas.height = Math.floor(vp.height);
    ph.canvas.style.width = ph.w + 'px';
    ph.canvas.style.height = ph.h + 'px';
    await page.render({ canvasContext: ph.canvas.getContext('2d'), viewport: vp }).promise;
    ph.canvas.style.display = 'block';
    ph.renderedAtScale = scale;
  } catch (e) {
    statusEl.textContent = 'Sayfa ' + ph.i + ' çizilemedi';
  } finally {
    pending.delete(ph.i);
  }
}

function renderVisible() {
  if (!pdfDoc) return;
  const pad = 700;  // ileri-geri kaydırınca boşluk görünmesin diye önden çiz
  const top = window.scrollY - pad;
  const bottom = window.scrollY + window.innerHeight + pad;
  for (const ph of placeholders) {
    const t = ph.wrap.offsetTop;
    const b = t + ph.wrap.offsetHeight;
    if (b >= top && t <= bottom) renderPage(ph);
  }
}

function updateVisible() {
  const mid = window.scrollY + window.innerHeight / 2;
  let cur = 1;
  for (const ph of placeholders) {
    const t = ph.wrap.offsetTop;
    const b = t + ph.wrap.offsetHeight;
    if (mid >= t && mid < b) { cur = ph.i; break; }
    if (t > mid) { cur = Math.max(1, ph.i - 1); break; }
  }
  pnumEl.textContent = cur + ' / ' + pdfDoc.numPages;
  pnumEl.dataset.cur = String(cur);
}

window.addEventListener('scroll', () => { updateVisible(); renderVisible(); });
window.addEventListener('resize', () => { updateVisible(); renderVisible(); });

document.getElementById('prev').onclick = () => gotoPage(Number(pnumEl.dataset.cur || 1) - 1);
document.getElementById('next').onclick = () => gotoPage(Number(pnumEl.dataset.cur || 1) + 1);
function gotoPage(n) {
  if (!pdfDoc) return;
  n = Math.min(pdfDoc.numPages, Math.max(1, n));
  const ph = placeholders[n - 1];
  if (ph) ph.wrap.scrollIntoView({ block: 'start' });
}
document.getElementById('zoomin').onclick = () => { if (pdfDoc) { scale = Math.min(4, scale * 1.2); rescale(); } };
document.getElementById('zoomout').onclick = () => { if (pdfDoc) { scale = Math.max(0.25, scale / 1.2); rescale(); } };
document.getElementById('fit').onclick = () => { if (pdfDoc) { scale = 0; rescale(); } };

async function rescale() {
  if (!pdfDoc) return;
  if (!scale || scale <= 0) {
    const p1 = await pdfDoc.getPage(1);
    const vp1 = p1.getViewport({ scale: 1 });
    scale = Math.max(0.25, Math.min(4, (window.innerWidth - 36) / vp1.width));
  }
  for (const ph of placeholders) {
    ph.w = Math.floor(ph.baseW * scale);
    ph.h = Math.floor(ph.baseH * scale);
    ph.wrap.style.width = ph.w + 'px';
    ph.wrap.style.height = ph.h + 'px';
    ph.canvas.style.display = 'none';
    ph.canvas.width = 0; ph.canvas.height = 0;
    ph.renderedAtScale = 0;
  }
  updateVisible();
  renderVisible();
}

init();
</script>
</body>
</html>
"""


def fetch_pdf_to_temp(url: str, max_bytes: int = 200 * 1024 * 1024, timeout: int = 30) -> str:
    """
    Uzak PDF'i Python tarafinda (urllib + certifi CA paketi) sessizce
    indirip temp dizinindeki yerel kopyanin yolunu dondurur.

    Neden Chromium'a indirtmiyoruz: file:// goruntuleyici sayfasindan uzak
    PDF'i fetch/XHR ile cekmek Qt 6.11'de CORS'a takiliyor
    (LocalContentCanAccessRemoteUrls artik bypass saglamiyor). Qt tarafi
    indirmede CORS kavrami yoktur; goruntuleyici yerel kopyayi file://'ten
    okur (bu erisim LocalContentCanAccessFileUrls ile serbesttir).

    BLOKLAYICI: QThread icinde calistirilmali (bkz. window.PdfFetchThread).
    """
    key = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
    dest = os.path.join(tempfile.gettempdir(), f"gem_pdf_src_{key}.pdf")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) GEM-Browser/1.0"},
    )
    ctx = ssl.create_default_context(cafile=certifi.where())
    tmp = dest + ".part"
    # Tamamini RAM'e yuklemek yerine diske parca parca akit (buyuk PDF'lerde
    # 200 MB'lik RAM sicramasini onler).
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp, \
                open(tmp, "wb") as f:
            total = 0
            first = True
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                if first:
                    # Icerik dogrulamasi: gercekten PDF mi?
                    if not chunk.lstrip()[:4] == b"%PDF":
                        raise ValueError("Icerik bir PDF degil (sunucu HTML/hata dondurdu olabilir)")
                    first = False
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"PDF sinirin cok buyuk (> {max_bytes // (1024 * 1024)} MB)")
                f.write(chunk)
        if first:
            raise ValueError("Bos yanit")
        os.replace(tmp, dest)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise
    return dest


def build_viewer_url(source: str, display_name: str = None, download_url: str = None) -> str:
    """PDF kaynağı için görüntüleyici sayfasının file:// URL'ini döndürür.
    Aynı kaynak için dosya önbelleklenir; en eski _KEEP_FILES dosya dışı
    temizlenir. interceptRequest IO thread'inden çağırabilir (saf IO)."""
    with _LOCK:
        key = hashlib.md5(source.encode("utf-8")).hexdigest()[:12]
        file_path = os.path.join(tempfile.gettempdir(), f"gem_pdf_viewer_{key}.html")
        needs_write = True
        if os.path.exists(file_path):
            try:
                needs_write = os.path.getsize(file_path) == 0
            except OSError:
                needs_write = True

        if needs_write:
            if not (os.path.exists(_PDF_MJS) and os.path.exists(_WORKER_MJS)):
                return ""  # PDF.js vendor edilmemiş: yönlendirme yapılamaz
            title = display_name or _source_filename(source)
            safe_title = (title.replace("&", "&amp;").replace('"', "&quot;")
                          .replace("<", "&lt;").replace(">", "&gt;"))
            # İndir hedefi: uzak kopyadan açılan PDF'lerde ORİJİNAL URL
            # (kullanıcı dosyayı gerçek kaynağından indirebilsin); gerçekten
            # yerel dosyalarda İndir anlamsızdır (ve görüntüleyiciye dönen
            # bir döngü yaratır) → düğme gizlenir.
            if download_url:
                dl_href = _marker_url(download_url)
                dl_hide = ""
            else:
                dl_href = "#"
                dl_hide = "display:none"
            html = (_HTML_TEMPLATE
                    .replace("__TITLE__", safe_title)
                    .replace("__SRC_JSON__", json.dumps(_marker_url(source)))
                    .replace("__DL_HREF__", dl_href.replace('"', "&quot;"))
                    .replace("__DL_HIDE__", dl_hide)
                    .replace("__PDF_MJS__", _file_url(_PDF_MJS))
                    .replace("__WORKER_MJS__", _file_url(_WORKER_MJS)))
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(html)
            except OSError:
                return ""

        _cleanup_old(file_path)
        return _file_url(file_path)


def _cleanup_old(current: str):
    try:
        files = sorted(
            glob.glob(os.path.join(tempfile.gettempdir(), "gem_pdf_viewer_*.html")) +
            glob.glob(os.path.join(tempfile.gettempdir(), "gem_pdf_src_*.pdf")),
            key=os.path.getmtime, reverse=True,
        )
        for old in files[_KEEP_FILES:]:
            try:
                os.remove(old)
            except OSError:
                pass
    except Exception:
        pass


def should_redirect_to_viewer(url: QUrl) -> bool:
    """Verilen URL ana/alt çerçeve PDF gezinmesi mi (görüntüleyiciye
    yönlendirilmeli mi)? Marker'lı istekler asla yönlendirilmez."""
    s = url.toString()
    if _MARKER in s:
        return False
    path = s.split("?", 1)[0].split("#", 1)[0]
    if not path.lower().endswith(".pdf"):
        return False
    scheme = url.scheme().lower()
    return scheme in ("http", "https", "file")
