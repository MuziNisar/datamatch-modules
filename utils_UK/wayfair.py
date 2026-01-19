
# # wayfair.py
# # Python 3.10+
# # pip install requests bs4 lxml pillow
# # Version: 2.0 - Fixed image deduplication

# from __future__ import annotations
# import os, re, time, json, html as _html, hashlib, io
# from pathlib import Path
# from typing import Optional, Tuple, List, Dict
# from urllib.parse import urldefrag

# import requests
# from bs4 import BeautifulSoup
# from PIL import Image

# __version__ = "2.0"

# # -----------------------------
# # Credentials (env or local module)
# # -----------------------------
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS
# except Exception:
#     OXY_USER = os.getenv("OXYLABS_USERNAME", "")
#     OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")

# if not OXY_USER or not OXY_PASS:
#     raise RuntimeError("Missing Oxylabs credentials. Set OXYLABS_USERNAME/OXYLABS_PASSWORD env or provide oxylabs_secrets.py")

# # -----------------------------
# # Constants
# # -----------------------------
# UA = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
# )
# ACCEPT_LANG_GB = "en-GB,en;q=0.9"
# ACCEPT_HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

# # -----------------------------
# # Paths
# # -----------------------------
# def _root() -> Path:
#     return Path(__file__).resolve().parent

# SAVE_DIR = _root() / "data1"

# # -----------------------------
# # Small helpers
# # -----------------------------
# def _clean(s: str | None) -> str:
#     return re.sub(r"\s+", " ", _html.unescape(s or "")).strip()

# def _safe_name(s: str) -> str:
#     n = re.sub(r"[^\w\s\-]", "", (s or "")).strip().replace(" ", "_")
#     return n or "NA"

# def _short_uid(s: str) -> str:
#     """8-char stable id from URL/content."""
#     return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:8]

# def _looks_like_html(s: str) -> bool:
#     if not s or len(s) < 300:
#         return False
#     ls = s.lower()
#     return any(k in ls for k in ("<!doctype", "<head", "<body", "<div", "<meta", "<title", "wayfair"))

# def _session_with_retries() -> requests.Session:
#     from urllib3.util.retry import Retry
#     from requests.adapters import HTTPAdapter
#     sess = requests.Session()
#     retry = Retry(
#         total=3,
#         connect=3,
#         read=3,
#         backoff_factor=0.6,
#         status_forcelist=(429, 500, 502, 503, 504),
#         allowed_methods=frozenset(["GET", "POST"])
#     )
#     sess.mount("https://", HTTPAdapter(max_retries=retry))
#     sess.mount("http://", HTTPAdapter(max_retries=retry))
#     return sess

# def _oxylabs_query(payload: dict, timeout: int) -> dict:
#     sess = _session_with_retries()
#     r = sess.post(
#         "https://realtime.oxylabs.io/v1/queries",
#         auth=(OXY_USER, OXY_PASS),
#         json=payload,
#         timeout=timeout,
#     )
#     r.raise_for_status()
#     return r.json()

# def oxy_fetch_html(url: str, *, geo="United Kingdom", accept_lang=ACCEPT_LANG_GB, timeout=90) -> tuple[str, str]:
#     """
#     Robust Oxylabs HTML fetcher:
#     Returns (html, final_url).
#     """
#     url, _ = urldefrag(url)
#     base_headers = {
#         "User-Agent": UA,
#         "Accept-Language": accept_lang,
#         "Accept": ACCEPT_HTML,
#         "Cache-Control": "no-cache",
#         "Pragma": "no-cache",
#     }

#     attempts = [
#         ("universal", "html"),
#         ("web",       "html"),
#         ("browser",   "html"),
#         ("universal", None),
#         ("web",       None),
#     ]

#     last_exc = None
#     for source, render in attempts:
#         try:
#             payload = {
#                 "source": source,
#                 "url": url,
#                 "geo_location": geo,
#                 "headers": base_headers,
#                 "user_agent_type": "desktop",
#             }
#             if render:
#                 payload["render"] = render

#             data = _oxylabs_query(payload, timeout=timeout)
#             res = (data.get("results") or [{}])[0]
#             content = res.get("content") or ""
#             final_url = res.get("final_url") or res.get("url") or url

#             if not _looks_like_html(content) and final_url and final_url != url:
#                 payload2 = dict(payload)
#                 payload2["url"] = final_url
#                 data2 = _oxylabs_query(payload2, timeout=timeout)
#                 res2 = (data2.get("results") or [{}])[0]
#                 content2 = res2.get("content") or ""
#                 if _looks_like_html(content2):
#                     return content2, final_url
#                 raise RuntimeError("Oxylabs returned non-HTML on follow")

#             if not _looks_like_html(content):
#                 raise RuntimeError("Oxylabs returned non-HTML (heuristic)")

#             return content, final_url
#         except Exception as e:
#             last_exc = e
#             time.sleep(1.2)

#     raise RuntimeError(f"Oxylabs HTML fetch failed: {last_exc}")

# # -----------------------------
# # JSON-LD helpers
# # -----------------------------
# def _iter_jsonld(soup: BeautifulSoup):
#     for tag in soup.select("script[type='application/ld+json']"):
#         txt = tag.get_text(strip=False)
#         if not txt:
#             continue
#         try:
#             data = json.loads(txt)
#             yield data
#         except Exception:
#             try:
#                 for part in re.split(r"\n(?=\s*{)", txt.strip()):
#                     part = part.strip()
#                     if part:
#                         yield json.loads(part)
#             except Exception:
#                 continue

# def _jsonld_find_products(data) -> List[dict]:
#     found = []
#     stack = [data]
#     while stack:
#         cur = stack.pop()
#         if isinstance(cur, dict):
#             if cur.get("@type") == "Product":
#                 found.append(cur)
#             for v in cur.values():
#                 if isinstance(v, (dict, list)):
#                     stack.append(v)
#         elif isinstance(cur, list):
#             for v in cur:
#                 if isinstance(v, (dict, list)):
#                     stack.append(v)
#     return found

# def _jsonld_availability_from_offers(offers) -> Optional[bool]:
#     if not offers:
#         return None
#     lst = offers if isinstance(offers, list) else [offers]
#     for off in lst:
#         if not isinstance(off, dict):
#             continue
#         avail = str(off.get("availability") or off.get("itemAvailability") or "")
#         if re.search(r"InStock", avail, re.I):
#             return True
#         if re.search(r"OutOfStock|SoldOut|PreOrder", avail, re.I):
#             return False
#     return None

# # -----------------------------
# # Wayfair image URL normalization
# # -----------------------------
# def _wf_to_hires(u: str, size: int = 1600) -> str:
#     """
#     Normalize Wayfair CDN URLs to higher-res.
#     """
#     if not u:
#         return u
#     u = u.replace(" ", "%20")
#     u = re.sub(r"/resize-h\d+-w\d+%5Ecompr-r\d+/", f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
#     u = re.sub(r"/resize-h\d+-w\d+\^compr-r\d+/",  f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
#     if "/resize-" not in u:
#         u = re.sub(r"(https://assets\.wfcdn\.com/im/[^/]+/)",
#                    rf"\1resize-h{size}-w{size}%5Ecompr-r85/", u)
#     return u

# def _img_dedup_key(u: str) -> str:
#     """
#     Extract the unique image identifier from Wayfair CDN URL.
#     URLs look like: https://assets.wfcdn.com/im/18220115/resize-h48-w48.../2732/273284981/VQ+...
#     The unique part is the image ID like '273284981'
#     """
#     # Try to extract the image ID (usually a 9-digit number before the filename)
#     # Pattern: /2732/273284981/filename.jpg
#     m = re.search(r"/(\d{8,10})/[^/]+\.(jpg|jpeg|png|webp)", u, re.I)
#     if m:
#         return m.group(1)  # Return just the image ID
    
#     # Fallback: remove resize segment and query string, normalize im/ segment
#     u = re.sub(r"/resize-h\d+-w\d+(?:%5E|\^)compr-r\d+/", "/", u)
#     u = re.sub(r"/im/\d+/", "/im/X/", u)
#     return re.sub(r"[?].*$", "", u)

# # -----------------------------
# # Core parsing from HTML
# # -----------------------------
# def _parse_name(soup: BeautifulSoup) -> str:
#     h = soup.select_one("h1[data-rtl-id='listingHeaderNameHeading']")
#     if h:
#         t = _clean(h.get_text(" ", strip=True))
#         if t:
#             return t

#     for data in _iter_jsonld(soup):
#         for prod in _jsonld_find_products(data):
#             nm = prod.get("name")
#             if isinstance(nm, str) and nm.strip():
#                 return _clean(nm)

#     og = soup.find("meta", attrs={"property": "og:title"})
#     if og and og.get("content"):
#         return _clean(og["content"])

#     if soup.title and soup.title.string:
#         return _clean(soup.title.string)

#     return "N/A"

# def _parse_price(soup: BeautifulSoup) -> str:
#     price_host = soup.select_one("[data-test-id='PriceDisplay']")
#     if price_host:
#         txt = _clean(price_host.get_text(" ", strip=True))
#         if txt:
#             return txt

#     cand = soup.find(string=re.compile(r"£\s?\d[\d,]*\.?\d{0,2}"))
#     if cand:
#         return _clean(cand)

#     for data in _iter_jsonld(soup):
#         for prod in _jsonld_find_products(data):
#             offers = prod.get("offers")
#             if isinstance(offers, dict):
#                 price = offers.get("price") or offers.get("lowPrice")
#                 cur = offers.get("priceCurrency", "")
#                 if price:
#                     return f"{price} {cur}".strip()
#             elif isinstance(offers, list):
#                 for o in offers:
#                     if not isinstance(o, dict):
#                         continue
#                     price = o.get("price") or o.get("lowPrice")
#                     cur = o.get("priceCurrency", "")
#                     if price:
#                         return f"{price} {cur}".strip()

#     return "N/A"

# def _parse_stock(soup: BeautifulSoup) -> Optional[bool]:
#     oos_texts = [
#         "Out of Stock",
#         "Not available",
#         "Sold Out",
#     ]
#     page_text = soup.get_text(" ", strip=True)
#     for t in oos_texts:
#         if re.search(rf"\b{re.escape(t)}\b", page_text, re.I):
#             return False

#     if re.search(r"\bAdd to (Cart|Basket)\b", page_text, re.I) and not re.search(r"Out of Stock|Not available", page_text, re.I):
#         return True

#     for data in _iter_jsonld(soup):
#         for prod in _jsonld_find_products(data):
#             avail = _jsonld_availability_from_offers(prod.get("offers"))
#             if avail is not None:
#                 return avail

#     return None

# def _parse_description(soup: BeautifulSoup) -> str:
#     def _clean_text(t: str) -> str:
#         t = _html.unescape(t or "")
#         t = t.replace("\r", "")
#         t = re.sub(r"[ \t]+", " ", t)
#         t = re.sub(r"\n{3,}", "\n\n", t)
#         return t.strip()

#     def _looks_generic(s: str) -> bool:
#         return bool(re.search(r"you'?ll love .* at wayfair", s, re.I))

#     for box in soup.select('[data-hb-id="BoxV3"]'):
#         st = (box.get("style") or "").lower()
#         if "pre-line" in st:
#             txt = _clean_text(box.get_text("\n", strip=True))
#             if txt and len(txt) > 120:
#                 return txt

#     features = []
#     for p in soup.select("p[data-hb-id='Text']"):
#         if re.search(r"\bFeatures\b", p.get_text(" ", strip=True), re.I):
#             nxt = p.find_next("ul")
#             if nxt:
#                 items = [ _clean_text(li.get_text(" ", strip=True)) for li in nxt.select("li") ]
#                 items = [i for i in items if i]
#                 if items:
#                     features.append("Features:\n- " + "\n- ".join(items))
#             break

#     best = ""
#     for data in _iter_jsonld(soup):
#         for prod in _jsonld_find_products(data):
#             desc = prod.get("description")
#             if isinstance(desc, str):
#                 cand = _clean_text(desc)
#                 if cand and not _looks_generic(cand) and len(cand) > len(best):
#                     best = cand
#     if best:
#         if features:
#             return best + "\n\n" + "\n\n".join(features)
#         return best

#     md = soup.find("meta", attrs={"name": "description"})
#     if md and md.get("content"):
#         cand = _clean_text(md["content"])
#         if cand and not _looks_generic(cand):
#             if features:
#                 return cand + "\n\n" + "\n\n".join(features)
#             return cand

#     if features:
#         return "\n\n".join(features)

#     return "N/A"

# def _parse_images(soup: BeautifulSoup) -> List[str]:
#     """
#     Extract unique product images from Wayfair PDP.
#     Only use thumbnails section which has the definitive count (e.g., "1 of 4").
#     """
#     from typing import Tuple
#     ordered: List[Tuple[int, str]] = []
#     seen_ids: set[str] = set()

#     # Primary source: thumbnails with aria-label showing position
#     # These tell us exactly how many images there are (e.g., "1 of 4", "2 of 4", etc.)
#     for btn in soup.select("[data-test-id='pdp-mt-thumbnails'] button[aria-label]"):
#         lab = btn.get("aria-label") or ""
#         m = re.search(r"(\d+)\s+of\s+(\d+)", lab, re.I)
#         if not m:
#             continue
#         order = int(m.group(1))
        
#         img = btn.find("img")
#         if not img:
#             continue
            
#         # Get src from srcset (prefer higher res) or src
#         src = None
#         srcset = img.get("srcset") or ""
#         if srcset:
#             # Parse srcset and get the URL (ignore resolution suffix)
#             parts = [p.strip().split()[0] for p in srcset.split(",") if p.strip()]
#             if parts:
#                 src = parts[-1]  # Last one is usually higher res
        
#         if not src:
#             src = img.get("src") or ""
        
#         if not src:
#             continue
        
#         # Extract unique image ID for deduplication
#         img_id = _img_dedup_key(src)
#         if img_id in seen_ids:
#             continue
#         seen_ids.add(img_id)
        
#         ordered.append((order, src))

#     # Sort by order number and convert to high-res
#     ordered.sort(key=lambda t: t[0])
    
#     images: List[str] = []
#     for _, u in ordered:
#         hu = _wf_to_hires(u, size=1600)
#         images.append(hu)
    
#     # If no thumbnails found, try carousel as fallback
#     if not images:
#         for img in soup.select("#MediaTrayCarouselWithThumbnailSidebar img, [data-test-id='pdp-mt-d-mainImageCarousel'] img"):
#             src = img.get("src") or img.get("data-src") or ""
#             if src and "assets.wfcdn.com/im/" in src:
#                 img_id = _img_dedup_key(src)
#                 if img_id not in seen_ids:
#                     seen_ids.add(img_id)
#                     images.append(_wf_to_hires(src, size=1600))
    
#     return images

# # -----------------------------
# # Downloader — JPG only + unique names
# # -----------------------------
# def _download_images_jpg(urls: List[str], referer: str, folder: Path, base_slug: str) -> List[str]:
#     """
#     Downloads all images and writes JPG only, with deterministic unique names.
#     Converts WEBP/PNG → JPG using Pillow.
#     """
#     folder.mkdir(parents=True, exist_ok=True)
#     out: List[str] = []
#     sess = _session_with_retries()
#     sess.headers.update({
#         "User-Agent": UA,
#         "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
#         "Accept-Language": ACCEPT_LANG_GB,
#         "Referer": referer,
#     })
#     for i, u in enumerate(urls, 1):
#         try:
#             r = sess.get(u, timeout=30)
#             if not r.ok or not r.content:
#                 continue

#             im = Image.open(io.BytesIO(r.content))
#             if im.mode in ("RGBA", "P"):
#                 im = im.convert("RGB")
#             elif im.mode != "RGB":
#                 im = im.convert("RGB")

#             path = folder / f"{base_slug}_{i:02d}.jpg"
#             im.save(path, format="JPEG", quality=92, optimize=True)
#             out.append(str(path))
#         except Exception:
#             continue
#     return out

# # -----------------------------
# # Public API
# # -----------------------------
# def scrape_wayfair_product(url: str, save_dir: Path | None = None, *, geo="United Kingdom") -> dict:
#     """
#     Fetch Wayfair PDP via Oxylabs and return parsed data + downloaded JPG images.
#     """
#     if save_dir is None:
#         save_dir = SAVE_DIR
#     save_dir = Path(save_dir)
#     save_dir.mkdir(parents=True, exist_ok=True)

#     accept_lang = ACCEPT_LANG_GB
#     html_doc, final_url = oxy_fetch_html(url, geo=geo, accept_lang=accept_lang, timeout=90)

#     soup = BeautifulSoup(html_doc, "lxml")

#     name = _parse_name(soup)
#     price = _parse_price(soup)
#     in_stock = _parse_stock(soup)
#     description = _parse_description(soup)

#     name_slug = _safe_name(name)
#     uid = _short_uid(final_url)
#     base_slug = f"{name_slug}_{uid}"

#     images = _parse_images(soup)
#     folder = save_dir / base_slug
#     downloaded = _download_images_jpg(images, referer=final_url, folder=folder, base_slug=base_slug)

#     return {
#         "name": name,
#         "price": price,
#         "in_stock": in_stock,
#         "description": description,
#         "image_count": len(downloaded),
#         "image_urls": images,
#         "images": downloaded,
#         "folder": str(folder),
#         "url": final_url,
#         "mode": "oxylabs(html)+direct(images_jpg_only)"
#     }

# # -----------------------------
# # CLI test
# # -----------------------------
# if __name__ == "__main__":
#     import sys
#     test_url = (sys.argv[1] if len(sys.argv) > 1 else
#                 "https://www.wayfair.co.uk/kitchenware-tableware/pdp/laura-ashley-vq-laura-ashley-jug-kettle-china-rose-laas1109.html")
#     data = scrape_wayfair_product(test_url)
#     print(json.dumps(data, indent=2, ensure_ascii=False))








# wayfair.py
# Python 3.10+
# pip install requests bs4 lxml pillow
# Version: 3.0 - Added page validation for invalid/category URLs

from __future__ import annotations
import os, re, time, json, html as _html, hashlib, io
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from urllib.parse import urldefrag, urlsplit

import requests
from bs4 import BeautifulSoup
from PIL import Image

__version__ = "3.0"

# -----------------------------
# Credentials (env or local module)
# -----------------------------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")

if not OXY_USER or not OXY_PASS:
    raise RuntimeError("Missing Oxylabs credentials. Set OXYLABS_USERNAME/OXYLABS_PASSWORD env or provide oxylabs_secrets.py")

# -----------------------------
# Constants
# -----------------------------
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
ACCEPT_LANG_GB = "en-GB,en;q=0.9"
ACCEPT_HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

# -----------------------------
# Paths
# -----------------------------
def _root() -> Path:
    return Path(__file__).resolve().parent

SAVE_DIR = _root() / "data1"
DEBUG_DIR = _root() / "debug"

# -----------------------------
# Small helpers
# -----------------------------
def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", _html.unescape(s or "")).strip()

def _safe_name(s: str) -> str:
    n = re.sub(r"[^\w\s\-]", "", (s or "")).strip().replace(" ", "_")
    return n or "NA"

def _short_uid(s: str) -> str:
    """8-char stable id from URL/content."""
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:8]

def _looks_like_html(s: str) -> bool:
    if not s or len(s) < 300:
        return False
    ls = s.lower()
    return any(k in ls for k in ("<!doctype", "<head", "<body", "<div", "<meta", "<title", "wayfair"))

def _session_with_retries() -> requests.Session:
    from urllib3.util.retry import Retry
    from requests.adapters import HTTPAdapter
    sess = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"])
    )
    sess.mount("https://", HTTPAdapter(max_retries=retry))
    sess.mount("http://", HTTPAdapter(max_retries=retry))
    return sess

def _oxylabs_query(payload: dict, timeout: int) -> dict:
    sess = _session_with_retries()
    r = sess.post(
        "https://realtime.oxylabs.io/v1/queries",
        auth=(OXY_USER, OXY_PASS),
        json=payload,
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()

def oxy_fetch_html(url: str, *, geo="United Kingdom", accept_lang=ACCEPT_LANG_GB, timeout=90) -> tuple[str, str]:
    """
    Robust Oxylabs HTML fetcher:
    Returns (html, final_url).
    """
    url, _ = urldefrag(url)
    base_headers = {
        "User-Agent": UA,
        "Accept-Language": accept_lang,
        "Accept": ACCEPT_HTML,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    attempts = [
        ("universal", "html"),
        ("web",       "html"),
        ("browser",   "html"),
        ("universal", None),
        ("web",       None),
    ]

    last_exc = None
    for source, render in attempts:
        try:
            payload = {
                "source": source,
                "url": url,
                "geo_location": geo,
                "headers": base_headers,
                "user_agent_type": "desktop",
            }
            if render:
                payload["render"] = render

            data = _oxylabs_query(payload, timeout=timeout)
            res = (data.get("results") or [{}])[0]
            content = res.get("content") or ""
            final_url = res.get("final_url") or res.get("url") or url

            if not _looks_like_html(content) and final_url and final_url != url:
                payload2 = dict(payload)
                payload2["url"] = final_url
                data2 = _oxylabs_query(payload2, timeout=timeout)
                res2 = (data2.get("results") or [{}])[0]
                content2 = res2.get("content") or ""
                if _looks_like_html(content2):
                    return content2, final_url
                raise RuntimeError("Oxylabs returned non-HTML on follow")

            if not _looks_like_html(content):
                raise RuntimeError("Oxylabs returned non-HTML (heuristic)")

            return content, final_url
        except Exception as e:
            last_exc = e
            time.sleep(1.2)

    raise RuntimeError(f"Oxylabs HTML fetch failed: {last_exc}")


# -----------------------------
# Page Validation - DETECT INVALID PAGES
# -----------------------------
def _is_category_or_listing_page(soup: BeautifulSoup, url: str) -> bool:
    """
    Detect if the page is a category/listing/search page instead of a product detail page.
    Returns True if it's NOT a valid product page.
    """
    path = urlsplit(url).path.lower()
    
    # Check 1: URL patterns for non-PDP pages
    # Category pages: /sb0/, /sb1/, ends with -cXXXXXX.html
    # PDP pages: /pdp/ in URL
    if "/sb0/" in path or "/sb1/" in path or "/sb2/" in path:
        return True
    if re.search(r"-c\d{5,}\.html$", path):  # Category URL pattern
        return True
    
    # Check 2: Results count indicator (e.g., "1,234 Results")
    results_patterns = [
        r"\d[\d,]*\s*results?\b",
        r"showing\s+\d+\s*-\s*\d+\s+of\s+\d+",
        r"\d+\s+products?\s+found",
    ]
    page_text = soup.get_text(" ", strip=True).lower()
    for pattern in results_patterns:
        if re.search(pattern, page_text, re.I):
            return True
    
    # Check 3: Product grid/listing containers
    listing_selectors = [
        "[data-test-id='ProductGrid']",
        "[data-test-id='SearchResults']",
        ".ProductGrid",
        "[class*='product-grid']",
        "[class*='search-results']",
        ".CategoryProductList",
    ]
    for sel in listing_selectors:
        if soup.select_one(sel):
            return True
    
    # Check 4: Multiple product cards (>3 indicates listing)
    product_cards = soup.select("[data-test-id='ProductCard'], [class*='ProductCard']")
    if len(product_cards) > 3:
        return True
    
    # Check 5: Filter/Sort UI elements (strong indicator of listing page)
    filter_indicators = [
        "[data-test-id='FilterSidebar']",
        "[data-test-id='SortDropdown']",
        "[class*='filter-sidebar']",
        "[class*='refinement']",
    ]
    filter_count = sum(1 for sel in filter_indicators if soup.select_one(sel))
    if filter_count >= 2:
        return True
    
    return False


def _is_product_unavailable(soup: BeautifulSoup) -> Tuple[bool, Optional[str]]:
    """
    Detect if the product page shows the product as unavailable/discontinued.
    Returns (is_unavailable, reason)
    """
    # Check for specific unavailability messages in product area
    unavailable_selectors = [
        "[data-test-id='ProductUnavailable']",
        "[data-test-id='DiscontinuedMessage']",
        ".product-unavailable",
        ".discontinued-product",
    ]
    
    for sel in unavailable_selectors:
        el = soup.select_one(sel)
        if el:
            text = _clean(el.get_text())
            if text:
                return True, text
    
    # Check for specific discontinuation messages in product containers
    product_containers = soup.select(
        "[data-test-id='ProductDetails'], .ProductDetails, main, #content"
    )
    
    for container in product_containers:
        text = _clean(container.get_text()).lower()
        # Very specific patterns
        if re.search(r"this (product|item) (is|has been) (discontinued|no longer available)", text):
            return True, "Product is no longer available"
        if re.search(r"(product|item) no longer (exists|available|sold)", text):
            return True, "Product no longer exists"
        if re.search(r"we'?re sorry.{0,30}(discontinued|no longer)", text):
            return True, "Product has been discontinued"
    
    # Check for 404-style page
    title = soup.title.string if soup.title else ""
    if re.search(r"page not found|404|not found", title, re.I):
        return True, "Page not found (404)"
    
    # Check for error containers
    error_selectors = [".error-page", ".page-not-found", "[data-test-id='ErrorPage']"]
    for sel in error_selectors:
        if soup.select_one(sel):
            return True, "Error page detected"
    
    return False, None


def _is_valid_pdp(soup: BeautifulSoup, url: str) -> Tuple[bool, str]:
    """
    Validate if the page is a legitimate Product Detail Page.
    Returns (is_valid, reason_if_invalid)
    """
    # Check if it's a category/listing page
    if _is_category_or_listing_page(soup, url):
        return False, "URL is a category/listing page, not a product page"
    
    # Check if product is unavailable
    is_unavailable, unavailable_reason = _is_product_unavailable(soup)
    if is_unavailable:
        return False, unavailable_reason or "Product is no longer available"
    
    # Check for essential PDP elements
    pdp_indicators = {
        "price_display": bool(soup.select_one("[data-test-id='PriceDisplay']")),
        "product_name": bool(soup.select_one("h1[data-rtl-id='listingHeaderNameHeading'], h1[data-test-id='ProductName']")),
        "media_carousel": bool(soup.select_one("[data-test-id='pdp-mt-thumbnails'], #MediaTrayCarouselWithThumbnailSidebar")),
        "add_to_cart": bool(soup.select_one("[data-test-id='AddToCartButton'], [class*='AddToCart']")),
        "product_details": bool(soup.select_one("[data-test-id='ProductDetails'], [class*='ProductDetails']")),
    }
    
    indicator_count = sum(pdp_indicators.values())
    
    # Need at least 2 PDP indicators for a valid page
    if indicator_count >= 2:
        return True, ""
    
    # If URL looks like a PDP (/pdp/) but lacks elements, product may be removed
    if "/pdp/" in url.lower() and indicator_count == 0:
        return False, "Product page structure not found - product may have been removed"
    
    # Accept with 1 indicator cautiously
    if indicator_count >= 1:
        return True, ""
    
    return False, "Page does not contain expected product detail elements"


def _create_invalid_result(url: str, reason: str) -> Dict:
    """
    Create a result dict for invalid/unavailable products.
    """
    return {
        "name": f"INVALID LINK - {reason}",
        "price": None,
        "in_stock": None,
        "description": None,
        "image_count": 0,
        "image_urls": [],
        "images": [],
        "folder": None,
        "url": url,
        "mode": "invalid",
        "is_valid": False,
        "invalid_reason": reason,
    }


# -----------------------------
# JSON-LD helpers
# -----------------------------
def _iter_jsonld(soup: BeautifulSoup):
    for tag in soup.select("script[type='application/ld+json']"):
        txt = tag.get_text(strip=False)
        if not txt:
            continue
        try:
            data = json.loads(txt)
            yield data
        except Exception:
            try:
                for part in re.split(r"\n(?=\s*{)", txt.strip()):
                    part = part.strip()
                    if part:
                        yield json.loads(part)
            except Exception:
                continue

def _jsonld_find_products(data) -> List[dict]:
    found = []
    stack = [data]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("@type") == "Product":
                found.append(cur)
            for v in cur.values():
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            for v in cur:
                if isinstance(v, (dict, list)):
                    stack.append(v)
    return found

def _jsonld_availability_from_offers(offers) -> Optional[bool]:
    if not offers:
        return None
    lst = offers if isinstance(offers, list) else [offers]
    for off in lst:
        if not isinstance(off, dict):
            continue
        avail = str(off.get("availability") or off.get("itemAvailability") or "")
        if re.search(r"InStock", avail, re.I):
            return True
        if re.search(r"OutOfStock|SoldOut|PreOrder", avail, re.I):
            return False
    return None

# -----------------------------
# Wayfair image URL normalization
# -----------------------------
def _wf_to_hires(u: str, size: int = 1600) -> str:
    """
    Normalize Wayfair CDN URLs to higher-res.
    """
    if not u:
        return u
    u = u.replace(" ", "%20")
    u = re.sub(r"/resize-h\d+-w\d+%5Ecompr-r\d+/", f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
    u = re.sub(r"/resize-h\d+-w\d+\^compr-r\d+/",  f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
    if "/resize-" not in u:
        u = re.sub(r"(https://assets\.wfcdn\.com/im/[^/]+/)",
                   rf"\1resize-h{size}-w{size}%5Ecompr-r85/", u)
    return u

def _img_dedup_key(u: str) -> str:
    """
    Extract the unique image identifier from Wayfair CDN URL.
    """
    m = re.search(r"/(\d{8,10})/[^/]+\.(jpg|jpeg|png|webp)", u, re.I)
    if m:
        return m.group(1)
    
    u = re.sub(r"/resize-h\d+-w\d+(?:%5E|\^)compr-r\d+/", "/", u)
    u = re.sub(r"/im/\d+/", "/im/X/", u)
    return re.sub(r"[?].*$", "", u)

# -----------------------------
# Core parsing from HTML
# -----------------------------
def _parse_name(soup: BeautifulSoup) -> str:
    h = soup.select_one("h1[data-rtl-id='listingHeaderNameHeading']")
    if h:
        t = _clean(h.get_text(" ", strip=True))
        if t:
            return t

    for data in _iter_jsonld(soup):
        for prod in _jsonld_find_products(data):
            nm = prod.get("name")
            if isinstance(nm, str) and nm.strip():
                return _clean(nm)

    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return _clean(og["content"])

    if soup.title and soup.title.string:
        return _clean(soup.title.string)

    return "N/A"

def _parse_price(soup: BeautifulSoup) -> str:
    price_host = soup.select_one("[data-test-id='PriceDisplay']")
    if price_host:
        txt = _clean(price_host.get_text(" ", strip=True))
        if txt:
            return txt

    # Look for price in product-specific containers only
    price_containers = soup.select("[data-test-id='ProductPrice'], .product-price, [class*='PriceBlock']")
    for container in price_containers:
        cand = container.find(string=re.compile(r"£\s?\d[\d,]*\.?\d{0,2}"))
        if cand:
            return _clean(cand)

    for data in _iter_jsonld(soup):
        for prod in _jsonld_find_products(data):
            offers = prod.get("offers")
            if isinstance(offers, dict):
                price = offers.get("price") or offers.get("lowPrice")
                cur = offers.get("priceCurrency", "")
                if price:
                    return f"{price} {cur}".strip()
            elif isinstance(offers, list):
                for o in offers:
                    if not isinstance(o, dict):
                        continue
                    price = o.get("price") or o.get("lowPrice")
                    cur = o.get("priceCurrency", "")
                    if price:
                        return f"{price} {cur}".strip()

    return "N/A"

def _parse_stock(soup: BeautifulSoup) -> Optional[bool]:
    oos_texts = [
        "Out of Stock",
        "Not available",
        "Sold Out",
    ]
    
    # Check in product-specific areas, not entire page
    product_area = soup.select_one("[data-test-id='ProductDetails'], main, #content") or soup
    page_text = product_area.get_text(" ", strip=True)
    
    for t in oos_texts:
        if re.search(rf"\b{re.escape(t)}\b", page_text, re.I):
            return False

    if re.search(r"\bAdd to (Cart|Basket)\b", page_text, re.I) and not re.search(r"Out of Stock|Not available", page_text, re.I):
        return True

    for data in _iter_jsonld(soup):
        for prod in _jsonld_find_products(data):
            avail = _jsonld_availability_from_offers(prod.get("offers"))
            if avail is not None:
                return avail

    return None

def _parse_description(soup: BeautifulSoup) -> str:
    def _clean_text(t: str) -> str:
        t = _html.unescape(t or "")
        t = t.replace("\r", "")
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()

    def _looks_generic(s: str) -> bool:
        return bool(re.search(r"you'?ll love .* at wayfair", s, re.I))

    for box in soup.select('[data-hb-id="BoxV3"]'):
        st = (box.get("style") or "").lower()
        if "pre-line" in st:
            txt = _clean_text(box.get_text("\n", strip=True))
            if txt and len(txt) > 120:
                return txt

    features = []
    for p in soup.select("p[data-hb-id='Text']"):
        if re.search(r"\bFeatures\b", p.get_text(" ", strip=True), re.I):
            nxt = p.find_next("ul")
            if nxt:
                items = [ _clean_text(li.get_text(" ", strip=True)) for li in nxt.select("li") ]
                items = [i for i in items if i]
                if items:
                    features.append("Features:\n- " + "\n- ".join(items))
            break

    best = ""
    for data in _iter_jsonld(soup):
        for prod in _jsonld_find_products(data):
            desc = prod.get("description")
            if isinstance(desc, str):
                cand = _clean_text(desc)
                if cand and not _looks_generic(cand) and len(cand) > len(best):
                    best = cand
    if best:
        if features:
            return best + "\n\n" + "\n\n".join(features)
        return best

    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        cand = _clean_text(md["content"])
        if cand and not _looks_generic(cand):
            if features:
                return cand + "\n\n" + "\n\n".join(features)
            return cand

    if features:
        return "\n\n".join(features)

    return "N/A"

def _parse_images(soup: BeautifulSoup) -> List[str]:
    """
    Extract unique product images from Wayfair PDP.
    """
    from typing import Tuple
    ordered: List[Tuple[int, str]] = []
    seen_ids: set[str] = set()

    for btn in soup.select("[data-test-id='pdp-mt-thumbnails'] button[aria-label]"):
        lab = btn.get("aria-label") or ""
        m = re.search(r"(\d+)\s+of\s+(\d+)", lab, re.I)
        if not m:
            continue
        order = int(m.group(1))
        
        img = btn.find("img")
        if not img:
            continue
            
        src = None
        srcset = img.get("srcset") or ""
        if srcset:
            parts = [p.strip().split()[0] for p in srcset.split(",") if p.strip()]
            if parts:
                src = parts[-1]
        
        if not src:
            src = img.get("src") or ""
        
        if not src:
            continue
        
        img_id = _img_dedup_key(src)
        if img_id in seen_ids:
            continue
        seen_ids.add(img_id)
        
        ordered.append((order, src))

    ordered.sort(key=lambda t: t[0])
    
    images: List[str] = []
    for _, u in ordered:
        hu = _wf_to_hires(u, size=1600)
        images.append(hu)
    
    if not images:
        for img in soup.select("#MediaTrayCarouselWithThumbnailSidebar img, [data-test-id='pdp-mt-d-mainImageCarousel'] img"):
            src = img.get("src") or img.get("data-src") or ""
            if src and "assets.wfcdn.com/im/" in src:
                img_id = _img_dedup_key(src)
                if img_id not in seen_ids:
                    seen_ids.add(img_id)
                    images.append(_wf_to_hires(src, size=1600))
    
    return images

# -----------------------------
# Downloader — JPG only + unique names
# -----------------------------
def _download_images_jpg(urls: List[str], referer: str, folder: Path, base_slug: str) -> List[str]:
    """
    Downloads all images and writes JPG only, with deterministic unique names.
    """
    folder.mkdir(parents=True, exist_ok=True)
    out: List[str] = []
    sess = _session_with_retries()
    sess.headers.update({
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG_GB,
        "Referer": referer,
    })
    for i, u in enumerate(urls, 1):
        try:
            r = sess.get(u, timeout=30)
            if not r.ok or not r.content:
                continue

            im = Image.open(io.BytesIO(r.content))
            if im.mode in ("RGBA", "P"):
                im = im.convert("RGB")
            elif im.mode != "RGB":
                im = im.convert("RGB")

            path = folder / f"{base_slug}_{i:02d}.jpg"
            im.save(path, format="JPEG", quality=92, optimize=True)
            out.append(str(path))
        except Exception:
            continue
    return out

# -----------------------------
# Public API
# -----------------------------
def scrape_wayfair_product(url: str, save_dir: Path | None = None, *, geo="United Kingdom", verbose: bool = True) -> dict:
    """
    Fetch Wayfair PDP via Oxylabs and return parsed data + downloaded JPG images.
    Validates that the URL is a legitimate product page.
    Returns invalid result for category/listing pages or unavailable products.
    """
    if save_dir is None:
        save_dir = SAVE_DIR
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    
    # Ensure debug dir exists
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    accept_lang = ACCEPT_LANG_GB
    
    try:
        html_doc, final_url = oxy_fetch_html(url, geo=geo, accept_lang=accept_lang, timeout=90)
    except Exception as e:
        if verbose:
            print(f"Failed to fetch URL: {e}")
        return _create_invalid_result(url, f"Failed to fetch page: {str(e)}")

    soup = BeautifulSoup(html_doc, "lxml")
    
    # Save HTML for debugging if needed
    if verbose:
        debug_file = DEBUG_DIR / f"wayfair_debug_{_short_uid(url)}.html"
        try:
            debug_file.write_text(html_doc, encoding="utf-8")
            print(f"Debug HTML saved to: {debug_file}")
        except Exception:
            pass

    # ========== VALIDATION CHECK ==========
    is_valid, invalid_reason = _is_valid_pdp(soup, url)
    if not is_valid:
        if verbose:
            print(f"⚠ Invalid page detected: {invalid_reason}")
        return _create_invalid_result(url, invalid_reason)
    # ======================================

    name = _parse_name(soup)
    price = _parse_price(soup)
    in_stock = _parse_stock(soup)
    description = _parse_description(soup)

    # Post-extraction validation
    if name == "N/A" and price == "N/A" and description == "N/A":
        if verbose:
            print("⚠ Could not extract any product data")
        return _create_invalid_result(url, "Could not extract product information")

    name_slug = _safe_name(name)
    uid = _short_uid(final_url)
    base_slug = f"{name_slug}_{uid}"

    images = _parse_images(soup)
    folder = save_dir / base_slug
    downloaded = _download_images_jpg(images, referer=final_url, folder=folder, base_slug=base_slug)

    return {
        "name": name,
        "price": price,
        "in_stock": in_stock,
        "description": description,
        "image_count": len(downloaded),
        "image_urls": images,
        "images": downloaded,
        "folder": str(folder),
        "url": final_url,
        "mode": "oxylabs(html)+direct(images_jpg_only)",
        "is_valid": True,
        "invalid_reason": None,
    }

# # -----------------------------
# # CLI test
# # -----------------------------
# if __name__ == "__main__":
#     import sys
    
#     # Test URLs
#     TEST_URLS = [
#         # Category URL (should be invalid)
#         # "https://www.wayfair.co.uk/kitchenware-tableware/sb0/mixers-attachments-c1804929.html",
#         # Valid product URL
#         "https://www.wayfair.co.uk/kitchenware-tableware/pdp/laura-ashley-vq-laura-ashley-jug-kettle-china-rose-laas1109.html",
#     ]
    
#     # Allow passing URL as command line argument
#     if len(sys.argv) > 1:
#         TEST_URLS = [sys.argv[1]]
    
#     for test_url in TEST_URLS:
#         print(f"\nTesting: {test_url}")
#         print("=" * 70)
#         data = scrape_wayfair_product(test_url, verbose=True)
#         print(json.dumps(data, indent=2, ensure_ascii=False))
#         print()