




# # walmart.py
# # Python 3.10+  |  Oxylabs walmart_product (JSON) + universal (HTML) fallback
# # pip install requests beautifulsoup4 lxml pillow

# import os
# import re
# import io
# import json
# import time
# import hashlib
# from pathlib import Path
# from typing import Optional, Tuple, List, Dict, Any
# from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode

# import requests
# from bs4 import BeautifulSoup
# from PIL import Image

# # ========= Secrets =========
# # Prefer the same pattern you used for QVC
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS  # type: ignore
# except Exception:
#     OXY_USER = os.getenv("OXYLABS_USERNAME", "")
#     OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")
# if not OXY_USER or not OXY_PASS:
#     raise RuntimeError("Set Oxylabs creds via oxylabs_secrets.py or env vars OXYLABS_USERNAME/PASSWORD.")

# # ========= Paths / Config =========
# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()
# SAVE_DIR = BASE_DIR / "data1"
# SAVE_DIR.mkdir(parents=True, exist_ok=True)

# UA_STR = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#     "AppleWebKit/537.36 (KHTML, like Gecko) "
#     "Chrome/127.0.0.0 Safari/537.36"
# )
# CURRENCY_SYMBOL = {"USD": "$", "GBP": "£", "EUR": "€", "CAD": "C$", "AUD": "A$"}
# OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"
# REQUEST_TIMEOUT = 90

# # ========= Helpers =========
# def _clean(s: str) -> str:
#     s = (s or "").replace("\r", "")
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

# def _extract_product_id(url: str) -> Optional[str]:
#     """
#     Walmart PDP canonical form has /ip/<slug>/<product_id>
#     """
#     m = re.search(r"/ip/(?:[^/]+)/(\d+)", urlsplit(url).path)
#     if m:
#         return m.group(1)
#     # fallback: any long digit blob in path
#     m2 = re.search(r"/(\d{7,})\b", urlsplit(url).path)
#     return m2.group(1) if m2 else None

# def _stable_id_from_url(url: str) -> str:
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

# def _drop_query(u: str) -> str:
#     parts = list(urlsplit(u)); parts[3] = ""; parts[4] = ""
#     return urlunsplit(parts)

# def _filename_id(u: str) -> str:
#     base = _drop_query(u)
#     fname = base.rsplit("/", 1)[-1]
#     fname = re.sub(r"\.(jpe?g|png|webp)$", "", fname, flags=re.I)
#     return fname.lower()

# def _parse_money_with_currency(val: str, currency_code: Optional[str]) -> str:
#     val = (val or "").strip()
#     sym = CURRENCY_SYMBOL.get((currency_code or "").upper(), "")
#     if sym and not val.startswith(sym):
#         return f"{sym}{val}"
#     return val or "N/A"

# def _parse_money_any(s: str) -> Optional[str]:
#     if not s:
#         return None
#     s = _clean(s)
#     m = re.search(r"([£$€]\s?\d[\d,]*(?:\.\d{2})?)", s)
#     if m:
#         return m.group(1).replace(" ", "")
#     m2 = re.search(r"(\d[\d,]*(?:\.\d{2})?)", s)
#     return "$" + m2.group(1) if m2 else None

# def _upgrade_walmart_image(u: str, size: int = 2000) -> str:
#     if "walmartimages.com" not in u:
#         return u
#     p = urlsplit(u)
#     qs = parse_qs(p.query, keep_blank_values=True)
#     qs["odnWidth"] = [str(size)]
#     qs["odnHeight"] = [str(size)]
#     qs.setdefault("odnBg", ["FFFFFF"])
#     new_q = urlencode({k: v[-1] for k, v in qs.items()})
#     return urlunsplit((p.scheme, p.netloc, p.path, new_q, ""))

# # ========= Oxylabs fetchers =========
# def _post_oxylabs(payload: Dict[str, Any]) -> Dict[str, Any]:
#     resp = requests.post(
#         OXY_ENDPOINT,
#         json=payload,
#         auth=(OXY_USER, OXY_PASS),
#         timeout=REQUEST_TIMEOUT,
#     )
#     if resp.status_code == 401:
#         raise RuntimeError("Oxylabs Unauthorized (401). Check OXY_USER/OXY_PASS.")
#     if not resp.ok:
#         raise RuntimeError(f"Oxylabs failed: HTTP {resp.status_code} - {resp.text[:400]}")
#     try:
#         return resp.json()
#     except Exception as e:
#         raise RuntimeError(f"Oxylabs response not JSON: {e}; text head: {resp.text[:200]}")

# def _fetch_walmart_parsed(product_id: str, delivery_zip: Optional[str] = None, store_id: Optional[str] = None) -> Dict[str, Any]:
#     """
#     walmart_product — returns parsed JSON (fast, stable)
#     """
#     payload: Dict[str, Any] = {
#         "source": "walmart_product",
#         "product_id": product_id,
#     }
#     # Optional location knobs (improves stock for some SKUs)
#     context: Dict[str, Any] = {}
#     if delivery_zip:
#         context["delivery_zip"] = delivery_zip
#     if store_id:
#         context["store_id"] = store_id
#     if context:
#         payload["context"] = context

#     data = _post_oxylabs(payload)
#     # Standard: results[0].content parsed JSON
#     if isinstance(data, dict) and data.get("results"):
#         c = data["results"][0].get("content")
#         if isinstance(c, dict):
#             return c
#     # Some schemas use top-level content
#     if isinstance(data, dict) and isinstance(data.get("content"), dict):
#         return data["content"]
#     raise RuntimeError("walmart_product returned no parsed content")

# def _fetch_html_universal(url: str) -> str:
#     payload = {
#         "source": "universal",
#         "url": url,
#         "render": "html",
#         "user_agent": UA_STR,
#         "geo_location": "United States",
#     }
#     data = _post_oxylabs(payload)
#     # Standard: results[0].content holds HTML
#     if isinstance(data, dict) and data.get("results"):
#         c = data["results"][0].get("content")
#         if isinstance(c, str):
#             return c
#     if isinstance(data, dict) and isinstance(data.get("content"), str):
#         return data["content"]
#     raise RuntimeError("universal returned no HTML content")

# # ========= Parsers (from parsed JSON) =========
# def _from_parsed_name(j: Dict[str, Any]) -> Optional[str]:
#     for path in [
#         ("product", "name"),
#         ("name",),
#         ("payload", "product", "name"),
#     ]:
#         t = j
#         ok = True
#         for k in path:
#             if isinstance(t, dict) and k in t:
#                 t = t[k]
#             else:
#                 ok = False; break
#         if ok and isinstance(t, str) and t.strip():
#             return _clean(t)
#     return None

# def _from_parsed_price(j: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
#     try_paths = [
#         ("product", "priceInfo", "currentPrice", "priceString"),
#         ("product", "priceInfo", "currentPrice", "price"),
#         ("priceInfo", "currentPrice", "priceString"),
#         ("priceInfo", "currentPrice", "price"),
#         ("offers", "price"),
#     ]
#     currency_paths = [
#         ("product", "priceInfo", "currentPrice", "currencyUnit"),
#         ("priceInfo", "currentPrice", "currencyUnit"),
#         ("offers", "priceCurrency"),
#     ]
#     val: Optional[str] = None
#     currency: Optional[str] = None
#     for p in currency_paths:
#         t = j; ok = True
#         for k in p:
#             if isinstance(t, dict) and k in t:
#                 t = t[k]
#             else:
#                 ok = False; break
#         if ok and isinstance(t, str) and t.strip():
#             currency = t.strip().upper()
#             break
#     for p in try_paths:
#         t = j; ok = True
#         for k in p:
#             if isinstance(t, dict) and k in t:
#                 t = t[k]
#             else:
#                 ok = False; break
#         if ok:
#             if isinstance(t, (int, float)):
#                 val = f"{t:.2f}"
#             elif isinstance(t, str):
#                 val = _clean(t)
#             if val:
#                 if re.search(r"[£$€]\s*\d", val):
#                     return val.replace(" ", ""), currency
#                 money = _parse_money_any(val)
#                 if money:
#                     return money, currency
#                 if currency:
#                     return _parse_money_with_currency(val, currency), currency
#     return None, currency

# def _from_parsed_stock(j: Dict[str, Any]) -> Tuple[Optional[bool], str]:
#     txt = ""
#     for p in [
#         ("product", "availabilityStatus"),
#         ("availabilityStatus",),
#         ("product", "availability", "status"),
#     ]:
#         t = j; ok = True
#         for k in p:
#             if isinstance(t, dict) and k in t:
#                 t = t[k]
#             else:
#                 ok = False; break
#         if ok and isinstance(t, str) and t.strip():
#             v = t.upper()
#             txt = t
#             if "IN_STOCK" in v or v in ("AVAILABLE", "INSTORE", "ONLINE"):
#                 return True, t
#             if "OUT" in v or "UNAVAILABLE" in v or "NOT_AVAILABLE" in v:
#                 return False, t
#     return None, txt

# def _from_parsed_images(j: Dict[str, Any]) -> List[str]:
#     urls: List[str] = []
#     candidates = []
#     for p in [
#         ("product", "images"),
#         ("images",),
#         ("product", "imageInfo", "allImages"),
#     ]:
#         t = j; ok = True
#         for k in p:
#             if isinstance(t, dict) and k in t:
#                 t = t[k]
#             else:
#                 ok = False; break
#         if ok and isinstance(t, list):
#             candidates.extend(t)

#     for item in candidates:
#         if isinstance(item, str) and item.strip():
#             urls.append(item)
#         elif isinstance(item, dict):
#             for k in ("url", "assetUrl", "thumbnailUrl"):
#                 if item.get(k):
#                     urls.append(str(item[k]))

#     out: List[str] = []
#     seen = set()
#     for u in urls:
#         nu = _upgrade_walmart_image(u, 2000)
#         key = _filename_id(nu) or hashlib.sha1(nu.encode("utf-8")).hexdigest()[:16]
#         if key in seen:
#             continue
#         seen.add(key)
#         out.append(nu)
#     return out

# # ========= HTML parsers (fallback) =========
# def _pick_from_src_or_srcset(img) -> Optional[str]:
#     if img.get("currentSrc"):
#         return img["currentSrc"]
#     if img.get("src"):
#         return img["src"]
#     ss = img.get("srcset") or ""
#     if ss:
#         last = ss.split(",")[-1].strip()
#         return last.split(" ")[0]
#     return None

# def _collect_images_from_html(soup: BeautifulSoup, max_images: Optional[int] = None) -> List[str]:
#     """
#     Collect images from the vertical carousel container.
#     Priority: srcset (higher res) > src
#     """
#     urls: List[str] = []
    
#     # Find the carousel container
#     root = soup.select_one('[data-testid="vertical-carousel-container"]')
#     if not root:
#         root = soup
    
#     # Find all image buttons in the carousel
#     for button in root.select('button[data-testid="item-page-vertical-carousel-hero-image-button"]'):
#         img = button.select_one("img")
#         if not img:
#             continue
        
#         # Try to get the best quality image from srcset
#         srcset = img.get("srcset", "")
#         src = img.get("src", "")
        
#         best_url = None
        
#         if srcset:
#             # Parse srcset and get the largest image (usually 2x)
#             parts = [p.strip() for p in srcset.split(",") if p.strip()]
#             best_w = -1
#             for part in parts:
#                 # Format: "url 1x" or "url 2x" or "url 160w"
#                 match = re.match(r"(\S+)\s+(\d+)([wx])", part)
#                 if match:
#                     url_part = match.group(1)
#                     num = int(match.group(2))
#                     unit = match.group(3)
#                     # Prefer 2x over 1x, or higher width
#                     weight = num * 1000 if unit == 'x' else num
#                     if weight > best_w:
#                         best_w = weight
#                         best_url = url_part
#                 else:
#                     # Just URL without descriptor
#                     tokens = part.split()
#                     if tokens:
#                         best_url = tokens[0]
        
#         # Fallback to src
#         if not best_url and src and not src.startswith("data:"):
#             best_url = src
        
#         if best_url and "walmartimages.com" in best_url:
#             urls.append(best_url)
    
#     # If no buttons found, try generic img selection
#     if not urls:
#         for img in root.select("img"):
#             src = img.get("src", "")
#             if src and "walmartimages.com" in src and not src.startswith("data:"):
#                 urls.append(src)
    
#     # Deduplicate and upgrade to high quality
#     seen = set()
#     final: List[str] = []
#     for u in urls:
#         # Upgrade to high quality
#         nu = _upgrade_walmart_image(u, 2000)
        
#         # Use the unique part of the URL (UUID) as the key
#         # Example: c7d6faf5-e5b5-4f91-87c1-a234bff51e1a
#         key = None
#         uuid_match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', nu)
#         if uuid_match:
#             key = uuid_match.group(1)
#         else:
#             # Fallback to filename
#             key = _filename_id(nu) or hashlib.sha1(nu.encode("utf-8")).hexdigest()[:16]
        
#         if key in seen:
#             continue
#         seen.add(key)
#         final.append(nu)
        
#         if max_images and len(final) >= max_images:
#             break
    
#     return final

# def _extract_images_from_scripts(soup: BeautifulSoup) -> List[str]:
#     """
#     Walmart often embeds full gallery arrays in JSON (e.g., imageInfo.allImages).
#     This recursively walks any JSON-like scripts and collects image URLs.
#     """
#     urls: List[str] = []

#     def _walk(o):
#         if isinstance(o, dict):
#             if "allImages" in o and isinstance(o["allImages"], list):
#                 for it in o["allImages"]:
#                     if isinstance(it, dict):
#                         for k in ("url", "assetUrl", "thumbnailUrl"):
#                             if isinstance(it.get(k), str):
#                                 urls.append(it[k])
#             if "images" in o and isinstance(o["images"], list):
#                 for it in o["images"]:
#                     if isinstance(it, str):
#                         urls.append(it)
#                     elif isinstance(it, dict):
#                         for k in ("url", "assetUrl", "thumbnailUrl"):
#                             if isinstance(it.get(k), str):
#                                 urls.append(it.get(k))
#             for v in o.values():
#                 _walk(v)
#         elif isinstance(o, list):
#             for v in o:
#                 _walk(v)

#     for sc in soup.find_all("script"):
#         txt = sc.string or sc.get_text(separator="", strip=True) or ""
#         if not txt:
#             continue
#         txt_stripped = txt.strip()
#         if not (txt_stripped.startswith("{") or txt_stripped.startswith("[")):
#             continue
#         try:
#             data = json.loads(txt_stripped)
#             _walk(data)
#         except Exception:
#             continue

#     out: List[str] = []
#     seen = set()
#     for u in urls:
#         if not isinstance(u, str) or "walmartimages.com" not in u:
#             continue
#         nu = _upgrade_walmart_image(u, 2000)
#         key = _filename_id(nu) or hashlib.sha1(nu.encode("utf-8")).hexdigest()[:16]
#         if key in seen:
#             continue
#         seen.add(key)
#         out.append(nu)
#     return out

# def _parse_description_from_html(soup: BeautifulSoup) -> str:
#     root = soup.select_one('[data-testid="product-description-content"]')
#     if not root:
#         for sel in ("#product-description", ".dangerous-html", ".expand-collapse-content",
#                     ".w_rNem", ".mb3 .dangerous-html"):
#             root = soup.select_one(sel)
#             if root:
#                 break
#     if not root:
#         meta = soup.select_one('meta[name="description"]')
#         return _clean(meta["content"]) if meta and meta.get("content") else ""

#     INTRO_STOP_TAGS = {"ul", "ol"}
#     DROP_PATTS = (
#         r"^info:\s*$",
#         r"^we aim to show you accurate product information\.",
#         r"^see our disclaimer$",
#     )

#     intro_lines: List[str] = []
#     for node in root.descendants:
#         tag = getattr(node, "name", None)
#         if tag in INTRO_STOP_TAGS:
#             break
#         if tag in {"p", "div", "span"}:
#             t = _clean(getattr(node, "get_text", lambda *_: "")(" ", strip=True))
#             if not t:
#                 continue
#             low = t.lower()
#             if any(re.search(p, low, re.I) for p in DROP_PATTS):
#                 continue
#             if len(t) >= 40:
#                 intro_lines.append(t)
#                 if len(intro_lines) >= 2:
#                     break

#     bullets: List[str] = []
#     for li in root.select("ul li, ol li"):
#         t = _clean(li.get_text(" ", strip=True))
#         if t:
#             bullets.append(f"• {t}")

#     parts: List[str] = []
#     seen = set()
#     intro_lines = [x for x in intro_lines if not (x in seen or seen.add(x))]
#     if intro_lines:
#         parts.append("\n\n".join(intro_lines))
#     if bullets:
#         parts.append("\n".join(bullets))

#     text = "\n\n".join(parts).strip()
#     if text:
#         return text
#     return _clean(root.get_text(" ", strip=True))

# def _extract_price_from_html(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
#     node = soup.select_one('[itemprop="price"][data-seo-id="hero-price"]') or soup.select_one('[itemprop="price"]')
#     if node:
#         money = _parse_money_any(node.get_text(" ", strip=True))
#         if money:
#             return money, None
#     og = soup.select_one('meta[property="product:price:amount"]')
#     if og and og.get("content"):
#         money = _parse_money_any(og["content"])
#         if money:
#             cur = None
#             ogc = soup.select_one('meta[property="product:price:currency"]')
#             if ogc and ogc.get("content"):
#                 cur = ogc["content"].strip().upper()
#             return money, cur
#     return None, None

# def _detect_stock_from_html(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
#     buy = soup.find(string=re.compile(r"\bAdd to cart\b", re.I))
#     if buy:
#         return True, "Add to cart available"
#     body = _clean(soup.get_text(" ", strip=True))
#     if re.search(r"\b(sold out|out of stock|not available|unavailable|temporarily unavailable)\b", body, re.I):
#         return False, "Unavailable"
#     price_node = soup.select_one('[itemprop="price"]')
#     if price_node and _parse_money_any(price_node.get_text(" ", strip=True)):
#         return True, "Price present"
#     return None, ""

# # ========= Download & convert images =========
# def _download_images(urls: List[str], folder: Path, *, convert_to_jpg: bool = True, quality: int = 90) -> List[str]:
#     saved: List[str] = []
#     folder.mkdir(parents=True, exist_ok=True)
#     with requests.Session() as s:
#         s.headers.update({
#             "User-Agent": UA_STR,
#             "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
#         })
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

# # ========= Main scraper =========
# def scrape_walmart_via_oxylabs(
#     url: str,
#     save_dir: Path = SAVE_DIR,
#     *,
#     convert_images_to_jpg: bool = True,
#     delivery_zip: Optional[str] = None,
#     store_id: Optional[str] = None,
# ) -> Dict[str, Any]:
#     """
#     1) Call walmart_product with product_id (fast & reliable for price/stock)
#     2) Fallback to universal HTML to enrich name/description/images
    
#     NOTE: For images, we PRIORITIZE the HTML carousel as it only shows
#     images for the selected variant, not all color variants.
#     """
#     save_dir.mkdir(parents=True, exist_ok=True)
#     product_id = _extract_product_id(url)
#     stable_id = product_id or _stable_id_from_url(url)

#     name: Optional[str] = None
#     price: Optional[str] = None
#     currency: Optional[str] = "USD"
#     in_stock: Optional[bool] = None
#     stock_text: str = ""
#     desc: str = ""
#     images_from_api: List[str] = []

#     # 1) walmart_product API (for price/stock/name - NOT images)
#     parsed: Dict[str, Any] = {}
#     if product_id:
#         try:
#             parsed = _fetch_walmart_parsed(product_id, delivery_zip=delivery_zip, store_id=store_id)
#             name = _from_parsed_name(parsed) or name
#             pval, cur = _from_parsed_price(parsed)
#             price = pval or price
#             currency = cur or currency
#             inst, stxt = _from_parsed_stock(parsed)
#             in_stock = inst if inst is not None else in_stock
#             stock_text = stxt or stock_text
#             # Store API images as fallback only
#             images_from_api = _from_parsed_images(parsed) or []
#         except Exception:
#             pass

#     # 2) universal HTML
#     html = ""
#     soup = None
#     try:
#         html = _fetch_html_universal(url)
#         soup = BeautifulSoup(html, "lxml")
#     except Exception:
#         soup = None

#     # price fallback
#     if (price is None) and soup is not None:
#         p, cur = _extract_price_from_html(soup)
#         if p:
#             price = p
#         if cur:
#             currency = cur

#     # stock fallback
#     if (in_stock is None) and soup is not None:
#         inst, stxt = _detect_stock_from_html(soup)
#         in_stock = inst
#         if stxt:
#             stock_text = stxt

#     # name fallback
#     if (not name) and soup is not None:
#         h1 = soup.select_one("h1") or soup.select_one('[itemprop="name"]')
#         if h1:
#             name = _clean(h1.get_text(" ", strip=True))
#     if not name:
#         name = "Unknown Product"

#     # description
#     if soup is not None:
#         desc = _parse_description_from_html(soup)

#     # ============================================================
#     # IMAGES: Prioritize HTML carousel (shows only selected variant)
#     # Only fall back to API images if carousel is empty
#     # ============================================================
#     images: List[str] = []
    
#     if soup is not None:
#         # First try: DOM carousel (most reliable for current variant)
#         images = _collect_images_from_html(soup, max_images=None)
    
#     # Only use API/script images if DOM carousel failed
#     if not images and soup is not None:
#         images = _extract_images_from_scripts(soup)
    
#     # Last resort: API images (may include other variants)
#     if not images:
#         images = images_from_api

#     # Folder
#     folder = save_dir / f"{_retailer_slug(url)}_{_safe_name(name)}_{stable_id}"
#     folder.mkdir(parents=True, exist_ok=True)

#     # Save HTML for debugging
#     try:
#         (folder / "raw_html.html").write_text(html or "", encoding="utf-8")
#     except Exception:
#         pass

#     # Download images
#     downloaded = _download_images(images, folder, convert_to_jpg=convert_images_to_jpg) if images else []

#     out = {
#         "url": urlsplit(url)._replace(query="").geturl(),
#         "name": name,
#         "price": price or "N/A",
#         "currency": currency or "",
#         "in_stock": in_stock,
#         "stock_text": stock_text,
#         "description": desc,
#         "image_count": len(downloaded),
#         "images": downloaded,
#         "folder": str(folder),
#         "fetched_via": "oxylabs-walmart_product+universal",
#     }
#     (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
#     return out

# # ========= CLI =========
# if __name__ == "__main__":
#     TEST_URL = "https://www.walmart.com/ip/VQ-Laura-Ashley-1-7L-Dome-Kettle-Elveden-Navy/14613657687"
#     data = scrape_walmart_via_oxylabs(
#         TEST_URL,
#         save_dir=SAVE_DIR,
#         convert_images_to_jpg=True,
#         delivery_zip=None,   # e.g. "10001" to influence stock
#         store_id=None,       # e.g. Walmart store ID to influence pickup stock
#     )
#     print(json.dumps(data, indent=2, ensure_ascii=False))








# walmart.py
# Python 3.10+  |  Oxylabs walmart_product (JSON) + universal (HTML) fallback
# Version 2.2 - Fixed image extraction to get all variant images
# pip install requests beautifulsoup4 lxml pillow

import os
import re
import io
import json
import time
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup
from PIL import Image

__version__ = "2.2"

# ========= Secrets =========
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")
if not OXY_USER or not OXY_PASS:
    raise RuntimeError("Set Oxylabs creds via oxylabs_secrets.py or env vars OXYLABS_USERNAME/PASSWORD.")

# ========= Paths / Config =========
try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()
SAVE_DIR = BASE_DIR / "data1"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

UA_STR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)
CURRENCY_SYMBOL = {"USD": "$", "GBP": "£", "EUR": "€", "CAD": "C$", "AUD": "A$"}
OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"
REQUEST_TIMEOUT = 120
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


# ========= Helpers =========
def _clean(s: str) -> str:
    s = (s or "").replace("\r", "")
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


def _extract_product_id(url: str) -> Optional[str]:
    m = re.search(r"/ip/(?:[^/]+)/(\d+)", urlsplit(url).path)
    if m:
        return m.group(1)
    m2 = re.search(r"/(\d{7,})\b", urlsplit(url).path)
    return m2.group(1) if m2 else None


def _stable_id_from_url(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _drop_query(u: str) -> str:
    parts = list(urlsplit(u))
    parts[3] = ""
    parts[4] = ""
    return urlunsplit(parts)


def _filename_id(u: str) -> str:
    base = _drop_query(u)
    fname = base.rsplit("/", 1)[-1]
    fname = re.sub(r"\.(jpe?g|png|webp)$", "", fname, flags=re.I)
    return fname.lower()


def _get_image_key(u: str) -> str:
    """Get unique key for image deduplication - prefer UUID."""
    uuid_match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', u)
    if uuid_match:
        return uuid_match.group(1).lower()
    # Fallback: use the hash part after the UUID-like segment
    hash_match = re.search(r'\.([a-f0-9]{32})\.(jpeg|jpg|png|webp)', u, re.I)
    if hash_match:
        return hash_match.group(1).lower()
    return _filename_id(u) or hashlib.sha1(u.encode("utf-8")).hexdigest()[:16]


def _parse_money_with_currency(val: str, currency_code: Optional[str]) -> str:
    val = (val or "").strip()
    sym = CURRENCY_SYMBOL.get((currency_code or "").upper(), "")
    if sym and not val.startswith(sym):
        return f"{sym}{val}"
    return val or "N/A"


def _parse_money_any(s: str) -> Optional[str]:
    if not s:
        return None
    s = _clean(s)
    m = re.search(r"([£$€]\s?\d[\d,]*(?:\.\d{2})?)", s)
    if m:
        return m.group(1).replace(" ", "")
    m2 = re.search(r"(\d[\d,]*(?:\.\d{2})?)", s)
    return "$" + m2.group(1) if m2 else None


def _upgrade_walmart_image(u: str, size: int = 2000) -> str:
    if "walmartimages.com" not in u:
        return u
    p = urlsplit(u)
    qs = parse_qs(p.query, keep_blank_values=True)
    qs["odnWidth"] = [str(size)]
    qs["odnHeight"] = [str(size)]
    qs.setdefault("odnBg", ["FFFFFF"])
    new_q = urlencode({k: v[-1] for k, v in qs.items()})
    return urlunsplit((p.scheme, p.netloc, p.path, new_q, ""))


# ========= Oxylabs fetchers with retry =========
def _post_oxylabs(payload: Dict[str, Any], verbose: bool = False) -> Dict[str, Any]:
    """Post to Oxylabs with retry logic."""
    attempt = 0
    last_error = None
    
    while attempt < MAX_RETRIES:
        attempt += 1
        try:
            resp = requests.post(
                OXY_ENDPOINT,
                json=payload,
                auth=(OXY_USER, OXY_PASS),
                timeout=REQUEST_TIMEOUT,
            )
            
            if resp.status_code == 401:
                raise RuntimeError("Oxylabs Unauthorized (401). Check OXY_USER/OXY_PASS.")
            
            if resp.ok:
                try:
                    return resp.json()
                except Exception as e:
                    raise RuntimeError(f"Oxylabs response not JSON: {e}; text head: {resp.text[:200]}")
            
            last_error = f"HTTP {resp.status_code} - {resp.text[:200]}"
            if verbose:
                print(f"  ⚠️ Oxylabs attempt {attempt}/{MAX_RETRIES} failed: {last_error}")
                
        except requests.exceptions.ReadTimeout:
            last_error = "Read timeout"
            if verbose:
                print(f"  ⚠️ Oxylabs attempt {attempt}/{MAX_RETRIES} timed out")
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            if verbose:
                print(f"  ⚠️ Oxylabs attempt {attempt}/{MAX_RETRIES} error: {e}")
        
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF * attempt)
    
    raise RuntimeError(f"Oxylabs failed after {MAX_RETRIES} attempts: {last_error}")


def _fetch_walmart_parsed(product_id: str, delivery_zip: Optional[str] = None, 
                          store_id: Optional[str] = None, verbose: bool = False) -> Dict[str, Any]:
    """walmart_product — returns parsed JSON."""
    payload: Dict[str, Any] = {
        "source": "walmart_product",
        "product_id": product_id,
    }
    context: Dict[str, Any] = {}
    if delivery_zip:
        context["delivery_zip"] = delivery_zip
    if store_id:
        context["store_id"] = store_id
    if context:
        payload["context"] = context

    data = _post_oxylabs(payload, verbose=verbose)
    
    if isinstance(data, dict) and data.get("results"):
        c = data["results"][0].get("content")
        if isinstance(c, dict):
            return c
    if isinstance(data, dict) and isinstance(data.get("content"), dict):
        return data["content"]
    raise RuntimeError("walmart_product returned no parsed content")


def _fetch_html_universal(url: str, verbose: bool = False) -> str:
    """Fetch HTML via universal source with retry."""
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
        "user_agent": UA_STR,
        "geo_location": "United States",
    }
    data = _post_oxylabs(payload, verbose=verbose)
    
    if isinstance(data, dict) and data.get("results"):
        c = data["results"][0].get("content")
        if isinstance(c, str):
            return c
    if isinstance(data, dict) and isinstance(data.get("content"), str):
        return data["content"]
    raise RuntimeError("universal returned no HTML content")


# ========= Parsers (from parsed JSON) =========
def _from_parsed_name(j: Dict[str, Any]) -> Optional[str]:
    for path in [
        ("product", "name"),
        ("name",),
        ("payload", "product", "name"),
    ]:
        t = j
        ok = True
        for k in path:
            if isinstance(t, dict) and k in t:
                t = t[k]
            else:
                ok = False
                break
        if ok and isinstance(t, str) and t.strip():
            return _clean(t)
    return None


def _from_parsed_price(j: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    try_paths = [
        ("product", "priceInfo", "currentPrice", "priceString"),
        ("product", "priceInfo", "currentPrice", "price"),
        ("priceInfo", "currentPrice", "priceString"),
        ("priceInfo", "currentPrice", "price"),
        ("offers", "price"),
    ]
    currency_paths = [
        ("product", "priceInfo", "currentPrice", "currencyUnit"),
        ("priceInfo", "currentPrice", "currencyUnit"),
        ("offers", "priceCurrency"),
    ]
    val: Optional[str] = None
    currency: Optional[str] = None
    
    for p in currency_paths:
        t = j
        ok = True
        for k in p:
            if isinstance(t, dict) and k in t:
                t = t[k]
            else:
                ok = False
                break
        if ok and isinstance(t, str) and t.strip():
            currency = t.strip().upper()
            break
            
    for p in try_paths:
        t = j
        ok = True
        for k in p:
            if isinstance(t, dict) and k in t:
                t = t[k]
            else:
                ok = False
                break
        if ok:
            if isinstance(t, (int, float)):
                val = f"{t:.2f}"
            elif isinstance(t, str):
                val = _clean(t)
            if val:
                if re.search(r"[£$€]\s*\d", val):
                    return val.replace(" ", ""), currency
                money = _parse_money_any(val)
                if money:
                    return money, currency
                if currency:
                    return _parse_money_with_currency(val, currency), currency
    return None, currency


def _from_parsed_stock(j: Dict[str, Any]) -> Tuple[Optional[bool], str]:
    txt = ""
    for p in [
        ("product", "availabilityStatus"),
        ("availabilityStatus",),
        ("product", "availability", "status"),
    ]:
        t = j
        ok = True
        for k in p:
            if isinstance(t, dict) and k in t:
                t = t[k]
            else:
                ok = False
                break
        if ok and isinstance(t, str) and t.strip():
            v = t.upper()
            txt = t
            if "IN_STOCK" in v or v in ("AVAILABLE", "INSTORE", "ONLINE"):
                return True, t
            if "OUT" in v or "UNAVAILABLE" in v or "NOT_AVAILABLE" in v:
                return False, t
    return None, txt


# ========= HTML parsers =========
def _extract_price_from_html(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
    node = soup.select_one('[itemprop="price"][data-seo-id="hero-price"]') or soup.select_one('[itemprop="price"]')
    if node:
        money = _parse_money_any(node.get_text(" ", strip=True))
        if money:
            return money, None
    og = soup.select_one('meta[property="product:price:amount"]')
    if og and og.get("content"):
        money = _parse_money_any(og["content"])
        if money:
            cur = None
            ogc = soup.select_one('meta[property="product:price:currency"]')
            if ogc and ogc.get("content"):
                cur = ogc["content"].strip().upper()
            return money, cur
    return None, None


def _detect_stock_from_html(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
    buy = soup.find(string=re.compile(r"\bAdd to cart\b", re.I))
    if buy:
        return True, "Add to cart available"
    body = _clean(soup.get_text(" ", strip=True))
    if re.search(r"\b(sold out|out of stock|not available|unavailable|temporarily unavailable)\b", body, re.I):
        return False, "Unavailable"
    price_node = soup.select_one('[itemprop="price"]')
    if price_node and _parse_money_any(price_node.get_text(" ", strip=True)):
        return True, "Price present"
    return None, ""


def _parse_description_from_html(soup: BeautifulSoup) -> str:
    root = soup.select_one('[data-testid="product-description-content"]')
    if not root:
        for sel in ("#product-description", ".dangerous-html", ".expand-collapse-content",
                    ".w_rNem", ".mb3 .dangerous-html"):
            root = soup.select_one(sel)
            if root:
                break
    if not root:
        meta = soup.select_one('meta[name="description"]')
        return _clean(meta["content"]) if meta and meta.get("content") else ""

    INTRO_STOP_TAGS = {"ul", "ol"}
    DROP_PATTS = (
        r"^info:\s*$",
        r"^we aim to show you accurate product information\.",
        r"^see our disclaimer$",
    )

    intro_lines: List[str] = []
    for node in root.descendants:
        tag = getattr(node, "name", None)
        if tag in INTRO_STOP_TAGS:
            break
        if tag in {"p", "div", "span"}:
            t = _clean(getattr(node, "get_text", lambda *_: "")(" ", strip=True))
            if not t:
                continue
            low = t.lower()
            if any(re.search(p, low, re.I) for p in DROP_PATTS):
                continue
            if len(t) >= 40:
                intro_lines.append(t)
                if len(intro_lines) >= 2:
                    break

    bullets: List[str] = []
    for li in root.select("ul li, ol li"):
        t = _clean(li.get_text(" ", strip=True))
        if t:
            bullets.append(f"• {t}")

    parts: List[str] = []
    seen = set()
    intro_lines = [x for x in intro_lines if not (x in seen or seen.add(x))]
    if intro_lines:
        parts.append("\n\n".join(intro_lines))
    if bullets:
        parts.append("\n".join(bullets))

    text = "\n\n".join(parts).strip()
    if text:
        return text
    return _clean(root.get_text(" ", strip=True))


# ========= Image extraction =========
def _collect_images_from_carousel(soup: BeautifulSoup) -> Tuple[List[str], Optional[int]]:
    """
    Collect images from the vertical carousel.
    Returns (urls, expected_count) where expected_count is parsed from alt text.
    """
    urls: List[str] = []
    expected_count: Optional[int] = None
    
    root = soup.select_one('[data-testid="vertical-carousel-container"]')
    if not root:
        return [], None
    
    for button in root.select('button[data-testid="item-page-vertical-carousel-hero-image-button"]'):
        img = button.select_one("img")
        if not img:
            continue
        
        # Extract expected count from alt text (e.g., "1 of 9")
        alt = img.get("alt", "")
        count_match = re.search(r'(\d+)\s+of\s+(\d+)', alt)
        if count_match and expected_count is None:
            expected_count = int(count_match.group(2))
        
        # Get image URL from srcset or src
        srcset = img.get("srcset", "")
        src = img.get("src", "")
        
        best_url = None
        
        if srcset:
            parts = [p.strip() for p in srcset.split(",") if p.strip()]
            best_w = -1
            for part in parts:
                match = re.match(r"(\S+)\s+(\d+)([wx])", part)
                if match:
                    url_part = match.group(1)
                    num = int(match.group(2))
                    unit = match.group(3)
                    weight = num * 1000 if unit == 'x' else num
                    if weight > best_w:
                        best_w = weight
                        best_url = url_part
                else:
                    tokens = part.split()
                    if tokens:
                        best_url = tokens[0]
        
        if not best_url and src and not src.startswith("data:"):
            best_url = src
        
        if best_url and "walmartimages.com" in best_url:
            urls.append(best_url)
    
    return urls, expected_count


def _extract_images_from_scripts_current_variant(soup: BeautifulSoup, product_id: Optional[str] = None) -> List[str]:
    """
    Extract images for the CURRENT variant from embedded JSON scripts.
    Looks for imageInfo.allImages which contains the current product's images.
    """
    urls: List[str] = []
    
    for sc in soup.find_all("script"):
        txt = sc.string or sc.get_text(separator="", strip=True) or ""
        if not txt or len(txt) < 500:
            continue
        
        # Skip non-JSON scripts
        if not ('{' in txt and 'image' in txt.lower()):
            continue
        
        # Method 1: Look for imageInfo.allImages pattern (most reliable for current variant)
        # This pattern: "imageInfo":{"allImages":[{"url":"..."},{"url":"..."}]}
        all_images_matches = re.findall(
            r'"allImages"\s*:\s*\[((?:[^\[\]]*(?:\[[^\[\]]*\])?)*)\]',
            txt
        )
        
        for match in all_images_matches:
            # Extract URLs from this array
            url_matches = re.findall(r'"url"\s*:\s*"(https?://[^"]+walmartimages[^"]+)"', match)
            if url_matches:
                urls.extend(url_matches)
                break  # Found the main image array
        
        if urls:
            break
        
        # Method 2: Look for product-specific images array
        # Pattern: "images":["url1","url2",...] near product ID
        if product_id:
            # Find section containing our product ID
            pid_pos = txt.find(product_id)
            if pid_pos != -1:
                # Look for images array within 5000 chars of product ID
                search_start = max(0, pid_pos - 2000)
                search_end = min(len(txt), pid_pos + 5000)
                section = txt[search_start:search_end]
                
                images_match = re.search(r'"images"\s*:\s*\[([^\]]+)\]', section)
                if images_match:
                    array_content = images_match.group(1)
                    url_matches = re.findall(r'"(https?://[^"]+walmartimages[^"]+)"', array_content)
                    urls.extend(url_matches)
        
        # Method 3: Generic imageInfo extraction
        if not urls:
            image_info_match = re.search(
                r'"imageInfo"\s*:\s*\{[^}]*"allImages"\s*:\s*\[([^\]]+)\]',
                txt
            )
            if image_info_match:
                array_content = image_info_match.group(1)
                url_matches = re.findall(r'"url"\s*:\s*"([^"]+)"', array_content)
                for url in url_matches:
                    if "walmartimages.com" in url:
                        urls.append(url)
    
    return urls


def _extract_all_images_from_scripts(soup: BeautifulSoup) -> List[str]:
    """
    Extract ALL images from scripts (fallback - may include other variants).
    """
    urls: List[str] = []

    def _walk(o):
        if isinstance(o, dict):
            if "allImages" in o and isinstance(o["allImages"], list):
                for it in o["allImages"]:
                    if isinstance(it, dict):
                        for k in ("url", "assetUrl", "thumbnailUrl"):
                            if isinstance(it.get(k), str):
                                urls.append(it[k])
            if "images" in o and isinstance(o["images"], list):
                for it in o["images"]:
                    if isinstance(it, str):
                        urls.append(it)
                    elif isinstance(it, dict):
                        for k in ("url", "assetUrl", "thumbnailUrl"):
                            if isinstance(it.get(k), str):
                                urls.append(it.get(k))
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)

    for sc in soup.find_all("script"):
        txt = sc.string or sc.get_text(separator="", strip=True) or ""
        if not txt:
            continue
        txt_stripped = txt.strip()
        if not (txt_stripped.startswith("{") or txt_stripped.startswith("[")):
            continue
        try:
            data = json.loads(txt_stripped)
            _walk(data)
        except Exception:
            continue

    return [u for u in urls if isinstance(u, str) and "walmartimages.com" in u]


def _collect_images_from_html(soup: BeautifulSoup, product_id: Optional[str] = None, 
                               max_images: Optional[int] = None, verbose: bool = False) -> List[str]:
    """
    Collect images for the current product variant.
    
    Strategy:
    1. Get carousel images and expected count from alt text
    2. If carousel has fewer than expected, supplement from scripts
    3. Deduplicate and upgrade to high quality
    """
    # Step 1: Get carousel images
    carousel_urls, expected_count = _collect_images_from_carousel(soup)
    
    if verbose:
        print(f"    Carousel: {len(carousel_urls)} images, expected: {expected_count}")
    
    # Deduplicate carousel images
    seen = set()
    final_urls: List[str] = []
    
    for u in carousel_urls:
        nu = _upgrade_walmart_image(u, 2000)
        key = _get_image_key(nu)
        if key not in seen:
            seen.add(key)
            final_urls.append(nu)
    
    # Step 2: If we have fewer than expected, get more from scripts
    if expected_count and len(final_urls) < expected_count:
        if verbose:
            print(f"    Need {expected_count - len(final_urls)} more images, checking scripts...")
        
        # Try current variant images first
        script_urls = _extract_images_from_scripts_current_variant(soup, product_id)
        
        if verbose:
            print(f"    Found {len(script_urls)} images in scripts")
        
        for u in script_urls:
            nu = _upgrade_walmart_image(u, 2000)
            key = _get_image_key(nu)
            if key not in seen:
                seen.add(key)
                final_urls.append(nu)
                if len(final_urls) >= expected_count:
                    break
    
    # Step 3: If still not enough, try generic extraction (may include other variants)
    if expected_count and len(final_urls) < expected_count:
        if verbose:
            print(f"    Still need more, trying generic extraction...")
        
        all_script_urls = _extract_all_images_from_scripts(soup)
        
        for u in all_script_urls:
            nu = _upgrade_walmart_image(u, 2000)
            key = _get_image_key(nu)
            if key not in seen:
                seen.add(key)
                final_urls.append(nu)
                if len(final_urls) >= expected_count:
                    break
    
    # Apply max_images limit
    if max_images and len(final_urls) > max_images:
        final_urls = final_urls[:max_images]
    
    return final_urls


# ========= Download & convert images =========
def _download_images(urls: List[str], folder: Path, *, convert_to_jpg: bool = True, quality: int = 90) -> List[str]:
    saved: List[str] = []
    folder.mkdir(parents=True, exist_ok=True)
    with requests.Session() as s:
        s.headers.update({
            "User-Agent": UA_STR,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        })
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
                    out_path = folder / f"{i:02d}.jpg"
                    im.save(out_path, format="JPEG", quality=quality, optimize=True)
                    saved.append(str(out_path))
                else:
                    ext = ".jpg"
                    ct = (r.headers.get("Content-Type") or "").lower()
                    lu = u.lower()
                    if "png" in ct or lu.endswith(".png"):
                        ext = ".png"
                    elif "webp" in ct or lu.endswith(".webp"):
                        ext = ".webp"
                    elif "jpeg" in ct or lu.endswith(".jpeg"):
                        ext = ".jpeg"
                    out_path = folder / f"{i:02d}{ext}"
                    out_path.write_bytes(r.content)
                    saved.append(str(out_path))
            except Exception:
                continue
    return saved


# ========= Main scraper =========
def scrape_walmart_via_oxylabs(
    url: str,
    save_dir: Path = SAVE_DIR,
    *,
    convert_images_to_jpg: bool = True,
    delivery_zip: Optional[str] = None,
    store_id: Optional[str] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Scrape Walmart product page.
    
    1) Call walmart_product API (for price/stock/name)
    2) Call universal HTML (for images from carousel - current variant only)
    """
    save_dir.mkdir(parents=True, exist_ok=True)
    product_id = _extract_product_id(url)
    stable_id = product_id or _stable_id_from_url(url)

    if verbose:
        print(f"Fetching {url}...")
        print(f"  Product ID: {product_id}")

    name: Optional[str] = None
    price: Optional[str] = None
    currency: Optional[str] = "USD"
    in_stock: Optional[bool] = None
    stock_text: str = ""
    desc: str = ""

    # 1) walmart_product API (for price/stock/name)
    parsed: Dict[str, Any] = {}
    if product_id:
        try:
            parsed = _fetch_walmart_parsed(product_id, delivery_zip=delivery_zip, 
                                           store_id=store_id, verbose=verbose)
            name = _from_parsed_name(parsed) or name
            pval, cur = _from_parsed_price(parsed)
            price = pval or price
            currency = cur or currency
            inst, stxt = _from_parsed_stock(parsed)
            in_stock = inst if inst is not None else in_stock
            stock_text = stxt or stock_text
            if verbose:
                print(f"  ✓ API: name={name}, price={price}, stock={in_stock}")
        except Exception as e:
            if verbose:
                print(f"  ✗ API failed: {e}")

    # 2) universal HTML
    html = ""
    soup = None
    try:
        html = _fetch_html_universal(url, verbose=verbose)
        soup = BeautifulSoup(html, "lxml")
        if verbose:
            print(f"  ✓ HTML fetched ({len(html)} bytes)")
    except Exception as e:
        soup = None
        if verbose:
            print(f"  ✗ HTML failed: {e}")

    # Price fallback
    if (price is None) and soup is not None:
        p, cur = _extract_price_from_html(soup)
        if p:
            price = p
        if cur:
            currency = cur

    # Stock fallback
    if (in_stock is None) and soup is not None:
        inst, stxt = _detect_stock_from_html(soup)
        in_stock = inst
        if stxt:
            stock_text = stxt

    # Name fallback
    if (not name) and soup is not None:
        h1 = soup.select_one("h1") or soup.select_one('[itemprop="name"]')
        if h1:
            name = _clean(h1.get_text(" ", strip=True))
    if not name:
        name = "Unknown Product"

    # Description
    if soup is not None:
        desc = _parse_description_from_html(soup)

    # Images - prioritize HTML carousel for current variant
    images: List[str] = []
    if soup is not None:
        images = _collect_images_from_html(soup, product_id=product_id, verbose=verbose)
        if verbose:
            print(f"  Images collected: {len(images)}")

    # Folder
    folder = save_dir / f"{_retailer_slug(url)}_{_safe_name(name)}_{stable_id}"
    folder.mkdir(parents=True, exist_ok=True)

    # Save HTML for debugging
    try:
        (folder / "raw_html.html").write_text(html or "", encoding="utf-8")
    except Exception:
        pass

    # Download images
    downloaded = _download_images(images, folder, convert_to_jpg=convert_images_to_jpg) if images else []

    out = {
        "url": urlsplit(url)._replace(query="").geturl(),
        "name": name,
        "price": price or "N/A",
        "currency": currency or "",
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": desc,
        "image_count": len(downloaded),
        "images": downloaded,
        "folder": str(folder),
        "fetched_via": "oxylabs-walmart_product+universal",
    }
    (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


# # ========= CLI =========
# if __name__ == "__main__":
#     TEST_URL = "https://www.walmart.com/ip/VQ-Laura-Ashley-1-7L-Dome-Kettle-Elveden-Navy/14613657687"
#     data = scrape_walmart_via_oxylabs(
#         TEST_URL,
#         save_dir=SAVE_DIR,
#         convert_images_to_jpg=True,
#         delivery_zip=None,
#         store_id=None,
#         verbose=True,
#     )
#     print(json.dumps(data, indent=2, ensure_ascii=False))

