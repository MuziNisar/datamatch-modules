
# # -*- coding: utf-8 -*-
# # kgelectronic_wsapi.py
# # Python 3.9+ | pip install requests beautifulsoup4 lxml

# from __future__ import annotations
# import json
# import os
# import re
# import time
# import base64
# import hashlib
# from pathlib import Path
# from typing import List, Optional, Dict, Tuple
# from urllib.parse import urlparse, urljoin, urldefrag, urlunparse, urlencode, unquote

# import requests
# from bs4 import BeautifulSoup

# # =========================
# # Credentials (create oxylabs_secrets.py with OXY_USER/OXY_PASS)
# # =========================
# from oxylabs_secrets import OXY_USER, OXY_PASS

# # =========================
# # Config
# # =========================
# BASE_DIR = Path(__file__).resolve().parent
# DATA_DIR = BASE_DIR / "data1"            # keep your original output path
# DATA_DIR.mkdir(parents=True, exist_ok=True)

# UA = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
# )
# ACCEPT_LANG = "en-AU,en;q=0.9"
# WSAPI_URL = "https://realtime.oxylabs.io/v1/queries"

# # =========================
# # Helpers
# # =========================
# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "")).strip()

# def _safe_name(s: str) -> str:
#     s = _clean(s)
#     return re.sub(r"[^\w.\-]+", "_", s)[:80] or "item"

# def _unique_suffix(url: str) -> str:
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]

# def _ensure_dir(p: Path):
#     p.mkdir(parents=True, exist_ok=True)

# def _parse_price(s: str) -> Optional[str]:
#     s = _clean(s)
#     m = re.search(r"\$\s*\d[\d,]*(?:\.\d{2})?", s)
#     return m.group(0) if m else None

# def _extract_text(soup: BeautifulSoup, selector: str) -> str:
#     el = soup.select_one(selector)
#     return _clean(el.get_text(" ", strip=True)) if el else ""

# def _wsapi_request(payload: dict, timeout: int = 90) -> dict:
#     r = requests.post(WSAPI_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
#     # Oxylabs returns 4xx when parse/render fails; surface their message:
#     if 400 <= r.status_code < 500:
#         try: err = r.json()
#         except Exception: err = {"message": r.text}
#         raise requests.HTTPError(f"{r.status_code} from WSAPI Realtime: {err}", response=r)
#     r.raise_for_status()
#     return r.json()

# def _extract_html_from_result(res0: dict) -> str:
#     """
#     Oxylabs 'universal' can put HTML in different fields depending on render/settings.
#     This normalizes and returns a string of HTML.
#     """
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
#         # Handle data URLs (data:text/html;base64,...)
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
#         # In some cases Oxylabs returns base64-ish blobs
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

# def _wsapi_get_html(url: str, geo: str = "Australia", render: str = "html", session_id: Optional[str] = None) -> str:
#     payload = {
#         "source": "universal",
#         "url": url,
#         "user_agent_type": "desktop_chrome",
#         "geo_location": geo,
#         "render": render,                # "html" to execute JS
#         "parse": False,                  # we'll parse locally for full control
#     }
#     if session_id:
#         payload["session_id"] = session_id
#     data = _wsapi_request(payload)
#     results = data.get("results") or []
#     if not results:
#         raise RuntimeError("WSAPI returned no results")
#     return _extract_html_from_result(results[0])

# # =========================
# # Page parsers (local, BeautifulSoup)
# # =========================
# def _description_text_from_html(soup: BeautifulSoup) -> str:
#     """
#     Mimics your Playwright version:
#     - target `section.productdetails`
#     - convert <br> to newlines
#     - strip HTML tags
#     - collapse/dedupe lines
#     """
#     node = soup.select_one("section.productdetails")
#     if not node:
#         return ""
#     # copy only the section HTML, then string-clean
#     html = str(node)
#     html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
#     html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.I | re.S)
#     html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
#     html = re.sub(r"<[^>]+>", " ", html)
#     text = html.replace("\xa0", " ").replace("&nbsp;", " ")

#     # normalize bullets if present in nested lists
#     text = re.sub(r"\s*•\s*", " • ", text)
#     lines = [ _clean(line) for line in text.split("\n") if _clean(line) ]

#     out: List[str] = []
#     for ln in lines:
#         if not out or out[-1] != ln:
#             out.append(ln)
#     return "\n".join(out)

# def _collect_image_urls_from_html(soup: BeautifulSoup, base: str) -> List[str]:
#     """
#     - From .thumbnail-row img (prefer full image if "_thumb/" in src)
#     - From #myModal .mySlides img
#     - Deduplicate by URL (without query)
#     """
#     urls: List[str] = []
#     # thumbnails
#     thumbs = soup.select(".thumbnail-row img")
#     for img in thumbs:
#         alt = (img.get("alt") or "").strip()
#         src = (img.get("src") or "").strip()
#         if alt.startswith("/assets/"):
#             urls.append(urljoin(base, alt))
#         elif src:
#             if "_thumb/" in src:
#                 urls.append(urljoin(base, src.replace("_thumb/", "/").split("?")[0]))
#             else:
#                 urls.append(urljoin(base, src))
#     # modal slides
#     slides = soup.select("#myModal .mySlides img")
#     for img in slides:
#         s = (img.get("src") or "").strip()
#         if s:
#             urls.append(urljoin(base, s))
#     # dedupe
#     seen = set()
#     finals = []
#     for u in urls:
#         k = u.split("?")[0].lower()
#         if k not in seen:
#             seen.add(k)
#             finals.append(u)
#     return finals

# # =========================
# # Image fetching (direct → Oxylabs proxy fallback)
# # =========================
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
#         # extension guess
#         ext = ".jpg"
#         m = re.search(r"\.(jpe?g|png|webp|gif|avif)", img_url.split("?")[0], re.I)
#         if m:
#             ext = "." + m.group(1).lower()
#             if ext == ".webp":  # normalize to jpg for downstream use, like your Playwright version
#                 ext = ".jpg"
#             if ext == ".avif":
#                 ext = ".avif"
#         fname = f"{idx:02d}_{_safe_name(os.path.basename(img_url.split('?')[0]))}{ext}"
#         dest = folder / fname
#         # try direct, then proxy
#         if _download_image_direct(img_url, dest, referer) or _download_image_via_proxy(img_url, dest, referer):
#             saved_paths.append(str(dest))
#     return saved_paths

# # =========================
# # Orchestrator
# # =========================
# def scrape_kgelectronic(url: str, geo: str = "Australia") -> Dict:
#     url, _ = urldefrag(url)
#     base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
#     session_id = f"sess-{int(time.time())}"

#     # 1) Get rendered HTML via WSAPI
#     html_text = _wsapi_get_html(url, geo=geo, render="html", session_id=session_id)
#     if not html_text or "<" not in html_text:
#         # fallback: non-rendered
#         html_text = _wsapi_get_html(url, geo=geo, render=None, session_id=session_id)

#     # 2) Parse locally
#     soup = BeautifulSoup(html_text, "lxml")

#     name = _extract_text(soup, "h1.custom_product_Heading[itemprop='name']")
#     price = _parse_price(_extract_text(soup, ".productprice.productpricetext")) or "N/A"

#     availability = _extract_text(soup, "span[itemprop='availability']") or _extract_text(soup, "[itemprop='availability']")
#     in_stock = None
#     al = availability.lower()
#     if "in stock" in al: in_stock = True
#     elif "out of stock" in al: in_stock = False

#     description = _description_text_from_html(soup)
#     image_urls = _collect_image_urls_from_html(soup, base)

#     # 3) Output folder and image downloads
#     suffix = _unique_suffix(url)
#     folder = DATA_DIR / f"kgelectronic_{_safe_name(name or 'product')}_{suffix}"
#     _ensure_dir(folder)
#     saved_paths = _download_images_auto(image_urls, folder, referer=url)

#     return {
#         "name": name,
#         "price": price,
#         "in_stock": in_stock,
#         "availability_text": availability,
#         "description": description,
#         "image_count": len(saved_paths),
#         "images": saved_paths,
#         "folder": str(folder),
#         "source_url": url,
#         "mode": "wsapi+render",
#     }

# # # =========================
# # # CLI
# # # =========================
# # if __name__ == "__main__":
# #     URL = "https://www.kgelectronic.com.au/p/Laura-Ashley-1.7L-Kettle-Elvenden-White-Silver/LADKEW"
# #     print(json.dumps(scrape_kgelectronic(URL), indent=2, ensure_ascii=False))








# -*- coding: utf-8 -*-
# kgelectronic_wsapi.py
# Python 3.9+ | pip install requests beautifulsoup4 lxml
# Version: 2.0 - Added retry logic for timeout handling

from __future__ import annotations
import json
import os
import re
import time
import base64
import hashlib
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from urllib.parse import urlparse, urljoin, urldefrag, urlunparse, urlencode, unquote

import requests
from requests.exceptions import RequestException, ReadTimeout, ConnectionError
from bs4 import BeautifulSoup

__version__ = "2.0"

# =========================
# Credentials (from oxylabs_secrets.py or environment)
# =========================
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = os.getenv("OXYLABS_USERNAME") or os.getenv("OXY_USER", "")
    OXY_PASS = os.getenv("OXYLABS_PASSWORD") or os.getenv("OXY_PASS", "")

if not (OXY_USER and OXY_PASS):
    raise RuntimeError("Oxylabs credentials missing. Create oxylabs_secrets.py with OXY_USER/OXY_PASS or set environment variables.")

# =========================
# Config
# =========================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data1"
DATA_DIR.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
ACCEPT_LANG = "en-AU,en;q=0.9"
WSAPI_URL = "https://realtime.oxylabs.io/v1/queries"

# =========================
# Helpers
# =========================
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _safe_name(s: str) -> str:
    s = _clean(s)
    return re.sub(r"[^\w.\-]+", "_", s)[:80] or "item"

def _unique_suffix(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]

def _ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def _parse_price(s: str) -> Optional[str]:
    s = _clean(s)
    m = re.search(r"\$\s*\d[\d,]*(?:\.\d{2})?", s)
    return m.group(0) if m else None

def _extract_text(soup: BeautifulSoup, selector: str) -> str:
    el = soup.select_one(selector)
    return _clean(el.get_text(" ", strip=True)) if el else ""


def _wsapi_request(payload: dict, timeout: int = 90, retries: int = 3, backoff: float = 2.0) -> dict:
    """
    Make request to Oxylabs WSAPI with retry logic for timeouts.
    """
    last_err = None
    
    for attempt in range(1, retries + 1):
        try:
            # Increase timeout progressively on retries
            current_timeout = timeout + (attempt - 1) * 30
            
            r = requests.post(
                WSAPI_URL, 
                auth=(OXY_USER, OXY_PASS), 
                json=payload, 
                timeout=current_timeout
            )
            
            # Oxylabs returns 4xx when parse/render fails
            if 400 <= r.status_code < 500:
                try:
                    err = r.json()
                except Exception:
                    err = {"message": r.text}
                raise requests.HTTPError(f"{r.status_code} from WSAPI Realtime: {err}", response=r)
            
            r.raise_for_status()
            return r.json()
            
        except (ReadTimeout, ConnectionError) as e:
            last_err = e
            if attempt < retries:
                sleep_time = backoff ** attempt
                print(f"  [KG] Timeout on attempt {attempt}/{retries}, retrying in {sleep_time:.1f}s...")
                time.sleep(sleep_time)
            else:
                raise RuntimeError(f"WSAPI request timed out after {retries} attempts: {e}") from e
                
        except RequestException as e:
            last_err = e
            if attempt < retries:
                sleep_time = backoff ** attempt
                print(f"  [KG] Error on attempt {attempt}/{retries}: {str(e)[:50]}, retrying...")
                time.sleep(sleep_time)
            else:
                raise RuntimeError(f"WSAPI request failed after {retries} attempts: {e}") from e
    
    raise RuntimeError(f"WSAPI request failed: {last_err}")


def _extract_html_from_result(res0: dict) -> str:
    """
    Oxylabs 'universal' can put HTML in different fields depending on render/settings.
    This normalizes and returns a string of HTML.
    """
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
        # Handle data URLs (data:text/html;base64,...)
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
        # In some cases Oxylabs returns base64-ish blobs
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


def _wsapi_get_html(url: str, geo: str = "Australia", render: str = "html", session_id: Optional[str] = None) -> str:
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
    
    data = _wsapi_request(payload, timeout=90, retries=3)
    results = data.get("results") or []
    if not results:
        raise RuntimeError("WSAPI returned no results")
    return _extract_html_from_result(results[0])


# =========================
# Page parsers (local, BeautifulSoup)
# =========================
def _description_text_from_html(soup: BeautifulSoup) -> str:
    """
    Mimics your Playwright version:
    - target `section.productdetails`
    - convert <br> to newlines
    - strip HTML tags
    - collapse/dedupe lines
    """
    node = soup.select_one("section.productdetails")
    if not node:
        return ""
    html = str(node)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<[^>]+>", " ", html)
    text = html.replace("\xa0", " ").replace("&nbsp;", " ")

    text = re.sub(r"\s*•\s*", " • ", text)
    lines = [_clean(line) for line in text.split("\n") if _clean(line)]

    out: List[str] = []
    for ln in lines:
        if not out or out[-1] != ln:
            out.append(ln)
    return "\n".join(out)


def _collect_image_urls_from_html(soup: BeautifulSoup, base: str) -> List[str]:
    """
    - From .thumbnail-row img (prefer full image if "_thumb/" in src)
    - From #myModal .mySlides img
    - Deduplicate by URL (without query)
    """
    urls: List[str] = []
    # thumbnails
    thumbs = soup.select(".thumbnail-row img")
    for img in thumbs:
        alt = (img.get("alt") or "").strip()
        src = (img.get("src") or "").strip()
        if alt.startswith("/assets/"):
            urls.append(urljoin(base, alt))
        elif src:
            if "_thumb/" in src:
                urls.append(urljoin(base, src.replace("_thumb/", "/").split("?")[0]))
            else:
                urls.append(urljoin(base, src))
    # modal slides
    slides = soup.select("#myModal .mySlides img")
    for img in slides:
        s = (img.get("src") or "").strip()
        if s:
            urls.append(urljoin(base, s))
    # dedupe
    seen = set()
    finals = []
    for u in urls:
        k = u.split("?")[0].lower()
        if k not in seen:
            seen.add(k)
            finals.append(u)
    return finals


# =========================
# Image fetching (direct → Oxylabs proxy fallback)
# =========================
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
        # extension guess
        ext = ".jpg"
        m = re.search(r"\.(jpe?g|png|webp|gif|avif)", img_url.split("?")[0], re.I)
        if m:
            ext = "." + m.group(1).lower()
            if ext == ".jpeg":
                ext = ".jpg"
        
        fname = f"{idx:02d}{ext}"
        dest = folder / fname
        
        # try direct, then proxy
        if _download_image_direct(img_url, dest, referer) or _download_image_via_proxy(img_url, dest, referer):
            saved_paths.append(str(dest))
    return saved_paths


# =========================
# Orchestrator
# =========================
def scrape_kgelectronic(url: str, geo: str = "Australia", verbose: bool = False) -> Dict:
    url, _ = urldefrag(url)
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    session_id = f"sess-{int(time.time())}"

    if verbose:
        print(f"Fetching {url}...")

    # 1) Get rendered HTML via WSAPI with retry
    html_text = _wsapi_get_html(url, geo=geo, render="html", session_id=session_id)
    if not html_text or "<" not in html_text:
        # fallback: non-rendered
        if verbose:
            print("  Retrying without render...")
        html_text = _wsapi_get_html(url, geo=geo, render=None, session_id=session_id)

    # 2) Parse locally
    soup = BeautifulSoup(html_text, "lxml")

    name = _extract_text(soup, "h1.custom_product_Heading[itemprop='name']")
    price = _parse_price(_extract_text(soup, ".productprice.productpricetext")) or "N/A"

    availability = _extract_text(soup, "span[itemprop='availability']") or _extract_text(soup, "[itemprop='availability']")
    in_stock = None
    al = availability.lower()
    if "in stock" in al:
        in_stock = True
    elif "out of stock" in al:
        in_stock = False

    description = _description_text_from_html(soup)
    image_urls = _collect_image_urls_from_html(soup, base)

    if verbose:
        print(f"  Name: {name}")
        print(f"  Price: {price}")
        print(f"  In Stock: {in_stock}")
        print(f"  Images: {len(image_urls)}")

    # 3) Output folder and image downloads
    suffix = _unique_suffix(url)
    folder = DATA_DIR / f"kgelectronic_{_safe_name(name or 'product')}_{suffix}"
    _ensure_dir(folder)
    
    # Clear existing images to prevent accumulation from previous runs
    for old_file in folder.glob("*.*"):
        if old_file.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif'}:
            try:
                old_file.unlink()
            except Exception:
                pass
    
    if verbose:
        print(f"  Downloading {len(image_urls)} images...")
    
    saved_paths = _download_images_auto(image_urls, folder, referer=url)

    return {
        "name": name,
        "price": price,
        "in_stock": in_stock,
        "availability_text": availability,
        "description": description,
        "image_count": len(saved_paths),
        "image_urls": image_urls,
        "images": saved_paths,
        "folder": str(folder),
        "source_url": url,
        "mode": "wsapi+render",
    }


# # =========================
# # CLI
# # =========================
# if __name__ == "__main__":
#     URL = "https://www.kgelectronic.com.au/p/Home-Appliances/Small-Kitchen-Appliances/Kettles/Laura-Ashley-Stainless-Steel-1.7L-Dome-Electric-Ke/LADKWM"
#     data = scrape_kgelectronic(URL, verbose=True)
#     print("\n" + "=" * 60)
#     print("RESULTS:")
#     print("=" * 60)
#     print(json.dumps(data, indent=2, ensure_ascii=False))