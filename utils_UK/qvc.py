
# # qvc_oxylabs.py
# # Python 3.9+
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

# # ---------------------------
# # Credentials (prefer .py, else env)
# # ---------------------------
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS  # define in your project
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
#     Keeps existing query (like ?$aempdlarge80$) and appends &fmt=jpg.
#     """
#     try:
#         p = urlparse(u)
#         if "scene7.com" not in p.netloc:
#             return u
#         # Keep existing query and append fmt=jpg if not present
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

#     # Not available banner → out of stock
#     sold_out = soup.select_one("p.status.allSoldOut, .status.allSoldOut")
#     if sold_out and "not available" in sold_out.get_text(" ", strip=True).lower():
#         in_stock = False
#         price = "N/A"  # no price shown when fully unavailable

#     # Otherwise try price block
#     if price == "N/A":
#         price_el = soup.select_one("span.pdpPrice.price")
#         if price_el:
#             dq = price_el.get("data-qvc-price", "").strip()
#             if dq:
#                 price = f"£{dq}"
#             else:
#                 txt = _clean_plain(price_el.get_text())
#                 txt = re.sub(r"(?i)\bdeleted\b", "", txt).strip()
#                 if txt:
#                     price = txt

#     # In-stock button or availability text
#     if in_stock is None:
#         btn = soup.select_one("#btnAddToCart")
#         if btn:
#             in_stock = True
#         else:
#             vis_txt = ""
#             for el in soup.select(".buyBoxAvailibility .status"):
#                 t = _clean_plain(el.get_text())
#                 if t:
#                     vis_txt = t; break
#             if vis_txt:
#                 if re.search(r"\bin\s*stock\b", vis_txt, re.I):
#                     in_stock = True
#                 elif re.search(r"(sold\s*out|all\s*sold\s*out|waitlist|not available)", vis_txt, re.I):
#                     in_stock = False

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
#                         desc_parts.append(cand); found = True; break
#             if found: break

#     description = _strip_rating_boilerplate("\n\n".join([p for p in desc_parts if p.strip()]), name) or "N/A"

#     # IMAGES — collect ALL thumbs in the list (your sample shows 8)
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
#         "description": description or "N/A",
#         "image_urls": ordered,  # all the thumbnails we found
#     }

# # ---------------------------
# # Image download (force real JPG files)
# # ---------------------------
# def _origin_for(url: str) -> str:
#     p = urlparse(url)
#     return f"{p.scheme or 'https'}://{p.netloc}"

# def _bytes_to_jpg_file(content: bytes, out_path: Path) -> None:
#     """
#     Convert arbitrary image bytes to a proper RGB JPEG on disk.
#     """
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

#             # If server already returns JPEG → write directly; else transcode to JPEG
#             ct = (r.headers.get("Content-Type") or "").lower()
#             out = folder / f"image_{i}.jpg"
#             if "jpeg" in ct or "jpg" in ct:
#                 with open(out, "wb") as f:
#                     for chunk in r.iter_content(65536):
#                         if chunk:
#                             f.write(chunk)
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
#                                     geo: str = "United Kingdom") -> Dict[str, Any]:
#     html = oxy_fetch_html(url, geo=geo)
#     parsed = parse_qvc(html, page_url=url)

#     safe = _safe_name(parsed["name"])
#     folder = SAVE_DIR / safe

#     images_downloaded: List[str] = []
#     if download_images_flag and parsed["image_urls"]:
#         images_downloaded = download_qvc_images_as_jpg(parsed["image_urls"], folder, referer=url, max_images=max_images)

#     return {
#         "name": parsed["name"],
#         "price": parsed["price"],
#         "in_stock": parsed["in_stock"],
#         "description": parsed["description"],
#         "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
#         "images": images_downloaded if images_downloaded else parsed["image_urls"],
#         "folder": str(folder),
#         "url": url,
#         "mode": "oxylabs-universal",
#     }

# # ---------------------------
# # CLI
# # ---------------------------
# if __name__ == "__main__":
#     TEST_URL = "https://www.qvcuk.com/vq-halo-portable-bluetooth-speaker%2C-powerbank-%26-lantern.product.737161.html"
#     data = scrape_qvc_product_with_oxylabs(TEST_URL, download_images_flag=True, max_images=None)
#     print(json.dumps(data, indent=2, ensure_ascii=False))






# qvc_oxylabs.py
# Python 3.9+
# Version: 2.0 - Fixed stock detection to prioritize Add to Cart button
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

__version__ = "2.0"

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
# Parsing (QVC PDP)
# ---------------------------
def parse_qvc(html: str, page_url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

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
    }

# # ---------------------------
# # CLI
# # ---------------------------
# if __name__ == "__main__":
#     TEST_URL = "https://www.qvcuk.com/vq-halo-portable-bluetooth-speaker%2C-powerbank-%26-lantern.product.737161.html"
#     data = scrape_qvc_product_with_oxylabs(TEST_URL, download_images_flag=True, max_images=None, verbose=True)
#     print(json.dumps(data, indent=2, ensure_ascii=False))