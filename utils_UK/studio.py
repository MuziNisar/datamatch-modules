
# # studio_oxylabs.py
# # Python 3.9+
# # pip install requests beautifulsoup4 lxml pillow

# from __future__ import annotations
# import os, re, html, io, json, hashlib, time
# from pathlib import Path
# from typing import List, Optional, Dict, Any
# from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, urldefrag

# import requests
# from bs4 import BeautifulSoup
# from requests.adapters import HTTPAdapter
# from urllib3.util.retry import Retry
# from PIL import Image

# # ---------------------------
# # Credentials (prefer .py, else env)
# # ---------------------------
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS
# except Exception:
#     OXY_USER = os.getenv("OXY_USER") or os.getenv("OXYLABS_USERNAME", "")
#     OXY_PASS = os.getenv("OXY_PASS") or os.getenv("OXYLABS_PASSWORD", "")

# if not (OXY_USER and OXY_PASS):
#     raise RuntimeError("Oxylabs credentials missing: set OXY_USER/OXY_PASS env or create oxylabs_secrets.py")

# # ---------------------------
# # Paths / headers
# # ---------------------------
# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()

# DATA_DIR = BASE_DIR / "data1"
# DATA_DIR.mkdir(parents=True, exist_ok=True)

# UA = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#     "AppleWebKit/537.36 (KHTML, like Gecko) "
#     "Chrome/128.0.0.0 Safari/537.36"
# )
# ACCEPT_LANG = "en-GB,en;q=0.9"

# # ---------------------------
# # Small helpers
# # ---------------------------
# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", html.unescape(s or "")).strip()

# def _safe_name(s: str) -> str:
#     n = re.sub(r"[^\w\s-]", "", (s or "")).strip().replace(" ", "_")
#     return n or "NA"

# def _session_with_retries(total=3, backoff=0.7) -> requests.Session:
#     s = requests.Session()
#     retry = Retry(
#         total=total, connect=total, read=total,
#         backoff_factor=backoff,
#         status_forcelist=(429, 500, 502, 503, 504),
#         allowed_methods=frozenset(["GET", "POST", "HEAD"])
#     )
#     adapter = HTTPAdapter(max_retries=retry, pool_maxsize=20)
#     s.mount("http://", adapter)
#     s.mount("https://", adapter)
#     return s

# def _bytes_to_jpg(content: bytes) -> bytes:
#     # Convert any image bytes (webp/png) to RGB JPEG bytes
#     with Image.open(io.BytesIO(content)) as im:
#         im = im.convert("RGB")
#         out = io.BytesIO()
#         im.save(out, format="JPEG", quality=90, optimize=True)
#         return out.getvalue()

# # ---------------------------
# # Oxylabs HTML fetch
# # ---------------------------
# def oxy_fetch_html(url: str, geo: str = "United Kingdom", timeout: int = 90) -> str:
#     url, _ = urldefrag(url)
#     payload = {
#         "source": "universal",
#         "url": url,
#         "render": "html",
#         "geo_location": geo,
#         "headers": {"User-Agent": UA, "Accept-Language": ACCEPT_LANG},
#     }
#     sess = _session_with_retries()
#     last = None
#     for i in range(3):
#         try:
#             r = sess.post(
#                 "https://realtime.oxylabs.io/v1/queries",
#                 auth=(OXY_USER, OXY_PASS),
#                 json=payload,
#                 timeout=timeout,
#             )
#             r.raise_for_status()
#             data = r.json()
#             html_content = (data.get("results") or [{}])[0].get("content", "")
#             if "<html" not in html_content.lower():
#                 raise RuntimeError("Oxylabs returned non-HTML content")
#             return html_content
#         except Exception as e:
#             last = e
#             time.sleep(1.5 ** (i + 1))
#     raise RuntimeError(f"Oxylabs HTML fetch failed: {last}")

# # ---------------------------
# # Studio-specific parsing
# # ---------------------------
# def _to_hires(u: str) -> str:
#     """
#     Normalize Studio image URLs to the hi-res "imgzoom ... _xxl" JPG.
#     Examples:
#       https://www.studio.co.uk/images/imgzoom/88/88647818_xxl_a1.jpg  (already hi-res)
#       https://www.studio.co.uk/images/products/88647818_l_a1.jpg     -> convert to xxl
#     """
#     if not u:
#         return u
#     if u.startswith("//"):
#         u = "https:" + u

#     # already imgzoom -> ensure fmt=jpg if params present
#     if "/images/imgzoom/" in u and "_xxl" in u:
#         parts = list(urlsplit(u))
#         q = dict(parse_qsl(parts[3], keep_blank_values=True))
#         q["fmt"] = "jpg"
#         parts[3] = urlencode(q)
#         return urlunsplit(parts)

#     # convert products -> imgzoom
#     m = re.search(r"/images/products/(\d{8})_l(_a\d+)?\.jpg", u, re.I)
#     if m:
#         code = m.group(1)
#         suf = m.group(2) or ""
#         return f"https://www.studio.co.uk/images/imgzoom/{code[:2]}/{code}_xxl{suf}.jpg"

#     return u

# def parse_studio(html: str) -> Dict[str, Any]:
#     soup = BeautifulSoup(html, "lxml")

#     # NAME
#     name = "N/A"
#     el = soup.select_one("#lblProductName")
#     if el:
#         name = _clean(el.get_text())

#     # PRICE
#     price = "N/A"
#     pr = soup.select_one("#lblSellingPrice")
#     if pr:
#         price = _clean(pr.get_text())

#     # STOCK
#     in_stock = None
#     slc = soup.select_one(".stock-level-container-wrapper")
#     if slc:
#         blob = _clean(slc.get_text(" ", strip=True)).lower()
#         if any(k in blob for k in ["in stock", "running low", "less than", "available"]):
#             in_stock = True
#         if any(k in blob for k in ["out of stock", "sold out", "unavailable"]):
#             in_stock = False

#     # DESCRIPTION
#     description = "N/A"
#     desc = soup.select_one(".productDescriptionInfoText")
#     if desc:
#         # strip tags, tidy
#         raw = desc.decode_contents() or ""
#         description = _clean(re.sub(r"<[^>]+>", " ", raw))

#     # IMAGES (anchors + view-more tiles + fallback imgs)
#     # 1) zoom anchors
#     imgs: List[str] = []
#     for a in soup.select("a.zoomMainImage[href]"):
#         href = a.get("href") or ""
#         imgs.append(href)

#     # 2) “view more” background tiles
#     for el in soup.select(".viewMoreImageGrid"):
#         style = el.get("style") or ""
#         m = re.search(r'url\(["\']?(.*?)["\']?\)', style)
#         if m:
#             imgs.append(m.group(1))

#     # 3) fallbacks inside container
#     for img in soup.select(".innerImageContainer img"):
#         u = img.get("src") or img.get("data-src") or img.get("currentSrc") or ""
#         if u:
#             imgs.append(u)

#     # Normalize to hires, de-dup by base path
#     def _base(u: str) -> str:
#         return re.sub(r"[?].*$", "", u or "")

#     ordered, seen = [], set()
#     for u in imgs:
#         hu = _to_hires(u)
#         b = _base(hu)
#         if b and b not in seen:
#             seen.add(b)
#             ordered.append(hu)

#     return {
#         "name": name,
#         "price": price,
#         "in_stock": in_stock,
#         "description": description,
#         "image_urls": ordered,
#     }

# # ---------------------------
# # Image download (direct; saves real JPG)
# # ---------------------------
# def download_images_as_jpg(urls: List[str], folder: Path, referer: str,
#                            max_images: Optional[int] = None,
#                            keep_original_ext: bool = False) -> List[str]:
#     if not urls:
#         return []
#     if max_images is not None:
#         urls = urls[:max_images]

#     folder.mkdir(parents=True, exist_ok=True)
#     sess = _session_with_retries()

#     h = {
#         "User-Agent": UA,
#         "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#         "Accept-Language": ACCEPT_LANG,
#         "Referer": referer,
#     }

#     saved, seen_hashes = [], set()
#     for i, u in enumerate(urls, 1):
#         try:
#             r = sess.get(u, headers=h, timeout=30, stream=True)
#             r.raise_for_status()
#             content = r.content or b""
#             if len(content) < 1500:
#                 continue
#             hsh = hashlib.md5(content).hexdigest()
#             if hsh in seen_hashes:
#                 continue
#             seen_hashes.add(hsh)

#             ct = (r.headers.get("Content-Type") or "").lower()
#             if keep_original_ext:
#                 ext = ".jpg"
#                 if "webp" in ct or u.lower().endswith(".webp"): ext = ".webp"
#                 elif "png" in ct or u.lower().endswith(".png"): ext = ".png"
#                 out = folder / f"image_{i:02d}{ext}"
#                 out.write_bytes(content)
#             else:
#                 # Force JPEG (transcode if needed)
#                 out = folder / f"image_{i:02d}.jpg"
#                 if ("jpeg" in ct or "jpg" in ct) and u.lower().endswith((".jpg", ".jpeg")):
#                     # already a JPEG → write raw
#                     with open(out, "wb") as f:
#                         for chunk in r.iter_content(65536):
#                             if chunk: f.write(chunk)
#                 else:
#                     out.write_bytes(_bytes_to_jpg(content))

#             saved.append(str(out))
#         except Exception as e:
#             print(f"  ! image error: {u} ({e})")
#     return saved

# # ---------------------------
# # Public API
# # ---------------------------
# def scrape_studio_product_with_oxylabs(url: str,
#                                        *,
#                                        download_images_flag: bool = True,
#                                        max_images: Optional[int] = None,
#                                        keep_original_ext: bool = False,
#                                        geo: str = "United Kingdom") -> Dict[str, Any]:
#     html = oxy_fetch_html(url, geo=geo)
#     parsed = parse_studio(html)

#     folder = DATA_DIR / _safe_name(parsed["name"])
#     images_downloaded: List[str] = []
#     if download_images_flag and parsed["image_urls"]:
#         images_downloaded = download_images_as_jpg(
#             parsed["image_urls"], folder, referer=url,
#             max_images=max_images, keep_original_ext=keep_original_ext
#         )

#     return {
#         "name": parsed["name"],
#         "price": parsed["price"],
#         "in_stock": parsed["in_stock"],
#         "description": parsed["description"],
#         "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
#         "images": images_downloaded if images_downloaded else parsed["image_urls"],
#         "folder": str(folder),
#         "url": url,
#         "mode": "oxylabs(html)+direct(images)"
#     }

# # ---------------------------
# # CLI
# # ---------------------------
# if __name__ == "__main__":
#     TEST_URL = "https://www.studio.co.uk/view-quest-laura-ashley-17l-dome-kettle-886478#colcode=88647818"  
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






# studio_oxylabs.py
# Python 3.9+
# pip install requests beautifulsoup4 lxml pillow
# Version: 2.0 - Added retry logic for 204 errors and invalid link detection

from __future__ import annotations
import os, re, html, io, json, hashlib, time, random
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, urldefrag

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from PIL import Image

__version__ = "2.0"

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
    return n[:100] or "NA"


def _extract_product_id_from_url(url: str) -> Optional[str]:
    """Extract product ID from Studio URL for validation."""
    # URL pattern: /view-quest-laura-ashley-17l-dome-kettle-886478#colcode=88647818
    # The 6-digit number at the end of the path is the product ID
    m = re.search(r'-(\d{6,})(?:#|$|\?)', url)
    return m.group(1) if m else None


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
    with Image.open(io.BytesIO(content)) as im:
        im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=90, optimize=True)
        return out.getvalue()


# ---------------------------
# Oxylabs HTML fetch with RETRY LOGIC
# ---------------------------
def oxy_fetch_html(url: str, geo: str = "United Kingdom", timeout: int = 90, verbose: bool = False) -> str:
    """
    Fetch HTML via Oxylabs with retry logic for 204/400 errors.
    """
    url, _ = urldefrag(url)
    
    max_attempts = 4
    consecutive_204 = 0
    session_failed_count = 0
    last = None
    
    for attempt in range(max_attempts):
        session_id = f"studio-{int(time.time())}-{random.randint(1000, 9999)}"
        
        payload = {
            "source": "universal",
            "url": url,
            "render": "html",
            "geo_location": geo,
            "headers": {"User-Agent": UA, "Accept-Language": ACCEPT_LANG},
            "context": [
                {"key": "session_id", "value": session_id}
            ],
            "rendering_wait": 3000,
        }
        
        if verbose:
            print(f"  Attempt {attempt + 1}/{max_attempts} (session: {session_id})...")
        
        try:
            sess = _session_with_retries()
            r = sess.post(
                "https://realtime.oxylabs.io/v1/queries",
                auth=(OXY_USER, OXY_PASS),
                json=payload,
                timeout=timeout,
            )
            
            # Success
            if r.status_code == 200:
                data = r.json()
                html_content = (data.get("results") or [{}])[0].get("content", "")
                
                if html_content and "<html" in html_content.lower() and len(html_content) > 500:
                    if verbose:
                        print(f"  ✓ Fetched {len(html_content):,} bytes")
                    return html_content
                else:
                    if verbose:
                        print(f"  ⚠ Empty/non-HTML content, retrying...")
                    last = RuntimeError("Empty or non-HTML content")
                    time.sleep(2)
                    continue
            
            # HTTP 204 - No Content
            if r.status_code == 204:
                consecutive_204 += 1
                if verbose:
                    print(f"  ⚠ HTTP 204 (No Content) - count {consecutive_204}")
                
                if consecutive_204 >= 3:
                    raise RuntimeError("INVALID_PAGE:HTTP_204_REPEATED")
                
                time.sleep(2 + attempt)
                continue
            
            # HTTP 400 - Session failed
            if r.status_code == 400:
                try:
                    err_data = r.json()
                    err_msg = err_data.get("message", "")
                except Exception:
                    err_msg = r.text[:200]
                
                if "failed" in err_msg.lower() or "session" in err_msg.lower():
                    session_failed_count += 1
                    if verbose:
                        print(f"  ⚠ Session failed: {err_msg[:60]}")
                    
                    if consecutive_204 > 0 and session_failed_count >= 2:
                        raise RuntimeError("INVALID_PAGE:SESSION_FAILED_AFTER_204")
                    
                    time.sleep(3)
                    continue
                
                raise RuntimeError(f"Oxylabs HTTP 400: {err_msg}")
            
            # Other errors
            r.raise_for_status()
            
        except RuntimeError as e:
            if "INVALID_PAGE:" in str(e):
                raise
            last = e
            if attempt < max_attempts - 1:
                time.sleep(1.5 ** (attempt + 1))
            continue
        except Exception as e:
            last = e
            if attempt < max_attempts - 1:
                time.sleep(1.5 ** (attempt + 1))
            continue
    
    if consecutive_204 >= 2:
        raise RuntimeError("INVALID_PAGE:FETCH_EXHAUSTED_204")
    
    raise RuntimeError(f"Oxylabs HTML fetch failed: {last}")


# ---------------------------
# Invalid Link Detection
# ---------------------------
def _check_invalid_product_page(soup: BeautifulSoup, html_doc: str, url: str, verbose: bool = False) -> Tuple[bool, str]:
    """
    Check if a Studio product URL has returned an error/listing page instead of PDP.
    
    Studio invalid page indicators:
    - "Sorry – this page could not be found" error page
    - .error-main div
    - Missing product elements (#lblProductName, #lblSellingPrice)
    
    Returns (is_invalid, reason) tuple.
    """
    html_lower = html_doc.lower()
    body_text = _clean(soup.get_text(" ", strip=True)).lower() if soup.body else ""
    
    # ===== Check 1: Error page div (MOST RELIABLE for Studio) =====
    error_main = soup.select_one(".error-main, #error-main, .error-page")
    if error_main:
        error_text = _clean(error_main.get_text(" ", strip=True)).lower()
        if "could not be found" in error_text or "page not found" in error_text or "no longer exists" in error_text:
            if verbose:
                print(f"  ⚠ INVALID: Error page div found - '{error_text[:60]}'")
            return True, "error_page_not_found"
    
    # ===== Check 2: Error message patterns in page text =====
    error_patterns = [
        "sorry – this page could not be found",
        "sorry - this page could not be found",
        "this page could not be found",
        "page not found",
        "404",
        "no longer exists",
        "product not found",
        "we can't find",
        "the page you were after no longer exists",
    ]
    for pattern in error_patterns:
        if pattern in body_text:
            if verbose:
                print(f"  ⚠ INVALID: Error pattern found - '{pattern}'")
            return True, f"error_message:{pattern[:30]}"
    
    # ===== THEN: Check if this looks like a valid PDP =====
    # Studio PDP indicators
    has_product_name = bool(soup.select_one("#lblProductName"))
    has_product_price = bool(soup.select_one("#lblSellingPrice"))
    has_stock_container = bool(soup.select_one(".stock-level-container-wrapper"))
    has_product_description = bool(soup.select_one(".productDescriptionInfoText"))
    has_zoom_images = bool(soup.select("a.zoomMainImage[href]"))
    has_image_container = bool(soup.select_one(".innerImageContainer"))
    
    pdp_indicators = sum([has_product_name, has_product_price, has_stock_container, 
                          has_product_description, has_zoom_images, has_image_container])
    
    # If we have strong PDP indicators (3+), this is likely a valid product page
    if pdp_indicators >= 3:
        if verbose:
            print(f"  ✓ Valid PDP detected ({pdp_indicators}/6 indicators)")
        return False, "valid"
    
    # ===== Check 3: Listing/category page (multiple products) =====
    if pdp_indicators < 2:
        product_cards = soup.select(".product-card, .product-tile, [class*='ProductCard'], .product-item")
        product_links = soup.select("a[href*='/view-'][href$='.html'], a[href*='product']")
        
        if len(product_cards) >= 4 or len(product_links) >= 6:
            if verbose:
                print(f"  ⚠ INVALID: Listing page detected ({len(product_cards)} cards, {len(product_links)} links)")
            return True, f"listing_page:{len(product_cards)}_products"
    
    # ===== Check 4: Pagination =====
    if pdp_indicators < 2:
        pagination = soup.select_one(".pagination, [class*='Pagination'], .pager")
        if pagination:
            if verbose:
                print(f"  ⚠ INVALID: Pagination found (listing page)")
            return True, "listing_page:pagination_found"
    
    # ===== Check 5: Missing PDP-specific elements =====
    if pdp_indicators < 2:
        if verbose:
            print(f"  ⚠ INVALID: Missing PDP elements (only {pdp_indicators}/6 found)")
            print(f"    - ProductName: {has_product_name}, Price: {has_product_price}, Stock: {has_stock_container}, "
                  f"Description: {has_product_description}, ZoomImages: {has_zoom_images}, ImageContainer: {has_image_container}")
        return True, f"no_pdp_content:{pdp_indicators}_indicators"
    
    # ===== Check 6: Product name would be "N/A" =====
    name_el = soup.select_one("#lblProductName")
    if not name_el or not _clean(name_el.get_text()):
        if verbose:
            print(f"  ⚠ INVALID: No product name found")
        return True, "no_product_name"
    
    return False, "valid"


# ---------------------------
# Studio-specific parsing
# ---------------------------
def _to_hires(u: str) -> str:
    """
    Normalize Studio image URLs to the hi-res "imgzoom ... _xxl" JPG.
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


def parse_studio(html_doc: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html_doc, "lxml")

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
    stock_text = "unknown"
    slc = soup.select_one(".stock-level-container-wrapper")
    if slc:
        blob = _clean(slc.get_text(" ", strip=True)).lower()
        stock_text = blob
        if any(k in blob for k in ["in stock", "running low", "less than", "available"]):
            in_stock = True
        if any(k in blob for k in ["out of stock", "sold out", "unavailable"]):
            in_stock = False

    # DESCRIPTION
    description = "N/A"
    desc = soup.select_one(".productDescriptionInfoText")
    if desc:
        raw = desc.decode_contents() or ""
        description = _clean(re.sub(r"<[^>]+>", " ", raw))

    # IMAGES
    imgs: List[str] = []
    
    # 1) zoom anchors
    for a in soup.select("a.zoomMainImage[href]"):
        href = a.get("href") or ""
        imgs.append(href)

    # 2) "view more" background tiles
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

    # Normalize to hires, de-dup
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
        "stock_text": stock_text,
        "description": description,
        "image_urls": ordered,
    }


# ---------------------------
# Image download
# ---------------------------
def download_images_as_jpg(urls: List[str], folder: Path, referer: str,
                           max_images: Optional[int] = None,
                           keep_original_ext: bool = False,
                           verbose: bool = True) -> List[str]:
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
                if "webp" in ct or u.lower().endswith(".webp"):
                    ext = ".webp"
                elif "png" in ct or u.lower().endswith(".png"):
                    ext = ".png"
                out = folder / f"image_{i:02d}{ext}"
                out.write_bytes(content)
            else:
                out = folder / f"image_{i:02d}.jpg"
                if ("jpeg" in ct or "jpg" in ct) and u.lower().endswith((".jpg", ".jpeg")):
                    with open(out, "wb") as f:
                        for chunk in r.iter_content(65536):
                            if chunk:
                                f.write(chunk)
                else:
                    out.write_bytes(_bytes_to_jpg(content))

            saved.append(str(out))
            if verbose:
                print(f"  ✓ image {i}")
                
        except Exception as e:
            if verbose:
                print(f"  ✗ image {i}: {e}")
    
    return saved


# ---------------------------
# Public API
# ---------------------------
def scrape_studio_product_with_oxylabs(url: str,
                                       *,
                                       download_images_flag: bool = True,
                                       max_images: Optional[int] = None,
                                       keep_original_ext: bool = False,
                                       geo: str = "United Kingdom",
                                       verbose: bool = True) -> Dict[str, Any]:
    if verbose:
        print(f"Fetching {url}...")
    
    # Try to fetch HTML with retry logic
    try:
        html_doc = oxy_fetch_html(url, geo=geo, verbose=verbose)
    except RuntimeError as e:
        err_str = str(e)
        
        if "INVALID_PAGE:" in err_str:
            reason = err_str.split("INVALID_PAGE:")[-1]
            if verbose:
                print(f"✗ Invalid link detected (fetch failed): {reason}")
            
            return {
                "name": "INVALID LINK - Product removed or no longer available",
                "price": "N/A",
                "in_stock": False,
                "stock_text": f"fetch_failed:{reason}",
                "description": "",
                "image_count": 0,
                "images": [],
                "folder": None,
                "url": url,
                "mode": "oxylabs(html)+direct(images)",
                "is_invalid": True,
                "invalid_reason": f"fetch_failed:{reason}"
            }
        
        raise
    
    soup = BeautifulSoup(html_doc, "lxml")
    
    # Check for invalid product page FIRST
    is_invalid, invalid_reason = _check_invalid_product_page(soup, html_doc, url, verbose=verbose)
    
    if is_invalid:
        if verbose:
            print(f"✗ Invalid link detected: {invalid_reason}")
        
        return {
            "name": "INVALID LINK - Product removed or no longer available",
            "price": "N/A",
            "in_stock": False,
            "stock_text": invalid_reason,
            "description": "",
            "image_count": 0,
            "images": [],
            "folder": None,
            "url": url,
            "mode": "oxylabs(html)+direct(images)",
            "is_invalid": True,
            "invalid_reason": invalid_reason
        }
    
    parsed = parse_studio(html_doc)

    if verbose:
        print(f"  Name: {parsed['name']}")
        print(f"  Price: {parsed['price']}")
        print(f"  In Stock: {parsed['in_stock']} ({parsed['stock_text']})")
        print(f"  Images found: {len(parsed['image_urls'])}")

    folder = DATA_DIR / _safe_name(parsed["name"])
    images_downloaded: List[str] = []
    
    if download_images_flag and parsed["image_urls"]:
        if verbose:
            print(f"\nDownloading {len(parsed['image_urls'])} images...")
        images_downloaded = download_images_as_jpg(
            parsed["image_urls"], folder, referer=url,
            max_images=max_images, keep_original_ext=keep_original_ext,
            verbose=verbose
        )

    return {
        "name": parsed["name"],
        "price": parsed["price"],
        "in_stock": parsed["in_stock"],
        "stock_text": parsed["stock_text"],
        "description": parsed["description"],
        "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
        "images": images_downloaded if images_downloaded else parsed["image_urls"],
        "folder": str(folder),
        "url": url,
        "mode": "oxylabs(html)+direct(images)",
        "is_invalid": False,
        "invalid_reason": None
    }


# # ---------------------------
# # CLI
# # ---------------------------
# if __name__ == "__main__":
#     import sys
    
#     if len(sys.argv) > 1:
#         TEST_URL = sys.argv[1]
#     else:
#         TEST_URL = "https://www.studio.co.uk/view-quest-laura-ashley-2-slice-toaster-776326#colcode=77632618"
    
#     print(f"\n{'='*60}")
#     print(f"Testing: {TEST_URL}")
#     print(f"{'='*60}\n")
    
#     try:
#         data = scrape_studio_product_with_oxylabs(
#             TEST_URL,
#             download_images_flag=True,
#             max_images=20,
#             keep_original_ext=False,
#             geo="United Kingdom",
#             verbose=True
#         )
#         print("\n" + "=" * 60)
#         print("RESULTS:")
#         print("=" * 60)
#         print(json.dumps(data, indent=2, ensure_ascii=False))
#     except Exception as e:
#         print(f"\n✗ ERROR: {e}")