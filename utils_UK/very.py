

# # very_oxylabs.py
# # Python 3.9+
# # pip install requests beautifulsoup4 lxml pillow

# from __future__ import annotations
# import os, re, sys, io, time, html, json, hashlib
# from pathlib import Path
# from typing import List, Optional, Dict, Any
# from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, urldefrag

# import requests
# from requests.adapters import HTTPAdapter
# from urllib3.util.retry import Retry
# from bs4 import BeautifulSoup
# from PIL import Image

# # ---------------------------
# # Paths (keep your data1 rule)
# # ---------------------------
# def _root() -> Path:
#     if getattr(sys, "frozen", False):
#         return Path(sys.executable).resolve().parent
#     return Path(__file__).resolve().parent

# SAVE_DIR = _root() / "data1"
# SAVE_DIR.mkdir(parents=True, exist_ok=True)

# # ---------------------------
# # Credentials
# # ---------------------------
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS
# except Exception:
#     OXY_USER = os.getenv("OXY_USER") or os.getenv("OXYLABS_USERNAME", "")
#     OXY_PASS = os.getenv("OXY_PASS") or os.getenv("OXYLABS_PASSWORD", "")

# if not (OXY_USER and OXY_PASS):
#     raise RuntimeError("Oxylabs credentials missing: set OXY_USER/OXY_PASS env or create oxylabs_secrets.py")

# # ---------------------------
# # Constants / helpers
# # ---------------------------
# UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#       "AppleWebKit/537.36 (KHTML, like Gecko) "
#       "Chrome/128.0.0.0 Safari/537.36")
# ACCEPT_LANG = "en-GB,en;q=0.9"

# def _session_with_retries(total=3, backoff=0.7) -> requests.Session:
#     s = requests.Session()
#     r = Retry(
#         total=total, connect=total, read=total,
#         backoff_factor=backoff,
#         status_forcelist=(429, 500, 502, 503, 504),
#         allowed_methods=frozenset(["GET", "POST", "HEAD"])
#     )
#     ad = HTTPAdapter(max_retries=r, pool_maxsize=20)
#     s.mount("https://", ad); s.mount("http://", ad)
#     return s

# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", html.unescape(s or "")).strip()

# def _safe_name(name: str) -> str:
#     n = re.sub(r"[^\w\s-]", "", name or "").strip().replace(" ", "_")
#     return n or "NA"

# def _stable_id_from_url(u: str) -> str:
#     m = re.search(r"/products?/([A-Za-z0-9_-]+)", u)
#     return (m.group(1) if m else hashlib.sha1(u.encode("utf-8")).hexdigest())[:16]

# def _to_hires(u: str) -> str:
#     # Upgrade Very's media square thumbs → hi-res JPG
#     # Example: https://media.very.co.uk/i/very/xxx_SQ90_?wid=1200&fmt=jpg
#     parts = list(urlsplit(u))
#     q = dict(parse_qsl(parts[3], keep_blank_values=True))
#     q.setdefault("wid", "1200")
#     q["fmt"] = "jpg"
#     parts[3] = urlencode(q)
#     return urlunsplit(parts)

# def _drop_query(u: str) -> str:
#     p = list(urlsplit(u)); p[3] = ""; p[4] = ""; return urlunsplit(p)

# def _bytes_to_jpg(content: bytes) -> bytes:
#     with Image.open(io.BytesIO(content)) as im:
#         im = im.convert("RGB")
#         out = io.BytesIO()
#         im.save(out, format="JPEG", quality=90, optimize=True)
#         return out.getvalue()

# # ---------------------------
# # Oxylabs HTML fetch
# # ---------------------------
# def oxy_fetch_html(url: str, *, geo="United Kingdom", timeout=90) -> str:
#     url, _ = urldefrag(url)
#     payload = {
#         "source": "universal",
#         "url": url,
#         "render": "html",
#         "geo_location": geo,
#         "headers": {"User-Agent": UA, "Accept-Language": ACCEPT_LANG},
#     }
#     sess = _session_with_retries()
#     last_exc: Optional[Exception] = None
#     for i in range(3):
#         try:
#             r = sess.post("https://realtime.oxylabs.io/v1/queries",
#                           auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
#             r.raise_for_status()
#             data = r.json()
#             html_content = (data.get("results") or [{}])[0].get("content", "")
#             if "<html" not in html_content.lower():
#                 raise RuntimeError("Oxylabs returned non-HTML content")
#             return html_content
#         except Exception as e:
#             last_exc = e
#             time.sleep(1.5 ** (i + 1))
#     raise RuntimeError(f"Oxylabs HTML fetch failed: {last_exc}")

# # ---------------------------
# # Parse Very PDP
# # ---------------------------
# def _parse_name(soup: BeautifulSoup) -> str:
#     # brand + title
#     brand = ""
#     title = ""
#     b = soup.select_one("[data-testid='product_brand']")
#     if b: brand = _clean(b.get_text(" ", strip=True))
#     t = soup.select_one("[data-testid='product_title']")
#     if t: title = _clean(t.get_text(" ", strip=True))
#     name = (brand + " " + title).strip()
#     if not name:
#         # fallback h1
#         h1 = soup.find("h1")
#         if h1: name = _clean(h1.get_text(" ", strip=True))
#     return name or "N/A"

# def _parse_price(soup: BeautifulSoup) -> str:
#     pr = soup.select_one("[data-testid='product-price__basic']")
#     if pr:
#         txt = _clean(pr.get_text(" ", strip=True))
#         # normalize common cases like "£79" / "£79.99"
#         m = re.search(r"£\s*\d+(?:\.\d{2})?", txt)
#         if m: return m.group(0).replace(" ", "")
#         return txt
#     # fallback: look for £ in the DOM
#     m = re.search(r"£\s*\d+(?:\.\d{2})?", soup.get_text(" ", strip=True))
#     return m.group(0).replace(" ", "") if m else "N/A"

# def _parse_stock(soup: BeautifulSoup) -> Optional[bool]:
#     # Prefer visible "Add to basket" button (usually present when in-stock)
#     add_btn = soup.find(lambda t: t.name in ("button","a") and re.search(r"add\s*to\s*basket", t.get_text(" ", strip=True), re.I))
#     if add_btn:
#         # try to ensure not disabled
#         if ("disabled" not in (add_btn.attrs or {})) and ("aria-disabled" not in (add_btn.attrs or {})):
#             return True
#     # Look for explicit "In stock" badge near PDP
#     text = soup.get_text(" ", strip=True)
#     if re.search(r"\bIn stock\b", text, re.I): return True
#     if re.search(r"\bOut of stock\b|\bSold out\b", text, re.I): return False
#     return None

# def _parse_description(soup: BeautifulSoup) -> str:
#     # The site uses data-testid='product_description_body'
#     body = soup.select_one("[data-testid='product_description_body']")
#     if body:
#         desc_html = body.decode() if hasattr(body, "decode") else body.get_text(" ", strip=True)
#         desc = _clean(re.sub(r"<[^>]+>", " ", desc_html))
#         if len(desc) > 40:
#             return desc
#     # fallback: a long paragraph near "Description"
#     try:
#         h = soup.find(lambda t: t.name in ("h2","h3") and re.search(r"Description", t.get_text(), re.I))
#         if h:
#             sib = h.find_next_sibling()
#             if sib:
#                 desc = _clean(sib.get_text(" ", strip=True))
#                 if len(desc) > 40:
#                     return desc
#     except Exception:
#         pass
#     return "N/A"

# def _extract_thumb_urls(soup: BeautifulSoup) -> List[str]:
#     # Collect thumb <img> src/srcset that match Very CDN “_SQ##_”
#     urls: List[str] = []

#     for img in soup.find_all("img"):
#         srcs = []
#         if img.has_attr("src"): srcs.append(img["src"])
#         if img.has_attr("data-src"): srcs.append(img["data-src"])
#         if img.has_attr("srcset"):
#             # take first src from srcset
#             srcs.extend([s.split()[0] for s in str(img["srcset"]).split(",") if s.strip()])

#         for s in srcs:
#             if not s: continue
#             if re.search(r"media\.very\.co\.uk/i/very/[^?\"'<>]*_SQ\d+_", s, re.I):
#                 urls.append(s)

#     # Fallback: regex over whole HTML in case images are not in DOM nodes
#     if not urls:
#         html_txt = str(soup)
#         urls = re.findall(r'https://media\.very\.co\.uk/i/very/[^?"\'<>]*_SQ\d+_[^?"\'<>]*',
#                           html_txt, flags=re.I)

#     # Deduplicate by base path (ignore query)
#     def _base(u: str) -> str: return re.sub(r'\?.*$', '', u)
#     seen = set(); unique = []
#     for u in urls:
#         b = _base(u)
#         if b not in seen:
#             seen.add(b); unique.append(u)

#     # Order by the SQ number
#     def _sq_num(u: str) -> int:
#         m = re.search(r"_SQ(\d+)_", u)
#         return int(m.group(1)) if m else 9999
#     unique.sort(key=_sq_num)
#     return unique[:7]

# # ---------------------------
# # Public API
# # ---------------------------
# def scrape_very_product(url: str, save_dir: Path = SAVE_DIR) -> Dict[str, Any]:
#     html_doc = oxy_fetch_html(url, geo="United Kingdom", timeout=90)
#     soup = BeautifulSoup(html_doc, "lxml")

#     name = _parse_name(soup)
#     price = _parse_price(soup)
#     in_stock = _parse_stock(soup)
#     description = _parse_description(soup)

#     # IMAGES
#     thumb_urls = _extract_thumb_urls(soup)
#     img_urls = [_to_hires(u) for u in thumb_urls]

#     # DOWNLOAD
#     folder = Path(save_dir) / f"{_safe_name(name)}_{_stable_id_from_url(url)}"
#     folder.mkdir(parents=True, exist_ok=True)

#     downloaded: List[str] = []
#     if img_urls:
#         s = _session_with_retries()
#         s.headers.update({
#             "User-Agent": UA,
#             "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
#             "Referer": url,
#             "Accept-Language": ACCEPT_LANG,
#         })
#         seen_hashes = set()
#         for i, u in enumerate(img_urls, 1):
#             try:
#                 r = s.get(u, timeout=25, stream=True)
#                 r.raise_for_status()
#                 content = r.content or b""
#                 if len(content) < 1500:
#                     continue
#                 h = hashlib.md5(content).hexdigest()
#                 if h in seen_hashes:
#                     continue
#                 seen_hashes.add(h)

#                 # save by MIME; convert weird types to jpg
#                 ext = ".jpg"
#                 ct = (r.headers.get("Content-Type") or "").lower()
#                 ul = u.lower()
#                 if "webp" in ct or ul.endswith(".webp"): ext = ".webp"
#                 elif "png" in ct or ul.endswith(".png"): ext = ".png"
#                 elif ul.endswith(".jpeg"): ext = ".jpeg"

#                 # If not a common image or you want guaranteed jpg, convert:
#                 if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
#                     data = _bytes_to_jpg(content)
#                     out = folder / f"image_{i:02d}.jpg"
#                     out.write_bytes(data)
#                     downloaded.append(str(out))
#                 else:
#                     out = folder / f"image_{i:02d}{ext}"
#                     with open(out, "wb") as f:
#                         for chunk in r.iter_content(65536):
#                             if chunk: f.write(chunk)
#                     downloaded.append(str(out))
#             except Exception as e:
#                 print(f"  ! image error: {u} ({e})")

#     return {
#         "name": name,
#         "price": price,
#         "in_stock": in_stock,
#         "description": description,
#         "image_count": len(downloaded),
#         "images": downloaded,
#         "folder": str(folder),
#     }

# # ---------------------------
# # CLI
# # ---------------------------
# if __name__ == "__main__":
#     test = "https://www.very.co.uk/laura-ashley-elveden-navy-17l-kettle/1601066431.prd?utm"  
#     print(json.dumps(scrape_very_product(test), indent=2, ensure_ascii=False))





# very.py
# Python 3.9+
# pip install requests beautifulsoup4 lxml pillow

from __future__ import annotations
import os, re, sys, io, time, html, json, hashlib
from pathlib import Path
from typing import List, Optional, Dict, Any
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, urldefrag

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from PIL import Image

# ---------------------------
# Paths (keep your data1 rule)
# ---------------------------
def _root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

SAVE_DIR = _root() / "data1"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------
# Credentials
# ---------------------------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = os.getenv("OXY_USER") or os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXY_PASS") or os.getenv("OXYLABS_PASSWORD", "")

if not (OXY_USER and OXY_PASS):
    raise RuntimeError("Oxylabs credentials missing: set OXY_USER/OXY_PASS env or create oxylabs_secrets.py")

# ---------------------------
# Constants / helpers
# ---------------------------
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0.0.0 Safari/537.36")
ACCEPT_LANG = "en-GB,en;q=0.9"

def _session_with_retries(total=3, backoff=0.7) -> requests.Session:
    s = requests.Session()
    r = Retry(
        total=total, connect=total, read=total,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST", "HEAD"])
    )
    ad = HTTPAdapter(max_retries=r, pool_maxsize=20)
    s.mount("https://", ad); s.mount("http://", ad)
    return s

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()

def _safe_name(name: str) -> str:
    n = re.sub(r"[^\w\s-]", "", name or "").strip().replace(" ", "_")
    return n or "NA"

def _stable_id_from_url(u: str) -> str:
    m = re.search(r"/products?/([A-Za-z0-9_-]+)", u)
    return (m.group(1) if m else hashlib.sha1(u.encode("utf-8")).hexdigest())[:16]

def _to_hires(u: str) -> str:
    """
    Upgrade Very's media URLs to high-res JPG.
    Input: https://media.very.co.uk/i/very/W7XJ1_SQ1_0000000048_NAVY_SLf?$pdp_48x64_x2$&fmt=webp
    Output: https://media.very.co.uk/i/very/W7XJ1_SQ1_0000000048_NAVY_SLf?wid=1200&fmt=jpg
    """
    # Remove any existing query params and add high-res ones
    base = re.sub(r'\?.*$', '', u)
    return f"{base}?wid=1200&fmt=jpg"

def _drop_query(u: str) -> str:
    p = list(urlsplit(u)); p[3] = ""; p[4] = ""; return urlunsplit(p)

def _bytes_to_jpg(content: bytes) -> bytes:
    with Image.open(io.BytesIO(content)) as im:
        im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=90, optimize=True)
        return out.getvalue()

# ---------------------------
# Oxylabs HTML fetch
# ---------------------------
def oxy_fetch_html(url: str, *, geo="United Kingdom", timeout=90) -> str:
    url, _ = urldefrag(url)
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
        "geo_location": geo,
        "headers": {"User-Agent": UA, "Accept-Language": ACCEPT_LANG},
    }
    sess = _session_with_retries()
    last_exc: Optional[Exception] = None
    for i in range(3):
        try:
            r = sess.post("https://realtime.oxylabs.io/v1/queries",
                          auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            html_content = (data.get("results") or [{}])[0].get("content", "")
            if "<html" not in html_content.lower():
                raise RuntimeError("Oxylabs returned non-HTML content")
            return html_content
        except Exception as e:
            last_exc = e
            time.sleep(1.5 ** (i + 1))
    raise RuntimeError(f"Oxylabs HTML fetch failed: {last_exc}")

# ---------------------------
# Parse Very PDP
# ---------------------------
def _parse_name(soup: BeautifulSoup) -> str:
    # brand + title
    brand = ""
    title = ""
    b = soup.select_one("[data-testid='product_brand']")
    if b: brand = _clean(b.get_text(" ", strip=True))
    t = soup.select_one("[data-testid='product_title']")
    if t: title = _clean(t.get_text(" ", strip=True))
    name = (brand + " " + title).strip()
    if not name:
        # fallback h1
        h1 = soup.find("h1")
        if h1: name = _clean(h1.get_text(" ", strip=True))
    return name or "N/A"

def _parse_price(soup: BeautifulSoup) -> str:
    pr = soup.select_one("[data-testid='product-price__basic']")
    if pr:
        txt = _clean(pr.get_text(" ", strip=True))
        # normalize common cases like "£79" / "£79.99"
        m = re.search(r"£\s*\d+(?:\.\d{2})?", txt)
        if m: return m.group(0).replace(" ", "")
        return txt
    # fallback: look for £ in the DOM
    m = re.search(r"£\s*\d+(?:\.\d{2})?", soup.get_text(" ", strip=True))
    return m.group(0).replace(" ", "") if m else "N/A"

def _parse_stock(soup: BeautifulSoup) -> Optional[bool]:
    # Prefer visible "Add to basket" button (usually present when in-stock)
    add_btn = soup.find(lambda t: t.name in ("button","a") and re.search(r"add\s*to\s*basket", t.get_text(" ", strip=True), re.I))
    if add_btn:
        # try to ensure not disabled
        if ("disabled" not in (add_btn.attrs or {})) and ("aria-disabled" not in (add_btn.attrs or {})):
            return True
    # Look for explicit "In stock" badge near PDP
    text = soup.get_text(" ", strip=True)
    if re.search(r"\bIn stock\b", text, re.I): return True
    if re.search(r"\bOut of stock\b|\bSold out\b", text, re.I): return False
    return None

def _parse_description(soup: BeautifulSoup) -> str:
    # The site uses data-testid='product_description_body'
    body = soup.select_one("[data-testid='product_description_body']")
    if body:
        desc_html = body.decode() if hasattr(body, "decode") else body.get_text(" ", strip=True)
        desc = _clean(re.sub(r"<[^>]+>", " ", desc_html))
        if len(desc) > 40:
            return desc
    # fallback: a long paragraph near "Description"
    try:
        h = soup.find(lambda t: t.name in ("h2","h3") and re.search(r"Description", t.get_text(), re.I))
        if h:
            sib = h.find_next_sibling()
            if sib:
                desc = _clean(sib.get_text(" ", strip=True))
                if len(desc) > 40:
                    return desc
    except Exception:
        pass
    return "N/A"

def _extract_thumb_urls(soup: BeautifulSoup) -> List[str]:
    """
    Extract thumbnail URLs from Very product pages.
    
    Very uses URLs like:
    https://media.very.co.uk/i/very/W7XJ1_SQ1_0000000048_NAVY_SLf?$pdp_48x64_x2$&fmt=webp
    
    The _SQ#_ part indicates the image sequence number (SQ1, SQ2, etc.)
    The code before _SQ (like W7XJ1) identifies the product.
    """
    urls: List[str] = []
    html_txt = str(soup)
    
    # First, find the main product's image code from the thumbnail carousel
    # The carousel contains the main product images with aria-label like "Go to slide 1"
    # or alt text like "Image thumbnail 1 of 7 of [Product Name]"
    main_product_code = None
    
    # Strategy 1: Look in the splide carousel (thumbnail gallery)
    carousel = soup.select_one('.splide, [class*="ThumbnailCarousel"], [class*="ImageGallery"]')
    if carousel:
        # Find first image in carousel
        for source in carousel.find_all(['source', 'img']):
            for attr in ['srcset', 'src']:
                val = source.get(attr, '')
                if val and 'media.very.co.uk' in val and '_SQ' in val:
                    val = html.unescape(val.split(',')[0].split()[0])
                    # Extract product code (the part before _SQ)
                    m = re.search(r'/very/([A-Z0-9]+)_SQ', val, re.I)
                    if m:
                        main_product_code = m.group(1)
                        break
            if main_product_code:
                break
    
    # Strategy 2: Look for images with "thumbnail 1 of" in alt text
    if not main_product_code:
        for img in soup.find_all('img', alt=re.compile(r'thumbnail\s+1\s+of', re.I)):
            src = img.get('src', '') or img.get('srcset', '')
            if src and 'media.very.co.uk' in src:
                src = html.unescape(src.split(',')[0].split()[0])
                m = re.search(r'/very/([A-Z0-9]+)_SQ', src, re.I)
                if m:
                    main_product_code = m.group(1)
                    break
    
    # Strategy 3: Find the most common product code with multiple SQ numbers
    if not main_product_code:
        all_codes = re.findall(r'/very/([A-Z0-9]+)_SQ(\d+)_', html_txt, re.I)
        if all_codes:
            # Count which product codes have multiple SQ numbers (SQ1, SQ2, etc.)
            from collections import defaultdict
            code_sq_numbers = defaultdict(set)
            for code, sq in all_codes:
                code_sq_numbers[code.upper()].add(int(sq))
            
            # The main product should have sequential SQ1, SQ2, SQ3...
            # Other products (recommendations) usually only have SQ1
            best_code = None
            best_count = 0
            for code, sq_nums in code_sq_numbers.items():
                if len(sq_nums) > best_count:
                    best_count = len(sq_nums)
                    best_code = code
            
            if best_code and best_count >= 2:
                main_product_code = best_code
    
    if not main_product_code:
        # Fallback: just take first code found
        m = re.search(r'/very/([A-Z0-9]+)_SQ\d+_', html_txt, re.I)
        if m:
            main_product_code = m.group(1)
    
    if not main_product_code:
        return []
    
    # Now extract all images with this product code
    # Pattern: https://media.very.co.uk/i/very/{CODE}_SQ{N}_{REST}
    pattern = rf'https://media\.very\.co\.uk/i/very/{main_product_code}_SQ(\d+)_[^?"\'<>\s&]+'
    
    found_urls = re.findall(pattern, html_txt, re.I)
    
    # Also check source and img tags specifically
    for source in soup.find_all(['source', 'img']):
        for attr in ['srcset', 'src', 'data-src']:
            val = source.get(attr, '')
            if val and 'media.very.co.uk' in val and main_product_code in val.upper():
                for part in val.split(','):
                    part = part.strip().split()[0] if part.strip() else ''
                    part = html.unescape(part)
                    if re.search(rf'{main_product_code}_SQ\d+_', part, re.I):
                        base_match = re.match(rf'(https://media\.very\.co\.uk/i/very/{main_product_code}_SQ\d+_[^?]+)', part, re.I)
                        if base_match:
                            urls.append(base_match.group(1))
    
    # Also get from regex on full HTML
    full_pattern = rf'https://media\.very\.co\.uk/i/very/{main_product_code}_SQ\d+_[^?"\'<>\s&]+'
    urls.extend(re.findall(full_pattern, html_txt, re.I))
    
    # Deduplicate by base path
    def _base_path(u: str) -> str:
        return re.sub(r'\?.*$', '', u).lower()
    
    seen = set()
    unique = []
    for u in urls:
        base = _base_path(u)
        if base not in seen:
            seen.add(base)
            unique.append(re.sub(r'\?.*$', '', u))  # Store without query params
    
    # Sort by SQ number to maintain correct order
    def _sq_num(u: str) -> int:
        m = re.search(r'_SQ(\d+)_', u, re.I)
        return int(m.group(1)) if m else 9999
    
    unique.sort(key=_sq_num)
    
    # Limit to reasonable number of images
    return unique[:10]

# ---------------------------
# Public API
# ---------------------------
def scrape_very_product(url: str, save_dir: Path = SAVE_DIR) -> Dict[str, Any]:
    html_doc = oxy_fetch_html(url, geo="United Kingdom", timeout=90)
    soup = BeautifulSoup(html_doc, "lxml")

    name = _parse_name(soup)
    price = _parse_price(soup)
    in_stock = _parse_stock(soup)
    description = _parse_description(soup)

    # IMAGES
    thumb_urls = _extract_thumb_urls(soup)
    img_urls = [_to_hires(u) for u in thumb_urls]

    # DOWNLOAD
    folder = Path(save_dir) / f"{_safe_name(name)}_{_stable_id_from_url(url)}"
    folder.mkdir(parents=True, exist_ok=True)

    downloaded: List[str] = []
    if img_urls:
        s = _session_with_retries()
        s.headers.update({
            "User-Agent": UA,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": url,
            "Accept-Language": ACCEPT_LANG,
        })
        seen_hashes = set()
        for i, u in enumerate(img_urls, 1):
            try:
                r = s.get(u, timeout=25, stream=True)
                r.raise_for_status()
                content = r.content or b""
                if len(content) < 1500:
                    continue
                h = hashlib.md5(content).hexdigest()
                if h in seen_hashes:
                    continue
                seen_hashes.add(h)

                # save by MIME; convert weird types to jpg
                ext = ".jpg"
                ct = (r.headers.get("Content-Type") or "").lower()
                ul = u.lower()
                if "webp" in ct or ul.endswith(".webp"): ext = ".webp"
                elif "png" in ct or ul.endswith(".png"): ext = ".png"
                elif ul.endswith(".jpeg"): ext = ".jpeg"

                # If not a common image or you want guaranteed jpg, convert:
                if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
                    data = _bytes_to_jpg(content)
                    out = folder / f"image_{i:02d}.jpg"
                    out.write_bytes(data)
                    downloaded.append(str(out))
                else:
                    out = folder / f"image_{i:02d}{ext}"
                    with open(out, "wb") as f:
                        for chunk in r.iter_content(65536):
                            if chunk: f.write(chunk)
                    downloaded.append(str(out))
            except Exception as e:
                print(f"  ! image error: {u} ({e})")

    return {
        "url": url,
        "name": name,
        "price": price,
        "in_stock": in_stock,
        "description": description,
        "image_count": len(downloaded),
        "image_urls": img_urls,
        "images": downloaded,
        "folder": str(folder),
    }

# # ---------------------------
# # CLI
# # ---------------------------
# if __name__ == "__main__":
#     test = "https://www.very.co.uk/laura-ashley-china-rose-17l-kettle/1601066433.prd"  
#     print(json.dumps(scrape_very_product(test), indent=2, ensure_ascii=False))