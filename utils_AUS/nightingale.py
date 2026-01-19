# # nightingalecc_scraper.py
# # Python 3.10+  |  Playwright (sync)
# # pip install playwright
# # playwright install

# import json
# import os
# import re
# import time
# import hashlib
# from pathlib import Path
# from urllib.parse import urlparse, urljoin

# from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# # -----------------------------
# # Config
# # -----------------------------
# UA = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
# )
# VIEWPORT = {"width": 1400, "height": 900}
# LOCALE = "en-AU"
# TIMEZONE = "Australia/Sydney"

# BASE_DIR = Path(__file__).resolve().parent
# DATA_DIR = BASE_DIR / "Data1"

# ANTI_AUTOMATION_JS = r"""
# Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
# """

# # -----------------------------
# # Helpers
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

# def _ensure_dir(p: Path): p.mkdir(parents=True, exist_ok=True)

# def _wait_idle(page, timeout_ms=15000, settle_ms=500):
#     try:
#         page.wait_for_load_state("networkidle", timeout=timeout_ms)
#     except PlaywrightTimeoutError:
#         pass
#     time.sleep(settle_ms / 1000)

# def _parse_money(s: str) -> str | None:
#     s = _clean(s)
#     m = re.search(r"\$?\s?(\d[\d,]*)(?:\.(\d{2}))?", s)
#     if not m:
#         return None
#     dollars = m.group(1).replace(",", "")
#     cents = m.group(2) if m.group(2) is not None else "00"
#     return f"${dollars}.{cents}"

# def _download_image(context, url: str, dest: Path) -> bool:
#     try:
#         r = context.request.get(url, timeout=30000)
#         if r.ok:
#             dest.write_bytes(r.body())
#             return True
#     except Exception:
#         pass
#     return False

# # -----------------------------
# # Extraction helpers (Nightingale CC)
# # -----------------------------
# def _extract_name(page) -> str:
#     # <div class="wrapper-product-title"> <h1 itemprop="name">...</h1>
#     try:
#         page.wait_for_selector("div.wrapper-product-title h1[itemprop='name']", timeout=12000)
#         el = page.locator("div.wrapper-product-title h1[itemprop='name']").first
#         if el and el.count():
#             return _clean(el.inner_text())
#     except Exception:
#         pass
#     # fallback og:title
#     try:
#         og = page.locator('meta[property="og:title"]').first
#         if og and og.count():
#             return _clean(og.get_attribute("content") or "")
#     except Exception:
#         pass
#     return "Unknown Product"

# def _extract_price(page) -> tuple[str, str]:
#     # <div class="h1" itemprop="price" content="169"> $169.00
#     try:
#         el = page.locator("div.h1[itemprop='price']").first
#         if el and el.count():
#             money = _parse_money(el.inner_text())
#             if money:
#                 return money, "ng-itemprop-price"
#     except Exception:
#         pass
#     # heuristic fallback
#     try:
#         body = _clean(page.locator("body").inner_text())
#         money = _parse_money(body)
#         if money:
#             return money, "heuristic"
#     except Exception:
#         pass
#     return "N/A", "none"

# def _detect_stock(page) -> tuple[bool | None, str]:
#     # <span itemprop="availability" content="http://schema.org/InStock" class="badge badge-success">In Stock</span>
#     try:
#         el = page.locator("span[itemprop='availability']").first
#         if el and el.count():
#             content = (el.get_attribute("content") or "").lower()
#             text = _clean(el.inner_text()).lower()
#             if "instock" in content or "in stock" in text:
#                 return True, "In Stock"
#             if "outofstock" in content or "out of stock" in text or "sold out" in text:
#                 return False, _clean(el.inner_text())
#     except Exception:
#         pass
#     return None, ""

# def _expand_description_if_collapsed(page):
#     # The content sits inside #accordionDescription.collapse; try to open it if toggle exists
#     for sel in [
#         "a[href='#accordionDescription']",
#         "[data-target='#accordionDescription']",
#         "button[aria-controls='accordionDescription']",
#         "#headingDescription a",
#     ]:
#         try:
#             if page.locator(sel).first.count():
#                 page.locator(sel).first.click(timeout=1500)
#                 _wait_idle(page, settle_ms=300)
#                 break
#         except Exception:
#             pass

# def _extract_description(page) -> str:
#     _expand_description_if_collapsed(page)

#     bullets = []
#     paras = []
#     try:
#         # main description container
#         scope = page.locator("#accordionDescription section.productdetails").first
#         if scope and scope.count():
#             # paragraphs
#             ps = scope.locator("p")
#             for i in range(ps.count()):
#                 t = _clean(ps.nth(i).inner_text())
#                 if t:
#                     paras.append(t)
#             # list items
#             lis = scope.locator("li")
#             for i in range(lis.count()):
#                 t = _clean(lis.nth(i).inner_text())
#                 if t:
#                     bullets.append("• " + t)
#     except Exception:
#         pass

#     # dedupe preserve order
#     def _dedupe(seq):
#         seen = set(); out = []
#         for x in seq:
#             if x not in seen:
#                 seen.add(x); out.append(x)
#         return out

#     paras = _dedupe(paras)
#     bullets = _dedupe(bullets)

#     # Prefer first paragraph + bullets
#     if bullets and paras:
#         return "• " + paras[0] + "\n" + "\n".join(bullets)
#     if bullets:
#         return "\n".join(bullets)
#     return " ".join(paras[:3])

# def _collect_images(page, page_url: str, max_images: int | None = None) -> list[str]:
#     """
#     Gallery thumbnails are anchors like:
#       <a href="/assets/alt_1/LAJK17WM.jpg?2025..." rel="product_images"><img ...></a>
#     We take the <a href> (full image), absolutize it, dedupe, preserve order.
#     """
#     urls: list[str] = []
#     try:
#         thumbs = page.locator("a[rel='product_images'][data-lightbox='product-lightbox']")
#         n = thumbs.count()
#         for i in range(n):
#             href = thumbs.nth(i).get_attribute("href") or ""
#             if not href:
#                 continue
#             full = urljoin(page_url, href)
#             if full.startswith("http"):
#                 urls.append(full)
#     except Exception:
#         pass

#     # Fallback: any direct full image anchors under the known row container
#     if not urls:
#         try:
#             thumbs = page.locator("div.row.align-items-center a[href*='/assets/']")
#             n = thumbs.count()
#             for i in range(n):
#                 href = thumbs.nth(i).get_attribute("href") or ""
#                 if href:
#                     urls.append(urljoin(page_url, href))
#         except Exception:
#             pass

#     # dedupe by path (ignore cache-busting query)
#     out = []
#     seen = set()
#     for u in urls:
#         key = (urlparse(u).path or "").lower()
#         if key and key not in seen:
#             seen.add(key)
#             out.append(u)

#     if max_images:
#         out = out[:max_images]
#     return out

# # -----------------------------
# # Playwright bootstrap
# # -----------------------------
# def _prepare_context(pw, headless: bool):
#     browser = pw.chromium.launch(headless=headless)
#     context = browser.new_context(
#         user_agent=UA,
#         locale=LOCALE,
#         timezone_id=TIMEZONE,
#         viewport=VIEWPORT,
#         java_script_enabled=True,
#         device_scale_factor=1.0,
#         accept_downloads=False,
#     )
#     context.add_init_script(ANTI_AUTOMATION_JS)
#     page = context.new_page()
#     return browser, context, page

# # -----------------------------
# # Scraper entry
# # -----------------------------
# def scrape_nightingalecc(url: str, headless: bool = True, max_images: int | None = 12) -> dict:
#     """
#     Scrape Nightingale CC PDP (headless by default).
#     Saves images to Data1/nightingalecc_<safe_name>_<stable_id>/ (re-runs overwrite).
#     """
#     slug = _slug_from_host(url)  # "nightingalecc"
#     stable_id = _stable_id_from_url(url)

#     with sync_playwright() as pw:
#         browser, context, page = _prepare_context(pw, headless=headless)
#         try:
#             page.set_default_timeout(25000)
#             page.goto(url, wait_until="domcontentloaded", referer="https://www.nightingalecc.com.au/")
#             _wait_idle(page, settle_ms=600)

#             # Small scroll to trigger lazy bits
#             try:
#                 page.mouse.wheel(0, 900)
#                 time.sleep(0.25)
#             except Exception:
#                 pass
#             _wait_idle(page, settle_ms=400)

#             name = _extract_name(page)
#             price, price_source = _extract_price(page)
#             in_stock, stock_text = _detect_stock(page)
#             description = _extract_description(page)

#             image_urls = _collect_images(page, url, max_images=max_images)

#             # Folder: Data1/nightingalecc_<safe name>_<stable_id>
#             _ensure_dir(DATA_DIR)
#             folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}"
#             _ensure_dir(folder)

#             # Save images
#             saved_paths = []
#             for idx, img_url in enumerate(image_urls, start=1):
#                 # normalize extension (png/jpg/webp → keep, map webp->jpg)
#                 ext = ".jpg"
#                 m = re.search(r"[.?](jpg|jpeg|png|webp)(?:$|[?&])", img_url, re.I)
#                 if m:
#                     ext_map = {"webp": "jpg"}
#                     ext = "." + ext_map.get(m.group(1).lower(), m.group(1).lower())
#                 # filename
#                 stem = os.path.splitext(os.path.basename(urlparse(img_url).path))[0]
#                 filekey = stem if stem else hashlib.sha1(img_url.encode("utf-8")).hexdigest()[:16]
#                 fname = f"{idx:02d}_{_safe_name(filekey)}{ext}"
#                 dest = folder / fname

#                 if _download_image(context, img_url, dest):
#                     saved_paths.append(str(dest))

#             out = {
#                 "name": name,
#                 "price": price,
#                 "price_source": price_source,
#                 "in_stock": in_stock,
#                 "stock_text": stock_text,
#                 "description": description,
#                 "image_count": len(saved_paths),
#                 "images": saved_paths,
#                 "folder": str(folder),
#             }
#             return out
#         finally:
#             try: context.close()
#             except Exception: pass
#             try: browser.close()
#             except Exception: pass

# # -----------------------------
# # CLI demo
# # -----------------------------
# if __name__ == "__main__":
#     URL = "https://www.nightingalecc.com.au/laura-ashley-1.7l-jug-kettle-wild-meadow-lajk17wm"
#     result = scrape_nightingalecc(URL, headless=True, max_images=20)  # headless=True = hidden Chrome
#     print(json.dumps(result, indent=2, ensure_ascii=False))











# -*- coding: utf-8 -*-
# nightingalecc_wsapi.py — single-file Oxylabs WSAPI scraper (render + browser_instructions)
# Python 3.10+  |  pip install requests beautifulsoup4 lxml

from __future__ import annotations
import json, os, re, time, base64, hashlib, html
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from urllib.parse import urlparse, urljoin, urldefrag, urlunparse, unquote

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
DATA_DIR = BASE_DIR / "Data1"   # keep your original folder name
DATA_DIR.mkdir(parents=True, exist_ok=True)

SITE_TAG = "nightingalecc"

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

def _dedupe_preserve(seq: List[str]) -> List[str]:
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x); out.append(x)
    return out

# -----------------------------
# Oxylabs WSAPI core
# -----------------------------
class WSAPIError(RuntimeError): ...
def _wsapi_request(payload: dict, timeout: int = 120) -> dict:
    if not (OXY_USER and OXY_PASS):
        raise RuntimeError("Missing Oxylabs credentials. Create oxylabs_secrets.py with OXY_USER/OXY_PASS.")
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
        "render": render,   # "html" to execute JS
        "parse": False,     # parse locally
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
# Site-specific parsing (Nightingale CC)
# -----------------------------
def _extract_name(soup: BeautifulSoup) -> str:
    el = soup.select_one("div.wrapper-product-title h1[itemprop='name']")
    if el:
        t = _clean(el.get_text(" ", strip=True))
        if t:
            return t
    og = soup.select_one("meta[property='og:title']")
    if og and og.get("content"):
        return _clean(og["content"])
    if soup.title:
        return _clean(soup.title.get_text())
    return "Unknown Product"

def _extract_price_dom(soup: BeautifulSoup) -> Tuple[Optional[str], str]:
    # <div class="h1" itemprop="price" content="169"> $169.00
    el = soup.select_one("div.h1[itemprop='price']")
    if el:
        txt = el.get_text(" ", strip=True) or el.get("content") or ""
        m = _parse_money(txt)
        if m:
            return m, "ng-itemprop-price"
    # Heuristic
    bodytxt = _clean(soup.get_text(" ", strip=True))
    m = _parse_money(bodytxt)
    if m:
        return m, "heuristic"
    return None, "none"

def _detect_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
    el = soup.select_one("span[itemprop='availability']")
    if el:
        content = (el.get("content") or "").lower()
        text = _clean(el.get_text(" ", strip=True)).lower()
        if "instock" in content or "in stock" in text:
            return True, "In Stock"
        if "outofstock" in content or "out of stock" in text or "sold out" in text:
            return False, _clean(el.get_text(" ", strip=True))
    # fallback scan
    body = _clean(soup.get_text(" ", strip=True)).lower()
    if "sold out" in body or "out of stock" in body:
        return False, "Sold Out"
    if "add to cart" in body:
        return True, "Add to cart visible"
    return None, ""

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

def _best_description_text(soup: BeautifulSoup) -> str:
    """
    DOM-first: try #accordionDescription section.productdetails; otherwise any section.productdetails.
    Keep bullets, dedupe, return intro + bullets style.
    """
    containers = []
    node = soup.select_one("#accordionDescription section.productdetails")
    if node:
        containers.append(node)
    containers += soup.select("section.productdetails")

    # Collect paras and bullets preserving order
    paras: List[str] = []
    bullets: List[str] = []
    for n in containers:
        for bad in n.select("style,script,noscript"):
            bad.decompose()
        # paragraphs
        for p in n.select("p"):
            t = _clean(p.get_text(" ", strip=True))
            if t:
                paras.append(t)
        # list items
        for li in n.select("li"):
            t = _clean(li.get_text(" ", strip=True))
            if t:
                bullets.append("• " + t)

    # dedupe-preserve
    def _dedupe(seq: List[str]) -> List[str]:
        seen, out = set(), []
        for x in seq:
            if x and x not in seen:
                seen.add(x); out.append(x)
        return out

    paras = _dedupe(paras)
    bullets = _dedupe(bullets)

    if bullets and paras:
        return "• " + paras[0] + "\n" + "\n".join(bullets)
    if bullets:
        return "\n".join(bullets)
    if paras:
        return " ".join(paras[:3])
    # last resort: try to strip any raw container we can find
    raw = soup.select_one("#accordionDescription") or soup.select_one("div.productdescription")
    if raw:
        return _strip_tags_keep_newlines(str(raw))
    return ""

def _collect_images_from_html(soup: BeautifulSoup, base: str, max_images: Optional[int]) -> List[str]:
    """
    Gallery thumbnails are anchors like:
      <a href="/assets/alt_1/LAJK17WM.jpg?..." rel="product_images" data-lightbox="product-lightbox">
    We take the anchor href (full image), absolutize, dedupe by path, preserve order.
    """
    urls: List[str] = []
    for a in soup.select("a[rel='product_images'][data-lightbox='product-lightbox']"):
        href = (a.get("href") or "").strip()
        if href:
            full = urljoin(base, href)
            if full.startswith("http"):
                urls.append(full)

    if not urls:
        for a in soup.select("div.row.align-items-center a[href*='/assets/']"):
            href = (a.get("href") or "").strip()
            if href:
                urls.append(urljoin(base, href))

    # dedupe by path (ignore query)
    out, seen = [], set()
    for u in urls:
        key = (urlparse(u).path or "").lower()
        if key and key not in seen:
            seen.add(key)
            out.append(u)

    if max_images is not None:
        out = out[:max_images]
    return out

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
        # extension guess (normalize webp → jpg)
        ext = ".jpg"
        m = re.search(r"[.?](jpg|jpeg|png|webp|gif|avif)(?:$|[?&])", img_url, re.I)
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
def scrape_nightingalecc(url: str, max_images: Optional[int] = 12) -> dict:
    """
    Scrape Nightingale CC PDP via Oxylabs WSAPI using:
      - render='html' with browser_instructions to open the description accordion
      - DOM parsing for name/price/stock/description
      - Full image anchors collection with de-dup
      - Unique folder per run: <slug>_<safe name>_<stable_id>_<UTCSTAMP>
    """
    url, _ = urldefrag(url)
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    slug = _slug_from_host(url)
    stable_id = _stable_id_from_url(url)
    ts = _utc_stamp()
    session_id = f"sess-{int(time.time())}"

    # Browser instructions — ALL waits are integers (WSAPI requires int)
    browser_instructions = [
        {"type": "scroll", "x": 0, "y": 800},
        {"type": "wait", "wait_time_s": 1},
        {"type": "scroll", "x": 0, "y": 1600},
        {"type": "wait", "wait_time_s": 1},
        # Try to open the description accordion
        {"type": "click", "selector": "a[href='#accordionDescription']", "strict": False},
        {"type": "wait", "wait_time_s": 1},
        {"type": "click", "selector": "[data-target='#accordionDescription']", "strict": False},
        {"type": "wait", "wait_time_s": 1},
        {"type": "click", "selector": "button[aria-controls='accordionDescription']", "strict": False},
        {"type": "wait", "wait_time_s": 1},
    ]

    # 1) Rendered attempt with clicks
    try:
        html_text = _wsapi_get_html(
            url, render="html", session_id=session_id,
            browser_instructions=browser_instructions, geo=GEO
        )
    except Exception:
        # 2) Rendered (no clicks)
        html_text = _wsapi_get_html(url, render="html", session_id=session_id, geo=GEO)

    # 3) Non-render fallback
    if not html_text or "<" not in html_text:
        html_text = _wsapi_get_html(url, render=None, session_id=session_id, geo=GEO)

    soup = BeautifulSoup(html_text or "", "lxml")

    # Name
    name = _extract_name(soup)

    # Price
    price, price_src = _extract_price_dom(soup)
    if not price:
        price, price_src = "N/A", "none"

    # Stock
    in_stock, stock_text = _detect_stock(soup)

    # Description
    description = _best_description_text(soup)

    # Images
    image_urls = _collect_images_from_html(soup, base, max_images=max_images)

    # Final folder (after we know the name)
    folder = DATA_DIR / f"{SITE_TAG}_{_safe_name(name)}_{stable_id}_{ts}"
    _ensure_dir(folder)
    images = _download_images_auto(image_urls, folder, referer="https://www.nightingalecc.com.au/")

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
#     URL = "https://www.nightingalecc.com.au/laura-ashley-1.7l-jug-kettle-wild-meadow-lajk17wm"
#     result = scrape_nightingalecc(URL, max_images=20)
#     print(json.dumps(result, indent=2, ensure_ascii=False))
