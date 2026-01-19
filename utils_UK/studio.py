# import re
# import html
# import requests
# from pathlib import Path
# from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
# from playwright.sync_api import sync_playwright


# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


# def _safe_name(s: str) -> str:
#     n = re.sub(r"[^\w\s-]", "", (s or "")).strip().replace(" ", "_")
#     return n or "NA"


# def scrape_studio_product(url: str, save_dir: Path | None = None) -> dict:
#     # ----- save folder next to this script -----
#     if save_dir is None:
#         save_dir = Path(__file__).resolve().parent / "data1"
#     save_dir.mkdir(parents=True, exist_ok=True)

#     UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#           "AppleWebKit/537.36 (KHTML, like Gecko) "
#           "Chrome/123.0.0.0 Safari/537.36")

#     with sync_playwright() as p:
#         browser = p.chromium.launch(headless=False, args=["--window-position=-32000,-32000"])
#         context = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 900})
#         page = context.new_page()

#         # Load page (no gallery interaction needed)
#         page.goto(url, timeout=90000, wait_until="domcontentloaded")

#         # Best-effort cookie accept
#         for sel in (
#             "#onetrust-accept-btn-handler",
#             "button#onetrust-accept-btn-handler",
#             "button:has-text('Accept All')",
#             "button:has-text('Accept all cookies')",
#             "button:has-text('Accept')",
#         ):
#             try:
#                 page.locator(sel).first.click(timeout=1200)
#                 break
#             except Exception:
#                 pass

#         # -------- NAME --------
#         try:
#             name = _clean(page.locator("#lblProductName").first.inner_text(timeout=6000))
#         except Exception:
#             name = "N/A"

#         # -------- PRICE --------
#         try:
#             raw_price = page.locator("#lblSellingPrice").first.inner_text(timeout=6000)
#             price = _clean(raw_price)
#         except Exception:
#             price = "N/A"

#         # -------- STOCK --------
#         in_stock = None
#         try:
#             stock_blob = " ".join([
#                 page.locator(".stock-level-container-wrapper").first.inner_text(timeout=3000),
#             ])
#             lower = stock_blob.lower()
#             if any(k in lower for k in ["in stock", "running low", "less than", "available"]):
#                 in_stock = True
#             if any(k in lower for k in ["out of stock", "sold out", "unavailable"]):
#                 in_stock = False
#         except Exception:
#             pass

#         # -------- DESCRIPTION --------
#         description = "N/A"
#         try:
#             desc_html = page.locator(".productDescriptionInfoText").first.inner_html(timeout=6000)
#             description = _clean(re.sub(r"<[^>]+>", " ", desc_html))
#         except Exception:
#             pass

#         # -------- IMAGES (hi-res) --------
#         def _to_hires(u: str) -> str:
#             """
#             Normalize Studio image URLs to the hi-res "imgzoom ... _xxl" JPG.
#             Examples:
#               https://www.studio.co.uk/images/imgzoom/88/88647818_xxl_a1.jpg  (already hi-res)
#               https://www.studio.co.uk/images/products/88647818_l_a1.jpg     -> convert to xxl
#             """
#             if not u:
#                 return u

#             if u.startswith("//"):
#                 u = "https:" + u
#             # already imgzoom
#             if "/images/imgzoom/" in u and "_xxl" in u:
#                 # ensure fmt=jpg if any params
#                 parts = list(urlsplit(u))
#                 q = dict(parse_qsl(parts[3], keep_blank_values=True))
#                 q["fmt"] = "jpg"
#                 parts[3] = urlencode(q)
#                 return urlunsplit(parts)

#             # convert products -> imgzoom
#             m = re.search(r"/images/products/(\d{8})_l(_a\d+)?\.jpg", u, re.I)
#             if m:
#                 code = m.group(1)
#                 suf = m.group(2) or ""
#                 return f"https://www.studio.co.uk/images/imgzoom/{code[:2]}/{code}_xxl{suf}.jpg"

#             return u

#         # Get all anchor zoom links (already hi-res)
#         zoom_items = page.evaluate("""() => {
#             return Array.from(document.querySelectorAll('a.zoomMainImage[href]')).map(a => {
#                 const img = a.querySelector('img');
#                 return {
#                     href: a.href,
#                     ctr: img?.dataset?.ctr || a.getAttribute('data-ctr') || ''
#                 };
#             });
#         }""")

#         # Any "view more" background tiles (+3 etc.)
#         bg_urls = page.evaluate("""() => {
#             return Array.from(document.querySelectorAll('.viewMoreImageGrid')).map(el => {
#                 const bg = getComputedStyle(el).backgroundImage || '';
#                 const m = bg.match(/url\\(["']?(.*?)["']?\\)/i);
#                 return m ? m[1] : '';
#             }).filter(Boolean);
#         }""")

#         # Also collect any product images inside the main container as fallbacks
#         product_imgs = page.evaluate("""() => {
#             return Array.from(document.querySelectorAll('.innerImageContainer img')).map(img => img.src || img.currentSrc).filter(Boolean);
#         }""")

#         # Build ordered list: anchors (sorted by ctr), then view-more, then fallbacks
#         def _ctr_key(v):
#             try:
#                 return int(v.get("ctr") or 1_000_000)
#             except Exception:
#                 return 1_000_000

#         ordered = []
#         if zoom_items:
#             for item in sorted(zoom_items, key=_ctr_key):
#                 ordered.append(item.get("href", ""))

#         ordered.extend(bg_urls or [])
#         ordered.extend(product_imgs or [])

#         # Normalize to hi-res, de-dup by base path
#         def _base(u: str) -> str:
#             return re.sub(r"[?].*$", "", u or "")

#         dedup = []
#         seen = set()
#         for u in ordered:
#             hu = _to_hires(u)
#             b = _base(hu)
#             if b and b not in seen:
#                 seen.add(b)
#                 dedup.append(hu)

#         # -------- DOWNLOAD --------
#         folder = save_dir / _safe_name(name)
#         folder.mkdir(parents=True, exist_ok=True)

#         downloaded = []
#         with requests.Session() as s:
#             s.headers.update({
#                 "User-Agent": UA,
#                 "Referer": url,
#                 "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
#             })
#             for i, u in enumerate(dedup, 1):
#                 try:
#                     r = s.get(u, timeout=20)
#                     if r.ok and r.content:
#                         ext = ".jpg"
#                         ct = (r.headers.get("Content-Type") or "").lower()
#                         if "webp" in ct:
#                             ext = ".webp"
#                         elif "png" in ct:
#                             ext = ".png"
#                         path = folder / f"image_{i}{ext}"
#                         path.write_bytes(r.content)
#                         downloaded.append(str(path))
#                 except Exception as e:
#                     print(f"⚠️ Could not download {u}: {e}")

#         browser.close()

#     return {
#         "name": name,
#         "price": price,
#         "in_stock": in_stock,
#         "description": description,
#         "image_count": len(downloaded),
#         "images": downloaded,
#         "folder": str(folder),
#     }







# studio_oxylabs.py
# Python 3.9+
# pip install requests beautifulsoup4 lxml pillow

from __future__ import annotations
import os, re, html, io, json, hashlib, time
from pathlib import Path
from typing import List, Optional, Dict, Any
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, urldefrag

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from PIL import Image

# ---------------------------
# Credentials (prefer .py, else env)
# ---------------------------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = os.getenv("OXY_USER") or os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXY_PASS") or os.getenv("OXYLABS_PASSWORD", "")

if not (OXY_USER and OXY_PASS):
    raise RuntimeError("Oxylabs credentials missing: set OXY_USER/OXY_PASS env or create oxylabs_secrets.py")

# ---------------------------
# Paths / headers
# ---------------------------
try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()

DATA_DIR = BASE_DIR / "data1"
DATA_DIR.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
ACCEPT_LANG = "en-GB,en;q=0.9"

# ---------------------------
# Small helpers
# ---------------------------
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()

def _safe_name(s: str) -> str:
    n = re.sub(r"[^\w\s-]", "", (s or "")).strip().replace(" ", "_")
    return n or "NA"

def _session_with_retries(total=3, backoff=0.7) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=total, connect=total, read=total,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST", "HEAD"])
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=20)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

def _bytes_to_jpg(content: bytes) -> bytes:
    # Convert any image bytes (webp/png) to RGB JPEG bytes
    with Image.open(io.BytesIO(content)) as im:
        im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=90, optimize=True)
        return out.getvalue()

# ---------------------------
# Oxylabs HTML fetch
# ---------------------------
def oxy_fetch_html(url: str, geo: str = "United Kingdom", timeout: int = 90) -> str:
    url, _ = urldefrag(url)
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
        "geo_location": geo,
        "headers": {"User-Agent": UA, "Accept-Language": ACCEPT_LANG},
    }
    sess = _session_with_retries()
    last = None
    for i in range(3):
        try:
            r = sess.post(
                "https://realtime.oxylabs.io/v1/queries",
                auth=(OXY_USER, OXY_PASS),
                json=payload,
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json()
            html_content = (data.get("results") or [{}])[0].get("content", "")
            if "<html" not in html_content.lower():
                raise RuntimeError("Oxylabs returned non-HTML content")
            return html_content
        except Exception as e:
            last = e
            time.sleep(1.5 ** (i + 1))
    raise RuntimeError(f"Oxylabs HTML fetch failed: {last}")

# ---------------------------
# Studio-specific parsing
# ---------------------------
def _to_hires(u: str) -> str:
    """
    Normalize Studio image URLs to the hi-res "imgzoom ... _xxl" JPG.
    Examples:
      https://www.studio.co.uk/images/imgzoom/88/88647818_xxl_a1.jpg  (already hi-res)
      https://www.studio.co.uk/images/products/88647818_l_a1.jpg     -> convert to xxl
    """
    if not u:
        return u
    if u.startswith("//"):
        u = "https:" + u

    # already imgzoom -> ensure fmt=jpg if params present
    if "/images/imgzoom/" in u and "_xxl" in u:
        parts = list(urlsplit(u))
        q = dict(parse_qsl(parts[3], keep_blank_values=True))
        q["fmt"] = "jpg"
        parts[3] = urlencode(q)
        return urlunsplit(parts)

    # convert products -> imgzoom
    m = re.search(r"/images/products/(\d{8})_l(_a\d+)?\.jpg", u, re.I)
    if m:
        code = m.group(1)
        suf = m.group(2) or ""
        return f"https://www.studio.co.uk/images/imgzoom/{code[:2]}/{code}_xxl{suf}.jpg"

    return u

def parse_studio(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    # NAME
    name = "N/A"
    el = soup.select_one("#lblProductName")
    if el:
        name = _clean(el.get_text())

    # PRICE
    price = "N/A"
    pr = soup.select_one("#lblSellingPrice")
    if pr:
        price = _clean(pr.get_text())

    # STOCK
    in_stock = None
    slc = soup.select_one(".stock-level-container-wrapper")
    if slc:
        blob = _clean(slc.get_text(" ", strip=True)).lower()
        if any(k in blob for k in ["in stock", "running low", "less than", "available"]):
            in_stock = True
        if any(k in blob for k in ["out of stock", "sold out", "unavailable"]):
            in_stock = False

    # DESCRIPTION
    description = "N/A"
    desc = soup.select_one(".productDescriptionInfoText")
    if desc:
        # strip tags, tidy
        raw = desc.decode_contents() or ""
        description = _clean(re.sub(r"<[^>]+>", " ", raw))

    # IMAGES (anchors + view-more tiles + fallback imgs)
    # 1) zoom anchors
    imgs: List[str] = []
    for a in soup.select("a.zoomMainImage[href]"):
        href = a.get("href") or ""
        imgs.append(href)

    # 2) “view more” background tiles
    for el in soup.select(".viewMoreImageGrid"):
        style = el.get("style") or ""
        m = re.search(r'url\(["\']?(.*?)["\']?\)', style)
        if m:
            imgs.append(m.group(1))

    # 3) fallbacks inside container
    for img in soup.select(".innerImageContainer img"):
        u = img.get("src") or img.get("data-src") or img.get("currentSrc") or ""
        if u:
            imgs.append(u)

    # Normalize to hires, de-dup by base path
    def _base(u: str) -> str:
        return re.sub(r"[?].*$", "", u or "")

    ordered, seen = [], set()
    for u in imgs:
        hu = _to_hires(u)
        b = _base(hu)
        if b and b not in seen:
            seen.add(b)
            ordered.append(hu)

    return {
        "name": name,
        "price": price,
        "in_stock": in_stock,
        "description": description,
        "image_urls": ordered,
    }

# ---------------------------
# Image download (direct; saves real JPG)
# ---------------------------
def download_images_as_jpg(urls: List[str], folder: Path, referer: str,
                           max_images: Optional[int] = None,
                           keep_original_ext: bool = False) -> List[str]:
    if not urls:
        return []
    if max_images is not None:
        urls = urls[:max_images]

    folder.mkdir(parents=True, exist_ok=True)
    sess = _session_with_retries()

    h = {
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Referer": referer,
    }

    saved, seen_hashes = [], set()
    for i, u in enumerate(urls, 1):
        try:
            r = sess.get(u, headers=h, timeout=30, stream=True)
            r.raise_for_status()
            content = r.content or b""
            if len(content) < 1500:
                continue
            hsh = hashlib.md5(content).hexdigest()
            if hsh in seen_hashes:
                continue
            seen_hashes.add(hsh)

            ct = (r.headers.get("Content-Type") or "").lower()
            if keep_original_ext:
                ext = ".jpg"
                if "webp" in ct or u.lower().endswith(".webp"): ext = ".webp"
                elif "png" in ct or u.lower().endswith(".png"): ext = ".png"
                out = folder / f"image_{i:02d}{ext}"
                out.write_bytes(content)
            else:
                # Force JPEG (transcode if needed)
                out = folder / f"image_{i:02d}.jpg"
                if ("jpeg" in ct or "jpg" in ct) and u.lower().endswith((".jpg", ".jpeg")):
                    # already a JPEG → write raw
                    with open(out, "wb") as f:
                        for chunk in r.iter_content(65536):
                            if chunk: f.write(chunk)
                else:
                    out.write_bytes(_bytes_to_jpg(content))

            saved.append(str(out))
        except Exception as e:
            print(f"  ! image error: {u} ({e})")
    return saved

# ---------------------------
# Public API
# ---------------------------
def scrape_studio_product_with_oxylabs(url: str,
                                       *,
                                       download_images_flag: bool = True,
                                       max_images: Optional[int] = None,
                                       keep_original_ext: bool = False,
                                       geo: str = "United Kingdom") -> Dict[str, Any]:
    html = oxy_fetch_html(url, geo=geo)
    parsed = parse_studio(html)

    folder = DATA_DIR / _safe_name(parsed["name"])
    images_downloaded: List[str] = []
    if download_images_flag and parsed["image_urls"]:
        images_downloaded = download_images_as_jpg(
            parsed["image_urls"], folder, referer=url,
            max_images=max_images, keep_original_ext=keep_original_ext
        )

    return {
        "name": parsed["name"],
        "price": parsed["price"],
        "in_stock": parsed["in_stock"],
        "description": parsed["description"],
        "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
        "images": images_downloaded if images_downloaded else parsed["image_urls"],
        "folder": str(folder),
        "url": url,
        "mode": "oxylabs(html)+direct(images)"
    }

# # ---------------------------
# # CLI
# # ---------------------------
# if __name__ == "__main__":
#     TEST_URL = "https://www.studio.co.uk/view-quest-laura-ashley-2-slice-toaster-776326#colcode=77632618"  
#     print(json.dumps(
#         scrape_studio_product_with_oxylabs(
#             TEST_URL,
#             download_images_flag=True,
#             max_images=20,
#             keep_original_ext=False,  # set True to save original formats
#             geo="United Kingdom"
#         ),
#         indent=2, ensure_ascii=False
#     ))



