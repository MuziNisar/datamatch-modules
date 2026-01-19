







# oxylabs_amazon_dropin.py
# Drop-in replacement for your original Playwright scraper.
# - Keeps: function name, signature, return keys, and CLI behavior.
# - Internals: uses Oxylabs Web Scraper API (Realtime) with parsed Amazon data.
# - Requires: oxylabs_secrets.py containing OXY_USER, OXY_PASS

import re, html, json, time, hashlib, uuid
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import requests

from oxylabs_secrets import OXY_USER, OXY_PASS

# ---------------- paths & UA (kept for compatibility) ----------------
try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()
SAVE_DIR = BASE_DIR / "data1"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

UA_STR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/127.0.0.0 Safari/537.36")

# ---------------- helpers (kept) ----------------
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()

def _safe_name(s: str, max_len: int = 50) -> str:
    n = re.sub(r"[^\w\s-]", "", (s or "")).strip().replace(" ", "_")
    n = n or "NA"
    # Truncate to avoid Windows path length issues
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

# ---------------- Oxylabs core ----------------
_REALTIME_URL = "https://realtime.oxylabs.io/v1/queries"

_session = requests.Session()
_session.headers.update({
    "User-Agent": UA_STR,
    "Accept": "application/json",
    "Content-Type": "application/json",
})

def _oxylabs_fetch_amazon(url_or_asin: str, geo_location: str, timeout: int = 180) -> dict:
    """
    Calls Oxylabs Realtime API for Amazon product page.
    Returns Oxylabs' raw JSON decoded.
    """
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
        "geo_location": geo_location,     # ZIP like "90210" or country code like "US"
        "parse": True
    }

    r = _session.post(_REALTIME_URL, auth=(OXY_USER, OXY_PASS),
                      data=json.dumps(payload), timeout=timeout)
    r.raise_for_status()
    return r.json()

def _unique_suffix() -> str:
    # short unique suffix per run (time + uuid fragment)
    t = int(time.time() * 1000) % 10_000_000
    u = uuid.uuid4().hex[:6]
    return f"{t}_{u}"

# ---------------- main (drop-in) ----------------
def scrape_amazon_product(url: str, *, headless: bool = False, country_code: str = "UM",
                          zip_code: str | None = None, max_images: int | None = None) -> dict:
    """
    Drop-in replacement:
    - keeps same signature & return schema as your original function
    - ignores Playwright-specific 'headless' internally (kept for compatibility)
    - uses Oxylabs geo_location set from zip_code or country_code
    """
    # Decide geo_location (ZIP has priority; else country code; else default US)
    geo_location = None
    if zip_code:
        geo_location = str(zip_code)
    elif country_code:
        # Oxylabs accepts country or ZIP; pass the ISO code directly
        geo_location = country_code
    else:
        geo_location = "US"

    # Call Oxylabs
    try:
        data = _oxylabs_fetch_amazon(url, geo_location=geo_location)
        # DEBUG: Print full response to see available fields
        # print("\n" + "="*60)
        # print("🔍 DEBUG: Full Oxylabs Response")
        # print("="*60)
        # print(json.dumps(data, indent=2))
        # print("="*60 + "\n")
    except Exception as e:
        # On error, return a minimal structured dict similar to original failures
        return {
            "name": "N/A",
            "price": "N/A",
            "price_source": "oxylabs.error",
            "in_stock": None,
            "stock_text": f"ERROR: {e}",
            "description": "N/A",
            "image_count": 0,
            "images": [],
            "folder": str(SAVE_DIR),
            "country_set": country_code,
            "zip_used": zip_code,
            "delivery_header": f"Deliver to: {geo_location}",
        }

    # Extract parsed content
    result = (data.get("results") or [{}])[0]
    content = result.get("content") or {}

    title = content.get("title") or "N/A"
    price_num = content.get("price")
    currency = (content.get("currency") or "").strip()

    # Normalize price to string like your original
    if isinstance(price_num, (int, float)) and price_num > 0:
        price_str = f"{currency}{price_num}" if currency else f"{price_num}"
    else:
        price_str = _norm_price(content.get("pricing_str") or "") or "N/A"

    stock_text = content.get("stock") or ""
    in_stock = None
    if stock_text:
        st = stock_text.lower()
        if any(x in st for x in ["in stock", "only", "ships from", "usually ships", "more on the way", "available"]):
            in_stock = True
        elif any(x in st for x in ["unavailable", "out of stock", "temporarily", "currently unavailable", "cannot be shipped"]):
            # align with your tri-state: None if "cannot be shipped" (shipping restriction)
            in_stock = None if "cannot be shipped" in st else False

    # Prefer bullet_points (About this item) over description
    bullet_points = content.get("bullet_points") or ""
    if bullet_points:
        # Split by newline and format as bullet list
        points = [p.strip() for p in bullet_points.split("\n") if p.strip()]
        description = "\n• " + "\n• ".join(points) if points else "N/A"
    else:
        description = content.get("description") or "N/A"

    images_urls = content.get("images") or []

    # Restrict number of images if requested
    if max_images is not None:
        images_urls = images_urls[:max_images]

    # Prepare unique folder name each time
    asin_guess = content.get("asin") or _asin_from_url(content.get("url") or url)
    folder = SAVE_DIR / f"amazon_{_safe_name(title)}_{asin_guess}_{_unique_suffix()}"
    folder.mkdir(parents=True, exist_ok=True)

    # Download images to disk (to keep your original behavior)
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
        except Exception:
            # quietly skip bad links (matches your original tolerance)
            pass

    # Build return payload exactly like before
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
    }

# # ---------------- CLI (kept) ----------------
# if __name__ == "__main__":
#     result = scrape_amazon_product(
#         "https://www.amazon.com/Laura-Ashley-Stainless-Electric-Kettle/dp/B0DJH88LB1?ref_=ast_sto_dp&th=1",
#         headless=False,
#         country_code="US",
#         zip_code="10001",
#         max_images=None
#     )
    
#     # Formatted output for testing
#     print("\n" + "="*60)
#     print("🛒 AMAZON PRODUCT SCRAPE RESULT")
#     print("="*60)
    
#     print(f"\n📦 Name:\n   {result['name']}")
#     print(f"\n💰 Price: {result['price']}")
#     print(f"   Source: {result['price_source']}")
    
#     stock_icon = "✅" if result['in_stock'] else ("❌" if result['in_stock'] is False else "❓")
#     print(f"\n📊 Stock: {stock_icon} {result['stock_text'] or 'Unknown'}")
    
#     print(f"\n📝 Description:")
#     for line in result['description'].split('\n'):
#         print(f"   {line}")
    
#     print(f"\n🖼️  Images: {result['image_count']} downloaded")
#     for img in result['images']:
#         print(f"   - {Path(img).name}")
    
#     print(f"\n📍 Location: {result['country_set']} / ZIP: {result['zip_used']}")
#     print(f"   {result['delivery_header']}")
    
#     print(f"\n📁 Folder:\n   {result['folder']}")
#     print("\n" + "="*60 + "\n")







