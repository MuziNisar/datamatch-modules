
# cdiscount_oxylabs.py  (forces images to .jpg, with invalid link detection)
# Python 3.10+
# pip install requests bs4 lxml pillow pillow-avif-plugin

from __future__ import annotations
import json, os, re, time, hashlib, html, concurrent.futures as cf
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

# -----------------------------
# Credentials (your pattern)
# -----------------------------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS  # preferred
except Exception:
    OXY_USER = os.getenv("OXYLABS_USERNAME", "").strip()
    OXY_PASS = os.getenv("OXYLABS_PASSWORD", "").strip()

# -----------------------------
# Config
# -----------------------------
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
ACCEPT_LANG = "fr-FR,fr;q=0.9,en;q=0.8"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / os.getenv("DATA_DIR", "data_fr")
DEBUG_DIR = BASE_DIR / "debug"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# Optional Oxylabs knobs
OXY_GEO = os.getenv("OXY_GEO_LOCATION", "France").strip()      # e.g., "France"
OXY_UA_TYPE = os.getenv("OXY_UA_TYPE", "desktop").strip()      # "desktop" or "mobile"
OXY_TIMEOUT = int(os.getenv("OXY_TIMEOUT", "180"))             # seconds
OXY_REALTIME_URL = os.getenv("OXY_REALTIME_URL", "https://realtime.oxylabs.io/v1/queries").strip()

# Cdiscount image host fingerprint
CD_IMG_HOST = "cdiscount.com"

# --- image convert prefs ---
TARGET_IMAGE_FORMAT = (os.getenv("TARGET_IMAGE_FORMAT", "jpg") or "jpg").lower()  # "jpg","png","webp","keep"
KEEP_ORIGINALS = False
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "92"))

# -----------------------------
# Helpers
# -----------------------------
def _vprint(v: bool, *a):
    if v: print(*a)

def _clean(s: str) -> str: return re.sub(r"\s+", " ", (s or "").strip())

def _normalize_url(u: str) -> str:
    """Normalize URL - add https: if protocol-relative (//...)"""
    if u and u.startswith("//"):
        return "https:" + u
    return u

def _clean_multiline(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _safe_name(s: str) -> str:
    """Create a safe filename by transliterating Unicode to ASCII and removing special chars."""
    s = _clean(s)
    
    # Transliterate common Unicode characters to ASCII equivalents
    # This prevents Windows path encoding issues with OpenCV
    transliterations = {
        # German
        'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
        'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
        # French/Spanish/Portuguese
        'à': 'a', 'á': 'a', 'â': 'a', 'ã': 'a', 'å': 'a',
        'è': 'e', 'é': 'e', 'ê': 'e', 'ë': 'e',
        'ì': 'i', 'í': 'i', 'î': 'i', 'ï': 'i',
        'ò': 'o', 'ó': 'o', 'ô': 'o', 'õ': 'o',
        'ù': 'u', 'ú': 'u', 'û': 'u',
        'ç': 'c', 'ñ': 'n',
        'æ': 'ae', 'œ': 'oe',
        # Swedish specific
        'Å': 'A', 'å': 'a',
        # Polish
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
        'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        'Ą': 'A', 'Ć': 'C', 'Ę': 'E', 'Ł': 'L', 'Ń': 'N',
        'Ó': 'O', 'Ś': 'S', 'Ź': 'Z', 'Ż': 'Z',
        # Common problematic characters
        '–': '-', '—': '-', ''': '', ''': '', '"': '', '"': '',
        '«': '', '»': '', '…': '', '•': '', '™': '', '®': '', '©': '',
        '/': '_', '\\': '_', ':': '_', '*': '_', '?': '_', '"': '_',
        '<': '_', '>': '_', '|': '_',
    }
    
    for unicode_char, ascii_equiv in transliterations.items():
        s = s.replace(unicode_char, ascii_equiv)
    
    # Remove any remaining non-ASCII/special characters
    s = s.encode('ascii', 'ignore').decode('ascii')
    
    # Replace remaining special chars with underscore
    s = re.sub(r"[^\w.\-]+", "_", s)
    
    # Remove multiple consecutive underscores
    s = re.sub(r"_+", "_", s)
    
    # Remove leading/trailing underscores
    s = s.strip("_")
    
    return s[:120] or "product"

def _stable_id_from_url(url: str) -> str:
    try:
        parts = [p for p in urlsplit(url).path.split("/") if p]
        token = parts[-1] if parts else ""
        if token: return re.sub(r"[^\w\-]+", "", token)
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

def _strip_query(u: str) -> str:
    sp = urlsplit(u); return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

def _get_image_base_key(u: str) -> str:
    """
    Extract a normalized key for deduplication that ignores size variants.
    
    Cdiscount URLs like:
    - https://www.cdiscount.com/pdt2/0/4/4/1/700x700/aaaqg33044/rw/bouilloire.jpg
    - https://www.cdiscount.com/pdt2/0/4/4/1/115x115/aaaqg33044/rw/bouilloire.jpg
    
    Should be treated as the SAME image (just different sizes).
    We extract: /pdt2/0/4/4/1/ + aaaqg33044 as the unique key.
    """
    sp = urlsplit(u)
    path = sp.path.lower()
    
    # Remove size variants (e.g., 700x700, 115x115, 400x400, 550x550)
    # Pattern: /pdt2/X/X/X/X/SIZExSIZE/SKU/...
    size_pattern = re.sub(r'/\d+x\d+/', '/', path)
    
    # Also strip query string
    return f"{sp.netloc}{size_pattern}"

def _dedupe_preserve_order(urls: List[str]) -> List[str]:
    """Deduplicate URLs, treating different size variants as the same image."""
    seen, out = set(), []
    for u in urls:
        if not u:
            continue
        key = _get_image_base_key(u)
        if key not in seen:
            seen.add(key)
            out.append(u)
    return out

def _is_product_image(u: str) -> bool:
    if not u or CD_IMG_HOST not in u: return False
    p = urlsplit(u).path.lower()
    if "/imagescnet/logos/" in p: return False  # logos
    return "/pdt2/" in p  # product thumbs/zoom live here (Cdiscount)

# Price parsing: € or EUR
_PRICE_RX = re.compile(r"(\d[\d\s.,]*)\s*(€|eur)\b", re.I)
def _parse_price_text_block(text: str) -> Optional[str]:
    m = _PRICE_RX.search(text)
    if not m: return None
    num, curr = m.group(1), m.group(2)
    num = num.replace("\u202f","").replace(" ", "")
    if "," in num and "." not in num:
        num = num.replace(",", ".")
    curr = "EUR"
    return f"{num} {curr}"

# -----------------------------
# File type detection
# -----------------------------
def _sniff_ext_from_bytes(b: bytes) -> Optional[str]:
    if len(b) >= 3 and b[:3] == b"\xFF\xD8\xFF": return ".jpg"
    if len(b) >= 8 and b[:8] == b"\x89PNG\r\n\x1a\n": return ".png"
    if len(b) >= 6 and (b[:6] in (b"GIF87a", b"GIF89a")): return ".gif"
    if len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP": return ".webp"
    if len(b) >= 12 and b[4:8] == b"ftyp" and b[8:12] in (b"avif",b"avis",b"isom",b"mif1"): return ".avif"
    if b.startswith(b"<?xml") or b.strip().startswith(b"<svg"): return ".svg"
    return None

def _ext_from_ct_or_url_or_bytes(ct: Optional[str], url: str, body: bytes) -> str:
    ct = (ct or "").lower()
    if "jpeg" in ct or "jpg" in ct:   return ".jpg"
    if "png" in ct:                   return ".png"
    if "webp" in ct:                  return ".webp"
    if "gif" in ct:                   return ".gif"
    if "svg" in ct:                   return ".svg"
    if "avif" in ct:                  return ".avif"
    path = urlsplit(url).path.lower()
    for ext in (".jpg",".jpeg",".png",".webp",".gif",".svg",".avif"):
        if path.endswith(ext): return ".jpg" if ext == ".jpeg" else ext
    sniff = _sniff_ext_from_bytes(body)
    return sniff or ".jpg"

# -----------------------------
# Download + optional convert
# -----------------------------
def _download_one(session: requests.Session, url: str, out: Path, verbose: bool, referer: str | None) -> Optional[str]:
    url = _normalize_url(url)

    session.headers.update({"Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
    if referer: session.headers["Referer"] = referer
    try:
        r = session.get(url, timeout=25)
        if r.status_code >= 400 or not r.content:
            _vprint(verbose, f"  ! HTTP {r.status_code} {url}")
            return None
        ext = _ext_from_ct_or_url_or_bytes(r.headers.get("content-type",""), url, r.content)
        out_final = out.with_suffix(ext)
        out_final.write_bytes(r.content)
        _vprint(verbose, f"  ✓ {out_final.name}  ← {url}")
        return _maybe_convert(out_final)
    except Exception as e:
        _vprint(verbose, f"  ! {url} error: {e}")
        return None

def _maybe_convert(path: Path) -> str:
    tfmt = TARGET_IMAGE_FORMAT
    if not tfmt or tfmt == "keep": return str(path)
    if path.suffix.lower() == f".{tfmt}": return str(path)
    try:
        from PIL import Image
        try:
            import pillow_avif  # noqa: F401
        except Exception:
            pass

        img = Image.open(path)

        def _to_rgb(im):
            if im.mode in ("RGB","L"): return im.convert("RGB")
            if im.mode in ("RGBA","LA","P"):
                from PIL import Image as PILImage
                bg = PILImage.new("RGB", im.size, (255,255,255))
                try:
                    alpha = im.split()[-1] if im.mode in ("RGBA","LA") else im.getchannel("A")
                except Exception:
                    alpha = None
                bg.paste(im.convert("RGBA"), mask=alpha)
                return bg
            return im.convert("RGB")

        if tfmt in ("jpg","jpeg"):
            img = _to_rgb(img)
            outp = path.with_suffix(".jpg")
            img.save(outp, quality=JPEG_QUALITY, optimize=True, progressive=True, subsampling="4:2:0")
        elif tfmt == "png":
            outp = path.with_suffix(".png")
            img.save(outp, optimize=True)
        elif tfmt == "webp":
            outp = path.with_suffix(".webp")
            img.save(outp, method=6, quality=90)
        else:
            return str(path)

        if not KEEP_ORIGINALS:
            try: path.unlink()
            except Exception: pass
        return str(outp)
    except Exception as e:
        _vprint(True, f"  ! convert {path.name} → {tfmt}: {e}")
        return str(path)

def _download_images_concurrent(img_urls: List[str], folder: Path, max_workers: int, verbose: bool, referer: str | None = None) -> List[str]:
    saved: List[str] = []
    folder.mkdir(parents=True, exist_ok=True)
    with requests.Session() as s:
        s.headers.update({"User-Agent": UA, "Accept-Language": ACCEPT_LANG})
        with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = []
            for idx, u in enumerate(img_urls, 1):
                out = folder / f"{idx:02d}"  # ext decided later / after conversion
                futures.append(ex.submit(_download_one, s, u, out, verbose, referer))
            for f in cf.as_completed(futures):
                p = f.result()
                if p: saved.append(p)
    return saved

# -----------------------------
# Invalid Link Detection
# -----------------------------
def _check_invalid_product_page(soup: BeautifulSoup, url: str, verbose: bool = False) -> bool:
    """
    Check if the page is NOT a valid product page.
    
    Cdiscount has several non-product page types:
    1. Category/showcase pages (contentType/pageType: "SHOWCASE")
    2. Category listing pages (contentType/pageType: "PRODUCTLISTER")
    3. Category listing pages (/l-XXXXX pattern in URL)
    4. Category pages (/v-XXXXX pattern in URL)
    5. Pages with pagination (multiple page links)
    
    IMPORTANT: When a product is discontinued, Cdiscount redirects the /f- URL
    to a category listing page. The HTML will contain "pageType":"PRODUCTLISTER"
    even though the original URL had /f-. We MUST check page content first!
    
    Returns True if this is an INVALID product page (should return "Invalid Link").
    """
    
    page_text = str(soup)
    
    # ============ PRODUCTLISTER/SHOWCASE CHECK (HIGHEST PRIORITY) ============
    # This MUST come first because redirected products land on category pages
    # The page content reveals the truth even if URL still has /f-
    
    # IMPORTANT: We must check the CURRENT PAGE's content type, not just any mention
    # Valid product pages also mention SHOWCASE in footer/navigation data
    # Look for "currentSceneContext" which contains the actual page type
    
    # Normalize the text by removing escape characters to make matching easier
    # This converts \\\" -> " so we can search for clean patterns
    normalized_text = page_text.replace('\\\\', '').replace('\\"', '"').replace("\\'", "'")
    
    # Now check for currentSceneContext with SHOWCASE or PRODUCTLISTER
    if '"currentSceneContext":{' in normalized_text:
        # Extract content after currentSceneContext to check its type
        idx = normalized_text.find('"currentSceneContext":{')
        if idx >= 0:
            # Look at the next 200 chars to find contentType
            window = normalized_text[idx:idx+300]
            if '"contentType":"SHOWCASE"' in window:
                _vprint(verbose, "[Cdiscount] ✗ currentSceneContext is SHOWCASE - category page (redirected)")
                return True
            if '"contentType":"PRODUCTLISTER"' in window:
                _vprint(verbose, "[Cdiscount] ✗ currentSceneContext is PRODUCTLISTER - category listing (redirected)")
                return True
    
    # Also check for pageType at the top level (appears in some redirects)
    if '"pageType":"PRODUCTLISTER"' in normalized_text:
        _vprint(verbose, "[Cdiscount] ✗ pageType is PRODUCTLISTER - category listing")
        return True
    
    # ============ URL PATTERN CHECKS ============
    
    path = urlsplit(url).path.lower()
    
    # /f-XXXXX.html pattern indicates a PRODUCT page URL (but content check above takes priority)
    is_product_url = "/f-" in path and path.endswith(".html")
    
    if is_product_url:
        _vprint(verbose, "[Cdiscount] ✓ URL has /f- pattern - checking page content...")
    
    # Category listing URL pattern /l-XXXXX.html (ONLY if not also /f-)
    if re.search(r'/l-\d+(-\d+)?\.html', path) and not is_product_url:
        _vprint(verbose, "[Cdiscount] ✗ URL pattern /l-XXXXX.html indicates category listing page")
        return True
    
    # Category URL pattern /v-XXXXX.html (without /f-)
    if "/v-" in path and not is_product_url and path.endswith(".html"):
        _vprint(verbose, "[Cdiscount] ✗ URL pattern /v-XXXXX.html indicates category page")
        return True
    
    # ============ VALID PRODUCT PAGE INDICATORS ============
    
    valid_indicators = 0
    
    # Indicator 1: JSON-LD Product schema with offers
    has_product_schema = False
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            raw = script.string or script.get_text()
            if not raw:
                continue
            data = json.loads(raw)
            objs = data if isinstance(data, list) else [data]
            for obj in objs:
                if isinstance(obj, dict) and obj.get("@type") == "Product":
                    if obj.get("offers"):
                        has_product_schema = True
                        valid_indicators += 1
                        _vprint(verbose, "[Cdiscount] ✓ Found JSON-LD Product schema with offers")
                    break
        except Exception:
            continue
        if has_product_schema:
            break
    
    # Indicator 2: Product title with itemprop="name"
    product_title = soup.select_one("h1[itemprop='name']")
    if product_title and product_title.get_text(strip=True):
        valid_indicators += 1
        _vprint(verbose, "[Cdiscount] ✓ Found product title with itemprop='name'")
    
    # Indicator 3: Buybox/add-to-cart elements
    buybox = soup.select_one(
        "div.c-buybox__price, "
        "[class*='buybox'], "
        "[data-qa='buybox'], "
        "#fpAddBsk, "
        "[data-qa='add-to-cart']"
    )
    if buybox:
        valid_indicators += 1
        _vprint(verbose, "[Cdiscount] ✓ Found buybox/add-to-cart element")
    
    # Indicator 4: Product viewer/gallery
    product_viewer = soup.select_one(
        ".c-productViewer, "
        "[class*='productViewer'], "
        "[data-qa='product-gallery'], "
        ".fpImgZmCt, "
        "#fpImgZmCt, "
        "li.scroller-item button[aria-label*='slide']"
    )
    if product_viewer:
        valid_indicators += 1
        _vprint(verbose, "[Cdiscount] ✓ Found product viewer/gallery element")
    
    # Indicator 5: Product description
    product_description = soup.select_one(
        "#MarketingLongDescription, "
        "[itemprop='description'], "
        ".fpDescTb, "
        "#fpDescTb"
    )
    if product_description and len(product_description.get_text(strip=True)) > 50:
        valid_indicators += 1
        _vprint(verbose, "[Cdiscount] ✓ Found product description")
    
    # Indicator 6: Any h1 title on a /f- URL (relaxed check)
    if is_product_url:
        h1 = soup.select_one("h1")
        if h1 and len(h1.get_text(strip=True)) > 5:
            valid_indicators += 1
            _vprint(verbose, "[Cdiscount] ✓ Found h1 title on /f- URL")
    
    _vprint(verbose, f"[Cdiscount] Total valid indicators: {valid_indicators}")
    
    # ============ DECISION LOGIC ============
    
    # If URL has /f- pattern AND we have at least 1 valid indicator, it's valid
    if is_product_url and valid_indicators >= 1:
        _vprint(verbose, f"[Cdiscount] ✓ Product URL with {valid_indicators} indicator(s) - valid product page")
        return False  # Valid product page
    
    # If we have 2+ valid indicators, it's valid regardless of URL
    if valid_indicators >= 2:
        _vprint(verbose, f"[Cdiscount] ✓ Found {valid_indicators} valid indicators - valid product page")
        return False  # Valid product page
    
    # ============ PAGINATION CHECK (only if not already validated) ============
    # Pagination indicates category listing ONLY if we haven't found valid indicators
    
    pagination = soup.select_one('nav[aria-label="Pagination"], nav.pagination-wrapper')
    if pagination:
        page_links = pagination.select('a[aria-label*="page"], a.button-item')
        if len(page_links) >= 3:
            _vprint(verbose, f"[Cdiscount] ✗ Found pagination with {len(page_links)} page links - category listing page")
            return True
    
    page_nav_links = soup.select('a[aria-label*="Aller à la page"], a[aria-label*="Go to page"]')
    if len(page_nav_links) >= 3:
        _vprint(verbose, f"[Cdiscount] ✗ Found {len(page_nav_links)} page navigation links - category listing page")
        return True
    
    # ============ ADDITIONAL CATEGORY PAGE INDICATORS ============
    
    product_cards = soup.select(
        "[data-testid='product-card'], "
        "article[class*='product'], "
        ".c-product, "
        "[class*='ProductCard'], "
        "div[data-productid]"
    )
    if len(product_cards) >= 4:
        _vprint(verbose, f"[Cdiscount] ✗ Found {len(product_cards)} product cards - category listing page")
        return True
    
    # Check for explicit "not found" messages
    body_text = soup.get_text(" ", strip=True).lower()
    not_found_phrases = [
        "produit introuvable",
        "cette offre n'est plus disponible",
        "ce produit n'existe plus",
        "page introuvable",
        "product not found",
        "page not found",
        "erreur 404",
    ]
    for phrase in not_found_phrases:
        if phrase in body_text:
            _vprint(verbose, f"[Cdiscount] ✗ Found 'not found' phrase: {phrase}")
            return True
    
    # If URL has /f- but we found no valid indicators, something is wrong
    if is_product_url and valid_indicators == 0:
        _vprint(verbose, "[Cdiscount] ? Product URL but 0 indicators - assuming valid (may be loading issue)")
        return False  # Assume valid for /f- URLs
    
    # Default: if few indicators and no /f- URL, it's probably not a product page
    if valid_indicators < 1:
        _vprint(verbose, f"[Cdiscount] ✗ Only {valid_indicators} valid indicators - likely not a product page")
        return True
    
    _vprint(verbose, "[Cdiscount] ? Uncertain - assuming valid product page")
    return False

# -----------------------------
# Oxylabs Web Scraper API
# -----------------------------
class OxylabsError(RuntimeError):
    pass

def _oxylabs_fetch_html(url: str, *, render: bool = True, verbose: bool = True) -> str:
    """
    Use Oxylabs Web Scraper API with retry logic for rate limiting (429).
    """
    if not (OXY_USER and OXY_PASS):
        raise OxylabsError("Missing OXY_USER / OXY_PASS (env or oxylabs_secrets).")

    payload = {
        "source": "universal",  # Using universal source for reliability
        "url": url,
        "user_agent_type": OXY_UA_TYPE or "desktop",
        "geo_location": OXY_GEO or "France",
        "render": "html" if render else None,
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    max_retries = 5
    base_delay = 10  # seconds
    
    for attempt in range(max_retries):
        try:
            _vprint(verbose, f"  [Oxylabs] Attempt {attempt + 1}/{max_retries}...")
            
            resp = requests.post(
                OXY_REALTIME_URL,
                auth=(OXY_USER, OXY_PASS),
                json=payload,
                timeout=OXY_TIMEOUT
            )
            
            # Handle rate limiting (429)
            if resp.status_code == 429:
                delay = base_delay * (2 ** attempt)  # 10, 20, 40, 80, 160 seconds
                _vprint(verbose, f"  [Oxylabs] ⚠️ Rate limited (429). Waiting {delay}s...")
                time.sleep(delay)
                continue
            
            if resp.status_code == 401:
                raise OxylabsError("401 Unauthorized: check Oxylabs credentials/plan.")
            
            resp.raise_for_status()
            data = resp.json()
            
            results = data.get("results") or []
            first = results[0] if results else {}
            status = int(first.get("status_code") or 0)
            
            # Handle rate limiting in result status
            if status == 429:
                delay = base_delay * (2 ** attempt)
                _vprint(verbose, f"  [Oxylabs] ⚠️ Rate limited (result 429). Waiting {delay}s...")
                time.sleep(delay)
                continue
            
            if status >= 400:
                raise OxylabsError(f"Target returned HTTP {status}")
            
            content = first.get("content") or ""
            if not content:
                raise OxylabsError("No HTML content in Oxylabs response.")
            
            _vprint(verbose, f"  [Oxylabs] ✓ Got {len(content):,} bytes")
            return content
            
        except requests.RequestException as e:
            error_str = str(e)
            if "429" in error_str or "Too Many Requests" in error_str:
                delay = base_delay * (2 ** attempt)
                _vprint(verbose, f"  [Oxylabs] ⚠️ Rate limited. Waiting {delay}s...")
                time.sleep(delay)
                continue
            raise OxylabsError(f"Oxylabs request failed: {e}") from e
    
    raise OxylabsError(f"Failed after {max_retries} attempts due to rate limiting")

# -----------------------------
# Extraction (HTML -> fields)
# -----------------------------
def _extract_name_from_soup(soup: BeautifulSoup) -> str:
    h1 = soup.select_one("h1[itemprop='name'], h1")
    if h1 and h1.get_text(strip=True): return _clean(h1.get_text(" ", strip=True))
    title = soup.title.string if soup.title else ""
    return _clean((title or "").split("|")[0]) or "Unknown_Product"

def _extract_price_from_soup(soup: BeautifulSoup) -> Tuple[str, str]:
    tag = soup.select_one("[itemprop='price'][content]")
    if tag:
        val = (tag.get("content") or "").replace(" ", "").replace("\u202f","").replace(",", ".")
        if val: return f"{val} EUR", "onsite"

    wrap = soup.select_one("div.c-buybox__price")
    if wrap:
        got = _parse_price_text_block(_clean(wrap.get_text(" ", strip=True)))
        if got: return got, "onsite"

    for tag in soup.select("script[type='application/ld+json']"):
        raw = tag.string or tag.get_text()
        if not raw: continue
        try:
            data = json.loads(raw)
        except Exception:
            try: data = json.loads(raw.strip().rstrip(","))
            except Exception: continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if isinstance(obj, dict) and obj.get("@type") in ("Product",):
                offers = obj.get("offers") or {}
                if isinstance(offers, list): offers = offers[0] if offers else {}
                p = offers.get("price"); curr = (offers.get("priceCurrency") or "").upper() or "EUR"
                if p is not None:
                    pv = str(p).replace(",", ".")
                    return _clean(f"{pv} {curr}"), "jsonld"

    return "N/A", "none"

def _extract_stock_from_text(text: str) -> Tuple[Optional[bool], Optional[str]]:
    if re.search(r"\b(en stock|disponible|in stock)\b", text, re.I): return True, "In stock"
    if re.search(r"\b(rupture|indisponible|épuisé|out of stock)\b", text, re.I): return False, "Out of stock"
    return None, None

def _extract_description_and_images_from_soup(soup: BeautifulSoup, max_images: Optional[int]) -> Tuple[str, List[str]]:
    desc = ""
    region = soup.select_one("#MarketingLongDescription") or soup.select_one("[itemprop='description']")
    if region:
        desc = _clean_multiline(html.unescape(region.get_text("\n", strip=True)))
    else:
        hdr = soup.find(string=re.compile(r"\b(Caractéristiques|Description|Points forts|Highlights)\b", re.I))
        if hdr and hasattr(hdr, "parent"):
            desc = _clean_multiline(html.unescape(hdr.parent.get_text("\n", strip=True)))

    urls: List[str] = []
    
    # Strategy 1: New Cdiscount structure - scroller with thumbnail buttons
    # Look for the product gallery scroller with "Go to slide" buttons
    for item in soup.select('li.scroller-item button[aria-label*="slide"] img, li.scroller-item button[aria-label*="Slide"] img'):
        u = item.get("src") or item.get("data-src")
        if u and _is_product_image(u):
            # Upgrade thumbnail (115x115) to high-res (700x700)
            u = _upgrade_image_size(u)
            urls.append(u)
    
    # Strategy 2: Old structure - c-productViewer thumbs
    if not urls:
        for img in soup.select(".c-productViewer__thumbs img.js-thumbnail, img.js-thumbnail"):
            u = img.get("data-zoom-url") or img.get("data-image-url") or img.get("src")
            if u and _is_product_image(u):
                u = _upgrade_image_size(u)
                urls.append(u)
    
    # Strategy 3: Fallback - any product image on the page
    if not urls:
        for img in soup.select("img"):
            u = img.get("data-zoom-url") or img.get("data-image-url") or img.get("src")
            if u and _is_product_image(u):
                u = _upgrade_image_size(u)
                urls.append(u)

    # Deduplicate (treating size variants as same image)
    urls = _dedupe_preserve_order(urls)
    
    # Filter out images from other products (different SKU in URL)
    # Extract the main product SKU from the first image URL
    if urls:
        main_sku = _extract_sku_from_url(urls[0])
        if main_sku:
            urls = [u for u in urls if main_sku in u]
    
    if max_images is not None:
        urls = urls[:max_images]
    
    return desc, urls

def _upgrade_image_size(url: str) -> str:
    """
    Upgrade thumbnail URL to high-resolution version.
    
    Cdiscount image sizes:
    - 115x115 = thumbnail
    - 400x400 = medium
    - 550x550 = large
    - 700x700 = high-res (preferred)
    """
    # Replace any size with 700x700
    return re.sub(r'/\d+x\d+/', '/700x700/', url)

def _extract_sku_from_url(url: str) -> Optional[str]:
    """
    Extract product SKU from Cdiscount image URL.
    
    URL pattern: /pdt2/X/X/X/X/SIZExSIZE/SKU/rw/name.jpg
    Example: /pdt2/0/4/4/1/700x700/aaaqg33044/rw/bouilloire.jpg
    SKU = aaaqg33044
    """
    path = urlsplit(url).path
    # Pattern: after size like /700x700/ comes the SKU
    match = re.search(r'/\d+x\d+/([a-zA-Z0-9]+)/', path)
    if match:
        return match.group(1).lower()
    return None

# -----------------------------
# Public API
# -----------------------------
def scrape_cdiscount(
    url: str,
    *,
    download_images: bool = True,
    max_images: Optional[int] = 12,
    max_image_workers: int = 6,
    verbose: bool = True,
) -> Dict:
    """
    Scrape a Cdiscount product URL using Oxylabs Web Scraper API (rendered HTML),
    parse product fields, and optionally download/convert images.
    
    Returns a dict with product info. If the product is no longer available
    (page redirects to category/showcase), returns "Invalid Link" status.
    """
    result = {
        "url": url,
        "name": "",
        "price": "N/A",
        "price_source": "none",
        "in_stock": None,
        "stock_text": None,
        "description": "",
        "image_count": 0,
        "image_urls": [],
        "images_downloaded": [],
        "folder": "",
        "mode": "oxylabs_web_scraper_api",
        "listing_status": "active",
    }

    # 1) Fetch fully-rendered HTML via Oxylabs (no local browser)
    html_text = _oxylabs_fetch_html(url, render=True, verbose=verbose)

    # 2) Parse
    soup = BeautifulSoup(html_text, "lxml")
    
    # ========== CHECK FOR INVALID/REDIRECTED PRODUCT PAGE ==========
    if _check_invalid_product_page(soup, url, verbose=verbose):
        print(f"[Cdiscount] ⚠️ INVALID LINK: Product no longer available - {url[:80]}...")
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
            "mode": "oxylabs_web_scraper_api",
            "listing_status": "invalid",
        }
    # ===============================================================

    name = _extract_name_from_soup(soup)
    price, price_source = _extract_price_from_soup(soup)
    in_stock, stock_text = _extract_stock_from_text(soup.get_text(" ", strip=True))
    description, image_urls = _extract_description_and_images_from_soup(soup, max_images)

    stable_id = _stable_id_from_url(url)
    folder = DATA_DIR / f"cdiscount_{_safe_name(name or 'product')}_{_safe_name(stable_id)}"
    folder.mkdir(parents=True, exist_ok=True)

    result.update({
        "name": name,
        "price": price,
        "price_source": price_source,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_urls": image_urls,
        "folder": str(folder),
    })

    # 3) Download images (with optional conversion)
    if download_images and image_urls:
        _vprint(verbose, f"Downloading {len(image_urls)} images …")
        saved = _download_images_concurrent(image_urls, folder, max_image_workers, verbose, referer=url)
        result["images_downloaded"] = saved
        result["image_count"] = len(saved)
    else:
        result["image_count"] = len(image_urls)

    # 4) Save raw HTML for debugging
    try:
        (folder / "page.html").write_text(html_text, encoding="utf-8", errors="ignore")
    except Exception:
        pass

    return result

# # -----------------------------
# # Simple runner
# # -----------------------------
# if __name__ == "__main__":
#     import sys
    
#     # Test with a valid product URL
#     TEST_URL = "https://www.cdiscount.com/electromenager/petit-dejeuner-cafe/grille-pain-2-tranches--/f-1101708-aaaqq08808.html#mpos=0|mp"
    
#     # Or use command line argument
#     if len(sys.argv) > 1:
#         TEST_URL = sys.argv[1]
    
#     print(f"[Cdiscount] Starting scrape for: {TEST_URL[:80]}...")
#     print("=" * 60)
    
#     data = scrape_cdiscount(
#         TEST_URL,
#         download_images=True,
#         max_images=12,
#         max_image_workers=6,
#         verbose=True,
#     )
    
#     print("\n" + "=" * 60)
#     print("SCRAPED DATA:")
#     print("=" * 60)
#     print(json.dumps(data, indent=2, ensure_ascii=False))
    
#     # Quick summary
#     print("\n" + "=" * 60)
#     print("SUMMARY:")
#     print(f"  Status: {data.get('listing_status', 'unknown')}")
#     print(f"  Name: {data.get('name', 'N/A')[:50]}...")
#     print(f"  Price: {data.get('price', 'N/A')}")
#     print(f"  In Stock: {data.get('in_stock', 'Unknown')}")
#     print(f"  Images: {data.get('image_count', 0)}")