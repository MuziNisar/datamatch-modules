# -*- coding: utf-8 -*-
# Python 3.9+  |  pip install requests beautifulsoup4 lxml

from __future__ import annotations
import os, re, json, base64, random, html, time
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from urllib.parse import urldefrag, urlsplit, urljoin, unquote

import requests
from bs4 import BeautifulSoup

# =========================
# Load credentials
# =========================
from oxylabs_secrets import OXY_USER, OXY_PASS
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS
# except Exception:
#     OXY_USER = os.getenv("OXY_USER", "")
#     OXY_PASS = os.getenv("OXY_PASS", "")
# if not (OXY_USER and OXY_PASS):
#     raise RuntimeError("Set Oxylabs credentials in oxylabs_secrets.py or env (OXY_USER/OXY_PASS)")

# =========================
# Config
# =========================
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
ACCEPT_LANG = "en-AU,en;q=0.9"
WSAPI_URL = "https://realtime.oxylabs.io/v1/queries"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR  = BASE_DIR / "data_au"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SITE_TAG = "binglee"

# =========================
# Site selectors (fallback HTML parsing)
# =========================
SEL_NAME   = "h1.text-blue.heading"
SEL_PRICE  = "span.heading.text-blue.text-5xl"
SEL_GALLERY_IMGS = "div.pdp-image-carousel-nav img"

# =========================
# Helpers
# =========================
def _run_id() -> str:
    # e.g., 20251030-203512-AB3F
    return time.strftime("%Y%m%d-%H%M%S") + "-" + "".join(random.choices("0123456789ABCDEF", k=4))

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
    u, _ = urldefrag(url)
    parts = urlsplit(u).path.rstrip("/").split("/")
    return (parts[-1] or str(abs(hash(url)) % (10**12))) if parts else str(abs(hash(url)) % (10**12))

def _dedupe_preserve(urls: List[str]) -> List[str]:
    seen, out = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u); out.append(u)
    return out

def _parse_money(s: str) -> Optional[str]:
    if not s: return None
    s = _clean(s)
    m = re.search(r"\$?\s?(\d[\d,]*)(?:\.(\d{2}))?", s)
    if not m: return None
    dollars = m.group(1).replace(",", "")
    cents = m.group(2) if m.group(2) is not None else "00"
    return f"${dollars}.{cents}"

def _price_text_to_float(s: str) -> Optional[float]:
    if not s: return None
    s = s.replace(",", "")
    m = re.search(r"\$?\s?(\d+)(?:\.(\d{2}))?", s)
    if not m: return None
    whole, cents = m.group(1), (m.group(2) or "00")
    try:
        return float(f"{whole}.{cents}")
    except Exception:
        return None

def _normalize_cf_variant(u: str) -> str:
    return re.sub(r"/cdn-cgi/image/[^/]+/", "/", u)

def _parse_srcset(srcset: str) -> Optional[str]:
    if not srcset: return None
    best_url, best_w = None, -1
    for url, w in re.findall(r'(\S+)\s+(\d+)w', srcset):
        try:
            width = int(w)
        except ValueError:
            continue
        if width >= best_w:
            best_w, best_url = width, url
    return best_url

def _best_text(el) -> str:
    return _clean(el.get_text(" ", strip=True)) if el else ""

def _attr_chain(tag, *attrs) -> Optional[str]:
    if not tag: return None
    for a in attrs:
        v = tag.get(a)
        if v: return v
    return None

def _ext_from_content_type(ct: Optional[str], fallback: str = ".jpg") -> str:
    ct = (ct or "").lower()
    if "jpeg" in ct or "jpg" in ct: return ".jpg"
    if "png"  in ct: return ".png"
    if "webp" in ct: return ".webp"
    if "gif"  in ct: return ".gif"
    if "avif" in ct: return ".avif"
    return fallback

# =========================
# WSAPI helpers
# =========================
def _wsapi_request(payload: dict, timeout: int = 90) -> dict:
    r = requests.post(WSAPI_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
    if 400 <= r.status_code < 500:
        try:
            err = r.json()
        except Exception:
            err = {"message": r.text}
        raise requests.HTTPError(f"{r.status_code} from WSAPI Realtime: {err}", response=r)
    r.raise_for_status()
    return r.json()

def _extract_html_from_result(res0: dict) -> str:
    candidates = [
        res0.get("content"),
        res0.get("page_content"),
        res0.get("rendered_html"),
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
        if s.startswith("data:text/html"):
            try: meta, data = s.split(",", 1)
            except ValueError:
                data, meta = s, ""
            if ";base64" in meta:
                try: return base64.b64decode(data).decode("utf-8", "replace")
                except Exception: pass
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

def _parsing_instructions_binglee() -> dict:
    # Oxylabs Custom Parser format: pipelines with _fns
    return {
        "name": {
            "_fns": [
                {"_fn": "css_one", "_args": ["h1.text-blue.heading, h1"]},
                {"_fn": "element_text"}
            ]
        },
        "price_text": {
            "_fns": [
                {"_fn": "css_one", "_args": ["span.heading.text-blue.text-5xl"]},
                {"_fn": "element_text"}
            ]
        },
        "body": {
            "_fns": [
                {"_fn": "xpath_one", "_args": ["/html/body"]},
                {"_fn": "element_text"}
            ]
        },
        "desc": {
            "_fns": [
                {"_fn": "css_one", "_args": [".pdp-cms-block"]},
                {"_fn": "element_text"}
            ]
        },

        # Broad image coverage (gallery containers + OG)
        "imgs_srcset":        {"_fns": [{"_fn": "xpath", "_args": [
            "//div[contains(@class,'pdp-image') or contains(@class,'image-carousel') or contains(@class,'gallery')]//img/@srcset"
        ]}]},
        "imgs_src":           {"_fns": [{"_fn": "xpath", "_args": [
            "//div[contains(@class,'pdp-image') or contains(@class,'image-carousel') or contains(@class,'gallery')]//img/@src"
        ]}]},
        "imgs_data_srcset":   {"_fns": [{"_fn": "xpath", "_args": [
            "//div[contains(@class,'pdp-image') or contains(@class,'image-carousel') or contains(@class,'gallery')]//img/@data-srcset"
        ]}]},
        "imgs_data_src":      {"_fns": [{"_fn": "xpath", "_args": [
            "//div[contains(@class,'pdp-image') or contains(@class,'image-carousel') or contains(@class,'gallery')]//img/@data-src"
        ]}]},
        "og_images":          {"_fns": [{"_fn": "xpath", "_args": [
            "//meta[@property='og:image']/@content | //meta[@name='og:image']/@content | //meta[@property='og:image:secure_url']/@content"
        ]}]},

        # JSON-LD
        "jsonld": {
            "_fns": [
                {"_fn": "xpath", "_args": ["//script[@type='application/ld+json']/text()"]}
            ]
        }
    }

def _wsapi_parse(url: str, geo: str, render: Optional[str], session_id: Optional[str]) -> dict:
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": geo,
        "user_agent_type": "desktop_chrome",
        "parse": True,
        "parsing_instructions": _parsing_instructions_binglee(),
    }
    if session_id:
        payload["session_id"] = session_id  # top-level, per WSAPI
    if render:
        payload["render"] = render          # "html" | "mhtml" | "png"
    data = _wsapi_request(payload)
    results = data.get("results") or []
    if not results:
        raise RuntimeError("WSAPI returned no results")
    res0 = results[0]
    parsed = res0.get("parsed_data") or res0.get("parsed") or res0.get("content")
    if isinstance(parsed, str):
        try: parsed = json.loads(parsed)
        except Exception: parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    html_text = _extract_html_from_result(res0)
    return {"parsed": parsed, "html": html_text}

# =========================
# Local HTML parser (fallback)
# =========================
def parse_binglee_html(html_text: str) -> Dict:
    soup = BeautifulSoup(html_text, "lxml")

    el = soup.select_one(SEL_NAME) or soup.select_one("h1")
    name = _best_text(el) or (_clean(soup.title.get_text().split("|")[0]) if soup.title else "") or "Unknown_Product"

    pel = soup.select_one(SEL_PRICE) or soup.find(lambda t: t.name in ("span","div") and "$" in t.get_text())
    money = _parse_money(_best_text(pel)) if pel else None
    price_text = f"{money.replace('$','')} AUD" if money else "N/A"

    # Description
    desc_parts: List[str] = []
    cms = soup.select_one(".pdp-cms-block")
    if cms:
        raw = cms.decode_contents()
        raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\\1>", "", raw)
        raw = re.sub(r"(?i)<br\\s*/?>", "\n", raw)
        text = re.sub(r"<[^>]+>", " ", raw)
        cleaned = _clean_multiline(html.unescape(text))
        if cleaned:
            desc_parts.append(cleaned)
    description = _clean_multiline("\n\n".join([d for d in desc_parts if d]))

    # Images (broad)
    imgs: List[str] = []
    search_scope = soup.select_one(".pdp-image, .pdp-image-carousel, .image-carousel, .gallery") or soup

    for img in search_scope.select("img"):
        srcset = img.get("srcset") or img.get("data-srcset") or ""
        best = _parse_srcset(srcset) if srcset else None
        if best: imgs.append(best)

    for img in search_scope.select("img"):
        src = img.get("src") or img.get("data-src")
        if src: imgs.append(src)

    for m in soup.select("meta[property='og:image'], meta[name='og:image'], meta[property='og:image:secure_url']"):
        content = m.get("content")
        if content:
            imgs.append(content)

    # JSON-LD images
    jsonlds = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            blob = tag.get_text() or ""
            jsonlds.append(blob)
            obj = json.loads(blob)
        except Exception:
            continue
        objs = obj if isinstance(obj, list) else [obj]
        for it in objs:
            if isinstance(it, dict):
                im = it.get("image")
                if isinstance(im, str):
                    imgs.append(im)
                elif isinstance(im, list):
                    for s in im:
                        if isinstance(s, str):
                            imgs.append(s)

    # Absolutize + dedupe
    abs_imgs = []
    seen = set()
    for u in imgs:
        au = urljoin("https://www.binglee.com.au/", u)
        key = _normalize_cf_variant(au)
        if key in seen: continue
        seen.add(key); abs_imgs.append(au)
    imgs = abs_imgs

    return {
        "name": name,
        "price_text": price_text,
        "description": description,
        "image_urls": imgs,
        "jsonld": jsonlds,
    }

# =========================
# Availability (JSON-LD)
# =========================
def _availability_from_jsonld(jsonld_list: List[str]) -> Tuple[Optional[bool], Optional[str]]:
    if not jsonld_list: return None, None
    try:
        for blob in jsonld_list:
            if not blob: continue
            obj = json.loads(blob)
            objs = obj if isinstance(obj, list) else [obj]
            for it in objs:
                nodes = []
                if isinstance(it, dict):
                    nodes.append(it)
                    if isinstance(it.get("@graph"), list):
                        nodes.extend([g for g in it["@graph"] if isinstance(g, dict)])
                for n in nodes:
                    if n.get("@type") in ("Product", "Offer"):
                        offers = n.get("offers")
                        if isinstance(offers, dict): offers = [offers]
                        if isinstance(offers, list):
                            for off in offers:
                                avail = str(off.get("availability","")).lower()
                                if "instock" in avail:  return True, "InStock (JSON-LD)"
                                if "outofstock" in avail or "soldout" in avail: return False, "OutOfStock (JSON-LD)"
    except Exception:
        pass
    return None, None

# =========================
# Image download (+ auto proxy fallback)
# =========================
def _download_images(urls: List[str], folder: Path, referer: str,
                     use_proxy: bool, timeout: int = 45) -> List[str]:
    headers = {
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Referer": referer,
    }
    proxies = None
    verify = True
    if use_proxy:
        proxies = {
            "http":  f"http://{OXY_USER}:{OXY_PASS}@realtime.oxylabs.io:60000",
            "https": f"http://{OXY_USER}:{OXY_PASS}@realtime.oxylabs.io:60000",
        }
        verify = False

    saved = []
    folder.mkdir(parents=True, exist_ok=True)
    for i, u in enumerate(urls, 1):
        try:
            with requests.get(u, headers=headers, timeout=timeout, stream=True, proxies=proxies, verify=verify) as r:
                ct = (r.headers.get("Content-Type") or "").lower()
                if r.status_code == 200 and (ct.startswith("image/") or r.content):
                    ext = _ext_from_content_type(ct, ".jpg")
                    out = folder / f"{i:02d}{ext}"
                    with open(out, "wb") as f:
                        for chunk in r.iter_content(65536):
                            if chunk: f.write(chunk)
                    saved.append(str(out))
                else:
                    print(f"  ! image HTTP {r.status_code} {u} {ct}")
        except Exception as e:
            print("  ! image error:", u, e)
    return saved

def download_images_auto(urls: List[str], folder: Path, referer: str,
                         max_images: Optional[int] = None) -> List[str]:
    if max_images is not None:
        urls = urls[:max_images]
    # Try direct first
    saved = _download_images(urls, folder, referer, use_proxy=False)
    if not saved:
        print("[images] direct fetch yielded 0 files → retrying via Proxy Endpoint…")
        saved = _download_images(urls, folder, referer, use_proxy=True, timeout=60)
    return saved

# =========================
# Orchestrator
# =========================
def scrape_binglee_wsapi(url: str,
                         download_images_flag: bool = True,
                         max_images: Optional[int] = None,
                         geo: str = "Australia") -> Dict:
    url, _ = urldefrag(url)
    session_id = f"sess-{random.randint(10_000, 99_999)}"

    # 1) WSAPI parse without rendering (omit render)
    parsed, html_text = {}, ""
    try:
        res = _wsapi_parse(url, geo=geo, render=None, session_id=session_id)
        parsed, html_text = res.get("parsed", {}), res.get("html", "") or ""
    except requests.HTTPError as e:
        print(f"[WSAPI no-render] {e}")
    except Exception as e:
        print(f"[WSAPI no-render] unexpected: {e}")

    # 2) If empty, try with JS rendering
    if not parsed:
        try:
            res = _wsapi_parse(url, geo=geo, render="html", session_id=session_id)
            parsed, html_text = res.get("parsed", {}), res.get("html", "") or ""
        except requests.HTTPError as e:
            print(f"[WSAPI render] {e}")
        except Exception as e:
            print(f"[WSAPI render] unexpected: {e}")

    # 3) If still empty but HTML available, parse locally; else last-resort direct GET
    if not parsed:
        if not html_text:
            try:
                r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": ACCEPT_LANG}, timeout=30)
                if r.status_code == 200 and "<" in r.text:
                    html_text = r.text
            except Exception:
                pass
        if html_text:
            local = parse_binglee_html(html_text)
            name = local["name"]
            price_text = local["price_text"]
            description = local["description"]
            imgs = [urljoin(url, u) for u in local["image_urls"]]
            jsonld_list = local.get("jsonld", [])
        else:
            raise RuntimeError("No usable HTML from WSAPI or direct request")
    else:
        name = _clean(parsed.get("name") or "")
        price_raw_text = _clean(parsed.get("price_text") or "")
        money = _parse_money(price_raw_text)
        price_text = f"{money.replace('$','')} AUD" if money else ("N/A" if not price_raw_text else price_raw_text)
        description = _clean_multiline(parsed.get("desc") or "")

        # Images via srcset/src/data-srcset/data-src + OG + JSON-LD
        candidates: List[str] = []
        for s in (parsed.get("imgs_srcset") or []):
            best = _parse_srcset(s)
            if best: candidates.append(best)
        for s in (parsed.get("imgs_src") or []):
            if s: candidates.append(s)
        for s in (parsed.get("imgs_data_srcset") or []):
            best = _parse_srcset(s)
            if best: candidates.append(best)
        for s in (parsed.get("imgs_data_src") or []):
            if s: candidates.append(s)
        for s in (parsed.get("og_images") or []):
            if s: candidates.append(s)

        jsonld_list = parsed.get("jsonld") or []
        for blob in jsonld_list:
            try:
                obj = json.loads(blob)
            except Exception:
                continue
            objs = obj if isinstance(obj, list) else [obj]
            for it in objs:
                if isinstance(it, dict):
                    images = it.get("image")
                    if isinstance(images, str):
                        candidates.append(images)
                    elif isinstance(images, list):
                        for im in images:
                            if isinstance(im, str):
                                candidates.append(im)

        # Absolutize + dedupe
        imgs = []
        seen = set()
        for u in candidates:
            au = urljoin(url, u)
            key = _normalize_cf_variant(au)
            if key in seen: continue
            seen.add(key); imgs.append(au)

    # 4) Availability from JSON-LD (with text heuristics fallback)
    in_stock, stock_text = _availability_from_jsonld(jsonld_list)
    if in_stock is None and html_text:
        body = _clean(BeautifulSoup(html_text, "lxml").get_text(" ", strip=True)).lower()
        if re.search(r"\bsold\s*out\b", body):
            in_stock, stock_text = False, "Sold Out"
        elif re.search(r"\badd\s+to\s+cart\b", body):
            in_stock, stock_text = True, "In Stock"

    # 5) Downloads
    imgs = _dedupe_preserve(imgs)
    folder = DATA_DIR / f"{SITE_TAG}_{_safe_name(name)}_{_stable_id_from_url(url)}_{_run_id()}"
    folder.mkdir(parents=True, exist_ok=True)

    images_downloaded: List[str] = []
    if download_images_flag and imgs:
        use = imgs[:max_images] if max_images is not None else imgs
        print(f"Downloading {len(use)} images …")
        images_downloaded = download_images_auto(use, folder, referer=url, max_images=None)

    # 6) Price object (numeric) + keep string for backward compatibility
    price_amount = _price_text_to_float(price_text) if price_text and price_text != "N/A" else None
    price_obj = {"amount": price_amount, "currency": "AUD"} if price_amount is not None else None

    return {
        "url": url,
        "name": name or "Unknown_Product",
        "price": price_text,               # human string (back-compat)
        "price_obj": price_obj,            # numeric object (new)
        "price_source": ("jsonld/onsite" if money else "onsite") if 'money' in locals() else "onsite",
        "in_stock": in_stock,              # True | False | None
        "stock_text": stock_text,          # e.g., "InStock (JSON-LD)"
        "description": description,
        "image_count": len(images_downloaded) if images_downloaded else len(imgs),
        "image_urls": imgs,
        "images_downloaded": images_downloaded,
        "folder": str(folder),
        "mode": "wsapi+fallback"
    }

# # =========================
# # CLI
# # =========================
# if __name__ == "__main__":
#     TEST_URL = "https://www.binglee.com.au/products/4-slice-toaster-china-rose-lat4cr?ref=JzRAFh"
#     data = scrape_binglee_wsapi(TEST_URL, download_images_flag=True, max_images=None, geo="Australia")
#     print(json.dumps(data, indent=2, ensure_ascii=False))
