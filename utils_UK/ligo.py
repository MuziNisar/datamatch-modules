# import os
# import re
# import requests
# from playwright.sync_api import sync_playwright
# from tkinter import messagebox
# from pathlib import Path

# BASE_DIR = Path(__file__).resolve().parent
# DEFAULT_SAVE_DIR = BASE_DIR / "data1"

# def scrape_ligo_product(url, save_dir=DEFAULT_SAVE_DIR):
#     with sync_playwright() as p:
#         # Launch Chromium in headful mode but hidden off-screen
#         browser = p.chromium.launch(
#             headless=False,
#             args=["--window-position=-32000,-32000", "--disable-blink-features=AutomationControlled"]
#         )
#         context = browser.new_context(
#             user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#                        "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
#         )
#         page = context.new_page()

#         try:
#             page.goto(url, wait_until="domcontentloaded", timeout=60000)
#         except Exception as e:
#             # print(f"❌ Navigation failed: {e}")
#             messagebox.showerror("Error", f"⚠️  error: {e}")
#             return {}

#         # ---------------------------
#         # 1. PRODUCT NAME
#         # ---------------------------
#         try:
#             name = page.locator("h1.product-info-heading").inner_text(timeout=15000).strip()
#         except:
#             name = "N/A"

#         # ---------------------------
#         # 2. PRODUCT PRICE
#         # ---------------------------
#         try:
#             price = page.locator("span.price-item").inner_text(timeout=15000).strip()
#         except:
#             price = "N/A"

#         # ---------------------------
#         # 3. STOCK STATUS
#         # ---------------------------
#         try:
#             stock_button = page.locator("div.product-actions-add-to-cart button").inner_text(timeout=10000).strip()
#             in_stock = "out of stock" not in stock_button.lower()
#         except:
#             in_stock = None

#         # ---------------------------
#         # 4. PRODUCT DESCRIPTION (Improved)
#         # ---------------------------
#         try:
#             if page.locator("div[data-content-type='text']").count() > 0:
#                 desc_html = page.locator("div[data-content-type='text']").inner_html(timeout=15000)
#             elif page.locator("div.product__description").count() > 0:
#                 desc_html = page.locator("div.product__description").inner_html(timeout=15000)
#             else:
#                 desc_html = ""
#             description = re.sub(r"<[^>]*>", " ", desc_html)
#             description = re.sub(r"\s+", " ", description).strip()
#         except:
#             description = "N/A"

#         # ---------------------------
#         # 5. PRODUCT IMAGES (Deduplicated)
#         # ---------------------------
#         try:
#             image_elements = page.query_selector_all("media-gallery img")
#             seen = set()
#             deduped_images = []
#             for img in image_elements:
#                 src = img.get_attribute("src")
#                 if not src:
#                     continue
#                 if src.startswith("//"):
#                     src = "https:" + src
#                 elif src.startswith("/"):
#                     src = "https://ligo.co.uk" + src
#                 src = src.split("?")[0]
#                 if src not in seen:
#                     seen.add(src)
#                     deduped_images.append(src)
#         except:
#             deduped_images = []

#         # ---------------------------
#         # 6. SAVE IMAGES LOCALLY
#         # ---------------------------
#         safe_name = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "_") if name != "N/A" else "Unknown_Product"
#         folder_name = os.path.join(save_dir, safe_name)
#         os.makedirs(folder_name, exist_ok=True)

#         downloaded_images = []
#         for idx, img_url in enumerate(deduped_images, start=1):
#             try:
#                 img_path = os.path.join(folder_name, f"image_{idx}.jpg")
#                 response = requests.get(img_url, timeout=20)
#                 if response.status_code == 200:
#                     with open(img_path, "wb") as f:
#                         f.write(response.content)
#                     downloaded_images.append(img_path)
#             except Exception as e:
#                 # print(f"⚠️ Could not download {img_url}: {e}")
#                 messagebox.showerror("Error", f"⚠️  error: {e}")

#         # ---------------------------
#         # 7. FINAL RESULT
#         # ---------------------------
#         result = {
#             "name": name or "N/A",
#             "price": price or "N/A",
#             "in_stock": in_stock,
#             "description": description or "N/A",
#             "image_count": len(downloaded_images),
#             "images": downloaded_images,
#             "folder": folder_name
#         }

#         browser.close()
#         return result







# ligo_oxylabs.py
# Python 3.10+
# pip install requests beautifulsoup4 lxml pillow

from __future__ import annotations
import os, re, io, json, time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse, urldefrag

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from PIL import Image

# ---------------------------
# Credentials (from oxylabs_secrets.py or env)
# ---------------------------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS  # optional helper file
except Exception:
    OXY_USER = os.getenv("OXY_USER") or os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXY_PASS") or os.getenv("OXYLABS_PASSWORD", "")

if not (OXY_USER and OXY_PASS):
    raise RuntimeError("Oxylabs credentials missing: set OXY_USER/OXY_PASS or provide oxylabs_secrets.py")

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
# Small helpers
# ---------------------------
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _safe_name(s: str) -> str:
    s = _clean(s)
    return re.sub(r"[^\w.\-]+", "_", s)[:120] or "Unknown_Product"

def _origin_for(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"

def _absolutize(u: str, base: str) -> str:
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

def _session_with_retries(total=3, backoff=0.5) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=total,
        read=total,
        connect=total,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"])
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=10)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

# ---------------------------
# Oxylabs HTML fetch
# ---------------------------
def oxy_fetch_html(url: str, geo: str = "United Kingdom", timeout: int = 90) -> str:
    url, _ = urldefrag(url)
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",                # fully-rendered HTML
        "geo_location": geo,
        "headers": {"User-Agent": UA, "Accept-Language": ACCEPT_LANG},
        # "premium": True,               # enable if your plan supports it for tougher pages
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
# Parsing (ligo.co.uk)
# ---------------------------
def parse_ligo(html: str, page_url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    # --- Name ---
    name = None
    for sel in ["h1.product-info-heading", "h1.page-title > span", "h1"]:
        el = soup.select_one(sel)
        if el:
            name = _clean(el.get_text())
            break
    if not name and soup.title:
        name = _clean(soup.title.get_text().split("|")[0])
    name = name or "Unknown Product"

    # --- Price ---
    price_val = None
    currency = "GBP"
    price_str = "N/A"
    price_source = "none"

    # JSON-LD first (Magento usually provides)
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(tag.text or "")
            arr = data if isinstance(data, list) else [data]
            for obj in arr:
                if isinstance(obj, dict) and obj.get("@type") == "Product":
                    offers = obj.get("offers")
                    if isinstance(offers, dict):
                        offers = [offers]
                    for off in offers or []:
                        if "price" in off:
                            price_val = float(str(off["price"]).replace(",", ""))
                            price_str = f"{price_val:.2f} {off.get('priceCurrency', 'GBP')}"
                            price_source = "jsonld"
                            break
        except Exception:
            pass
        if price_val is not None:
            break

    # On-page fallback
    if price_val is None:
        el = soup.select_one("span.price-item, span.price, .price-box .price")
        if not el:
            el = soup.find(lambda t: t.name in ("span", "div") and t.get_text() and "£" in t.get_text())
        if el:
            parsed = _parse_gbp(_clean(el.get_text()))
            if parsed:
                price_val, currency, price_str = parsed
                price_source = "onsite"

    # --- Stock / Availability ---
    in_stock = None
    stock_text = ""
    # Button heuristics
    btn = soup.select_one("div.product-actions-add-to-cart button, button#product-addtocart-button, button.tocart")
    if btn:
        t = _clean(btn.get_text()).lower()
        if "add to basket" in t or "add to cart" in t or "buy now" in t:
            in_stock, stock_text = True, t
        elif any(k in t for k in ["out of stock", "unavailable"]):
            in_stock, stock_text = False, t
    if in_stock is None:
        body = _clean(soup.get_text(" ", strip=True)).lower()
        if "out of stock" in body:
            in_stock, stock_text = False, "out of stock"
        elif "add to cart" in body or "add to basket" in body or "in stock" in body:
            in_stock, stock_text = True, "in stock (heuristic)"

    # --- Description ---
    description = ""
    for sel in [
        "div[data-content-type='text']",
        "div.product__description",
        "div.product.attribute.description",
        "div#description",
        "div.product.info.detailed .data.item.content"
    ]:
        el = soup.select_one(sel)
        if el:
            description = _clean(el.get_text(" ", strip=True))
            break
    if not description:
        # JSON-LD fallback
        for tag in soup.select("script[type='application/ld+json']"):
            try:
                data = json.loads(tag.text or "")
                arr = data if isinstance(data, list) else [data]
                for obj in arr:
                    if isinstance(obj, dict) and obj.get("@type") == "Product" and obj.get("description"):
                        description = _clean(obj["description"])
                        break
            except Exception:
                pass
        description = description or "N/A"

    # --- Images (dedup, prefer largest if srcset) ---
    imgs: List[str] = []
    seen = set()

    def _add(u: str):
        if not u:
            return
        u = _absolutize(u, page_url)
        base = u.split("?")[0]
        if base not in seen:
            seen.add(base)
            imgs.append(u)

    # Common Magento gallery selectors
    for im in soup.select("media-gallery img, .fotorama__stage__frame img, .gallery-placeholder img, picture img, img.product-image-photo"):
        srcset = im.get("srcset") or im.get("data-srcset")
        if srcset:
            # pick the widest candidate
            best_url, best_w = None, -1
            for part in srcset.split(","):
                p = part.strip().split()
                u = p[0]
                w = 0
                if len(p) > 1 and p[1].endswith("w"):
                    try: w = int(re.sub(r"\D", "", p[1]))
                    except Exception: w = 0
                if w >= best_w:
                    best_w, best_url = w, u
            _add(best_url)
        else:
            u = im.get("data-src") or im.get("src") or im.get("data-image") or ""
            # some Magento imgs are protocol-relative or path-relative
            if u:
                _add(u)

    # Final fallback: any big-ish product-ish images on page
    if not imgs:
        for im in soup.select("img[src]"):
            u = im.get("src")
            if u and any(k in u.lower() for k in ["product", "catalog", "media", "image", "product", "cache"]):
                _add(u)

    return {
        "name": name,
        "price": price_str,
        "price_value": price_val,
        "currency": currency,
        "price_source": price_source,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_urls": imgs,
    }

# ---------------------------
# Image download (force real JPG)
# ---------------------------
def download_images_as_jpg(urls: List[str], folder: Path, referer: str, max_images: Optional[int]=None) -> List[str]:
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
            # GET image bytes directly
            r = sess.get(u, headers=headers, timeout=30, stream=True)
            r.raise_for_status()
            data = r.content

            # Convert to actual JPG (handles webp/png etc. via Pillow)
            try:
                im = Image.open(io.BytesIO(data))
                rgb = im.convert("RGB")
                out = folder / f"{i:02d}.jpg"
                rgb.save(out, format="JPEG", quality=92, optimize=True)
                saved.append(str(out))
            except Exception:
                # If PIL fails, still save bytes with .jpg (some browsers serve JPEG already)
                out = folder / f"{i:02d}.jpg"
                with open(out, "wb") as f:
                    f.write(data)
                saved.append(str(out))
        except Exception as e:
            print(f"  ! image error: {u} ({e})")
    return saved

# ---------------------------
# Public API
# ---------------------------
def scrape_ligo_with_oxylabs(url: str,
                             download_images_flag: bool = True,
                             max_images: Optional[int] = None,
                             geo: str = "United Kingdom") -> Dict[str, Any]:
    html = oxy_fetch_html(url, geo=geo)
    parsed = parse_ligo(html, page_url=url)

    folder = DATA_DIR / f"ligo_{_safe_name(parsed['name'])}"
    imgs_local: List[str] = []
    if download_images_flag and parsed["image_urls"]:
        imgs_local = download_images_as_jpg(parsed["image_urls"], folder, referer=url, max_images=max_images)

    return {
        "name": parsed["name"] or "N/A",
        "price": parsed["price"] or "N/A",
        "in_stock": parsed["in_stock"],
        "stock_text": parsed["stock_text"],
        "description": parsed["description"] or "N/A",
        "image_count": len(imgs_local) if imgs_local else len(parsed["image_urls"]),
        "images": imgs_local if imgs_local else parsed["image_urls"],
        "folder": str(folder),
        "mode": "oxylabs-universal",
        "url": url,
    }

# # ---------------------------
# # CLI test
# # ---------------------------
# if __name__ == "__main__":
#     # Example product (replace with any ligo PDP)
#     TEST_URL = "https://ligo.co.uk/products/vq-dexter-portable-dab-fm-radio-in-oak?_pos=2&_sid=73049f767&_ss=r"
#     data = scrape_ligo_with_oxylabs(TEST_URL, download_images_flag=True, max_images=20)
#     print(json.dumps(data, indent=2, ensure_ascii=False))
