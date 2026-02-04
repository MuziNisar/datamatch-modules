





# # frasers.py
# # Python 3.10+
# # pip install requests beautifulsoup4 lxml pillow

# import os, re, io, json, time, random
# from pathlib import Path
# from urllib.parse import urlparse
# import requests
# from bs4 import BeautifulSoup
# from PIL import Image

# # ---------- Paths ----------
# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()
# SAVE_ROOT = BASE_DIR / "data_houseoffraser"
# SAVE_ROOT.mkdir(parents=True, exist_ok=True)

# # ---------- Headers & HTTP ----------
# def get_random_headers():
#     uas = [
#         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
#         "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
#         "Mozilla/5.0 (Linux; Android 14; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36",
#         "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
#     ]
#     return {
#         "User-Agent": random.choice(uas),
#         "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
#         "Accept-Language": "en-GB,en;q=0.9",
#         "Referer": "https://www.google.com/",
#         "Connection": "keep-alive",
#         "Upgrade-Insecure-Requests": "1",
#     }

# def robust_get(session: requests.Session, url: str, timeout: int = 25, max_retries: int = 3) -> requests.Response:
#     last_exc = None
#     for attempt in range(max_retries):
#         try:
#             r = session.get(url, timeout=timeout)
#             r.raise_for_status()
#             return r
#         except requests.exceptions.RequestException as e:
#             last_exc = e
#             if attempt < max_retries - 1:
#                 time.sleep(1.5 * (attempt + 1))
#                 session.headers.update(get_random_headers())
#             else:
#                 raise
#     raise last_exc

# # ---------- Helpers ----------
# def _clean(s: str) -> str:
#     s = re.sub(r"\s+", " ", (s or "").strip())
#     return s

# def _safe_name(name: str) -> str:
#     n = re.sub(r"[^\w\s-]", "", name or "").strip()
#     n = re.sub(r"\s+", "_", n)
#     return n or "Unknown_Product"

# def _retailer_slug(url: str) -> str:
#     host = urlparse(url).netloc.lower()
#     host = re.sub(r"^www\.", "", host)
#     return (host.split(".")[0] or "site")

# def _stable_id_from_url(url: str) -> str:
#     m = re.search(r"(\d{6,})", url)
#     return m.group(1) if m else "na"

# def _jsonld_first(soup: BeautifulSoup, type_name: str):
#     for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
#         try:
#             data = json.loads(tag.string or "")
#         except Exception:
#             continue
#         objs = data if isinstance(data, list) else [data]
#         for obj in objs:
#             if obj.get("@type") == type_name:
#                 return obj
#     return None

# def _extract_price(soup: BeautifulSoup):
#     # Prefer <p data-testid="price" data-testvalue="6999"><span>£69.99</span></p>
#     p = soup.select_one("p[data-testid='price']")
#     if p:
#         # Try attribute first for numeric cents
#         val = p.get("data-testvalue")
#         if val and val.isdigit():
#             try:
#                 pennies = int(val)
#                 if pennies > 0:
#                     return f"{pennies/100:.2f} GBP", "price-testid-attr"
#             except Exception:
#                 pass
#         # Fallback to visible span text
#         txt = _clean(p.get_text(" ", strip=True))
#         m = re.search(r"(£\s?\d[\d,]*(?:\.\d{2})?)", txt)
#         if m:
#             return m.group(1).replace(" ", "") + " GBP", "price-testid-text"

#     # Secondary fallbacks
#     metas = soup.select("meta[itemprop='price'], [itemprop='price']")
#     for el in metas:
#         txt = _clean(el.get("content") or el.get_text(" ", strip=True))
#         m = re.search(r"(\d[\d,]*(?:\.\d{2})?)", txt)
#         if m:
#             return f"{m.group(1)} GBP", "itemprop"

#     body_price = _clean(soup.get_text(" ", strip=True))
#     m = re.search(r"(£\s?\d[\d,]*(?:\.\d{2})?)", body_price)
#     if m:
#         return m.group(1).replace(" ", "") + " GBP", "body"

#     return "N/A", "none"

# def _extract_name(soup: BeautifulSoup):
#     for sel in ("h1", "[data-testid='pdp-title']", "[class*='ProductTitle']", "[class*='pdpTitle']"):
#         el = soup.select_one(sel)
#         if el:
#             txt = _clean(el.get_text(" ", strip=True))
#             if txt:
#                 return txt
#     # JSON-LD product name
#     jld = _jsonld_first(soup, "Product")
#     if jld and jld.get("name"):
#         return _clean(jld["name"])
#     return "Unknown Product"

# def _extract_description(soup: BeautifulSoup) -> str:
#     def _clean_spaces(s: str) -> str:
#         return re.sub(r"\s+", " ", (s or "").strip())

#     def _strip_product_code(txt: str) -> str:
#         return re.sub(r"^Product code:\s*\S+\s*", "", txt, flags=re.I)

#     # 1) JSON-LD
#     jld = _jsonld_first(soup, "Product")
#     if jld:
#         jld_desc = _clean_spaces(jld.get("description") or "")
#         if jld_desc and len(jld_desc) > 60:
#             return _strip_product_code(jld_desc)

#     # 2) Open accordion → data-testid="description"
#     for sel in (
#         "[data-testid='accordion-content'] [data-testid='description']",
#         "[data-testid='description']",
#     ):
#         root = soup.select_one(sel)
#         if root:
#             span = root.select_one(
#                 ".ProductDetails_description__hX1PR, [class*='ProductDetails_description'] span, [class*='ProductDetails_description']"
#             )
#             if span:
#                 txt = _clean_spaces(span.get_text(" ", strip=True))
#                 if txt:
#                     return _strip_product_code(txt)
#             txt = _clean_spaces(root.get_text(" ", strip=True))
#             if txt:
#                 return _strip_product_code(txt)

#     # 3) Broader fallbacks
#     for sel in (
#         "[class*='ProductDetails_description']",
#         "[data-testid='accordion-content'] [class*='ProductDetails_root']",
#         "[class*='ProductDetails_root']",
#     ):
#         el = soup.select_one(sel)
#         if el:
#             txt = _clean_spaces(el.get_text(" ", strip=True))
#             if txt:
#                 return _strip_product_code(txt)

#     # 4) Meta description
#     meta = soup.select_one("meta[name='description']")
#     if meta and meta.get("content"):
#         txt = _clean_spaces(meta["content"])
#         if len(txt) > 60:
#             return _strip_product_code(txt)

#     return "N/A"

# def _extract_stock(soup: BeautifulSoup):
#     # Presence of purchase button implies purchasable (in stock / addable)
#     btn = soup.select_one("button[data-testid='purchase-button']")
#     if btn:
#         return True, "purchase-button"
#     # JSON-LD availability
#     jld = _jsonld_first(soup, "Product")
#     if jld:
#         offers = jld.get("offers")
#         offers = offers if isinstance(offers, list) else [offers] if offers else []
#         for off in offers:
#             avail = str(off.get("availability") or off.get("itemAvailability") or "")
#             if re.search(r"InStock", avail, re.I):
#                 return True, "jsonld"
#             if re.search(r"OutOfStock|SoldOut", avail, re.I):
#                 return False, "jsonld"
#     # Unknown
#     return True if btn else False, "Unknown"

# def _desired_gallery_urls(soup: BeautifulSoup):
#     """
#     Only the main 7 images in order:
#       .../77632618_o, ..._o_a2, ..._o_a3, ..._o_a4, ..._o_a5, ..._o_a6, ..._o_a7
#     We build from the thumbs carousel to keep the exact order, then force fmt=jpg & 1500x1500.
#     """
#     thumbs = []
#     # Take the thumbnail <img> sources under the thumbs carousel
#     for img in soup.select(".ImageGallery_thumbsContainer img[src]"):
#         src = img.get("src") or ""
#         if "cdn.media.amplience.net/i/frasersdev/" not in src:
#             continue
#         # Only keep the main product images, skip badges, etc.
#         # These start with ".../{code}_o" or ".../{code}_o_aX"
#         if re.search(r"/\d+_o(?:_a[2-7])?\?", src):
#             thumbs.append(src)

#     # Deduplicate keeping order
#     seen = set()
#     ordered = []
#     for u in thumbs:
#         # normalize to jpg, 1500x1500
#         u = re.sub(r"\?(.*)$", "", u)  # strip existing query
#         u = u + "?fmt=jpg&upscale=true&w=1500&h=1500&sm=scaleFit"
#         if u not in seen:
#             seen.add(u)
#             ordered.append(u)

#     # If page structure changes, try a deterministic pattern fallback from first base
#     if not ordered:
#         # Try to guess the base from any amplience image present
#         any_img = soup.select_one("img[src*='cdn.media.amplience.net/i/frasersdev/']")
#         if any_img:
#             base = re.sub(r"\?.*$", "", any_img["src"])
#             m = re.search(r"(https://cdn\.media\.amplience\.net/i/frasersdev/\d+)_", base)
#             if m:
#                 code = m.group(1)
#                 candidates = [code + "_o"] + [f"{code}_o_a{i}" for i in range(2, 8)]
#                 ordered = [f"{c}?fmt=jpg&upscale=true&w=1500&h=1500&sm=scaleFit" for c in candidates]

#     # Cap to 7 (o + a2..a7)
#     return ordered[:7]

# def _download_images_jpg(urls, folder: Path, session: requests.Session):
#     folder.mkdir(parents=True, exist_ok=True)
#     out_files = []
#     for i, u in enumerate(urls, start=1):
#         try:
#             r = robust_get(session, u, timeout=30)
#             content = r.content
#             # Save as JPG explicitly (convert if not JPG)
#             ext = ".jpg"
#             # Try decoding via PIL and re-encode to JPG to guarantee extension/content alignment
#             try:
#                 im = Image.open(io.BytesIO(content))
#                 rgb = im.convert("RGB")
#                 fp = folder / f"{i:02d}{ext}"
#                 rgb.save(fp, format="JPEG", quality=92, optimize=True)
#                 out_files.append(str(fp))
#             except Exception:
#                 # In case PIL can't decode, just write raw with .jpg
#                 fp = folder / f"{i:02d}{ext}"
#                 with open(fp, "wb") as f:
#                     f.write(content)
#                 out_files.append(str(fp))
#         except Exception:
#             print(f"  ! image error: {u}")
#     return out_files

# # ---------- Main ----------
# def fetch_product_houseoffraser(url: str):
#     session = requests.Session()
#     session.headers.update(get_random_headers())
#     resp = robust_get(session, url, timeout=25)
#     soup = BeautifulSoup(resp.text, "lxml")

#     name = _extract_name(soup)
#     price, price_source = _extract_price(soup)
#     in_stock, stock_text = _extract_stock(soup)
#     description = _extract_description(soup)

#     # Images
#     image_urls = _desired_gallery_urls(soup)
#     print(f"Downloading {len(image_urls)} images …")
#     folder = SAVE_ROOT / f"{_retailer_slug(url)}_{_safe_name(name)}_{_stable_id_from_url(url)}"
#     images_downloaded = _download_images_jpg(image_urls, folder, session)

#     result = {
#         "url": url,
#         "name": name,
#         "price": price,
#         "price_source": price_source,
#         "in_stock": in_stock,
#         "stock_text": stock_text,
#         "description": description,
#         "image_count": len(image_urls),
#         "image_urls": image_urls,
#         "images_downloaded": images_downloaded,
#         "folder": str(folder),
#         "mode": "oxylabs-universal",
#     }
#     return result

# if __name__ == "__main__":
#     test_url = "https://www.houseoffraser.co.uk/brand/view-quest/laura-ashley-4-slice-toaster-china-rose-426943#colcode=42694301"
#     data = fetch_product_houseoffraser(test_url)
#     print(json.dumps(data, indent=2, ensure_ascii=False))



# frasers.py
# Python 3.10+
# pip install requests beautifulsoup4 lxml pillow
# Version: 2.1 - Added invalid link detection

import os, re, io, json, time, random
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from PIL import Image

__version__ = "2.1"

# ---------- Paths ----------
try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()
SAVE_ROOT = BASE_DIR / "data_houseoffraser"
SAVE_ROOT.mkdir(parents=True, exist_ok=True)

# ---------- Headers & HTTP ----------
def get_random_headers():
    uas = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Mozilla/5.0 (Linux; Android 14; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    ]
    return {
        "User-Agent": random.choice(uas),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

def robust_get(session: requests.Session, url: str, timeout: int = 25, max_retries: int = 3) -> Tuple[requests.Response, Optional[str]]:
    """
    Returns (response, error_reason) tuple.
    If successful: (response, None)
    If failed: (response or None, error_reason)
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            r = session.get(url, timeout=timeout)
            
            # Check for HTTP errors but don't raise - return them for handling
            if r.status_code == 404:
                return r, "http_404"
            elif r.status_code == 410:
                return r, "http_410_gone"
            elif r.status_code >= 400:
                return r, f"http_{r.status_code}"
            
            return r, None
            
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(1.5 * (attempt + 1))
                session.headers.update(get_random_headers())
            else:
                return None, f"request_failed:{str(e)[:50]}"
    
    return None, f"request_failed:{str(last_exc)[:50]}"

# ---------- Helpers ----------
def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s

def _safe_name(name: str) -> str:
    n = re.sub(r"[^\w\s-]", "", name or "").strip()
    n = re.sub(r"\s+", "_", n)
    return n[:100] or "Unknown_Product"

def _retailer_slug(url: str) -> str:
    host = urlparse(url).netloc.lower()
    host = re.sub(r"^www\.", "", host)
    return (host.split(".")[0] or "site")

def _stable_id_from_url(url: str) -> str:
    m = re.search(r"(\d{6,})", url)
    return m.group(1) if m else "na"

def _jsonld_first(soup: BeautifulSoup, type_name: str):
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if obj.get("@type") == type_name:
                return obj
    return None


# ---------------------------
# Invalid Link Detection
# ---------------------------
def _check_invalid_product_page(soup: BeautifulSoup, html: str, url: str, http_error: Optional[str] = None, verbose: bool = False) -> Tuple[bool, str]:
    """
    Check if a House of Fraser product URL has returned an error/removed page.
    Returns (is_invalid, reason) tuple.
    """
    # Check 1: HTTP error already detected
    if http_error:
        if verbose:
            print(f"  ⚠ INVALID: HTTP error - {http_error}")
        return True, http_error
    
    if not soup or not html:
        return True, "empty_response"
    
    body_text = _clean(soup.get_text(" ", strip=True)).lower() if soup.body else ""
    
    # Check 2: Error page elements (404 page structure)
    error_selectors = [
        "[data-testid='error-view']",
        "[data-testid='404-title']",
        ".ErrorView_container__",
        "[class*='ErrorView']",
        ".error-page",
        "#error-page",
        ".not-found",
        "#not-found",
    ]
    for sel in error_selectors:
        el = soup.select_one(sel)
        if el:
            if verbose:
                print(f"  ⚠ INVALID: Error page element found - '{sel}'")
            return True, f"error_element:{sel}"
    
    # Check 3: 404/error page text indicators
    error_patterns = [
        "page could not be found",
        "page not found",
        "product not found",
        "sorry, we can't find",
        "this page doesn't exist",
        "this product is no longer available",
        "has been removed",
        "no longer available",
        "no longer exists",
        "404",
    ]
    for pattern in error_patterns:
        if pattern in body_text:
            if verbose:
                print(f"  ⚠ INVALID: Error pattern found - '{pattern}'")
            return True, f"error_message:{pattern[:30]}"
    
    # Check 4: Category/listing page detection
    plp_selectors = [
        "[data-testid='plp-results']",
        "[data-testid='product-listing']",
        "[class*='ProductListing']",
        "[class*='CategoryPage']",
    ]
    for sel in plp_selectors:
        el = soup.select_one(sel)
        if el:
            if verbose:
                print(f"  ⚠ INVALID: Category/listing page detected - '{sel}'")
            return True, f"category_page:{sel}"
    
    # Check 5: Multiple product cards (listing page)
    product_cards = soup.select("[data-testid*='product-card'], [class*='ProductCard'], .product-tile")
    if len(product_cards) >= 3:
        # Check if we're missing PDP elements
        has_pdp_title = bool(soup.select_one("h1, [data-testid='pdp-title']"))
        has_purchase_btn = bool(soup.select_one("button[data-testid='purchase-button']"))
        has_gallery = bool(soup.select_one(".ImageGallery_thumbsContainer, [class*='ImageGallery']"))
        
        if not (has_purchase_btn or has_gallery):
            if verbose:
                print(f"  ⚠ INVALID: Multiple product cards found ({len(product_cards)}), no PDP elements")
            return True, f"product_grid:{len(product_cards)}_items"
    
    # Check 6: Search results page
    if "/search?" in url.lower() or "search results" in body_text:
        if verbose:
            print(f"  ⚠ INVALID: Search results page")
        return True, "search_results_page"
    
    # Check 7: No product content at all
    has_name = bool(soup.select_one('h1, [data-testid="pdp-title"], [class*="ProductTitle"]'))
    has_price = bool(soup.select_one("[data-testid='price'], [itemprop='price']"))
    has_purchase_btn = bool(soup.select_one("button[data-testid='purchase-button']"))
    has_images = bool(soup.select_one(".ImageGallery_thumbsContainer, [class*='ImageGallery']"))
    
    if not has_name and not has_price and not has_purchase_btn and not has_images:
        if verbose:
            print(f"  ⚠ INVALID: No product content found")
        return True, "no_product_content"
    
    return False, "valid"


# ---------------------------
# Extractors
# ---------------------------
def _extract_price(soup: BeautifulSoup) -> Tuple[str, str]:
    # Check if out of stock first (some sites don't show price for OOS)
    oos_el = soup.select_one("[class*='outOfStock'], [class*='OutOfStock'], [data-testid='out-of-stock']")
    
    # Prefer <p data-testid="price" data-testvalue="6999"><span>£69.99</span></p>
    p = soup.select_one("p[data-testid='price']")
    if p:
        val = p.get("data-testvalue")
        if val and val.isdigit():
            try:
                pennies = int(val)
                if pennies > 0:
                    return f"{pennies/100:.2f} GBP", "price-testid-attr"
            except Exception:
                pass
        txt = _clean(p.get_text(" ", strip=True))
        m = re.search(r"(£\s?\d[\d,]*(?:\.\d{2})?)", txt)
        if m:
            return m.group(1).replace(" ", "") + " GBP", "price-testid-text"

    # Secondary fallbacks
    metas = soup.select("meta[itemprop='price'], [itemprop='price']")
    for el in metas:
        txt = _clean(el.get("content") or el.get_text(" ", strip=True))
        m = re.search(r"(\d[\d,]*(?:\.\d{2})?)", txt)
        if m:
            return f"{m.group(1)} GBP", "itemprop"

    # JSON-LD
    jld = _jsonld_first(soup, "Product")
    if jld:
        offers = jld.get("offers")
        offers = offers if isinstance(offers, list) else [offers] if offers else []
        for off in offers:
            price = off.get("price") or off.get("lowPrice")
            if price:
                try:
                    return f"{float(price):.2f} GBP", "jsonld"
                except Exception:
                    pass

    # Body fallback - only if NOT out of stock
    if not oos_el:
        body_price = _clean(soup.get_text(" ", strip=True))
        m = re.search(r"(£\s?\d[\d,]*(?:\.\d{2})?)", body_price)
        if m:
            return m.group(1).replace(" ", "") + " GBP", "body"

    return "N/A", "none"

def _extract_name(soup: BeautifulSoup) -> str:
    for sel in ("h1", "[data-testid='pdp-title']", "[class*='ProductTitle']", "[class*='pdpTitle']"):
        el = soup.select_one(sel)
        if el:
            txt = _clean(el.get_text(" ", strip=True))
            if txt:
                return txt
    jld = _jsonld_first(soup, "Product")
    if jld and jld.get("name"):
        return _clean(jld["name"])
    return "Unknown Product"

def _extract_description(soup: BeautifulSoup) -> str:
    def _clean_spaces(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip())

    def _strip_product_code(txt: str) -> str:
        return re.sub(r"^Product code:\s*\S+\s*", "", txt, flags=re.I)

    jld = _jsonld_first(soup, "Product")
    if jld:
        jld_desc = _clean_spaces(jld.get("description") or "")
        if jld_desc and len(jld_desc) > 60:
            return _strip_product_code(jld_desc)

    for sel in (
        "[data-testid='accordion-content'] [data-testid='description']",
        "[data-testid='description']",
    ):
        root = soup.select_one(sel)
        if root:
            span = root.select_one(
                ".ProductDetails_description__hX1PR, [class*='ProductDetails_description'] span, [class*='ProductDetails_description']"
            )
            if span:
                txt = _clean_spaces(span.get_text(" ", strip=True))
                if txt:
                    return _strip_product_code(txt)
            txt = _clean_spaces(root.get_text(" ", strip=True))
            if txt:
                return _strip_product_code(txt)

    for sel in (
        "[class*='ProductDetails_description']",
        "[data-testid='accordion-content'] [class*='ProductDetails_root']",
        "[class*='ProductDetails_root']",
    ):
        el = soup.select_one(sel)
        if el:
            txt = _clean_spaces(el.get_text(" ", strip=True))
            if txt:
                return _strip_product_code(txt)

    meta = soup.select_one("meta[name='description']")
    if meta and meta.get("content"):
        txt = _clean_spaces(meta["content"])
        if len(txt) > 60:
            return _strip_product_code(txt)

    return "N/A"

def _extract_stock(soup: BeautifulSoup) -> Tuple[bool, str]:
    # Check for out of stock indicators first
    oos_selectors = [
        "[class*='outOfStock']",
        "[class*='OutOfStock']",
        "[data-testid='out-of-stock']",
    ]
    for sel in oos_selectors:
        if soup.select_one(sel):
            return False, "outOfStock-element"
    
    # Check body text for OOS
    body_text = _clean(soup.get_text(" ", strip=True)).lower()
    if "out of stock" in body_text and "add to bag" not in body_text:
        return False, "body-oos"
    
    # Presence of purchase button implies in stock
    btn = soup.select_one("button[data-testid='purchase-button']")
    if btn:
        # Check if disabled
        if btn.get("disabled") or "disabled" in (btn.get("class") or []):
            return False, "purchase-button-disabled"
        return True, "purchase-button"
    
    # JSON-LD availability
    jld = _jsonld_first(soup, "Product")
    if jld:
        offers = jld.get("offers")
        offers = offers if isinstance(offers, list) else [offers] if offers else []
        for off in offers:
            avail = str(off.get("availability") or off.get("itemAvailability") or "")
            if re.search(r"InStock", avail, re.I):
                return True, "jsonld"
            if re.search(r"OutOfStock|SoldOut", avail, re.I):
                return False, "jsonld"
    
    return None, "unknown"

def _desired_gallery_urls(soup: BeautifulSoup) -> List[str]:
    """
    Only the main 7 images in order.
    """
    thumbs = []
    for img in soup.select(".ImageGallery_thumbsContainer img[src]"):
        src = img.get("src") or ""
        if "cdn.media.amplience.net/i/frasersdev/" not in src:
            continue
        if re.search(r"/\d+_o(?:_a[2-7])?\?", src):
            thumbs.append(src)

    seen = set()
    ordered = []
    for u in thumbs:
        u = re.sub(r"\?(.*)$", "", u)
        u = u + "?fmt=jpg&upscale=true&w=1500&h=1500&sm=scaleFit"
        if u not in seen:
            seen.add(u)
            ordered.append(u)

    if not ordered:
        any_img = soup.select_one("img[src*='cdn.media.amplience.net/i/frasersdev/']")
        if any_img:
            base = re.sub(r"\?.*$", "", any_img["src"])
            m = re.search(r"(https://cdn\.media\.amplience\.net/i/frasersdev/\d+)_", base)
            if m:
                code = m.group(1)
                candidates = [code + "_o"] + [f"{code}_o_a{i}" for i in range(2, 8)]
                ordered = [f"{c}?fmt=jpg&upscale=true&w=1500&h=1500&sm=scaleFit" for c in candidates]

    return ordered[:7]

def _download_images_jpg(urls: List[str], folder: Path, session: requests.Session, verbose: bool = True) -> List[str]:
    folder.mkdir(parents=True, exist_ok=True)
    out_files = []
    for i, u in enumerate(urls, start=1):
        try:
            r, err = robust_get(session, u, timeout=30)
            if err or not r:
                if verbose:
                    print(f"  ✗ image {i}: {err}")
                continue
            
            content = r.content
            ext = ".jpg"
            try:
                im = Image.open(io.BytesIO(content))
                rgb = im.convert("RGB")
                fp = folder / f"{i:02d}{ext}"
                rgb.save(fp, format="JPEG", quality=92, optimize=True)
                out_files.append(str(fp))
                if verbose:
                    print(f"  ✓ image {i} ({len(content):,} bytes)")
            except Exception:
                fp = folder / f"{i:02d}{ext}"
                with open(fp, "wb") as f:
                    f.write(content)
                out_files.append(str(fp))
                if verbose:
                    print(f"  ✓ image {i} raw ({len(content):,} bytes)")
        except Exception as e:
            if verbose:
                print(f"  ✗ image {i}: {e}")
    return out_files


# ---------- Main ----------
def fetch_product_houseoffraser(url: str, verbose: bool = True) -> Dict[str, Any]:
    if verbose:
        print(f"Fetching {url}...")
    
    session = requests.Session()
    session.headers.update(get_random_headers())
    
    # Fetch page with error handling
    resp, http_error = robust_get(session, url, timeout=25)
    
    # Parse HTML (even error pages have content we can check)
    html = resp.text if resp else ""
    soup = BeautifulSoup(html, "lxml") if html else None
    
    # Check for invalid product page
    is_invalid, invalid_reason = _check_invalid_product_page(
        soup, html, url, http_error=http_error, verbose=verbose
    )
    
    if is_invalid:
        if verbose:
            print(f"✗ Invalid link detected: {invalid_reason}")
        return {
            "url": url,
            "name": "INVALID LINK - Product removed or no longer available",
            "price": "N/A",
            "price_source": "none",
            "in_stock": False,
            "stock_text": invalid_reason,
            "description": "",
            "image_count": 0,
            "image_urls": [],
            "images_downloaded": [],
            "folder": None,
            "mode": "direct",
            "is_invalid": True,
            "invalid_reason": invalid_reason
        }

    # Extract product data
    name = _extract_name(soup)
    price, price_source = _extract_price(soup)
    in_stock, stock_text = _extract_stock(soup)
    description = _extract_description(soup)

    if verbose:
        print(f"  Name: {name}")
        print(f"  Price: {price}")
        print(f"  In Stock: {in_stock} ({stock_text})")

    # Images
    image_urls = _desired_gallery_urls(soup)
    
    if verbose:
        print(f"\nDownloading {len(image_urls)} images...")
    
    folder = SAVE_ROOT / f"{_retailer_slug(url)}_{_safe_name(name)}_{_stable_id_from_url(url)}"
    images_downloaded = _download_images_jpg(image_urls, folder, session, verbose=verbose)

    return {
        "url": url,
        "name": name,
        "price": price,
        "price_source": price_source,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_count": len(image_urls),
        "image_urls": image_urls,
        "images_downloaded": images_downloaded,
        "folder": str(folder) if images_downloaded else None,
        "mode": "direct",
        "is_invalid": False,
        "invalid_reason": None
    }


# # ---------------------------
# # CLI
# # ---------------------------
# if __name__ == "__main__":
#     import sys
    
#     if len(sys.argv) > 1:
#         test_url = sys.argv[1]
#     else:
#         # Test with invalid URL (404)
#         test_url = "https://www.houseoffraser.co.uk/brand/view-quest/laura-ashley-4-slice-toaster-china-rose-426943#colcode=42694301"
    
#     print(f"\n{'='*60}")
#     print(f"Testing: {test_url}")
#     print(f"{'='*60}\n")
    
#     try:
#         data = fetch_product_houseoffraser(test_url, verbose=True)
#         print("\n" + "=" * 60)
#         print("RESULTS:")
#         print("=" * 60)
#         print(json.dumps(data, indent=2, ensure_ascii=False))
#     except Exception as e:
#         print(f"\n✗ ERROR: {e}")
