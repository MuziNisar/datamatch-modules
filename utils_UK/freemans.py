# import re
# import os
# import requests
# import time
# from typing import Dict, Any
# from playwright.sync_api import sync_playwright
# from tkinter import messagebox


# def _clean_text(text: str) -> str:
#     return re.sub(r'\s+', ' ', text).strip()


# def fetch_freemans_product_with_playwright(url: str) -> Dict[str, Any]:
#     with sync_playwright() as p:
#         browser = p.chromium.launch(
#                                         headless=False,
#                                         args=[
#                                             "--window-position=-32000,-32000",  # Moves the window off-screen
#                                             "--disable-popup-blocking",
#                                         ]
#                                     )
#         context = browser.new_context(
#             user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#                        "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
#             viewport={"width": 1280, "height": 800}
#         )

#         page = context.new_page()
#         page.goto(url, wait_until="networkidle", timeout=60000)
#         time.sleep(5)  # Let React fully render content

#         data = {
#             "name": None,
#             "price": None,
#             "description": None,
#             "image_urls": [],
#             "image_count": 0,
#             "availability_message": None,
#             "in_stock": None,
#         }

#         # ---------- Product Name ----------
#         try:
#             name = page.locator("h1#prodShortDesc").evaluate("el => el.textContent")
#             data["name"] = _clean_text(name)
#         except Exception as e:
#             # print(f"❌ Name error: {e}")
#             messagebox.showerror("Error", f"⚠️ Name error: {e}")

#         # ---------- Price ----------
#         try:
#             pound = page.locator("span.productPriceInteger").evaluate("el => el.textContent")
#             pence = page.locator("span.productPriceDecimal").evaluate("el => el.textContent")
#             data["price"] = f"£{pound}.{pence}"
#         except Exception as e:
#             # print(f"❌ Price error: {e}")
#             messagebox.showerror("Error", f"⚠️ Price error: {e}")

#         # ---------- Description ----------
#         try:
#             desc_html = page.locator("div.productDescription").inner_html()
#             clean_desc = re.sub(r'<[^>]+>', '', desc_html)
#             data["description"] = _clean_text(clean_desc)
#         except Exception as e:
#             # print(f"❌ Description error: {e}")
#             messagebox.showerror("Error", f"⚠️ Description error: {e}")

#         # ---------- Images ----------

#         try:
#             seen = set()
#             img_tags = page.query_selector_all("ul.altProductImages img")

#             for tag in img_tags:
#                 src = (
#                     tag.get_attribute("data-image")
#                     or tag.get_attribute("data-original")
#                 )
#                 if not src:
#                     continue

#                 clean_src = src.split("?")[0]
#                 if clean_src in seen:
#                     continue
#                 seen.add(clean_src)
#                 data["image_urls"].append(clean_src)

#             data["image_count"] = len(data["image_urls"])

#             # ---------- Download to data1/<product-name>/ ----------
#             safe_name = re.sub(r"[^\w\s-]", "", data["name"]).strip().replace(" ", "_")
#             folder = os.path.join(os.getcwd(), "data1", safe_name)
#             os.makedirs(folder, exist_ok=True)

#             for i, url in enumerate(data["image_urls"], start=1):
#                 try:
#                     img_data = requests.get(url, stream=True, timeout=20)
#                     img_data.raise_for_status()
#                     ext = os.path.splitext(url)[-1] or ".jpg"
#                     if ext.lower() not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
#                         ext = ".jpg"
#                     filename = os.path.join(folder, f"{i:02d}{ext}")
#                     with open(filename, "wb") as f:
#                         for chunk in img_data.iter_content(1024):
#                             f.write(chunk)
#                 except Exception as e:
#                     # print(f"⚠️ Failed to download {url}: {e}")
#                     messagebox.showerror("Error", f"⚠️ download error: {e}")

#             # ✅ Add the folder path to your result dictionary
#             data["image_folder"] = folder

#         except Exception as e:
#             # print(f"❌ Image extraction error: {e}")
#             messagebox.showerror("Error", f"⚠️ Image error: {e}")

#         # ---------- Availability ----------
#         try:
#             status_text = page.locator("span.stockStatus").evaluate("el => el.textContent")
#             status_text = _clean_text(status_text).lower()

#             if "not currently available" in status_text or "out of stock" in status_text or "unavailable" in status_text:
#                 data["in_stock"] = False
#                 data["availability_message"] = status_text
#             elif "in stock" in status_text:
#                 data["in_stock"] = True
#                 data["availability_message"] = status_text
#             else:
#                 data["in_stock"] = None
#                 data["availability_message"] = status_text
#         except Exception as e:
#             # print(f"❌ Availability check failed: {e}")
#             messagebox.showerror("Error", f"⚠️ Stock error: {e}")


#         result = {
#             "name": data.get("name") or "N/A",
#             "price": data.get("price") or "N/A",
#             "in_stock": data.get("in_stock"),
#             "description": data.get("description") or "N/A",
#             "image_count": data.get("image_count", 0),
#             "images": data.get("image_urls", []),
#             "folder": data.get("image_folder", "N/A")
#         }

#         browser.close()
#         return result


















# freemans.py
# Python 3.10+
# pip install requests beautifulsoup4 lxml pillow

import os
import re
import io
import json
import random
from pathlib import Path
from typing import Dict, Any, List, Tuple

import requests
from bs4 import BeautifulSoup
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------
# Credentials
# ---------------------------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS  # optional helper file
except Exception:
    OXY_USER = os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")

if not (OXY_USER and OXY_PASS):
    raise RuntimeError(
        "Oxylabs credentials missing. Set OXYLABS_USERNAME / OXYLABS_PASSWORD "
        "or provide oxylabs_secrets.py with OXY_USER, OXY_PASS."
    )

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
def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _safe_name(name: str) -> str:
    n = re.sub(r"[^\w\s-]", "", name or "").strip()
    n = re.sub(r"\s+", "_", n)
    return n or "Unknown_Product"

def _retailer_slug(url: str) -> str:
    m = re.search(r"https?://(?:www\.)?([^/]+)", url or "", re.I)
    if not m:
        return "site"
    host = re.sub(r"^www\.", "", m.group(1).lower())
    return host.split(".")[0]

def _stable_id_from_url(url: str) -> str:
    # Prefer long numeric code in path/query; otherwise "freemans"
    m = re.search(r"(\d{6,})", url or "")
    return m.group(1) if m else "freemans"

def _ua() -> str:
    return random.choice([
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Mozilla/5.0 (Linux; Android 14; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
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

# ---------------------------
# Oxylabs call
# ---------------------------
def _oxylabs_universal_html(url: str, country: str = "United Kingdom", timeout: int = 75) -> str:
    """
    Returns rendered HTML via Oxylabs Web Scraper API Universal source.
    """
    endpoint = "https://realtime.oxylabs.io/v1/queries"
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": country,
        "render": "html",                # valid values: html, mhtml, png
        "user_agent_type": "desktop",
        "headers": {"User-Agent": _ua()},
        # "premium": True,               # enable if your plan allows
    }
    sess = _session_with_retries()
    r = sess.post(endpoint, auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
    if r.status_code != 200:
        # surface Oxylabs error body so you can see exact issue
        msg = r.text.strip()
        raise RuntimeError(f"Oxylabs HTML fetch failed: HTTP {r.status_code} — {msg}")
    data = r.json()
    try:
        return data["results"][0]["content"]
    except Exception:
        raise RuntimeError(f"Oxylabs response missing content: {data}")

# ---------------------------
# Parsers (Freemans)
# ---------------------------
def _extract_name(soup: BeautifulSoup) -> str:
    el = soup.select_one("h1#prodShortDesc")
    if el:
        txt = _clean_text(el.get_text(" ", strip=True))
        if txt:
            return txt
    for sel in ("h1", ".productShortDesc", "[data-testid='pdp-title']"):
        el = soup.select_one(sel)
        if el:
            txt = _clean_text(el.get_text(" ", strip=True))
            if txt:
                return txt
    # JSON-LD fallback
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if obj.get("@type") == "Product" and obj.get("name"):
                return _clean_text(obj["name"])
    return "Unknown Product"

def _extract_price(soup: BeautifulSoup) -> Tuple[str, str]:
    p_int = soup.select_one("span.productPriceInteger")
    p_dec = soup.select_one("span.productPriceDecimal")
    if p_int and p_dec:
        pint = _clean_text(p_int.get_text())
        pdec = _clean_text(p_dec.get_text())
        if pint and pdec:
            return f"{pint}.{pdec} GBP", "integer+decimal"
    # body fallback
    txt = _clean_text(soup.get_text(" ", strip=True))
    m = re.search(r"(£\s?\d[\d,]*(?:\.\d{2})?)", txt)
    if m:
        return m.group(1).replace(" ", "") + " GBP", "body"
    # JSON-LD fallback
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if obj.get("@type") == "Product":
                offers = obj.get("offers")
                offers = offers if isinstance(offers, list) else [offers] if offers else []
                for off in offers:
                    price = off.get("price") or off.get("lowPrice")
                    if price:
                        return f"{price} GBP", "jsonld"
    return "N/A", "none"

def _extract_description(soup: BeautifulSoup) -> str:
    d = soup.select_one("div.productDescription")
    if d:
        txt = _clean_text(d.get_text(" ", strip=True))
        if txt:
            return txt
    for sel in ("#prodDescription", "[data-testid='pdp-description']",
                ".product-description", ".pdp-description"):
        el = soup.select_one(sel)
        if el:
            txt = _clean_text(el.get_text(" ", strip=True))
            if txt:
                return txt
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if obj.get("@type") == "Product" and obj.get("description"):
                t = _clean_text(obj["description"])
                if t:
                    return t
    meta = soup.select_one("meta[name='description']")
    if meta and meta.get("content"):
        t = _clean_text(meta["content"])
        if t:
            return t
    return "N/A"

def _extract_stock(soup: BeautifulSoup) -> Tuple[bool | None, str]:
    """
    Freemans stock heuristic:
    1) If stockStatus text is decisive (explicit OOS or clearly available), use it.
    2) Else, look for the Add-to-Bag CTA.
    3) Else, fall back to JSON-LD availability.
    4) Else, unknown.
    """
    last_txt = "unknown"

    # 1) stockStatus text (decisive only)
    st = soup.select_one("span.stockStatus, .stockStatus")
    if st:
        txt = _clean_text(st.get_text(" ", strip=True)).lower()
        last_txt = txt
        if any(x in txt for x in ["out of stock", "not currently available", "unavailable"]):
            return False, txt
        if any(x in txt for x in [
            "in stock",
            "delivered direct",          # drop-ship wording; treat as purchasable
            "available to order",
            "delivery",                   # e.g., "delivery in 2–4 days"
            "despatched",
            "ready to ship",
        ]):
            return True, txt
        # else not decisive; keep going

    # 2) CTA present?
    btn = soup.select_one(
        "button.bagButton, button.button.primary.bagButton, "
        "button.addToBasket, button[data-testid='add-to-basket']"
    )
    if btn or soup.find(string=re.compile(r"\bAdd to Bag\b", re.I)):
        return True, "add-to-bag"

    # 3) JSON-LD availability
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
                    if re.search(r"InStock", avail, re.I):
                        return True, "jsonld"
                    if re.search(r"OutOfStock|SoldOut", avail, re.I):
                        return False, "jsonld"

    # 4) unknown
    return None, last_txt

def _extract_images(soup: BeautifulSoup) -> List[str]:
    """
    From Playwright version: ul.altProductImages img with data-image / data-original.
    Upgrade to high-res Scene7 JPGs (fmt=jpg&wid=1800&hei=1800&qlt=92).
    """
    urls = []
    seen = set()
    for img in soup.select("ul.altProductImages img"):
        src = img.get("data-image") or img.get("data-original") or img.get("src") or ""
        if not src:
            continue
        base = src.split("?")[0]
        # Force high-res jpg via Scene7 params if on is/image host
        if "is/image/" in base:
            base = base  # keep path
            full = f"{base}?fmt=jpg&wid=1800&hei=1800&qlt=92"
        else:
            full = base
        if full and full not in seen:
            seen.add(full)
            urls.append(full)

    if not urls:
        for img in soup.select("img[src]"):
            s = img.get("src") or ""
            if not s:
                continue
            base = s.split("?")[0]
            if "product" in base.lower() or "zoom" in base.lower() or "gallery" in base.lower():
                if "is/image/" in base:
                    full = f"{base}?fmt=jpg&wid=1800&hei=1800&qlt=92"
                else:
                    full = base
                if full not in seen:
                    seen.add(full)
                    urls.append(full)

    return urls

# ---------------------------
# Image download (force JPG)
# ---------------------------
def _download_images_jpg(urls: List[str], folder: Path, session: requests.Session) -> List[str]:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    headers = {
        "User-Agent": _ua(),
        "Referer": "https://www.freemans.com/",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }

    for i, u in enumerate(urls, start=1):
        try:
            r = session.get(u, timeout=20, stream=True, headers=headers)
            r.raise_for_status()
            data = r.content

            # Convert to real JPG with Pillow (best-effort)
            try:
                im = Image.open(io.BytesIO(data))
                rgb = im.convert("RGB")
                fp = folder / f"{i:02d}.jpg"
                rgb.save(fp, format="JPEG", quality=92, optimize=True)
                out.append(str(fp))
            except Exception:
                # Raw write with .jpg if Pillow fails
                fp = folder / f"{i:02d}.jpg"
                with open(fp, "wb") as f:
                    f.write(data)
                out.append(str(fp))
        except Exception as e:
            print(f"  ! image error: {u} ({e})")
    return out

# ---------------------------
# Public API
# ---------------------------
def fetch_freemans_product_with_oxylabs(url: str) -> Dict[str, Any]:
    html = _oxylabs_universal_html(url, country="United Kingdom", timeout=75)
    soup = BeautifulSoup(html, "lxml")

    name = _extract_name(soup)
    price, price_src = _extract_price(soup)
    description = _extract_description(soup)
    in_stock, avail_msg = _extract_stock(soup)
    image_urls = _extract_images(soup)

    # Download images as JPG
    folder = SAVE_ROOT / f"{_retailer_slug(url)}_{_safe_name(name)}_{_stable_id_from_url(url)}"
    sess = _session_with_retries()
    imgs = _download_images_jpg(image_urls, folder, sess)

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
#     TEST_URL = "https://www.freemans.com/products/laura-ashley-jug-kettle-china-rose/_/A-64H070_?PFM_rsn=browse&PFM_ref=false&PFM_psp=own&PFM_pge=1&PFM_lpn=1"
#     data = fetch_freemans_product_with_oxylabs(TEST_URL)
#     print(json.dumps(data, indent=2, ensure_ascii=False))



