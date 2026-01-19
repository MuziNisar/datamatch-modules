# import re
# import html
# import requests
# from pathlib import Path
# from playwright.sync_api import sync_playwright


# # --- put this near your other helpers ---
# import json

# def _jsonld_availability(page):
#     """Return True/False if availability is stated in JSON-LD; else None."""
#     try:
#         for raw in page.locator("script[type='application/ld+json']").all_inner_texts():
#             try:
#                 data = json.loads(raw)
#             except Exception:
#                 continue
#             objs = data if isinstance(data, list) else [data]
#             for o in objs:
#                 if not isinstance(o, dict):
#                     continue
#                 offers = o.get("offers")
#                 if not offers:
#                     # sometimes nested in @graph
#                     if isinstance(o.get("@graph"), list):
#                         for g in o["@graph"]:
#                             if isinstance(g, dict) and g.get("@type") == "Product":
#                                 offers = g.get("offers")
#                                 break
#                 if not offers:
#                     continue
#                 offers_list = offers if isinstance(offers, list) else [offers]
#                 for off in offers_list:
#                     if not isinstance(off, dict):
#                         continue
#                     avail = str(off.get("availability") or off.get("itemAvailability") or "")
#                     if re.search(r"InStock", avail, re.I):   return True
#                     if re.search(r"OutOfStock|SoldOut", avail, re.I): return False
#         return None
#     except Exception:
#         return None


# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


# def _safe_name(s: str) -> str:
#     n = re.sub(r"[^\w\s-]", "", (s or "")).strip().replace(" ", "_")
#     return n or "NA"


# def _wf_to_hires(u: str, size: int = 1600) -> str:
#     """
#     Normalize Wayfair CDN URLs to higher-res:
#       https://assets.wfcdn.com/im/<hash>/resize-h48-w48%5Ecompr-r65/2984/298437615/file.jpg
#         -> resize-h1600-w1600%5Ecompr-r85
#     Works whether '^' is encoded as %5E or literal.
#     """
#     if not u:
#         return u
#     u = u.replace(" ", "%20")
#     # Handle encoded and literal '^' variants
#     u = re.sub(r"/resize-h\d+-w\d+%5Ecompr-r\d+/", f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
#     u = re.sub(r"/resize-h\d+-w\d+\^compr-r\d+/",  f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
#     # If no resize segment exists, insert one after '/im/<hash>/'
#     if "/resize-" not in u:
#         u = re.sub(r"(https://assets\.wfcdn\.com/im/[^/]+/)",
#                    rf"\1resize-h{size}-w{size}%5Ecompr-r85/", u)
#     return u


# def scrape_wayfair_USA_product(url: str, save_dir: Path | None = None) -> dict:
#     # ---- Save folder next to this script (portable/relative path) ----
#     if save_dir is None:
#         save_dir = Path(__file__).resolve().parent / "data1"
#     save_dir.mkdir(parents=True, exist_ok=True)

#     UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#           "AppleWebKit/537.36 (KHTML, like Gecko) "
#           "Chrome/123.0.0.0 Safari/537.36")

#     with sync_playwright() as p:
#         browser = p.chromium.launch(headless=False, args=["--window-position=-32000,-32000"])
#         context = browser.new_context(
#             user_agent=UA,
#             viewport={"width": 1366, "height": 900},
#             locale="en-GB"
#         )
#         page = context.new_page()
#         page.goto(url, timeout=90000, wait_until="domcontentloaded")

#         # Cookie banners (best effort)
#         for sel in (
#             "#onetrust-accept-btn-handler",
#             "button#onetrust-accept-btn-handler",
#             "button:has-text('Accept All Cookies')",
#             "button:has-text('Accept All')",
#             "button:has-text('Accept')",
#         ):
#             try:
#                 page.locator(sel).first.click(timeout=1200)
#                 break
#             except Exception:
#                 pass

#         # -------- NAME --------
#         try:
#             name = _clean(page.locator("h1[data-rtl-id='listingHeaderNameHeading']").first.inner_text(timeout=6000))
#         except Exception:
#             name = "N/A"

#         # -------- PRICE --------
#         try:
#             price = _clean(page.locator("[data-test-id='PriceDisplay']").first.inner_text(timeout=6000))
#         except Exception:
#             price = "N/A"

#         # -------- STOCK --------
#         # -------- STOCK (robust) --------
#         in_stock = None

#         # 1) Explicit "Out of Stock" / "Not available" banners
#         try:
#             oos_selectors = [
#                 "text=Out of Stock",
#                 "text=Not available",
#                 "[data-test-id='outOfStock']",
#                 "[data-test-id='availability']:has-text('Out of Stock')",
#                 "div:has-text('Out of Stock')",
#                 "div:has-text('Not available')",
#             ]
#             for sel in oos_selectors:
#                 loc = page.locator(sel).first
#                 if loc.count() > 0 and loc.is_visible():
#                     in_stock = False
#                     break
#         except Exception:
#             pass

#         # 2) Real Add-to-Cart button presence/enablement
#         if in_stock is None:
#             try:
#                 atc = page.locator(
#                     "button[data-testing-id='atc-button'], form[name='AddItem'] button[type='submit']"
#                 ).first
#                 if atc.count() > 0 and atc.is_visible():
#                     if atc.is_enabled():
#                         in_stock = True
#                     else:
#                         # some pages use aria-disabled or a disabled class
#                         disabled_attr = (atc.get_attribute("disabled") or "").lower()
#                         aria_disabled = (atc.get_attribute("aria-disabled") or "").lower()
#                         cls = atc.get_attribute("class") or ""
#                         if disabled_attr == "true" or aria_disabled == "true" or re.search(r"\bdisabled\b", cls, re.I):
#                             in_stock = False
#             except Exception:
#                 pass

#         # 3) JSON-LD availability fallback
#         if in_stock is None:
#             in_stock = _jsonld_availability(page)

#         # 4) Last-resort weak heuristic (only if still None)
#         if in_stock is None:
#             try:
#                 blob = page.locator("body").inner_text(timeout=3000).lower()
#                 if ("add to cart" in blob or "in stock" in blob) and "out of stock" not in blob and "not available" not in blob:
#                     in_stock = True
#             except Exception:
#                 pass

#         # -------- DESCRIPTION (best-effort) --------
#         import json, html as _html, re

#         def _clean_text(t: str) -> str:
#             t = _html.unescape(t or "")
#             # keep intended newlines but tidy everything else
#             t = t.replace("\r", "")
#             t = re.sub(r"[ \t]+", " ", t)
#             t = re.sub(r"\n{3,}", "\n\n", t)
#             return t.strip()

#         def _looks_generic(s: str) -> bool:
#             return bool(re.search(r"you'?ll love .* at wayfair", s, re.I))

#         description = "N/A"
#         blocks = []

#         # 1) Main prose block (the one with pre-line whitespace handling)
#         try:
#             prose = page.locator('[data-hb-id="BoxV3"][style*="pre-line"]').first.inner_text(timeout=4000)
#             prose = _clean_text(prose)
#             if prose and len(prose) > 120:
#                 blocks.append(prose)
#         except: 
#             pass

#         # 2) “Features” bullets following the <p>Features</p> label
#         try:
#             p_feat = page.locator("p[data-hb-id='Text']", has_text="Features").first
#             ul_handle = p_feat.evaluate_handle(
#                 "n => { let el = n.nextElementSibling; while (el && el.tagName !== 'UL') el = el.nextElementSibling; return el; }"
#             )
#             if ul_handle:
#                 items = page.evaluate(
#                     "ul => Array.from(ul.querySelectorAll('li')).map(li => (li.innerText||'').trim()).filter(Boolean)",
#                     ul_handle
#                 )
#                 if items:
#                     blocks.append("Features:\n- " + "\n- ".join(_clean_text(i) for i in items))
#         except:
#             pass

#         if blocks:
#             description = "\n\n".join(blocks)

#         # 3) Fallback to JSON-LD Product.description if we didn’t get anything
#         if description == "N/A":
#             try:
#                 texts = page.locator("script[type='application/ld+json']").all_inner_texts()
#                 best = ""
#                 for txt in texts:
#                     try:
#                         data = json.loads(txt)
#                     except:
#                         continue
#                     for obj in (data if isinstance(data, list) else [data]):
#                         if isinstance(obj, dict):
#                             if obj.get("@type") == "Product" and isinstance(obj.get("description"), str):
#                                 cand = _clean_text(obj["description"])
#                                 if cand and not _looks_generic(cand) and len(cand) > len(best):
#                                     best = cand
#                             if isinstance(obj.get("@graph"), list):
#                                 for g in obj["@graph"]:
#                                     if isinstance(g, dict) and g.get("@type") == "Product" and isinstance(g.get("description"), str):
#                                         cand = _clean_text(g["description"])
#                                         if cand and not _looks_generic(cand) and len(cand) > len(best):
#                                             best = cand
#                 if best:
#                     description = best
#             except:
#                 pass

#         # 4) Final fallback: meta description (only if not generic)
#         if description == "N/A":
#             try:
#                 meta = page.locator("meta[name='description']").first.get_attribute("content") or ""
#                 meta = _clean_text(meta)
#                 if meta and not _looks_generic(meta):
#                     description = meta
#             except:
#                 pass

#         # -------- IMAGES (use thumbnails + main carousel, order preserved) --------
#         # 1) Thumbnails with order via aria-label "... 1 of 7"
#         thumbs = page.evaluate("""
#         () => {
#           const out = [];
#           const btns = document.querySelectorAll('[data-test-id="pdp-mt-thumbnails"] button[aria-label]');
#           btns.forEach(btn => {
#             const lab = btn.getAttribute('aria-label') || '';
#             const m = lab.match(/(\\d+)\\s+of\\s+\\d+/i);
#             const order = m ? parseInt(m[1], 10) : 9999;
#             const img = btn.querySelector('img');
#             const src = img?.currentSrc || img?.src || '';
#             if (src) out.push({src, order});
#           });
#           return out;
#         }
#         """)

#         # 2) Main carousel images (sometimes larger than thumbs)
#         mains = page.evaluate("""
#         () => {
#           const out = [];
#           const imgs = document.querySelectorAll('#MediaTrayCarouselWithThumbnailSidebar img, [data-test-id="pdp-mt-d-mainImageCarousel"] img');
#           imgs.forEach(img => {
#             const src = img.currentSrc || img.src || '';
#             if (src) out.push(src);
#           });
#           return out;
#         }
#         """)

#         # Build ordered list
#         ordered = []
#         if thumbs:
#             for t in sorted(thumbs, key=lambda x: x.get("order", 9999)):
#                 ordered.append(t.get("src", ""))
#         ordered.extend(mains or [])

#         # Normalize to hi-res & dedupe (ignore resize segment when deduping)
#         def _dedup_key(u: str) -> str:
#             u = re.sub(r"/resize-h\d+-w\d+(?:%5E|\^)compr-r\d+/", "/", u)
#             return re.sub(r"[?].*$", "", u)

#         images = []
#         seen = set()
#         for u in ordered:
#             if not u:
#                 continue
#             hu = _wf_to_hires(u, size=1600)
#             key = _dedup_key(hu)
#             if key not in seen:
#                 seen.add(key)
#                 images.append(hu)

#         # Keep first 7 (Wayfair gallery count)
#         images = images[:7]

#         # -------- DOWNLOAD --------
#         folder = save_dir / _safe_name(name)
#         folder.mkdir(parents=True, exist_ok=True)

#         downloaded = []
#         with requests.Session() as s:
#             s.headers.update({
#                 "User-Agent": UA,
#                 "Referer": url,
#                 "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
#                 "Accept-Language": "en-GB,en;q=0.9",
#             })
#             for i, u in enumerate(images, 1):
#                 try:
#                     r = s.get(u, timeout=25)
#                     if r.ok and r.content:
#                         ext = ".jpg"
#                         ct = (r.headers.get("Content-Type") or "").lower()
#                         if "webp" in ct:
#                             ext = ".webp"
#                         elif "png" in ct:
#                             ext = ".png"
#                         path = folder / f"image_{i}{ext}"
#                         path.write_bytes(r.content)
#                         downloaded.append(str(path))
#                 except Exception as e:
#                     print(f"⚠️ Could not download {u}: {e}")

#         browser.close()

#     return {
#         "name": name,
#         "price": price,
#         "in_stock": in_stock,
#         "description": description,
#         "image_count": len(downloaded),
#         "images": downloaded,
#         "folder": str(folder),
#     }













# wayfair.py
# Python 3.10+
# Oxylabs Web Scraper API (universal) -> HTML -> BeautifulSoup parsing
#
# pip install requests beautifulsoup4 lxml pillow

from __future__ import annotations

import os
import re
import io
import json
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup
from PIL import Image

# ========= Secrets =========
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS  # type: ignore
except Exception:
    OXY_USER = os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")
if not OXY_USER or not OXY_PASS:
    raise RuntimeError("Set Oxylabs creds via oxylabs_secrets.py or env vars OXYLABS_USERNAME/PASSWORD.")

# ========= Config / Paths =========
OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"
REQUEST_TIMEOUT = 90
UA_STR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)
GEO_LOCATION = "United States"

try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()
SAVE_DIR = BASE_DIR / "data1"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

# ========= Helpers =========
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _safe_name(s: str) -> str:
    n = re.sub(r"[^\w\s-]", "", (s or "")).strip().replace(" ", "_")
    return n or "NA"

def _stable_id_from_url(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

def _wf_to_hires(u: str, size: int = 1600) -> str:
    """
    Normalize Wayfair CDN URLs to higher-res:
      https://assets.wfcdn.com/im/<hash>/resize-h48-w48%5Ecompr-r65/.../file.jpg
      -> resize-h{size}-w{size}%5Ecompr-r85
    Supports encoded ^ (%5E) and literal ^.
    """
    if not u:
        return u
    u = u.replace(" ", "%20")
    u = re.sub(r"/resize-h\d+-w\d+%5Ecompr-r\d+/", f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
    u = re.sub(r"/resize-h\d+-w\d+\^compr-r\d+/",  f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
    if "/resize-" not in u:
        u = re.sub(r"(https://assets\.wfcdn\.com/im/[^/]+/)",
                   rf"\1resize-h{size}-w{size}%5Ecompr-r85/", u)
    return u

def _post_oxylabs_universal(url: str) -> str:
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
        "user_agent": UA_STR,
        "geo_location": GEO_LOCATION,
    }
    resp = requests.post(
        OXY_ENDPOINT,
        json=payload,
        auth=(OXY_USER, OXY_PASS),
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 401:
        raise RuntimeError("Oxylabs Unauthorized (401). Check OXYLABS_USERNAME/PASSWORD.")
    if not resp.ok:
        raise RuntimeError(f"Oxylabs failed: HTTP {resp.status_code} - {resp.text[:400]}")
    data = resp.json()
    if isinstance(data, dict) and data.get("results"):
        c = data["results"][0].get("content")
        if isinstance(c, str):
            return c
    if isinstance(data, dict) and isinstance(data.get("content"), str):
        return data["content"]
    raise RuntimeError("Oxylabs universal returned no HTML content")

# ========= Very strict gallery pickers =========
def _extract_gallery_images_strict(soup: BeautifulSoup, *, max_images: Optional[int] = None) -> List[str]:
    """
    Only collect images from Wayfair's official PDP gallery:
      - Thumbnails container: [data-test-id='pdp-mt-thumbnails'] (ordered by aria-label "1 of N")
      - Main carousel: #MediaTrayCarouselWithThumbnailSidebar, [data-test-id='pdp-mt-d-mainImageCarousel']
    Ignore everything else (badges, icons, lifestyle blocks outside gallery).
    """
    candidates: List[Tuple[int, str]] = []

    # 1) Ordered thumbnails ("... 1 of N")
    for btn in soup.select("[data-test-id='pdp-mt-thumbnails'] button[aria-label]"):
        lab = btn.get("aria-label") or ""
        m = re.search(r"(\d+)\s+of\s+\d+", lab, re.I)
        order = int(m.group(1)) if m else 9999
        img = btn.find("img")
        src = ""
        if img:
            # Prefer currentSrc/srcset last entry (highest DPR)
            srcset = (img.get("srcset") or "").split(",")
            if srcset:
                last = srcset[-1].strip().split(" ")[0]
                src = last or ""
            if not src:
                src = img.get("src") or img.get("data-src") or ""
        if src:
            candidates.append((order, src))

    # 2) Main carousel images (set a larger order to come after thumbs if duplicates)
    for img in soup.select("#MediaTrayCarouselWithThumbnailSidebar img, [data-test-id='pdp-mt-d-mainImageCarousel'] img"):
        src = ""
        srcset = (img.get("srcset") or "").split(",")
        if srcset:
            src = srcset[-1].strip().split(" ")[0]
        if not src:
            src = img.get("src") or img.get("data-src") or ""
        if src:
            candidates.append((5000, src))

    # Sort by order
    candidates.sort(key=lambda x: x[0])

    # 3) Filter: only Wayfair CDN gallery images
    # - must be assets.wfcdn.com
    # - must be under /im/ path (Wayfair image CDN)
    # - exclude obvious non-gallery assets by keyword
    EXCLUDE_PAT = re.compile(r"(sprite|badge|icon|logo|swatch|color-swatch|video|360|manual|instructions)", re.I)

    def _accept(u: str) -> bool:
        if not u:
            return False
        if "assets.wfcdn.com" not in u:
            return False
        if "/im/" not in u:  # restrict to CDN image path
            return False
        if EXCLUDE_PAT.search(u):
            return False
        # ignore tiny thumbs with explicit small sizes (h<=120 or w<=120)
        if re.search(r"resize-h(\d+)-w(\d+)", u):
            m = re.search(r"resize-h(\d+)-w(\d+)", u)
            if m:
                h = int(m.group(1)); w = int(m.group(2))
                if h <= 120 or w <= 120:
                    return False
        return True

    # 4) Normalize to hi-res, dedupe by URL-key (ignoring resize & query)
    def _url_key(u: str) -> str:
        u = re.sub(r"/resize-h\d+-w\d+(?:%5E|\^)compr-r\d+/", "/", u)
        u = re.sub(r"[?].*$", "", u)
        return u

    seen = set()
    out: List[str] = []
    for _, src in candidates:
        if not _accept(src):
            continue
        hi = _wf_to_hires(src, size=1600)
        key = _url_key(hi)
        if key in seen:
            continue
        seen.add(key)
        out.append(hi)
        if max_images and len(out) >= max_images:
            break

    return out

# ========= Perceptual-hash dedupe =========
def _ahash(img: Image.Image, hash_size: int = 8) -> int:
    im = img.convert("L").resize((hash_size, hash_size), Image.BILINEAR)
    pixels = list(im.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for p in pixels:
        bits = (bits << 1) | (1 if p >= avg else 0)
    return bits

def _hamming(a: int, b: int) -> int:
    x = a ^ b
    return x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1")

def _dedupe_downloaded_by_phash(paths: List[str], *, max_hamming: int = 4) -> List[str]:
    kept: List[str] = []
    hashes: List[int] = []
    for p in paths:
        try:
            im = Image.open(p)
            h = _ahash(im)
        except Exception:
            kept.append(p)
            continue

        is_dup = False
        for prev_h in hashes:
            if _hamming(h, prev_h) <= max_hamming:
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass
                is_dup = True
                break
        if not is_dup:
            hashes.append(h)
            kept.append(p)
    return kept

# ========= Downloading =========
def _download_images(
    urls: List[str],
    folder: Path,
    *,
    convert_to_jpg: bool = True,
    quality: int = 90,
    referer: Optional[str] = None,
) -> List[str]:
    saved: List[str] = []
    folder.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": UA_STR,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer

    with requests.Session() as s:
        s.headers.update(headers)
        for i, u in enumerate(urls, 1):
            try:
                r = s.get(u, timeout=25)
                if not (r.ok and r.content):
                    continue
                if convert_to_jpg:
                    img_bytes = io.BytesIO(r.content)
                    im = Image.open(img_bytes)
                    if im.mode in ("RGBA", "LA", "P"):
                        if im.mode == "P":
                            im = im.convert("RGBA")
                        bg = Image.new("RGB", im.size, (255, 255, 255))
                        bg.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
                        im = bg
                    else:
                        im = im.convert("RGB")
                    out_path = folder / f"image_{i}.jpg"
                    im.save(out_path, format="JPEG", quality=quality, optimize=True)
                    saved.append(str(out_path))
                else:
                    ext = ".jpg"
                    ct = (r.headers.get("Content-Type") or "").lower()
                    lu = u.lower()
                    if "png" in ct or lu.endswith(".png"): ext = ".png"
                    elif "webp" in ct or lu.endswith(".webp"): ext = ".webp"
                    elif "jpeg" in ct or lu.endswith(".jpeg"): ext = ".jpeg"
                    out_path = folder / f"image_{i}{ext}"
                    out_path.write_bytes(r.content)
                    saved.append(str(out_path))
            except Exception:
                continue
    return saved

# ========= Public API (images-first, strict) =========
def scrape_wayfair_USA_product(url: str) -> Dict[str, Any]:
    """
    Fetch via Oxylabs (universal), parse with BS4, extract ONLY gallery images,
    download, phash-dedupe, cap to 12, and return dict.
    (We still parse name/price/stock/description in case you want it later.)
    """
    html = _post_oxylabs_universal(url)
    soup = BeautifulSoup(html, "lxml")

    # Quick block detection
    page_txt = _clean(soup.get_text(" ", strip=True)).lower()
    is_blocked = bool(re.search(r"(access denied|verify you are human|blocked|captcha)", page_txt))

    # --- Parse minimal fields (optional) ---
    name = _clean((soup.select_one("h1[data-rtl-id='listingHeaderNameHeading']") or soup.select_one("h1") or {}).get_text(" ", strip=True) if soup.select_one("h1[data-rtl-id='listingHeaderNameHeading']") or soup.select_one("h1") else "") or "N/A"
    price_node = soup.select_one("[data-test-id='PriceDisplay']")
    price = _clean(price_node.get_text(" ", strip=True)) if price_node else "N/A"

    # Stock: prefer explicit Out-of-Stock badge if present
    in_stock = None
    stock_text = ""
    badge = soup.select_one("[data-test-id='InventoryWidgetDisplay-Text']")
    if badge and "out of stock" in _clean(badge.get_text(" ", strip=True)).lower():
        in_stock, stock_text = False, "Out of Stock badge"
    else:
        # Only positive if Add to Cart button is present and not disabled
        html_l = soup.decode().lower()
        if re.search(r">\s*add to cart\s*<", html_l) or re.search(r'aria-label="\s*add to cart\s*"', html_l):
            # make sure it's not disabled
            atc = soup.select_one("button[data-testing-id='atc-button'], form[name='AddItem'] button[type='submit']")
            if atc:
                disabled_attr = (atc.get("disabled") or "").lower()
                aria_disabled = (atc.get("aria-disabled") or "").lower()
                cls = atc.get("class") or []
                cls_str = " ".join(cls) if isinstance(cls, list) else str(cls)
                if disabled_attr == "true" or aria_disabled == "true" or re.search(r"\bdisabled\b", cls_str, re.I):
                    in_stock, stock_text = False, "Add to Cart disabled"
                else:
                    in_stock, stock_text = True, "Add to Cart present"

    # Description (optional, minimal)
    description = "N/A"
    for box in soup.select('[data-hb-id="BoxV3"]'):
        style = (box.get("style") or "").lower()
        if "pre-line" in style:
            txt = box.get_text("\n", strip=True)
            txt = re.sub(r"\n{3,}", "\n\n", (txt or ""))
            txt = _clean(txt)
            if len(txt) > 120:
                description = txt
                break

    # --- Strict gallery images only ---
    images = _extract_gallery_images_strict(soup, max_images=None)

    # Save folder & raw HTML
    stable_id = _stable_id_from_url(url)
    folder = SAVE_DIR / f"wayfair_{_safe_name(name)}_{stable_id}"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        (folder / "raw_html.html").write_text(html, encoding="utf-8")
    except Exception:
        pass

    # Download + pHash-dedupe
    downloaded = _download_images(images, folder, convert_to_jpg=True, referer=url)
    deduped = _dedupe_downloaded_by_phash(downloaded, max_hamming=4)

    # Cap to a sane maximum (Wayfair typically shows ~7–12 gallery images)
    MAX_KEEP = 12
    deduped = deduped[:MAX_KEEP]

    out = {
        "url": urlsplit(url)._replace(query="").geturl(),
        "name": name,
        "price": price,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_count": len(deduped),
        "images": deduped,
        "folder": str(folder),
        "fetched_via": "oxylabs-universal" + ("(block?)" if is_blocked else ""),
    }
    try:
        (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return out

# # ========= Hardcoded run =========
# if __name__ == "__main__":
#     # Hardcoded URL; single-arg call only
#     u = "https://www.wayfair.com/kitchen-tabletop/pdp/laura-ashley-vq-laura-ashley-jug-kettle-kbfc2699.html?piid=108339007"
#     data = scrape_wayfair_USA_product(u)
#     print(json.dumps(data, indent=2, ensure_ascii=False))




