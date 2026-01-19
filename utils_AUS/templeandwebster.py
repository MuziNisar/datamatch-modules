
# -*- coding: utf-8 -*-
# templeandwebster_wsapi.py — Oxylabs WSAPI scraper (render + browser_instructions)
# Python 3.9+  |  pip install requests beautifulsoup4 lxml

from __future__ import annotations
import os, re, json, time, base64, hashlib, html
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from urllib.parse import urlparse, urldefrag, unquote

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# =========================
# Config & Credentials
# =========================
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
ACCEPT_LANG = "en-AU,en;q=0.9"
GEO = "Australia"
WSAPI_URL = "https://realtime.oxylabs.io/v1/queries"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data_au"        # keep your original path
DATA_DIR.mkdir(parents=True, exist_ok=True)

SITE_TAG = "templeandwebster"

# Put creds in oxylabs_secrets.py (preferred over env vars)
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = os.getenv("OXY_USER")
    OXY_PASS = os.getenv("OXY_PASS")

# =========================
# Helpers
# =========================
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _clean_multiline(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _safe_name(s: str) -> str:
    s = _clean(s)
    return re.sub(r"[^\w.\-]+", "_", s)[:120] or "product"

def _stable_id_from_url(url: str) -> str:
    try:
        u, _ = urldefrag(url)
        path = urlparse(u).path.strip("/").split("/")
        last = (path[-1] if path else "") or u
        return re.sub(r"[^\w\-]+", "", last) or hashlib.sha1(u.encode()).hexdigest()[:12]
    except Exception:
        return hashlib.sha1(url.encode()).hexdigest()[:12]

def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

def _dedupe_preserve(seq: List[str]) -> List[str]:
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x); out.append(x)
    return out

def _parse_aud(text: str) -> Optional[Tuple[float, str, str]]:
    """
    Returns (value_float, currency, display_string) e.g. (179.99, 'AUD', '179.99 AUD')
    """
    if not text: return None
    m = re.search(r"A\$\s*([\d.,]+)", text) or re.search(r"\$\s*([\d.,]+)", text)
    if not m:
        m = re.search(r"\b([\d.,]+)\b", text)
    if not m: return None
    raw = m.group(1).replace(",", "")
    try:
        val = float(raw)
    except Exception:
        return None
    return val, "AUD", f"{val:.2f} AUD"

def _first_jsonld_product_or_offer(soup: BeautifulSoup) -> dict:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(tag.string or "")
        except Exception:
            continue
        arr = obj if isinstance(obj, list) else [obj]
        for it in arr:
            if not isinstance(it, dict): continue
            if it.get("@type") in {"Product", "Offer"}:
                return it
            # scan @graph if present
            if isinstance(it.get("@graph"), list):
                for g in it["@graph"]:
                    if isinstance(g, dict) and g.get("@type") in {"Product", "Offer"}:
                        return g
    return {}

def _best_text(el) -> str:
    return _clean(el.get_text(" ", strip=True)) if el else ""

def _is_taw_product_image(u: str) -> bool:
    # Temple & Webster typically: img.zcdn.com.au with /lf/ or /image/
    if not u: return False
    u = u.lower()
    return ("img.zcdn.com.au/" in u) and ("/lf/" in u or "/image/" in u)

def _ext_from_content_type(ct: Optional[str], fallback: str = ".jpg") -> str:
    ct = (ct or "").lower()
    if "jpeg" in ct or "jpg" in ct: return ".jpg"
    if "png"  in ct: return ".png"
    if "webp" in ct: return ".webp"
    if "gif"  in ct: return ".gif"
    if "avif" in ct: return ".avif"
    return fallback

# =========================
# WSAPI Core
# =========================
class WSAPIError(RuntimeError): ...
def _wsapi_request(payload: dict, timeout: int = 120) -> dict:
    if not (OXY_USER and OXY_PASS):
        raise RuntimeError("Missing Oxylabs credentials (OXY_USER/OXY_PASS).")
    r = requests.post(WSAPI_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
    if 400 <= r.status_code < 500:
        try: err = r.json()
        except Exception: err = {"message": r.text}
        raise WSAPIError(f"{r.status_code} from WSAPI: {err}")
    r.raise_for_status()
    return r.json()

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
        if not c: continue
        if isinstance(c, bytes):
            try: return c.decode("utf-8", "replace")
            except Exception: continue
        if not isinstance(c, str): continue
        s = c
        # data:text/html;base64,...
        if s.startswith("data:text/html"):
            try: meta, data = s.split(",", 1)
            except ValueError:
                data, meta = s, ""
            if ";base64" in meta:
                try: return base64.b64decode(data).decode("utf-8", "replace")
                except Exception: pass
            return unquote(data)
        # base64-like blob heuristic
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
        "render": render,     # "html" to execute JS
        "parse": False,       # parse locally
        # headers are generally not needed, UA is handled by user_agent_type
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

# =========================
# Local Parsers (Temple & Webster)
# =========================
def _extract_name(soup: BeautifulSoup) -> str:
    # JSON-LD name preferred if present
    jld = _first_jsonld_product_or_offer(soup)
    if jld and jld.get("name"):
        t = _clean(str(jld["name"]))
        if t: return t

    # DOM fallbacks
    el = soup.select_one(".pdp_product_title .prod_name, h1.pdp_product_title, h1[itemprop='name'], h1")
    if el:
        t = _best_text(el)
        if t: return t

    if soup.title:
        return _clean(soup.title.get_text().split("|")[0])

    return "Unknown Product"

def _extract_price_and_stock(soup: BeautifulSoup) -> Tuple[str, Optional[float], str, Optional[bool], str, str]:
    """
    Returns: (price_str, price_value, currency, in_stock, stock_text, price_source)
    """
    jld = _first_jsonld_product_or_offer(soup)

    price_value: Optional[float] = None
    currency: Optional[str] = None
    price_str, price_source = "N/A", "none"
    in_stock, stock_text = None, ""

    # Price from JSON-LD
    if jld:
        offers = jld.get("offers")
        offer = offers if isinstance(offers, dict) else (offers[0] if isinstance(offers, list) and offers else None)
        if offer and isinstance(offer, dict):
            try:
                price_value = float(str(offer.get("price", "")).replace(",", ""))
                currency = offer.get("priceCurrency", "AUD") or "AUD"
            except Exception:
                pass
            # stock from JSON-LD
            avail = str(offer.get("availability", "")).lower()
            if "instock" in avail:
                in_stock, stock_text = True, "InStock (JSON-LD)"
            elif any(x in avail for x in ["outofstock", "soldout", "oos"]):
                in_stock, stock_text = False, "OutOfStock (JSON-LD)"

    # Price from DOM if needed
    if price_value is None:
        price_el = soup.select_one('[data-qa="dynamic_sku_price_qa"], [data-id="dynamic-sku-price"], .price, [class*="price"]')
        if not price_el:
            price_el = soup.find(lambda t: t.name in ("span", "div") and t.get_text() and "$" in t.get_text())
        if price_el:
            parsed = _parse_aud(_best_text(price_el))
            if parsed:
                price_value, currency, price_str = parsed
                price_source = "onsite"

    if price_value is not None and currency:
        price_str = f"{price_value:.2f} {currency}"
        if price_source == "none":
            price_source = "jsonld"

    # Stock from DOM if still unknown
    if in_stock is None:
        stock_el = soup.select_one('[data-qa="text-available-stocks"], .js-stock-count.stock_count')
        if stock_el:
            txt = _best_text(stock_el)
            tl = txt.lower()
            if "in stock" in tl or "stock in australia" in tl:
                in_stock, stock_text = True, txt
            elif any(k in tl for k in ["out of stock", "unavailable", "sold out"]):
                in_stock, stock_text = False, txt
        if in_stock is None:
            body = _clean(soup.get_text(" ", strip=True)).lower()
            if "in stock" in body:
                in_stock, stock_text = True, "In Stock"
            elif any(w in body for w in ["out of stock", "unavailable", "sold out"]):
                in_stock, stock_text = False, "Unavailable"

    return price_str, price_value, (currency or "AUD"), in_stock, stock_text, price_source

def _extract_description(soup: BeautifulSoup) -> str:
    parts: List[str] = []

    # JSON-LD description first if present
    jld = _first_jsonld_product_or_offer(soup)
    if jld and jld.get("description"):
        parts.append(_clean_multiline(html.unescape(str(jld["description"]))))

    # Main description / features blocks (common selectors)
    desc_box = soup.select_one("div.description, .product_details, #productDescription, div[data-qa='product-description']")
    if desc_box:
        # turn <br> into newlines
        for br in desc_box.find_all("br"):
            br.replace_with("\n")
        # pull a headline if present
        head = desc_box.select_one(".pdp-description-title, .emphasis, .product_details h2, .product_details h3")
        if head:
            parts.append(_clean_multiline(head.get_text("\n", strip=True)))
        # features list
        features_ul = desc_box.select_one("ul.product_features_wrapper, ul, .features-list")
        if features_ul:
            items = [li.get_text(" ", strip=True) for li in features_ul.select("li")]
            items = [i for i in items if i]
            if items:
                parts.append("Features:\n- " + "\n- ".join(items))
        # fallback: entire box text if we still have little
        if len("\n\n".join(parts)) < 80:
            parts.append(_clean_multiline(desc_box.get_text("\n", strip=True)))

    description = _clean_multiline("\n\n".join([p for p in parts if p]))
    return description

def _collect_images(soup: BeautifulSoup, max_images: Optional[int]) -> List[str]:
    """
    Collect product images (keep original server sizes). Temple & Webster often uses:
      .js-pdp-main-image-thumbnail img.car_item
      img.car_item
      .pdp_main_carousel img
    """
    urls: List[str] = []
    for img in soup.select(".js-pdp-main-image-thumbnail img.car_item, img.car_item, .pdp_main_carousel img"):
        # prefer data-src/data-srcset/srcset/src
        src = (img.get("data-src") or img.get("data-srcset") or img.get("srcset") or img.get("src") or "").strip()
        if not src:
            continue
        # srcset-like → take first URL token
        if " " in src:
            src = src.split()[0]
        if _is_taw_product_image(src):
            urls.append(src)

    urls = _dedupe_preserve(urls)
    if max_images is not None:
        urls = urls[:max_images]
    return urls

# =========================
# Image download (direct → proxy fallback)
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
        # keep server extension when known (normalize jpeg→jpg)
        ext = ".jpg"
        m = re.search(r"\.(jpg|jpeg|png|webp|gif|avif)(?:$|\?)", img_url, re.I)
        if m:
            ext = "." + m.group(1).lower().replace("jpeg", "jpg")
        fname = f"{idx:02d}{ext}"
        dest = folder / fname
        if _download_image_direct(img_url, dest, referer) or _download_image_via_proxy(img_url, dest, referer):
            saved_paths.append(str(dest))
    return saved_paths

# =========================
# Scraper entry (WSAPI)
# =========================
def scrape_templeandwebster(url: str, max_images: Optional[int] = None, geo: str = GEO) -> Dict:
    """
    WSAPI flow:
      1) Rendered HTML with small scrolls (integer waits only)
      2) Fallback: rendered without instructions
      3) Fallback: non-rendered
    Then parse DOM+JSON-LD; download images with proxy fallback; unique timestamped folder.
    """
    url, _ = urldefrag(url)
    session_id = f"sess-{int(time.time())}"
    ts = _utc_stamp()

    # Browser instructions (integers only)
    browser_instructions = [
        {"type": "scroll", "x": 0, "y": 800},
        {"type": "wait", "wait_time_s": 1},
        {"type": "scroll", "x": 0, "y": 1600},
        {"type": "wait", "wait_time_s": 1},
    ]

    # 1) Rendered with instructions
    try:
        html_text = _wsapi_get_html(
            url, render="html", session_id=session_id,
            browser_instructions=browser_instructions, geo=geo
        )
    except Exception:
        # 2) Rendered without instructions
        try:
            html_text = _wsapi_get_html(url, render="html", session_id=session_id, geo=geo)
        except Exception:
            html_text = ""

    # 3) Non-render fallback if needed
    if not html_text or "<" not in html_text:
        html_text = _wsapi_get_html(url, render=None, session_id=session_id, geo=geo)

    soup = BeautifulSoup(html_text or "", "lxml")

    # Name / Price / Stock / Description
    name = _extract_name(soup)
    price_str, price_value, currency, in_stock, stock_text, price_source = _extract_price_and_stock(soup)
    description = _extract_description(soup)
    image_urls = _collect_images(soup, max_images=max_images)

    # Output folder
    folder = DATA_DIR / f"{SITE_TAG}_{_safe_name(name)}_{_stable_id_from_url(url)}_{ts}"
    folder.mkdir(parents=True, exist_ok=True)

    images = _download_images_auto(image_urls, folder, referer=url)

    return {
        "url": url,
        "name": name,
        "price": price_str,
        "price_value": price_value,
        "currency": currency,
        "price_source": price_source,
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

# # =========================
# # CLI
# # =========================
# if __name__ == "__main__":
#     TEST_URL = "https://www.templeandwebster.com.au/Laura-Ashley-Elveden-1.7L-Dome-Kettle-LAUE1152.html"
#     data = scrape_templeandwebster(TEST_URL, max_images=12, geo="Australia")
#     print(json.dumps(data, indent=2, ensure_ascii=False))
