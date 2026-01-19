

# # ao_com_oxylabs.py — Oxylabs universal + JPG-only images
# # Python 3.9+
# # pip install requests beautifulsoup4 lxml pillow pillow-avif-plugin

# from __future__ import annotations
# import re, json, hashlib, time, random
# from pathlib import Path
# from typing import Optional, List, Dict
# from urllib.parse import urlparse, urldefrag, urlsplit, urlunsplit
# from io import BytesIO
# from datetime import datetime, timezone

# import requests
# from requests.exceptions import RequestException
# from bs4 import BeautifulSoup
# from PIL import Image

# # Optional AVIF/HEIF support
# try:
#     import pillow_avif  # noqa: F401
# except Exception:
#     pass

# # =========================
# # Config
# # =========================
# # Credentials from oxylabs_secrets.py (required)
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS
# except Exception as e:
#     raise RuntimeError("Missing oxylabs_secrets.py with OXY_USER and OXY_PASS") from e
# if not (OXY_USER and OXY_PASS):
#     raise RuntimeError("OXY_USER/OXY_PASS in oxylabs_secrets.py must be non-empty.")

# UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
# ACCEPT_LANG = "en-GB,en;q=0.9"

# BASE_DIR = Path(__file__).resolve().parent
# DATA_DIR = BASE_DIR / "data_uk"
# DATA_DIR.mkdir(parents=True, exist_ok=True)

# OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"

# # =========================
# # Helpers
# # =========================
# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "").strip())

# def _clean_multiline(s: str) -> str:
#     s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
#     s = re.sub(r"[ \t]+\n", "\n", s)
#     s = re.sub(r"\n{3,}", "\n\n", s)
#     return s.strip()

# def _safe_name(s: str) -> str:
#     s = _clean(s)
#     return re.sub(r"[^\w.\-]+", "_", s)[:120] or "product"

# def _stable_id_from_url(url: str) -> str:
#     try:
#         url, _ = urldefrag(url)
#         path = urlparse(url).path.strip("/").split("/")
#         last = (path[-1] if path else "") or url
#         return re.sub(r"[^\w\-]+", "", last) or hashlib.sha1(url.encode()).hexdigest()[:12]
#     except Exception:
#         return hashlib.sha1(url.encode()).hexdigest()[:12]

# def _dedupe_preserve(urls: List[str]) -> List[str]:
#     seen, out = set(), []
#     for u in urls:
#         k = u.split("?")[0]
#         if k and k not in seen:
#             seen.add(k); out.append(u)
#     return out

# def _strip_query(u: str) -> str:
#     sp = urlsplit(u)
#     return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

# # GBP parser -> returns "xx.xx GBP"
# def _parse_gbp_text(text: str) -> Optional[str]:
#     if not text: return None
#     m = re.search(r"£\s*([\d,]+(?:\.\d{1,2})?)", text)
#     if not m:
#         m = re.search(r"\b([\d,]+(?:\.\d{1,2})?)\b", text)  # fallback
#     if not m:
#         return None
#     val = m.group(1).replace(",", "")
#     if "." not in val:
#         val = f"{val}.00"
#     return f"{val} GBP"

# # =========================
# # Oxylabs client (no browser_instructions)
# # =========================
# def _build_context_array(session_id: Optional[str]) -> list[dict]:
#     ctx: list[dict] = []
#     if session_id:
#         ctx.append({"key": "session_id", "value": session_id})
#     ctx.append({
#         "key": "headers",
#         "value": {
#             "User-Agent": UA,
#             "Accept-Language": ACCEPT_LANG
#         }
#     })
#     return ctx

# def _parse_retry_after(headers: Dict[str, str]) -> Optional[float]:
#     ra = headers.get("Retry-After")
#     if ra:
#         try:
#             return float(ra)
#         except ValueError:
#             try:
#                 dt = datetime.strptime(ra, "%a, %d %b %Y %H:%M:%S %Z")
#                 return max(0.0, (dt.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds())
#             except Exception:
#                 pass
#     xr = headers.get("X-RateLimit-Reset") or headers.get("X-Ratelimit-Reset")
#     if xr:
#         try:
#             return max(0.0, float(xr) - time.time())
#         except Exception:
#             pass
#     return None

# def oxy_post(payload: dict, retries: int = 6, base_sleep: float = 2.0) -> dict:
#     last_err = None
#     for attempt in range(retries + 1):
#         try:
#             r = requests.post(OXY_ENDPOINT, auth=(OXY_USER, OXY_PASS), json=payload, timeout=120)
#             if r.status_code == 200:
#                 data = r.json()
#                 results = data.get("results") or []
#                 if not results:
#                     raise RuntimeError("Oxylabs: empty results")
#                 content = results[0].get("content", "")
#                 if "<html" not in content.lower():
#                     raise RuntimeError("Oxylabs: non-HTML content")
#                 return data

#             if r.status_code in (429, 500, 502, 503, 504):
#                 wait = _parse_retry_after(r.headers)
#                 if wait is None:
#                     wait = (base_sleep * (2 ** attempt)) + random.uniform(0.25, 0.75)
#                 time.sleep(min(wait, 30.0))
#                 continue

#             try:
#                 err_json = r.json()
#                 raise RuntimeError(f"Oxylabs HTTP {r.status_code}: {err_json}")
#             except ValueError:
#                 raise RuntimeError(f"Oxylabs HTTP {r.status_code}: {r.text[:500]}")

#         except (RequestException, ValueError, RuntimeError) as e:
#             last_err = e
#             if attempt < retries:
#                 wait = (base_sleep * (2 ** attempt)) + random.uniform(0.25, 0.75)
#                 time.sleep(min(wait, 10.0))
#                 continue
#             raise RuntimeError(f"Oxylabs failed after {retries+1} attempts: {e}") from e
#     raise last_err or RuntimeError("Oxylabs unknown error")

# def oxy_fetch_html(url: str, geo: str = "United Kingdom") -> str:
#     url, _ = urldefrag(url)
#     session_id = f"ao-{int(time.time())}-{random.randint(1000,9999)}"
#     payload = {
#         "source": "universal",
#         "url": url,
#         "render": "html",
#         "geo_location": geo,
#         "user_agent_type": "desktop",
#         "context": _build_context_array(session_id),
#     }
#     data = oxy_post(payload)
#     return data["results"][0]["content"]

# # =========================
# # Image download (ALWAYS .jpg)
# # =========================
# def _img_to_jpg_bytes(raw: bytes) -> bytes:
#     """
#     Convert any supported raster image to JPEG bytes.
#     Flattens transparency onto white.
#     """
#     with Image.open(BytesIO(raw)) as im:
#         if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
#             bg = Image.new("RGB", im.size, (255, 255, 255))
#             im_rgba = im.convert("RGBA")
#             bg.paste(im_rgba, mask=im_rgba.split()[-1])
#             out = BytesIO()
#             bg.save(out, format="JPEG", quality=92, optimize=True, progressive=True)
#             return out.getvalue()
#         if im.mode != "RGB":
#             im = im.convert("RGB")
#         out = BytesIO()
#         im.save(out, format="JPEG", quality=92, optimize=True, progressive=True)
#         return out.getvalue()

# def download_images_jpg(urls: List[str], folder: Path, referer: str, max_images: Optional[int]=None) -> List[str]:
#     if max_images is not None:
#         urls = urls[:max_images]
#     saved = []
#     folder.mkdir(parents=True, exist_ok=True)
#     headers = {
#         "User-Agent": UA,
#         "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#         "Accept-Language": ACCEPT_LANG,
#         "Referer": referer,
#     }
#     for i, u in enumerate(urls, 1):
#         try:
#             u = _strip_query(u)
#             with requests.get(u, headers=headers, timeout=40) as r:
#                 ct = (r.headers.get("Content-Type", "") or "").lower()
#                 if r.status_code == 200 and (ct.startswith("image/") or r.content):
#                     out = folder / f"{i:02d}.jpg"
#                     try:
#                         out.write_bytes(_img_to_jpg_bytes(r.content))
#                         saved.append(str(out))
#                     except Exception as pe:
#                         if ct.startswith(("image/jpeg", "image/jpg")):
#                             out.write_bytes(r.content)
#                             saved.append(str(out))
#                         else:
#                             print("  ! convert error:", u, pe)
#                 else:
#                     print("  ! image HTTP", r.status_code, u, ct)
#         except Exception as e:
#             print("  ! image error:", u, e)
#     return saved

# # =========================
# # AO.com parser
# # =========================
# def parse_ao(html: str) -> Dict:
#     soup = BeautifulSoup(html, "lxml")

#     # ---- name ----
#     name = ""
#     el = soup.select_one("h1#pageTitle[itemprop='name']")
#     if el:
#         name = _clean(el.get_text(" ", strip=True))
#     if not name and soup.title:
#         name = _clean(soup.title.get_text().split("|")[0])
#     if not name:
#         name = "Unknown Product"

#     # ---- price (current) ----
#     price, price_source = "N/A", "none"
#     price_pod = soup.select_one('[data-testid="standard-price-pod"]')
#     if price_pod:
#         p_text = _clean(price_pod.get_text(" ", strip=True))
#         gbp = _parse_gbp_text(p_text)
#         if gbp:
#             price, price_source = gbp, "onsite"
#     if price_source == "none":
#         # fallbacks
#         any_price = soup.find(string=re.compile(r"£\s*[\d,]+(?:\.\d{1,2})?"))
#         if any_price:
#             gbp = _parse_gbp_text(any_price)
#             if gbp:
#                 price, price_source = gbp, "onsite"

#     # ---- stock ----
#     in_stock, stock_text = None, ""
#     # AO has "Add to basket" CTA
#     atb = soup.select_one("a.addToBasket.btn-add-to-basket, button.btn-add-to-basket, [data-testid='add-to-basket']")
#     if atb:
#         in_stock, stock_text = True, _clean(atb.get_text(" ", strip=True)) or "Add to basket"
#     body_txt = _clean(soup.get_text(" ", strip=True)).lower()
#     if any(w in body_txt for w in ["out of stock", "sold out", "unavailable"]):
#         in_stock, stock_text = False, "Unavailable"

#     # ---- description ----
#     desc_parts: List[str] = []
#     # main summary block
#     summ = soup.select_one("#product-summary-webshop, [data-testid='product-summary']")
#     if summ:
#         desc_parts.append(_clean_multiline(summ.get_text("\n", strip=True)))
#     # dimensions near summary
#     dims = soup.find(string=re.compile(r"Dimensions\s*\(cm\)", re.I))
#     if dims:
#         parent = getattr(dims, "parent", None)
#         txt = _clean_multiline(parent.get_text("\n", strip=True) if parent else str(dims))
#         if txt and txt not in desc_parts:
#             desc_parts.append(txt)
#     description = _clean_multiline("\n\n".join([d for d in desc_parts if d]))

#     # ---- images ----
#     imgs: List[str] = []
#     # thumbs container
#     for img in soup.select("#galleryThumbs img"):
#         u = img.get("data-src") or img.get("data-original") or img.get("src") or ""
#         if not u and img.get("srcset"):
#             u = str(img.get("srcset")).split()[0]
#         if u:
#             imgs.append(u)
#     # generic fallbacks
#     if not imgs:
#         for img in soup.select("img[data-src], img[data-original], img[srcset], img[src]"):
#             u = img.get("data-src") or img.get("data-original") or img.get("src") or ""
#             if not u and img.get("srcset"):
#                 u = str(img.get("srcset")).split()[0]
#             if u:
#                 imgs.append(u)

#     imgs = _dedupe_preserve([u for u in imgs if u.startswith("http")])

#     return {
#         "name": name,
#         "price": price,
#         "price_source": price_source,
#         "in_stock": in_stock,
#         "stock_text": stock_text,
#         "description": description,
#         "image_urls": imgs
#     }

# # =========================
# # Orchestrator
# # =========================
# def scrape_ao_with_oxylabs(url: str,
#                            download_images_flag: bool=True,
#                            max_images: Optional[int]=None) -> Dict:
#     html = oxy_fetch_html(url, geo="United Kingdom")
#     parsed = parse_ao(html)

#     folder = DATA_DIR / f"ao_{_safe_name(parsed['name'])}_{_stable_id_from_url(url)}"
#     folder.mkdir(parents=True, exist_ok=True)

#     images_downloaded: List[str] = []
#     if download_images_flag and parsed["image_urls"]:
#         print(f"Downloading {len(parsed['image_urls']) if not max_images else min(len(parsed['image_urls']), max_images)} images …")
#         images_downloaded = download_images_jpg(parsed["image_urls"], folder, referer=url, max_images=max_images)

#     return {
#         "url": url,
#         "name": parsed["name"],
#         "price": parsed["price"],
#         "price_source": parsed["price_source"],
#         "in_stock": parsed["in_stock"],
#         "stock_text": parsed["stock_text"],
#         "description": parsed["description"],
#         "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
#         "image_urls": parsed["image_urls"],
#         "images_downloaded": images_downloaded,
#         "folder": str(folder),
#         "mode": "oxylabs-universal"
#     }

# # =========================
# # CLI
# # =========================
# if __name__ == "__main__":
#     TEST_URL = "https://ao.com/product/vqsbpkk336laew-laura-ashley-kettle-white-103106-78.aspx"
#     data = scrape_ao_with_oxylabs(TEST_URL, download_images_flag=True, max_images=20)
#     print(json.dumps(data, indent=2, ensure_ascii=False))




# ao_com_oxylabs.py — Oxylabs universal + JPG-only images
# Python 3.9+
# pip install requests beautifulsoup4 lxml pillow pillow-avif-plugin
# Version: 2.0 - Fixed stock detection + added page validation

from __future__ import annotations
import re, json, hashlib, time, random
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from urllib.parse import urlparse, urldefrag, urlsplit, urlunsplit
from io import BytesIO
from datetime import datetime, timezone

import requests
from requests.exceptions import RequestException
from bs4 import BeautifulSoup
from PIL import Image

# Optional AVIF/HEIF support
try:
    import pillow_avif  # noqa: F401
except Exception:
    pass

__version__ = "2.0"

# =========================
# Config
# =========================
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception as e:
    raise RuntimeError("Missing oxylabs_secrets.py with OXY_USER and OXY_PASS") from e
if not (OXY_USER and OXY_PASS):
    raise RuntimeError("OXY_USER/OXY_PASS in oxylabs_secrets.py must be non-empty.")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
ACCEPT_LANG = "en-GB,en;q=0.9"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data_uk"
DEBUG_DIR = BASE_DIR / "debug"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"

# =========================
# Helpers
# =========================
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _clean_multiline(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _safe_name(s: str) -> str:
    s = _clean(s)
    return re.sub(r"[^\w.\-]+", "_", s)[:120] or "product"

def _stable_id_from_url(url: str) -> str:
    try:
        url, _ = urldefrag(url)
        path = urlparse(url).path.strip("/").split("/")
        last = (path[-1] if path else "") or url
        return re.sub(r"[^\w\-]+", "", last) or hashlib.sha1(url.encode()).hexdigest()[:12]
    except Exception:
        return hashlib.sha1(url.encode()).hexdigest()[:12]

def _dedupe_preserve(urls: List[str]) -> List[str]:
    seen, out = set(), []
    for u in urls:
        k = u.split("?")[0]
        if k and k not in seen:
            seen.add(k); out.append(u)
    return out

def _strip_query(u: str) -> str:
    sp = urlsplit(u)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

def _parse_gbp_text(text: str) -> Optional[str]:
    if not text: return None
    m = re.search(r"£\s*([\d,]+(?:\.\d{1,2})?)", text)
    if not m:
        m = re.search(r"\b([\d,]+(?:\.\d{1,2})?)\b", text)
    if not m:
        return None
    val = m.group(1).replace(",", "")
    if "." not in val:
        val = f"{val}.00"
    return f"{val} GBP"

def _vprint(v: bool, *a):
    if v:
        print(*a)

# =========================
# Oxylabs client
# =========================
def _build_context_array(session_id: Optional[str]) -> list[dict]:
    ctx: list[dict] = []
    if session_id:
        ctx.append({"key": "session_id", "value": session_id})
    ctx.append({
        "key": "headers",
        "value": {
            "User-Agent": UA,
            "Accept-Language": ACCEPT_LANG
        }
    })
    return ctx

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

def oxy_post(payload: dict, retries: int = 6, base_sleep: float = 2.0) -> dict:
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(OXY_ENDPOINT, auth=(OXY_USER, OXY_PASS), json=payload, timeout=120)
            if r.status_code == 200:
                data = r.json()
                results = data.get("results") or []
                if not results:
                    raise RuntimeError("Oxylabs: empty results")
                content = results[0].get("content", "")
                if "<html" not in content.lower():
                    raise RuntimeError("Oxylabs: non-HTML content")
                return data

            if r.status_code in (429, 500, 502, 503, 504):
                wait = _parse_retry_after(r.headers)
                if wait is None:
                    wait = (base_sleep * (2 ** attempt)) + random.uniform(0.25, 0.75)
                time.sleep(min(wait, 30.0))
                continue

            try:
                err_json = r.json()
                raise RuntimeError(f"Oxylabs HTTP {r.status_code}: {err_json}")
            except ValueError:
                raise RuntimeError(f"Oxylabs HTTP {r.status_code}: {r.text[:500]}")

        except (RequestException, ValueError, RuntimeError) as e:
            last_err = e
            if attempt < retries:
                wait = (base_sleep * (2 ** attempt)) + random.uniform(0.25, 0.75)
                time.sleep(min(wait, 10.0))
                continue
            raise RuntimeError(f"Oxylabs failed after {retries+1} attempts: {e}") from e
    raise last_err or RuntimeError("Oxylabs unknown error")

def oxy_fetch_html(url: str, geo: str = "United Kingdom") -> str:
    url, _ = urldefrag(url)
    session_id = f"ao-{int(time.time())}-{random.randint(1000,9999)}"
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
        "geo_location": geo,
        "user_agent_type": "desktop",
        "context": _build_context_array(session_id),
    }
    data = oxy_post(payload)
    return data["results"][0]["content"]


# =========================
# Page Validation - DETECT INVALID PAGES
# =========================
def _is_category_or_listing_page(soup: BeautifulSoup, url: str) -> bool:
    """
    Detect if the page is a category/listing/search page instead of a product detail page.
    Returns True if it's NOT a valid product page.
    """
    path = urlsplit(url).path.lower()
    
    # Check 1: URL patterns for non-PDP pages
    # AO.com product URLs typically end with .aspx and contain "product"
    # Category/listing pages have patterns like /l/, /cat/, /search/
    if "/l/" in path or "/cat/" in path or "/search" in path:
        return True
    if not path.endswith(".aspx"):
        # Most AO product pages end in .aspx
        if "/product/" not in path and not re.search(r"-\d+\.aspx$", path):
            # Could be a category page
            pass
    
    # Check 2: Results count indicator
    results_patterns = [
        r"\d[\d,]*\s*results?\b",
        r"showing\s+\d+\s*-\s*\d+\s+of\s+\d+",
        r"\d+\s+products?\s*found",
        r"we found \d+ products",
    ]
    page_text = soup.get_text(" ", strip=True).lower()
    for pattern in results_patterns:
        if re.search(pattern, page_text, re.I):
            return True
    
    # Check 3: Product grid/listing containers
    listing_selectors = [
        "[data-testid='product-grid']",
        "[data-testid='product-list']",
        ".product-grid",
        ".product-list",
        ".search-results",
        ".category-products",
    ]
    for sel in listing_selectors:
        if soup.select_one(sel):
            return True
    
    # Check 4: Multiple product cards (>3 indicates listing)
    product_cards = soup.select("[data-testid='product-card'], .product-card, .product-tile")
    if len(product_cards) > 3:
        return True
    
    # Check 5: Filter/facet UI (strong indicator of listing page)
    filter_selectors = [
        "[data-testid='filter-sidebar']",
        ".filter-panel",
        ".facet-list",
        "[class*='refinement']",
    ]
    filter_count = sum(1 for sel in filter_selectors if soup.select_one(sel))
    if filter_count >= 1:
        return True
    
    return False


def _is_product_unavailable(soup: BeautifulSoup) -> Tuple[bool, Optional[str]]:
    """
    Detect if the product page shows the product as permanently unavailable/discontinued.
    Note: "Back in stock soon" is NOT permanent unavailability - it's temporary out of stock.
    Returns (is_unavailable, reason)
    """
    # Check for PERMANENT unavailability (discontinued, removed, etc.)
    # NOT temporary out of stock situations
    
    unavailable_selectors = [
        "[data-testid='product-discontinued']",
        ".product-discontinued",
        ".product-removed",
    ]
    
    for sel in unavailable_selectors:
        el = soup.select_one(sel)
        if el:
            text = _clean(el.get_text())
            if text:
                return True, text
    
    # Check for specific PERMANENT discontinuation messages
    product_area = soup.select_one("main, #content, .product-detail") or soup
    text = _clean(product_area.get_text()).lower()
    
    permanent_patterns = [
        r"this product (has been|is) discontinued",
        r"this product is no longer available",
        r"product (has been )?removed",
        r"we no longer (stock|sell) this",
    ]
    
    for pattern in permanent_patterns:
        if re.search(pattern, text):
            return True, "Product has been discontinued"
    
    # Check for 404-style page
    title = soup.title.string if soup.title else ""
    if re.search(r"page not found|404|not found", title, re.I):
        return True, "Page not found (404)"
    
    return False, None


def _is_valid_pdp(soup: BeautifulSoup, url: str) -> Tuple[bool, str]:
    """
    Validate if the page is a legitimate Product Detail Page.
    Returns (is_valid, reason_if_invalid)
    """
    # Check if it's a category/listing page
    if _is_category_or_listing_page(soup, url):
        return False, "URL is a category/listing page, not a product page"
    
    # Check if product is permanently unavailable
    is_unavailable, unavailable_reason = _is_product_unavailable(soup)
    if is_unavailable:
        return False, unavailable_reason or "Product is no longer available"
    
    # Check for essential AO.com PDP elements
    pdp_indicators = {
        "page_title": bool(soup.select_one("h1#pageTitle[itemprop='name'], h1#pageTitle")),
        "price_pod": bool(soup.select_one('[data-testid="standard-price-pod"], .price-pod, [class*="price"]')),
        "product_summary": bool(soup.select_one("#product-summary-webshop, [data-testid='product-summary']")),
        "gallery": bool(soup.select_one("#galleryThumbs, .product-gallery, [data-testid='product-gallery']")),
        "add_to_basket": bool(soup.select_one(".addToBasket, .btn-add-to-basket, [data-testid='add-to-basket']")),
    }
    
    indicator_count = sum(pdp_indicators.values())
    
    # Need at least 2 PDP indicators
    if indicator_count >= 2:
        return True, ""
    
    # If URL looks like a product URL but lacks elements
    if ".aspx" in url.lower() and indicator_count == 0:
        return False, "Product page structure not found - product may have been removed"
    
    if indicator_count >= 1:
        return True, ""
    
    return False, "Page does not contain expected product detail elements"


def _create_invalid_result(url: str, reason: str) -> Dict:
    """
    Create a result dict for invalid/unavailable products.
    """
    return {
        "url": url,
        "name": f"INVALID LINK - {reason}",
        "price": None,
        "price_source": None,
        "in_stock": None,
        "stock_text": None,
        "description": None,
        "image_count": 0,
        "image_urls": [],
        "images_downloaded": [],
        "folder": None,
        "mode": "invalid",
        "is_valid": False,
        "invalid_reason": reason,
    }


# =========================
# Image download (ALWAYS .jpg)
# =========================
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

def download_images_jpg(urls: List[str], folder: Path, referer: str, max_images: Optional[int]=None, verbose: bool=True) -> List[str]:
    if max_images is not None:
        urls = urls[:max_images]
    saved = []
    folder.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Referer": referer,
    }
    for i, u in enumerate(urls, 1):
        try:
            u = _strip_query(u)
            with requests.get(u, headers=headers, timeout=40) as r:
                ct = (r.headers.get("Content-Type", "") or "").lower()
                if r.status_code == 200 and (ct.startswith("image/") or r.content):
                    out = folder / f"{i:02d}.jpg"
                    try:
                        out.write_bytes(_img_to_jpg_bytes(r.content))
                        saved.append(str(out))
                        _vprint(verbose, f"  ✓ image {i:02d}.jpg")
                    except Exception as pe:
                        if ct.startswith(("image/jpeg", "image/jpg")):
                            out.write_bytes(r.content)
                            saved.append(str(out))
                            _vprint(verbose, f"  ✓ image {i:02d}.jpg (raw)")
                        else:
                            _vprint(verbose, f"  ! convert error: {u} - {pe}")
                else:
                    _vprint(verbose, f"  ! image HTTP {r.status_code}: {u}")
        except Exception as e:
            _vprint(verbose, f"  ! image error: {u} - {e}")
    return saved


# =========================
# AO.com parser
# =========================
def parse_ao(html: str) -> Dict:
    soup = BeautifulSoup(html, "lxml")

    # ---- name ----
    name = ""
    el = soup.select_one("h1#pageTitle[itemprop='name']")
    if el:
        name = _clean(el.get_text(" ", strip=True))
    if not name and soup.title:
        name = _clean(soup.title.get_text().split("|")[0])
    if not name:
        name = "Unknown Product"

    # ---- price (current) ----
    price, price_source = "N/A", "none"
    price_pod = soup.select_one('[data-testid="standard-price-pod"]')
    if price_pod:
        p_text = _clean(price_pod.get_text(" ", strip=True))
        gbp = _parse_gbp_text(p_text)
        if gbp:
            price, price_source = gbp, "onsite"
    if price_source == "none":
        any_price = soup.find(string=re.compile(r"£\s*[\d,]+(?:\.\d{1,2})?"))
        if any_price:
            gbp = _parse_gbp_text(any_price)
            if gbp:
                price, price_source = gbp, "onsite"

    # ---- stock (IMPROVED) ----
    in_stock, stock_text = None, ""
    
    # FIRST: Check for explicit OUT OF STOCK indicators
    # These take priority over "Add to basket" button detection
    out_of_stock_patterns = [
        # "Back in stock soon" - this is OUT OF STOCK
        (r"back in stock soon", "Back in stock soon"),
        (r"out of stock", "Out of stock"),
        (r"sold out", "Sold out"),
        (r"currently unavailable", "Currently unavailable"),
        (r"temporarily unavailable", "Temporarily unavailable"),
        (r"notify me when available", "Out of stock"),
        (r"email me when (back )?in stock", "Out of stock"),
        (r"this one flew off the shelves", "Back in stock soon"),
    ]
    
    # Check specific stock message containers first
    stock_containers = soup.select(
        ".bg-ui-warning, [class*='stock-message'], [class*='availability'], "
        "[data-testid='stock-status'], [data-testid='availability']"
    )
    
    for container in stock_containers:
        container_text = _clean(container.get_text()).lower()
        for pattern, status_text in out_of_stock_patterns:
            if re.search(pattern, container_text, re.I):
                in_stock = False
                stock_text = status_text
                break
        if in_stock is False:
            break
    
    # If not found in specific containers, check broader page text
    if in_stock is None:
        body_txt = _clean(soup.get_text(" ", strip=True)).lower()
        for pattern, status_text in out_of_stock_patterns:
            if re.search(pattern, body_txt, re.I):
                in_stock = False
                stock_text = status_text
                break
    
    # ONLY if no out-of-stock indicators found, check for Add to Basket
    if in_stock is None:
        atb = soup.select_one(
            "a.addToBasket.btn-add-to-basket, "
            "button.btn-add-to-basket, "
            "[data-testid='add-to-basket']"
        )
        if atb:
            # Check if the button is disabled or has out-of-stock text
            btn_text = _clean(atb.get_text()).lower()
            is_disabled = atb.get("disabled") is not None or "disabled" in (atb.get("class") or [])
            
            if is_disabled or any(oos in btn_text for oos in ["out of stock", "unavailable", "sold out"]):
                in_stock = False
                stock_text = "Out of stock"
            else:
                in_stock = True
                stock_text = _clean(atb.get_text(" ", strip=True)) or "Add to basket"
    
    # Check JSON-LD for availability as final fallback
    if in_stock is None:
        for script in soup.select("script[type='application/ld+json']"):
            try:
                data = json.loads(script.get_text())
                if isinstance(data, dict):
                    offers = data.get("offers", {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    avail = str(offers.get("availability", "")).lower()
                    if "instock" in avail:
                        in_stock = True
                        stock_text = "In stock"
                    elif "outofstock" in avail or "soldout" in avail:
                        in_stock = False
                        stock_text = "Out of stock"
            except Exception:
                continue

    # ---- description ----
    desc_parts: List[str] = []
    summ = soup.select_one("#product-summary-webshop, [data-testid='product-summary']")
    if summ:
        desc_parts.append(_clean_multiline(summ.get_text("\n", strip=True)))
    dims = soup.find(string=re.compile(r"Dimensions\s*\(cm\)", re.I))
    if dims:
        parent = getattr(dims, "parent", None)
        txt = _clean_multiline(parent.get_text("\n", strip=True) if parent else str(dims))
        if txt and txt not in desc_parts:
            desc_parts.append(txt)
    description = _clean_multiline("\n\n".join([d for d in desc_parts if d]))

    # ---- images ----
    imgs: List[str] = []
    for img in soup.select("#galleryThumbs img"):
        u = img.get("data-src") or img.get("data-original") or img.get("src") or ""
        if not u and img.get("srcset"):
            u = str(img.get("srcset")).split()[0]
        if u:
            imgs.append(u)
    if not imgs:
        for img in soup.select("img[data-src], img[data-original], img[srcset], img[src]"):
            u = img.get("data-src") or img.get("data-original") or img.get("src") or ""
            if not u and img.get("srcset"):
                u = str(img.get("srcset")).split()[0]
            if u:
                imgs.append(u)

    imgs = _dedupe_preserve([u for u in imgs if u.startswith("http")])

    return {
        "name": name,
        "price": price,
        "price_source": price_source,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_urls": imgs
    }


# =========================
# Orchestrator
# =========================
def scrape_ao_with_oxylabs(
    url: str,
    download_images_flag: bool = True,
    max_images: Optional[int] = None,
    verbose: bool = True
) -> Dict:
    """
    Scrape an AO.com product page via Oxylabs.
    Validates that the URL is a legitimate product page.
    Returns invalid result for category/listing pages or unavailable products.
    """
    try:
        html = oxy_fetch_html(url, geo="United Kingdom")
    except Exception as e:
        _vprint(verbose, f"Failed to fetch URL: {e}")
        return _create_invalid_result(url, f"Failed to fetch page: {str(e)}")
    
    soup = BeautifulSoup(html, "lxml")
    
    # Save HTML for debugging
    if verbose:
        debug_file = DEBUG_DIR / f"ao_debug_{_stable_id_from_url(url)}.html"
        try:
            debug_file.write_text(html, encoding="utf-8")
            _vprint(verbose, f"Debug HTML saved to: {debug_file}")
        except Exception:
            pass
    
    # ========== VALIDATION CHECK ==========
    is_valid, invalid_reason = _is_valid_pdp(soup, url)
    if not is_valid:
        _vprint(verbose, f"⚠ Invalid page detected: {invalid_reason}")
        return _create_invalid_result(url, invalid_reason)
    # ======================================
    
    parsed = parse_ao(html)

    folder = DATA_DIR / f"ao_{_safe_name(parsed['name'])}_{_stable_id_from_url(url)}"
    folder.mkdir(parents=True, exist_ok=True)

    images_downloaded: List[str] = []
    if download_images_flag and parsed["image_urls"]:
        img_count = len(parsed['image_urls']) if not max_images else min(len(parsed['image_urls']), max_images)
        _vprint(verbose, f"Downloading {img_count} images …")
        images_downloaded = download_images_jpg(
            parsed["image_urls"], folder, referer=url, max_images=max_images, verbose=verbose
        )

    return {
        "url": url,
        "name": parsed["name"],
        "price": parsed["price"],
        "price_source": parsed["price_source"],
        "in_stock": parsed["in_stock"],
        "stock_text": parsed["stock_text"],
        "description": parsed["description"],
        "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
        "image_urls": parsed["image_urls"],
        "images_downloaded": images_downloaded,
        "folder": str(folder),
        "mode": "oxylabs-universal",
        "is_valid": True,
        "invalid_reason": None,
    }


# # =========================
# # CLI
# # =========================
# if __name__ == "__main__":
#     import sys
    
#     # Test URLs
#     TEST_URLS = [
#         # Product URL (may be out of stock)
#         "https://ao.com/product/vqsbpkk336laew-laura-ashley-kettle-white-103106-78.aspx",
#     ]
    
#     if len(sys.argv) > 1:
#         TEST_URLS = [sys.argv[1]]
    
#     for test_url in TEST_URLS:
#         print(f"\nTesting: {test_url}")
#         print("=" * 70)
#         data = scrape_ao_with_oxylabs(test_url, download_images_flag=True, verbose=True)
#         print(json.dumps(data, indent=2, ensure_ascii=False))
#         print()