
# # woolworths_gallery_dl.py
# # Python 3.10+ | Playwright (sync)
# #
# # Install:
# #   pip install playwright
# #   playwright install

# import json
# import os
# import re
# import time
# import hashlib
# import html
# from pathlib import Path
# from typing import List, Optional, Dict, Tuple
# from urllib.parse import urlparse, urlsplit, urlunsplit, parse_qsl, urlencode

# from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# # -----------------------------
# # Config
# # -----------------------------
# UA = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
# )
# VIEWPORT = {"width": 1400, "height": 900}
# LOCALE = "en-AU"
# TIMEZONE = "Australia/Sydney"

# # Save next to this script (not the working directory)
# try:
#     SCRIPT_DIR = Path(__file__).resolve().parent
# except NameError:
#     # Fallback for REPL/Jupyter
#     SCRIPT_DIR = Path.cwd()

# DATA_DIR = SCRIPT_DIR / "data1"   # <- folder will be created if missing
# DEBUG_DIR = SCRIPT_DIR / "debug"

# ANTI_AUTOMATION_JS = r"""
# Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
# """

# # Woolworths selectors
# SEL_NAME    = "h1.product-title_component_product-title__azQKW"
# SEL_PRICE   = "div.product-price_component_price-lead__vlm8f"
# SEL_THUMBS  = "div.image-thumbnails_thumbnails__1iOKe img"  # gallery thumbs

# # stock selectors (robust)
# SEL_OOS_BADGE    = ".product-label_component_out-of-stock__s4JE4"
# SEL_LABELS_GROUP = ".product-labels-group_component_product-labels-group__xVBX2"

# # -----------------------------
# # Helpers
# # -----------------------------
# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "").strip())

# def _clean_multiline(s: str) -> str:
#     # keep line breaks roughly intact for readability
#     s = s.replace("\r\n", "\n").replace("\r", "\n")
#     s = re.sub(r"[ \t]+\n", "\n", s)
#     s = re.sub(r"\n{3,}", "\n\n", s)
#     return s.strip()

# def _safe_name(s: str) -> str:
#     s = _clean(s)
#     return re.sub(r"[^\w.\-]+", "_", s)[:120] or "product"

# def _slug_from_host(url: str) -> str:
#     try:
#         host = (urlparse(url).hostname or "site").replace("www.", "")
#         return host.split(".")[0]
#     except Exception:
#         return "site"

# def _stable_id_from_url(url: str) -> str:
#     try:
#         parts = urlsplit(url).path.strip("/").split("/")
#         if "productdetails" in parts:
#             i = parts.index("productdetails")
#             if i + 1 < len(parts) and parts[i + 1].isdigit():
#                 return parts[i + 1]
#         slug = os.path.splitext(os.path.basename(urlsplit(url).path.rstrip("/")))[0]
#         if slug:
#             return slug
#     except Exception:
#         pass
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

# def _ensure_dir(p: Path):
#     p.mkdir(parents=True, exist_ok=True)

# def _parse_money(s: str) -> Optional[str]:
#     s = _clean(s)
#     m = re.search(r"\$?\s?(\d[\d,]*)(?:\.(\d{2}))?", s)
#     if not m:
#         return None
#     dollars = m.group(1).replace(",", "")
#     cents = m.group(2) if m.group(2) is not None else "00"
#     return f"${dollars}.{cents}"

# def _strip_query(u: str) -> str:
#     sp = urlsplit(u)
#     return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

# def _base_no_ext(u: str) -> str:
#     sp = urlsplit(u)
#     root, _ext = os.path.splitext(sp.path)
#     return urlunsplit((sp.scheme, sp.netloc, root, "", ""))

# def _ext_from_content_type(ct: Optional[str], fallback: str = ".jpg") -> str:
#     ct = (ct or "").lower()
#     if "jpeg" in ct or "jpg" in ct: return ".jpg"
#     if "png" in ct:  return ".png"
#     if "webp" in ct: return ".webp"
#     if "gif" in ct:  return ".gif"
#     return fallback

# def _upgrade_thumb_to_hires(u: str, size: int = 600) -> str:
#     """
#     Thumb example:
#       https://assets.woolworths.com.au/images/1005/1123128555_4.jpg?impolicy=wowsmkqiema&w=46&h=46
#     Hi-res target:
#       ... same URL with w=600&h=600 (keeps impolicy)
#     """
#     sp = urlsplit(u)
#     q = dict(parse_qsl(sp.query, keep_blank_values=True))
#     q["w"] = str(size)
#     q["h"] = str(size)
#     return sp._replace(query=urlencode(q, doseq=True)).geturl()

# def _dedupe_preserve_order(urls: List[str]) -> List[str]:
#     """Deduplicate by slide (drop query and extension) but keep DOM order."""
#     seen: set = set()
#     out: List[str] = []
#     for u in urls:
#         key = _base_no_ext(u)
#         if key in seen:
#             continue
#         seen.add(key)
#         out.append(u)
#     return out

# # -----------------------------
# # Extraction helpers
# # -----------------------------
# def _extract_name(page) -> str:
#     try:
#         return _clean(page.locator(SEL_NAME).inner_text(timeout=8000))
#     except Exception:
#         return "Unknown_Product"

# def _extract_price(page) -> Tuple[str, str]:
#     try:
#         raw = page.locator(SEL_PRICE).inner_text(timeout=5000)
#         money = _parse_money(raw)
#         return (money, "onsite") if money else ("N/A", "none")
#     except Exception:
#         return "N/A", "none"

# def _expand_and_extract_description(page) -> str:
#     """
#     Click the “Product details” accordion using its aria-controls, then read the
#     exact region. Falls back gracefully if already expanded.
#     """
#     # 1) Find the button by accessible name (case-insensitive)
#     btn = None
#     try:
#         cand = page.get_by_role("button", name=re.compile(r"product\s*details", re.I))
#         if cand.count() > 0:
#             btn = cand.first
#     except Exception:
#         pass

#     # 2) If not found, try a CSS fallback for any accordion trigger that contains the text
#     if btn is None:
#         try:
#             cand2 = page.locator("button.accordion_core-accordion-trigger__bdEc2")
#             # find the one whose text includes "Product details"
#             count = cand2.count()
#             for i in range(count):
#                 t = cand2.nth(i).inner_text().strip().lower()
#                 if "product details" in t:
#                     btn = cand2.nth(i)
#                     break
#         except Exception:
#             pass

#     # 3) If we found a button, open it (if not already)
#     region_sel = None
#     if btn is not None:
#         controls_id = btn.get_attribute("aria-controls")
#         expanded = (btn.get_attribute("aria-expanded") or "false").lower()
#         if expanded == "false":
#             try:
#                 btn.click()
#                 page.wait_for_timeout(250)
#             except Exception:
#                 pass
#         if controls_id:
#             region_sel = f"#{controls_id} .text_component_text__ErEDp"

#     # 4) Preferred read: the exact region under aria-controls
#     if region_sel:
#         try:
#             page.wait_for_selector(region_sel, timeout=8000)
#             # inner_text keeps human-readable layout; html.unescape fixes &amp; etc.
#             text = page.locator(region_sel).inner_text()
#             return _clean_multiline(html.unescape(text))
#         except Exception:
#             pass

#     # 5) Fallback: any accordion content block (already expanded)
#     try:
#         fallback_sel = "div[id^='accordion-'][id$='-content'] .text_component_text__ErEDp"
#         page.wait_for_selector(fallback_sel, timeout=8000)
#         text = page.locator(fallback_sel).first.inner_text()
#         return _clean_multiline(html.unescape(text))
#     except Exception:
#         return ""

# def _extract_stock(page) -> Tuple[Optional[bool], Optional[str]]:
#     """
#     Determine stock by:
#       - explicit Out of Stock badge
#       - presence of Add to trolley/cart button
#       - 'Unavailable' style labels
#     """
#     # Out of stock badge
#     try:
#         oos = page.locator(SEL_OOS_BADGE)
#         if oos.count() > 0 and oos.first.is_visible():
#             return (False, _clean(oos.first.inner_text()))
#     except Exception:
#         pass

#     # Add to trolley/cart button = in stock
#     try:
#         add_btn = page.get_by_role("button", name=re.compile(r"add\s+to\s+(trolley|cart)", re.I))
#         if add_btn.count() > 0 and add_btn.first.is_enabled() and add_btn.first.is_visible():
#             return (True, "In Stock")
#     except Exception:
#         pass

#     # Any label that says Unavailable / Temporarily unavailable
#     try:
#         grp = page.locator(SEL_LABELS_GROUP)
#         if grp.count() > 0:
#             text = grp.first.inner_text().lower()
#             if "unavailable" in text:
#                 return (False, _clean(grp.first.inner_text()))
#     except Exception:
#         pass

#     return (None, None)

# def _get_all_thumb_urls(page) -> List[str]:
#     """Read ALL thumbnails inside the gallery container."""
#     try:
#         page.wait_for_selector(SEL_THUMBS, timeout=12000)
#         urls = page.locator(SEL_THUMBS).evaluate_all("els => els.map(e => e.src)")
#         return [u for u in urls if isinstance(u, str) and u]
#     except Exception:
#         return []

# # -----------------------------
# # Playwright bootstrap
# # -----------------------------
# def _prepare_context(pw, headless: bool):
#     print("Launching real Chrome browser to avoid detection...")
#     browser = pw.chromium.launch(channel="chrome", headless=headless)
#     context = browser.new_context(
#         user_agent=UA,
#         locale=LOCALE,
#         timezone_id=TIMEZONE,
#         viewport=VIEWPORT,
#         java_script_enabled=True,
#         accept_downloads=False,
#     )
#     context.add_init_script(ANTI_AUTOMATION_JS)
#     page = context.new_page()
#     return browser, context, page

# # -----------------------------
# # Scraper
# # -----------------------------
# def scrape_product(url: str, headless: bool = True, size: int = 600, max_images: Optional[int] = None) -> dict:
#     slug = _slug_from_host(url)
#     stable_id = _stable_id_from_url(url)

#     with sync_playwright() as pw:
#         browser, context, page = _prepare_context(pw, headless=headless)

#         result = {
#             "url": url,
#             "name": "",
#             "price": "N/A",
#             "price_source": "none",
#             "in_stock": None,
#             "stock_text": None,
#             "description": "",
#             "image_count": 0,
#             "image_urls": [],
#             "images_downloaded": [],
#             "folder": "",
#         }

#         try:
#             print(f"Navigating to {url}...")
#             page.goto(url, wait_until="load", timeout=45000)

#             print("Waiting for product content...")
#             page.wait_for_selector(SEL_NAME, timeout=25000)

#             # Core fields
#             name = _extract_name(page)
#             price, price_source = _extract_price(page)

#             # Stock & Description (robust)
#             in_stock, stock_text = _extract_stock(page)
#             description = _expand_and_extract_description(page)

#             # Collect dynamic gallery (ALL slides, deduped by slide)
#             thumb_urls = _get_all_thumb_urls(page)
#             thumb_urls = _dedupe_preserve_order(thumb_urls)

#             hires_all = [_upgrade_thumb_to_hires(u, size=size) for u in thumb_urls]
#             if max_images is not None:
#                 hires_all = hires_all[:max_images]

#             # Prepare output folder
#             _ensure_dir(DATA_DIR)
#             folder_name = f"{slug}_{_safe_name(name)}_{stable_id}"
#             folder_path = DATA_DIR / folder_name
#             _ensure_dir(folder_path)

#             # Download with browser context (keeps site cookies; avoids 403)
#             saved_paths: List[str] = []
#             for idx, img_url in enumerate(hires_all, start=1):
#                 try:
#                     resp = context.request.get(img_url)
#                     if resp.ok:
#                         body = resp.body()
#                         ct = resp.headers.get("content-type")
#                         ext = _ext_from_content_type(ct, ".jpg")
#                         out = folder_path / f"{idx:02d}{ext}"
#                         out.write_bytes(body)
#                         saved_paths.append(str(out))
#                     else:
#                         print(f"Warning: HTTP {resp.status} for {img_url}")
#                 except Exception as e:
#                     print(f"Download error for {img_url}: {e}")

#             result.update({
#                 "name": name,
#                 "price": price,
#                 "price_source": price_source,
#                 "in_stock": in_stock,
#                 "stock_text": stock_text,
#                 "description": description,
#                 "image_count": len(saved_paths),
#                 "image_urls": hires_all,
#                 "images_downloaded": saved_paths,
#                 "folder": str(folder_path),
#             })
#             return result

#         except PlaywrightTimeoutError as e:
#             print("\n" + "=" * 50)
#             print("CRITICAL ERROR: Timed out waiting for page content.")
#             _ensure_dir(DEBUG_DIR)
#             screenshot_path = DEBUG_DIR / f"blocked_page_{int(time.time())}.png"
#             html_path = DEBUG_DIR / f"blocked_page_{int(time.time())}.html"
#             page.screenshot(path=screenshot_path)
#             html_path.write_text(page.content(), encoding="utf-8")
#             print(f"Debug saved. See screenshot: {screenshot_path}")
#             print("=" * 50 + "\n")
#             raise e
#         finally:
#             print("Closing browser.")
#             browser.close()

# # -----------------------------
# # CLI demo
# # -----------------------------
# if __name__ == "__main__":
#     URL = "https://www.woolworths.com.au/shop/productdetails/1123128555/laura-ashley-1-7l-dome-kettle-elveden-blue-ladken"
#     data = scrape_product(URL, headless=True, size=600, max_images=None)  # None => ALL gallery slides
#     print("\n--- SCRAPED DATA ---")
#     print(json.dumps(data, indent=2, ensure_ascii=False))




# # woolworths_gallery_dl.py
# # Python 3.10+ | Playwright (sync)
# #
# # Install:
# #   pip install playwright
# #   playwright install

# import json
# import os
# import re
# import time
# import hashlib
# import html
# from pathlib import Path
# from typing import List, Optional, Tuple
# from urllib.parse import urlparse, urlsplit, urlunsplit, parse_qsl, urlencode

# from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# # -----------------------------
# # Config
# # -----------------------------
# UA = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
# )
# VIEWPORT = {"width": 1400, "height": 900}
# LOCALE = "en-AU"
# TIMEZONE = "Australia/Sydney"

# # Save next to this script (not the working directory)
# try:
#     SCRIPT_DIR = Path(__file__).resolve().parent
# except NameError:
#     # Fallback for REPL/Jupyter
#     SCRIPT_DIR = Path.cwd()

# DATA_DIR = SCRIPT_DIR / "data1"   # <- will be created if missing
# DEBUG_DIR = SCRIPT_DIR / "debug"

# ANTI_AUTOMATION_JS = r"""
# Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
# """

# # Woolworths selectors
# SEL_NAME    = "h1.product-title_component_product-title__azQKW"
# SEL_PRICE   = "div.product-price_component_price-lead__vlm8f"
# SEL_THUMBS  = "div.image-thumbnails_thumbnails__1iOKe img"  # gallery thumbs

# # stock selectors (robust)
# SEL_OUS_BADGE    = ".product-label_component_out-of-stock__s4JE4"
# SEL_LABELS_GROUP = ".product-labels-group_component_product-labels-group__xVBX2"

# # -----------------------------
# # Small utils
# # -----------------------------
# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "").strip())

# def _clean_multiline(s: str) -> str:
#     s = s.replace("\r\n", "\n").replace("\r", "\n")
#     s = re.sub(r"[ \t]+\n", "\n", s)
#     s = re.sub(r"\n{3,}", "\n\n", s)
#     return s.strip()

# def _safe_name(s: str) -> str:
#     s = _clean(s)
#     return re.sub(r"[^\w.\-]+", "_", s)[:120] or "product"

# def _slug_from_host(url: str) -> str:
#     try:
#         host = (urlparse(url).hostname or "site").replace("www.", "")
#         return host.split(".")[0]
#     except Exception:
#         return "site"

# def _stable_id_from_url(url: str) -> str:
#     try:
#         parts = urlsplit(url).path.strip("/").split("/")
#         if "productdetails" in parts:
#             i = parts.index("productdetails")
#             if i + 1 < len(parts) and parts[i + 1].isdigit():
#                 return parts[i + 1]
#         slug = os.path.splitext(os.path.basename(urlsplit(url).path.rstrip("/")))[0]
#         if slug:
#             return slug
#     except Exception:
#         pass
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

# def _ensure_dir(p: Path):
#     p.mkdir(parents=True, exist_ok=True)

# def _parse_money(s: str) -> Optional[str]:
#     s = _clean(s)
#     m = re.search(r"\$?\s?(\d[\d,]*)(?:\.(\d{2}))?", s)
#     if not m:
#         return None
#     dollars = m.group(1).replace(",", "")
#     cents = m.group(2) if m.group(2) is not None else "00"
#     return f"${dollars}.{cents}"

# def _strip_query(u: str) -> str:
#     sp = urlsplit(u)
#     return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

# def _base_no_ext(u: str) -> str:
#     sp = urlsplit(u)
#     root, _ext = os.path.splitext(sp.path)
#     return urlunsplit((sp.scheme, sp.netloc, root, "", ""))

# def _ext_from_content_type(ct: Optional[str], fallback: str = ".jpg") -> str:
#     ct = (ct or "").lower()
#     if "jpeg" in ct or "jpg" in ct: return ".jpg"
#     if "png" in ct:  return ".png"
#     if "webp" in ct: return ".webp"
#     if "gif" in ct:  return ".gif"
#     return fallback

# def _upgrade_thumb_to_hires(u: str, size: int = 600) -> str:
#     sp = urlsplit(u)
#     q = dict(parse_qsl(sp.query, keep_blank_values=True))
#     q["w"] = str(size)
#     q["h"] = str(size)
#     return sp._replace(query=urlencode(q, doseq=True)).geturl()

# def _dedupe_preserve_order(urls: List[str]) -> List[str]:
#     seen: set = set()
#     out: List[str] = []
#     for u in urls:
#         key = _base_no_ext(u)
#         if key in seen:
#             continue
#         seen.add(key)
#         out.append(u)
#     return out

# # -----------------------------
# # Extraction helpers
# # -----------------------------
# def _extract_name(page) -> str:
#     try:
#         return _clean(page.locator(SEL_NAME).inner_text(timeout=8000))
#     except Exception:
#         return "Unknown_Product"

# def _extract_price(page) -> Tuple[str, str]:
#     try:
#         raw = page.locator(SEL_PRICE).inner_text(timeout=5000)
#         money = _parse_money(raw)
#         return (money, "onsite") if money else ("N/A", "none")
#     except Exception:
#         return "N/A", "none"

# def _expand_and_extract_description(page) -> str:
#     # Find the Product details button by accessible name
#     btn = None
#     try:
#         cand = page.get_by_role("button", name=re.compile(r"product\s*details", re.I))
#         if cand.count() > 0:
#             btn = cand.first
#     except Exception:
#         pass

#     if btn is None:
#         # CSS fallback
#         try:
#             cand2 = page.locator("button.accordion_core-accordion-trigger__bdEc2")
#             count = cand2.count()
#             for i in range(count):
#                 t = cand2.nth(i).inner_text().strip().lower()
#                 if "product details" in t:
#                     btn = cand2.nth(i)
#                     break
#         except Exception:
#             pass

#     region_sel = None
#     if btn is not None:
#         controls_id = btn.get_attribute("aria-controls")
#         expanded = (btn.get_attribute("aria-expanded") or "false").lower()
#         if expanded == "false":
#             try:
#                 btn.click()
#                 page.wait_for_timeout(250)
#             except Exception:
#                 pass
#         if controls_id:
#             region_sel = f"#{controls_id} .text_component_text__ErEDp"

#     if region_sel:
#         try:
#             page.wait_for_selector(region_sel, timeout=8000)
#             text = page.locator(region_sel).inner_text()
#             return _clean_multiline(html.unescape(text))
#         except Exception:
#             pass

#     try:
#         fallback_sel = "div[id^='accordion-'][id$='-content'] .text_component_text__ErEDp"
#         page.wait_for_selector(fallback_sel, timeout=8000)
#         text = page.locator(fallback_sel).first.inner_text()
#         return _clean_multiline(html.unescape(text))
#     except Exception:
#         return ""

# def _extract_stock(page) -> Tuple[Optional[bool], Optional[str]]:
#     try:
#         oos = page.locator(SEL_OUS_BADGE)
#         if oos.count() > 0 and oos.first.is_visible():
#             return (False, _clean(oos.first.inner_text()))
#     except Exception:
#         pass

#     try:
#         add_btn = page.get_by_role("button", name=re.compile(r"add\s+to\s+(trolley|cart)", re.I))
#         if add_btn.count() > 0 and add_btn.first.is_enabled() and add_btn.first.is_visible():
#             return (True, "In Stock")
#     except Exception:
#         pass

#     try:
#         grp = page.locator(SEL_LABELS_GROUP)
#         if grp.count() > 0:
#             text = grp.first.inner_text().lower()
#             if "unavailable" in text:
#                 return (False, _clean(grp.first.inner_text()))
#     except Exception:
#         pass

#     return (None, None)

# def _get_all_thumb_urls(page) -> List[str]:
#     try:
#         page.wait_for_selector(SEL_THUMBS, timeout=12000)
#         urls = page.locator(SEL_THUMBS).evaluate_all("els => els.map(e => e.src)")
#         return [u for u in urls if isinstance(u, str) and u]
#     except Exception:
#         return []

# # -----------------------------
# # Playwright bootstrap
# # -----------------------------
# def _prepare_context(pw, headless: bool):
#     browser = pw.chromium.launch(channel="chrome", headless=headless)
#     context = browser.new_context(
#         user_agent=UA,
#         locale=LOCALE,
#         timezone_id=TIMEZONE,
#         viewport=VIEWPORT,
#         java_script_enabled=True,
#         accept_downloads=False,
#     )
#     context.add_init_script(ANTI_AUTOMATION_JS)
#     page = context.new_page()
#     return browser, context, page

# # -----------------------------
# # Scraper (with verbose switch)
# # -----------------------------
# def scrape_product(
#     url: str,
#     headless: bool = True,
#     size: int = 600,
#     max_images: Optional[int] = None,
#     verbose: bool = True,
# ) -> dict:

#     # simple logger
#     def log(msg: str):
#         if verbose:
#             print(msg)

#     slug = _slug_from_host(url)
#     stable_id = _stable_id_from_url(url)

#     with sync_playwright() as pw:
#         browser, context, page = _prepare_context(pw, headless=headless)

#         result = {
#             "url": url,
#             "name": "",
#             "price": "N/A",
#             "price_source": "none",
#             "in_stock": None,
#             "stock_text": None,
#             "description": "",
#             "image_count": 0,
#             "image_urls": [],
#             "images_downloaded": [],
#             "folder": "",
#         }

#         try:
#             log("Launching real Chrome browser to avoid detection...")
#             log(f"Navigating to {url}...")
#             page.goto(url, wait_until="load", timeout=45000)

#             log("Waiting for product content...")
#             page.wait_for_selector(SEL_NAME, timeout=25000)

#             name = _extract_name(page)
#             price, price_source = _extract_price(page)
#             in_stock, stock_text = _extract_stock(page)
#             description = _expand_and_extract_description(page)

#             thumb_urls = _get_all_thumb_urls(page)
#             thumb_urls = _dedupe_preserve_order(thumb_urls)

#             hires_all = [_upgrade_thumb_to_hires(u, size=size) for u in thumb_urls]
#             if max_images is not None:
#                 hires_all = hires_all[:max_images]

#             _ensure_dir(DATA_DIR)
#             folder_name = f"{slug}_{_safe_name(name)}_{stable_id}"
#             folder_path = DATA_DIR / folder_name
#             _ensure_dir(folder_path)
#             log(f"Saving images to: {folder_path}")

#             saved_paths: List[str] = []
#             for idx, img_url in enumerate(hires_all, start=1):
#                 try:
#                     resp = context.request.get(img_url)
#                     if resp.ok:
#                         body = resp.body()
#                         ct = resp.headers.get("content-type")
#                         ext = _ext_from_content_type(ct, ".jpg")
#                         out = folder_path / f"{idx:02d}{ext}"
#                         out.write_bytes(body)
#                         saved_paths.append(str(out))
#                         log(f"Saved [{resp.status}] {img_url} -> {out}")
#                     else:
#                         log(f"Warning: HTTP {resp.status} for {img_url}")
#                 except Exception as e:
#                     log(f"Download error for {img_url}: {e}")

#             result.update({
#                 "name": name,
#                 "price": price,
#                 "price_source": price_source,
#                 "in_stock": in_stock,
#                 "stock_text": stock_text,
#                 "description": description,
#                 "image_count": len(saved_paths),
#                 "image_urls": hires_all,
#                 "images_downloaded": saved_paths,
#                 "folder": str(folder_path),
#             })
#             return result

#         except PlaywrightTimeoutError as e:
#             _ensure_dir(DEBUG_DIR)
#             screenshot_path = DEBUG_DIR / f"blocked_page_{int(time.time())}.png"
#             html_path = DEBUG_DIR / f"blocked_page_{int(time.time())}.html"
#             try:
#                 page.screenshot(path=screenshot_path)
#                 html_path.write_text(page.content(), encoding="utf-8")
#             except Exception:
#                 pass
#             log("\n" + "=" * 50)
#             log("CRITICAL ERROR: Timed out waiting for page content.")
#             log(f"Debug saved. See screenshot: {screenshot_path}")
#             log("=" * 50 + "\n")
#             raise e
#         finally:
#             log("Closing browser.")
#             browser.close()

# # -----------------------------
# # CLI demo
# # -----------------------------
# if __name__ == "__main__":
#     URL = "https://www.woolworths.com.au/shop/productdetails/1119132395/laura-ashley-china-rose-2-slice-toaster-w-7-heat-settings-lat2cr"
#     data = scrape_product(
#         URL,
#         headless=True,
#         size=600,
#         max_images=None,   # None => ALL gallery slides
#         verbose=False      # <-- toggle this to False to silence prints
#     )
#     print("\n--- SCRAPED DATA ---")
#     print(json.dumps(data, indent=2, ensure_ascii=False))




# -*- coding: utf-8 -*-
# woolworths_wsapi.py — Oxylabs WSAPI scraper for Woolworths PDP
# Python 3.10+ | pip install requests beautifulsoup4 lxml certifi

from __future__ import annotations
import json, os, re, time, hashlib, html
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from urllib.parse import urlparse, urlsplit, urlunsplit, parse_qsl, urlencode, urldefrag

import requests
import certifi
from bs4 import BeautifulSoup

# -----------------------------
# Config / Secrets
# -----------------------------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = os.getenv("OXY_USER")
    OXY_PASS = os.getenv("OXY_PASS")

if not (OXY_USER and OXY_PASS):
    raise RuntimeError("Missing Oxylabs credentials. Provide oxylabs_secrets.py or OXY_USER/OXY_PASS env vars.")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
ACCEPT_LANG = "en-AU,en;q=0.9"
WSAPI_URL = "https://realtime.oxylabs.io/v1/queries"
GEO = "Australia"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data1"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Woolworths selectors (classnames change occasionally; keep heuristics as fallback)
SEL_NAME    = "h1.product-title_component_product-title__azQKW"
SEL_PRICE   = "div.product-price_component_price-lead__vlm8f"
SEL_THUMBS  = "div.image-thumbnails_thumbnails__1iOKe img"

SEL_OOS_BADGE    = ".product-label_component_out-of-stock__s4JE4"
SEL_LABELS_GROUP = ".product-labels-group_component_product-labels-group__xVBX2"

# -----------------------------
# Small utils
# -----------------------------
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

def _slug_from_host(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "site").replace("www.", "")
        return host.split(".")[0]
    except Exception:
        return "site"

def _stable_id_from_url(url: str) -> str:
    try:
        parts = urlsplit(url).path.strip("/").split("/")
        if "productdetails" in parts:
            i = parts.index("productdetails")
            if i + 1 < len(parts) and parts[i + 1].isdigit():
                return parts[i + 1]
        slug = os.path.splitext(os.path.basename(urlsplit(url).path.rstrip("/")))[0]
        if slug:
            return slug
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

def _parse_money(s: str) -> Optional[str]:
    s = _clean(s)
    m = re.search(r"\$?\s?(\d[\d,]*)(?:\.(\d{2}))?", s)
    if not m:
        return None
    dollars = m.group(1).replace(",", "")
    cents = m.group(2) if m.group(2) is not None else "00"
    return f"${dollars}.{cents}"

def _strip_query(u: str) -> str:
    sp = urlsplit(u)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

def _base_no_ext(u: str) -> str:
    sp = urlsplit(u)
    root, _ext = os.path.splitext(sp.path)
    return urlunsplit((sp.scheme, sp.netloc, root, "", ""))

def _dedupe_preserve_order(urls: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for u in urls:
        key = _base_no_ext(u)
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out

def _upgrade_thumb_to_hires(u: str, size: int = 600) -> str:
    sp = urlsplit(u)
    q = dict(parse_qsl(sp.query, keep_blank_values=True))
    q["w"] = str(size)
    q["h"] = str(size)
    return sp._replace(query=urlencode(q, doseq=True)).geturl()

# -----------------------------
# WSAPI core
# -----------------------------
def _wsapi_request(payload: dict, timeout: int = 120) -> dict:
    r = requests.post(
        WSAPI_URL,
        auth=(OXY_USER, OXY_PASS),
        json=payload,
        timeout=timeout,
        verify=certifi.where(),  # proper TLS verification
    )
    if 400 <= r.status_code < 500:
        try:
            err = r.json()
        except Exception:
            err = {"message": r.text}
        raise requests.HTTPError(f"{r.status_code} from WSAPI: {err}", response=r)
    r.raise_for_status()
    return r.json()

def _wsapi_get_html(url: str, browser_instructions: Optional[list] = None) -> str:
    payload = {
        "source": "universal",
        "url": url,
        "user_agent_type": "desktop_chrome",
        "geo_location": GEO,
        "render": "html",          # execute JS
        "parse": False,            # we parse locally
    }
    if browser_instructions:
        payload["browser_instructions"] = browser_instructions
    data = _wsapi_request(payload)
    res = (data.get("results") or [{}])[0]
    html_text = (
        res.get("rendered_html")
        or res.get("content")
        or (res.get("response") or {}).get("body")
        or ""
    )
    return html_text or ""

# -----------------------------
# DOM parse helpers (BeautifulSoup)
# -----------------------------
def _extract_name(soup: BeautifulSoup) -> str:
    el = soup.select_one(SEL_NAME) or soup.select_one("h1")
    return _clean(el.get_text(" ", strip=True)) if el else "Unknown_Product"

def _detect_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], Optional[str]]:
    oos = soup.select_one(SEL_OOS_BADGE)
    if oos and oos.get_text(strip=True):
        return False, _clean(oos.get_text(" ", strip=True))
    grp = soup.select_one(SEL_LABELS_GROUP)
    if grp:
        txt = _clean(grp.get_text(" ", strip=True)).lower()
        if any(w in txt for w in ["out of stock", "unavailable", "sold out"]):
            return False, _clean(grp.get_text(" ", strip=True))
    bodytxt = _clean(soup.get_text(" ", strip=True)).lower()
    if re.search(r"\badd\s+to\s+(trolley|cart)\b", bodytxt):
        return True, "In Stock"
    return None, None

def _extract_price_if_instock(soup: BeautifulSoup, in_stock: Optional[bool]) -> Tuple[str, str]:
    # If NOT in stock ⇒ price must be N/A (your rule)
    if in_stock is False:
        return "N/A", "none"
    el = soup.select_one(SEL_PRICE)
    if el:
        money = _parse_money(el.get_text(" ", strip=True))
        if money:
            return money, "onsite"
    bodytxt = _clean(soup.get_text(" ", strip=True))
    money = _parse_money(bodytxt)
    if money:
        return money, "heuristic"
    return "N/A", "none"

def _expand_and_extract_description(soup: BeautifulSoup) -> str:
    for sel in [
        "div[id^='accordion-'][id$='-content'] .text_component_text__ErEDp",
        "section[aria-labelledby*='product-details'] .text_component_text__ErEDp",
        "div[data-testid='product-details']",
    ]:
        node = soup.select_one(sel)
        if node:
            t = _clean_multiline(html.unescape(node.get_text("\n", strip=True)))
            if t:
                return t
    body = _clean_multiline(soup.get_text("\n", strip=True))
    m = re.search(r"(Product details.*)", body, flags=re.I | re.S)
    if m:
        return _clean_multiline(m.group(1))[:4000]
    return ""

def _collect_image_urls(soup: BeautifulSoup, page_url: str, size: int = 600, max_images: Optional[int] = None) -> List[str]:
    thumbs = []
    for img in soup.select(SEL_THUMBS):
        src = (img.get("src") or "").strip()
        if src:
            thumbs.append(src)
    thumbs = _dedupe_preserve_order(thumbs)
    hires = [_upgrade_thumb_to_hires(u, size=size) for u in thumbs]
    if max_images is not None:
        hires = hires[:max_images]
    return hires

# -----------------------------
# Image downloads (direct; no proxy needed)
# -----------------------------
def _ext_from_content_type(ct: Optional[str], fallback: str = ".jpg") -> str:
    ct = (ct or "").lower()
    if "jpeg" in ct or "jpg" in ct: return ".jpg"
    if "png"  in ct: return ".png"
    if "webp" in ct: return ".webp"
    if "gif"  in ct: return ".gif"
    return fallback

def _download_images(urls: List[str], folder: Path, referer: str) -> List[str]:
    saved = []
    headers = {
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Referer": referer,
    }
    for i, u in enumerate(urls, 1):
        try:
            with requests.get(u, headers=headers, timeout=45, stream=True, verify=certifi.where()) as r:
                ct = (r.headers.get("Content-Type") or "").lower()
                if r.status_code == 200 and (ct.startswith("image/") or r.content):
                    ext = _ext_from_content_type(ct, ".jpg")
                    out = folder / f"{i:02d}{ext}"
                    with open(out, "wb") as f:
                        for chunk in r.iter_content(65536):
                            if chunk:
                                f.write(chunk)
                    saved.append(str(out))
        except Exception:
            pass
    return saved

# -----------------------------
# Scraper entry
# -----------------------------
def scrape_woolworths(url: str,
                      img_size: int = 600,
                      max_images: Optional[int] = None,
                      download_images_flag: bool = True) -> Dict:
    url, _ = urldefrag(url)
    slug = _slug_from_host(url)
    stable_id = _stable_id_from_url(url)

    # All waits are INTEGERS, and selectors are proper dicts (SelectorSchema)
    browser_instructions = [
        {"type": "wait", "wait_time_s": 1},
        # Try clicking a button/tab that reveals "Product details" region
        {"type": "click", "selector": {"type": "xpath", "value": "//button[contains(., 'Product details') or contains(., 'Product Details')]" }},
        {"type": "wait", "wait_time_s": 1},
        # Fallback generic accordion trigger classes
        {"type": "click", "selector": {"type": "css", "value": "button[class*='accordion_'][class*='trigger']" }},
        {"type": "wait", "wait_time_s": 1},
        # Scroll a bit to ensure gallery thumbs mount
        {"type": "scroll", "x": 0, "y": 1000},
        {"type": "wait", "wait_time_s": 1},
    ]

    html_text = _wsapi_get_html(url, browser_instructions=browser_instructions)
    if not html_text or "<" not in html_text:
        # fallback without BI
        html_text = _wsapi_get_html(url)

    soup = BeautifulSoup(html_text or "", "lxml")

    name = _extract_name(soup)
    in_stock, stock_text = _detect_stock(soup)                       # detect stock FIRST
    price, price_source = _extract_price_if_instock(soup, in_stock)  # apply OOS→N/A rule

    description = _expand_and_extract_description(soup)
    image_urls = _collect_image_urls(soup, url, size=img_size, max_images=max_images)

    folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}_{time.strftime('%Y%m%d-%H%M%S')}"
    folder.mkdir(parents=True, exist_ok=True)

    images_saved: List[str] = []
    if download_images_flag and image_urls:
        images_saved = _download_images(image_urls, folder, referer=url)

    return {
        "url": url,
        "name": name,
        "price": price,
        "price_source": price_source,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_count": len(images_saved) if images_saved else len(image_urls),
        "image_urls": image_urls,
        "images": images_saved,
        "folder": str(folder),
        "mode": "wsapi (render+browser_instructions)",
        "timestamp_utc": time.strftime("%Y%m%d-%H%M%S"),
    }

# # -----------------------------
# # CLI
# # -----------------------------
# if __name__ == "__main__":
#     URL = "https://www.woolworths.com.au/shop/productdetails/1119132395/laura-ashley-china-rose-2-slice-toaster-w-7-heat-settings-lat2cr"
#     result = scrape_woolworths(URL, img_size=600, max_images=None, download_images_flag=True)
#     print(json.dumps(result, indent=2, ensure_ascii=False))
