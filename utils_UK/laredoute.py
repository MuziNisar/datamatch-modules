


# # laredoute_oxylabs.py
# # Python 3.9+
# # pip install requests beautifulsoup4 lxml
# # Version: 2.0 - Fixed credentials to use oxylabs_secrets.py

# from __future__ import annotations
# import os, re, json, hashlib, time, base64
# from pathlib import Path
# from typing import Optional, List, Dict, Tuple
# from urllib.parse import urlparse, urldefrag

# import requests
# from requests.exceptions import RequestException
# from bs4 import BeautifulSoup

# __version__ = "2.0"

# # =========================
# # Config
# # =========================
# UA = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
# )
# ACCEPT_LANG = "en-GB,en;q=0.9"

# BASE_DIR = Path(__file__).resolve().parent
# DATA_DIR = BASE_DIR / "data_uk"
# DATA_DIR.mkdir(parents=True, exist_ok=True)

# SITE_TAG = "laredoute"
# BASE_HOST = "https://www.laredoute.co.uk"

# # =========================
# # Credentials (from oxylabs_secrets.py or environment)
# # =========================
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS
# except Exception:
#     OXY_USER = os.getenv("OXYLABS_USERNAME") or os.getenv("OXY_USER", "")
#     OXY_PASS = os.getenv("OXYLABS_PASSWORD") or os.getenv("OXY_PASS", "")

# if not (OXY_USER and OXY_PASS):
#     raise RuntimeError("Oxylabs credentials missing. Create oxylabs_secrets.py with OXY_USER/OXY_PASS or set environment variables.")

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
#         k = u.split("?")[0]
#         if k and k not in seen:
#             seen.add(k)
#             out.append(u)
#     return out

# def _parse_gbp(text: str) -> Optional[Tuple[float, str, str]]:
#     """
#     Returns (value_float, currency, display_string), e.g. (60.0, 'GBP', '60.00 GBP')
#     """
#     if not text:
#         return None
#     m = re.search(r"£\s*([\d.,]+)", text) or re.search(r"\b([\d.,]+)\b\s*£", text)
#     if not m:
#         m = re.search(r"\b([\d.,]+)\b", text)
#     if not m:
#         return None
#     raw = m.group(1).replace(",", "")
#     try:
#         val = float(raw)
#     except Exception:
#         return None
#     disp = f"{val:.2f} GBP"
#     return val, "GBP", disp

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

# def _parse_srcset_max(srcset: str) -> Optional[str]:
#     """
#     Choose the largest candidate from a srcset string.
#     """
#     if not srcset:
#         return None
#     best_url, best_w = None, -1
#     for part in srcset.split(","):
#         p = part.strip()
#         if not p:
#             continue
#         url_w = p.split()
#         url = url_w[0]
#         w = 0
#         if len(url_w) > 1 and url_w[1].endswith("w"):
#             try:
#                 w = int(re.sub(r"\D", "", url_w[1]))
#             except Exception:
#                 w = 0
#         if w >= best_w:
#             best_w, best_url = w, url
#     return best_url

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

# def _normalize_url(u: str) -> str:
#     u = (u or "").strip()
#     if not u:
#         return u
#     if not re.match(r"^https?://", u, re.I):
#         u = "https://" + u
#     u = re.sub(r"\s+", "%20", u)
#     return u

# # =========================
# # Oxylabs client
# # =========================
# def oxy_post(payload: dict, retries: int = 3, backoff: float = 1.5) -> dict:
#     """
#     Generic Oxylabs POST wrapper for HTML (Web Scraper API Realtime).
#     """
#     if not OXY_USER or not OXY_PASS:
#         raise RuntimeError("Missing Oxylabs credentials.")

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
#             if "<html" not in content.lower() and payload.get("parse") is not False:
#                 raise RuntimeError("Oxylabs: non-HTML content")
#             return data
#         except (RequestException, ValueError, RuntimeError) as e:
#             last_err = e
#             if attempt < retries:
#                 time.sleep(backoff ** attempt)
#             else:
#                 raise RuntimeError(f"Oxylabs failed after {retries} attempts: {e}") from e
#     raise last_err or RuntimeError("Oxylabs unknown error")

# def oxy_fetch_html(url: str, geo: str = "United Kingdom") -> str:
#     """
#     Fetch HTML via Oxylabs Web Scraper API (universal source, render=html).
#     """
#     url, _frag = urldefrag(url)
#     url = _normalize_url(url)
#     payload = {
#         "source": "universal",
#         "url": url,
#         "render": "html",
#         "parse": False,
#         "geo_location": geo,
#         "user_agent_type": "desktop",
#         "headers": {
#             "User-Agent": UA,
#             "Accept-Language": ACCEPT_LANG,
#         },
#     }
#     data = oxy_post(payload)
#     return data["results"][0]["content"]

# # =========================
# # Oxylabs image fetch (proxy + realtime)
# # =========================
# def oxy_fetch_binary_via_proxy(url: str, referer: str, timeout: int = 60) -> Tuple[Optional[bytes], str]:
#     """
#     Fetch binary content (images) through Oxylabs Proxy Endpoint.
#     Returns (bytes_or_none, content_type).
#     """
#     if not OXY_USER or not OXY_PASS:
#         return None, ""

#     proxies = {
#         "http":  f"http://{OXY_USER}:{OXY_PASS}@realtime.oxylabs.io:60000",
#         "https": f"http://{OXY_USER}:{OXY_PASS}@realtime.oxylabs.io:60000",
#     }

#     try:
#         url = _normalize_url(url)
#         headers = {
#             "User-Agent": UA,
#             "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#             "Accept-Language": ACCEPT_LANG,
#             "Referer": referer or BASE_HOST + "/",
#             "x-oxylabs-user-agent-type": "desktop_chrome",
#             "x-oxylabs-geo-location": "United Kingdom",
#         }

#         r = requests.get(url, proxies=proxies, headers=headers, timeout=timeout)
#         if r.status_code == 200 and r.content:
#             ctype = r.headers.get("Content-Type", "")
#             return r.content, ctype
#         return None, ""
#     except Exception:
#         return None, ""

# def oxy_fetch_binary_realtime(url: str, referer: str, timeout: int = 60) -> Optional[bytes]:
#     """
#     Fetch binary asset via Oxylabs Web Scraper API (Realtime) as base64.
#     NOTE: This consumes Web Scraper API 'results' per image.
#     """
#     if not OXY_USER or not OXY_PASS:
#         return None

#     url = _normalize_url(url)
#     payload = {
#         "source": "universal",
#         "url": url,
#         "parse": False,
#         "user_agent_type": "desktop",
#         "geo_location": "United Kingdom",
#         "content_encoding": "base64",
#         "headers": {
#             "Accept-Language": ACCEPT_LANG,
#             "User-Agent": UA,
#             "Referer": referer or BASE_HOST + "/",
#             "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#         },
#     }

#     try:
#         data = oxy_post(payload)
#         res = (data.get("results") or [{}])[0]
#         content = res.get("content")
#         encoding = (res.get("content_encoding") or res.get("encoding") or "").lower()

#         if not content:
#             return None

#         if encoding == "base64":
#             try:
#                 return base64.b64decode(content)
#             except Exception:
#                 return None

#         if isinstance(content, bytes):
#             return content

#         if isinstance(content, str):
#             try:
#                 return base64.b64decode(content)
#             except Exception:
#                 return None

#         return None
#     except Exception:
#         return None

# # =========================
# # Image download
# # =========================
# def download_images(
#     urls: List[str],
#     folder: Path,
#     referer: str,
#     max_images: Optional[int] = None
# ) -> List[str]:
#     """
#     Download images for Laredoute products.
#     Strategy:
#       1) Try Oxylabs proxy endpoint.
#       2) Fallback to Web Scraper API Realtime (base64).
#       3) Final fallback: direct HTTP (may 403).
#     """
#     # Filter out broken srcset entries like "dpr=1/products/..."
#     urls = [u for u in urls if isinstance(u, str) and u.startswith("http")]
#     if max_images is not None:
#         urls = urls[:max_images]

#     saved: List[str] = []
#     folder.mkdir(parents=True, exist_ok=True)

#     session = requests.Session()
#     session.headers.update(
#         {
#             "User-Agent": UA,
#             "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#             "Accept-Language": ACCEPT_LANG,
#             "Referer": referer,
#         }
#     )

#     for i, u in enumerate(urls, 1):
#         # Method 1: Oxylabs proxy endpoint
#         data, ct_proxy = oxy_fetch_binary_via_proxy(u, referer=referer, timeout=60)
#         if data:
#             ext = _guess_ext(u, ct_proxy)
#             out = folder / f"{i:02d}{ext}"
#             try:
#                 with open(out, "wb") as f:
#                     f.write(data)
#                 saved.append(str(out))
#                 print(f"  ✓ (oxy-proxy) {out.name} ← {u}")
#                 continue
#             except Exception as e:
#                 print(f"  ! error writing proxy image {u}: {e}")

#         # Method 2: Web Scraper API Realtime (base64)
#         data_rt = oxy_fetch_binary_realtime(u, referer=referer, timeout=60)
#         if data_rt:
#             out = folder / f"{i:02d}.jpg"
#             try:
#                 with open(out, "wb") as f:
#                     f.write(data_rt)
#                 saved.append(str(out))
#                 print(f"  ✓ (oxy-api) {out.name} ← {u}")
#                 continue
#             except Exception as e:
#                 print(f"  ! error writing realtime image {u}: {e}")

#         # Method 3: Direct HTTP (fallback)
#         try:
#             with session.get(u, timeout=30, stream=True) as r:
#                 ct = r.headers.get("Content-Type", "")
#                 if r.status_code == 200 and (ct.startswith("image/") or r.content):
#                     ext = _guess_ext(u, ct)
#                     out = folder / f"{i:02d}{ext}"
#                     with open(out, "wb") as f:
#                         for chunk in r.iter_content(chunk_size=65536):
#                             if chunk:
#                                 f.write(chunk)
#                     saved.append(str(out))
#                     print(f"  ✓ (direct) {out.name} ← {u}")
#                 else:
#                     print("  ! image HTTP", r.status_code, u, ct)
#         except Exception as e:
#             print("  ! image error:", u, e)

#     return saved

# # =========================
# # La Redoute parser
# # =========================
# def parse_laredoute(html: str) -> Dict:
#     soup = BeautifulSoup(html, "lxml")
#     jld = _first_jsonld(soup)

#     # ---- name ----
#     name = _clean(jld.get("name", "")) if jld else ""
#     if not name:
#         el = soup.select_one(
#             "h1.pdp-title, h2.pdp-title, "
#             "[data-cerberus='txt_pdp_productName1'], "
#             "h1[itemprop='name'], h2[itemprop='name']"
#         )
#         if not el:
#             el = soup.select_one("h1, h2")
#         name = _best_text(el) or (
#             _clean(soup.title.get_text().split("|")[0]) if soup.title else ""
#         ) or "Unknown Product"

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
#                 currency = offer.get("priceCurrency", "GBP")
#             except Exception:
#                 pass

#     if price_value is None:
#         price_el = soup.select_one(
#             ".price .value, "
#             ".price, "
#             "[data-cerberus='txt_pdp_discountedPrice1'], "
#             "span.price__value, "
#             "[class*='showSalePriceAfter_'], "
#             ".product-price"
#         )
#         if not price_el:
#             price_el = soup.find(
#                 lambda t: t.name in ("span", "div") and t.get_text() and "£" in t.get_text()
#             )
#         if price_el:
#             parsed = _parse_gbp(_best_text(price_el))
#             if parsed:
#                 price_value, currency, price_str = parsed
#                 price_source = "onsite"

#     if price_value is not None and currency:
#         price_str = f"{price_value:.2f} {currency}"
#         if price_source == "none":
#             price_source = "jsonld"

#     # ---- stock ----
#     in_stock, stock_text = None, ""
#     if offer and isinstance(offer, dict):
#         avail = str(offer.get("availability", "")).lower()
#         if "instock" in avail:
#             in_stock, stock_text = True, "InStock (JSON-LD)"
#         elif any(x in avail for x in ["outofstock", "soldout", "oos"]):
#             in_stock, stock_text = False, "OutOfStock (JSON-LD)"

#     if in_stock is None:
#         stock_el = soup.select_one(
#             ".js--deliveryOrDelayMessage, "
#             "[data-cerberus='txt_pdp_stockDeliveryDate1']"
#         )
#         if stock_el:
#             txt = _best_text(stock_el).lower()
#             if "in stock" in txt:
#                 in_stock, stock_text = True, "In stock"
#             elif any(k in txt for k in ["out of stock", "unavailable"]):
#                 in_stock, stock_text = False, txt

#     if in_stock is None:
#         body_txt = _clean(soup.get_text(" ", strip=True)).lower()
#         if "in stock" in body_txt:
#             in_stock, stock_text = True, "In stock"
#         elif any(w in body_txt for w in ["out of stock", "unavailable", "sold out"]):
#             in_stock, stock_text = False, "Unavailable"

#     # ---- description ----
#     desc_parts: List[str] = []
#     if jld and jld.get("description"):
#         desc_parts.append(_clean_multiline(jld["description"]))

#     desc_box = soup.select_one(
#         "div.pdp-description, #productDescription, [id^='productDescription_']"
#     )
#     if desc_box:
#         head = desc_box.select_one(".pdp-description-title")
#         ref = desc_box.select_one("#productReference, [id^='productReference_']")
#         main = desc_box.select_one(
#             "#mainProductDescription, [id^='mainProductDescription']"
#         )
#         if main:
#             for tag in main.find_all(["br"]):
#                 tag.replace_with("\n")
#         parts = [head, ref, main]
#         for p in parts:
#             if p:
#                 desc_parts.append(
#                     _clean_multiline(p.get_text("\n", strip=True))
#                 )

#         attrs = desc_box.select_one(".pdp-description-attr")
#         if attrs:
#             desc_parts.append(
#                 _clean_multiline(attrs.get_text("\n", strip=True))
#             )

#     description = _clean_multiline("\n\n".join([d for d in desc_parts if d]))

#     # ---- images ----
#     imgs: List[str] = []

#     if jld:
#         if isinstance(jld.get("image"), list):
#             imgs += [u for u in jld["image"] if isinstance(u, str)]
#         elif isinstance(jld.get("image"), str):
#             imgs.append(jld["image"])

#     for fig in soup.select(
#         "[id^='prodCarousel_'] picture, .swipe picture, .pdp-carousel picture"
#     ):
#         best = None
#         for source in fig.find_all("source"):
#             url = _parse_srcset_max(source.get("srcset"))
#             if url:
#                 best = url
#         if not best:
#             img = fig.find("img")
#             if img:
#                 srcset = _attr_chain(img, "srcset", "data-srcset")
#                 if srcset:
#                     best = _parse_srcset_max(srcset)
#                 if not best:
#                     best = _attr_chain(img, "data-src", "src")
#         if best:
#             imgs.append(best)

#     if not imgs:
#         for img in soup.select("img[itemprop='image'], img[src*='laredoute.com']"):
#             u = _attr_chain(img, "srcset", "data-srcset", "data-src", "src")
#             if u:
#                 if " " in u:
#                     u = _parse_srcset_max(u) or u.split()[0]
#                 imgs.append(u)

#     imgs = _dedupe_preserve(imgs)

#     return {
#         "name": name,
#         "price": price_str,
#         "price_value": price_value,
#         "currency": currency or "GBP",
#         "price_source": price_source,
#         "in_stock": in_stock,
#         "stock_text": stock_text,
#         "description": description,
#         "image_urls": imgs,
#     }

# # =========================
# # Orchestrator
# # =========================
# def scrape_laredoute_with_oxylabs(
#     url: str,
#     download_images_flag: bool = True,
#     max_images: Optional[int] = None,
#     geo: str = "United Kingdom",
# ) -> Dict:
#     html = oxy_fetch_html(url, geo=geo)
#     parsed = parse_laredoute(html)

#     folder = DATA_DIR / f"{SITE_TAG}_{_safe_name(parsed['name'])}_{_stable_id_from_url(url)}"
#     folder.mkdir(parents=True, exist_ok=True)

#     images_downloaded: List[str] = []
#     if download_images_flag and parsed["image_urls"]:
#         print(
#             f"Downloading {len(parsed['image_urls']) if not max_images else min(len(parsed['image_urls']), max_images)} images …"
#         )
#         images_downloaded = download_images(
#             parsed["image_urls"],
#             folder,
#             referer=url,
#             max_images=max_images,
#         )

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
#         "image_count": len(images_downloaded)
#         if images_downloaded
#         else len(parsed["image_urls"]),
#         "image_urls": parsed["image_urls"],
#         "images_downloaded": images_downloaded,
#         "folder": str(folder),
#         "mode": "oxylabs-universal+proxy+api",
#     }

# # # =========================
# # # CLI
# # # =========================
# # if __name__ == "__main__":
# #     TEST_URL = "https://www.laredoute.co.uk/ppdp/prod-350344450.aspx#searchkeyword=LAURA%20ASHLEY&shoppingtool=search"
# #     data = scrape_laredoute_with_oxylabs(
# #         TEST_URL,
# #         download_images_flag=True,
# #         max_images=12,
# #     )
# #     print(json.dumps(data, indent=2, ensure_ascii=False))





# laredoute_oxylabs.py
# Python 3.9+
# pip install requests beautifulsoup4 lxml
# Version: 2.1 - Added retry logic for 204 errors and invalid link detection

from __future__ import annotations
import os, re, json, hashlib, time, base64, random
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from urllib.parse import urlparse, urldefrag

import requests
from requests.exceptions import RequestException
from bs4 import BeautifulSoup

__version__ = "2.2"

# =========================
# Config
# =========================
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
ACCEPT_LANG = "en-GB,en;q=0.9"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data_uk"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SITE_TAG = "laredoute"
BASE_HOST = "https://www.laredoute.co.uk"

# =========================
# Credentials (from oxylabs_secrets.py or environment)
# =========================
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = os.getenv("OXYLABS_USERNAME") or os.getenv("OXY_USER", "")
    OXY_PASS = os.getenv("OXYLABS_PASSWORD") or os.getenv("OXY_PASS", "")

if not (OXY_USER and OXY_PASS):
    raise RuntimeError("Oxylabs credentials missing. Create oxylabs_secrets.py with OXY_USER/OXY_PASS or set environment variables.")

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


def _extract_product_id_from_url(url: str) -> Optional[str]:
    """Extract product ID from La Redoute URL for validation."""
    # URL pattern: /ppdp/prod-350344450.aspx
    m = re.search(r"prod-(\d+)", url, re.I)
    return m.group(1) if m else None


def _dedupe_preserve(urls: List[str]) -> List[str]:
    seen, out = set(), []
    for u in urls:
        k = u.split("?")[0]
        if k and k not in seen:
            seen.add(k)
            out.append(u)
    return out


def _parse_gbp(text: str) -> Optional[Tuple[float, str, str]]:
    if not text:
        return None
    m = re.search(r"£\s*([\d.,]+)", text) or re.search(r"\b([\d.,]+)\b\s*£", text)
    if not m:
        m = re.search(r"\b([\d.,]+)\b", text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        val = float(raw)
    except Exception:
        return None
    disp = f"{val:.2f} GBP"
    return val, "GBP", disp


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


def _parse_srcset_max(srcset: str) -> Optional[str]:
    if not srcset:
        return None
    best_url, best_w = None, -1
    for part in srcset.split(","):
        p = part.strip()
        if not p:
            continue
        url_w = p.split()
        url = url_w[0]
        w = 0
        if len(url_w) > 1 and url_w[1].endswith("w"):
            try:
                w = int(re.sub(r"\D", "", url_w[1]))
            except Exception:
                w = 0
        if w >= best_w:
            best_w, best_url = w, url
    return best_url


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


def _normalize_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return u
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    u = re.sub(r"\s+", "%20", u)
    return u


# =========================
# Oxylabs client with RETRY LOGIC
# =========================
def oxy_post(payload: dict, retries: int = 3, backoff: float = 1.5, verbose: bool = False) -> dict:
    """
    Generic Oxylabs POST wrapper for HTML with retry logic for 204/400 errors.
    """
    if not OXY_USER or not OXY_PASS:
        raise RuntimeError("Missing Oxylabs credentials.")

    last_err = None
    consecutive_204 = 0
    session_failed_count = 0
    
    for attempt in range(1, retries + 1):
        try:
            if verbose:
                print(f"    Oxylabs attempt {attempt}/{retries}...")
            
            r = requests.post(
                "https://realtime.oxylabs.io/v1/queries",
                auth=(OXY_USER, OXY_PASS),
                json=payload,
                timeout=90,
            )
            
            # Success
            if r.status_code == 200:
                data = r.json()
                results = data.get("results") or []
                if not results:
                    raise RuntimeError("Oxylabs: empty results")
                content = results[0].get("content", "")
                if "<html" not in content.lower() and payload.get("parse") is not False:
                    raise RuntimeError("Oxylabs: non-HTML content")
                return data
            
            # HTTP 204 - No Content
            if r.status_code == 204:
                consecutive_204 += 1
                if verbose:
                    print(f"    ⚠ HTTP 204 (No Content) - count {consecutive_204}")
                
                if consecutive_204 >= 3:
                    raise RuntimeError("INVALID_PAGE:HTTP_204_REPEATED")
                
                time.sleep(backoff ** attempt)
                continue
            
            # HTTP 400 - Session failed
            if r.status_code == 400:
                try:
                    err_data = r.json()
                    err_msg = err_data.get("message", "")
                except Exception:
                    err_msg = r.text[:200]
                
                if "failed" in err_msg.lower() or "session" in err_msg.lower():
                    session_failed_count += 1
                    if verbose:
                        print(f"    ⚠ Session failed: {err_msg[:60]}")
                    
                    if consecutive_204 > 0 and session_failed_count >= 2:
                        raise RuntimeError("INVALID_PAGE:SESSION_FAILED_AFTER_204")
                    
                    time.sleep(backoff ** attempt)
                    continue
                
                raise RuntimeError(f"Oxylabs HTTP 400: {err_msg}")
            
            # Other errors
            r.raise_for_status()
            
        except (RequestException, ValueError, RuntimeError) as e:
            last_err = e
            err_str = str(e)
            
            # Check if this is our special "invalid page" signal
            if "INVALID_PAGE:" in err_str:
                raise
            
            if attempt < retries:
                time.sleep(backoff ** attempt)
            else:
                # Check if pattern suggests invalid page
                if consecutive_204 >= 2:
                    raise RuntimeError("INVALID_PAGE:FETCH_EXHAUSTED_204")
                raise RuntimeError(f"Oxylabs failed after {retries} attempts: {e}") from e
    
    if consecutive_204 >= 2:
        raise RuntimeError("INVALID_PAGE:EXHAUSTED_RETRIES")
    
    raise last_err or RuntimeError("Oxylabs unknown error")


def oxy_fetch_html(url: str, geo: str = "United Kingdom", verbose: bool = False) -> str:
    """
    Fetch HTML via Oxylabs Web Scraper API with retry logic.
    """
    url, _frag = urldefrag(url)
    url = _normalize_url(url)
    
    session_id = f"laredoute-{int(time.time())}-{random.randint(1000, 9999)}"
    
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
        "parse": False,
        "geo_location": geo,
        "user_agent_type": "desktop",
        "headers": {
            "User-Agent": UA,
            "Accept-Language": ACCEPT_LANG,
        },
        "context": [
            {"key": "session_id", "value": session_id}
        ],
        "rendering_wait": 3000,
    }
    
    max_attempts = 4
    last_err = None
    
    for attempt in range(max_attempts):
        # Update session ID for each attempt
        payload["context"] = [
            {"key": "session_id", "value": f"laredoute-{int(time.time())}-{random.randint(1000, 9999)}"}
        ]
        
        if verbose:
            print(f"  Attempt {attempt + 1}/{max_attempts}...")
        
        try:
            data = oxy_post(payload, retries=2, verbose=verbose)
            html = data["results"][0]["content"]
            
            if html and len(html) > 500:
                if verbose:
                    print(f"  ✓ Fetched {len(html):,} bytes")
                return html
            else:
                if verbose:
                    print(f"  ⚠ Short content ({len(html)} bytes), retrying...")
                last_err = RuntimeError("Short content")
                time.sleep(2)
                continue
                
        except RuntimeError as e:
            err_str = str(e)
            if "INVALID_PAGE:" in err_str:
                raise
            last_err = e
            if attempt < max_attempts - 1:
                time.sleep(2)
                continue
            raise
    
    raise last_err or RuntimeError("Oxylabs failed after all attempts")


# =========================
# Oxylabs image fetch (proxy + realtime)
# =========================
def oxy_fetch_binary_via_proxy(url: str, referer: str, timeout: int = 60) -> Tuple[Optional[bytes], str]:
    """
    Fetch binary content (images) through Oxylabs Proxy Endpoint.
    """
    if not OXY_USER or not OXY_PASS:
        return None, ""

    proxies = {
        "http":  f"http://{OXY_USER}:{OXY_PASS}@realtime.oxylabs.io:60000",
        "https": f"http://{OXY_USER}:{OXY_PASS}@realtime.oxylabs.io:60000",
    }

    try:
        url = _normalize_url(url)
        headers = {
            "User-Agent": UA,
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            "Accept-Language": ACCEPT_LANG,
            "Referer": referer or BASE_HOST + "/",
            "x-oxylabs-user-agent-type": "desktop_chrome",
            "x-oxylabs-geo-location": "United Kingdom",
        }

        r = requests.get(url, proxies=proxies, headers=headers, timeout=timeout)
        if r.status_code == 200 and r.content:
            ctype = r.headers.get("Content-Type", "")
            return r.content, ctype
        return None, ""
    except Exception:
        return None, ""


def oxy_fetch_binary_realtime(url: str, referer: str, timeout: int = 60) -> Optional[bytes]:
    """
    Fetch binary asset via Oxylabs Web Scraper API (Realtime) as base64.
    """
    if not OXY_USER or not OXY_PASS:
        return None

    url = _normalize_url(url)
    payload = {
        "source": "universal",
        "url": url,
        "parse": False,
        "user_agent_type": "desktop",
        "geo_location": "United Kingdom",
        "content_encoding": "base64",
        "headers": {
            "Accept-Language": ACCEPT_LANG,
            "User-Agent": UA,
            "Referer": referer or BASE_HOST + "/",
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        },
    }

    try:
        data = oxy_post(payload, retries=2)
        res = (data.get("results") or [{}])[0]
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


# =========================
# Invalid Link Detection
# =========================
def _check_invalid_product_page(soup: BeautifulSoup, html: str, url: str, verbose: bool = False) -> Tuple[bool, str]:
    """
    Check if a La Redoute product URL has returned an error/listing page instead of PDP.
    
    La Redoute invalid page indicators:
    - 404/error page
    - Redirect to search/category page
    - Missing product elements (title, price, images)
    - Multiple product cards (listing page) WITHOUT PDP elements
    
    Returns (is_invalid, reason) tuple.
    """
    html_lower = html.lower()
    body_text = _clean(soup.get_text(" ", strip=True)).lower() if soup.body else ""
    
    # Extract expected product ID from URL
    expected_id = _extract_product_id_from_url(url)
    
    # ===== FIRST: Check if this looks like a valid PDP =====
    # La Redoute PDP indicators - check these BEFORE checking for listing indicators
    has_pdp_title = bool(soup.select_one("h1.pdp-title, h2.pdp-title, [data-cerberus='txt_pdp_productName1']"))
    has_price = bool(soup.select_one(".price .value, .price, [data-cerberus='txt_pdp_discountedPrice1'], span.price__value"))
    has_add_cart = bool(soup.select_one("[data-cerberus='btn_pdp_addToBasket'], .add-to-cart, button[class*='addToCart'], .pdp-add-to-bag"))
    has_carousel = bool(soup.select_one("[id^='prodCarousel_'], .pdp-carousel, .swipe, .pdp-images"))
    has_description = bool(soup.select_one("div.pdp-description, #productDescription, [id^='productDescription_']"))
    
    # Check for JSON-LD Product data
    jld = _first_jsonld(soup)
    has_jsonld_product = bool(jld and jld.get("@type") == "Product")
    
    pdp_indicators = sum([has_pdp_title, has_price, has_add_cart, has_carousel, has_description, has_jsonld_product])
    
    # If we have strong PDP indicators (3+), this is likely a valid product page
    # Don't check for listing page indicators as they might be "related products"
    if pdp_indicators >= 3:
        if verbose:
            print(f"  ✓ Valid PDP detected ({pdp_indicators}/6 indicators)")
        return False, "valid"
    
    # ===== Check 1: 404/Error page indicators =====
    error_patterns = [
        "page not found",
        "404",
        "product not found",
        "sorry, we can't find",
        "this page doesn't exist",
        "no longer available",
        "has been removed",
        "the page you requested does not exist",
        "nous sommes désolés",  # French error message
        "page introuvable",
    ]
    for pattern in error_patterns:
        if pattern in body_text:
            if verbose:
                print(f"  ⚠ INVALID: Error pattern found - '{pattern}'")
            return True, f"error_message:{pattern[:30]}"
    
    # ===== Check 2: Error page elements =====
    error_selectors = [
        ".error-page", "#error-page", ".page-404", "#page-404",
        "[class*='ErrorPage']", "[class*='NotFound']",
        ".error-content", "#error-content"
    ]
    for sel in error_selectors:
        if soup.select_one(sel):
            if verbose:
                print(f"  ⚠ INVALID: Error page element found - '{sel}'")
            return True, f"error_element:{sel}"
    
    # ===== Check 3: Listing/category page (multiple products WITHOUT PDP elements) =====
    # Only check this if we don't have PDP indicators
    if pdp_indicators < 2:
        product_cards = soup.select(".product-card, .product-tile, [class*='ProductCard'], [class*='product-item']")
        
        # For product links, exclude "related products" sections
        # Only count links in main content area, not in recommendations
        main_content = soup.select_one(".plp-content, .search-results, #searchResults, .category-products")
        if main_content:
            product_links = main_content.select("a[href*='/ppdp/prod-']")
        else:
            product_links = []
        
        if len(product_cards) >= 4 or len(product_links) >= 6:
            if verbose:
                print(f"  ⚠ INVALID: Listing page detected ({len(product_cards)} cards, {len(product_links)} product links in main content)")
            return True, f"listing_page:{len(product_cards)}_cards"
    
    # ===== Check 4: Pagination (listing page indicator) - only if no PDP elements =====
    if pdp_indicators < 2:
        pagination = soup.select_one(".pagination, [class*='Pagination'], .pager, nav[aria-label*='page']")
        results_count = soup.find(string=re.compile(r"\d+\s+products?|\d+\s+results?|\d+\s+articles?", re.I))
        
        if pagination and results_count:
            if verbose:
                print(f"  ⚠ INVALID: Pagination with results count found (listing page)")
            return True, "listing_page:pagination_found"
    
    # ===== Check 5: Missing PDP-specific elements =====
    if pdp_indicators < 2:
        if verbose:
            print(f"  ⚠ INVALID: Missing PDP elements (only {pdp_indicators}/6 found)")
            print(f"    - Title: {has_pdp_title}, Price: {has_price}, AddCart: {has_add_cart}, "
                  f"Carousel: {has_carousel}, Description: {has_description}, JSON-LD: {has_jsonld_product}")
        return True, f"no_pdp_content:{pdp_indicators}_indicators"
    
    # ===== Check 6: Search results page without PDP elements =====
    if pdp_indicators < 2:
        if soup.select_one(".search-results, #searchResults, [class*='SearchResults'], .plp-content"):
            if verbose:
                print(f"  ⚠ INVALID: Search/listing results page detected")
            return True, "search_results_page"
    
    # ===== Check 7: No product name found at all =====
    name_found = False
    if jld and jld.get("name"):
        name_found = True
    else:
        for sel in ["h1.pdp-title", "h2.pdp-title", "[data-cerberus='txt_pdp_productName1']", "h1", "h2"]:
            el = soup.select_one(sel)
            if el and _best_text(el):
                name_found = True
                break
    
    if not name_found:
        if verbose:
            print(f"  ⚠ INVALID: No product name found")
        return True, "no_product_name"
    
    return False, "valid"


# =========================
# La Redoute parser
# =========================
def parse_laredoute(html: str) -> Dict:
    soup = BeautifulSoup(html, "lxml")
    jld = _first_jsonld(soup)

    # ---- name ----
    name = _clean(jld.get("name", "")) if jld else ""
    if not name:
        el = soup.select_one(
            "h1.pdp-title, h2.pdp-title, "
            "[data-cerberus='txt_pdp_productName1'], "
            "h1[itemprop='name'], h2[itemprop='name']"
        )
        if not el:
            el = soup.select_one("h1, h2")
        name = _best_text(el) or (
            _clean(soup.title.get_text().split("|")[0]) if soup.title else ""
        ) or "Unknown Product"

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
                currency = offer.get("priceCurrency", "GBP")
            except Exception:
                pass

    if price_value is None:
        price_el = soup.select_one(
            ".price .value, "
            ".price, "
            "[data-cerberus='txt_pdp_discountedPrice1'], "
            "span.price__value, "
            "[class*='showSalePriceAfter_'], "
            ".product-price"
        )
        if not price_el:
            price_el = soup.find(
                lambda t: t.name in ("span", "div") and t.get_text() and "£" in t.get_text()
            )
        if price_el:
            parsed = _parse_gbp(_best_text(price_el))
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

    if in_stock is None:
        stock_el = soup.select_one(
            ".js--deliveryOrDelayMessage, "
            "[data-cerberus='txt_pdp_stockDeliveryDate1']"
        )
        if stock_el:
            txt = _best_text(stock_el).lower()
            if "in stock" in txt:
                in_stock, stock_text = True, "In stock"
            elif any(k in txt for k in ["out of stock", "unavailable"]):
                in_stock, stock_text = False, txt

    if in_stock is None:
        body_txt = _clean(soup.get_text(" ", strip=True)).lower()
        if "in stock" in body_txt:
            in_stock, stock_text = True, "In stock"
        elif any(w in body_txt for w in ["out of stock", "unavailable", "sold out"]):
            in_stock, stock_text = False, "Unavailable"

    # ---- description ----
    desc_parts: List[str] = []
    if jld and jld.get("description"):
        desc_parts.append(_clean_multiline(jld["description"]))

    desc_box = soup.select_one(
        "div.pdp-description, #productDescription, [id^='productDescription_']"
    )
    if desc_box:
        head = desc_box.select_one(".pdp-description-title")
        ref = desc_box.select_one("#productReference, [id^='productReference_']")
        main = desc_box.select_one(
            "#mainProductDescription, [id^='mainProductDescription']"
        )
        if main:
            for tag in main.find_all(["br"]):
                tag.replace_with("\n")
        parts = [head, ref, main]
        for p in parts:
            if p:
                desc_parts.append(
                    _clean_multiline(p.get_text("\n", strip=True))
                )

        attrs = desc_box.select_one(".pdp-description-attr")
        if attrs:
            desc_parts.append(
                _clean_multiline(attrs.get_text("\n", strip=True))
            )

    description = _clean_multiline("\n\n".join([d for d in desc_parts if d]))

    # ---- images ----
    imgs: List[str] = []

    if jld:
        if isinstance(jld.get("image"), list):
            imgs += [u for u in jld["image"] if isinstance(u, str)]
        elif isinstance(jld.get("image"), str):
            imgs.append(jld["image"])

    for fig in soup.select(
        "[id^='prodCarousel_'] picture, .swipe picture, .pdp-carousel picture"
    ):
        best = None
        for source in fig.find_all("source"):
            url = _parse_srcset_max(source.get("srcset"))
            if url:
                best = url
        if not best:
            img = fig.find("img")
            if img:
                srcset = _attr_chain(img, "srcset", "data-srcset")
                if srcset:
                    best = _parse_srcset_max(srcset)
                if not best:
                    best = _attr_chain(img, "data-src", "src")
        if best:
            imgs.append(best)

    if not imgs:
        for img in soup.select("img[itemprop='image'], img[src*='laredoute.com']"):
            u = _attr_chain(img, "srcset", "data-srcset", "data-src", "src")
            if u:
                if " " in u:
                    u = _parse_srcset_max(u) or u.split()[0]
                imgs.append(u)

    imgs = _dedupe_preserve(imgs)

    return {
        "name": name,
        "price": price_str,
        "price_value": price_value,
        "currency": currency or "GBP",
        "price_source": price_source,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_urls": imgs,
    }


# =========================
# Image download
# =========================
def download_images(
    urls: List[str],
    folder: Path,
    referer: str,
    max_images: Optional[int] = None,
    verbose: bool = True
) -> List[str]:
    """
    Download images for Laredoute products.
    """
    urls = [u for u in urls if isinstance(u, str) and u.startswith("http")]
    if max_images is not None:
        urls = urls[:max_images]

    saved: List[str] = []
    folder.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": UA,
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            "Accept-Language": ACCEPT_LANG,
            "Referer": referer,
        }
    )

    for i, u in enumerate(urls, 1):
        # Method 1: Oxylabs proxy endpoint
        data, ct_proxy = oxy_fetch_binary_via_proxy(u, referer=referer, timeout=60)
        if data:
            ext = _guess_ext(u, ct_proxy)
            out = folder / f"{i:02d}{ext}"
            try:
                with open(out, "wb") as f:
                    f.write(data)
                saved.append(str(out))
                if verbose:
                    print(f"  ✓ image {i} via proxy ({len(data):,} bytes)")
                continue
            except Exception as e:
                if verbose:
                    print(f"  ✗ error writing proxy image {i}: {e}")

        # Method 2: Web Scraper API Realtime (base64)
        data_rt = oxy_fetch_binary_realtime(u, referer=referer, timeout=60)
        if data_rt:
            out = folder / f"{i:02d}.jpg"
            try:
                with open(out, "wb") as f:
                    f.write(data_rt)
                saved.append(str(out))
                if verbose:
                    print(f"  ✓ image {i} via API ({len(data_rt):,} bytes)")
                continue
            except Exception as e:
                if verbose:
                    print(f"  ✗ error writing API image {i}: {e}")

        # Method 3: Direct HTTP (fallback)
        try:
            with session.get(u, timeout=30, stream=True) as r:
                ct = r.headers.get("Content-Type", "")
                if r.status_code == 200 and (ct.startswith("image/") or r.content):
                    ext = _guess_ext(u, ct)
                    out = folder / f"{i:02d}{ext}"
                    with open(out, "wb") as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                    saved.append(str(out))
                    if verbose:
                        print(f"  ✓ image {i} direct")
                else:
                    if verbose:
                        print(f"  ✗ image {i}: HTTP {r.status_code}")
        except Exception as e:
            if verbose:
                print(f"  ✗ image {i}: {e}")

    return saved


# =========================
# Orchestrator
# =========================
def scrape_laredoute_with_oxylabs(
    url: str,
    download_images_flag: bool = True,
    max_images: Optional[int] = None,
    geo: str = "United Kingdom",
    verbose: bool = True
) -> Dict:
    if verbose:
        print(f"Fetching {url}...")
    
    # Try to fetch HTML with retry logic
    try:
        html = oxy_fetch_html(url, geo=geo, verbose=verbose)
    except RuntimeError as e:
        err_str = str(e)
        
        if "INVALID_PAGE:" in err_str:
            reason = err_str.split("INVALID_PAGE:")[-1]
            if verbose:
                print(f"✗ Invalid link detected (fetch failed): {reason}")
            
            return {
                "url": url,
                "name": "INVALID LINK - Product removed or no longer available",
                "price": "N/A",
                "price_value": None,
                "currency": "GBP",
                "price_source": "none",
                "in_stock": False,
                "stock_text": f"fetch_failed:{reason}",
                "description": "",
                "image_count": 0,
                "image_urls": [],
                "images_downloaded": [],
                "folder": None,
                "mode": "oxylabs-universal+proxy+api",
                "is_invalid": True,
                "invalid_reason": f"fetch_failed:{reason}"
            }
        
        raise
    
    soup = BeautifulSoup(html, "lxml")
    
    # Check for invalid product page FIRST
    is_invalid, invalid_reason = _check_invalid_product_page(soup, html, url, verbose=verbose)
    
    if is_invalid:
        if verbose:
            print(f"✗ Invalid link detected: {invalid_reason}")
        
        return {
            "url": url,
            "name": "INVALID LINK - Product removed or no longer available",
            "price": "N/A",
            "price_value": None,
            "currency": "GBP",
            "price_source": "none",
            "in_stock": False,
            "stock_text": invalid_reason,
            "description": "",
            "image_count": 0,
            "image_urls": [],
            "images_downloaded": [],
            "folder": None,
            "mode": "oxylabs-universal+proxy+api",
            "is_invalid": True,
            "invalid_reason": invalid_reason
        }
    
    parsed = parse_laredoute(html)

    if verbose:
        print(f"  Name: {parsed['name']}")
        print(f"  Price: {parsed['price']}")
        print(f"  In Stock: {parsed['in_stock']} ({parsed['stock_text']})")
        print(f"  Images found: {len(parsed['image_urls'])}")

    folder = DATA_DIR / f"{SITE_TAG}_{_safe_name(parsed['name'])}_{_stable_id_from_url(url)}"
    folder.mkdir(parents=True, exist_ok=True)

    images_downloaded: List[str] = []
    if download_images_flag and parsed["image_urls"]:
        count = len(parsed['image_urls']) if not max_images else min(len(parsed['image_urls']), max_images)
        if verbose:
            print(f"\nDownloading {count} images...")
        images_downloaded = download_images(
            parsed["image_urls"],
            folder,
            referer=url,
            max_images=max_images,
            verbose=verbose
        )

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
        "mode": "oxylabs-universal+proxy+api",
        "is_invalid": False,
        "invalid_reason": None
    }


# # =========================
# # CLI
# # =========================
# if __name__ == "__main__":
#     import sys
    
#     if len(sys.argv) > 1:
#         TEST_URL = sys.argv[1]
#     else:
#         TEST_URL = "https://www.laredoute.co.uk/ppdp/prod-350344450.aspx#searchkeyword=LAURA%20ASHLEY&shoppingtool=search"
    
#     print(f"\n{'='*60}")
#     print(f"Testing: {TEST_URL}")
#     print(f"{'='*60}\n")
    
#     try:
#         data = scrape_laredoute_with_oxylabs(
#             TEST_URL,
#             download_images_flag=True,
#             max_images=12,
#             verbose=True
#         )
#         print("\n" + "=" * 60)
#         print("RESULTS:")
#         print("=" * 60)
#         print(json.dumps(data, indent=2, ensure_ascii=False))
#     except Exception as e:
#         print(f"\n✗ ERROR: {e}")