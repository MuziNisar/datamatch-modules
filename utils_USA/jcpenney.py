













# # jcpenney_oxylabs.py
# # Python 3.9+
# # pip install requests beautifulsoup4 lxml

# from __future__ import annotations
# import os, re, json, hashlib, time
# from pathlib import Path
# from typing import Optional, List, Dict, Tuple
# from urllib.parse import urlparse, urldefrag

# import requests
# from requests.exceptions import RequestException
# from bs4 import BeautifulSoup

# # =========================
# # Config
# # =========================
# OXY_USER = os.getenv("OXY_USER", "Muzamil_wUDhn")   # set env or hardcode
# OXY_PASS = os.getenv("OXY_PASS", "Muzamil_13111")

# UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
# ACCEPT_LANG = "en-US,en;q=0.9"

# BASE_DIR = Path(__file__).resolve().parent
# DATA_DIR = BASE_DIR / "data_us"
# DATA_DIR.mkdir(parents=True, exist_ok=True)

# SITE_TAG = "jcpenney"

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
#         url, _frag = urldefrag(url)
#         path = urlparse(url).path.strip("/").split("/")
#         last = (path[-1] if path else "") or url
#         return re.sub(r"[^\w\-]+", "", last) or hashlib.sha1(url.encode()).hexdigest()[:12]
#     except Exception:
#         return hashlib.sha1(url.encode()).hexdigest()[:12]

# def _dedupe_preserve(urls: List[str]) -> List[str]:
#     seen, out = set(), []
#     for u in urls:
#         # Deduplicate by full URL (including wid/hei) to keep exact served sizes
#         k = u
#         if k and k not in seen:
#             seen.add(k); out.append(u)
#     return out

# def _ensure_http(u: str) -> str:
#     if not u:
#         return u
#     # JCP Scene7 often starts with //jcpenney.scene7.com/...
#     if u.startswith("//"):
#         return "https:" + u
#     return u

# def _parse_usd(text: str) -> Optional[Tuple[float, str, str]]:
#     """
#     Returns (value_float, currency, display_string), e.g. (150.0, 'USD', '150.00 USD')
#     """
#     if not text:
#         return None
#     m = re.search(r"\$\s*([\d.,]+)", text)
#     if not m:
#         m = re.search(r"\b([\d.,]+)\b", text)
#     if not m:
#         return None
#     raw = m.group(1).replace(",", "")
#     try:
#         val = float(raw)
#     except Exception:
#         return None
#     return val, "USD", f"{val:.2f} USD"

# def _first_jsonld(soup: BeautifulSoup) -> dict:
#     for tag in soup.find_all("script", type="application/ld+json"):
#         try:
#             obj = json.loads(tag.string or "")
#             if isinstance(obj, list):
#                 for it in obj:
#                     if isinstance(it, dict) and it.get("@type") in {"Product", "Offer"}:
#                         return it
#             elif isinstance(obj, dict) and obj.get("@type") in {"Product", "Offer"}:
#                 return obj
#         except Exception:
#             continue
#     return {}

# def _best_text(el) -> str:
#     return _clean(el.get_text(" ", strip=True)) if el else ""

# def _attr_chain(tag, *attrs) -> Optional[str]:
#     if not tag:
#         return None
#     for a in attrs:
#         v = tag.get(a)
#         if v:
#             return v
#     return None

# def _guess_ext(u: str, content_type: str) -> str:
#     m = re.search(r"\.(jpg|jpeg|png|webp|gif)(?:$|\?)", u, re.I)
#     if m:
#         return "." + m.group(1).lower().replace("jpeg", "jpg")
#     if content_type:
#         ct = content_type.lower()
#         if "jpeg" in ct: return ".jpg"
#         if "png"  in ct: return ".png"
#         if "webp" in ct: return ".webp"
#         if "gif"  in ct: return ".gif"
#     return ".jpg"

# # ----- image filters (keep product, drop promos) -----
# def _is_jcp_product_image(u: str, data_id: str = "", alt: str = "") -> bool:
#     u = _ensure_http(u or "")
#     # Strong allow: explicit product image markers
#     if data_id.startswith("product-image-block-s7image"):
#         return True
#     # Only accept Scene7 product namespace; reject promo/banners
#     if u.startswith("https://jcpenney.scene7.com/is/image/JCPenney/"):
#         bad = ("buy-more", "save-more", "promo", "badge", "logo", "icon")
#         if any(k in u.lower() for k in bad):
#             return False
#         return True
#     return False

# # =========================
# # Oxylabs client
# # =========================
# def oxy_post(payload: dict, retries: int = 3, backoff: float = 1.5) -> dict:
#     last_err = None
#     for attempt in range(1, retries + 1):
#         try:
#             r = requests.post(
#                 "https://realtime.oxylabs.io/v1/queries",
#                 auth=(OXY_USER, OXY_PASS),
#                 json=payload,
#                 timeout=90,
#             )
#             r.raise_for_status()
#             data = r.json()
#             results = data.get("results") or []
#             if not results:
#                 raise RuntimeError("Oxylabs: empty results")
#             content = results[0].get("content", "")
#             if "<html" not in content.lower():
#                 raise RuntimeError("Oxylabs: non-HTML content")
#             return data
#         except (RequestException, ValueError, RuntimeError) as e:
#             last_err = e
#             if attempt < retries:
#                 time.sleep(backoff ** attempt)
#             else:
#                 raise RuntimeError(f"Oxylabs failed after {retries} attempts: {e}") from e
#     raise last_err or RuntimeError("Oxylabs unknown error")

# def oxy_fetch_html(url: str, geo: str = "United States") -> str:
#     url, _frag = urldefrag(url)
#     payload = {
#         "source": "universal",
#         "url": url,
#         "render": "html",
#         "geo_location": geo,
#         "headers": {
#             "User-Agent": UA,
#             "Accept-Language": ACCEPT_LANG
#         }
#     }
#     data = oxy_post(payload)
#     return data["results"][0]["content"]

# # =========================
# # Image download (direct) — keeps original size (no upscaling)
# # =========================
# def download_images(urls: List[str], folder: Path, referer: str, max_images: Optional[int]=None) -> List[str]:
#     if max_images is not None:
#         urls = urls[:max_images]
#     saved = []
#     folder.mkdir(parents=True, exist_ok=True)
#     h = {
#         "User-Agent": UA,
#         "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#         "Accept-Language": ACCEPT_LANG,
#         "Referer": referer,
#     }
#     for i, u in enumerate(urls, 1):
#         u = _ensure_http(u)
#         try:
#             with requests.get(u, headers=h, timeout=30, stream=True) as r:
#                 ct = r.headers.get("Content-Type", "")
#                 if r.status_code == 200 and (ct.startswith("image/") or r.content):
#                     ext = _guess_ext(u, ct)
#                     out = folder / f"{i:02d}{ext}"
#                     with open(out, "wb") as f:
#                         for chunk in r.iter_content(chunk_size=65536):
#                             if chunk:
#                                 f.write(chunk)
#                     saved.append(str(out))
#                 else:
#                     print("  ! image HTTP", r.status_code, u, ct)
#         except Exception as e:
#             print("  ! image error:", u, e)
#     return saved

# # =========================
# # JCPenney parser
# # =========================
# def parse_jcpenney(html: str) -> Dict:
#     soup = BeautifulSoup(html, "lxml")
#     jld = _first_jsonld(soup)

#     # ---- name ----
#     name = _clean(jld.get("name", "")) if jld else ""
#     if not name:
#         el = soup.select_one("h1[data-automation-id='product-title'], h1#productTitle, h1#productTitle-false, h1")
#         name = _best_text(el) or (_clean(soup.title.get_text().split('|')[0]) if soup.title else "") or "Unknown Product"

#     # ---- price ----
#     price_value: Optional[float] = None
#     currency: Optional[str] = None
#     price_str, price_source = "N/A", "none"

#     offer = None
#     if jld:
#         offers = jld.get("offers")
#         if isinstance(offers, dict):
#             offer = offers
#         elif isinstance(offers, list) and offers:
#             offer = offers[0]
#         if offer:
#             try:
#                 price_value = float(str(offer.get("price", "")).replace(",", ""))
#                 currency = offer.get("priceCurrency", "USD")
#             except Exception:
#                 pass

#     if price_value is None:
#         price_el = soup.select_one("[data-automation-id='at-price-value'], .price, [class*='price']")
#         if not price_el:
#             price_el = soup.find(lambda t: t.name in ("span", "div") and t.get_text() and "$" in t.get_text())
#         if price_el:
#             parsed = _parse_usd(_best_text(price_el))
#             if parsed:
#                 price_value, currency, price_str = parsed
#                 price_source = "onsite"

#     if price_value is not None and currency:
#         price_str = f"{price_value:.2f} {currency}"
#         if price_source == "none":
#             price_source = "jsonld"

#     # ---- stock ----
#     in_stock, stock_text = None, ""
#     # JSON-LD first (can be stale)
#     if offer and isinstance(offer, dict):
#         avail = str(offer.get("availability", "")).lower()
#         if "instock" in avail:
#             in_stock, stock_text = True, "InStock (JSON-LD)"
#         elif any(x in avail for x in ["outofstock", "soldout", "oos"]):
#             in_stock, stock_text = False, "OutOfStock (JSON-LD)"

#     # On-page ATC overrides JSON-LD when explicit
#     atc_block = soup.select_one("[data-automation-id='addToCartBlock'], #GlobalOptions-AddToCart")
#     if atc_block:
#         btn = atc_block.find("button")
#         txt = _best_text(btn) if btn else ""
#         disabled = bool(btn and btn.has_attr("disabled"))
#         txt_l = txt.lower()
#         if "out of stock" in txt_l or disabled:
#             in_stock, stock_text = False, txt or "Out of Stock"
#         elif any(k in txt_l for k in ["add to cart", "ship it", "pickup"]):
#             in_stock, stock_text = True, txt

#     if in_stock is None:
#         body_txt = _clean(soup.get_text(" ", strip=True)).lower()
#         if "out of stock" in body_txt:
#             in_stock, stock_text = False, "Out of Stock"
#         elif any(w in body_txt for w in ["in stock", "available"]):
#             in_stock, stock_text = True, "In Stock"

#     # ---- description ----
#     desc_parts: List[str] = []
#     if jld and jld.get("description"):
#         desc_parts.append(_clean_multiline(jld["description"]))

#     desc_wrap = soup.select_one("#productDescriptionContainer, [aria-label='productDeccription']")
#     if desc_wrap:
#         for br in desc_wrap.find_all("br"):
#             br.replace_with("\n")
#         desc_parts.append(_clean_multiline(desc_wrap.get_text("\n", strip=True)))

#     description = _clean_multiline("\n\n".join([d for d in desc_parts if d]))

#     # ---- images (filtered; keep served size, no upscaling) ----
#     imgs: List[str] = []

#     # Prefer explicit carousel/product images; filter promos
#     candidates: List[str] = []
#     for img in soup.select(".carousel img[src], img[data-automation-id^='product-image-block-s7image'], img[src*='scene7']"):
#         u = _attr_chain(img, "srcset", "data-srcset", "data-src", "src")
#         if not u:
#             continue
#         if " " in u:  # handle srcset-like value
#             u = u.split()[0]
#         u = _ensure_http(u)
#         data_id = img.get("data-automation-id", "")
#         alt = img.get("alt", "")
#         if _is_jcp_product_image(u, data_id=data_id, alt=alt):
#             candidates.append(u)

#     # JSON-LD images (only keep if they pass product filter)
#     if jld:
#         jimgs = []
#         if isinstance(jld.get("image"), list):
#             jimgs = [u for u in jld["image"] if isinstance(u, str)]
#         elif isinstance(jld.get("image"), str):
#             jimgs = [jld["image"]]
#         for u in jimgs:
#             u = _ensure_http(u)
#             if _is_jcp_product_image(u):
#                 candidates.append(u)

#     imgs = _dedupe_preserve(candidates)

#     return {
#         "name": name,
#         "price": price_str,
#         "price_value": price_value,
#         "currency": currency or "USD",
#         "price_source": price_source,
#         "in_stock": in_stock,
#         "stock_text": stock_text,
#         "description": description,
#         "image_urls": imgs
#     }

# # =========================
# # Orchestrator
# # =========================
# def scrape_jcpenney_with_oxylabs(url: str,
#                                  download_images_flag: bool = True,
#                                  max_images: Optional[int] = None,
#                                  geo: str = "United States") -> Dict:
#     html = oxy_fetch_html(url, geo=geo)
#     parsed = parse_jcpenney(html)

#     folder = DATA_DIR / f"{SITE_TAG}_{_safe_name(parsed['name'])}_{_stable_id_from_url(url)}"
#     folder.mkdir(parents=True, exist_ok=True)

#     images_downloaded: List[str] = []
#     if download_images_flag and parsed["image_urls"]:
#         print(f"Downloading {len(parsed['image_urls']) if not max_images else min(len(parsed['image_urls']), max_images)} images …")
#         images_downloaded = download_images(parsed["image_urls"], folder, referer=url, max_images=max_images)

#     return {
#         "url": url,
#         "name": parsed["name"],
#         "price": parsed["price"],
#         "price_value": parsed["price_value"],
#         "currency": parsed["currency"],
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
# # 
# #  =========================
# # CLI
# # =========================
# if __name__ == "__main__":
#     TEST_URL = "https://www.jcpenney.com/p/laura-ashley-17-liter-dome-kettle/ppr5008464649?pTmplType=regular&catId=SearchResults&searchTerm=LAURA+ASHLEY+JUG+KETTLE&productGridView=medium"
#     data = scrape_jcpenney_with_oxylabs(TEST_URL, download_images_flag=True, max_images=12)
#     print(json.dumps(data, indent=2, ensure_ascii=False))












# jcpenney_oxylabs.py
# Python 3.9+
# pip install requests beautifulsoup4 lxml

from __future__ import annotations
import re, json, hashlib, time, uuid
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any
from urllib.parse import urlparse, urldefrag

import requests
from requests.exceptions import RequestException
from bs4 import BeautifulSoup

# =========================
# Config
# =========================
# Use local secrets file (keep credentials out of source)
from oxylabs_secrets import OXY_USER, OXY_PASS  # <-- make sure this exists

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
ACCEPT_LANG = "en-US,en;q=0.9"

try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()

DATA_DIR = BASE_DIR / "data_us"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SITE_TAG = "jcpenney"

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
        url, _frag = urldefrag(url)
        path = urlparse(url).path.strip("/").split("/")
        last = (path[-1] if path else "") or url
        return re.sub(r"[^\w\-]+", "", last) or hashlib.sha1(url.encode()).hexdigest()[:12]
    except Exception:
        return hashlib.sha1(url.encode()).hexdigest()[:12]

def _unique_suffix() -> str:
    t = int(time.time() * 1000) % 10_000_000
    u = uuid.uuid4().hex[:6]
    return f"{t}_{u}"

def _dedupe_preserve(urls: List[str]) -> List[str]:
    seen, out = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u); out.append(u)
    return out

def _ensure_http(u: str) -> str:
    if not u:
        return u
    if u.startswith("//"):
        return "https:" + u
    return u

def _parse_usd(text: str) -> Optional[Tuple[float, str, str]]:
    if not text:
        return None
    m = re.search(r"\$\s*([\d.,]+)", text)
    if not m:
        m = re.search(r"\b([\d.,]+)\b", text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        val = float(raw)
    except Exception:
        return None
    return val, "USD", f"{val:.2f} USD"

def _first_jsonld(soup: BeautifulSoup) -> dict:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(tag.string or "")
            if isinstance(obj, list):
                for it in obj:
                    if isinstance(it, dict) and it.get("@type") in {"Product", "Offer"}:
                        return it
            elif isinstance(obj, dict) and obj.get("@type") in {"Product", "Offer"}:
                return obj
        except Exception:
            continue
    return {}

def _best_text(el) -> str:
    return _clean(el.get_text(" ", strip=True)) if el else ""

def _attr_chain(tag, *attrs) -> Optional[str]:
    if not tag:
        return None
    for a in attrs:
        v = tag.get(a)
        if v:
            return v
    return None

def _guess_ext(u: str, content_type: str) -> str:
    m = re.search(r"\.(jpg|jpeg|png|webp|gif)(?:$|\?)", u, re.I)
    if m:
        return "." + m.group(1).lower().replace("jpeg", "jpg")
    if content_type:
        ct = content_type.lower()
        if "jpeg" in ct: return ".jpg"
        if "png"  in ct: return ".png"
        if "webp" in ct: return ".webp"
        if "gif"  in ct: return ".gif"
    return ".jpg"

# ----- image filters (keep product, drop promos) -----
def _is_jcp_product_image(u: str, data_id: str = "", alt: str = "") -> bool:
    u = _ensure_http(u or "")
    # Strong allow: explicit product image markers
    if data_id.startswith("product-image-block-s7image"):
        return True
    # Only accept Scene7 product namespace; reject promo/banners
    if u.startswith("https://jcpenney.scene7.com/is/image/JCPenney/"):
        bad = ("buy-more", "save-more", "promo", "badge", "logo", "icon")
        if any(k in u.lower() for k in bad):
            return False
        return True
    return False

# =========================
# Oxylabs client
# =========================
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": UA,
    "Accept": "application/json",
    "Content-Type": "application/json",
})

def _browser_instructions_light() -> List[Dict[str, Any]]:
    # Nudge page + bottom scroll to trigger lazy loads
    return [
        {"type": "wait_for_element",
         "selector": {"type": "css", "value": "body"},
         "timeout_s": 12},
        {"type": "scroll_to_bottom", "timeout_s": 8},
        {"type": "wait", "wait_time_s": 0.7},
    ]

def _browser_instructions_aggressive() -> List[Dict[str, Any]]:
    # Focus the gallery + description regions explicitly
    return [
        {"type": "wait_for_element",
         "selector": {"type": "css", "value": "body"},
         "timeout_s": 15},
        {"type": "wait_for_element",
         "selector": {"type": "css", "value": ".carousel img, img[src*='scene7'], #productDescriptionContainer"},
         "timeout_s": 12},
        {"type": "scroll_element_into_view",
         "selector": {"type": "css", "value": ".carousel, #productDescriptionContainer"},
         "timeout_s": 8},
        {"type": "scroll_by", "x": 0, "y": 600, "timeout_s": 4},
        {"type": "wait", "wait_time_s": 0.6},
        {"type": "scroll_by", "x": 0, "y": -400, "timeout_s": 4},
        {"type": "wait", "wait_time_s": 0.6},
        {"type": "scroll_to_bottom", "timeout_s": 8},
        {"type": "wait", "wait_time_s": 0.8},
    ]

def oxy_post(payload: dict, retries: int = 3, backoff: float = 1.5) -> dict:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = _SESSION.post(
                "https://realtime.oxylabs.io/v1/queries",
                auth=(OXY_USER, OXY_PASS),
                data=json.dumps(payload),
                timeout=120,
            )
            r.raise_for_status()
            data = r.json()
            results = data.get("results") or []
            if not results:
                raise RuntimeError("Oxylabs: empty results")
            content = results[0].get("content", "")
            if "<html" not in content.lower():
                raise RuntimeError("Oxylabs: non-HTML content")
            return data
        except (RequestException, ValueError, RuntimeError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff ** attempt)
            else:
                raise RuntimeError(f"Oxylabs failed after {retries} attempts: {e}") from e
    raise last_err or RuntimeError("Oxylabs unknown error")

def oxy_fetch_html(url: str, geo: str = "United States", aggressive: bool = False) -> str:
    url, _frag = urldefrag(url)
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
        "geo_location": geo,
        "headers": {
            "User-Agent": UA,
            "Accept-Language": ACCEPT_LANG
        },
        "browser_instructions": _browser_instructions_aggressive() if aggressive else _browser_instructions_light(),
    }
    try:
        data = oxy_post(payload)
    except Exception:
        # Fallback without instructions (some accounts prefer the simpler shape)
        payload2 = {
            "source": "universal",
            "url": url,
            "render": "html",
            "geo_location": geo,
            "headers": {"User-Agent": UA, "Accept-Language": ACCEPT_LANG},
        }
        data = oxy_post(payload2)
    return data["results"][0]["content"]

# =========================
# Image download (direct)
# =========================
def download_images(urls: List[str], folder: Path, referer: str, max_images: Optional[int]=None) -> List[str]:
    if max_images is not None:
        urls = urls[:max_images]
    saved = []
    folder.mkdir(parents=True, exist_ok=True)
    h = {
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Referer": referer,
    }
    for i, u in enumerate(urls, 1):
        u = _ensure_http(u)
        try:
            with requests.get(u, headers=h, timeout=30, stream=True) as r:
                ct = r.headers.get("Content-Type", "")
                if r.status_code == 200 and (ct.startswith("image/") or r.content):
                    ext = _guess_ext(u, ct)
                    out = folder / f"{i:02d}{ext}"
                    with open(out, "wb") as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                    saved.append(str(out))
                else:
                    print("  ! image HTTP", r.status_code, u, ct)
        except Exception as e:
            print("  ! image error:", u, e)
    return saved

# =========================
# JCPenney parser
# =========================
def parse_jcpenney(html: str) -> Dict:
    soup = BeautifulSoup(html, "lxml")
    jld = _first_jsonld(soup)

    # ---- name ----
    name = _clean(jld.get("name", "")) if jld else ""
    if not name:
        el = soup.select_one("h1[data-automation-id='product-title'], h1#productTitle, h1#productTitle-false, h1")
        name = _best_text(el) or (_clean(soup.title.get_text().split('|')[0]) if soup.title else "") or "Unknown Product"

    # ---- price ----
    price_value: Optional[float] = None
    currency: Optional[str] = None
    price_str, price_source = "N/A", "none"

    offer = None
    if jld:
        offers = jld.get("offers")
        if isinstance(offers, dict):
            offer = offers
        elif isinstance(offers, list) and offers:
            offer = offers[0]
        if offer:
            try:
                price_value = float(str(offer.get("price", "")).replace(",", ""))
                currency = offer.get("priceCurrency", "USD")
            except Exception:
                pass

    if price_value is None:
        price_el = soup.select_one("[data-automation-id='at-price-value'], .price, [class*='price']")
        if not price_el:
            price_el = soup.find(lambda t: t.name in ("span", "div") and t.get_text() and "$" in t.get_text())
        if price_el:
            parsed = _parse_usd(_best_text(price_el))
            if parsed:
                price_value, currency, price_str = parsed
                price_source = "onsite"

    if price_value is not None and currency:
        price_str = f"{price_value:.2f} {currency}"
        if price_source == "none":
            price_source = "jsonld"

    # ---- stock ----
    in_stock, stock_text = None, ""
    if offer and isinstance(offer, dict):
        avail = str(offer.get("availability", "")).lower()
        if "instock" in avail:
            in_stock, stock_text = True, "InStock (JSON-LD)"
        elif any(x in avail for x in ["outofstock", "soldout", "oos"]):
            in_stock, stock_text = False, "OutOfStock (JSON-LD)"

    atc_block = soup.select_one("[data-automation-id='addToCartBlock'], #GlobalOptions-AddToCart")
    if atc_block:
        btn = atc_block.find("button")
        txt = _best_text(btn) if btn else ""
        disabled = bool(btn and btn.has_attr("disabled"))
        txt_l = txt.lower()
        if "out of stock" in txt_l or disabled:
            in_stock, stock_text = False, txt or "Out of Stock"
        elif any(k in txt_l for k in ["add to cart", "ship it", "pickup"]):
            in_stock, stock_text = True, txt

    if in_stock is None:
        body_txt = _clean(soup.get_text(" ", strip=True)).lower()
        if "out of stock" in body_txt:
            in_stock, stock_text = False, "Out of Stock"
        elif any(w in body_txt for w in ["in stock", "available"]):
            in_stock, stock_text = True, "In Stock"

    # ---- description ----
    desc_parts: List[str] = []
    if jld and jld.get("description"):
        desc_parts.append(_clean_multiline(jld["description"]))

    desc_wrap = soup.select_one("#productDescriptionContainer, [aria-label='productDeccription']")
    if desc_wrap:
        for br in desc_wrap.find_all("br"):
            br.replace_with("\n")
        desc_parts.append(_clean_multiline(desc_wrap.get_text("\n", strip=True)))

    description = _clean_multiline("\n\n".join([d for d in desc_parts if d]))

    # ---- images (filtered; keep served size) ----
    candidates: List[str] = []

    for img in soup.select(".carousel img[src], img[data-automation-id^='product-image-block-s7image'], img[src*='scene7']"):
        u = _attr_chain(img, "srcset", "data-srcset", "data-src", "src")
        if not u:
            continue
        if " " in u:  # srcset-like value
            u = u.split()[0]
        u = _ensure_http(u)
        data_id = img.get("data-automation-id", "")
        alt = img.get("alt", "")
        if _is_jcp_product_image(u, data_id=data_id, alt=alt):
            candidates.append(u)

    if jld:
        jimgs = []
        if isinstance(jld.get("image"), list):
            jimgs = [u for u in jld["image"] if isinstance(u, str)]
        elif isinstance(jld.get("image"), str):
            jimgs = [jld["image"]]
        for u in jimgs:
            u = _ensure_http(u)
            if _is_jcp_product_image(u):
                candidates.append(u)

    imgs = _dedupe_preserve(candidates)

    return {
        "name": name,
        "price": price_str,
        "price_value": price_value,
        "currency": currency or "USD",
        "price_source": price_source,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_urls": imgs
    }

# =========================
# Orchestrator
# =========================
def scrape_jcpenney_with_oxylabs(url: str,
                                 download_images_flag: bool = True,
                                 max_images: Optional[int] = None,
                                 geo: str = "United States") -> Dict:
    """
    Same function name/signature/return as before.
    Adds light->aggressive Oxylabs render and unique output folder per run.
    """
    # First, light render
    html1 = oxy_fetch_html(url, geo=geo, aggressive=False)
    parsed = parse_jcpenney(html1)

    # If images/description look sparse, retry with aggressive render
    need_imgs = not parsed["image_urls"] or len(parsed["image_urls"]) < 2
    need_desc = (not parsed["description"]) or (len(parsed["description"]) < 60)
    if need_imgs or need_desc:
        html2 = oxy_fetch_html(url, geo=geo, aggressive=True)
        parsed = parse_jcpenney(html2)

    # unique folder each run
    folder = DATA_DIR / f"{SITE_TAG}_{_safe_name(parsed['name'])}_{_stable_id_from_url(url)}_{_unique_suffix()}"
    folder.mkdir(parents=True, exist_ok=True)

    images_downloaded: List[str] = []
    if download_images_flag and parsed["image_urls"]:
        images_downloaded = download_images(parsed["image_urls"], folder, referer=url, max_images=max_images)

    return {
        "url": url,
        "name": parsed["name"],
        "price": parsed["price"],
        "price_value": parsed["price_value"],
        "currency": parsed["currency"],
        "price_source": parsed["price_source"],
        "in_stock": parsed["in_stock"],
        "stock_text": parsed["stock_text"],
        "description": parsed["description"],
        "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
        "image_urls": parsed["image_urls"],
        "images_downloaded": images_downloaded,
        "folder": str(folder),
        "mode": "oxylabs-universal"
    }

# # =========================
# # CLI (unchanged)
# # =========================
# if __name__ == "__main__":
#     TEST_URL = "https://www.jcpenney.com/p/laura-ashley-17-liter-dome-kettle/ppr5008464649?pTmplType=regular&catId=SearchResults&searchTerm=LAURA+ASHLEY+JUG+KETTLE&productGridView=medium"
#     data = scrape_jcpenney_with_oxylabs(TEST_URL, download_images_flag=True, max_images=12)
#     print(json.dumps(data, indent=2, ensure_ascii=False))





