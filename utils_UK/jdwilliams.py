


# jdw_oxylabs.py
# Python 3.10+
# pip install requests beautifulsoup4 lxml pillow
# Version: 2.1 - Added retry logic for 204 errors and invalid link detection

import os
import re
import io
import json
import time
import random
import base64
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import requests
from bs4 import BeautifulSoup
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

__version__ = "2.1"

# ---------------------------
# Credentials
# ---------------------------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")

if not (OXY_USER and OXY_PASS):
    raise RuntimeError("Oxylabs credentials missing. Set OXYLABS_USERNAME / OXYLABS_PASSWORD or provide oxylabs_secrets.py")


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
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


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


def _safe_name(name: str) -> str:
    n = re.sub(r"[^\w\s-]", "", name or "").strip()
    n = re.sub(r"\s+", "_", n)
    return n[:100] or "Unknown_Product"


def _retailer_slug(url: str) -> str:
    m = re.search(r"https?://(?:www\.)?([^/]+)", url or "", re.I)
    host = (m.group(1).lower() if m else "site")
    host = re.sub(r"^www\.", "", host)
    return host.split(".")[0]


def _stable_id_from_url(url: str) -> str:
    # Extract product code like mp935
    m = re.search(r"/p/([a-zA-Z0-9]+)", url or "")
    if m:
        return m.group(1)
    m = re.search(r"(\d{6,})", url or "")
    return m.group(1) if m else "jdw"


def _is_valid_image(data: bytes) -> bool:
    if not data or len(data) < 100:
        return False
    return data[:2] == b'\xff\xd8' or data[:4] == b'\x89PNG' or data[:4] == b'GIF8'


# ---------------------------
# Oxylabs universal (rendered HTML) with RETRY LOGIC
# ---------------------------
def _oxylabs_universal_html(url: str, country: str = "United Kingdom", timeout: int = 75, verbose: bool = False) -> str:
    """
    Fetch HTML via Oxylabs with retry logic for 204/400 errors.
    
    Returns HTML on success.
    Raises RuntimeError with "INVALID_PAGE:" prefix if product doesn't exist.
    Raises RuntimeError with other message for transient failures.
    """
    endpoint = "https://realtime.oxylabs.io/v1/queries"
    
    max_attempts = 4
    consecutive_204 = 0
    session_failed_count = 0
    last_err = None
    
    for attempt in range(max_attempts):
        session_id = f"jdw-{int(time.time())}-{random.randint(1000, 9999)}"
        
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
            "rendering_wait": 3000,  # 3 seconds
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
                
                # After 3 consecutive 204s, likely invalid page
                if consecutive_204 >= 3:
                    raise RuntimeError("INVALID_PAGE:HTTP_204_REPEATED")
                
                time.sleep(2 + attempt)  # Increasing delay
                continue
            
            # HTTP 400 - Often session failed
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
                    
                    # 204 + session failed = likely invalid
                    if consecutive_204 > 0 and session_failed_count >= 2:
                        raise RuntimeError("INVALID_PAGE:SESSION_FAILED_AFTER_204")
                    
                    time.sleep(3)
                    continue
                
                last_err = RuntimeError(f"Oxylabs HTTP 400: {err_msg}")
                time.sleep(2)
                continue
            
            # Other errors (429, 5xx)
            if r.status_code in (429, 500, 502, 503, 504):
                if verbose:
                    print(f"  ⚠ HTTP {r.status_code}, retrying...")
                last_err = RuntimeError(f"Oxylabs HTTP {r.status_code}")
                time.sleep(3 + attempt * 2)
                continue
            
            # Unexpected status
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
    
    # Exhausted all attempts
    # If we had multiple 204s, it's likely an invalid page
    if consecutive_204 >= 2:
        raise RuntimeError("INVALID_PAGE:FETCH_EXHAUSTED_204")
    
    raise last_err or RuntimeError("Oxylabs failed after all attempts")


# ---------------------------
# Invalid Link Detection
# ---------------------------
def _check_invalid_product_page(soup: BeautifulSoup, html: str, url: str, verbose: bool = False) -> Tuple[bool, str]:
    """
    Check if a JD Williams product URL has returned an error/removed page.
    Returns (is_invalid, reason) tuple.
    """
    html_lower = html.lower()
    body_text = _clean(soup.get_text(" ", strip=True)).lower() if soup.body else ""
    
    # Check 1: 404/error page indicators
    error_patterns = [
        "page not found",
        "product not found", 
        "sorry, we can't find",
        "this page doesn't exist",
        "this product is no longer available",
        "has been removed",
        "no longer available",
        "404",
    ]
    for pattern in error_patterns:
        if pattern in body_text:
            if verbose:
                print(f"  ⚠ INVALID: Error pattern found - '{pattern}'")
            return True, f"error_message:{pattern[:30]}"
    
    # Check 2: Error page class/elements
    error_selectors = [
        ".error-page", "#error-page", ".not-found", "#not-found",
        "[class*='ErrorPage']", "[class*='NotFound']", "[class*='404']"
    ]
    for sel in error_selectors:
        if soup.select_one(sel):
            if verbose:
                print(f"  ⚠ INVALID: Error page element found - '{sel}'")
            return True, f"error_element:{sel}"
    
    # Check 3: No product name AND no price (empty product page)
    has_name = bool(soup.select_one('h1[data-testid="product-name"], h1'))
    has_price = bool(soup.select_one("[data-cy='product-details-price'], [class*='price'], [class*='Price']"))
    has_add_btn = bool(soup.find("button", attrs={"data-ga-tracking-id": "addToBagButton"}))
    
    if not has_name and not has_price and not has_add_btn:
        # Check if it looks like a category/listing page
        product_cards = soup.select("[class*='ProductCard'], [class*='product-card'], .product-tile")
        if len(product_cards) >= 3:
            if verbose:
                print(f"  ⚠ INVALID: Category page detected ({len(product_cards)} products)")
            return True, f"category_page:{len(product_cards)}_products"
        
        if verbose:
            print(f"  ⚠ INVALID: No product content found")
        return True, "no_product_content"
    
    # Check 4: Redirect to search/category
    if "/search?" in html_lower or "search results" in body_text:
        if verbose:
            print(f"  ⚠ INVALID: Redirected to search page")
        return True, "redirected_to_search"
    
    return False, "valid"


# ---------------------------
# Parsers for JD Williams PDP
# ---------------------------
def _extract_name(soup: BeautifulSoup) -> str:
    el = soup.select_one('h1[data-testid="product-name"]')
    if el:
        t = _clean(el.get_text(" ", strip=True))
        if t:
            return t
    # fallbacks
    for sel in ("h1", "[data-testid='pdp-title']"):
        el = soup.select_one(sel)
        if el:
            t = _clean(el.get_text(" ", strip=True))
            if t:
                return t
    # JSON-LD
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for o in objs:
            if o.get("@type") == "Product" and o.get("name"):
                return _clean(o["name"])
    return "Unknown Product"


def _extract_price(soup: BeautifulSoup) -> Tuple[str, str]:
    # Check if out of stock first - JDW doesn't show price for OOS items
    oos_el = soup.select_one("[class*='outOfStock'], [class*='OutOfStock']")
    oos_text = soup.select_one("[class*='outOfStockText']")
    
    if oos_el or oos_text:
        # For OOS products, only check specific price container (not body fallback)
        price_container = soup.select_one("div[data-cy='product-details-price']")
        if price_container:
            txt = _clean(price_container.get_text())
            m = re.search(r"(£\s?\d[\d,]*(?:\.\d{2})?)", txt)
            if m:
                return m.group(1).replace(" ", "") + " GBP", "price-block-oos"
        return "N/A", "out-of-stock-no-price"

    # Main price block
    p = soup.select_one("div[data-cy='product-details-price'] span")
    if p:
        txt = _clean(p.get_text())
        if txt:
            m = re.search(r"(£\s?\d[\d,]*(?:\.\d{2})?)", txt)
            if m:
                return m.group(1).replace(" ", "") + " GBP", "price-block"

    # Look for price in product details area
    for sel in [".ProductDetails_price__", "[class*='price']", "[class*='Price']"]:
        el = soup.select_one(sel)
        if el:
            txt = _clean(el.get_text())
            m = re.search(r"(£\s?\d[\d,]*(?:\.\d{2})?)", txt)
            if m:
                return m.group(1).replace(" ", "") + " GBP", "price-class"

    # JSON-LD
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
                    price = off.get("price") or off.get("lowPrice")
                    if price:
                        return f"£{price} GBP", "jsonld"

    # Body fallback - only for in-stock items
    body = _clean(soup.get_text(" ", strip=True))
    m = re.search(r"(£\s?\d[\d,]*(?:\.\d{2})?)", body)
    if m:
        return m.group(1).replace(" ", "") + " GBP", "body"

    return "N/A", "none"

def _extract_description(soup: BeautifulSoup) -> str:
    # Look for description section
    for sel in [
        "section.FullProductDetails_section__sSjSs",
        "[data-testid='product-description']",
        ".product-description",
        ".pdp-description",
        "[class*='ProductDetails_description']",
        "[class*='FullProductDetails']",
    ]:
        el = soup.select_one(sel)
        if el:
            t = _clean(el.get_text(" ", strip=True))
            if t and len(t) > 20:
                return t

    # JSON-LD
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for o in objs:
            if o.get("@type") == "Product" and o.get("description"):
                t = _clean(o["description"])
                if t:
                    return t

    # Meta description
    meta = soup.select_one("meta[name='description']")
    if meta and meta.get("content"):
        t = _clean(meta["content"])
        if t:
            return t

    return "N/A"


def _extract_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
    """
    Check for out of stock indicators FIRST, then check for add to bag.
    """
    # Check for explicit out of stock element (PRIORITY)
    oos_el = soup.select_one("[class*='outOfStock'], [class*='OutOfStock']")
    if oos_el:
        return False, "outOfStock-class"
    
    # Check for out of stock text in specific elements
    oos_text_el = soup.select_one("[class*='outOfStockText']")
    if oos_text_el:
        return False, "outOfStockText"
    
    # Check for "Sorry, this item is out of stock" text
    body_text = soup.get_text(" ", strip=True).lower()
    if "sorry, this item is out of stock" in body_text:
        return False, "sorry-text"
    if "out of stock" in body_text and "add to bag" not in body_text.lower():
        return False, "body-oos"
    
    # Check for notify/alert button (usually means OOS)
    notify_btn = soup.find("button", string=re.compile(r"notify|alert|email.*stock", re.I))
    if notify_btn:
        return False, "notify-button"

    # Now check for Add to Bag (only if not OOS)
    add_btn = soup.find("button", attrs={"data-ga-tracking-id": "addToBagButton"})
    if add_btn:
        # Check if button is disabled
        if add_btn.get("disabled") or "disabled" in add_btn.get("class", []):
            return False, "addToBag-disabled"
        return True, "addToBagButton"
    
    if soup.find(string=re.compile(r"\bAdd to (Bag|basket)\b", re.I)):
        return True, "cta-text"

    # JSON-LD availability
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
                    if re.search(r"OutOfStock|SoldOut", avail, re.I):
                        return False, "jsonld-oos"
                    if re.search(r"InStock", avail, re.I):
                        return True, "jsonld"

    return None, "unknown"


def _extract_images(soup: BeautifulSoup) -> List[str]:
    """
    Extract product images from gallery.
    """
    urls, seen = [], set()

    # Primary selector: gallery images
    for img in soup.select("picture.MediaGallery_mediaGalleryImage__FQEPD img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            srcset = img.get("srcset") or ""
            parts = [p.split(" ")[0] for p in srcset.split(",") if p.strip()]
            if parts:
                src = parts[-1]

        if not src:
            continue

        base = src.split("?")[0]
        if not base or base in seen:
            continue
        seen.add(base)
        urls.append(base)

    # Try alternative gallery selectors
    if not urls:
        for img in soup.select("[class*='MediaGallery'] img, [class*='Gallery'] img"):
            src = img.get("src") or img.get("data-src") or ""
            if src:
                base = src.split("?")[0]
                if base and base not in seen and "/products/" in base:
                    seen.add(base)
                    urls.append(base)

    # Fallback: any product images
    if not urls:
        for img in soup.select("img[src*='/products/']"):
            src = img.get("src") or ""
            base = src.split("?")[0]
            if base and base not in seen:
                seen.add(base)
                urls.append(base)

    return urls


# ---------------------------
# Image download with Oxylabs fallback
# ---------------------------
def _download_images_jpg(
    urls: List[str],
    folder: Path,
    page_url: str,
    verbose: bool = True
) -> List[str]:
    """
    Download images, using Oxylabs proxy as fallback for 403 errors.
    """
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    
    sess = _session_with_retries()
    headers = {
        "User-Agent": _ua(),
        "Referer": page_url,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }

    for i, u in enumerate(urls, start=1):
        fp = folder / f"{i:02d}.jpg"
        
        # Method 1: Direct download
        try:
            r = sess.get(u, timeout=25, headers=headers)
            if r.status_code == 200 and _is_valid_image(r.content):
                _save_as_jpg(r.content, fp)
                out.append(str(fp))
                if verbose:
                    print(f"  ✓ image {i} direct ({len(r.content):,} bytes)")
                continue
        except Exception:
            pass
        
        # Method 2: Oxylabs proxy
        try:
            if verbose:
                print(f"  → image {i} via Oxylabs...")
            
            payload = {
                "source": "universal",
                "url": u,
                "render": "png",
                "geo_location": "United Kingdom",
                "user_agent_type": "desktop",
                "context": [
                    {"key": "headers", "value": {
                        "Referer": page_url,
                        "Accept": "image/*,*/*;q=0.8",
                    }}
                ],
            }
            
            r = requests.post(
                "https://realtime.oxylabs.io/v1/queries",
                auth=(OXY_USER, OXY_PASS),
                json=payload,
                timeout=45,
            )
            
            if r.status_code == 200:
                data = r.json()
                results = data.get("results", [])
                if results:
                    content = results[0].get("content", "")
                    if content:
                        try:
                            img_bytes = base64.b64decode(content)
                            if img_bytes and len(img_bytes) > 1000 and _is_valid_image(img_bytes):
                                _save_as_jpg(img_bytes, fp)
                                out.append(str(fp))
                                if verbose:
                                    print(f"  ✓ image {i} via Oxylabs ({len(img_bytes):,} bytes)")
                                continue
                        except Exception:
                            pass
            
            if verbose:
                print(f"  ✗ image {i}: Oxylabs failed")
                
        except Exception as e:
            if verbose:
                print(f"  ✗ image {i}: {str(e)[:50]}")

    return out


def _save_as_jpg(data: bytes, fp: Path) -> bool:
    """Convert image to JPG and save."""
    try:
        im = Image.open(io.BytesIO(data))
        rgb = im.convert("RGB")
        rgb.save(fp, format="JPEG", quality=92, optimize=True)
        return True
    except Exception:
        # Fallback: save raw
        fp.write_bytes(data)
        return True


# ---------------------------
# Public API
# ---------------------------
def fetch_jdw_product_with_oxylabs(url: str, verbose: bool = True) -> Dict[str, Any]:
    if verbose:
        print(f"Fetching {url}...")
    
    # Try to fetch HTML with retry logic
    try:
        html = _oxylabs_universal_html(url, country="United Kingdom", timeout=75, verbose=verbose)
    except RuntimeError as e:
        err_str = str(e)
        
        # Check if this is an invalid page signal
        if "INVALID_PAGE:" in err_str:
            reason = err_str.split("INVALID_PAGE:")[-1]
            if verbose:
                print(f"✗ Invalid link detected (fetch failed): {reason}")
            
            # Return invalid product result
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
        
        # Re-raise other errors
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

    folder = SAVE_ROOT / f"{_retailer_slug(url)}_{_safe_name(name)}_{_stable_id_from_url(url)}"
    
    if verbose:
        print(f"\nDownloading {len(image_urls)} images...")
    
    imgs = _download_images_jpg(image_urls, folder, page_url=url, verbose=verbose)

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
#         TEST_URL = "https://www.jdwilliams.co.uk/shop/p/mp129"
    
#     print(f"\n{'='*60}")
#     print(f"Testing: {TEST_URL}")
#     print(f"{'='*60}\n")
    
#     try:
#         data = fetch_jdw_product_with_oxylabs(TEST_URL, verbose=True)
#         print("\n" + "=" * 60)
#         print("RESULTS:")
#         print("=" * 60)
#         print(json.dumps(data, indent=2, ensure_ascii=False))
#     except Exception as e:
#         print(f"\n✗ ERROR: {e}")