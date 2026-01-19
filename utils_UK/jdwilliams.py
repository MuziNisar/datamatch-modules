# # jdw_oxylabs.py
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
#     raise RuntimeError("Oxylabs credentials missing. Set OXYLABS_USERNAME / OXYLABS_PASSWORD or provide oxylabs_secrets.py")


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
# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "").strip())


# def _ua() -> str:
#     return random.choice([
#         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
#         "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
#         "Mozilla/5.0 (Linux; Android 14; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36",
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


# def _safe_name(name: str) -> str:
#     n = re.sub(r"[^\w\s-]", "", name or "").strip()
#     n = re.sub(r"\s+", "_", n)
#     return n or "Unknown_Product"


# def _retailer_slug(url: str) -> str:
#     m = re.search(r"https?://(?:www\.)?([^/]+)", url or "", re.I)
#     host = (m.group(1).lower() if m else "site")
#     host = re.sub(r"^www\.", "", host)
#     return host.split(".")[0]


# def _stable_id_from_url(url: str) -> str:
#     m = re.search(r"(\d{6,})", url or "")
#     return m.group(1) if m else "jdw"


# # ---------------------------
# # Oxylabs universal (rendered HTML)
# # ---------------------------
# def _oxylabs_universal_html(url: str, country: str = "United Kingdom", timeout: int = 75) -> str:
#     endpoint = "https://realtime.oxylabs.io/v1/queries"
#     payload = {
#         "source": "universal",
#         "url": url,
#         "geo_location": country,
#         "render": "html",             # valid: html/mhtml/png
#         "user_agent_type": "desktop",
#         "headers": {"User-Agent": _ua()},
#         # "premium": True,            # enable if your plan supports it
#     }
#     sess = _session_with_retries()
#     r = sess.post(endpoint, auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
#     if r.status_code != 200:
#         raise RuntimeError(f"Oxylabs HTML fetch failed: HTTP {r.status_code} — {r.text.strip()}")
#     data = r.json()
#     try:
#         return data["results"][0]["content"]
#     except Exception:
#         raise RuntimeError(f"Oxylabs response missing content: {data}")


# # ---------------------------
# # Parsers for JD Williams PDP
# # ---------------------------
# def _extract_name(soup: BeautifulSoup) -> str:
#     el = soup.select_one('h1[data-testid="product-name"]')
#     if el:
#         t = _clean(el.get_text(" ", strip=True))
#         if t:
#             return t
#     # fallbacks
#     for sel in ("h1", "[data-testid='pdp-title']"):
#         el = soup.select_one(sel)
#         if el:
#             t = _clean(el.get_text(" ", strip=True))
#             if t:
#                 return t
#     # JSON-LD
#     for tag in soup.select("script[type='application/ld+json']"):
#         try:
#             data = json.loads(tag.string or "")
#         except Exception:
#             continue
#         objs = data if isinstance(data, list) else [data]
#         for o in objs:
#             if o.get("@type") == "Product" and o.get("name"):
#                 return _clean(o["name"])
#     return "Unknown Product"


# def _extract_price(soup: BeautifulSoup) -> Tuple[str, str]:
#     # main price block
#     p = soup.select_one("div[data-cy='product-details-price'] span")
#     if p:
#         txt = _clean(p.get_text())
#         if txt:
#             # normalize "£69" -> "69 GBP"
#             m = re.search(r"(£\s?\d[\d,]*(?:\.\d{2})?)", txt)
#             if m:
#                 return m.group(1).replace(" ", "") + " GBP", "price-block"
#             return txt + " GBP", "price-block-raw"

#     # body fallback
#     body = _clean(soup.get_text(" ", strip=True))
#     m = re.search(r"(£\s?\d[\d,]*(?:\.\d{2})?)", body)
#     if m:
#         return m.group(1).replace(" ", "") + " GBP", "body"

#     # JSON-LD
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
#                     price = off.get("price") or off.get("lowPrice")
#                     if price:
#                         return f"{price} GBP", "jsonld"
#     return "N/A", "none"


# def _extract_description(soup: BeautifulSoup) -> str:
#     d = soup.select_one("section.FullProductDetails_section__sSjSs")
#     if d:
#         t = _clean(d.get_text(" ", strip=True))
#         if t:
#             return t
#     # fallbacks
#     for sel in ("[data-testid='product-description']", ".product-description", ".pdp-description"):
#         el = soup.select_one(sel)
#         if el:
#             t = _clean(el.get_text(" ", strip=True))
#             if t:
#                 return t
#     # JSON-LD
#     for tag in soup.select("script[type='application/ld+json']"):
#         try:
#             data = json.loads(tag.string or "")
#         except Exception:
#             continue
#         objs = data if isinstance(data, list) else [data]
#         for o in objs:
#             if o.get("@type") == "Product" and o.get("description"):
#                 t = _clean(o["description"])
#                 if t:
#                     return t
#     # meta
#     meta = soup.select_one("meta[name='description']")
#     if meta and meta.get("content"):
#         t = _clean(meta["content"])
#         if t:
#             return t
#     return "N/A"


# def _extract_stock(soup: BeautifulSoup) -> Tuple[bool | None, str]:
#     """
#     Heuristic: visible Add to Bag CTA => in stock.
#     Also parse JSON-LD availability if present.
#     """
#     # CTA text check
#     if soup.find("button", attrs={"data-ga-tracking-id": "addToBagButton"}):
#         return True, "addToBagButton"
#     if soup.find(string=re.compile(r"\bAdd to (Bag|basket)\b", re.I)):
#         return True, "cta-text"

#     # explicit OOS phrases in body
#     body = _clean(soup.get_text(" ", strip=True)).lower()
#     if any(x in body for x in ["out of stock", "sold out", "not available", "unavailable"]):
#         return False, "body-oos"

#     # JSON-LD availability
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

#     return None, "unknown"


# def _extract_images(soup: BeautifulSoup) -> List[str]:
#     """
#     Use the gallery <picture> images. Prefer data-src/srcset entries; clean query;
#     upgrade to large if width params exist.
#     """
#     urls, seen = [], set()

#     # Primary selector from your code:
#     for img in soup.select("picture.MediaGallery_mediaGalleryImage__FQEPD img"):
#         src = img.get("src") or img.get("data-src") or ""
#         if not src:
#             # parse srcset if present
#             srcset = img.get("srcset") or ""
#             parts = [p.split(" ")[0] for p in srcset.split(",") if p.strip()]
#             if parts:
#                 src = parts[-1]  # largest candidate

#         if not src:
#             continue

#         base = src.split("?")[0]
#         if not base or base in seen:
#             continue
#         seen.add(base)
#         urls.append(base)

#     # Fallback: any sizable product/gallery images on page
#     if not urls:
#         for img in soup.select("img[src]"):
#             s = img.get("src") or ""
#             if "product" in s.lower() or "gallery" in s.lower() or "zoom" in s.lower():
#                 base = s.split("?")[0]
#                 if base and base not in seen:
#                     seen.add(base)
#                     urls.append(base)

#     return urls


# # ---------------------------
# # Image download (force JPG)
# # ---------------------------
# def _download_images_jpg(urls: List[str], folder: Path, session: requests.Session) -> List[str]:
#     folder.mkdir(parents=True, exist_ok=True)
#     out = []
#     headers = {
#         "User-Agent": _ua(),
#         "Referer": "https://www.jdwilliams.co.uk/",
#         "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
#     }

#     for i, u in enumerate(urls, start=1):
#         try:
#             r = session.get(u, timeout=25, stream=True, headers=headers)
#             r.raise_for_status()
#             data = r.content
#             try:
#                 im = Image.open(io.BytesIO(data))
#                 rgb = im.convert("RGB")
#                 fp = folder / f"{i:02d}.jpg"
#                 rgb.save(fp, format="JPEG", quality=92, optimize=True)
#                 out.append(str(fp))
#             except Exception:
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
# def fetch_jdw_product_with_oxylabs(url: str) -> Dict[str, Any]:
#     html = _oxylabs_universal_html(url, country="United Kingdom", timeout=75)
#     soup = BeautifulSoup(html, "lxml")

#     name = _extract_name(soup)
#     price, price_src = _extract_price(soup)
#     description = _extract_description(soup)
#     in_stock, avail_msg = _extract_stock(soup)
#     image_urls = _extract_images(soup)

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


# # ---------------------------
# # CLI test
# # ---------------------------
# if __name__ == "__main__":
#     TEST_URL = "https://www.jdwilliams.co.uk/shop/p/mp935"  
#     data = fetch_jdw_product_with_oxylabs(TEST_URL)
#     print(json.dumps(data, indent=2, ensure_ascii=False))






# jdw_oxylabs.py
# Python 3.10+
# pip install requests beautifulsoup4 lxml pillow
# Version: 2.0 - Fixed stock detection and image downloads

import os
import re
import io
import json
import random
import base64
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
# Oxylabs universal (rendered HTML)
# ---------------------------
def _oxylabs_universal_html(url: str, country: str = "United Kingdom", timeout: int = 75) -> str:
    endpoint = "https://realtime.oxylabs.io/v1/queries"
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": country,
        "render": "html",
        "user_agent_type": "desktop",
        "headers": {"User-Agent": _ua()},
    }
    sess = _session_with_retries()
    r = sess.post(endpoint, auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"Oxylabs HTML fetch failed: HTTP {r.status_code} — {r.text.strip()}")
    data = r.json()
    try:
        return data["results"][0]["content"]
    except Exception:
        raise RuntimeError(f"Oxylabs response missing content: {data}")


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

    # Body fallback
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
    
    html = _oxylabs_universal_html(url, country="United Kingdom", timeout=75)
    soup = BeautifulSoup(html, "lxml")

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
    }


# # ---------------------------
# # CLI test
# # ---------------------------
# if __name__ == "__main__":
#     TEST_URL = "https://www.jdwilliams.co.uk/shop/p/mp935"
#     data = fetch_jdw_product_with_oxylabs(TEST_URL, verbose=True)
#     print("\n" + "=" * 60)
#     print("RESULTS:")
#     print("=" * 60)
#     print(json.dumps(data, indent=2, ensure_ascii=False))