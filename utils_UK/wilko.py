# # wilko.py
# # Python 3.10+
# # pip install requests bs4 lxml pillow

# from __future__ import annotations
# import os, re, time, json, html, hashlib, base64
# from pathlib import Path
# from typing import List, Optional, Tuple, Dict
# from urllib.parse import urlsplit, urlunsplit, urljoin
# from io import BytesIO

# import requests
# from bs4 import BeautifulSoup
# from PIL import Image

# # ===============================
# # Config / Paths
# # ===============================
# UA = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
# )
# ACCEPT_LANG = "en-GB,en;q=0.9"
# BASE_DIR = Path(__file__).resolve().parent
# DATA_DIR = BASE_DIR / os.getenv("DATA_DIR", "data_uk")
# DEBUG_DIR = BASE_DIR / "debug"
# DATA_DIR.mkdir(parents=True, exist_ok=True)
# DEBUG_DIR.mkdir(parents=True, exist_ok=True)
# BASE_HOST = "https://www.wilko.com"

# # ===============================
# # Small helpers
# # ===============================
# def _vprint(v: bool, *a):
#     if v:
#         print(*a)

# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "").strip())

# def _clean_multiline_preserve(s: str) -> str:
#     s = html.unescape((s or "")).replace("\r", "")
#     s = re.sub(r"[ \t]+", " ", s)
#     s = re.sub(r"\n{3,}", "\n\n", s)
#     return s.strip()

# def _safe_name(s: str) -> str:
#     s = _clean(s)
#     return re.sub(r"[^\w.\-]+", "_", s)[:120] or "product"

# def _stable_id_from_url(url: str) -> str:
#     try:
#         parts = [p for p in urlsplit(url).path.split("/") if p]
#         for p in reversed(parts):
#             if re.fullmatch(r"\d{6,}", p):
#                 return p
#         if parts:
#             return re.sub(r"[^\w\-]+", "", parts[-1])
#     except Exception:
#         pass
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

# def _strip_query(u: str) -> str:
#     sp = urlsplit(u)
#     return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

# def _dedupe_preserve_order(urls: List[str]) -> List[str]:
#     seen, out = set(), []
#     for u in urls:
#         k = _strip_query(u)
#         if k and k not in seen:
#             seen.add(k)
#             out.append(u)
#     return out

# def _abs(u: str) -> str:
#     return u if u.startswith("http") else urljoin(BASE_HOST, u)

# GBP_RX = re.compile(r"£\s*([0-9][\d,]*(?:\.\d{1,2})?)")
# def _parse_price(text: str) -> Optional[str]:
#     m = GBP_RX.search(text or "")
#     if not m:
#         return None
#     return f"{m.group(1).replace(',','')} GBP"

# # ===============================
# # Oxylabs: creds + call
# # ===============================
# def _oxy_creds() -> Tuple[str, str]:
#     try:
#         from oxylabs_secrets import OXY_USER, OXY_PASS
#         if OXY_USER and OXY_PASS:
#             return OXY_USER, OXY_PASS
#     except Exception:
#         pass
#     return os.getenv("OXYLABS_USERNAME", ""), os.getenv("OXYLABS_PASSWORD", "")

# def _normalize_url(u: str) -> str:
#     u = (u or "").strip()
#     if not u:
#         return u
#     if not re.match(r"^https?://", u, re.I):
#         u = "https://" + u
#     u = re.sub(r"\s+", "%20", u)
#     return u

# def _oxy_call(payload: dict, timeout: int = 90) -> dict:
#     user, pwd = _oxy_creds()
#     if not user or not pwd:
#         raise RuntimeError(
#             "Missing Oxylabs credentials. Set OXYLABS_USERNAME / OXYLABS_PASSWORD "
#             "or provide oxylabs_secrets.py with OXY_USER/OXY_PASS"
#         )
#     r = requests.post(
#         "https://realtime.oxylabs.io/v1/queries",
#         auth=(user, pwd),
#         json=payload,
#         timeout=timeout,
#     )
#     if r.status_code >= 400:
#         try:
#             err = r.json()
#         except Exception:
#             err = r.text[:800]
#         raise requests.HTTPError(
#             f"{r.status_code} {r.reason} – payload invalid? details={err}", response=r
#         )
#     return r.json()

# def oxy_fetch_html(url: str, accept_lang: str = ACCEPT_LANG, timeout: int = 90) -> str:
#     """
#     Fetch HTML using Oxylabs universal source with render.
#     """
#     url = _normalize_url(url)
#     headers = {"Accept-Language": accept_lang, "User-Agent": UA}

#     payload = {
#         "source": "universal",
#         "url": url,
#         "parse": False,
#         "render": "html",
#         "geo_location": "United Kingdom",
#         "user_agent_type": "desktop",
#         "headers": headers,
#     }

#     try:
#         resp = _oxy_call(payload, timeout=timeout)
#         content = (resp.get("results") or [{}])[0].get("content") or ""
#         if not content or not re.search(r"<html|<head|<body", content, re.I):
#             raise RuntimeError("Non-HTML content returned")
#         return content
#     except Exception as e:
#         raise RuntimeError(f"Oxylabs HTML fetch failed: {e}")

# # ---- Oxylabs image fetch: proxy-based (primary) ----
# def oxy_fetch_binary_via_proxy(url: str, timeout: int = 60) -> Optional[bytes]:
#     """
#     Fetch binary content (images) through Oxylabs using their proxy-style approach.
#     Uses proper TLS verification and accepts any 'image/*' content-type.
#     """
#     user, pwd = _oxy_creds()
#     if not user or not pwd:
#         return None

#     proxies = {
#         "http":  f"http://{user}:{pwd}@realtime.oxylabs.io:60000",
#         "https": f"http://{user}:{pwd}@realtime.oxylabs.io:60000",
#     }

#     try:
#         url = _normalize_url(url)
#         headers = {
#             "User-Agent": UA,
#             "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#             "Accept-Language": ACCEPT_LANG,
#             "Referer": BASE_HOST + "/",
#         }

#         r = requests.get(url, proxies=proxies, headers=headers, timeout=timeout)
#         if r.status_code == 200 and r.content:
#             ctype = (r.headers.get("Content-Type") or "").lower()
#             if "image" in ctype:
#                 return r.content
#             # If content-type is missing or weird, still let PIL try
#             return r.content

#         return None
#     except Exception:
#         return None

# # ---- Oxylabs image fetch: realtime API (fallback) ----
# def oxy_fetch_binary_realtime(
#     url: str, accept_lang: str = ACCEPT_LANG, timeout: int = 60
# ) -> Optional[bytes]:
#     """
#     Fetch binary asset via Oxylabs Realtime API (fallback method).
#     Uses content_encoding=base64 and lets PIL decide if it's a valid image.
#     This still consumes Web Scraper API "results", so consider disabling if you
#     want to save credits on a micro plan.
#     """
#     url = _normalize_url(url)
#     payload = {
#         "source": "universal",
#         "url": url,
#         "parse": False,
#         "user_agent_type": "desktop",
#         "geo_location": "United Kingdom",
#         "content_encoding": "base64",
#         "headers": {
#             "Accept-Language": accept_lang,
#             "User-Agent": UA,
#             "Referer": BASE_HOST + "/",
#             "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#         },
#     }

#     try:
#         resp = _oxy_call(payload, timeout=timeout)
#         res = (resp.get("results") or [{}])[0]

#         content = res.get("content")
#         encoding = (res.get("content_encoding") or res.get("encoding") or "").lower()

#         if not content:
#             return None

#         # Expect base64-encoded binary data
#         if encoding == "base64":
#             try:
#                 return base64.b64decode(content)
#             except Exception:
#                 return None

#         # In case Oxylabs returns raw bytes
#         if isinstance(content, bytes):
#             return content

#         # If it's a string but not explicitly marked, try base64 decode anyway
#         if isinstance(content, str):
#             try:
#                 return base64.b64decode(content)
#             except Exception:
#                 return None

#         return None
#     except Exception:
#         return None

# # ===============================
# # Wilko PDP parsers
# # ===============================
# def _jsonld_availability(soup: BeautifulSoup) -> Optional[bool]:
#     try:
#         for sc in soup.select("script[type='application/ld+json']"):
#             raw = sc.string or sc.get_text() or ""
#             try:
#                 data = json.loads(raw)
#             except Exception:
#                 continue
#             objs = data if isinstance(data, list) else [data]
#             for o in objs:
#                 if not isinstance(o, dict):
#                     continue
#                 offers = o.get("offers")
#                 if not offers and isinstance(o.get("@graph"), list):
#                     for g in o["@graph"]:
#                         if isinstance(g, dict) and g.get("@type") == "Product":
#                             offers = g.get("offers")
#                             if offers:
#                                 break
#                 if not offers:
#                     continue
#                 lst = offers if isinstance(offers, list) else [offers]
#                 for off in lst:
#                     if not isinstance(off, dict):
#                         continue
#                     avail = str(
#                         off.get("availability") or off.get("itemAvailability") or ""
#                     )
#                     if re.search(r"InStock", avail, re.I):
#                         return True
#                     if re.search(r"OutOfStock|SoldOut", avail, re.I):
#                         return False
#         return None
#     except Exception:
#         return None

# def _extract_name(soup: BeautifulSoup) -> str:
#     h = soup.select_one(
#         "div.product-title h1.name[itemprop='name'], h1.name[itemprop='name']"
#     )
#     if h:
#         return _clean(h.get_text(" ", strip=True))
#     t = soup.title.string if soup.title else ""
#     return _clean((t or "").split("|")[0]) or "Unknown_Product"

# def _extract_price(soup: BeautifulSoup) -> Tuple[str, str]:
#     for sel in ["div.pdp-price", "[class*='pdp-price']"]:
#         el = soup.select_one(sel)
#         if el:
#             p = _parse_price(el.get_text(" ", strip=True))
#             if p:
#                 return p, "onsite"
#     p = _parse_price(soup.get_text(" ", strip=True))
#     if p:
#         return p, "page"
#     return "N/A", "none"

# def _extract_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], Optional[str]]:
#     el = soup.select_one("div.product-widget__stock")
#     if el:
#         t = _clean(el.get_text(" ", strip=True))
#         if re.search(r"in stock", t, re.I):
#             m = re.search(r"(\d+\+?)", t)
#             return True, f"In stock ({m.group(1)})" if m else "In stock"
#         if re.search(r"out of stock|sold out|not available", t, re.I):
#             return False, "Out of stock"
#     avail = _jsonld_availability(soup)
#     if isinstance(avail, bool):
#         return avail, "In stock" if avail else "Out of stock"

#     blob = soup.get_text(" ", strip=True).lower()
#     if (
#         ("add to basket" in blob or "add to cart" in blob or "in stock" in blob)
#         and ("out of stock" not in blob)
#         and ("not available" not in blob)
#         and ("sold out" not in blob)
#     ):
#         return True, None
#     return None, None

# def _extract_description_and_images(
#     soup: BeautifulSoup, max_images: Optional[int]
# ) -> Tuple[str, List[str]]:
#     parts: List[str] = []

#     info = (
#         soup.select_one(".pdp-panel.product-information .pdp-panel__content")
#         or soup.select_one(".pdp-panel__content")
#     )

#     # Bullet list / key features
#     if info:
#         bl = info.select_one(".list ul")
#         if bl:
#             bullets = [
#                 _clean(li.get_text(" ", strip=True))
#                 for li in bl.select("li")
#                 if _clean(li.get_text(" ", strip=True))
#             ]
#             if bullets:
#                 parts.append("• " + "\n• ".join(bullets))

#     # Main description
#     desc_el = None
#     for sel in [
#         ".cropped-desc-js.more-desc[itemprop='description']",
#         ".cropped-desc-js.more-desc",
#         "[itemprop='description']",
#         ".product-description",
#         ".pdp-panel__content .more-desc",
#         ".pdp-panel__content [data-test='description']",
#     ]:
#         cand = soup.select_one(sel)
#         if cand and _clean(cand.get_text(" ", strip=True)):
#             desc_el = cand
#             break

#     if desc_el:
#         text = desc_el.get_text("\n", strip=True)
#         parts.append(_clean_multiline_preserve(text))

#     # Specs (dl/specification)
#     if info:
#         spec = info.select("dl.specification-wrapper .specification-item")
#         if spec:
#             kv = []
#             for it in spec:
#                 k_el = it.select_one(".specification-name")
#                 v_el = it.select_one(".specification-value")
#                 k = _clean(k_el.get_text(" ", strip=True)) if k_el else ""
#                 v = _clean(v_el.get_text(" ", strip=True)) if v_el else ""
#                 if k and v:
#                     kv.append(f"{k} {v}")
#             if kv:
#                 parts.append("\n".join(kv))

#     description = _clean_multiline_preserve(
#         "\n\n".join([p for p in parts if p])
#     ) or ""

#     # Images
#     urls: List[str] = []
#     for img in soup.select(".pdp-image-gallery-thumbnails__slider img[src]"):
#         u = img.get("src")
#         if u:
#             urls.append(_abs(u))

#     if not urls:
#         for img in soup.select("img[src]"):
#             src = img.get("src") or ""
#             if any(k in src for k in ("/product/", "/media/", "/images/", "/assets/")):
#                 urls.append(_abs(src))

#     urls = _dedupe_preserve_order(urls)
#     if max_images is not None:
#         urls = urls[:max_images]
#     return description, urls

# # ===============================
# # Image download (force JPEG)
# # ===============================
# def _save_jpg_bytes(b: bytes, out_path: Path) -> bool:
#     try:
#         img = Image.open(BytesIO(b))
#         if img.mode not in ("RGB", "L"):
#             img = img.convert("RGB")
#         img.save(out_path, format="JPEG", quality=92, optimize=True)
#         return True
#     except Exception:
#         return False

# def _download_images_jpg(
#     img_urls: List[str], folder: Path, referer: Optional[str], verbose: bool
# ) -> List[str]:
#     """
#     Download images through Oxylabs proxy, then fallback to realtime API, then direct.
#     Converts everything to JPEG as image_#.jpg.
#     """
#     folder.mkdir(parents=True, exist_ok=True)
#     saved: List[str] = []

#     s = requests.Session()
#     s.headers.update(
#         {
#             "User-Agent": UA,
#             "Accept-Language": ACCEPT_LANG,
#             "Referer": referer or "",
#             "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#         }
#     )

#     for idx, url in enumerate(img_urls, 1):
#         out_path = folder / f"image_{idx}.jpg"

#         # Method 1: Oxylabs proxy (primary)
#         b = oxy_fetch_binary_via_proxy(url, timeout=60)
#         if b and _save_jpg_bytes(b, out_path):
#             saved.append(str(out_path))
#             _vprint(verbose, f"  ✓ (oxy-proxy) image_{idx}.jpg ← {url}")
#             continue

#         # Method 2: Oxylabs realtime API (optional, consumes results)
#         b = oxy_fetch_binary_realtime(url, accept_lang=ACCEPT_LANG, timeout=60)
#         if b and _save_jpg_bytes(b, out_path):
#             saved.append(str(out_path))
#             _vprint(verbose, f"  ✓ (oxy-api) image_{idx}.jpg ← {url}")
#             continue

#         # Method 3: Direct request (may 403, but cheap)
#         try:
#             r = s.get(url, timeout=30)
#             if r.ok and r.content and _save_jpg_bytes(r.content, out_path):
#                 saved.append(str(out_path))
#                 _vprint(verbose, f"  ✓ (direct) image_{idx}.jpg ← {url}")
#             else:
#                 _vprint(verbose, f"  ! Failed all methods for {url}")
#         except Exception as e:
#             _vprint(verbose, f"  ! Error: {url} - {e}")

#     return saved

# # ===============================
# # Main API
# # ===============================
# def scrape_wilko_oxylabs(
#     url: str,
#     download_images: bool = True,
#     max_images: Optional[int] = 12,
#     verbose: bool = True,
# ) -> Dict:
#     """
#     Scrape a Wilko product page via Oxylabs.
#     - Uses proxy-based image fetching (more reliable)
#     - Optional realtime API fallback for images
#     - All images saved as .jpg
#     - Robust description extraction
#     """
#     result = {
#         "url": url,
#         "name": "",
#         "price": "N/A",
#         "price_source": "none",
#         "in_stock": None,
#         "stock_text": None,
#         "description": "",
#         "image_count": 0,
#         "images": [],
#         "folder": "",
#         "mode": "oxylabs(proxy)",
#     }

#     html_doc = oxy_fetch_html(url, accept_lang=ACCEPT_LANG, timeout=90)
#     soup = BeautifulSoup(html_doc, "lxml")

#     name = _extract_name(soup)
#     price, price_src = _extract_price(soup)
#     instock, stock_txt = _extract_stock(soup)
#     description, img_urls = _extract_description_and_images(soup, max_images)

#     ts = time.strftime("%Y%m%d-%H%M%S")
#     folder = DATA_DIR / f"wilko_{_safe_name(name)}_{_stable_id_from_url(url)}_{ts}"
#     folder.mkdir(parents=True, exist_ok=True)

#     result.update(
#         {
#             "name": name,
#             "price": price,
#             "price_source": price_src,
#             "in_stock": instock,
#             "stock_text": stock_txt,
#             "description": description,
#             "folder": str(folder),
#         }
#     )

#     if download_images and img_urls:
#         _vprint(verbose, f"Downloading {len(img_urls)} images as JPG …")
#         saved = _download_images_jpg(img_urls, folder, referer=url, verbose=verbose)
#         result["images"] = saved
#         result["image_count"] = len(saved)
#     else:
#         result["image_count"] = len(img_urls)

#     return result

# # ===============================
# # CLI (example)
# # ===============================
# if __name__ == "__main__":
#     TEST_URL = "https://www.wilko.com/en-uk/stationery-office/computer-mobile-tablet/mobile-phone-tablet-accessories/c/1000"
#     data = scrape_wilko_oxylabs(
#         TEST_URL, download_images=True, max_images=12, verbose=True
#     )
#     print(json.dumps(data, indent=2, ensure_ascii=False))

























# wilko.py
# Python 3.10+
# pip install requests bs4 lxml pillow

from __future__ import annotations
import os, re, time, json, html, hashlib, base64
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from urllib.parse import urlsplit, urlunsplit, urljoin
from io import BytesIO

import requests
from bs4 import BeautifulSoup
from PIL import Image

# ===============================
# Config / Paths
# ===============================
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
ACCEPT_LANG = "en-GB,en;q=0.9"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / os.getenv("DATA_DIR", "data_uk")
DEBUG_DIR = BASE_DIR / "debug"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)
BASE_HOST = "https://www.wilko.com"

# ===============================
# Small helpers
# ===============================
def _vprint(v: bool, *a):
    if v:
        print(*a)

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _clean_multiline_preserve(s: str) -> str:
    s = html.unescape((s or "")).replace("\r", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _safe_name(s: str) -> str:
    s = _clean(s)
    return re.sub(r"[^\w.\-]+", "_", s)[:120] or "product"

def _stable_id_from_url(url: str) -> str:
    try:
        parts = [p for p in urlsplit(url).path.split("/") if p]
        for p in reversed(parts):
            if re.fullmatch(r"\d{6,}", p):
                return p
        if parts:
            return re.sub(r"[^\w\-]+", "", parts[-1])
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

def _strip_query(u: str) -> str:
    sp = urlsplit(u)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

def _dedupe_preserve_order(urls: List[str]) -> List[str]:
    seen, out = set(), []
    for u in urls:
        k = _strip_query(u)
        if k and k not in seen:
            seen.add(k)
            out.append(u)
    return out

def _abs(u: str) -> str:
    return u if u.startswith("http") else urljoin(BASE_HOST, u)

GBP_RX = re.compile(r"£\s*([0-9][\d,]*(?:\.\d{1,2})?)")
def _parse_price(text: str) -> Optional[str]:
    m = GBP_RX.search(text or "")
    if not m:
        return None
    return f"{m.group(1).replace(',','')} GBP"

# ===============================
# Oxylabs: creds + call
# ===============================
def _oxy_creds() -> Tuple[str, str]:
    try:
        from oxylabs_secrets import OXY_USER, OXY_PASS
        if OXY_USER and OXY_PASS:
            return OXY_USER, OXY_PASS
    except Exception:
        pass
    return os.getenv("OXYLABS_USERNAME", ""), os.getenv("OXYLABS_PASSWORD", "")

def _normalize_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return u
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    u = re.sub(r"\s+", "%20", u)
    return u

def _oxy_call(payload: dict, timeout: int = 90) -> dict:
    user, pwd = _oxy_creds()
    if not user or not pwd:
        raise RuntimeError(
            "Missing Oxylabs credentials. Set OXYLABS_USERNAME / OXYLABS_PASSWORD "
            "or provide oxylabs_secrets.py with OXY_USER/OXY_PASS"
        )
    r = requests.post(
        "https://realtime.oxylabs.io/v1/queries",
        auth=(user, pwd),
        json=payload,
        timeout=timeout,
    )
    if r.status_code >= 400:
        try:
            err = r.json()
        except Exception:
            err = r.text[:800]
        raise requests.HTTPError(
            f"{r.status_code} {r.reason} – payload invalid? details={err}", response=r
        )
    return r.json()

def oxy_fetch_html(url: str, accept_lang: str = ACCEPT_LANG, timeout: int = 90) -> str:
    """
    Fetch HTML using Oxylabs universal source with render.
    """
    url = _normalize_url(url)
    headers = {"Accept-Language": accept_lang, "User-Agent": UA}

    payload = {
        "source": "universal",
        "url": url,
        "parse": False,
        "render": "html",
        "geo_location": "United Kingdom",
        "user_agent_type": "desktop",
        "headers": headers,
    }

    try:
        resp = _oxy_call(payload, timeout=timeout)
        content = (resp.get("results") or [{}])[0].get("content") or ""
        if not content or not re.search(r"<html|<head|<body", content, re.I):
            raise RuntimeError("Non-HTML content returned")
        return content
    except Exception as e:
        raise RuntimeError(f"Oxylabs HTML fetch failed: {e}")

# ---- Oxylabs image fetch: proxy-based (primary) ----
def oxy_fetch_binary_via_proxy(url: str, timeout: int = 60) -> Optional[bytes]:
    user, pwd = _oxy_creds()
    if not user or not pwd:
        return None

    proxies = {
        "http":  f"http://{user}:{pwd}@realtime.oxylabs.io:60000",
        "https": f"http://{user}:{pwd}@realtime.oxylabs.io:60000",
    }

    try:
        url = _normalize_url(url)
        headers = {
            "User-Agent": UA,
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            "Accept-Language": ACCEPT_LANG,
            "Referer": BASE_HOST + "/",
        }

        r = requests.get(url, proxies=proxies, headers=headers, timeout=timeout)
        if r.status_code == 200 and r.content:
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "image" in ctype:
                return r.content
            return r.content

        return None
    except Exception:
        return None

# ---- Oxylabs image fetch: realtime API (fallback) ----
def oxy_fetch_binary_realtime(
    url: str, accept_lang: str = ACCEPT_LANG, timeout: int = 60
) -> Optional[bytes]:
    url = _normalize_url(url)
    payload = {
        "source": "universal",
        "url": url,
        "parse": False,
        "user_agent_type": "desktop",
        "geo_location": "United Kingdom",
        "content_encoding": "base64",
        "headers": {
            "Accept-Language": accept_lang,
            "User-Agent": UA,
            "Referer": BASE_HOST + "/",
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        },
    }

    try:
        resp = _oxy_call(payload, timeout=timeout)
        res = (resp.get("results") or [{}])[0]

        content = res.get("content")
        encoding = (res.get("content_encoding") or res.get("encoding") or "").lower()

        if not content:
            return None

        if encoding == "base64":
            try:
                return base64.b64decode(content)
            except Exception:
                return None

        if isinstance(content, bytes):
            return content

        if isinstance(content, str):
            try:
                return base64.b64decode(content)
            except Exception:
                return None

        return None
    except Exception:
        return None


# ===============================
# Page Validation - DETECT INVALID PAGES
# ===============================
def _is_category_or_listing_page(soup: BeautifulSoup, url: str) -> bool:
    """
    Detect if the page is a category/listing page instead of a product detail page.
    Returns True if it's NOT a valid product page.
    """
    # Check 1: URL pattern - category pages end with /c/XXXX
    if re.search(r"/c/\d+", url) or re.search(r"/c/[a-zA-Z\-]+$", url):
        return True
    
    # Check 2: Pagination bar with "X products found" - strong indicator
    pagination_results = soup.select_one(".pagination-bar-results")
    if pagination_results:
        text = _clean(pagination_results.get_text())
        if re.search(r"\d+\s*products?\s*found", text, re.I):
            return True
    
    # Check 3: Product grid/listing containers (only if no PDP elements present)
    has_pdp_price = bool(soup.select_one("div.pdp-price, [class*='pdp-price']"))
    has_pdp_gallery = bool(soup.select_one(".pdp-image-gallery"))
    
    if not has_pdp_price and not has_pdp_gallery:
        listing_selectors = [
            ".product-listing",
            ".product-grid",
            ".category-products",
            "[class*='product-list']",
        ]
        for sel in listing_selectors:
            if soup.select_one(sel):
                return True
        
        # Multiple product tiles without PDP elements = listing page
        product_tiles = soup.select(".product-tile, .product-card")
        if len(product_tiles) > 5:
            return True
    
    return False


def _is_product_unavailable(soup: BeautifulSoup) -> Tuple[bool, Optional[str]]:
    """
    Detect if the product page shows the product as unavailable/discontinued.
    Only checks SPECIFIC product-related elements, not the entire page.
    Returns (is_unavailable, reason)
    """
    # Check 1: Specific unavailability elements in the product area
    product_area_selectors = [
        ".pdp-content",
        ".product-detail",
        "[class*='product-main']",
        "main",
        "#content",
    ]
    
    product_area = None
    for sel in product_area_selectors:
        product_area = soup.select_one(sel)
        if product_area:
            break
    
    if not product_area:
        product_area = soup  # Fallback to whole page but be more careful
    
    # Check for explicit unavailability messages in the product area
    unavailable_selectors = [
        ".product-unavailable",
        ".product-discontinued",
        "[class*='not-available']",
        "[class*='unavailable-message']",
        ".out-of-stock-message",
    ]
    
    for sel in unavailable_selectors:
        el = product_area.select_one(sel)
        if el:
            text = _clean(el.get_text())
            if text:
                return True, text
    
    # Check 2: Look for specific "product not available" messages
    # Only in specific containers, NOT site-wide
    message_containers = product_area.select(
        ".pdp-panel, .product-info, .product-message, .alert, .notification"
    )
    
    for container in message_containers:
        text = _clean(container.get_text()).lower()
        # Very specific patterns - must be about THIS product
        if re.search(r"this (product|item) is (no longer|not) available", text):
            return True, "Product is no longer available"
        if re.search(r"(product|item) has been discontinued", text):
            return True, "Product has been discontinued"
        if re.search(r"(product|item) no longer (exists|available)", text):
            return True, "Product no longer exists"
    
    # Check 3: 404-style page detection
    title = soup.title.string if soup.title else ""
    if re.search(r"page not found|404|not found", title, re.I):
        return True, "Page not found (404)"
    
    # Check for error page indicators
    error_selectors = [".error-page", ".page-not-found", "#error-container"]
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
    
    # Check if product is explicitly marked unavailable
    is_unavailable, unavailable_reason = _is_product_unavailable(soup)
    if is_unavailable:
        return False, unavailable_reason or "Product is no longer available"
    
    # For Wilko specifically, check for essential PDP elements
    # A valid Wilko PDP should have at least some of these
    pdp_indicators = {
        "pdp_price": bool(soup.select_one("div.pdp-price, [class*='pdp-price']")),
        "pdp_gallery": bool(soup.select_one(".pdp-image-gallery, .pdp-image-gallery-thumbnails")),
        "product_title": bool(soup.select_one("h1.name[itemprop='name'], .product-title h1")),
        "add_to_basket": bool(soup.select_one("[class*='add-to-basket'], [class*='add-to-cart']")),
        "product_widget": bool(soup.select_one(".product-widget, .pdp-panel")),
    }
    
    # Count how many indicators are present
    indicator_count = sum(pdp_indicators.values())
    
    # If we have at least 2 PDP indicators, it's likely a valid product page
    if indicator_count >= 2:
        return True, ""
    
    # If URL looks like a product URL (/p/XXXXXX) but lacks PDP elements,
    # it might be that the product was removed
    if re.search(r"/p/\d+", url) and indicator_count == 0:
        return False, "Product page structure not found - product may have been removed"
    
    # If we have some indicators, accept it cautiously
    if indicator_count >= 1:
        return True, ""
    
    return False, "Page does not contain expected product detail elements"


# ===============================
# Invalid Result Generator
# ===============================
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
        "images": [],
        "folder": None,
        "mode": "invalid",
        "is_valid": False,
        "invalid_reason": reason,
    }


# ===============================
# Wilko PDP parsers
# ===============================
def _jsonld_availability(soup: BeautifulSoup) -> Optional[bool]:
    try:
        for sc in soup.select("script[type='application/ld+json']"):
            raw = sc.string or sc.get_text() or ""
            try:
                data = json.loads(raw)
            except Exception:
                continue
            objs = data if isinstance(data, list) else [data]
            for o in objs:
                if not isinstance(o, dict):
                    continue
                offers = o.get("offers")
                if not offers and isinstance(o.get("@graph"), list):
                    for g in o["@graph"]:
                        if isinstance(g, dict) and g.get("@type") == "Product":
                            offers = g.get("offers")
                            if offers:
                                break
                if not offers:
                    continue
                lst = offers if isinstance(offers, list) else [offers]
                for off in lst:
                    if not isinstance(off, dict):
                        continue
                    avail = str(
                        off.get("availability") or off.get("itemAvailability") or ""
                    )
                    if re.search(r"InStock", avail, re.I):
                        return True
                    if re.search(r"OutOfStock|SoldOut", avail, re.I):
                        return False
        return None
    except Exception:
        return None

def _extract_name(soup: BeautifulSoup) -> str:
    h = soup.select_one(
        "div.product-title h1.name[itemprop='name'], h1.name[itemprop='name']"
    )
    if h:
        return _clean(h.get_text(" ", strip=True))
    t = soup.title.string if soup.title else ""
    return _clean((t or "").split("|")[0]) or "Unknown_Product"

def _extract_price(soup: BeautifulSoup) -> Tuple[str, str]:
    # Primary: PDP-specific price selectors
    for sel in ["div.pdp-price", "[class*='pdp-price']", ".product-price .price"]:
        el = soup.select_one(sel)
        if el:
            p = _parse_price(el.get_text(" ", strip=True))
            if p:
                return p, "onsite"
    
    # Secondary: Product widget price
    widget_price = soup.select_one(".product-widget__price, [itemprop='price']")
    if widget_price:
        p = _parse_price(widget_price.get_text(" ", strip=True))
        if p:
            return p, "widget"
    
    return "N/A", "none"

def _extract_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], Optional[str]]:
    el = soup.select_one("div.product-widget__stock")
    if el:
        t = _clean(el.get_text(" ", strip=True))
        if re.search(r"in stock", t, re.I):
            m = re.search(r"(\d+\+?)", t)
            return True, f"In stock ({m.group(1)})" if m else "In stock"
        if re.search(r"out of stock|sold out|not available", t, re.I):
            return False, "Out of stock"
    avail = _jsonld_availability(soup)
    if isinstance(avail, bool):
        return avail, "In stock" if avail else "Out of stock"

    # Check for add to basket button presence
    add_btn = soup.select_one("[class*='add-to-basket'], [class*='add-to-cart']")
    if add_btn:
        btn_text = _clean(add_btn.get_text()).lower()
        if "out of stock" not in btn_text and "unavailable" not in btn_text:
            return True, None
    
    return None, None

def _extract_description_and_images(
    soup: BeautifulSoup, max_images: Optional[int]
) -> Tuple[str, List[str]]:
    parts: List[str] = []

    info = (
        soup.select_one(".pdp-panel.product-information .pdp-panel__content")
        or soup.select_one(".pdp-panel__content")
    )

    # Bullet list / key features
    if info:
        bl = info.select_one(".list ul")
        if bl:
            bullets = [
                _clean(li.get_text(" ", strip=True))
                for li in bl.select("li")
                if _clean(li.get_text(" ", strip=True))
            ]
            if bullets:
                parts.append("• " + "\n• ".join(bullets))

    # Main description
    desc_el = None
    for sel in [
        ".cropped-desc-js.more-desc[itemprop='description']",
        ".cropped-desc-js.more-desc",
        "[itemprop='description']",
        ".product-description",
        ".pdp-panel__content .more-desc",
        ".pdp-panel__content [data-test='description']",
    ]:
        cand = soup.select_one(sel)
        if cand and _clean(cand.get_text(" ", strip=True)):
            desc_el = cand
            break

    if desc_el:
        text = desc_el.get_text("\n", strip=True)
        parts.append(_clean_multiline_preserve(text))

    # Specs (dl/specification)
    if info:
        spec = info.select("dl.specification-wrapper .specification-item")
        if spec:
            kv = []
            for it in spec:
                k_el = it.select_one(".specification-name")
                v_el = it.select_one(".specification-value")
                k = _clean(k_el.get_text(" ", strip=True)) if k_el else ""
                v = _clean(v_el.get_text(" ", strip=True)) if v_el else ""
                if k and v:
                    kv.append(f"{k} {v}")
            if kv:
                parts.append("\n".join(kv))

    description = _clean_multiline_preserve(
        "\n\n".join([p for p in parts if p])
    ) or ""

    # Images - Only extract from product gallery
    urls: List[str] = []
    
    # Primary: PDP image gallery thumbnails
    for img in soup.select(".pdp-image-gallery-thumbnails__slider img[src]"):
        u = img.get("src")
        if u:
            urls.append(_abs(u))
    
    # Secondary: Main gallery image
    if not urls:
        for img in soup.select(".pdp-image-gallery img[src], .product-gallery img[src]"):
            src = img.get("src") or ""
            urls.append(_abs(src))
    
    # Tertiary: Look for product images but EXCLUDE navigation/site images
    if not urls:
        exclude_patterns = [
            "/nav.", "-nav.", "logo", "icon", "banner", "promo",
            "christmas-nav", "garden-and-outdoor-nav", "offers-regular",
            "thumbnail", "sprite", "placeholder",
        ]
        for img in soup.select("img[src]"):
            src = img.get("src") or ""
            if any(k in src for k in ("/product/", "/media/catalog/", "/assets/")):
                if not any(ex in src.lower() for ex in exclude_patterns):
                    urls.append(_abs(src))

    urls = _dedupe_preserve_order(urls)
    if max_images is not None:
        urls = urls[:max_images]
    return description, urls

# ===============================
# Image download (force JPEG)
# ===============================
def _save_jpg_bytes(b: bytes, out_path: Path) -> bool:
    try:
        img = Image.open(BytesIO(b))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(out_path, format="JPEG", quality=92, optimize=True)
        return True
    except Exception:
        return False

def _download_images_jpg(
    img_urls: List[str], folder: Path, referer: Optional[str], verbose: bool
) -> List[str]:
    folder.mkdir(parents=True, exist_ok=True)
    saved: List[str] = []

    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept-Language": ACCEPT_LANG,
            "Referer": referer or "",
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        }
    )

    for idx, url in enumerate(img_urls, 1):
        out_path = folder / f"image_{idx}.jpg"

        b = oxy_fetch_binary_via_proxy(url, timeout=60)
        if b and _save_jpg_bytes(b, out_path):
            saved.append(str(out_path))
            _vprint(verbose, f"  ✓ (oxy-proxy) image_{idx}.jpg ← {url}")
            continue

        b = oxy_fetch_binary_realtime(url, accept_lang=ACCEPT_LANG, timeout=60)
        if b and _save_jpg_bytes(b, out_path):
            saved.append(str(out_path))
            _vprint(verbose, f"  ✓ (oxy-api) image_{idx}.jpg ← {url}")
            continue

        try:
            r = s.get(url, timeout=30)
            if r.ok and r.content and _save_jpg_bytes(r.content, out_path):
                saved.append(str(out_path))
                _vprint(verbose, f"  ✓ (direct) image_{idx}.jpg ← {url}")
            else:
                _vprint(verbose, f"  ! Failed all methods for {url}")
        except Exception as e:
            _vprint(verbose, f"  ! Error: {url} - {e}")

    return saved

# ===============================
# Main API
# ===============================
def scrape_wilko_oxylabs(
    url: str,
    download_images: bool = True,
    max_images: Optional[int] = 12,
    verbose: bool = True,
) -> Dict:
    """
    Scrape a Wilko product page via Oxylabs.
    - Validates that the URL is a legitimate product page
    - Returns None/invalid result for category pages or unavailable products
    - Uses proxy-based image fetching (more reliable)
    - All images saved as .jpg
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
        "images": [],
        "folder": "",
        "mode": "oxylabs(proxy)",
        "is_valid": True,
        "invalid_reason": None,
    }

    try:
        html_doc = oxy_fetch_html(url, accept_lang=ACCEPT_LANG, timeout=90)
    except Exception as e:
        _vprint(verbose, f"Failed to fetch URL: {e}")
        return _create_invalid_result(url, f"Failed to fetch page: {str(e)}")

    soup = BeautifulSoup(html_doc, "lxml")
    
    # Save HTML for debugging if needed
    if verbose:
        debug_file = DEBUG_DIR / f"wilko_debug_{_stable_id_from_url(url)}.html"
        try:
            debug_file.write_text(html_doc, encoding="utf-8")
            _vprint(verbose, f"Debug HTML saved to: {debug_file}")
        except Exception:
            pass

    # ========== VALIDATION CHECK ==========
    is_valid, invalid_reason = _is_valid_pdp(soup, url)
    if not is_valid:
        _vprint(verbose, f"⚠ Invalid page detected: {invalid_reason}")
        return _create_invalid_result(url, invalid_reason)
    # ======================================

    name = _extract_name(soup)
    price, price_src = _extract_price(soup)
    instock, stock_txt = _extract_stock(soup)
    description, img_urls = _extract_description_and_images(soup, max_images)

    # Post-extraction validation: if critical data is missing, check more carefully
    # But only fail if NOTHING was extracted
    if not name or name == "Unknown_Product":
        if price == "N/A" and not description and not img_urls:
            _vprint(verbose, "⚠ Could not extract any product data")
            return _create_invalid_result(url, "Could not extract product information")

    ts = time.strftime("%Y%m%d-%H%M%S")
    folder = DATA_DIR / f"wilko_{_safe_name(name)}_{_stable_id_from_url(url)}_{ts}"
    folder.mkdir(parents=True, exist_ok=True)

    result.update(
        {
            "name": name,
            "price": price,
            "price_source": price_src,
            "in_stock": instock,
            "stock_text": stock_txt,
            "description": description,
            "folder": str(folder),
        }
    )

    if download_images and img_urls:
        _vprint(verbose, f"Downloading {len(img_urls)} images as JPG …")
        saved = _download_images_jpg(img_urls, folder, referer=url, verbose=verbose)
        result["images"] = saved
        result["image_count"] = len(saved)
    else:
        result["image_count"] = len(img_urls)

    return result

# # ===============================
# # CLI (example)
# # ===============================
# if __name__ == "__main__":
#     import sys
    
#     # Default test URLs
#     TEST_URLS = [
#         # Category URL (should be invalid)
#         "https://www.wilko.com/en-uk/stationery-office/computer-mobile-tablet/mobile-phone-tablet-accessories/c/1000",
#         # Valid product URL
#         # "https://www.wilko.com/en-uk/vq-skylark-bees-earbuds/p/0637036",
#     ]
    
#     # Allow passing URL as command line argument
#     if len(sys.argv) > 1:
#         TEST_URLS = [sys.argv[1]]
    
#     for test_url in TEST_URLS:
#         print(f"\nTesting: {test_url}")
#         print("=" * 70)
#         data = scrape_wilko_oxylabs(
#             test_url, download_images=False, max_images=12, verbose=True
#         )
#         print(json.dumps(data, indent=2, ensure_ascii=False))
#         print()