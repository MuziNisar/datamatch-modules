

# # ligo_oxylabs.py
# # Python 3.10+
# # pip install requests beautifulsoup4 lxml pillow

# from __future__ import annotations
# import os, re, io, json, time
# from pathlib import Path
# from typing import Dict, Any, List, Optional, Tuple
# from urllib.parse import urlparse, urldefrag

# import requests
# from requests.adapters import HTTPAdapter
# from urllib3.util.retry import Retry
# from bs4 import BeautifulSoup
# from PIL import Image

# # ---------------------------
# # Credentials (from oxylabs_secrets.py or env)
# # ---------------------------
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS  # optional helper file
# except Exception:
#     OXY_USER = os.getenv("OXY_USER") or os.getenv("OXYLABS_USERNAME", "")
#     OXY_PASS = os.getenv("OXY_PASS") or os.getenv("OXYLABS_PASSWORD", "")

# if not (OXY_USER and OXY_PASS):
#     raise RuntimeError("Oxylabs credentials missing: set OXY_USER/OXY_PASS or provide oxylabs_secrets.py")

# # ---------------------------
# # Paths & headers
# # ---------------------------
# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()
# DATA_DIR = BASE_DIR / "data1"
# DATA_DIR.mkdir(parents=True, exist_ok=True)

# UA = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
# )
# ACCEPT_LANG = "en-GB,en;q=0.9"

# # ---------------------------
# # Small helpers
# # ---------------------------
# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "").strip())

# def _safe_name(s: str) -> str:
#     s = _clean(s)
#     return re.sub(r"[^\w.\-]+", "_", s)[:120] or "Unknown_Product"

# def _origin_for(url: str) -> str:
#     p = urlparse(url)
#     return f"{p.scheme}://{p.netloc}"

# def _absolutize(u: str, base: str) -> str:
#     if u.startswith("//"):
#         scheme = urlparse(base).scheme or "https"
#         return f"{scheme}:{u}"
#     if u.startswith("/"):
#         return _origin_for(base) + u
#     return u

# def _parse_gbp(text: str) -> Optional[Tuple[float, str, str]]:
#     if not text:
#         return None
#     m = re.search(r"£\s*([\d.,]+)", text)
#     if not m:
#         return None
#     val = float(m.group(1).replace(",", ""))
#     return val, "GBP", f"{val:.2f} GBP"

# def _session_with_retries(total=3, backoff=0.5) -> requests.Session:
#     s = requests.Session()
#     retry = Retry(
#         total=total,
#         read=total,
#         connect=total,
#         backoff_factor=backoff,
#         status_forcelist=(429, 500, 502, 503, 504),
#         allowed_methods=frozenset(["GET", "POST"])
#     )
#     adapter = HTTPAdapter(max_retries=retry, pool_maxsize=10)
#     s.mount("http://", adapter)
#     s.mount("https://", adapter)
#     return s

# # ---------------------------
# # Oxylabs HTML fetch
# # ---------------------------
# def oxy_fetch_html(url: str, geo: str = "United Kingdom", timeout: int = 90) -> str:
#     url, _ = urldefrag(url)
#     payload = {
#         "source": "universal",
#         "url": url,
#         "render": "html",                # fully-rendered HTML
#         "geo_location": geo,
#         "headers": {"User-Agent": UA, "Accept-Language": ACCEPT_LANG},
#         # "premium": True,               # enable if your plan supports it for tougher pages
#     }
#     sess = _session_with_retries()
#     last = None
#     for i in range(3):
#         try:
#             r = sess.post("https://realtime.oxylabs.io/v1/queries",
#                           auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
#             r.raise_for_status()
#             data = r.json()
#             html = data["results"][0]["content"]
#             if "<html" not in html.lower():
#                 raise RuntimeError("Oxylabs returned non-HTML content")
#             return html
#         except Exception as e:
#             last = e
#             time.sleep(1.5 ** (i + 1))
#     raise RuntimeError(f"Oxylabs HTML fetch failed: {last}")

# # ---------------------------
# # Parsing (ligo.co.uk)
# # ---------------------------
# def parse_ligo(html: str, page_url: str) -> Dict[str, Any]:
#     soup = BeautifulSoup(html, "lxml")

#     # --- Name ---
#     name = None
#     for sel in ["h1.product-info-heading", "h1.page-title > span", "h1"]:
#         el = soup.select_one(sel)
#         if el:
#             name = _clean(el.get_text())
#             break
#     if not name and soup.title:
#         name = _clean(soup.title.get_text().split("|")[0])
#     name = name or "Unknown Product"

#     # --- Price ---
#     price_val = None
#     currency = "GBP"
#     price_str = "N/A"
#     price_source = "none"

#     # JSON-LD first (Magento usually provides)
#     for tag in soup.select("script[type='application/ld+json']"):
#         try:
#             data = json.loads(tag.text or "")
#             arr = data if isinstance(data, list) else [data]
#             for obj in arr:
#                 if isinstance(obj, dict) and obj.get("@type") == "Product":
#                     offers = obj.get("offers")
#                     if isinstance(offers, dict):
#                         offers = [offers]
#                     for off in offers or []:
#                         if "price" in off:
#                             price_val = float(str(off["price"]).replace(",", ""))
#                             price_str = f"{price_val:.2f} {off.get('priceCurrency', 'GBP')}"
#                             price_source = "jsonld"
#                             break
#         except Exception:
#             pass
#         if price_val is not None:
#             break

#     # On-page fallback
#     if price_val is None:
#         el = soup.select_one("span.price-item, span.price, .price-box .price")
#         if not el:
#             el = soup.find(lambda t: t.name in ("span", "div") and t.get_text() and "£" in t.get_text())
#         if el:
#             parsed = _parse_gbp(_clean(el.get_text()))
#             if parsed:
#                 price_val, currency, price_str = parsed
#                 price_source = "onsite"

#     # --- Stock / Availability ---
#     in_stock = None
#     stock_text = ""
#     # Button heuristics
#     btn = soup.select_one("div.product-actions-add-to-cart button, button#product-addtocart-button, button.tocart")
#     if btn:
#         t = _clean(btn.get_text()).lower()
#         if "add to basket" in t or "add to cart" in t or "buy now" in t:
#             in_stock, stock_text = True, t
#         elif any(k in t for k in ["out of stock", "unavailable"]):
#             in_stock, stock_text = False, t
#     if in_stock is None:
#         body = _clean(soup.get_text(" ", strip=True)).lower()
#         if "out of stock" in body:
#             in_stock, stock_text = False, "out of stock"
#         elif "add to cart" in body or "add to basket" in body or "in stock" in body:
#             in_stock, stock_text = True, "in stock (heuristic)"

#     # --- Description ---
#     description = ""
#     for sel in [
#         "div[data-content-type='text']",
#         "div.product__description",
#         "div.product.attribute.description",
#         "div#description",
#         "div.product.info.detailed .data.item.content"
#     ]:
#         el = soup.select_one(sel)
#         if el:
#             description = _clean(el.get_text(" ", strip=True))
#             break
#     if not description:
#         # JSON-LD fallback
#         for tag in soup.select("script[type='application/ld+json']"):
#             try:
#                 data = json.loads(tag.text or "")
#                 arr = data if isinstance(data, list) else [data]
#                 for obj in arr:
#                     if isinstance(obj, dict) and obj.get("@type") == "Product" and obj.get("description"):
#                         description = _clean(obj["description"])
#                         break
#             except Exception:
#                 pass
#         description = description or "N/A"

#     # --- Images (dedup, prefer largest if srcset) ---
#     imgs: List[str] = []
#     seen = set()

#     def _add(u: str):
#         if not u:
#             return
#         u = _absolutize(u, page_url)
#         base = u.split("?")[0]
#         if base not in seen:
#             seen.add(base)
#             imgs.append(u)

#     # Common Magento gallery selectors
#     for im in soup.select("media-gallery img, .fotorama__stage__frame img, .gallery-placeholder img, picture img, img.product-image-photo"):
#         srcset = im.get("srcset") or im.get("data-srcset")
#         if srcset:
#             # pick the widest candidate
#             best_url, best_w = None, -1
#             for part in srcset.split(","):
#                 p = part.strip().split()
#                 u = p[0]
#                 w = 0
#                 if len(p) > 1 and p[1].endswith("w"):
#                     try: w = int(re.sub(r"\D", "", p[1]))
#                     except Exception: w = 0
#                 if w >= best_w:
#                     best_w, best_url = w, u
#             _add(best_url)
#         else:
#             u = im.get("data-src") or im.get("src") or im.get("data-image") or ""
#             # some Magento imgs are protocol-relative or path-relative
#             if u:
#                 _add(u)

#     # Final fallback: any big-ish product-ish images on page
#     if not imgs:
#         for im in soup.select("img[src]"):
#             u = im.get("src")
#             if u and any(k in u.lower() for k in ["product", "catalog", "media", "image", "product", "cache"]):
#                 _add(u)

#     return {
#         "name": name,
#         "price": price_str,
#         "price_value": price_val,
#         "currency": currency,
#         "price_source": price_source,
#         "in_stock": in_stock,
#         "stock_text": stock_text,
#         "description": description,
#         "image_urls": imgs,
#     }

# # ---------------------------
# # Image download (force real JPG)
# # ---------------------------
# def download_images_as_jpg(urls: List[str], folder: Path, referer: str, max_images: Optional[int]=None) -> List[str]:
#     if max_images is not None:
#         urls = urls[:max_images]
#     folder.mkdir(parents=True, exist_ok=True)

#     sess = _session_with_retries()
#     headers = {
#         "User-Agent": UA,
#         "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#         "Accept-Language": ACCEPT_LANG,
#         "Referer": referer,
#     }

#     saved = []
#     for i, u in enumerate(urls, start=1):
#         try:
#             # GET image bytes directly
#             r = sess.get(u, headers=headers, timeout=30, stream=True)
#             r.raise_for_status()
#             data = r.content

#             # Convert to actual JPG (handles webp/png etc. via Pillow)
#             try:
#                 im = Image.open(io.BytesIO(data))
#                 rgb = im.convert("RGB")
#                 out = folder / f"{i:02d}.jpg"
#                 rgb.save(out, format="JPEG", quality=92, optimize=True)
#                 saved.append(str(out))
#             except Exception:
#                 # If PIL fails, still save bytes with .jpg (some browsers serve JPEG already)
#                 out = folder / f"{i:02d}.jpg"
#                 with open(out, "wb") as f:
#                     f.write(data)
#                 saved.append(str(out))
#         except Exception as e:
#             print(f"  ! image error: {u} ({e})")
#     return saved

# # ---------------------------
# # Public API
# # ---------------------------
# def scrape_ligo_with_oxylabs(url: str,
#                              download_images_flag: bool = True,
#                              max_images: Optional[int] = None,
#                              geo: str = "United Kingdom") -> Dict[str, Any]:
#     html = oxy_fetch_html(url, geo=geo)
#     parsed = parse_ligo(html, page_url=url)

#     folder = DATA_DIR / f"ligo_{_safe_name(parsed['name'])}"
#     imgs_local: List[str] = []
#     if download_images_flag and parsed["image_urls"]:
#         imgs_local = download_images_as_jpg(parsed["image_urls"], folder, referer=url, max_images=max_images)

#     return {
#         "name": parsed["name"] or "N/A",
#         "price": parsed["price"] or "N/A",
#         "in_stock": parsed["in_stock"],
#         "stock_text": parsed["stock_text"],
#         "description": parsed["description"] or "N/A",
#         "image_count": len(imgs_local) if imgs_local else len(parsed["image_urls"]),
#         "images": imgs_local if imgs_local else parsed["image_urls"],
#         "folder": str(folder),
#         "mode": "oxylabs-universal",
#         "url": url,
#     }

# # # ---------------------------
# # # CLI test
# # # ---------------------------
# # if __name__ == "__main__":
# #     # Example product (replace with any ligo PDP)
# #     TEST_URL = "https://ligo.co.uk/products/vq-dexter-portable-dab-fm-radio-in-oak?_pos=2&_sid=73049f767&_ss=r"
# #     data = scrape_ligo_with_oxylabs(TEST_URL, download_images_flag=True, max_images=20)
# #     print(json.dumps(data, indent=2, ensure_ascii=False))




# ligo_oxylabs.py
# Python 3.10+
# pip install requests beautifulsoup4 lxml pillow
# Version: 2.0 - Added retry logic for 204 errors and invalid link detection

from __future__ import annotations
import os, re, io, json, time, random
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse, urldefrag

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from PIL import Image

__version__ = "2.0"

# ---------------------------
# Credentials (from oxylabs_secrets.py or env)
# ---------------------------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = os.getenv("OXY_USER") or os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXY_PASS") or os.getenv("OXYLABS_PASSWORD", "")

if not (OXY_USER and OXY_PASS):
    raise RuntimeError("Oxylabs credentials missing: set OXY_USER/OXY_PASS or provide oxylabs_secrets.py")

# ---------------------------
# Paths & headers
# ---------------------------
try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()
DATA_DIR = BASE_DIR / "data1"
DATA_DIR.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
ACCEPT_LANG = "en-GB,en;q=0.9"

# ---------------------------
# Small helpers
# ---------------------------
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _safe_name(s: str) -> str:
    s = _clean(s)
    return re.sub(r"[^\w.\-]+", "_", s)[:120] or "Unknown_Product"


def _origin_for(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _absolutize(u: str, base: str) -> str:
    if u.startswith("//"):
        scheme = urlparse(base).scheme or "https"
        return f"{scheme}:{u}"
    if u.startswith("/"):
        return _origin_for(base) + u
    return u


def _parse_gbp(text: str) -> Optional[Tuple[float, str, str]]:
    if not text:
        return None
    m = re.search(r"£\s*([\d.,]+)", text)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    return val, "GBP", f"{val:.2f} GBP"


def _extract_product_handle_from_url(url: str) -> Optional[str]:
    """Extract product handle/slug from Ligo URL for validation."""
    # URL pattern: https://ligo.co.uk/products/vq-dexter-portable-dab-fm-radio-in-oak
    m = re.search(r"/products/([^/?#]+)", url)
    return m.group(1) if m else None


def _session_with_retries(total=3, backoff=0.5) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=total,
        read=total,
        connect=total,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"])
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=10)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


# ---------------------------
# Oxylabs HTML fetch with RETRY LOGIC
# ---------------------------
def oxy_fetch_html(url: str, geo: str = "United Kingdom", timeout: int = 90, verbose: bool = False) -> str:
    """
    Fetch HTML via Oxylabs with retry logic for 204/400 errors.
    
    Returns HTML on success.
    Raises RuntimeError with "INVALID_PAGE:" prefix if product doesn't exist.
    """
    url, _ = urldefrag(url)
    
    max_attempts = 4
    consecutive_204 = 0
    session_failed_count = 0
    last_err = None
    
    for attempt in range(max_attempts):
        session_id = f"ligo-{int(time.time())}-{random.randint(1000, 9999)}"
        
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
            r = sess.post("https://realtime.oxylabs.io/v1/queries",
                          auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
            
            # Success
            if r.status_code == 200:
                data = r.json()
                try:
                    html = data["results"][0]["content"]
                    if html and "<html" in html.lower() and len(html) > 500:
                        if verbose:
                            print(f"  ✓ Fetched {len(html):,} bytes")
                        return html
                    else:
                        if verbose:
                            print(f"  ⚠ Empty/non-HTML content, retrying...")
                        last_err = RuntimeError("Empty or non-HTML content")
                        time.sleep(2)
                        continue
                except (KeyError, IndexError):
                    last_err = RuntimeError(f"Oxylabs response missing content")
                    time.sleep(2)
                    continue
            
            # HTTP 204 - No Content
            if r.status_code == 204:
                consecutive_204 += 1
                if verbose:
                    print(f"  ⚠ HTTP 204 (No Content) - attempt {consecutive_204}")
                
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
                
                last_err = RuntimeError(f"Oxylabs HTTP 400: {err_msg}")
                time.sleep(2)
                continue
            
            # Other errors
            if r.status_code in (429, 500, 502, 503, 504):
                if verbose:
                    print(f"  ⚠ HTTP {r.status_code}, retrying...")
                last_err = RuntimeError(f"Oxylabs HTTP {r.status_code}")
                time.sleep(3 + attempt * 2)
                continue
            
            last_err = RuntimeError(f"Oxylabs HTTP {r.status_code}: {r.text[:200]}")
            
        except requests.exceptions.Timeout:
            if verbose:
                print(f"  ⚠ Timeout, retrying...")
            last_err = RuntimeError("Oxylabs timeout")
            time.sleep(2)
            continue
        except requests.exceptions.RequestException as e:
            last_err = RuntimeError(f"Request error: {e}")
            time.sleep(2)
            continue
    
    if consecutive_204 >= 2:
        raise RuntimeError("INVALID_PAGE:FETCH_EXHAUSTED_204")
    
    raise last_err or RuntimeError("Oxylabs failed after all attempts")


# ---------------------------
# Invalid Link Detection
# ---------------------------
def _check_invalid_product_page(soup: BeautifulSoup, html: str, url: str, verbose: bool = False) -> Tuple[bool, str]:
    """
    Check if a Ligo product URL has returned an error/listing page instead of PDP.
    
    Ligo is a Shopify-based store. When products are removed:
    - May show 404 page
    - May redirect to collection/search page
    - May show "product not found" message
    
    Returns (is_invalid, reason) tuple.
    """
    html_lower = html.lower()
    body_text = _clean(soup.get_text(" ", strip=True)).lower() if soup.body else ""
    
    # Extract expected product handle from URL
    expected_handle = _extract_product_handle_from_url(url)
    
    # ===== Check 1: 404/Error page indicators =====
    error_patterns = [
        "page not found",
        "404 not found",
        "product not found",
        "sorry, we can't find",
        "this page doesn't exist",
        "no longer available",
        "has been removed",
        "the page you requested does not exist",
        "we couldn't find the page",
    ]
    for pattern in error_patterns:
        if pattern in body_text:
            if verbose:
                print(f"  ⚠ INVALID: Error pattern found - '{pattern}'")
            return True, f"error_message:{pattern[:30]}"
    
    # ===== Check 2: Shopify 404 page template =====
    # Shopify often uses template-404 class or specific 404 elements
    if soup.select_one(".template-404, #shopify-section-404, [class*='page-404']"):
        if verbose:
            print(f"  ⚠ INVALID: Shopify 404 template detected")
        return True, "shopify_404_template"
    
    # ===== Check 3: Collection/listing page (multiple products) =====
    product_cards = soup.select(".product-card, .product-item, [class*='ProductCard'], [class*='product-grid-item']")
    collection_products = soup.select(".collection-product, .grid-product")
    
    total_product_elements = len(product_cards) + len(collection_products)
    if total_product_elements >= 3:
        if verbose:
            print(f"  ⚠ INVALID: Collection page detected ({total_product_elements} products)")
        return True, f"collection_page:{total_product_elements}_products"
    
    # ===== Check 4: Pagination (listing page indicator) =====
    pagination = soup.select_one(".pagination, [class*='Pagination'], nav[aria-label*='page']")
    if pagination:
        # Make sure it's not product image pagination
        if not soup.select_one(".product-single, .product__info, [class*='ProductForm']"):
            if verbose:
                print(f"  ⚠ INVALID: Pagination found without product content")
            return True, "listing_page:pagination_found"
    
    # ===== Check 5: Missing PDP-specific elements =====
    # Ligo/Shopify PDP indicators
    has_product_title = bool(soup.select_one("h1.product-info-heading, h1.page-title, h1.product__title, .product-single__title"))
    has_price = bool(soup.select_one("span.price-item, span.price, .price-box .price, .product__price"))
    has_add_cart = bool(soup.select_one("button#product-addtocart-button, button.tocart, button[name='add'], form[action*='/cart/add']"))
    has_product_images = bool(soup.select_one("media-gallery, .fotorama, .product-single__photos, .product__media"))
    has_product_form = bool(soup.select_one("form.product-form, form[action*='/cart/add'], .product-single__form"))
    
    pdp_indicators = sum([has_product_title, has_price, has_add_cart, has_product_images, has_product_form])
    
    if pdp_indicators < 2:
        if verbose:
            print(f"  ⚠ INVALID: Missing PDP elements (only {pdp_indicators}/5 found)")
            print(f"    - Title: {has_product_title}, Price: {has_price}, AddCart: {has_add_cart}, "
                  f"Images: {has_product_images}, Form: {has_product_form}")
        return True, f"no_pdp_content:{pdp_indicators}_indicators"
    
    # ===== Check 6: Search results page =====
    if soup.select_one(".search-results, #search-results, [class*='SearchResults']"):
        if verbose:
            print(f"  ⚠ INVALID: Search results page detected")
        return True, "search_results_page"
    
    # ===== Check 7: URL handle mismatch =====
    # Check if the page's canonical URL or og:url matches what we requested
    if expected_handle:
        canonical = soup.select_one("link[rel='canonical']")
        og_url = soup.select_one("meta[property='og:url']")
        
        page_url = None
        if canonical and canonical.get("href"):
            page_url = canonical["href"]
        elif og_url and og_url.get("content"):
            page_url = og_url["content"]
        
        if page_url:
            page_handle = _extract_product_handle_from_url(page_url)
            if page_handle and page_handle.lower() != expected_handle.lower():
                # Check if redirected to a different product or collection
                if "/products/" not in page_url.lower():
                    if verbose:
                        print(f"  ⚠ INVALID: Redirected away from product page - {page_url}")
                    return True, f"redirected_to:{page_url[:50]}"
    
    # ===== Check 8: Empty product name would be extracted =====
    name_found = False
    for sel in ["h1.product-info-heading", "h1.page-title > span", "h1.product__title", "h1"]:
        el = soup.select_one(sel)
        if el and _clean(el.get_text()):
            name_found = True
            break
    
    if not name_found:
        # Check JSON-LD
        for tag in soup.select("script[type='application/ld+json']"):
            try:
                data = json.loads(tag.text or "")
                arr = data if isinstance(data, list) else [data]
                for obj in arr:
                    if isinstance(obj, dict) and obj.get("@type") == "Product" and obj.get("name"):
                        name_found = True
                        break
            except Exception:
                pass
        
        if not name_found:
            if verbose:
                print(f"  ⚠ INVALID: No product name found")
            return True, "no_product_name"
    
    return False, "valid"


# ---------------------------
# Parsing (ligo.co.uk)
# ---------------------------
def parse_ligo(html: str, page_url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    # --- Name ---
    name = None
    for sel in ["h1.product-info-heading", "h1.page-title > span", "h1.product__title", "h1"]:
        el = soup.select_one(sel)
        if el:
            name = _clean(el.get_text())
            break
    if not name and soup.title:
        name = _clean(soup.title.get_text().split("|")[0])
    name = name or "Unknown Product"

    # --- Price ---
    price_val = None
    currency = "GBP"
    price_str = "N/A"
    price_source = "none"

    # JSON-LD first
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(tag.text or "")
            arr = data if isinstance(data, list) else [data]
            for obj in arr:
                if isinstance(obj, dict) and obj.get("@type") == "Product":
                    offers = obj.get("offers")
                    if isinstance(offers, dict):
                        offers = [offers]
                    for off in offers or []:
                        if "price" in off:
                            price_val = float(str(off["price"]).replace(",", ""))
                            price_str = f"{price_val:.2f} {off.get('priceCurrency', 'GBP')}"
                            price_source = "jsonld"
                            break
        except Exception:
            pass
        if price_val is not None:
            break

    # On-page fallback
    if price_val is None:
        el = soup.select_one("span.price-item, span.price, .price-box .price, .product__price")
        if not el:
            el = soup.find(lambda t: t.name in ("span", "div") and t.get_text() and "£" in t.get_text())
        if el:
            parsed = _parse_gbp(_clean(el.get_text()))
            if parsed:
                price_val, currency, price_str = parsed
                price_source = "onsite"

    # --- Stock / Availability ---
    in_stock = None
    stock_text = ""
    
    # Button heuristics
    btn = soup.select_one("div.product-actions-add-to-cart button, button#product-addtocart-button, button.tocart, button[name='add']")
    if btn:
        t = _clean(btn.get_text()).lower()
        if "add to basket" in t or "add to cart" in t or "buy now" in t:
            in_stock, stock_text = True, t
        elif any(k in t for k in ["out of stock", "unavailable", "sold out"]):
            in_stock, stock_text = False, t
    
    if in_stock is None:
        body = _clean(soup.get_text(" ", strip=True)).lower()
        if "out of stock" in body or "sold out" in body:
            in_stock, stock_text = False, "out of stock"
        elif "add to cart" in body or "add to basket" in body or "in stock" in body:
            in_stock, stock_text = True, "in stock (heuristic)"

    # --- Description ---
    description = ""
    for sel in [
        "div[data-content-type='text']",
        "div.product__description",
        "div.product.attribute.description",
        "div#description",
        "div.product.info.detailed .data.item.content",
        ".product-single__description",
    ]:
        el = soup.select_one(sel)
        if el:
            description = _clean(el.get_text(" ", strip=True))
            break
    
    if not description:
        for tag in soup.select("script[type='application/ld+json']"):
            try:
                data = json.loads(tag.text or "")
                arr = data if isinstance(data, list) else [data]
                for obj in arr:
                    if isinstance(obj, dict) and obj.get("@type") == "Product" and obj.get("description"):
                        description = _clean(obj["description"])
                        break
            except Exception:
                pass
        description = description or "N/A"

    # --- Images ---
    imgs: List[str] = []
    seen = set()

    def _add(u: str):
        if not u:
            return
        u = _absolutize(u, page_url)
        base = u.split("?")[0]
        if base not in seen:
            seen.add(base)
            imgs.append(u)

    for im in soup.select("media-gallery img, .fotorama__stage__frame img, .gallery-placeholder img, picture img, img.product-image-photo, .product__media img"):
        srcset = im.get("srcset") or im.get("data-srcset")
        if srcset:
            best_url, best_w = None, -1
            for part in srcset.split(","):
                p = part.strip().split()
                u = p[0]
                w = 0
                if len(p) > 1 and p[1].endswith("w"):
                    try: w = int(re.sub(r"\D", "", p[1]))
                    except Exception: w = 0
                if w >= best_w:
                    best_w, best_url = w, u
            _add(best_url)
        else:
            u = im.get("data-src") or im.get("src") or im.get("data-image") or ""
            if u:
                _add(u)

    if not imgs:
        for im in soup.select("img[src]"):
            u = im.get("src")
            if u and any(k in u.lower() for k in ["product", "catalog", "media", "image", "cache"]):
                _add(u)

    return {
        "name": name,
        "price": price_str,
        "price_value": price_val,
        "currency": currency,
        "price_source": price_source,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_urls": imgs,
    }


# ---------------------------
# Image download (force real JPG)
# ---------------------------
def download_images_as_jpg(urls: List[str], folder: Path, referer: str, max_images: Optional[int] = None, verbose: bool = True) -> List[str]:
    if max_images is not None:
        urls = urls[:max_images]
    folder.mkdir(parents=True, exist_ok=True)

    sess = _session_with_retries()
    headers = {
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Referer": referer,
    }

    saved = []
    for i, u in enumerate(urls, start=1):
        try:
            r = sess.get(u, headers=headers, timeout=30, stream=True)
            r.raise_for_status()
            data = r.content

            try:
                im = Image.open(io.BytesIO(data))
                rgb = im.convert("RGB")
                out = folder / f"{i:02d}.jpg"
                rgb.save(out, format="JPEG", quality=92, optimize=True)
                saved.append(str(out))
                if verbose:
                    print(f"  ✓ image {i} ({len(data):,} bytes)")
            except Exception:
                out = folder / f"{i:02d}.jpg"
                with open(out, "wb") as f:
                    f.write(data)
                saved.append(str(out))
        except Exception as e:
            if verbose:
                print(f"  ✗ image {i}: {e}")
    return saved


# ---------------------------
# Public API
# ---------------------------
def scrape_ligo_with_oxylabs(url: str,
                             download_images_flag: bool = True,
                             max_images: Optional[int] = None,
                             geo: str = "United Kingdom",
                             verbose: bool = True) -> Dict[str, Any]:
    if verbose:
        print(f"Fetching {url}...")
    
    # Try to fetch HTML with retry logic
    try:
        html = oxy_fetch_html(url, geo=geo, verbose=verbose)
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
                "mode": "oxylabs-universal",
                "url": url,
                "is_invalid": True,
                "invalid_reason": f"fetch_failed:{reason}"
            }
        
        raise
    
    soup = BeautifulSoup(html, "lxml")
    
    # Check for invalid product page FIRST
    is_invalid, invalid_reason = _check_invalid_product_page(soup, html, url, verbose=verbose)
    
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
            "mode": "oxylabs-universal",
            "url": url,
            "is_invalid": True,
            "invalid_reason": invalid_reason
        }
    
    parsed = parse_ligo(html, page_url=url)

    if verbose:
        print(f"  Name: {parsed['name']}")
        print(f"  Price: {parsed['price']}")
        print(f"  In Stock: {parsed['in_stock']} ({parsed['stock_text']})")
        print(f"  Images found: {len(parsed['image_urls'])}")

    folder = DATA_DIR / f"ligo_{_safe_name(parsed['name'])}"
    imgs_local: List[str] = []
    
    if download_images_flag and parsed["image_urls"]:
        if verbose:
            print(f"\nDownloading {len(parsed['image_urls'])} images...")
        imgs_local = download_images_as_jpg(parsed["image_urls"], folder, referer=url, max_images=max_images, verbose=verbose)

    return {
        "name": parsed["name"] or "N/A",
        "price": parsed["price"] or "N/A",
        "in_stock": parsed["in_stock"],
        "stock_text": parsed["stock_text"],
        "description": parsed["description"] or "N/A",
        "image_count": len(imgs_local) if imgs_local else len(parsed["image_urls"]),
        "images": imgs_local if imgs_local else parsed["image_urls"],
        "folder": str(folder),
        "mode": "oxylabs-universal",
        "url": url,
        "is_invalid": False,
        "invalid_reason": None
    }


# # ---------------------------
# # CLI test
# # ---------------------------
# if __name__ == "__main__":
#     import sys
    
#     if len(sys.argv) > 1:
#         TEST_URL = sys.argv[1]
#     else:
#         TEST_URL = "https://ligo.co.uk/products/vq-dexter-portable-dab-fm-radio-in-oak?_pos=2&_sid=73049f767&_ss=r"
    
#     print(f"\n{'='*60}")
#     print(f"Testing: {TEST_URL}")
#     print(f"{'='*60}\n")
    
#     try:
#         data = scrape_ligo_with_oxylabs(TEST_URL, download_images_flag=True, max_images=20, verbose=True)
#         print("\n" + "=" * 60)
#         print("RESULTS:")
#         print("=" * 60)
#         print(json.dumps(data, indent=2, ensure_ascii=False))
#     except Exception as e:
#         print(f"\n✗ ERROR: {e}")