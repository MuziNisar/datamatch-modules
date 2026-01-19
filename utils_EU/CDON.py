







# CDON.py — Oxylabs Web Scraper API (no browser_instructions, robust retries, JPG conversion)
# Python 3.10+
#
# pip install requests beautifulsoup4 lxml pillow pillow-avif-plugin
# oxylabs_secrets.py must define:
#   OXY_USER = "..."
#   OXY_PASS = "..."

from __future__ import annotations

import json, re, time, random, hashlib, html as htmlmod
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from io import BytesIO
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from PIL import Image

# Optional AVIF/HEIF decode support
try:
    import pillow_avif  # noqa: F401
except Exception:
    pass

# -----------------------------
# Config
# -----------------------------
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
LOCALE = "sv-SE"
GEO_LOCATION = "Sweden"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "Data1"
DEBUG_DIR = BASE_DIR / "debug"
DATA_DIR.mkdir(exist_ok=True)
DEBUG_DIR.mkdir(exist_ok=True)

# Credentials
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception as e:
    OXY_USER = None
    OXY_PASS = None
    print("[CDON] Warning: oxylabs_secrets.py not found - using test mode only")

OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"

# -----------------------------
# Small utils
# -----------------------------
def _vprint(verbose: bool, *args):
    if verbose:
        print(*args)

def _ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _clean_multiline(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _safe_name(s: str) -> str:
    """Create a safe filename by transliterating Unicode to ASCII and removing special chars."""
    s = _clean(s)
    
    transliterations = {
        'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
        'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
        'à': 'a', 'á': 'a', 'â': 'a', 'ã': 'a', 'å': 'a',
        'è': 'e', 'é': 'e', 'ê': 'e', 'ë': 'e',
        'ì': 'i', 'í': 'i', 'î': 'i', 'ï': 'i',
        'ò': 'o', 'ó': 'o', 'ô': 'o', 'õ': 'o',
        'ù': 'u', 'ú': 'u', 'û': 'u',
        'ç': 'c', 'ñ': 'n',
        'æ': 'ae', 'œ': 'oe',
        'Å': 'A', 'å': 'a',
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
        'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        'Ą': 'A', 'Ć': 'C', 'Ę': 'E', 'Ł': 'L', 'Ń': 'N',
        'Ó': 'O', 'Ś': 'S', 'Ź': 'Z', 'Ż': 'Z',
        '–': '-', '—': '-', ''': '', ''': '', '"': '', '"': '',
        '«': '', '»': '', '…': '', '•': '', '™': '', '®': '', '©': '',
        '/': '_', '\\': '_', ':': '_', '*': '_', '?': '_', '"': '_',
        '<': '_', '>': '_', '|': '_',
    }
    
    for unicode_char, ascii_equiv in transliterations.items():
        s = s.replace(unicode_char, ascii_equiv)
    
    s = s.encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r"[^\w.\-]+", "_", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_")
    
    # return s[:120] or "product"
    return s[:60] or "product"  # Shortened to prevent Windows path length issues

def _stable_id_from_url(url: str) -> str:
    try:
        parts = [p for p in urlsplit(url).path.split("/") if p]
        candidates = [p for p in parts if re.search(r"[0-9a-f\-]{16,}", p, re.I)]
        token = (candidates[-1] if candidates else parts[-1]) if parts else ""
        if token:
            return re.sub(r"[^\w\-]+", "", token)
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

def _replace_imwidth(u: str, width: int = 1200) -> str:
    sp = urlsplit(u)
    q = dict(parse_qsl(sp.query, keep_blank_values=True))
    q["imWidth"] = str(width)
    return sp._replace(query=urlencode(q, doseq=True)).geturl()

def _strip_query_and_imwidth(u: str) -> str:
    sp = urlsplit(u)
    q = dict(parse_qsl(sp.query, keep_blank_values=True))
    q.pop("imWidth", None)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, urlencode(q, doseq=True), ""))

def _dedupe_preserve_order(urls: List[str]) -> List[str]:
    seen = set(); out: List[str] = []
    for u in urls:
        if not u: continue
        key = _strip_query_and_imwidth(u)
        if key in seen: continue
        seen.add(key); out.append(u)
    return out

def _parse_price_text_block(text: str) -> Optional[str]:
    m = re.search(r"(\d[\d\s.,]*)\s*SEK", text, re.I)
    if not m: return None
    num = re.sub(r"\s+", "", m.group(1))
    return f"{num} SEK"

# -----------------------------
# Invalid Link Detection
# -----------------------------
def _check_invalid_product_page(soup: BeautifulSoup, url: str, verbose: bool = False) -> bool:
    """
    Check if the page is NOT a valid product page.
    
    CDON redirects unavailable products to category listing pages.
    These listing pages have:
    1. Pagination navigation (nav with aria-label="Paginering" - SWEDISH!)
    2. Multiple product cards
    3. No single product details (no JSON-LD Product, no add-to-cart button)
    
    IMPORTANT: Out-of-stock products are still VALID product pages!
    
    Returns True if this is an INVALID product page (should return "Invalid Link").
    """
    
    # ============ STRONG INDICATORS OF VALID PRODUCT PAGE ============
    # If ANY of these are present, it's likely a valid product (even if out of stock)
    
    # Check for JSON-LD Product schema
    has_product_schema = False
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    has_product_schema = True
                    _vprint(verbose, "[CDON] ✓ Found JSON-LD Product schema - valid product page")
                    break
        except Exception:
            continue
        if has_product_schema:
            break
    
    # If we have Product schema, it's definitely a valid product page
    if has_product_schema:
        return False  # Valid product page
    
    # Check for add-to-cart button
    add_to_cart = soup.select_one(
        "[data-cy='pdp-add-to-cart'], "
        "[data-testid='pdp-add-to-cart'], "
        "button[class*='add-to-cart'], "
        "[data-testid='add-to-cart-button']"
    )
    if add_to_cart:
        _vprint(verbose, "[CDON] ✓ Found add-to-cart button - valid product page")
        return False  # Valid product page
    
    # Check for product image gallery
    product_gallery = soup.select("[role='tablist'] img, [data-testid='image-panel'] img")
    if len(product_gallery) >= 1:
        _vprint(verbose, "[CDON] ✓ Found product gallery images - valid product page")
        return False  # Valid product page
    
    # Check for h1 product title on a /produkt/ URL
    path = urlsplit(url).path.lower()
    h1 = soup.select_one("h1")
    if "/produkt/" in path and h1 and len(h1.get_text(strip=True)) > 3:
        # Additional check: make sure there's no pagination on this page
        pagination = soup.select_one('nav[aria-label="Paginering"], nav[aria-label="Pagination"]')
        if not pagination:
            _vprint(verbose, "[CDON] ✓ Found h1 title on /produkt/ URL without pagination - valid product page")
            return False  # Valid product page
    
    # ============ STRONG INDICATORS OF INVALID/CATEGORY PAGE ============
    
    # Check 1: Pagination exists (SWEDISH: "Paginering")
    # This is the STRONGEST indicator of a category/listing page
    pagination = soup.select_one(
        'nav[aria-label="Paginering"], '  # Swedish
        'nav[aria-label="Pagination"], '  # English fallback
        'nav[role="navigation"][aria-label*="aginering"], '  # Partial match
        'nav[role="navigation"][aria-label*="agination"]'    # Partial match
    )
    
    if pagination:
        # Check if it has multiple page links
        page_links = pagination.select('a[aria-label*="sida"], a[aria-label*="page"]')
        if len(page_links) >= 3:
            _vprint(verbose, f"[CDON] ✗ Detected pagination with {len(page_links)} page links - category page")
            return True
    
    # Check 2: Multiple "Gå till sida X" links (Swedish pagination)
    page_nav_links = soup.select('a[aria-label^="Gå till sida"], a[aria-label^="Go to page"]')
    if len(page_nav_links) >= 3:
        _vprint(verbose, f"[CDON] ✗ Detected {len(page_nav_links)} page navigation links - category page")
        return True
    
    # Check 3: URL doesn't contain /produkt/
    if "/produkt/" not in path:
        _vprint(verbose, "[CDON] ✗ URL path doesn't contain /produkt/ - not a product page")
        return True
    
    # Check 4: Multiple product cards (listing page indicator)
    product_cards = soup.select(
        "[data-testid='product-card'], "
        "[class*='product-card'], "
        "[class*='ProductCard'], "
        "article[class*='product']"
    )
    if len(product_cards) >= 4:
        _vprint(verbose, f"[CDON] ✗ Found {len(product_cards)} product cards - category page")
        return True
    
    # Check 5: Explicit "product not found" messages
    page_text = soup.get_text(" ", strip=True).lower()
    not_found_phrases = [
        "produkten finns inte",
        "produkten är inte tillgänglig",
        "denna produkt finns inte längre",
        "product not found",
        "product is not available",
        "sidan kunde inte hittas",
        "page not found",
    ]
    for phrase in not_found_phrases:
        if phrase in page_text:
            _vprint(verbose, f"[CDON] ✗ Found 'not found' phrase: {phrase}")
            return True
    
    # If we reach here, we're not sure - assume it's valid to avoid false positives
    _vprint(verbose, "[CDON] ? Uncertain - assuming valid product page")
    return False


def detect_invalid_link_from_html(html: str, url: str, verbose: bool = False) -> Tuple[bool, str, Dict]:
    """
    Standalone function to detect invalid links from HTML content.
    
    Returns:
        (is_invalid, reason, details_dict)
    """
    soup = BeautifulSoup(html, "lxml")
    
    details = {
        'has_product_schema': False,
        'has_add_to_cart': False,
        'has_gallery': False,
        'has_pagination': False,
        'pagination_pages': 0,
        'product_cards': 0,
        'url_has_produkt': '/produkt/' in urlsplit(url).path.lower(),
    }
    
    # Check JSON-LD Product schema
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    details['has_product_schema'] = True
                    break
        except Exception:
            continue
    
    # Check add-to-cart
    add_to_cart = soup.select_one(
        "[data-cy='pdp-add-to-cart'], [data-testid='pdp-add-to-cart'], "
        "button[class*='add-to-cart'], [data-testid='add-to-cart-button']"
    )
    details['has_add_to_cart'] = add_to_cart is not None
    
    # Check gallery
    gallery = soup.select("[role='tablist'] img, [data-testid='image-panel'] img")
    details['has_gallery'] = len(gallery) >= 1
    
    # Check pagination (Swedish: Paginering)
    pagination = soup.select_one(
        'nav[aria-label="Paginering"], nav[aria-label="Pagination"], '
        'nav[role="navigation"][aria-label*="aginering"]'
    )
    if pagination:
        details['has_pagination'] = True
        page_links = pagination.select('a[aria-label*="sida"], a[aria-label*="page"]')
        details['pagination_pages'] = len(page_links)
    
    # Check product cards
    product_cards = soup.select(
        "[data-testid='product-card'], [class*='product-card'], "
        "[class*='ProductCard'], article[class*='product']"
    )
    details['product_cards'] = len(product_cards)
    
    # Decision logic
    # Valid indicators
    if details['has_product_schema']:
        return False, "Valid: has JSON-LD Product schema", details
    
    if details['has_add_to_cart']:
        return False, "Valid: has add-to-cart button", details
    
    if details['has_gallery'] and details['url_has_produkt'] and not details['has_pagination']:
        return False, "Valid: has gallery on /produkt/ URL", details
    
    # Invalid indicators
    if details['has_pagination'] and details['pagination_pages'] >= 3:
        return True, f"Invalid: pagination with {details['pagination_pages']} pages (category page)", details
    
    if details['product_cards'] >= 4:
        return True, f"Invalid: {details['product_cards']} product cards (category page)", details
    
    if not details['url_has_produkt']:
        return True, "Invalid: URL doesn't contain /produkt/", details
    
    # Default to valid
    return False, "Uncertain: defaulting to valid", details


# -----------------------------
# Parsers (BS4)
# -----------------------------
def _extract_name_html(soup: BeautifulSoup) -> str:
    h1 = soup.select_one("h1")
    if h1 and h1.get_text(strip=True):
        return _clean(h1.get_text(" ", strip=True))
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return _clean(title.split("|")[0]) or "Unknown_Product"

def _extract_price_html(soup: BeautifulSoup, full_text: str) -> Tuple[str, str]:
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            raw = tag.string or tag.get_text("", strip=True)
            if not raw: continue
            data = json.loads(raw)
            objs = data if isinstance(data, list) else [data]
            for obj in objs:
                if isinstance(obj, dict) and obj.get("@type") == "Product":
                    offers = obj.get("offers") or {}
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    price = offers.get("price")
                    curr = offers.get("priceCurrency") or "SEK"
                    if price not in (None, ""):
                        p = f"{price} {curr}" if isinstance(price, str) else f"{str(price).replace(',', '.') } {curr}"
                        return _clean(p), "jsonld"
        except Exception:
            continue
    parsed = _parse_price_text_block(full_text)
    if parsed: return parsed, "onsite"
    return "N/A", "none"

def _extract_stock_html(soup: BeautifulSoup, full_text: str) -> Tuple[Optional[bool], Optional[str]]:
    btn = soup.select_one("[data-cy='pdp-add-to-cart'], [data-testid='pdp-add-to-cart']")
    
    if btn:
        btn_text = btn.get_text(" ", strip=True).lower()
        
        out_of_stock_phrases = [
            "out of stock", "temporarily out of stock", "tillfälligt slut",
            "slut i lager", "ej i lager", "inte tillgänglig", "unavailable", "not available",
        ]
        
        for phrase in out_of_stock_phrases:
            if phrase in btn_text:
                return False, _clean(btn.get_text(" ", strip=True))
        
        disabled = btn.has_attr("disabled") or str(btn.get("aria-disabled")).lower() == "true"
        if disabled:
            return False, "Out of Stock (button disabled)"
        
        return True, "In Stock"
    
    oos_re = re.compile(r"slut i lager|tillf[aä]lligt slut|ej i lager|inte tillg[aä]nglig|out of stock|temporarily out", re.I)
    m = oos_re.search(full_text)
    if m: 
        return False, _clean(m.group(0))
    
    return None, None

def _extract_description_html(soup: BeautifulSoup) -> str:
    region = soup.select_one("[aria-label*='Produktbeskrivning' i]")
    if region:
        return _clean_multiline(htmlmod.unescape(region.get_text("\n", strip=True)))
    patt = re.compile(r"Produktbeskrivning|Produkt|Beskrivning|Description", re.I)
    for t in soup.find_all(string=patt):
        parent = t.find_parent()
        if parent:
            return _clean_multiline(htmlmod.unescape(parent.get_text("\n", strip=True)))
    return ""

def _collect_gallery_urls_html(soup: BeautifulSoup, max_images: Optional[int]) -> List[str]:
    urls: List[str] = []
    for img in soup.select("[role='tablist'] img"):
        u = img.get("data-src") or img.get("src")
        if u and u.startswith("http"): urls.append(u)
        if max_images and len(urls) >= max_images: break
    if not urls:
        for img in soup.select("[data-testid='image-panel'] img, [id^='image-panel-'] img"):
            u = img.get("src")
            if u and u.startswith("http"): urls.append(u)
            if max_images and len(urls) >= max_images: break
    urls = [_replace_imwidth(u, 1200) for u in urls if u]
    urls = _dedupe_preserve_order(urls)
    return urls[:max_images] if max_images is not None else urls

# -----------------------------
# Oxylabs client
# -----------------------------
def _build_context_array(session_id: Optional[str]) -> list[dict]:
    ctx: list[dict] = []
    if session_id:
        ctx.append({"key": "session_id", "value": session_id})
    ctx.append({
        "key": "headers",
        "value": {
            "Accept-Language": LOCALE,
            "User-Agent": UA
        }
    })
    return ctx

def _build_payload(url: str, session_id: Optional[str]) -> Dict:
    return {
        "source": "universal",
        "url": url,
        "render": "html",
        "geo_location": GEO_LOCATION,
        "user_agent_type": "desktop",
        "context": _build_context_array(session_id),
    }

def _parse_retry_after(headers: Dict[str, str]) -> Optional[float]:
    ra = headers.get("Retry-After")
    if ra:
        try:
            return float(ra)
        except ValueError:
            try:
                dt = datetime.strptime(ra, "%a, %d %b %Y %H:%M:%S %Z")
                return max(0.0, (dt.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds())
            except Exception:
                pass
    xr = headers.get("X-RateLimit-Reset") or headers.get("X-Ratelimit-Reset")
    if xr:
        try:
            return max(0.0, float(xr) - time.time())
        except Exception:
            pass
    return None

def oxy_fetch_html(url: str, verbose: bool = False, max_retries: int = 6, base_sleep: float = 2.0) -> str:
    if not OXY_USER or not OXY_PASS:
        raise RuntimeError("Oxylabs credentials not configured")
    
    session_id = f"cdon-{int(time.time())}-{random.randint(1000,9999)}"

    def _post(payload: Dict) -> requests.Response:
        return requests.post(OXY_ENDPOINT, auth=(OXY_USER, OXY_PASS), json=payload, timeout=120)

    attempt = 0
    while attempt <= max_retries:
        payload = _build_payload(url, session_id=session_id)
        _vprint(verbose, f"[WSAPI] POST universal render=html (attempt {attempt+1}/{max_retries+1}, session={session_id})")
        r = _post(payload)

        if r.status_code == 200:
            data = r.json()
            try:
                return data["results"][0]["content"]
            except Exception:
                dbg = DEBUG_DIR / f"cdon_oxy_badshape_{int(time.time())}.json"
                dbg.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                raise RuntimeError(f"Unexpected WSAPI response shape. Saved to {dbg}")

        if r.status_code in (429, 500, 502, 503, 504):
            wait = _parse_retry_after(r.headers)
            if wait is None:
                wait = (base_sleep * (2 ** attempt)) + random.uniform(0.25, 0.75)
            _vprint(verbose, f"[WSAPI] HTTP {r.status_code} — backing off {wait:.2f}s …")
            time.sleep(min(wait, 30.0))
            attempt += 1
            continue

        dbg = DEBUG_DIR / f"cdon_oxy_error_{int(time.time())}.json"
        try:
            dbg.write_text(json.dumps(r.json(), indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            dbg.write_text(r.text, encoding="utf-8", errors="ignore")
        raise RuntimeError(f"Oxylabs HTTP {r.status_code}. Saved debug to {dbg}")

    raise RuntimeError("Exceeded max_retries for Oxylabs Realtime request.")

# -----------------------------
# Image download & conversion
# -----------------------------
def _img_to_jpg_bytes(raw: bytes) -> bytes:
    with Image.open(BytesIO(raw)) as im:
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            im_rgba = im.convert("RGBA")
            bg.paste(im_rgba, mask=im_rgba.split()[-1])
            out = BytesIO()
            bg.save(out, format="JPEG", quality=92, optimize=True, progressive=True)
            return out.getvalue()
        if im.mode != "RGB":
            im = im.convert("RGB")
        out = BytesIO()
        im.save(out, format="JPEG", quality=92, optimize=True, progressive=True)
        return out.getvalue()

def _download_and_save_jpg(img_url: str, out_jpg: Path, referer: Optional[str] = None, verbose: bool = False) -> bool:
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    try:
        rr = requests.get(img_url, headers=headers, timeout=40)
        if rr.status_code != 200 or not rr.content:
            _vprint(verbose, f"[IMG] HTTP {rr.status_code} {img_url}")
            return False
        try:
            jpg_bytes = _img_to_jpg_bytes(rr.content)
            out_jpg.write_bytes(jpg_bytes)
            _vprint(verbose, f"[IMG] Saved JPG -> {out_jpg.name}")
            return True
        except Exception as pe:
            if rr.headers.get("content-type", "").lower().startswith(("image/jpeg", "image/jpg")):
                out_jpg.write_bytes(rr.content)
                _vprint(verbose, f"[IMG] Saved RAW JPEG -> {out_jpg.name}")
                return True
            _vprint(verbose, f"[IMG] Convert error: {pe}")
            return False
    except Exception as e:
        _vprint(verbose, f"[IMG] Download error for {img_url}: {e}")
        return False

# -----------------------------
# Scraper
# -----------------------------
def scrape_cdon(url: str, max_images: Optional[int] = None, verbose: bool = False) -> Dict:
    html = oxy_fetch_html(url, verbose=verbose)

    if verbose:
        ts = int(time.time())
        (DEBUG_DIR / f"cdon_{ts}.html").write_text(html, encoding="utf-8", errors="ignore")

    soup = BeautifulSoup(html, "lxml")
    
    if _check_invalid_product_page(soup, url, verbose=verbose):
        print(f"[CDON] ⚠️ INVALID LINK: Product no longer available - {url[:80]}...")
        return {
            "url": url,
            "name": "Invalid Link - Product Not Available",
            "price": "N/A",
            "price_source": "none",
            "in_stock": False,
            "stock_text": "Product no longer available",
            "description": "",
            "image_count": 0,
            "image_urls": [],
            "images_downloaded": [],
            "folder": "",
            "context": {"locale": LOCALE, "geo_location": GEO_LOCATION},
            "listing_status": "invalid",
        }
    
    full_text = soup.get_text("\n", strip=True)

    name = _extract_name_html(soup)
    price, price_source = _extract_price_html(soup, full_text)
    in_stock, stock_text = _extract_stock_html(soup, full_text)
    description = _extract_description_html(soup)
    image_urls = _collect_gallery_urls_html(soup, max_images)

    slug = "cdon"
    stable_id = _stable_id_from_url(url)
    # Limit folder name to prevent Windows MAX_PATH issues
    safe_product_name = _safe_name(name)[:40]
    safe_id = stable_id[-12:] if len(stable_id) > 12 else stable_id  # Take LAST 12 chars (the GUID part)
    safe_id = re.sub(r"[^\w\-]", "", safe_id)  # Clean it
    folder_name = f"{slug}_{safe_product_name}_{safe_id}"
    folder = DATA_DIR / folder_name
    _ensure_dir(folder)

    saved: List[str] = []
    for idx, img_url in enumerate(image_urls, start=1):
        out = folder / f"{idx:02d}.jpg"
        if _download_and_save_jpg(img_url, out, referer=url, verbose=verbose):
            saved.append(str(out))

    return {
        "url": url,
        "name": name,
        "price": price,
        "price_source": price_source,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_count": len(saved),
        "image_urls": image_urls,
        "images_downloaded": saved,
        "folder": str(folder),
        "context": {"locale": LOCALE, "geo_location": GEO_LOCATION},
        "listing_status": "active",
    }


# -----------------------------
# Test Invalid Link Detection
# -----------------------------
def test_invalid_detection():
    """Test the invalid link detection with sample HTML snippets."""
    
    print("=" * 60)
    print("CDON Invalid Link Detection Tests")
    print("=" * 60)
    
    # Test 1: Category page with Swedish pagination
    html_category = '''
    <!DOCTYPE html>
    <html>
    <body>
    <nav role="navigation" aria-label="Paginering">
        <ul>
            <li><a aria-label="Gå till föregående sida" href="/category/">prev</a></li>
            <li><a aria-current="true" aria-label="Gå till sida 1" href="/category/">1</a></li>
            <li><a aria-label="Gå till sida 2" href="/category/?page=2">2</a></li>
            <li><a aria-label="Gå till sida 3" href="/category/?page=3">3</a></li>
            <li><a aria-label="Gå till sida 4" href="/category/?page=4">4</a></li>
            <li><a aria-label="Gå till sida 5" href="/category/?page=5">5</a></li>
            <li><a aria-label="Gå till nästa sida" href="/category/?page=2">next</a></li>
        </ul>
    </nav>
    <div data-testid="product-card">Product 1</div>
    <div data-testid="product-card">Product 2</div>
    <div data-testid="product-card">Product 3</div>
    <div data-testid="product-card">Product 4</div>
    </body>
    </html>
    '''
    
    is_invalid, reason, details = detect_invalid_link_from_html(
        html_category,
        "https://cdon.se/produkt/elkedel-laura-ashley-dec4c93592da5638/",
        verbose=True
    )
    print(f"\n=== Test 1: Category Page (Swedish pagination) ===")
    print(f"Is Invalid: {is_invalid}")
    print(f"Reason: {reason}")
    print(f"Details: {details}")
    assert is_invalid, "Should detect category page with Swedish pagination"
    
    # Test 2: Valid product page with JSON-LD
    html_product = '''
    <!DOCTYPE html>
    <html>
    <body>
    <script type="application/ld+json">
    {"@type": "Product", "name": "Robot Patissier", "offers": {"price": "1299", "priceCurrency": "SEK"}}
    </script>
    <h1>Robot Patissier 4.5L Laura Ashley</h1>
    <button data-cy="pdp-add-to-cart">Lägg i varukorgen</button>
    <div role="tablist">
        <img src="https://example.com/image1.jpg" />
        <img src="https://example.com/image2.jpg" />
    </div>
    </body>
    </html>
    '''
    
    is_invalid, reason, details = detect_invalid_link_from_html(
        html_product,
        "https://cdon.se/produkt/robotpatissier-45l-laura-ashley-3d292169dd1c588f/",
        verbose=True
    )
    print(f"\n=== Test 2: Valid Product Page ===")
    print(f"Is Invalid: {is_invalid}")
    print(f"Reason: {reason}")
    print(f"Details: {details}")
    assert not is_invalid, "Should recognize valid product page"
    
    # Test 3: Out of stock product (still valid!)
    html_oos = '''
    <!DOCTYPE html>
    <html>
    <body>
    <script type="application/ld+json">
    {"@type": "Product", "name": "Out of Stock Item", "offers": {"price": "599", "priceCurrency": "SEK", "availability": "OutOfStock"}}
    </script>
    <h1>Out of Stock Item</h1>
    <button data-cy="pdp-add-to-cart" disabled>Tillfälligt slut</button>
    <div role="tablist">
        <img src="https://example.com/image1.jpg" />
    </div>
    </body>
    </html>
    '''
    
    is_invalid, reason, details = detect_invalid_link_from_html(
        html_oos,
        "https://cdon.se/produkt/out-of-stock-item-abc123/",
        verbose=True
    )
    print(f"\n=== Test 3: Out of Stock Product (still valid!) ===")
    print(f"Is Invalid: {is_invalid}")
    print(f"Reason: {reason}")
    assert not is_invalid, "Out of stock products should still be valid"
    
    # Test 4: Product page without JSON-LD but with add-to-cart
    html_no_jsonld = '''
    <!DOCTYPE html>
    <html>
    <body>
    <h1>Some Product Without Schema</h1>
    <button data-testid="pdp-add-to-cart">Add to Cart</button>
    <div data-testid="image-panel">
        <img src="https://example.com/image1.jpg" />
    </div>
    </body>
    </html>
    '''
    
    is_invalid, reason, details = detect_invalid_link_from_html(
        html_no_jsonld,
        "https://cdon.se/produkt/some-product-xyz789/",
        verbose=True
    )
    print(f"\n=== Test 4: Product without JSON-LD (has add-to-cart) ===")
    print(f"Is Invalid: {is_invalid}")
    print(f"Reason: {reason}")
    assert not is_invalid, "Should recognize product with add-to-cart button"
    
    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)


# # -----------------------------
# # CLI
# # -----------------------------
# if __name__ == "__main__":
#     import sys
    
#     if "--test" in sys.argv:
#         test_invalid_detection()
#         sys.exit(0)
    
#     TEST_URL = "https://cdon.se/produkt/robotpatissier-45l-laura-ashley-china-rose-stamixare-1300w-10-hastigheter-3d292169dd1c588f/"
    
#     if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
#         TEST_URL = sys.argv[1]
    
#     print(f"[CDON] Starting scrape for: {TEST_URL[:80]}...")
#     print("=" * 60)
    
#     data = scrape_cdon(TEST_URL, max_images=20, verbose=True)
    
#     print("\n" + "=" * 60)
#     print("SCRAPED DATA:")
#     print("=" * 60)
#     print(json.dumps(data, indent=2, ensure_ascii=False))
    
#     print("\n" + "=" * 60)
#     print("SUMMARY:")
#     print(f"  Status: {data.get('listing_status', 'unknown')}")
#     print(f"  Name: {data.get('name', 'N/A')[:50]}...")
#     print(f"  Price: {data.get('price', 'N/A')}")
#     print(f"  In Stock: {data.get('in_stock', 'Unknown')}")
#     print(f"  Images: {data.get('image_count', 0)}")