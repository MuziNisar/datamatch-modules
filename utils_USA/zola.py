
# zola.py
# Python 3.10+
# Oxylabs Web Scraper API (universal) -> HTML -> BeautifulSoup parsing
#
# pip install requests beautifulsoup4 lxml pillow

from __future__ import annotations

import os
import re
import io
import json
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

# ========= Secrets =========
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS  # type: ignore
except Exception:
    OXY_USER = os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")

if not OXY_USER or not OXY_PASS:
    raise RuntimeError("Set Oxylabs creds via oxylabs_secrets.py or env vars OXYLABS_USERNAME/PASSWORD.")

# ========= Config / Paths =========
OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"
REQUEST_TIMEOUT = 90
UA_STR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)
GEO_LOCATION = "United States"

try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()
DATA_DIR = BASE_DIR / "data1"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ========= Helpers =========
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _safe_name(s: str) -> str:
    s = _clean(s)
    s = re.sub(r"[^\w.\-]+", "_", s, flags=re.UNICODE)
    return s[:100] if s else "product"

def _slug_from_host(url: str) -> str:
    try:
        host = urlparse(url).hostname or "site"
        host = host.replace("www.", "")
        return host.split(".")[0]
    except Exception:
        return "site"

def _stable_id_from_url(url: str) -> str:
    """
    Prefer path segment after /product/<slug>. If none, fallback to last segment or URL hash.
    """
    try:
        path = (urlparse(url).path or "").strip("/")
        m = re.search(r"(?:^|/)product/([^/?#]+)", path, re.I)
        if m:
            return m.group(1)
        segs = [p for p in path.split("/") if p]
        if segs:
            return segs[-1]
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

def _unique_path(base: Path) -> Path:
    """Return a unique folder path by suffixing _01, _02, ... if needed."""
    if not base.exists():
        return base
    stem = base.name
    parent = base.parent
    m = re.match(r"^(.*)_(\d{2})$", stem)
    if m:
        core, num = m.groups()
        n = int(num)
        while True:
            n += 1
            cand = parent / f"{core}_{n:02d}"
            if not cand.exists():
                return cand
    else:
        n = 1
        while True:
            cand = parent / f"{stem}_{n:02d}"
            if not cand.exists():
                return cand
            n += 1

def _post_oxylabs_universal(url: str) -> str:
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
        "user_agent": UA_STR,
        "geo_location": GEO_LOCATION,
    }
    resp = requests.post(
        OXY_ENDPOINT,
        json=payload,
        auth=(OXY_USER, OXY_PASS),
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 401:
        raise RuntimeError("Oxylabs Unauthorized (401). Check OXYLABS_USERNAME/PASSWORD.")
    if not resp.ok:
        raise RuntimeError(f"Oxylabs failed: HTTP {resp.status_code} - {resp.text[:400]}")
    data = resp.json()
    if isinstance(data, dict) and data.get("results"):
        c = data["results"][0].get("content")
        if isinstance(c, str):
            return c
    if isinstance(data, dict) and isinstance(data.get("content"), str):
        return data["content"]
    raise RuntimeError("Oxylabs universal returned no HTML content")

# ========= Field extractors =========
def _parse_money(s: str) -> Optional[str]:
    if not s:
        return None
    s = _clean(s)
    m = re.search(r"(\$?\s*\d[\d,]*(?:\.\d{2})?)", s)
    if m:
        val = m.group(1).replace(" ", "")
        if not val.startswith("$"):
            val = "$" + val
        return val
    return None

def _extract_name(soup: BeautifulSoup) -> str:
    # Brand + product name block
    wrap = soup.select_one("div.brand-product-names-nonmobile")
    if wrap:
        brand = _clean(wrap.select_one("a.brand-name").get_text(" ", strip=True)) if wrap.select_one("a.brand-name") else ""
        pname = _clean(wrap.select_one("h1.product-name").get_text(" ", strip=True)) if wrap.select_one("h1.product-name") else ""
        if pname and brand:
            return f"{brand} – {pname}"
        if pname:
            return pname
        if brand:
            return brand

    for sel in [
        "h1[data-testid*='product-name']",
        "h1.product-name",
        "meta[property='og:title']",
        "title",
    ]:
        node = soup.select_one(sel)
        if not node:
            continue
        txt = node.get("content") if node.name == "meta" else node.get_text(" ", strip=True)
        txt = _clean(txt)
        if txt:
            return txt
    return "Unknown Product"

def _extract_price_and_src(soup: BeautifulSoup) -> Tuple[str, str]:
    for sel in [
        "div.zola-price",
        "[data-testid*='price']",
        "[class*='price']",
    ]:
        node = soup.select_one(sel)
        if node:
            money = _parse_money(node.get_text(" ", strip=True))
            if money:
                return money, "zola-price"

    node = soup.select_one("[itemprop='price'], meta[itemprop='price']")
    if node:
        val = (node.get("content") or node.get_text(" ", strip=True) or "").strip()
        money = _parse_money(val)
        if money:
            return money, "microdata"

    for sc in soup.select("script[type='application/ld+json']"):
        raw = sc.string or sc.get_text(separator="", strip=True) or ""
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if not isinstance(obj, dict):
                continue
            if obj.get("@type") in ("Product", "Offer", "AggregateOffer"):
                offers = obj.get("offers")
                if isinstance(offers, dict):
                    price = offers.get("price")
                    money = _parse_money(str(price) if price is not None else "")
                    if money:
                        return money, "jsonld"
                elif isinstance(offers, list):
                    for off in offers:
                        if isinstance(off, dict) and off.get("price"):
                            money = _parse_money(str(off["price"]))
                            if money:
                                return money, "jsonld"

    # Heuristic: buy-box text
    buybox = soup.find(lambda t: hasattr(t, "get_text") and "Add to cart" in t.get_text(" ", strip=True))
    if buybox:
        money = _parse_money(buybox.get_text(" ", strip=True))
        if money:
            return money, "heuristic-buybox"

    return "N/A", "none"

def _detect_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], str]:
    stock_text = ""
    # Explicit “Out of stock / Sold out / Unavailable” text anywhere
    neg = soup.find(string=re.compile(r"\b(Out of stock|Sold out|Unavailable|Currently unavailable)\b", re.I))
    if neg:
        return False, _clean(str(neg))

    # Positive if Add to cart visible (and not obviously disabled)
    html = soup.decode().lower()
    if re.search(r">\s*add to cart\s*<", html) or re.search(r'aria-label="\s*add to cart\s*"', html):
        atc = soup.find("button", string=re.compile(r"add to cart", re.I))
        if atc:
            disabled_attr = (atc.get("disabled") or "").lower()
            aria_disabled = (atc.get("aria-disabled") or "").lower()
            cls = atc.get("class") or []
            cls_str = " ".join(cls) if isinstance(cls, list) else str(cls)
            if disabled_attr == "true" or aria_disabled == "true" or re.search(r"\bdisabled\b", cls_str, re.I):
                return False, "Add to cart disabled"
        return True, "Add to cart available"

    # Try stock message node (best-effort)
    node = soup.select_one(".stock-message-text, [data-testid*='stock']")
    if node:
        stock_text = _clean(node.get_text(" ", strip=True))

    return None, stock_text

def _extract_description(soup: BeautifulSoup) -> str:
    """
    Capture the lead paragraph(s) ABOVE the bullets + then the bullets.
    If not present, fall back to meta/JSON-LD.
    """
    cont = None
    for sel in [
        "div.product-description",
        "section[aria-label='Product Description']",
        "[data-testid*='description']",
        "div[class*='description']",
    ]:
        cont = soup.select_one(sel)
        if cont:
            break

    intro_paras: List[str] = []
    bullets: List[str] = []

    if cont:
        # Gather paragraphs until the first <ul> (intro block above bullets)
        first_ul = cont.find("ul")
        if first_ul:
            # paragraphs that appear before first <ul>
            for p in cont.find_all("p", recursive=True):
                if p.find_parent("ul"):
                    continue
                # stop collecting once we pass the first UL in document order
                # by checking if this <p> appears after the UL
                if p.sourceline and first_ul.sourceline and p.sourceline > first_ul.sourceline:
                    continue
                t = _clean(p.get_text(" ", strip=True))
                if t:
                    intro_paras.append(t)
            # bullets from that first UL (and immediate siblings ULs)
            ul = first_ul
            while ul and ul.name == "ul":
                for li in ul.select("li"):
                    t = _clean(li.get_text(" ", strip=True))
                    if t:
                        bullets.append(f"• {t}")
                ul = ul.find_next_sibling(lambda n: n.name == "ul")
        else:
            # No ULs—just collect meaningful paragraphs
            for p in cont.find_all("p", recursive=True):
                t = _clean(p.get_text(" ", strip=True))
                if t:
                    intro_paras.append(t)

    # Compose description: intro paragraphs first, then bullets
    parts: List[str] = []
    if intro_paras:
        # keep first 1–2 paras to avoid overly long blobs
        head = "\n\n".join(intro_paras[:2])
        if len(head) > 40:
            parts.append(head)
    if bullets:
        parts.append("\n".join(bullets))

    if parts:
        return "\n\n".join(parts).strip()

    # Meta description fallback
    meta = soup.select_one("meta[name='description']")
    if meta and meta.get("content"):
        txt = _clean(meta["content"])
        if txt:
            return txt

    # JSON-LD Product.description
    best = ""
    for sc in soup.select("script[type='application/ld+json']"):
        raw = sc.string or sc.get_text(separator="", strip=True) or ""
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if isinstance(obj, dict) and obj.get("@type") == "Product":
                desc = _clean(obj.get("description") or "")
                if desc and len(desc) > len(best):
                    best = desc
    return best

# ========= Images =========
def _pick_largest_from_srcset(srcset: str) -> Optional[str]:
    try:
        parts = [p.strip() for p in (srcset or "").split(",") if p.strip()]
        best_url = None
        best_w = -1
        for part in parts:
            m = re.match(r"(.+?)\s+(\d+)w", part)
            if m:
                url = m.group(1).strip()
                w = int(m.group(2))
                if w > best_w:
                    best_w = w
                    best_url = url
            else:
                best_url = part
        return best_url
    except Exception:
        return None

def _normalize_zola_image_url(url: str) -> str:
    try:
        parts = list(urlparse(url.strip()))
        parts[4] = ""  # query
        parts[5] = ""  # fragment
        return urlunparse(parts)
    except Exception:
        return url

def _stable_image_key(url: str) -> str:
    try:
        path = urlparse(url).path or ""
        m = re.search(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", path, re.I)
        if m:
            return m.group(1).lower()
        fname = os.path.basename(path)
        stem = os.path.splitext(fname)[0]
        if stem:
            return stem.lower()
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]

def _collect_images(soup: BeautifulSoup, *, max_images: Optional[int] = None) -> List[str]:
    urls: List[str] = []

    # Thumbnails / gallery imgs
    for sel in [
        ".thumbnail-slider img[src]",
        "[data-testid*='gallery'] img[src]",
        "div[class*='gallery'] img[src]",
    ]:
        for img in soup.select(sel):
            u = img.get("src") or ""
            if u:
                urls.append(u)

    # <source srcset>
    for source in soup.select("source[srcset]"):
        best = _pick_largest_from_srcset(source.get("srcset") or "")
        if best:
            urls.append(best)

    # OpenGraph
    og = soup.select_one("meta[property='og:image']")
    if og and og.get("content"):
        urls.append(og["content"])

    # JSON-LD Product.image
    for sc in soup.select("script[type='application/ld+json']"):
        raw = sc.string or sc.get_text(separator="", strip=True) or ""
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if isinstance(obj, dict) and obj.get("@type") == "Product":
                imgs = obj.get("image")
                if isinstance(imgs, str):
                    urls.append(imgs)
                elif isinstance(imgs, list):
                    for u in imgs:
                        if isinstance(u, str):
                            urls.append(u)

    # Accept filter
    def _accept(u: str) -> bool:
        if not u:
            return False
        hu = u.lower()
        if "images.zola.com" in hu:
            return True
        if not re.search(r"\.(jpg|jpeg|png|webp)(?:$|\?)", hu):
            return False
        if re.search(r"(sprite|icon|badge|logo|placeholder|swatch|thumb|share)", hu):
            return False
        return True

    # Normalize + dedupe by stable key
    seen = set()
    final: List[str] = []
    for u in urls:
        if not _accept(u):
            continue
        nu = _normalize_zola_image_url(u)
        key = _stable_image_key(nu)
        if key in seen:
            continue
        seen.add(key)
        final.append(nu)
        if max_images and len(final) >= max_images:
            break

    return final

# ========= Perceptual-hash dedupe =========
def _ahash(img: Image.Image, hash_size: int = 8) -> int:
    im = img.convert("L").resize((hash_size, hash_size), Image.BILINEAR)
    pixels = list(im.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for p in pixels:
        bits = (bits << 1) | (1 if p >= avg else 0)
    return bits

def _hamming(a: int, b: int) -> int:
    x = a ^ b
    return x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1")

def _dedupe_downloaded_by_phash(paths: List[str], *, max_hamming: int = 4) -> List[str]:
    kept: List[str] = []
    hashes: List[int] = []
    for p in paths:
        try:
            im = Image.open(p)
            h = _ahash(im)
        except Exception:
            kept.append(p)
            continue
        is_dup = False
        for prev in hashes:
            if _hamming(h, prev) <= max_hamming:
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass
                is_dup = True
                break
        if not is_dup:
            hashes.append(h)
            kept.append(p)
    return kept

# ========= Downloading =========
def _download_images(
    urls: List[str],
    folder: Path,
    *,
    convert_to_jpg: bool = True,
    quality: int = 90,
    referer: Optional[str] = None,
) -> List[str]:
    saved: List[str] = []
    folder.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": UA_STR,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer

    with requests.Session() as s:
        s.headers.update(headers)
        for i, u in enumerate(urls, 1):
            try:
                r = s.get(u, timeout=25)
                if not (r.ok and r.content):
                    continue
                if convert_to_jpg:
                    img_bytes = io.BytesIO(r.content)
                    im = Image.open(img_bytes)
                    if im.mode in ("RGBA", "LA", "P"):
                        if im.mode == "P":
                            im = im.convert("RGBA")
                        bg = Image.new("RGB", im.size, (255, 255, 255))
                        bg.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
                        im = bg
                    else:
                        im = im.convert("RGB")
                    out_path = folder / f"image_{i}.jpg"
                    im.save(out_path, format="JPEG", quality=quality, optimize=True)
                    saved.append(str(out_path))
                else:
                    ext = ".jpg"
                    ct = (r.headers.get("Content-Type") or "").lower()
                    lu = u.lower()
                    if "png" in ct or lu.endswith(".png"): ext = ".png"
                    elif "webp" in ct or lu.endswith(".webp"): ext = ".webp"
                    elif "jpeg" in ct or lu.endswith(".jpeg"): ext = ".jpeg"
                    out_path = folder / f"image_{i}{ext}"
                    out_path.write_bytes(r.content)
                    saved.append(str(out_path))
            except Exception:
                continue
    return saved

# ========= Public API (single-arg) =========
def scrape_zola(url: str) -> Dict[str, Any]:
    """
    Fetch via Oxylabs (universal), parse with BS4, download images, pHash-dedupe,
    return the exact schema required.
    """
    html = _post_oxylabs_universal(url)
    soup = BeautifulSoup(html, "lxml")

    # Fields
    name = _extract_name(soup)
    price, price_source = _extract_price_and_src(soup)
    in_stock, stock_text = _detect_stock(soup)
    description = _extract_description(soup)
    images = _collect_images(soup, max_images=None)

    # Save folder (UNIQUE) & raw HTML
    slug = _slug_from_host(url)
    stable_id = _stable_id_from_url(url)
    base_folder = DATA_DIR / f"{slug}_{_safe_name(name)}_{stable_id}"
    folder = _unique_path(base_folder)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        (folder / "raw_html.html").write_text(html, encoding="utf-8")
    except Exception:
        pass

    # Download + pHash-dedupe
    downloaded = _download_images(images, folder, convert_to_jpg=True, referer=url)
    deduped = _dedupe_downloaded_by_phash(downloaded, max_hamming=4)

    out = {
        "name": name,
        "price": price,
        "price_source": price_source if price != "N/A" else "none",
        "in_stock": in_stock,
        "stock_text": stock_text or "",
        "description": description or "",
        "image_count": len(deduped),
        "images": deduped,
        "folder": str(folder),
        "country_code": None,
        "zip_used": None,
    }
    try:
        (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return out

# # ========= Hardcoded run =========
# if __name__ == "__main__":
#     u = "https://www.zola.com/shop/product/lauraashley_10cup_stove_top_kettle_elvedenwhite"
#     data = scrape_zola(u)  # <- single argument only
#     print(json.dumps(data, indent=2, ensure_ascii=False))
