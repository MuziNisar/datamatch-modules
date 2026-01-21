
# # qvc_oxylabs.py
# # Python 3.9+
# # Version: 2.0 - Fixed stock detection to prioritize Add to Cart button
# # pip install requests beautifulsoup4 lxml pillow

# from __future__ import annotations
# import os, re, json, html as html_lib, time, io
# from pathlib import Path
# from typing import Dict, Any, List, Optional, Tuple
# from urllib.parse import urlsplit, urlunsplit, urldefrag, urlparse, urlunparse, parse_qsl, urlencode

# import requests
# from requests.adapters import HTTPAdapter
# from urllib3.util.retry import Retry
# from bs4 import BeautifulSoup
# from PIL import Image

# __version__ = "2.0"

# # ---------------------------
# # Credentials (prefer .py, else env)
# # ---------------------------
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS
# except Exception:
#     OXY_USER = os.getenv("OXY_USER") or os.getenv("OXYLABS_USERNAME", "")
#     OXY_PASS = os.getenv("OXY_PASS") or os.getenv("OXYLABS_PASSWORD", "")

# if not (OXY_USER and OXY_PASS):
#     raise RuntimeError("Oxylabs credentials missing: set OXY_USER/OXY_PASS env or create oxylabs_secrets.py")

# # ---------------------------
# # Paths / headers
# # ---------------------------
# try:
#     BASE_DIR = Path(__file__).resolve().parent
# except NameError:
#     BASE_DIR = Path.cwd()

# SAVE_DIR = BASE_DIR / "data1"
# SAVE_DIR.mkdir(parents=True, exist_ok=True)

# UA_STR = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#     "AppleWebKit/537.36 (KHTML, like Gecko) "
#     "Chrome/128.0.0.0 Safari/537.36"
# )
# ACCEPT_LANG = "en-GB,en;q=0.9"

# # ---------------------------
# # Retry session
# # ---------------------------
# def _session_with_retries(total=3, backoff=0.6) -> requests.Session:
#     s = requests.Session()
#     retry = Retry(
#         total=total, connect=total, read=total,
#         backoff_factor=backoff,
#         status_forcelist=(429, 500, 502, 503, 504),
#         allowed_methods=frozenset(["GET", "POST", "HEAD"])
#     )
#     adapter = HTTPAdapter(max_retries=retry, pool_maxsize=20)
#     s.mount("http://", adapter)
#     s.mount("https://", adapter)
#     return s

# # ---------------------------
# # Helpers
# # ---------------------------
# def _clean_plain(s: str) -> str:
#     s = html_lib.unescape(s or "")
#     s = s.replace("\r", "")
#     s = re.sub(r"[ \t]+", " ", s)
#     s = re.sub(r"\n{3,}", "\n\n", s)
#     return s.strip()

# def _strip_rating_boilerplate(s: str, name: str = "") -> str:
#     if not s:
#         return s
#     s = s.replace("\xa0", " ")
#     if name and s.lower().startswith(name.lower()):
#         s = s[len(name):].lstrip(" \n:-—")
#     drops = (
#         r"out of 5 stars",
#         r"average rating value",
#         r"Same page link",
#         r"Read\s+\d+\s+Reviews?",
#         r"Read a Review",
#     )
#     kept, prev_had_rating = [], False
#     for ln in s.splitlines():
#         l = ln.strip()
#         if any(re.search(pat, l, re.I) for pat in drops):
#             prev_had_rating = True
#             continue
#         if prev_had_rating and re.fullmatch(r"\d+(?:\.\d+)?", l):
#             prev_had_rating = False
#             continue
#         if re.fullmatch(r"\(?\d+\)?", l):
#             continue
#         kept.append(ln)
#     s = "\n".join(kept)
#     s = re.sub(r"\n{3,}", "\n\n", s).strip()
#     return s

# def _clean_html_to_text(desc_html: str) -> str:
#     if not desc_html:
#         return ""
#     s = desc_html
#     s = re.sub(r"(?i)<br\s*/?>", "\n", s)
#     s = re.sub(r"(?is)</p\s*>", "\n\n", s)
#     def _li_to_bullet(m):
#         inner = re.sub(r"<[^>]+>", " ", m.group(1))
#         inner = re.sub(r"\s+", " ", inner).strip()
#         return f"• {inner}\n"
#     s = re.sub(r"(?is)<li[^>]*>(.*?)</li>", _li_to_bullet, s)
#     s = re.sub(r"(?is)<\s*span[^>]*>\s*(Contains:)\s*</\s*span\s*>", r"\1", s)
#     s = re.sub(r"(?is)<[^>]+>", " ", s)
#     s = html_lib.unescape(s)
#     s = re.sub(r"[ \t]+\n", "\n", s)
#     s = re.sub(r"\n{3,}", "\n\n", s)
#     s = re.sub(r"[ \t]{2,}", " ", s).strip()
#     s = re.sub(r"(?i)\bAll measurements are approximate\b.*", "", s).strip()
#     return s

# def _safe_name(name: str) -> str:
#     n = re.sub(r"[^\w\s-]", "", name or "").strip().replace(" ", "_")
#     return n or "NA"

# def _abs(url: str) -> str:
#     return "https:" + url if url.startswith("//") else url

# def _drop_query(u: str) -> str:
#     parts = list(urlsplit(u))
#     parts[3] = ""  # query
#     parts[4] = ""  # fragment
#     return urlunsplit(parts)

# def _ensure_jpg_on_scene7(u: str) -> str:
#     """
#     For QVC Scene7 (qvc.scene7.com), add fmt=jpg to force JPEG.
#     """
#     try:
#         p = urlparse(u)
#         if "scene7.com" not in p.netloc:
#             return u
#         q = p.query or ""
#         if "fmt=jpg" not in q.lower():
#             sep = "&" if q else ""
#             q = q + (sep + "fmt=jpg")
#         new_url = urlunparse((p.scheme or "https", p.netloc, p.path, p.params, q, p.fragment))
#         return new_url
#     except Exception:
#         return u

# # ---------------------------
# # Oxylabs HTML fetch
# # ---------------------------
# def oxy_fetch_html(url: str, geo: str = "United Kingdom", timeout: int = 90) -> str:
#     url, _ = urldefrag(url)
#     payload = {
#         "source": "universal",
#         "url": url,
#         "render": "html",
#         "geo_location": geo,
#         "headers": {"User-Agent": UA_STR, "Accept-Language": ACCEPT_LANG},
#     }
#     sess = _session_with_retries()
#     last = None
#     for i in range(3):
#         try:
#             r = sess.post(
#                 "https://realtime.oxylabs.io/v1/queries",
#                 auth=(OXY_USER, OXY_PASS),
#                 json=payload,
#                 timeout=timeout,
#             )
#             r.raise_for_status()
#             data = r.json()
#             html = data["results"][0]["content"]
#             if "<html" not in html.lower():
#                 raise RuntimeError("Oxylabs returned non-HTML content")
#             return html
#         except Exception as e:
#             last = e
#             time.sleep(1.5 ** (i + 1))
#     raise RuntimeError(f"Oxylabs HTML fetch failed: {last}")

# # ---------------------------
# # Parsing (QVC PDP)
# # ---------------------------
# def parse_qvc(html: str, page_url: str) -> Dict[str, Any]:
#     soup = BeautifulSoup(html, "lxml")

#     # NAME
#     name = "N/A"
#     og = soup.select_one("meta[property='og:title']")
#     if og and og.get("content"):
#         cand = re.sub(r"\s*[-–|]\s*QVC.*$", "", og["content"]).strip()
#         if cand:
#             name = cand
#     if name == "N/A":
#         h1 = soup.select_one("h1")
#         if h1:
#             name = _clean_plain(h1.get_text())

#     # PRICE & STOCK
#     price = "N/A"
#     in_stock: Optional[bool] = None
#     stock_text = ""

#     # ============================================================
#     # Strategy 1 (HIGHEST PRIORITY): Check for Add to Cart button
#     # ============================================================
#     btn = soup.select_one("#btnAddToCart, .btnAddToCart, button[id='btnAddToCart']")
#     if btn:
#         btn_disabled = btn.has_attr("disabled") or btn.get("aria-disabled", "").lower() == "true"
#         btn_text = _clean_plain(btn.get_text()).lower()
        
#         if btn_disabled:
#             in_stock = False
#             stock_text = "Add to Cart disabled"
#         elif any(phrase in btn_text for phrase in ["add to basket", "add to cart", "add to bag"]):
#             in_stock = True
#             stock_text = "Add to Basket available"
#         else:
#             # Button exists but unclear text - assume available
#             in_stock = True
#             stock_text = "Add to Cart button present"

#     # ============================================================
#     # Strategy 2: Check for sold out / not available banner
#     # ============================================================
#     if in_stock is None:
#         sold_out = soup.select_one("p.status.allSoldOut, .status.allSoldOut, .allSoldOut")
#         if sold_out:
#             sold_text = sold_out.get_text(" ", strip=True).lower()
#             if "not available" in sold_text or "sold out" in sold_text:
#                 in_stock = False
#                 stock_text = _clean_plain(sold_out.get_text()) or "Not available"
#                 price = "N/A"

#     # ============================================================
#     # Strategy 3: Check availability status text
#     # ============================================================
#     if in_stock is None:
#         for el in soup.select(".buyBoxAvailibility .status, .status"):
#             t = _clean_plain(el.get_text()).lower()
#             if t:
#                 if re.search(r"\bin\s*stock\b", t, re.I):
#                     in_stock = True
#                     stock_text = _clean_plain(el.get_text())
#                     break
#                 elif re.search(r"(sold\s*out|all\s*sold\s*out|waitlist|not available)", t, re.I):
#                     in_stock = False
#                     stock_text = _clean_plain(el.get_text())
#                     break

#     # ============================================================
#     # Get price
#     # ============================================================
#     price_el = soup.select_one("span.pdpPrice.price")
#     if price_el:
#         dq = price_el.get("data-qvc-price", "").strip()
#         if dq:
#             price = f"£{dq}"
#         else:
#             txt = _clean_plain(price_el.get_text())
#             txt = re.sub(r"(?i)\bdeleted\b", "", txt).strip()
#             if txt:
#                 price = txt

#     # DESCRIPTION (short + long)
#     desc_parts: List[str] = []
#     short_el = soup.select_one(".pdShortDescTxt")
#     if short_el:
#         short_txt = _strip_rating_boilerplate(_clean_plain(short_el.get_text()), name)
#         if short_txt and len(short_txt) > 20:
#             desc_parts.append(short_txt)

#     long_el = soup.select_one(".accordionText")
#     if long_el:
#         long_txt = _strip_rating_boilerplate(_clean_html_to_text(str(long_el)), name)
#         if long_txt and len(long_txt) > 40:
#             desc_parts.append(long_txt)

#     if not desc_parts:
#         for tag in soup.select("script[type='application/ld+json']"):
#             try:
#                 data = json.loads(tag.text or "")
#             except Exception:
#                 continue
#             objs = data if isinstance(data, list) else [data]
#             found = False
#             for o in objs:
#                 if isinstance(o, dict) and o.get("@type") == "Product":
#                     cand = _strip_rating_boilerplate(_clean_plain(str(o.get("description", ""))), name)
#                     if cand and len(cand) > 40:
#                         desc_parts.append(cand)
#                         found = True
#                         break
#             if found:
#                 break

#     description = _strip_rating_boilerplate("\n\n".join([p for p in desc_parts if p.strip()]), name) or "N/A"

#     # IMAGES — collect ALL thumbs in the list
#     img_urls: List[str] = []
#     for a in soup.select("#imageThumbnails .imageList a.thumbcell"):
#         href = a.get("data-standard") or a.get("href") or ""
#         if href:
#             u = _abs(href)
#             img_urls.append(u)

#     # Deduplicate by base (drop query/fragment), keep order
#     seen, ordered = set(), []
#     for u in img_urls:
#         b = _drop_query(u)
#         if b not in seen:
#             seen.add(b)
#             ordered.append(u)

#     # Force Scene7 to serve JPEG if possible
#     ordered = [_ensure_jpg_on_scene7(u) for u in ordered]

#     return {
#         "name": name or "N/A",
#         "price": price or "N/A",
#         "in_stock": in_stock,
#         "stock_text": stock_text,
#         "description": description or "N/A",
#         "image_urls": ordered,
#     }

# # ---------------------------
# # Image download (force real JPG files)
# # ---------------------------
# def _origin_for(url: str) -> str:
#     p = urlparse(url)
#     return f"{p.scheme or 'https'}://{p.netloc}"

# def _bytes_to_jpg_file(content: bytes, out_path: Path) -> None:
#     """Convert arbitrary image bytes to a proper RGB JPEG on disk."""
#     with Image.open(io.BytesIO(content)) as im:
#         if im.mode in ("RGBA", "LA", "P"):
#             im = im.convert("RGB")
#         else:
#             im = im.convert("RGB")
#         im.save(out_path, format="JPEG", quality=90, optimize=True)

# def download_qvc_images_as_jpg(urls: List[str], folder: Path, referer: str, max_images: Optional[int] = None) -> List[str]:
#     if not urls:
#         return []
#     if max_images is not None:
#         urls = urls[:max_images]
#     folder.mkdir(parents=True, exist_ok=True)

#     sess = _session_with_retries()
#     headers = {
#         "User-Agent": UA_STR,
#         "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#         "Accept-Language": ACCEPT_LANG,
#         "Referer": referer,
#         "Origin": _origin_for(referer),
#     }

#     saved = []
#     for i, u in enumerate(urls, 1):
#         try:
#             r = sess.get(u, headers=headers, timeout=30, stream=True)
#             r.raise_for_status()
#             content = r.content or b""
#             if not content:
#                 print(f"  ! empty content: {u}")
#                 continue

#             ct = (r.headers.get("Content-Type") or "").lower()
#             out = folder / f"{i:02d}.jpg"
#             if "jpeg" in ct or "jpg" in ct:
#                 with open(out, "wb") as f:
#                     f.write(content)
#             else:
#                 _bytes_to_jpg_file(content, out)

#             saved.append(str(out))
#         except Exception as e:
#             print(f"  ! image download failed: {u} ({e})")
#     return saved

# # ---------------------------
# # Public API
# # ---------------------------
# def scrape_qvc_product_with_oxylabs(url: str,
#                                     download_images_flag: bool = True,
#                                     max_images: Optional[int] = None,
#                                     geo: str = "United Kingdom",
#                                     verbose: bool = False) -> Dict[str, Any]:
#     if verbose:
#         print(f"Fetching {url}...")
    
#     html = oxy_fetch_html(url, geo=geo)
#     parsed = parse_qvc(html, page_url=url)

#     safe = _safe_name(parsed["name"])
#     folder = SAVE_DIR / safe
    
#     if verbose:
#         print(f"  Name: {parsed['name']}")
#         print(f"  Price: {parsed['price']}")
#         print(f"  In Stock: {parsed['in_stock']}")
#         print(f"  Stock Text: {parsed['stock_text']}")

#     images_downloaded: List[str] = []
#     if download_images_flag and parsed["image_urls"]:
#         images_downloaded = download_qvc_images_as_jpg(parsed["image_urls"], folder, referer=url, max_images=max_images)

#     return {
#         "name": parsed["name"],
#         "price": parsed["price"],
#         "in_stock": parsed["in_stock"],
#         "stock_text": parsed["stock_text"],
#         "description": parsed["description"],
#         "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
#         "images": images_downloaded if images_downloaded else parsed["image_urls"],
#         "folder": str(folder),
#         "url": url,
#         "mode": "oxylabs-universal",
#     }

# # # ---------------------------
# # # CLI
# # # ---------------------------
# # if __name__ == "__main__":
# #     TEST_URL = "https://www.qvcuk.com/vq-halo-portable-bluetooth-speaker%2C-powerbank-%26-lantern.product.737161.html"
# #     data = scrape_qvc_product_with_oxylabs(TEST_URL, download_images_flag=True, max_images=None, verbose=True)
# #     print(json.dumps(data, indent=2, ensure_ascii=False))




# qvc_oxylabs.py
# Python 3.9+
# Version: 2.1 - Added invalid link detection (404, error pages, listing pages)
# pip install requests beautifulsoup4 lxml pillow

from __future__ import annotations
import os, re, json, html as html_lib, time, io
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit, urldefrag, urlparse, urlunparse, parse_qsl, urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from PIL import Image

__version__ = "2.1"

# ---------------------------
# Credentials (prefer .py, else env)
# ---------------------------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = os.getenv("OXY_USER") or os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXY_PASS") or os.getenv("OXYLABS_PASSWORD", "")

if not (OXY_USER and OXY_PASS):
    raise RuntimeError("Oxylabs credentials missing: set OXY_USER/OXY_PASS env or create oxylabs_secrets.py")

# ---------------------------
# Paths / headers
# ---------------------------
try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()

SAVE_DIR = BASE_DIR / "data1"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

UA_STR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
ACCEPT_LANG = "en-GB,en;q=0.9"

# ---------------------------
# Retry session
# ---------------------------
def _session_with_retries(total=3, backoff=0.6) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=total, connect=total, read=total,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST", "HEAD"])
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=20)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

# ---------------------------
# Helpers
# ---------------------------
def _clean_plain(s: str) -> str:
    s = html_lib.unescape(s or "")
    s = s.replace("\r", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _strip_rating_boilerplate(s: str, name: str = "") -> str:
    if not s:
        return s
    s = s.replace("\xa0", " ")
    if name and s.lower().startswith(name.lower()):
        s = s[len(name):].lstrip(" \n:-—")
    drops = (
        r"out of 5 stars",
        r"average rating value",
        r"Same page link",
        r"Read\s+\d+\s+Reviews?",
        r"Read a Review",
    )
    kept, prev_had_rating = [], False
    for ln in s.splitlines():
        l = ln.strip()
        if any(re.search(pat, l, re.I) for pat in drops):
            prev_had_rating = True
            continue
        if prev_had_rating and re.fullmatch(r"\d+(?:\.\d+)?", l):
            prev_had_rating = False
            continue
        if re.fullmatch(r"\(?\d+\)?", l):
            continue
        kept.append(ln)
    s = "\n".join(kept)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s

def _clean_html_to_text(desc_html: str) -> str:
    if not desc_html:
        return ""
    s = desc_html
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</p\s*>", "\n\n", s)
    def _li_to_bullet(m):
        inner = re.sub(r"<[^>]+>", " ", m.group(1))
        inner = re.sub(r"\s+", " ", inner).strip()
        return f"• {inner}\n"
    s = re.sub(r"(?is)<li[^>]*>(.*?)</li>", _li_to_bullet, s)
    s = re.sub(r"(?is)<\s*span[^>]*>\s*(Contains:)\s*</\s*span\s*>", r"\1", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = html_lib.unescape(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s).strip()
    s = re.sub(r"(?i)\bAll measurements are approximate\b.*", "", s).strip()
    return s

def _safe_name(name: str) -> str:
    n = re.sub(r"[^\w\s-]", "", name or "").strip().replace(" ", "_")
    return n or "NA"

def _abs(url: str) -> str:
    return "https:" + url if url.startswith("//") else url

def _drop_query(u: str) -> str:
    parts = list(urlsplit(u))
    parts[3] = ""  # query
    parts[4] = ""  # fragment
    return urlunsplit(parts)

def _ensure_jpg_on_scene7(u: str) -> str:
    """
    For QVC Scene7 (qvc.scene7.com), add fmt=jpg to force JPEG.
    """
    try:
        p = urlparse(u)
        if "scene7.com" not in p.netloc:
            return u
        q = p.query or ""
        if "fmt=jpg" not in q.lower():
            sep = "&" if q else ""
            q = q + (sep + "fmt=jpg")
        new_url = urlunparse((p.scheme or "https", p.netloc, p.path, p.params, q, p.fragment))
        return new_url
    except Exception:
        return u

# ---------------------------
# Oxylabs HTML fetch
# ---------------------------
def oxy_fetch_html(url: str, geo: str = "United Kingdom", timeout: int = 90) -> str:
    url, _ = urldefrag(url)
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
        "geo_location": geo,
        "headers": {"User-Agent": UA_STR, "Accept-Language": ACCEPT_LANG},
    }
    sess = _session_with_retries()
    last = None
    for i in range(3):
        try:
            r = sess.post(
                "https://realtime.oxylabs.io/v1/queries",
                auth=(OXY_USER, OXY_PASS),
                json=payload,
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json()
            html = data["results"][0]["content"]
            if "<html" not in html.lower():
                raise RuntimeError("Oxylabs returned non-HTML content")
            return html
        except Exception as e:
            last = e
            time.sleep(1.5 ** (i + 1))
    raise RuntimeError(f"Oxylabs HTML fetch failed: {last}")

# ---------------------------
# Invalid Link Detection
# ---------------------------
def _extract_product_name(soup: BeautifulSoup, page_url: str = "") -> str:
    """
    Extract product name from page - works even on error/invalid pages.
    Tries multiple sources: og:title, h1, title tag, URL.
    """
    # 1. Try og:title meta tag (most reliable)
    og = soup.select_one("meta[property='og:title']")
    if og and og.get("content"):
        name = re.sub(r"\s*[-–|]\s*QVC.*$", "", og["content"]).strip()
        if name and name.lower() not in ["qvc", "qvcuk", "oops!", "error", ""]:
            return name
    
    # 2. Try page title
    title = soup.select_one("title")
    if title:
        name = re.sub(r"\s*[-–|]\s*QVC.*$", "", title.get_text()).strip()
        if name and name.lower() not in ["qvc", "qvcuk", "oops!", "error", ""]:
            return name
    
    # 3. Try h1 (but skip error headers)
    h1 = soup.select_one("h1")
    if h1:
        h1_text = _clean_plain(h1.get_text())
        if h1_text.lower() not in ["oops!", "error", "page not found", ""]:
            return h1_text
    
    # 4. Try product name specific selectors
    for sel in [".productName", ".pdpProductName", "[data-product-name]"]:
        el = soup.select_one(sel)
        if el:
            name = _clean_plain(el.get_text())
            if name:
                return name
    
    # 5. FALLBACK: Extract name from URL
    # QVC URL pattern: /product-name-here.product.XXXXXX.html
    if page_url:
        try:
            path = urlparse(page_url).path  # e.g., /outlet-cath-kidston-vq-monty-portable-dab-fm-bluetooth.product.740403.html
            # Remove leading slash and .html
            path = path.strip("/").replace(".html", "")
            # Split by .product. and take the first part (the name slug)
            if ".product." in path:
                slug = path.split(".product.")[0]
            else:
                slug = path
            # Convert slug to readable name: "outlet-cath-kidston-vq-monty" -> "Outlet Cath Kidston Vq Monty"
            if slug:
                name = slug.replace("-", " ").replace("_", " ").strip()
                # Title case
                name = " ".join(word.capitalize() for word in name.split())
                if name:
                    return name
        except Exception:
            pass
    
    return "N/A"


def _detect_invalid_page(soup: BeautifulSoup, page_url: str) -> Tuple[bool, str, str]:
    """
    Detect if the page is invalid (404, error, listing page, etc.)
    Returns: (is_invalid: bool, reason: str, extracted_name: str)
    
    Detection priority:
    1. Error page elements (404, "Oops!", "can't find")
    2. Generic error messages
    3. Listing/category page detection
    4. Missing essential PDP elements
    
    ALWAYS extracts product name even for invalid pages.
    """
    
    # Extract name FIRST - we want this regardless of validity
    extracted_name = _extract_product_name(soup, page_url)
    
    # ============================================================
    # 1. QVC-specific error page: <section id="error" data-module-type="error">
    # ============================================================
    error_section = soup.select_one(
        "section#error[data-module-type='error'], "
        "section.qModule[data-module-type='error'], "
        "section[data-module-feature-name='error']"
    )
    if error_section:
        error_text = error_section.get_text(" ", strip=True).lower()
        if any(phrase in error_text for phrase in [
            "can't find", "cannot find", "doesn't exist", 
            "no longer available", "page not found", "been moved", "been removed"
        ]):
            return True, "error_page:qvc_error_section", extracted_name
    
    # ============================================================
    # 2. Check for "Oops!" h1 header (QVC's 404 indicator)
    # ============================================================
    h1 = soup.select_one("h1")
    if h1:
        h1_text = _clean_plain(h1.get_text()).lower()
        if h1_text == "oops!" or "page not found" in h1_text:
            # Verify with h2 or surrounding text
            h2 = soup.select_one("h2")
            if h2:
                h2_text = h2.get_text().lower()
                if any(phrase in h2_text for phrase in ["can't find", "cannot find", "doesn't exist"]):
                    return True, "error_page:oops_404", extracted_name
            # Even without h2 confirmation, "Oops!" as main header is suspicious
            return True, "error_page:oops_header", extracted_name
    
    # ============================================================
    # 3. Check for generic error text patterns in body
    # ============================================================
    body_text = soup.get_text(" ", strip=True).lower() if soup.body else ""
    error_patterns = [
        r"this page (has been|was) (removed|deleted)",
        r"product (is )?no longer available",
        r"item (is )?no longer available", 
        r"we couldn'?t find (that|this) page",
        r"sorry,?\s*(this|the) page (doesn'?t|does not) exist",
        r"404\s*-?\s*(page)?\s*not found",
    ]
    for pattern in error_patterns:
        if re.search(pattern, body_text):
            return True, "error_page:pattern_match", extracted_name
    
    # ============================================================
    # 4. Check if it's a listing/category page (not a PDP)
    # ============================================================
    # QVC product listing indicators
    product_cards = soup.select(".productItem, .product-tile, .searchProduct, .plpProduct")
    if len(product_cards) >= 4:
        return True, f"listing_page:{len(product_cards)}_product_cards", extracted_name
    
    # Pagination with multiple pages suggests listing
    pagination = soup.select(".pagination a, .paging a, .pageNumber")
    if len(pagination) >= 3:
        return True, f"listing_page:pagination_{len(pagination)}_pages", extracted_name
    
    # ============================================================
    # 5. Check for essential PDP elements (positive validation)
    # ============================================================
    has_product_name = bool(soup.select_one("h1, meta[property='og:title']"))
    has_price = bool(soup.select_one("span.pdpPrice, .price, [data-qvc-price]"))
    has_add_to_cart = bool(soup.select_one("#btnAddToCart, .btnAddToCart, button[id='btnAddToCart']"))
    has_product_images = bool(soup.select_one("#imageThumbnails, .productImage, .pdpImage"))
    
    # Check JSON-LD for Product schema
    has_jsonld_product = False
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.text or "")
            objs = data if isinstance(data, list) else [data]
            for obj in objs:
                if isinstance(obj, dict) and obj.get("@type") == "Product":
                    has_jsonld_product = True
                    break
        except Exception:
            continue
    
    # If JSON-LD Product exists, it's definitely a valid product page
    if has_jsonld_product:
        return False, "", extracted_name
    
    # If we have add-to-cart button, it's a valid PDP
    if has_add_to_cart:
        return False, "", extracted_name
    
    # If missing most PDP elements, likely invalid
    pdp_score = sum([has_product_name, has_price, has_product_images])
    if pdp_score < 2:
        return True, f"missing_pdp_elements:score_{pdp_score}/3", extracted_name
    
    # ============================================================
    # 6. URL-based validation (product ID in URL)
    # ============================================================
    # QVC URLs typically have pattern: /product-name.product.XXXXXX.html
    url_lower = page_url.lower()
    if ".product." not in url_lower and "/product/" not in url_lower:
        # Check if it looks like a category or search page
        if any(seg in url_lower for seg in ["/category/", "/search/", "/browse/", "/shop/"]):
            return True, "url_pattern:category_or_search", extracted_name
    
    return False, "", extracted_name

# ---------------------------
# Parsing (QVC PDP)
# ---------------------------
def parse_qvc(html: str, page_url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    # ============================================================
    # INVALID LINK DETECTION - CHECK FIRST
    # ============================================================
    is_invalid, invalid_reason, extracted_name = _detect_invalid_page(soup, page_url)
    if is_invalid:
        # Determine display name based on invalid reason
        if "error_page" in invalid_reason or "oops" in invalid_reason:
            display_name = "Invalid Link"
        else:
            display_name = "Product not available"
        
        return {
            "name": display_name,
            "price": "N/A",
            "in_stock": False,
            "stock_text": display_name,
            "description": "N/A",
            "image_urls": [],
            "is_invalid": True,
            "invalid_reason": invalid_reason,
        }

    # NAME
    name = "N/A"
    og = soup.select_one("meta[property='og:title']")
    if og and og.get("content"):
        cand = re.sub(r"\s*[-–|]\s*QVC.*$", "", og["content"]).strip()
        if cand:
            name = cand
    if name == "N/A":
        h1 = soup.select_one("h1")
        if h1:
            name = _clean_plain(h1.get_text())

    # PRICE & STOCK
    price = "N/A"
    in_stock: Optional[bool] = None
    stock_text = ""

    # ============================================================
    # Strategy 1 (HIGHEST PRIORITY): Check for Add to Cart button
    # ============================================================
    btn = soup.select_one("#btnAddToCart, .btnAddToCart, button[id='btnAddToCart']")
    if btn:
        btn_disabled = btn.has_attr("disabled") or btn.get("aria-disabled", "").lower() == "true"
        btn_text = _clean_plain(btn.get_text()).lower()
        
        if btn_disabled:
            in_stock = False
            stock_text = "Add to Cart disabled"
        elif any(phrase in btn_text for phrase in ["add to basket", "add to cart", "add to bag"]):
            in_stock = True
            stock_text = "Add to Basket available"
        else:
            # Button exists but unclear text - assume available
            in_stock = True
            stock_text = "Add to Cart button present"

    # ============================================================
    # Strategy 2: Check for sold out / not available banner
    # ============================================================
    if in_stock is None:
        sold_out = soup.select_one("p.status.allSoldOut, .status.allSoldOut, .allSoldOut")
        if sold_out:
            sold_text = sold_out.get_text(" ", strip=True).lower()
            if "not available" in sold_text or "sold out" in sold_text:
                in_stock = False
                stock_text = _clean_plain(sold_out.get_text()) or "Not available"
                price = "N/A"

    # ============================================================
    # Strategy 3: Check availability status text
    # ============================================================
    if in_stock is None:
        for el in soup.select(".buyBoxAvailibility .status, .status"):
            t = _clean_plain(el.get_text()).lower()
            if t:
                if re.search(r"\bin\s*stock\b", t, re.I):
                    in_stock = True
                    stock_text = _clean_plain(el.get_text())
                    break
                elif re.search(r"(sold\s*out|all\s*sold\s*out|waitlist|not available)", t, re.I):
                    in_stock = False
                    stock_text = _clean_plain(el.get_text())
                    break

    # ============================================================
    # Get price
    # ============================================================
    price_el = soup.select_one("span.pdpPrice.price")
    if price_el:
        dq = price_el.get("data-qvc-price", "").strip()
        if dq:
            price = f"£{dq}"
        else:
            txt = _clean_plain(price_el.get_text())
            txt = re.sub(r"(?i)\bdeleted\b", "", txt).strip()
            if txt:
                price = txt

    # DESCRIPTION (short + long)
    desc_parts: List[str] = []
    short_el = soup.select_one(".pdShortDescTxt")
    if short_el:
        short_txt = _strip_rating_boilerplate(_clean_plain(short_el.get_text()), name)
        if short_txt and len(short_txt) > 20:
            desc_parts.append(short_txt)

    long_el = soup.select_one(".accordionText")
    if long_el:
        long_txt = _strip_rating_boilerplate(_clean_html_to_text(str(long_el)), name)
        if long_txt and len(long_txt) > 40:
            desc_parts.append(long_txt)

    if not desc_parts:
        for tag in soup.select("script[type='application/ld+json']"):
            try:
                data = json.loads(tag.text or "")
            except Exception:
                continue
            objs = data if isinstance(data, list) else [data]
            found = False
            for o in objs:
                if isinstance(o, dict) and o.get("@type") == "Product":
                    cand = _strip_rating_boilerplate(_clean_plain(str(o.get("description", ""))), name)
                    if cand and len(cand) > 40:
                        desc_parts.append(cand)
                        found = True
                        break
            if found:
                break

    description = _strip_rating_boilerplate("\n\n".join([p for p in desc_parts if p.strip()]), name) or "N/A"

    # IMAGES — collect ALL thumbs in the list
    img_urls: List[str] = []
    for a in soup.select("#imageThumbnails .imageList a.thumbcell"):
        href = a.get("data-standard") or a.get("href") or ""
        if href:
            u = _abs(href)
            img_urls.append(u)

    # Deduplicate by base (drop query/fragment), keep order
    seen, ordered = set(), []
    for u in img_urls:
        b = _drop_query(u)
        if b not in seen:
            seen.add(b)
            ordered.append(u)

    # Force Scene7 to serve JPEG if possible
    ordered = [_ensure_jpg_on_scene7(u) for u in ordered]

    return {
        "name": name or "N/A",
        "price": price or "N/A",
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description or "N/A",
        "image_urls": ordered,
        "is_invalid": False,
        "invalid_reason": "",
    }

# ---------------------------
# Image download (force real JPG files)
# ---------------------------
def _origin_for(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme or 'https'}://{p.netloc}"

def _bytes_to_jpg_file(content: bytes, out_path: Path) -> None:
    """Convert arbitrary image bytes to a proper RGB JPEG on disk."""
    with Image.open(io.BytesIO(content)) as im:
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGB")
        else:
            im = im.convert("RGB")
        im.save(out_path, format="JPEG", quality=90, optimize=True)

def download_qvc_images_as_jpg(urls: List[str], folder: Path, referer: str, max_images: Optional[int] = None) -> List[str]:
    if not urls:
        return []
    if max_images is not None:
        urls = urls[:max_images]
    folder.mkdir(parents=True, exist_ok=True)

    sess = _session_with_retries()
    headers = {
        "User-Agent": UA_STR,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Referer": referer,
        "Origin": _origin_for(referer),
    }

    saved = []
    for i, u in enumerate(urls, 1):
        try:
            r = sess.get(u, headers=headers, timeout=30, stream=True)
            r.raise_for_status()
            content = r.content or b""
            if not content:
                print(f"  ! empty content: {u}")
                continue

            ct = (r.headers.get("Content-Type") or "").lower()
            out = folder / f"{i:02d}.jpg"
            if "jpeg" in ct or "jpg" in ct:
                with open(out, "wb") as f:
                    f.write(content)
            else:
                _bytes_to_jpg_file(content, out)

            saved.append(str(out))
        except Exception as e:
            print(f"  ! image download failed: {u} ({e})")
    return saved

# ---------------------------
# Public API
# ---------------------------
def scrape_qvc_product_with_oxylabs(url: str,
                                    download_images_flag: bool = True,
                                    max_images: Optional[int] = None,
                                    geo: str = "United Kingdom",
                                    verbose: bool = False) -> Dict[str, Any]:
    if verbose:
        print(f"Fetching {url}...")
    
    html = oxy_fetch_html(url, geo=geo)
    parsed = parse_qvc(html, page_url=url)

    # ============================================================
    # Handle invalid link - return early
    # ============================================================
    if parsed.get("is_invalid"):
        if verbose:
            print(f"  ⚠ INVALID: {parsed['invalid_reason']}")
        return {
            "name": parsed["name"],  # Already has "Product Name - Invalid Link" suffix
            "price": "N/A",
            "in_stock": False,
            "stock_text": parsed["stock_text"],
            "description": "N/A",
            "image_count": 0,
            "images": [],
            "folder": "",
            "url": url,
            "mode": "oxylabs-universal",
            "is_invalid": True,
            "invalid_reason": parsed["invalid_reason"],
        }

    safe = _safe_name(parsed["name"])
    folder = SAVE_DIR / safe
    
    if verbose:
        print(f"  Name: {parsed['name']}")
        print(f"  Price: {parsed['price']}")
        print(f"  In Stock: {parsed['in_stock']}")
        print(f"  Stock Text: {parsed['stock_text']}")

    images_downloaded: List[str] = []
    if download_images_flag and parsed["image_urls"]:
        images_downloaded = download_qvc_images_as_jpg(parsed["image_urls"], folder, referer=url, max_images=max_images)

    return {
        "name": parsed["name"],
        "price": parsed["price"],
        "in_stock": parsed["in_stock"],
        "stock_text": parsed["stock_text"],
        "description": parsed["description"],
        "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
        "images": images_downloaded if images_downloaded else parsed["image_urls"],
        "folder": str(folder),
        "url": url,
        "mode": "oxylabs-universal",
        "is_invalid": False,
        "invalid_reason": "",
    }

# # ---------------------------
# # CLI
# # ---------------------------
# if __name__ == "__main__":
#     import sys
    
#     # Test URLs
#     TEST_URLS = [
#         # Valid product
#         "https://www.qvcuk.com/outlet-cath-kidston-vq-monty-portable-dab-fm-bluetooth.product.740403.html?sc=PSCH&sa=suggested&qq=mh&",
       
#     ]
    
#     if len(sys.argv) > 1:
#         TEST_URLS = sys.argv[1:]
    
#     for test_url in TEST_URLS:
#         print(f"\n{'='*60}")
#         print(f"Testing: {test_url}")
#         print('='*60)
#         try:
#             data = scrape_qvc_product_with_oxylabs(test_url, download_images_flag=False, verbose=True)
#             print(json.dumps(data, indent=2, ensure_ascii=False))
#         except Exception as e:
#             print(f"ERROR: {e}")