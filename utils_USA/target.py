











# # target.py
# # Python 3.10+ | Oxylabs Real-Time Crawler + BeautifulSoup
# # Version: 2.1 - Fixed image collection to prioritize DOM gallery
# #
# # pip install requests beautifulsoup4 lxml pillow

# import os
# import re
# import io
# import json
# import time
# import hashlib
# from pathlib import Path
# from typing import Optional, Tuple, List, Dict, Any, Iterable
# from urllib.parse import urlparse, parse_qs, urlunparse, urlencode

# import requests
# from bs4 import BeautifulSoup
# from PIL import Image  # for optional webp/png -> jpg

# __version__ = "2.1"

# # ========= Secrets =========
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS
# except Exception as e:
#     raise RuntimeError("Missing oxylabs_secrets.py with OXY_USER and OXY_PASS") from e

# # ========= Config / Paths =========
# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()

# SAVE_DIR = BASE_DIR / "data1"
# SAVE_DIR.mkdir(parents=True, exist_ok=True)

# # Debug mode - set to True to save HTML for inspection
# DEBUG_SAVE_HTML = False

# UA = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
# )

# OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"
# OXY_SOURCE = "target"
# DEFAULT_GEO = "United States"
# REQUEST_TIMEOUT = 90
# MAX_RETRIES = 3
# RETRY_BACKOFF = 2.0

# # ========= Small helpers =========
# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "")).strip()


# def _safe_name(s: str) -> str:
#     s = _clean(s)
#     s = re.sub(r"[^\w.\-]+", "_", s, flags=re.UNICODE)
#     return s[:120] if s else "product"


# def _slug_from_host(url: str) -> str:
#     try:
#         host = (urlparse(url).hostname or "site").replace("www.", "")
#         return host.split(".")[0]
#     except Exception:
#         return "site"


# def _stable_id_from_url(url: str) -> str:
#     """Prefer 'A-########' path segment, then query param 'preselect' (TCIN), else SHA1(url)[:12]."""
#     try:
#         p = urlparse(url).path or ""
#         m = re.search(r"/A-(\d+)", p, re.I)
#         if m:
#             return f"A-{m.group(1)}"
#         qs = parse_qs(urlparse(url).query)
#         if "preselect" in qs and qs["preselect"]:
#             return f"TCIN-{qs['preselect'][0]}"
#     except Exception:
#         pass
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


# def _parse_money(s: str) -> Optional[str]:
#     if not s:
#         return None
#     s = _clean(s)
#     m = re.search(r"(\$\s*\d[\d,]*(?:\.\d{2})?)", s)
#     if m:
#         val = m.group(1).replace(" ", "")
#         return val
#     m = re.search(r"(\d[\d,]*\.\d{2})", s)
#     if m:
#         return "$" + m.group(1)
#     return None


# # ========= Price / Stock / Desc =========
# def _extract_price(soup: BeautifulSoup, html: str) -> Tuple[str, str]:
#     """Extract price with multiple strategies - prioritize DOM selectors."""
    
#     # Strategy 1 (BEST): Direct selector for current price
#     node = soup.select_one('[data-test="product-price"]')
#     if node:
#         money = _parse_money(node.get_text(" ", strip=True))
#         if money:
#             return money, "target-price"
    
#     # Strategy 2: Price container
#     price_container = soup.select_one('[data-test="@web/Price/PriceFull"]')
#     if price_container:
#         current_price = price_container.select_one('[data-test="product-price"]')
#         if current_price:
#             money = _parse_money(current_price.get_text(" ", strip=True))
#             if money:
#                 return money, "target-price-container"
#         money = _parse_money(price_container.get_text(" ", strip=True))
#         if money:
#             return money, "target-price-container"

#     # Strategy 3: Price module
#     price_module = soup.select_one('[data-module-type="ProductDetailPrice"]')
#     if price_module:
#         current_price = price_module.select_one('[data-test="product-price"]')
#         if current_price:
#             money = _parse_money(current_price.get_text(" ", strip=True))
#             if money:
#                 return money, "price-module"
#         money = _parse_money(price_module.get_text(" ", strip=True))
#         if money:
#             return money, "price-module"

#     # Strategy 4: Regex on raw HTML for data-test="product-price"
#     m = re.search(r'data-test="product-price"[^>]*>\s*\$?([\d,]+\.?\d*)', html)
#     if m:
#         price_val = m.group(1).replace(',', '')
#         if price_val:
#             return f"${price_val}", "regex-product-price"

#     # Strategy 5: Extract from __TGT_DATA__ JSON - formatted_current_price
#     m = re.search(r'formatted_current_price\\":\\"(\$[\d,.]+)\\"', html)
#     if m:
#         return m.group(1), "tgt-data-formatted"
    
#     # Strategy 6: __TGT_DATA__ - current_retail (numeric)
#     m = re.search(r'current_retail\\":(\d+\.?\d*)', html)
#     if m:
#         price_val = float(m.group(1))
#         if price_val >= 5:
#             return f"${m.group(1)}", "tgt-data-current-retail"
    
#     # Strategy 7: __TGT_DATA__ - reg_retail (numeric)
#     m = re.search(r'reg_retail\\":(\d+\.?\d*)', html)
#     if m:
#         price_val = float(m.group(1))
#         if price_val >= 5:
#             return f"${m.group(1)}", "tgt-data-reg-retail"
    
#     # Strategy 8: Non-escaped versions
#     m = re.search(r'"formatted_current_price"\s*:\s*"(\$[\d,.]+)"', html)
#     if m:
#         return m.group(1), "tgt-data-formatted-alt"
    
#     m = re.search(r'"current_retail"\s*:\s*([\d.]+)', html)
#     if m:
#         price_val = float(m.group(1))
#         if price_val >= 5:
#             return f"${m.group(1)}", "tgt-data-current-retail-alt"

#     # Strategy 9: JSON-LD
#     for script in soup.select('script[type="application/ld+json"]'):
#         try:
#             data = json.loads(script.get_text(strip=True))
#             data_list = data if isinstance(data, list) else [data]
#             for obj in data_list:
#                 if not isinstance(obj, dict):
#                     continue
#                 if obj.get("@type") in ("Product", "Offer", "AggregateOffer"):
#                     offers = obj.get("offers")
#                     if isinstance(offers, dict):
#                         price_val = offers.get("price")
#                         if price_val:
#                             money = _parse_money(str(price_val))
#                             if money:
#                                 return money, "jsonld"
#                     elif isinstance(offers, list):
#                         for o in offers:
#                             if isinstance(o, dict) and o.get("price"):
#                                 money = _parse_money(str(o["price"]))
#                                 if money:
#                                     return money, "jsonld"
#         except Exception:
#             continue

#     # Strategy 10: Regex for JSON-LD price in raw HTML
#     m = re.search(r'"price"\s*:\s*["\']?(\d+\.?\d*)["\']?', html)
#     if m:
#         price_val = float(m.group(1))
#         if price_val >= 5:
#             return f"${m.group(1)}", "regex-jsonld-price"

#     # Strategy 11: Microdata
#     loc = soup.select_one("[itemprop='price'], meta[itemprop='price']")
#     if loc:
#         val = loc.get("content") or loc.get_text(strip=True)
#         money = _parse_money(val)
#         if money:
#             return money, "microdata"

#     # Strategy 12: Look for price class patterns
#     m = re.search(r'class="[^"]*[Pp]rice[^"]*"[^>]*>\s*\$(\d+\.?\d*)', html)
#     if m:
#         return f"${m.group(1)}", "regex-class-price"

#     # Strategy 13: Any $XX.XX pattern near "price" keyword
#     m = re.search(r'price[^$]{0,50}\$(\d+\.\d{2})', html, re.IGNORECASE)
#     if m:
#         return f"${m.group(1)}", "regex-nearby-price"

#     return "N/A", "none"


# def _detect_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
#     """Detect stock status - prioritize Add to Cart button presence."""
#     stock_text = ""

#     # Strategy 1 (BEST): Check for Add to Cart button
#     add_to_cart_btn = soup.select_one('[data-test="shippingButton"]')
#     if add_to_cart_btn:
#         btn_text = _clean(add_to_cart_btn.get_text(" ", strip=True))
#         is_disabled = add_to_cart_btn.get("disabled") is not None or add_to_cart_btn.get("aria-disabled") == "true"
#         if not is_disabled and "add to cart" in btn_text.lower():
#             return True, btn_text or "Add to cart available"
    
#     # Strategy 2: Check for any button with "Add to cart" text
#     for btn in soup.select('button'):
#         btn_text = _clean(btn.get_text(" ", strip=True))
#         if "add to cart" in btn_text.lower():
#             is_disabled = btn.get("disabled") is not None or btn.get("aria-disabled") == "true"
#             if not is_disabled:
#                 return True, btn_text or "Add to cart available"

#     # Strategy 3: Get stock text from fulfillment sections
#     for sel in [
#         '[data-test="fulfillment-wrapper"]',
#         '[data-test="fulfillment-shipping"]',
#         '[data-test="store-fulfillment"]',
#         '[data-test="@web/ProductDetails/ATCSection"]',
#     ]:
#         node = soup.select_one(sel)
#         if node:
#             txt = _clean(node.get_text(" ", strip=True))
#             if txt:
#                 stock_text = txt
#                 break

#     # Strategy 4: Check for explicit out of stock indicators
#     out_of_stock_selectors = [
#         '[data-test="fulfillment-wrapper"]',
#         '[data-test="oosMessage"]',
#         '[data-test="outOfStock"]',
#         '[data-test="soldOut"]',
#         '[data-module-type="ProductDetailPrice"]',
#         '[data-test="@web/ProductDetails/ATCSection"]',
#     ]
    
#     for sel in out_of_stock_selectors:
#         node = soup.select_one(sel)
#         if node:
#             txt = _clean(node.get_text(" ", strip=True))
#             if re.search(r"\b(sold out|out of stock|not available|unavailable|temporarily unavailable)\b", txt, re.I):
#                 return False, stock_text or "Unavailable"

#     # Strategy 5: Check for disabled Add to Cart button
#     for btn in soup.select('button'):
#         btn_text = _clean(btn.get_text(" ", strip=True))
#         if "add to cart" in btn_text.lower():
#             is_disabled = btn.get("disabled") is not None or btn.get("aria-disabled") == "true"
#             if is_disabled:
#                 return False, stock_text or "Add to cart disabled"

#     if stock_text:
#         if re.search(r"\b(sold out|out of stock|not available|unavailable)\b", stock_text, re.I):
#             return False, stock_text
#         if re.search(r"\b(in stock|available|add to cart|shipping|delivery)\b", stock_text, re.I):
#             return True, stock_text

#     return None, stock_text


# def _extract_description(soup: BeautifulSoup, html: str) -> str:
#     """Extract description with multiple strategies."""
#     bullets: List[str] = []
#     paras: List[str] = []

#     # Strategy 1: Extract "bullets" array from __TGT_DATA__ JSON
#     bullets_match = re.search(r'bullets\\":\s*\[([^\]]+)\]', html)
#     if bullets_match:
#         raw_content = bullets_match.group(1)
#         bullet_items = re.findall(r'\\"([^"]{20,}?)\\"', raw_content)
#         for item in bullet_items:
#             item = item.replace('\\u0026', '&').replace('\\n', ' ').replace('\\r', '')
#             item = _clean(item)
#             if item and len(item) > 20:
#                 bullets.append(f"• {item}")

#     # Strategy 2: Extract "downstream_description" from __TGT_DATA__
#     desc_match = re.search(r'downstream_description\\":\\"([^"\\]+)', html)
#     if desc_match:
#         desc_text = desc_match.group(1)
#         desc_text = desc_text.replace('\\u0026', '&').replace('\\n', ' ')
#         desc_text = re.sub(r'<[^>]+>', ' ', desc_text)
#         desc_text = _clean(desc_text)
#         if desc_text and len(desc_text) > 20:
#             paras.append(desc_text)

#     # Strategy 3: Highlights section from DOM
#     if not bullets:
#         highlights = soup.select_one('[data-test="@web/ProductDetailPageHighlights"]')
#         if highlights:
#             for li in highlights.select("ul li"):
#                 span = li.select_one("span")
#                 if span:
#                     t = _clean(span.get_text(" ", strip=True))
#                 else:
#                     t = _clean(li.get_text(" ", strip=True))
#                 if t and len(t) > 10:
#                     bullets.append(f"• {t}")

#     # Strategy 4: Item details description from DOM
#     if not paras:
#         desc = soup.select_one('[data-test="item-details-description"]')
#         if desc:
#             for br in desc.find_all("br"):
#                 br.replace_with(" ")
#             text = _clean(desc.get_text(" ", strip=True))
#             if text and len(text) > 20:
#                 paras.append(text)
    
#     # Strategy 5: JSON-LD description
#     if not bullets and not paras:
#         for script in soup.select('script[type="application/ld+json"]'):
#             try:
#                 data = json.loads(script.get_text(strip=True))
#                 data_list = data if isinstance(data, list) else [data]
#                 for obj in data_list:
#                     if isinstance(obj, dict) and obj.get("@type") == "Product":
#                         d = _clean(obj.get("description") or "")
#                         if d and len(d) > 20:
#                             paras.append(d)
#                             break
#             except Exception:
#                 continue

#     # Strategy 6: Meta description (last resort)
#     if not bullets and not paras:
#         meta = soup.select_one('meta[name="description"]')
#         if meta and meta.get("content"):
#             content = _clean(meta["content"])
#             if content:
#                 paras.append(content)

#     # Deduplicate bullets
#     seen = set()
#     unique_bullets = []
#     for b in bullets:
#         b_key = b.lower()[:50]
#         if b_key not in seen:
#             seen.add(b_key)
#             unique_bullets.append(b)
#     bullets = unique_bullets

#     if bullets and paras:
#         return "\n".join(bullets + ["", paras[0]])
#     if bullets:
#         return "\n".join(bullets)
#     if paras:
#         return _clean(" ".join(paras))

#     return ""


# # ========= Images =========
# def _scene7_hq(url: str, wid: int = 2000) -> str:
#     """Target Scene7: upsize to 2000x2000, progressive jpeg."""
#     try:
#         u = urlparse(url)
#         q = parse_qs(u.query)
#         q["wid"] = [str(wid)]
#         q["hei"] = [str(wid)]
#         q["qlt"] = [q.get("qlt", ["90"])[0]]
#         q["fmt"] = ["pjpeg"]
#         new_q = urlencode({k: v[0] for k, v in q.items()})
#         return urlunparse((u.scheme, u.netloc, u.path, u.params, new_q, ""))
#     except Exception:
#         return url


# def _extract_image_id(url: str) -> str:
#     """Extract GUEST_xxx ID from Target Scene7 URL for deduplication."""
#     try:
#         path = urlparse(url).path or ""
#         m = re.search(r"(GUEST_[a-f0-9\-]+)", path, re.I)
#         if m:
#             return m.group(1).lower()
#         # Fallback to path
#         m = re.search(r"/Target/([^/?]+)", path)
#         if m:
#             return m.group(1).lower()
#         stem = os.path.splitext(os.path.basename(path))[0]
#         if stem:
#             return stem.lower()
#     except Exception:
#         pass
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


# def _collect_images_from_html(soup: BeautifulSoup, html: str, max_images: Optional[int], product_url: str = "") -> List[str]:
#     """
#     Collect product images from Target page.
    
#     PRIORITY ORDER:
#     1. DOM gallery (most reliable - only shows current product/variant images)
#     2. Srcset patterns in HTML (for images hidden behind "Show more")
#     3. OG image (single main product image)
#     4. JSON-LD images
#     """
#     seen_ids: set = set()
#     urls: List[str] = []
    
#     def add_url(u: str) -> bool:
#         if not u or not u.startswith("http"):
#             return False
#         # Must be Target Scene7 product image
#         if "scene7.com" not in u or "Target" not in u:
#             return False
#         img_id = _extract_image_id(u)
#         if img_id in seen_ids:
#             return False
#         seen_ids.add(img_id)
#         urls.append(u)
#         return True

#     # ============================================================
#     # Strategy 1 (BEST): Extract from DOM image gallery
#     # ============================================================
#     gallery = soup.select_one('section[aria-label="Image gallery"]')
#     if gallery:
#         for item in gallery.select('[data-test^="image-gallery-item-"]'):
#             # Skip the "upload photo" section
#             if item.select_one('[data-crl8-container-id]'):
#                 continue
            
#             img = item.select_one('img[src*="scene7.com"]')
#             if img:
#                 srcset = img.get("srcset", "")
#                 if srcset and "scene7.com" in srcset:
#                     best_url, best_w = None, -1
#                     for part in srcset.split(","):
#                         part = part.strip()
#                         m = re.match(r"(\S+)\s+(\d+)w", part)
#                         if m:
#                             url_part = m.group(1).strip()
#                             w = int(m.group(2))
#                             if w > best_w:
#                                 best_w, best_url = w, url_part
#                     if best_url:
#                         add_url(best_url)
#                         continue
                
#                 src = img.get("src", "")
#                 if src and "scene7.com" in src:
#                     add_url(src)
    
#     # ============================================================
#     # Strategy 2: If we got less than expected, look for srcset patterns
#     # in the raw HTML that might be hidden behind "Show more images"
#     # ============================================================
#     if len(urls) < 8:  # Target typically has 8+ images
#         # Find all srcset attributes with GUEST IDs
#         srcset_matches = re.findall(r'srcset="([^"]+GUEST_[^"]+)"', html)
#         for srcset in srcset_matches:
#             if 'scene7.com' not in srcset:
#                 continue
#             # Parse srcset and get best URL
#             best_url, best_w = None, -1
#             for part in srcset.split(","):
#                 part = part.strip()
#                 m = re.match(r"(\S+)\s+(\d+)w", part)
#                 if m:
#                     url_part = m.group(1).strip()
#                     w = int(m.group(2))
#                     if w > best_w:
#                         best_w, best_url = w, url_part
#             if best_url:
#                 add_url(best_url)
    
#     # If we got images, normalize and return
#     if len(urls) >= 1:
#         final = []
#         for u in urls:
#             if "scene7.com/is/image/Target/" in u:
#                 nu = _scene7_hq(u, wid=2000)
#             else:
#                 nu = u
#             img_id = _extract_image_id(nu)
#             if img_id not in {_extract_image_id(x) for x in final}:
#                 final.append(nu)
#             if max_images and len(final) >= max_images:
#                 break
#         return final

#     # ============================================================
#     # Strategy 3 (Fallback): OG image
#     # ============================================================
#     og = soup.select_one('meta[property="og:image"]')
#     if og and og.get("content"):
#         add_url(og["content"])

#     # ============================================================
#     # Strategy 4 (Fallback): JSON-LD images
#     # ============================================================
#     for script in soup.select('script[type="application/ld+json"]'):
#         try:
#             data = json.loads(script.get_text(strip=True))
#             data_list = data if isinstance(data, list) else [data]
#             for obj in data_list:
#                 if isinstance(obj, dict) and obj.get("@type") == "Product":
#                     imgs = obj.get("image")
#                     if isinstance(imgs, str):
#                         add_url(imgs)
#                     elif isinstance(imgs, list):
#                         for u in imgs:
#                             if isinstance(u, str):
#                                 add_url(u)
#         except Exception:
#             continue

#     # Normalize to high quality Scene7
#     final: List[str] = []
#     for u in urls:
#         if "scene7.com/is/image/Target/" in u:
#             nu = _scene7_hq(u, wid=2000)
#         else:
#             nu = u
#         img_id = _extract_image_id(nu)
#         if img_id not in {_extract_image_id(x) for x in final}:
#             final.append(nu)
#         if max_images and len(final) >= max_images:
#             break
    
#     return final


# # ========= Image download / optional JPG conversion =========
# def _download_image_raw(url: str, dest: Path) -> bool:
#     try:
#         r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
#         if r.ok and r.content:
#             dest.write_bytes(r.content)
#             return True
#     except Exception:
#         pass
#     return False


# def _download_images(urls: List[str], folder: Path) -> List[str]:
#     saved: List[str] = []
#     folder.mkdir(parents=True, exist_ok=True)
#     for idx, img_url in enumerate(urls, start=1):
#         ext = ".jpg"
#         fname = f"{idx:02d}{ext}"
#         dest = folder / fname
#         if _download_image_raw(img_url, dest):
#             saved.append(str(dest))
#     return saved


# def _download_images_as_jpg(urls: List[str], folder: Path, quality: int = 90) -> List[str]:
#     saved: List[str] = []
#     folder.mkdir(parents=True, exist_ok=True)
#     with requests.Session() as s:
#         s.headers.update({
#             "User-Agent": UA,
#             "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
#         })
#         for i, u in enumerate(urls, 1):
#             try:
#                 r = s.get(u, timeout=30)
#                 if not (r.ok and r.content):
#                     continue
#                 img_bytes = io.BytesIO(r.content)
#                 im = Image.open(img_bytes)
#                 if im.mode in ("RGBA", "LA", "P"):
#                     if im.mode == "P":
#                         im = im.convert("RGBA")
#                     bg = Image.new("RGB", im.size, (255, 255, 255))
#                     bg.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
#                     im = bg
#                 else:
#                     im = im.convert("RGB")
#                 out_path = folder / f"{i:02d}.jpg"
#                 im.save(out_path, format="JPEG", quality=quality, optimize=True)
#                 saved.append(str(out_path))
#             except Exception as e:
#                 try:
#                     ext = ".jpg"
#                     ct = (r.headers.get("Content-Type") or "").lower()
#                     if "png" in ct: ext = ".png"
#                     elif "webp" in ct: ext = ".webp"
#                     elif "jpeg" in ct: ext = ".jpg"
#                     raw_path = folder / f"{i:02d}{ext}"
#                     raw_path.write_bytes(r.content)
#                     saved.append(str(raw_path))
#                 except Exception:
#                     print(f"⚠️ Could not download/convert {u}: {e}")
#     return saved


# # ========= Oxylabs =========
# def _oxy_payload_for_url(url: str, with_browser_instructions: bool = True) -> Dict[str, Any]:
#     payload = {
#         "source": OXY_SOURCE,
#         "url": url,
#         "render": "html",
#         "geo_location": DEFAULT_GEO,
#         "user_agent_type": "desktop",
#     }
    
#     # Add browser instructions to expand hidden images
#     if with_browser_instructions:
#         payload["browser_instructions"] = [
#             # Scroll down to load lazy images
#             {"type": "scroll", "x": 0, "y": 800},
#             {"type": "wait", "wait_time_s": 1},
#             # Click "Show more images" button if present
#             {"type": "click", "selector": {"type": "css", "value": "button[aria-label='Show more images']"}},
#             {"type": "wait", "wait_time_s": 1},
#             # Scroll more to load all images
#             {"type": "scroll", "x": 0, "y": 1200},
#             {"type": "wait", "wait_time_s": 1},
#         ]
    
#     return payload


# def _post_realtime_one(session: requests.Session, url: str, with_browser_instructions: bool = True) -> dict:
#     payload = _oxy_payload_for_url(url, with_browser_instructions=with_browser_instructions)
#     attempt = 0
#     while True:
#         attempt += 1
#         resp = session.post(
#             OXY_ENDPOINT,
#             json=payload,
#             timeout=REQUEST_TIMEOUT,
#             auth=(OXY_USER, OXY_PASS),
#         )
#         if resp.status_code == 401:
#             raise RuntimeError("Oxylabs Unauthorized (401). Check OXY_USER/OXY_PASS.")
#         if resp.ok:
#             try:
#                 return resp.json()
#             except Exception as e:
#                 raise RuntimeError(f"Oxylabs response not JSON: {e}; head: {resp.text[:200]}")
        
#         # If browser instructions fail, retry without them
#         if attempt == 1 and with_browser_instructions and resp.status_code == 400:
#             payload = _oxy_payload_for_url(url, with_browser_instructions=False)
#             continue
            
#         if attempt >= MAX_RETRIES:
#             raise RuntimeError(f"Oxylabs failed: HTTP {resp.status_code} - {resp.text[:400]}")
#         time.sleep(RETRY_BACKOFF * attempt)


# def _result_content_or_error(res: dict, requested_url: Optional[str] = None) -> str:
#     if isinstance(res, dict) and isinstance(res.get("results"), list) and res["results"]:
#         items = res["results"]
#         selected = None
#         if requested_url:
#             for it in items:
#                 if isinstance(it, dict) and it.get("url") == requested_url:
#                     selected = it
#                     break
#         if selected is None:
#             selected = items[0]
#         status = selected.get("status_code", 0)
#         if status != 200:
#             raise RuntimeError(f"Bad Oxylabs response: {status} {selected.get('error') or selected.get('message') or ''}")
#         if "content" not in selected:
#             raise RuntimeError("Oxylabs results[0] missing 'content'")
#         return selected["content"]

#     status = res.get("status_code", 0)
#     if status != 200:
#         raise RuntimeError(f"Bad Oxylabs response: {status} {res.get('error') or res.get('message') or ''}")
#     if "content" not in res:
#         raise RuntimeError("Oxylabs response missing 'content'")
#     return res["content"]


# # ========= Color/Variant Helpers =========
# def _extract_available_colors(soup: BeautifulSoup, html: str) -> List[Dict[str, Any]]:
#     """Extract available color variants from the page."""
#     colors = []
    
#     # Method 1: From DOM - variation selector
#     variation_div = soup.select_one('[data-test="@web/VariationComponent"]')
#     if variation_div:
#         for link in variation_div.select('a[aria-label*="Color"]'):
#             aria_label = link.get("aria-label", "")
#             href = link.get("href", "")
            
#             color_name = ""
#             is_selected = "selected" in aria_label.lower()
#             is_unavailable = "out of stock" in aria_label.lower() or "unavailable" in link.get("class", [])
            
#             parts = aria_label.split(",")
#             if len(parts) >= 2:
#                 color_name = parts[1].strip().split(" - ")[0].split(",")[0].strip()
            
#             tcin = ""
#             m = re.search(r'/A-(\d+)', href)
#             if m:
#                 tcin = m.group(1)
            
#             if color_name:
#                 colors.append({
#                     "name": color_name,
#                     "tcin": tcin,
#                     "url": href if href.startswith("http") else f"https://www.target.com{href}",
#                     "selected": is_selected,
#                     "available": not is_unavailable,
#                 })
    
#     # Method 2: From __TGT_DATA__ JSON
#     if not colors:
#         color_matches = re.findall(
#             r'"variation_value"\\?:\\?"([^"]+)"\\?[^}]*"tcin"\\?:\\?"(\d+)"',
#             html
#         )
#         for color_name, tcin in color_matches:
#             if color_name and tcin:
#                 colors.append({
#                     "name": color_name,
#                     "tcin": tcin,
#                     "url": f"https://www.target.com/p/-/A-{tcin}",
#                     "selected": False,
#                     "available": True,
#                 })
    
#     return colors


# def _get_url_for_color(base_url: str, color: str, soup: BeautifulSoup, html: str) -> Tuple[str, Optional[str]]:
#     """Get the URL for a specific color variant."""
#     if not color:
#         return base_url, None
    
#     color_lower = color.lower().strip()
#     available_colors = _extract_available_colors(soup, html)
    
#     if not available_colors:
#         return base_url, "No color variants found on this product page"
    
#     for c in available_colors:
#         if c["name"].lower() == color_lower:
#             if not c["available"]:
#                 return c["url"], f"Color '{color}' is out of stock"
#             return c["url"], None
    
#     available_names = [c["name"] for c in available_colors]
#     return base_url, f"Color '{color}' not found. Available colors: {', '.join(available_names)}"


# def scrape_target_oxylabs(
#     url: str,
#     *,
#     color: Optional[str] = None,
#     save_dir: Path = SAVE_DIR,
#     max_images: int = 10,
#     convert_images_to_jpg: bool = True,
#     verbose: bool = False,
# ) -> dict:
#     """
#     Scrape a Target product page.
    
#     Args:
#         url: The Target product URL
#         color: Optional color variant to select
#         save_dir: Directory to save images and data
#         max_images: Maximum number of images to download
#         convert_images_to_jpg: Whether to convert images to JPG format
#         verbose: Print progress messages
#     """
#     original_url = url
#     color_error = None
#     selected_color = None
#     available_colors = []
    
#     if verbose:
#         print(f"Fetching {url}...")
    
#     with requests.Session() as session:
#         session.headers.update({"User-Agent": UA})

#         res = _post_realtime_one(session, url)
#         html = _result_content_or_error(res, requested_url=url)
#         soup = BeautifulSoup(html, "lxml")
        
#         available_colors = _extract_available_colors(soup, html)
        
#         if color:
#             new_url, color_error = _get_url_for_color(url, color, soup, html)
            
#             if new_url != url:
#                 url = new_url
#                 res = _post_realtime_one(session, url)
#                 html = _result_content_or_error(res, requested_url=url)
#                 soup = BeautifulSoup(html, "lxml")
#                 selected_color = color
#                 available_colors = _extract_available_colors(soup, html)
        
#         if not selected_color:
#             for c in available_colors:
#                 if c.get("selected"):
#                     selected_color = c["name"]
#                     break
        
#         slug = _slug_from_host(url) or "target"
#         stable_id = _stable_id_from_url(url)

#         # NAME
#         name = ""
#         node = soup.select_one('[data-module-type="ProductDetailTitle"] [data-test="product-title"]')
#         if node:
#             name = _clean(node.get_text(" ", strip=True))
#         if not name:
#             ogt = soup.select_one('meta[property="og:title"]')
#             if ogt and ogt.get("content"):
#                 name = _clean(ogt["content"])
#         name = name or "Unknown Product"

#         # FOLDER
#         folder = save_dir / f"{slug}_{_safe_name(name)}_{stable_id}"
#         folder.mkdir(parents=True, exist_ok=True)

#         # DEBUG: Save HTML for inspection
#         if DEBUG_SAVE_HTML:
#             (folder / "debug_page.html").write_text(html, encoding="utf-8")

#         # PRICE
#         price, price_source = _extract_price(soup, html)

#         # STOCK
#         in_stock, stock_text = _detect_stock(soup)

#         # DESCRIPTION
#         description = _extract_description(soup, html)

#         # IMAGES
#         image_urls = _collect_images_from_html(soup, html, max_images=max_images, product_url=url)
        
#         if verbose:
#             print(f"  Name: {name}")
#             print(f"  Price: {price}")
#             print(f"  In Stock: {in_stock}")
#             print(f"  Images found: {len(image_urls)}")
        
#         if convert_images_to_jpg:
#             images_saved = _download_images_as_jpg(image_urls, folder, quality=90)
#         else:
#             images_saved = _download_images(image_urls, folder)

#         out = {
#             "url": url,
#             "name": name,
#             "selected_color": selected_color,
#             "available_colors": [{"name": c["name"], "available": c["available"], "tcin": c["tcin"]} for c in available_colors] if available_colors else None,
#             "color_error": color_error,
#             "price": price,
#             "price_source": price_source if price != "N/A" else "none",
#             "in_stock": in_stock,
#             "stock_text": stock_text or "",
#             "description": description,
#             "image_count": len(images_saved),
#             "image_urls": image_urls,
#             "images_downloaded": images_saved,
#             "folder": str(folder),
#             "fetched_via": f"oxylabs-{OXY_SOURCE}",
#         }
#         out = {k: v for k, v in out.items() if v is not None}
#         (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
#         return out


# # ========= Batch scraping =========
# def scrape_target_batch_oxylabs(
#     urls: Iterable[str],
#     *,
#     save_dir: Path = SAVE_DIR,
#     max_images: int = 10,
#     convert_images_to_jpg: bool = True,
# ) -> List[Dict[str, Any]]:
#     urls = [u for u in urls if u]
#     if not urls:
#         return []
#     save_dir.mkdir(parents=True, exist_ok=True)

#     results: List[Dict[str, Any]] = []
#     with requests.Session() as session:
#         session.headers.update({"User-Agent": UA})
#         for u in urls:
#             try:
#                 result = scrape_target_oxylabs(u, save_dir=save_dir, max_images=max_images, 
#                                                convert_images_to_jpg=convert_images_to_jpg)
#                 results.append(result)
#             except Exception as e:
#                 results.append({"url": u, "error": str(e)})
#     return results


# # ========= CLI =========
# if __name__ == "__main__":
#     import sys
    
#     TEST_URL = "https://www.target.com/p/laura-ashley-6-5l-slow-cooker/-/A-94282953?preselect=93986319#lnk=sametab"
    
#     color_arg = sys.argv[1] if len(sys.argv) > 1 else None
    
#     data = scrape_target_oxylabs(
#         TEST_URL,
#         color=color_arg,
#         save_dir=SAVE_DIR,
#         max_images=10,
#         convert_images_to_jpg=True,
#         verbose=True,
#     )
#     print("\n" + "=" * 60)
#     print("RESULTS:")
#     print("=" * 60)
#     print(json.dumps(data, indent=2, ensure_ascii=False))

    




# target.py
# Python 3.10+ | Oxylabs Real-Time Crawler + BeautifulSoup
# Version: 2.3 - Fixed timeout issues and stock detection based on selected color
#
# pip install requests beautifulsoup4 lxml pillow

import os
import re
import io
import json
import time
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any, Iterable
from urllib.parse import urlparse, parse_qs, urlunparse, urlencode

import requests
from bs4 import BeautifulSoup
from PIL import Image

__version__ = "2.3"

# ========= Secrets =========
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception as e:
    raise RuntimeError("Missing oxylabs_secrets.py with OXY_USER and OXY_PASS") from e

# ========= Config / Paths =========
try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()

SAVE_DIR = BASE_DIR / "data1"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

DEBUG_SAVE_HTML = False

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"
OXY_SOURCE = "target"
DEFAULT_GEO = "United States"
REQUEST_TIMEOUT = 120  # Increased for stability
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


# ========= Small helpers =========
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _safe_name(s: str) -> str:
    s = _clean(s)
    s = re.sub(r"[^\w.\-]+", "_", s, flags=re.UNICODE)
    return s[:120] if s else "product"


def _slug_from_host(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "site").replace("www.", "")
        return host.split(".")[0]
    except Exception:
        return "site"


def _stable_id_from_url(url: str) -> str:
    try:
        p = urlparse(url).path or ""
        m = re.search(r"/A-(\d+)", p, re.I)
        if m:
            return f"A-{m.group(1)}"
        qs = parse_qs(urlparse(url).query)
        if "preselect" in qs and qs["preselect"]:
            return f"TCIN-{qs['preselect'][0]}"
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _parse_money(s: str) -> Optional[str]:
    if not s:
        return None
    s = _clean(s)
    m = re.search(r"(\$\s*\d[\d,]*(?:\.\d{2})?)", s)
    if m:
        val = m.group(1).replace(" ", "")
        return val
    m = re.search(r"(\d[\d,]*\.\d{2})", s)
    if m:
        return "$" + m.group(1)
    return None


# ========= Price Extraction =========
def _extract_price(soup: BeautifulSoup, html: str) -> Tuple[str, str]:
    # Strategy 1: Direct selector
    node = soup.select_one('[data-test="product-price"]')
    if node:
        money = _parse_money(node.get_text(" ", strip=True))
        if money:
            return money, "target-price"
    
    # Strategy 2: Price container
    price_container = soup.select_one('[data-test="@web/Price/PriceFull"]')
    if price_container:
        current_price = price_container.select_one('[data-test="product-price"]')
        if current_price:
            money = _parse_money(current_price.get_text(" ", strip=True))
            if money:
                return money, "target-price-container"
        money = _parse_money(price_container.get_text(" ", strip=True))
        if money:
            return money, "target-price-container"

    # Strategy 3: Price module
    price_module = soup.select_one('[data-module-type="ProductDetailPrice"]')
    if price_module:
        current_price = price_module.select_one('[data-test="product-price"]')
        if current_price:
            money = _parse_money(current_price.get_text(" ", strip=True))
            if money:
                return money, "price-module"
        money = _parse_money(price_module.get_text(" ", strip=True))
        if money:
            return money, "price-module"

    # Strategy 4: Regex on raw HTML
    m = re.search(r'data-test="product-price"[^>]*>\s*\$?([\d,]+\.?\d*)', html)
    if m:
        price_val = m.group(1).replace(',', '')
        if price_val:
            return f"${price_val}", "regex-product-price"

    # Strategy 5: __TGT_DATA__ formatted_current_price
    m = re.search(r'formatted_current_price\\":\\"(\$[\d,.]+)\\"', html)
    if m:
        return m.group(1), "tgt-data-formatted"
    
    # Strategy 6: __TGT_DATA__ current_retail
    m = re.search(r'current_retail\\":(\d+\.?\d*)', html)
    if m:
        price_val = float(m.group(1))
        if price_val >= 5:
            return f"${m.group(1)}", "tgt-data-current-retail"
    
    # Strategy 7: __TGT_DATA__ reg_retail
    m = re.search(r'reg_retail\\":(\d+\.?\d*)', html)
    if m:
        price_val = float(m.group(1))
        if price_val >= 5:
            return f"${m.group(1)}", "tgt-data-reg-retail"
    
    # Strategy 8: Non-escaped versions
    m = re.search(r'"formatted_current_price"\s*:\s*"(\$[\d,.]+)"', html)
    if m:
        return m.group(1), "tgt-data-formatted-alt"
    
    m = re.search(r'"current_retail"\s*:\s*([\d.]+)', html)
    if m:
        price_val = float(m.group(1))
        if price_val >= 5:
            return f"${m.group(1)}", "tgt-data-current-retail-alt"

    # Strategy 9: JSON-LD
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
            data_list = data if isinstance(data, list) else [data]
            for obj in data_list:
                if not isinstance(obj, dict):
                    continue
                if obj.get("@type") in ("Product", "Offer", "AggregateOffer"):
                    offers = obj.get("offers")
                    if isinstance(offers, dict):
                        price_val = offers.get("price")
                        if price_val:
                            money = _parse_money(str(price_val))
                            if money:
                                return money, "jsonld"
                    elif isinstance(offers, list):
                        for o in offers:
                            if isinstance(o, dict) and o.get("price"):
                                money = _parse_money(str(o["price"]))
                                if money:
                                    return money, "jsonld"
        except Exception:
            continue

    # Strategy 10: Regex for JSON-LD price
    m = re.search(r'"price"\s*:\s*["\']?(\d+\.?\d*)["\']?', html)
    if m:
        price_val = float(m.group(1))
        if price_val >= 5:
            return f"${m.group(1)}", "regex-jsonld-price"

    # Strategy 11: Microdata
    loc = soup.select_one("[itemprop='price'], meta[itemprop='price']")
    if loc:
        val = loc.get("content") or loc.get_text(strip=True)
        money = _parse_money(val)
        if money:
            return money, "microdata"

    # Strategy 12: Price class patterns
    m = re.search(r'class="[^"]*[Pp]rice[^"]*"[^>]*>\s*\$(\d+\.?\d*)', html)
    if m:
        return f"${m.group(1)}", "regex-class-price"

    # Strategy 13: Any $XX.XX pattern near "price"
    m = re.search(r'price[^$]{0,50}\$(\d+\.\d{2})', html, re.IGNORECASE)
    if m:
        return f"${m.group(1)}", "regex-nearby-price"

    return "N/A", "none"


# ========= Stock Detection =========
def _detect_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
    stock_text = ""

    # Strategy 1: Check for Add to Cart button
    add_to_cart_btn = soup.select_one('[data-test="shippingButton"]')
    if add_to_cart_btn:
        btn_text = _clean(add_to_cart_btn.get_text(" ", strip=True))
        is_disabled = add_to_cart_btn.get("disabled") is not None or add_to_cart_btn.get("aria-disabled") == "true"
        if not is_disabled and "add to cart" in btn_text.lower():
            return True, btn_text or "Add to cart"
    
    # Strategy 2: Any button with "Add to cart"
    for btn in soup.select('button'):
        btn_text = _clean(btn.get_text(" ", strip=True))
        if "add to cart" in btn_text.lower():
            is_disabled = btn.get("disabled") is not None or btn.get("aria-disabled") == "true"
            if not is_disabled:
                return True, btn_text or "Add to cart"

    # Strategy 3: Fulfillment sections
    for sel in [
        '[data-test="fulfillment-wrapper"]',
        '[data-test="fulfillment-shipping"]',
        '[data-test="store-fulfillment"]',
        '[data-test="@web/ProductDetails/ATCSection"]',
    ]:
        node = soup.select_one(sel)
        if node:
            txt = _clean(node.get_text(" ", strip=True))
            if txt:
                stock_text = txt
                break

    # Strategy 4: Out of stock indicators
    out_of_stock_selectors = [
        '[data-test="fulfillment-wrapper"]',
        '[data-test="oosMessage"]',
        '[data-test="outOfStock"]',
        '[data-test="soldOut"]',
        '[data-module-type="ProductDetailPrice"]',
        '[data-test="@web/ProductDetails/ATCSection"]',
    ]
    
    for sel in out_of_stock_selectors:
        node = soup.select_one(sel)
        if node:
            txt = _clean(node.get_text(" ", strip=True))
            if re.search(r"\b(sold out|out of stock|not available|unavailable|temporarily unavailable)\b", txt, re.I):
                return False, stock_text or "Unavailable"

    # Strategy 5: Disabled Add to Cart
    for btn in soup.select('button'):
        btn_text = _clean(btn.get_text(" ", strip=True))
        if "add to cart" in btn_text.lower():
            is_disabled = btn.get("disabled") is not None or btn.get("aria-disabled") == "true"
            if is_disabled:
                return False, stock_text or "Add to cart disabled"

    if stock_text:
        if re.search(r"\b(sold out|out of stock|not available|unavailable)\b", stock_text, re.I):
            return False, stock_text
        if re.search(r"\b(in stock|available|add to cart|shipping|delivery)\b", stock_text, re.I):
            return True, stock_text

    return None, stock_text


# ========= Description Extraction =========
def _extract_description(soup: BeautifulSoup, html: str) -> str:
    bullets: List[str] = []
    paras: List[str] = []

    # Strategy 1: bullets array from __TGT_DATA__
    bullets_match = re.search(r'bullets\\":\s*\[([^\]]+)\]', html)
    if bullets_match:
        raw_content = bullets_match.group(1)
        bullet_items = re.findall(r'\\"([^"]{20,}?)\\"', raw_content)
        for item in bullet_items:
            item = item.replace('\\u0026', '&').replace('\\n', ' ').replace('\\r', '')
            item = _clean(item)
            if item and len(item) > 20:
                bullets.append(f"• {item}")

    # Strategy 2: downstream_description from __TGT_DATA__
    desc_match = re.search(r'downstream_description\\":\\"([^"\\]+)', html)
    if desc_match:
        desc_text = desc_match.group(1)
        desc_text = desc_text.replace('\\u0026', '&').replace('\\n', ' ')
        desc_text = re.sub(r'<[^>]+>', ' ', desc_text)
        desc_text = _clean(desc_text)
        if desc_text and len(desc_text) > 20:
            paras.append(desc_text)

    # Strategy 3: Highlights from DOM
    if not bullets:
        highlights = soup.select_one('[data-test="@web/ProductDetailPageHighlights"]')
        if highlights:
            for li in highlights.select("ul li"):
                span = li.select_one("span")
                if span:
                    t = _clean(span.get_text(" ", strip=True))
                else:
                    t = _clean(li.get_text(" ", strip=True))
                if t and len(t) > 10:
                    bullets.append(f"• {t}")

    # Strategy 4: Item details from DOM
    if not paras:
        desc = soup.select_one('[data-test="item-details-description"]')
        if desc:
            for br in desc.find_all("br"):
                br.replace_with(" ")
            text = _clean(desc.get_text(" ", strip=True))
            if text and len(text) > 20:
                paras.append(text)
    
    # Strategy 5: JSON-LD description
    if not bullets and not paras:
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.get_text(strip=True))
                data_list = data if isinstance(data, list) else [data]
                for obj in data_list:
                    if isinstance(obj, dict) and obj.get("@type") == "Product":
                        d = _clean(obj.get("description") or "")
                        if d and len(d) > 20:
                            paras.append(d)
                            break
            except Exception:
                continue

    # Strategy 6: Meta description
    if not bullets and not paras:
        meta = soup.select_one('meta[name="description"]')
        if meta and meta.get("content"):
            content = _clean(meta["content"])
            if content:
                paras.append(content)

    # Deduplicate bullets
    seen = set()
    unique_bullets = []
    for b in bullets:
        b_key = b.lower()[:50]
        if b_key not in seen:
            seen.add(b_key)
            unique_bullets.append(b)
    bullets = unique_bullets

    if bullets and paras:
        return "\n".join(bullets + ["", paras[0]])
    if bullets:
        return "\n".join(bullets)
    if paras:
        return _clean(" ".join(paras))

    return ""


# ========= Images =========
def _scene7_hq(url: str, wid: int = 2000) -> str:
    try:
        u = urlparse(url)
        q = parse_qs(u.query)
        q["wid"] = [str(wid)]
        q["hei"] = [str(wid)]
        q["qlt"] = [q.get("qlt", ["90"])[0]]
        q["fmt"] = ["pjpeg"]
        new_q = urlencode({k: v[0] for k, v in q.items()})
        return urlunparse((u.scheme, u.netloc, u.path, u.params, new_q, ""))
    except Exception:
        return url


def _extract_image_id(url: str) -> str:
    try:
        path = urlparse(url).path or ""
        m = re.search(r"(GUEST_[a-f0-9\-]+)", path, re.I)
        if m:
            return m.group(1).lower()
        m = re.search(r"/Target/([^/?]+)", path)
        if m:
            return m.group(1).lower()
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem:
            return stem.lower()
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _collect_images_from_html(soup: BeautifulSoup, html: str, max_images: Optional[int], product_url: str = "") -> List[str]:
    seen_ids: set = set()
    urls: List[str] = []
    
    def add_url(u: str) -> bool:
        if not u or not u.startswith("http"):
            return False
        if "scene7.com" not in u or "Target" not in u:
            return False
        img_id = _extract_image_id(u)
        if img_id in seen_ids:
            return False
        seen_ids.add(img_id)
        urls.append(u)
        return True

    # Strategy 1: DOM image gallery
    gallery = soup.select_one('section[aria-label="Image gallery"]')
    if gallery:
        for item in gallery.select('[data-test^="image-gallery-item-"]'):
            if item.select_one('[data-crl8-container-id]'):
                continue
            
            img = item.select_one('img[src*="scene7.com"]')
            if img:
                srcset = img.get("srcset", "")
                if srcset and "scene7.com" in srcset:
                    best_url, best_w = None, -1
                    for part in srcset.split(","):
                        part = part.strip()
                        m = re.match(r"(\S+)\s+(\d+)w", part)
                        if m:
                            url_part = m.group(1).strip()
                            w = int(m.group(2))
                            if w > best_w:
                                best_w, best_url = w, url_part
                    if best_url:
                        add_url(best_url)
                        continue
                
                src = img.get("src", "")
                if src and "scene7.com" in src:
                    add_url(src)
    
    # Strategy 2: srcset patterns in raw HTML
    if len(urls) < 8:
        srcset_matches = re.findall(r'srcset="([^"]+GUEST_[^"]+)"', html)
        for srcset in srcset_matches:
            if 'scene7.com' not in srcset:
                continue
            best_url, best_w = None, -1
            for part in srcset.split(","):
                part = part.strip()
                m = re.match(r"(\S+)\s+(\d+)w", part)
                if m:
                    url_part = m.group(1).strip()
                    w = int(m.group(2))
                    if w > best_w:
                        best_w, best_url = w, url_part
            if best_url:
                add_url(best_url)
    
    if len(urls) >= 1:
        final = []
        for u in urls:
            if "scene7.com/is/image/Target/" in u:
                nu = _scene7_hq(u, wid=2000)
            else:
                nu = u
            img_id = _extract_image_id(nu)
            if img_id not in {_extract_image_id(x) for x in final}:
                final.append(nu)
            if max_images and len(final) >= max_images:
                break
        return final

    # Strategy 3: OG image
    og = soup.select_one('meta[property="og:image"]')
    if og and og.get("content"):
        add_url(og["content"])

    # Strategy 4: JSON-LD images
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
            data_list = data if isinstance(data, list) else [data]
            for obj in data_list:
                if isinstance(obj, dict) and obj.get("@type") == "Product":
                    imgs = obj.get("image")
                    if isinstance(imgs, str):
                        add_url(imgs)
                    elif isinstance(imgs, list):
                        for u in imgs:
                            if isinstance(u, str):
                                add_url(u)
        except Exception:
            continue

    final: List[str] = []
    for u in urls:
        if "scene7.com/is/image/Target/" in u:
            nu = _scene7_hq(u, wid=2000)
        else:
            nu = u
        img_id = _extract_image_id(nu)
        if img_id not in {_extract_image_id(x) for x in final}:
            final.append(nu)
        if max_images and len(final) >= max_images:
            break
    
    return final


# ========= Image download =========
def _download_image_raw(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        if r.ok and r.content:
            dest.write_bytes(r.content)
            return True
    except Exception:
        pass
    return False


def _download_images(urls: List[str], folder: Path) -> List[str]:
    saved: List[str] = []
    folder.mkdir(parents=True, exist_ok=True)
    for idx, img_url in enumerate(urls, start=1):
        fname = f"{idx:02d}.jpg"
        dest = folder / fname
        if _download_image_raw(img_url, dest):
            saved.append(str(dest))
    return saved


def _download_images_as_jpg(urls: List[str], folder: Path, quality: int = 90) -> List[str]:
    saved: List[str] = []
    folder.mkdir(parents=True, exist_ok=True)
    with requests.Session() as s:
        s.headers.update({
            "User-Agent": UA,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        })
        for i, u in enumerate(urls, 1):
            try:
                r = s.get(u, timeout=30)
                if not (r.ok and r.content):
                    continue
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
                out_path = folder / f"{i:02d}.jpg"
                im.save(out_path, format="JPEG", quality=quality, optimize=True)
                saved.append(str(out_path))
            except Exception as e:
                try:
                    ext = ".jpg"
                    ct = (r.headers.get("Content-Type") or "").lower()
                    if "png" in ct: ext = ".png"
                    elif "webp" in ct: ext = ".webp"
                    elif "jpeg" in ct: ext = ".jpg"
                    raw_path = folder / f"{i:02d}{ext}"
                    raw_path.write_bytes(r.content)
                    saved.append(str(raw_path))
                except Exception:
                    print(f"⚠️ Could not download/convert {u}: {e}")
    return saved


# ========= Oxylabs =========
def _oxy_payload_for_url(url: str) -> Dict[str, Any]:
    """Simple payload without browser instructions to avoid timeouts."""
    return {
        "source": OXY_SOURCE,
        "url": url,
        "render": "html",
        "geo_location": DEFAULT_GEO,
        "user_agent_type": "desktop",
    }


def _post_realtime_one(session: requests.Session, url: str) -> dict:
    """Post to Oxylabs realtime API with retry logic and timeout handling."""
    payload = _oxy_payload_for_url(url)
    attempt = 0
    
    while True:
        attempt += 1
        try:
            resp = session.post(
                OXY_ENDPOINT,
                json=payload,
                timeout=REQUEST_TIMEOUT,
                auth=(OXY_USER, OXY_PASS),
            )
        except requests.exceptions.ReadTimeout:
            if attempt >= MAX_RETRIES:
                raise RuntimeError(f"Oxylabs timed out after {MAX_RETRIES} attempts")
            print(f"  ⚠️ Timeout, retrying ({attempt}/{MAX_RETRIES})...")
            time.sleep(RETRY_BACKOFF * attempt)
            continue
        except requests.exceptions.RequestException as e:
            if attempt >= MAX_RETRIES:
                raise RuntimeError(f"Oxylabs request failed: {e}")
            print(f"  ⚠️ Request error, retrying ({attempt}/{MAX_RETRIES})...")
            time.sleep(RETRY_BACKOFF * attempt)
            continue
        
        if resp.status_code == 401:
            raise RuntimeError("Oxylabs Unauthorized (401). Check OXY_USER/OXY_PASS.")
        
        if resp.ok:
            try:
                return resp.json()
            except Exception as e:
                raise RuntimeError(f"Oxylabs response not JSON: {e}; head: {resp.text[:200]}")
            
        if attempt >= MAX_RETRIES:
            raise RuntimeError(f"Oxylabs failed: HTTP {resp.status_code} - {resp.text[:400]}")
        
        print(f"  ⚠️ HTTP {resp.status_code}, retrying ({attempt}/{MAX_RETRIES})...")
        time.sleep(RETRY_BACKOFF * attempt)


def _result_content_or_error(res: dict, requested_url: Optional[str] = None) -> str:
    if isinstance(res, dict) and isinstance(res.get("results"), list) and res["results"]:
        items = res["results"]
        selected = None
        if requested_url:
            for it in items:
                if isinstance(it, dict) and it.get("url") == requested_url:
                    selected = it
                    break
        if selected is None:
            selected = items[0]
        status = selected.get("status_code", 0)
        if status != 200:
            raise RuntimeError(f"Bad Oxylabs response: {status} {selected.get('error') or selected.get('message') or ''}")
        if "content" not in selected:
            raise RuntimeError("Oxylabs results[0] missing 'content'")
        return selected["content"]

    status = res.get("status_code", 0)
    if status != 200:
        raise RuntimeError(f"Bad Oxylabs response: {status} {res.get('error') or res.get('message') or ''}")
    if "content" not in res:
        raise RuntimeError("Oxylabs response missing 'content'")
    return res["content"]


# ========= Color/Variant Helpers =========
def _extract_available_colors(soup: BeautifulSoup, html: str) -> List[Dict[str, Any]]:
    """Extract available color variants from the page."""
    colors = []
    
    # Method 1: From DOM - variation selector
    variation_div = soup.select_one('[data-test="@web/VariationComponent"]')
    if variation_div:
        for link in variation_div.select('a[aria-label*="Color"]'):
            aria_label = link.get("aria-label", "")
            href = link.get("href", "")
            
            color_name = ""
            is_selected = "selected" in aria_label.lower()
            is_unavailable = "out of stock" in aria_label.lower() or "unavailable" in aria_label.lower()
            
            parts = aria_label.split(",")
            if len(parts) >= 2:
                color_name = parts[1].strip().split(" - ")[0].split(",")[0].strip()
            
            tcin = ""
            m = re.search(r'/A-(\d+)', href)
            if m:
                tcin = m.group(1)
            
            if color_name:
                colors.append({
                    "name": color_name,
                    "tcin": tcin,
                    "url": href if href.startswith("http") else f"https://www.target.com{href}",
                    "selected": is_selected,
                    "available": not is_unavailable,
                })
    
    # Method 2: From __TGT_DATA__ JSON
    if not colors:
        color_matches = re.findall(
            r'"variation_value"\\?:\\?"([^"]+)"\\?[^}]*"tcin"\\?:\\?"(\d+)"',
            html
        )
        for color_name, tcin in color_matches:
            if color_name and tcin:
                is_available = True
                tcin_section = re.search(rf'tcin["\s:\\]+{tcin}[^}}]{{0,500}}', html)
                if tcin_section:
                    section_text = tcin_section.group(0)
                    if 'OUT_OF_STOCK' in section_text or '"available":false' in section_text or '\\"available\\":false' in section_text:
                        is_available = False
                
                colors.append({
                    "name": color_name,
                    "tcin": tcin,
                    "url": f"https://www.target.com/p/-/A-{tcin}",
                    "selected": False,
                    "available": is_available,
                })
    
    return colors


def _get_url_for_color(base_url: str, color: str, soup: BeautifulSoup, html: str) -> Tuple[str, Optional[str]]:
    """Get the URL for a specific color variant."""
    if not color:
        return base_url, None
    
    color_lower = color.lower().strip()
    available_colors = _extract_available_colors(soup, html)
    
    if not available_colors:
        return base_url, "No color variants found on this product page"
    
    for c in available_colors:
        if c["name"].lower() == color_lower:
            if not c["available"]:
                return c["url"], f"Color '{color}' is out of stock"
            return c["url"], None
    
    available_names = [c["name"] for c in available_colors]
    return base_url, f"Color '{color}' not found. Available colors: {', '.join(available_names)}"


# ========= Main Scraper Function =========
def scrape_target_oxylabs(
    url: str,
    *,
    color: Optional[str] = None,
    save_dir: Path = SAVE_DIR,
    max_images: int = 15,
    convert_images_to_jpg: bool = True,
    verbose: bool = False,
) -> dict:
    """
    Scrape a Target product page.
    
    Args:
        url: The Target product URL
        color: Optional color variant to select
        save_dir: Directory to save images and data
        max_images: Maximum number of images to download
        convert_images_to_jpg: Whether to convert images to JPG format
        verbose: Print progress messages
    
    Returns:
        dict with product data including name, price, description, images,
        available_colors, selected_color, in_stock (based on selected color), etc.
    """
    color_error = None
    selected_color = None
    available_colors = []
    
    if verbose:
        print(f"Fetching {url}...")
    
    with requests.Session() as session:
        session.headers.update({"User-Agent": UA})

        res = _post_realtime_one(session, url)
        html = _result_content_or_error(res, requested_url=url)
        soup = BeautifulSoup(html, "lxml")
        
        available_colors = _extract_available_colors(soup, html)
        
        if color:
            new_url, color_error = _get_url_for_color(url, color, soup, html)
            
            if new_url != url:
                url = new_url
                res = _post_realtime_one(session, url)
                html = _result_content_or_error(res, requested_url=url)
                soup = BeautifulSoup(html, "lxml")
                selected_color = color
                available_colors = _extract_available_colors(soup, html)
        
        # Determine selected color if not explicitly set
        if not selected_color:
            for c in available_colors:
                if c.get("selected"):
                    selected_color = c["name"]
                    break
        
        slug = _slug_from_host(url) or "target"
        stable_id = _stable_id_from_url(url)

        # NAME
        name = ""
        node = soup.select_one('[data-module-type="ProductDetailTitle"] [data-test="product-title"]')
        if node:
            name = _clean(node.get_text(" ", strip=True))
        if not name:
            ogt = soup.select_one('meta[property="og:title"]')
            if ogt and ogt.get("content"):
                name = _clean(ogt["content"])
        name = name or "Unknown Product"

        # FOLDER
        folder = save_dir / f"{slug}_{_safe_name(name)}_{stable_id}"
        folder.mkdir(parents=True, exist_ok=True)

        # DEBUG: Save HTML
        if DEBUG_SAVE_HTML:
            (folder / "debug_page.html").write_text(html, encoding="utf-8")

        # PRICE
        price, price_source = _extract_price(soup, html)

        # STOCK - Get DOM-based detection as fallback
        in_stock, stock_text = _detect_stock(soup)

        # ============================================================
        # OVERRIDE: Use selected color availability as source of truth
        # ============================================================
        if available_colors and selected_color:
            for c in available_colors:
                if c["name"].lower() == selected_color.lower():
                    if not c["available"]:
                        in_stock = False
                        stock_text = f"{selected_color} - Out of stock"
                    else:
                        in_stock = True
                        stock_text = f"{selected_color} - In stock"
                    break
        
        # If no specific color but ALL colors unavailable
        elif available_colors:
            all_unavailable = all(not c["available"] for c in available_colors)
            any_available = any(c["available"] for c in available_colors)
            
            if all_unavailable:
                in_stock = False
                stock_text = "All variants out of stock"
            elif any_available:
                available_names = [c["name"] for c in available_colors if c["available"]]
                in_stock = True
                stock_text = f"Available in: {', '.join(available_names)}"

        # DESCRIPTION
        description = _extract_description(soup, html)

        # IMAGES
        image_urls = _collect_images_from_html(soup, html, max_images=max_images, product_url=url)
        
        if verbose:
            print(f"  Name: {name}")
            print(f"  Price: {price}")
            print(f"  Selected Color: {selected_color}")
            print(f"  In Stock: {in_stock}")
            print(f"  Stock Text: {stock_text}")
            print(f"  Images found: {len(image_urls)}")
        
        if convert_images_to_jpg:
            images_saved = _download_images_as_jpg(image_urls, folder, quality=90)
        else:
            images_saved = _download_images(image_urls, folder)

        out = {
            "url": url,
            "name": name,
            "selected_color": selected_color,
            "available_colors": [{"name": c["name"], "available": c["available"], "tcin": c["tcin"]} for c in available_colors] if available_colors else None,
            "color_error": color_error,
            "price": price,
            "price_source": price_source if price != "N/A" else "none",
            "in_stock": in_stock,
            "stock_text": stock_text or "",
            "description": description,
            "image_count": len(images_saved),
            "image_urls": image_urls,
            "images_downloaded": images_saved,
            "folder": str(folder),
            "fetched_via": f"oxylabs-{OXY_SOURCE}",
        }
        out = {k: v for k, v in out.items() if v is not None}
        (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        return out


# ========= Batch scraping =========
def scrape_target_batch_oxylabs(
    urls: Iterable[str],
    *,
    save_dir: Path = SAVE_DIR,
    max_images: int = 15,
    convert_images_to_jpg: bool = True,
) -> List[Dict[str, Any]]:
    urls = [u for u in urls if u]
    if not urls:
        return []
    save_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    with requests.Session() as session:
        session.headers.update({"User-Agent": UA})
        for u in urls:
            try:
                result = scrape_target_oxylabs(u, save_dir=save_dir, max_images=max_images, 
                                               convert_images_to_jpg=convert_images_to_jpg)
                results.append(result)
            except Exception as e:
                results.append({"url": u, "error": str(e)})
    return results


# # ========= CLI =========
# if __name__ == "__main__":
#     import sys
    
#     TEST_URL = "https://www.target.com/p/laura-ashley-4-5l-lightweight-stand-mixer-rose/-/A-93986328#lnk=sametab"
    
#     color_arg = sys.argv[1] if len(sys.argv) > 1 else None
    
#     data = scrape_target_oxylabs(
#         TEST_URL,
#         color=color_arg,
#         save_dir=SAVE_DIR,
#         max_images=15,
#         convert_images_to_jpg=True,
#         verbose=True,
#     )
#     print("\n" + "=" * 60)
#     print("RESULTS:")
#     print("=" * 60)
#     print(json.dumps(data, indent=2, ensure_ascii=False))