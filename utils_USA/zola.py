# # zola.py
# # Python 3.13
# # Stdlib + Playwright (sync)
# #
# # Scrapes Zola product pages like:
# #   https://www.zola.com/shop/product/lauraashley_jug_kettle
# #
# # Return format (exact keys):
# # {
# #   "name": str,
# #   "price": str | "N/A",
# #   "price_source": str | "none",
# #   "in_stock": true | false | null,
# #   "stock_text": str,
# #   "description": str,
# #   "image_count": int,
# #   "images": [str],
# #   "folder": str,
# #   "country_code": str | null,
# #   "zip_used": str | null
# # }
# #
# # Notes:
# # - Fixed type hints; removed invalid `is_visible(timeout=...)` usage.
# # - Uses explicit waits (locator.wait_for) where needed.
# # - Downloads images with Playwright's context.request.
# # - Dedupe images by stable CDN key (UUID in path or filename stem).
# # - _set_location is a no-op (Zola has no generic popover flow).
# # - Robust price/stock/description/image fallbacks.

# import json
# import os
# import re
# import time
# import hashlib
# from pathlib import Path
# from typing import Optional, Tuple, List
# from urllib.parse import urlparse, urlunparse

# from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# # -------- Core utilities --------

# # put this near the top of your script
# BASE_DIR = Path(__file__).resolve().parent
# DATA_DIR = BASE_DIR / "data1"


# UA = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
# )
# VIEWPORT = {"width": 1400, "height": 900}
# LOCALE = "en-US"
# TIMEZONE = "America/Los_Angeles"

# ANTI_AUTOMATION_JS = r"""
# Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
# """

# COOKIE_ACCEPT_SELECTORS = [
#     "#onetrust-accept-btn-handler",       # OneTrust
#     "button#truste-consent-button",       # TrustArc variant
#     "button:has-text('Accept All')",
#     "button:has-text('Accept all')",
#     "button:has-text('Accept')",
#     "button:has-text('I agree')",
# ]

# LIGHT_INTERSTITIAL_TEXTS = [
#     "Continue", "Continue shopping", "Go to site", "Verify", "Close"
# ]

# def _clean(s: str) -> str:
#     if not s:
#         return ""
#     return re.sub(r"\s+", " ", s).strip()

# def _safe_name(s: str) -> str:
#     s = _clean(s)
#     s = re.sub(r"[^\w.\-]+", "_", s, flags=re.UNICODE)
#     return s[:100] if s else "product"

# def _slug_from_host(url: str) -> str:
#     try:
#         host = urlparse(url).hostname or "site"
#         host = host.replace("www.", "")
#         return host.split(".")[0]
#     except Exception:
#         return "site"

# def _stable_id_from_url(url: str) -> str:
#     """
#     Prefer path segment after /product/<slug>. If none, hash the URL.
#     """
#     try:
#         path = (urlparse(url).path or "").strip("/")
#         m = re.search(r"(?:^|/)product/([^/?#]+)", path, re.I)
#         if m:
#             return m.group(1)
#         segs = [p for p in path.split("/") if p]
#         if segs:
#             return segs[-1]
#     except Exception:
#         pass
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

# def _ensure_dir(p: Path):
#     p.mkdir(parents=True, exist_ok=True)

# def _small_human_scrolls(page):
#     try:
#         page.mouse.wheel(0, 400); time.sleep(0.07)
#         page.mouse.wheel(0, 350); time.sleep(0.07)
#         page.mouse.wheel(0, 300)
#     except Exception:
#         pass

# def _wait_idle(page, timeout_ms: int = 10000, settle_ms: int = 400):
#     try:
#         page.wait_for_load_state("networkidle", timeout=timeout_ms)
#     except PlaywrightTimeoutError:
#         pass
#     time.sleep(settle_ms / 1000.0)

# def _click_if_visible(page, selector: str, timeout_ms: int = 1200) -> bool:
#     try:
#         loc = page.locator(selector).first
#         if not loc:
#             return False
#         # Try to wait briefly for it to appear; if not, just probe visibility
#         try:
#             loc.wait_for(state="visible", timeout=timeout_ms)
#             loc.click(timeout=timeout_ms)
#             return True
#         except Exception:
#             if loc.is_visible():
#                 loc.click()
#                 return True
#     except Exception:
#         pass
#     return False

# def _click_text_if_visible(page, texts: List[str], timeout_ms: int = 1200) -> bool:
#     for t in texts:
#         try:
#             loc = page.get_by_text(t, exact=False).first
#             if not loc:
#                 continue
#             try:
#                 loc.wait_for(state="visible", timeout=timeout_ms)
#                 loc.click(timeout=timeout_ms)
#                 return True
#             except Exception:
#                 if loc.is_visible():
#                     loc.click()
#                     return True
#         except Exception:
#             continue
#     return False

# def _handle_cookies_and_interstitials(page):
#     for sel in COOKIE_ACCEPT_SELECTORS:
#         if _click_if_visible(page, sel):
#             break
#     _click_text_if_visible(page, LIGHT_INTERSTITIAL_TEXTS, timeout_ms=1000)

# def _parse_money(s: str) -> Optional[str]:
#     if not s:
#         return None
#     s = _clean(s)
#     m = re.search(r"(\$?\s*\d[\d,]*(?:\.\d{2})?)", s)
#     if m:
#         val = m.group(1).replace(" ", "")
#         if not val.startswith("$"):
#             val = "$" + val
#         return val
#     return None

# # -------- Price extraction --------

# def _extract_price(page) -> Tuple[str, str]:
#     # Primary: Zola price container
#     try:
#         loc = page.locator("div.zola-price").first
#         if loc:
#             try:
#                 loc.wait_for(state="visible", timeout=2500)
#             except Exception:
#                 pass
#             if loc.is_visible():
#                 txt = _clean(loc.inner_text())
#                 money = _parse_money(txt)
#                 if money:
#                     return money, "zola-price"
#     except Exception:
#         pass

#     # JSON-LD offers
#     try:
#         scripts = page.locator("script[type='application/ld+json']")
#         count = scripts.count()
#         for i in range(count):
#             try:
#                 raw = scripts.nth(i).inner_text(timeout=200)
#                 if not raw:
#                     continue
#                 data = json.loads(raw)
#                 candidates = data if isinstance(data, list) else [data]
#                 for obj in candidates:
#                     if not isinstance(obj, dict):
#                         continue
#                     if obj.get("@type") in ("Product", "Offer", "AggregateOffer"):
#                         offers = obj.get("offers")
#                         if isinstance(offers, dict):
#                             price = offers.get("price")
#                             if price:
#                                 money = _parse_money(str(price))
#                                 if money:
#                                     return money, "jsonld"
#                         elif isinstance(offers, list):
#                             for offr in offers:
#                                 if isinstance(offr, dict) and offr.get("price"):
#                                     money = _parse_money(str(offr["price"]))
#                                     if money:
#                                         return money, "jsonld"
#             except Exception:
#                 continue
#     except Exception:
#         pass

#     # Microdata itemprop=price
#     try:
#         loc = page.locator("[itemprop='price'], meta[itemprop='price']").first
#         if loc and loc.count():
#             val = (loc.get_attribute("content") or loc.inner_text() or "").strip()
#             money = _parse_money(val)
#             if money:
#                 return money, "microdata"
#     except Exception:
#         pass

#     # Heuristic near buy box
#     try:
#         buybox = page.locator("section:has(button:has-text('Add to cart'))").first
#         if buybox and buybox.count():
#             txt = _clean(buybox.inner_text())
#             money = _parse_money(txt)
#             if money:
#                 return money, "heuristic-buybox"
#     except Exception:
#         pass

#     return "N/A", "none"

# # -------- Stock heuristics --------

# def _detect_stock(page) -> Tuple[Optional[bool], str]:
#     stock_text = ""

#     # Explicit stock message
#     try:
#         msg = page.locator(".stock-message-text").first
#         if msg and msg.count():
#             stock_text = _clean(msg.inner_text())
#     except Exception:
#         pass

#     # Positive: Add to cart visible & enabled
#     try:
#         btn = page.locator("button:has-text('Add to cart')").first
#         if btn:
#             # wait a bit for hydration
#             try:
#                 btn.wait_for(state="visible", timeout=2000)
#             except Exception:
#                 pass
#             if btn.is_visible() and btn.is_enabled():
#                 return True, stock_text or "Add to cart available"
#     except Exception:
#         pass

#     # Negative cues
#     neg_selectors = [
#         "button:has-text('Sold out')",
#         "button[disabled]:has-text('Add to cart')",
#         "div:has-text('Out of stock')",
#         "div:has-text('Currently unavailable')",
#         "div:has-text('Unavailable')",
#     ]
#     for sel in neg_selectors:
#         try:
#             loc = page.locator(sel).first
#             if loc and loc.count():
#                 if loc.is_visible():
#                     return False, stock_text or _clean(loc.inner_text())
#         except Exception:
#             continue

#     return None, stock_text

# # -------- Description extraction --------

# def _extract_description(page) -> str:
#     bullets: List[str] = []
#     paras: List[str] = []

#     try:
#         container = page.locator("div.product-description").first
#         if container and container.count():
#             # Bullets
#             try:
#                 lis = container.locator("ul li")
#                 for i in range(lis.count()):
#                     t = _clean(lis.nth(i).inner_text())
#                     if t:
#                         bullets.append(f"• {t}")
#             except Exception:
#                 pass
#             # Paragraphs
#             try:
#                 ps = container.locator("p")
#                 for i in range(ps.count()):
#                     t = _clean(ps.nth(i).inner_text())
#                     if t:
#                         paras.append(t)
#             except Exception:
#                 pass
#     except Exception:
#         pass

#     if bullets:
#         if paras:
#             lead = f"• {paras[0]}"
#             return "\n".join([lead] + bullets)
#         return "\n".join(bullets)

#     if paras:
#         return _clean(" ".join(paras))

#     # Meta description
#     try:
#         meta = page.locator("meta[name='description']").first
#         if meta and meta.count():
#             content = _clean(meta.get_attribute("content") or "")
#             if content:
#                 return content
#     except Exception:
#         pass

#     # JSON-LD description
#     try:
#         scripts = page.locator("script[type='application/ld+json']")
#         for i in range(scripts.count()):
#             try:
#                 raw = scripts.nth(i).inner_text(timeout=200)
#                 if not raw:
#                     continue
#                 data = json.loads(raw)
#                 candidates = data if isinstance(data, list) else [data]
#                 for obj in candidates:
#                     if isinstance(obj, dict) and obj.get("@type") == "Product":
#                         desc = _clean(obj.get("description") or "")
#                         if desc:
#                             return desc
#             except Exception:
#                 continue
#     except Exception:
#         pass

#     return ""

# # -------- Image collection, normalization & download --------

# def _pick_largest_from_srcset(srcset: str) -> Optional[str]:
#     """
#     Parse a srcset string and return the largest width candidate's URL.
#     """
#     try:
#         parts = [p.strip() for p in (srcset or "").split(",") if p.strip()]
#         best_url = None
#         best_w = -1
#         for part in parts:
#             m = re.match(r"(.+?)\s+(\d+)w", part)
#             if m:
#                 url = m.group(1).strip()
#                 w = int(m.group(2))
#                 if w > best_w:
#                     best_w = w
#                     best_url = url
#             else:
#                 # no descriptor — keep last seen
#                 best_url = part
#         return best_url
#     except Exception:
#         return None

# def _normalize_zola_image_url(url: str) -> str:
#     """
#     For images.zola.com, strip query (?w=84 etc.) to fetch original HQ.
#     For other hosts, drop query/fragment as a generic HQ heuristic.
#     """
#     try:
#         parts = list(urlparse(url.strip()))
#         parts[4] = ""  # query
#         parts[5] = ""  # fragment
#         return urlunparse(parts)
#     except Exception:
#         return url

# def _stable_image_key(url: str) -> str:
#     """
#     Use UUID in path if present (images.zola.com/<uuid>), else filename stem; else hash.
#     """
#     try:
#         path = urlparse(url).path or ""
#         m = re.search(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", path, re.I)
#         if m:
#             return m.group(1).lower()
#         fname = os.path.basename(path)
#         stem = os.path.splitext(fname)[0]
#         if stem:
#             return stem.lower()
#     except Exception:
#         pass
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]

# def _collect_images(page, max_images: Optional[int] = None) -> List[str]:
#     urls: List[str] = []

#     # 1) Gallery thumbnails
#     try:
#         thumbs = page.locator(".thumbnail-slider img[src]")
#         count = thumbs.count()
#         for i in range(count):
#             src = thumbs.nth(i).get_attribute("src") or ""
#             if src:
#                 urls.append(src)
#     except Exception:
#         pass

#     # 2) Hero/other <img> and <source srcset>
#     try:
#         hero_imgs = page.locator("img[alt][src]")
#         for i in range(min(hero_imgs.count(), 10)):
#             src = hero_imgs.nth(i).get_attribute("src") or ""
#             if src:
#                 urls.append(src)
#     except Exception:
#         pass
#     try:
#         sources = page.locator("source[srcset]")
#         for i in range(min(sources.count(), 12)):
#             ss = sources.nth(i).get_attribute("srcset") or ""
#             best = _pick_largest_from_srcset(ss)
#             if best:
#                 urls.append(best)
#     except Exception:
#         pass

#     # 3) OpenGraph
#     try:
#         og = page.locator("meta[property='og:image']").first
#         if og and og.count():
#             u = og.get_attribute("content") or ""
#             if u:
#                 urls.append(u)
#     except Exception:
#         pass

#     # 4) JSON-LD Product.image
#     try:
#         scripts = page.locator("script[type='application/ld+json']")
#         for i in range(scripts.count()):
#             try:
#                 raw = scripts.nth(i).inner_text(timeout=200)
#                 if not raw:
#                     continue
#                 data = json.loads(raw)
#                 candidates = data if isinstance(data, list) else [data]
#                 for obj in candidates:
#                     if isinstance(obj, dict) and obj.get("@type") == "Product":
#                         imgs = obj.get("image")
#                         if isinstance(imgs, str):
#                             urls.append(imgs)
#                         elif isinstance(imgs, list):
#                             for u in imgs:
#                                 if isinstance(u, str):
#                                     urls.append(u)
#             except Exception:
#                 continue
#     except Exception:
#         pass

#     # Normalize & dedupe
#     seen = set()
#     final_urls: List[str] = []
#     for u in urls:
#         if not u:
#             continue
#         nu = _normalize_zola_image_url(u)
#         key = _stable_image_key(nu)
#         if key in seen:
#             continue
#         seen.add(key)
#         final_urls.append(nu)
#         if max_images and len(final_urls) >= max_images:
#             break

#     return final_urls

# def _download_image(context, url: str, dest: Path) -> bool:
#     try:
#         r = context.request.get(url, timeout=20000)
#         if r.ok:
#             dest.write_bytes(r.body())
#             return True
#     except Exception:
#         pass
#     return False

# # -------- Optional location setter (no-op for Zola) --------

# def _set_location(context, page, country_code: Optional[str] = None, zip_code: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
#     """
#     Zola doesn't expose a generic delivery-location popover.
#     Per spec: only act IF supported. Return (None, None) here.
#     """
#     if not country_code and not zip_code:
#         return None, None
#     return None, None

# # -------- Main entry --------

# def _prepare_context(pw, headless: bool):
#     browser = pw.chromium.launch(headless=headless)
#     context = browser.new_context(
#         user_agent=UA,
#         locale=LOCALE,
#         timezone_id=TIMEZONE,
#         viewport=VIEWPORT,
#         java_script_enabled=True,
#         device_scale_factor=1.0,
#         accept_downloads=False,
#     )
#     context.add_init_script(ANTI_AUTOMATION_JS)
#     page = context.new_page()
#     return browser, context, page

# def scrape_zola(
#     url: str,
#     headless: bool = False,
#     country_code: Optional[str] = None,
#     zip_code: Optional[str] = None,
#     max_images: Optional[int] = None
# ) -> dict:
#     slug = _slug_from_host(url) or "zola"
#     stable_id = _stable_id_from_url(url)
#     folder = Path("data1") / f"{slug}_UNKNOWN_{stable_id}"  # temp until name known

#     with sync_playwright() as pw:
#         browser, context, page = _prepare_context(pw, headless=headless)
#         try:
#             page.set_default_timeout(15000)
#             page.goto(url, wait_until="domcontentloaded")
#             _handle_cookies_and_interstitials(page)
#             _small_human_scrolls(page)
#             _wait_idle(page)

#             applied_country, zip_used = _set_location(context, page, country_code, zip_code)

#             # ----- NAME -----
#             name = ""
#             brand = ""
#             try:
#                 wrap = page.locator("div.brand-product-names-nonmobile").first
#                 if wrap and wrap.count():
#                     try:
#                         brand = _clean(wrap.locator("a.brand-name").first.inner_text())
#                     except Exception:
#                         brand = ""
#                     try:
#                         pname = _clean(wrap.locator("h1.product-name").first.inner_text())
#                     except Exception:
#                         pname = ""
#                     if pname and brand:
#                         name = f"{brand} – {pname}"
#                     elif pname:
#                         name = pname
#                     elif brand:
#                         name = brand
#             except Exception:
#                 pass
#             if not name:
#                 try:
#                     h1 = page.locator("h1[data-testid*='product-name'], h1.product-name").first
#                     if h1 and h1.count():
#                         name = _clean(h1.inner_text())
#                 except Exception:
#                     pass
#             if not name:
#                 try:
#                     ogt = page.locator("meta[property='og:title']").first
#                     if ogt and ogt.count():
#                         name = _clean(ogt.get_attribute("content") or "")
#                 except Exception:
#                     pass
#             name = name or "Unknown Product"

#             # Update folder now that we have a name
#             # Update folder now that we have a name
#             folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}"
#             _ensure_dir(folder)

#             # ----- PRICE -----
#             price, price_source = _extract_price(page)

#             # ----- STOCK -----
#             in_stock, stock_text = _detect_stock(page)

#             # ----- DESCRIPTION -----
#             description = _extract_description(page)

#             # ----- IMAGES -----
#             image_urls = _collect_images(page, max_images=max_images)
#             saved_paths: List[str] = []
#             for idx, img_url in enumerate(image_urls, start=1):
#                 ext = ".jpg"
#                 m = re.search(r"\.(jpg|jpeg|png|webp|gif)(?:$|\?)", img_url, re.I)
#                 if m:
#                     ext = "." + m.group(1).lower()
#                 fname = f"{idx:02d}_{_safe_name(_stable_image_key(img_url))}{ext}"
#                 dest = folder / fname
#                 if _download_image(context, img_url, dest):
#                     saved_paths.append(str(dest))

#             out = {
#                 "name": name,
#                 "price": price,
#                 "price_source": price_source if price != "N/A" else "none",
#                 "in_stock": in_stock,
#                 "stock_text": stock_text or "",
#                 "description": description,
#                 "image_count": len(saved_paths),
#                 "images": saved_paths,
#                 "folder": str(folder),
#                 "country_code": applied_country,
#                 "zip_used": zip_used,
#             }
#             return out
#         finally:
#             try: context.close()
#             except Exception: pass
#             try: browser.close()
#             except Exception: pass

# # -------- CLI test --------

# if __name__ == "__main__":
#     TEST_URL = "https://www.zola.com/shop/product/lauraashley_jug_kettle"
#     result = scrape_zola(TEST_URL, headless=True)
#     print(json.dumps(result, indent=2, ensure_ascii=False))










# # zola.py
# # Python 3.10+
# # Oxylabs Web Scraper API (universal) -> HTML -> BeautifulSoup parsing
# #
# # pip install requests beautifulsoup4 lxml pillow

# from __future__ import annotations

# import os
# import re
# import io
# import json
# import hashlib
# from pathlib import Path
# from typing import Optional, Tuple, List, Dict, Any
# from urllib.parse import urlparse, urlunparse

# import requests
# from bs4 import BeautifulSoup
# from PIL import Image

# # ========= Secrets =========
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS  # type: ignore
# except Exception:
#     OXY_USER = os.getenv("OXYLABS_USERNAME", "")
#     OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")

# if not OXY_USER or not OXY_PASS:
#     raise RuntimeError("Set Oxylabs creds via oxylabs_secrets.py or env vars OXYLABS_USERNAME/PASSWORD.")

# # ========= Config / Paths =========
# OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"
# REQUEST_TIMEOUT = 90
# UA_STR = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#     "AppleWebKit/537.36 (KHTML, like Gecko) "
#     "Chrome/127.0.0.0 Safari/537.36"
# )
# GEO_LOCATION = "United States"

# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()
# DATA_DIR = BASE_DIR / "data1"
# DATA_DIR.mkdir(parents=True, exist_ok=True)

# # ========= Helpers =========
# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "").strip())

# def _safe_name(s: str) -> str:
#     s = _clean(s)
#     s = re.sub(r"[^\w.\-]+", "_", s, flags=re.UNICODE)
#     return s[:100] if s else "product"

# def _slug_from_host(url: str) -> str:
#     try:
#         host = urlparse(url).hostname or "site"
#         host = host.replace("www.", "")
#         return host.split(".")[0]
#     except Exception:
#         return "site"

# def _stable_id_from_url(url: str) -> str:
#     """
#     Prefer path segment after /product/<slug>. If none, fallback to last segment or URL hash.
#     """
#     try:
#         path = (urlparse(url).path or "").strip("/")
#         m = re.search(r"(?:^|/)product/([^/?#]+)", path, re.I)
#         if m:
#             return m.group(1)
#         segs = [p for p in path.split("/") if p]
#         if segs:
#             return segs[-1]
#     except Exception:
#         pass
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

# def _post_oxylabs_universal(url: str) -> str:
#     payload = {
#         "source": "universal",
#         "url": url,
#         "render": "html",
#         "user_agent": UA_STR,
#         "geo_location": GEO_LOCATION,
#     }
#     resp = requests.post(
#         OXY_ENDPOINT,
#         json=payload,
#         auth=(OXY_USER, OXY_PASS),
#         timeout=REQUEST_TIMEOUT,
#     )
#     if resp.status_code == 401:
#         raise RuntimeError("Oxylabs Unauthorized (401). Check OXYLABS_USERNAME/PASSWORD.")
#     if not resp.ok:
#         raise RuntimeError(f"Oxylabs failed: HTTP {resp.status_code} - {resp.text[:400]}")
#     data = resp.json()
#     if isinstance(data, dict) and data.get("results"):
#         c = data["results"][0].get("content")
#         if isinstance(c, str):
#             return c
#     if isinstance(data, dict) and isinstance(data.get("content"), str):
#         return data["content"]
#     raise RuntimeError("Oxylabs universal returned no HTML content")

# # ========= Field extractors =========
# def _parse_money(s: str) -> Optional[str]:
#     if not s:
#         return None
#     s = _clean(s)
#     m = re.search(r"(\$?\s*\d[\d,]*(?:\.\d{2})?)", s)
#     if m:
#         val = m.group(1).replace(" ", "")
#         if not val.startswith("$"):
#             val = "$" + val
#         return val
#     return None

# def _extract_name(soup: BeautifulSoup) -> str:
#     # Common Zola structures
#     for sel in [
#         "div.brand-product-names-nonmobile h1.product-name",
#         "h1[data-testid*='product-name']",
#         "h1.product-name",
#         "meta[property='og:title']",
#         "title",
#     ]:
#         node = soup.select_one(sel)
#         if not node:
#             continue
#         txt = node.get("content") if node.name == "meta" else node.get_text(" ", strip=True)
#         txt = _clean(txt)
#         if txt:
#             return txt
#     return "Unknown Product"

# def _extract_price_and_src(soup: BeautifulSoup) -> Tuple[str, str]:
#     # Primary containers
#     for sel in [
#         "div.zola-price",
#         "[data-testid*='price']",
#         "[class*='price']",
#     ]:
#         node = soup.select_one(sel)
#         if node:
#             money = _parse_money(node.get_text(" ", strip=True))
#             if money:
#                 return money, "zola-price"
#     # Microdata
#     node = soup.select_one("[itemprop='price'], meta[itemprop='price']")
#     if node:
#         val = (node.get("content") or node.get_text(" ", strip=True) or "").strip()
#         money = _parse_money(val)
#         if money:
#             return money, "microdata"
#     # JSON-LD
#     for sc in soup.select("script[type='application/ld+json']"):
#         raw = sc.string or sc.get_text(separator="", strip=True) or ""
#         if not raw:
#             continue
#         try:
#             data = json.loads(raw)
#         except Exception:
#             continue
#         objs = data if isinstance(data, list) else [data]
#         for obj in objs:
#             if not isinstance(obj, dict):
#                 continue
#             if obj.get("@type") in ("Product", "Offer", "AggregateOffer"):
#                 offers = obj.get("offers")
#                 if isinstance(offers, dict):
#                     price = offers.get("price")
#                     money = _parse_money(str(price) if price is not None else "")
#                     if money:
#                         return money, "jsonld"
#                 elif isinstance(offers, list):
#                     for off in offers:
#                         if isinstance(off, dict) and off.get("price"):
#                             money = _parse_money(str(off["price"]))
#                             if money:
#                                 return money, "jsonld"
#     # Heuristic: buy box text
#     buybox = soup.find(lambda t: hasattr(t, "get_text") and "Add to cart" in t.get_text(" ", strip=True))
#     if buybox:
#         money = _parse_money(buybox.get_text(" ", strip=True))
#         if money:
#             return money, "heuristic-buybox"
#     return "N/A", "none"

# def _detect_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
#     # Explicit message
#     stock_text = ""
#     for sel in [".stock-message-text", "[data-testid*='stock']", "div:has(> span:contains('Out of stock'))"]:
#         node = soup.select_one(sel)
#         if node:
#             st = _clean(node.get_text(" ", strip=True))
#             if st:
#                 stock_text = st
#                 break

#     # Positive if Add to cart present and not disabled
#     html = soup.decode().lower()
#     if re.search(r">\s*add to cart\s*<", html) or re.search(r'aria-label="\s*add to cart\s*"', html):
#         # quick disabled check when we can see attributes
#         atc = soup.find("button", string=re.compile(r"add to cart", re.I))
#         if atc:
#             disabled_attr = (atc.get("disabled") or "").lower()
#             aria_disabled = (atc.get("aria-disabled") or "").lower()
#             cls = atc.get("class") or []
#             cls_str = " ".join(cls) if isinstance(cls, list) else str(cls)
#             if disabled_attr == "true" or aria_disabled == "true" or re.search(r"\bdisabled\b", cls_str, re.I):
#                 return False, stock_text or "Add to cart disabled"
#         return True, stock_text or "Add to cart available"

#     # Negative cues
#     body = _clean(soup.get_text(" ", strip=True))
#     if re.search(r"\b(out of stock|sold out|unavailable|currently unavailable)\b", body, re.I):
#         return False, stock_text or "Out of stock"

#     return None, stock_text

# def _extract_description(soup: BeautifulSoup) -> str:
#     # Primary product description area
#     for sel in [
#         "div.product-description",
#         "[data-testid*='description']",
#         "section[aria-label='Product Description']",
#     ]:
#         cont = soup.select_one(sel)
#         if cont:
#             parts: List[str] = []
#             # bullets first
#             for li in cont.select("ul li"):
#                 t = _clean(li.get_text(" ", strip=True))
#                 if t:
#                     parts.append(f"• {t}")
#             # then paragraphs (avoid duplicating bullets)
#             if not parts:
#                 ps = [ _clean(p.get_text(" ", strip=True)) for p in cont.select("p") ]
#                 ps = [p for p in ps if p]
#                 if ps:
#                     return " ".join(ps)
#             if parts:
#                 return "\n".join(parts)

#     # Meta description fallback
#     meta = soup.select_one("meta[name='description']")
#     if meta and meta.get("content"):
#         txt = _clean(meta["content"])
#         if txt:
#             return txt

#     # JSON-LD description
#     best = ""
#     for sc in soup.select("script[type='application/ld+json']"):
#         raw = sc.string or sc.get_text(separator="", strip=True) or ""
#         if not raw:
#             continue
#         try:
#             data = json.loads(raw)
#         except Exception:
#             continue
#         objs = data if isinstance(data, list) else [data]
#         for obj in objs:
#             if isinstance(obj, dict) and obj.get("@type") == "Product":
#                 desc = _clean(obj.get("description") or "")
#                 if desc and len(desc) > len(best):
#                     best = desc
#     return best

# # ========= Images =========
# def _pick_largest_from_srcset(srcset: str) -> Optional[str]:
#     try:
#         parts = [p.strip() for p in (srcset or "").split(",") if p.strip()]
#         best_url = None
#         best_w = -1
#         for part in parts:
#             m = re.match(r"(.+?)\s+(\d+)w", part)
#             if m:
#                 url = m.group(1).strip()
#                 w = int(m.group(2))
#                 if w > best_w:
#                     best_w = w
#                     best_url = url
#             else:
#                 best_url = part
#         return best_url
#     except Exception:
#         return None

# def _normalize_zola_image_url(url: str) -> str:
#     """
#     For images.zola.com, strip query (?w=84 etc.) to fetch original HQ.
#     For others, drop query/fragment as a generic HQ heuristic.
#     """
#     try:
#         parts = list(urlparse(url.strip()))
#         parts[4] = ""  # query
#         parts[5] = ""  # fragment
#         return urlunparse(parts)
#     except Exception:
#         return url

# def _stable_image_key(url: str) -> str:
#     """
#     Use UUID in path if present (images.zola.com/<uuid>), else filename stem; else hash.
#     """
#     try:
#         path = urlparse(url).path or ""
#         m = re.search(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", path, re.I)
#         if m:
#             return m.group(1).lower()
#         fname = os.path.basename(path)
#         stem = os.path.splitext(fname)[0]
#         if stem:
#             return stem.lower()
#     except Exception:
#         pass
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]

# def _collect_images(soup: BeautifulSoup, *, max_images: Optional[int] = None) -> List[str]:
#     """
#     Only accept likely PDP images:
#       - Host: images.zola.com (primary)
#       - Else: allow other hosts but must come from gallery/og/json-ld
#     """
#     urls: List[str] = []

#     # 1) Thumbnails / gallery imgs
#     for sel in [
#         ".thumbnail-slider img[src]",
#         "[data-testid*='gallery'] img[src]",
#         "div[class*='gallery'] img[src]",
#     ]:
#         for img in soup.select(sel):
#             u = img.get("src") or ""
#             if not u:
#                 continue
#             urls.append(u)

#     # 2) <source srcset> candidates
#     for source in soup.select("source[srcset]"):
#         best = _pick_largest_from_srcset(source.get("srcset") or "")
#         if best:
#             urls.append(best)

#     # 3) OpenGraph
#     og = soup.select_one("meta[property='og:image']")
#     if og and og.get("content"):
#         urls.append(og["content"])

#     # 4) JSON-LD Product.image
#     for sc in soup.select("script[type='application/ld+json']"):
#         raw = sc.string or sc.get_text(separator="", strip=True) or ""
#         if not raw:
#             continue
#         try:
#             data = json.loads(raw)
#         except Exception:
#             continue
#         objs = data if isinstance(data, list) else [data]
#         for obj in objs:
#             if isinstance(obj, dict) and obj.get("@type") == "Product":
#                 imgs = obj.get("image")
#                 if isinstance(imgs, str):
#                     urls.append(imgs)
#                 elif isinstance(imgs, list):
#                     for u in imgs:
#                         if isinstance(u, str):
#                             urls.append(u)

#     # Accept filter: prefer images.zola.com; otherwise allow if path looks like product media
#     def _accept(u: str) -> bool:
#         if not u:
#             return False
#         hu = u.lower()
#         if "images.zola.com" in hu:
#             return True
#         # Allow common image file endings for non-Zola hosts but avoid icons/sprites
#         if not re.search(r"\.(jpg|jpeg|png|webp)(?:$|\?)", hu):
#             return False
#         if re.search(r"(sprite|icon|badge|logo|placeholder|swatch|thumb|share)", hu):
#             return False
#         return True

#     # Normalize + dedupe by stable key
#     seen = set()
#     final: List[str] = []
#     for u in urls:
#         if not _accept(u):
#             continue
#         nu = _normalize_zola_image_url(u)
#         key = _stable_image_key(nu)
#         if key in seen:
#             continue
#         seen.add(key)
#         final.append(nu)
#         if max_images and len(final) >= max_images:
#             break

#     return final

# # ========= Perceptual-hash dedupe =========
# def _ahash(img: Image.Image, hash_size: int = 8) -> int:
#     im = img.convert("L").resize((hash_size, hash_size), Image.BILINEAR)
#     pixels = list(im.getdata())
#     avg = sum(pixels) / len(pixels)
#     bits = 0
#     for p in pixels:
#         bits = (bits << 1) | (1 if p >= avg else 0)
#     return bits

# def _hamming(a: int, b: int) -> int:
#     x = a ^ b
#     return x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1")

# def _dedupe_downloaded_by_phash(paths: List[str], *, max_hamming: int = 4) -> List[str]:
#     kept: List[str] = []
#     hashes: List[int] = []
#     for p in paths:
#         try:
#             im = Image.open(p)
#             h = _ahash(im)
#         except Exception:
#             kept.append(p)
#             continue
#         is_dup = False
#         for prev in hashes:
#             if _hamming(h, prev) <= max_hamming:
#                 try:
#                     Path(p).unlink(missing_ok=True)
#                 except Exception:
#                     pass
#                 is_dup = True
#                 break
#         if not is_dup:
#             hashes.append(h)
#             kept.append(p)
#     return kept

# # ========= Downloading =========
# def _download_images(
#     urls: List[str],
#     folder: Path,
#     *,
#     convert_to_jpg: bool = True,
#     quality: int = 90,
#     referer: Optional[str] = None,
# ) -> List[str]:
#     saved: List[str] = []
#     folder.mkdir(parents=True, exist_ok=True)
#     headers = {
#         "User-Agent": UA_STR,
#         "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
#     }
#     if referer:
#         headers["Referer"] = referer

#     with requests.Session() as s:
#         s.headers.update(headers)
#         for i, u in enumerate(urls, 1):
#             try:
#                 r = s.get(u, timeout=25)
#                 if not (r.ok and r.content):
#                     continue
#                 if convert_to_jpg:
#                     img_bytes = io.BytesIO(r.content)
#                     im = Image.open(img_bytes)
#                     if im.mode in ("RGBA", "LA", "P"):
#                         if im.mode == "P":
#                             im = im.convert("RGBA")
#                         bg = Image.new("RGB", im.size, (255, 255, 255))
#                         bg.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
#                         im = bg
#                     else:
#                         im = im.convert("RGB")
#                     out_path = folder / f"image_{i}.jpg"
#                     im.save(out_path, format="JPEG", quality=quality, optimize=True)
#                     saved.append(str(out_path))
#                 else:
#                     ext = ".jpg"
#                     ct = (r.headers.get("Content-Type") or "").lower()
#                     lu = u.lower()
#                     if "png" in ct or lu.endswith(".png"): ext = ".png"
#                     elif "webp" in ct or lu.endswith(".webp"): ext = ".webp"
#                     elif "jpeg" in ct or lu.endswith(".jpeg"): ext = ".jpeg"
#                     out_path = folder / f"image_{i}{ext}"
#                     out_path.write_bytes(r.content)
#                     saved.append(str(out_path))
#             except Exception:
#                 continue
#     return saved

# # ========= Public API (single-arg) =========
# def scrape_zola(url: str) -> Dict[str, Any]:
#     """
#     Fetch via Oxylabs (universal), parse with BS4, download images, pHash-dedupe,
#     return the exact schema required.
#     """
#     html = _post_oxylabs_universal(url)
#     soup = BeautifulSoup(html, "lxml")

#     # Fields
#     name = _extract_name(soup)
#     price, price_source = _extract_price_and_src(soup)
#     in_stock, stock_text = _detect_stock(soup)
#     description = _extract_description(soup)
#     images = _collect_images(soup, max_images=None)

#     # Save folder & raw HTML
#     slug = _slug_from_host(url)
#     stable_id = _stable_id_from_url(url)
#     folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}"
#     folder.mkdir(parents=True, exist_ok=True)
#     try:
#         (folder / "raw_html.html").write_text(html, encoding="utf-8")
#     except Exception:
#         pass

#     # Download + pHash-dedupe
#     downloaded = _download_images(images, folder, convert_to_jpg=True, referer=url)
#     deduped = _dedupe_downloaded_by_phash(downloaded, max_hamming=4)

#     out = {
#         "name": name,
#         "price": price,
#         "price_source": price_source if price != "N/A" else "none",
#         "in_stock": in_stock,
#         "stock_text": stock_text or "",
#         "description": description or "",
#         "image_count": len(deduped),
#         "images": deduped,
#         "folder": str(folder),
#         "country_code": None,  # Zola generic location not supported via HTML path
#         "zip_used": None,      # ditto
#     }
#     try:
#         (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
#     except Exception:
#         pass
#     return out

# # ========= Hardcoded run =========
# if __name__ == "__main__":
#     u = "https://www.zola.com/shop/product/lauraashley_jug_kettle"
#     data = scrape_zola(u)  # <- single argument only
#     print(json.dumps(data, indent=2, ensure_ascii=False))
















# zola.py
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
from urllib.parse import urlparse, urlunparse

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
DATA_DIR = BASE_DIR / "data1"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ========= Helpers =========
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _safe_name(s: str) -> str:
    s = _clean(s)
    s = re.sub(r"[^\w.\-]+", "_", s, flags=re.UNICODE)
    return s[:100] if s else "product"

def _slug_from_host(url: str) -> str:
    try:
        host = urlparse(url).hostname or "site"
        host = host.replace("www.", "")
        return host.split(".")[0]
    except Exception:
        return "site"

def _stable_id_from_url(url: str) -> str:
    """
    Prefer path segment after /product/<slug>. If none, fallback to last segment or URL hash.
    """
    try:
        path = (urlparse(url).path or "").strip("/")
        m = re.search(r"(?:^|/)product/([^/?#]+)", path, re.I)
        if m:
            return m.group(1)
        segs = [p for p in path.split("/") if p]
        if segs:
            return segs[-1]
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

def _unique_path(base: Path) -> Path:
    """Return a unique folder path by suffixing _01, _02, ... if needed."""
    if not base.exists():
        return base
    stem = base.name
    parent = base.parent
    m = re.match(r"^(.*)_(\d{2})$", stem)
    if m:
        core, num = m.groups()
        n = int(num)
        while True:
            n += 1
            cand = parent / f"{core}_{n:02d}"
            if not cand.exists():
                return cand
    else:
        n = 1
        while True:
            cand = parent / f"{stem}_{n:02d}"
            if not cand.exists():
                return cand
            n += 1

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

# ========= Field extractors =========
def _parse_money(s: str) -> Optional[str]:
    if not s:
        return None
    s = _clean(s)
    m = re.search(r"(\$?\s*\d[\d,]*(?:\.\d{2})?)", s)
    if m:
        val = m.group(1).replace(" ", "")
        if not val.startswith("$"):
            val = "$" + val
        return val
    return None

def _extract_name(soup: BeautifulSoup) -> str:
    # Brand + product name block
    wrap = soup.select_one("div.brand-product-names-nonmobile")
    if wrap:
        brand = _clean(wrap.select_one("a.brand-name").get_text(" ", strip=True)) if wrap.select_one("a.brand-name") else ""
        pname = _clean(wrap.select_one("h1.product-name").get_text(" ", strip=True)) if wrap.select_one("h1.product-name") else ""
        if pname and brand:
            return f"{brand} – {pname}"
        if pname:
            return pname
        if brand:
            return brand

    for sel in [
        "h1[data-testid*='product-name']",
        "h1.product-name",
        "meta[property='og:title']",
        "title",
    ]:
        node = soup.select_one(sel)
        if not node:
            continue
        txt = node.get("content") if node.name == "meta" else node.get_text(" ", strip=True)
        txt = _clean(txt)
        if txt:
            return txt
    return "Unknown Product"

def _extract_price_and_src(soup: BeautifulSoup) -> Tuple[str, str]:
    for sel in [
        "div.zola-price",
        "[data-testid*='price']",
        "[class*='price']",
    ]:
        node = soup.select_one(sel)
        if node:
            money = _parse_money(node.get_text(" ", strip=True))
            if money:
                return money, "zola-price"

    node = soup.select_one("[itemprop='price'], meta[itemprop='price']")
    if node:
        val = (node.get("content") or node.get_text(" ", strip=True) or "").strip()
        money = _parse_money(val)
        if money:
            return money, "microdata"

    for sc in soup.select("script[type='application/ld+json']"):
        raw = sc.string or sc.get_text(separator="", strip=True) or ""
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if not isinstance(obj, dict):
                continue
            if obj.get("@type") in ("Product", "Offer", "AggregateOffer"):
                offers = obj.get("offers")
                if isinstance(offers, dict):
                    price = offers.get("price")
                    money = _parse_money(str(price) if price is not None else "")
                    if money:
                        return money, "jsonld"
                elif isinstance(offers, list):
                    for off in offers:
                        if isinstance(off, dict) and off.get("price"):
                            money = _parse_money(str(off["price"]))
                            if money:
                                return money, "jsonld"

    # Heuristic: buy-box text
    buybox = soup.find(lambda t: hasattr(t, "get_text") and "Add to cart" in t.get_text(" ", strip=True))
    if buybox:
        money = _parse_money(buybox.get_text(" ", strip=True))
        if money:
            return money, "heuristic-buybox"

    return "N/A", "none"

def _detect_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
    stock_text = ""
    # Explicit “Out of stock / Sold out / Unavailable” text anywhere
    neg = soup.find(string=re.compile(r"\b(Out of stock|Sold out|Unavailable|Currently unavailable)\b", re.I))
    if neg:
        return False, _clean(str(neg))

    # Positive if Add to cart visible (and not obviously disabled)
    html = soup.decode().lower()
    if re.search(r">\s*add to cart\s*<", html) or re.search(r'aria-label="\s*add to cart\s*"', html):
        atc = soup.find("button", string=re.compile(r"add to cart", re.I))
        if atc:
            disabled_attr = (atc.get("disabled") or "").lower()
            aria_disabled = (atc.get("aria-disabled") or "").lower()
            cls = atc.get("class") or []
            cls_str = " ".join(cls) if isinstance(cls, list) else str(cls)
            if disabled_attr == "true" or aria_disabled == "true" or re.search(r"\bdisabled\b", cls_str, re.I):
                return False, "Add to cart disabled"
        return True, "Add to cart available"

    # Try stock message node (best-effort)
    node = soup.select_one(".stock-message-text, [data-testid*='stock']")
    if node:
        stock_text = _clean(node.get_text(" ", strip=True))

    return None, stock_text

def _extract_description(soup: BeautifulSoup) -> str:
    """
    Capture the lead paragraph(s) ABOVE the bullets + then the bullets.
    If not present, fall back to meta/JSON-LD.
    """
    cont = None
    for sel in [
        "div.product-description",
        "section[aria-label='Product Description']",
        "[data-testid*='description']",
        "div[class*='description']",
    ]:
        cont = soup.select_one(sel)
        if cont:
            break

    intro_paras: List[str] = []
    bullets: List[str] = []

    if cont:
        # Gather paragraphs until the first <ul> (intro block above bullets)
        first_ul = cont.find("ul")
        if first_ul:
            # paragraphs that appear before first <ul>
            for p in cont.find_all("p", recursive=True):
                if p.find_parent("ul"):
                    continue
                # stop collecting once we pass the first UL in document order
                # by checking if this <p> appears after the UL
                if p.sourceline and first_ul.sourceline and p.sourceline > first_ul.sourceline:
                    continue
                t = _clean(p.get_text(" ", strip=True))
                if t:
                    intro_paras.append(t)
            # bullets from that first UL (and immediate siblings ULs)
            ul = first_ul
            while ul and ul.name == "ul":
                for li in ul.select("li"):
                    t = _clean(li.get_text(" ", strip=True))
                    if t:
                        bullets.append(f"• {t}")
                ul = ul.find_next_sibling(lambda n: n.name == "ul")
        else:
            # No ULs—just collect meaningful paragraphs
            for p in cont.find_all("p", recursive=True):
                t = _clean(p.get_text(" ", strip=True))
                if t:
                    intro_paras.append(t)

    # Compose description: intro paragraphs first, then bullets
    parts: List[str] = []
    if intro_paras:
        # keep first 1–2 paras to avoid overly long blobs
        head = "\n\n".join(intro_paras[:2])
        if len(head) > 40:
            parts.append(head)
    if bullets:
        parts.append("\n".join(bullets))

    if parts:
        return "\n\n".join(parts).strip()

    # Meta description fallback
    meta = soup.select_one("meta[name='description']")
    if meta and meta.get("content"):
        txt = _clean(meta["content"])
        if txt:
            return txt

    # JSON-LD Product.description
    best = ""
    for sc in soup.select("script[type='application/ld+json']"):
        raw = sc.string or sc.get_text(separator="", strip=True) or ""
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if isinstance(obj, dict) and obj.get("@type") == "Product":
                desc = _clean(obj.get("description") or "")
                if desc and len(desc) > len(best):
                    best = desc
    return best

# ========= Images =========
def _pick_largest_from_srcset(srcset: str) -> Optional[str]:
    try:
        parts = [p.strip() for p in (srcset or "").split(",") if p.strip()]
        best_url = None
        best_w = -1
        for part in parts:
            m = re.match(r"(.+?)\s+(\d+)w", part)
            if m:
                url = m.group(1).strip()
                w = int(m.group(2))
                if w > best_w:
                    best_w = w
                    best_url = url
            else:
                best_url = part
        return best_url
    except Exception:
        return None

def _normalize_zola_image_url(url: str) -> str:
    try:
        parts = list(urlparse(url.strip()))
        parts[4] = ""  # query
        parts[5] = ""  # fragment
        return urlunparse(parts)
    except Exception:
        return url

def _stable_image_key(url: str) -> str:
    try:
        path = urlparse(url).path or ""
        m = re.search(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", path, re.I)
        if m:
            return m.group(1).lower()
        fname = os.path.basename(path)
        stem = os.path.splitext(fname)[0]
        if stem:
            return stem.lower()
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]

def _collect_images(soup: BeautifulSoup, *, max_images: Optional[int] = None) -> List[str]:
    urls: List[str] = []

    # Thumbnails / gallery imgs
    for sel in [
        ".thumbnail-slider img[src]",
        "[data-testid*='gallery'] img[src]",
        "div[class*='gallery'] img[src]",
    ]:
        for img in soup.select(sel):
            u = img.get("src") or ""
            if u:
                urls.append(u)

    # <source srcset>
    for source in soup.select("source[srcset]"):
        best = _pick_largest_from_srcset(source.get("srcset") or "")
        if best:
            urls.append(best)

    # OpenGraph
    og = soup.select_one("meta[property='og:image']")
    if og and og.get("content"):
        urls.append(og["content"])

    # JSON-LD Product.image
    for sc in soup.select("script[type='application/ld+json']"):
        raw = sc.string or sc.get_text(separator="", strip=True) or ""
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if isinstance(obj, dict) and obj.get("@type") == "Product":
                imgs = obj.get("image")
                if isinstance(imgs, str):
                    urls.append(imgs)
                elif isinstance(imgs, list):
                    for u in imgs:
                        if isinstance(u, str):
                            urls.append(u)

    # Accept filter
    def _accept(u: str) -> bool:
        if not u:
            return False
        hu = u.lower()
        if "images.zola.com" in hu:
            return True
        if not re.search(r"\.(jpg|jpeg|png|webp)(?:$|\?)", hu):
            return False
        if re.search(r"(sprite|icon|badge|logo|placeholder|swatch|thumb|share)", hu):
            return False
        return True

    # Normalize + dedupe by stable key
    seen = set()
    final: List[str] = []
    for u in urls:
        if not _accept(u):
            continue
        nu = _normalize_zola_image_url(u)
        key = _stable_image_key(nu)
        if key in seen:
            continue
        seen.add(key)
        final.append(nu)
        if max_images and len(final) >= max_images:
            break

    return final

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
        for prev in hashes:
            if _hamming(h, prev) <= max_hamming:
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

# ========= Public API (single-arg) =========
def scrape_zola(url: str) -> Dict[str, Any]:
    """
    Fetch via Oxylabs (universal), parse with BS4, download images, pHash-dedupe,
    return the exact schema required.
    """
    html = _post_oxylabs_universal(url)
    soup = BeautifulSoup(html, "lxml")

    # Fields
    name = _extract_name(soup)
    price, price_source = _extract_price_and_src(soup)
    in_stock, stock_text = _detect_stock(soup)
    description = _extract_description(soup)
    images = _collect_images(soup, max_images=None)

    # Save folder (UNIQUE) & raw HTML
    slug = _slug_from_host(url)
    stable_id = _stable_id_from_url(url)
    base_folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}"
    folder = _unique_path(base_folder)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        (folder / "raw_html.html").write_text(html, encoding="utf-8")
    except Exception:
        pass

    # Download + pHash-dedupe
    downloaded = _download_images(images, folder, convert_to_jpg=True, referer=url)
    deduped = _dedupe_downloaded_by_phash(downloaded, max_hamming=4)

    out = {
        "name": name,
        "price": price,
        "price_source": price_source if price != "N/A" else "none",
        "in_stock": in_stock,
        "stock_text": stock_text or "",
        "description": description or "",
        "image_count": len(deduped),
        "images": deduped,
        "folder": str(folder),
        "country_code": None,
        "zip_used": None,
    }
    try:
        (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return out

# # ========= Hardcoded run =========
# if __name__ == "__main__":
#     u = "https://www.zola.com/shop/product/lauraashley_jug_kettle"
#     data = scrape_zola(u)  # <- single argument only
#     print(json.dumps(data, indent=2, ensure_ascii=False))
