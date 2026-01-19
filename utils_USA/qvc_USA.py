








# qvc_USA.py
# Python 3.9+ | Oxylabs Real-Time Crawler (source="universal") + BeautifulSoup

import os, re, json, html as ihtml, time, random, hashlib, io
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any, Iterable
from urllib.parse import urlsplit, urlunsplit
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag
from PIL import Image  # pip install pillow

# ========= Secrets =========
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception as e:
    raise RuntimeError("Missing oxylabs_secrets.py with OXY_USER and OXY_PASS") from e

# ========= Paths / Config =========
try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()
SAVE_DIR = BASE_DIR / "data1"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

UA_STR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)
CURRENCY_SYMBOL = {"USD": "$","GBP":"£","EUR":"€","CAD":"C$","AUD":"A$"}

# Oxylabs
OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"
REQUEST_TIMEOUT = 90
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0  # seconds
DEFAULT_GEO = "United States"

# ========= Helpers =========
def _clean_plain(s: str) -> str:
    s = ihtml.unescape(s or "")
    s = s.replace("\r","")
    s = re.sub(r"[ \t]+"," ",s)
    s = re.sub(r"\n{3,}","\n\n",s)
    return s.strip()

def _strip_rating_boilerplate(s: str, name: str = "") -> str:
    if not s: return s
    s = s.replace("\xa0"," ")
    if name and s.lower().startswith(name.lower()):
        s = s[len(name):].lstrip(" \n:-—")
    drops = (r"out of 5 stars", r"average rating value", r"Same page link",
             r"Read\s+\d+\s+Reviews?", r"Read a Review")
    kept, prev = [], False
    for ln in s.splitlines():
        l = ln.strip()
        if any(re.search(p, l, re.I) for p in drops):
            prev = True; continue
        if prev and re.fullmatch(r"\d+(?:\.\d+)?", l):
            prev = False; continue
        if re.fullmatch(r"\(?\d+\)?", l):
            continue
        kept.append(ln)
    s = "\n".join(kept)
    return re.sub(r"\n{3,}","\n\n",s).strip()

def _strip_cta_inline(s: str) -> str:
    if not s: return s
    INLINE_PATTS = [
        r"(?i)\bmake your selection\b\s*:?(\s*[^\n]*)?",
        r"(?i)\badd to wish list\b",
        r"(?i)\bset a reminder\b",
        r"(?i)\bsave reminders?\b",
        r"(?i)\breminders?\b",
        r"(?i)\bqvc\s+app\b",
        r"(?i)\bdownload the qvc app\b",
        r"(?i)\babout the brand\b",
        r"(?i)\bitem number\s*[:#]?\s*\w+",
        r"(?i)\bshipping\s*&\s*returns\b.*",
        r"(?i)\bpolicies\b.*",
        r"(?i)\breviews?\b.*",
    ]
    out = s
    for p in INLINE_PATTS:
        out = re.sub(p, "", out).strip()
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip()

def _safe_name(name: str) -> str:
    n = re.sub(r"[^\w\s-]","", name or "").strip().replace(" ","_")
    return n or "NA"

def _drop_query(u: str) -> str:
    parts = list(urlsplit(u)); parts[3] = ""; parts[4] = ""
    return urlunsplit(parts)

def _human_delay(a=80, b=160):
    time.sleep(random.uniform(a/1000.0, b/1000.0))

def _stable_id_from_url(url: str) -> str:
    m = re.search(r"\b([A-Z]\d{5,})\b", url, re.I)
    if m:
        return m.group(1).upper()
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]

def _parse_money_with_currency(val: str, currency_code: Optional[str]) -> str:
    val = (val or "").strip()
    sym = CURRENCY_SYMBOL.get((currency_code or "").upper(), "")
    if sym and not val.startswith(sym):
        return f"{sym}{val}"
    return val or "N/A"

# ========= Oxylabs =========
def _oxy_payload_for_url(url: str) -> Dict[str, Any]:
    return {
        "source": "universal",
        "url": url,
        "render": "html",
        "geo_location": DEFAULT_GEO,
        "user_agent": UA_STR,
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
            raise RuntimeError("Oxylabs Unauthorized (401). Check OXY_USER/OXY_PASS.")
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

# ========= Field extraction (QVC) =========
def _extract_name(soup: BeautifulSoup) -> str:
    og = soup.select_one("meta[property='og:title']")
    if og and og.get("content"):
        t = re.sub(r"\s*[-–|]\s*QVC.*$", "", og["content"]).strip()
        if t:
            return t
    h1 = soup.select_one("h1")
    if h1:
        t = _clean_plain(h1.get_text(" ", strip=True))
        if t:
            return t
    if soup.title and soup.title.string:
        t = re.sub(r"\s*[-–|]\s*QVC.*$", "", soup.title.string).strip()
        if t:
            return t
    return "N/A"

def _extract_price(soup: BeautifulSoup) -> Tuple[str, Optional[str]]:
    for sc in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(sc.get_text() or "null")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for o in objs:
            if isinstance(o, dict) and o.get("@type") == "Product":
                offers = o.get("offers")
                offers = offers if isinstance(offers, list) else [offers]
                for off in offers or []:
                    if isinstance(off, dict) and off.get("price"):
                        currency = (off.get("priceCurrency") or "").upper() or None
                        price_val = str(off.get("price")).strip()
                        return _parse_money_with_currency(price_val, currency), currency
    for sel in ("span.pdpPrice.price", "[itemprop='price']", ".price"):
        node = soup.select_one(sel)
        if node:
            raw = _clean_plain(node.get_text(" ", strip=True))
            raw = re.sub(r"(?i)\bdeleted\b","", raw).strip()
            m = re.search(r"([£$€]\s?\d[\d,]*(?:\.\d{2})?)", raw)
            if m:
                return m.group(1).replace(" ",""), None
            m2 = re.search(r"(\d[\d,]*(?:\.\d{2})?)", raw)
            if m2:
                return m2.group(1), None
    return "N/A", None

def _extract_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
    # 1. Priority: Visible "Add to Cart" button
    btn = soup.select_one("#btnAddToCart")
    if btn:
        txt = _clean_plain(btn.get_text(" ", strip=True)).lower()
        # Robust disabled check
        classes = btn.get("class") or []
        if isinstance(classes, str):
            classes = [classes]
        # Check class for 'disabled' or aria-disabled
        is_disabled = any("disabled" in c.lower() for c in classes) or (btn.get("aria-disabled") in ("true", "1"))
        
        if ("add" in txt or "cart" in txt) and not is_disabled:
            return True, "Add to Cart present"

    # 2. JSON-LD fallback
    for sc in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(sc.get_text() or "null")
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for o in objs:
            if isinstance(o, dict) and o.get("@type") == "Product":
                offers = o.get("offers")
                offers = offers if isinstance(offers, list) else [offers]
                for off in offers or []:
                    if not isinstance(off, dict): continue
                    av = str(off.get("availability") or "")
                    if re.search(r"InStock", av, re.I):
                        return True, "JSON-LD availability: InStock"
                    if re.search(r"OutOfStock|SoldOut", av, re.I):
                        return False, "JSON-LD availability: OutOfStock"

    # 3. Text fallback
    body = _clean_plain(soup.get_text(" ", strip=True)).lower()
    if re.search(r"\b(out of stock|sold out|waitlist|unavailable|not available)\b", body, re.I):
        return False, "Unavailable"
    return None, ""

# ======== Description extractor (intro paragraph + bullets + specs, CTA-scrubbed) ========
def _extract_description(soup: BeautifulSoup, name: str) -> str:
    INTRO_SELECTORS = [
        ".pdShortDescTxt",
        "[data-automation='pdp-short-description']",
        ".product-detail__short-description",
        ".product-information__short-description",
        ".product-copy .copy__intro",
        "[data-automation='intro-copy']",
        "[data-testid='pdp-short-description']",
        ".short-description",
    ]
    DETAILS_ROOTS = [
        "#tab-ProductDetails",
        "[data-automation='product-details']",
        "[data-automation='long-description']",
        ".product-detail__description",
        ".product-detail__copy",
        ".product-description",
        ".descriptionWrapper",
        ".accordionText",        # QVC long copy container seen in your HTML
        "#productDescription",
        ".product-copy",
    ]
    DROP_LINE_PATTS = [
        r"^make your selection:?$",
        r"^add to wish list$",
        r"^set a reminder$",
        r"^save reminders$",
        r"^reminders?$",
        r"^\s*about the brand\s*$",
        r"^\s*item number\s*[:#].*$",
        r"^\s*shipping & returns.*$",
        r"^\s*policies.*$",
        r"^\s*reviews?$",
        r"^qvc.*app$",
    ]
    CTA_KEYWORDS = re.compile(
        r"(?i)\b(make your selection|add to wish list|set a reminder|save reminders?|reminders?|qvc\s+app)\b"
    )

    def _norm_line(t: str) -> Optional[str]:
        t = _clean_plain(t)
        if not t or len(t) < 2:
            return None
        low = t.lower().strip()
        for p in DROP_LINE_PATTS:
            if re.search(p, low, re.I):
                return None
        return t

    def _node_to_bullets(node: BeautifulSoup) -> List[str]:
        out = []
        for li in node.select("li"):
            t = _norm_line(li.get_text(" ", strip=True))
            if t:
                t = _strip_cta_inline(t)
                if t:
                    out.append(f"• {t}")
        return out

    # choose details root
    root = None
    for sel in DETAILS_ROOTS:
        r = soup.select_one(sel)
        if r:
            root = r
            break
    if root is None:
        root = soup

    # strip interactive junk in root
    for bad_sel in [
        "button",
        "a[role='button']",
        "[data-automation='reminder']",
        ".add-to-wishlist",
        ".wishlist",
        ".tuneIn",               # the 'Set a Reminder' block wrapper in your HTML
        ".tvpgOverlay",
        ".reminderLayer",
    ]:
        for bad in root.select(bad_sel):
            bad.decompose()

    # 1) short-description blocks
    intro: Optional[str] = None
    for sel in INTRO_SELECTORS:
        node = soup.select_one(sel)
        if not node:
            continue
        raw = _clean_plain(node.get_text(" ", strip=True))
        raw = _strip_rating_boilerplate(raw, name)
        raw = _strip_cta_inline(raw)
        if not raw or len(raw) < 40:
            continue
        if CTA_KEYWORDS.search(raw):
            continue
        intro = raw
        break

    # 2) FIRST TEXT BEFORE LIST — works even if it's a direct text node in .accordionText
    if not intro:
        chunks: List[str] = []
        for child in root.children:
            if isinstance(child, Tag) and child.name in ("ul", "ol"):
                break
            # collect textual content from NavigableString or Tags (like <div> with plain text)
            text = ""
            if isinstance(child, NavigableString):
                text = str(child)
            elif isinstance(child, Tag):
                # take only text, avoid nested lists
                if child.name not in ("ul", "ol"):
                    text = child.get_text(" ", strip=True)
            text = _strip_cta_inline(_strip_rating_boilerplate(_clean_plain(text), name))
            if text:
                chunks.append(text)
            # stop if we already got a solid paragraph
            if chunks and sum(len(c) for c in chunks) >= 60:
                break
        intro = _clean_plain(" ".join(chunks)) if chunks else None
        if intro and (len(intro) < 40 or CTA_KEYWORDS.search(intro)):
            intro = None

    # 3) bullets
    bullets = _node_to_bullets(root)
    seen = set(); bullets = [b for b in bullets if not (b in seen or seen.add(b))]

    # 4) specs
    specs: List[str] = []
    for tr in root.select("table tr"):
        th, td = tr.find("th"), tr.find("td")
        lab = _clean_plain(th.get_text(" ", strip=True)) if th else ""
        val = _clean_plain(td.get_text(" ", strip=True)) if td else ""
        lab = re.sub(r"\s*[:：]\s*$", "", lab)
        row = f"{lab}: {val}" if (lab and val) else ""
        row = _strip_cta_inline(row)
        if _norm_line(row):
            specs.append(row)
    seen = set(); specs = [s for s in specs if not (s in seen or seen.add(s))]

    # 5) JSON-LD fallback
    if not intro and not bullets:
        for sc in soup.select("script[type='application/ld+json']"):
            try:
                data = json.loads(sc.get_text() or "null")
            except Exception:
                continue
            arr = data if isinstance(data, list) else [data]
            for obj in arr:
                if isinstance(obj, dict) and obj.get("@type") == "Product":
                    d = _clean_plain(str(obj.get("description","")))
                    d = _strip_rating_boilerplate(d, name)
                    d = _strip_cta_inline(d)
                    if d and len(d) > 40 and not CTA_KEYWORDS.search(d):
                        intro = d
                        break
            if intro:
                break

    parts: List[str] = []
    if intro:
        parts.append(intro)
    if bullets:
        parts.append("\n".join(bullets))
    if specs:
        parts.append("\n".join(specs))

    out = "\n\n".join([p for p in parts if p.strip()]) or "N/A"
    return _strip_rating_boilerplate(_strip_cta_inline(out), name)

def _collect_images(soup: BeautifulSoup, max_images: int) -> List[str]:
    img_candidates: List[str] = []
    for a in soup.select("#imageThumbnails .imageList a.thumbcell"):
        for attr in ("data-superzoom","data-zoom","data-standard","href"):
            href = a.get(attr) or ""
            if href:
                img_candidates.append(href if href.startswith("http") else "https:" + href if href.startswith("//") else href)
                break
    if not img_candidates:
        for img in soup.select("picture img[src], .pdpMainImage img[src], img#mainProductImage[src]"):
            src = img.get("src") or ""
            if src:
                img_candidates.append(src if src.startswith("http") else "https:" + src if src.startswith("//") else src)
    seen_bases, img_urls = set(), []
    for u in img_candidates:
        b = _drop_query(u)
        if b not in seen_bases:
            seen_bases.add(b); img_urls.append(u)
        if len(img_urls) >= max_images:
            break
    return img_urls

# ======== Convert & save all images as JPG ========
def _download_images_as_jpg(urls: List[str], folder: Path, quality: int = 90) -> List[str]:
    saved = []
    folder.mkdir(parents=True, exist_ok=True)
    with requests.Session() as s:
        s.headers.update({
            "User-Agent": UA_STR,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        })
        for i, u in enumerate(urls, 1):
            try:
                r = s.get(u, timeout=25)
                if not (r.ok and r.content):
                    continue
                img_bytes = io.BytesIO(r.content)
                im = Image.open(img_bytes)
                if im.mode in ("RGBA", "LA", "P"):
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    if im.mode == "P":
                        im = im.convert("RGBA")
                    bg.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
                    im = bg
                else:
                    im = im.convert("RGB")
                out_path = folder / f"image_{i}.jpg"
                im.save(out_path, format="JPEG", quality=quality, optimize=True)
                saved.append(str(out_path))
            except Exception as e:
                try:
                    ext = ".jpg"
                    ct = (r.headers.get("Content-Type") or "").lower()
                    if "png" in ct: ext = ".png"
                    elif "webp" in ct: ext = ".webp"
                    elif "jpeg" in ct: ext = ".jpg"
                    raw_path = folder / f"image_{i}{ext}"
                    raw_path.write_bytes(r.content)
                    saved.append(str(raw_path))
                except Exception:
                    print(f"⚠️ Could not download/convert {u}: {e}")
    return saved

# ========= Single-page scrape =========
def scrape_qvc_oxylabs(
    url: str,
    save_dir: Path = SAVE_DIR,
    *,
    max_images: int = 10
) -> dict:
    save_dir.mkdir(parents=True, exist_ok=True)

    with requests.Session() as session:
        session.headers.update({"User-Agent": UA_STR})

        res = _post_realtime_one(session, url)
        html = _result_content_or_error(res, requested_url=url)
        soup = BeautifulSoup(html, "lxml")

        name = _extract_name(soup)
        price, currency = _extract_price(soup)
        in_stock, stock_text = _extract_stock(soup)
        description = _extract_description(soup, name)

        product_id = _stable_id_from_url(url)
        folder = save_dir / f"qvc_{_safe_name(name)}_{product_id}"
        folder.mkdir(parents=True, exist_ok=True)

        img_urls = _collect_images(soup, max_images=max_images)
        downloaded = _download_images_as_jpg(img_urls, folder, quality=90)

        out = {
            "url": url,
            "name": name,
            "price": price,
            "currency": currency or "",
            "in_stock": in_stock,
            "stock_text": stock_text,
            "description": description,
            "image_count": len(downloaded),
            "images": downloaded,
            "folder": str(folder),
            "fetched_via": "oxylabs-universal",
        }
        (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        return out

# ========= Batch scraping =========
def _scrape_one(session: requests.Session, url: str, save_dir: Path, max_images: int) -> Dict[str, Any]:
    try:
        res = _post_realtime_one(session, url)
        html = _result_content_or_error(res, requested_url=url)
        soup = BeautifulSoup(html, "lxml")

        name = _extract_name(soup)
        price, currency = _extract_price(soup)
        in_stock, stock_text = _extract_stock(soup)
        description = _extract_description(soup, name)

        product_id = _stable_id_from_url(url)
        folder = save_dir / f"qvc_{_safe_name(name)}_{product_id}"
        folder.mkdir(parents=True, exist_ok=True)

        img_urls = _collect_images(soup, max_images=max_images)
        downloaded = _download_images_as_jpg(img_urls, folder, quality=90)

        out = {
            "url": url,
            "name": name,
            "price": price,
            "currency": currency or "",
            "in_stock": in_stock,
            "stock_text": stock_text,
            "description": description,
            "image_count": len(downloaded),
            "images": downloaded,
            "folder": str(folder),
            "fetched_via": "oxylabs-universal",
        }
        (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        return out
    except Exception as e:
        return {"url": url, "error": str(e)}

def scrape_qvc_batch_oxylabs(
    urls: Iterable[str],
    save_dir: Path = SAVE_DIR,
    *,
    max_images: int = 10,
    threads: int = 0
) -> List[Dict[str, Any]]:
    urls = [u for u in urls if u]
    if not urls:
        return []
    save_dir.mkdir(parents=True, exist_ok=True)

    results = []
    if threads and threads > 1:
        with requests.Session() as session:
            session.headers.update({"User-Agent": UA_STR})
            with ThreadPoolExecutor(max_workers=threads) as ex:
                futs = {ex.submit(_scrape_one, session, u, save_dir, max_images): u for u in urls}
                for f in as_completed(futs):
                    results.append(f.result())
        return results

    with requests.Session() as session:
        session.headers.update({"User-Agent": UA_STR})
        for u in urls:
            results.append(_scrape_one(session, u, save_dir, max_images))
    return results

# # ========= CLI =========
# if __name__ == "__main__":
#     TEST_URL = "https://www.qvc.com/laura-ashley-17-liter-cordless-electric-jug-kettle.product.K91948.html?sc=SRCH"
#     data = scrape_qvc_oxylabs(TEST_URL, save_dir=SAVE_DIR, max_images=10)
#     print(json.dumps(data, indent=2, ensure_ascii=False))





