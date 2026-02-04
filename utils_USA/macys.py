




# macys.py
# Python 3.13 compatible
# Version: 2.0 - Fixed stock detection to prioritize DOM over JSON-LD
# Deps: requests, beautifulsoup4, lxml (recommended)
# Uses Oxylabs Realtime Web Scraper API (rendered HTML) with creds from oxylabs_secrets.py

import json
import os
import re
import time
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any, Iterable
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

__version__ = "2.0"

# =============================
# Secrets (put your creds in oxylabs_secrets.py)
# =============================
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception as e:
    raise RuntimeError("Missing oxylabs_secrets.py with OXY_USER and OXY_PASS") from e

# =============================
# Config
# =============================
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_GEO = "United States"
RENDER_MODE = "html"
OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data1"
DATA_DIR.mkdir(parents=True, exist_ok=True)

REQUEST_TIMEOUT = 90
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0

# Debug mode - set to True to save HTML for inspection
DEBUG_SAVE_HTML = True

# =============================
# Helpers
# =============================
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


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
        qs = parse_qs(urlparse(url).query)
        if "ID" in qs and qs["ID"]:
            return f"ID-{qs['ID'][0]}"
        path = (urlparse(url).path or "").strip("/")
        segs = [p for p in path.split("/") if p]
        if segs:
            return segs[-1]
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _parse_money(s: str) -> Optional[str]:
    s = _clean(s)
    m = re.search(r"(\$?\s*\d[\d,]*(?:\.\d{2})?)", s)
    if m:
        val = m.group(1).replace(" ", "")
        return val if val.startswith("$") else f"${val}"
    return None


def _pick_largest_from_srcset(srcset: str) -> Optional[str]:
    try:
        parts = [p.strip() for p in (srcset or "").split(",") if p.strip()]
        best_url, best_w = None, -1
        for part in parts:
            m = re.match(r"(.+?)\s+(\d+)w", part)
            if m:
                url, w = m.group(1).strip(), int(m.group(2))
                if w > best_w:
                    best_url, best_w = url, w
            else:
                best_url = part
        return best_url
    except Exception:
        return None


def _scene7_hq_macys(url: str, wid: int = 2000) -> str:
    try:
        u = urlparse(url)
        q = parse_qs(u.query)
        q["wid"] = [str(wid)]
        q["hei"] = [str(wid)]
        q["fmt"] = ["pjpeg"]
        q.setdefault("qlt", ["90"])
        new_q = urlencode({k: v[0] for k, v in q.items()})
        return urlunparse((u.scheme, u.netloc, u.path, u.params, new_q, ""))
    except Exception:
        return url


def _stable_image_key(url: str) -> str:
    try:
        path = urlparse(url).path or ""
        m = re.search(r"/MCY/(?:products/\d+/optimized/)?([A-Za-z0-9]+_fpx)", path)
        if m:
            return m.group(1).lower()
        fname = os.path.basename(path)
        stem = os.path.splitext(fname)[0]
        if stem:
            return stem.lower()
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _download_image(session: requests.Session, url: str, dest: Path) -> bool:
    try:
        r = session.get(url, timeout=45)
        if r.ok:
            dest.write_bytes(r.content)
            return True
    except Exception:
        pass
    return False


# ---------- JSON helpers ----------
def _json_iter(obj):
    """Yield every dict/list node inside a JSON structure."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _json_iter(v)
    elif isinstance(obj, list):
        for it in obj:
            yield from _json_iter(it)


def _load_json_scripts(soup: BeautifulSoup) -> list:
    """Collect JSON payloads from script tags."""
    payloads = []
    
    for sc in soup.select('script[type="application/ld+json"]'):
        txt = sc.get_text() or ""
        if not txt.strip():
            continue
        try:
            payloads.append(json.loads(txt))
        except Exception:
            pass
            
    for sc in soup.find_all("script"):
        t = (sc.get("type") or "").lower()
        sid = (sc.get("id") or "").lower()
        if sid == "__next_data__" or sid == "__NEXT_DATA__": 
            txt = sc.get_text() or ""
            if txt.strip():
                try:
                    payloads.append(json.loads(txt))
                except Exception:
                    pass
            continue
        if t == "application/json":
            txt = sc.get_text() or ""
            if txt.strip():
                try:
                    payloads.append(json.loads(txt))
                except Exception:
                    pass
    return payloads


# =============================
# Oxylabs Realtime helpers
# =============================
def _oxy_payload_for_url(url: str) -> Dict[str, Any]:
    return {
        "source": "universal",
        "url": url,
        "render": RENDER_MODE,
        "geo_location": DEFAULT_GEO,
        "user_agent": UA,
    }


def _post_realtime_one(session: requests.Session, url: str) -> dict:
    payload = _oxy_payload_for_url(url)
    attempt = 0
    while True:
        attempt += 1
        resp = session.post(
            OXY_ENDPOINT,
            json=payload,
            timeout=REQUEST_TIMEOUT,
            auth=(OXY_USER, OXY_PASS),
        )
        if resp.status_code == 401:
            raise RuntimeError("Oxylabs Unauthorized (401). Check OXY_USER/OXY_PASS in oxylabs_secrets.py")
        if resp.ok:
            try:
                return resp.json()
            except Exception as e:
                raise RuntimeError(f"Oxylabs response not JSON: {e}; text head: {resp.text[:200]}")
        if attempt >= MAX_RETRIES:
            raise RuntimeError(f"Oxylabs realtime failed: HTTP {resp.status_code} - {resp.text[:400]}")
        time.sleep(RETRY_BACKOFF * attempt)


def _result_content_or_error(res: dict, requested_url: Optional[str] = None) -> str:
    if isinstance(res, dict) and isinstance(res.get("results"), list) and res["results"]:
        items = res["results"]
        selected = None
        if requested_url:
            for it in items:
                if isinstance(it, dict) and it.get("url") == requested_url:
                    selected = it
                    break
        if selected is None:
            selected = items[0]
        status = selected.get("status_code", 0)
        if status != 200:
            raise RuntimeError(f"Bad Oxylabs response: {status} {selected.get('error') or selected.get('message') or ''}")
        if "content" not in selected:
            raise RuntimeError("Oxylabs response (results[0]) missing 'content'")
        return selected["content"]

    status = res.get("status_code", 0)
    if status != 200:
        raise RuntimeError(f"Bad Oxylabs response: {status} {res.get('error') or res.get('message') or ''}")
    if "content" not in res:
        raise RuntimeError("Oxylabs response missing 'content'")
    return res["content"]


# =============================
# Macy's parsers
# =============================
def _extract_name(soup: BeautifulSoup) -> str:
    h1 = soup.select_one("h1.product-title")
    if h1:
        brand = ""
        prod = ""
        lab = h1.select_one("label a.link, label .link, a.brand-link")
        name_node = h1.select_one('[itemprop="name"], span[itemprop="name"], span.product-name, .pdp-title, .product-name')
        if lab:
            brand = _clean(lab.get_text(" ", strip=True))
        if name_node:
            prod = _clean(name_node.get_text(" ", strip=True))
        if not prod:
            raw = _clean(h1.get_text(" ", strip=True))
            if brand and raw.lower().startswith(brand.lower()):
                prod = raw[len(brand):].strip(" –-|")
            else:
                prod = raw
        if brand and prod and brand.lower() not in prod.lower():
            return f"{brand} – {prod}"
        return prod or brand or "Unknown Product"

    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        title = _clean(og["content"])
        for sep in [" – ", " — ", " | ", " - "]:
            if sep in title:
                return title
        return title

    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.get_text() or "null")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if isinstance(obj, dict) and obj.get("@type") == "Product":
                nm = _clean(obj.get("name") or "")
                if nm:
                    return nm
    return "Unknown Product"


def _extract_price(soup: BeautifulSoup) -> Tuple[str, str]:
    aria = soup.select_one('.price-wrapper span[aria-label*="Current Price"]')
    if aria and aria.get("aria-label"):
        money = _parse_money(aria["aria-label"])
        if money:
            return money, "macys-aria"

    wrap = soup.select_one("div.price-wrapper")
    if wrap:
        money = _parse_money(_clean(wrap.get_text(" ", strip=True)))
        if money:
            return money, "macys-price-wrapper"

    ogp = soup.select_one('meta[property="og:price:amount"], meta[name="price"]')
    if ogp and ogp.get("content"):
        money = _parse_money(ogp["content"])
        if money:
            return money, "og:price"

    pmeta = soup.select_one("[itemprop='price'], meta[itemprop='price']")
    if pmeta:
        val = pmeta.get("content") or _clean(pmeta.get_text(" ", strip=True))
        money = _parse_money(val)
        if money:
            return money, "microdata"

    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.get_text() or "null")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if isinstance(obj, dict) and obj.get("@type") in ("Product", "Offer", "AggregateOffer"):
                offers = obj.get("offers")
                if isinstance(offers, dict) and offers.get("price"):
                    m = _parse_money(str(offers["price"]))
                    if m:
                        return m, "jsonld"
                if isinstance(offers, list):
                    for o in offers:
                        if isinstance(o, dict) and o.get("price"):
                            m = _parse_money(str(o["price"]))
                            if m:
                                return m, "jsonld"

    buybox = soup.find(lambda tag: tag.name in ("section", "div") and tag.find("button", string=lambda t: t and "Add To Bag" in t))
    if buybox:
        m = _parse_money(_clean(buybox.get_text(" ", strip=True)))
        if m:
            return m, "heuristic-buybox"

    return "N/A", "none"


def _detect_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
    """
    Priority:
      1) DOM: "Currently Unavailable" text in error-color div (HIGHEST PRIORITY)
      2) DOM: Add To Bag button
      3) Body text patterns
      4) Next.js / app-state
      5) JSON-LD (Last resort - often outdated/cached)
    Returns: (True/False/None, context_text)
    """
    # ============================================================
    # (1) DOM Checks - Error messages (HIGHEST PRIORITY)
    # These are the MOST RELIABLE indicators on Macy's
    # ============================================================
    
    # Check for error-color divs with unavailable text
    for err_div in soup.select("div.error-color, .error-color"):
        txt = _clean(err_div.get_text(" ", strip=True)).lower()
        if any(pattern in txt for pattern in ["unavailable", "sorry", "out of stock", "sold out"]):
            return False, f"Error message: {txt}"
    
    # Also check for any element with "error-color" class
    err_elements = soup.find_all(class_=lambda c: c and "error-color" in str(c))
    for el in err_elements:
        txt = _clean(el.get_text(" ", strip=True)).lower()
        if any(pattern in txt for pattern in ["unavailable", "sorry", "out of stock", "sold out"]):
            return False, f"Error element: {txt}"
    
    # Check for data-testid or other specific unavailable indicators
    unavail_indicators = soup.select('[data-testid*="unavailable"], [class*="unavailable"], [class*="out-of-stock"]')
    for el in unavail_indicators:
        return False, "Unavailable indicator found"

    # ============================================================
    # (2) Check for "Add To Bag" button
    # ============================================================
    add_btn = soup.find("button", string=lambda t: t and "Add To Bag" in t)
    if add_btn:
        if add_btn.has_attr("disabled"):
            return False, "Add To Bag disabled"
        aria_dis = add_btn.get("aria-disabled")
        if aria_dis and aria_dis.lower() in ("true", "1"):
            return False, "Add To Bag disabled (aria)"
        return True, "Add To Bag present"
    
    # Check for any button containing "Add to Bag" text (case insensitive)
    for btn in soup.find_all("button"):
        btn_text = _clean(btn.get_text(" ", strip=True)).lower()
        if "add to bag" in btn_text:
            if btn.has_attr("disabled") or btn.get("aria-disabled", "").lower() in ("true", "1"):
                return False, "Add To Bag disabled"
            return True, "Add To Bag present"

    # ============================================================
    # (3) Check body text for unavailable patterns
    # Do this BEFORE checking JSON data
    # ============================================================
    body_txt = _clean(soup.get_text(" ", strip=True)).lower()
    unavailable_patterns = [
        "sorry, this item is currently unavailable",
        "currently unavailable",
        "this item is unavailable",
        "item is unavailable",
        "sold out",
        "out of stock",
        "temporarily unavailable",
    ]
    for pattern in unavailable_patterns:
        if pattern in body_txt:
            return False, f"Body text: {pattern}"

    # ============================================================
    # (4) Next.js / app-state flags
    # ============================================================
    next_flags = {"in_stock": None, "purchasable": None, "availability": None, "availability_status": None}
    for root in _load_json_scripts(soup):
        for node in _json_iter(root):
            if not isinstance(node, dict):
                continue
            for k in list(node.keys()):
                lk = str(k).lower()
                v = node[k]
                if lk in ("instock", "in_stock", "isinstock"):
                    if isinstance(v, bool):
                        next_flags["in_stock"] = v
                if lk in ("purchasable", "isavailable", "available"):
                    if isinstance(v, bool):
                        next_flags["purchasable"] = v
                if lk in ("availability",):
                    if isinstance(v, str):
                        next_flags["availability"] = v.lower()
                if lk in ("availabilitystatus", "availability_status", "stockstatus", "stock_status"):
                    if isinstance(v, str):
                        next_flags["availability_status"] = str(v).lower()

    # Check for explicit out of stock in Next data FIRST
    if (next_flags["availability"] and "out" in next_flags["availability"]) or \
       (next_flags["availability_status"] and ("out" in next_flags["availability_status"] or "sold" in next_flags["availability_status"])):
        return False, "Next-data indicates out-of-stock"
    
    if next_flags["in_stock"] is True or next_flags["purchasable"] is True:
        return True, "Next-data indicates available"

    # ============================================================
    # (5) JSON-LD availability (LOWEST PRIORITY - often outdated!)
    # Only use this if we found NO other indicators
    # ============================================================
    for root in _load_json_scripts(soup):
        objs = root if isinstance(root, list) else [root]
        for obj in _json_iter(objs):
            if isinstance(obj, dict) and obj.get("@type") == "Product":
                offers = obj.get("offers")
                cand = []
                if isinstance(offers, dict):
                    cand = [offers]
                elif isinstance(offers, list):
                    cand = [o for o in offers if isinstance(o, dict)]
                for off in cand:
                    av = (off.get("availability") or "").lower()
                    # Check OutOfStock BEFORE InStock
                    if "outofstock" in av or "out_of_stock" in av:
                        return False, "availability: OutOfStock (JSON-LD)"
                    if "instock" in av:
                        # JSON-LD says in stock - this is a WEAK signal
                        # We should have caught DOM errors above if item is actually unavailable
                        return True, "availability: InStock (JSON-LD)"
                    if "preorder" in av:
                        return None, "availability: PreOrder (JSON-LD)"

    return None, ""


def _extract_description(soup: BeautifulSoup) -> str:
    def norm_line(t: str) -> str:
        t = _clean(t)
        t = re.sub(r"^[•\-\u2022]+\s*", "", t).strip()
        t = re.sub(r"\s*[•\-\u2022]+\s*$", "", t).strip()
        t = re.sub(r"\s{2,}", " ", t)
        return t

    def dedupe_keep_order(lines: List[str]) -> List[str]:
        seen, out = set(), []
        for ln in lines:
            key = re.sub(r"[^\w]+", "", ln).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(ln)
        return out

    # (1) Next/app-state JSON
    bullets_json: List[str] = []
    paras_json: List[str] = []
    for root in _load_json_scripts(soup):
        for node in _json_iter(root):
            if not isinstance(node, dict):
                continue
            if node.get("@type") == "Product" or "productId" in node or "skuId" in node or "purchasable" in node:
                for key in ("bullets", "features", "highlights"):
                    if isinstance(node.get(key), list):
                        for v in node[key]:
                            if isinstance(v, str):
                                line = norm_line(v)
                                if line:
                                    bullets_json.append(line)
                for key in ("longDescription", "shortDescription", "description"):
                    v = node.get(key)
                    if isinstance(v, str) and _clean(v):
                        paras_json.append(_clean(v))

    bullets_json = dedupe_keep_order([b for b in bullets_json if b])
    if bullets_json:
        return "\n".join(f"• {t}" for t in bullets_json)

    paras_json = dedupe_keep_order([p for p in paras_json if p])
    if paras_json:
        return _clean(" ".join(paras_json))

    # (2) JSON-LD Product.description
    for root in _load_json_scripts(soup):
        objs = root if isinstance(root, list) else [root]
        for obj in _json_iter(objs):
            if isinstance(obj, dict) and obj.get("@type") == "Product":
                desc = obj.get("description")
                if isinstance(desc, str) and _clean(desc):
                    return _clean(desc)
                if isinstance(desc, list):
                    lines = [norm_line(x) for x in desc if isinstance(x, str) and norm_line(x)]
                    if lines:
                        return "\n".join(f"• {t}" for t in dedupe_keep_order(lines))

    # (3) DOM
    bullets_dom, paras_dom = [], []
    for li in soup.select('[data-auto="product-summary-section"] li'):
        t = norm_line(li.get_text(" ", strip=True))
        if t:
            bullets_dom.append(t)

    container = soup.select_one('[data-auto="product-long-description-section"]') or soup.select_one("#product-details-drawer-slideout-body")
    if container:
        for li in container.select("li"):
            t = norm_line(li.get_text(" ", strip=True))
            if t:
                bullets_dom.append(t)
        for p in container.select("p"):
            t = _clean(p.get_text(" ", strip=True))
            if t:
                paras_dom.append(t)

    DROP_PATTERNS = [
        r"^request warranty information$",
        r"^imported$",
        r"^made in .*",
        r"^warranty.*available.*",
    ]
    keep = []
    for t in bullets_dom:
        low = t.lower()
        if any(re.search(p, low) for p in DROP_PATTERNS):
            continue
        keep.append(t)
    keep = dedupe_keep_order(keep)
    if keep:
        return "\n".join(f"• {t}" for t in keep)

    paras_dom = dedupe_keep_order([_clean(p) for p in paras_dom if _clean(p)])
    if paras_dom:
        return _clean(" ".join(paras_dom))

    # (4) Meta description
    meta = soup.select_one('meta[name="description"]')
    if meta and meta.get("content"):
        return _clean(meta["content"])

    return ""


def _collect_images(soup: BeautifulSoup, max_images: Optional[int] = None) -> List[str]:
    def _process_and_return(candidates: List[str]) -> List[str]:
        if not candidates:
            return []
        
        filtered = []
        for u in candidates:
            u = u.strip()
            if not u:
                continue
            if u.startswith("//"):
                u = "https:" + u
            if u.lower().startswith("data:"):
                continue
            filtered.append(u)

        def _normalize(u: str) -> str:
            if "is/image/MCY/" in u:
                return _scene7_hq_macys(u, wid=2000)
            return u

        normalized = [_normalize(u) for u in filtered]

        seen, norm = set(), []
        for u in normalized:
            key = _stable_image_key(u)
            if key in seen:
                continue
            seen.add(key)
            norm.append(u)

        def _family_digits(u: str) -> Optional[str]:
            path = urlparse(u).path or ""
            m = re.search(r"/MCY/(?:products/\d+/optimized/)?(\d+)_fpx", path)
            if m:
                return m.group(1)
            stem = os.path.splitext(os.path.basename(path))[0]
            m2 = re.search(r"(\d{6,})", stem or "")
            return m2.group(1) if m2 else None

        chosen = norm
        
        def _sort_key(u: str):
            fd = _family_digits(u) or ""
            try:
                return (int(fd[:-2]) if len(fd) > 2 else 0,
                        int(fd[-2:]) if len(fd) >= 2 else 0)
            except Exception:
                return (0, 0)

        chosen.sort(key=_sort_key)
        if max_images:
            chosen = chosen[:max_images]
        return chosen

    # 1) JSON-LD & OpenGraph (High Priority)
    candidates_meta: List[str] = []
    
    def _push_jsonld_images(obj):
        imgs = obj.get("image")
        if isinstance(imgs, str):
            candidates_meta.append(imgs)
        elif isinstance(imgs, list):
            for u in imgs:
                if isinstance(u, str):
                    candidates_meta.append(u)

    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.get_text() or "null")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if isinstance(obj, dict) and obj.get("@type") == "Product":
                _push_jsonld_images(obj)
            if isinstance(obj, dict) and "@graph" in obj and isinstance(obj["@graph"], list):
                for g in obj["@graph"]:
                    if isinstance(g, dict) and g.get("@type") == "Product":
                        _push_jsonld_images(g)

    for ogi in soup.select('meta[property="og:image"], meta[name="og:image"]'):
        u = ogi.get("content")
        if u:
            candidates_meta.append(u)
            
    if candidates_meta:
        return _process_and_return(candidates_meta)

    # 2) Rails (Medium Priority)
    candidates_rails: List[str] = []
    for rail_sel in ("ul.alt-desktop-images", "ul.v-carousel-container"):
        rail = soup.select_one(rail_sel)
        if not rail:
            continue
        for im in rail.select("picture img, img"):
            u = im.get("data-src") or im.get("src")
            if u:
                candidates_rails.append(u)
        for src in rail.select("picture source[srcset]"):
            best = _pick_largest_from_srcset(src.get("srcset"))
            if best:
                candidates_rails.append(best)
    
    if candidates_rails:
        return _process_and_return(candidates_rails)

    # 3) Regex Scans (Low Priority)
    candidates_regex: List[str] = []
    for sc in soup.find_all("script"):
        ttype = sc.get("type")
        if ttype == "application/ld+json":
            continue
        txt = sc.string or sc.get_text() or ""
        if not txt or ("_fpx" not in txt and "is/image/MCY/" not in txt and "macysassets.com" not in txt):
            continue
        for m in re.finditer(r'https?:\/\/[^\s\'"]+?(?:_fpx|is\/image\/MCY\/)[^\s\'"]*', txt):
            candidates_regex.append(m.group(0))

    return _process_and_return(candidates_regex)


# =============================
# Single-page scrape via Oxylabs
# =============================
def scrape_macys_oxylabs(url: str, max_images: Optional[int] = 12, verbose: bool = False) -> Dict[str, Any]:
    slug = _slug_from_host(url) or "macys"
    stable_id = _stable_id_from_url(url)
    
    if verbose:
        print(f"Fetching {url}...")

    with requests.Session() as s:
        s.headers.update({"User-Agent": UA})
        res = _post_realtime_one(s, url)
        html = _result_content_or_error(res, requested_url=url)
        soup = BeautifulSoup(html, "lxml")

        name = _extract_name(soup)
        folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}"
        folder.mkdir(parents=True, exist_ok=True)
        
        # DEBUG: Save HTML for inspection
        if DEBUG_SAVE_HTML:
            (folder / "debug_page.html").write_text(html, encoding="utf-8")
            if verbose:
                print(f"  DEBUG: HTML saved to {folder / 'debug_page.html'}")

        price, price_source = _extract_price(soup)
        in_stock, stock_text = _detect_stock(soup)
        description = _extract_description(soup)

        if verbose:
            print(f"  Name: {name}")
            print(f"  Price: {price}")
            print(f"  In Stock: {in_stock}")
            print(f"  Stock Text: {stock_text}")

        image_urls = _collect_images(soup, max_images=max_images or 7)
        saved_paths: List[str] = []
        for idx, img_url in enumerate(image_urls, start=1):
            ext = ".jpg"
            m = re.search(r"[.?](jpg|jpeg|png|webp|tif|tiff)(?:$|[?&])", img_url, re.I)
            if m:
                ext_map = {"tif": "jpg", "tiff": "jpg"}
                ext = "." + ext_map.get(m.group(1).lower(), m.group(1).lower())
            fname = f"{idx:02d}{ext}"
            dest = folder / fname
            if _download_image(s, img_url, dest):
                saved_paths.append(str(dest))

        out = {
            "url": url,
            "name": name,
            "price": price,
            "price_source": price_source if price != "N/A" else "none",
            "in_stock": in_stock,
            "stock_text": stock_text or "",
            "description": description,
            "image_count": len(saved_paths),
            "images": saved_paths,
            "folder": str(folder),
        }
        (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        return out


# =============================
# Batch scraping
# =============================
def _scrape_one_url_with_session(session: requests.Session, url: str, max_images: Optional[int]) -> Dict[str, Any]:
    try:
        res = _post_realtime_one(session, url)
        html = _result_content_or_error(res, requested_url=url)
        soup = BeautifulSoup(html, "lxml")

        name = _extract_name(soup)
        slug = _slug_from_host(url) or "macys"
        stable_id = _stable_id_from_url(url)
        folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}"
        folder.mkdir(parents=True, exist_ok=True)

        price, price_source = _extract_price(soup)
        in_stock, stock_text = _detect_stock(soup)
        description = _extract_description(soup)
        image_urls = _collect_images(soup, max_images=max_images or 7)

        saved_paths: List[str] = []
        for idx, img_url in enumerate(image_urls, start=1):
            ext = ".jpg"
            m = re.search(r"[.?](jpg|jpeg|png|webp|tif|tiff)(?:$|[?&])", img_url, re.I)
            if m:
                ext_map = {"tif": "jpg", "tiff": "jpg"}
                ext = "." + ext_map.get(m.group(1).lower(), m.group(1).lower())
            fname = f"{idx:02d}{ext}"
            dest = folder / fname
            if _download_image(session, img_url, dest):
                saved_paths.append(str(dest))

        out = {
            "url": url,
            "name": name,
            "price": price,
            "price_source": price_source if price != "N/A" else "none",
            "in_stock": in_stock,
            "stock_text": stock_text or "",
            "description": description,
            "image_count": len(saved_paths),
            "images": saved_paths,
            "folder": str(folder),
        }
        (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        return out

    except Exception as e:
        return {"url": url, "error": str(e)}


def scrape_macys_batch_oxylabs(
    urls: Iterable[str],
    max_images: Optional[int] = 12,
    threads: int = 0
) -> List[Dict[str, Any]]:
    urls = [u for u in urls if u]
    results_all: List[Dict[str, Any]] = []

    if not urls:
        return results_all

    if threads and threads > 1:
        with requests.Session() as s:
            s.headers.update({"User-Agent": UA})
            with ThreadPoolExecutor(max_workers=threads) as ex:
                fut_to_url = {
                    ex.submit(_scrape_one_url_with_session, s, url, max_images): url
                    for url in urls
                }
                for fut in as_completed(fut_to_url):
                    results_all.append(fut.result())
        return results_all

    with requests.Session() as s:
        s.headers.update({"User-Agent": UA})
        for url in urls:
            results_all.append(_scrape_one_url_with_session(s, url, max_images))
    return results_all


# =============================
# Backward-compatible alias
# =============================
def scrape_macys(url: str, headless: bool = False, country_code: Optional[str] = None,
                 zip_code: Optional[str] = None, max_images: Optional[int] = None) -> dict:
    return scrape_macys_oxylabs(url, max_images=(max_images or 7))


# # =============================
# # CLI
# # =============================
# if __name__ == "__main__":
#     test_urls = [
#         "https://www.macys.com/shop/product/laura-ashley-floral-print-5-speed-300-watt-hand-mixer?ID=21262908&swatchColor=Elveden%20Navy",
#     ]

#     print(json.dumps(scrape_macys_oxylabs(test_urls[0], max_images=20, verbose=True), indent=2, ensure_ascii=False))