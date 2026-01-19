# import re, html, json, time, requests
# from pathlib import Path
# from urllib.parse import urlsplit
# from playwright.sync_api import sync_playwright


# # ----------------- config -----------------
# UA_STR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#           "AppleWebKit/537.36 (KHTML, like Gecko) "
#           "Chrome/124.0.0.0 Safari/537.36")

# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()

# SAVE_DIR = BASE_DIR / "data1"


# # ----------------- helpers -----------------
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

# def _stable_id_from_page(page) -> str:
#     # best: the product id on Add To Bag input
#     try:
#         pid = page.locator("input.add-to-bag-proxy, input.add-to-bag").first.get_attribute("data-object-id")
#         if pid and re.fullmatch(r"\d{5,}", pid):
#             return pid
#     except: pass
#     # ld+json fallback (sku / productID)
#     try:
#         for raw in page.locator("script[type='application/ld+json']").all_inner_texts():
#             try:
#                 data = json.loads(raw)
#             except: 
#                 continue
#             objs = data if isinstance(data, list) else [data]
#             for o in objs:
#                 if isinstance(o, dict) and o.get("@type") in ("Product","SomeProducts"):
#                     for key in ("sku","productID"):
#                         val = str(o.get(key) or "")
#                         if re.fullmatch(r"\d{5,}", val):
#                             return val
#     except: pass
#     # last resort: digits in URL
#     try:
#         m = re.search(r"(\d{6,})", page.url)
#         if m: return m.group(1)
#     except: pass
#     return "NA"

# def _abs(u: str) -> str:
#     if not u: return ""
#     return "https:" + u if u.startswith("//") else u

# def _cookie_click(page):
#     for sel in (
#         "#onetrust-accept-btn-handler",
#         "button#onetrust-accept-btn-handler",
#         "button:has-text('Accept All')",
#         "button:has-text('Accept Cookies')",
#         "button:has-text('Accept')",
#     ):
#         try:
#             page.locator(sel).first.click(timeout=1200)
#             break
#         except: 
#             pass

# def _jsonld_availability(page):
#     try:
#         for raw in page.locator("script[type='application/ld+json']").all_inner_texts():
#             try:
#                 data = json.loads(raw)
#             except:
#                 continue
#             objs = data if isinstance(data, list) else [data]
#             for o in objs:
#                 if not isinstance(o, dict):
#                     continue
#                 offers = o.get("offers")
#                 if not offers and isinstance(o.get("@graph"), list):
#                     for g in o["@graph"]:
#                         if isinstance(g, dict) and g.get("@type") == "Product":
#                             offers = g.get("offers"); break
#                 if not offers:
#                     continue
#                 offers_list = offers if isinstance(offers, list) else [offers]
#                 for off in offers_list:
#                     if not isinstance(off, dict): continue
#                     avail = str(off.get("availability") or off.get("itemAvailability") or "")
#                     if re.search(r"InStock", avail, re.I):   return True
#                     if re.search(r"OutOfStock|SoldOut", avail, re.I): return False
#         return None
#     except:
#         return None

# def _html_to_text(desc_html: str) -> str:
#     if not desc_html: return ""
#     s = desc_html
#     s = re.sub(r"(?i)<br\s*/?>", "\n", s)
#     s = re.sub(r"(?is)</p\s*>", "\n\n", s)
#     def _li(m):
#         inner = re.sub(r"<[^>]+>", " ", m.group(1))
#         inner = re.sub(r"\s+", " ", inner).strip()
#         return f"• {inner}\n"
#     s = re.sub(r"(?is)<li[^>]*>(.*?)</li>", _li, s)
#     s = re.sub(r"(?is)<[^>]+>", " ", s)  # strip the rest
#     s = html.unescape(s)
#     s = re.sub(r"[ \t]+\n", "\n", s)
#     s = re.sub(r"\n{3,}", "\n\n", s)
#     s = re.sub(r"[ \t]{2,}", " ", s).strip()
#     return s


# # ----------------- scraper -----------------
# def scrape_hsn_product(url: str, *, headless: bool = False, max_images: int = 12) -> dict:
#     SAVE_DIR.mkdir(parents=True, exist_ok=True)

#     with sync_playwright() as p:
#         browser = p.chromium.launch(
#             headless=headless,
#             args=["--window-position=-32000,-32000", "--lang=en-US", "--disable-blink-features=AutomationControlled"]
#         )
#         ctx = browser.new_context(
#             user_agent=UA_STR,
#             locale="en-US",
#             timezone_id="America/New_York",
#             viewport={"width": 1400, "height": 900},
#             ignore_https_errors=True,
#         )
#         page = ctx.new_page()
#         page.add_init_script("""() => { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); }""")

#         page.goto(url, timeout=90_000, wait_until="domcontentloaded")
#         _cookie_click(page)

#         # Nudge the page
#         try:
#             page.mouse.wheel(0, 800); page.wait_for_timeout(250)
#             page.mouse.wheel(0, -800); page.wait_for_timeout(250)
#         except: pass

#         # ---------- NAME ----------
#         name = "N/A"
#         try:
#             name = _clean(page.locator("h1.product-name-container #product-name, #product-name").first.inner_text(timeout=4000))
#         except:
#             try:
#                 name = _clean(page.locator("meta[property='og:title']").first.get_attribute("content")) or "N/A"
#                 name = re.sub(r"\s*[-–|]\s*HSN.*$", "", name)
#             except: pass

#         # ---------- PRICE ----------
#         price = "N/A"
#         try:
#             pr = page.locator(".product-price [itemprop='price']").first
#             if pr.count() > 0:
#                 val = pr.get_attribute("content") or _clean(pr.inner_text())
#                 cur_el = page.locator(".product-price [itemprop='priceCurrency']").first
#                 cur = (cur_el.get_attribute("content") or _clean(cur_el.inner_text()) or "$") if cur_el.count() else "$"
#                 if cur.upper() == "USD": cur = "$"
#                 if val and not re.search(r"^\$|£|€", val):
#                     price = f"{cur}{val}"
#                 else:
#                     price = val or "N/A"
#         except: pass

#         # ---------- STOCK ----------
#         in_stock = None

#         # 1) explicit SOLD OUT label
#         try:
#             sold_loc = page.locator(".sold-out, span.sold-out, .product-actions:has-text('SOLD OUT')")
#             if sold_loc.count() and sold_loc.first.is_visible():
#                 in_stock = False
#         except: pass

#         # 2) Add To Bag button presence/enablement
#         if in_stock is None:
#             try:
#                 atc = page.locator("input.add-to-bag-proxy.add-to-bag.button[type='submit'][value*='Add To Bag']").first
#                 if atc.count() > 0 and atc.is_visible():
#                     # HSN uses <input type=submit>, no is_enabled; treat visible as available
#                     disabled = (atc.get_attribute("disabled") or "").lower() == "true"
#                     in_stock = not disabled
#             except: pass

#         # 3) microdata availability
#         if in_stock is None:
#             try:
#                 meta_av = page.locator(".product-price meta[itemprop='availability']").first
#                 if meta_av.count():
#                     av = (meta_av.get_attribute("content") or "").strip()
#                     if re.search(r"InStock", av, re.I): in_stock = True
#                     elif re.search(r"OutOfStock|SoldOut", av, re.I): in_stock = False
#             except: pass

#         # 4) JSON-LD fallback
#         if in_stock is None:
#             in_stock = _jsonld_availability(page)

#         # ---------- DESCRIPTION ----------
#         description = "N/A"
#         try:
#             desc_html = page.locator("[itemprop='description']").first.inner_html(timeout=4000)
#             txt = _html_to_text(desc_html)
#             if txt and len(txt) > 40:
#                 description = txt
#         except: pass

#         # ---------- IMAGES ----------
#         # Prefer 'orig' URLs from data-zoom; fallback to 'rocs1200' or input@href
#         urls = []
#         try:
#             thumbs = page.locator(".product-image-thumbnails input[name='image']")
#             n = thumbs.count()
#             for i in range(n):
#                 node = thumbs.nth(i)
#                 cand = []
#                 dz = node.get_attribute("data-zoom") or ""
#                 if dz:
#                     dz = dz.replace("&quot;", "\"")
#                     try:
#                         arr = json.loads(dz)
#                         if isinstance(arr, list):
#                             cand.extend(arr)
#                     except: pass
#                 href = node.get_attribute("href") or ""
#                 if href:
#                     cand.append(href)

#                 best = None
#                 for u in cand:
#                     if "/orig/" in u:
#                         best = u; break
#                 if not best:
#                     for u in cand:
#                         if "/rocs1200/" in u:
#                             best = u; break
#                 if not best and cand:
#                     best = cand[0]
#                 if best:
#                     urls.append(_abs(best))
#         except: pass

#         # Dedupe & cap
#         seen, clean = set(), []
#         for u in urls:
#             k = re.sub(r"[?].*$", "", u)
#             if k not in seen:
#                 seen.add(k); clean.append(u)
#         img_urls = clean[:max_images] if max_images else clean

#         # ---------- DOWNLOAD ----------
#         pid = _stable_id_from_page(page)
#         folder = SAVE_DIR / f"{_retailer_slug(url)}_{_safe_name(name)}_{pid}"
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
#                     r = s.get(u, timeout=30)
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

#         ctx.close(); browser.close()

#     return {
#         "name": name,
#         "price": price,
#         "in_stock": in_stock,
#         "description": description,
#         "image_count": len(downloaded),
#         "images": downloaded,
#         "folder": str(folder),
#     }


# # quick test
# if __name__ == "__main__":
#     print(scrape_hsn_product(
#         "https://www.hsn.com/products/laura-ashley-5-speed-300-watt-hand-mixer/23554815",
#         headless=False  # hidden off-screen
#     ))




# hsn_oxylabs.py
# Python 3.9+
# pip install requests beautifulsoup4 lxml

import re
import html
import json
import time
import uuid
import requests
from pathlib import Path
from urllib.parse import urlsplit
from typing import List, Dict, Any, Optional, Tuple

from bs4 import BeautifulSoup

# ---- secrets (use your local oxylabs_secrets.py) ----
from oxylabs_secrets import OXY_USER, OXY_PASS

# ----------------- config -----------------
UA_STR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/124.0.0.0 Safari/537.36")

try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()

SAVE_DIR = BASE_DIR / "data1"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

# ----------------- helpers -----------------
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

def _unique_suffix() -> str:
    # time + short uuid for uniqueness
    t = int(time.time() * 1000) % 10_000_000
    u = uuid.uuid4().hex[:6]
    return f"{t}_{u}"

def _stable_id_from_html_and_url(soup: BeautifulSoup, url: str) -> str:
    # 1) ld+json (sku / productID)
    try:
        for s in soup.select("script[type='application/ld+json']"):
            raw = s.get_text(strip=True)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            objs = data if isinstance(data, list) else [data]
            for o in objs:
                if isinstance(o, dict) and o.get("@type") in ("Product", "SomeProducts"):
                    for key in ("sku", "productID"):
                        val = str(o.get(key) or "")
                        if re.fullmatch(r"\d{5,}", val):
                            return val
                # Sometimes nested in @graph
                if isinstance(o, dict) and isinstance(o.get("@graph"), list):
                    for g in o["@graph"]:
                        if isinstance(g, dict) and g.get("@type") == "Product":
                            for key in ("sku", "productID"):
                                val = str(g.get(key) or "")
                                if re.fullmatch(r"\d{5,}", val):
                                    return val
    except Exception:
        pass

    # 2) URL digits fallback
    m = re.search(r"(\d{6,})", url or "")
    if m:
        return m.group(1)

    return "NA"

def _abs(u: str) -> str:
    if not u:
        return ""
    return "https:" + u if u.startswith("//") else u

def _jsonld_availability_from_soup(soup: BeautifulSoup) -> Optional[bool]:
    try:
        for s in soup.select("script[type='application/ld+json']"):
            raw = s.get_text(strip=True)
            if not raw:
                continue
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
                            break
                if not offers:
                    continue
                offers_list = offers if isinstance(offers, list) else [offers]
                for off in offers_list:
                    if not isinstance(off, dict):
                        continue
                    avail = str(off.get("availability") or off.get("itemAvailability") or "")
                    if re.search(r"InStock", avail, re.I):
                        return True
                    if re.search(r"OutOfStock|SoldOut", avail, re.I):
                        return False
        return None
    except Exception:
        return None

def _html_to_text(desc_html: str) -> str:
    if not desc_html:
        return ""
    s = desc_html
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</p\s*>", "\n\n", s)
    def _li(m):
        inner = re.sub(r"<[^>]+>", " ", m.group(1))
        inner = re.sub(r"\s+", " ", inner).strip()
        return f"• {inner}\n"
    s = re.sub(r"(?is)<li[^>]*>(.*?)</li>", _li, s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)  # strip rest
    s = html.unescape(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s).strip()
    return s

# ----------------- Oxylabs fetch -----------------
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": UA_STR,
    "Accept": "application/json",
    "Content-Type": "application/json",
})

def _browser_instructions_light() -> List[Dict]:
    # Enough to mount most lazy content
    return [
        {"type": "wait_for_element",
         "selector": {"type": "css", "value": "body"},
         "timeout_s": 12},
        {"type": "scroll_to_bottom", "timeout_s": 8},
        {"type": "wait", "wait_time_s": 0.7},
    ]

def _browser_instructions_aggressive() -> List[Dict]:
    # Focus thumbnails & description area to trigger lazy loads
    return [
        {"type": "wait_for_element",
         "selector": {"type": "css", "value": "body"},
         "timeout_s": 15},
        {"type": "wait_for_element",
         "selector": {"type": "css", "value": ".product-image-thumbnails input[name='image'], [itemprop='description']"},
         "timeout_s": 12},
        {"type": "scroll_element_into_view",
         "selector": {"type": "css", "value": ".product-image-thumbnails"},
         "timeout_s": 8},
        {"type": "scroll_by", "x": 0, "y": 600, "timeout_s": 4},
        {"type": "wait", "wait_time_s": 0.6},
        {"type": "scroll_by", "x": 0, "y": -400, "timeout_s": 4},
        {"type": "wait", "wait_time_s": 0.6},
        {"type": "scroll_to_bottom", "timeout_s": 8},
        {"type": "wait", "wait_time_s": 0.8},
    ]

def _post_oxylabs(payload: Dict) -> str:
    r = _SESSION.post(
        "https://realtime.oxylabs.io/v1/queries",
        auth=(OXY_USER, OXY_PASS),
        data=json.dumps(payload),
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):
        if data.get("results"):
            c = data["results"][0].get("content") or ""
            if c:
                return c
        if data.get("content"):
            return data["content"] or ""
    raise RuntimeError("Oxylabs: no rendered HTML returned")

def _fetch_with_oxylabs_universal(url: str, aggressive: bool = False) -> str:
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
        "browser_instructions": _browser_instructions_aggressive() if aggressive else _browser_instructions_light(),
    }
    try:
        return _post_oxylabs(payload)
    except requests.HTTPError:
        # Fallback without instructions (some accounts prefer the simple shape)
        payload2 = {"source": "universal", "url": url, "render": "html"}
        return _post_oxylabs(payload2)

# ----------------- parsing helpers -----------------
def _parse_name(soup: BeautifulSoup) -> str:
    # Your original order, translated to HTML parsing
    el = soup.select_one("h1.product-name-container #product-name, #product-name")
    if el:
        t = _clean(el.get_text(" ", strip=True))
        if t:
            return t
    og = soup.select_one("meta[property='og:title']")
    if og and og.get("content"):
        t = _clean(og["content"])
        t = re.sub(r"\s*[-–|]\s*HSN.*$", "", t)
        if t:
            return t
    return "N/A"

def _parse_price(soup: BeautifulSoup) -> str:
    # Look for [itemprop='price'] like before
    pr = soup.select_one(".product-price [itemprop='price']")
    if pr:
        val = pr.get("content") or _clean(pr.get_text(" ", strip=True))
        cur_el = soup.select_one(".product-price [itemprop='priceCurrency']")
        cur = "$"
        if cur_el:
            cur = (cur_el.get("content") or _clean(cur_el.get_text(" ", strip=True)) or "$")
        if cur.upper() == "USD":
            cur = "$"
        if val and not re.search(r"^\$|£|€", val):
            return f"{cur}{val}"
        return val or "N/A"
    # Fallback: scan text for money
    money = re.search(r"([$£€]\s?\d[\d,]*(?:\.\d{2})?)", soup.get_text(" ", strip=True))
    return money.group(1) if money else "N/A"

def _parse_stock(soup: BeautifulSoup) -> Optional[bool]:
    # 1) SOLD OUT badges
    sold = soup.select_one(".sold-out, span.sold-out, .product-actions:-soup-contains('SOLD OUT')")
    if sold:
        return False
    # 2) Add To Bag (input[type=submit])
    atc = soup.select_one("input.add-to-bag-proxy.add-to-bag.button[type='submit'][value*='Add To Bag']")
    if atc:
        disabled = (atc.get("disabled") or "").lower() == "true"
        return not disabled
    # 3) Microdata availability
    m = soup.select_one(".product-price meta[itemprop='availability']")
    if m:
        av = (m.get("content") or "").strip()
        if re.search(r"InStock", av, re.I):
            return True
        if re.search(r"OutOfStock|SoldOut", av, re.I):
            return False
    # 4) JSON-LD fallback
    return _jsonld_availability_from_soup(soup)

def _parse_description(soup: BeautifulSoup) -> str:
    el = soup.select_one("[itemprop='description']")
    if not el:
        return "N/A"
    txt = _html_to_text(str(el))
    if txt and len(txt) > 40:
        return txt
    return "N/A"

def _parse_images(soup: BeautifulSoup, max_images: int) -> List[str]:
    # Prefer 'orig' from data-zoom; fallback to 'rocs1200' or input@href
    urls: List[str] = []
    for node in soup.select(".product-image-thumbnails input[name='image']"):
        cand: List[str] = []
        dz = node.get("data-zoom") or ""
        if dz:
            dz = dz.replace("&quot;", "\"")
            try:
                arr = json.loads(dz)
                if isinstance(arr, list):
                    cand.extend(arr)
            except Exception:
                pass
        href = node.get("href") or ""
        if href:
            cand.append(href)

        best = None
        # choose by quality preference like original logic
        for u in cand:
            if "/orig/" in u:
                best = u
                break
        if not best:
            for u in cand:
                if "/rocs1200/" in u:
                    best = u
                    break
        if not best and cand:
            best = cand[0]
        if best:
            urls.append(_abs(best))

    # Dedupe & cap
    seen, clean = set(), []
    for u in urls:
        k = re.sub(r"[?].*$", "", u)
        if k not in seen:
            seen.add(k)
            clean.append(u)

    if max_images:
        clean = clean[:max_images]
    return clean

# ----------------- scraper (same name/signature/return!) -----------------
def scrape_hsn_product(url: str, *, headless: bool = False, max_images: int = 12) -> dict:
    """
    Converted to Oxylabs Universal (no Playwright).
    - Keeps function name, parameters, return dict exactly as your original.
    - Creates a unique folder each run.
    """
    SAVE_DIR.mkdir(parents=True, exist_ok=True)

    # First pass (light)
    html1 = _fetch_with_oxylabs_universal(url, aggressive=False)
    soup1 = BeautifulSoup(html1, "lxml")

    # If thumbnails/desc look missing, try aggressive
    need_more = not soup1.select_one(".product-image-thumbnails input[name='image']") or not soup1.select_one("[itemprop='description']")
    soup = soup1
    if need_more:
        html2 = _fetch_with_oxylabs_universal(url, aggressive=True)
        soup = BeautifulSoup(html2, "lxml")

    # ---------- NAME ----------
    name = _parse_name(soup)

    # ---------- PRICE ----------
    price = _parse_price(soup)

    # ---------- STOCK ----------
    in_stock = _parse_stock(soup)

    # ---------- DESCRIPTION ----------
    description = _parse_description(soup)

    # ---------- IMAGES ----------
    img_urls = _parse_images(soup, max_images=max_images)

    # ---------- DOWNLOAD ----------
    pid = _stable_id_from_html_and_url(soup, url)
    unique = _unique_suffix()
    folder = SAVE_DIR / f"{_retailer_slug(url)}_{_safe_name(name)}_{pid}_{unique}"
    folder.mkdir(parents=True, exist_ok=True)

    downloaded: List[str] = []
    with requests.Session() as s:
        s.headers.update({
            "User-Agent": UA_STR,
            "Referer": url,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        })
        for i, u in enumerate(img_urls, 1):
            try:
                r = s.get(u, timeout=30)
                if r.ok and r.content:
                    ext = ".jpg"
                    ct = (r.headers.get("Content-Type") or "").lower()
                    if "webp" in ct:
                        ext = ".webp"
                    elif "png" in ct:
                        ext = ".png"
                    path = folder / f"image_{i}{ext}"
                    path.write_bytes(r.content)
                    downloaded.append(str(path))
            except Exception as e:
                print(f"⚠️ Could not download {u}: {e}")

    return {
        "name": name,
        "price": price,
        "in_stock": in_stock,
        "description": description,
        "image_count": len(downloaded),
        "images": downloaded,
        "folder": str(folder),
    }

# # quick test (CLI unchanged)
# if __name__ == "__main__":
#     print(scrape_hsn_product(
#         "https://www.hsn.com/products/laura-ashley-5-speed-300-watt-hand-mixer/23554815",
#         headless=False,  # ignored (kept for compatibility)
#         max_images=12
#     ))


