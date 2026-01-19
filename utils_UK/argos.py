# import os
# import re
# import json
# import time
# import requests
# from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
# from playwright.sync_api import sync_playwright

# ARGOS_CDN_HOST = "media.4rgos.it"
# ARGOS_CDN_PATH_PREFIX = "/i/Argos/"

# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "")).strip()

# def _safe_folder(name: str) -> str:
#     safe = re.sub(r"[^\w\s-]", "", name or "").strip().replace(" ", "_")
#     return safe or "Unknown_Product"

# def _get_product_id(url: str, html: str) -> str | None:
#     # 1) from URL
#     m = re.search(r"/product/(\d{7})", url)
#     if m:
#         return m.group(1)
#     # 2) JSON-LD: sku
#     for txt in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, flags=re.S):
#         try:
#             data = json.loads(txt)
#             if isinstance(data, dict):
#                 sku = data.get("sku") or data.get("mpn")
#                 if isinstance(sku, str) and re.fullmatch(r"\d{7}", sku):
#                     return sku
#         except Exception:
#             pass
#     # 3) Any inline “sku”: "4841227"
#     m = re.search(r'"sku"\s*:\s*"(\d{7})"', html)
#     return m.group(1) if m else None

# def _extract_gallery_asset_bases(html: str, product_id: str) -> list[str]:
#     """
#     Return unique base asset names like: 4841227_R_Z001A (no query/format).
#     Only keep assets that start with this product_id_ to avoid cross-page junk.
#     """
#     # Grab every Argos CDN URL on the page
#     # (both //media.4rgos.it/... and https://media.4rgos.it/...)
#     urls = re.findall(r"(?:https:)?//media\.4rgos\.it/i/Argos/([^\s\"'<>?]+)", html)

#     # Keep only the ones for this product id
#     bases = []
#     seen = set()
#     for path in urls:
#         base = path.split("?")[0]            # strip query
#         base = base.split(",")[0]            # strip srcset extra
#         file = base.rsplit("/", 1)[-1]       # just the filename part
#         if not file.startswith(product_id + "_"):
#             continue
#         if file not in seen:
#             seen.add(file)
#             bases.append(file)
#     return bases

# def _sort_argos_bases(bases: list[str]) -> list[str]:
#     """
#     Sort like Z001A, Z002A, ... if present; fallback to plain alpha.
#     """
#     def key(fn: str):
#         # e.g. 4841227_R_Z003A -> Z003 -> 3
#         m = re.search(r"_Z(\d{3})", fn)
#         return (0, int(m.group(1))) if m else (1, fn)
#     return sorted(bases, key=key)

# def _compose_hq_url(base_file: str, fmt="jpeg", w=1500, h=880, qlt="95") -> str:
#     # Build a single canonical HQ URL for each base file
#     return f"https://{ARGOS_CDN_HOST}{ARGOS_CDN_PATH_PREFIX}{base_file}?w={w}&h={h}&qlt={qlt}&fmt={fmt}"

# from pathlib import Path

# BASE_DIR = Path(__file__).resolve().parent
# DEFAULT_SAVE_DIR = BASE_DIR / "data1"

# def scrape_argos_product(url, save_dir=DEFAULT_SAVE_DIR):
#     with sync_playwright() as p:
#         browser = p.chromium.launch(
#             headless=False,
#             args=["--window-position=-32000,-32000"]
#         )
#         page = browser.new_page(
#             viewport={"width": 1400, "height": 1000},
#             user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#                         "AppleWebKit/537.36 (KHTML, like Gecko) "
#                         "Chrome/120.0.0.0 Safari/537.36")
#         )

#         try:
#             page.goto(url, timeout=90000, wait_until="domcontentloaded")
#             page.wait_for_load_state("load", timeout=30000)

#             # Cookie banner (best-effort)
#             for sel in (
#                 "#onetrust-accept-btn-handler",
#                 "[data-test='ot-accept-all-button']",
#                 "button[aria-label='Accept All']",
#                 "button:has-text('Accept all')",
#             ):
#                 try:
#                     page.locator(sel).click(timeout=1200)
#                     break
#                 except:
#                     pass

#             # Smoothly trigger lazy areas
#             try:
#                 page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
#                 time.sleep(0.5)
#                 page.evaluate("window.scrollTo(0, 0)")
#                 time.sleep(0.3)
#             except:
#                 pass

#             html = page.content()

#             # ---------- NAME ----------
#             name = "N/A"
#             try:
#                 name = _clean(page.locator("[data-test='product-title'][itemprop='name']").first.inner_text(timeout=12000))
#             except:
#                 try:
#                     name = _clean(page.locator("[data-test='product-title']").first.inner_text(timeout=12000))
#                 except:
#                     # JSON-LD fallback
#                     for txt in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, flags=re.S):
#                         try:
#                             data = json.loads(txt)
#                             if isinstance(data, dict) and data.get("name"):
#                                 name = _clean(data["name"])
#                                 break
#                         except:
#                             pass

#             # ---------- PRICE ----------
#             price = "N/A"
#             try:
#                 price = _clean(page.locator("h2:has-text('£')").first.inner_text(timeout=12000))
#             except:
#                 pass

#             # ---------- STOCK ----------
#             in_stock = None
#             try:
#                 btn = _clean(page.locator("button[data-test='add-to-trolley-button-button']").first.inner_text(timeout=12000))
#                 in_stock = "add" in btn.lower()
#             except:
#                 pass

#             # ---------- DESCRIPTION ----------
#             description = "N/A"
#             try:
#                 page.wait_for_selector("div.product-description-content-text", timeout=20000)
#                 desc_html = page.locator("div.product-description-content-text").inner_html()
#                 description = _clean(re.sub(r"<[^>]+>", " ", desc_html))
#             except:
#                 # JSON-LD fallback
#                 for txt in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, flags=re.S):
#                     try:
#                         data = json.loads(txt)
#                         if isinstance(data, dict) and data.get("description"):
#                             description = _clean(data["description"])
#                             break
#                     except:
#                         pass

#             # ---------- IMAGES (no clicking, no thumbnails spam) ----------
#             product_id = _get_product_id(url, html)
#             bases = _extract_gallery_asset_bases(html, product_id) if product_id else []
#             bases = _sort_argos_bases(bases)

#             # If for some reason we didn't find any with the product_id filter,
#             # fall back to the thumbnails container only (still deduped by filename).
#             if not bases:
#                 try:
#                     thumbs_html = page.locator("[data-test='component-media-gallery-thumbnails_landscape']").first.inner_html(timeout=8000)
#                     candidates = re.findall(r"(?:https:)?//media\.4rgos\.it/i/Argos/([^\s\"'<>?]+)", thumbs_html)
#                     seen = set()
#                     for path in candidates:
#                         file = path.split("?")[0].split(",")[0].rsplit("/", 1)[-1]
#                         if file not in seen:
#                             seen.add(file)
#                             bases.append(file)
#                     bases = _sort_argos_bases(bases)
#                 except:
#                     pass

#             # Compose final HQ URLs (force JPEG to keep extension simple)
#             final_urls = [_compose_hq_url(b, fmt="jpeg") for b in bases]

#             # ---------- DOWNLOAD ----------
#             folder = os.path.join(save_dir, _safe_folder(name))
#             os.makedirs(folder, exist_ok=True)

#             try:
#                 UA = page.evaluate("() => navigator.userAgent")
#             except:
#                 UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#                       "AppleWebKit/537.36 (KHTML, like Gecko) "
#                       "Chrome/120.0.0.0 Safari/537.36")

#             session = requests.Session()
#             session.headers.update({
#                 "User-Agent": UA,
#                 "Referer": "https://www.argos.co.uk/",
#                 "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
#                 "Accept-Language": "en-GB,en;q=0.9",
#                 "Connection": "keep-alive"
#             })

#             downloaded = []
#             for i, u in enumerate(final_urls, 1):
#                 try:
#                     r = session.get(u, timeout=25)
#                     if r.status_code == 200 and r.content:
#                         path = os.path.join(folder, f"image_{i}.jpg")
#                         with open(path, "wb") as f:
#                             f.write(r.content)
#                         downloaded.append(path)
#                 except Exception as e:
#                     print(f"⚠️ Download error: {u}\n   {e}")

#             return {
#                 "name": name or "N/A",
#                 "price": price or "N/A",
#                 "in_stock": in_stock,
#                 "description": description or "N/A",
#                 "image_count": len(downloaded),
#                 "images": downloaded,
#                 "folder": folder
#             }

#         finally:
#             browser.close()









# argos_oxylabs.py — Oxylabs universal + precise price parsing + JPG-only images
# Python 3.10+
# pip install requests beautifulsoup4 lxml pillow pillow-avif-plugin

from __future__ import annotations
import re, json, time, random, hashlib
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from urllib.parse import urldefrag, urlparse, urlsplit, urlunsplit
from io import BytesIO
from datetime import datetime, timezone

import requests
from requests.exceptions import RequestException
from bs4 import BeautifulSoup
from PIL import Image

# Optional AVIF/HEIF support
try:
    import pillow_avif  # noqa: F401
except Exception:
    pass

# -----------------------------
# Config
# -----------------------------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception as e:
    raise RuntimeError("Missing oxylabs_secrets.py with OXY_USER and OXY_PASS") from e
if not (OXY_USER and OXY_PASS):
    raise RuntimeError("OXY_USER/OXY_PASS in oxylabs_secrets.py must be non-empty.")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
ACCEPT_LANG = "en-GB,en;q=0.9"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data_argos"
DEBUG_DIR = BASE_DIR / "debug"
DATA_DIR.mkdir(exist_ok=True)
DEBUG_DIR.mkdir(exist_ok=True)

OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"
GEO = "United Kingdom"

# Argos CDN rules
ARGOS_CDN_HOST = "media.4rgos.it"
ARGOS_CDN_PATH_PREFIX = "/i/Argos/"

# -----------------------------
# Small utils
# -----------------------------
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _clean_multiline(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _safe_name(s: str) -> str:
    s = _clean(s)
    return re.sub(r"[^\w.\-]+", "_", s)[:120] or "Unknown_Product"

def _stable_id_from_url(url: str) -> str:
    try:
        url, _ = urldefrag(url)
        m = re.search(r"/product/(\d{7})", url)
        if m:
            return m.group(1)
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
            seen.add(k); out.append(u)
    return out

def _strip_query(u: str) -> str:
    sp = urlsplit(u)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

def _to_float(x: str) -> Optional[float]:
    try:
        return float(x.replace(",", "").strip())
    except Exception:
        return None

# GBP -> ("xx.xx GBP", float)
def _parse_gbp_container(el: BeautifulSoup) -> Tuple[Optional[str], Optional[float]]:
    if not el:
        return None, None
    # Preferred: microdata itemprop=price content="54.99"
    m = el.get("content")
    if m:
        f = _to_float(m)
        if f is not None:
            return f"{f:.2f} GBP", f
    # H2 text like £54.99
    txt = _clean(el.get_text(" ", strip=True))
    m = re.search(r"£\s*([\d,]+(?:\.\d{1,2})?)", txt)
    if m:
        val = m.group(1).replace(",", "")
        if "." not in val:
            val = f"{val}.00"
        try:
            f = float(val)
            return f"{f:.2f} GBP", f
        except Exception:
            return f"{val} GBP", _to_float(val)
    return None, None

# -----------------------------
# Argos-specific helpers
# -----------------------------
def _get_product_id(url: str, html: str) -> Optional[str]:
    m = re.search(r"/product/(\d{7})", url)
    if m:
        return m.group(1)
    for txt in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, flags=re.S):
        try:
            data = json.loads(txt)
            if isinstance(data, dict):
                sku = data.get("sku") or data.get("mpn")
                if isinstance(sku, str) and re.fullmatch(r"\d{7}", sku):
                    return sku
        except Exception:
            pass
    m = re.search(r'"sku"\s*:\s*"(\d{7})"', html)
    return m.group(1) if m else None

def _extract_gallery_asset_bases(html: str, product_id: str) -> list[str]:
    urls = re.findall(r"(?:https:)?//media\.4rgos\.it/i/Argos/([^\s\"'<>?]+)", html)
    bases, seen = [], set()
    for path in urls:
        base = path.split("?")[0].split(",")[0]
        file = base.rsplit("/", 1)[-1]
        if not file.startswith(product_id + "_"):
            continue
        if file not in seen:
            seen.add(file)
            bases.append(file)
    return bases

def _sort_argos_bases(bases: list[str]) -> list[str]:
    def key(fn: str):
        m = re.search(r"_Z(\d{3})", fn)
        return (0, int(m.group(1))) if m else (1, fn)
    return sorted(bases, key=key)

def _compose_hq_url(base_file: str, fmt="jpeg", w=1500, h=880, qlt="95") -> str:
    return f"https://{ARGOS_CDN_HOST}{ARGOS_CDN_PATH_PREFIX}{base_file}?w={w}&h={h}&qlt={qlt}&fmt={fmt}"

# -----------------------------
# Oxylabs client (no browser_instructions)
# -----------------------------
def _build_context_array(session_id: Optional[str]) -> list[dict]:
    ctx: list[dict] = []
    if session_id:
        ctx.append({"key": "session_id", "value": session_id})
    ctx.append({
        "key": "headers",
        "value": {
            "User-Agent": UA,
            "Accept-Language": ACCEPT_LANG
        }
    })
    return ctx

def _parse_retry_after(headers: Dict[str, str]) -> Optional[float]:
    ra = headers.get("Retry-After")
    if ra:
        try:
            return float(ra)
        except ValueError:
            try:
                dt = datetime.strptime(ra, "%a, %d %b %Y %H:%M:%S %Z")
                return max(0.0, (dt.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds())
            except Exception:
                pass
    xr = headers.get("X-RateLimit-Reset") or headers.get("X-Ratelimit-Reset")
    if xr:
        try:
            return max(0.0, float(xr) - time.time())
        except Exception:
            pass
    return None

def oxy_post(payload: dict, retries: int = 6, base_sleep: float = 2.0) -> dict:
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(OXY_ENDPOINT, auth=(OXY_USER, OXY_PASS), json=payload, timeout=120)
            if r.status_code == 200:
                data = r.json()
                results = data.get("results") or []
                if not results:
                    raise RuntimeError("Oxylabs: empty results")
                content = results[0].get("content", "")
                if "<html" not in content.lower():
                    raise RuntimeError("Oxylabs: non-HTML content")
                return data

            if r.status_code in (429, 500, 502, 503, 504):
                wait = _parse_retry_after(r.headers)
                if wait is None:
                    wait = (base_sleep * (2 ** attempt)) + random.uniform(0.25, 0.75)
                time.sleep(min(wait, 30.0))
                continue

            try:
                err_json = r.json()
                raise RuntimeError(f"Oxylabs HTTP {r.status_code}: {err_json}")
            except ValueError:
                raise RuntimeError(f"Oxylabs HTTP {r.status_code}: {r.text[:500]}")

        except (RequestException, ValueError, RuntimeError) as e:
            last_err = e
            if attempt < retries:
                wait = (base_sleep * (2 ** attempt)) + random.uniform(0.25, 0.75)
                time.sleep(min(wait, 10.0))
                continue
            raise RuntimeError(f"Oxylabs failed after {retries+1} attempts: {e}") from e
    raise last_err or RuntimeError("Oxylabs unknown error")

def oxy_fetch_html(url: str, geo: str = GEO) -> str:
    url, _ = urldefrag(url)
    session_id = f"argos-{int(time.time())}-{random.randint(1000,9999)}"
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
        "geo_location": geo,
        "user_agent_type": "desktop",
        "context": _build_context_array(session_id),
    }
    data = oxy_post(payload)
    return data["results"][0]["content"]

# -----------------------------
# Image download (ALWAYS .jpg)
# -----------------------------
def _img_to_jpg_bytes(raw: bytes) -> bytes:
    with Image.open(BytesIO(raw)) as im:
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            im_rgba = im.convert("RGBA")
            bg.paste(im_rgba, mask=im_rgba.split()[-1])
            out = BytesIO()
            bg.save(out, format="JPEG", quality=92, optimize=True, progressive=True)
            return out.getvalue()
        if im.mode != "RGB":
            im = im.convert("RGB")
        out = BytesIO()
        im.save(out, format="JPEG", quality=92, optimize=True, progressive=True)
        return out.getvalue()

def download_images_jpg(urls: List[str], folder: Path, referer: str, max_images: Optional[int] = None) -> List[str]:
    if max_images is not None:
        urls = urls[:max_images]
    saved = []
    folder.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Referer": "https://www.argos.co.uk/",
    }
    for i, u in enumerate(urls, 1):
        try:
            u = _strip_query(u)
            with requests.get(u, headers=headers, timeout=40) as r:
                ct = (r.headers.get("Content-Type", "") or "").lower()
                if r.status_code == 200 and (ct.startswith("image/") or r.content):
                    out = folder / f"{i:02d}.jpg"
                    try:
                        out.write_bytes(_img_to_jpg_bytes(r.content))
                        saved.append(str(out))
                    except Exception as pe:
                        if ct.startswith(("image/jpeg", "image/jpg")):
                            out.write_bytes(r.content)
                            saved.append(str(out))
                        else:
                            print("  ! convert error:", u, pe)
                else:
                    print("  ! image HTTP", r.status_code, u, ct)
        except Exception as e:
            print("  ! image error:", u, e)
    return saved

# -----------------------------
# Parser (Argos) — precise price selection
# -----------------------------
def parse_argos(html: str, url: str) -> Dict:
    soup = BeautifulSoup(html, "lxml")

    # NAME
    name = ""
    el = soup.select_one("[data-test='product-title'][itemprop='name']") or soup.select_one("[data-test='product-title']")
    if el:
        name = _clean(el.get_text(" ", strip=True))
    if not name and soup.title:
        name = _clean(soup.title.get_text().split("|")[0])
    name = name or "Unknown Product"

    # PRICE (prefer primary price container)
    price_str, price_value, price_source = "N/A", None, "none"

    # 1) Primary price: <li data-test="product-price-primary" itemprop="price" content="54.99"><h2>£54.99</h2>
    primary_li = soup.select_one('[data-test="product-price-primary"][itemprop="price"]')
    if primary_li:
        price_str, price_value = _parse_gbp_container(primary_li)
        if price_value is not None:
            price_source = "onsite"

    # 2) If content attr not present, read the <h2> inside the primary block
    if price_value is None:
        primary_block = soup.select_one('[data-test="product-price-primary"]')
        if primary_block:
            price_str, price_value = _parse_gbp_container(primary_block.find("h2") or primary_block)
            if price_value is not None:
                price_source = "onsite"

    # 3) JSON-LD Offer fallback
    if price_value is None:
        for txt in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, flags=re.S):
            try:
                data = json.loads(txt)
                if isinstance(data, dict):
                    offers = data.get("offers")
                    if isinstance(offers, dict):
                        p = _to_float(str(offers.get("price", "")).strip())
                        if p is not None:
                            price_value = p
                            price_str = f"{p:.2f} GBP"
                            price_source = "jsonld"
                            break
                elif isinstance(data, list):
                    for d in data:
                        if isinstance(d, dict) and isinstance(d.get("offers"), dict):
                            p = _to_float(str(d["offers"].get("price", "")).strip())
                            if p is not None:
                                price_value = p
                                price_str = f"{p:.2f} GBP"
                                price_source = "jsonld"
                                break
            except Exception:
                pass

    # 4) Strict fallback within price container only (avoid monthly/upsell prices)
    if price_value is None:
        price_wrap = soup.select_one('.PriceContainerstyles__PriceContainer-sc-3awrsy-0') \
                     or soup.find(lambda t: t and t.name in ("div", "section") and "Price" in t.get("class", []) if hasattr(t, "get") else False)
        if price_wrap:
            m = re.search(r"£\s*([\d,]+(?:\.\d{1,2})?)", _clean(price_wrap.get_text(" ", strip=True)))
            if m:
                v = m.group(1).replace(",", "")
                try:
                    price_value = float(v if "." in v else f"{v}.00")
                    price_str = f"{price_value:.2f} GBP"
                    price_source = "onsite"
                except Exception:
                    pass

    # STOCK
    in_stock = None
    atc = soup.select_one("button[data-test='add-to-trolley-button-button'], [data-test='add-to-trolley-button-button']")
    if atc:
        btn_txt = _clean(atc.get_text(" ", strip=True)).lower()
        in_stock = ("add" in btn_txt) or ("trolley" in btn_txt)
    # textual negatives
    page_txt = _clean(soup.get_text(" ", strip=True)).lower()
    if any(w in page_txt for w in ["out of stock", "sold out", "unavailable"]):
        in_stock = False

    # DESCRIPTION
    description = ""
    desc_block = soup.select_one("div.product-description-content-text")
    if desc_block:
        description = _clean_multiline(desc_block.get_text("\n", strip=True))
    if not description:
        for txt in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, flags=re.S):
            try:
                data = json.loads(txt)
                if isinstance(data, dict) and data.get("description"):
                    description = _clean_multiline(data["description"])
                    break
            except Exception:
                pass

    # IMAGES
    product_id = _get_product_id(url, html)
    bases = _extract_gallery_asset_bases(html, product_id) if product_id else []
    bases = _sort_argos_bases(bases)

    if not bases:
        thumbs = soup.select_one("[data-test='component-media-gallery-thumbnails_landscape']")
        if thumbs:
            candidates = re.findall(r"(?:https:)?//media\.4rgos\.it/i/Argos/([^\s\"'<>?]+)", str(thumbs))
            seen = set()
            for path in candidates:
                file = path.split("?")[0].split(",")[0].rsplit("/", 1)[-1]
                if file not in seen:
                    seen.add(file)
                    bases.append(file)
            bases = _sort_argos_bases(bases)

    image_urls = [_compose_hq_url(b, fmt="jpeg") for b in bases]
    image_urls = _dedupe_preserve(image_urls)

    return {
        "name": name,
        "price": price_str,
        "price_value": price_value,
        "currency": "GBP" if price_value is not None else None,
        "price_source": price_source,
        "in_stock": in_stock,
        "description": description,
        "image_urls": image_urls
    }

# -----------------------------
# Orchestrator
# -----------------------------
def scrape_argos_with_oxylabs(url: str,
                              download_images_flag: bool = True,
                              max_images: Optional[int] = None) -> Dict:
    html = oxy_fetch_html(url, geo=GEO)
    parsed = parse_argos(html, url)

    folder = DATA_DIR / f"argos_{_safe_name(parsed['name'])}_{_stable_id_from_url(url)}"
    folder.mkdir(parents=True, exist_ok=True)

    images_downloaded: List[str] = []
    if download_images_flag and parsed["image_urls"]:
        print(f"Downloading {len(parsed['image_urls']) if not max_images else min(len(parsed['image_urls']), max_images)} images …")
        images_downloaded = download_images_jpg(parsed["image_urls"], folder, referer=url, max_images=max_images)

    return {
        "url": url,
        "name": parsed["name"],
        "price": parsed["price"],
        "price_value": parsed["price_value"],
        "currency": parsed["currency"],
        "price_source": parsed["price_source"],
        "in_stock": parsed["in_stock"],
        "description": parsed["description"],
        "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
        "image_urls": parsed["image_urls"],
        "images_downloaded": images_downloaded,
        "folder": str(folder),
        "mode": "oxylabs-universal"
    }

# # -----------------------------
# # CLI
# # -----------------------------
# if __name__ == "__main__":
#     TEST_URL = "https://www.argos.co.uk/product/4841227"
#     data = scrape_argos_with_oxylabs(TEST_URL, download_images_flag=True, max_images=20)
#     print(json.dumps(data, indent=2, ensure_ascii=False))

