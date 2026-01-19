
# -*- coding: utf-8 -*-
# kitchenwarehouse_wsapi.py — single-file Oxylabs WSAPI scraper (render + browser_instructions)
# Python 3.10+  |  pip install requests beautifulsoup4 lxml

from __future__ import annotations
import json, os, re, time, base64, hashlib, html
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from urllib.parse import urlparse, parse_qs, urlunparse, unquote, urldefrag

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# -----------------------------
# Config
# -----------------------------
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
ACCEPT_LANG = "en-AU,en;q=0.9"
GEO = "Australia"
WSAPI_URL = "https://realtime.oxylabs.io/v1/queries"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "Data1"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Put your creds in a sibling file oxylabs_secrets.py
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = OXY_PASS = None  # we'll error clearly later

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

def _parse_money(s: str) -> Optional[str]:
    s = _clean(s)
    m = re.search(r"\$?\s?(\d[\d,]*)(?:\.(\d{2}))?", s)
    if not m:
        return None
    dollars = m.group(1).replace(",", "")
    cents = m.group(2) if m.group(2) is not None else "00"
    return f"${dollars}.{cents}"

def _dedupe_preserve(seq: List[str]) -> List[str]:
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x); out.append(x)
    return out

def _utc_stamp() -> str:
    # timezone-aware UTC stamp (Py3.11+ future-proof)
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

# -----------------------------
# Oxylabs WSAPI core
# -----------------------------
def _wsapi_request(payload: dict, timeout: int = 120) -> dict:
    if not (OXY_USER and OXY_PASS):
        raise RuntimeError("Missing Oxylabs credentials. Create oxylabs_secrets.py with OXY_USER/OXY_PASS.")
    r = requests.post(WSAPI_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
    # Treat 5xx/edge hiccups as soft failures (we’ll retry at higher level if needed)
    if 400 <= r.status_code < 500:
        # hard client error with details
        try: err = r.json()
        except Exception: err = {"message": r.text}
        raise requests.HTTPError(f"{r.status_code} from WSAPI Realtime: {err}", response=r)
    r.raise_for_status()
    return r.json()

def _extract_html_from_result(res0: dict) -> str:
    # WSAPI may return content under various keys depending on features used.
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
        # data:text/html;base64,...
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
        # Some results may be base64-like blobs
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

def _wsapi_get_html(url: str, *, render: Optional[str] = "html", session_id: Optional[str] = None,
                    browser_instructions: Optional[list] = None, geo: str = GEO, parse: bool = False) -> str:
    payload = {
        "source": "universal",
        "url": url,
        "user_agent_type": "desktop_chrome",
        "geo_location": geo,
        "render": render,           # "html" to execute JS
        "parse": parse,             # we parse locally
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
# Site-specific parsing (Kitchenware AU)
# -----------------------------
def _extract_next_json(soup: BeautifulSoup) -> dict:
    # Next.js style JSON can live in several places
    for sel in ("script#__NEXT_DATA__", "script[id='__NEXT_DATA__']", "script[data-nextjs-runtime]"):
        tag = soup.select_one(sel)
        if tag and tag.string:
            try:
                return json.loads(tag.string)
            except Exception:
                pass
    # Sometimes embedded in window.__NEXT_DATA__ = {...}
    for script in soup.find_all("script"):
        txt = script.string or ""
        if not txt:
            continue
        if "__NEXT_DATA__" in txt and "{" in txt and "}" in txt:
            try:
                jtxt = txt.split("=",1)[1]
                jtxt = jtxt.strip().rstrip(";")
                return json.loads(jtxt)
            except Exception:
                continue
    return {}

def _extract_name(soup: BeautifulSoup) -> str:
    # Prefer semantic h1
    el = soup.select_one("h1[class*='Typography_display'], h1")
    if el:
        t = _clean(el.get_text(" ", strip=True))
        if t:
            return t
    # Fallback og:title
    og = soup.select_one("meta[property='og:title']")
    if og and og.get("content"):
        return _clean(og.get("content"))
    # Title
    if soup.title:
        return _clean(soup.title.get_text())
    return "Unknown Product"

def _extract_price_from_next(next_data: dict) -> Tuple[Optional[str], str]:
    # Walk nested dict for a price-like number
    txt = json.dumps(next_data)
    # prefer sale/price cents if exposed
    m = re.search(r'"price"\s*:\s*(\d+(?:\.\d+)?)', txt)
    if not m:
        m = re.search(r'"salePrice"\s*:\s*(\d+(?:\.\d+)?)', txt)
    if m:
        price = f"${m.group(1)}"
        return price, "__next_data__"
    return None, "none"

def _extract_price_dom(soup: BeautifulSoup) -> Tuple[Optional[str], str]:
    # Primary style on this site
    el = soup.select_one("span[class*='Typography_display'][class*='text-base-orange']")
    if el:
        m = _parse_money(el.get_text())
        if m:
            return m, "kw-orange-span"
    # Heuristic
    bodytxt = _clean(soup.get_text(" ", strip=True))
    m = _parse_money(bodytxt)
    if m:
        return m, "heuristic"
    return None, "none"

def _detect_stock_from_next(next_data: dict) -> Tuple[Optional[bool], str]:
    txt = json.dumps(next_data).lower()
    if '"instock":true' in txt or '"in_stock":true' in txt:
        return True, "__next_data__ inStock"
    if '"instock":false' in txt or '"in_stock":false' in txt:
        return False, "__next_data__ outOfStock"
    return None, ""

def _detect_stock_dom(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
    # "Add to cart" button visible/disabled
    for btn in soup.find_all("button"):
        t = _clean(btn.get_text())
        if not t:
            continue
        l = t.lower()
        if "add to cart" in l:
            if btn.has_attr("disabled"):
                return False, "Add to cart disabled"
            return True, "Add to cart available"
        if "out of stock" in l or "sold out" in l or "unavailable" in l:
            return False, t
    # Scan body
    body = _clean(soup.get_text(" ", strip=True)).lower()
    for w in ("out of stock", "unavailable", "sold out"):
        if w in body:
            return False, w.title()
    return None, ""

def _strip_tags_keep_newlines(html_fragment: str) -> str:
    # Convert <li> to bulleted lines, <br>/<p> to newlines, drop tags
    s = html_fragment
    # list items → bullets
    s = re.sub(r"\s*<li[^>]*>\s*", "\n• ", s, flags=re.I)
    s = re.sub(r"\s*</li>\s*", "", s, flags=re.I)
    # headings to plain lines
    s = re.sub(r"\s*<h[1-6][^>]*>\s*", "\n", s, flags=re.I)
    s = re.sub(r"\s*</h[1-6]>\s*", "\n", s, flags=re.I)
    # paragraph / breaks to newlines
    s = re.sub(r"\s*<p[^>]*>\s*", "\n", s, flags=re.I)
    s = re.sub(r"\s*</p>\s*", "\n", s, flags=re.I)
    s = re.sub(r"\s*<br\s*/?>\s*", "\n", s, flags=re.I)
    # strip remaining tags
    s = re.sub(r"<[^>]+>", " ", s)
    # unescape entities and clean
    s = html.unescape(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    return _clean(re.sub(r"\n{3,}", "\n\n", s)).strip()

def _best_description_text(soup: BeautifulSoup) -> str:
    """
    1) Use the visible HTML description container (after clicking 'View More' via browser instructions).
    2) Else, use any .pdp-description / data-testid*='description' container we can find.
    3) Else, heuristically capture the 'Key Features' UL block if present.
    """
    # Primary known container
    primary = soup.select_one("div.html-container.pdp-description")
    if primary:
        txt = _strip_tags_keep_newlines(str(primary))
        if txt:
            return txt

    # Secondary containers
    for sel in ("div.pdp-description", "[data-testid*='description']"):
        tag = soup.select_one(sel)
        if tag:
            txt = _strip_tags_keep_newlines(str(tag))
            if txt:
                return txt

    # Heuristic: look for 'Key Features' heading and grab the next UL
    html_text = str(soup)
    m = re.search(r"(<h2[^>]*>\s*Key\s+Features\s*:?\s*</h2>\s*<ul[\s\S]*?</ul>)", html_text, flags=re.I)
    if m:
        txt = _strip_tags_keep_newlines(m.group(1))
        if txt:
            # Prepend a short lead if we can find a preceding paragraph
            lead = ""
            pm = re.search(r"(<p[^>]*>[\s\S]{40,800}?</p>)\s*<h2[^>]*>\s*Key\s+Features", html_text, flags=re.I)
            if pm:
                lead = _strip_tags_keep_newlines(pm.group(1))
            return (lead + ("\n" if lead else "") + txt).strip()

    return ""  # if truly nothing

# ----- Image helpers (normalize, pick dominant family, download) -----
def _next_image_to_origin(u: str) -> str:
    try:
        pu = urlparse(u)
        if pu.path.startswith("/_next/image"):
            qs = parse_qs(pu.query)
            if "url" in qs and qs["url"]:
                return unquote(qs["url"][0])
    except Exception:
        pass
    return u

def _bump_img_transform(url: str) -> str:
    try:
        pu = urlparse(url)
        if "kitchenware.com.au" not in (pu.netloc or ""):
            return url
        path = pu.path or ""
        path2 = re.sub(r"w_(\d+)", "w_2000", path)
        if path2 != path:
            return urlunparse((pu.scheme, pu.netloc, path2, pu.params, pu.query, pu.fragment))
    except Exception:
        pass
    return url

def _parse_srcset(srcset: str) -> Optional[str]:
    best_url, best_w = None, -1
    for part in (srcset or "").split(","):
        part = part.strip()
        m = re.match(r"(\S+)\s+(\d+)w", part)
        if not m: 
            continue
        u, w = m.group(1), int(m.group(2))
        if w >= best_w:
            best_w, best_url = w, u
    return best_url

def _image_family_key(url: str) -> str:
    fname = os.path.basename(urlparse(url).path).lower()
    stem = os.path.splitext(fname)[0]
    stem = re.sub(r'_(\d{3,4}(?:x\d{3,4})?|[12]\d{3}px)$', '', stem)
    stem = re.sub(r'[-_](\d{1,3})$', '', stem)
    stem = re.sub(r'[-_]+', '-', stem)
    return stem.strip('-_')

def _pick_dominant_family(urls: List[str]) -> List[str]:
    def last_num(u: str):
        base = os.path.splitext(os.path.basename(urlparse(u).path))[0].lower()
        m = re.search(r'[-_](\d{1,3})(?:_[a-z]+)?$', base)
        return int(m.group(1)) if m else None
    def run_score(arr: List[str]) -> int:
        nums = [n for n in (last_num(u) for u in arr) if n is not None]
        if not nums: return 0
        s = set(nums); best = 0
        for n in s:
            if (n-1) not in s:
                cur = 1
                while (n+cur) in s:
                    cur += 1
                best = max(best, cur)
        return best
    buckets: Dict[str, Dict] = {}
    for i, u in enumerate(urls):
        k = _image_family_key(u)
        buckets.setdefault(k, {"urls": [], "first_idx": i})
        buckets[k]["urls"].append(u)
    best_key, best_tuple = None, None
    for k, v in buckets.items():
        group = v["urls"]
        score = (len(group), run_score(group), -v["first_idx"])
        if best_tuple is None or score > best_tuple:
            best_tuple = score
            best_key = k
    return buckets[best_key]["urls"] if best_key else urls

def _collect_images_from_html(soup: BeautifulSoup, max_images: Optional[int]) -> List[str]:
    candidates: List[str] = []
    # Thumbs first
    for img in soup.select("div.swiper-wrapper img"):
        src = (img.get("src") or "").strip()
        srcset = (img.get("srcset") or "").strip()
        cand = src or _parse_srcset(srcset) or ""
        if not cand:
            continue
        cand = _next_image_to_origin(cand)
        if cand.startswith("http"):
            candidates.append(cand)
    # Fallback: any domain images
    if not candidates:
        for img in soup.select("img"):
            u = (img.get("src") or "").strip()
            if not u:
                continue
            u = _next_image_to_origin(u)
            if u.startswith("http") and "kitchenware.com.au" in u:
                candidates.append(u)
    if not candidates:
        return []
    
    # Step 1: HQ normalize + dedupe by EXACT filename (removes carousel duplicates)
    uniq: List[str] = []
    seen = set()
    for u in candidates:
        nu = _bump_img_transform(u)
        # Extract just the filename from the path for deduplication
        path = urlparse(nu).path or ""
        filename = os.path.basename(path).lower()
        
        if filename and filename not in seen:
            seen.add(filename)
            uniq.append(nu)
    
    # Step 2: Pick dominant product family (removes cross-variant images like White vs Navy Blue)
    chosen = _pick_dominant_family(uniq)
    
    if max_images:
        chosen = chosen[:max_images]
    return chosen

# ---- image downloads (direct → proxy fallback) ----
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
            "http":  f"http://{OXY_USER}:{OXY_PASS}@realtime.oxylabs.io:60000",
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
        # decide extension (normalize webp -> jpg)
        ext = ".jpg"
        m = re.search(r"[.?](jpg|jpeg|png|webp|avif)(?:$|[?&])", img_url, re.I)
        if m:
            ext_map = {"webp": "jpg"}
            ext = "." + ext_map.get(m.group(1).lower(), m.group(1).lower())
        stem = os.path.splitext(os.path.basename(urlparse(img_url).path))[0]
        filekey = stem if stem else hashlib.sha1(img_url.encode("utf-8")).hexdigest()[:16]
        fname = f"{idx:02d}_{_safe_name(filekey)}{ext}"
        dest = folder / fname
        if _download_image_direct(img_url, dest, referer) or _download_image_via_proxy(img_url, dest, referer):
            saved_paths.append(str(dest))
    return saved_paths

# -----------------------------
# Scraper entry
# -----------------------------
def scrape_kitchenwarehouse(url: str, max_images: Optional[int] = 10) -> dict:
    """
    Scrape Kitchenware AU product page via Oxylabs WSAPI using:
      - render='html' with browser_instructions to expand description
      - DOM & __NEXT_DATA__ parsing for price/stock
      - High-res image gathering with filename-family filtering
      - Unique folder per run: <slug>_<safe name>_<stable_id>_<UTCSTAMP>
    """
    url, _ = urldefrag(url)
    slug = _slug_from_host(url)
    stable_id = _stable_id_from_url(url)

    ts = _utc_stamp()
    folder = DATA_DIR / f"{slug}_{_safe_name(_extract_name(BeautifulSoup('', 'lxml')) or 'product')}_{stable_id}_{ts}"  # temp; replaced after we know the name
    # Build render-first request with browser instructions to click "View More"
    session_id = f"sess-{int(time.time())}"
    browser_instructions = [
        # small scrolls to let lazy blocks mount
        {"type": "scroll", "x": 0, "y": 800},
        {"type": "wait", "wait_time_s": 0.6},
        {"type": "scroll", "x": 0, "y": 1600},
        {"type": "wait", "wait_time_s": 0.6},
        # Try to click the "View More" button near description
        {"type": "click", "selector": "button:has(span:contains('View More'))", "strict": False},
        {"type": "wait", "wait_time_s": 0.8},
        # Fallback click variants (class-only)
        {"type": "click", "selector": "div.html-container.pdp-description + button", "strict": False},
        {"type": "wait", "wait_time_s": 0.6},
    ]

    # 1) Rendered attempt with clicks
    try:
        html_text = _wsapi_get_html(
            url, render="html", session_id=session_id,
            browser_instructions=browser_instructions, geo=GEO, parse=False
        )
    except Exception:
        # 2) Rendered (no clicks)
        html_text = _wsapi_get_html(url, render="html", session_id=session_id, geo=GEO, parse=False)

    # 3) If for any reason still not helpful, try non-rendered once
    if not html_text or "<" not in html_text:
        html_text = _wsapi_get_html(url, render=None, session_id=session_id, geo=GEO, parse=False)

    soup = BeautifulSoup(html_text, "lxml")

    # Name (final)
    name = _extract_name(soup)

    # Price (prefer __NEXT_DATA__ then DOM)
    price, price_src = None, "none"
    next_data = _extract_next_json(soup)
    if next_data:
        price, price_src = _extract_price_from_next(next_data)
    if not price:
        price, price_src = _extract_price_dom(soup)

    # Stock
    in_stock, stock_text = _detect_stock_from_next(next_data) if next_data else (None, "")
    if in_stock is None:
        in_stock, stock_text = _detect_stock_dom(soup)

    # Description
    description = _best_description_text(soup)

    # Images
    image_urls = _collect_images_from_html(soup, max_images=max_images)

    # Final folder now that we know name
    folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}_{ts}"
    _ensure_dir(folder)
    images = _download_images_auto(image_urls, folder, referer="https://www.kitchenware.com.au/")

    out = {
        "source_url": url,
        "name": name,
        "price": price or "N/A",
        "price_source": price_src,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_count": len(images),
        "images": images,
        "folder": str(folder),
        "mode": "wsapi (render+browser_instructions)",
        "timestamp_utc": ts,
    }
    return out

# # -----------------------------
# # CLI demo
# # -----------------------------
# if __name__ == "__main__":
#     URL = "https://www.kitchenware.com.au/product/laura-ashley-elveden-electric-kettle-1-7l-navy-blue-and-silver"
#     result = scrape_kitchenwarehouse(URL, max_images=10)
#     print(json.dumps(result, indent=2, ensure_ascii=False))
