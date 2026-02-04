

# # wayfair.py
# # Python 3.10+
# # pip install requests bs4 lxml pillow
# # Version: 3.1 - Fixed validation to not flag out-of-stock products as invalid

# from __future__ import annotations
# import os, re, time, json, html as _html, hashlib, io, random
# from pathlib import Path
# from typing import Optional, Tuple, List, Dict
# from urllib.parse import urldefrag, urlsplit

# import requests
# from bs4 import BeautifulSoup
# from PIL import Image

# __version__ = "3.1"

# # -----------------------------
# # Credentials (env or local module)
# # -----------------------------
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS
# except Exception:
#     OXY_USER = os.getenv("OXYLABS_USERNAME", "")
#     OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")

# if not OXY_USER or not OXY_PASS:
#     raise RuntimeError("Missing Oxylabs credentials. Set OXYLABS_USERNAME/OXYLABS_PASSWORD env or provide oxylabs_secrets.py")

# # -----------------------------
# # Constants
# # -----------------------------
# UA = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
# )
# ACCEPT_LANG_GB = "en-GB,en;q=0.9"
# ACCEPT_HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

# # -----------------------------
# # Paths
# # -----------------------------
# def _root() -> Path:
#     return Path(__file__).resolve().parent

# SAVE_DIR = _root() / "data1"
# DEBUG_DIR = _root() / "debug"

# # -----------------------------
# # Small helpers
# # -----------------------------
# def _clean(s: str | None) -> str:
#     return re.sub(r"\s+", " ", _html.unescape(s or "")).strip()


# def _safe_name(s: str) -> str:
#     n = re.sub(r"[^\w\s\-]", "", (s or "")).strip().replace(" ", "_")
#     return n[:100] or "NA"


# def _short_uid(s: str) -> str:
#     return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:8]


# def _looks_like_html(s: str) -> bool:
#     if not s or len(s) < 300:
#         return False
#     ls = s.lower()
#     return any(k in ls for k in ("<!doctype", "<head", "<body", "<div", "<meta", "<title", "wayfair"))


# def _session_with_retries() -> requests.Session:
#     from urllib3.util.retry import Retry
#     from requests.adapters import HTTPAdapter
#     sess = requests.Session()
#     retry = Retry(
#         total=3,
#         connect=3,
#         read=3,
#         backoff_factor=0.6,
#         status_forcelist=(429, 500, 502, 503, 504),
#         allowed_methods=frozenset(["GET", "POST"])
#     )
#     sess.mount("https://", HTTPAdapter(max_retries=retry))
#     sess.mount("http://", HTTPAdapter(max_retries=retry))
#     return sess


# def _oxylabs_query(payload: dict, timeout: int) -> dict:
#     sess = _session_with_retries()
#     r = sess.post(
#         "https://realtime.oxylabs.io/v1/queries",
#         auth=(OXY_USER, OXY_PASS),
#         json=payload,
#         timeout=timeout,
#     )
#     r.raise_for_status()
#     return r.json()


# def oxy_fetch_html(url: str, *, geo="United Kingdom", accept_lang=ACCEPT_LANG_GB, timeout=90, verbose=False) -> tuple[str, str]:
#     """
#     Robust Oxylabs HTML fetcher with retry logic.
#     Returns (html, final_url).
#     """
#     url, _ = urldefrag(url)
#     base_headers = {
#         "User-Agent": UA,
#         "Accept-Language": accept_lang,
#         "Accept": ACCEPT_HTML,
#         "Cache-Control": "no-cache",
#         "Pragma": "no-cache",
#     }

#     attempts = [
#         ("universal", "html"),
#         ("web",       "html"),
#         ("universal", None),
#     ]

#     last_exc = None
#     consecutive_204 = 0
    
#     for source, render in attempts:
#         session_id = f"wayfair-{int(time.time())}-{random.randint(1000, 9999)}"
        
#         try:
#             payload = {
#                 "source": source,
#                 "url": url,
#                 "geo_location": geo,
#                 "headers": base_headers,
#                 "user_agent_type": "desktop",
#                 "context": [
#                     {"key": "session_id", "value": session_id}
#                 ],
#             }
#             if render:
#                 payload["render"] = render
#                 payload["rendering_wait"] = 3000

#             if verbose:
#                 print(f"  Trying source={source}, render={render}...")

#             data = _oxylabs_query(payload, timeout=timeout)
#             res = (data.get("results") or [{}])[0]
#             content = res.get("content") or ""
#             final_url = res.get("final_url") or res.get("url") or url

#             if not content:
#                 consecutive_204 += 1
#                 if consecutive_204 >= 3:
#                     raise RuntimeError("INVALID_PAGE:HTTP_204_REPEATED")
#                 time.sleep(2)
#                 continue

#             if not _looks_like_html(content) and final_url and final_url != url:
#                 payload2 = dict(payload)
#                 payload2["url"] = final_url
#                 data2 = _oxylabs_query(payload2, timeout=timeout)
#                 res2 = (data2.get("results") or [{}])[0]
#                 content2 = res2.get("content") or ""
#                 if _looks_like_html(content2):
#                     if verbose:
#                         print(f"  ✓ Fetched {len(content2):,} bytes (via redirect)")
#                     return content2, final_url
#                 raise RuntimeError("Oxylabs returned non-HTML on follow")

#             if not _looks_like_html(content):
#                 raise RuntimeError("Oxylabs returned non-HTML (heuristic)")

#             if verbose:
#                 print(f"  ✓ Fetched {len(content):,} bytes")
#             return content, final_url
            
#         except Exception as e:
#             err_str = str(e)
#             if "INVALID_PAGE:" in err_str:
#                 raise
#             last_exc = e
#             time.sleep(1.2)

#     if consecutive_204 >= 2:
#         raise RuntimeError("INVALID_PAGE:FETCH_EXHAUSTED_204")
    
#     raise RuntimeError(f"Oxylabs HTML fetch failed: {last_exc}")


# # -----------------------------
# # Page Validation - DETECT TRULY INVALID PAGES
# # -----------------------------
# def _is_category_or_listing_page(soup: BeautifulSoup, url: str) -> bool:
#     """
#     Detect if the page is a category/listing/search page instead of a product detail page.
#     Returns True if it's NOT a valid product page.
#     """
#     path = urlsplit(url).path.lower()
    
#     # Check 1: URL patterns for non-PDP pages
#     # Category pages: /sb0/, /sb1/, ends with -cXXXXXX.html
#     # PDP pages: /pdp/ in URL
#     if "/sb0/" in path or "/sb1/" in path or "/sb2/" in path:
#         return True
#     if re.search(r"-c\d{5,}\.html$", path):  # Category URL pattern
#         return True
    
#     # Check 2: Results count indicator (e.g., "1,234 Results") - but only in specific containers
#     listing_containers = soup.select("[data-test-id='ProductGrid'], [data-test-id='SearchResults'], .ProductGrid")
#     if listing_containers:
#         for container in listing_containers:
#             text = container.get_text(" ", strip=True).lower()
#             if re.search(r"\d[\d,]*\s*results?\b", text, re.I):
#                 return True
    
#     # Check 3: Multiple product cards (>5 indicates listing, not just "related products")
#     product_cards = soup.select("[data-test-id='ProductCard'], [class*='ProductCard']")
#     if len(product_cards) > 5:
#         return True
    
#     # Check 4: Filter/Sort UI elements WITH product grid (strong indicator of listing page)
#     filter_indicators = [
#         "[data-test-id='FilterSidebar']",
#         "[data-test-id='SortDropdown']",
#     ]
#     has_filters = any(soup.select_one(sel) for sel in filter_indicators)
#     has_product_grid = bool(soup.select_one("[data-test-id='ProductGrid']"))
    
#     if has_filters and has_product_grid:
#         return True
    
#     return False


# def _is_truly_invalid_page(soup: BeautifulSoup, url: str, verbose: bool = False) -> Tuple[bool, str]:
#     """
#     Detect if the page is TRULY invalid (404, removed, etc.)
#     NOT for out-of-stock products - those are valid pages with stock=False.
    
#     Returns (is_invalid, reason)
#     """
#     body_text = _clean(soup.get_text(" ", strip=True)).lower() if soup.body else ""
    
#     # Check 1: 404/Error page indicators
#     title = soup.title.string if soup.title else ""
#     if re.search(r"page not found|404|not found", title, re.I):
#         if verbose:
#             print(f"  ⚠ INVALID: 404 in title")
#         return True, "page_not_found_404"
    
#     # Check 2: Error page containers
#     error_selectors = [
#         ".error-page", 
#         ".page-not-found", 
#         "[data-test-id='ErrorPage']",
#         "[data-test-id='404Page']",
#     ]
#     for sel in error_selectors:
#         if soup.select_one(sel):
#             if verbose:
#                 print(f"  ⚠ INVALID: Error page element found - '{sel}'")
#             return True, f"error_element:{sel}"
    
#     # Check 3: Specific "product removed/discontinued" messages (NOT just out of stock)
#     # These indicate the product listing itself is gone, not just temporarily unavailable
#     removed_patterns = [
#         "this product has been removed",
#         "this product is no longer available for purchase",
#         "this item has been discontinued and removed",
#         "product no longer exists",
#         "we're sorry, this product is no longer available",
#     ]
#     for pattern in removed_patterns:
#         if pattern in body_text:
#             if verbose:
#                 print(f"  ⚠ INVALID: Removed product pattern - '{pattern}'")
#             return True, f"product_removed:{pattern[:30]}"
    
#     # Check 4: Category/listing page check
#     if _is_category_or_listing_page(soup, url):
#         if verbose:
#             print(f"  ⚠ INVALID: Category/listing page detected")
#         return True, "category_or_listing_page"
    
#     return False, "valid"


# def _check_pdp_indicators(soup: BeautifulSoup, verbose: bool = False) -> Tuple[int, dict]:
#     """
#     Check for PDP indicators and return count + details.
#     """
#     indicators = {
#         "price_display": bool(soup.select_one("[data-test-id='PriceDisplay'], [class*='PriceBlock']")),
#         "product_name": bool(soup.select_one("h1[data-rtl-id='listingHeaderNameHeading'], h1[data-test-id='ProductName'], h1")),
#         "media_carousel": bool(soup.select_one("[data-test-id='pdp-mt-thumbnails'], #MediaTrayCarouselWithThumbnailSidebar, [class*='MediaCarousel']")),
#         "product_details": bool(soup.select_one("[data-test-id='ProductDetails'], [class*='ProductDetails'], [class*='ProductInfo']")),
#         "product_images": bool(soup.select("img[src*='assets.wfcdn.com']")),
#     }
    
#     # Also check for add to cart OR out of stock message (both indicate valid PDP)
#     has_add_cart = bool(soup.select_one("[data-test-id='AddToCartButton'], [class*='AddToCart']"))
#     has_oos_message = bool(re.search(r"out of stock|sold out|currently unavailable", 
#                                       soup.get_text(" ", strip=True), re.I))
#     indicators["cart_or_stock_info"] = has_add_cart or has_oos_message
    
#     count = sum(indicators.values())
    
#     if verbose:
#         print(f"  PDP indicators ({count}/6): {indicators}")
    
#     return count, indicators


# def _is_valid_pdp(soup: BeautifulSoup, url: str, verbose: bool = False) -> Tuple[bool, str]:
#     """
#     Validate if the page is a legitimate Product Detail Page.
    
#     IMPORTANT: Out-of-stock products are VALID pages, just with in_stock=False.
#     Only truly removed/404/category pages should be marked invalid.
    
#     Returns (is_valid, reason_if_invalid)
#     """
#     # First: Check for truly invalid pages (404, removed, category)
#     is_invalid, invalid_reason = _is_truly_invalid_page(soup, url, verbose=verbose)
#     if is_invalid:
#         return False, invalid_reason
    
#     # Second: Check PDP indicators
#     indicator_count, indicators = _check_pdp_indicators(soup, verbose=verbose)
    
#     # If we have 3+ PDP indicators, it's a valid product page
#     if indicator_count >= 3:
#         if verbose:
#             print(f"  ✓ Valid PDP detected ({indicator_count}/6 indicators)")
#         return True, ""
    
#     # If URL contains /pdp/ it should be a product page
#     if "/pdp/" in url.lower():
#         # Even with few indicators, /pdp/ URL with ANY product info is likely valid
#         if indicator_count >= 1:
#             if verbose:
#                 print(f"  ✓ PDP URL with {indicator_count} indicators - accepting as valid")
#             return True, ""
#         # /pdp/ URL with zero indicators - product likely removed
#         if verbose:
#             print(f"  ⚠ PDP URL but no product indicators found")
#         return False, "pdp_url_no_content"
    
#     # For non-/pdp/ URLs, be more lenient - could be alternate URL format
#     if indicator_count >= 2:
#         if verbose:
#             print(f"  ✓ Accepting page with {indicator_count} PDP indicators")
#         return True, ""
    
#     if verbose:
#         print(f"  ⚠ Only {indicator_count} PDP indicators - may not be a product page")
#     return False, f"insufficient_pdp_indicators:{indicator_count}"


# def _create_invalid_result(url: str, reason: str) -> Dict:
#     """
#     Create a result dict for invalid/unavailable products.
#     """
#     return {
#         "name": "INVALID LINK - Product removed or no longer available",
#         "price": "N/A",
#         "in_stock": False,
#         "stock_text": reason,
#         "description": "",
#         "image_count": 0,
#         "image_urls": [],
#         "images": [],
#         "folder": None,
#         "url": url,
#         "mode": "invalid",
#         "is_invalid": True,
#         "invalid_reason": reason,
#     }


# # -----------------------------
# # JSON-LD helpers
# # -----------------------------
# def _iter_jsonld(soup: BeautifulSoup):
#     for tag in soup.select("script[type='application/ld+json']"):
#         txt = tag.get_text(strip=False)
#         if not txt:
#             continue
#         try:
#             data = json.loads(txt)
#             yield data
#         except Exception:
#             try:
#                 for part in re.split(r"\n(?=\s*{)", txt.strip()):
#                     part = part.strip()
#                     if part:
#                         yield json.loads(part)
#             except Exception:
#                 continue


# def _jsonld_find_products(data) -> List[dict]:
#     found = []
#     stack = [data]
#     while stack:
#         cur = stack.pop()
#         if isinstance(cur, dict):
#             if cur.get("@type") == "Product":
#                 found.append(cur)
#             for v in cur.values():
#                 if isinstance(v, (dict, list)):
#                     stack.append(v)
#         elif isinstance(cur, list):
#             for v in cur:
#                 if isinstance(v, (dict, list)):
#                     stack.append(v)
#     return found


# def _jsonld_availability_from_offers(offers) -> Optional[bool]:
#     if not offers:
#         return None
#     lst = offers if isinstance(offers, list) else [offers]
#     for off in lst:
#         if not isinstance(off, dict):
#             continue
#         avail = str(off.get("availability") or off.get("itemAvailability") or "")
#         if re.search(r"InStock", avail, re.I):
#             return True
#         if re.search(r"OutOfStock|SoldOut|PreOrder|Discontinued", avail, re.I):
#             return False
#     return None


# # -----------------------------
# # Wayfair image URL normalization
# # -----------------------------
# def _wf_to_hires(u: str, size: int = 1600) -> str:
#     if not u:
#         return u
#     u = u.replace(" ", "%20")
#     u = re.sub(r"/resize-h\d+-w\d+%5Ecompr-r\d+/", f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
#     u = re.sub(r"/resize-h\d+-w\d+\^compr-r\d+/",  f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
#     if "/resize-" not in u:
#         u = re.sub(r"(https://assets\.wfcdn\.com/im/[^/]+/)",
#                    rf"\1resize-h{size}-w{size}%5Ecompr-r85/", u)
#     return u


# def _img_dedup_key(u: str) -> str:
#     m = re.search(r"/(\d{8,10})/[^/]+\.(jpg|jpeg|png|webp)", u, re.I)
#     if m:
#         return m.group(1)
    
#     u = re.sub(r"/resize-h\d+-w\d+(?:%5E|\^)compr-r\d+/", "/", u)
#     u = re.sub(r"/im/\d+/", "/im/X/", u)
#     return re.sub(r"[?].*$", "", u)


# # -----------------------------
# # Core parsing from HTML
# # -----------------------------
# def _parse_name(soup: BeautifulSoup) -> str:
#     h = soup.select_one("h1[data-rtl-id='listingHeaderNameHeading']")
#     if h:
#         t = _clean(h.get_text(" ", strip=True))
#         if t:
#             return t

#     # Try any h1
#     h1 = soup.select_one("h1")
#     if h1:
#         t = _clean(h1.get_text(" ", strip=True))
#         if t and len(t) > 3:
#             return t

#     for data in _iter_jsonld(soup):
#         for prod in _jsonld_find_products(data):
#             nm = prod.get("name")
#             if isinstance(nm, str) and nm.strip():
#                 return _clean(nm)

#     og = soup.find("meta", attrs={"property": "og:title"})
#     if og and og.get("content"):
#         return _clean(og["content"])

#     if soup.title and soup.title.string:
#         return _clean(soup.title.string)

#     return "N/A"


# def _parse_price(soup: BeautifulSoup) -> str:
#     price_host = soup.select_one("[data-test-id='PriceDisplay']")
#     if price_host:
#         txt = _clean(price_host.get_text(" ", strip=True))
#         if txt:
#             return txt

#     # Look for price in product-specific containers
#     price_containers = soup.select("[data-test-id='ProductPrice'], .product-price, [class*='PriceBlock']")
#     for container in price_containers:
#         cand = container.find(string=re.compile(r"£\s?\d[\d,]*\.?\d{0,2}"))
#         if cand:
#             return _clean(cand)

#     # Try to find any price on page
#     price_match = re.search(r"£\s?\d[\d,]*\.\d{2}", soup.get_text(" ", strip=True))
#     if price_match:
#         return price_match.group(0)

#     for data in _iter_jsonld(soup):
#         for prod in _jsonld_find_products(data):
#             offers = prod.get("offers")
#             if isinstance(offers, dict):
#                 price = offers.get("price") or offers.get("lowPrice")
#                 cur = offers.get("priceCurrency", "")
#                 if price:
#                     return f"£{price}" if cur == "GBP" else f"{price} {cur}".strip()
#             elif isinstance(offers, list):
#                 for o in offers:
#                     if not isinstance(o, dict):
#                         continue
#                     price = o.get("price") or o.get("lowPrice")
#                     cur = o.get("priceCurrency", "")
#                     if price:
#                         return f"£{price}" if cur == "GBP" else f"{price} {cur}".strip()

#     return "N/A"


# def _parse_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
#     """
#     Parse stock status. Returns (in_stock, stock_text).
    
#     IMPORTANT: Out-of-stock is a valid status, not an error!
#     """
#     page_text = soup.get_text(" ", strip=True)
    
#     # Check for out of stock indicators
#     oos_patterns = [
#         (r"\bout of stock\b", "out_of_stock"),
#         (r"\bsold out\b", "sold_out"),
#         (r"\bcurrently unavailable\b", "currently_unavailable"),
#         (r"\bnot available\b", "not_available"),
#         (r"\bdiscontinued\b", "discontinued"),
#     ]
    
#     for pattern, status in oos_patterns:
#         if re.search(pattern, page_text, re.I):
#             return False, status

#     # Check for in-stock indicators
#     if re.search(r"\bAdd to (Cart|Basket)\b", page_text, re.I):
#         # Make sure it's not disabled
#         add_btn = soup.select_one("[data-test-id='AddToCartButton']")
#         if add_btn:
#             if add_btn.get("disabled") or "disabled" in (add_btn.get("class") or []):
#                 return False, "add_to_cart_disabled"
#             return True, "add_to_cart_available"
#         return True, "add_to_cart_text"

#     if re.search(r"\bin stock\b", page_text, re.I):
#         return True, "in_stock_text"

#     # Check JSON-LD
#     for data in _iter_jsonld(soup):
#         for prod in _jsonld_find_products(data):
#             avail = _jsonld_availability_from_offers(prod.get("offers"))
#             if avail is not None:
#                 return avail, "jsonld"

#     return None, "unknown"


# def _parse_description(soup: BeautifulSoup) -> str:
#     def _clean_text(t: str) -> str:
#         t = _html.unescape(t or "")
#         t = t.replace("\r", "")
#         t = re.sub(r"[ \t]+", " ", t)
#         t = re.sub(r"\n{3,}", "\n\n", t)
#         return t.strip()

#     def _looks_generic(s: str) -> bool:
#         return bool(re.search(r"you'?ll love .* at wayfair", s, re.I))

#     for box in soup.select('[data-hb-id="BoxV3"]'):
#         st = (box.get("style") or "").lower()
#         if "pre-line" in st:
#             txt = _clean_text(box.get_text("\n", strip=True))
#             if txt and len(txt) > 120:
#                 return txt

#     features = []
#     for p in soup.select("p[data-hb-id='Text']"):
#         if re.search(r"\bFeatures\b", p.get_text(" ", strip=True), re.I):
#             nxt = p.find_next("ul")
#             if nxt:
#                 items = [_clean_text(li.get_text(" ", strip=True)) for li in nxt.select("li")]
#                 items = [i for i in items if i]
#                 if items:
#                     features.append("Features:\n- " + "\n- ".join(items))
#             break

#     best = ""
#     for data in _iter_jsonld(soup):
#         for prod in _jsonld_find_products(data):
#             desc = prod.get("description")
#             if isinstance(desc, str):
#                 cand = _clean_text(desc)
#                 if cand and not _looks_generic(cand) and len(cand) > len(best):
#                     best = cand
#     if best:
#         if features:
#             return best + "\n\n" + "\n\n".join(features)
#         return best

#     md = soup.find("meta", attrs={"name": "description"})
#     if md and md.get("content"):
#         cand = _clean_text(md["content"])
#         if cand and not _looks_generic(cand):
#             if features:
#                 return cand + "\n\n" + "\n\n".join(features)
#             return cand

#     if features:
#         return "\n\n".join(features)

#     return "N/A"


# def _parse_images(soup: BeautifulSoup) -> List[str]:
#     from typing import Tuple
#     ordered: List[Tuple[int, str]] = []
#     seen_ids: set[str] = set()

#     for btn in soup.select("[data-test-id='pdp-mt-thumbnails'] button[aria-label]"):
#         lab = btn.get("aria-label") or ""
#         m = re.search(r"(\d+)\s+of\s+(\d+)", lab, re.I)
#         if not m:
#             continue
#         order = int(m.group(1))
        
#         img = btn.find("img")
#         if not img:
#             continue
            
#         src = None
#         srcset = img.get("srcset") or ""
#         if srcset:
#             parts = [p.strip().split()[0] for p in srcset.split(",") if p.strip()]
#             if parts:
#                 src = parts[-1]
        
#         if not src:
#             src = img.get("src") or ""
        
#         if not src:
#             continue
        
#         img_id = _img_dedup_key(src)
#         if img_id in seen_ids:
#             continue
#         seen_ids.add(img_id)
        
#         ordered.append((order, src))

#     ordered.sort(key=lambda t: t[0])
    
#     images: List[str] = []
#     for _, u in ordered:
#         hu = _wf_to_hires(u, size=1600)
#         images.append(hu)
    
#     if not images:
#         for img in soup.select("#MediaTrayCarouselWithThumbnailSidebar img, [data-test-id='pdp-mt-d-mainImageCarousel'] img"):
#             src = img.get("src") or img.get("data-src") or ""
#             if src and "assets.wfcdn.com/im/" in src:
#                 img_id = _img_dedup_key(src)
#                 if img_id not in seen_ids:
#                     seen_ids.add(img_id)
#                     images.append(_wf_to_hires(src, size=1600))
    
#     # Fallback: any Wayfair CDN images
#     if not images:
#         for img in soup.select("img[src*='assets.wfcdn.com']"):
#             src = img.get("src") or ""
#             if src:
#                 img_id = _img_dedup_key(src)
#                 if img_id not in seen_ids:
#                     seen_ids.add(img_id)
#                     images.append(_wf_to_hires(src, size=1600))
    
#     return images


# # -----------------------------
# # Downloader
# # -----------------------------
# def _download_images_jpg(urls: List[str], referer: str, folder: Path, base_slug: str, verbose: bool = True) -> List[str]:
#     folder.mkdir(parents=True, exist_ok=True)
#     out: List[str] = []
#     sess = _session_with_retries()
#     sess.headers.update({
#         "User-Agent": UA,
#         "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
#         "Accept-Language": ACCEPT_LANG_GB,
#         "Referer": referer,
#     })
#     for i, u in enumerate(urls, 1):
#         try:
#             r = sess.get(u, timeout=30)
#             if not r.ok or not r.content:
#                 continue

#             im = Image.open(io.BytesIO(r.content))
#             if im.mode in ("RGBA", "P"):
#                 im = im.convert("RGB")
#             elif im.mode != "RGB":
#                 im = im.convert("RGB")

#             path = folder / f"{base_slug}_{i:02d}.jpg"
#             im.save(path, format="JPEG", quality=92, optimize=True)
#             out.append(str(path))
            
#             if verbose:
#                 print(f"  ✓ image {i}")
                
#         except Exception as e:
#             if verbose:
#                 print(f"  ✗ image {i}: {e}")
#             continue
#     return out


# # -----------------------------
# # Public API
# # -----------------------------
# def scrape_wayfair_product(url: str, save_dir: Path | None = None, *, geo="United Kingdom", verbose: bool = True) -> dict:
#     """
#     Fetch Wayfair PDP via Oxylabs and return parsed data + downloaded JPG images.
    
#     IMPORTANT: Out-of-stock products are returned as valid with in_stock=False.
#     Only truly removed/404/category pages are marked as invalid.
#     """
#     if verbose:
#         print(f"Fetching {url}...")
    
#     if save_dir is None:
#         save_dir = SAVE_DIR
#     save_dir = Path(save_dir)
#     save_dir.mkdir(parents=True, exist_ok=True)
#     DEBUG_DIR.mkdir(parents=True, exist_ok=True)

#     # Fetch HTML
#     try:
#         html_doc, final_url = oxy_fetch_html(url, geo=geo, timeout=90, verbose=verbose)
#     except RuntimeError as e:
#         err_str = str(e)
#         if "INVALID_PAGE:" in err_str:
#             reason = err_str.split("INVALID_PAGE:")[-1]
#             if verbose:
#                 print(f"✗ Invalid link detected (fetch failed): {reason}")
#             return _create_invalid_result(url, f"fetch_failed:{reason}")
        
#         if verbose:
#             print(f"✗ Failed to fetch URL: {e}")
#         return _create_invalid_result(url, f"fetch_failed:{str(e)}")

#     soup = BeautifulSoup(html_doc, "lxml")

#     # Validate page
#     is_valid, invalid_reason = _is_valid_pdp(soup, url, verbose=verbose)
#     if not is_valid:
#         if verbose:
#             print(f"✗ Invalid page detected: {invalid_reason}")
#         return _create_invalid_result(url, invalid_reason)

#     # Parse product data
#     name = _parse_name(soup)
#     price = _parse_price(soup)
#     in_stock, stock_text = _parse_stock(soup)
#     description = _parse_description(soup)

#     if verbose:
#         print(f"  Name: {name}")
#         print(f"  Price: {price}")
#         print(f"  In Stock: {in_stock} ({stock_text})")

#     # Post-extraction validation - only fail if we got NOTHING
#     if name == "N/A" and price == "N/A" and description == "N/A":
#         if verbose:
#             print("✗ Could not extract any product data")
#         return _create_invalid_result(url, "no_product_data_extracted")

#     name_slug = _safe_name(name)
#     uid = _short_uid(final_url)
#     base_slug = f"{name_slug}_{uid}"

#     images = _parse_images(soup)
    
#     if verbose:
#         print(f"  Images found: {len(images)}")

#     folder = save_dir / base_slug
    
#     if images:
#         if verbose:
#             print(f"\nDownloading {len(images)} images...")
#         downloaded = _download_images_jpg(images, referer=final_url, folder=folder, base_slug=base_slug, verbose=verbose)
#     else:
#         downloaded = []

#     return {
#         "name": name,
#         "price": price,
#         "in_stock": in_stock,
#         "stock_text": stock_text,
#         "description": description,
#         "image_count": len(downloaded),
#         "image_urls": images,
#         "images": downloaded,
#         "folder": str(folder),
#         "url": final_url,
#         "mode": "oxylabs(html)+direct(images_jpg_only)",
#         "is_invalid": False,
#         "invalid_reason": None,
#     }


# # -----------------------------
# # CLI test
# # -----------------------------
# if __name__ == "__main__":
#     import sys
    
#     if len(sys.argv) > 1:
#         TEST_URL = sys.argv[1]
#     else:
#         TEST_URL = "https://www.wayfair.co.uk/kitchenware-tableware/pdp/laura-ashley-vq-laura-ashley-china-rose-5-speed-hand-mixer-laas1107.html"
    
#     print(f"\n{'='*60}")
#     print(f"Testing: {TEST_URL}")
#     print(f"{'='*60}\n")
    
#     try:
#         data = scrape_wayfair_product(TEST_URL, verbose=True)
#         print("\n" + "=" * 60)
#         print("RESULTS:")
#         print("=" * 60)
#         print(json.dumps(data, indent=2, ensure_ascii=False))
#     except Exception as e:
#         print(f"\n✗ ERROR: {e}")





# wayfair.py
# Python 3.10+
# pip install requests bs4 lxml pillow
# Version: 3.2 - Improved invalid link detection for category redirects

from __future__ import annotations
import os, re, time, json, html as _html, hashlib, io, random
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from urllib.parse import urldefrag, urlsplit

import requests
from bs4 import BeautifulSoup
from PIL import Image

__version__ = "3.2"

# -----------------------------
# Credentials (env or local module)
# -----------------------------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")

if not OXY_USER or not OXY_PASS:
    raise RuntimeError("Missing Oxylabs credentials. Set OXYLABS_USERNAME/OXYLABS_PASSWORD env or provide oxylabs_secrets.py")

# -----------------------------
# Constants
# -----------------------------
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
ACCEPT_LANG_GB = "en-GB,en;q=0.9"
ACCEPT_HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

# -----------------------------
# Paths
# -----------------------------
def _root() -> Path:
    return Path(__file__).resolve().parent

SAVE_DIR = _root() / "data1"
DEBUG_DIR = _root() / "debug"

# -----------------------------
# Small helpers
# -----------------------------
def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", _html.unescape(s or "")).strip()


def _safe_name(s: str) -> str:
    n = re.sub(r"[^\w\s\-]", "", (s or "")).strip().replace(" ", "_")
    return n[:100] or "NA"


def _short_uid(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:8]


def _looks_like_html(s: str) -> bool:
    if not s or len(s) < 300:
        return False
    ls = s.lower()
    return any(k in ls for k in ("<!doctype", "<head", "<body", "<div", "<meta", "<title", "wayfair"))


def _session_with_retries() -> requests.Session:
    from urllib3.util.retry import Retry
    from requests.adapters import HTTPAdapter
    sess = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"])
    )
    sess.mount("https://", HTTPAdapter(max_retries=retry))
    sess.mount("http://", HTTPAdapter(max_retries=retry))
    return sess


def _oxylabs_query(payload: dict, timeout: int) -> dict:
    sess = _session_with_retries()
    r = sess.post(
        "https://realtime.oxylabs.io/v1/queries",
        auth=(OXY_USER, OXY_PASS),
        json=payload,
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def oxy_fetch_html(url: str, *, geo="United Kingdom", accept_lang=ACCEPT_LANG_GB, timeout=90, verbose=False) -> tuple[str, str]:
    """
    Robust Oxylabs HTML fetcher with retry logic.
    Returns (html, final_url).
    """
    url, _ = urldefrag(url)
    base_headers = {
        "User-Agent": UA,
        "Accept-Language": accept_lang,
        "Accept": ACCEPT_HTML,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    attempts = [
        ("universal", "html"),
        ("web",       "html"),
        ("universal", None),
    ]

    last_exc = None
    consecutive_204 = 0
    
    for source, render in attempts:
        session_id = f"wayfair-{int(time.time())}-{random.randint(1000, 9999)}"
        
        try:
            payload = {
                "source": source,
                "url": url,
                "geo_location": geo,
                "headers": base_headers,
                "user_agent_type": "desktop",
                "context": [
                    {"key": "session_id", "value": session_id}
                ],
            }
            if render:
                payload["render"] = render
                payload["rendering_wait"] = 3000

            if verbose:
                print(f"  Trying source={source}, render={render}...")

            data = _oxylabs_query(payload, timeout=timeout)
            res = (data.get("results") or [{}])[0]
            content = res.get("content") or ""
            final_url = res.get("final_url") or res.get("url") or url

            if not content:
                consecutive_204 += 1
                if consecutive_204 >= 3:
                    raise RuntimeError("INVALID_PAGE:HTTP_204_REPEATED")
                time.sleep(2)
                continue

            if not _looks_like_html(content) and final_url and final_url != url:
                payload2 = dict(payload)
                payload2["url"] = final_url
                data2 = _oxylabs_query(payload2, timeout=timeout)
                res2 = (data2.get("results") or [{}])[0]
                content2 = res2.get("content") or ""
                if _looks_like_html(content2):
                    if verbose:
                        print(f"  ✓ Fetched {len(content2):,} bytes (via redirect)")
                    return content2, final_url
                raise RuntimeError("Oxylabs returned non-HTML on follow")

            if not _looks_like_html(content):
                raise RuntimeError("Oxylabs returned non-HTML (heuristic)")

            if verbose:
                print(f"  ✓ Fetched {len(content):,} bytes")
            return content, final_url
            
        except Exception as e:
            err_str = str(e)
            if "INVALID_PAGE:" in err_str:
                raise
            last_exc = e
            time.sleep(1.2)

    if consecutive_204 >= 2:
        raise RuntimeError("INVALID_PAGE:FETCH_EXHAUSTED_204")
    
    raise RuntimeError(f"Oxylabs HTML fetch failed: {last_exc}")


# -----------------------------
# Page Validation - DETECT TRULY INVALID PAGES
# -----------------------------
def _is_category_or_listing_page(soup: BeautifulSoup, url: str, verbose: bool = False) -> Tuple[bool, str]:
    """
    Detect if the page is a category/listing/search page instead of a product detail page.
    Returns (is_listing, reason) tuple.
    """
    path = urlsplit(url).path.lower()
    body_text = _clean(soup.get_text(" ", strip=True)) if soup.body else ""
    
    # Check 1: URL patterns for non-PDP pages
    if "/sb0/" in path or "/sb1/" in path or "/sb2/" in path:
        if verbose:
            print(f"  ⚠ Category URL pattern detected: /sbX/")
        return True, "category_url_pattern"
    if re.search(r"-c\d{5,}\.html$", path):
        if verbose:
            print(f"  ⚠ Category URL pattern detected: -cXXXXX.html")
        return True, "category_url_pattern"
    
    # Check 2: "X Items" count indicator - STRONG indicator of listing page
    # Look for patterns like "164 Items", "1,234 Items", "50 Results"
    items_match = re.search(r"(\d[\d,]*)\s*Items?\b", body_text, re.I)
    if items_match:
        count = int(items_match.group(1).replace(",", ""))
        if count > 1:  # More than 1 item = listing page
            if verbose:
                print(f"  ⚠ Listing page detected: '{items_match.group(0)}'")
            return True, f"listing_page:{count}_items"
    
    results_match = re.search(r"(\d[\d,]*)\s*Results?\b", body_text, re.I)
    if results_match:
        count = int(results_match.group(1).replace(",", ""))
        if count > 1:
            if verbose:
                print(f"  ⚠ Search results page detected: '{results_match.group(0)}'")
            return True, f"search_results:{count}_results"
    
    # Check 3: H1 is a generic category name (not a product name)
    h1 = soup.select_one("h1")
    if h1:
        h1_text = _clean(h1.get_text()).lower()
        # Generic category names
        category_keywords = [
            "mixers", "attachments", "kettles", "toasters", "blenders",
            "coffee makers", "coffee machines", "microwaves", "ovens",
            "refrigerators", "dishwashers", "washing machines",
            "sofas", "chairs", "tables", "beds", "mattresses",
            "rugs", "curtains", "lighting", "lamps",
            "storage", "shelving", "desks", "wardrobes",
            "bathroom", "kitchen", "bedroom", "living room",
            "outdoor", "garden", "patio",
        ]
        for keyword in category_keywords:
            # Check if H1 IS the category or starts with it (e.g., "Mixers & Attachments")
            if h1_text == keyword or h1_text.startswith(keyword + " ") or f"& {keyword}" in h1_text:
                # Verify it's not a specific product by checking for item count nearby
                if items_match or results_match:
                    if verbose:
                        print(f"  ⚠ Generic category H1 detected: '{h1_text}'")
                    return True, f"category_title:{h1_text[:30]}"
    
    # Check 4: Product grid/listing elements
    product_grid = soup.select_one("[data-test-id='ProductGrid'], [class*='ProductGrid'], [class*='product-grid']")
    if product_grid:
        # Count product cards in the grid
        cards = product_grid.select("[data-test-id='ProductCard'], [class*='ProductCard']")
        if len(cards) >= 3:
            if verbose:
                print(f"  ⚠ Product grid detected with {len(cards)} cards")
            return True, f"product_grid:{len(cards)}_cards"
    
    # Check 5: Multiple product cards anywhere on page (>10 is definitely a listing)
    all_cards = soup.select("[data-test-id='ProductCard'], [class*='ProductCard']")
    if len(all_cards) > 10:
        if verbose:
            print(f"  ⚠ Multiple product cards detected: {len(all_cards)}")
        return True, f"multiple_product_cards:{len(all_cards)}"
    
    # Check 6: Filter/Sort UI with product count
    has_filters = bool(soup.select_one("[data-test-id='FilterSidebar'], [class*='FilterSidebar'], [class*='filter-sidebar']"))
    has_sort = bool(soup.select_one("[data-test-id='SortDropdown'], [class*='SortDropdown'], [class*='sort-dropdown']"))
    if (has_filters or has_sort) and (items_match or results_match or len(all_cards) > 5):
        if verbose:
            print(f"  ⚠ Filter/Sort UI with listing content detected")
        return True, "filter_sort_with_listing"
    
    return False, "valid"


def _is_truly_invalid_page(soup: BeautifulSoup, url: str, verbose: bool = False) -> Tuple[bool, str]:
    """
    Detect if the page is TRULY invalid (404, removed, etc.)
    NOT for out-of-stock products - those are valid pages with stock=False.
    
    Returns (is_invalid, reason)
    """
    body_text = _clean(soup.get_text(" ", strip=True)).lower() if soup.body else ""
    
    # Check 1: 404/Error page indicators
    title = soup.title.string if soup.title else ""
    if re.search(r"page not found|404|not found", title, re.I):
        if verbose:
            print(f"  ⚠ INVALID: 404 in title")
        return True, "page_not_found_404"
    
    # Check 2: Error page containers
    error_selectors = [
        ".error-page", 
        ".page-not-found", 
        "[data-test-id='ErrorPage']",
        "[data-test-id='404Page']",
    ]
    for sel in error_selectors:
        if soup.select_one(sel):
            if verbose:
                print(f"  ⚠ INVALID: Error page element found - '{sel}'")
            return True, f"error_element:{sel}"
    
    # Check 3: Specific "product removed/discontinued" messages
    removed_patterns = [
        "this product has been removed",
        "this product is no longer available for purchase",
        "this item has been discontinued and removed",
        "product no longer exists",
        "we're sorry, this product is no longer available",
    ]
    for pattern in removed_patterns:
        if pattern in body_text:
            if verbose:
                print(f"  ⚠ INVALID: Removed product pattern - '{pattern}'")
            return True, f"product_removed:{pattern[:30]}"
    
    # Check 4: Category/listing page check
    is_listing, listing_reason = _is_category_or_listing_page(soup, url, verbose=verbose)
    if is_listing:
        return True, listing_reason
    
    return False, "valid"


def _check_pdp_indicators(soup: BeautifulSoup, verbose: bool = False) -> Tuple[int, dict]:
    """
    Check for PDP-specific indicators and return count + details.
    These should be elements that ONLY appear on product detail pages, not category pages.
    """
    indicators = {
        # Specific product price display (not category price ranges)
        "specific_price": bool(soup.select_one("[data-test-id='PriceDisplay'] [class*='SFPrice'], [data-test-id='ProductPrice']")),
        # Product-specific name heading (check it's not a category)
        "product_heading": False,  # Will check below
        # Media carousel with thumbnails (PDPs have this, categories don't)
        "media_carousel": bool(soup.select_one("[data-test-id='pdp-mt-thumbnails'], #MediaTrayCarouselWithThumbnailSidebar")),
        # Product details/specs section
        "product_specs": bool(soup.select_one("[data-test-id='ProductDetails'], [data-test-id='ProductSpecs']")),
        # Add to cart button (not just text)
        "add_to_cart_btn": bool(soup.select_one("[data-test-id='AddToCartButton'], button[class*='AddToCart']")),
        # Product SKU/item number
        "product_sku": bool(soup.select_one("[data-test-id='ProductSku'], [class*='ProductSku']")),
    }
    
    # Check if H1 looks like a specific product name (not a category)
    h1 = soup.select_one("h1")
    if h1:
        h1_text = _clean(h1.get_text())
        # Product names typically have brand names, model numbers, or specific descriptors
        # Categories are generic like "Mixers", "Kettles", etc.
        looks_like_product = (
            len(h1_text) > 20 or  # Longer names are usually products
            re.search(r"\b(vq|laura ashley|morphy richards|russell hobbs|delonghi|breville|smeg|kitchenaid)\b", h1_text, re.I) or  # Brand names
            re.search(r"\b\d+[a-z]*\b", h1_text, re.I) or  # Model numbers
            re.search(r"\b(hand mixer|stand mixer|food processor|coffee maker|espresso|toaster oven)\b", h1_text, re.I)  # Specific product types
        )
        # Check it's NOT a category
        not_category = not re.search(r"^\s*(mixers?|attachments?|kettles?|toasters?|blenders?)\s*(&|$)", h1_text, re.I)
        indicators["product_heading"] = looks_like_product and not_category
    
    count = sum(indicators.values())
    
    if verbose:
        print(f"  PDP indicators ({count}/6): {indicators}")
    
    return count, indicators


def _is_valid_pdp(soup: BeautifulSoup, url: str, verbose: bool = False) -> Tuple[bool, str]:
    """
    Validate if the page is a legitimate Product Detail Page.
    
    IMPORTANT: Out-of-stock products are VALID pages, just with in_stock=False.
    Only truly removed/404/category pages should be marked invalid.
    
    Returns (is_valid, reason_if_invalid)
    """
    # First: Check for truly invalid pages (404, removed, category)
    is_invalid, invalid_reason = _is_truly_invalid_page(soup, url, verbose=verbose)
    if is_invalid:
        return False, invalid_reason
    
    # Second: Check PDP indicators
    indicator_count, indicators = _check_pdp_indicators(soup, verbose=verbose)
    
    # If we have 3+ strong PDP indicators, it's a valid product page
    if indicator_count >= 3:
        if verbose:
            print(f"  ✓ Valid PDP detected ({indicator_count}/6 indicators)")
        return True, ""
    
    # If URL contains /pdp/ it should be a product page
    if "/pdp/" in url.lower():
        # For /pdp/ URLs, require at least media carousel OR add to cart
        if indicators.get("media_carousel") or indicators.get("add_to_cart_btn"):
            if verbose:
                print(f"  ✓ PDP URL with key indicators - accepting as valid")
            return True, ""
        
        # /pdp/ URL with no key PDP indicators - likely redirected to category
        if verbose:
            print(f"  ⚠ PDP URL but missing key product indicators")
        return False, "pdp_url_redirected_to_category"
    
    # For non-/pdp/ URLs, be more strict
    if indicator_count >= 2 and (indicators.get("media_carousel") or indicators.get("add_to_cart_btn")):
        if verbose:
            print(f"  ✓ Accepting page with {indicator_count} PDP indicators including key element")
        return True, ""
    
    if verbose:
        print(f"  ⚠ Only {indicator_count} PDP indicators - not a valid product page")
    return False, f"insufficient_pdp_indicators:{indicator_count}"


def _create_invalid_result(url: str, reason: str) -> Dict:
    """
    Create a result dict for invalid/unavailable products.
    """
    return {
        "name": "INVALID LINK - Product removed or no longer available",
        "price": "N/A",
        "in_stock": False,
        "stock_text": reason,
        "description": "",
        "image_count": 0,
        "image_urls": [],
        "images": [],
        "folder": None,
        "url": url,
        "mode": "invalid",
        "is_invalid": True,
        "invalid_reason": reason,
    }


# -----------------------------
# JSON-LD helpers
# -----------------------------
def _iter_jsonld(soup: BeautifulSoup):
    for tag in soup.select("script[type='application/ld+json']"):
        txt = tag.get_text(strip=False)
        if not txt:
            continue
        try:
            data = json.loads(txt)
            yield data
        except Exception:
            try:
                for part in re.split(r"\n(?=\s*{)", txt.strip()):
                    part = part.strip()
                    if part:
                        yield json.loads(part)
            except Exception:
                continue


def _jsonld_find_products(data) -> List[dict]:
    found = []
    stack = [data]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("@type") == "Product":
                found.append(cur)
            for v in cur.values():
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            for v in cur:
                if isinstance(v, (dict, list)):
                    stack.append(v)
    return found


def _jsonld_availability_from_offers(offers) -> Optional[bool]:
    if not offers:
        return None
    lst = offers if isinstance(offers, list) else [offers]
    for off in lst:
        if not isinstance(off, dict):
            continue
        avail = str(off.get("availability") or off.get("itemAvailability") or "")
        if re.search(r"InStock", avail, re.I):
            return True
        if re.search(r"OutOfStock|SoldOut|PreOrder|Discontinued", avail, re.I):
            return False
    return None


# -----------------------------
# Wayfair image URL normalization
# -----------------------------
def _wf_to_hires(u: str, size: int = 1600) -> str:
    if not u:
        return u
    u = u.replace(" ", "%20")
    u = re.sub(r"/resize-h\d+-w\d+%5Ecompr-r\d+/", f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
    u = re.sub(r"/resize-h\d+-w\d+\^compr-r\d+/",  f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
    if "/resize-" not in u:
        u = re.sub(r"(https://assets\.wfcdn\.com/im/[^/]+/)",
                   rf"\1resize-h{size}-w{size}%5Ecompr-r85/", u)
    return u


def _img_dedup_key(u: str) -> str:
    m = re.search(r"/(\d{8,10})/[^/]+\.(jpg|jpeg|png|webp)", u, re.I)
    if m:
        return m.group(1)
    
    u = re.sub(r"/resize-h\d+-w\d+(?:%5E|\^)compr-r\d+/", "/", u)
    u = re.sub(r"/im/\d+/", "/im/X/", u)
    return re.sub(r"[?].*$", "", u)


# -----------------------------
# Core parsing from HTML
# -----------------------------
def _parse_name(soup: BeautifulSoup) -> str:
    h = soup.select_one("h1[data-rtl-id='listingHeaderNameHeading']")
    if h:
        t = _clean(h.get_text(" ", strip=True))
        if t:
            return t

    h1 = soup.select_one("h1")
    if h1:
        t = _clean(h1.get_text(" ", strip=True))
        if t and len(t) > 3:
            return t

    for data in _iter_jsonld(soup):
        for prod in _jsonld_find_products(data):
            nm = prod.get("name")
            if isinstance(nm, str) and nm.strip():
                return _clean(nm)

    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return _clean(og["content"])

    if soup.title and soup.title.string:
        return _clean(soup.title.string)

    return "N/A"


def _parse_price(soup: BeautifulSoup) -> str:
    price_host = soup.select_one("[data-test-id='PriceDisplay']")
    if price_host:
        txt = _clean(price_host.get_text(" ", strip=True))
        if txt:
            return txt

    price_containers = soup.select("[data-test-id='ProductPrice'], .product-price, [class*='PriceBlock']")
    for container in price_containers:
        cand = container.find(string=re.compile(r"£\s?\d[\d,]*\.?\d{0,2}"))
        if cand:
            return _clean(cand)

    price_match = re.search(r"£\s?\d[\d,]*\.\d{2}", soup.get_text(" ", strip=True))
    if price_match:
        return price_match.group(0)

    for data in _iter_jsonld(soup):
        for prod in _jsonld_find_products(data):
            offers = prod.get("offers")
            if isinstance(offers, dict):
                price = offers.get("price") or offers.get("lowPrice")
                cur = offers.get("priceCurrency", "")
                if price:
                    return f"£{price}" if cur == "GBP" else f"{price} {cur}".strip()
            elif isinstance(offers, list):
                for o in offers:
                    if not isinstance(o, dict):
                        continue
                    price = o.get("price") or o.get("lowPrice")
                    cur = o.get("priceCurrency", "")
                    if price:
                        return f"£{price}" if cur == "GBP" else f"{price} {cur}".strip()

    return "N/A"


def _parse_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
    """
    Parse stock status. Returns (in_stock, stock_text).
    """
    page_text = soup.get_text(" ", strip=True)
    
    oos_patterns = [
        (r"\bout of stock\b", "out_of_stock"),
        (r"\bsold out\b", "sold_out"),
        (r"\bcurrently unavailable\b", "currently_unavailable"),
        (r"\bnot available\b", "not_available"),
        (r"\bdiscontinued\b", "discontinued"),
    ]
    
    for pattern, status in oos_patterns:
        if re.search(pattern, page_text, re.I):
            return False, status

    if re.search(r"\bAdd to (Cart|Basket)\b", page_text, re.I):
        add_btn = soup.select_one("[data-test-id='AddToCartButton']")
        if add_btn:
            if add_btn.get("disabled") or "disabled" in (add_btn.get("class") or []):
                return False, "add_to_cart_disabled"
            return True, "add_to_cart_available"
        return True, "add_to_cart_text"

    if re.search(r"\bin stock\b", page_text, re.I):
        return True, "in_stock_text"

    for data in _iter_jsonld(soup):
        for prod in _jsonld_find_products(data):
            avail = _jsonld_availability_from_offers(prod.get("offers"))
            if avail is not None:
                return avail, "jsonld"

    return None, "unknown"


def _parse_description(soup: BeautifulSoup) -> str:
    def _clean_text(t: str) -> str:
        t = _html.unescape(t or "")
        t = t.replace("\r", "")
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()

    def _looks_generic(s: str) -> bool:
        return bool(re.search(r"you'?ll love .* at wayfair", s, re.I))

    for box in soup.select('[data-hb-id="BoxV3"]'):
        st = (box.get("style") or "").lower()
        if "pre-line" in st:
            txt = _clean_text(box.get_text("\n", strip=True))
            if txt and len(txt) > 120:
                return txt

    features = []
    for p in soup.select("p[data-hb-id='Text']"):
        if re.search(r"\bFeatures\b", p.get_text(" ", strip=True), re.I):
            nxt = p.find_next("ul")
            if nxt:
                items = [_clean_text(li.get_text(" ", strip=True)) for li in nxt.select("li")]
                items = [i for i in items if i]
                if items:
                    features.append("Features:\n- " + "\n- ".join(items))
            break

    best = ""
    for data in _iter_jsonld(soup):
        for prod in _jsonld_find_products(data):
            desc = prod.get("description")
            if isinstance(desc, str):
                cand = _clean_text(desc)
                if cand and not _looks_generic(cand) and len(cand) > len(best):
                    best = cand
    if best:
        if features:
            return best + "\n\n" + "\n\n".join(features)
        return best

    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        cand = _clean_text(md["content"])
        if cand and not _looks_generic(cand):
            if features:
                return cand + "\n\n" + "\n\n".join(features)
            return cand

    if features:
        return "\n\n".join(features)

    return "N/A"


def _parse_images(soup: BeautifulSoup) -> List[str]:
    from typing import Tuple
    ordered: List[Tuple[int, str]] = []
    seen_ids: set[str] = set()

    for btn in soup.select("[data-test-id='pdp-mt-thumbnails'] button[aria-label]"):
        lab = btn.get("aria-label") or ""
        m = re.search(r"(\d+)\s+of\s+(\d+)", lab, re.I)
        if not m:
            continue
        order = int(m.group(1))
        
        img = btn.find("img")
        if not img:
            continue
            
        src = None
        srcset = img.get("srcset") or ""
        if srcset:
            parts = [p.strip().split()[0] for p in srcset.split(",") if p.strip()]
            if parts:
                src = parts[-1]
        
        if not src:
            src = img.get("src") or ""
        
        if not src:
            continue
        
        img_id = _img_dedup_key(src)
        if img_id in seen_ids:
            continue
        seen_ids.add(img_id)
        
        ordered.append((order, src))

    ordered.sort(key=lambda t: t[0])
    
    images: List[str] = []
    for _, u in ordered:
        hu = _wf_to_hires(u, size=1600)
        images.append(hu)
    
    if not images:
        for img in soup.select("#MediaTrayCarouselWithThumbnailSidebar img, [data-test-id='pdp-mt-d-mainImageCarousel'] img"):
            src = img.get("src") or img.get("data-src") or ""
            if src and "assets.wfcdn.com/im/" in src:
                img_id = _img_dedup_key(src)
                if img_id not in seen_ids:
                    seen_ids.add(img_id)
                    images.append(_wf_to_hires(src, size=1600))
    
    # Don't do fallback for category pages - they have lots of images that aren't product images
    # Only use fallback if we have strong PDP indicators
    
    return images


# -----------------------------
# Downloader
# -----------------------------
def _download_images_jpg(urls: List[str], referer: str, folder: Path, base_slug: str, verbose: bool = True) -> List[str]:
    folder.mkdir(parents=True, exist_ok=True)
    out: List[str] = []
    sess = _session_with_retries()
    sess.headers.update({
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG_GB,
        "Referer": referer,
    })
    for i, u in enumerate(urls, 1):
        try:
            r = sess.get(u, timeout=30)
            if not r.ok or not r.content:
                continue

            im = Image.open(io.BytesIO(r.content))
            if im.mode in ("RGBA", "P"):
                im = im.convert("RGB")
            elif im.mode != "RGB":
                im = im.convert("RGB")

            path = folder / f"{base_slug}_{i:02d}.jpg"
            im.save(path, format="JPEG", quality=92, optimize=True)
            out.append(str(path))
            
            if verbose:
                print(f"  ✓ image {i}")
                
        except Exception as e:
            if verbose:
                print(f"  ✗ image {i}: {e}")
            continue
    return out


# -----------------------------
# Public API
# -----------------------------
def scrape_wayfair_product(url: str, save_dir: Path | None = None, *, geo="United Kingdom", verbose: bool = True) -> dict:
    """
    Fetch Wayfair PDP via Oxylabs and return parsed data + downloaded JPG images.
    """
    if verbose:
        print(f"Fetching {url}...")
    
    if save_dir is None:
        save_dir = SAVE_DIR
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    # Fetch HTML
    try:
        html_doc, final_url = oxy_fetch_html(url, geo=geo, timeout=90, verbose=verbose)
    except RuntimeError as e:
        err_str = str(e)
        if "INVALID_PAGE:" in err_str:
            reason = err_str.split("INVALID_PAGE:")[-1]
            if verbose:
                print(f"✗ Invalid link detected (fetch failed): {reason}")
            return _create_invalid_result(url, f"fetch_failed:{reason}")
        
        if verbose:
            print(f"✗ Failed to fetch URL: {e}")
        return _create_invalid_result(url, f"fetch_failed:{str(e)}")

    soup = BeautifulSoup(html_doc, "lxml")

    # Validate page
    is_valid, invalid_reason = _is_valid_pdp(soup, url, verbose=verbose)
    if not is_valid:
        if verbose:
            print(f"✗ Invalid page detected: {invalid_reason}")
        return _create_invalid_result(url, invalid_reason)

    # Parse product data
    name = _parse_name(soup)
    price = _parse_price(soup)
    in_stock, stock_text = _parse_stock(soup)
    description = _parse_description(soup)

    if verbose:
        print(f"  Name: {name}")
        print(f"  Price: {price}")
        print(f"  In Stock: {in_stock} ({stock_text})")

    # Post-extraction validation - only fail if we got NOTHING
    if name == "N/A" and price == "N/A" and description == "N/A":
        if verbose:
            print("✗ Could not extract any product data")
        return _create_invalid_result(url, "no_product_data_extracted")

    name_slug = _safe_name(name)
    uid = _short_uid(final_url)
    base_slug = f"{name_slug}_{uid}"

    images = _parse_images(soup)
    
    if verbose:
        print(f"  Images found: {len(images)}")

    folder = save_dir / base_slug
    
    if images:
        if verbose:
            print(f"\nDownloading {len(images)} images...")
        downloaded = _download_images_jpg(images, referer=final_url, folder=folder, base_slug=base_slug, verbose=verbose)
    else:
        downloaded = []

    return {
        "name": name,
        "price": price,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_count": len(downloaded),
        "image_urls": images,
        "images": downloaded,
        "folder": str(folder) if downloaded else None,
        "url": final_url,
        "mode": "oxylabs(html)+direct(images_jpg_only)",
        "is_invalid": False,
        "invalid_reason": None,
    }


# # -----------------------------
# # CLI test
# # -----------------------------
# if __name__ == "__main__":
#     import sys
    
#     if len(sys.argv) > 1:
#         TEST_URL = sys.argv[1]
#     else:
#         TEST_URL = "https://www.wayfair.co.uk/kitchenware-tableware/pdp/laura-ashley-vq-laura-ashley-china-rose-5-speed-hand-mixer-laas1107.html"
    
#     print(f"\n{'='*60}")
#     print(f"Testing: {TEST_URL}")
#     print(f"{'='*60}\n")
    
#     try:
#         data = scrape_wayfair_product(TEST_URL, verbose=True)
#         print("\n" + "=" * 60)
#         print("RESULTS:")
#         print("=" * 60)
#         print(json.dumps(data, indent=2, ensure_ascii=False))
#     except Exception as e:
#         print(f"\n✗ ERROR: {e}")
