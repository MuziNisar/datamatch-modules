

# kaufland.py — Oxylabs universal + robust price parsing (current, original, savings), JPG-only images
# Python 3.9+
# pip install requests beautifulsoup4 lxml pillow pillow-avif-plugin

from __future__ import annotations
import os, re, json, hashlib, time, random
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from urllib.parse import urlparse, urldefrag, urlsplit, urlunsplit
from io import BytesIO
from datetime import datetime, timezone

import requests
from requests.exceptions import RequestException
from bs4 import BeautifulSoup
from PIL import Image

# Try AVIF/HEIF
try:
    import pillow_avif  # noqa: F401
except Exception:
    pass

# =========================
# Config
# =========================
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception as e:
    raise RuntimeError("Missing oxylabs_secrets.py with OXY_USER and OXY_PASS") from e
if not (OXY_USER and OXY_PASS):
    raise RuntimeError("OXY_USER/OXY_PASS in oxylabs_secrets.py must be non-empty.")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
ACCEPT_LANG = "de-DE,de;q=0.9"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data_de"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SITE_TAG = "kaufland"
OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"

# Image resolution for Kaufland CDN
# Options: 100x100, 200x200, 300x300, 400x400, 600x600, 800x800, 1000x1000, 1200x1200, 1500x1500, 2000x2000, original
KAUFLAND_IMAGE_SIZE = "1500x1500"

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
    """Create a safe filename by normalizing Unicode to ASCII (OpenCV compatible)."""
    import unicodedata
    s = _clean(s)
    # Normalize unicode: ö→o, ß→s, ü→u, etc.
    s = unicodedata.normalize('NFKD', s)
    s = s.encode('ascii', 'ignore').decode('ascii')
    # Replace remaining special chars with underscore
    return re.sub(r"[^\w.\-]+", "_", s)[:120] or "product"

def _stable_id_from_url(url: str) -> str:
    try:
        url, _frag = urldefrag(url)
        path = urlparse(url).path.strip("/").split("/")
        last = (path[-1] if path else "") or url
        return re.sub(r"[^\w\-]+", "", last) or hashlib.sha1(url.encode()).hexdigest()[:12]
    except Exception:
        return hashlib.sha1(url.encode()).hexdigest()[:12]

def _dedupe_preserve(urls: List[str]) -> List[str]:
    seen, out = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u); out.append(u)
    return out

def _best_text(el) -> str:
    return _clean(el.get_text(" ", strip=True)) if el else ""

def _attr_chain(tag, *attrs) -> Optional[str]:
    if not tag:
        return None
    for a in attrs:
        v = tag.get(a)
        if v:
            return v
    return None

def _strip_query(u: str) -> str:
    sp = urlsplit(u)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

def _upgrade_kaufland_image_url(u: str, target_size: str = KAUFLAND_IMAGE_SIZE) -> str:
    """
    Upgrade Kaufland CDN image URL to higher resolution.
    
    Known working sizes vary by product. Common sizes include:
    100x100, 200x200, 300x300, 400x400, 600x600, 800x800, 1024x1024
    
    Example:
        Input:  https://media.cdn.kaufland.de/product-images/100x100/abc123.webp
        Output: https://media.cdn.kaufland.de/product-images/1024x1024/abc123.webp
    """
    if not u or "media.cdn.kaufland.de/product-images/" not in u:
        return u
    
    # Replace the size in the URL path
    upgraded = re.sub(r'/product-images/\d+x\d+/', f'/product-images/{target_size}/', u)
    return upgraded

def _get_kaufland_image_url_variants(u: str) -> List[str]:
    """
    Generate a list of URL variants to try, from highest to lowest resolution.
    """
    if not u or "media.cdn.kaufland.de/product-images/" not in u:
        return [u] if u else []
    
    # Sizes to try, from largest to smallest
    # Based on common Kaufland CDN patterns
    sizes_to_try = ["1024x1024", "800x800", "600x600", "400x400", "300x300", "200x200", "100x100"]
    
    variants = []
    for size in sizes_to_try:
        variant = re.sub(r'/product-images/\d+x\d+/', f'/product-images/{size}/', u)
        if variant not in variants:
            variants.append(variant)
    
    return variants

def _is_kaufland_product_image(u: str) -> bool:
    return bool(u and "media.cdn.kaufland.de/product-images/" in u)

# ---- price parsing helpers ----
_EUR_NUM_RE = re.compile(r"([\d\.\s]+[.,]\d{2})")
def _parse_eur_text(text: str) -> Optional[float]:
    if not text:
        return None
    t = text.replace("\xa0", " ").replace("€", "").strip()
    m = _EUR_NUM_RE.search(t)
    if not m:
        return None
    raw = m.group(1).replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except Exception:
        return None

def _fmt_eur(v: Optional[float]) -> str:
    return f"{v:.2f} EUR" if v is not None else "N/A"

# =========================
# Oxylabs client (no browser_instructions)
# =========================
def _build_context_array(session_id: Optional[str]) -> list[dict]:
    ctx: list[dict] = []
    if session_id:
        ctx.append({"key": "session_id", "value": session_id})
    ctx.append({
        "key": "headers",
        "value": {
            "User-Agent": UA,
            "Accept-Language": ACCEPT_LANG
        }
    })
    return ctx

def _parse_retry_after(headers: Dict[str, str]) -> Optional[float]:
    ra = headers.get("Retry-After")
    if ra:
        try:
            return float(ra)
        except ValueError:
            try:
                dt = datetime.strptime(ra, "%a, %d %b %Y %H:%M:%S %Z")
                return max(0.0, (dt.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds())
            except Exception:
                pass
    xr = headers.get("X-RateLimit-Reset") or headers.get("X-Ratelimit-Reset")
    if xr:
        try:
            return max(0.0, float(xr) - time.time())
        except Exception:
            pass
    return None

def oxy_post(payload: dict, retries: int = 6, base_sleep: float = 2.0) -> dict:
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(OXY_ENDPOINT, auth=(OXY_USER, OXY_PASS), json=payload, timeout=120)
            if r.status_code == 200:
                data = r.json()
                results = data.get("results") or []
                if not results:
                    raise RuntimeError("Oxylabs: empty results")
                content = results[0].get("content", "")
                if "<html" not in content.lower():
                    raise RuntimeError("Oxylabs: non-HTML content")
                return data

            if r.status_code in (429, 500, 502, 503, 504):
                wait = _parse_retry_after(r.headers)
                if wait is None:
                    wait = (base_sleep * (2 ** attempt)) + random.uniform(0.25, 0.75)
                time.sleep(min(wait, 30.0))
                continue

            try:
                err_json = r.json()
                raise RuntimeError(f"Oxylabs HTTP {r.status_code}: {err_json}")
            except ValueError:
                raise RuntimeError(f"Oxylabs HTTP {r.status_code}: {r.text[:500]}")

        except (RequestException, ValueError, RuntimeError) as e:
            last_err = e
            if attempt < retries:
                wait = (base_sleep * (2 ** attempt)) + random.uniform(0.25, 0.75)
                time.sleep(min(wait, 10.0))
                continue
            raise RuntimeError(f"Oxylabs failed after {retries+1} attempts: {e}") from e
    raise last_err or RuntimeError("Oxylabs unknown error")

def oxy_fetch_html(url: str, geo: str = "Germany") -> str:
    url, _frag = urldefrag(url)
    session_id = f"kaufland-{int(time.time())}-{random.randint(1000,9999)}"
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
        "geo_location": geo,
        "user_agent_type": "desktop",
        "context": _build_context_array(session_id),
    }
    data = oxy_post(payload)
    return data["results"][0]["content"]

# =========================
# Image download (ALWAYS .jpg)
# =========================
def _img_to_jpg_bytes(raw: bytes) -> bytes:
    with Image.open(BytesIO(raw)) as im:
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            im_rgba = im.convert("RGBA")
            bg.paste(im_rgba, mask=im_rgba.split()[-1])
            out = BytesIO()
            bg.save(out, format="JPEG", quality=92, optimize=True, progressive=True)
            return out.getvalue()
        if im.mode != "RGB":
            im = im.convert("RGB")
        out = BytesIO()
        im.save(out, format="JPEG", quality=92, optimize=True, progressive=True)
        return out.getvalue()

def download_images_jpg(urls: List[str], folder: Path, referer: str, max_images: Optional[int]=None) -> List[str]:
    if max_images is not None:
        urls = urls[:max_images]
    saved = []
    folder.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Referer": referer,
    }
    
    for i, original_url in enumerate(urls, 1):
        downloaded = False
        
        # Get list of URL variants to try (different sizes)
        url_variants = _get_kaufland_image_url_variants(original_url)
        
        for u in url_variants:
            try:
                u_clean = _strip_query(u)
                
                with requests.get(u_clean, headers=headers, timeout=40) as r:
                    ct = (r.headers.get("Content-Type", "") or "").lower()
                    
                    if r.status_code == 200 and (ct.startswith("image/") or (r.content and len(r.content) > 1000)):
                        out = folder / f"{i:02d}.jpg"
                        try:
                            out.write_bytes(_img_to_jpg_bytes(r.content))
                            saved.append(str(out))
                            downloaded = True
                            # Extract size from successful URL for logging
                            size_match = re.search(r'/product-images/(\d+x\d+)/', u_clean)
                            size_info = size_match.group(1) if size_match else "unknown"
                            print(f"  ✓ Image {i} downloaded at {size_info}")
                            break  # Success, move to next image
                        except Exception as pe:
                            if ct.startswith(("image/jpeg", "image/jpg")):
                                out.write_bytes(r.content)
                                saved.append(str(out))
                                downloaded = True
                                break
                            # Try next size variant
                            continue
                    elif r.status_code == 404:
                        # Size not available, try next
                        continue
                    else:
                        # Other error, try next size
                        continue
                        
            except Exception as e:
                # Network error, try next size
                continue
        
        if not downloaded:
            print(f"  ! Failed to download image {i} (tried all sizes)")
    
    return saved

# =========================
# Kaufland.de parser (fixes discount vs current price)
# =========================
def _first_jsonld(soup: BeautifulSoup) -> dict:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(tag.string or "")
            if isinstance(obj, list):
                for it in obj:
                    if isinstance(it, dict) and it.get("@type") in {"Product", "Offer"}:
                        return it
            elif isinstance(obj, dict) and obj.get("@type") in {"Product", "Offer"}:
                return obj
        except Exception:
            continue
    return {}

def _extract_prices(soup: BeautifulSoup) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
    """
    Returns: (price_current, price_original, saving_value, price_source)
    price_source: 'onsite', 'jsonld', or 'mixed'
    """
    price_source = "none"
    price_current = None
    price_original = None
    saving_value = None

    # 1) On-page current price (most reliable)
    # <span data-testid="product-price">€69.99</span>
    price_el = soup.select_one('[data-testid="product-price"], .rd-price-information__price[aria-label]')
    if price_el:
        # prefer visible text; fallback to aria-label
        txt = price_el.get_text(strip=True) or price_el.get("aria-label", "")
        price_current = _parse_eur_text(txt)
        if price_current is not None:
            price_source = "onsite"

    # 2) On-page strikeout/original price
    # <div class="rd-buybox-comparison__price rd-buybox-comparison__strikeout">€111.06</div>
    strike_el = soup.select_one(".rd-buybox-comparison__price, .rd-buybox-comparison__strikeout")
    if strike_el:
        po = _parse_eur_text(strike_el.get_text(" ", strip=True))
        if po is not None:
            price_original = po
            if price_source == "none":
                price_source = "onsite"

    # 3) On-page saving badge (e.g., "-€41.07")
    save_el = soup.select_one('[data-test-id="strikeout-discount"], .rd-price-information__saving')
    if save_el:
        sv = _parse_eur_text(save_el.get_text(" ", strip=True))
        if sv is not None:
            # It might be negative in text, ensure positive numeric saving
            saving_value = abs(sv)
            if price_source == "none":
                price_source = "onsite"

    # 4) JSON-LD offers as fallback / complement
    jld = _first_jsonld(soup)
    offers = jld.get("offers") if isinstance(jld, dict) else None
    if offers:
        off = offers[0] if isinstance(offers, list) and offers else (offers if isinstance(offers, dict) else None)
        if isinstance(off, dict):
            jld_price = _parse_eur_text(str(off.get("price", "")))
            if jld_price is not None:
                if price_current is None:
                    price_current = jld_price
                    price_source = "jsonld" if price_source == "none" else "mixed"

    # 5) Derive missing fields
    if price_original is None and price_current is not None and saving_value is not None:
        price_original = round(price_current + saving_value, 2)
    if saving_value is None and price_current is not None and price_original is not None:
        saving_value = round(max(0.0, price_original - price_current), 2)

    return price_current, price_original, saving_value, (price_source if price_source != "none" else "onsite")

def parse_kaufland(html: str) -> Dict:
    soup = BeautifulSoup(html, "lxml")
    jld = _first_jsonld(soup)

    # ---- name ----
    name = _clean(jld.get("name", "")) if jld else ""
    if not name:
        el = soup.select_one("h1#product-title, h1.rd-title, h1[itemprop='name'], h1")
        name = _best_text(el) or (_clean(soup.title.get_text().split('|')[0]) if soup.title else "") or "Unknown Product"

    # ---- prices (current, original, saving) ----
    price_current, price_original, saving_value, price_source = _extract_prices(soup)
    saving_percent = None
    if price_current is not None and price_original:
        if price_original > 0:
            saving_percent = round((price_original - price_current) / price_original * 100.0, 2)

    # ---- stock ----
    in_stock, stock_text = None, ""
    
    # HIGHEST PRIORITY: Check for error/warning notifications
    # <div class="rd-notification rd-notification--error"> with "not currently available" or "ausverkauft"
    error_notifications = soup.select('.rd-notification--error, .rd-notification--warning, .rd-sidebar-notification')
    for notif in error_notifications:
        notif_text = _clean(notif.get_text(" ", strip=True)).lower()
        if any(phrase in notif_text for phrase in [
            "not currently available", "currently not available", "nicht verfügbar",
            "ausverkauft", "nicht lieferbar", "out of stock", "sold out",
            "leider nicht", "unfortunately not"
        ]):
            in_stock = False
            stock_text = _clean(notif.get_text(" ", strip=True)) or "Nicht verfügbar"
            break
    
    # Also check for rd-sidebar-notification__out-of-stock
    if in_stock is None:
        oos_el = soup.select_one('.rd-sidebar-notification__out-of-stock--bold, [class*="out-of-stock"]')
        if oos_el:
            in_stock = False
            stock_text = _clean(oos_el.get_text(" ", strip=True)) or "Nicht verfügbar"
    
    # JSON-LD availability as secondary check
    if in_stock is None:
        offer = None
        offers = jld.get("offers") if isinstance(jld, dict) else None
        if offers:
            offer = offers[0] if isinstance(offers, list) and offers else (offers if isinstance(offers, dict) else None)
        if isinstance(offer, dict):
            avail = str(offer.get("availability", "")).lower()
            if any(x in avail for x in ["outofstock", "soldout", "oos", "discontinued"]):
                in_stock, stock_text = False, "OutOfStock (JSON-LD)"
            elif "instock" in avail:
                in_stock, stock_text = True, "InStock (JSON-LD)"

    # Check Add to Cart button
    if in_stock is None:
        atc_btn = soup.select_one("#atc-button, .rd-add-to-cart__button, button[aria-label*='Warenkorb' i]")
        if atc_btn:
            txt = _best_text(atc_btn).lower()
            disabled = atc_btn.has_attr("disabled")
            if disabled or any(k in txt for k in ["ausverkauft", "nicht verfügbar"]):
                in_stock, stock_text = False, _best_text(atc_btn) or "Nicht verfügbar"
            elif any(k in txt for k in ["in den warenkorb", "kaufen", "jetzt kaufen"]):
                in_stock, stock_text = True, _best_text(atc_btn) or "In den Warenkorb"

    # Body text search (LOWEST PRIORITY - only if nothing else matched)
    if in_stock is None:
        body_txt = _clean(soup.get_text(" ", strip=True)).lower()
        # Check for out of stock phrases FIRST
        if any(w in body_txt for w in ["ausverkauft", "nicht verfügbar", "nicht lieferbar", "not currently available"]):
            in_stock, stock_text = False, "Nicht verfügbar"
        elif any(w in body_txt for w in ["in den warenkorb", "lieferbar", "verfügbar"]):
            in_stock, stock_text = True, "Verfügbar"

    # ---- description ----
    desc_parts: List[str] = []
    if jld and jld.get("description"):
        desc_parts.append(_clean_multiline(jld["description"]))
    desc_box = soup.select_one(".pdp-product-description__section, [aria-label='Produktinformationen']")
    if desc_box:
        for br in desc_box.find_all("br"):
            br.replace_with("\n")
        desc_parts.append(_clean_multiline(desc_box.get_text("\n", strip=True)))
    description = _clean_multiline("\n\n".join([d for d in desc_parts if d]))

    # ---- images ----
    imgs: List[str] = []
    for img in soup.select("#preview-slider img[src], .gallery-desktop__preview-slider img[src]"):
        u = _attr_chain(img, "data-src", "srcset", "src")
        if not u:
            continue
        if " " in u:
            u = u.split()[0]
        if _is_kaufland_product_image(u):
            # Store original URL - we'll try multiple sizes at download time
            imgs.append(u)
    imgs = _dedupe_preserve(imgs)

    return {
        "name": name,
        "price": _fmt_eur(price_current),          # kept for backward-compat
        "price_value": price_current,
        "currency": "EUR" if price_current is not None else (jld.get("priceCurrency", "EUR") if isinstance(jld, dict) else "EUR"),
        "price_source": price_source,
        "price_original": _fmt_eur(price_original) if price_original is not None else None,
        "price_original_value": price_original,
        "price_saving": _fmt_eur(saving_value) if saving_value is not None else None,
        "price_saving_value": saving_value,
        "price_saving_percent": saving_percent,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_urls": imgs
    }

# =========================
# Orchestrator
# =========================
def scrape_kaufland_with_oxylabs(url: str,
                                 download_images_flag: bool = True,
                                 max_images: Optional[int] = None,
                                 geo: str = "Germany") -> Dict:
    html = oxy_fetch_html(url, geo=geo)
    parsed = parse_kaufland(html)

    folder = DATA_DIR / f"{SITE_TAG}_{_safe_name(parsed['name'])}_{_safe_name(_stable_id_from_url(url))}"
    folder.mkdir(parents=True, exist_ok=True)

    images_downloaded: List[str] = []
    if download_images_flag and parsed["image_urls"]:
        count = len(parsed['image_urls']) if not max_images else min(len(parsed['image_urls']), max_images)
        print(f"Downloading {count} images (trying sizes: 1024x1024 → 100x100)…")
        images_downloaded = download_images_jpg(parsed["image_urls"], folder, referer=url, max_images=max_images)

    return {
        "url": url,
        "name": parsed["name"],
        "price": parsed["price"],  # current price (string)
        "price_value": parsed["price_value"],  # current price (float)
        "currency": parsed["currency"],
        "price_source": parsed["price_source"],
        "price_original": parsed["price_original"],
        "price_original_value": parsed["price_original_value"],
        "price_saving": parsed["price_saving"],
        "price_saving_value": parsed["price_saving_value"],
        "price_saving_percent": parsed["price_saving_percent"],
        "in_stock": parsed["in_stock"],
        "stock_text": parsed["stock_text"],
        "description": parsed["description"],
        "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
        "image_urls": parsed["image_urls"],
        "images_downloaded": images_downloaded,
        "folder": str(folder),
        "mode": "oxylabs-universal"
    }

# # =========================
# # CLI
# # =========================
# if __name__ == "__main__":
#     TEST_URL = "https://www.kaufland.de/product/524728348/"
#     data = scrape_kaufland_with_oxylabs(TEST_URL, download_images_flag=True, max_images=20)
#     print(json.dumps(data, indent=2, ensure_ascii=False))