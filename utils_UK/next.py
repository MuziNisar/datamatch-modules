
# # next_oxylabs.py
# # Python 3.10+
# # pip install requests beautifulsoup4 lxml

# from __future__ import annotations
# import os, re, json, time
# from pathlib import Path
# from typing import Dict, Any, List, Optional, Tuple
# from urllib.parse import urlparse, urldefrag

# import requests
# from requests.adapters import HTTPAdapter
# from urllib3.util.retry import Retry
# from bs4 import BeautifulSoup

# # ---------------------------
# # Credentials (oxylabs_secrets.py or env)
# # ---------------------------
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS  # optional helper file
# except Exception:
#     OXY_USER = os.getenv("OXY_USER") or os.getenv("OXYLABS_USERNAME", "")
#     OXY_PASS = os.getenv("OXY_PASS") or os.getenv("OXYLABS_PASSWORD", "")

# if not (OXY_USER and OXY_PASS):
#     raise RuntimeError("Oxylabs credentials missing. Set OXY_USER/OXY_PASS or provide oxylabs_secrets.py")

# # ---------------------------
# # Paths & headers
# # ---------------------------
# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()
# DATA_DIR = BASE_DIR / "data1"
# DATA_DIR.mkdir(parents=True, exist_ok=True)

# UA = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
# )
# ACCEPT_LANG = "en-GB,en;q=0.9"

# # ---------------------------
# # Session with retries
# # ---------------------------
# def _session_with_retries(total=3, backoff=0.6) -> requests.Session:
#     s = requests.Session()
#     retry = Retry(
#         total=total, read=total, connect=total,
#         backoff_factor=backoff,
#         status_forcelist=(429, 500, 502, 503, 504),
#         allowed_methods=frozenset(["GET", "POST", "HEAD"])
#     )
#     adapter = HTTPAdapter(max_retries=retry, pool_maxsize=20)
#     s.mount("http://", adapter)
#     s.mount("https://", adapter)
#     return s

# # ---------------------------
# # Helpers
# # ---------------------------
# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "").strip())

# def _safe_name(s: str) -> str:
#     s = _clean(s)
#     return re.sub(r"[^\w.\-]+", "_", s)[:120] or "unknown_product"

# def _origin_for(url: str) -> str:
#     p = urlparse(url)
#     return f"{p.scheme}://{p.netloc}"

# def _absolutize(u: str, base: str) -> str:
#     if not u:
#         return u
#     if u.startswith("//"):
#         scheme = urlparse(base).scheme or "https"
#         return f"{scheme}:{u}"
#     if u.startswith("/"):
#         return _origin_for(base) + u
#     return u

# def _parse_gbp(text: str) -> Optional[Tuple[float, str, str]]:
#     if not text:
#         return None
#     m = re.search(r"£\s*([\d.,]+)", text)
#     if not m:
#         return None
#     val = float(m.group(1).replace(",", ""))
#     return val, "GBP", f"{val:.2f} GBP"

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
#         "headers": {"User-Agent": UA, "Accept-Language": ACCEPT_LANG},
#         # "premium": True,  # uncomment if your plan supports it
#     }
#     sess = _session_with_retries()
#     last = None
#     for i in range(3):
#         try:
#             r = sess.post("https://realtime.oxylabs.io/v1/queries",
#                           auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
#             r.raise_for_status()
#             data = r.json()
#             html = data["results"][0]["content"]
#             if "<html" not in html.lower():
#                 raise RuntimeError("Oxylabs returned non-HTML content")
#             return html
#         except Exception as e:
#             last = e
#             time.sleep(1.5 ** (i + 1))
#     raise RuntimeError(f"Oxylabs HTML fetch failed: {last}")

# # ---------------------------
# # Parse Next PDP
# # ---------------------------
# def parse_next(html: str, page_url: str) -> Dict[str, Any]:
#     soup = BeautifulSoup(html, "lxml")

#     # JSON-LD (Product)
#     product_ld: Optional[dict] = None
#     for tag in soup.select("script[type='application/ld+json']"):
#         try:
#             obj = json.loads(tag.text or "")
#             arr = obj if isinstance(obj, list) else [obj]
#             for it in arr:
#                 if isinstance(it, dict) and it.get("@type") == "Product":
#                     product_ld = it
#                     break
#             if product_ld:
#                 break
#         except Exception:
#             pass

#     # Name
#     name = None
#     if product_ld and product_ld.get("name"):
#         name = _clean(product_ld["name"])
#     if not name:
#         el = soup.find(["h1"], attrs={"data-testid": re.compile("(?i)product-name")}) or soup.select_one("h1")
#         if el:
#             name = _clean(el.get_text())
#     name = name or "N/A"

#     # Description
#     description = ""
#     if product_ld and product_ld.get("description"):
#         description = _clean(product_ld["description"])
#     if not description:
#         desc_el = soup.select_one("[data-testid='accordion-description']") or soup.select_one("div#tab-details, div.product-description, div#tab-description")
#         if desc_el:
#             description = _clean(desc_el.get_text(" ", strip=True))
#     description = description or "N/A"

#     # Price & stock from JSON-LD offers
#     price = None
#     in_stock: Optional[bool] = None
#     if product_ld and product_ld.get("offers"):
#         offers = product_ld["offers"]
#         if isinstance(offers, dict):
#             offers = [offers]
#         for off in offers:
#             if "price" in off and off["price"]:
#                 try:
#                     pv = float(str(off["price"]).replace(",", ""))
#                     price = f"{pv:.2f} GBP"
#                 except Exception:
#                     pass
#             avail = str(off.get("availability", "")).lower()
#             if "instock" in avail:
#                 in_stock = True
#             elif any(x in avail for x in ["outofstock", "soldout", "unavailable"]):
#                 in_stock = False

#     # On-page price fallback
#     if price is None:
#         el = soup.find(lambda t: t and t.name in ("span", "div") and "£" in t.get_text())
#         if el:
#             parsed = _parse_gbp(_clean(el.get_text()))
#             if parsed:
#                 price = parsed[2]

#     # Add-to-bag heuristic fallback
#     if in_stock is None:
#         body = _clean(soup.get_text(" ", strip=True)).lower()
#         if "add to bag" in body or "add to bag" in body:
#             in_stock = True
#         elif "out of stock" in body:
#             in_stock = False

#     # Images from carousel
#     images: List[str] = []
#     for img in soup.select("#pdp-image-carousel img, [data-testid='image-gallery'] img"):
#         src = img.get("data-src") or img.get("data-fallback-src") or img.get("src") or ""
#         src = _absolutize(src, page_url)
#         if src.startswith("http"):
#             images.append(src.split("?")[0])

#     # Dedup
#     seen = set()
#     deduped = []
#     for u in images:
#         if u not in seen:
#             seen.add(u); deduped.append(u)

#     return {
#         "name": name,
#         "price": price or "N/A",
#         "in_stock": in_stock,
#         "description": description,
#         "image_urls": deduped
#     }

# # ---------------------------
# # Next unofficial Product API fallback
# # ---------------------------
# def next_api_enrich(url: str, data: Dict[str, Any]) -> Dict[str, Any]:
#     # Try to find product code in URL (patterns like "C12345" or "AB12345")
#     m = re.search(r"([A-Z]{1,2}\d{4,}s?)", url, re.IGNORECASE)
#     if not m:
#         return data
#     code = m.group(1).upper()

#     api_url = f"https://www.next.co.uk/ProductApi/ProductDetails?productCode={code}&country=GB"
#     sess = _session_with_retries()
#     try:
#         r = sess.get(api_url, headers={"User-Agent": UA, "Accept-Language": ACCEPT_LANG}, timeout=20)
#         r.raise_for_status()
#         api = r.json() if r.content else {}
#     except Exception:
#         return data

#     if not data.get("name") or data["name"] == "N/A":
#         data["name"] = api.get("name") or data["name"]
#     if (not data.get("description")) or data["description"] == "N/A":
#         data["description"] = api.get("description") or data["description"]
#     if (not data.get("price")) or data["price"] == "N/A":
#         price_info = (api.get("prices") or {}).get("GBP") or {}
#         if "price" in price_info:
#             try:
#                 pv = float(str(price_info["price"]).replace(",", ""))
#                 data["price"] = f"{pv:.2f} GBP"
#             except Exception:
#                 pass
#     if data.get("in_stock") is None:
#         stock = (api.get("stock") or {}).get("available")
#         if isinstance(stock, bool):
#             data["in_stock"] = stock

#     return data

# # ---------------------------
# # Image discovery: brute-force (Next CDN pattern)
# # ---------------------------
# def brute_force_next_images(seed_images: List[str], max_brute_force: int = 20) -> List[str]:
#     if not seed_images:
#         return seed_images
#     # Detect base code from first image
#     m = re.search(r"/([A-Z]{1,2}\d+s?)\d*", seed_images[0], re.IGNORECASE)
#     if not m:
#         return seed_images
#     base_code = m.group(1)

#     out = seed_images[:]
#     sess = _session_with_retries()
#     for i in range(1, max_brute_force + 1):
#         suffix = "" if i == 1 else str(i)
#         test_url = f"https://xcdn.next.co.uk/common/items/default/default/itemimages/3_4Ratio/product/lge/{base_code}{suffix}.jpg"
#         if test_url in out:
#             continue
#         try:
#             h = sess.head(test_url, timeout=5)
#             if h.status_code == 200:
#                 out.append(test_url)
#             else:
#                 # stop early if sequence ends
#                 if i > 1:
#                     break
#         except Exception:
#             break
#     # dedupe
#     seen, deduped = set(), []
#     for u in out:
#         if u not in seen:
#             seen.add(u); deduped.append(u)
#     return deduped

# # ---------------------------
# # Image download
# # ---------------------------
# def download_images(urls: List[str], folder: Path, referer: str, max_images: Optional[int] = None) -> List[str]:
#     if max_images is not None:
#         urls = urls[:max_images]
#     folder.mkdir(parents=True, exist_ok=True)

#     sess = _session_with_retries()
#     headers = {
#         "User-Agent": UA,
#         "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#         "Accept-Language": ACCEPT_LANG,
#         "Referer": referer,
#     }

#     saved = []
#     for i, u in enumerate(urls, start=1):
#         try:
#             r = sess.get(u, headers=headers, timeout=20, stream=True)
#             r.raise_for_status()
#             ext = os.path.splitext(urlparse(u).path)[1] or ".jpg"
#             out = folder / f"{i:02d}{ext}"
#             with open(out, "wb") as f:
#                 for chunk in r.iter_content(65536):
#                     if chunk:
#                         f.write(chunk)
#             saved.append(str(out))
#         except Exception as e:
#             print(f"  ! image download failed: {u} ({e})")
#     return saved

# # ---------------------------
# # Public API
# # ---------------------------
# def scrape_next_with_oxylabs(url: str,
#                              download_images_flag: bool = True,
#                              max_brute_force: int = 20,
#                              max_images: Optional[int] = None,
#                              geo: str = "United Kingdom") -> Dict[str, Any]:
#     html = oxy_fetch_html(url, geo=geo)
#     parsed = parse_next(html, page_url=url)
#     parsed = next_api_enrich(url, parsed)

#     # Brute-force discover more CDN images
#     imgs_all = brute_force_next_images(parsed["image_urls"], max_brute_force=max_brute_force)

#     safe_name = _safe_name(parsed["name"] if parsed["name"] != "N/A" else "Unknown_Product")
#     folder = DATA_DIR / f"next_{safe_name}"

#     images_downloaded: List[str] = []
#     if download_images_flag and imgs_all:
#         images_downloaded = download_images(imgs_all, folder, referer=url, max_images=max_images)

#     return {
#         "name": parsed["name"] or "N/A",
#         "price": parsed["price"] or "N/A",
#         "in_stock": parsed["in_stock"],
#         "description": parsed["description"] or "N/A",
#         "image_count": len(images_downloaded) if images_downloaded else len(imgs_all),
#         "images": images_downloaded if images_downloaded else imgs_all,
#         "folder": str(folder),
#         "url": url,
#         "mode": "oxylabs-universal"
#     }

# # ---------------------------
# # CLI
# # ---------------------------
# if __name__ == "__main__":
#     TEST_URL = "https://www.next.co.uk/style/su620644/f30484"  
#     data = scrape_next_with_oxylabs(TEST_URL, download_images_flag=True, max_brute_force=20, max_images=20)
#     print(json.dumps(data, indent=2, ensure_ascii=False))







# next_oxylabs.py
# Python 3.10+
# pip install requests beautifulsoup4 lxml

from __future__ import annotations
import os, re, json, time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse, urldefrag

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# ---------------------------
# Credentials (oxylabs_secrets.py or env)
# ---------------------------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS  # optional helper file
except Exception:
    OXY_USER = os.getenv("OXY_USER") or os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXY_PASS") or os.getenv("OXYLABS_PASSWORD", "")

if not (OXY_USER and OXY_PASS):
    raise RuntimeError("Oxylabs credentials missing. Set OXY_USER/OXY_PASS or provide oxylabs_secrets.py")

# ---------------------------
# Paths & headers
# ---------------------------
try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()
DATA_DIR = BASE_DIR / "data1"
DATA_DIR.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
ACCEPT_LANG = "en-GB,en;q=0.9"

# ---------------------------
# Session with retries
# ---------------------------
def _session_with_retries(total=3, backoff=0.6) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=total, read=total, connect=total,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST", "HEAD"])
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=20)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

# ---------------------------
# Helpers
# ---------------------------
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _safe_name(s: str) -> str:
    s = _clean(s)
    return re.sub(r"[^\w.\-]+", "_", s)[:120] or "unknown_product"

def _origin_for(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"

def _absolutize(u: str, base: str) -> str:
    if not u:
        return u
    if u.startswith("//"):
        scheme = urlparse(base).scheme or "https"
        return f"{scheme}:{u}"
    if u.startswith("/"):
        return _origin_for(base) + u
    return u

def _parse_gbp(text: str) -> Optional[Tuple[float, str, str]]:
    if not text:
        return None
    m = re.search(r"£\s*([\d.,]+)", text)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    return val, "GBP", f"{val:.2f} GBP"

def _normalize_next_image_url(url: str) -> str:
    """
    Normalize Next CDN image URL to a consistent base form for deduplication.
    Removes query parameters and gets the base filename.
    
    Example:
        Input:  https://xcdn.next.co.uk/.../F30484s.jpg?im=Resize,width=750
        Output: https://xcdn.next.co.uk/.../F30484s.jpg
    """
    if not url:
        return url
    # Remove query parameters
    base_url = url.split("?")[0]
    return base_url

def _get_image_key(url: str) -> str:
    """
    Get a unique key for an image URL based on the filename.
    This handles cases like F30484s.jpg vs F30484s2.jpg
    
    Example:
        Input:  https://xcdn.next.co.uk/.../F30484s.jpg?im=Resize,width=750
        Output: f30484s.jpg
    """
    if not url:
        return ""
    # Get the base URL without query params
    base_url = url.split("?")[0]
    # Extract just the filename
    filename = base_url.rstrip("/").split("/")[-1].lower()
    return filename

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
        "headers": {"User-Agent": UA, "Accept-Language": ACCEPT_LANG},
    }
    sess = _session_with_retries()
    last = None
    for i in range(3):
        try:
            r = sess.post("https://realtime.oxylabs.io/v1/queries",
                          auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            html = data["results"][0]["content"]
            if "<html" not in html.lower():
                raise RuntimeError("Oxylabs returned non-HTML content")
            return html
        except Exception as e:
            last = e
            time.sleep(1.5 ** (i + 1))
    raise RuntimeError(f"Oxylabs HTML fetch failed: {last}")

# ---------------------------
# Parse Next PDP
# ---------------------------
def parse_next(html: str, page_url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    # JSON-LD (Product)
    product_ld: Optional[dict] = None
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            obj = json.loads(tag.text or "")
            arr = obj if isinstance(obj, list) else [obj]
            for it in arr:
                if isinstance(it, dict) and it.get("@type") == "Product":
                    product_ld = it
                    break
            if product_ld:
                break
        except Exception:
            pass

    # Name
    name = None
    if product_ld and product_ld.get("name"):
        name = _clean(product_ld["name"])
    if not name:
        el = soup.find(["h1"], attrs={"data-testid": re.compile("(?i)product-name")}) or soup.select_one("h1")
        if el:
            name = _clean(el.get_text())
    name = name or "N/A"

    # Description
    description = ""
    if product_ld and product_ld.get("description"):
        description = _clean(product_ld["description"])
    if not description:
        desc_el = soup.select_one("[data-testid='accordion-description']") or soup.select_one("div#tab-details, div.product-description, div#tab-description")
        if desc_el:
            description = _clean(desc_el.get_text(" ", strip=True))
    description = description or "N/A"

    # Price & stock from JSON-LD offers
    price = None
    in_stock: Optional[bool] = None
    if product_ld and product_ld.get("offers"):
        offers = product_ld["offers"]
        if isinstance(offers, dict):
            offers = [offers]
        for off in offers:
            if "price" in off and off["price"]:
                try:
                    pv = float(str(off["price"]).replace(",", ""))
                    price = f"{pv:.2f} GBP"
                except Exception:
                    pass
            avail = str(off.get("availability", "")).lower()
            if "instock" in avail:
                in_stock = True
            elif any(x in avail for x in ["outofstock", "soldout", "unavailable"]):
                in_stock = False

    # On-page price fallback
    if price is None:
        el = soup.find(lambda t: t and t.name in ("span", "div") and "£" in t.get_text())
        if el:
            parsed = _parse_gbp(_clean(el.get_text()))
            if parsed:
                price = parsed[2]

    # Add-to-bag heuristic fallback
    if in_stock is None:
        body = _clean(soup.get_text(" ", strip=True)).lower()
        if "add to bag" in body:
            in_stock = True
        elif "out of stock" in body:
            in_stock = False

    # Images from carousel - FIXED: proper deduplication
    images: List[str] = []
    seen_keys: set = set()
    
    # Strategy 1: Get images from the carousel (data-testid="image-carousel-slide")
    for img in soup.select('[data-testid="image-carousel-slide"], #pdp-image-carousel img'):
        # Only use the src attribute (primary image), not srcset
        src = img.get("src") or ""
        if not src:
            continue
        
        src = _absolutize(src, page_url)
        if not src.startswith("http"):
            continue
        
        # Normalize and deduplicate
        normalized = _normalize_next_image_url(src)
        key = _get_image_key(src)
        
        if key and key not in seen_keys:
            seen_keys.add(key)
            images.append(normalized)
    
    # Strategy 2: Fallback to other image selectors if no images found
    if not images:
        for img in soup.select('[data-testid="image-gallery"] img'):
            src = img.get("data-src") or img.get("data-fallback-src") or img.get("src") or ""
            src = _absolutize(src, page_url)
            if src.startswith("http"):
                normalized = _normalize_next_image_url(src)
                key = _get_image_key(src)
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    images.append(normalized)

    return {
        "name": name,
        "price": price or "N/A",
        "in_stock": in_stock,
        "description": description,
        "image_urls": images
    }

# ---------------------------
# Next unofficial Product API fallback
# ---------------------------
def next_api_enrich(url: str, data: Dict[str, Any]) -> Dict[str, Any]:
    # Try to find product code in URL (patterns like "C12345" or "AB12345")
    m = re.search(r"([A-Z]{1,2}\d{4,}s?)", url, re.IGNORECASE)
    if not m:
        return data
    code = m.group(1).upper()

    api_url = f"https://www.next.co.uk/ProductApi/ProductDetails?productCode={code}&country=GB"
    sess = _session_with_retries()
    try:
        r = sess.get(api_url, headers={"User-Agent": UA, "Accept-Language": ACCEPT_LANG}, timeout=20)
        r.raise_for_status()
        api = r.json() if r.content else {}
    except Exception:
        return data

    if not data.get("name") or data["name"] == "N/A":
        data["name"] = api.get("name") or data["name"]
    if (not data.get("description")) or data["description"] == "N/A":
        data["description"] = api.get("description") or data["description"]
    if (not data.get("price")) or data["price"] == "N/A":
        price_info = (api.get("prices") or {}).get("GBP") or {}
        if "price" in price_info:
            try:
                pv = float(str(price_info["price"]).replace(",", ""))
                data["price"] = f"{pv:.2f} GBP"
            except Exception:
                pass
    if data.get("in_stock") is None:
        stock = (api.get("stock") or {}).get("available")
        if isinstance(stock, bool):
            data["in_stock"] = stock

    return data

# ---------------------------
# Image discovery: brute-force (Next CDN pattern) - DISABLED
# The carousel already contains all images, brute-force causes duplicates
# ---------------------------
def brute_force_next_images(seed_images: List[str], max_brute_force: int = 0) -> List[str]:
    """
    Brute-force discover additional CDN images.
    NOTE: Disabled by default (max_brute_force=0) because the carousel 
    already contains all images and brute-force causes duplicates.
    """
    if not seed_images or max_brute_force <= 0:
        return seed_images
    
    # Detect base code from first image
    m = re.search(r"/([A-Z]{1,2}\d+)s?(\d*)\.jpg", seed_images[0], re.IGNORECASE)
    if not m:
        return seed_images
    
    base_code = m.group(1)
    
    # Get existing image numbers to avoid duplicates
    existing_nums = set()
    for img in seed_images:
        m2 = re.search(rf"{base_code}s(\d*)\.jpg", img, re.IGNORECASE)
        if m2:
            num = m2.group(1)
            existing_nums.add(int(num) if num else 1)
    
    out = seed_images[:]
    sess = _session_with_retries()
    
    for i in range(1, max_brute_force + 1):
        if i in existing_nums:
            continue  # Already have this image
            
        suffix = "" if i == 1 else str(i)
        test_url = f"https://xcdn.next.co.uk/common/items/default/default/itemimages/3_4Ratio/product/lge/{base_code}s{suffix}.jpg"
        
        try:
            h = sess.head(test_url, timeout=5)
            if h.status_code == 200:
                out.append(test_url)
            elif i > len(existing_nums) + 2:
                # Stop if we've gone past expected count
                break
        except Exception:
            break
    
    return out

# ---------------------------
# Image download
# ---------------------------
def download_images(urls: List[str], folder: Path, referer: str, max_images: Optional[int] = None) -> List[str]:
    if max_images is not None:
        urls = urls[:max_images]
    folder.mkdir(parents=True, exist_ok=True)

    sess = _session_with_retries()
    headers = {
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Referer": referer,
    }

    saved = []
    for i, u in enumerate(urls, start=1):
        try:
            r = sess.get(u, headers=headers, timeout=20, stream=True)
            r.raise_for_status()
            ext = os.path.splitext(urlparse(u).path)[1] or ".jpg"
            out = folder / f"{i:02d}{ext}"
            with open(out, "wb") as f:
                for chunk in r.iter_content(65536):
                    if chunk:
                        f.write(chunk)
            saved.append(str(out))
        except Exception as e:
            print(f"  ! image download failed: {u} ({e})")
    return saved

# ---------------------------
# Public API
# ---------------------------
def scrape_next_with_oxylabs(url: str,
                             download_images_flag: bool = True,
                             max_brute_force: int = 0,  # Disabled by default
                             max_images: Optional[int] = None,
                             geo: str = "United Kingdom") -> Dict[str, Any]:
    html = oxy_fetch_html(url, geo=geo)
    parsed = parse_next(html, page_url=url)
    parsed = next_api_enrich(url, parsed)

    # Brute-force is disabled by default (causes duplicates)
    imgs_all = brute_force_next_images(parsed["image_urls"], max_brute_force=max_brute_force)

    safe_name = _safe_name(parsed["name"] if parsed["name"] != "N/A" else "Unknown_Product")
    folder = DATA_DIR / f"next_{safe_name}"

    images_downloaded: List[str] = []
    if download_images_flag and imgs_all:
        print(f"Downloading {len(imgs_all)} images...")
        images_downloaded = download_images(imgs_all, folder, referer=url, max_images=max_images)

    return {
        "url": url,
        "name": parsed["name"] or "N/A",
        "price": parsed["price"] or "N/A",
        "in_stock": parsed["in_stock"],
        "description": parsed["description"] or "N/A",
        "image_count": len(images_downloaded) if images_downloaded else len(imgs_all),
        "image_urls": imgs_all,
        "images": images_downloaded if images_downloaded else [],
        "folder": str(folder),
        "mode": "oxylabs-universal"
    }

# # ---------------------------
# # CLI
# # ---------------------------
# if __name__ == "__main__":
#     TEST_URL = "https://www.next.co.uk/style/su620644/f30484"  
#     data = scrape_next_with_oxylabs(TEST_URL, download_images_flag=True, max_brute_force=0, max_images=20)
#     print(json.dumps(data, indent=2, ensure_ascii=False))