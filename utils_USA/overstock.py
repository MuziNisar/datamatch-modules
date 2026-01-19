






# # overstock.py
# # Python 3.9+ | Oxylabs Realtime (source="universal") + BeautifulSoup + requests
# # Deps: requests, beautifulsoup4, lxml
# #
# # Credentials in oxylabs_secrets.py:
# #   OXY_USER = "your_username"
# #   OXY_PASS = "your_password"

# import json
# import re
# import hashlib
# import time
# import html as ihtml
# from pathlib import Path
# from typing import Optional, Tuple, List, Dict, Any, Iterable
# from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
# from concurrent.futures import ThreadPoolExecutor, as_completed

# import requests
# from bs4 import BeautifulSoup

# # =============================
# # Secrets
# # =============================
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS
# except Exception as e:
#     raise RuntimeError("Missing oxylabs_secrets.py with OXY_USER and OXY_PASS") from e

# # =============================
# # Config
# # =============================
# UA = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
# )
# DEFAULT_GEO = "United States"
# RENDER_MODE = "html"
# OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"

# BASE_DIR = Path(__file__).resolve().parent
# DATA_DIR = BASE_DIR / "data_overstock"
# DATA_DIR.mkdir(parents=True, exist_ok=True)

# REQUEST_TIMEOUT = 90
# MAX_RETRIES = 3
# RETRY_BACKOFF = 2.0  # seconds

# # =============================
# # Helpers
# # =============================
# def _unesc(s: str) -> str:
#     return ihtml.unescape(s or "")

# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", _unesc(s)).strip()

# def _clean_multiline(s: str) -> str:
#     s = _unesc(s).replace("\r\n", "\n").replace("\r", "\n")
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
#     """
#     Prefer numeric product id from '.../<id>/product.html' if present,
#     else SHA1(url)[:12].
#     """
#     try:
#         path = (urlparse(url).path or "").strip("/")
#         m = re.search(r"/?(\d{6,})/product\.html$", "/" + path)
#         if m:
#             return m.group(1)
#     except Exception:
#         pass
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

# def _parse_money(s: str) -> Optional[str]:
#     if not s:
#         return None
#     s = _clean(s)
#     m = re.search(r"\$?\s*(\d[\d,]*)(?:\.(\d{2}))?", s)
#     if not m:
#         return None
#     dollars = m.group(1).replace(",", "")
#     cents = m.group(2) if m.group(2) else "00"
#     return f"${dollars}.{cents}"

# # ---------- JSON helpers ----------
# def _json_iter(obj):
#     """Yield every dict/list node inside a JSON structure."""
#     if isinstance(obj, dict):
#         yield obj
#         for v in obj.values():
#             yield from _json_iter(v)
#     elif isinstance(obj, list):
#         for it in obj:
#             yield from _json_iter(it)

# def _load_json_scripts(soup: BeautifulSoup) -> list:
#     """
#     Collect JSON payloads from:
#       - <script type="application/ld+json">
#       - <script type="application/json"> (some builds)
#     """
#     payloads = []
#     for sc in soup.select('script[type="application/ld+json"]'):
#         txt = sc.get_text() or ""
#         if not txt.strip():
#             continue
#         try:
#             payloads.append(json.loads(txt))
#         except Exception:
#             pass
#     for sc in soup.find_all("script"):
#         t = (sc.get("type") or "").lower()
#         if t == "application/json":
#             txt = sc.get_text() or ""
#             if txt.strip():
#                 try:
#                     payloads.append(json.loads(txt))
#                 except Exception:
#                     pass
#     return payloads

# # =============================
# # Oxylabs Realtime
# # =============================
# def _oxy_payload_for_url(url: str) -> Dict[str, Any]:
#     return {
#         "source": "universal",
#         "url": url,
#         "render": RENDER_MODE,
#         "geo_location": DEFAULT_GEO,
#         "user_agent": UA,
#     }

# def _post_realtime_one(session: requests.Session, url: str) -> dict:
#     payload = _oxy_payload_for_url(url)
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
#             raise RuntimeError("Oxylabs Unauthorized (401). Check OXY_USER/OXY_PASS in oxylabs_secrets.py")
#         if resp.ok:
#             try:
#                 return resp.json()
#             except Exception as e:
#                 raise RuntimeError(f"Oxylabs response not JSON: {e}; text head: {resp.text[:200]}")
#         if attempt >= MAX_RETRIES:
#             raise RuntimeError(f"Oxylabs realtime failed: HTTP {resp.status_code} - {resp.text[:400]}")
#         time.sleep(RETRY_BACKOFF * attempt)

# def _result_content_or_error(res: dict, requested_url: Optional[str] = None) -> str:
#     """
#     Accept both shapes:
#       A) {"status_code": 200, "content": "..."}
#       B) {"results":[{"status_code":200,"content":"...","url":"..."}], ...}
#     Prefer the item whose "url" matches requested_url if multiple are present.
#     """
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
        
#         # Check if content is available (even for 404s, which Overstock uses for out-of-stock)
#         if "content" not in selected:
#             raise RuntimeError("Oxylabs response (results[0]) missing 'content'")
        
#         # Allow 404 if content exists (out-of-stock products return 404 with valid HTML)
#         if status not in (200, 404):
#             error_msg = selected.get('error') or selected.get('message') or ''
#             raise RuntimeError(f"Bad Oxylabs response: {status} {error_msg}")
        
#         return selected["content"]

#     status = res.get("status_code", 0)
#     if status != 200:
#         error_msg = res.get('error') or res.get('message') or ''
#         if status == 404:
#             raise RuntimeError(
#                 f"Product not found (404). The URL may be invalid or the product has been removed: {requested_url or 'N/A'}"
#             )
#         raise RuntimeError(f"Bad Oxylabs response: {status} {error_msg}")
#     if "content" not in res:
#         raise RuntimeError("Oxylabs response missing 'content'")
#     return res["content"]

# # =============================
# # Field extraction (Overstock)
# # =============================
# def _extract_name(soup: BeautifulSoup) -> str:
#     node = soup.select_one('h1[data-testid="product-name"]')
#     if node:
#         t = _clean(node.get_text(" ", strip=True))
#         if t:
#             return t
#     og = soup.select_one('meta[property="og:title"]')
#     if og and og.get("content"):
#         return _clean(og["content"])
#     h1 = soup.select_one("h1")
#     return _clean(h1.get_text(" ", strip=True)) if h1 else "Unknown Product"

# def _extract_price(soup: BeautifulSoup) -> Tuple[str, str]:
#     node = soup.select_one('span.product-price-amount[data-testid="product-price-amount"]')
#     if node:
#         money = _parse_money(node.get_text(" ", strip=True))
#         if money:
#             return money, "onsite"

#     for sc in soup.select('script[type="application/ld+json"]'):
#         try:
#             data = json.loads(sc.get_text(strip=True))
#             arr = data if isinstance(data, list) else [data]
#             for obj in arr:
#                 if isinstance(obj, dict) and obj.get("@type") in ("Product", "Offer", "AggregateOffer"):
#                     offers = obj.get("offers")
#                     if isinstance(offers, dict) and offers.get("price"):
#                         money = _parse_money(str(offers["price"]))
#                         if money:
#                             return money, "jsonld"
#                     if isinstance(offers, list):
#                         for off in offers:
#                             if isinstance(off, dict) and off.get("price"):
#                                 money = _parse_money(str(off["price"]))
#                                 if money:
#                                     return money, "jsonld"
#         except Exception:
#             continue

#     loc = soup.select_one("[itemprop='price'], meta[itemprop='price']")
#     if loc:
#         val = loc.get("content") or loc.get_text(" ", strip=True)
#         money = _parse_money(val)
#         if money:
#             return money, "microdata"

#     return "N/A", "none"

# def _extract_sku(soup: BeautifulSoup) -> Optional[str]:
#     node = soup.select_one('[data-testid="product-sku-value"]')
#     if node:
#         t = _clean(node.get_text())
#         if t:
#             return t
#     m = re.search(r"ITEM#:\s*([A-Za-z0-9\-]+)", soup.get_text(" ", strip=True))
#     return m.group(1) if m else None

# def _extract_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
#     # (1) JSON-LD availability first (reliable when present)
#     for root in _load_json_scripts(soup):
#         objs = root if isinstance(root, list) else [root]
#         for obj in _json_iter(objs):
#             if isinstance(obj, dict) and obj.get("@type") == "Product":
#                 offers = obj.get("offers")
#                 cand = []
#                 if isinstance(offers, dict):
#                     cand = [offers]
#                 elif isinstance(offers, list):
#                     cand = [o for o in offers if isinstance(o, dict)]
#                 for off in cand:
#                     av = (off.get("availability") or "").lower()
#                     if "instock" in av:
#                         return True, "availability: InStock (JSON-LD)"
#                     if "outofstock" in av or "out_of_stock" in av:
#                         return False, "availability: OutOfStock (JSON-LD)"
#                     if "preorder" in av:
#                         return None, "availability: PreOrder (JSON-LD)"

#     # (2) DOM cues
#     atc = soup.select_one('[data-testid="add-to-cart-button"]')
#     if atc:
#         body = _clean(soup.get_text(" ", strip=True)).lower()
#         if re.search(r"\b(out of stock|sold out|unavailable|temporarily unavailable)\b", body, re.I):
#             return False, "Unavailable"
#         if not atc.get("disabled") and atc.get("aria-disabled") not in ("true", "1"):
#             return True, "Add to Cart present"

#     # (3) Negative keywords fallback
#     body = _clean(soup.get_text(" ", strip=True)).lower()
#     if re.search(r"\b(out of stock|sold out|unavailable|temporarily unavailable)\b", body, re.I):
#         return False, "Unavailable"

#     return None, ""

# # =============================
# # Description (richer + clean)
# # =============================
# def _extract_description(soup: BeautifulSoup) -> str:
#     """
#     Priority:
#       1) JSON-LD Product.description + additionalProperty (name/value)
#       2) JSON blobs: bullets/features/highlights/descriptionRichText
#       3) DOM: multiple containers (left content, product-description, accordions)
#          - lists (• bullets), paragraphs
#          - spec tables -> "• Name: Value"
#     Output is **plain text** (no HTML), HTML entities unescaped, deduped.
#     """

#     def norm_line(t: str) -> str:
#         t = _clean(t)
#         t = re.sub(r"^[•\-\u2022]+\s*", "", t).strip()
#         t = re.sub(r"\s*[•\-\u2022]+\s*$", "", t).strip()
#         t = re.sub(r"\s{2,}", " ", t)
#         return t

#     def dedupe_keep_order(lines: List[str]) -> List[str]:
#         seen, out = set(), []
#         for ln in lines:
#             key = re.sub(r"[^\w]+", "", ln).lower()
#             if key in seen:
#                 continue
#             seen.add(key); out.append(ln)
#         return out

#     def html_to_text(fragment: str) -> List[str]:
#         """Convert an HTML snippet to clean paragraphs (no tags)."""
#         if not fragment:
#             return []
#         frag = BeautifulSoup(fragment, "lxml")
#         # convert <br> to newlines for get_text
#         for br in frag.find_all("br"):
#             br.replace_with("\n")
#         text = frag.get_text("\n", strip=True)
#         parts = [norm_line(p) for p in text.split("\n") if norm_line(p)]
#         return parts

#     bullets: List[str] = []
#     paras: List[str] = []

#     # ---- (1) JSON-LD ----
#     for sc in soup.select('script[type="application/ld+json"]'):
#         try:
#             data = json.loads(sc.get_text() or "null")
#         except Exception:
#             continue
#         objs = data if isinstance(data, list) else [data]
#         for obj in objs:
#             if not isinstance(obj, dict):
#                 continue
#             if obj.get("@type") == "Product":
#                 d = obj.get("description")
#                 if isinstance(d, str):
#                     paras.extend(html_to_text(d))
#                 elif isinstance(d, list):
#                     for v in d:
#                         if isinstance(v, str):
#                             bullets.append(norm_line(v))
#                 addp = obj.get("additionalProperty")
#                 if isinstance(addp, list):
#                     for prop in addp:
#                         if not isinstance(prop, dict):
#                             continue
#                         nm = norm_line(str(prop.get("name") or ""))
#                         val = norm_line(str(prop.get("value") or ""))
#                         if nm and val:
#                             bullets.append(f"{nm}: {val}")

#     # ---- (2) JSON blobs ----
#     for root in _load_json_scripts(soup):
#         for node in _json_iter(root):
#             if not isinstance(node, dict):
#                 continue
#             for key in ("bullets", "features", "highlights", "whatsIncluded", "includedItems"):
#                 arr = node.get(key)
#                 if isinstance(arr, list):
#                     for v in arr:
#                         if isinstance(v, str) and v.strip():
#                             # some blobs contain HTML; strip to text
#                             for piece in html_to_text(v):
#                                 bullets.append(piece)
#             for key in ("descriptionRichText", "longDescription", "shortDescription", "description"):
#                 v = node.get(key)
#                 if isinstance(v, str) and v.strip():
#                     paras.extend(html_to_text(v))

#     # ---- (3) DOM sweep ----
#     containers = [
#         '[data-testid="side-by-side-container-left-content"]',
#         '[data-testid="product-description"]',
#         '#product-description',
#         '[data-testid="product-details"]',
#         '[data-testid="accordion"]',
#         '.product-details',
#         '.product-information',
#     ]
#     root_nodes = []
#     for sel in containers:
#         for n in soup.select(sel):
#             if n and n not in root_nodes:
#                 root_nodes.append(n)

#     def harvest_from_root(root):
#         for bad in root.select('[data-testid="product-disclaimers"], .product-disclaimers, .warnings'):
#             bad.decompose()

#         for li in root.select("ul li"):
#             t = norm_line(li.get_text(" ", strip=True))
#             if t:
#                 bullets.append(t)

#         # paragraphs – use get_text and split on <br>
#         for p in root.select("p"):
#             ptxt = p.decode_contents() or p.get_text(" ", strip=True)
#             for piece in html_to_text(ptxt):
#                 if piece and not piece.lower().startswith("warning:"):
#                     paras.append(piece)

#         # Spec tables -> "• Name: Value"
#         for tbl in root.select("table"):
#             for tr in tbl.select("tr"):
#                 ths = [norm_line(th.get_text(" ", strip=True)) for th in tr.select("th")]
#                 tds = [norm_line(td.get_text(" ", strip=True)) for td in tr.select("td")]
#                 key, val = "", ""
#                 if ths and tds:
#                     key, val = ths[0], tds[0]
#                 elif len(tds) >= 2:
#                     key, val = tds[0], tds[1]
#                 if key and val:
#                     bullets.append(f"{key}: {val}")

#         # Accordion sections with headers
#         for sec in root.select("section, div"):
#             header = None
#             for htag in ("h2", "h3", "h4"):
#                 h = sec.find(htag)
#                 if h:
#                     header = norm_line(h.get_text(" ", strip=True))
#                     break
#             if not header:
#                 continue
#             lines_here: List[str] = []
#             for li in sec.select("ul li"):
#                 t = norm_line(li.get_text(" ", strip=True))
#                 if t:
#                     lines_here.append(t)
#             for p in sec.select("p"):
#                 ptxt = p.decode_contents() or p.get_text(" ", strip=True)
#                 for piece in html_to_text(ptxt):
#                     if piece and not piece.lower().startswith("warning:"):
#                         lines_here.append(piece)
#             for tbl in sec.select("table"):
#                 for tr in tbl.select("tr"):
#                     ths = [norm_line(th.get_text(" ", strip=True)) for th in tr.select("th")]
#                     tds = [norm_line(td.get_text(" ", strip=True)) for td in tr.select("td")]
#                     key, val = "", ""
#                     if ths and tds:
#                         key, val = ths[0], tds[0]
#                     elif len(tds) >= 2:
#                         key, val = tds[0], tds[1]
#                     if key and val:
#                         lines_here.append(f"{key}: {val}")
#             for ln in lines_here:
#                 bullets.append(f"{header} — {ln}")

#     for root in root_nodes:
#         harvest_from_root(root)

#     # ---------- Post-process ----------
#     # remove tiny teasers repeated verbatim
#     def drop_teaser_dupes(lines: List[str]) -> List[str]:
#         if not lines:
#             return lines
#         seen = set()
#         out = []
#         for ln in lines:
#             k = re.sub(r"[^\w]+", "", ln).lower()
#             if k in seen:
#                 continue
#             seen.add(k)
#             out.append(ln)
#         return out

#     bullets = drop_teaser_dupes(dedupe_keep_order([b for b in bullets if b]))
#     paras  = drop_teaser_dupes(dedupe_keep_order([p for p in paras if p]))

#     # Prefer bullets if present; else paragraphs
#     if bullets:
#         return _clean_multiline("\n".join(f"• {t}" for t in bullets))
#     if paras:
#         return _clean_multiline(" ".join(paras))

#     meta = soup.select_one('meta[name="description"]')
#     if meta and meta.get("content"):
#         return _clean(meta["content"])

#     return ""

# # =============================
# # Images
# # =============================
# def _ostk_hq(url: str, width: int = 2000) -> str:
#     """
#     Overstock CDN: ...jpg?imwidth=80&impolicy=medium
#     We'll set imwidth to 2000 and keep/strip the rest.
#     """
#     try:
#         u = urlparse(url)
#         q = parse_qs(u.query)
#         q["imwidth"] = [str(width)]
#         query = urlencode({k: v[0] for k, v in q.items() if v and v[0]})
#         return urlunparse((u.scheme, u.netloc, u.path, u.params, query, ""))
#     except Exception:
#         return url

# def _image_dedupe_key(url: str) -> str:
#     u = urlparse(url)
#     return (u.netloc + u.path).lower()

# def _collect_images(soup: BeautifulSoup, max_images: Optional[int]) -> List[str]:
#     urls: List[str] = []

#     # Film-strip thumbnails
#     for img in soup.select('[data-testid="film-strip__media-container"] img[src]'):
#         u = img.get("src")
#         if u:
#             urls.append(u)

#     # OG image
#     og = soup.select_one('meta[property="og:image"]')
#     if og and og.get("content"):
#         urls.append(og["content"])

#     # JSON-LD images
#     for sc in soup.select('script[type="application/ld+json"]'):
#         try:
#             data = json.loads(sc.get_text(strip=True))
#             arr = data if isinstance(data, list) else [data]
#             for obj in arr:
#                 if isinstance(obj, dict) and obj.get("@type") == "Product":
#                     imgs = obj.get("image")
#                     if isinstance(imgs, str):
#                         urls.append(imgs)
#                     elif isinstance(imgs, list):
#                         for u in imgs:
#                             if isinstance(u, str):
#                                 urls.append(u)
#         except Exception:
#             continue

#     # Normalize + dedupe
#     out: List[str] = []
#     seen = set()
#     for u in urls:
#         if not u:
#             continue
#         if u.startswith("//"):
#             u = "https:" + u
#         nu = _ostk_hq(u, width=2000) if "ostkcdn.com" in u else u
#         key = _image_dedupe_key(nu)
#         if key in seen:
#             continue
#         seen.add(key)
#         out.append(nu)
#         if max_images and len(out) >= max_images:
#             break
#     return out

# def _download_image(session: requests.Session, url: str, dest: Path) -> bool:
#     try:
#         r = session.get(url, headers={"User-Agent": UA}, timeout=30)
#         if r.ok and r.content:
#             dest.write_bytes(r.content)
#             return True
#     except Exception:
#         pass
#     return False

# # =============================
# # Single-page scrape
# # =============================
# def scrape_overstock_oxylabs(
#     url: str,
#     max_images: Optional[int] = None,
#     download_images: bool = True,
# ) -> dict:
#     slug = _slug_from_host(url) or "overstock"
#     stable_id = _stable_id_from_url(url)

#     with requests.Session() as s:
#         s.headers.update({"User-Agent": UA})
#         res = _post_realtime_one(s, url)
#         html = _result_content_or_error(res, requested_url=url)
#         soup = BeautifulSoup(html, "lxml")

#         name = _extract_name(soup)
#         price, price_source = _extract_price(soup)
#         sku = _extract_sku(soup)
#         in_stock, stock_text = _extract_stock(soup)
#         description = _extract_description(soup)

#         # Folder
#         folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}"
#         folder.mkdir(parents=True, exist_ok=True)

#         # Images
#         image_urls = _collect_images(soup, max_images=max_images)
#         saved: List[str] = []
#         if download_images:
#             for idx, img in enumerate(image_urls, start=1):
#                 ext = ".jpg"
#                 m = re.search(r"\.(jpg|jpeg|png|webp|gif)(?:$|\?)", img, re.I)
#                 if m:
#                     ext = "." + m.group(1).lower()
#                 fname = f"{idx:02d}{ext}"
#                 dest = folder / fname
#                 if _download_image(s, img, dest):
#                     saved.append(str(dest))

#         out = {
#             "url": url,
#             "name": name,
#             "price": price,
#             "price_source": price_source,
#             "sku": sku,
#             "in_stock": in_stock,
#             "stock_text": stock_text,
#             "description": description,
#             "image_count": len(saved) if download_images else len(image_urls),
#             "image_urls": image_urls,
#             "images_downloaded": saved,
#             "folder": str(folder),
#             "fetched_via": "oxylabs-universal",
#         }
#         (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
#         return out

# # =============================
# # Batch scraping
# # =============================
# def _scrape_one_with_session(session: requests.Session, url: str, max_images: Optional[int], download_images: bool) -> Dict[str, Any]:
#     try:
#         res = _post_realtime_one(session, url)
#         html = _result_content_or_error(res, requested_url=url)
#         soup = BeautifulSoup(html, "lxml")

#         name = _extract_name(soup)
#         price, price_source = _extract_price(soup)
#         sku = _extract_sku(soup)
#         in_stock, stock_text = _extract_stock(soup)
#         description = _extract_description(soup)

#         slug = _slug_from_host(url) or "overstock"
#         stable_id = _stable_id_from_url(url)
#         folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}"
#         folder.mkdir(parents=True, exist_ok=True)

#         image_urls = _collect_images(soup, max_images=max_images)
#         saved: List[str] = []
#         if download_images:
#             for idx, img in enumerate(image_urls, start=1):
#                 ext = ".jpg"
#                 m = re.search(r"\.(jpg|jpeg|png|webp|gif)(?:$|\?)", img, re.I)
#                 if m:
#                     ext = "." + m.group(1).lower()
#                 fname = f"{idx:02d}{ext}"
#                 dest = folder / fname
#                 if _download_image(session, img, dest):
#                     saved.append(str(dest))

#         out = {
#             "url": url,
#             "name": name,
#             "price": price,
#             "price_source": price_source,
#             "sku": sku,
#             "in_stock": in_stock,
#             "stock_text": stock_text,
#             "description": description,
#             "image_count": len(saved) if download_images else len(image_urls),
#             "image_urls": image_urls,
#             "images_downloaded": saved,
#             "folder": str(folder),
#             "fetched_via": "oxylabs-universal",
#         }
#         (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
#         return out

#     except Exception as e:
#         return {"url": url, "error": str(e)}

# def scrape_overstock_batch_oxylabs(
#     urls: Iterable[str],
#     max_images: Optional[int] = None,
#     download_images: bool = True,
#     threads: int = 0,   # 0/1 => sequential; >1 => threaded
# ) -> List[Dict[str, Any]]:
#     urls = [u for u in urls if u]
#     results_all: List[Dict[str, Any]] = []
#     if not urls:
#         return results_all

#     if threads and threads > 1:
#         with requests.Session() as s:
#             s.headers.update({"User-Agent": UA})
#             with ThreadPoolExecutor(max_workers=threads) as ex:
#                 fut_to_url = {
#                     ex.submit(_scrape_one_with_session, s, url, max_images, download_images): url
#                     for url in urls
#                 }
#                 for fut in as_completed(fut_to_url):
#                     results_all.append(fut.result())
#         return results_all

#     # Sequential
#     with requests.Session() as s:
#         s.headers.update({"User-Agent": UA})
#         for url in urls:
#             results_all.append(_scrape_one_with_session(s, url, max_images, download_images))
#     return results_all

# # =============================
# # Back-compat alias (optional)
# # =============================
# def scrape_overstock_with_oxylabs(url: str, max_images: Optional[int] = None, download_images: bool = True) -> dict:
#     return scrape_overstock_oxylabs(url, max_images=max_images, download_images=download_images)

# # =============================
# # CLI
# # =============================
# if __name__ == "__main__":
#     TEST_URLS = [
#         "https://www.overstock.com/products/laura-ashley-5-speed-300-watt-hand-mixer-42124558?variant=62105632702623",
#     ]
#     single = scrape_overstock_oxylabs(TEST_URLS[0], max_images=12, download_images=True)
#     print(json.dumps(single, indent=2, ensure_ascii=False))
#     # batch = scrape_overstock_batch_oxylabs(TEST_URLS, max_images=10, download_images=True, threads=6)
#     # print(json.dumps(batch, indent=2, ensure_ascii=False))








# overstock.py
# Python 3.9+ | Oxylabs Realtime (source="universal") + BeautifulSoup + requests
# Deps: requests, beautifulsoup4, lxml
#
# Credentials in oxylabs_secrets.py:
#   OXY_USER = "your_username"
#   OXY_PASS = "your_password"

import json
import re
import hashlib
import time
import html as ihtml
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any, Iterable
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

# =============================
# Secrets
# =============================
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception as e:
    raise RuntimeError("Missing oxylabs_secrets.py with OXY_USER and OXY_PASS") from e

# =============================
# Config
# =============================
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_GEO = "United States"
RENDER_MODE = "html"
OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data_overstock"
DATA_DIR.mkdir(parents=True, exist_ok=True)

REQUEST_TIMEOUT = 90
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0  # seconds

# =============================
# Helpers
# =============================
def _unesc(s: str) -> str:
    return ihtml.unescape(s or "")

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", _unesc(s)).strip()

def _clean_multiline(s: str) -> str:
    s = _unesc(s).replace("\r\n", "\n").replace("\r", "\n")
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
    """
    Prefer numeric product id from '.../<id>/product.html' if present,
    else SHA1(url)[:12].
    """
    try:
        path = (urlparse(url).path or "").strip("/")
        m = re.search(r"/?(\d{6,})/product\.html$", "/" + path)
        if m:
            return m.group(1)
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

def _parse_money(s: str) -> Optional[str]:
    if not s:
        return None
    s = _clean(s)
    m = re.search(r"\$?\s*(\d[\d,]*)(?:\.(\d{2}))?", s)
    if not m:
        return None
    dollars = m.group(1).replace(",", "")
    cents = m.group(2) if m.group(2) else "00"
    return f"${dollars}.{cents}"

# ---------- JSON helpers ----------
def _json_iter(obj):
    """Yield every dict/list node inside a JSON structure."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _json_iter(v)
    elif isinstance(obj, list):
        for it in obj:
            yield from _json_iter(it)

def _load_json_scripts(soup: BeautifulSoup) -> list:
    """
    Collect JSON payloads from:
      - <script type="application/ld+json">
      - <script type="application/json"> (some builds)
    """
    payloads = []
    for sc in soup.select('script[type="application/ld+json"]'):
        txt = sc.get_text() or ""
        if not txt.strip():
            continue
        try:
            payloads.append(json.loads(txt))
        except Exception:
            pass
    for sc in soup.find_all("script"):
        t = (sc.get("type") or "").lower()
        if t == "application/json":
            txt = sc.get_text() or ""
            if txt.strip():
                try:
                    payloads.append(json.loads(txt))
                except Exception:
                    pass
    return payloads

# =============================
# Oxylabs Realtime
# =============================
def _oxy_payload_for_url(url: str) -> Dict[str, Any]:
    return {
        "source": "universal",
        "url": url,
        "render": RENDER_MODE,
        "geo_location": DEFAULT_GEO,
        "user_agent": UA,
    }

def _post_realtime_one(session: requests.Session, url: str) -> dict:
    payload = _oxy_payload_for_url(url)
    attempt = 0
    while True:
        attempt += 1
        resp = session.post(
            OXY_ENDPOINT,
            json=payload,
            timeout=REQUEST_TIMEOUT,
            auth=(OXY_USER, OXY_PASS),
        )
        if resp.status_code == 401:
            raise RuntimeError("Oxylabs Unauthorized (401). Check OXY_USER/OXY_PASS in oxylabs_secrets.py")
        if resp.ok:
            try:
                return resp.json()
            except Exception as e:
                raise RuntimeError(f"Oxylabs response not JSON: {e}; text head: {resp.text[:200]}")
        if attempt >= MAX_RETRIES:
            raise RuntimeError(f"Oxylabs realtime failed: HTTP {resp.status_code} - {resp.text[:400]}")
        time.sleep(RETRY_BACKOFF * attempt)

def _result_content_or_error(res: dict, requested_url: Optional[str] = None) -> str:
    """
    Accept both shapes:
      A) {"status_code": 200, "content": "..."}
      B) {"results":[{"status_code":200,"content":"...","url":"..."}], ...}
    Prefer the item whose "url" matches requested_url if multiple are present.
    """
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
        
        # Check if content is available (even for 404s, which Overstock uses for out-of-stock)
        if "content" not in selected:
            raise RuntimeError("Oxylabs response (results[0]) missing 'content'")
        
        # Allow 404 if content exists (out-of-stock products return 404 with valid HTML)
        if status not in (200, 404):
            error_msg = selected.get('error') or selected.get('message') or ''
            raise RuntimeError(f"Bad Oxylabs response: {status} {error_msg}")
        
        return selected["content"]

    status = res.get("status_code", 0)
    
    # Check if content is available (even for 404s, which Overstock uses for out-of-stock)
    if "content" not in res:
        raise RuntimeError("Oxylabs response missing 'content'")
    
    # Allow 404 if content exists (out-of-stock products return 404 with valid HTML)
    if status not in (200, 404):
        error_msg = res.get('error') or res.get('message') or ''
        raise RuntimeError(f"Bad Oxylabs response: {status} {error_msg}")
    
    return res["content"]

# =============================
# Field extraction (Overstock)
# =============================
def _extract_name(soup: BeautifulSoup) -> str:
    node = soup.select_one('h1[data-testid="product-name"]')
    if node:
        t = _clean(node.get_text(" ", strip=True))
        if t:
            return t
    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        return _clean(og["content"])
    h1 = soup.select_one("h1")
    return _clean(h1.get_text(" ", strip=True)) if h1 else "Unknown Product"

def _extract_price(soup: BeautifulSoup) -> Tuple[str, str]:
    node = soup.select_one('span.product-price-amount[data-testid="product-price-amount"]')
    if node:
        money = _parse_money(node.get_text(" ", strip=True))
        if money:
            return money, "onsite"

    for sc in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(sc.get_text(strip=True))
            arr = data if isinstance(data, list) else [data]
            for obj in arr:
                if isinstance(obj, dict) and obj.get("@type") in ("Product", "Offer", "AggregateOffer"):
                    offers = obj.get("offers")
                    if isinstance(offers, dict) and offers.get("price"):
                        money = _parse_money(str(offers["price"]))
                        if money:
                            return money, "jsonld"
                    if isinstance(offers, list):
                        for off in offers:
                            if isinstance(off, dict) and off.get("price"):
                                money = _parse_money(str(off["price"]))
                                if money:
                                    return money, "jsonld"
        except Exception:
            continue

    loc = soup.select_one("[itemprop='price'], meta[itemprop='price']")
    if loc:
        val = loc.get("content") or loc.get_text(" ", strip=True)
        money = _parse_money(val)
        if money:
            return money, "microdata"

    return "N/A", "none"

def _extract_sku(soup: BeautifulSoup) -> Optional[str]:
    node = soup.select_one('[data-testid="product-sku-value"]')
    if node:
        t = _clean(node.get_text())
        if t:
            return t
    m = re.search(r"ITEM#:\s*([A-Za-z0-9\-]+)", soup.get_text(" ", strip=True))
    return m.group(1) if m else None

def _extract_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
    # (1) JSON-LD availability first (reliable when present)
    for root in _load_json_scripts(soup):
        objs = root if isinstance(root, list) else [root]
        for obj in _json_iter(objs):
            if isinstance(obj, dict) and obj.get("@type") == "Product":
                offers = obj.get("offers")
                cand = []
                if isinstance(offers, dict):
                    cand = [offers]
                elif isinstance(offers, list):
                    cand = [o for o in offers if isinstance(o, dict)]
                for off in cand:
                    av = (off.get("availability") or "").lower()
                    if "instock" in av:
                        return True, "availability: InStock (JSON-LD)"
                    if "outofstock" in av or "out_of_stock" in av:
                        return False, "availability: OutOfStock (JSON-LD)"
                    if "preorder" in av:
                        return None, "availability: PreOrder (JSON-LD)"

    # (2) Specific out-of-stock banner
    oos_banner = soup.select_one('[data-testid="product-out-of-stock-infobanner-tablet-desktop"]')
    if oos_banner:
        return False, "Out of stock (info banner)"

    # (2) DOM cues
    atc = soup.select_one('[data-testid="add-to-cart-button"]')
    if atc:
        body = _clean(soup.get_text(" ", strip=True)).lower()
        if re.search(r"\b(out of stock|sold out|unavailable|temporarily unavailable)\b", body, re.I):
            return False, "Unavailable"
        if not atc.get("disabled") and atc.get("aria-disabled") not in ("true", "1"):
            return True, "Add to Cart present"

    # (3) Negative keywords fallback
    body = _clean(soup.get_text(" ", strip=True)).lower()
    if re.search(r"\b(out of stock|sold out|unavailable|temporarily unavailable)\b", body, re.I):
        return False, "Unavailable"

    return None, ""

# =============================
# Description (richer + clean)
# =============================
def _extract_description(soup: BeautifulSoup) -> str:
    """
    Priority:
      1) JSON-LD Product.description + additionalProperty (name/value)
      2) JSON blobs: bullets/features/highlights/descriptionRichText
      3) DOM: multiple containers (left content, product-description, accordions)
         - lists (• bullets), paragraphs
         - spec tables -> "• Name: Value"
    Output is **plain text** (no HTML), HTML entities unescaped, deduped.
    """

    def norm_line(t: str) -> str:
        t = _clean(t)
        t = re.sub(r"^[•\-\u2022]+\s*", "", t).strip()
        t = re.sub(r"\s*[•\-\u2022]+\s*$", "", t).strip()
        t = re.sub(r"\s{2,}", " ", t)
        return t

    def dedupe_keep_order(lines: List[str]) -> List[str]:
        seen, out = set(), []
        for ln in lines:
            key = re.sub(r"[^\w]+", "", ln).lower()
            if key in seen:
                continue
            seen.add(key); out.append(ln)
        return out

    def html_to_text(fragment: str) -> List[str]:
        """Convert an HTML snippet to clean paragraphs (no tags)."""
        if not fragment:
            return []
        frag = BeautifulSoup(fragment, "lxml")
        # convert <br> to newlines for get_text
        for br in frag.find_all("br"):
            br.replace_with("\n")
        text = frag.get_text("\n", strip=True)
        parts = [norm_line(p) for p in text.split("\n") if norm_line(p)]
        return parts

    bullets: List[str] = []
    paras: List[str] = []

    # ---- (1) JSON-LD ----
    for sc in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(sc.get_text() or "null")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if not isinstance(obj, dict):
                continue
            if obj.get("@type") == "Product":
                d = obj.get("description")
                if isinstance(d, str):
                    paras.extend(html_to_text(d))
                elif isinstance(d, list):
                    for v in d:
                        if isinstance(v, str):
                            bullets.append(norm_line(v))
                addp = obj.get("additionalProperty")
                if isinstance(addp, list):
                    for prop in addp:
                        if not isinstance(prop, dict):
                            continue
                        nm = norm_line(str(prop.get("name") or ""))
                        val = norm_line(str(prop.get("value") or ""))
                        if nm and val:
                            bullets.append(f"{nm}: {val}")

    # ---- (2) JSON blobs ----
    for root in _load_json_scripts(soup):
        for node in _json_iter(root):
            if not isinstance(node, dict):
                continue
            for key in ("bullets", "features", "highlights", "whatsIncluded", "includedItems"):
                arr = node.get(key)
                if isinstance(arr, list):
                    for v in arr:
                        if isinstance(v, str) and v.strip():
                            # some blobs contain HTML; strip to text
                            for piece in html_to_text(v):
                                bullets.append(piece)
            for key in ("descriptionRichText", "longDescription", "shortDescription", "description"):
                v = node.get(key)
                if isinstance(v, str) and v.strip():
                    paras.extend(html_to_text(v))

    # ---- (3) DOM sweep ----
    containers = [
        '[data-testid="side-by-side-container-left-content"]',
        '[data-testid="product-description"]',
        '#product-description',
        '[data-testid="product-details"]',
        '[data-testid="accordion"]',
        '.product-details',
        '.product-information',
    ]
    root_nodes = []
    for sel in containers:
        for n in soup.select(sel):
            if n and n not in root_nodes:
                root_nodes.append(n)

    def harvest_from_root(root):
        for bad in root.select('[data-testid="product-disclaimers"], .product-disclaimers, .warnings'):
            bad.decompose()

        for li in root.select("ul li"):
            t = norm_line(li.get_text(" ", strip=True))
            if t:
                bullets.append(t)

        # paragraphs – use get_text and split on <br>
        for p in root.select("p"):
            ptxt = p.decode_contents() or p.get_text(" ", strip=True)
            for piece in html_to_text(ptxt):
                if piece and not piece.lower().startswith("warning:"):
                    paras.append(piece)

        # Spec tables -> "• Name: Value"
        for tbl in root.select("table"):
            for tr in tbl.select("tr"):
                ths = [norm_line(th.get_text(" ", strip=True)) for th in tr.select("th")]
                tds = [norm_line(td.get_text(" ", strip=True)) for td in tr.select("td")]
                key, val = "", ""
                if ths and tds:
                    key, val = ths[0], tds[0]
                elif len(tds) >= 2:
                    key, val = tds[0], tds[1]
                if key and val:
                    bullets.append(f"{key}: {val}")

        # Accordion sections with headers
        for sec in root.select("section, div"):
            header = None
            for htag in ("h2", "h3", "h4"):
                h = sec.find(htag)
                if h:
                    header = norm_line(h.get_text(" ", strip=True))
                    break
            if not header:
                continue
            lines_here: List[str] = []
            for li in sec.select("ul li"):
                t = norm_line(li.get_text(" ", strip=True))
                if t:
                    lines_here.append(t)
            for p in sec.select("p"):
                ptxt = p.decode_contents() or p.get_text(" ", strip=True)
                for piece in html_to_text(ptxt):
                    if piece and not piece.lower().startswith("warning:"):
                        lines_here.append(piece)
            for tbl in sec.select("table"):
                for tr in tbl.select("tr"):
                    ths = [norm_line(th.get_text(" ", strip=True)) for th in tr.select("th")]
                    tds = [norm_line(td.get_text(" ", strip=True)) for td in tr.select("td")]
                    key, val = "", ""
                    if ths and tds:
                        key, val = ths[0], tds[0]
                    elif len(tds) >= 2:
                        key, val = tds[0], tds[1]
                    if key and val:
                        lines_here.append(f"{key}: {val}")
            for ln in lines_here:
                bullets.append(f"{header} — {ln}")

    for root in root_nodes:
        harvest_from_root(root)

    # ---------- Post-process ----------
    # remove tiny teasers repeated verbatim
    def drop_teaser_dupes(lines: List[str]) -> List[str]:
        if not lines:
            return lines
        seen = set()
        out = []
        for ln in lines:
            k = re.sub(r"[^\w]+", "", ln).lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(ln)
        return out

    bullets = drop_teaser_dupes(dedupe_keep_order([b for b in bullets if b]))
    paras  = drop_teaser_dupes(dedupe_keep_order([p for p in paras if p]))

    # Prefer bullets if present; else paragraphs
    if bullets:
        return _clean_multiline("\n".join(f"• {t}" for t in bullets))
    if paras:
        return _clean_multiline(" ".join(paras))

    meta = soup.select_one('meta[name="description"]')
    if meta and meta.get("content"):
        return _clean(meta["content"])

    return ""

# =============================
# Images
# =============================
def _ostk_hq(url: str, width: int = 2000) -> str:
    """
    Overstock CDN: ...jpg?imwidth=80&impolicy=medium
    We'll set imwidth to 2000 and keep/strip the rest.
    """
    try:
        u = urlparse(url)
        q = parse_qs(u.query)
        q["imwidth"] = [str(width)]
        query = urlencode({k: v[0] for k, v in q.items() if v and v[0]})
        return urlunparse((u.scheme, u.netloc, u.path, u.params, query, ""))
    except Exception:
        return url

def _image_dedupe_key(url: str) -> str:
    u = urlparse(url)
    return (u.netloc + u.path).lower()

def _collect_images(soup: BeautifulSoup, max_images: Optional[int]) -> List[str]:
    urls: List[str] = []

    # Film-strip thumbnails
    for img in soup.select('[data-testid="film-strip__media-container"] img[src]'):
        u = img.get("src")
        if u:
            urls.append(u)

    # OG image
    og = soup.select_one('meta[property="og:image"]')
    if og and og.get("content"):
        urls.append(og["content"])

    # JSON-LD images
    for sc in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(sc.get_text(strip=True))
            arr = data if isinstance(data, list) else [data]
            for obj in arr:
                if isinstance(obj, dict) and obj.get("@type") == "Product":
                    imgs = obj.get("image")
                    if isinstance(imgs, str):
                        urls.append(imgs)
                    elif isinstance(imgs, list):
                        for u in imgs:
                            if isinstance(u, str):
                                urls.append(u)
        except Exception:
            continue

    # Normalize + dedupe
    out: List[str] = []
    seen = set()
    for u in urls:
        if not u:
            continue
        if u.startswith("//"):
            u = "https:" + u
        nu = _ostk_hq(u, width=2000) if "ostkcdn.com" in u else u
        key = _image_dedupe_key(nu)
        if key in seen:
            continue
        seen.add(key)
        out.append(nu)
        if max_images and len(out) >= max_images:
            break
    return out

def _download_image(session: requests.Session, url: str, dest: Path) -> bool:
    try:
        r = session.get(url, headers={"User-Agent": UA}, timeout=30)
        if r.ok and r.content:
            dest.write_bytes(r.content)
            return True
    except Exception:
        pass
    return False

# =============================
# Single-page scrape
# =============================
def scrape_overstock_oxylabs(
    url: str,
    max_images: Optional[int] = None,
    download_images: bool = True,
) -> dict:
    slug = _slug_from_host(url) or "overstock"
    stable_id = _stable_id_from_url(url)

    with requests.Session() as s:
        s.headers.update({"User-Agent": UA})
        res = _post_realtime_one(s, url)
        html = _result_content_or_error(res, requested_url=url)
        soup = BeautifulSoup(html, "lxml")

        name = _extract_name(soup)
        price, price_source = _extract_price(soup)
        sku = _extract_sku(soup)
        in_stock, stock_text = _extract_stock(soup)
        description = _extract_description(soup)

        # Folder
        folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}"
        folder.mkdir(parents=True, exist_ok=True)

        # Images
        image_urls = _collect_images(soup, max_images=max_images)
        saved: List[str] = []
        if download_images:
            for idx, img in enumerate(image_urls, start=1):
                ext = ".jpg"
                m = re.search(r"\.(jpg|jpeg|png|webp|gif)(?:$|\?)", img, re.I)
                if m:
                    ext = "." + m.group(1).lower()
                fname = f"{idx:02d}{ext}"
                dest = folder / fname
                if _download_image(s, img, dest):
                    saved.append(str(dest))

        out = {
            "url": url,
            "name": name,
            "price": price,
            "price_source": price_source,
            "sku": sku,
            "in_stock": in_stock,
            "stock_text": stock_text,
            "description": description,
            "image_count": len(saved) if download_images else len(image_urls),
            "image_urls": image_urls,
            "images_downloaded": saved,
            "folder": str(folder),
            "fetched_via": "oxylabs-universal",
        }
        (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        return out

# =============================
# Batch scraping
# =============================
def _scrape_one_with_session(session: requests.Session, url: str, max_images: Optional[int], download_images: bool) -> Dict[str, Any]:
    try:
        res = _post_realtime_one(session, url)
        html = _result_content_or_error(res, requested_url=url)
        soup = BeautifulSoup(html, "lxml")

        name = _extract_name(soup)
        price, price_source = _extract_price(soup)
        sku = _extract_sku(soup)
        in_stock, stock_text = _extract_stock(soup)
        description = _extract_description(soup)

        slug = _slug_from_host(url) or "overstock"
        stable_id = _stable_id_from_url(url)
        folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}"
        folder.mkdir(parents=True, exist_ok=True)

        image_urls = _collect_images(soup, max_images=max_images)
        saved: List[str] = []
        if download_images:
            for idx, img in enumerate(image_urls, start=1):
                ext = ".jpg"
                m = re.search(r"\.(jpg|jpeg|png|webp|gif)(?:$|\?)", img, re.I)
                if m:
                    ext = "." + m.group(1).lower()
                fname = f"{idx:02d}{ext}"
                dest = folder / fname
                if _download_image(session, img, dest):
                    saved.append(str(dest))

        out = {
            "url": url,
            "name": name,
            "price": price,
            "price_source": price_source,
            "sku": sku,
            "in_stock": in_stock,
            "stock_text": stock_text,
            "description": description,
            "image_count": len(saved) if download_images else len(image_urls),
            "image_urls": image_urls,
            "images_downloaded": saved,
            "folder": str(folder),
            "fetched_via": "oxylabs-universal",
        }
        (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        return out

    except Exception as e:
        return {"url": url, "error": str(e)}

def scrape_overstock_batch_oxylabs(
    urls: Iterable[str],
    max_images: Optional[int] = None,
    download_images: bool = True,
    threads: int = 0,   # 0/1 => sequential; >1 => threaded
) -> List[Dict[str, Any]]:
    urls = [u for u in urls if u]
    results_all: List[Dict[str, Any]] = []
    if not urls:
        return results_all

    if threads and threads > 1:
        with requests.Session() as s:
            s.headers.update({"User-Agent": UA})
            with ThreadPoolExecutor(max_workers=threads) as ex:
                fut_to_url = {
                    ex.submit(_scrape_one_with_session, s, url, max_images, download_images): url
                    for url in urls
                }
                for fut in as_completed(fut_to_url):
                    results_all.append(fut.result())
        return results_all

    # Sequential
    with requests.Session() as s:
        s.headers.update({"User-Agent": UA})
        for url in urls:
            results_all.append(_scrape_one_with_session(s, url, max_images, download_images))
    return results_all

# =============================
# Back-compat alias (optional)
# =============================
def scrape_overstock_with_oxylabs(url: str, max_images: Optional[int] = None, download_images: bool = True) -> dict:
    return scrape_overstock_oxylabs(url, max_images=max_images, download_images=download_images)

# =============================
# CLI
# =============================
if __name__ == "__main__":
    TEST_URLS = [
        "https://www.overstock.com/products/laura-ashley-5-speed-300-watt-hand-mixer-42124558?variant=62105632702623",
    ]
    single = scrape_overstock_oxylabs(TEST_URLS[0], max_images=12, download_images=True)
    print(json.dumps(single, indent=2, ensure_ascii=False))
    # batch = scrape_overstock_batch_oxylabs(TEST_URLS, max_images=10, download_images=True, threads=6)
    # print(json.dumps(batch, indent=2, ensure_ascii=False))

