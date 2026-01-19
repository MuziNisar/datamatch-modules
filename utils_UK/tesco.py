# import re, json, html, hashlib, requests
# from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
# from pathlib import Path
# from playwright.sync_api import sync_playwright

# # ---------- paths (relative to this script) ----------
# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()
# SAVE_DIR = BASE_DIR / "data1"

# UA_STR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#           "AppleWebKit/537.36 (KHTML, like Gecko) "
#           "Chrome/127.0.0.0 Safari/537.36")

# EXTRA_HEADERS = {
#     "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
#     "accept-language": "en-GB,en;q=0.9",
#     "sec-ch-ua": '"Google Chrome";v="127", "Chromium";v="127", "Not;A=Brand";v="24"',
#     "sec-ch-ua-mobile": "?0",
#     "sec-ch-ua-platform": '"Windows"',
#     "upgrade-insecure-requests": "1",
# }

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
#     return "https:" + u if u.startswith("//") else u

# def _drop_query(u: str) -> str:
#     parts = list(urlsplit(u))
#     parts[3] = ""
#     parts[4] = ""
#     return urlunsplit(parts)

# def _img_1600(u: str) -> str:
#     parts = list(urlsplit(u))
#     q = dict(parse_qsl(parts[3], keep_blank_values=True))
#     q["h"] = "1600"
#     q["w"] = "1600"
#     parts[3] = urlencode(q)
#     return urlunsplit(parts)

# def _jsonld_products(page):
#     items = []
#     try:
#         for raw in page.locator('script[type="application/ld+json"]').all_inner_texts():
#             try:
#                 data = json.loads(raw)
#             except:
#                 continue
#             objs = data if isinstance(data, list) else [data]
#             for o in objs:
#                 if isinstance(o, dict) and o.get("@type") == "Product":
#                     items.append(o)
#     except:
#         pass
#     return items

# def _build_folder(url, name):
#     return SAVE_DIR / f"{_retailer_slug(url)}_{_safe_name(name)}_{_stable_id_from_url(url)}"

# def _create_context(p, engine="chromium", *, channel=None, headless=True, user_data_dir=None, disable_http2=False):
#     args = ["--lang=en-GB", "--disable-blink-features=AutomationControlled"]
#     if disable_http2:
#         args.append("--disable-http2")
#     viewport = {"width": 1366, "height": 900}

#     if engine == "chromium":
#         if user_data_dir:
#             ctx = p.chromium.launch_persistent_context(
#                 user_data_dir, headless=headless, channel=channel,
#                 args=args, locale="en-GB", timezone_id="Europe/London",
#                 user_agent=UA_STR, ignore_https_errors=True, viewport=viewport
#             )
#             return ctx, None
#         else:
#             browser = p.chromium.launch(headless=headless, channel=channel, args=args)
#             ctx = browser.new_context(locale="en-GB", timezone_id="Europe/London",
#                                       user_agent=UA_STR, ignore_https_errors=True,
#                                       viewport=viewport, extra_http_headers=EXTRA_HEADERS)
#             return ctx, browser

#     if engine == "firefox":
#         browser = p.firefox.launch(headless=headless, args=["-profile", ""])
#         ctx = browser.new_context(locale="en-GB", timezone_id="Europe/London",
#                                   user_agent=UA_STR, ignore_https_errors=True,
#                                   viewport=viewport, extra_http_headers=EXTRA_HEADERS)
#         return ctx, browser

#     raise ValueError("Unknown engine")

# def _goto_with_retries(page, url):
#     for wait in ("domcontentloaded", "load", None):
#         try:
#             if wait:
#                 page.goto(url, timeout=90_000, wait_until=wait)
#             else:
#                 page.goto(url, timeout=90_000)
#             return True
#         except:
#             pass
#     return False

# def scrape_tesco_product(url: str, *, headless: bool = True, user_data_dir: str | None = None):
#     SAVE_DIR.mkdir(parents=True, exist_ok=True)

#     def _try_engine(p, engine, **kw):
#         ctx, browser = _create_context(p, engine=engine, headless=headless, user_data_dir=user_data_dir, **kw)
#         page = ctx.new_page()
#         page.set_extra_http_headers(EXTRA_HEADERS)
#         ok = _goto_with_retries(page, url)
#         return ok, page, ctx, browser

#     with sync_playwright() as p:
#         # 1) Chromium
#         ok, page, ctx, browser = _try_engine(p, "chromium", channel=None, disable_http2=False)
#         if not ok:
#             # 2) Chrome channel
#             try:
#                 ctx.close()
#                 if browser: browser.close()
#             except: pass
#             ok, page, ctx, browser = _try_engine(p, "chromium", channel="chrome", disable_http2=False)

#         if not ok:
#             # 3) Chrome + disable HTTP/2
#             try:
#                 ctx.close()
#                 if browser: browser.close()
#             except: pass
#             ok, page, ctx, browser = _try_engine(p, "chromium", channel="chrome", disable_http2=True)

#         if not ok:
#             # 4) Firefox fallback
#             try:
#                 ctx.close()
#                 if browser: browser.close()
#             except: pass
#             ok, page, ctx, browser = _try_engine(p, "firefox")

#         if not ok:
#             raise RuntimeError("Could not open Tesco PDP (edge blocked all attempts).")

#         # Accept cookies (best effort)
#         for sel in (
#             "#onetrust-accept-btn-handler",
#             "button#onetrust-accept-btn-handler",
#             "button:has-text('Accept all cookies')",
#             "button:has-text('Accept All')",
#             "button:has-text('Accept')",
#         ):
#             try:
#                 page.locator(sel).first.click(timeout=1500)
#                 break
#             except:
#                 pass

#         # ---------- NAME ----------
#         name = "N/A"
#         try:
#             name = _clean(page.locator('[data-auto="pdp-product-title"]').first.inner_text(timeout=6000)) or "N/A"
#         except:
#             pass
#         if name == "N/A":
#             for o in _jsonld_products(page):
#                 if o.get("name"):
#                     name = _clean(o["name"])
#                     break
#         if name == "N/A":
#             try:
#                 name = _clean(page.locator("h1").first.inner_text(timeout=2000)) or "N/A"
#             except:
#                 pass

#         # ---------- PRICE ----------
#         price = "N/A"
#         try:
#             price = _clean(page.locator("p[class*='priceText']").first.inner_text(timeout=5000))
#         except:
#             pass
#         if price == "N/A":
#             for o in _jsonld_products(page):
#                 offers = o.get("offers")
#                 if isinstance(offers, dict) and offers.get("price"):
#                     price = f"£{offers['price']}"
#                     break

#         # ---------- STOCK ----------
#         in_stock = None
#         try:
#             # Explicit out-of-stock message
#             if page.locator("span:has-text(\"This product's currently out of stock\")").first.is_visible():
#                 in_stock = False
#         except:
#             pass
#         if in_stock is None:
#             try:
#                 # Add button if available
#                 if page.locator('[data-auto="ddsweb-quantity-controls-add-button"]').first.is_visible():
#                     in_stock = True
#             except:
#                 pass

#         # ---------- DESCRIPTION & SELLER ----------
#         description = "N/A"
#         seller = ""
#         try:
#             # Grab the block after the "Description" heading
#             h = page.locator("h3", has_text="Description").first
#             desc_txt = h.evaluate("el => (el.nextElementSibling && el.nextElementSibling.innerText) || ''")
#             desc_txt = _clean(desc_txt)
#             if desc_txt and len(desc_txt) > 40:
#                 description = desc_txt
#         except:
#             pass
#         if description == "N/A":
#             for o in _jsonld_products(page):
#                 if isinstance(o.get("description"), str):
#                     cand = _clean(o["description"])
#                     if len(cand) > 40:
#                         description = cand
#                         break

#         # Seller line (e.g., "Sold by ...")
#         try:
#             sel = page.get_by_text("Sold by", exact=False).first
#             if sel.is_visible():
#                 seller = _clean(sel.inner_text())
#         except:
#             pass

#         # ---------- IMAGES ----------
#         img_urls = []
#         try:
#             thumbs = page.locator('[data-testid="image-slider"] img').all()
#             seen = set()
#             for im in thumbs:
#                 u = im.get_attribute("src") or ""
#                 if not u:
#                     continue
#                 u = _abs(u)
#                 base = _drop_query(u)
#                 if base not in seen:
#                     seen.add(base)
#                     img_urls.append(_img_1600(u))
#         except:
#             pass
#         if not img_urls:
#             for o in _jsonld_products(page):
#                 imgs = o.get("image")
#                 if imgs:
#                     if isinstance(imgs, str):
#                         imgs = [imgs]
#                     img_urls = [_img_1600(_abs(u)) for u in imgs]
#                     break

#         # ---------- DOWNLOAD ----------
#         folder = _build_folder(url, name if name != "N/A" else "Tesco_Product")
#         folder.mkdir(parents=True, exist_ok=True)

#         downloaded = []
#         with requests.Session() as s:
#             s.headers.update({
#                 "User-Agent": UA_STR,
#                 "Referer": url,
#                 "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
#             })
#             for i, u in enumerate(img_urls, 1):
#                 try:
#                     r = s.get(u, timeout=25)
#                     if r.ok and r.content:
#                         ext = ".jpg"
#                         ct = (r.headers.get("Content-Type") or "").lower()
#                         if "webp" in ct: ext = ".webp"
#                         elif "png" in ct: ext = ".png"
#                         path = folder / f"image_{i}{ext}"
#                         path.write_bytes(r.content)
#                         downloaded.append(str(path))
#                 except Exception as e:
#                     print(f"⚠️ Could not download {u}: {e}")

#         # Debug snapshot if everything failed
#         if name == "N/A" and price == "N/A" and not downloaded:
#             try:
#                 (folder / "page.html").write_text(page.content(), encoding="utf-8")
#                 page.screenshot(path=str(folder / "page.png"), full_page=True)
#                 print(f"Saved debug snapshot to {folder}")
#             except:
#                 pass

#         ctx.close()
#         if browser:
#             browser.close()

#     return {
#         "name": name,
#         "price": price,
#         "in_stock": in_stock,
#         "description": description,
#         "seller": seller,
#         "image_count": len(downloaded),
#         "images": downloaded,
#         "folder": str(folder),
#     }












# tesco_oxylabs.py (fixed)
# Python 3.9+
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
def parse_tesco(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
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
    # Do NOT match message templates like "This product’s currently out of stock" in JSON.
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
                                      geo: str = "United Kingdom") -> Dict[str, Any]:
    html = oxy_fetch_html(url, geo=geo)
    parsed = parse_tesco(html)

    folder = SAVE_DIR / f"{_retailer_slug(url)}_{_safe_name(parsed['name'] if parsed['name'] != 'N/A' else 'Tesco_Product')}_{_stable_id_from_url(url)}"

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
        "mode": "oxylabs(html)+direct(images)"
    }

# # ---------------------------
# # CLI
# # ---------------------------
# if __name__ == "__main__":
#     TEST_URL = "https://www.tesco.com/groceries/en-GB/products/311757809"
#     print(json.dumps(
#         scrape_tesco_product_with_oxylabs(
#             TEST_URL,
#             download_images_flag=True,
#             max_images=12,
#             force_jpg=True,
#             geo="United Kingdom"
#         ),
#         indent=2, ensure_ascii=False
#     ))

