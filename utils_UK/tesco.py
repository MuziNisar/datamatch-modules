
# # tesco_oxylabs.py (fixed)
# # Python 3.9+
# # pip install requests beautifulsoup4 lxml pillow

# from __future__ import annotations
# import os, re, html, io, json, hashlib, time
# from pathlib import Path
# from typing import List, Optional, Dict, Any, Tuple
# from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, urldefrag

# import requests
# from bs4 import BeautifulSoup
# from requests.adapters import HTTPAdapter
# from urllib3.util.retry import Retry
# from PIL import Image

# # ---------------------------
# # Credentials
# # ---------------------------
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS  # create this file or set env
# except Exception:
#     OXY_USER = os.getenv("OXY_USER") or os.getenv("OXYLABS_USERNAME", "")
#     OXY_PASS = os.getenv("OXY_PASS") or os.getenv("OXYLABS_PASSWORD", "")

# if not (OXY_USER and OXY_PASS):
#     raise RuntimeError("Oxylabs credentials missing: set OXY_USER/OXY_PASS env or create oxylabs_secrets.py")

# # ---------------------------
# # Paths / headers
# # ---------------------------
# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()

# SAVE_DIR = BASE_DIR / "data1"
# SAVE_DIR.mkdir(parents=True, exist_ok=True)

# UA_STR = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#     "AppleWebKit/537.36 (KHTML, like Gecko) "
#     "Chrome/128.0.0.0 Safari/537.36"
# )
# ACCEPT_LANG = "en-GB,en;q=0.9"

# # ---------------------------
# # Helpers
# # ---------------------------
# def _clean(s: str) -> str:
#     s = html.unescape(s or "")
#     s = s.replace("\r", "")
#     s = re.sub(r"[ \t]+", " ", s)
#     s = re.sub(r"\n{3,}", "\n\n", s)
#     return s.strip()

# def _safe_name(name: str) -> str:
#     n = re.sub(r"[^\w\s-]", "", name or "").strip().replace(" ", "_")
#     return n or "NA"

# def _retailer_slug(u: str) -> str:
#     host = urlsplit(u).netloc.lower()
#     host = re.sub(r"^www\.", "", host)
#     return (host.split(".")[0] or "site")

# def _stable_id_from_url(u: str) -> str:
#     m = re.search(r"(\d{8,})", u)
#     return m.group(1) if m else hashlib.sha1(u.encode("utf-8")).hexdigest()[:8]

# def _abs(u: str) -> str:
#     return "https:" + u if (u and u.startswith("//")) else u

# def _drop_query(u: str) -> str:
#     parts = list(urlsplit(u))
#     parts[3] = ""  # query
#     parts[4] = ""  # fragment
#     return urlunsplit(parts)

# def _img_1600(u: str) -> str:
#     parts = list(urlsplit(u))
#     q = dict(parse_qsl(parts[3], keep_blank_values=True))
#     q["h"] = q.get("h") or "1600"
#     q["w"] = q.get("w") or "1600"
#     parts[3] = urlencode(q)
#     return urlunsplit(parts)

# def _session_with_retries(total=3, backoff=0.7) -> requests.Session:
#     s = requests.Session()
#     retry = Retry(
#         total=total, connect=total, read=total,
#         backoff_factor=backoff,
#         status_forcelist=(429, 500, 502, 503, 504),
#         allowed_methods=frozenset(["GET", "POST", "HEAD"])
#     )
#     adapter = HTTPAdapter(max_retries=retry, pool_maxsize=20)
#     s.mount("http://", adapter)
#     s.mount("https://", adapter)
#     return s

# def _bytes_to_jpg(content: bytes) -> bytes:
#     with Image.open(io.BytesIO(content)) as im:
#         im = im.convert("RGB")
#         out = io.BytesIO()
#         im.save(out, format="JPEG", quality=90, optimize=True)
#         return out.getvalue()

# # ---------------------------
# # Oxylabs HTML fetch
# # ---------------------------
# def oxy_fetch_html(url: str, geo: str = "United Kingdom", timeout: int = 90) -> str:
#     url, _ = urldefrag(url)
#     payload = {
#         "source": "universal",
#         "url": url,
#         "render": "html",
#         "geo_location": geo,
#         "headers": {"User-Agent": UA_STR, "Accept-Language": ACCEPT_LANG},
#     }
#     sess = _session_with_retries()
#     last = None
#     for i in range(3):
#         try:
#             r = sess.post(
#                 "https://realtime.oxylabs.io/v1/queries",
#                 auth=(OXY_USER, OXY_PASS),
#                 json=payload,
#                 timeout=timeout,
#             )
#             r.raise_for_status()
#             data = r.json()
#             html_content = (data.get("results") or [{}])[0].get("content", "")
#             if "<html" not in html_content.lower():
#                 raise RuntimeError("Oxylabs returned non-HTML content")
#             return html_content
#         except Exception as e:
#             last = e
#             time.sleep(1.5 ** (i + 1))
#     raise RuntimeError(f"Oxylabs HTML fetch failed: {last}")

# # ---------------------------
# # Tesco: Apollo/GraphQL extractor
# # ---------------------------
# def _extract_apollo_product(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
#     """
#     Tesco PDP ships a big JSON with key: 'mfe-orchestrator' -> props -> apolloCache.
#     We scan all <script> tags, load JSON, and pull the first 'ProductType:*' node.
#     """
#     def _pick_product(cache: Dict[str, Any]) -> Optional[Dict[str, Any]]:
#         # Prefer the __ref from ROOT_QUERY.product(...) when present
#         root = cache.get("ROOT_QUERY", {})
#         for k, v in root.items():
#             if k.startswith("product(") and isinstance(v, dict) and "__ref" in v:
#                 prod = cache.get(v["__ref"])
#                 if isinstance(prod, dict) and prod.get("__typename") == "ProductType":
#                     return prod
#         # Fallback: first ProductType:* entry
#         for k, v in cache.items():
#             if k.startswith("ProductType:") and isinstance(v, dict) and v.get("__typename") == "ProductType":
#                 return v
#         return None

#     scripts = soup.find_all("script")
#     for sc in scripts:
#         raw = (sc.string or sc.text or "").strip()
#         if not raw:
#             continue
#         # Quick filter to skip huge non-JSON blocks early
#         if '"mfe-orchestrator"' not in raw and '"apolloCache"' not in raw and '"ProductType:' not in raw:
#             continue
#         try:
#             data = json.loads(raw)
#         except Exception:
#             continue
#         # Walk a few possible shapes
#         candidates = []
#         if isinstance(data, dict):
#             # plain orchestrator shape
#             mo = data.get("mfe-orchestrator", {})
#             props = (mo if isinstance(mo, dict) else {}).get("props", {})
#             cache = (props if isinstance(props, dict) else {}).get("apolloCache", {})
#             if isinstance(cache, dict) and cache:
#                 prod = _pick_product(cache)
#                 if prod:
#                     return prod
#             # sometimes apolloCache is top-level
#             if "apolloCache" in data and isinstance(data["apolloCache"], dict):
#                 prod = _pick_product(data["apolloCache"])
#                 if prod:
#                     return prod
#     return None

# # ---------------------------
# # JSON-LD helpers
# # ---------------------------
# def _jsonld_products_from_soup(soup: BeautifulSoup) -> List[Dict[str, Any]]:
#     out: List[Dict[str, Any]] = []
#     for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
#         raw = tag.string or tag.text or ""
#         if not raw:
#             continue
#         try:
#             data = json.loads(raw)
#         except Exception:
#             continue
#         objs = data if isinstance(data, list) else [data]
#         for o in objs:
#             if isinstance(o, dict) and o.get("@type") == "Product":
#                 out.append(o)
#     return out

# # ---------------------------
# # Parsing Tesco PDP (now prefers Apollo)
# # ---------------------------
# def parse_tesco(html: str) -> Dict[str, Any]:
#     soup = BeautifulSoup(html, "lxml")
#     ap = _extract_apollo_product(soup)

#     name = "N/A"
#     price = "N/A"
#     in_stock: Optional[bool] = None
#     description = "N/A"
#     seller = ""
#     img_urls: List[str] = []

#     if ap:
#         # --- name / brand ---
#         name = _clean(ap.get("title") or "") or "N/A"
#         brand = _clean(ap.get("brandName") or "")
#         if brand:
#             seller = brand  # prefer brand when marketplace seller is not explicit

#         # --- price ---
#         try:
#             p = ap.get("price", {})
#             if isinstance(p, dict) and p.get("actual") is not None:
#                 price = f"£{float(p['actual']):.2f}"
#         except Exception:
#             pass

#         # --- stock ---
#         status = (ap.get("status") or "").lower()
#         is_for_sale = ap.get("isForSale")
#         if isinstance(is_for_sale, bool):
#             in_stock = is_for_sale
#         elif status:
#             in_stock = ("available" in status) and ("unavailable" not in status)

#         # --- description ---
#         det = ap.get("details") or {}
#         # prefer productMarketing (paragraphs) then features (bullets)
#         pm = det.get("productMarketing") or []
#         if isinstance(pm, list) and pm:
#             desc = " ".join(_clean(x) for x in pm if isinstance(x, str))
#             if len(desc) > 40:
#                 description = desc
#         if description == "N/A":
#             feats = det.get("features") or []
#             if isinstance(feats, list) and feats:
#                 description = "; ".join(_clean(x) for x in feats if isinstance(x, str))

#         # --- images ---
#         imgs = ap.get("images") or {}
#         disp = imgs.get("display") or []
#         for entry in disp:
#             try:
#                 z = (entry.get("zoom") or {}).get("url") \
#                     or (entry.get("default") or {}).get("url")
#                 if z:
#                     u = _img_1600(_abs(z))
#                     base = _drop_query(u)
#                     if base not in { _drop_query(x) for x in img_urls }:
#                         img_urls.append(u)
#             except Exception:
#                 pass
#         # fallback to media.defaultImage
#         if not img_urls:
#             media = ap.get("media") or {}
#             di = (media.get("defaultImage") or {}).get("url")
#             if di:
#                 img_urls.append(_img_1600(_abs(di)))

#     # --------- Fallbacks from DOM/JSON-LD if Apollo missing bits ---------
#     if name == "N/A":
#         el = soup.select_one('[data-auto="pdp-product-title"]') or soup.select_one("h1")
#         if el:
#             name = _clean(el.get_text(" ", strip=True))
#     if price == "N/A":
#         pr = soup.select_one("p[class*='priceText']")
#         if pr:
#             price = _clean(pr.get_text(" ", strip=True))
#     if description == "N/A":
#         # try "Description" sibling
#         try:
#             h3 = soup.find(lambda t: t.name == "h3" and re.search(r"^\s*Description\s*$", t.get_text(), re.I))
#             if h3:
#                 sib = h3.find_next_sibling()
#                 if sib:
#                     desc_txt = _clean(sib.get_text(" ", strip=True))
#                     if len(desc_txt) > 40:
#                         description = desc_txt
#         except Exception:
#             pass
#     # JSON-LD last resort
#     if price == "N/A" or description == "N/A" or not img_urls:
#         for o in _jsonld_products_from_soup(soup):
#             if name == "N/A" and o.get("name"):
#                 name = _clean(o["name"])
#             if price == "N/A":
#                 offers = o.get("offers")
#                 if isinstance(offers, dict) and offers.get("price"):
#                     price = f"£{offers['price']}"
#             if description == "N/A" and isinstance(o.get("description"), str):
#                 cand = _clean(o["description"])
#                 if len(cand) > 40:
#                     description = cand
#             if not img_urls:
#                 imgs = o.get("image")
#                 if imgs:
#                     if isinstance(imgs, str):
#                         imgs = [imgs]
#                     img_urls = [_img_1600(_abs(u)) for u in imgs]

#     # --- robust stock fix ---
#     # Do NOT match message templates like "This product’s currently out of stock" in JSON.
#     if in_stock is None:
#         add_btn = soup.select_one('[data-auto="ddsweb-quantity-controls-add-button"]')
#         in_stock = bool(add_btn)

#     # seller: keep brand; avoid scanning generic strings to dodge giant blobs
#     # If marketplace UI exposes a visible seller element later, we can add a very specific selector there.

#     return {
#         "name": name or "N/A",
#         "price": price or "N/A",
#         "in_stock": in_stock,
#         "description": description or "N/A",
#         "seller": seller,
#         "image_urls": img_urls,
#     }

# # ---------------------------
# # Image download (direct)
# # ---------------------------
# def download_images(urls: List[str], folder: Path, referer: str,
#                     max_images: Optional[int] = None,
#                     force_jpg: bool = False) -> List[str]:
#     if not urls:
#         return []
#     if max_images is not None:
#         urls = urls[:max_images]
#     folder.mkdir(parents=True, exist_ok=True)

#     sess = _session_with_retries()
#     sess.headers.update({
#         "User-Agent": UA_STR,
#         "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#         "Accept-Language": ACCEPT_LANG,
#         "Referer": referer,
#     })

#     saved, seen_hashes = [], set()
#     for i, u in enumerate(urls, 1):
#         try:
#             r = sess.get(u, timeout=30, stream=True)
#             r.raise_for_status()
#             content = r.content or b""
#             if len(content) < 1500:
#                 continue
#             h = hashlib.md5(content).hexdigest()
#             if h in seen_hashes:
#                 continue
#             seen_hashes.add(h)

#             if force_jpg:
#                 out = folder / f"image_{i:02d}.jpg"
#                 out.write_bytes(_bytes_to_jpg(content))
#                 saved.append(str(out))
#             else:
#                 ct = (r.headers.get("Content-Type") or "").lower()
#                 ext = ".jpg"
#                 ul = u.lower()
#                 if "webp" in ct or ul.endswith(".webp"): ext = ".webp"
#                 elif "png" in ct or ul.endswith(".png"): ext = ".png"
#                 elif ul.endswith(".jpeg"): ext = ".jpeg"
#                 out = folder / f"image_{i:02d}{ext}"
#                 with open(out, "wb") as f:
#                     for chunk in r.iter_content(65536):
#                         if chunk:
#                             f.write(chunk)
#                 saved.append(str(out))
#         except Exception as e:
#             print(f"  ! image error: {u} ({e})")

#     return saved

# # ---------------------------
# # Public API
# # ---------------------------
# def scrape_tesco_product_with_oxylabs(url: str,
#                                       *,
#                                       download_images_flag: bool = True,
#                                       max_images: Optional[int] = None,
#                                       force_jpg: bool = False,
#                                       geo: str = "United Kingdom") -> Dict[str, Any]:
#     html = oxy_fetch_html(url, geo=geo)
#     parsed = parse_tesco(html)

#     folder = SAVE_DIR / f"{_retailer_slug(url)}_{_safe_name(parsed['name'] if parsed['name'] != 'N/A' else 'Tesco_Product')}_{_stable_id_from_url(url)}"

#     images_downloaded: List[str] = []
#     if download_images_flag and parsed["image_urls"]:
#         images_downloaded = download_images(parsed["image_urls"], folder, referer=url,
#                                             max_images=max_images, force_jpg=force_jpg)

#     return {
#         "name": parsed["name"],
#         "price": parsed["price"],
#         "in_stock": parsed["in_stock"],
#         "description": parsed["description"],
#         "seller": parsed["seller"],
#         "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
#         "images": images_downloaded if images_downloaded else parsed["image_urls"],
#         "folder": str(folder),
#         "url": url,
#         "mode": "oxylabs(html)+direct(images)"
#     }

# # # ---------------------------
# # # CLI
# # # ---------------------------
# # if __name__ == "__main__":
# #     TEST_URL = "https://www.tesco.com/groceries/en-GB/products/311757809"
# #     print(json.dumps(
# #         scrape_tesco_product_with_oxylabs(
# #             TEST_URL,
# #             download_images_flag=True,
# #             max_images=12,
# #             force_jpg=True,
# #             geo="United Kingdom"
# #         ),
# #         indent=2, ensure_ascii=False
# #     ))



# tesco_oxylabs.py (fixed)
# Python 3.9+
# Version: 2.1 - Added invalid link detection (404, error pages)
# pip install requests beautifulsoup4 lxml pillow

from __future__ import annotations
import os, re, html, io, json, hashlib, time
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, urldefrag

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from PIL import Image

__version__ = "2.1"

# ---------------------------
# Credentials
# ---------------------------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS  # create this file or set env
except Exception:
    OXY_USER = os.getenv("OXY_USER") or os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXY_PASS") or os.getenv("OXYLABS_PASSWORD", "")

if not (OXY_USER and OXY_PASS):
    raise RuntimeError("Oxylabs credentials missing: set OXY_USER/OXY_PASS env or create oxylabs_secrets.py")

# ---------------------------
# Paths / headers
# ---------------------------
try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()

SAVE_DIR = BASE_DIR / "data1"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

UA_STR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
ACCEPT_LANG = "en-GB,en;q=0.9"

# ---------------------------
# Helpers
# ---------------------------
def _clean(s: str) -> str:
    s = html.unescape(s or "")
    s = s.replace("\r", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _safe_name(name: str) -> str:
    n = re.sub(r"[^\w\s-]", "", name or "").strip().replace(" ", "_")
    return n or "NA"

def _retailer_slug(u: str) -> str:
    host = urlsplit(u).netloc.lower()
    host = re.sub(r"^www\.", "", host)
    return (host.split(".")[0] or "site")

def _stable_id_from_url(u: str) -> str:
    m = re.search(r"(\d{8,})", u)
    return m.group(1) if m else hashlib.sha1(u.encode("utf-8")).hexdigest()[:8]

def _abs(u: str) -> str:
    return "https:" + u if (u and u.startswith("//")) else u

def _drop_query(u: str) -> str:
    parts = list(urlsplit(u))
    parts[3] = ""  # query
    parts[4] = ""  # fragment
    return urlunsplit(parts)

def _img_1600(u: str) -> str:
    parts = list(urlsplit(u))
    q = dict(parse_qsl(parts[3], keep_blank_values=True))
    q["h"] = q.get("h") or "1600"
    q["w"] = q.get("w") or "1600"
    parts[3] = urlencode(q)
    return urlunsplit(parts)

def _session_with_retries(total=3, backoff=0.7) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=total, connect=total, read=total,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST", "HEAD"])
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=20)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

def _bytes_to_jpg(content: bytes) -> bytes:
    with Image.open(io.BytesIO(content)) as im:
        im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=90, optimize=True)
        return out.getvalue()

# ---------------------------
# Oxylabs HTML fetch
# ---------------------------
def oxy_fetch_html(url: str, geo: str = "United Kingdom", timeout: int = 90) -> str:
    url, _ = urldefrag(url)
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
        "geo_location": geo,
        "headers": {"User-Agent": UA_STR, "Accept-Language": ACCEPT_LANG},
    }
    sess = _session_with_retries()
    last = None
    for i in range(3):
        try:
            r = sess.post(
                "https://realtime.oxylabs.io/v1/queries",
                auth=(OXY_USER, OXY_PASS),
                json=payload,
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json()
            html_content = (data.get("results") or [{}])[0].get("content", "")
            if "<html" not in html_content.lower():
                raise RuntimeError("Oxylabs returned non-HTML content")
            return html_content
        except Exception as e:
            last = e
            time.sleep(1.5 ** (i + 1))
    raise RuntimeError(f"Oxylabs HTML fetch failed: {last}")

# ---------------------------
# Invalid Link Detection
# ---------------------------
def _detect_invalid_page(soup: BeautifulSoup, page_url: str) -> Tuple[bool, str]:
    """
    Detect if the page is invalid (404, error, listing page, etc.)
    Returns: (is_invalid: bool, reason: str)
    
    Detection priority:
    1. Tesco-specific error page: "Not down this aisle"
    2. Generic error text patterns
    3. Missing essential PDP elements
    """
    
    # ============================================================
    # 1. Tesco-specific error page: "Not down this aisle"
    # ============================================================
    # Check for error container with specific heading
    error_container = soup.select_one(".M90PRG_container, [class*='error'], [class*='Error']")
    if error_container:
        error_text = error_container.get_text(" ", strip=True).lower()
        if any(phrase in error_text for phrase in [
            "not down this aisle",
            "page is missing",
            "page not found",
            "can't find",
            "cannot find",
        ]):
            return True, "error_page:tesco_not_found"
    
    # Check h1 for error messages
    h1 = soup.select_one("h1")
    if h1:
        h1_text = _clean(h1.get_text()).lower()
        if any(phrase in h1_text for phrase in [
            "not down this aisle",
            "page not found",
            "sorry",
            "oops",
            "error",
        ]):
            return True, "error_page:h1_error"
    
    # ============================================================
    # 2. Check for generic error text patterns in body
    # ============================================================
    body_text = soup.get_text(" ", strip=True).lower() if soup.body else ""
    error_patterns = [
        r"not down this aisle",
        r"that page is missing",
        r"page (has been|was) (removed|deleted)",
        r"product (is )?no longer available",
        r"item (is )?no longer available",
        r"we couldn'?t find (that|this) page",
        r"sorry,?\s*(this|the) page (doesn'?t|does not) exist",
        r"404\s*-?\s*(page)?\s*not found",
    ]
    for pattern in error_patterns:
        if re.search(pattern, body_text):
            return True, "error_page:pattern_match"
    
    # ============================================================
    # 3. Check if it's a listing/category page (not a PDP)
    # ============================================================
    # Tesco product listing indicators
    product_tiles = soup.select("[data-auto='product-tile'], .product-list-item, .product-tile")
    if len(product_tiles) >= 4:
        return True, f"listing_page:{len(product_tiles)}_product_tiles"
    
    # ============================================================
    # 4. Check for essential PDP elements (positive validation)
    # ============================================================
    has_product_title = bool(soup.select_one('[data-auto="pdp-product-title"], h1'))
    has_price = bool(soup.select_one("p[class*='priceText'], [data-auto*='price']"))
    has_add_button = bool(soup.select_one('[data-auto="ddsweb-quantity-controls-add-button"]'))
    has_product_image = bool(soup.select_one('[data-auto="product-image"], img[class*="product"]'))
    
    # Check for Apollo/GraphQL product data
    has_apollo_product = False
    for script in soup.find_all("script"):
        raw = (script.string or script.text or "").strip()
        if '"ProductType:' in raw or '"apolloCache"' in raw:
            has_apollo_product = True
            break
    
    # Check JSON-LD for Product schema
    has_jsonld_product = False
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.text or "")
            objs = data if isinstance(data, list) else [data]
            for obj in objs:
                if isinstance(obj, dict) and obj.get("@type") == "Product":
                    has_jsonld_product = True
                    break
        except Exception:
            continue
    
    # If Apollo product data or JSON-LD Product exists, it's valid
    if has_apollo_product or has_jsonld_product:
        return False, ""
    
    # If we have add button, it's a valid PDP
    if has_add_button:
        return False, ""
    
    # If missing most PDP elements, likely invalid
    pdp_score = sum([has_product_title, has_price, has_product_image])
    if pdp_score < 2:
        return True, f"missing_pdp_elements:score_{pdp_score}/3"
    
    return False, ""

# ---------------------------
# Tesco: Apollo/GraphQL extractor
# ---------------------------
def _extract_apollo_product(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
    """
    Tesco PDP ships a big JSON with key: 'mfe-orchestrator' -> props -> apolloCache.
    We scan all <script> tags, load JSON, and pull the first 'ProductType:*' node.
    """
    def _pick_product(cache: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Prefer the __ref from ROOT_QUERY.product(...) when present
        root = cache.get("ROOT_QUERY", {})
        for k, v in root.items():
            if k.startswith("product(") and isinstance(v, dict) and "__ref" in v:
                prod = cache.get(v["__ref"])
                if isinstance(prod, dict) and prod.get("__typename") == "ProductType":
                    return prod
        # Fallback: first ProductType:* entry
        for k, v in cache.items():
            if k.startswith("ProductType:") and isinstance(v, dict) and v.get("__typename") == "ProductType":
                return v
        return None

    scripts = soup.find_all("script")
    for sc in scripts:
        raw = (sc.string or sc.text or "").strip()
        if not raw:
            continue
        # Quick filter to skip huge non-JSON blocks early
        if '"mfe-orchestrator"' not in raw and '"apolloCache"' not in raw and '"ProductType:' not in raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        # Walk a few possible shapes
        candidates = []
        if isinstance(data, dict):
            # plain orchestrator shape
            mo = data.get("mfe-orchestrator", {})
            props = (mo if isinstance(mo, dict) else {}).get("props", {})
            cache = (props if isinstance(props, dict) else {}).get("apolloCache", {})
            if isinstance(cache, dict) and cache:
                prod = _pick_product(cache)
                if prod:
                    return prod
            # sometimes apolloCache is top-level
            if "apolloCache" in data and isinstance(data["apolloCache"], dict):
                prod = _pick_product(data["apolloCache"])
                if prod:
                    return prod
    return None

# ---------------------------
# JSON-LD helpers
# ---------------------------
def _jsonld_products_from_soup(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.text or ""
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for o in objs:
            if isinstance(o, dict) and o.get("@type") == "Product":
                out.append(o)
    return out

# ---------------------------
# Parsing Tesco PDP (now prefers Apollo)
# ---------------------------
def parse_tesco(html_content: str, page_url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html_content, "lxml")
    
    # ============================================================
    # INVALID LINK DETECTION - CHECK FIRST
    # ============================================================
    is_invalid, invalid_reason = _detect_invalid_page(soup, page_url)
    if is_invalid:
        # Determine display name based on invalid reason
        if "error_page" in invalid_reason:
            display_name = "Invalid Link"
        else:
            display_name = "Product not available"
        
        return {
            "name": display_name,
            "price": "N/A",
            "in_stock": False,
            "description": "N/A",
            "seller": "",
            "image_urls": [],
            "is_invalid": True,
            "invalid_reason": invalid_reason,
        }
    
    ap = _extract_apollo_product(soup)

    name = "N/A"
    price = "N/A"
    in_stock: Optional[bool] = None
    description = "N/A"
    seller = ""
    img_urls: List[str] = []

    if ap:
        # --- name / brand ---
        name = _clean(ap.get("title") or "") or "N/A"
        brand = _clean(ap.get("brandName") or "")
        if brand:
            seller = brand  # prefer brand when marketplace seller is not explicit

        # --- price ---
        try:
            p = ap.get("price", {})
            if isinstance(p, dict) and p.get("actual") is not None:
                price = f"£{float(p['actual']):.2f}"
        except Exception:
            pass

        # --- stock ---
        status = (ap.get("status") or "").lower()
        is_for_sale = ap.get("isForSale")
        if isinstance(is_for_sale, bool):
            in_stock = is_for_sale
        elif status:
            in_stock = ("available" in status) and ("unavailable" not in status)

        # --- description ---
        det = ap.get("details") or {}
        # prefer productMarketing (paragraphs) then features (bullets)
        pm = det.get("productMarketing") or []
        if isinstance(pm, list) and pm:
            desc = " ".join(_clean(x) for x in pm if isinstance(x, str))
            if len(desc) > 40:
                description = desc
        if description == "N/A":
            feats = det.get("features") or []
            if isinstance(feats, list) and feats:
                description = "; ".join(_clean(x) for x in feats if isinstance(x, str))

        # --- images ---
        imgs = ap.get("images") or {}
        disp = imgs.get("display") or []
        for entry in disp:
            try:
                z = (entry.get("zoom") or {}).get("url") \
                    or (entry.get("default") or {}).get("url")
                if z:
                    u = _img_1600(_abs(z))
                    base = _drop_query(u)
                    if base not in { _drop_query(x) for x in img_urls }:
                        img_urls.append(u)
            except Exception:
                pass
        # fallback to media.defaultImage
        if not img_urls:
            media = ap.get("media") or {}
            di = (media.get("defaultImage") or {}).get("url")
            if di:
                img_urls.append(_img_1600(_abs(di)))

    # --------- Fallbacks from DOM/JSON-LD if Apollo missing bits ---------
    if name == "N/A":
        el = soup.select_one('[data-auto="pdp-product-title"]') or soup.select_one("h1")
        if el:
            name = _clean(el.get_text(" ", strip=True))
    if price == "N/A":
        pr = soup.select_one("p[class*='priceText']")
        if pr:
            price = _clean(pr.get_text(" ", strip=True))
    if description == "N/A":
        # try "Description" sibling
        try:
            h3 = soup.find(lambda t: t.name == "h3" and re.search(r"^\s*Description\s*$", t.get_text(), re.I))
            if h3:
                sib = h3.find_next_sibling()
                if sib:
                    desc_txt = _clean(sib.get_text(" ", strip=True))
                    if len(desc_txt) > 40:
                        description = desc_txt
        except Exception:
            pass
    # JSON-LD last resort
    if price == "N/A" or description == "N/A" or not img_urls:
        for o in _jsonld_products_from_soup(soup):
            if name == "N/A" and o.get("name"):
                name = _clean(o["name"])
            if price == "N/A":
                offers = o.get("offers")
                if isinstance(offers, dict) and offers.get("price"):
                    price = f"£{offers['price']}"
            if description == "N/A" and isinstance(o.get("description"), str):
                cand = _clean(o["description"])
                if len(cand) > 40:
                    description = cand
            if not img_urls:
                imgs = o.get("image")
                if imgs:
                    if isinstance(imgs, str):
                        imgs = [imgs]
                    img_urls = [_img_1600(_abs(u)) for u in imgs]

    # --- robust stock fix ---
    # Do NOT match message templates like "This product's currently out of stock" in JSON.
    if in_stock is None:
        add_btn = soup.select_one('[data-auto="ddsweb-quantity-controls-add-button"]')
        in_stock = bool(add_btn)

    # seller: keep brand; avoid scanning generic strings to dodge giant blobs
    # If marketplace UI exposes a visible seller element later, we can add a very specific selector there.

    return {
        "name": name or "N/A",
        "price": price or "N/A",
        "in_stock": in_stock,
        "description": description or "N/A",
        "seller": seller,
        "image_urls": img_urls,
        "is_invalid": False,
        "invalid_reason": "",
    }

# ---------------------------
# Image download (direct)
# ---------------------------
def download_images(urls: List[str], folder: Path, referer: str,
                    max_images: Optional[int] = None,
                    force_jpg: bool = False) -> List[str]:
    if not urls:
        return []
    if max_images is not None:
        urls = urls[:max_images]
    folder.mkdir(parents=True, exist_ok=True)

    sess = _session_with_retries()
    sess.headers.update({
        "User-Agent": UA_STR,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Referer": referer,
    })

    saved, seen_hashes = [], set()
    for i, u in enumerate(urls, 1):
        try:
            r = sess.get(u, timeout=30, stream=True)
            r.raise_for_status()
            content = r.content or b""
            if len(content) < 1500:
                continue
            h = hashlib.md5(content).hexdigest()
            if h in seen_hashes:
                continue
            seen_hashes.add(h)

            if force_jpg:
                out = folder / f"image_{i:02d}.jpg"
                out.write_bytes(_bytes_to_jpg(content))
                saved.append(str(out))
            else:
                ct = (r.headers.get("Content-Type") or "").lower()
                ext = ".jpg"
                ul = u.lower()
                if "webp" in ct or ul.endswith(".webp"): ext = ".webp"
                elif "png" in ct or ul.endswith(".png"): ext = ".png"
                elif ul.endswith(".jpeg"): ext = ".jpeg"
                out = folder / f"image_{i:02d}{ext}"
                with open(out, "wb") as f:
                    for chunk in r.iter_content(65536):
                        if chunk:
                            f.write(chunk)
                saved.append(str(out))
        except Exception as e:
            print(f"  ! image error: {u} ({e})")

    return saved

# ---------------------------
# Public API
# ---------------------------
def scrape_tesco_product_with_oxylabs(url: str,
                                      *,
                                      download_images_flag: bool = True,
                                      max_images: Optional[int] = None,
                                      force_jpg: bool = False,
                                      geo: str = "United Kingdom",
                                      verbose: bool = False) -> Dict[str, Any]:
    if verbose:
        print(f"Fetching {url}...")
    
    html_content = oxy_fetch_html(url, geo=geo)
    parsed = parse_tesco(html_content, page_url=url)

    # ============================================================
    # Handle invalid link - return early
    # ============================================================
    if parsed.get("is_invalid"):
        if verbose:
            print(f"  ⚠ INVALID: {parsed['invalid_reason']}")
        return {
            "name": parsed["name"],  # "Invalid Link" or "Product not available"
            "price": "N/A",
            "in_stock": False,
            "description": "N/A",
            "seller": "",
            "image_count": 0,
            "images": [],
            "folder": "",
            "url": url,
            "mode": "oxylabs(html)+direct(images)",
            "is_invalid": True,
            "invalid_reason": parsed["invalid_reason"],
        }

    folder = SAVE_DIR / f"{_retailer_slug(url)}_{_safe_name(parsed['name'] if parsed['name'] != 'N/A' else 'Tesco_Product')}_{_stable_id_from_url(url)}"

    if verbose:
        print(f"  Name: {parsed['name']}")
        print(f"  Price: {parsed['price']}")
        print(f"  In Stock: {parsed['in_stock']}")

    images_downloaded: List[str] = []
    if download_images_flag and parsed["image_urls"]:
        images_downloaded = download_images(parsed["image_urls"], folder, referer=url,
                                            max_images=max_images, force_jpg=force_jpg)

    return {
        "name": parsed["name"],
        "price": parsed["price"],
        "in_stock": parsed["in_stock"],
        "description": parsed["description"],
        "seller": parsed["seller"],
        "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
        "images": images_downloaded if images_downloaded else parsed["image_urls"],
        "folder": str(folder),
        "url": url,
        "mode": "oxylabs(html)+direct(images)",
        "is_invalid": False,
        "invalid_reason": "",
    }

# # ---------------------------
# # CLI
# # ---------------------------
# if __name__ == "__main__":
#     import sys
    
#     # Test URLs
#     TEST_URLS = [
#         # Valid product
#         "https://www.tesco.com/groceries/en-GB/products/311757809",
#         # Invalid URL (likely 404)
#         "https://www.tesco.com/groceries/en-GB/products/999999999",
#     ]
    
#     if len(sys.argv) > 1:
#         TEST_URLS = sys.argv[1:]
    
#     for test_url in TEST_URLS:
#         print(f"\n{'='*60}")
#         print(f"Testing: {test_url}")
#         print('='*60)
#         try:
#             data = scrape_tesco_product_with_oxylabs(
#                 test_url,
#                 download_images_flag=False,
#                 verbose=True
#             )
#             print(json.dumps(data, indent=2, ensure_ascii=False))
#         except Exception as e:
#             print(f"ERROR: {e}")