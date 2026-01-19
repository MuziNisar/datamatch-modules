# # laredoute_oxylabs.py
# # Python 3.9+
# # pip install requests beautifulsoup4 lxml

# from __future__ import annotations
# import os, re, json, hashlib, time, base64
# from pathlib import Path
# from typing import Optional, List, Dict, Tuple
# from urllib.parse import urlparse, urldefrag

# import requests
# from requests.exceptions import RequestException
# from bs4 import BeautifulSoup

# # =========================
# # Config
# # =========================
# # Fallback creds; prefer env or oxylabs_secrets.py
# OXY_USER_FALLBACK = os.getenv("OXY_USER", "Muzamil_wUDhn")
# OXY_PASS_FALLBACK = os.getenv("OXY_PASS", "Muzamil_13111")

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
# # Oxylabs creds + client
# # =========================
# def _oxy_creds() -> Tuple[str, str]:
#     """
#     Resolve Oxylabs credentials from:
#       1) oxylabs_secrets.py (if present)
#       2) OXYLABS_USERNAME / OXYLABS_PASSWORD
#       3) OXY_USER / OXY_PASS (fallbacks above)
#     """
#     try:
#         from oxylabs_secrets import OXY_USER, OXY_PASS
#         if OXY_USER and OXY_PASS:
#             return OXY_USER, OXY_PASS
#     except Exception:
#         pass

#     user = os.getenv("OXYLABS_USERNAME") or os.getenv("OXY_USER", OXY_USER_FALLBACK)
#     pwd  = os.getenv("OXYLABS_PASSWORD") or os.getenv("OXY_PASS", OXY_PASS_FALLBACK)
#     return user, pwd

# def oxy_post(payload: dict, retries: int = 3, backoff: float = 1.5) -> dict:
#     """
#     Generic Oxylabs POST wrapper for HTML (Web Scraper API Realtime).
#     """
#     user, pwd = _oxy_creds()
#     if not user or not pwd:
#         raise RuntimeError("Missing Oxylabs credentials.")

#     last_err = None
#     for attempt in range(1, retries + 1):
#         try:
#             r = requests.post(
#                 "https://realtime.oxylabs.io/v1/queries",
#                 auth=(user, pwd),
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
#                 # For HTML jobs, enforce HTML check; for binary we skip.
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
#     user, pwd = _oxy_creds()
#     if not user or not pwd:
#         return None, ""

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
#             "Referer": referer or BASE_HOST + "/",
#             # Optional job parameters for proxy endpoint
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
#     user, pwd = _oxy_creds()
#     if not user or not pwd:
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
#         # For binary, we don't enforce "<html" in oxy_post
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
#             out = folder / f"{i:02d}.jpg"  # force .jpg, we don't know type but PIL can handle if needed
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
#         # FIXED: valid CSS (no '.showSalePriceAfter_*'; use [class*='showSalePriceAfter_'])
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
# #     TEST_URL = "https://www.laredoute.co.uk/ppdp/prod-350267371.aspx?dim1=1#headerSearchContainer&searchkeyword=Laura%20ashley&shoppingtool=search"
# #     data = scrape_laredoute_with_oxylabs(
# #         TEST_URL,
# #         download_images_flag=True,
# #         max_images=12,
# #     )
# #     print(json.dumps(data, indent=2, ensure_ascii=False))















# laredoute_oxylabs.py
# Python 3.9+
# pip install requests beautifulsoup4 lxml
# Version: 2.0 - Fixed credentials to use oxylabs_secrets.py

from __future__ import annotations
import os, re, json, hashlib, time, base64
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from urllib.parse import urlparse, urldefrag

import requests
from requests.exceptions import RequestException
from bs4 import BeautifulSoup

__version__ = "2.0"

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

def _dedupe_preserve(urls: List[str]) -> List[str]:
    seen, out = set(), []
    for u in urls:
        k = u.split("?")[0]
        if k and k not in seen:
            seen.add(k)
            out.append(u)
    return out

def _parse_gbp(text: str) -> Optional[Tuple[float, str, str]]:
    """
    Returns (value_float, currency, display_string), e.g. (60.0, 'GBP', '60.00 GBP')
    """
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
    """
    Choose the largest candidate from a srcset string.
    """
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
# Oxylabs client
# =========================
def oxy_post(payload: dict, retries: int = 3, backoff: float = 1.5) -> dict:
    """
    Generic Oxylabs POST wrapper for HTML (Web Scraper API Realtime).
    """
    if not OXY_USER or not OXY_PASS:
        raise RuntimeError("Missing Oxylabs credentials.")

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(
                "https://realtime.oxylabs.io/v1/queries",
                auth=(OXY_USER, OXY_PASS),
                json=payload,
                timeout=90,
            )
            r.raise_for_status()
            data = r.json()
            results = data.get("results") or []
            if not results:
                raise RuntimeError("Oxylabs: empty results")
            content = results[0].get("content", "")
            if "<html" not in content.lower() and payload.get("parse") is not False:
                raise RuntimeError("Oxylabs: non-HTML content")
            return data
        except (RequestException, ValueError, RuntimeError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff ** attempt)
            else:
                raise RuntimeError(f"Oxylabs failed after {retries} attempts: {e}") from e
    raise last_err or RuntimeError("Oxylabs unknown error")

def oxy_fetch_html(url: str, geo: str = "United Kingdom") -> str:
    """
    Fetch HTML via Oxylabs Web Scraper API (universal source, render=html).
    """
    url, _frag = urldefrag(url)
    url = _normalize_url(url)
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
    }
    data = oxy_post(payload)
    return data["results"][0]["content"]

# =========================
# Oxylabs image fetch (proxy + realtime)
# =========================
def oxy_fetch_binary_via_proxy(url: str, referer: str, timeout: int = 60) -> Tuple[Optional[bytes], str]:
    """
    Fetch binary content (images) through Oxylabs Proxy Endpoint.
    Returns (bytes_or_none, content_type).
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
    NOTE: This consumes Web Scraper API 'results' per image.
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
        data = oxy_post(payload)
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
# Image download
# =========================
def download_images(
    urls: List[str],
    folder: Path,
    referer: str,
    max_images: Optional[int] = None
) -> List[str]:
    """
    Download images for Laredoute products.
    Strategy:
      1) Try Oxylabs proxy endpoint.
      2) Fallback to Web Scraper API Realtime (base64).
      3) Final fallback: direct HTTP (may 403).
    """
    # Filter out broken srcset entries like "dpr=1/products/..."
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
                print(f"  ✓ (oxy-proxy) {out.name} ← {u}")
                continue
            except Exception as e:
                print(f"  ! error writing proxy image {u}: {e}")

        # Method 2: Web Scraper API Realtime (base64)
        data_rt = oxy_fetch_binary_realtime(u, referer=referer, timeout=60)
        if data_rt:
            out = folder / f"{i:02d}.jpg"
            try:
                with open(out, "wb") as f:
                    f.write(data_rt)
                saved.append(str(out))
                print(f"  ✓ (oxy-api) {out.name} ← {u}")
                continue
            except Exception as e:
                print(f"  ! error writing realtime image {u}: {e}")

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
                    print(f"  ✓ (direct) {out.name} ← {u}")
                else:
                    print("  ! image HTTP", r.status_code, u, ct)
        except Exception as e:
            print("  ! image error:", u, e)

    return saved

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
# Orchestrator
# =========================
def scrape_laredoute_with_oxylabs(
    url: str,
    download_images_flag: bool = True,
    max_images: Optional[int] = None,
    geo: str = "United Kingdom",
) -> Dict:
    html = oxy_fetch_html(url, geo=geo)
    parsed = parse_laredoute(html)

    folder = DATA_DIR / f"{SITE_TAG}_{_safe_name(parsed['name'])}_{_stable_id_from_url(url)}"
    folder.mkdir(parents=True, exist_ok=True)

    images_downloaded: List[str] = []
    if download_images_flag and parsed["image_urls"]:
        print(
            f"Downloading {len(parsed['image_urls']) if not max_images else min(len(parsed['image_urls']), max_images)} images …"
        )
        images_downloaded = download_images(
            parsed["image_urls"],
            folder,
            referer=url,
            max_images=max_images,
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
        "image_count": len(images_downloaded)
        if images_downloaded
        else len(parsed["image_urls"]),
        "image_urls": parsed["image_urls"],
        "images_downloaded": images_downloaded,
        "folder": str(folder),
        "mode": "oxylabs-universal+proxy+api",
    }

# # =========================
# # CLI
# # =========================
# if __name__ == "__main__":
#     TEST_URL = "https://www.laredoute.co.uk/ppdp/prod-350344450.aspx#searchkeyword=LAURA%20ASHLEY&shoppingtool=search"
#     data = scrape_laredoute_with_oxylabs(
#         TEST_URL,
#         download_images_flag=True,
#         max_images=12,
#     )
#     print(json.dumps(data, indent=2, ensure_ascii=False))

