
# oxylabs_amazon_dropin.py
# Version: 2.5 - Added debug output and improved stock detection

import re, html, json, time, hashlib, uuid
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlparse, parse_qs
import requests

from oxylabs_secrets import OXY_USER, OXY_PASS

__version__ = "2.5"

# ---------------- paths & UA ----------------
try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()
SAVE_DIR = BASE_DIR / "data1"
DEBUG_DIR = BASE_DIR / "debug"
SAVE_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

UA_STR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/127.0.0.0 Safari/537.36")

# ---------------- helpers ----------------
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()

def _safe_name(s: str, max_len: int = 50) -> str:
    n = re.sub(r"[^\w\s-]", "", (s or "")).strip().replace(" ", "_")
    n = n or "NA"
    if len(n) > max_len:
        n = n[:max_len].rstrip("_")
    return n

def _asin_from_url(u: str) -> str:
    p = urlparse(u)
    m = re.search(r"/dp/([A-Z0-9]{10})", p.path)
    if m:
        return m.group(1)
    q = parse_qs(p.query or "")
    for k in ("asin", "ASIN"):
        if q.get(k):
            a = q[k][0]
            if re.fullmatch(r"[A-Z0-9]{10}", a):
                return a
    return hashlib.sha1(u.encode("utf-8")).hexdigest()[:10]

def _norm_price(s: str) -> str | None:
    s = (s or "").replace("\xa0", " ")
    m = re.search(r"([£$€]\s?\d[\d,]*(?:\.\d{2})?)", s)
    return m.group(1).replace(" ", "") if m else None

def _unique_suffix() -> str:
    t = int(time.time() * 1000) % 10_000_000
    u = uuid.uuid4().hex[:6]
    return f"{t}_{u}"

# ---------------- Oxylabs core ----------------
_REALTIME_URL = "https://realtime.oxylabs.io/v1/queries"

_session = requests.Session()
_session.headers.update({
    "User-Agent": UA_STR,
    "Accept": "application/json",
    "Content-Type": "application/json",
})

def _oxylabs_fetch_amazon_parsed(url_or_asin: str, geo_location: str, timeout: int = 180) -> dict:
    """Fetch Amazon product with parsed data."""
    is_url = bool(re.match(r"^https?://", url_or_asin, re.I))
    if is_url:
        asin = _asin_from_url(url_or_asin)
        is_asin = bool(re.fullmatch(r"[A-Z0-9]{10}", asin))
    else:
        asin = url_or_asin
        is_asin = bool(re.fullmatch(r"[A-Z0-9]{10}", asin))

    payload = {
        "source": "amazon_product" if is_asin else "amazon",
        ("query" if is_asin else "url"): (asin if is_asin else url_or_asin),
        "geo_location": geo_location,
        "parse": True
    }

    r = _session.post(_REALTIME_URL, auth=(OXY_USER, OXY_PASS),
                      data=json.dumps(payload), timeout=timeout)
    r.raise_for_status()
    return r.json()


def _oxylabs_fetch_amazon_html(url: str, geo_location: str, timeout: int = 180) -> str:
    """Fetch raw HTML from Amazon via Oxylabs."""
    asin = _asin_from_url(url)
    is_asin = bool(re.fullmatch(r"[A-Z0-9]{10}", asin))
    
    payload = {
        "source": "amazon_product" if is_asin else "amazon",
        ("query" if is_asin else "url"): (asin if is_asin else url),
        "geo_location": geo_location,
        "parse": False
    }
    
    r = _session.post(_REALTIME_URL, auth=(OXY_USER, OXY_PASS),
                      data=json.dumps(payload), timeout=timeout)
    r.raise_for_status()
    data = r.json()
    
    result = (data.get("results") or [{}])[0]
    return result.get("content") or ""


# ---------------- Stock Detection from HTML ----------------
def _parse_stock_from_html(html_content: str, target_asin: str = "", verbose: bool = False) -> Tuple[Optional[bool], str]:
    """
    Parse stock status directly from HTML content.
    """
    if not html_content:
        return None, "No HTML content"
    
    html_lower = html_content.lower()
    
    # Debug: Save HTML for inspection
    if verbose:
        debug_file = DEBUG_DIR / f"amazon_{target_asin}_{_unique_suffix()}.html"
        debug_file.write_text(html_content, encoding='utf-8')
        print(f"  → Debug HTML saved to: {debug_file}")
    
    # Debug: Check what stock-related elements exist
    if verbose:
        print(f"  → Checking HTML for stock indicators...")
        print(f"     - 'outofstock' in HTML: {'id=\"outofstock\"' in html_lower or 'id=\"outOfStock\"' in html_content}")
        print(f"     - 'currently unavailable' in HTML: {'currently unavailable' in html_lower}")
        print(f"     - 'id=\"availability\"' in HTML: {'id=\"availability\"' in html_lower}")
        print(f"     - 'add-to-cart-button' in HTML: {'add-to-cart-button' in html_lower}")
        print(f"     - 'in stock' in HTML: {'in stock' in html_lower}")
    
    # Priority 1: Check for outOfStock div (MOST RELIABLE)
    if 'id="outofstock"' in html_lower or 'id="outOfStock"' in html_content:
        if verbose:
            print(f"  → Found outOfStock div!")
        return False, "Currently unavailable"
    
    # Priority 2: Search for "Currently unavailable" text anywhere in key areas
    # Extract the availability section
    avail_match = re.search(
        r'id="availability"[^>]*>(.*?)</div>',
        html_content,
        re.DOTALL | re.IGNORECASE
    )
    
    if avail_match:
        avail_text = _clean(re.sub(r'<[^>]+>', ' ', avail_match.group(1))).lower()
        if verbose:
            print(f"  → Availability text: '{avail_text[:100]}...'")
        
        # Check for unavailable patterns
        if "currently unavailable" in avail_text:
            return False, "Currently unavailable"
        if "out of stock" in avail_text:
            return False, "Out of stock"
        if "we don't know when" in avail_text:
            return False, "Currently unavailable"
        
        # Check for in-stock patterns
        if "in stock" in avail_text:
            # Extract more specific message
            match = re.search(r'(only \d+ left|in stock[^.]*)', avail_text, re.I)
            return True, match.group(0).capitalize() if match else "In Stock"
    
    # Priority 3: Check for "Currently unavailable" in spans with specific classes
    # This catches: <span class="a-size-medium a-color-success"> Currently unavailable. </span>
    unavail_spans = re.findall(
        r'<span[^>]*>([^<]*currently unavailable[^<]*)</span>',
        html_content,
        re.I
    )
    if unavail_spans:
        if verbose:
            print(f"  → Found unavailable span: '{unavail_spans[0][:50]}'")
        return False, "Currently unavailable"
    
    # Priority 4: Check the entire buybox/right column area
    # Look for "Currently unavailable" in the buy box
    buybox_patterns = [
        r'id="rightCol"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        r'id="buybox"[^>]*>(.*?)</div>',
        r'id="desktop_buybox"[^>]*>(.*?)</div>',
    ]
    for pattern in buybox_patterns:
        match = re.search(pattern, html_content, re.DOTALL | re.I)
        if match:
            text = _clean(re.sub(r'<[^>]+>', ' ', match.group(1))).lower()
            if "currently unavailable" in text:
                if verbose:
                    print(f"  → Found 'currently unavailable' in buybox area")
                return False, "Currently unavailable"
    
    # Priority 5: Check if add-to-cart button exists and is NOT disabled
    add_cart_match = re.search(r'id="add-to-cart-button"[^>]*>', html_content, re.I)
    if add_cart_match:
        button_html = add_cart_match.group(0)
        if 'disabled' not in button_html.lower():
            # Button exists and is not disabled - but double check for unavailable text
            if "currently unavailable" not in html_lower[:50000]:  # Check first 50KB
                if verbose:
                    print(f"  → Add to cart button found and enabled")
                return True, "Add to cart available"
    
    # Priority 6: Final scan - if "Currently unavailable" appears prominently
    # Count occurrences
    unavail_count = html_lower.count("currently unavailable")
    in_stock_count = html_lower.count("in stock")
    
    if verbose:
        print(f"  → 'currently unavailable' count: {unavail_count}")
        print(f"  → 'in stock' count: {in_stock_count}")
    
    if unavail_count > 0 and unavail_count >= in_stock_count:
        return False, "Currently unavailable"
    
    if in_stock_count > unavail_count:
        return True, "In Stock"
    
    return None, "Stock status unknown"


def _parse_stock_status(stock_text: str, content: dict) -> Tuple[Optional[bool], str]:
    """Parse stock status from Oxylabs parsed response (fallback)."""
    stock_text = (stock_text or "").strip()
    stock_lower = stock_text.lower()
    
    unavailable_patterns = [
        "currently unavailable",
        "not available",
        "out of stock",
        "we don't know when",
        "won't be back in stock",
        "no longer available",
        "unavailable",
    ]
    for pattern in unavailable_patterns:
        if pattern in stock_lower:
            return False, stock_text or "Currently unavailable"
    
    in_stock_patterns = [
        "in stock",
        "only",
        "left in stock",
        "ships from",
        "usually ships",
        "more on the way",
    ]
    for pattern in in_stock_patterns:
        if pattern in stock_lower:
            if "not " not in stock_lower and "unavailable" not in stock_lower:
                return True, stock_text
    
    if "cannot be shipped" in stock_lower:
        return None, stock_text or "Shipping restricted"
    
    return None, stock_text or "Stock status unknown"


# ---------------- Invalid Link Detection ----------------
def _check_invalid_product(content: dict, html_content: str, url: str) -> Tuple[bool, str]:
    """Check if the Amazon product page indicates an invalid/removed product."""
    title = content.get("title") or ""
    
    if not title or title == "N/A":
        return True, "no_product_title"
    
    error_titles = ["page not found", "404", "sorry!", "we're sorry"]
    for pattern in error_titles:
        if pattern in title.lower():
            return True, f"error_title:{pattern}"
    
    if html_content:
        if "sorry, we couldn't find that page" in html_content.lower():
            return True, "404_page"
    
    asin = content.get("asin") or ""
    if not asin and not content.get("price") and not content.get("images"):
        return True, "no_product_data"
    
    return False, "valid"


def _create_invalid_result(url: str, reason: str, country_code: str, zip_code: str, geo_location: str) -> dict:
    """Create a result dict for invalid/unavailable products."""
    return {
        "name": "INVALID LINK - Product removed or no longer available",
        "price": "N/A",
        "price_source": "invalid",
        "in_stock": False,
        "stock_text": reason,
        "description": "",
        "image_count": 0,
        "images": [],
        "folder": str(SAVE_DIR),
        "country_set": country_code,
        "zip_used": zip_code,
        "delivery_header": f"Deliver to: {geo_location}",
        "is_invalid": True,
        "invalid_reason": reason,
    }


# ---------------- main ----------------
def scrape_amazon_product(url: str, *, headless: bool = False, country_code: str = "US",
                          zip_code: str | None = None, max_images: int | None = None,
                          verbose: bool = True, verify_stock_html: bool = True,
                          debug: bool = False) -> dict:
    """Scrape Amazon product with optional HTML verification for stock status."""
    if verbose:
        print(f"Fetching {url}...")
    
    geo_location = zip_code if zip_code else (country_code or "US")
    target_asin = _asin_from_url(url)

    # Step 1: Fetch parsed data
    try:
        data = _oxylabs_fetch_amazon_parsed(url, geo_location=geo_location)
    except Exception as e:
        if verbose:
            print(f"✗ Fetch error: {e}")
        return _create_invalid_result(url, f"fetch_error:{str(e)[:50]}", country_code, zip_code, geo_location)

    result = (data.get("results") or [{}])[0]
    content = result.get("content") or {}

    if verbose:
        print(f"  ✓ Received Oxylabs parsed response")
        print(f"  → Target ASIN: {target_asin}")
        # Show what Oxylabs parsed thinks about stock
        oxylabs_stock = content.get("stock", "")
        print(f"  → Oxylabs parsed stock: '{oxylabs_stock}'")

    # Step 2: Fetch raw HTML for stock verification
    html_content = ""
    if verify_stock_html:
        try:
            if verbose:
                print(f"  → Fetching HTML for stock verification...")
            html_content = _oxylabs_fetch_amazon_html(url, geo_location=geo_location)
            if verbose:
                print(f"  ✓ Received HTML ({len(html_content):,} bytes)")
        except Exception as e:
            if verbose:
                print(f"  ⚠ HTML fetch failed: {e} (using parsed data only)")

    # Step 3: Check for invalid product
    is_invalid, invalid_reason = _check_invalid_product(content, html_content, url)
    if is_invalid:
        if verbose:
            print(f"✗ Invalid product detected: {invalid_reason}")
        return _create_invalid_result(url, invalid_reason, country_code, zip_code, geo_location)

    # Step 4: Extract product data
    title = content.get("title") or "N/A"
    price_num = content.get("price")
    currency = (content.get("currency") or "").strip()

    if isinstance(price_num, (int, float)) and price_num > 0:
        price_str = f"{currency}{price_num}" if currency else f"{price_num}"
    else:
        price_str = _norm_price(content.get("pricing_str") or "") or "N/A"

    # Step 5: Parse stock status with debug output
    stock_source = "parsed"
    if html_content:
        in_stock, stock_text = _parse_stock_from_html(html_content, target_asin=target_asin, verbose=debug)
        if in_stock is not None:
            stock_source = "html"
        else:
            stock_text_raw = content.get("stock") or ""
            in_stock, stock_text = _parse_stock_status(stock_text_raw, content)
    else:
        stock_text_raw = content.get("stock") or ""
        in_stock, stock_text = _parse_stock_status(stock_text_raw, content)

    # Step 6: Description
    bullet_points = content.get("bullet_points") or ""
    if bullet_points:
        points = [p.strip() for p in bullet_points.split("\n") if p.strip()]
        description = "\n• " + "\n• ".join(points) if points else "N/A"
    else:
        description = content.get("description") or "N/A"

    images_urls = content.get("images") or []

    if verbose:
        print(f"  Name: {_clean(title)[:60]}...")
        print(f"  Price: {price_str}")
        print(f"  In Stock: {in_stock} ({stock_text}) [source: {stock_source}]")
        print(f"  Images found: {len(images_urls)}")

    if max_images is not None:
        images_urls = images_urls[:max_images]

    asin_guess = content.get("asin") or target_asin
    folder = SAVE_DIR / f"amazon_{_safe_name(title)}_{asin_guess}_{_unique_suffix()}"
    folder.mkdir(parents=True, exist_ok=True)

    if verbose and images_urls:
        print(f"\nDownloading {len(images_urls)} images...")
    
    downloaded = []
    for idx, u in enumerate(images_urls, start=1):
        try:
            img = _session.get(u, timeout=30)
            ct = (img.headers.get("content-type") or "").lower()
            if img.ok and ct.startswith("image/"):
                ext = ".jpg"
                if "png" in ct: ext = ".png"
                elif "webp" in ct: ext = ".webp"
                path = folder / f"image_{idx}{ext}"
                path.write_bytes(img.content)
                downloaded.append(str(path))
                if verbose:
                    print(f"  ✓ image {idx}")
        except Exception as e:
            if verbose:
                print(f"  ✗ image {idx}: {e}")

    return {
        "name": _clean(title),
        "price": price_str,
        "price_source": "oxylabs.parsed",
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_count": len(downloaded),
        "images": downloaded,
        "folder": str(folder),
        "country_set": country_code,
        "zip_used": zip_code,
        "delivery_header": f"Deliver to: {geo_location}",
        "is_invalid": False,
        "invalid_reason": None,
    }


# # ---------------- CLI ----------------
# if __name__ == "__main__":
#     import sys
    
#     if len(sys.argv) > 1:
#         TEST_URL = sys.argv[1]
#     else:
#         TEST_URL = "https://www.amazon.com/Laura-Ashley-Stainless-Electric-Kettle/dp/B0DPLM3KN5?ref_=ast_sto_dp&th=1"
    
#     print(f"\n{'='*60}")
#     print(f"Testing: {TEST_URL}")
#     print(f"{'='*60}\n")
    
#     result = scrape_amazon_product(
#         TEST_URL,
#         headless=False,
#         country_code="US",
#         zip_code="10001",
#         max_images=None,
#         verbose=True,
#         verify_stock_html=True,
#         debug=True  # Enable debug to save HTML and show detailed checks
#     )
    
#     print("\n" + "="*60)
#     print("🛒 AMAZON PRODUCT SCRAPE RESULT")
#     print("="*60)
    
#     print(f"\n📦 Name:\n   {result['name']}")
#     print(f"\n💰 Price: {result['price']}")
#     print(f"   Source: {result['price_source']}")
    
#     stock_icon = "✅" if result['in_stock'] else ("❌" if result['in_stock'] is False else "❓")
#     print(f"\n📊 Stock: {stock_icon} {result['stock_text'] or 'Unknown'}")
    
#     if result.get('is_invalid'):
#         print(f"\n⚠️  INVALID: {result['invalid_reason']}")
    
#     print(f"\n📝 Description:")
#     desc_lines = result['description'].split('\n')[:5]
#     for line in desc_lines:
#         print(f"   {line}")
#     if len(result['description'].split('\n')) > 5:
#         print(f"   ... (truncated)")
    
#     print(f"\n🖼️  Images: {result['image_count']} downloaded")
#     for img in result['images'][:5]:
#         print(f"   - {Path(img).name}")
#     if len(result['images']) > 5:
#         print(f"   ... and {len(result['images']) - 5} more")
    
#     print(f"\n📍 Location: {result['country_set']} / ZIP: {result['zip_used']}")
#     print(f"   {result['delivery_header']}")
    
#     print(f"\n📁 Folder:\n   {result['folder']}")
#     print("\n" + "="*60 + "\n")


