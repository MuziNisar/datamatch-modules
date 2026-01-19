# # fyndiq_se.py
# # Python 3.10+
# # pip install playwright requests bs4 lxml
# # playwright install

# from __future__ import annotations
# import json, os, re, time, hashlib, html, concurrent.futures as cf
# from pathlib import Path
# from typing import List, Optional, Tuple, Dict
# from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# import requests
# from bs4 import BeautifulSoup
# from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# # -----------------------------
# # Config
# # -----------------------------
# UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
# ACCEPT_LANG = "sv-SE,sv;q=0.9,en;q=0.8"
# VIEWPORT = {"width": 1400, "height": 900}
# LOCALE = "sv-SE"
# TIMEZONE = "Europe/Stockholm"

# BASE_DIR = Path(__file__).resolve().parent
# DATA_DIR = BASE_DIR / os.getenv("DATA_DIR", "data1")
# DEBUG_DIR = BASE_DIR / "debug"
# STORAGE_DIR = BASE_DIR / "storage"; STORAGE_DIR.mkdir(exist_ok=True)
# STORAGE_STATE = STORAGE_DIR / "fyndiq_state.json"
# LAUNCH_CHANNEL: Optional[str] = None  # e.g. "chrome" to use system Chrome

# ANTI_AUTOMATION_JS = r"Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"

# # Selectors (kept loose/robust)
# SEL_H1_ANY          = "h1"
# SEL_ADD_TO_CART_BTN = "[data-cy='pdp-add-to-cart'], [data-testid='pdp-add-to-cart']"
# SEL_DESC_ARIA       = "[aria-label*='Product description content' i], [aria-label*='Produktbeskrivning' i]"
# SEL_TABLIST         = "[role='tablist'] img"
# SEL_MAIN_IMG        = "[data-testid='image-panel'] img, [id^='image-panel-'] img"

# # -----------------------------
# # Helpers
# # -----------------------------
# def _vprint(verbose: bool, *args):
#     if verbose: print(*args)

# def _ensure_dir(p: Path): p.mkdir(parents=True, exist_ok=True)

# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "").strip())

# def _clean_multiline(s: str) -> str:
#     s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
#     s = re.sub(r"[ \t]+\n", "\n", s)
#     s = re.sub(r"\n{3,}", "\n\n", s)
#     return s.strip()

# def _safe_name(s: str) -> str:
#     """Create a safe filename by transliterating Unicode to ASCII and removing special chars."""
#     s = _clean(s)
    
#     # Transliterate common Unicode characters to ASCII equivalents
#     # This prevents Windows path encoding issues with OpenCV
#     transliterations = {
#         'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',  # German
#         'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
#         'à': 'a', 'á': 'a', 'â': 'a', 'ã': 'a', 'å': 'a',  # French/Spanish/Portuguese
#         'è': 'e', 'é': 'e', 'ê': 'e', 'ë': 'e',
#         'ì': 'i', 'í': 'i', 'î': 'i', 'ï': 'i',
#         'ò': 'o', 'ó': 'o', 'ô': 'o', 'õ': 'o',
#         'ù': 'u', 'ú': 'u', 'û': 'u',
#         'ç': 'c', 'ñ': 'n',
#         'æ': 'ae', 'œ': 'oe',
#     }
    
#     for unicode_char, ascii_equiv in transliterations.items():
#         s = s.replace(unicode_char, ascii_equiv)
    
#     # Remove any remaining non-ASCII/special characters
#     s = s.encode('ascii', 'ignore').decode('ascii')
    
#     # Replace remaining special chars with underscore
#     return re.sub(r"[^\w.\-]+", "_", s)[:120] or "product"

# def _stable_id_from_url(url: str) -> str:
#     try:
#         parts = [p for p in urlsplit(url).path.split("/") if p]
#         candidates = [p for p in parts if re.search(r"[0-9a-f\-]{16,}", p, re.I)]
#         token = (candidates[-1] if candidates else parts[-1]) if parts else ""
#         if token:
#             return re.sub(r"[^\w\-]+", "", token)
#     except Exception:
#         pass
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

# def _ext_from_ct_or_url(ct: Optional[str], url: str) -> str:
#     ct = (ct or "").lower()
#     if "jpeg" in ct or "jpg" in ct: return ".jpg"
#     if "png" in ct:  return ".png"
#     if "webp" in ct: return ".webp"
#     if "gif" in ct:  return ".gif"
#     path = urlsplit(url).path.lower()
#     for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
#         if path.endswith(ext): return ".jpg" if ext == ".jpeg" else ext
#     return ".jpg"

# def _replace_q(u: str, q: dict) -> str:
#     sp = urlsplit(u); qq = dict(parse_qsl(sp.query, keep_blank_values=True)); qq.update(q)
#     return urlunsplit((sp.scheme, sp.netloc, sp.path, urlencode(qq, doseq=True), ""))

# def _strip_query_and_transform(u: str) -> str:
#     sp = urlsplit(u)
#     # normalize by removing query (f_auto is in path, so safe)
#     return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

# def _dedupe_preserve_order(urls: List[str]) -> List[str]:
#     seen, out = set(), []
#     for u in urls:
#         if not u: continue
#         key = _strip_query_and_transform(u)
#         if key in seen: continue
#         seen.add(key); out.append(u)
#     return out

# # --- Price parsing (SEK/kr, spaces/commas) ---
# _PRICE_RX = re.compile(r"(\d[\d\s.,]*)\s*(SEK|kr)\b", re.I)
# def _parse_price_text_block(text: str) -> Optional[str]:
#     m = _PRICE_RX.search(text)
#     if not m: return None
#     num = re.sub(r"\s+", "", m.group(1))
#     curr = m.group(2).upper()
#     if curr == "KR": curr = "SEK"
#     return f"{num} {curr}"

# def _requests_session() -> requests.Session:
#     s = requests.Session()
#     s.headers.update({
#         "User-Agent": UA,
#         "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
#         "Accept-Language": ACCEPT_LANG,
#         "Cache-Control": "no-cache",
#         "Pragma": "no-cache",
#     })
#     return s

# # -----------------------------
# # Fyndiq image helpers (fixes 400s)
# # -----------------------------
# def _fyndiq_image_candidates(u: str) -> list[str]:
#     """
#     Generate a few likely-valid size transforms for Fyndiq CDN.
#     Keep original first, then try common presets. De-duped.
#     """
#     if not u or "images.fyndiq.se" not in u:
#         return [u]

#     sizes = ["t_1000x1000", "t_800x800", "t_712x712", "t_640x640", "t_480x480", "t_360x360", "t_120x120"]

#     out = [u]  # original first
#     m = re.search(r"/t_\d+x\d+/", u)
#     if m:
#         for sz in sizes:
#             out.append(u.replace(m.group(0), f"/{sz}/"))
#     else:
#         # If no size segment, inject before /prod/
#         out.extend([u.replace("/prod/", f"/{sz}/prod/") for sz in sizes])

#     # de-dupe
#     seen, uniq = set(), []
#     for x in out:
#         if x not in seen:
#             seen.add(x); uniq.append(x)
#     return uniq

# def _prefer_non_thumbnail(urls: list[str]) -> list[str]:
#     """
#     If both a 'miniatyrbild-*' and its base exist, drop the 'miniatyrbild-*'.
#     """
#     base_set = set()
#     minis, bases = [], []
#     for u in urls:
#         last = urlsplit(u).path.rsplit("/", 1)[-1]
#         if last.startswith("miniatyrbild-"):
#             minis.append(u)
#         else:
#             bases.append(u)
#             base_set.add(last)
#     keep = bases[:]
#     for u in minis:
#         last = urlsplit(u).path.rsplit("/", 1)[-1]
#         probable_base = re.sub(r"^miniatyrbild-\d+-av-\d+-", "", last)
#         if probable_base not in base_set:
#             keep.append(u)
#     return keep

# # -----------------------------
# # Playwright bootstrap
# # -----------------------------
# def _prepare_context(pw, headless: bool, verbose: bool):
#     launch_kwargs = {
#         "headless": headless,
#         "args": [
#             "--disable-blink-features=AutomationControlled",
#             "--no-default-browser-check",
#             "--no-first-run",
#             "--disable-background-networking",
#             "--disable-background-timer-throttling",
#             "--disable-renderer-backgrounding",
#         ],
#     }
#     if LAUNCH_CHANNEL:
#         launch_kwargs["channel"] = LAUNCH_CHANNEL
#     browser = pw.chromium.launch(**launch_kwargs)
#     context = browser.new_context(
#         user_agent=UA,
#         locale=LOCALE,
#         timezone_id=TIMEZONE,
#         viewport=VIEWPORT,
#         java_script_enabled=True,
#         accept_downloads=False,
#         storage_state=str(STORAGE_STATE) if STORAGE_STATE.exists() else None,
#     )
#     context.add_init_script(ANTI_AUTOMATION_JS)

#     # block noisy 3P requests (keep images/css/js)
#     noisy_hosts = (
#         "googletagmanager.com","google-analytics.com","doubleclick.net",
#         "facebook.net","facebook.com/tr","hotjar.com","bing.com","criteo.com",
#         "quantserve.com","adservice.google.com","optimizely.com",
#     )
#     def _should_block(req):
#         rt, u = req.resource_type, req.url
#         if rt in ("font","media"):  # keep images
#             return True
#         return any(h in u for h in noisy_hosts)
#     def _router(route):
#         try:
#             if _should_block(route.request): return route.abort()
#         except Exception: pass
#         return route.continue_()
#     context.route("**/*", _router)

#     page = context.new_page()
#     page.set_default_timeout(12000)
#     page.set_default_navigation_timeout(18000)
#     _vprint(verbose, f"Storage state exists: {STORAGE_STATE.exists()}")
#     return browser, context, page

# def _accept_didomi(page, context, verbose: bool):
#     # Exact button: #didomi-notice-agree-button
#     try:
#         btn = page.locator("#didomi-notice-agree-button").first
#         if btn and btn.is_visible():
#             _vprint(verbose, "Clicking Didomi consent…")
#             btn.click(force=True, timeout=3000)
#             page.wait_for_timeout(200)
#     except Exception: pass
#     # iframe fallback (some implementations)
#     try:
#         for f in page.frames:
#             try:
#                 ib = f.locator("#didomi-notice-agree-button").first
#                 if ib and ib.is_visible():
#                     _vprint(verbose, "Clicking Didomi in iframe…")
#                     ib.click(force=True, timeout=3000)
#                     page.wait_for_timeout(200)
#                     break
#             except Exception: continue
#     except Exception: pass
#     # persist
#     try:
#         context.storage_state(path=str(STORAGE_STATE))
#         _vprint(verbose, f"Consent persisted → {STORAGE_STATE}")
#     except Exception: pass

# # -----------------------------
# # DOM extractors (Playwright)
# # -----------------------------
# def _extract_name_dom(page) -> str:
#     try:
#         page.wait_for_selector(SEL_H1_ANY, timeout=6000)
#         t = _clean(page.locator(SEL_H1_ANY).first.inner_text())
#         if t: return t
#     except Exception: pass
#     try:
#         return _clean(page.title().split("|")[0])
#     except Exception:
#         return "Unknown_Product"

# def _extract_price_dom(page) -> Tuple[str, str]:
#     # JSON-LD first
#     try:
#         blocks = page.locator("script[type='application/ld+json']")
#         for i in range(blocks.count()):
#             raw = blocks.nth(i).inner_text() or ""
#             try:
#                 data = json.loads(raw)
#             except Exception:
#                 try: data = json.loads(raw.strip().rstrip(","))
#                 except Exception: continue
#             objs = data if isinstance(data, list) else [data]
#             for obj in objs:
#                 if isinstance(obj, dict) and obj.get("@type") in ("Product",):
#                     offers = obj.get("offers") or {}
#                     if isinstance(offers, list): offers = offers[0] if offers else {}
#                     p = offers.get("price"); curr = (offers.get("priceCurrency") or "").upper() or "SEK"
#                     if p is not None:
#                         pv = p if isinstance(p, str) else str(p).replace(",", ".")
#                         return _clean(f"{pv} {curr}"), "jsonld"
#     except Exception: pass
#     # Visible text fallback
#     try:
#         body_txt = page.locator("body").inner_text(timeout=4000)
#         parsed = _parse_price_text_block(body_txt)
#         if parsed: return parsed, "onsite"
#     except Exception: pass
#     return "N/A", "none"

# def _extract_stock_dom(page) -> Tuple[Optional[bool], Optional[str]]:
#     # “In stock” / “I lager” etc.
#     try:
#         stock = page.get_by_text(re.compile(r"\bIn stock\b|\bI lager\b|\bFinns i lager\b", re.I))
#         if stock.count() > 0 and stock.first.is_visible():
#             return True, _clean(stock.first.inner_text())
#     except Exception: pass
#     try:
#         oos = page.get_by_text(re.compile(r"slut i lager|tillf[aä]lligt slut|ej i lager", re.I))
#         if oos.count() > 0 and oos.first.is_visible():
#             return False, _clean(oos.first.inner_text())
#     except Exception: pass
#     # Add-to-cart heuristic (if present)
#     try:
#         btn = page.locator(SEL_ADD_TO_CART_BTN).first
#         if btn and btn.is_visible():
#             disabled = btn.get_attribute("disabled")
#             aria_dis = btn.get_attribute("aria-disabled")
#             if not disabled and (aria_dis in (None, "false")):
#                 return True, "In Stock"
#     except Exception: pass
#     return None, None

# def _extract_desc_dom(page) -> str:
#     # aria-labeled content region
#     try:
#         region = page.locator(SEL_DESC_ARIA).first
#         if region and region.is_visible():
#             return _clean_multiline(html.unescape(region.inner_text()))
#     except Exception: pass
#     # keyword fallback
#     try:
#         para = page.get_by_text(re.compile(r"Product description|Produktbeskrivning", re.I)).first
#         if para and para.is_visible():
#             return _clean_multiline(html.unescape(para.locator("xpath=..").inner_text()))
#     except Exception: pass
#     return ""

# def _collect_images_dom(page, max_images: Optional[int]) -> List[str]:
#     urls: List[str] = []
#     try:
#         thumbs = page.locator(SEL_TABLIST)
#         cnt = min(thumbs.count(), max_images or 9999)
#         for i in range(cnt):
#             u = thumbs.nth(i).get_attribute("data-src") or thumbs.nth(i).get_attribute("src")
#             if u: urls.append(u)
#     except Exception: pass
#     if not urls:
#         try:
#             tabs = page.locator("[role='tab']")
#             n = min(tabs.count(), 6)
#             for i in range(n):
#                 tabs.nth(i).click()
#                 page.wait_for_timeout(80)
#                 mains = page.locator(SEL_MAIN_IMG)
#                 mcnt = min(mains.count(), 3)
#                 for j in range(mcnt):
#                     u = mains.nth(j).get_attribute("src")
#                     if u: urls.append(u)
#         except Exception: pass

#     # Prefer non-thumbnail filenames if their base exists; keep order + de-dupe
#     urls = [u for u in urls if u and u.startswith("http")]
#     urls = _prefer_non_thumbnail(urls)
#     urls = _dedupe_preserve_order(urls)
#     if max_images is not None: urls = urls[:max_images]
#     return urls

# # -----------------------------
# # HTTP/BS4 fast path
# # -----------------------------
# def _extract_from_html_bs4(html_text: str) -> Dict[str, str | List[str]]:
#     soup = BeautifulSoup(html_text, "lxml")

#     # name
#     name = ""
#     h1 = soup.select_one("h1")
#     if h1: name = _clean(h1.get_text(" ", strip=True))
#     if not name and soup.title:
#         name = _clean(soup.title.get_text().split("|")[0])

#     # price via JSON-LD
#     price, price_source = "N/A", "none"
#     for tag in soup.select("script[type='application/ld+json']"):
#         raw = tag.string or tag.get_text()
#         if not raw: continue
#         try:
#             data = json.loads(raw)
#         except Exception:
#             try: data = json.loads(raw.strip().rstrip(","))
#             except Exception: continue
#         objs = data if isinstance(data, list) else [data]
#         done = False
#         for obj in objs:
#             if isinstance(obj, dict) and obj.get("@type") in ("Product",):
#                 offers = obj.get("offers") or {}
#                 if isinstance(offers, list): offers = offers[0] if offers else {}
#                 p = offers.get("price"); curr = (offers.get("priceCurrency") or "").upper() or "SEK"
#                 if p is not None:
#                     pv = p if isinstance(p, str) else str(p).replace(",", ".")
#                     price, price_source = _clean(f"{pv} {curr}"), "jsonld"; done = True; break
#         if done: break

#     if price_source == "none":
#         body_txt = soup.get_text(" ", strip=True)
#         maybe = _parse_price_text_block(body_txt)
#         if maybe: price, price_source = maybe, "onsite"

#     # description
#     desc = ""
#     region = soup.select_one("[aria-label*='Product description content' i], [aria-label*='Produktbeskrivning' i]")
#     if region:
#         desc = _clean_multiline(html.unescape(region.get_text("\n", strip=True)))
#     else:
#         candidates = soup.find_all(string=re.compile(r"Product description|Produktbeskrivning", re.I))
#         if candidates:
#             node = candidates[0].parent
#             desc = _clean_multiline(html.unescape(node.get_text("\n", strip=True)))

#     # images (SSR may already include)
#     img_urls: List[str] = []
#     for img in soup.select(f"{SEL_TABLIST}, {SEL_MAIN_IMG}"):
#         src = img.get("data-src") or img.get("src")
#         if src and src.startswith("http"):
#             img_urls.append(src)
#     img_urls = _prefer_non_thumbnail(img_urls)
#     img_urls = _dedupe_preserve_order(img_urls)

#     return {"name": name or "", "price": price, "price_source": price_source,
#             "description": desc, "image_urls": img_urls}

# # -----------------------------
# # Downloads (with size probing + Referer)
# # -----------------------------
# def _download_one(session: requests.Session, url: str, out: Path, verbose: bool, referer: str | None) -> Optional[str]:
#     # image-friendly headers + Referer for hotlink protection
#     session.headers.update({
#         "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#     })
#     if referer:
#         session.headers["Referer"] = referer

#     for candidate in _fyndiq_image_candidates(url):
#         try:
#             r = session.get(candidate, timeout=20)
#             if r.status_code < 400 and r.content:
#                 ct = r.headers.get("content-type", "")
#                 ext = _ext_from_ct_or_url(ct, candidate)
#                 out_final = out.with_suffix(ext)
#                 out_final.write_bytes(r.content)
#                 _vprint(verbose, f"  ✓ {out_final.name}  ← {candidate}")
#                 return str(out_final)
#             else:
#                 _vprint(verbose, f"  ! HTTP {r.status_code} {candidate}")
#         except Exception as e:
#             _vprint(verbose, f"  ! {candidate} error: {e}")
#     return None

# def _download_images_concurrent(img_urls: List[str], folder: Path, max_workers: int, verbose: bool, referer: str | None = None) -> List[str]:
#     saved: List[str] = []
#     _ensure_dir(folder)
#     with requests.Session() as s:
#         s.headers.update({"User-Agent": UA, "Accept-Language": ACCEPT_LANG})
#         with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
#             futures = []
#             for idx, u in enumerate(img_urls, 1):
#                 out = folder / f"{idx:02d}"  # ext later
#                 futures.append(ex.submit(_download_one, s, u, out, verbose, referer))
#             for f in cf.as_completed(futures):
#                 p = f.result()
#                 if p: saved.append(p)
#     return saved

# # -----------------------------
# # Public API
# # -----------------------------
# def scrape_fyndiq(
#     url: str,
#     headless: bool = True,
#     prefer_http: bool = True,
#     render_fallback: bool = True,
#     download_images: bool = False,
#     max_images: Optional[int] = 12,
#     max_image_workers: int = 6,
#     verbose: bool = False,
# ) -> Dict:
#     """
#     Fast path (HTTP/BS4), then Playwright if critical fields are missing.
#     """
#     _ensure_dir(DATA_DIR); _ensure_dir(DEBUG_DIR)
#     result = {
#         "url": url,
#         "name": "",
#         "price": "N/A",
#         "price_source": "none",
#         "in_stock": None,
#         "stock_text": None,
#         "description": "",
#         "image_count": 0,
#         "image_urls": [],
#         "images_downloaded": [],
#         "folder": "",
#         "mode": "http"
#     }

#     # ---------- Tier 1: HTTP ----------
#     if prefer_http:
#         try:
#             with _requests_session() as s:
#                 r = s.get(url, timeout=15)
#                 r.raise_for_status()
#                 parsed = _extract_from_html_bs4(r.text)
#                 result.update({
#                     "name": parsed["name"],
#                     "price": parsed["price"],
#                     "price_source": parsed["price_source"],
#                     "description": parsed["description"],
#                     "image_urls": parsed["image_urls"][: (max_images or 9999)]
#                 })
#             # best-effort stock from HTML text
#             txt = r.text
#             if re.search(r"\bIn stock\b|\bI lager\b|\bFinns i lager\b", txt, re.I):
#                 result["in_stock"], result["stock_text"] = True, "In stock"
#             elif re.search(r"slut i lager|tillf[aä]lligt slut|ej i lager", txt, re.I):
#                 result["in_stock"], result["stock_text"] = False, "Out of stock"
#         except Exception as e:
#             _vprint(verbose, f"[HTTP] failed → {e}")

#     need_render = (
#         (not result["name"]) or
#         (result["price_source"] == "none") or
#         (download_images and not result["image_urls"])
#     )

#     # ---------- Tier 2: Playwright ----------
#     if (not prefer_http) or (need_render and render_fallback):
#         try:
#             with sync_playwright() as pw:
#                 browser, context, page = _prepare_context(pw, headless=headless, verbose=verbose)
#                 try:
#                     _vprint(verbose, "[PW] Navigating …")
#                     resp = page.goto(url, wait_until="domcontentloaded", timeout=18000)
#                     if not resp or not (200 <= resp.status <= 399):
#                         _vprint(verbose, f"[PW] status {resp.status if resp else 'n/a'}")

#                     _accept_didomi(page, context, verbose)

#                     try: page.wait_for_selector(SEL_H1_ANY, timeout=7000)
#                     except Exception: pass

#                     name = _extract_name_dom(page)
#                     price, price_source = _extract_price_dom(page)
#                     in_stock, stock_text = _extract_stock_dom(page)
#                     description = _extract_desc_dom(page)
#                     image_urls = _collect_images_dom(page, max_images)

#                     result.update({
#                         "name": name or result["name"],
#                         "price": price if price_source != "none" else result["price"],
#                         "price_source": price_source if price_source != "none" else result["price_source"],
#                         "in_stock": in_stock if in_stock is not None else result["in_stock"],
#                         "stock_text": stock_text if stock_text else result["stock_text"],
#                         "description": description if description else result["description"],
#                         "image_urls": image_urls if image_urls else result["image_urls"],
#                         "mode": "render"
#                     })
#                 finally:
#                     context.storage_state(path=str(STORAGE_STATE))
#                     browser.close()
#         except PlaywrightTimeoutError as e:
#             ts = int(time.time())
#             _ensure_dir(DEBUG_DIR)
#             (DEBUG_DIR / f"fyndiq_timeout_{ts}.note").write_text(f"Timed out {url}", encoding="utf-8")
#             raise e

#     # ---------- Output & optional downloads ----------
#     slug = "fyndiq"
#     stable_id = _stable_id_from_url(url)
#     folder = DATA_DIR / f"{slug}_{_safe_name(result['name'] or 'product')}_{_safe_name(stable_id)}"
#     _ensure_dir(folder)
#     result["folder"] = str(folder)

#     if download_images and result["image_urls"]:
#         _vprint(verbose, f"Downloading {len(result['image_urls'])} images …")
#         saved = _download_images_concurrent(result["image_urls"], folder, max_image_workers, verbose, referer=url)
#         result["images_downloaded"] = saved
#         result["image_count"] = len(saved)
#     else:
#         result["image_count"] = len(result["image_urls"])

#     return result

# # # -----------------------------
# # # Simple VS Code runner
# # # -----------------------------
# # if __name__ == "__main__":
# #     # 1) Paste your product URL here:
# #     URL = "https://fyndiq.se/produkt/tradl-kettles-laura-ashley-marine-elveden-kapacitet-15l-kalkfilter-2200w-automatisk-avstangning-mang-a468e94ffb7442f9/"

# #     # 2) Tweak options if you like:
# #     HEADLESS         = True          # set False to watch the browser
# #     PREFER_HTTP      = True          # try fast BS4 first
# #     RENDER_FALLBACK  = True          # use Playwright if needed
# #     DOWNLOAD_IMAGES  = True          # True = save images
# #     MAX_IMAGES       = 20            # cap images
# #     WORKERS          = 6             # concurrent image downloads
# #     VERBOSE          = True

# #     data = scrape_fyndiq(
# #         URL,
# #         headless=HEADLESS,
# #         prefer_http=PREFER_HTTP,
# #         render_fallback=RENDER_FALLBACK,
# #         download_images=DOWNLOAD_IMAGES,
# #         max_images=MAX_IMAGES,
# #         max_image_workers=WORKERS,
# #         verbose=VERBOSE,
# #     )

# #     # Pretty print result
# #     print(json.dumps(data, indent=2, ensure_ascii=False))







# fyndiq_se.py
# Python 3.10+
# pip install playwright requests bs4 lxml
# playwright install

from __future__ import annotations
import json, os, re, time, hashlib, html, concurrent.futures as cf
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# -----------------------------
# Config
# -----------------------------
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
ACCEPT_LANG = "sv-SE,sv;q=0.9,en;q=0.8"
VIEWPORT = {"width": 1400, "height": 900}
LOCALE = "sv-SE"
TIMEZONE = "Europe/Stockholm"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / os.getenv("DATA_DIR", "data1")
DEBUG_DIR = BASE_DIR / "debug"
STORAGE_DIR = BASE_DIR / "storage"; STORAGE_DIR.mkdir(exist_ok=True)
STORAGE_STATE = STORAGE_DIR / "fyndiq_state.json"
LAUNCH_CHANNEL: Optional[str] = None  # e.g. "chrome" to use system Chrome

ANTI_AUTOMATION_JS = r"Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"

# Selectors (kept loose/robust)
SEL_H1_ANY          = "h1"
SEL_ADD_TO_CART_BTN = "[data-cy='pdp-add-to-cart'], [data-testid='pdp-add-to-cart']"
SEL_DESC_ARIA       = "[aria-label*='Product description content' i], [aria-label*='Produktbeskrivning' i]"
SEL_TABLIST         = "[role='tablist'] img"
SEL_MAIN_IMG        = "[data-testid='image-panel'] img, [id^='image-panel-'] img"

# -----------------------------
# Invalid Link Detection Patterns
# -----------------------------
# Layer 1: 404 Page Detection (Swedish)
# These patterns are checked within context windows to avoid false positives
INVALID_404_PATTERNS_STRICT = [
    # Must appear in H1 or prominent error message - very specific
    r"<h1[^>]*>.*?Ooops!\s*Sidan finns inte.*?</h1>",  # 404 in H1
    r"<h1[^>]*>.*?404.*?</h1>",                         # 404 in H1
    r"<h1[^>]*>.*?[Ss]idan\s+finns\s+inte.*?</h1>",    # "Page doesn't exist" in H1
]

# These are checked as text but with additional validation
INVALID_404_PATTERNS_CONTEXTUAL = [
    r"Ooops!\s*Sidan finns inte l[aä]ngre",        # "Oops! The page no longer exists"
    r"hittade du till en sida som inte finns",     # "you found a page that doesn't exist"
]

# Patterns that CONFIRM it's NOT a 404 (product page indicators in same context)
NOT_404_INDICATORS = [
    r'"@type"\s*:\s*"Product"',                    # JSON-LD Product
    r'data-cy=["\']pdp-add-to-cart["\']',          # Add to cart button
    r'data-testid=["\']pdp-add-to-cart["\']',      # Add to cart (alternate)
    r'"offers"\s*:\s*\{',                          # JSON-LD offers block
    r'itemprop=["\']price["\']',                   # Schema.org price
]

# Layer 2: Category/Listing Page Indicators
CATEGORY_INDICATORS = [
    # Pagination (strong signal)
    r'aria-label=["\']Paginering["\']',             # Swedish "Pagination"
    r'aria-label=["\']G[aå]\s+till\s+sida\s+\d+["\']',  # "Go to page X"
    r'aria-label=["\']n[aä]sta\s+sida["\']',        # "Next page"
    r'aria-label=["\']f[oö]reg[aå]ende\s+sida["\']', # "Previous page"
    r'\?page=\d+',                                   # Pagination URL parameter
    
    # Product listing/grid
    r'role=["\']navigation["\'][^>]*Paginering',   # Navigation with pagination
    r'class="[^"]*product-?grid[^"]*"',            # Product grid
    r'class="[^"]*product-?list[^"]*"',            # Product list
    r'data-testid=["\']product-?card["\']',        # Product cards (multiple)
    
    # Filter/Sort controls
    r'aria-label=["\']Sortera["\']',               # "Sort"
    r'aria-label=["\']Filter["\']',                # "Filter"
    r'Visa\s+\d+\s+produkter',                     # "Show X products"
    r'\d+\s+produkter',                            # "X products"
]

# Layer 3: Product Page Indicators (absence = likely invalid)
PRODUCT_INDICATORS = [
    r'data-cy=["\']pdp-add-to-cart["\']',          # Add to cart button
    r'data-testid=["\']pdp-add-to-cart["\']',      # Add to cart button (alternate)
    r'@type["\']?\s*:\s*["\']Product["\']',        # JSON-LD Product type
    r'"@type"\s*:\s*"Product"',                    # JSON-LD (escaped)
    r'aria-label=["\']Produktbeskrivning["\']',    # "Product description"
    r'aria-label=["\']Product description["\']',   # English variant
    r'data-testid=["\']image-panel["\']',          # Product image panel
    r'class="[^"]*price[^"]*".*?SEK',              # Price in SEK
    r'class="[^"]*price[^"]*".*?kr\b',             # Price in kr
]

# -----------------------------
# Invalid Link Detector
# -----------------------------
class FyndiqInvalidLinkDetector:
    """
    Detects when a Fyndiq product URL leads to:
    - 404 page (product removed)
    - Category/listing page (product unavailable, redirected)
    """
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
    
    def _vprint(self, *args):
        if self.verbose:
            print("[InvalidDetector]", *args)
    
    def _normalize_text(self, text: str) -> str:
        """Remove escape sequences for consistent pattern matching."""
        return text.replace('\\\\', '').replace('\\"', '"').replace("\\'", "'")
    
    def _check_404_page(self, page_text: str) -> Tuple[bool, Optional[str]]:
        """Check for 404/removed product page patterns with context awareness."""
        normalized = self._normalize_text(page_text)
        
        # First, check if this looks like a valid product page
        # If we find strong product indicators, it's NOT a 404
        for pattern in NOT_404_INDICATORS:
            if re.search(pattern, normalized, re.IGNORECASE | re.DOTALL):
                self._vprint(f"Found product indicator, skipping 404 check: {pattern[:40]}")
                return False, None
        
        # Check strict patterns (must be in H1 or specific structure)
        for pattern in INVALID_404_PATTERNS_STRICT:
            if re.search(pattern, normalized, re.IGNORECASE | re.DOTALL):
                self._vprint(f"Strict 404 pattern matched: {pattern[:50]}")
                return True, f"404 page detected (H1 contains error message)"
        
        # Check contextual patterns - these need additional validation
        for pattern in INVALID_404_PATTERNS_CONTEXTUAL:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                # Get surrounding context (500 chars before and after)
                start = max(0, match.start() - 500)
                end = min(len(normalized), match.end() + 500)
                context = normalized[start:end]
                
                # Validate: should NOT have product-related content nearby
                has_product_context = any(
                    re.search(p, context, re.IGNORECASE) 
                    for p in [r'add.?to.?cart', r'price', r'pris', r'SEK', r'offers', r'Product']
                )
                
                if not has_product_context:
                    self._vprint(f"Contextual 404 pattern matched: {pattern[:50]}")
                    return True, f"404 page detected (pattern: {pattern[:30]}...)"
                else:
                    self._vprint(f"404 pattern found but has product context, ignoring")
        
        return False, None
    
    def _check_category_page(self, page_text: str) -> Tuple[bool, int, List[str]]:
        """
        Check for category/listing page indicators.
        Returns (is_category, score, matched_patterns)
        """
        normalized = self._normalize_text(page_text)
        matched = []
        
        for pattern in CATEGORY_INDICATORS:
            if re.search(pattern, normalized, re.IGNORECASE):
                matched.append(pattern[:40])
        
        score = len(matched)
        # Need at least 2 category indicators to be confident
        is_category = score >= 2
        
        if matched:
            self._vprint(f"Category indicators ({score}): {matched[:3]}")
        
        return is_category, score, matched
    
    def _check_product_page(self, page_text: str) -> Tuple[bool, int, List[str]]:
        """
        Check for product page indicators.
        Returns (is_product, score, matched_patterns)
        """
        normalized = self._normalize_text(page_text)
        matched = []
        
        for pattern in PRODUCT_INDICATORS:
            if re.search(pattern, normalized, re.IGNORECASE):
                matched.append(pattern[:40])
        
        score = len(matched)
        # Need at least 2 product indicators to confirm it's a product page
        is_product = score >= 2
        
        if matched:
            self._vprint(f"Product indicators ({score}): {matched[:3]}")
        
        return is_product, score, matched
    
    def _check_url_redirect(self, original_url: str, final_url: str) -> Tuple[bool, Optional[str]]:
        """
        Check if URL was redirected away from product page.
        Fyndiq product URLs: /produkt/slug-uuid/
        Category URLs: /category/subcategory/ or /search/
        """
        orig_path = urlsplit(original_url).path.lower()
        final_path = urlsplit(final_url).path.lower()
        
        # Original should be a product URL
        if '/produkt/' not in orig_path:
            return False, None
        
        # Check if redirected away from product
        if '/produkt/' not in final_path:
            self._vprint(f"URL redirect: {orig_path} → {final_path}")
            return True, f"Redirected from product to: {final_path}"
        
        # Check if UUID part changed significantly (different product)
        orig_uuid = orig_path.split('/')[-2] if orig_path.endswith('/') else orig_path.split('/')[-1]
        final_uuid = final_path.split('/')[-2] if final_path.endswith('/') else final_path.split('/')[-1]
        
        if orig_uuid != final_uuid:
            self._vprint(f"Product ID changed: {orig_uuid} → {final_uuid}")
            # This might be OK (slug normalization), so don't flag as invalid
            pass
        
        return False, None
    
    def _check_json_ld(self, page_text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract page type from JSON-LD structured data.
        Returns (page_type, None) or (None, error_msg)
        """
        normalized = self._normalize_text(page_text)
        
        # Find JSON-LD blocks
        ld_pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
        matches = re.findall(ld_pattern, normalized, re.DOTALL | re.IGNORECASE)
        
        for match in matches:
            try:
                # Clean up the JSON
                clean = match.strip().rstrip(',')
                data = json.loads(clean)
                
                if isinstance(data, list):
                    data = data[0] if data else {}
                
                if isinstance(data, dict):
                    page_type = data.get('@type', '')
                    if page_type:
                        self._vprint(f"JSON-LD @type: {page_type}")
                        return page_type, None
            except json.JSONDecodeError:
                continue
        
        return None, None
    
    def is_invalid_link(
        self,
        page_text: str,
        original_url: str,
        final_url: Optional[str] = None,
        http_status: Optional[int] = None
    ) -> Tuple[bool, str, Dict]:
        """
        Main entry point: determine if link is invalid.
        
        Returns:
            (is_invalid, reason, details_dict)
        """
        details = {
            'http_status': http_status,
            'is_404': False,
            'is_category': False,
            'is_product': False,
            'category_score': 0,
            'product_score': 0,
            'redirect_detected': False,
            'json_ld_type': None,
        }
        
        # Check HTTP status first
        if http_status and http_status == 404:
            details['is_404'] = True
            return True, "HTTP 404 response", details
        
        # Layer 1: 404 page content
        is_404, reason_404 = self._check_404_page(page_text)
        if is_404:
            details['is_404'] = True
            return True, reason_404, details
        
        # Layer 2: URL redirect check
        if final_url:
            redirected, redirect_reason = self._check_url_redirect(original_url, final_url)
            if redirected:
                details['redirect_detected'] = True
                # Continue checking - redirect alone isn't definitive
        
        # Layer 3: JSON-LD type
        json_type, _ = self._check_json_ld(page_text)
        details['json_ld_type'] = json_type
        
        if json_type:
            # ItemList, CollectionPage, SearchResultsPage = category/listing
            invalid_types = ['ItemList', 'CollectionPage', 'SearchResultsPage', 'WebPage']
            if json_type in invalid_types:
                details['is_category'] = True
                return True, f"JSON-LD type indicates listing: {json_type}", details
            elif json_type == 'Product':
                details['is_product'] = True
                # Likely valid, but continue checks
        
        # Layer 4: DOM indicator scoring
        is_category, cat_score, _ = self._check_category_page(page_text)
        is_product, prod_score, _ = self._check_product_page(page_text)
        
        details['is_category'] = is_category
        details['is_product'] = is_product
        details['category_score'] = cat_score
        details['product_score'] = prod_score
        
        # Decision logic
        # Strong category signal + weak/no product signal = invalid
        if cat_score >= 2 and prod_score == 0:
            return True, f"Category page detected (cat={cat_score}, prod={prod_score})", details
        
        # Strong category + redirect = invalid
        if cat_score >= 2 and details['redirect_detected']:
            return True, f"Redirected to category page (cat={cat_score})", details
        
        # Category signals present but product also present - ambiguous, favor valid
        if cat_score >= 2 and prod_score >= 2:
            self._vprint(f"Ambiguous: cat={cat_score}, prod={prod_score}, defaulting to valid")
            return False, "Ambiguous signals, defaulting to valid", details
        
        # Product page confirmed
        if prod_score >= 2:
            return False, "Valid product page", details
        
        # Low signals on both - check if it looks like an error page
        if cat_score == 0 and prod_score == 0:
            # Could be a soft 404 or error page
            if details['redirect_detected']:
                return True, "Redirected with no product indicators", details
            # No clear signals, default to valid
            return False, "No clear signals, defaulting to valid", details
        
        # Default: trust it's valid
        return False, "Passed all checks", details


def detect_invalid_link(
    page_text: str,
    original_url: str,
    final_url: Optional[str] = None,
    http_status: Optional[int] = None,
    verbose: bool = False
) -> Tuple[bool, str, Dict]:
    """
    Convenience function for invalid link detection.
    
    Args:
        page_text: HTML content of the page
        original_url: The URL that was requested
        final_url: The final URL after any redirects (optional)
        http_status: HTTP response status code (optional)
        verbose: Print debug info
    
    Returns:
        (is_invalid, reason, details_dict)
    """
    detector = FyndiqInvalidLinkDetector(verbose=verbose)
    return detector.is_invalid_link(page_text, original_url, final_url, http_status)


# -----------------------------
# Helpers
# -----------------------------
def _vprint(verbose: bool, *args):
    if verbose: print(*args)

def _ensure_dir(p: Path): p.mkdir(parents=True, exist_ok=True)

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _clean_multiline(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _safe_name(s: str) -> str:
    """Create a safe filename by transliterating Unicode to ASCII and removing special chars."""
    s = _clean(s)
    
    # Transliterate common Unicode characters to ASCII equivalents
    # This prevents Windows path encoding issues with OpenCV
    transliterations = {
        'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',  # German
        'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
        'à': 'a', 'á': 'a', 'â': 'a', 'ã': 'a', 'å': 'a',  # French/Spanish/Portuguese
        'è': 'e', 'é': 'e', 'ê': 'e', 'ë': 'e',
        'ì': 'i', 'í': 'i', 'î': 'i', 'ï': 'i',
        'ò': 'o', 'ó': 'o', 'ô': 'o', 'õ': 'o',
        'ù': 'u', 'ú': 'u', 'û': 'u',
        'ç': 'c', 'ñ': 'n',
        'æ': 'ae', 'œ': 'oe',
    }
    
    for unicode_char, ascii_equiv in transliterations.items():
        s = s.replace(unicode_char, ascii_equiv)
    
    # Remove any remaining non-ASCII/special characters
    s = s.encode('ascii', 'ignore').decode('ascii')
    
    # Replace remaining special chars with underscore
    return re.sub(r"[^\w.\-]+", "_", s)[:120] or "product"

def _stable_id_from_url(url: str) -> str:
    try:
        parts = [p for p in urlsplit(url).path.split("/") if p]
        candidates = [p for p in parts if re.search(r"[0-9a-f\-]{16,}", p, re.I)]
        token = (candidates[-1] if candidates else parts[-1]) if parts else ""
        if token:
            return re.sub(r"[^\w\-]+", "", token)
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

def _ext_from_ct_or_url(ct: Optional[str], url: str) -> str:
    ct = (ct or "").lower()
    if "jpeg" in ct or "jpg" in ct: return ".jpg"
    if "png" in ct:  return ".png"
    if "webp" in ct: return ".webp"
    if "gif" in ct:  return ".gif"
    path = urlsplit(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if path.endswith(ext): return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"

def _replace_q(u: str, q: dict) -> str:
    sp = urlsplit(u); qq = dict(parse_qsl(sp.query, keep_blank_values=True)); qq.update(q)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, urlencode(qq, doseq=True), ""))

def _strip_query_and_transform(u: str) -> str:
    sp = urlsplit(u)
    # normalize by removing query (f_auto is in path, so safe)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

def _dedupe_preserve_order(urls: List[str]) -> List[str]:
    seen, out = set(), []
    for u in urls:
        if not u: continue
        key = _strip_query_and_transform(u)
        if key in seen: continue
        seen.add(key); out.append(u)
    return out

# --- Price parsing (SEK/kr, spaces/commas) ---
_PRICE_RX = re.compile(r"(\d[\d\s.,]*)\s*(SEK|kr)\b", re.I)
def _parse_price_text_block(text: str) -> Optional[str]:
    m = _PRICE_RX.search(text)
    if not m: return None
    num = re.sub(r"\s+", "", m.group(1))
    curr = m.group(2).upper()
    if curr == "KR": curr = "SEK"
    return f"{num} {curr}"

def _requests_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    return s

# -----------------------------
# Fyndiq image helpers (fixes 400s)
# -----------------------------
def _fyndiq_image_candidates(u: str) -> list[str]:
    """
    Generate a few likely-valid size transforms for Fyndiq CDN.
    Keep original first, then try common presets. De-duped.
    """
    if not u or "images.fyndiq.se" not in u:
        return [u]

    sizes = ["t_1000x1000", "t_800x800", "t_712x712", "t_640x640", "t_480x480", "t_360x360", "t_120x120"]

    out = [u]  # original first
    m = re.search(r"/t_\d+x\d+/", u)
    if m:
        for sz in sizes:
            out.append(u.replace(m.group(0), f"/{sz}/"))
    else:
        # If no size segment, inject before /prod/
        out.extend([u.replace("/prod/", f"/{sz}/prod/") for sz in sizes])

    # de-dupe
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x); uniq.append(x)
    return uniq

def _prefer_non_thumbnail(urls: list[str]) -> list[str]:
    """
    If both a 'miniatyrbild-*' and its base exist, drop the 'miniatyrbild-*'.
    """
    base_set = set()
    minis, bases = [], []
    for u in urls:
        last = urlsplit(u).path.rsplit("/", 1)[-1]
        if last.startswith("miniatyrbild-"):
            minis.append(u)
        else:
            bases.append(u)
            base_set.add(last)
    keep = bases[:]
    for u in minis:
        last = urlsplit(u).path.rsplit("/", 1)[-1]
        probable_base = re.sub(r"^miniatyrbild-\d+-av-\d+-", "", last)
        if probable_base not in base_set:
            keep.append(u)
    return keep

# -----------------------------
# Playwright bootstrap
# -----------------------------
def _prepare_context(pw, headless: bool, verbose: bool):
    launch_kwargs = {
        "headless": headless,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
            "--no-first-run",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
        ],
    }
    if LAUNCH_CHANNEL:
        launch_kwargs["channel"] = LAUNCH_CHANNEL
    browser = pw.chromium.launch(**launch_kwargs)
    context = browser.new_context(
        user_agent=UA,
        locale=LOCALE,
        timezone_id=TIMEZONE,
        viewport=VIEWPORT,
        java_script_enabled=True,
        accept_downloads=False,
        storage_state=str(STORAGE_STATE) if STORAGE_STATE.exists() else None,
    )
    context.add_init_script(ANTI_AUTOMATION_JS)

    # block noisy 3P requests (keep images/css/js)
    noisy_hosts = (
        "googletagmanager.com","google-analytics.com","doubleclick.net",
        "facebook.net","facebook.com/tr","hotjar.com","bing.com","criteo.com",
        "quantserve.com","adservice.google.com","optimizely.com",
    )
    def _should_block(req):
        rt, u = req.resource_type, req.url
        if rt in ("font","media"):  # keep images
            return True
        return any(h in u for h in noisy_hosts)
    def _router(route):
        try:
            if _should_block(route.request): return route.abort()
        except Exception: pass
        return route.continue_()
    context.route("**/*", _router)

    page = context.new_page()
    page.set_default_timeout(12000)
    page.set_default_navigation_timeout(18000)
    _vprint(verbose, f"Storage state exists: {STORAGE_STATE.exists()}")
    return browser, context, page

def _accept_didomi(page, context, verbose: bool):
    # Exact button: #didomi-notice-agree-button
    try:
        btn = page.locator("#didomi-notice-agree-button").first
        if btn and btn.is_visible():
            _vprint(verbose, "Clicking Didomi consent…")
            btn.click(force=True, timeout=3000)
            page.wait_for_timeout(200)
    except Exception: pass
    # iframe fallback (some implementations)
    try:
        for f in page.frames:
            try:
                ib = f.locator("#didomi-notice-agree-button").first
                if ib and ib.is_visible():
                    _vprint(verbose, "Clicking Didomi in iframe…")
                    ib.click(force=True, timeout=3000)
                    page.wait_for_timeout(200)
                    break
            except Exception: continue
    except Exception: pass
    # persist
    try:
        context.storage_state(path=str(STORAGE_STATE))
        _vprint(verbose, f"Consent persisted → {STORAGE_STATE}")
    except Exception: pass

# -----------------------------
# DOM extractors (Playwright)
# -----------------------------
def _extract_name_dom(page) -> str:
    try:
        page.wait_for_selector(SEL_H1_ANY, timeout=6000)
        t = _clean(page.locator(SEL_H1_ANY).first.inner_text())
        if t: return t
    except Exception: pass
    try:
        return _clean(page.title().split("|")[0])
    except Exception:
        return "Unknown_Product"

def _extract_price_dom(page) -> Tuple[str, str]:
    # JSON-LD first
    try:
        blocks = page.locator("script[type='application/ld+json']")
        for i in range(blocks.count()):
            raw = blocks.nth(i).inner_text() or ""
            try:
                data = json.loads(raw)
            except Exception:
                try: data = json.loads(raw.strip().rstrip(","))
                except Exception: continue
            objs = data if isinstance(data, list) else [data]
            for obj in objs:
                if isinstance(obj, dict) and obj.get("@type") in ("Product",):
                    offers = obj.get("offers") or {}
                    if isinstance(offers, list): offers = offers[0] if offers else {}
                    p = offers.get("price"); curr = (offers.get("priceCurrency") or "").upper() or "SEK"
                    if p is not None:
                        pv = p if isinstance(p, str) else str(p).replace(",", ".")
                        return _clean(f"{pv} {curr}"), "jsonld"
    except Exception: pass
    # Visible text fallback
    try:
        body_txt = page.locator("body").inner_text(timeout=4000)
        parsed = _parse_price_text_block(body_txt)
        if parsed: return parsed, "onsite"
    except Exception: pass
    return "N/A", "none"

def _extract_stock_dom(page) -> Tuple[Optional[bool], Optional[str]]:
    # "In stock" / "I lager" etc.
    try:
        stock = page.get_by_text(re.compile(r"\bIn stock\b|\bI lager\b|\bFinns i lager\b", re.I))
        if stock.count() > 0 and stock.first.is_visible():
            return True, _clean(stock.first.inner_text())
    except Exception: pass
    try:
        oos = page.get_by_text(re.compile(r"slut i lager|tillf[aä]lligt slut|ej i lager", re.I))
        if oos.count() > 0 and oos.first.is_visible():
            return False, _clean(oos.first.inner_text())
    except Exception: pass
    # Add-to-cart heuristic (if present)
    try:
        btn = page.locator(SEL_ADD_TO_CART_BTN).first
        if btn and btn.is_visible():
            disabled = btn.get_attribute("disabled")
            aria_dis = btn.get_attribute("aria-disabled")
            if not disabled and (aria_dis in (None, "false")):
                return True, "In Stock"
    except Exception: pass
    return None, None

def _extract_desc_dom(page) -> str:
    # aria-labeled content region
    try:
        region = page.locator(SEL_DESC_ARIA).first
        if region and region.is_visible():
            return _clean_multiline(html.unescape(region.inner_text()))
    except Exception: pass
    # keyword fallback
    try:
        para = page.get_by_text(re.compile(r"Product description|Produktbeskrivning", re.I)).first
        if para and para.is_visible():
            return _clean_multiline(html.unescape(para.locator("xpath=..").inner_text()))
    except Exception: pass
    return ""

def _collect_images_dom(page, max_images: Optional[int]) -> List[str]:
    urls: List[str] = []
    try:
        thumbs = page.locator(SEL_TABLIST)
        cnt = min(thumbs.count(), max_images or 9999)
        for i in range(cnt):
            u = thumbs.nth(i).get_attribute("data-src") or thumbs.nth(i).get_attribute("src")
            if u: urls.append(u)
    except Exception: pass
    if not urls:
        try:
            tabs = page.locator("[role='tab']")
            n = min(tabs.count(), 6)
            for i in range(n):
                tabs.nth(i).click()
                page.wait_for_timeout(80)
                mains = page.locator(SEL_MAIN_IMG)
                mcnt = min(mains.count(), 3)
                for j in range(mcnt):
                    u = mains.nth(j).get_attribute("src")
                    if u: urls.append(u)
        except Exception: pass

    # Prefer non-thumbnail filenames if their base exists; keep order + de-dupe
    urls = [u for u in urls if u and u.startswith("http")]
    urls = _prefer_non_thumbnail(urls)
    urls = _dedupe_preserve_order(urls)
    if max_images is not None: urls = urls[:max_images]
    return urls

# -----------------------------
# HTTP/BS4 fast path
# -----------------------------
def _extract_from_html_bs4(html_text: str) -> Dict[str, str | List[str]]:
    soup = BeautifulSoup(html_text, "lxml")

    # name
    name = ""
    h1 = soup.select_one("h1")
    if h1: name = _clean(h1.get_text(" ", strip=True))
    if not name and soup.title:
        name = _clean(soup.title.get_text().split("|")[0])

    # price via JSON-LD
    price, price_source = "N/A", "none"
    for tag in soup.select("script[type='application/ld+json']"):
        raw = tag.string or tag.get_text()
        if not raw: continue
        try:
            data = json.loads(raw)
        except Exception:
            try: data = json.loads(raw.strip().rstrip(","))
            except Exception: continue
        objs = data if isinstance(data, list) else [data]
        done = False
        for obj in objs:
            if isinstance(obj, dict) and obj.get("@type") in ("Product",):
                offers = obj.get("offers") or {}
                if isinstance(offers, list): offers = offers[0] if offers else {}
                p = offers.get("price"); curr = (offers.get("priceCurrency") or "").upper() or "SEK"
                if p is not None:
                    pv = p if isinstance(p, str) else str(p).replace(",", ".")
                    price, price_source = _clean(f"{pv} {curr}"), "jsonld"; done = True; break
        if done: break

    if price_source == "none":
        body_txt = soup.get_text(" ", strip=True)
        maybe = _parse_price_text_block(body_txt)
        if maybe: price, price_source = maybe, "onsite"

    # description
    desc = ""
    region = soup.select_one("[aria-label*='Product description content' i], [aria-label*='Produktbeskrivning' i]")
    if region:
        desc = _clean_multiline(html.unescape(region.get_text("\n", strip=True)))
    else:
        candidates = soup.find_all(string=re.compile(r"Product description|Produktbeskrivning", re.I))
        if candidates:
            node = candidates[0].parent
            desc = _clean_multiline(html.unescape(node.get_text("\n", strip=True)))

    # images (SSR may already include)
    img_urls: List[str] = []
    for img in soup.select(f"{SEL_TABLIST}, {SEL_MAIN_IMG}"):
        src = img.get("data-src") or img.get("src")
        if src and src.startswith("http"):
            img_urls.append(src)
    img_urls = _prefer_non_thumbnail(img_urls)
    img_urls = _dedupe_preserve_order(img_urls)

    return {"name": name or "", "price": price, "price_source": price_source,
            "description": desc, "image_urls": img_urls}

# -----------------------------
# Downloads (with size probing + Referer)
# -----------------------------
def _download_one(session: requests.Session, url: str, out: Path, verbose: bool, referer: str | None) -> Optional[str]:
    # image-friendly headers + Referer for hotlink protection
    session.headers.update({
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    })
    if referer:
        session.headers["Referer"] = referer

    for candidate in _fyndiq_image_candidates(url):
        try:
            r = session.get(candidate, timeout=20)
            if r.status_code < 400 and r.content:
                ct = r.headers.get("content-type", "")
                ext = _ext_from_ct_or_url(ct, candidate)
                out_final = out.with_suffix(ext)
                out_final.write_bytes(r.content)
                _vprint(verbose, f"  ✓ {out_final.name}  ← {candidate}")
                return str(out_final)
            else:
                _vprint(verbose, f"  ! HTTP {r.status_code} {candidate}")
        except Exception as e:
            _vprint(verbose, f"  ! {candidate} error: {e}")
    return None

def _download_images_concurrent(img_urls: List[str], folder: Path, max_workers: int, verbose: bool, referer: str | None = None) -> List[str]:
    saved: List[str] = []
    _ensure_dir(folder)
    with requests.Session() as s:
        s.headers.update({"User-Agent": UA, "Accept-Language": ACCEPT_LANG})
        with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = []
            for idx, u in enumerate(img_urls, 1):
                out = folder / f"{idx:02d}"  # ext later
                futures.append(ex.submit(_download_one, s, u, out, verbose, referer))
            for f in cf.as_completed(futures):
                p = f.result()
                if p: saved.append(p)
    return saved

# -----------------------------
# Public API
# -----------------------------
def scrape_fyndiq(
    url: str,
    headless: bool = True,
    prefer_http: bool = True,
    render_fallback: bool = True,
    download_images: bool = False,
    max_images: Optional[int] = 12,
    max_image_workers: int = 6,
    verbose: bool = False,
) -> Dict:
    """
    Fast path (HTTP/BS4), then Playwright if critical fields are missing.
    Now includes invalid link detection.
    """
    _ensure_dir(DATA_DIR); _ensure_dir(DEBUG_DIR)
    result = {
        "url": url,
        "name": "",
        "price": "N/A",
        "price_source": "none",
        "in_stock": None,
        "stock_text": None,
        "description": "",
        "image_count": 0,
        "image_urls": [],
        "images_downloaded": [],
        "folder": "",
        "mode": "http",
        # Invalid link detection fields
        "listing_status": "active",
        "invalid_reason": None,
    }

    page_html = ""
    final_url = url
    http_status = None

    # ---------- Tier 1: HTTP ----------
    if prefer_http:
        try:
            with _requests_session() as s:
                r = s.get(url, timeout=15, allow_redirects=True)
                http_status = r.status_code
                final_url = r.url
                page_html = r.text
                
                # Check for invalid link FIRST
                is_invalid, invalid_reason, invalid_details = detect_invalid_link(
                    page_html, url, final_url, http_status, verbose
                )
                
                if is_invalid:
                    _vprint(verbose, f"[HTTP] Invalid link detected: {invalid_reason}")
                    result.update({
                        "listing_status": "invalid",
                        "invalid_reason": invalid_reason,
                        "name": "Invalid Link - Product Not Available",
                        "mode": "http",
                    })
                    return result
                
                r.raise_for_status()
                parsed = _extract_from_html_bs4(r.text)
                result.update({
                    "name": parsed["name"],
                    "price": parsed["price"],
                    "price_source": parsed["price_source"],
                    "description": parsed["description"],
                    "image_urls": parsed["image_urls"][: (max_images or 9999)]
                })
            # best-effort stock from HTML text
            txt = r.text
            if re.search(r"\bIn stock\b|\bI lager\b|\bFinns i lager\b", txt, re.I):
                result["in_stock"], result["stock_text"] = True, "In stock"
            elif re.search(r"slut i lager|tillf[aä]lligt slut|ej i lager", txt, re.I):
                result["in_stock"], result["stock_text"] = False, "Out of stock"
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                result.update({
                    "listing_status": "invalid",
                    "invalid_reason": "HTTP 404 - Product not found",
                    "name": "Invalid Link - Product Not Available",
                    "mode": "http",
                })
                return result
            _vprint(verbose, f"[HTTP] failed → {e}")
        except Exception as e:
            _vprint(verbose, f"[HTTP] failed → {e}")

    need_render = (
        (not result["name"]) or
        (result["price_source"] == "none") or
        (download_images and not result["image_urls"])
    )

    # ---------- Tier 2: Playwright ----------
    if (not prefer_http) or (need_render and render_fallback):
        try:
            with sync_playwright() as pw:
                browser, context, page = _prepare_context(pw, headless=headless, verbose=verbose)
                try:
                    _vprint(verbose, "[PW] Navigating …")
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=18000)
                    
                    http_status = resp.status if resp else None
                    final_url = page.url
                    
                    if not resp or not (200 <= resp.status <= 399):
                        _vprint(verbose, f"[PW] status {resp.status if resp else 'n/a'}")

                    _accept_didomi(page, context, verbose)

                    try: page.wait_for_selector(SEL_H1_ANY, timeout=7000)
                    except Exception: pass

                    # Get page content for invalid link detection
                    page_html = page.content()
                    
                    # Check for invalid link
                    is_invalid, invalid_reason, invalid_details = detect_invalid_link(
                        page_html, url, final_url, http_status, verbose
                    )
                    
                    if is_invalid:
                        _vprint(verbose, f"[PW] Invalid link detected: {invalid_reason}")
                        result.update({
                            "listing_status": "invalid",
                            "invalid_reason": invalid_reason,
                            "name": "Invalid Link - Product Not Available",
                            "mode": "render",
                        })
                        return result

                    name = _extract_name_dom(page)
                    price, price_source = _extract_price_dom(page)
                    in_stock, stock_text = _extract_stock_dom(page)
                    description = _extract_desc_dom(page)
                    image_urls = _collect_images_dom(page, max_images)

                    result.update({
                        "name": name or result["name"],
                        "price": price if price_source != "none" else result["price"],
                        "price_source": price_source if price_source != "none" else result["price_source"],
                        "in_stock": in_stock if in_stock is not None else result["in_stock"],
                        "stock_text": stock_text if stock_text else result["stock_text"],
                        "description": description if description else result["description"],
                        "image_urls": image_urls if image_urls else result["image_urls"],
                        "mode": "render"
                    })
                finally:
                    context.storage_state(path=str(STORAGE_STATE))
                    browser.close()
        except PlaywrightTimeoutError as e:
            ts = int(time.time())
            _ensure_dir(DEBUG_DIR)
            (DEBUG_DIR / f"fyndiq_timeout_{ts}.note").write_text(f"Timed out {url}", encoding="utf-8")
            raise e

    # ---------- Output & optional downloads ----------
    slug = "fyndiq"
    stable_id = _stable_id_from_url(url)
    folder = DATA_DIR / f"{slug}_{_safe_name(result['name'] or 'product')}_{_safe_name(stable_id)}"
    _ensure_dir(folder)
    result["folder"] = str(folder)

    if download_images and result["image_urls"]:
        _vprint(verbose, f"Downloading {len(result['image_urls'])} images …")
        saved = _download_images_concurrent(result["image_urls"], folder, max_image_workers, verbose, referer=url)
        result["images_downloaded"] = saved
        result["image_count"] = len(saved)
    else:
        result["image_count"] = len(result["image_urls"])

    return result


# -----------------------------
# Test Invalid Link Detection
# -----------------------------
def test_invalid_detection():
    """Test the invalid link detection with sample HTML snippets."""
    
    # Test 1: 404 page (clear error page, NO product indicators)
    html_404 = '''
    <!DOCTYPE html>
    <html>
    <head><title>404 - Fyndiq</title></head>
    <body>
    <div class="sc-71f18213-2 mttCo sc-fe1e7d1b-0 kkRyEz">
        <div class="sc-8db71312-0 hMLGxq">
            <h1 class="sc-bb81a56-0 zQxOM">Ooops! Sidan finns inte längre :(</h1>
            <img alt="404" src="image404.webp">
            <p>Av alla miljoner produkter vi har så hittade du till en sida som inte finns längre.</p>
            <a href="/"><span>Tillbaka till Startsidan</span></a>
        </div>
    </div>
    </body>
    </html>
    '''
    
    is_invalid, reason, details = detect_invalid_link(
        html_404, 
        "https://fyndiq.se/produkt/test-product-abc123/",
        verbose=True
    )
    print(f"\n=== Test 1: 404 Page ===")
    print(f"Is Invalid: {is_invalid}")
    print(f"Reason: {reason}")
    assert is_invalid, "Should detect 404 page"
    
    # Test 2: Category/listing page with pagination
    html_category = '''
    <nav role="navigation" aria-label="Paginering">
        <ul class="sc-86a6c4a0-0 iYteYv">
            <li><a aria-label="Gå till föregående sida" href="/category/"></a></li>
            <li><a aria-current="true" aria-label="Gå till sida 1" href="/category/">1</a></li>
            <li><a aria-label="Gå till sida 2" href="/category/?page=2">2</a></li>
            <li><a aria-label="Gå till nästa sida" href="/category/?page=2"></a></li>
        </ul>
    </nav>
    <div class="product-grid">
        <div data-testid="product-card">Product 1</div>
        <div data-testid="product-card">Product 2</div>
    </div>
    '''
    
    is_invalid, reason, details = detect_invalid_link(
        html_category,
        "https://fyndiq.se/produkt/test-product-xyz789/",
        "https://fyndiq.se/hemmet/kok/kastruller/",  # Redirected to category
        verbose=True
    )
    print(f"\n=== Test 2: Category Page ===")
    print(f"Is Invalid: {is_invalid}")
    print(f"Reason: {reason}")
    print(f"Details: {details}")
    assert is_invalid, "Should detect category page"
    
    # Test 3: Valid product page (HAS product indicators)
    html_product = '''
    <!DOCTYPE html>
    <html>
    <head><title>Test Product | Fyndiq</title></head>
    <body>
    <script type="application/ld+json">
    {"@type": "Product", "name": "Test Product", "offers": {"price": "199", "priceCurrency": "SEK"}}
    </script>
    <h1>Test Product</h1>
    <button data-cy="pdp-add-to-cart">Lägg i varukorg</button>
    <div aria-label="Produktbeskrivning">This is a great product.</div>
    <div data-testid="image-panel"><img src="product.jpg"></div>
    <span class="price">199 SEK</span>
    <footer>
        <a href="/">Tillbaka till Startsidan</a>
    </footer>
    </body>
    </html>
    '''
    
    is_invalid, reason, details = detect_invalid_link(
        html_product,
        "https://fyndiq.se/produkt/test-product-abc123/",
        verbose=True
    )
    print(f"\n=== Test 3: Valid Product Page ===")
    print(f"Is Invalid: {is_invalid}")
    print(f"Reason: {reason}")
    print(f"Details: {details}")
    assert not is_invalid, "Should recognize valid product page"
    
    # Test 4: Valid product page that might have "404" somewhere innocently
    html_product_with_noise = '''
    <!DOCTYPE html>
    <html>
    <body>
    <script type="application/ld+json">
    {"@type": "Product", "name": "Model X-404 Speaker", "offers": {"price": "299", "priceCurrency": "SEK"}}
    </script>
    <h1>Model X-404 Speaker</h1>
    <p>Sidan finns inte alltid uppdaterad med senaste info.</p>
    <button data-cy="pdp-add-to-cart">Lägg i varukorg</button>
    <span class="price">299 SEK</span>
    </body>
    </html>
    '''
    
    is_invalid, reason, details = detect_invalid_link(
        html_product_with_noise,
        "https://fyndiq.se/produkt/model-x-404-speaker/",
        verbose=True
    )
    print(f"\n=== Test 4: Product with '404' in name ===")
    print(f"Is Invalid: {is_invalid}")
    print(f"Reason: {reason}")
    assert not is_invalid, "Should NOT flag product with '404' in name"
    
    print("\n✅ All tests passed!")


# # -----------------------------
# # Simple VS Code runner
# # -----------------------------
# if __name__ == "__main__":
#     import sys
    
#     # Run tests if --test flag
#     if "--test" in sys.argv:
#         test_invalid_detection()
#         sys.exit(0)
    
#     # 1) Paste your product URL here:
#     URL = "https://fyndiq.se/produkt/non-stick-mjolkgrytan-16-cm-med-hallpip-laura-ashley-salviablad-induktionskompatibel-av-pendeford-gron-cd5d34b67f134e52/"

#     # 2) Tweak options if you like:
#     HEADLESS         = True          # set False to watch the browser
#     PREFER_HTTP      = True          # try fast BS4 first
#     RENDER_FALLBACK  = True          # use Playwright if needed
#     DOWNLOAD_IMAGES  = True          # True = save images
#     MAX_IMAGES       = 20            # cap images
#     WORKERS          = 6             # concurrent image downloads
#     VERBOSE          = True

#     data = scrape_fyndiq(
#         URL,
#         headless=HEADLESS,
#         prefer_http=PREFER_HTTP,
#         render_fallback=RENDER_FALLBACK,
#         download_images=DOWNLOAD_IMAGES,
#         max_images=MAX_IMAGES,
#         max_image_workers=WORKERS,
#         verbose=VERBOSE,
#     )

#     # Pretty print result
#     print(json.dumps(data, indent=2, ensure_ascii=False))