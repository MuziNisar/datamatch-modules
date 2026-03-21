
# wayfair.py
# Python 3.10+
# Oxylabs Web Scraper API (universal) -> HTML -> BeautifulSoup parsing
#
# pip install requests beautifulsoup4 lxml pillow

# from __future__ import annotations
# 
# import os
# import re
# import io
# import json
# import hashlib
# from pathlib import Path
# from typing import Optional, Tuple, List, Dict, Any
# from urllib.parse import urlsplit
# 
# import requests
# from bs4 import BeautifulSoup
# from PIL import Image
# 
# # ========= Secrets =========
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS  # type: ignore
# except Exception:
#     OXY_USER = os.getenv("OXYLABS_USERNAME", "")
#     OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")
# if not OXY_USER or not OXY_PASS:
#     raise RuntimeError("Set Oxylabs creds via oxylabs_secrets.py or env vars OXYLABS_USERNAME/PASSWORD.")
# 
# # ========= Config / Paths =========
# OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"
# REQUEST_TIMEOUT = 90
# UA_STR = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#     "AppleWebKit/537.36 (KHTML, like Gecko) "
#     "Chrome/127.0.0.0 Safari/537.36"
# )
# GEO_LOCATION = "United States"
# 
# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()
# SAVE_DIR = BASE_DIR / "data1"
# SAVE_DIR.mkdir(parents=True, exist_ok=True)
# 
# # ========= Helpers =========
# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "").strip())
# 
# def _safe_name(s: str) -> str:
#     n = re.sub(r"[^\w\s-]", "", (s or "")).strip().replace(" ", "_")
#     return n or "NA"
# 
# def _stable_id_from_url(url: str) -> str:
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
# 
# def _wf_to_hires(u: str, size: int = 1600) -> str:
#     """
#     Normalize Wayfair CDN URLs to higher-res:
#       https://assets.wfcdn.com/im/<hash>/resize-h48-w48%5Ecompr-r65/.../file.jpg
#       -> resize-h{size}-w{size}%5Ecompr-r85
#     Supports encoded ^ (%5E) and literal ^.
#     """
#     if not u:
#         return u
#     u = u.replace(" ", "%20")
#     u = re.sub(r"/resize-h\d+-w\d+%5Ecompr-r\d+/", f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
#     u = re.sub(r"/resize-h\d+-w\d+\^compr-r\d+/",  f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
#     if "/resize-" not in u:
#         u = re.sub(r"(https://assets\.wfcdn\.com/im/[^/]+/)",
#                    rf"\1resize-h{size}-w{size}%5Ecompr-r85/", u)
#     return u
# 
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
# 
# # ========= Very strict gallery pickers =========
# def _extract_gallery_images_strict(soup: BeautifulSoup, *, max_images: Optional[int] = None) -> List[str]:
#     """
#     Only collect images from Wayfair's official PDP gallery:
#       - Thumbnails container: [data-test-id='pdp-mt-thumbnails'] (ordered by aria-label "1 of N")
#       - Main carousel: #MediaTrayCarouselWithThumbnailSidebar, [data-test-id='pdp-mt-d-mainImageCarousel']
#     Ignore everything else (badges, icons, lifestyle blocks outside gallery).
#     """
#     candidates: List[Tuple[int, str]] = []
# 
#     # 1) Ordered thumbnails ("... 1 of N")
#     for btn in soup.select("[data-test-id='pdp-mt-thumbnails'] button[aria-label]"):
#         lab = btn.get("aria-label") or ""
#         m = re.search(r"(\d+)\s+of\s+\d+", lab, re.I)
#         order = int(m.group(1)) if m else 9999
#         img = btn.find("img")
#         src = ""
#         if img:
#             # Prefer currentSrc/srcset last entry (highest DPR)
#             srcset = (img.get("srcset") or "").split(",")
#             if srcset:
#                 last = srcset[-1].strip().split(" ")[0]
#                 src = last or ""
#             if not src:
#                 src = img.get("src") or img.get("data-src") or ""
#         if src:
#             candidates.append((order, src))
# 
#     # 2) Main carousel images (set a larger order to come after thumbs if duplicates)
#     for img in soup.select("#MediaTrayCarouselWithThumbnailSidebar img, [data-test-id='pdp-mt-d-mainImageCarousel'] img"):
#         src = ""
#         srcset = (img.get("srcset") or "").split(",")
#         if srcset:
#             src = srcset[-1].strip().split(" ")[0]
#         if not src:
#             src = img.get("src") or img.get("data-src") or ""
#         if src:
#             candidates.append((5000, src))
# 
#     # Sort by order
#     candidates.sort(key=lambda x: x[0])
# 
#     # 3) Filter: only Wayfair CDN gallery images
#     # - must be assets.wfcdn.com
#     # - must be under /im/ path (Wayfair image CDN)
#     # - exclude obvious non-gallery assets by keyword
#     EXCLUDE_PAT = re.compile(r"(sprite|badge|icon|logo|swatch|color-swatch|video|360|manual|instructions)", re.I)
# 
#     def _accept(u: str) -> bool:
#         if not u:
#             return False
#         if "assets.wfcdn.com" not in u:
#             return False
#         if "/im/" not in u:  # restrict to CDN image path
#             return False
#         if EXCLUDE_PAT.search(u):
#             return False
#         # ignore tiny thumbs with explicit small sizes (h<=120 or w<=120)
#         if re.search(r"resize-h(\d+)-w(\d+)", u):
#             m = re.search(r"resize-h(\d+)-w(\d+)", u)
#             if m:
#                 h = int(m.group(1)); w = int(m.group(2))
#                 if h <= 120 or w <= 120:
#                     return False
#         return True
# 
#     # 4) Normalize to hi-res, dedupe by URL-key (ignoring resize & query)
#     def _url_key(u: str) -> str:
#         u = re.sub(r"/resize-h\d+-w\d+(?:%5E|\^)compr-r\d+/", "/", u)
#         u = re.sub(r"[?].*$", "", u)
#         return u
# 
#     seen = set()
#     out: List[str] = []
#     for _, src in candidates:
#         if not _accept(src):
#             continue
#         hi = _wf_to_hires(src, size=1600)
#         key = _url_key(hi)
#         if key in seen:
#             continue
#         seen.add(key)
#         out.append(hi)
#         if max_images and len(out) >= max_images:
#             break
# 
#     return out
# 
# # ========= Perceptual-hash dedupe =========
# def _ahash(img: Image.Image, hash_size: int = 8) -> int:
#     im = img.convert("L").resize((hash_size, hash_size), Image.BILINEAR)
#     pixels = list(im.getdata())
#     avg = sum(pixels) / len(pixels)
#     bits = 0
#     for p in pixels:
#         bits = (bits << 1) | (1 if p >= avg else 0)
#     return bits
# 
# def _hamming(a: int, b: int) -> int:
#     x = a ^ b
#     return x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1")
# 
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
# 
#         is_dup = False
#         for prev_h in hashes:
#             if _hamming(h, prev_h) <= max_hamming:
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
# 
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
# 
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
# 
# # ========= Public API (images-first, strict) =========
# def scrape_wayfair_USA_product(url: str) -> Dict[str, Any]:
#     """
#     Fetch via Oxylabs (universal), parse with BS4, extract ONLY gallery images,
#     download, phash-dedupe, cap to 12, and return dict.
#     (We still parse name/price/stock/description in case you want it later.)
#     """
#     html = _post_oxylabs_universal(url)
#     soup = BeautifulSoup(html, "lxml")
# 
#     # Quick block detection
#     page_txt = _clean(soup.get_text(" ", strip=True)).lower()
#     is_blocked = bool(re.search(r"(access denied|verify you are human|blocked|captcha)", page_txt))
# 
#     # --- Parse minimal fields (optional) ---
#     name = _clean((soup.select_one("h1[data-rtl-id='listingHeaderNameHeading']") or soup.select_one("h1") or {}).get_text(" ", strip=True) if soup.select_one("h1[data-rtl-id='listingHeaderNameHeading']") or soup.select_one("h1") else "") or "N/A"
#     price_node = soup.select_one("[data-test-id='PriceDisplay']")
#     price = _clean(price_node.get_text(" ", strip=True)) if price_node else "N/A"
# 
#     # Stock: prefer explicit Out-of-Stock badge if present
#     in_stock = None
#     stock_text = ""
#     badge = soup.select_one("[data-test-id='InventoryWidgetDisplay-Text']")
#     if badge and "out of stock" in _clean(badge.get_text(" ", strip=True)).lower():
#         in_stock, stock_text = False, "Out of Stock badge"
#     else:
#         # Only positive if Add to Cart button is present and not disabled
#         html_l = soup.decode().lower()
#         if re.search(r">\s*add to cart\s*<", html_l) or re.search(r'aria-label="\s*add to cart\s*"', html_l):
#             # make sure it's not disabled
#             atc = soup.select_one("button[data-testing-id='atc-button'], form[name='AddItem'] button[type='submit']")
#             if atc:
#                 disabled_attr = (atc.get("disabled") or "").lower()
#                 aria_disabled = (atc.get("aria-disabled") or "").lower()
#                 cls = atc.get("class") or []
#                 cls_str = " ".join(cls) if isinstance(cls, list) else str(cls)
#                 if disabled_attr == "true" or aria_disabled == "true" or re.search(r"\bdisabled\b", cls_str, re.I):
#                     in_stock, stock_text = False, "Add to Cart disabled"
#                 else:
#                     in_stock, stock_text = True, "Add to Cart present"
# 
#     # Description (optional, minimal)
#     description = "N/A"
#     for box in soup.select('[data-hb-id="BoxV3"]'):
#         style = (box.get("style") or "").lower()
#         if "pre-line" in style:
#             txt = box.get_text("\n", strip=True)
#             txt = re.sub(r"\n{3,}", "\n\n", (txt or ""))
#             txt = _clean(txt)
#             if len(txt) > 120:
#                 description = txt
#                 break
# 
#     # --- Strict gallery images only ---
#     images = _extract_gallery_images_strict(soup, max_images=None)
# 
#     # Save folder & raw HTML
#     stable_id = _stable_id_from_url(url)
#     folder = SAVE_DIR / f"wayfair_{_safe_name(name)}_{stable_id}"
#     folder.mkdir(parents=True, exist_ok=True)
#     try:
#         (folder / "raw_html.html").write_text(html, encoding="utf-8")
#     except Exception:
#         pass
# 
#     # Download + pHash-dedupe
#     downloaded = _download_images(images, folder, convert_to_jpg=True, referer=url)
#     deduped = _dedupe_downloaded_by_phash(downloaded, max_hamming=4)
# 
#     # Cap to a sane maximum (Wayfair typically shows ~7–12 gallery images)
#     MAX_KEEP = 12
#     deduped = deduped[:MAX_KEEP]
# 
#     out = {
#         "url": urlsplit(url)._replace(query="").geturl(),
#         "name": name,
#         "price": price,
#         "in_stock": in_stock,
#         "stock_text": stock_text,
#         "description": description,
#         "image_count": len(deduped),
#         "images": deduped,
#         "folder": str(folder),
#         "fetched_via": "oxylabs-universal" + ("(block?)" if is_blocked else ""),
#     }
#     try:
#         (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
#     except Exception:
#         pass
#     return out
# 
# # ========= Hardcoded run =========
# if __name__ == "__main__":
#     # Hardcoded URL; single-arg call only
#     u = "https://www.wayfair.com/kitchen-tabletop/pdp/laura-ashley-vq-laura-ashley-35l-slow-cooker-kbfc2707.html?piid=108469953"
#     data = scrape_wayfair_USA_product(u)
#     print(json.dumps(data, indent=2, ensure_ascii=False))
# 
# 
# 
# 


# from __future__ import annotations
# 
# import os
# import re
# import io
# import json
# import hashlib
# from pathlib import Path
# from typing import Optional, Tuple, List, Dict, Any
# from urllib.parse import urlsplit
# 
# import requests
# from bs4 import BeautifulSoup
# from PIL import Image
# 
# # ========= Secrets =========
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS  # type: ignore
# except Exception:
#     OXY_USER = os.getenv("OXYLABS_USERNAME", "")
#     OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")
# if not OXY_USER or not OXY_PASS:
#     raise RuntimeError("Set Oxylabs creds via oxylabs_secrets.py or env vars OXYLABS_USERNAME/PASSWORD.")
# 
# # ========= Config / Paths =========
# OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"
# REQUEST_TIMEOUT = 90
# UA_STR = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#     "AppleWebKit/537.36 (KHTML, like Gecko) "
#     "Chrome/127.0.0.0 Safari/537.36"
# )
# GEO_LOCATION = "United States"
# 
# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()
# SAVE_DIR = BASE_DIR / "data1"
# SAVE_DIR.mkdir(parents=True, exist_ok=True)
# 
# # ========= Helpers =========
# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "").strip())
# 
# def _safe_name(s: str) -> str:
#     n = re.sub(r"[^\w\s-]", "", (s or "")).strip().replace(" ", "_")
#     return n or "NA"
# 
# def _stable_id_from_url(url: str) -> str:
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
# 
# def _wf_to_hires(u: str, size: int = 1600) -> str:
#     """
#     Normalize Wayfair CDN URLs to higher-res:
#       https://assets.wfcdn.com/im/<hash>/resize-h48-w48%5Ecompr-r65/.../file.jpg
#       -> resize-h{size}-w{size}%5Ecompr-r85
#     Supports encoded ^ (%5E) and literal ^.
#     """
#     if not u:
#         return u
#     u = u.replace(" ", "%20")
#     u = re.sub(r"/resize-h\d+-w\d+%5Ecompr-r\d+/", f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
#     u = re.sub(r"/resize-h\d+-w\d+\^compr-r\d+/",  f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
#     if "/resize-" not in u:
#         u = re.sub(r"(https://assets\.wfcdn\.com/im/[^/]+/)",
#                    rf"\1resize-h{size}-w{size}%5Ecompr-r85/", u)
#     return u
# 
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
# 
# # ========= Very strict gallery pickers =========
# def _extract_gallery_images_strict(soup: BeautifulSoup, *, max_images: Optional[int] = None) -> List[str]:
#     """
#     Only collect images from Wayfair's official PDP gallery:
#       - Main grid: #pdp-mt-grid (primary product images)
#       - Thumbnails: [data-test-id='pdp-mt-thumbnails'] (ordered by aria-label "1 of N")
#     Ignore everything else (badges, icons, lifestyle blocks outside gallery).
#     """
#     candidates: List[Tuple[int, str]] = []
# 
#     # 1) Ordered thumbnails ("... 1 of N") — upgrade before filtering so size check works
#     for btn in soup.select("[data-test-id='pdp-mt-thumbnails'] button[aria-label]"):
#         lab = btn.get("aria-label") or ""
#         m = re.search(r"(\d+)\s+of\s+\d+", lab, re.I)
#         order = int(m.group(1)) if m else 9999
#         img = btn.find("img")
#         src = ""
#         if img:
#             # Prefer highest resolution from srcset
#             srcset = (img.get("srcset") or "").split(",")
#             if srcset:
#                 last = srcset[-1].strip().split(" ")[0]
#                 src = last or ""
#             if not src:
#                 src = img.get("src") or img.get("data-src") or ""
#         if src:
#             # Upgrade to hi-res BEFORE filtering so size check sees 1600px not 48/96px
#             hi = _wf_to_hires(src, size=1600)
#             candidates.append((order, hi))
# 
#     # 2) Main grid images (#pdp-mt-grid) — primary product photos
#     for img in soup.select("#pdp-mt-grid img"):
#         src = ""
#         srcset = (img.get("srcset") or "").split(",")
#         if srcset:
#             src = srcset[-1].strip().split(" ")[0]
#         if not src:
#             src = img.get("src") or img.get("data-src") or ""
#         if src:
#             hi = _wf_to_hires(src, size=1600)
#             candidates.append((100, hi))  # after thumbnail order
# 
#     # 3) Fallback: MediaTray container (catches older page layouts)
#     if not candidates:
#         for img in soup.select("[data-name='MediaTray'] img, #MediaTrayCarouselWithThumbnailSidebar img, [data-test-id='pdp-mt-d-mainImageCarousel'] img"):
#             src = ""
#             srcset = (img.get("srcset") or "").split(",")
#             if srcset:
#                 src = srcset[-1].strip().split(" ")[0]
#             if not src:
#                 src = img.get("src") or img.get("data-src") or ""
#             if src:
#                 hi = _wf_to_hires(src, size=1600)
#                 candidates.append((5000, hi))
# 
#     # Sort by order
#     candidates.sort(key=lambda x: x[0])
# 
#     # 4) Filter: only Wayfair CDN gallery images (size check removed — already upgraded)
#     EXCLUDE_PAT = re.compile(r"(sprite|badge|icon|logo|swatch|color-swatch|video|360|manual|instructions)", re.I)
# 
#     def _accept(u: str) -> bool:
#         if not u:
#             return False
#         if "assets.wfcdn.com" not in u:
#             return False
#         if "/im/" not in u:
#             return False
#         if EXCLUDE_PAT.search(u):
#             return False
#         return True
# 
#     # 5) Normalize, dedupe by URL-key (ignoring resize & query)
#     def _url_key(u: str) -> str:
#         u = re.sub(r"/resize-h\d+-w\d+(?:%5E|\^)compr-r\d+/", "/", u)
#         u = re.sub(r"[?].*$", "", u)
#         return u
# 
#     seen = set()
#     out: List[str] = []
#     for _, src in candidates:
#         if not _accept(src):
#             continue
#         key = _url_key(src)
#         if key in seen:
#             continue
#         seen.add(key)
#         out.append(src)
#         if max_images and len(out) >= max_images:
#             break
# 
#     return out
# 
# 
# # ========= Perceptual-hash dedupe =========
# def _ahash(img: Image.Image, hash_size: int = 8) -> int:
#     im = img.convert("L").resize((hash_size, hash_size), Image.BILINEAR)
#     pixels = list(im.getdata())
#     avg = sum(pixels) / len(pixels)
#     bits = 0
#     for p in pixels:
#         bits = (bits << 1) | (1 if p >= avg else 0)
#     return bits
# 
# def _hamming(a: int, b: int) -> int:
#     x = a ^ b
#     return x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1")
# 
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
# 
#         is_dup = False
#         for prev_h in hashes:
#             if _hamming(h, prev_h) <= max_hamming:
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
# 
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
# 
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
# 
# # ========= Public API (images-first, strict) =========
# def scrape_wayfair_USA_product(url: str) -> Dict[str, Any]:
#     """
#     Fetch via Oxylabs (universal), parse with BS4, extract ONLY gallery images,
#     download, phash-dedupe, cap to 12, and return dict.
#     (We still parse name/price/stock/description in case you want it later.)
#     """
#     html = _post_oxylabs_universal(url)
#     soup = BeautifulSoup(html, "lxml")
# 
#     # Quick block detection
#     page_txt = _clean(soup.get_text(" ", strip=True)).lower()
#     is_blocked = bool(re.search(r"(access denied|verify you are human|blocked|captcha)", page_txt))
# 
#     # --- Parse minimal fields (optional) ---
#     name = _clean((soup.select_one("h1[data-rtl-id='listingHeaderNameHeading']") or soup.select_one("h1") or {}).get_text(" ", strip=True) if soup.select_one("h1[data-rtl-id='listingHeaderNameHeading']") or soup.select_one("h1") else "") or "N/A"
#     price_node = soup.select_one("[data-test-id='PriceDisplay']")
#     price = _clean(price_node.get_text(" ", strip=True)) if price_node else "N/A"
# 
#     # Stock: prefer explicit Out-of-Stock badge if present
#     in_stock = None
#     stock_text = ""
#     badge = soup.select_one("[data-test-id='InventoryWidgetDisplay-Text']")
#     if badge and "out of stock" in _clean(badge.get_text(" ", strip=True)).lower():
#         in_stock, stock_text = False, "Out of Stock badge"
#     else:
#         # Only positive if Add to Cart button is present and not disabled
#         html_l = soup.decode().lower()
#         if re.search(r">\s*add to cart\s*<", html_l) or re.search(r'aria-label="\s*add to cart\s*"', html_l):
#             # make sure it's not disabled
#             atc = soup.select_one("button[data-testing-id='atc-button'], form[name='AddItem'] button[type='submit']")
#             if atc:
#                 disabled_attr = (atc.get("disabled") or "").lower()
#                 aria_disabled = (atc.get("aria-disabled") or "").lower()
#                 cls = atc.get("class") or []
#                 cls_str = " ".join(cls) if isinstance(cls, list) else str(cls)
#                 if disabled_attr == "true" or aria_disabled == "true" or re.search(r"\bdisabled\b", cls_str, re.I):
#                     in_stock, stock_text = False, "Add to Cart disabled"
#                 else:
#                     in_stock, stock_text = True, "Add to Cart present"
# 
#     # Description (optional, minimal)
#     description = "N/A"
#     for box in soup.select('[data-hb-id="BoxV3"]'):
#         style = (box.get("style") or "").lower()
#         if "pre-line" in style:
#             txt = box.get_text("\n", strip=True)
#             txt = re.sub(r"\n{3,}", "\n\n", (txt or ""))
#             txt = _clean(txt)
#             if len(txt) > 120:
#                 description = txt
#                 break
# 
#     # --- Strict gallery images only ---
#     images = _extract_gallery_images_strict(soup, max_images=None)
# 
#     # Save folder & raw HTML
#     stable_id = _stable_id_from_url(url)
#     folder = SAVE_DIR / f"wayfair_{_safe_name(name)}_{stable_id}"
#     folder.mkdir(parents=True, exist_ok=True)
#     try:
#         (folder / "raw_html.html").write_text(html, encoding="utf-8")
#     except Exception:
#         pass
# 
#     # Download + pHash-dedupe
#     downloaded = _download_images(images, folder, convert_to_jpg=True, referer=url)
#     deduped = _dedupe_downloaded_by_phash(downloaded, max_hamming=4)
# 
#     # Cap to a sane maximum (Wayfair typically shows ~7–12 gallery images)
#     MAX_KEEP = 12
#     deduped = deduped[:MAX_KEEP]
# 
#     out = {
#         "url": urlsplit(url)._replace(query="").geturl(),
#         "name": name,
#         "price": price,
#         "in_stock": in_stock,
#         "stock_text": stock_text,
#         "description": description,
#         "image_count": len(deduped),
#         "images": deduped,
#         "folder": str(folder),
#         "fetched_via": "oxylabs-universal" + ("(block?)" if is_blocked else ""),
#     }
#     try:
#         (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
#     except Exception:
#         pass
#     return out
# 
# # ========= Hardcoded run =========
# if __name__ == "__main__":
#     # Hardcoded URL; single-arg call only
#     u = "https://www.wayfair.com/kitchen-tabletop/pdp/laura-ashley-vq-laura-ashley-35l-slow-cooker-kbfc2707.html?piid=108469953"
#     data = scrape_wayfair_USA_product(u)
#     print(json.dumps(data, indent=2, ensure_ascii=False))
# 
# 
# 
# 


from __future__ import annotations

import os
import re
import io
import json
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from urllib.parse import urlsplit

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
SAVE_DIR = BASE_DIR / "data1"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

# ========= Helpers =========
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _safe_name(s: str) -> str:
    n = re.sub(r"[^\w\s-]", "", (s or "")).strip().replace(" ", "_")
    return n or "NA"

def _stable_id_from_url(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

def _wf_to_hires(u: str, size: int = 1600) -> str:
    """
    Normalize Wayfair CDN URLs to higher-res:
      https://assets.wfcdn.com/im/<hash>/resize-h48-w48%5Ecompr-r65/.../file.jpg
      -> resize-h{size}-w{size}%5Ecompr-r85
    Supports encoded ^ (%5E) and literal ^.
    """
    if not u:
        return u
    u = u.replace(" ", "%20")
    u = re.sub(r"/resize-h\d+-w\d+%5Ecompr-r\d+/", f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
    u = re.sub(r"/resize-h\d+-w\d+\^compr-r\d+/",  f"/resize-h{size}-w{size}%5Ecompr-r85/", u)
    if "/resize-" not in u:
        u = re.sub(r"(https://assets\.wfcdn\.com/im/[^/]+/)",
                   rf"\1resize-h{size}-w{size}%5Ecompr-r85/", u)
    return u

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

# ========= Very strict gallery pickers =========
# --- VERSION 3 (BACKUP — button images excluded as fallback-only; caused image_count: 1 because
#     #pdp-mt-grid only renders 1 main display image; other 2 only exist inside button thumbnails) ---
# def _extract_gallery_images_strict(soup: BeautifulSoup, *, max_images: Optional[int] = None) -> List[str]:
#     candidates: List[Tuple[int, str]] = []
#     for i, img in enumerate(soup.select("#pdp-mt-grid img")):
#         if img.find_parent("button"):
#             continue
#         src = ""
#         srcset = (img.get("srcset") or "").split(",")
#         if srcset:
#             src = srcset[-1].strip().split(" ")[0]
#         if not src:
#             src = img.get("src") or img.get("data-src") or ""
#         if src:
#             hi = _wf_to_hires(src, size=1600)
#             candidates.append((i, hi))
#     if not candidates:
#         for btn in soup.select("[data-test-id='pdp-mt-thumbnails'] button[aria-label]"):
#             lab = btn.get("aria-label") or ""
#             m = re.search(r"(\d+)\s+of\s+\d+", lab, re.I)
#             order = int(m.group(1)) if m else 9999
#             img = btn.find("img")
#             src = ""
#             if img:
#                 srcset = (img.get("srcset") or "").split(",")
#                 if srcset:
#                     last = srcset[-1].strip().split(" ")[0]
#                     src = last or ""
#                 if not src:
#                     src = img.get("src") or img.get("data-src") or ""
#             if src:
#                 hi = _wf_to_hires(src, size=1600)
#                 candidates.append((order, hi))
#     if not candidates:
#         for img in soup.select("[data-name='MediaTray'] img, #MediaTrayCarouselWithThumbnailSidebar img, [data-test-id='pdp-mt-d-mainImageCarousel'] img"):
#             if img.find_parent("button"):
#                 continue
#             src = ""
#             srcset = (img.get("srcset") or "").split(",")
#             if srcset:
#                 src = srcset[-1].strip().split(" ")[0]
#             if not src:
#                 src = img.get("src") or img.get("data-src") or ""
#             if src:
#                 hi = _wf_to_hires(src, size=1600)
#                 candidates.append((5000, hi))
#     candidates.sort(key=lambda x: x[0])
#     EXCLUDE_PAT = re.compile(r"(sprite|badge|icon|logo|swatch|color-swatch|video|360|manual|instructions)", re.I)
#     def _accept(u):
#         if not u: return False
#         if "assets.wfcdn.com" not in u: return False
#         if "/im/" not in u: return False
#         if EXCLUDE_PAT.search(u): return False
#         return True
#     def _url_key(u):
#         u = re.sub(r"/resize-h\d+-w\d+(?:%5E|\^)compr-r\d+/", "/", u)
#         u = re.sub(r"[?].*$", "", u)
#         return u
#     seen = set(); out = []
#     for _, src in candidates:
#         if not _accept(src): continue
#         key = _url_key(src)
#         if key in seen: continue
#         seen.add(key); out.append(src)
#         if max_images and len(out) >= max_images: break
#     return out

# --- VERSION 4 (ACTIVE) ---
# Root cause of image_count:1: #pdp-mt-grid only has 1 non-button <img> at render time
# (the active/focused image). The other 2 gallery images only exist as <img> inside
# thumbnail <button> elements (aria-label="Open full product image... N of 3").
# Fix: always collect ALL thumbnail buttons from #pdp-mt-grid (not fallback-only),
# combine with the main display image, then URL-key dedup removes any overlap.
def _extract_gallery_images_strict(soup: BeautifulSoup, *, max_images: Optional[int] = None) -> List[str]:
    """
    Collect all Wayfair PDP gallery images:
      1) Non-button imgs from #pdp-mt-grid (currently active display image)
      2) Button thumbnails from #pdp-mt-grid (carry all N gallery image hashes) — always collected
      3) Fallback: MediaTray container for older page layouts
    URL-key dedup (ignoring resize params) merges any overlaps.
    """
    candidates: List[Tuple[int, str]] = []

    def _img_src(img) -> str:
        src = ""
        srcset = (img.get("srcset") or "").split(",")
        if srcset:
            src = srcset[-1].strip().split(" ")[0]
        if not src:
            src = img.get("src") or img.get("data-src") or ""
        return src

    # 1) Non-button main display image(s) from #pdp-mt-grid
    for i, img in enumerate(soup.select("#pdp-mt-grid img")):
        if img.find_parent("button"):
            continue
        src = _img_src(img)
        if src:
            candidates.append((i, _wf_to_hires(src, size=1600)))

    # 2) Thumbnail buttons inside #pdp-mt-grid — always collect as insurance.
    #    Each thumbnail is the SAME photo as a display image but lower CDN resolution (48w/96w).
    #    Order 100+ ensures they always sort AFTER display images (order 0,1,2).
    #    phash dedup then keeps the display version and discards the thumbnail duplicate.
    #    If NO display images were found (lazy loading miss), thumbnails survive and we still get N images.
    for btn in soup.select("#pdp-mt-grid button[aria-label]"):
        lab = btn.get("aria-label") or ""
        m = re.search(r"(\d+)\s+of\s+\d+", lab, re.I)
        order = 100 + (int(m.group(1)) if m else 99)  # 100+ keeps thumbnails after display images
        img = btn.find("img")
        if img:
            src = _img_src(img)
            if src:
                candidates.append((order, _wf_to_hires(src, size=1600)))

    # Also try the dedicated thumbnail container (some page variants)
    for btn in soup.select("[data-test-id='pdp-mt-thumbnails'] button[aria-label]"):
        lab = btn.get("aria-label") or ""
        m = re.search(r"(\d+)\s+of\s+\d+", lab, re.I)
        order = 100 + (int(m.group(1)) if m else 99)
        img = btn.find("img")
        if img:
            src = _img_src(img)
            if src:
                candidates.append((order, _wf_to_hires(src, size=1600)))

    # 3) Fallback: MediaTray / older page layouts
    if not candidates:
        for img in soup.select("[data-name='MediaTray'] img, #MediaTrayCarouselWithThumbnailSidebar img, [data-test-id='pdp-mt-d-mainImageCarousel'] img"):
            if img.find_parent("button"):
                continue
            src = _img_src(img)
            if src:
                candidates.append((5000, _wf_to_hires(src, size=1600)))

    # Sort by gallery order
    candidates.sort(key=lambda x: x[0])

    # Filter: only Wayfair CDN gallery images
    EXCLUDE_PAT = re.compile(r"(sprite|badge|icon|logo|swatch|color-swatch|video|360|manual|instructions)", re.I)

    def _accept(u: str) -> bool:
        if not u:
            return False
        if "assets.wfcdn.com" not in u:
            return False
        if "/im/" not in u:
            return False
        if EXCLUDE_PAT.search(u):
            return False
        return True

    # Dedupe by URL-key (strips resize params so same image at different sizes → same key)
    def _url_key(u: str) -> str:
        u = re.sub(r"/resize-h\d+-w\d+(?:%5E|\^)compr-r\d+/", "/", u)
        u = re.sub(r"[?].*$", "", u)
        return u

    seen: set = set()
    out: List[str] = []
    for _, src in candidates:
        if not _accept(src):
            continue
        key = _url_key(src)
        if key in seen:
            continue
        seen.add(key)
        out.append(src)
        if max_images and len(out) >= max_images:
            break

    return out


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
        for prev_h in hashes:
            if _hamming(h, prev_h) <= max_hamming:
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

# ========= Public API (images-first, strict) =========
def scrape_wayfair_USA_product(url: str) -> Dict[str, Any]:
    """
    Fetch via Oxylabs (universal), parse with BS4, extract ONLY gallery images,
    download, phash-dedupe, cap to 12, and return dict.
    (We still parse name/price/stock/description in case you want it later.)
    """
    html = _post_oxylabs_universal(url)
    soup = BeautifulSoup(html, "lxml")

    # Quick block detection
    page_txt = _clean(soup.get_text(" ", strip=True)).lower()
    is_blocked = bool(re.search(r"(access denied|verify you are human|blocked|captcha)", page_txt))

    # --- Parse minimal fields (optional) ---
    name = _clean((soup.select_one("h1[data-rtl-id='listingHeaderNameHeading']") or soup.select_one("h1") or {}).get_text(" ", strip=True) if soup.select_one("h1[data-rtl-id='listingHeaderNameHeading']") or soup.select_one("h1") else "") or "N/A"
    price_node = soup.select_one("[data-test-id='PriceDisplay']")
    price = _clean(price_node.get_text(" ", strip=True)) if price_node else "N/A"

    # Stock: prefer explicit Out-of-Stock badge if present
    in_stock = None
    stock_text = ""
    badge = soup.select_one("[data-test-id='InventoryWidgetDisplay-Text']")
    if badge and "out of stock" in _clean(badge.get_text(" ", strip=True)).lower():
        in_stock, stock_text = False, "Out of Stock badge"
    else:
        # Only positive if Add to Cart button is present and not disabled
        html_l = soup.decode().lower()
        if re.search(r">\s*add to cart\s*<", html_l) or re.search(r'aria-label="\s*add to cart\s*"', html_l):
            # make sure it's not disabled
            atc = soup.select_one("button[data-testing-id='atc-button'], form[name='AddItem'] button[type='submit']")
            if atc:
                disabled_attr = (atc.get("disabled") or "").lower()
                aria_disabled = (atc.get("aria-disabled") or "").lower()
                cls = atc.get("class") or []
                cls_str = " ".join(cls) if isinstance(cls, list) else str(cls)
                if disabled_attr == "true" or aria_disabled == "true" or re.search(r"\bdisabled\b", cls_str, re.I):
                    in_stock, stock_text = False, "Add to Cart disabled"
                else:
                    in_stock, stock_text = True, "Add to Cart present"

    # Description (optional, minimal)
    description = "N/A"
    for box in soup.select('[data-hb-id="BoxV3"]'):
        style = (box.get("style") or "").lower()
        if "pre-line" in style:
            txt = box.get_text("\n", strip=True)
            txt = re.sub(r"\n{3,}", "\n\n", (txt or ""))
            txt = _clean(txt)
            if len(txt) > 120:
                description = txt
                break

    # --- Strict gallery images only ---
    images = _extract_gallery_images_strict(soup, max_images=None)

    # Save folder & raw HTML
    stable_id = _stable_id_from_url(url)
    folder = SAVE_DIR / f"wayfair_{_safe_name(name)}_{stable_id}"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        (folder / "raw_html.html").write_text(html, encoding="utf-8")
    except Exception:
        pass

    # Download + pHash-dedupe
    downloaded = _download_images(images, folder, convert_to_jpg=True, referer=url)
    deduped = _dedupe_downloaded_by_phash(downloaded, max_hamming=4)

    # Cap to a sane maximum (Wayfair typically shows ~7–12 gallery images)
    MAX_KEEP = 12
    deduped = deduped[:MAX_KEEP]

    out = {
        "url": urlsplit(url)._replace(query="").geturl(),
        "name": name,
        "price": price,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_count": len(deduped),
        "images": deduped,
        "folder": str(folder),
        "fetched_via": "oxylabs-universal" + ("(block?)" if is_blocked else ""),
    }
    try:
        (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return out

# # ========= Hardcoded run =========
# if __name__ == "__main__":
#     # Hardcoded URL; single-arg call only
#     u = "https://www.wayfair.com/kitchen-tabletop/pdp/laura-ashley-vq-laura-ashley-65l-slow-cooker-kbfc2706.html?piid=108469955"
#     data = scrape_wayfair_USA_product(u)
#     print(json.dumps(data, indent=2, ensure_ascii=False))




