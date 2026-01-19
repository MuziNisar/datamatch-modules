# # homedepot_oxylabs.py
# # Python 3.9+
# # pip install requests beautifulsoup4 lxml

# import os
# import re
# import json
# import hashlib
# from pathlib import Path
# from typing import Optional, Tuple, List
# from urllib.parse import urlparse

# import requests
# from bs4 import BeautifulSoup

# # -----------------------------
# # Config
# # -----------------------------
# UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# BASE_DIR = Path(__file__).resolve().parent
# DATA_DIR = BASE_DIR / "data_homedepot"
# DATA_DIR.mkdir(parents=True, exist_ok=True)

# # # Set your Oxylabs credentials via env or hardcode here
# # OXY_USER = os.getenv("OXYLABS_USERNAME", "Muzamil_wUDhn")
# # OXY_PASS = os.getenv("OXYLABS_PASSWORD", "Muzamil_13111")


# OXY_USER = os.getenv("OXY_USER", "dawni_MDFrW")   
# OXY_PASS = os.getenv("OXY_PASS", "Dawn_1234567")


# # -----------------------------
# # Small helpers
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
#     """
#     Prefer the explicit Internet # in page later; here use last path token or SHA1.
#     """
#     try:
#         path = (urlparse(url).path or "").rstrip("/")
#         last = path.split("/")[-1]
#         if last:
#             return last
#     except Exception:
#         pass
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

# def _ensure_dir(p: Path):
#     p.mkdir(parents=True, exist_ok=True)

# def _parse_money(text: str) -> Optional[str]:
#     if not text:
#         return None
#     text = _clean(text)
#     m = re.search(r"\$?\s*(\d[\d,]*)(?:\.(\d{2}))?", text)
#     if not m:
#         return None
#     dollars = m.group(1).replace(",", "")
#     cents = m.group(2) if m.group(2) is not None else "00"
#     return f"${dollars}.{cents}"

# # -----------------------------
# # Oxylabs fetch
# # -----------------------------
# def _fetch_with_oxylabs_universal(url: str, render_html: bool = True) -> str:
#     payload = {"source": "universal", "url": url}
#     if render_html:
#         payload["render"] = "html"

#     r = requests.post(
#         "https://realtime.oxylabs.io/v1/queries",
#         auth=(OXY_USER, OXY_PASS),
#         json=payload,
#         timeout=60,
#     )
#     r.raise_for_status()
#     data = r.json()

#     # Standard: results[0].content
#     if isinstance(data, dict) and data.get("results"):
#         content = data["results"][0].get("content") or ""
#         if content:
#             return content

#     # Some accounts return top-level content
#     if isinstance(data, dict) and data.get("content"):
#         return data["content"] or ""

#     raise RuntimeError("Oxylabs: no rendered HTML returned")

# # -----------------------------
# # Field extraction
# # -----------------------------
# def _extract_name(soup: BeautifulSoup) -> str:
#     # Exact selector you provided
#     h1 = soup.select_one("h1.sui-h4-bold.sui-line-clamp-unset.sui-font-normal.sui-text-primary")
#     if h1:
#         t = _clean(h1.get_text(" ", strip=True))
#         if t:
#             return t
#     # Fallbacks
#     h1_any = soup.select_one("h1")
#     if h1_any:
#         return _clean(h1_any.get_text(" ", strip=True))
#     og = soup.select_one('meta[property="og:title"]')
#     if og and og.get("content"):
#         return _clean(og["content"])
#     return "Unknown Product"

# def _extract_price(soup: BeautifulSoup) -> Tuple[str, str]:
#     """
#     HomeDepot splits price into 3 spans: $, dollars (e.g., '89'), cents (e.g., '99').
#     We'll try to reconstruct; then fallback to regex scan.
#     """
#     price_wrap = soup.select_one("div.sui-flex.sui-flex-row.sui-leading-none")
#     if price_wrap:
#         parts = [el.get_text("", strip=True) for el in price_wrap.find_all("span")]
#         # Expected like ['$', '89', '99'] (there may be a screen-reader '.' span)
#         digits = "".join([p for p in parts if p and p != "."])
#         m = re.match(r"^\$?(\d+)(\d{2})$", digits)
#         if m:
#             return f"${m.group(1)}.{m.group(2)}", "onsite"
#         # if not matching, try general money parsing
#         money = _parse_money("".join(parts))
#         if money:
#             return money, "onsite"

#     # Fallback: wide scan
#     money = _parse_money(soup.get_text(" ", strip=True))
#     if money:
#         return money, "text-scan"

#     return "N/A", "none"

# def _extract_ids(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
#     """
#     Grab 'Internet #' and 'Model #' from Product Information bar.
#     """
#     internet_no = None
#     model_no = None
#     # Look for "Product Information" block first
#     try:
#         info = soup.select_one('[data-testid="productInfo"]') or soup.find("div", class_="product-info-bar")
#         block_text = info.get_text(" ", strip=True) if info else soup.get_text(" ", strip=True)
#         m1 = re.search(r"Internet\s*#\s*(\d+)", block_text, re.I)
#         if m1:
#             internet_no = m1.group(1)
#         m2 = re.search(r"Model\s*#\s*([A-Za-z0-9\-\._]+)", block_text, re.I)
#         if m2:
#             model_no = m2.group(1)
#     except Exception:
#         pass
#     return internet_no, model_no

# def _extract_description_and_highlights(soup: BeautifulSoup) -> str:
#     parts: List[str] = []

#     # About This Product (paragraphs under the h3)
#     about_h3 = None
#     for h3 in soup.select("h3"):
#         if _clean(h3.get_text()).lower() == "about this product":
#             about_h3 = h3
#             break
#     if about_h3:
#         # collect sibling <p> within the same container
#         parent = about_h3.find_parent()
#         if parent:
#             for p in parent.find_all("p"):
#                 txt = _clean(p.get_text(" ", strip=True))
#                 if txt:
#                     parts.append(txt)

#     # Highlights bullets
#     ul = soup.select_one('[data-testid="bullet-list"]')
#     if ul:
#         for li in ul.select('[data-testid="bullet-list-item"]'):
#             txt = _clean(li.get_text(" ", strip=True))
#             if txt:
#                 parts.append(f"• {txt}")

#     # Fallback: meta description / JSON-LD
#     if not parts:
#         meta = soup.select_one('meta[name="description"]')
#         if meta and meta.get("content"):
#             parts.append(_clean(meta["content"]))
#     if not parts:
#         for s in soup.select('script[type="application/ld+json"]'):
#             try:
#                 data = json.loads(s.get_text(strip=True))
#                 objs = data if isinstance(data, list) else [data]
#                 for o in objs:
#                     if isinstance(o, dict) and o.get("@type") == "Product":
#                         d = _clean(o.get("description") or "")
#                         if d:
#                             parts.append(d)
#                             break
#             except Exception:
#                 continue

#     # De-dupe consecutive
#     out: List[str] = []
#     for p in parts:
#         if not out or out[-1] != p:
#             out.append(p)
#     return "\n".join(out)

# def _detect_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
#     # Positive: Add to Cart button in add-to-cart component
#     atc_divs = soup.select('[data-component^="add-to-cart"]')
#     for d in atc_divs:
#         btn = d.find("button")
#         if btn and "add to cart" in _clean(btn.get_text(" ", strip=True)).lower():
#             return True, "Add to Cart available"

#     # Negative cues
#     body = _clean(soup.get_text(" ", strip=True)).lower()
#     if any(w in body for w in ["out of stock", "unavailable", "sold out"]):
#         return False, "Unavailable"

#     return None, ""

# # -----------------------------
# # Images (HomeDepot thumbnails -> upsize)
# # -----------------------------
# def _upsize_hd_thumb(u: str, size: int = 1000) -> str:
#     """
#     THD thumbs look like ...-64_100.jpg or ...-e1_100.jpg etc.
#     Replace trailing _100 with _1000 to request larger image.
#     """
#     return re.sub(r"_(\d+)(\.(?:jpg|jpeg|png|webp))$", f"_{size}\\2", u, flags=re.I)

# def _stable_image_key(url: str) -> str:
#     try:
#         fname = os.path.basename(urlparse(url).path)
#         stem, ext = os.path.splitext(fname)
#         # Remove trailing _<digits> size tag for dedupe
#         stem = re.sub(r"_(\d+)$", "", stem)
#         return stem.lower()
#     except Exception:
#         return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]

# def _collect_images(soup: BeautifulSoup, max_images: Optional[int] = None) -> List[str]:
#     urls: List[str] = []
#     for img in soup.select(".mediagallery__thumbnails img[src]"):
#         src = img.get("src")
#         if src:
#             urls.append(src)

#     # Upsize & dedupe
#     seen = set()
#     out: List[str] = []
#     for u in urls:
#         nu = _upsize_hd_thumb(u, size=1000) if "images.thdstatic.com" in u else u
#         key = _stable_image_key(nu)
#         if key in seen:
#             continue
#         seen.add(key)
#         out.append(nu)
#         if max_images and len(out) >= max_images:
#             break
#     return out

# def _download_image(url: str, dest: Path) -> bool:
#     try:
#         r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
#         if r.ok and r.content:
#             dest.write_bytes(r.content)
#             return True
#     except Exception:
#         pass
#     return False

# # -----------------------------
# # Scraper
# # -----------------------------
# def scrape_homedepot_with_oxylabs(
#     url: str,
#     max_images: Optional[int] = None,
#     download_images: bool = True,
# ) -> dict:
#     html = _fetch_with_oxylabs_universal(url, render_html=True)
#     soup = BeautifulSoup(html, "lxml")

#     name = _extract_name(soup)
#     price, price_source = _extract_price(soup)
#     internet_no, model_no = _extract_ids(soup)
#     in_stock, stock_text = _detect_stock(soup)
#     description = _extract_description_and_highlights(soup)
#     image_urls = _collect_images(soup, max_images=max_images)

#     slug = _slug_from_host(url)
#     stable_id = internet_no or model_no or _stable_id_from_url(url)
#     folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}"
#     _ensure_dir(folder)

#     saved: List[str] = []
#     if download_images:
#         for i, img_url in enumerate(image_urls, start=1):
#             ext = ".jpg"
#             m = re.search(r"\.(jpg|jpeg|png|webp|gif)(?:$|\?)", img_url, re.I)
#             if m:
#                 ext = "." + m.group(1).lower()
#             fname = f"{i:02d}_{_safe_name(_stable_image_key(img_url))}{ext}"
#             if _download_image(img_url, folder / fname):
#                 saved.append(str(folder / fname))

#     return {
#         "url": url,
#         "name": name,
#         "price": price,
#         "price_source": price_source if price != "N/A" else "none",
#         "in_stock": in_stock,
#         "stock_text": stock_text,
#         "internet_no": internet_no,
#         "model_no": model_no,
#         "description": description,
#         "image_count": len(saved) if download_images else len(image_urls),
#         "image_urls": image_urls,
#         "images_downloaded": saved,
#         "folder": str(folder),
#         "fetched_via": "oxylabs-universal",
#     }

# # -----------------------------
# # CLI
# # -----------------------------
# if __name__ == "__main__":
#     TEST_URL = "https://www.homedepot.com/p/Laura-Ashley-VQ-7-Cup-China-Rose-Cordless-Dome-Electric-Kettle-with-Thermometer-VQSBPKK336LACR/331358936"
#     data = scrape_homedepot_with_oxylabs(TEST_URL, max_images=None, download_images=True)
#     print(json.dumps(data, indent=2, ensure_ascii=False))










# # homedepot_oxylabs.py
# # Python 3.9+
# # pip install requests beautifulsoup4 lxml

# import os
# import re
# import json
# import time
# import uuid
# import hashlib
# from pathlib import Path
# from typing import Optional, Tuple, List
# from urllib.parse import urlparse

# import requests
# from bs4 import BeautifulSoup

# # ---- use your secrets file (no hardcoded creds) ----
# from oxylabs_secrets import OXY_USER, OXY_PASS

# # -----------------------------
# # Config
# # -----------------------------
# UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()

# DATA_DIR = BASE_DIR / "data_homedepot"
# DATA_DIR.mkdir(parents=True, exist_ok=True)

# # -----------------------------
# # Small helpers
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
#     """
#     Prefer the explicit Internet # later; here use last path token or SHA1.
#     """
#     try:
#         path = (urlparse(url).path or "").rstrip("/")
#         last = path.split("/")[-1]
#         if last:
#             return last
#     except Exception:
#         pass
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

# def _ensure_dir(p: Path):
#     p.mkdir(parents=True, exist_ok=True)

# def _parse_money(text: str) -> Optional[str]:
#     if not text:
#         return None
#     text = _clean(text)
#     m = re.search(r"\$?\s*(\d[\d,]*)(?:\.(\d{2}))?", text)
#     if not m:
#         return None
#     dollars = m.group(1).replace(",", "")
#     cents = m.group(2) if m.group(2) is not None else "00"
#     return f"${dollars}.{cents}"

# def _unique_suffix() -> str:
#     # short unique suffix per run (time + uuid fragment)
#     t = int(time.time() * 1000) % 10_000_000
#     u = uuid.uuid4().hex[:6]
#     return f"{t}_{u}"

# # -----------------------------
# # Oxylabs fetch
# # -----------------------------
# _SESSION = requests.Session()
# _SESSION.headers.update({
#     "User-Agent": UA,
#     "Accept": "application/json",
#     "Content-Type": "application/json",
# })

# def _fetch_with_oxylabs_universal(url: str, render_html: bool = True) -> str:
#     payload = {"source": "universal", "url": url}
#     if render_html:
#         payload["render"] = "html"

#     r = _SESSION.post(
#         "https://realtime.oxylabs.io/v1/queries",
#         auth=(OXY_USER, OXY_PASS),
#         json=payload,
#         timeout=60,
#     )
#     r.raise_for_status()
#     data = r.json()

#     # Standard: results[0].content
#     if isinstance(data, dict) and data.get("results"):
#         content = data["results"][0].get("content") or ""
#         if content:
#             return content

#     # Some accounts return top-level content
#     if isinstance(data, dict) and data.get("content"):
#         return data["content"] or ""

#     raise RuntimeError("Oxylabs: no rendered HTML returned")

# # -----------------------------
# # Field extraction
# # -----------------------------
# def _extract_name(soup: BeautifulSoup) -> str:
#     # Your exact selector (primary)
#     h1 = soup.select_one("h1.sui-h4-bold.sui-line-clamp-unset.sui-font-normal.sui-text-primary")
#     if h1:
#         t = _clean(h1.get_text(" ", strip=True))
#         if t:
#             return t
#     # Fallbacks
#     h1_any = soup.select_one("h1")
#     if h1_any:
#         t = _clean(h1_any.get_text(" ", strip=True))
#         if t:
#             return t
#     og = soup.select_one('meta[property="og:title"]')
#     if og and og.get("content"):
#         return _clean(og["content"])
#     return "Unknown Product"

# def _extract_price(soup: BeautifulSoup) -> Tuple[str, str]:
#     """
#     HomeDepot often splits price into spans.
#     Try to reconstruct; then fallback to broad scan.
#     """
#     # Common price container (adjusted to be robust)
#     candidates = [
#         "div.sui-flex.sui-flex-row.sui-leading-none",
#         "[data-testid='price']",
#         "div.price__numbers"  # generic fallback
#     ]
#     for sel in candidates:
#         wrap = soup.select_one(sel)
#         if not wrap:
#             continue
#         parts = [el.get_text("", strip=True) for el in wrap.find_all("span")]
#         digits = "".join([p for p in parts if p and p != "."])
#         m = re.match(r"^\$?(\d+)(\d{2})$", digits)
#         if m:
#             return f"${m.group(1)}.{m.group(2)}", "onsite"
#         money = _parse_money(" ".join(parts))
#         if money:
#             return money, "onsite"

#     # Fallback: wide scan of whole page text
#     money = _parse_money(soup.get_text(" ", strip=True))
#     if money:
#         return money, "text-scan"

#     return "N/A", "none"

# def _extract_ids(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
#     """
#     Grab 'Internet #' and 'Model #' from Product Information block.
#     """
#     internet_no = None
#     model_no = None
#     try:
#         info = soup.select_one('[data-testid="productInfo"]') or soup.find("div", class_="product-info-bar")
#         block_text = _clean(info.get_text(" ", strip=True)) if info else _clean(soup.get_text(" ", strip=True))
#         m1 = re.search(r"Internet\s*#\s*([A-Za-z0-9\-]+)", block_text, re.I)
#         if m1:
#             internet_no = m1.group(1)
#         m2 = re.search(r"Model\s*#\s*([A-Za-z0-9\-\._]+)", block_text, re.I)
#         if m2:
#             model_no = m2.group(1)
#     except Exception:
#         pass
#     return internet_no, model_no

# def _extract_description_and_highlights(soup: BeautifulSoup) -> str:
#     parts: List[str] = []

#     # About This Product
#     about_h3 = None
#     for h3 in soup.select("h3"):
#         if _clean(h3.get_text()).lower() == "about this product":
#             about_h3 = h3
#             break
#     if about_h3:
#         parent = about_h3.find_parent()
#         if parent:
#             for p in parent.find_all("p"):
#                 txt = _clean(p.get_text(" ", strip=True))
#                 if txt:
#                     parts.append(txt)

#     # Highlights bullets
#     ul = soup.select_one('[data-testid="bullet-list"]')
#     if ul:
#         for li in ul.select('[data-testid="bullet-list-item"]'):
#             txt = _clean(li.get_text(" ", strip=True))
#             if txt:
#                 parts.append(f"• {txt}")

#     # Fallbacks
#     if not parts:
#         meta = soup.select_one('meta[name="description"]')
#         if meta and meta.get("content"):
#             parts.append(_clean(meta["content"]))
#     if not parts:
#         for s in soup.select('script[type="application/ld+json"]'):
#             try:
#                 data = json.loads(s.get_text(strip=True))
#                 objs = data if isinstance(data, list) else [data]
#                 for o in objs:
#                     if isinstance(o, dict) and o.get("@type") == "Product":
#                         d = _clean(o.get("description") or "")
#                         if d:
#                             parts.append(d)
#                             break
#             except Exception:
#                 continue

#     # De-dupe consecutive
#     out: List[str] = []
#     for p in parts:
#         if not out or out[-1] != p:
#             out.append(p)
#     return "\n".join(out)

# def _detect_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
#     # Positive: Add to Cart button
#     atc_divs = soup.select('[data-component^="add-to-cart"], [data-testid="add-to-cart"]')
#     for d in atc_divs:
#         btn = d.find("button")
#         if btn and "add to cart" in _clean(btn.get_text(" ", strip=True)).lower():
#             return True, "Add to Cart available"
#     # Negative cues
#     body = _clean(soup.get_text(" ", strip=True)).lower()
#     if any(w in body for w in ["out of stock", "unavailable", "sold out"]):
#         return False, "Unavailable"
#     return None, ""

# # -----------------------------
# # Images (HomeDepot thumbnails -> upsize)
# # -----------------------------
# def _upsize_hd_thumb(u: str, size: int = 1000) -> str:
#     """
#     THD thumbs look like ...-64_100.jpg or ...-e1_100.jpg etc.
#     Replace trailing _100 with _1000 to request larger image.
#     """
#     return re.sub(r"_(\d+)(\.(?:jpg|jpeg|png|webp))$", f"_{size}\\2", u, flags=re.I)

# def _stable_image_key(url: str) -> str:
#     try:
#         fname = os.path.basename(urlparse(url).path)
#         stem, ext = os.path.splitext(fname)
#         # Remove trailing _<digits> size tag for dedupe
#         stem = re.sub(r"_(\d+)$", "", stem)
#         return stem.lower()
#     except Exception:
#         return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]

# def _collect_images(soup: BeautifulSoup, max_images: Optional[int] = None) -> List[str]:
#     urls: List[str] = []
#     # primary gallery
#     for img in soup.select(".mediagallery__thumbnails img[src]"):
#         src = img.get("src")
#         if src:
#             urls.append(src)
#     # also check og:image as fallback
#     og_img = soup.select_one('meta[property="og:image"]')
#     if og_img and og_img.get("content"):
#         urls.append(og_img["content"])

#     # Upsize & dedupe
#     seen = set()
#     out: List[str] = []
#     for u in urls:
#         nu = _upsize_hd_thumb(u, size=1000) if "images.thdstatic.com" in u else u
#         key = _stable_image_key(nu)
#         if key in seen:
#             continue
#         seen.add(key)
#         out.append(nu)
#         if max_images and len(out) >= max_images:
#             break
#     return out

# def _download_image(url: str, dest: Path) -> bool:
#     try:
#         r = _SESSION.get(url, headers={"User-Agent": UA}, timeout=25)
#         if r.ok and r.content:
#             dest.write_bytes(r.content)
#             return True
#     except Exception:
#         pass
#     return False

# # -----------------------------
# # Scraper (kept function name & signature)
# # -----------------------------
# def scrape_homedepot_with_oxylabs(
#     url: str,
#     max_images: Optional[int] = None,
#     download_images: bool = True,
# ) -> dict:
#     """
#     Drop-in: same signature & return schema, but:
#       - uses Oxylabs Realtime 'universal' with rendered HTML
#       - saves to a unique folder each run
#       - uses creds from oxylabs_secrets.py
#     """
#     html = _fetch_with_oxylabs_universal(url, render_html=True)
#     soup = BeautifulSoup(html, "lxml")

#     name = _extract_name(soup)
#     price, price_source = _extract_price(soup)
#     internet_no, model_no = _extract_ids(soup)
#     in_stock, stock_text = _detect_stock(soup)
#     description = _extract_description_and_highlights(soup)
#     image_urls = _collect_images(soup, max_images=max_images)

#     slug = _slug_from_host(url)
#     stable_id = internet_no or model_no or _stable_id_from_url(url)

#     # ---- UNIQUE folder name each time ----
#     unique = _unique_suffix()
#     folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}_{unique}"
#     _ensure_dir(folder)

#     saved: List[str] = []
#     if download_images:
#         for i, img_url in enumerate(image_urls, start=1):
#             ext = ".jpg"
#             m = re.search(r"\.(jpg|jpeg|png|webp|gif)(?:$|\?)", img_url, re.I)
#             if m:
#                 ext = "." + m.group(1).lower()
#             fname = f"{i:02d}_{_safe_name(_stable_image_key(img_url))}{ext}"
#             if _download_image(img_url, folder / fname):
#                 saved.append(str(folder / fname))

#     return {
#         "url": url,
#         "name": name,
#         "price": price,
#         "price_source": price_source if price != "N/A" else "none",
#         "in_stock": in_stock,
#         "stock_text": stock_text,
#         "internet_no": internet_no,
#         "model_no": model_no,
#         "description": description,
#         "image_count": len(saved) if download_images else len(image_urls),
#         "image_urls": image_urls,
#         "images_downloaded": saved,
#         "folder": str(folder),
#         "fetched_via": "oxylabs-universal",
#     }

# # -----------------------------
# # CLI (kept exactly)
# # -----------------------------
# if __name__ == "__main__":
#     TEST_URL = "https://www.homedepot.com/p/Laura-Ashley-VQ-7-Cup-China-Rose-Cordless-Dome-Electric-Kettle-with-Thermometer-VQSBPKK336LACR/331358936"
#     data = scrape_homedepot_with_oxylabs(TEST_URL, max_images=None, download_images=True)
#     print(json.dumps(data, indent=2, ensure_ascii=False))




# homedepot_oxylabs.py
# Python 3.9+
# pip install requests beautifulsoup4 lxml

import os
import re
import json
import time
import uuid
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag

# ---- secrets (use your local oxylabs_secrets.py) ----
from oxylabs_secrets import OXY_USER, OXY_PASS

# -----------------------------
# Config
# -----------------------------
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()

DATA_DIR = BASE_DIR / "data_homedepot"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# aim for main gallery; typical 8–10, but we accept any >= 2 as “good”
TARGET_GALLERY_MIN = 8
MIN_OK_IMAGES = 2

# -----------------------------
# Small helpers
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
    """
    Prefer Internet # later; otherwise last path token or SHA1.
    """
    try:
        path = (urlparse(url).path or "").rstrip("/")
        last = path.split("/")[-1]
        if last:
            return last
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

def _ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def _parse_money(text: str) -> Optional[str]:
    if not text:
        return None
    text = _clean(text)
    m = re.search(r"\$?\s*(\d[\d,]*)(?:\.(\d{2}))?", text)
    if not m:
        return None
    dollars = m.group(1).replace(",", "")
    cents = m.group(2) if m.group(2) is not None else "00"
    return f"${dollars}.{cents}"

def _unique_suffix() -> str:
    t = int(time.time() * 1000) % 10_000_000
    u = uuid.uuid4().hex[:6]
    return f"{t}_{u}"

def _guid_from_thd_url(u: str) -> Optional[str]:
    """
    https://images.thdstatic.com/productImages/<GUID>/svn/...
    """
    m = re.search(r"/productImages/([0-9a-f-]{32,36})/", u, re.I)
    return m.group(1).lower() if m else None

# -----------------------------
# Oxylabs fetch
# -----------------------------
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": UA,
    "Accept": "application/json",
    "Content-Type": "application/json",
})

def _browser_instructions_light() -> List[Dict]:
    # fast: just ensure page & a bottom scroll to mount some lazy content
    return [
        {"type": "wait_for_element",
         "selector": {"type": "css", "value": "body"},
         "timeout_s": 10},
        {"type": "scroll_to_bottom", "timeout_s": 8},
        {"type": "wait", "wait_time_s": 0.8},
    ]

def _browser_instructions_aggressive() -> List[Dict]:
    # slower but robust: focus the media gallery, scroll around it
    return [
        {"type": "wait_for_element",
         "selector": {"type": "css", "value": "body"},
         "timeout_s": 15},
        {"type": "wait_for_element",
         "selector": {"type": "css", "value": ".mediagallery__thumbnail img, img[data-testid='thumbnail-image']"},
         "timeout_s": 12},
        {"type": "scroll_element_into_view",
         "selector": {"type": "css", "value": ".mediagallery__thumbnail, [data-testid='thumbnail-image']"},
         "timeout_s": 8},
        {"type": "scroll_by", "x": 0, "y": 600, "timeout_s": 4},
        {"type": "wait", "wait_time_s": 0.6},
        {"type": "scroll_by", "x": 0, "y": -400, "timeout_s": 4},
        {"type": "wait", "wait_time_s": 0.6},
        # one more bottom pass to trigger lazy grids
        {"type": "scroll_to_bottom", "timeout_s": 8},
        {"type": "wait", "wait_time_s": 0.8},
    ]

def _post_oxylabs(payload: Dict) -> str:
    r = _SESSION.post(
        "https://realtime.oxylabs.io/v1/queries",
        auth=(OXY_USER, OXY_PASS),
        data=json.dumps(payload),
        timeout=150,
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
        # Plain render fallback (some accounts prefer this)
        payload2 = {"source": "universal", "url": url, "render": "html"}
        return _post_oxylabs(payload2)

# -----------------------------
# JSON helpers
# -----------------------------
def _load_json_scripts(soup: BeautifulSoup) -> List[Any]:
    blobs: List[Any] = []

    # Next.js: __NEXT_DATA__
    for s in soup.find_all("script", id=re.compile(r"__NEXT_DATA__", re.I), type=re.compile("application/json", re.I)):
        try:
            blobs.append(json.loads(s.get_text(strip=True)))
        except Exception:
            pass

    # Apollo state / arbitrary JSON blocks
    for s in soup.find_all("script"):
        txt = s.get_text(" ", strip=True)
        if not txt:
            continue
        m = re.search(r"__APOLLO_STATE__\s*=\s*({.*?})\s*;?\s*</", str(s), re.S)
        if m:
            try:
                blobs.append(json.loads(m.group(1)))
            except Exception:
                pass
            continue
        if ("Product" in txt or "media" in txt or "description" in txt) and "{" in txt and "}" in txt:
            try:
                jtxt = _largest_curly_json(txt)
                if jtxt:
                    blobs.append(json.loads(jtxt))
            except Exception:
                pass

    # dataLayer
    for s in soup.find_all("script"):
        txt = s.get_text(" ", strip=True)
        if "dataLayer" in txt and "[" in txt and "]" in txt:
            m = re.search(r"dataLayer\s*=\s*(\[[\s\S]*?\])", txt)
            if m:
                try:
                    blobs.append(json.loads(m.group(1)))
                except Exception:
                    pass
    return blobs

def _largest_curly_json(txt: str) -> Optional[str]:
    stack = []
    best = (0, 0)
    for i, ch in enumerate(txt):
        if ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            length = i - start + 1
            if length > best[0]:
                best = (length, start)
    if best[0] > 80:
        return txt[best[1]:best[1] + best[0]]
    return None

def _from_json_try_keys(obj: Any, keys: List[str]) -> Optional[Any]:
    if isinstance(obj, dict):
        for k in keys:
            if k in obj:
                return obj[k]
        for v in obj.values():
            r = _from_json_try_keys(v, keys)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for it in obj:
            r = _from_json_try_keys(it, keys)
            if r is not None:
                return r
    return None

def _json_extract_description(blobs: List[Any]) -> Optional[str]:
    for b in blobs:
        for key in ("pageProps", "props"):
            pp = isinstance(b, dict) and b.get(key)
            if isinstance(pp, dict):
                cand = _from_json_try_keys(pp, ["description", "productOverview", "aboutThisProduct"])
                if isinstance(cand, str) and len(_clean(cand)) > 200:
                    return _clean(cand)
        cand = _from_json_try_keys(b, ["description", "longDescription", "productOverview"])
        if isinstance(cand, str) and len(_clean(cand)) > 200:
            return _clean(cand)
    return None

def _json_extract_stock(blobs: List[Any]) -> Tuple[Optional[bool], str]:
    text = json.dumps(blobs, ensure_ascii=False).lower()
    if any(kw in text for kw in ["out of stock", "unavailable", "sold out"]):
        return False, "Unavailable"
    if any(kw in text for kw in ["add to cart", "available for pickup", "ship to home"]):
        return True, "Available"
    return None, ""

# -----------------------------
# Image normalization & selection
# -----------------------------
def _pick_largest_from_srcset(srcset: str) -> Optional[str]:
    if not srcset:
        return None
    best = (0, None)
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split()
        if not bits:
            continue
        url = bits[0]
        width = 0
        if len(bits) > 1 and bits[1].endswith("w"):
            try:
                width = int(bits[1][:-1])
            except Exception:
                width = 0
        if width >= best[0]:
            best = (width, url)
    return best[1]

def _normalize_hd_image(u: str, target: int = 1000) -> str:
    """
    Normalize THD productImages URL to concrete size (1000px).
    Handles:
      - ..._100.jpg / ..._200.jpg -> ..._1000.jpg
      - ..._<SIZE>.jpg / ..._{size}.jpg -> ..._1000.jpg
      - wid/hei query params -> 1000
    Strips query for dedupe.
    """
    if not u or "images.thdstatic.com/productImages/" not in u:
        return u
    u = re.sub(r"([?&])(wid|width)=\d+", rf"\1\2={target}", u, flags=re.I)
    u = re.sub(r"([?&])(hei|height)=\d+", rf"\1\2={target}", u, flags=re.I)
    u = re.sub(r"_(\d+)(\.(?:jpg|jpeg|png|webp))(?:[?#].*)?$", rf"_{target}\2", u, flags=re.I)
    u = re.sub(r"_(?:<SIZE>|\{size\}|SZ_|SIZE_|<size>|<SIZES>|s\d+)(\.(?:jpg|jpeg|png|webp))(?:[?#].*)?$",
               rf"_{target}\1", u, flags=re.I)
    u = re.sub(r"[?#].*$", "", u)
    return u

def _stable_image_key(url: str) -> str:
    """
    Key on GUID + filename stem without trailing _{size}, ignoring query.
    """
    try:
        guid = _guid_from_thd_url(url) or ""
        fname = os.path.basename(urlparse(url).path)
        stem, _ext = os.path.splitext(fname)
        stem = re.sub(r"_(?:\d+|<SIZE>|\{size\}|SZ_|SIZE_|<size>|<SIZES>|s\d+)$", "", stem, flags=re.I)
        return (guid + ":" + stem).lower() or hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]

def _json_extract_gallery_urls(blobs: List[Any]) -> List[str]:
    urls: List[str] = []

    def _collect(v: Any):
        nonlocal urls
        if isinstance(v, dict):
            for kk in ("templateUrl", "url", "image", "src", "href"):
                if kk in v and isinstance(v[kk], str):
                    u = v[kk]
                    if "images.thdstatic.com/productImages/" in u:
                        urls.append(u)
            for kk in ("images", "media", "gallery", "mediaGallery", "mediaAssets", "items"):
                if kk in v and isinstance(v[kk], (list, dict)):
                    _collect(v[kk])
            for vv in v.values():
                _collect(vv)
        elif isinstance(v, list):
            for it in v:
                _collect(it)

    for b in blobs:
        _collect(b)

    out: List[str] = []
    seen = set()
    for u in urls:
        if "images.thdstatic.com/productImages/" not in u:
            continue
        nu = _normalize_hd_image(u, 1000)
        key = _stable_image_key(nu)
        if key in seen:
            continue
        seen.add(key)
        out.append(nu)
    return out

def _json_extract_primary_guid(blobs: List[Any]) -> Optional[str]:
    for b in blobs:
        urls = _json_extract_gallery_urls([b])
        for u in urls:
            g = _guid_from_thd_url(u)
            if g:
                return g
    return None

def _collect_images_from_json(blobs: List[Any], max_images: Optional[int], enforce_guid: Optional[str]) -> List[str]:
    raw = _json_extract_gallery_urls(blobs)
    out: List[str] = []
    seen = set()
    for u in raw:
        nu = _normalize_hd_image(u, 1000)
        if enforce_guid:
            g = _guid_from_thd_url(nu)
            if g and g != enforce_guid:
                continue
        key = _stable_image_key(nu)
        if key in seen:
            continue
        seen.add(key)
        out.append(nu)
        if max_images and len(out) >= max_images:
            break
    return out

def _collect_images_from_html(soup: BeautifulSoup, max_images: Optional[int], enforce_guid: Optional[str]) -> List[str]:
    urls: List[str] = []

    def _maybe_add(raw: Optional[str]):
        if not raw:
            return
        if "images.thdstatic.com/productImages/" not in raw:
            return
        nu = _normalize_hd_image(raw, 1000)
        if enforce_guid:
            g = _guid_from_thd_url(nu)
            if g and g != enforce_guid:
                return
        urls.append(nu)

    # Thumbnails and main gallery
    for img in soup.select("div.mediagallery__thumbnail img[src], img[data-testid='thumbnail-image'][src]"):
        _maybe_add(img.get("src"))

    # Other images in DOM (viewer/modal)
    for img in soup.select("img[src]"):
        _maybe_add(img.get("src"))

    for img in soup.select("img[srcset]"):
        best = _pick_largest_from_srcset(img.get("srcset", ""))
        if best:
            _maybe_add(best)

    # De-dupe
    seen = set()
    out: List[str] = []
    for u in urls:
        key = _stable_image_key(u)
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
        if max_images and len(out) >= max_images:
            break

    return out

# -----------------------------
# HTML extractors (fallback)
# -----------------------------
def _extract_name(soup: BeautifulSoup) -> str:
    h1 = soup.select_one("h1.sui-h4-bold.sui-line-clamp-unset.sui-font-normal.sui-text-primary")
    if h1:
        t = _clean(h1.get_text(" ", strip=True))
        if t:
            return t
    h1_any = soup.select_one("h1")
    if h1_any:
        t = _clean(h1_any.get_text(" ", strip=True))
        if t:
            return t
    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        return _clean(og["content"])
    return "Unknown Product"

def _extract_price(soup: BeautifulSoup) -> Tuple[str, str]:
    candidates = [
        "div.sui-flex.sui-flex-row.sui-leading-none",
        "[data-testid='price']",
        "div.price__numbers"
    ]
    for sel in candidates:
        wrap = soup.select_one(sel)
        if not wrap:
            continue
        parts = [el.get_text("", strip=True) for el in wrap.find_all("span")]
        digits = "".join([p for p in parts if p and p != "."])
        m = re.match(r"^\$?(\d+)(\d{2})$", digits)
        if m:
            return f"${m.group(1)}.{m.group(2)}", "onsite"
        money = _parse_money(" ".join(parts))
        if money:
            return money, "onsite"
    money = _parse_money(soup.get_text(" ", strip=True))
    if money:
        return money, "text-scan"
    return "N/A", "none"

def _extract_ids(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
    internet_no = None
    model_no = None
    try:
        info = soup.select_one('[data-testid="productInfo"]') or soup.find("div", class_="product-info-bar")
        block_text = _clean(info.get_text(" ", strip=True)) if info else _clean(soup.get_text(" ", strip=True))
        m1 = re.search(r"Internet\s*#\s*([A-Za-z0-9\-]+)", block_text, re.I)
        if m1:
            internet_no = m1.group(1)
        m2 = re.search(r"Model\s*#\s*([A-Za-z0-9\-\._]+)", block_text, re.I)
        if m2:
            model_no = m2.group(1)
    except Exception:
        pass
    return internet_no, model_no

def _about_block_candidates(soup: BeautifulSoup) -> List[Tag]:
    out: List[Tag] = []
    for h3 in soup.select("h3"):
        if _clean(h3.get_text()).lower() == "about this product":
            parent = (
                h3.find_parent(class_=re.compile(r"(sui-)?flex|sui-flex-col|sui-gap"))
                or h3.parent
            )
            if parent and isinstance(parent, Tag):
                out.append(parent)
    for sel in (
        "[data-testid='overview']",
        "[data-testid='productOverview']",
        "[data-testid='aboutThisProduct']",
        ".product-overview",
        ".overview",
    ):
        for el in soup.select(sel):
            if isinstance(el, Tag):
                out.append(el)
    seen = set()
    uniq: List[Tag] = []
    for el in out:
        key = getattr(el, "attrs", {}).get("id") or str(el)[:120]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(el)
    return uniq

def _collect_text_from_container(container: Tag) -> List[str]:
    parts: List[str] = []
    for p in container.find_all("p"):
        txt = _clean(p.get_text(" ", strip=True))
        if txt:
            parts.append(txt)
    for li in container.find_all("li"):
        txt = _clean(li.get_text(" ", strip=True))
        if txt:
            parts.append(f"• {txt}")
    for div in container.find_all("div"):
        if div.find(["p", "li"]):
            continue
        txt = _clean(div.get_text(" ", strip=True))
        if txt and txt.lower() != "about this product" and len(txt) > 60:
            parts.append(txt)
    return parts

def _extract_description_and_highlights(soup: BeautifulSoup) -> str:
    blocks = _about_block_candidates(soup)
    collected: List[str] = []
    for b in blocks:
        collected.extend(_collect_text_from_container(b))
    if not collected:
        meta = soup.select_one('meta[name="description"]')
        if meta and meta.get("content"):
            collected.append(_clean(meta["content"]))
    if not collected:
        for s in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(s.get_text(strip=True))
                objs = data if isinstance(data, list) else [data]
                for o in objs:
                    if isinstance(o, dict) and (o.get("@type") in ("Product", "WebPage")):
                        d = _clean(o.get("description") or "")
                        if d:
                            collected.append(d)
                            break
            except Exception:
                continue
    seen = set()
    out: List[str] = []
    for line in collected:
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return "\n".join(out)

def _detect_stock_html(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
    selectors = (
        "[data-component^='add-to-cart']",
        "[data-testid='add-to-cart']",
        "button[data-automation-id='add-to-cart']",
        "button#add-to-cart",
    )
    for sel in selectors:
        for el in soup.select(sel):
            btn = el if el.name == "button" else el.find("button")
            if btn:
                label = _clean(btn.get_text(" ", strip=True)).lower()
                if "add to cart" in label or "add to" in label:
                    return True, "Add to Cart available"
    body = _clean(soup.get_text(" ", strip=True)).lower()
    negatives = ("out of stock", "unavailable", "sold out")
    if any(n in body for n in negatives):
        return False, "Unavailable"
    return None, ""

# -----------------------------
# Scraper (same name & signature preserved)
# -----------------------------
def scrape_homedepot_with_oxylabs(
    url: str,
    max_images: Optional[int] = None,
    download_images: bool = True,
) -> dict:
    """
    Strategy:
      1) Fetch (light). Parse JSON/HTML.
      2) If too few images (< MIN_OK_IMAGES), refetch (aggressive) & re-parse.
      3) Prefer JSON images; enforce primary GUID only if it doesn't nuke the count.
    """
    # First pass (light)
    html = _fetch_with_oxylabs_universal(url, aggressive=False)
    soup = BeautifulSoup(html, "lxml")
    blobs = _load_json_scripts(soup)

    name = _extract_name(soup)
    price, price_source = _extract_price(soup)
    internet_no, model_no = _extract_ids(soup)
    description = _json_extract_description(blobs) or _extract_description_and_highlights(soup)

    in_stock, stock_text = _json_extract_stock(blobs)
    if in_stock is None:
        in_stock, stock_text = _detect_stock_html(soup)

    # Images — JSON first
    primary_guid = _json_extract_primary_guid(blobs)
    # only enforce GUID if it won't drop us below a useful threshold
    json_imgs_all = _collect_images_from_json(blobs, max_images, enforce_guid=None)
    json_imgs_guid = _collect_images_from_json(blobs, max_images, enforce_guid=primary_guid) if primary_guid else json_imgs_all

    image_urls = json_imgs_guid if len(json_imgs_guid) >= MIN_OK_IMAGES else json_imgs_all

    if len(image_urls) < MIN_OK_IMAGES:
        # HTML fallback with/without GUID
        html_imgs_guid = _collect_images_from_html(soup, max_images, enforce_guid=primary_guid)
        html_imgs_all = _collect_images_from_html(soup, max_images, enforce_guid=None)
        cand = html_imgs_guid if len(html_imgs_guid) >= MIN_OK_IMAGES else html_imgs_all

        # merge JSON + HTML
        merged: List[str] = []
        seen = set(_stable_image_key(u) for u in image_urls)
        merged.extend(image_urls)
        for u in cand:
            key = _stable_image_key(u)
            if key not in seen:
                merged.append(u); seen.add(key)
        image_urls = merged

    # If still too few, try a second, aggressive render and rebuild soup/blobs
    if len(image_urls) < MIN_OK_IMAGES:
        html2 = _fetch_with_oxylabs_universal(url, aggressive=True)
        soup2 = BeautifulSoup(html2, "lxml")
        blobs2 = _load_json_scripts(soup2)

        # repeat image logic on aggressive pass
        primary_guid2 = _json_extract_primary_guid(blobs2) or primary_guid
        json2_all = _collect_images_from_json(blobs2, max_images, enforce_guid=None)
        json2_guid = _collect_images_from_json(blobs2, max_images, enforce_guid=primary_guid2) if primary_guid2 else json2_all
        pick2 = json2_guid if len(json2_guid) >= MIN_OK_IMAGES else json2_all

        html2_guid = _collect_images_from_html(soup2, max_images, enforce_guid=primary_guid2)
        html2_all = _collect_images_from_html(soup2, max_images, enforce_guid=None)
        cand2 = html2_guid if len(html2_guid) >= MIN_OK_IMAGES else html2_all

        merged2: List[str] = []
        seen2 = set(_stable_image_key(u) for u in image_urls)
        merged2.extend(image_urls)
        for u in pick2 + cand2:
            key = _stable_image_key(u)
            if key not in seen2:
                merged2.append(u); seen2.add(key)
        image_urls = merged2

    # --------- Folder & downloads ---------
    slug = _slug_from_host(url)
    stable_id = internet_no or model_no or _stable_id_from_url(url)
    unique = _unique_suffix()
    folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}_{unique}"
    _ensure_dir(folder)

    saved: List[str] = []
    if download_images:
        for i, img_url in enumerate(image_urls, start=1):
            ext = ".jpg"
            m = re.search(r"\.(jpg|jpeg|png|webp|gif)(?:$|\?)", img_url, re.I)
            if m:
                ext = "." + m.group(1).lower()
            fname = f"{i:02d}_{_safe_name(_stable_image_key(img_url))}{ext}"
            try:
                r = _SESSION.get(
                    img_url,
                    headers={"User-Agent": UA, "Referer": "https://www.homedepot.com/"},
                    timeout=20
                )
                if r.ok and r.content:
                    (folder / fname).write_bytes(r.content)
                    saved.append(str(folder / fname))
            except Exception:
                continue

    return {
        "url": url,
        "name": name,
        "price": price,
        "price_source": price_source if price != "N/A" else "none",
        "in_stock": in_stock,
        "stock_text": stock_text,
        "internet_no": internet_no,
        "model_no": model_no,
        "description": description,
        "image_count": len(saved) if download_images else len(image_urls),
        "image_urls": image_urls,
        "images_downloaded": saved,
        "folder": str(folder),
        "fetched_via": "oxylabs-universal",
    }

# # -----------------------------
# # CLI (unchanged)
# # -----------------------------
# if __name__ == "__main__":
#     TEST_URL = "https://www.homedepot.com/p/Laura-Ashley-VQ-7-Cup-China-Rose-Cordless-Dome-Electric-Kettle-with-Thermometer-VQSBPKK336LACR/331358936"
#     data = scrape_homedepot_with_oxylabs(TEST_URL, max_images=None, download_images=True)
#     print(json.dumps(data, indent=2, ensure_ascii=False))



