






# # -*- coding: utf-8 -*-
# # harveynorman_wsapi.py — single-file Oxylabs WSAPI scraper (render + browser_instructions)
# # Python 3.9+  |  pip install requests beautifulsoup4 lxml

# from __future__ import annotations
# import json, os, re, time, base64, hashlib, html
# from pathlib import Path
# from typing import List, Optional, Dict, Tuple
# from urllib.parse import urlparse, urljoin, urldefrag, urlunparse, urlencode, unquote, parse_qs

# import requests
# from bs4 import BeautifulSoup
# from datetime import datetime, timezone

# # -----------------------------
# # Config
# # -----------------------------
# UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
# ACCEPT_LANG = "en-AU,en;q=0.9"
# GEO = "Australia"
# WSAPI_URL = "https://realtime.oxylabs.io/v1/queries"

# BASE_DIR = Path(__file__).resolve().parent
# DATA_DIR = BASE_DIR / "data_au"   # keep your original output path
# DATA_DIR.mkdir(parents=True, exist_ok=True)

# SITE_TAG = "harveynorman"

# # Put your creds in a sibling file oxylabs_secrets.py
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS
# except Exception:
#     OXY_USER = OXY_PASS = None  # we'll error clearly later

# # -----------------------------
# # Generic helpers
# # -----------------------------
# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "").strip())

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
#         path = (urlparse(url).path or "").rstrip("/")
#         slug = os.path.splitext(os.path.basename(path))[0]
#         if slug:
#             return slug
#     except Exception:
#         pass
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

# def _ensure_dir(p: Path): 
#     p.mkdir(parents=True, exist_ok=True)

# def _utc_stamp() -> str:
#     return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

# def _parse_money(s: str) -> Optional[str]:
#     s = _clean(s)
#     m = re.search(r"\$?\s?(\d[\d,]*)(?:\.(\d{2}))?", s)
#     if not m:
#         return None
#     dollars = m.group(1).replace(",", "")
#     cents = m.group(2) if m.group(2) is not None else "00"
#     return f"${dollars}.{cents}"

# def _dedupe_preserve(seq: List[str]) -> List[str]:
#     seen, out = set(), []
#     for x in seq:
#         if x and x not in seen:
#             seen.add(x); out.append(x)
#     return out

# # -----------------------------
# # Oxylabs WSAPI core
# # -----------------------------
# class WSAPIError(RuntimeError): ...
# def _wsapi_request(payload: dict, timeout: int = 120) -> dict:
#     if not (OXY_USER and OXY_PASS):
#         raise RuntimeError("Missing Oxylabs credentials. Create oxylabs_secrets.py with OXY_USER/OXY_PASS.")
#     r = requests.post(WSAPI_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
#     if 400 <= r.status_code < 500:
#         try: err = r.json()
#         except Exception: err = {"message": r.text}
#         raise WSAPIError(f"{r.status_code} from WSAPI: {err}")
#     r.raise_for_status()
#     return r.json()

# def _extract_html_from_result(res0: dict) -> str:
#     candidates = [
#         res0.get("rendered_html"),
#         res0.get("content"),
#         res0.get("page_content"),
#         (res0.get("response") or {}).get("body"),
#         (res0.get("response") or {}).get("content"),
#         (res0.get("result") or {}).get("content"),
#     ]
#     for c in candidates:
#         if not c: 
#             continue
#         if isinstance(c, bytes):
#             try:
#                 return c.decode("utf-8", "replace")
#             except Exception:
#                 continue
#         if not isinstance(c, str):
#             continue
#         s = c
#         # data:text/html;base64,...
#         if s.startswith("data:text/html"):
#             try:
#                 meta, data = s.split(",", 1)
#             except ValueError:
#                 data, meta = s, ""
#             if ";base64" in meta:
#                 try:
#                     return base64.b64decode(data).decode("utf-8", "replace")
#                 except Exception:
#                     pass
#             return unquote(data)
#         # base64-like blob heuristic
#         b64_like = re.fullmatch(r"[A-Za-z0-9+/=\s]{200,}", s or "")
#         if b64_like and (len(s.strip()) % 4 == 0):
#             try:
#                 decoded = base64.b64decode(s)
#                 if b"<" in decoded:
#                     return decoded.decode("utf-8", "replace")
#             except Exception:
#                 pass
#         return s
#     return ""

# def _wsapi_get_html(url: str, *, render: Optional[str] = "html",
#                     session_id: Optional[str] = None,
#                     browser_instructions: Optional[list] = None,
#                     geo: str = GEO) -> str:
#     payload = {
#         "source": "universal",
#         "url": url,
#         "user_agent_type": "desktop_chrome",
#         "geo_location": geo,
#         "render": render,   # "html" to execute JS
#         "parse": False,     # parse locally
#     }
#     if session_id:
#         payload["session_id"] = session_id
#     if browser_instructions:
#         payload["browser_instructions"] = browser_instructions
#     data = _wsapi_request(payload)
#     results = data.get("results") or []
#     if not results:
#         raise RuntimeError("WSAPI returned no results")
#     return _extract_html_from_result(results[0])

# # -----------------------------
# # Site-specific parsing (Harvey Norman AU)
# # -----------------------------
# def _extract_name(soup: BeautifulSoup) -> str:
#     el = soup.select_one("h1.title")
#     if el:
#         t = _clean(el.get_text(" ", strip=True))
#         if t: return t
#     og = soup.select_one("meta[property='og:title'], meta[name='og:title']")
#     if og and og.get("content"):
#         t = _clean(og["content"])
#         if t: return t
#     if soup.title:
#         t = _clean(soup.title.get_text())
#         if t: return t
#     return "Unknown Product"

# def _extract_price_dom(soup: BeautifulSoup) -> Tuple[Optional[str], str]:
#     # Modern React chunk
#     wrap = soup.select_one("div[class*='PriceCard_sf-price-card']")
#     if wrap:
#         m = _parse_money(wrap.get_text(" ", strip=True))
#         if m: return m, "PriceCard"
#     # Meta price
#     meta_price = soup.select_one("meta[itemprop='price']")
#     if meta_price and meta_price.get("content"):
#         m = _parse_money(meta_price["content"])
#         if m: return m, "meta[itemprop=price]"
#     # Heuristic
#     bodytxt = _clean(soup.get_text(" ", strip=True))
#     m = _parse_money(bodytxt)
#     if m: return m, "heuristic"
#     return None, "none"

# def _extract_price_from_json(soup: BeautifulSoup) -> Tuple[Optional[str], str]:
#     for script in soup.find_all("script", type=lambda v: not v or "json" not in v.lower()):
#         txt = (script.string or script.get_text() or "").strip()
#         if not txt or "price" not in txt.lower():
#             continue
#         m = re.search(r'"price"\s*:\s*"?(\d+(?:\.\d{2})?)"?', txt)
#         if not m:
#             m = re.search(r'"salePrice"\s*:\s*"?(\d+(?:\.\d{2})?)"?', txt)
#         if m:
#             return f"${m.group(1)}", "script JSON"
#     # JSON-LD explicit
#     for tag in soup.find_all("script", type="application/ld+json"):
#         try:
#             obj = json.loads(tag.get_text() or "")
#             objs = obj if isinstance(obj, list) else [obj]
#             for it in objs:
#                 if isinstance(it, dict):
#                     offers = it.get("offers")
#                     if isinstance(offers, dict):
#                         offers = [offers]
#                     if isinstance(offers, list):
#                         for off in offers:
#                             price = off.get("price")
#                             if price:
#                                 m = _parse_money(str(price))
#                                 if m: return m, "jsonld"
#         except Exception:
#             continue
#     return None, "none"

# def _strip_tags_keep_newlines(html_fragment: str) -> str:
#     s = html_fragment
#     # list items → bullets
#     s = re.sub(r"\s*<li[^>]*>\s*", "\n• ", s, flags=re.I)
#     s = re.sub(r"\s*</li>\s*", "", s, flags=re.I)
#     # headings to plain lines
#     s = re.sub(r"\s*<h[1-6][^>]*>\s*", "\n", s, flags=re.I)
#     s = re.sub(r"\s*</h[1-6]>\s*", "\n", s, flags=re.I)
#     # paragraphs / breaks
#     s = re.sub(r"\s*<p[^>]*>\s*", "\n", s, flags=re.I)
#     s = re.sub(r"\s*</p>\s*", "\n", s, flags=re.I)
#     s = re.sub(r"\s*<br\s*/?>\s*", "\n", s, flags=re.I)
#     # strip remaining tags
#     s = re.sub(r"<[^>]+>", " ", s)
#     # unescape and clean
#     s = html.unescape(s)
#     s = re.sub(r"[ \t]+\n", "\n", s)
#     return _clean(re.sub(r"\n{3,}", "\n\n", s)).strip()

# def _best_description_text(soup: BeautifulSoup, html_text: str) -> str:
#     """
#     1) Target known containers: #productTabDescription, ProductPageDescription_*, sf-decode-rich-content.
#     2) Normalize to plaintext keeping bullets.
#     3) Fallback to og:description/meta:description.
#     """
#     # Primary blocks
#     containers = []
#     tab = soup.select_one("#productTabDescription")
#     if tab:
#         containers.append(tab)
#     containers += soup.select("div[class*='ProductPageDescription_']")
#     containers += soup.select("div.sf-decode-rich-content")

#     for node in containers:
#         for bad in node.select("style,script,noscript"):
#             bad.decompose()
#         txt = _strip_tags_keep_newlines(str(node))
#         if txt:
#             return txt

#     og_desc_el   = soup.select_one("meta[property='og:description'], meta[name='og:description']")
#     meta_desc_el = soup.select_one("meta[name='description']")
#     if og_desc_el and og_desc_el.get("content"):
#         return _clean(og_desc_el["content"])
#     if meta_desc_el and meta_desc_el.get("content"):
#         return _clean(meta_desc_el["content"])

#     # last-ditch: grab any rich content container text
#     if html_text:
#         soup2 = BeautifulSoup(html_text, "lxml")
#         alt = soup2.select_one("div.sf-decode-rich-content, [data-content-type='html']")
#         if alt:
#             return _strip_tags_keep_newlines(str(alt))
#     return ""

# # ----- Image helpers (imgix HQ, de-dup, ordering) -----
# def _parse_srcset(srcset: str) -> Optional[str]:
#     best_url, best_w = None, -1
#     for part in (srcset or "").split(","):
#         part = part.strip()
#         m = re.match(r"(\S+)\s+(\d+)w", part)
#         if not m: 
#             continue
#         u, w = m.group(1), int(m.group(2))
#         if w >= best_w:
#             best_w, best_url = w, u
#     return best_url

# def _imgix_to_hq(url: str, w: int = 2000, h: int = 2000) -> str:
#     try:
#         u = urlparse(url)
#         qs = dict(re.findall(r"([^=&?#]+)=([^&=#]+)", u.query or ""))
#         qs["w"] = str(w); qs["h"] = str(h); qs["fit"] = "max"
#         if "auto" not in qs:
#             qs["auto"] = "compress,format"
#         q = urlencode(qs)
#         return urlunparse((u.scheme, u.netloc, u.path, u.params, q, ""))
#     except Exception:
#         return url

# def _is_product_image(u: str) -> bool:
#     # Most HN product imgs go via imgix CDN; keep obvious non-product paths out
#     path = (urlparse(u).path or "").lower()
#     if "imgix.net" not in u.lower():
#         return False
#     bad = ("/brand/", "/placeholder", "/logo", "/badge", "/payment", "/footer", "/wysiwyg")
#     return not any(b in path for b in bad)

# def _img_key_for_dedupe(u: str) -> str:
#     up = urlparse(u)
#     return (up.netloc + up.path).lower()

# def _collect_images_from_html(soup: BeautifulSoup, base: str, max_images: Optional[int]) -> List[str]:
#     cands: List[str] = []
#     # primary: product gallery images (imgix)
#     for img in soup.select("img[src*='imgix.net']"):
#         s = (img.get("data-src") or img.get("src") or "").strip()
#         if s:
#             cands.append(s)
#     for img in soup.select("img[srcset*='imgix.net']"):
#         ss = (img.get("srcset") or "").strip()
#         b = _parse_srcset(ss)
#         if b:
#             cands.append(b)
#     # meta og:image
#     for m in soup.select("meta[property='og:image'], meta[name='og:image']"):
#         c = (m.get("content") or "").strip()
#         if c:
#             cands.append(c)

#     # normalize + filter
#     uniq: List[str] = []
#     seen = set()
#     for u in cands:
#         au = urljoin(base, u)
#         if "imgix.net" in au:
#             au = _imgix_to_hq(au)
#         if not _is_product_image(au):
#             continue
#         key = _img_key_for_dedupe(au)
#         if key in seen:
#             continue
#         seen.add(key); uniq.append(au)

#     # basic ordering by numeric token if present
#     def _order_key(s: str) -> tuple:
#         m = re.search(r"/(\d+)[._-]", urlparse(s).path or "")
#         if m:
#             try: return (int(m.group(1)), s)
#             except Exception: pass
#         return (9999, s)

#     uniq.sort(key=_order_key)
#     if max_images is not None:
#         uniq = uniq[:max_images]
#     return uniq

# # ---- image downloads (direct → proxy fallback) ----
# def _download_image_direct(url: str, dest: Path, referer: str) -> bool:
#     try:
#         headers = {
#             "User-Agent": UA,
#             "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#             "Accept-Language": ACCEPT_LANG,
#             "Referer": referer,
#         }
#         with requests.get(url, headers=headers, timeout=45, stream=True) as r:
#             ct = (r.headers.get("Content-Type") or "").lower()
#             if r.status_code == 200 and (ct.startswith("image/") or r.content):
#                 with open(dest, "wb") as f:
#                     for chunk in r.iter_content(65536):
#                         if chunk:
#                             f.write(chunk)
#                 return True
#     except Exception:
#         pass
#     return False

# def _download_image_via_proxy(url: str, dest: Path, referer: str) -> bool:
#     try:
#         headers = {
#             "User-Agent": UA,
#             "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#             "Accept-Language": ACCEPT_LANG,
#             "Referer": referer,
#         }
#         proxies = {
#             "http":  f"http://{OXY_USER}:{OXY_PASS}@realtime.oxylabs.io:60000",
#             "https": f"http://{OXY_USER}:{OXY_PASS}@realtime.oxylabs.io:60000",
#         }
#         with requests.get(url, headers=headers, timeout=60, stream=True, proxies=proxies, verify=False) as r:
#             ct = (r.headers.get("Content-Type") or "").lower()
#             if r.status_code == 200 and (ct.startswith("image/") or r.content):
#                 with open(dest, "wb") as f:
#                     for chunk in r.iter_content(65536):
#                         if chunk:
#                             f.write(chunk)
#                 return True
#     except Exception:
#         pass
#     return False

# def _download_images_auto(image_urls: List[str], folder: Path, referer: str) -> List[str]:
#     saved_paths: List[str] = []
#     for idx, img_url in enumerate(image_urls, start=1):
#         # extension guess (normalize webp → jpg)
#         ext = ".jpg"
#         m = re.search(r"[.?](jpg|jpeg|png|webp|gif|avif)(?:$|[?&])", img_url, re.I)
#         if m:
#             ext_map = {"webp": "jpg"}
#             ext = "." + ext_map.get(m.group(1).lower(), m.group(1).lower())
#         stem = os.path.splitext(os.path.basename(urlparse(img_url).path))[0]
#         filekey = stem if stem else hashlib.sha1(img_url.encode("utf-8")).hexdigest()[:16]
#         fname = f"{idx:02d}_{_safe_name(filekey)}{ext}"
#         dest = folder / fname
#         if _download_image_direct(img_url, dest, referer) or _download_image_via_proxy(img_url, dest, referer):
#             saved_paths.append(str(dest))
#     return saved_paths

# # -----------------------------
# # Scraper entry
# # -----------------------------
# def scrape_harveynorman(url: str, max_images: Optional[int] = 10) -> dict:
#     """
#     Scrape Harvey Norman AU product page via Oxylabs WSAPI using:
#       - render='html' with browser_instructions to expose description/tabs
#       - DOM + JSON/JSON-LD parsing for price/stock
#       - HQ imgix image gathering + de-dup + ordering
#       - Unique folder per run: <slug>_<safe name>_<stable_id>_<UTCSTAMP>
#     """
#     url, _ = urldefrag(url)
#     base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
#     slug = _slug_from_host(url)
#     stable_id = _stable_id_from_url(url)
#     ts = _utc_stamp()

#     # Browser instructions — ALL waits are integers (WSAPI requires int)
#     browser_instructions = [
#         {"type": "scroll", "x": 0, "y": 700},
#         {"type": "wait", "wait_time_s": 1},
#         {"type": "scroll", "x": 0, "y": 1600},
#         {"type": "wait", "wait_time_s": 1},
#         # Try to reveal description tab/collapsible content
#         {"type": "click", "selector": "a[href*='productTabDescription'], button:has(span:contains('Description'))", "strict": False},
#         {"type": "wait", "wait_time_s": 1},
#         {"type": "click", "selector": "#productTabDescription button:has(span:contains('Read more'))", "strict": False},
#         {"type": "wait", "wait_time_s": 1},
#     ]
#     session_id = f"sess-{int(time.time())}"

#     # 1) Rendered with clicks
#     try:
#         html_text = _wsapi_get_html(
#             url, render="html", session_id=session_id,
#             browser_instructions=browser_instructions, geo=GEO
#         )
#     except Exception:
#         # 2) Rendered (no clicks)
#         html_text = _wsapi_get_html(url, render="html", session_id=session_id, geo=GEO)

#     # 3) Non-render fallback
#     if not html_text or "<" not in html_text:
#         html_text = _wsapi_get_html(url, render=None, session_id=session_id, geo=GEO)

#     soup = BeautifulSoup(html_text or "", "lxml")

#     # Name
#     name = _extract_name(soup)

#     # # Price (JSON/script first, then DOM)
#     # price, price_src = _extract_price_from_json(soup)
#     # if not price:
#     #     price, price_src = _extract_price_dom(soup)

#     # Price (DOM first to catch special/sale prices, then JSON fallback)
#     price, price_src = _extract_price_dom(soup)
#     if not price:
#         price, price_src = _extract_price_from_json(soup)

#     # Stock / availability (JSON-LD → DOM heuristics)
#     in_stock, stock_text = None, ""
#     # quick JSON-LD pass
#     jsonld_list: List[str] = []
#     for tag in soup.find_all("script", type="application/ld+json"):
#         try: jsonld_list.append(tag.get_text() or "")
#         except Exception: pass
#     try:
#         for blob in jsonld_list:
#             obj = json.loads(blob)
#             objs = obj if isinstance(obj, list) else [obj]
#             for it in objs:
#                 if isinstance(it, dict):
#                     offers = it.get("offers")
#                     if isinstance(offers, dict):
#                         offers = [offers]
#                     if isinstance(offers, list):
#                         for off in offers:
#                             avail = str(off.get("availability","")).lower()
#                             if "instock" in avail:
#                                 in_stock, stock_text = True, "InStock (JSON-LD)"
#                             elif "outofstock" in avail or "soldout" in avail:
#                                 in_stock, stock_text = False, "OutOfStock (JSON-LD)"
#     except Exception:
#         pass
#     if in_stock is None:
#         body = _clean(soup.get_text(" ", strip=True)).lower()
#         if "out of stock" in body or "sold out" in body:
#             in_stock, stock_text = False, "Sold Out"
#         elif "add to cart" in body:
#             in_stock, stock_text = True, "Add to cart visible"

#     # Description
#     description = _best_description_text(soup, html_text)

#     # Images
#     image_urls = _collect_images_from_html(soup, base, max_images=max_images)

#     # Final folder (after we know the name)
#     folder = DATA_DIR / f"{SITE_TAG}_{_safe_name(name)}_{stable_id}_{ts}"
#     _ensure_dir(folder)
#     images = _download_images_auto(image_urls, folder, referer=url)

#     out = {
#         "source_url": url,
#         "name": name,
#         "price": price or "N/A",
#         "price_source": price_src,
#         "in_stock": in_stock,
#         "stock_text": stock_text,
#         "description": description,
#         "image_count": len(images),
#         "images": images,
#         "folder": str(folder),
#         "mode": "wsapi (render+browser_instructions)",
#         "timestamp_utc": ts,
#     }
#     return out

# # -----------------------------
# # CLI demo
# # -----------------------------
# if __name__ == "__main__":
#     URL = "https://www.harveynorman.com.au/laura-ashley-1-7l-dome-kettle-elveden-navy.html"
#     result = scrape_harveynorman(URL, max_images=12)
#     print(json.dumps(result, indent=2, ensure_ascii=False))









# -*- coding: utf-8 -*-
# harveynorman_wsapi.py — single-file Oxylabs WSAPI scraper (render + browser_instructions)
# Python 3.9+  |  pip install requests beautifulsoup4 lxml
# Version: 2.0 - Fixed image deduplication, skip clone slides

# from __future__ import annotations
# import json, os, re, time, base64, hashlib, html
# from pathlib import Path
# from typing import List, Optional, Dict, Tuple
# from urllib.parse import urlparse, urljoin, urldefrag, urlunparse, urlencode, unquote, parse_qs
# 
# import requests
# from requests.exceptions import ReadTimeout, ConnectionError
# from bs4 import BeautifulSoup
# from datetime import datetime, timezone
# 
# __version__ = "2.0"
# 
# # -----------------------------
# # Config
# # -----------------------------
# UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
# ACCEPT_LANG = "en-AU,en;q=0.9"
# GEO = "Australia"
# WSAPI_URL = "https://realtime.oxylabs.io/v1/queries"
# 
# BASE_DIR = Path(__file__).resolve().parent
# DATA_DIR = BASE_DIR / "data_au"
# DATA_DIR.mkdir(parents=True, exist_ok=True)
# 
# SITE_TAG = "harveynorman"
# 
# # Credentials from oxylabs_secrets.py or environment
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS
# except Exception:
#     OXY_USER = os.getenv("OXYLABS_USERNAME") or os.getenv("OXY_USER", "")
#     OXY_PASS = os.getenv("OXYLABS_PASSWORD") or os.getenv("OXY_PASS", "")
# 
# if not (OXY_USER and OXY_PASS):
#     raise RuntimeError("Oxylabs credentials missing. Create oxylabs_secrets.py or set environment variables.")
# 
# # -----------------------------
# # Generic helpers
# # -----------------------------
# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "").strip())
# 
# 
# def _safe_name(s: str) -> str:
#     s = _clean(s)
#     return re.sub(r"[^\w.\-]+", "_", s)[:120] or "product"
# 
# 
# def _slug_from_host(url: str) -> str:
#     try:
#         host = (urlparse(url).hostname or "site").replace("www.", "")
#         return host.split(".")[0]
#     except Exception:
#         return "site"
# 
# 
# def _stable_id_from_url(url: str) -> str:
#     try:
#         path = (urlparse(url).path or "").rstrip("/")
#         slug = os.path.splitext(os.path.basename(path))[0]
#         if slug:
#             return slug
#     except Exception:
#         pass
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
# 
# 
# def _ensure_dir(p: Path): 
#     p.mkdir(parents=True, exist_ok=True)
# 
# 
# def _utc_stamp() -> str:
#     return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
# 
# 
# def _parse_money(s: str) -> Optional[str]:
#     s = _clean(s)
#     m = re.search(r"\$?\s?(\d[\d,]*)(?:\.(\d{2}))?", s)
#     if not m:
#         return None
#     dollars = m.group(1).replace(",", "")
#     cents = m.group(2) if m.group(2) is not None else "00"
#     return f"${dollars}.{cents}"
# 
# 
# # -----------------------------
# # Oxylabs WSAPI core
# # -----------------------------
# def _wsapi_request(payload: dict, timeout: int = 120, retries: int = 3, backoff: float = 2.0) -> dict:
#     """Make request to Oxylabs WSAPI with retry logic."""
#     if not (OXY_USER and OXY_PASS):
#         raise RuntimeError("Missing Oxylabs credentials.")
#     
#     last_err = None
#     for attempt in range(1, retries + 1):
#         try:
#             current_timeout = timeout + (attempt - 1) * 30
#             r = requests.post(WSAPI_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=current_timeout)
#             
#             if 400 <= r.status_code < 500:
#                 try:
#                     err = r.json()
#                 except Exception:
#                     err = {"message": r.text}
#                 raise requests.HTTPError(f"{r.status_code} from WSAPI: {err}", response=r)
#             
#             r.raise_for_status()
#             return r.json()
#             
#         except (ReadTimeout, ConnectionError) as e:
#             last_err = e
#             if attempt < retries:
#                 sleep_time = backoff ** attempt
#                 print(f"  [HN] Timeout on attempt {attempt}/{retries}, retrying in {sleep_time:.1f}s...")
#                 time.sleep(sleep_time)
#             else:
#                 raise RuntimeError(f"WSAPI timed out after {retries} attempts: {e}") from e
#         except Exception as e:
#             last_err = e
#             if attempt < retries:
#                 time.sleep(backoff ** attempt)
#             else:
#                 raise
#     
#     raise RuntimeError(f"WSAPI request failed: {last_err}")
# 
# 
# def _extract_html_from_result(res0: dict) -> str:
#     candidates = [
#         res0.get("rendered_html"),
#         res0.get("content"),
#         res0.get("page_content"),
#         (res0.get("response") or {}).get("body"),
#         (res0.get("response") or {}).get("content"),
#         (res0.get("result") or {}).get("content"),
#     ]
#     for c in candidates:
#         if not c: 
#             continue
#         if isinstance(c, bytes):
#             try:
#                 return c.decode("utf-8", "replace")
#             except Exception:
#                 continue
#         if not isinstance(c, str):
#             continue
#         s = c
#         if s.startswith("data:text/html"):
#             try:
#                 meta, data = s.split(",", 1)
#             except ValueError:
#                 data, meta = s, ""
#             if ";base64" in meta:
#                 try:
#                     return base64.b64decode(data).decode("utf-8", "replace")
#                 except Exception:
#                     pass
#             return unquote(data)
#         b64_like = re.fullmatch(r"[A-Za-z0-9+/=\s]{200,}", s or "")
#         if b64_like and (len(s.strip()) % 4 == 0):
#             try:
#                 decoded = base64.b64decode(s)
#                 if b"<" in decoded:
#                     return decoded.decode("utf-8", "replace")
#             except Exception:
#                 pass
#         return s
#     return ""
# 
# 
# def _wsapi_get_html(url: str, *, render: Optional[str] = "html",
#                     session_id: Optional[str] = None,
#                     browser_instructions: Optional[list] = None,
#                     geo: str = GEO) -> str:
#     payload = {
#         "source": "universal",
#         "url": url,
#         "user_agent_type": "desktop_chrome",
#         "geo_location": geo,
#         "render": render,
#         "parse": False,
#     }
#     if session_id:
#         payload["session_id"] = session_id
#     if browser_instructions:
#         payload["browser_instructions"] = browser_instructions
#     data = _wsapi_request(payload)
#     results = data.get("results") or []
#     if not results:
#         raise RuntimeError("WSAPI returned no results")
#     return _extract_html_from_result(results[0])
# 
# 
# # -----------------------------
# # Site-specific parsing (Harvey Norman AU)
# # -----------------------------
# def _extract_name(soup: BeautifulSoup) -> str:
#     el = soup.select_one("h1.title")
#     if el:
#         t = _clean(el.get_text(" ", strip=True))
#         if t:
#             return t
#     og = soup.select_one("meta[property='og:title'], meta[name='og:title']")
#     if og and og.get("content"):
#         t = _clean(og["content"])
#         if t:
#             return t
#     if soup.title:
#         t = _clean(soup.title.get_text())
#         if t:
#             return t
#     return "Unknown Product"
# 
# 
# def _extract_price_dom(soup: BeautifulSoup) -> Tuple[Optional[str], str]:
#     wrap = soup.select_one("div[class*='PriceCard_sf-price-card']")
#     if wrap:
#         m = _parse_money(wrap.get_text(" ", strip=True))
#         if m:
#             return m, "PriceCard"
#     meta_price = soup.select_one("meta[itemprop='price']")
#     if meta_price and meta_price.get("content"):
#         m = _parse_money(meta_price["content"])
#         if m:
#             return m, "meta[itemprop=price]"
#     bodytxt = _clean(soup.get_text(" ", strip=True))
#     m = _parse_money(bodytxt)
#     if m:
#         return m, "heuristic"
#     return None, "none"
# 
# 
# def _extract_price_from_json(soup: BeautifulSoup) -> Tuple[Optional[str], str]:
#     for script in soup.find_all("script", type=lambda v: not v or "json" not in v.lower()):
#         txt = (script.string or script.get_text() or "").strip()
#         if not txt or "price" not in txt.lower():
#             continue
#         m = re.search(r'"price"\s*:\s*"?(\d+(?:\.\d{2})?)"?', txt)
#         if not m:
#             m = re.search(r'"salePrice"\s*:\s*"?(\d+(?:\.\d{2})?)"?', txt)
#         if m:
#             return f"${m.group(1)}", "script JSON"
#     
#     for tag in soup.find_all("script", type="application/ld+json"):
#         try:
#             obj = json.loads(tag.get_text() or "")
#             objs = obj if isinstance(obj, list) else [obj]
#             for it in objs:
#                 if isinstance(it, dict):
#                     offers = it.get("offers")
#                     if isinstance(offers, dict):
#                         offers = [offers]
#                     if isinstance(offers, list):
#                         for off in offers:
#                             price = off.get("price")
#                             if price:
#                                 m = _parse_money(str(price))
#                                 if m:
#                                     return m, "jsonld"
#         except Exception:
#             continue
#     return None, "none"
# 
# 
# def _strip_tags_keep_newlines(html_fragment: str) -> str:
#     s = html_fragment
#     s = re.sub(r"\s*<li[^>]*>\s*", "\n• ", s, flags=re.I)
#     s = re.sub(r"\s*</li>\s*", "", s, flags=re.I)
#     s = re.sub(r"\s*<h[1-6][^>]*>\s*", "\n", s, flags=re.I)
#     s = re.sub(r"\s*</h[1-6]>\s*", "\n", s, flags=re.I)
#     s = re.sub(r"\s*<p[^>]*>\s*", "\n", s, flags=re.I)
#     s = re.sub(r"\s*</p>\s*", "\n", s, flags=re.I)
#     s = re.sub(r"\s*<br\s*/?>\s*", "\n", s, flags=re.I)
#     s = re.sub(r"<[^>]+>", " ", s)
#     s = html.unescape(s)
#     s = re.sub(r"[ \t]+\n", "\n", s)
#     return _clean(re.sub(r"\n{3,}", "\n\n", s)).strip()
# 
# 
# def _best_description_text(soup: BeautifulSoup, html_text: str) -> str:
#     containers = []
#     tab = soup.select_one("#productTabDescription")
#     if tab:
#         containers.append(tab)
#     containers += soup.select("div[class*='ProductPageDescription_']")
#     containers += soup.select("div.sf-decode-rich-content")
# 
#     for node in containers:
#         for bad in node.select("style,script,noscript"):
#             bad.decompose()
#         txt = _strip_tags_keep_newlines(str(node))
#         if txt:
#             return txt
# 
#     og_desc_el = soup.select_one("meta[property='og:description'], meta[name='og:description']")
#     meta_desc_el = soup.select_one("meta[name='description']")
#     if og_desc_el and og_desc_el.get("content"):
#         return _clean(og_desc_el["content"])
#     if meta_desc_el and meta_desc_el.get("content"):
#         return _clean(meta_desc_el["content"])
# 
#     if html_text:
#         soup2 = BeautifulSoup(html_text, "lxml")
#         alt = soup2.select_one("div.sf-decode-rich-content, [data-content-type='html']")
#         if alt:
#             return _strip_tags_keep_newlines(str(alt))
#     return ""
# 
# 
# # ----- Image helpers -----
# def _imgix_to_hq(url: str, w: int = 2000, h: int = 2000) -> str:
#     """Upgrade imgix URL to higher resolution."""
#     try:
#         u = urlparse(url)
#         qs = dict(re.findall(r"([^=&?#]+)=([^&=#]+)", u.query or ""))
#         qs["w"] = str(w)
#         qs["h"] = str(h)
#         qs["fit"] = "max"
#         if "auto" not in qs:
#             qs["auto"] = "compress,format"
#         q = urlencode(qs)
#         return urlunparse((u.scheme, u.netloc, u.path, u.params, q, ""))
#     except Exception:
#         return url
# 
# 
# def _extract_image_id(url: str) -> str:
#     """
#     Extract unique identifier from Harvey Norman imgix URL.
#     URLs look like: https://hnau.imgix.net/media/catalog/product/1/_/1._product_image_laen_dome_kettle.jpg?...
#     The unique part is the path: /media/catalog/product/1/_/1._product_image_laen_dome_kettle.jpg
#     """
#     try:
#         path = urlparse(url).path
#         # Normalize path (remove leading/trailing slashes, lowercase)
#         return path.strip("/").lower()
#     except Exception:
#         return url.lower()
# 
# 
# def _is_product_image(u: str) -> bool:
#     """Check if URL is a valid product image (not logo, badge, etc.)"""
#     path = (urlparse(u).path or "").lower()
#     
#     # Must be from imgix CDN
#     if "imgix.net" not in u.lower():
#         return False
#     
#     # Must be in catalog/product path
#     if "/media/catalog/product/" not in path:
#         return False
#     
#     # Exclude non-product images
#     bad = ("/brand/", "/placeholder", "/logo", "/badge", "/payment", "/footer", "/wysiwyg")
#     return not any(b in path for b in bad)
# 
# 
# def _collect_images_from_html(soup: BeautifulSoup, base: str, max_images: Optional[int]) -> List[str]:
#     """
#     Collect unique product images from Harvey Norman page.
#     - Only from the product carousel (not og:image meta)
#     - Skip clone slides (used for infinite scroll)
#     - Deduplicate by image path
#     """
#     candidates: List[str] = []
#     seen_ids: set = set()
#     
#     # Primary: product gallery images from Glide slider
#     # Skip slides with 'glide__slide--clone' class (these are duplicates for infinite scrolling)
#     for slide in soup.select("li.Slider_glide__slide__INv_h"):
#         # Skip clone slides
#         classes = slide.get("class", [])
#         if "glide__slide--clone" in classes:
#             continue
#         
#         # Get image from this slide
#         img = slide.select_one("img")
#         if not img:
#             continue
#         
#         src = (img.get("src") or "").strip()
#         if not src or "imgix.net" not in src:
#             continue
#         
#         # Check for duplicates using image path
#         img_id = _extract_image_id(src)
#         if img_id in seen_ids:
#             continue
#         seen_ids.add(img_id)
#         
#         # Only include actual product images
#         if _is_product_image(src):
#             candidates.append(src)
#     
#     # Fallback: if no images found from slider, try general imgix images
#     if not candidates:
#         for img in soup.select("img[src*='imgix.net']"):
#             src = (img.get("src") or "").strip()
#             if not src:
#                 continue
#             
#             img_id = _extract_image_id(src)
#             if img_id in seen_ids:
#                 continue
#             seen_ids.add(img_id)
#             
#             if _is_product_image(src):
#                 candidates.append(src)
#     
#     # Upgrade to high-res
#     result = [_imgix_to_hq(u) for u in candidates]
#     
#     # Sort by image number (1._product, 2._product, etc.)
#     def _order_key(s: str) -> tuple:
#         path = urlparse(s).path or ""
#         fname = os.path.basename(path)
#         # Extract leading number like "1." or "2."
#         m = re.match(r"(\d+)\.", fname)
#         if m:
#             return (int(m.group(1)), fname)
#         return (999, fname)
#     
#     result.sort(key=_order_key)
#     
#     if max_images is not None:
#         result = result[:max_images]
#     
#     return result
# 
# 
# # ---- Image downloads ----
# def _download_image_direct(url: str, dest: Path, referer: str) -> bool:
#     try:
#         headers = {
#             "User-Agent": UA,
#             "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#             "Accept-Language": ACCEPT_LANG,
#             "Referer": referer,
#         }
#         with requests.get(url, headers=headers, timeout=45, stream=True) as r:
#             ct = (r.headers.get("Content-Type") or "").lower()
#             if r.status_code == 200 and (ct.startswith("image/") or r.content):
#                 with open(dest, "wb") as f:
#                     for chunk in r.iter_content(65536):
#                         if chunk:
#                             f.write(chunk)
#                 return True
#     except Exception:
#         pass
#     return False
# 
# 
# def _download_image_via_proxy(url: str, dest: Path, referer: str) -> bool:
#     try:
#         headers = {
#             "User-Agent": UA,
#             "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#             "Accept-Language": ACCEPT_LANG,
#             "Referer": referer,
#         }
#         proxies = {
#             "http": f"http://{OXY_USER}:{OXY_PASS}@realtime.oxylabs.io:60000",
#             "https": f"http://{OXY_USER}:{OXY_PASS}@realtime.oxylabs.io:60000",
#         }
#         with requests.get(url, headers=headers, timeout=60, stream=True, proxies=proxies, verify=False) as r:
#             ct = (r.headers.get("Content-Type") or "").lower()
#             if r.status_code == 200 and (ct.startswith("image/") or r.content):
#                 with open(dest, "wb") as f:
#                     for chunk in r.iter_content(65536):
#                         if chunk:
#                             f.write(chunk)
#                 return True
#     except Exception:
#         pass
#     return False
# 
# 
# def _download_images_auto(image_urls: List[str], folder: Path, referer: str) -> List[str]:
#     saved_paths: List[str] = []
#     for idx, img_url in enumerate(image_urls, start=1):
#         ext = ".jpg"
#         m = re.search(r"[.?](jpg|jpeg|png|webp|gif|avif)(?:$|[?&])", img_url, re.I)
#         if m:
#             ext_found = m.group(1).lower()
#             ext = ".jpg" if ext_found in ("jpeg", "webp") else f".{ext_found}"
#         
#         fname = f"{idx:02d}{ext}"
#         dest = folder / fname
#         
#         if _download_image_direct(img_url, dest, referer) or _download_image_via_proxy(img_url, dest, referer):
#             saved_paths.append(str(dest))
#     
#     return saved_paths
# 
# 
# # -----------------------------
# # Scraper entry
# # -----------------------------
# def scrape_harveynorman(url: str, max_images: Optional[int] = 10, verbose: bool = False) -> dict:
#     """
#     Scrape Harvey Norman AU product page via Oxylabs WSAPI.
#     """
#     url, _ = urldefrag(url)
#     base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
#     slug = _slug_from_host(url)
#     stable_id = _stable_id_from_url(url)
#     ts = _utc_stamp()
# 
#     if verbose:
#         print(f"Fetching {url}...")
# 
#     browser_instructions = [
#         {"type": "scroll", "x": 0, "y": 700},
#         {"type": "wait", "wait_time_s": 1},
#         {"type": "scroll", "x": 0, "y": 1600},
#         {"type": "wait", "wait_time_s": 1},
#         # Click description tab
#         {"type": "click", "selector": {"type": "css", "value": "a[href*='productTabDescription']"}},
#         {"type": "wait", "wait_time_s": 1},
#         # Click "Read more" button
#         {"type": "click", "selector": {"type": "css", "value": "#productTabDescription button"}},
#         {"type": "wait", "wait_time_s": 1},
#     ]
#     session_id = f"sess-{int(time.time())}"
# 
#     # 1) Rendered with clicks
#     html_text = ""
#     try:
#         html_text = _wsapi_get_html(
#             url, render="html", session_id=session_id,
#             browser_instructions=browser_instructions, geo=GEO
#         )
#     except Exception as e:
#         if verbose:
#             print(f"  First attempt failed: {e}")
#         try:
#             html_text = _wsapi_get_html(url, render="html", session_id=session_id, geo=GEO)
#         except Exception:
#             pass
# 
#     # 3) Non-render fallback
#     if not html_text or "<" not in html_text:
#         if verbose:
#             print("  Trying non-rendered fallback...")
#         html_text = _wsapi_get_html(url, render=None, session_id=session_id, geo=GEO)
# 
#     soup = BeautifulSoup(html_text or "", "lxml")
# 
#     # Name
#     name = _extract_name(soup)
# 
#     # Price (DOM first to catch special/sale prices, then JSON fallback)
#     price, price_src = _extract_price_dom(soup)
#     if not price:
#         price, price_src = _extract_price_from_json(soup)
# 
#     # Stock / availability
#     in_stock, stock_text = None, ""
#     jsonld_list: List[str] = []
#     for tag in soup.find_all("script", type="application/ld+json"):
#         try:
#             jsonld_list.append(tag.get_text() or "")
#         except Exception:
#             pass
#     try:
#         for blob in jsonld_list:
#             obj = json.loads(blob)
#             objs = obj if isinstance(obj, list) else [obj]
#             for it in objs:
#                 if isinstance(it, dict):
#                     offers = it.get("offers")
#                     if isinstance(offers, dict):
#                         offers = [offers]
#                     if isinstance(offers, list):
#                         for off in offers:
#                             avail = str(off.get("availability", "")).lower()
#                             if "instock" in avail:
#                                 in_stock, stock_text = True, "InStock (JSON-LD)"
#                             elif "outofstock" in avail or "soldout" in avail:
#                                 in_stock, stock_text = False, "OutOfStock (JSON-LD)"
#     except Exception:
#         pass
#     
#     if in_stock is None:
#         body = _clean(soup.get_text(" ", strip=True)).lower()
#         if "out of stock" in body or "sold out" in body:
#             in_stock, stock_text = False, "Sold Out"
#         elif "add to cart" in body:
#             in_stock, stock_text = True, "Add to cart visible"
# 
#     # Description
#     description = _best_description_text(soup, html_text)
# 
#     # Images
#     image_urls = _collect_images_from_html(soup, base, max_images=max_images)
# 
#     if verbose:
#         print(f"  Name: {name}")
#         print(f"  Price: {price}")
#         print(f"  In Stock: {in_stock}")
#         print(f"  Images found: {len(image_urls)}")
# 
#     # Final folder
#     folder = DATA_DIR / f"{SITE_TAG}_{_safe_name(name)}_{stable_id}_{ts}"
#     _ensure_dir(folder)
#     
#     if verbose:
#         print(f"  Downloading {len(image_urls)} images...")
#     
#     images = _download_images_auto(image_urls, folder, referer=url)
# 
#     return {
#         "source_url": url,
#         "name": name,
#         "price": price or "N/A",
#         "price_source": price_src,
#         "in_stock": in_stock,
#         "stock_text": stock_text,
#         "description": description,
#         "image_count": len(images),
#         "image_urls": image_urls,
#         "images": images,
#         "folder": str(folder),
#         "mode": "wsapi (render+browser_instructions)",
#         "timestamp_utc": ts,
#     }
# 
# 
# # -----------------------------
# # CLI
# # -----------------------------
# if __name__ == "__main__":
#     URL = "https://www.harveynorman.com.au/laura-ashley-1-7l-dome-kettle-elveden-navy.html"
#     result = scrape_harveynorman(URL, max_images=12, verbose=True)
#     print("\n" + "=" * 60)
#     print("RESULTS:")
#     print("=" * 60)
#     print(json.dumps(result, indent=2, ensure_ascii=False))

from __future__ import annotations
import json, os, re, time, base64, hashlib, html
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from urllib.parse import urlparse, urljoin, urldefrag, urlunparse, urlencode, unquote, parse_qs

import requests
from requests.exceptions import ReadTimeout, ConnectionError
from bs4 import BeautifulSoup
from datetime import datetime, timezone

__version__ = "2.0"

# -----------------------------
# Config
# -----------------------------
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
ACCEPT_LANG = "en-AU,en;q=0.9"
GEO = "Australia"
WSAPI_URL = "https://realtime.oxylabs.io/v1/queries"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data_au"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SITE_TAG = "harveynorman"

# Credentials from oxylabs_secrets.py or environment
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = os.getenv("OXYLABS_USERNAME") or os.getenv("OXY_USER", "")
    OXY_PASS = os.getenv("OXYLABS_PASSWORD") or os.getenv("OXY_PASS", "")

if not (OXY_USER and OXY_PASS):
    raise RuntimeError("Oxylabs credentials missing. Create oxylabs_secrets.py or set environment variables.")

# -----------------------------
# Generic helpers
# -----------------------------
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


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
        path = (urlparse(url).path or "").rstrip("/")
        slug = os.path.splitext(os.path.basename(path))[0]
        if slug:
            return slug
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _ensure_dir(p: Path): 
    p.mkdir(parents=True, exist_ok=True)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _parse_money(s: str) -> Optional[str]:
    s = _clean(s)
    m = re.search(r"\$?\s?(\d[\d,]*)(?:\.(\d{2}))?", s)
    if not m:
        return None
    dollars = m.group(1).replace(",", "")
    cents = m.group(2) if m.group(2) is not None else "00"
    return f"${dollars}.{cents}"


# -----------------------------
# Oxylabs WSAPI core
# -----------------------------
def _wsapi_request(payload: dict, timeout: int = 120, retries: int = 3, backoff: float = 2.0) -> dict:
    """Make request to Oxylabs WSAPI with retry logic."""
    if not (OXY_USER and OXY_PASS):
        raise RuntimeError("Missing Oxylabs credentials.")
    
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            current_timeout = timeout + (attempt - 1) * 30
            r = requests.post(WSAPI_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=current_timeout)
            
            if 400 <= r.status_code < 500:
                try:
                    err = r.json()
                except Exception:
                    err = {"message": r.text}
                raise requests.HTTPError(f"{r.status_code} from WSAPI: {err}", response=r)
            
            r.raise_for_status()
            return r.json()
            
        except (ReadTimeout, ConnectionError) as e:
            last_err = e
            if attempt < retries:
                sleep_time = backoff ** attempt
                print(f"  [HN] Timeout on attempt {attempt}/{retries}, retrying in {sleep_time:.1f}s...")
                time.sleep(sleep_time)
            else:
                raise RuntimeError(f"WSAPI timed out after {retries} attempts: {e}") from e
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff ** attempt)
            else:
                raise
    
    raise RuntimeError(f"WSAPI request failed: {last_err}")


def _extract_html_from_result(res0: dict) -> str:
    candidates = [
        res0.get("rendered_html"),
        res0.get("content"),
        res0.get("page_content"),
        (res0.get("response") or {}).get("body"),
        (res0.get("response") or {}).get("content"),
        (res0.get("result") or {}).get("content"),
    ]
    for c in candidates:
        if not c: 
            continue
        if isinstance(c, bytes):
            try:
                return c.decode("utf-8", "replace")
            except Exception:
                continue
        if not isinstance(c, str):
            continue
        s = c
        if s.startswith("data:text/html"):
            try:
                meta, data = s.split(",", 1)
            except ValueError:
                data, meta = s, ""
            if ";base64" in meta:
                try:
                    return base64.b64decode(data).decode("utf-8", "replace")
                except Exception:
                    pass
            return unquote(data)
        b64_like = re.fullmatch(r"[A-Za-z0-9+/=\s]{200,}", s or "")
        if b64_like and (len(s.strip()) % 4 == 0):
            try:
                decoded = base64.b64decode(s)
                if b"<" in decoded:
                    return decoded.decode("utf-8", "replace")
            except Exception:
                pass
        return s
    return ""


def _wsapi_get_html(url: str, *, render: Optional[str] = "html",
                    session_id: Optional[str] = None,
                    browser_instructions: Optional[list] = None,
                    geo: str = GEO) -> str:
    payload = {
        "source": "universal",
        "url": url,
        "user_agent_type": "desktop_chrome",
        "geo_location": geo,
        "render": render,
        "parse": False,
    }
    if session_id:
        payload["session_id"] = session_id
    if browser_instructions:
        payload["browser_instructions"] = browser_instructions
    data = _wsapi_request(payload)
    results = data.get("results") or []
    if not results:
        raise RuntimeError("WSAPI returned no results")
    return _extract_html_from_result(results[0])


# -----------------------------
# Site-specific parsing (Harvey Norman AU)
# -----------------------------
def _extract_name(soup: BeautifulSoup) -> str:
    el = soup.select_one("h1.title")
    if el:
        t = _clean(el.get_text(" ", strip=True))
        if t:
            return t
    og = soup.select_one("meta[property='og:title'], meta[name='og:title']")
    if og and og.get("content"):
        t = _clean(og["content"])
        if t:
            return t
    if soup.title:
        t = _clean(soup.title.get_text())
        if t:
            return t
    return "Unknown Product"


def _extract_price_dom(soup: BeautifulSoup) -> Tuple[Optional[str], str]:
    wrap = soup.select_one("div[class*='PriceCard_sf-price-card']")
    if wrap:
        m = _parse_money(wrap.get_text(" ", strip=True))
        if m:
            return m, "PriceCard"
    meta_price = soup.select_one("meta[itemprop='price']")
    if meta_price and meta_price.get("content"):
        m = _parse_money(meta_price["content"])
        if m:
            return m, "meta[itemprop=price]"
    bodytxt = _clean(soup.get_text(" ", strip=True))
    m = _parse_money(bodytxt)
    if m:
        return m, "heuristic"
    return None, "none"


def _extract_price_from_json(soup: BeautifulSoup) -> Tuple[Optional[str], str]:
    for script in soup.find_all("script", type=lambda v: not v or "json" not in v.lower()):
        txt = (script.string or script.get_text() or "").strip()
        if not txt or "price" not in txt.lower():
            continue
        m = re.search(r'"price"\s*:\s*"?(\d+(?:\.\d{2})?)"?', txt)
        if not m:
            m = re.search(r'"salePrice"\s*:\s*"?(\d+(?:\.\d{2})?)"?', txt)
        if m:
            return f"${m.group(1)}", "script JSON"
    
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(tag.get_text() or "")
            objs = obj if isinstance(obj, list) else [obj]
            for it in objs:
                if isinstance(it, dict):
                    offers = it.get("offers")
                    if isinstance(offers, dict):
                        offers = [offers]
                    if isinstance(offers, list):
                        for off in offers:
                            price = off.get("price")
                            if price:
                                m = _parse_money(str(price))
                                if m:
                                    return m, "jsonld"
        except Exception:
            continue
    return None, "none"


def _strip_tags_keep_newlines(html_fragment: str) -> str:
    s = html_fragment
    s = re.sub(r"\s*<li[^>]*>\s*", "\n• ", s, flags=re.I)
    s = re.sub(r"\s*</li>\s*", "", s, flags=re.I)
    s = re.sub(r"\s*<h[1-6][^>]*>\s*", "\n", s, flags=re.I)
    s = re.sub(r"\s*</h[1-6]>\s*", "\n", s, flags=re.I)
    s = re.sub(r"\s*<p[^>]*>\s*", "\n", s, flags=re.I)
    s = re.sub(r"\s*</p>\s*", "\n", s, flags=re.I)
    s = re.sub(r"\s*<br\s*/?>\s*", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    return _clean(re.sub(r"\n{3,}", "\n\n", s)).strip()


def _best_description_text(soup: BeautifulSoup, html_text: str) -> str:
    containers = []
    tab = soup.select_one("#productTabDescription")
    if tab:
        containers.append(tab)
    containers += soup.select("div[class*='ProductPageDescription_']")
    containers += soup.select("div.sf-decode-rich-content")

    for node in containers:
        for bad in node.select("style,script,noscript"):
            bad.decompose()
        txt = _strip_tags_keep_newlines(str(node))
        if txt:
            return txt

    og_desc_el = soup.select_one("meta[property='og:description'], meta[name='og:description']")
    meta_desc_el = soup.select_one("meta[name='description']")
    if og_desc_el and og_desc_el.get("content"):
        return _clean(og_desc_el["content"])
    if meta_desc_el and meta_desc_el.get("content"):
        return _clean(meta_desc_el["content"])

    if html_text:
        soup2 = BeautifulSoup(html_text, "lxml")
        alt = soup2.select_one("div.sf-decode-rich-content, [data-content-type='html']")
        if alt:
            return _strip_tags_keep_newlines(str(alt))
    return ""


# ----- Image helpers -----
def _imgix_to_hq(url: str, w: int = 2000, h: int = 2000) -> str:
    """Upgrade imgix URL to higher resolution."""
    try:
        u = urlparse(url)
        qs = dict(re.findall(r"([^=&?#]+)=([^&=#]+)", u.query or ""))
        qs["w"] = str(w)
        qs["h"] = str(h)
        qs["fit"] = "max"
        if "auto" not in qs:
            qs["auto"] = "compress,format"
        q = urlencode(qs)
        return urlunparse((u.scheme, u.netloc, u.path, u.params, q, ""))
    except Exception:
        return url


def _extract_image_id(url: str) -> str:
    """
    Extract unique identifier from Harvey Norman imgix URL.
    URLs look like: https://hnau.imgix.net/media/catalog/product/1/_/1._product_image_laen_dome_kettle.jpg?...
    The unique part is the path: /media/catalog/product/1/_/1._product_image_laen_dome_kettle.jpg
    """
    try:
        path = urlparse(url).path
        # Normalize path (remove leading/trailing slashes, lowercase)
        return path.strip("/").lower()
    except Exception:
        return url.lower()


def _is_product_image(u: str) -> bool:
    """Check if URL is a valid product image (not logo, badge, etc.)"""
    path = (urlparse(u).path or "").lower()
    
    # Must be from imgix CDN
    if "imgix.net" not in u.lower():
        return False
    
    # Must be in catalog/product path
    if "/media/catalog/product/" not in path:
        return False
    
    # Exclude non-product images
    bad = ("/brand/", "/placeholder", "/logo", "/badge", "/payment", "/footer", "/wysiwyg")
    return not any(b in path for b in bad)


def _collect_images_from_html(soup: BeautifulSoup, base: str, max_images: Optional[int]) -> List[str]:
    """
    Collect unique product images from Harvey Norman page.
    - Only from the product carousel (not og:image meta)
    - Skip clone slides (used for infinite scroll)
    - Deduplicate by image path
    """
    candidates: List[str] = []
    seen_ids: set = set()
    
    # Primary: product gallery images from Glide slider
    # Skip slides with 'glide__slide--clone' class (these are duplicates for infinite scrolling)
    for slide in soup.select("li.Slider_glide__slide__INv_h"):
        # Skip clone slides
        classes = slide.get("class", [])
        if "glide__slide--clone" in classes:
            continue
        
        # Get image from this slide
        img = slide.select_one("img")
        if not img:
            continue
        
        src = (img.get("src") or "").strip()
        if not src or "imgix.net" not in src:
            continue
        
        # Check for duplicates using image path
        img_id = _extract_image_id(src)
        if img_id in seen_ids:
            continue
        seen_ids.add(img_id)
        
        # Only include actual product images
        if _is_product_image(src):
            candidates.append(src)
    
    # Fallback: if no images found from slider, try general imgix images
    if not candidates:
        for img in soup.select("img[src*='imgix.net']"):
            src = (img.get("src") or "").strip()
            if not src:
                continue
            
            img_id = _extract_image_id(src)
            if img_id in seen_ids:
                continue
            seen_ids.add(img_id)
            
            if _is_product_image(src):
                candidates.append(src)
    
    # Upgrade to high-res
    result = [_imgix_to_hq(u) for u in candidates]
    
    # Sort by image number (1._product, 2._product, etc.)
    def _order_key(s: str) -> tuple:
        path = urlparse(s).path or ""
        fname = os.path.basename(path)
        # Extract leading number like "1." or "2."
        m = re.match(r"(\d+)\.", fname)
        if m:
            return (int(m.group(1)), fname)
        return (999, fname)
    
    result.sort(key=_order_key)
    
    if max_images is not None:
        result = result[:max_images]
    
    return result


# ---- Image downloads ----
def _download_image_direct(url: str, dest: Path, referer: str) -> bool:
    try:
        headers = {
            "User-Agent": UA,
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            "Accept-Language": ACCEPT_LANG,
            "Referer": referer,
        }
        with requests.get(url, headers=headers, timeout=45, stream=True) as r:
            ct = (r.headers.get("Content-Type") or "").lower()
            if r.status_code == 200 and (ct.startswith("image/") or r.content):
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(65536):
                        if chunk:
                            f.write(chunk)
                return True
    except Exception:
        pass
    return False


def _download_image_via_proxy(url: str, dest: Path, referer: str) -> bool:
    try:
        headers = {
            "User-Agent": UA,
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            "Accept-Language": ACCEPT_LANG,
            "Referer": referer,
        }
        proxies = {
            "http": f"http://{OXY_USER}:{OXY_PASS}@realtime.oxylabs.io:60000",
            "https": f"http://{OXY_USER}:{OXY_PASS}@realtime.oxylabs.io:60000",
        }
        with requests.get(url, headers=headers, timeout=60, stream=True, proxies=proxies, verify=False) as r:
            ct = (r.headers.get("Content-Type") or "").lower()
            if r.status_code == 200 and (ct.startswith("image/") or r.content):
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(65536):
                        if chunk:
                            f.write(chunk)
                return True
    except Exception:
        pass
    return False


def _download_images_auto(image_urls: List[str], folder: Path, referer: str) -> List[str]:
    saved_paths: List[str] = []
    for idx, img_url in enumerate(image_urls, start=1):
        ext = ".jpg"
        m = re.search(r"[.?](jpg|jpeg|png|webp|gif|avif)(?:$|[?&])", img_url, re.I)
        if m:
            ext_found = m.group(1).lower()
            ext = ".jpg" if ext_found in ("jpeg", "webp") else f".{ext_found}"
        
        fname = f"{idx:02d}{ext}"
        dest = folder / fname
        
        if _download_image_direct(img_url, dest, referer) or _download_image_via_proxy(img_url, dest, referer):
            saved_paths.append(str(dest))
    
    return saved_paths


# -----------------------------
# Scraper entry
# -----------------------------
def scrape_harveynorman(url: str, max_images: Optional[int] = 10, verbose: bool = False) -> dict:
    """
    Scrape Harvey Norman AU product page via Oxylabs WSAPI.
    """
    url, _ = urldefrag(url)
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    slug = _slug_from_host(url)
    stable_id = _stable_id_from_url(url)
    ts = _utc_stamp()

    if verbose:
        print(f"Fetching {url}...")

    browser_instructions = [
        {"type": "scroll", "x": 0, "y": 700},
        {"type": "wait", "wait_time_s": 1},
        {"type": "scroll", "x": 0, "y": 1600},
        {"type": "wait", "wait_time_s": 1},
        # Click description tab
        {"type": "click", "selector": {"type": "css", "value": "a[href*='productTabDescription']"}},
        {"type": "wait", "wait_time_s": 1},
        # Click "Read more" button
        {"type": "click", "selector": {"type": "css", "value": "#productTabDescription button"}},
        {"type": "wait", "wait_time_s": 1},
    ]
    session_id = f"sess-{int(time.time())}"

    # 1) Rendered with clicks
    html_text = ""
    try:
        html_text = _wsapi_get_html(
            url, render="html", session_id=session_id,
            browser_instructions=browser_instructions, geo=GEO
        )
    except Exception as e:
        if verbose:
            print(f"  First attempt failed: {e}")
        try:
            html_text = _wsapi_get_html(url, render="html", session_id=session_id, geo=GEO)
        except Exception:
            pass

    # 3) Non-render fallback
    if not html_text or "<" not in html_text:
        if verbose:
            print("  Trying non-rendered fallback...")
        html_text = _wsapi_get_html(url, render=None, session_id=session_id, geo=GEO)

    soup = BeautifulSoup(html_text or "", "lxml")

    # Name
    name = _extract_name(soup)

    # Price (DOM first to catch special/sale prices, then JSON fallback)
    price, price_src = _extract_price_dom(soup)
    if not price:
        price, price_src = _extract_price_from_json(soup)

    # Stock / availability
    # Priority: 1) Rendered CTA button (most reliable), 2) JSON-LD fallback, 3) Text scan last resort
    in_stock: Optional[bool] = None
    stock_text = ""

    # 1) Check rendered CTA button first — reflects actual page state
    cta = (
        soup.select_one("[data-testid='add-to-cart']") or
        soup.select_one("button[data-gtm-tracking*='Add to cart' i]") or
        soup.select_one("#regular-cta-buttons-wrapper button") or
        soup.select_one("button[aria-label*='cart' i]")
    )
    if cta:
        cta_txt = _clean(cta.get_text(" ", strip=True)).lower()
        cta_label = (cta.get("aria-label") or "").lower()
        combined = cta_txt + " " + cta_label
        is_disabled = (
            cta.has_attr("disabled")
            or str(cta.get("aria-disabled", "")).lower() == "true"
        )
        if is_disabled:
            in_stock, stock_text = False, "CTA disabled"
        elif re.search(r"add.{0,5}(cart|basket|trolley)|buy now", combined):
            in_stock, stock_text = True, "Add to cart button"
        elif re.search(r"out of stock|notify me|pre-?order|coming soon|sold out", combined):
            in_stock, stock_text = False, "CTA OOS text"

    # 2) JSON-LD fallback (only if CTA button not found or inconclusive)
    if in_stock is None:
        jsonld_list: List[str] = []
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                jsonld_list.append(tag.get_text() or "")
            except Exception:
                pass
        try:
            for blob in jsonld_list:
                obj = json.loads(blob)
                objs = obj if isinstance(obj, list) else [obj]
                for it in objs:
                    if isinstance(it, dict):
                        offers = it.get("offers")
                        if isinstance(offers, dict):
                            offers = [offers]
                        if isinstance(offers, list):
                            for off in offers:
                                avail = str(off.get("availability", "")).lower()
                                if "instock" in avail:
                                    in_stock, stock_text = True, "InStock (JSON-LD)"
                                elif "outofstock" in avail or "soldout" in avail:
                                    in_stock, stock_text = False, "OutOfStock (JSON-LD)"
        except Exception:
            pass

    # 3) Text scan last resort
    if in_stock is None:
        body = _clean(soup.get_text(" ", strip=True)).lower()
        if "add to cart" in body:
            in_stock, stock_text = True, "Add to cart visible"
        elif "out of stock" in body or "sold out" in body:
            in_stock, stock_text = False, "Sold Out"

    # Description
    description = _best_description_text(soup, html_text)

    # Images
    image_urls = _collect_images_from_html(soup, base, max_images=max_images)

    if verbose:
        print(f"  Name: {name}")
        print(f"  Price: {price}")
        print(f"  In Stock: {in_stock}")
        print(f"  Images found: {len(image_urls)}")

    # Final folder
    folder = DATA_DIR / f"{SITE_TAG}_{_safe_name(name)}_{stable_id}_{ts}"
    _ensure_dir(folder)
    
    if verbose:
        print(f"  Downloading {len(image_urls)} images...")
    
    images = _download_images_auto(image_urls, folder, referer=url)

    return {
        "source_url": url,
        "name": name,
        "price": price or "N/A",
        "price_source": price_src,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_count": len(images),
        "image_urls": image_urls,
        "images": images,
        "folder": str(folder),
        "mode": "wsapi (render+browser_instructions)",
        "timestamp_utc": ts,
    }


# # -----------------------------
# # CLI
# # -----------------------------
# if __name__ == "__main__":
#     URL = "https://www.harveynorman.com.au/laura-ashley-1-7l-dome-kettle-elveden-navy.html"
#     result = scrape_harveynorman(URL, max_images=12, verbose=True)
#     print("\n" + "=" * 60)
#     print("RESULTS:")
#     print("=" * 60)
#     print(json.dumps(result, indent=2, ensure_ascii=False))