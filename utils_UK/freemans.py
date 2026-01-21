
# # freemans.py
# # Python 3.10+
# # pip install requests beautifulsoup4 lxml pillow

# import os
# import re
# import io
# import json
# import random
# from pathlib import Path
# from typing import Dict, Any, List, Tuple

# import requests
# from bs4 import BeautifulSoup
# from PIL import Image
# from requests.adapters import HTTPAdapter
# from urllib3.util.retry import Retry

# # ---------------------------
# # Credentials
# # ---------------------------
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS  # optional helper file
# except Exception:
#     OXY_USER = os.getenv("OXYLABS_USERNAME", "")
#     OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")

# if not (OXY_USER and OXY_PASS):
#     raise RuntimeError(
#         "Oxylabs credentials missing. Set OXYLABS_USERNAME / OXYLABS_PASSWORD "
#         "or provide oxylabs_secrets.py with OXY_USER, OXY_PASS."
#     )

# # ---------------------------
# # Paths
# # ---------------------------
# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()
# SAVE_ROOT = BASE_DIR / "data1"
# SAVE_ROOT.mkdir(parents=True, exist_ok=True)

# # ---------------------------
# # Helpers
# # ---------------------------
# def _clean_text(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "").strip())

# def _safe_name(name: str) -> str:
#     n = re.sub(r"[^\w\s-]", "", name or "").strip()
#     n = re.sub(r"\s+", "_", n)
#     return n or "Unknown_Product"

# def _retailer_slug(url: str) -> str:
#     m = re.search(r"https?://(?:www\.)?([^/]+)", url or "", re.I)
#     if not m:
#         return "site"
#     host = re.sub(r"^www\.", "", m.group(1).lower())
#     return host.split(".")[0]

# def _stable_id_from_url(url: str) -> str:
#     # Prefer long numeric code in path/query; otherwise "freemans"
#     m = re.search(r"(\d{6,})", url or "")
#     return m.group(1) if m else "freemans"

# def _ua() -> str:
#     return random.choice([
#         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
#         "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
#         "Mozilla/5.0 (Linux; Android 14; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36",
#         "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
#     ])

# def _session_with_retries(total: int = 4, backoff: float = 0.6) -> requests.Session:
#     sess = requests.Session()
#     retry = Retry(
#         total=total,
#         connect=total,
#         read=total,
#         status=total,
#         backoff_factor=backoff,
#         status_forcelist=(429, 500, 502, 503, 504),
#         allowed_methods=frozenset(["GET", "POST"]),
#         raise_on_status=False,
#     )
#     adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=40)
#     sess.mount("https://", adapter)
#     sess.mount("http://", adapter)
#     return sess

# # ---------------------------
# # Oxylabs call
# # ---------------------------
# def _oxylabs_universal_html(url: str, country: str = "United Kingdom", timeout: int = 75) -> str:
#     """
#     Returns rendered HTML via Oxylabs Web Scraper API Universal source.
#     """
#     endpoint = "https://realtime.oxylabs.io/v1/queries"
#     payload = {
#         "source": "universal",
#         "url": url,
#         "geo_location": country,
#         "render": "html",                # valid values: html, mhtml, png
#         "user_agent_type": "desktop",
#         "headers": {"User-Agent": _ua()},
#         # "premium": True,               # enable if your plan allows
#     }
#     sess = _session_with_retries()
#     r = sess.post(endpoint, auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
#     if r.status_code != 200:
#         # surface Oxylabs error body so you can see exact issue
#         msg = r.text.strip()
#         raise RuntimeError(f"Oxylabs HTML fetch failed: HTTP {r.status_code} — {msg}")
#     data = r.json()
#     try:
#         return data["results"][0]["content"]
#     except Exception:
#         raise RuntimeError(f"Oxylabs response missing content: {data}")

# # ---------------------------
# # Parsers (Freemans)
# # ---------------------------
# def _extract_name(soup: BeautifulSoup) -> str:
#     el = soup.select_one("h1#prodShortDesc")
#     if el:
#         txt = _clean_text(el.get_text(" ", strip=True))
#         if txt:
#             return txt
#     for sel in ("h1", ".productShortDesc", "[data-testid='pdp-title']"):
#         el = soup.select_one(sel)
#         if el:
#             txt = _clean_text(el.get_text(" ", strip=True))
#             if txt:
#                 return txt
#     # JSON-LD fallback
#     for tag in soup.select("script[type='application/ld+json']"):
#         try:
#             data = json.loads(tag.string or "")
#         except Exception:
#             continue
#         objs = data if isinstance(data, list) else [data]
#         for obj in objs:
#             if obj.get("@type") == "Product" and obj.get("name"):
#                 return _clean_text(obj["name"])
#     return "Unknown Product"

# def _extract_price(soup: BeautifulSoup) -> Tuple[str, str]:
#     p_int = soup.select_one("span.productPriceInteger")
#     p_dec = soup.select_one("span.productPriceDecimal")
#     if p_int and p_dec:
#         pint = _clean_text(p_int.get_text())
#         pdec = _clean_text(p_dec.get_text())
#         if pint and pdec:
#             return f"{pint}.{pdec} GBP", "integer+decimal"
#     # body fallback
#     txt = _clean_text(soup.get_text(" ", strip=True))
#     m = re.search(r"(£\s?\d[\d,]*(?:\.\d{2})?)", txt)
#     if m:
#         return m.group(1).replace(" ", "") + " GBP", "body"
#     # JSON-LD fallback
#     for tag in soup.select("script[type='application/ld+json']"):
#         try:
#             data = json.loads(tag.string or "")
#         except Exception:
#             continue
#         objs = data if isinstance(data, list) else [data]
#         for obj in objs:
#             if obj.get("@type") == "Product":
#                 offers = obj.get("offers")
#                 offers = offers if isinstance(offers, list) else [offers] if offers else []
#                 for off in offers:
#                     price = off.get("price") or off.get("lowPrice")
#                     if price:
#                         return f"{price} GBP", "jsonld"
#     return "N/A", "none"

# def _extract_description(soup: BeautifulSoup) -> str:
#     d = soup.select_one("div.productDescription")
#     if d:
#         txt = _clean_text(d.get_text(" ", strip=True))
#         if txt:
#             return txt
#     for sel in ("#prodDescription", "[data-testid='pdp-description']",
#                 ".product-description", ".pdp-description"):
#         el = soup.select_one(sel)
#         if el:
#             txt = _clean_text(el.get_text(" ", strip=True))
#             if txt:
#                 return txt
#     for tag in soup.select("script[type='application/ld+json']"):
#         try:
#             data = json.loads(tag.string or "")
#         except Exception:
#             continue
#         objs = data if isinstance(data, list) else [data]
#         for obj in objs:
#             if obj.get("@type") == "Product" and obj.get("description"):
#                 t = _clean_text(obj["description"])
#                 if t:
#                     return t
#     meta = soup.select_one("meta[name='description']")
#     if meta and meta.get("content"):
#         t = _clean_text(meta["content"])
#         if t:
#             return t
#     return "N/A"

# def _extract_stock(soup: BeautifulSoup) -> Tuple[bool | None, str]:
#     """
#     Freemans stock heuristic:
#     1) If stockStatus text is decisive (explicit OOS or clearly available), use it.
#     2) Else, look for the Add-to-Bag CTA.
#     3) Else, fall back to JSON-LD availability.
#     4) Else, unknown.
#     """
#     last_txt = "unknown"

#     # 1) stockStatus text (decisive only)
#     st = soup.select_one("span.stockStatus, .stockStatus")
#     if st:
#         txt = _clean_text(st.get_text(" ", strip=True)).lower()
#         last_txt = txt
#         if any(x in txt for x in ["out of stock", "not currently available", "unavailable"]):
#             return False, txt
#         if any(x in txt for x in [
#             "in stock",
#             "delivered direct",          # drop-ship wording; treat as purchasable
#             "available to order",
#             "delivery",                   # e.g., "delivery in 2–4 days"
#             "despatched",
#             "ready to ship",
#         ]):
#             return True, txt
#         # else not decisive; keep going

#     # 2) CTA present?
#     btn = soup.select_one(
#         "button.bagButton, button.button.primary.bagButton, "
#         "button.addToBasket, button[data-testid='add-to-basket']"
#     )
#     if btn or soup.find(string=re.compile(r"\bAdd to Bag\b", re.I)):
#         return True, "add-to-bag"

#     # 3) JSON-LD availability
#     for tag in soup.select("script[type='application/ld+json']"):
#         try:
#             data = json.loads(tag.string or "")
#         except Exception:
#             continue
#         objs = data if isinstance(data, list) else [data]
#         for o in objs:
#             if o.get("@type") == "Product":
#                 offers = o.get("offers")
#                 offers = offers if isinstance(offers, list) else [offers] if offers else []
#                 for off in offers:
#                     avail = str(off.get("availability") or "")
#                     if re.search(r"InStock", avail, re.I):
#                         return True, "jsonld"
#                     if re.search(r"OutOfStock|SoldOut", avail, re.I):
#                         return False, "jsonld"

#     # 4) unknown
#     return None, last_txt

# def _extract_images(soup: BeautifulSoup) -> List[str]:
#     """
#     From Playwright version: ul.altProductImages img with data-image / data-original.
#     Upgrade to high-res Scene7 JPGs (fmt=jpg&wid=1800&hei=1800&qlt=92).
#     """
#     urls = []
#     seen = set()
#     for img in soup.select("ul.altProductImages img"):
#         src = img.get("data-image") or img.get("data-original") or img.get("src") or ""
#         if not src:
#             continue
#         base = src.split("?")[0]
#         # Force high-res jpg via Scene7 params if on is/image host
#         if "is/image/" in base:
#             base = base  # keep path
#             full = f"{base}?fmt=jpg&wid=1800&hei=1800&qlt=92"
#         else:
#             full = base
#         if full and full not in seen:
#             seen.add(full)
#             urls.append(full)

#     if not urls:
#         for img in soup.select("img[src]"):
#             s = img.get("src") or ""
#             if not s:
#                 continue
#             base = s.split("?")[0]
#             if "product" in base.lower() or "zoom" in base.lower() or "gallery" in base.lower():
#                 if "is/image/" in base:
#                     full = f"{base}?fmt=jpg&wid=1800&hei=1800&qlt=92"
#                 else:
#                     full = base
#                 if full not in seen:
#                     seen.add(full)
#                     urls.append(full)

#     return urls

# # ---------------------------
# # Image download (force JPG)
# # ---------------------------
# def _download_images_jpg(urls: List[str], folder: Path, session: requests.Session) -> List[str]:
#     folder.mkdir(parents=True, exist_ok=True)
#     out = []
#     headers = {
#         "User-Agent": _ua(),
#         "Referer": "https://www.freemans.com/",
#         "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
#     }

#     for i, u in enumerate(urls, start=1):
#         try:
#             r = session.get(u, timeout=20, stream=True, headers=headers)
#             r.raise_for_status()
#             data = r.content

#             # Convert to real JPG with Pillow (best-effort)
#             try:
#                 im = Image.open(io.BytesIO(data))
#                 rgb = im.convert("RGB")
#                 fp = folder / f"{i:02d}.jpg"
#                 rgb.save(fp, format="JPEG", quality=92, optimize=True)
#                 out.append(str(fp))
#             except Exception:
#                 # Raw write with .jpg if Pillow fails
#                 fp = folder / f"{i:02d}.jpg"
#                 with open(fp, "wb") as f:
#                     f.write(data)
#                 out.append(str(fp))
#         except Exception as e:
#             print(f"  ! image error: {u} ({e})")
#     return out

# # ---------------------------
# # Public API
# # ---------------------------
# def fetch_freemans_product_with_oxylabs(url: str) -> Dict[str, Any]:
#     html = _oxylabs_universal_html(url, country="United Kingdom", timeout=75)
#     soup = BeautifulSoup(html, "lxml")

#     name = _extract_name(soup)
#     price, price_src = _extract_price(soup)
#     description = _extract_description(soup)
#     in_stock, avail_msg = _extract_stock(soup)
#     image_urls = _extract_images(soup)

#     # Download images as JPG
#     folder = SAVE_ROOT / f"{_retailer_slug(url)}_{_safe_name(name)}_{_stable_id_from_url(url)}"
#     sess = _session_with_retries()
#     imgs = _download_images_jpg(image_urls, folder, sess)

#     return {
#         "name": name or "N/A",
#         "price": price or "N/A",
#         "price_source": price_src,
#         "in_stock": in_stock,
#         "availability_message": avail_msg,
#         "description": description or "N/A",
#         "image_count": len(image_urls),
#         "images": image_urls,
#         "images_downloaded": imgs,
#         "folder": str(folder),
#         "mode": "oxylabs-universal",
#         "url": url,
#     }

# # # ---------------------------
# # # CLI test
# # # ---------------------------
# # if __name__ == "__main__":
# #     TEST_URL = "https://www.freemans.com/products/laura-ashley-jug-kettle-china-rose/_/A-64H070_?PFM_rsn=browse&PFM_ref=false&PFM_psp=own&PFM_pge=1&PFM_lpn=1"
# #     data = fetch_freemans_product_with_oxylabs(TEST_URL)
# #     print(json.dumps(data, indent=2, ensure_ascii=False))






# freemans.py
# Python 3.10+
# pip install requests beautifulsoup4 lxml pillow
# Version: 2.0 - Added retry logic for 204 errors and invalid link detection

import os
import re
import io
import json
import time
import random
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import requests
from bs4 import BeautifulSoup
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

__version__ = "2.0"

# ---------------------------
# Credentials
# ---------------------------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")

if not (OXY_USER and OXY_PASS):
    raise RuntimeError(
        "Oxylabs credentials missing. Set OXYLABS_USERNAME / OXYLABS_PASSWORD "
        "or provide oxylabs_secrets.py with OXY_USER, OXY_PASS."
    )

# ---------------------------
# Paths
# ---------------------------
try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()
SAVE_ROOT = BASE_DIR / "data1"
SAVE_ROOT.mkdir(parents=True, exist_ok=True)

# ---------------------------
# Helpers
# ---------------------------
def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _safe_name(name: str) -> str:
    n = re.sub(r"[^\w\s-]", "", name or "").strip()
    n = re.sub(r"\s+", "_", n)
    return n[:100] or "Unknown_Product"


def _retailer_slug(url: str) -> str:
    m = re.search(r"https?://(?:www\.)?([^/]+)", url or "", re.I)
    if not m:
        return "site"
    host = re.sub(r"^www\.", "", m.group(1).lower())
    return host.split(".")[0]


def _stable_id_from_url(url: str) -> str:
    # Extract product code like A-77X974
    m = re.search(r"A-([A-Z0-9]+)", url or "", re.I)
    if m:
        return m.group(1)
    # Fallback to numeric
    m = re.search(r"(\d{6,})", url or "")
    return m.group(1) if m else "freemans"


def _extract_product_code_from_url(url: str) -> Optional[str]:
    """Extract the product code (e.g., 77X974) from URL for validation."""
    m = re.search(r"A-([A-Z0-9]+)", url or "", re.I)
    return m.group(1) if m else None


def _ua() -> str:
    return random.choice([
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    ])


def _session_with_retries(total: int = 4, backoff: float = 0.6) -> requests.Session:
    sess = requests.Session()
    retry = Retry(
        total=total,
        connect=total,
        read=total,
        status=total,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=40)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess


# ---------------------------
# Oxylabs call with RETRY LOGIC
# ---------------------------
def _oxylabs_universal_html(url: str, country: str = "United Kingdom", timeout: int = 75, verbose: bool = False) -> str:
    """
    Returns rendered HTML via Oxylabs Web Scraper API Universal source.
    Includes retry logic for 204/400 errors.
    """
    endpoint = "https://realtime.oxylabs.io/v1/queries"
    
    max_attempts = 4
    consecutive_204 = 0
    session_failed_count = 0
    last_err = None
    
    for attempt in range(max_attempts):
        session_id = f"freemans-{int(time.time())}-{random.randint(1000, 9999)}"
        
        payload = {
            "source": "universal",
            "url": url,
            "geo_location": country,
            "render": "html",
            "user_agent_type": "desktop",
            "headers": {"User-Agent": _ua()},
            "context": [
                {"key": "session_id", "value": session_id}
            ],
            "rendering_wait": 3000,
        }
        
        if verbose:
            print(f"  Attempt {attempt + 1}/{max_attempts} (session: {session_id})...")
        
        try:
            sess = _session_with_retries()
            r = sess.post(endpoint, auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
            
            # Success
            if r.status_code == 200:
                data = r.json()
                try:
                    html = data["results"][0]["content"]
                    if html and len(html) > 500:
                        if verbose:
                            print(f"  ✓ Fetched {len(html):,} bytes")
                        return html
                    else:
                        if verbose:
                            print(f"  ⚠ Empty/short content, retrying...")
                        last_err = RuntimeError("Empty content from Oxylabs")
                        time.sleep(2)
                        continue
                except (KeyError, IndexError):
                    last_err = RuntimeError(f"Oxylabs response missing content: {data}")
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
    Check if a Freemans product URL has returned an error/listing page instead of PDP.
    
    Key indicators of INVALID page:
    1. Redirected to search/listing page (multiple product cards)
    2. URL product code doesn't match page product code
    3. No product-specific elements (prodShortDesc, productDescription)
    4. Error page indicators
    
    Returns (is_invalid, reason) tuple.
    """
    html_lower = html.lower()
    body_text = _clean_text(soup.get_text(" ", strip=True)).lower() if soup.body else ""
    
    # Extract expected product code from URL
    expected_code = _extract_product_code_from_url(url)
    
    # ===== Check 1: Error page indicators =====
    error_patterns = [
        "page not found",
        "product not found",
        "sorry, we can't find",
        "this page doesn't exist",
        "no longer available",
        "has been removed",
        "404",
    ]
    for pattern in error_patterns:
        if pattern in body_text:
            if verbose:
                print(f"  ⚠ INVALID: Error pattern found - '{pattern}'")
            return True, f"error_message:{pattern[:30]}"
    
    # ===== Check 2: Redirected to listing/search page =====
    # Freemans listing pages have multiple product tiles/cards
    product_tiles = soup.select(".productTile, .product-tile, [class*='ProductTile'], [class*='productCard']")
    product_links = soup.select("a.productLink, a[class*='productLink']")
    
    # If we have 3+ product tiles/links, it's a listing page
    if len(product_tiles) >= 3 or len(product_links) >= 3:
        if verbose:
            print(f"  ⚠ INVALID: Listing page detected ({len(product_tiles)} tiles, {len(product_links)} links)")
        return True, f"listing_page:{len(product_tiles)}_tiles"
    
    # ===== Check 3: Check for pagination (listing page indicator) =====
    pagination = soup.select_one(".pagination, [class*='Pagination'], .paging, nav[aria-label*='page']")
    page_count_text = soup.find(string=re.compile(r"\d+\s+products?\s+found|\d+\s+results?", re.I))
    if pagination or page_count_text:
        if verbose:
            print(f"  ⚠ INVALID: Pagination/results count found (listing page)")
        return True, "listing_page:pagination_found"
    
    # ===== Check 4: No PDP-specific elements =====
    has_prod_name = bool(soup.select_one("h1#prodShortDesc, h1.productShortDesc"))
    has_prod_desc = bool(soup.select_one("div.productDescription, #prodDescription"))
    has_price_block = bool(soup.select_one("span.productPriceInteger, .productPrice, [class*='productPrice']"))
    has_alt_images = bool(soup.select_one("ul.altProductImages"))
    has_add_bag = bool(soup.select_one("button.bagButton, button.addToBasket"))
    
    pdp_indicators = sum([has_prod_name, has_prod_desc, has_price_block, has_alt_images, has_add_bag])
    
    if pdp_indicators < 2:
        if verbose:
            print(f"  ⚠ INVALID: Missing PDP elements (only {pdp_indicators}/5 found)")
            print(f"    - Name: {has_prod_name}, Desc: {has_prod_desc}, Price: {has_price_block}, "
                  f"Images: {has_alt_images}, AddBag: {has_add_bag}")
        return True, f"no_pdp_content:{pdp_indicators}_indicators"
    
    # ===== Check 5: Product code mismatch (if we have expected code) =====
    if expected_code:
        # Look for the product code in the page
        code_in_page = expected_code.lower() in html_lower
        
        # Also check if the page has a different product code prominently
        # Freemans often has product code in data attributes or hidden fields
        page_codes = re.findall(r'data-product[^>]*?([A-Z0-9]{5,8})', html, re.I)
        page_codes += re.findall(r'productCode["\s:]+([A-Z0-9]{5,8})', html, re.I)
        
        if page_codes and expected_code.upper() not in [c.upper() for c in page_codes]:
            if verbose:
                print(f"  ⚠ INVALID: Product code mismatch - expected {expected_code}, found {page_codes[:3]}")
            return True, f"code_mismatch:expected_{expected_code}"
    
    # ===== Check 6: Search results page =====
    if "searchresults" in html_lower or "search results" in body_text:
        # But make sure it's not just a URL parameter
        if soup.select_one(".searchResults, #searchResults, [class*='SearchResults']"):
            if verbose:
                print(f"  ⚠ INVALID: Search results page detected")
            return True, "search_results_page"
    
    # ===== Check 7: "Unknown Product" would be extracted =====
    # Pre-check if name extraction would fail
    name_el = soup.select_one("h1#prodShortDesc")
    if not name_el:
        for sel in ("h1", ".productShortDesc", "[data-testid='pdp-title']"):
            name_el = soup.select_one(sel)
            if name_el:
                break
    
    if not name_el or not _clean_text(name_el.get_text(" ", strip=True)):
        # Check JSON-LD
        has_jsonld_name = False
        for tag in soup.select("script[type='application/ld+json']"):
            try:
                data = json.loads(tag.string or "")
                objs = data if isinstance(data, list) else [data]
                for obj in objs:
                    if obj.get("@type") == "Product" and obj.get("name"):
                        has_jsonld_name = True
                        break
            except Exception:
                continue
        
        if not has_jsonld_name:
            if verbose:
                print(f"  ⚠ INVALID: No product name found anywhere")
            return True, "no_product_name"
    
    return False, "valid"


# ---------------------------
# Parsers (Freemans)
# ---------------------------
def _extract_name(soup: BeautifulSoup) -> str:
    el = soup.select_one("h1#prodShortDesc")
    if el:
        txt = _clean_text(el.get_text(" ", strip=True))
        if txt:
            return txt
    for sel in ("h1", ".productShortDesc", "[data-testid='pdp-title']"):
        el = soup.select_one(sel)
        if el:
            txt = _clean_text(el.get_text(" ", strip=True))
            if txt:
                return txt
    # JSON-LD fallback
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if obj.get("@type") == "Product" and obj.get("name"):
                return _clean_text(obj["name"])
    return "Unknown Product"


def _extract_price(soup: BeautifulSoup) -> Tuple[str, str]:
    p_int = soup.select_one("span.productPriceInteger")
    p_dec = soup.select_one("span.productPriceDecimal")
    if p_int and p_dec:
        pint = _clean_text(p_int.get_text())
        pdec = _clean_text(p_dec.get_text())
        if pint and pdec:
            return f"{pint}.{pdec} GBP", "integer+decimal"
    # body fallback
    txt = _clean_text(soup.get_text(" ", strip=True))
    m = re.search(r"(£\s?\d[\d,]*(?:\.\d{2})?)", txt)
    if m:
        return m.group(1).replace(" ", "") + " GBP", "body"
    # JSON-LD fallback
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if obj.get("@type") == "Product":
                offers = obj.get("offers")
                offers = offers if isinstance(offers, list) else [offers] if offers else []
                for off in offers:
                    price = off.get("price") or off.get("lowPrice")
                    if price:
                        return f"{price} GBP", "jsonld"
    return "N/A", "none"


def _extract_description(soup: BeautifulSoup) -> str:
    d = soup.select_one("div.productDescription")
    if d:
        txt = _clean_text(d.get_text(" ", strip=True))
        if txt:
            return txt
    for sel in ("#prodDescription", "[data-testid='pdp-description']",
                ".product-description", ".pdp-description"):
        el = soup.select_one(sel)
        if el:
            txt = _clean_text(el.get_text(" ", strip=True))
            if txt:
                return txt
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if obj.get("@type") == "Product" and obj.get("description"):
                t = _clean_text(obj["description"])
                if t:
                    return t
    meta = soup.select_one("meta[name='description']")
    if meta and meta.get("content"):
        t = _clean_text(meta["content"])
        if t:
            return t
    return "N/A"


def _extract_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
    """
    Freemans stock heuristic:
    1) If stockStatus text is decisive (explicit OOS or clearly available), use it.
    2) Else, look for the Add-to-Bag CTA.
    3) Else, fall back to JSON-LD availability.
    4) Else, unknown.
    """
    last_txt = "unknown"

    # 1) stockStatus text (decisive only)
    st = soup.select_one("span.stockStatus, .stockStatus")
    if st:
        txt = _clean_text(st.get_text(" ", strip=True)).lower()
        last_txt = txt
        if any(x in txt for x in ["out of stock", "not currently available", "unavailable"]):
            return False, txt
        if any(x in txt for x in [
            "in stock",
            "delivered direct",
            "available to order",
            "delivery",
            "despatched",
            "ready to ship",
        ]):
            return True, txt

    # 2) CTA present?
    btn = soup.select_one(
        "button.bagButton, button.button.primary.bagButton, "
        "button.addToBasket, button[data-testid='add-to-basket']"
    )
    if btn or soup.find(string=re.compile(r"\bAdd to Bag\b", re.I)):
        return True, "add-to-bag"

    # 3) JSON-LD availability
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for o in objs:
            if o.get("@type") == "Product":
                offers = o.get("offers")
                offers = offers if isinstance(offers, list) else [offers] if offers else []
                for off in offers:
                    avail = str(off.get("availability") or "")
                    if re.search(r"InStock", avail, re.I):
                        return True, "jsonld"
                    if re.search(r"OutOfStock|SoldOut", avail, re.I):
                        return False, "jsonld"

    # 4) unknown
    return None, last_txt


def _extract_images(soup: BeautifulSoup) -> List[str]:
    """
    From ul.altProductImages img with data-image / data-original.
    Upgrade to high-res Scene7 JPGs.
    """
    urls = []
    seen = set()
    for img in soup.select("ul.altProductImages img"):
        src = img.get("data-image") or img.get("data-original") or img.get("src") or ""
        if not src:
            continue
        base = src.split("?")[0]
        if "is/image/" in base:
            full = f"{base}?fmt=jpg&wid=1800&hei=1800&qlt=92"
        else:
            full = base
        if full and full not in seen:
            seen.add(full)
            urls.append(full)

    if not urls:
        for img in soup.select("img[src]"):
            s = img.get("src") or ""
            if not s:
                continue
            base = s.split("?")[0]
            if "product" in base.lower() or "zoom" in base.lower() or "gallery" in base.lower():
                if "is/image/" in base:
                    full = f"{base}?fmt=jpg&wid=1800&hei=1800&qlt=92"
                else:
                    full = base
                if full not in seen:
                    seen.add(full)
                    urls.append(full)

    return urls


# ---------------------------
# Image download (force JPG)
# ---------------------------
def _download_images_jpg(urls: List[str], folder: Path, session: requests.Session, verbose: bool = True) -> List[str]:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    headers = {
        "User-Agent": _ua(),
        "Referer": "https://www.freemans.com/",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }

    for i, u in enumerate(urls, start=1):
        try:
            r = session.get(u, timeout=20, stream=True, headers=headers)
            r.raise_for_status()
            data = r.content

            try:
                im = Image.open(io.BytesIO(data))
                rgb = im.convert("RGB")
                fp = folder / f"{i:02d}.jpg"
                rgb.save(fp, format="JPEG", quality=92, optimize=True)
                out.append(str(fp))
                if verbose:
                    print(f"  ✓ image {i} ({len(data):,} bytes)")
            except Exception:
                fp = folder / f"{i:02d}.jpg"
                with open(fp, "wb") as f:
                    f.write(data)
                out.append(str(fp))
        except Exception as e:
            if verbose:
                print(f"  ✗ image {i}: {e}")
    return out


# ---------------------------
# Public API
# ---------------------------
def fetch_freemans_product_with_oxylabs(url: str, verbose: bool = True) -> Dict[str, Any]:
    if verbose:
        print(f"Fetching {url}...")
    
    # Try to fetch HTML with retry logic
    try:
        html = _oxylabs_universal_html(url, country="United Kingdom", timeout=75, verbose=verbose)
    except RuntimeError as e:
        err_str = str(e)
        
        if "INVALID_PAGE:" in err_str:
            reason = err_str.split("INVALID_PAGE:")[-1]
            if verbose:
                print(f"✗ Invalid link detected (fetch failed): {reason}")
            
            return {
                "name": "INVALID LINK - Product removed or no longer available",
                "price": "N/A",
                "price_source": "none",
                "in_stock": False,
                "availability_message": f"fetch_failed:{reason}",
                "description": "",
                "image_count": 0,
                "images": [],
                "images_downloaded": [],
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
            "price_source": "none",
            "in_stock": False,
            "availability_message": invalid_reason,
            "description": "",
            "image_count": 0,
            "images": [],
            "images_downloaded": [],
            "folder": None,
            "mode": "oxylabs-universal",
            "url": url,
            "is_invalid": True,
            "invalid_reason": invalid_reason
        }

    name = _extract_name(soup)
    price, price_src = _extract_price(soup)
    description = _extract_description(soup)
    in_stock, avail_msg = _extract_stock(soup)
    image_urls = _extract_images(soup)

    if verbose:
        print(f"  Name: {name}")
        print(f"  Price: {price}")
        print(f"  In Stock: {in_stock} ({avail_msg})")
        print(f"  Images found: {len(image_urls)}")

    # Download images as JPG
    folder = SAVE_ROOT / f"{_retailer_slug(url)}_{_safe_name(name)}_{_stable_id_from_url(url)}"
    sess = _session_with_retries()
    
    if verbose and image_urls:
        print(f"\nDownloading {len(image_urls)} images...")
    
    imgs = _download_images_jpg(image_urls, folder, sess, verbose=verbose) if image_urls else []

    return {
        "name": name or "N/A",
        "price": price or "N/A",
        "price_source": price_src,
        "in_stock": in_stock,
        "availability_message": avail_msg,
        "description": description or "N/A",
        "image_count": len(image_urls),
        "images": image_urls,
        "images_downloaded": imgs,
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
#         # Test with a potentially invalid URL
#         TEST_URL = "https://www.freemans.com/products/laura-ashley-elveden-white-4-slice-toaster/_/A-77X974_?searchResults=true&PFM_rsn=search&PFM_ref=true&PFM_psp=own&PFM_pge=1&PFM_lpn=9&PFM_trm=laura+ashley"
    
#     print(f"\n{'='*60}")
#     print(f"Testing: {TEST_URL}")
#     print(f"{'='*60}\n")
    
#     try:
#         data = fetch_freemans_product_with_oxylabs(TEST_URL, verbose=True)
#         print("\n" + "=" * 60)
#         print("RESULTS:")
#         print("=" * 60)
#         print(json.dumps(data, indent=2, ensure_ascii=False))
#     except Exception as e:
#         print(f"\n✗ ERROR: {e}")



