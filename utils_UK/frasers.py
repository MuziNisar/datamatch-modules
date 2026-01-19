# import re, html, hashlib, time, shutil, random, json
# from pathlib import Path
# from urllib.parse import urlsplit, parse_qs, urlparse
# from playwright.sync_api import sync_playwright, Error as PWError

# # ---------- paths ----------
# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()
# SAVE_DIR = BASE_DIR / "data1"

# UA_STR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#           "AppleWebKit/537.36 (KHTML, like Gecko) "
#           "Chrome/127.0.0.0 Safari/537.36")

# # ---------- helpers ----------
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
#     parsed = urlparse(u)
#     q = parse_qs(parsed.query or "")
#     if "colcode" in q and q["colcode"]:
#         return q["colcode"][0]
#     m = re.search(r"(\d{6,})", parsed.path)
#     if m: return m.group(1)
#     return hashlib.sha1(u.encode("utf-8")).hexdigest()[:8]

# def _abs(u: str) -> str:
#     if not u: return ""
#     return "https:" + u if u.startswith("//") else u

# def _cookie_header(cookies):
#     return "; ".join(f"{c['name']}={c['value']}" for c in cookies if 'name' in c and 'value' in c)

# def _is_visible(page, selector: str) -> bool:
#     try:
#         return page.evaluate("""
#             (sel) => {
#                 const el = document.querySelector(sel);
#                 if (!el) return false;
#                 const st = window.getComputedStyle(el);
#                 if (!st || st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) === 0) return false;
#                 const r = el.getBoundingClientRect();
#                 return r.width > 0 && r.height > 0;
#             }
#         """, selector)
#     except Exception:
#         return False

# def _jsonld_availability(page) -> int:
#     # 1 = InStock, 0 = OutOfStock, -1 = unknown
#     try:
#         data_list = page.evaluate("""
#             () => Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
#                         .map(s => s.textContent)
#         """) or []
#         for txt in data_list:
#             try:
#                 data = json.loads(txt)
#             except Exception:
#                 continue
#             objs = data if isinstance(data, list) else [data]
#             for obj in objs:
#                 offers = obj.get("offers")
#                 if not offers: continue
#                 offers = offers if isinstance(offers, list) else [offers]
#                 for off in offers:
#                     a = (off.get("availability") or off.get("itemAvailability") or "")
#                     a = str(a)
#                     if re.search(r"InStock", a, re.I): return 1
#                     if re.search(r"OutOfStock|SoldOut", a, re.I): return 0
#         return -1
#     except Exception:
#         return -1

# def _human_delay(a=90, b=180):
#     time.sleep(random.uniform(a/1000.0, b/1000.0))

# def _goto(page, url: str, referer: str = None):
#     # quick retry
#     try:
#         page.goto(url, timeout=45_000, wait_until="domcontentloaded", referer=referer)
#     except PWError:
#         _human_delay(300, 600)
#         page.goto(url, timeout=45_000, wait_until="domcontentloaded", referer=referer)

# # ---------- single run (engine) ----------
# def _run_once(p, engine: str, url: str, *, headless: bool, hide_ui: bool, max_images: int):
#     """
#     Returns (result_dict, http2_failed: bool)
#     """
#     tmp_folder = SAVE_DIR / "tmp_houseoffraser"
#     if tmp_folder.exists():
#         shutil.rmtree(tmp_folder, ignore_errors=True)
#     tmp_folder.mkdir(parents=True, exist_ok=True)

#     saved_map = {}       # clean_url -> temp file path (only if we preload misses)
#     allowed_urls = set() # gate response hook when preloading
#     hash_seen = set()    # content hash dedupe (md5 of body)

#     browser = None; ctx = None; page = None
#     http2_failed = False

#     try:
#         # ---- launch engine ----
#         launch_args = ["--lang=en-GB", "--disable-blink-features=AutomationControlled"]
#         if not headless and hide_ui:
#             launch_args += ["--window-position=-32000,-32000", "--window-size=400,300"]

#         if engine == "chromium":
#             browser = p.chromium.launch(headless=headless, args=launch_args + [
#                 "--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox",
#                 "--mute-audio"
#             ])
#         elif engine == "firefox":
#             browser = p.firefox.launch(headless=headless, args=([] if headless else ["-width", "400", "-height", "300"]))
#         else:
#             raise RuntimeError("Unsupported engine")

#         ctx = browser.new_context(
#             user_agent=UA_STR if engine != "firefox" else None,
#             locale="en-GB",
#             timezone_id="Europe/London",
#             viewport={"width": 1400, "height": 900},
#             ignore_https_errors=True,
#         )

#         # Response hook (only used when we decide to preload)
#         def on_response(resp):
#             try:
#                 ct = (resp.headers.get("content-type") or "").lower()
#                 if not ct.startswith("image/"): return
#                 clean_url = re.sub(r"\?.*$", "", resp.url)
#                 if clean_url not in allowed_urls: return
#                 body = resp.body()
#                 if not body or len(body) < 3000: return
#                 h = hashlib.md5(body).hexdigest()
#                 if h in hash_seen: return
#                 hash_seen.add(h)
#                 ext = ".jpg"
#                 if "webp" in ct or clean_url.lower().endswith(".webp"): ext = ".webp"
#                 elif "png" in ct or clean_url.lower().endswith(".png"): ext = ".png"
#                 elif clean_url.lower().endswith(".jpeg"): ext = ".jpeg"
#                 fname = f"resp_{h[:10]}{ext}"
#                 path = tmp_folder / fname
#                 if not path.exists():
#                     path.write_bytes(body)
#                 saved_map[clean_url] = str(path)
#             except Exception:
#                 pass

#         ctx.on("response", on_response)
#         page = ctx.new_page()
#         page.add_init_script("""() => { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); }""")

#         # Speed: block heavy assets while navigating; we’ll unroute before any preload stage
#         def _route(route, request):
#             rtype = request.resource_type
#             urlr = request.url
#             # allow zoom originals in case the page tries to load them itself
#             if rtype == "image" and "/images/imgzoom/" in urlr:
#                 return route.continue_()
#             if rtype in ("image", "media", "font"):
#                 return route.abort()
#             return route.continue_()
#         page.route("**/*", _route)

#         # Navigate via homepage (referer helps), then product.
#         home = "https://www.houseoffraser.co.uk/"
#         try:
#             _goto(page, home)
#         except PWError as e:
#             http2_failed = http2_failed or ("ERR_HTTP2" in str(e))

#         # Cookie banner (best effort)
#         for sel in ("#onetrust-accept-btn-handler",
#                     "button#onetrust-accept-btn-handler",
#                     "button:has-text('Accept all')",
#                     "button:has-text('Accept All')",
#                     "button:has-text('Accept Cookies')",
#                     "button:has-text('Allow all')"):
#             try:
#                 page.locator(sel).first.click(timeout=900); break
#             except:
#                 pass

#         try:
#             _goto(page, url, referer=home)
#         except PWError as e:
#             http2_failed = http2_failed or ("ERR_HTTP2" in str(e))
#             raise

#         # minimal scroll; reveal "+N" if present
#         try:
#             page.locator(".productRollOverPanel.active, [class*='productRollOverPanel']").first.scroll_into_view_if_needed(timeout=4000)
#         except: pass
#         page.mouse.wheel(0, 600); page.wait_for_timeout(120)
#         page.mouse.wheel(0, -600); page.wait_for_timeout(120)
#         try:
#             vm = page.locator(".productRollOverPanel.active a.viewMoreNumber, a.viewMoreNumber").first
#             if vm and vm.count() > 0:
#                 vm.click(timeout=900)
#                 page.wait_for_timeout(200)
#         except: pass

#         # ---------- NAME ----------
#         try:
#             name = _clean(page.locator("#lblProductName").first.inner_text())
#         except:
#             try: name = _clean(page.locator("h1, .productTitle, .pdpTitle").first.inner_text())
#             except: name = "N/A"

#         # ---------- PRICE ----------
#         price = "N/A"
#         try:
#             price_raw = _clean(page.locator("#lblSellingPrice, .pdpPrice span, [itemprop='price']").first.inner_text())
#             m = re.search(r"([£$€]\s?\d[\d,]*(?:\.\d{2})?)", price_raw)
#             if m: price = m.group(1).replace(" ", "")
#         except: pass

#         # ---------- STOCK ----------
#         in_stock = None
#         flag = _jsonld_availability(page)
#         if flag == 1:
#             in_stock = True
#         elif flag == 0:
#             in_stock = False
#         else:
#             try:
#                 overlay_vis = _is_visible(page, "#NonBuyableOverlayMessage, .NonBuyableOverlayMessage")
#             except Exception:
#                 overlay_vis = False
#             if overlay_vis:
#                 in_stock = False
#             else:
#                 try:
#                     add_vis = _is_visible(page, "#aAddToBag, .addToBag, button:has-text('Add to bag')")
#                 except Exception:
#                     add_vis = False
#                 disabled = False
#                 try:
#                     disabled = page.locator("#aAddToBag[disabled], .addToBag[disabled], .addToBag.disabled, [aria-disabled='true']").count() > 0
#                 except Exception:
#                     pass
#                 if add_vis and not disabled:
#                     in_stock = True

#         # ---------- DESCRIPTION ----------
#         parts = []
#         try:
#             info = _clean(page.locator(".productDescriptionInfoText, .productDescription, #productDescription").first.inner_text())
#             if info and len(info) > 40:
#                 parts.append(info)
#         except: pass
#         try:
#             lis = page.locator(".productDescriptionInfoText li, .productDescription li, #productDescription li").all()
#             bullets, seenb = [], set()
#             for li in lis:
#                 try:
#                     t = _clean(li.inner_text())
#                     tl = t.lower()
#                     if t and tl not in seenb:
#                         seenb.add(tl); bullets.append(f"• {t}")
#                 except: pass
#             if bullets: parts.append("\n".join(bullets))
#         except: pass
#         description = "N/A"
#         if parts:
#             dedup, seenl = [], set()
#             for block in parts:
#                 for line in block.splitlines():
#                     L = line.strip()
#                     if not L: dedup.append(""); continue
#                     if L.lower() in seenl: continue
#                     seenl.add(L.lower()); dedup.append(L)
#             description = re.sub(r"\n{3,}", "\n\n", "\n".join(dedup)).strip()

#         # ---------- IMAGE URLS: only zoom originals (/images/imgzoom/*_xxl*.jpg) ----------
#         try:
#             active_panel_id = page.evaluate("""
#                 () => {
#                     const el = document.querySelector('.productRollOverPanel.active');
#                     return el ? el.id : '';
#                 }
#             """) or ""
#         except:
#             active_panel_id = ""
#         base_sel = f"#{active_panel_id}" if active_panel_id else ".productRollOverPanel.active"
#         if not page.locator(base_sel).count():
#             base_sel = ".productRollOverPanel"

#         try:
#             raw_urls = page.evaluate(f"""
#                 () => Array.from(document.querySelectorAll("{base_sel} a.zoomMainImage"))
#                     .map(a => a.getAttribute('href') || '')
#                     .filter(Boolean)
#             """) or []
#         except:
#             raw_urls = []

#         cleaned, seenu = [], set()
#         for u in raw_urls:
#             u = _abs(u); u = re.sub(r"\?.*$", "", u)
#             if not u or not re.match(r"^https?://", u): continue
#             if "/images/imgzoom/" not in u: continue
#             if u in seenu: continue
#             seenu.add(u); cleaned.append(u)

#         if not cleaned:
#             # fallback: upgrade product large -> zoom
#             try:
#                 alt = page.evaluate(f"""
#                     () => Array.from(document.querySelectorAll("{base_sel} img.imgProduct"))
#                         .map(img => img.getAttribute('src') || '')
#                         .filter(Boolean)
#                 """) or []
#             except:
#                 alt = []
#             for u in alt:
#                 u = _abs(u); u = re.sub(r"\?.*$", "", u)
#                 if not u or not re.match(r"^https?://", u): continue
#                 u_zoom = re.sub(r"/images/products/(\d+)_l(_[a-z0-9]+)?\.jpg$",
#                                 r"/images/imgzoom/\1_xxl\2.jpg", u, flags=re.I)
#                 cand = u_zoom if u_zoom != u else u
#                 if "/images/imgzoom/" in cand and cand not in seenu:
#                     seenu.add(cand); cleaned.append(cand)

#         chosen_urls = cleaned[:max_images]

#         # ---------- FINAL FOLDER ----------
#         folder = SAVE_DIR / f"{_retailer_slug(url)}_{_safe_name(name or 'HouseOfFraser_Product')}_{_stable_id_from_url(url)}"
#         folder.mkdir(parents=True, exist_ok=True)

#         # ---------- Direct download first ----------
#         downloaded = []
#         try:
#             cookie_hdr = _cookie_header(ctx.cookies("https://www.houseoffraser.co.uk"))
#         except:
#             cookie_hdr = ""
#         headers = {"Referer": url, "User-Agent": UA_STR, "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}
#         if cookie_hdr: headers["Cookie"] = cookie_hdr

#         misses = []
#         idx = 1
#         for u in chosen_urls:
#             try:
#                 resp = ctx.request.get(u, headers=headers, timeout=25_000)
#                 ok = resp.ok and (resp.headers.get("content-type") or "").lower().startswith("image/")
#                 body = resp.body() if ok else b""
#                 if ok and body and len(body) > 5000:
#                     h = hashlib.md5(body).hexdigest()
#                     if h in hash_seen:
#                         continue
#                     hash_seen.add(h)
#                     ext = ".jpg"
#                     ul = u.lower()
#                     if ul.endswith(".webp"): ext = ".webp"
#                     elif ul.endswith(".png"): ext = ".png"
#                     elif ul.endswith(".jpeg"): ext = ".jpeg"
#                     path = folder / f"image_{idx}{ext}"
#                     path.write_bytes(body)
#                     downloaded.append(str(path)); idx += 1
#                 else:
#                     misses.append(u)
#             except Exception:
#                 misses.append(u)

#         # ---------- Fallback: preload only the misses in-page ----------
#         if misses:
#             # allow images now
#             try: page.unroute("**/*")
#             except Exception: pass

#             for u in misses: allowed_urls.add(u)
#             try:
#                 page.evaluate("""
#                     (urls) => Promise.all(urls.map(u => new Promise((res) => {
#                         const cb = (Date.now() + Math.random()).toString(36);
#                         const img = new Image();
#                         img.onload = () => res(true);
#                         img.onerror = () => res(false);
#                         img.referrerPolicy = 'strict-origin-when-cross-origin';
#                         img.src = u + (u.includes('?') ? '&' : '?') + 'cb=' + cb;
#                     })))
#                 """, misses)
#                 page.wait_for_timeout(700)
#             except Exception:
#                 pass

#             # Move any captured bodies
#             for u in misses:
#                 temp_path = saved_map.get(u)
#                 if not temp_path: continue
#                 try:
#                     src = Path(temp_path)
#                     if not src.exists() or src.stat().st_size < 6000: continue
#                     body = src.read_bytes()
#                     h = hashlib.md5(body).hexdigest()
#                     if h in hash_seen: continue
#                     hash_seen.add(h)
#                     ext = src.suffix or ".jpg"
#                     dest = folder / f"image_{idx}{ext}"
#                     dest.write_bytes(body)
#                     downloaded.append(str(dest)); idx += 1
#                 except Exception:
#                     pass

#         result = {
#             "name": name,
#             "price": price,
#             "in_stock": in_stock,
#             "description": description,
#             "image_count": len(downloaded),
#             "images": downloaded,
#             "folder": str(folder),
#         }
#         return result, http2_failed
#     finally:
#         # Cleanup playwright objects and temp folder
#         try:
#             if page: page.unroute("**/*")
#         except: pass
#         try:
#             if ctx: ctx.close()
#         except: pass
#         try:
#             if browser: browser.close()
#         except: pass
#         shutil.rmtree(SAVE_DIR / "tmp_houseoffraser", ignore_errors=True)

# # ---------- public API ----------
# def scrape_houseoffraser_product(url: str, *, headless: bool = True, hide_ui: bool = True, max_images: int = 25):
#     SAVE_DIR.mkdir(parents=True, exist_ok=True)
#     with sync_playwright() as p:
#         # Chromium first
#         try:
#             res, http2 = _run_once(p, "chromium", url, headless=headless, hide_ui=hide_ui, max_images=max_images)
#             return res
#         except PWError as e:
#             msg = str(e)
#             if "ERR_HTTP2" in msg or "net::" in msg:
#                 # transparent fallback to Firefox
#                 res, _ = _run_once(p, "firefox", url, headless=headless, hide_ui=hide_ui, max_images=max_images)
#                 return res
#             raise

# # quick test
# if __name__ == "__main__":
#     print(scrape_houseoffraser_product(
#         "https://www.houseoffraser.co.uk/brand/view-quest/laura-ashley-17l-dome-kettle-elveden-navy-886478#colcode=88647818",
#         headless=False,   # run headful
#         hide_ui=True,     # but hide the window off-screen
#         max_images=25
#     ))








# frasers.py
# Python 3.10+
# pip install requests beautifulsoup4 lxml pillow

import os, re, io, json, time, random
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from PIL import Image

# ---------- Paths ----------
try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()
SAVE_ROOT = BASE_DIR / "data_houseoffraser"
SAVE_ROOT.mkdir(parents=True, exist_ok=True)

# ---------- Headers & HTTP ----------
def get_random_headers():
    uas = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Mozilla/5.0 (Linux; Android 14; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    ]
    return {
        "User-Agent": random.choice(uas),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

def robust_get(session: requests.Session, url: str, timeout: int = 25, max_retries: int = 3) -> requests.Response:
    last_exc = None
    for attempt in range(max_retries):
        try:
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(1.5 * (attempt + 1))
                session.headers.update(get_random_headers())
            else:
                raise
    raise last_exc

# ---------- Helpers ----------
def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s

def _safe_name(name: str) -> str:
    n = re.sub(r"[^\w\s-]", "", name or "").strip()
    n = re.sub(r"\s+", "_", n)
    return n or "Unknown_Product"

def _retailer_slug(url: str) -> str:
    host = urlparse(url).netloc.lower()
    host = re.sub(r"^www\.", "", host)
    return (host.split(".")[0] or "site")

def _stable_id_from_url(url: str) -> str:
    m = re.search(r"(\d{6,})", url)
    return m.group(1) if m else "na"

def _jsonld_first(soup: BeautifulSoup, type_name: str):
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if obj.get("@type") == type_name:
                return obj
    return None

def _extract_price(soup: BeautifulSoup):
    # Prefer <p data-testid="price" data-testvalue="6999"><span>£69.99</span></p>
    p = soup.select_one("p[data-testid='price']")
    if p:
        # Try attribute first for numeric cents
        val = p.get("data-testvalue")
        if val and val.isdigit():
            try:
                pennies = int(val)
                if pennies > 0:
                    return f"{pennies/100:.2f} GBP", "price-testid-attr"
            except Exception:
                pass
        # Fallback to visible span text
        txt = _clean(p.get_text(" ", strip=True))
        m = re.search(r"(£\s?\d[\d,]*(?:\.\d{2})?)", txt)
        if m:
            return m.group(1).replace(" ", "") + " GBP", "price-testid-text"

    # Secondary fallbacks
    metas = soup.select("meta[itemprop='price'], [itemprop='price']")
    for el in metas:
        txt = _clean(el.get("content") or el.get_text(" ", strip=True))
        m = re.search(r"(\d[\d,]*(?:\.\d{2})?)", txt)
        if m:
            return f"{m.group(1)} GBP", "itemprop"

    body_price = _clean(soup.get_text(" ", strip=True))
    m = re.search(r"(£\s?\d[\d,]*(?:\.\d{2})?)", body_price)
    if m:
        return m.group(1).replace(" ", "") + " GBP", "body"

    return "N/A", "none"

def _extract_name(soup: BeautifulSoup):
    for sel in ("h1", "[data-testid='pdp-title']", "[class*='ProductTitle']", "[class*='pdpTitle']"):
        el = soup.select_one(sel)
        if el:
            txt = _clean(el.get_text(" ", strip=True))
            if txt:
                return txt
    # JSON-LD product name
    jld = _jsonld_first(soup, "Product")
    if jld and jld.get("name"):
        return _clean(jld["name"])
    return "Unknown Product"

def _extract_description(soup: BeautifulSoup) -> str:
    def _clean_spaces(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip())

    def _strip_product_code(txt: str) -> str:
        return re.sub(r"^Product code:\s*\S+\s*", "", txt, flags=re.I)

    # 1) JSON-LD
    jld = _jsonld_first(soup, "Product")
    if jld:
        jld_desc = _clean_spaces(jld.get("description") or "")
        if jld_desc and len(jld_desc) > 60:
            return _strip_product_code(jld_desc)

    # 2) Open accordion → data-testid="description"
    for sel in (
        "[data-testid='accordion-content'] [data-testid='description']",
        "[data-testid='description']",
    ):
        root = soup.select_one(sel)
        if root:
            span = root.select_one(
                ".ProductDetails_description__hX1PR, [class*='ProductDetails_description'] span, [class*='ProductDetails_description']"
            )
            if span:
                txt = _clean_spaces(span.get_text(" ", strip=True))
                if txt:
                    return _strip_product_code(txt)
            txt = _clean_spaces(root.get_text(" ", strip=True))
            if txt:
                return _strip_product_code(txt)

    # 3) Broader fallbacks
    for sel in (
        "[class*='ProductDetails_description']",
        "[data-testid='accordion-content'] [class*='ProductDetails_root']",
        "[class*='ProductDetails_root']",
    ):
        el = soup.select_one(sel)
        if el:
            txt = _clean_spaces(el.get_text(" ", strip=True))
            if txt:
                return _strip_product_code(txt)

    # 4) Meta description
    meta = soup.select_one("meta[name='description']")
    if meta and meta.get("content"):
        txt = _clean_spaces(meta["content"])
        if len(txt) > 60:
            return _strip_product_code(txt)

    return "N/A"

def _extract_stock(soup: BeautifulSoup):
    # Presence of purchase button implies purchasable (in stock / addable)
    btn = soup.select_one("button[data-testid='purchase-button']")
    if btn:
        return True, "purchase-button"
    # JSON-LD availability
    jld = _jsonld_first(soup, "Product")
    if jld:
        offers = jld.get("offers")
        offers = offers if isinstance(offers, list) else [offers] if offers else []
        for off in offers:
            avail = str(off.get("availability") or off.get("itemAvailability") or "")
            if re.search(r"InStock", avail, re.I):
                return True, "jsonld"
            if re.search(r"OutOfStock|SoldOut", avail, re.I):
                return False, "jsonld"
    # Unknown
    return True if btn else False, "Unknown"

def _desired_gallery_urls(soup: BeautifulSoup):
    """
    Only the main 7 images in order:
      .../77632618_o, ..._o_a2, ..._o_a3, ..._o_a4, ..._o_a5, ..._o_a6, ..._o_a7
    We build from the thumbs carousel to keep the exact order, then force fmt=jpg & 1500x1500.
    """
    thumbs = []
    # Take the thumbnail <img> sources under the thumbs carousel
    for img in soup.select(".ImageGallery_thumbsContainer img[src]"):
        src = img.get("src") or ""
        if "cdn.media.amplience.net/i/frasersdev/" not in src:
            continue
        # Only keep the main product images, skip badges, etc.
        # These start with ".../{code}_o" or ".../{code}_o_aX"
        if re.search(r"/\d+_o(?:_a[2-7])?\?", src):
            thumbs.append(src)

    # Deduplicate keeping order
    seen = set()
    ordered = []
    for u in thumbs:
        # normalize to jpg, 1500x1500
        u = re.sub(r"\?(.*)$", "", u)  # strip existing query
        u = u + "?fmt=jpg&upscale=true&w=1500&h=1500&sm=scaleFit"
        if u not in seen:
            seen.add(u)
            ordered.append(u)

    # If page structure changes, try a deterministic pattern fallback from first base
    if not ordered:
        # Try to guess the base from any amplience image present
        any_img = soup.select_one("img[src*='cdn.media.amplience.net/i/frasersdev/']")
        if any_img:
            base = re.sub(r"\?.*$", "", any_img["src"])
            m = re.search(r"(https://cdn\.media\.amplience\.net/i/frasersdev/\d+)_", base)
            if m:
                code = m.group(1)
                candidates = [code + "_o"] + [f"{code}_o_a{i}" for i in range(2, 8)]
                ordered = [f"{c}?fmt=jpg&upscale=true&w=1500&h=1500&sm=scaleFit" for c in candidates]

    # Cap to 7 (o + a2..a7)
    return ordered[:7]

def _download_images_jpg(urls, folder: Path, session: requests.Session):
    folder.mkdir(parents=True, exist_ok=True)
    out_files = []
    for i, u in enumerate(urls, start=1):
        try:
            r = robust_get(session, u, timeout=30)
            content = r.content
            # Save as JPG explicitly (convert if not JPG)
            ext = ".jpg"
            # Try decoding via PIL and re-encode to JPG to guarantee extension/content alignment
            try:
                im = Image.open(io.BytesIO(content))
                rgb = im.convert("RGB")
                fp = folder / f"{i:02d}{ext}"
                rgb.save(fp, format="JPEG", quality=92, optimize=True)
                out_files.append(str(fp))
            except Exception:
                # In case PIL can't decode, just write raw with .jpg
                fp = folder / f"{i:02d}{ext}"
                with open(fp, "wb") as f:
                    f.write(content)
                out_files.append(str(fp))
        except Exception:
            print(f"  ! image error: {u}")
    return out_files

# ---------- Main ----------
def fetch_product_houseoffraser(url: str):
    session = requests.Session()
    session.headers.update(get_random_headers())
    resp = robust_get(session, url, timeout=25)
    soup = BeautifulSoup(resp.text, "lxml")

    name = _extract_name(soup)
    price, price_source = _extract_price(soup)
    in_stock, stock_text = _extract_stock(soup)
    description = _extract_description(soup)

    # Images
    image_urls = _desired_gallery_urls(soup)
    print(f"Downloading {len(image_urls)} images …")
    folder = SAVE_ROOT / f"{_retailer_slug(url)}_{_safe_name(name)}_{_stable_id_from_url(url)}"
    images_downloaded = _download_images_jpg(image_urls, folder, session)

    result = {
        "url": url,
        "name": name,
        "price": price,
        "price_source": price_source,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_count": len(image_urls),
        "image_urls": image_urls,
        "images_downloaded": images_downloaded,
        "folder": str(folder),
        "mode": "oxylabs-universal",
    }
    return result

# if __name__ == "__main__":
#     test_url = "https://www.houseoffraser.co.uk/brand/view-quest/laura-ashley-2-slice-toaster-elveden-blue-silver-776326#colcode=77632618"
#     data = fetch_product_houseoffraser(test_url)
#     print(json.dumps(data, indent=2, ensure_ascii=False))




