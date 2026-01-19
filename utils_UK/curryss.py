
# # curryss.py
# # Python 3.9+
# # pip install requests beautifulsoup4 lxml

# from __future__ import annotations
# import os, re, json, hashlib
# from pathlib import Path
# from typing import Optional, List, Dict, Any

# import requests
# from bs4 import BeautifulSoup

# # =========================
# # Config (set your creds via env or hardcode here)
# # =========================
# OXY_USER = os.getenv("OXY_USER", "Muzamil_wUDhn")
# OXY_PASS = os.getenv("OXY_PASS", "Muzamil_13111")

# UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
# ACCEPT_LANG = "en-GB,en;q=0.9"

# BASE_DIR = Path(__file__).resolve().parent
# DATA_DIR = BASE_DIR / "data_currys"
# DATA_DIR.mkdir(parents=True, exist_ok=True)

# # =========================
# # Generic helpers
# # =========================
# def _clean(s: str) -> str:
#     return re.sub(r"\s+", " ", (s or "").strip())

# def _safe_name(s: str) -> str:
#     s = _clean(s)
#     return re.sub(r"[^\w.\-]+", "_", s)[:140] or "product"

# def _stable_id_from_url(url: str) -> str:
#     # Prefer 8-digit product id in URL; else short hash
#     m = re.search(r"-([0-9]{8})\.html(?:$|\?)", url)
#     if m:
#         return m.group(1)
#     return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

# # =========================
# # Currys-specific helpers (PID, URLs, images, stock)
# # =========================
# def _currys_pid_from_url(u: str) -> Optional[str]:
#     m = re.search(r"-([0-9]{8})\.html(?:$|\?)", u)
#     return m.group(1) if m else None

# def _absolute(u: str, base: str = "https://www.currys.co.uk") -> str:
#     if not u:
#         return u
#     if u.startswith("//"):
#         return "https:" + u
#     if u.startswith("/"):
#         return base.rstrip("/") + u
#     return u

# def _upgrade_currys_image(u: str) -> str:
#     # Replace any $t-...$ token with $l-large$ and ensure absolute URL
#     u = re.sub(r"\$t-[^$]*\$", "$l-large$", u)
#     return _absolute(u, "https://www.currys.co.uk")

# def _is_pdp_image(url: str, pid: str) -> bool:
#     """
#     Accept only:
#       https://media.currys.biz/i/currysprod/<PID>
#       https://media.currys.biz/i/currysprod/<PID>_<NNN>  (001..006)
#     Reject loaders, stickers, svgs, different product IDs, and 'g-small' aux art.
#     """
#     url = _absolute(url)
#     if not url.startswith("https://media.currys.biz/i/currysprod/"):
#         return False
#     core = url.split("?")[0]  # strip query
#     m = re.match(rf"https://media\.currys\.biz/i/currysprod/{pid}(?:_(\d{{3}}))?$", core)
#     if not m:
#         return False
#     if m.group(1) and m.group(1) not in {f"{i:03d}" for i in range(0, 7)}:
#         return False
#     return True

# def _collect_images(soup: BeautifulSoup, pid: str) -> List[str]:
#     """
#     Read image candidates from the carousel and product gallery, then
#     whitelist strictly to the PID set: <pid>, <pid>_001.._006.
#     Return at most 7 images in canonical order.
#     """
#     cand: List[str] = []

#     # Primary: carousel indicators (thumbnails often carry correct src[*])
#     for el in soup.select(".carouselindicators img[src], .carouselindicators source[srcset]"):
#         u = el.get("src") or el.get("srcset") or ""
#         if not u:
#             continue
#         if "," in u:  # srcset -> take largest (last)
#             u = u.split(",")[-1].strip().split(" ")[0]
#         cand.append(_upgrade_currys_image(u))

#     # Fallback: any declared product gallery component
#     if not cand:
#         for el in soup.select("[data-component='product-gallery'] img[src], [data-component='product-gallery'] source[srcset]"):
#             u = el.get("src") or el.get("srcset") or ""
#             if not u:
#                 continue
#             if "," in u:
#                 u = u.split(",")[-1].strip().split(" ")[0]
#             cand.append(_upgrade_currys_image(u))

#     # Whitelist & de-duplicate (preserve first occurrence order)
#     seen, whitelisted = set(), []
#     for u in cand:
#         if _is_pdp_image(u, pid) and u not in seen:
#             seen.add(u)
#             whitelisted.append(u)

#     # Canonical ordering: main, then 001..006 if present
#     ordered: List[str] = []
#     main_core = f"https://media.currys.biz/i/currysprod/{pid}"
#     if any(x.split("?")[0] == main_core for x in whitelisted):
#         ordered.append(_upgrade_currys_image(f"{main_core}?$l-large$&fmt=auto"))
#     for i in range(1, 7):
#         core = f"{main_core}_{i:03d}"
#         if any(x.split("?")[0] == core for x in whitelisted):
#             ordered.append(_upgrade_currys_image(f"{core}?$l-large$&fmt=auto"))

#     # If nothing matched canonical order (very rare), keep first seven that passed whitelist
#     final = ordered if ordered else whitelisted
#     return final[:7]

# def _detect_stock(soup: BeautifulSoup) -> tuple[Optional[bool], str]:
#     """
#     Currys CTA looks like:
#       <div class="addToCartActionButton ...">
#         <button class="add-to-cart ...">Add to basket</button>
#     """
#     btn = soup.select_one("button.add-to-cart, .addToCartActionButton button")
#     if btn:
#         disabled = btn.has_attr("disabled") or str(btn.get("aria-disabled", "")).lower() == "true"
#         return (not disabled, "Add to basket" + (" (disabled)" if disabled else ""))
#     # Fallback text scan
#     body = _clean(soup.get_text(" ", strip=True)).lower()
#     if any(t in body for t in ["out of stock", "sold out", "unavailable"]):
#         return (False, "Unavailable")
#     if "in stock" in body:
#         return (True, "In stock")
#     return (None, "")

# # =========================
# # Oxylabs client
# # =========================
# def oxy_post(payload: dict) -> dict:
#     r = requests.post(
#         "https://realtime.oxylabs.io/v1/queries",
#         auth=(OXY_USER, OXY_PASS),
#         json=payload,
#         timeout=90
#     )
#     r.raise_for_status()
#     return r.json()

# def oxy_fetch_html(url: str, geo: str = "United Kingdom") -> str:
#     payload = {
#         "source": "universal",
#         "url": url,
#         "render": "html",
#         "geo_location": geo,
#         "headers": {"User-Agent": UA, "Accept-Language": ACCEPT_LANG},
#     }
#     data = oxy_post(payload)
#     results = data.get("results") or []
#     if not results or "content" not in results[0]:
#         raise RuntimeError("Oxylabs: no HTML content returned")
#     html = results[0]["content"] or ""
#     if "<html" not in html.lower():
#         raise RuntimeError("Oxylabs: returned payload is not HTML")
#     return html

# # =========================
# # Parser
# # =========================
# def parse_currys(html: str, url: str) -> Dict[str, Any]:
#     soup = BeautifulSoup(html, "lxml")

#     pid = _currys_pid_from_url(url) or ""

#     # Name & JSON-LD
#     name = ""
#     jld: Dict[str, Any] = {}
#     for tag in soup.find_all("script", type="application/ld+json"):
#         try:
#             obj = json.loads(tag.string or "")
#         except Exception:
#             continue
#         if isinstance(obj, dict) and obj.get("@type") == "Product":
#             jld = obj
#             break
#         if isinstance(obj, list):
#             for e in obj:
#                 if isinstance(e, dict) and e.get("@type") == "Product":
#                     jld = e
#                     break
#         if jld:
#             break

#     if jld:
#         name = _clean(jld.get("name") or "")
#     if not name:
#         h1 = soup.select_one("#js-product-detail h1") or soup.find("h1")
#         if h1:
#             name = _clean(h1.get_text(" ", strip=True))
#     name = name or "Unknown Product"

#     # Price
#     price, price_source = "N/A", "none"
#     if jld and isinstance(jld.get("offers"), dict) and jld["offers"].get("price"):
#         try:
#             val = float(str(jld["offers"]["price"]).replace(",", ""))
#             price, price_source = f"{val:.2f} GBP", "jsonld"
#         except Exception:
#             pass
#     if price == "N/A":
#         el = soup.select_one(
#             '[data-component="product-price"] h2, '
#             '[data-test="product-price-primary"] h2, '
#             '.pdp-price h2, .price h2'
#         )
#         if el:
#             m = re.search(r"£\s*([\d,]+(?:\.\d{1,2})?)", el.get_text(" ", strip=True))
#             if m:
#                 val = m.group(1).replace(",", "")
#                 if "." not in val:
#                     val += ".00"
#                 price, price_source = f"{val} GBP", "onsite"

#     # Stock
#     in_stock, stock_text = _detect_stock(soup)

#     # Description
#     desc = ""
#     if jld and jld.get("description"):
#         desc = _clean(jld["description"])
#     if not desc:
#         for sel in (
#             '[data-component="product-description"]',
#             "#js-product-detail [data-auto='product-description']",
#             ".productDescription",
#             ".pdp-description",
#         ):
#             el = soup.select_one(sel)
#             if el:
#                 desc = el.get_text("\n", strip=True)
#                 desc = re.sub(r"[ \t]+\n", "\n", desc)
#                 desc = _clean(desc)
#                 break

#     # Images (strict to PID 0..6)
#     image_urls: List[str] = _collect_images(soup, pid) if pid else []

#     return {
#         "name": name,
#         "price": price,
#         "price_source": price_source,
#         "in_stock": (False if in_stock is None else in_stock),
#         "stock_text": stock_text or ("In stock" if in_stock else "Unavailable"),
#         "description": desc,
#         "image_urls": image_urls,
#     }

# # =========================
# # Image downloader
# # =========================
# def download_images_jpg(urls: List[str], folder: Path, referer: str,
#                         pid: Optional[str] = None,
#                         max_images: Optional[int] = None) -> List[str]:
#     if max_images is not None:
#         urls = urls[:max_images]
#     saved: List[str] = []
#     folder.mkdir(parents=True, exist_ok=True)
#     h = {
#         "User-Agent": UA,
#         "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#         "Accept-Language": ACCEPT_LANG,
#         "Referer": referer,
#         "Connection": "keep-alive",
#     }
#     for i, u in enumerate(urls, 1):
#         try:
#             # Belt-and-braces PID filter
#             if pid and not _is_pdp_image(u, pid):
#                 continue
#             r = requests.get(u, headers=h, timeout=30)
#             if r.status_code == 200 and r.content:
#                 ext = ".jpg"
#                 ct = (r.headers.get("Content-Type") or "").lower()
#                 if "webp" in ct:
#                     ext = ".webp"
#                 elif "png" in ct:
#                     ext = ".png"
#                 out = folder / f"{i:02d}{ext}"
#                 out.write_bytes(r.content)
#                 saved.append(str(out))
#             else:
#                 print("  ! image HTTP", r.status_code, u)
#         except Exception as e:
#             print("  ! image error:", u, e)
#     return saved

# # =========================
# # Orchestrator
# # =========================
# def scrape_currys_with_oxylabs(url: str,
#                                download_images_flag: bool = True,
#                                max_images: Optional[int] = None) -> Dict[str, Any]:
#     html = oxy_fetch_html(url, geo="United Kingdom")
#     parsed = parse_currys(html, url)

#     pid = _currys_pid_from_url(url) or _stable_id_from_url(url)
#     folder = DATA_DIR / f"currys_{_safe_name(parsed['name'])}_{pid}"
#     folder.mkdir(parents=True, exist_ok=True)

#     images_downloaded: List[str] = []
#     if download_images_flag and parsed["image_urls"]:
#         print(f"Downloading {min(len(parsed['image_urls']), max_images) if max_images else len(parsed['image_urls'])} images …")
#         images_downloaded = download_images_jpg(
#             parsed["image_urls"], folder, referer=url, pid=_currys_pid_from_url(url), max_images=max_images
#         )

#     return {
#         "url": url,
#         "name": parsed["name"],
#         "price": parsed["price"],
#         "price_source": parsed["price_source"],
#         "in_stock": parsed["in_stock"],
#         "stock_text": parsed["stock_text"],
#         "description": parsed["description"],
#         "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
#         "image_urls": parsed["image_urls"],
#         "images_downloaded": images_downloaded,
#         "folder": str(folder),
#         "mode": "oxylabs-universal",
#     }

# # =========================
# # CLI / quick test
# # =========================
# if __name__ == "__main__":
#     TEST_URL = "https://www.currys.co.uk/products/vq-dexter-portable-dabfm-radio-laura-ashley-elveden-navy-10220700.html"
#     data = scrape_currys_with_oxylabs(TEST_URL, download_images_flag=True, max_images=None)
#     print(json.dumps(data, indent=2, ensure_ascii=False))





# curryss.py
# Python 3.9+
# pip install requests beautifulsoup4 lxml

from __future__ import annotations
import os, re, json, hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

# =========================
# Config (set your creds via env or hardcode here)
# =========================
OXY_USER = os.getenv("OXY_USER", "Muzamil_wUDhn")
OXY_PASS = os.getenv("OXY_PASS", "Muzamil_13111")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
ACCEPT_LANG = "en-GB,en;q=0.9"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data_currys"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# Generic helpers
# =========================
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _safe_name(s: str, max_len: int = 50) -> str:
    """Create a safe filename with length limit to prevent Windows path issues."""
    s = _clean(s)
    s = re.sub(r"[^\w.\-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:max_len] or "product"

def _stable_id_from_url(url: str) -> str:
    # Prefer 8-digit product id in URL; else short hash
    m = re.search(r"-([0-9]{8})\.html(?:$|\?)", url)
    if m:
        return m.group(1)
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

# =========================
# Currys-specific helpers (PID, URLs, images, stock)
# =========================
def _currys_pid_from_url(u: str) -> Optional[str]:
    m = re.search(r"-([0-9]{8})\.html(?:$|\?)", u)
    return m.group(1) if m else None

def _absolute(u: str, base: str = "https://www.currys.co.uk") -> str:
    if not u:
        return u
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return base.rstrip("/") + u
    return u

def _upgrade_currys_image(u: str) -> str:
    # Replace any $t-...$ token with $l-large$ and ensure absolute URL
    u = re.sub(r"\$t-[^$]*\$", "$l-large$", u)
    return _absolute(u, "https://www.currys.co.uk")

def _is_pdp_image(url: str, pid: str) -> bool:
    """
    Accept only:
      https://media.currys.biz/i/currysprod/<PID>
      https://media.currys.biz/i/currysprod/<PID>_<NNN>  (001..006)
    Reject loaders, stickers, svgs, different product IDs, and 'g-small' aux art.
    """
    url = _absolute(url)
    if not url.startswith("https://media.currys.biz/i/currysprod/"):
        return False
    core = url.split("?")[0]  # strip query
    m = re.match(rf"https://media\.currys\.biz/i/currysprod/{pid}(?:_(\d{{3}}))?$", core)
    if not m:
        return False
    if m.group(1) and m.group(1) not in {f"{i:03d}" for i in range(0, 7)}:
        return False
    return True

def _collect_images(soup: BeautifulSoup, pid: str) -> List[str]:
    """
    Read image candidates from the carousel and product gallery, then
    whitelist strictly to the PID set: <pid>, <pid>_001.._006.
    Return at most 7 images in canonical order.
    """
    cand: List[str] = []

    # Primary: carousel indicators (thumbnails often carry correct src[*])
    for el in soup.select(".carouselindicators img[src], .carouselindicators source[srcset]"):
        u = el.get("src") or el.get("srcset") or ""
        if not u:
            continue
        if "," in u:  # srcset -> take largest (last)
            u = u.split(",")[-1].strip().split(" ")[0]
        cand.append(_upgrade_currys_image(u))

    # Fallback: any declared product gallery component
    if not cand:
        for el in soup.select("[data-component='product-gallery'] img[src], [data-component='product-gallery'] source[srcset]"):
            u = el.get("src") or el.get("srcset") or ""
            if not u:
                continue
            if "," in u:
                u = u.split(",")[-1].strip().split(" ")[0]
            cand.append(_upgrade_currys_image(u))

    # Whitelist & de-duplicate (preserve first occurrence order)
    seen, whitelisted = set(), []
    for u in cand:
        if _is_pdp_image(u, pid) and u not in seen:
            seen.add(u)
            whitelisted.append(u)

    # Canonical ordering: main, then 001..006 if present
    ordered: List[str] = []
    main_core = f"https://media.currys.biz/i/currysprod/{pid}"
    if any(x.split("?")[0] == main_core for x in whitelisted):
        ordered.append(_upgrade_currys_image(f"{main_core}?$l-large$&fmt=auto"))
    for i in range(1, 7):
        core = f"{main_core}_{i:03d}"
        if any(x.split("?")[0] == core for x in whitelisted):
            ordered.append(_upgrade_currys_image(f"{core}?$l-large$&fmt=auto"))

    # If nothing matched canonical order (very rare), keep first seven that passed whitelist
    final = ordered if ordered else whitelisted
    return final[:7]

def _detect_stock(soup: BeautifulSoup) -> tuple[Optional[bool], str]:
    """
    Currys CTA looks like:
      <div class="addToCartActionButton ...">
        <button class="add-to-cart ...">Add to basket</button>
    """
    btn = soup.select_one("button.add-to-cart, .addToCartActionButton button")
    if btn:
        disabled = btn.has_attr("disabled") or str(btn.get("aria-disabled", "")).lower() == "true"
        return (not disabled, "Add to basket" + (" (disabled)" if disabled else ""))
    # Fallback text scan
    body = _clean(soup.get_text(" ", strip=True)).lower()
    if any(t in body for t in ["out of stock", "sold out", "unavailable"]):
        return (False, "Unavailable")
    if "in stock" in body:
        return (True, "In stock")
    return (None, "")


# =========================
# Invalid Link Detection
# =========================
def _check_invalid_product_page(soup: BeautifulSoup, url: str, pid: str) -> tuple[bool, str]:
    """
    Check if the page is NOT a valid product page.
    
    Currys redirects unavailable products to category pages.
    
    Detection methods:
    1. URL changed to category page (no product ID in URL)
    2. No JSON-LD Product schema found
    3. Page title/H1 is a category name (e.g., "Radios", "TVs", "Laptops")
    4. No product-specific elements (price, add-to-cart for THIS product)
    5. Multiple product cards visible (category/search page)
    6. No product images for the specific PID
    
    Returns:
        (is_invalid: bool, reason: str)
    """
    page_text = soup.get_text(" ", strip=True).lower()
    
    # ========== CHECK 1: JSON-LD Product Schema ==========
    has_product_schema = False
    product_name_from_schema = ""
    
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(tag.string or "")
            items = obj if isinstance(obj, list) else [obj]
            for item in items:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    has_product_schema = True
                    product_name_from_schema = item.get("name", "")
                    break
        except Exception:
            continue
        if has_product_schema:
            break
    
    # ========== CHECK 2: Product Detail Container ==========
    # Currys product pages have specific containers
    product_detail = soup.select_one(
        "#js-product-detail, "
        "[data-component='product-detail'], "
        "[data-test='product-detail-page'], "
        ".pdp-container"
    )
    
    # ========== CHECK 3: Product Images for THIS PID ==========
    has_pid_images = False
    if pid:
        for img in soup.select("img[src*='media.currys.biz']"):
            src = img.get("src", "")
            if pid in src:
                has_pid_images = True
                break
    
    # ========== CHECK 4: Category Page Indicators ==========
    # Category pages have product grids/lists with multiple products
    product_cards = soup.select(
        "[data-component='product-card'], "
        "[data-test='product-card'], "
        ".product-card, "
        ".productCard, "
        "[class*='ProductCard'], "
        ".product-list-item"
    )
    has_multiple_products = len(product_cards) >= 3
    
    # ========== CHECK 5: Pagination (Category Page) ==========
    pagination = soup.select_one(
        "[data-component='pagination'], "
        ".pagination, "
        "[aria-label='Pagination'], "
        "nav[aria-label*='page']"
    )
    
    # ========== CHECK 6: Category-style H1 ==========
    h1 = soup.select_one("h1")
    h1_text = _clean(h1.get_text(" ", strip=True)) if h1 else ""
    
    # Common category names that indicate redirect
    category_keywords = [
        "radios", "tvs", "televisions", "laptops", "tablets", "phones",
        "headphones", "speakers", "cameras", "appliances", "computing",
        "gaming", "smart home", "wearables", "accessories", "audio",
        "washing machines", "fridges", "freezers", "dishwashers",
        "vacuum cleaners", "microwaves", "kettles", "toasters",
        "coffee machines", "air fryers", "blenders", "food processors"
    ]
    
    h1_lower = h1_text.lower()
    is_category_title = any(cat == h1_lower or h1_lower.endswith(f" {cat}") for cat in category_keywords)
    
    # Also check if H1 is very short and generic (likely category)
    is_short_generic_title = len(h1_text) < 20 and not any(c.isdigit() for c in h1_text)
    
    # ========== CHECK 7: "Product not found" messages ==========
    not_found_phrases = [
        "product not found",
        "page not found",
        "item no longer available",
        "this product is no longer available",
        "sorry, we couldn't find",
        "this item has been discontinued",
        "no longer stocked",
    ]
    has_not_found_message = any(phrase in page_text for phrase in not_found_phrases)
    
    # ========== CHECK 8: Filter/Sort Controls (Category Page) ==========
    has_filters = soup.select_one(
        "[data-component='filter'], "
        "[data-test='filter'], "
        ".filter-panel, "
        ".facet-navigation, "
        "[aria-label*='Filter']"
    ) is not None
    
    # ========== DECISION LOGIC ==========
    
    # Strong indicators of INVALID page:
    if has_not_found_message:
        return True, "Product not found message detected"
    
    if has_multiple_products and pagination:
        return True, "Category page detected (multiple products + pagination)"
    
    if has_multiple_products and has_filters:
        return True, "Category page detected (multiple products + filters)"
    
    if is_category_title and not has_product_schema:
        return True, f"Category page detected (H1='{h1_text}', no Product schema)"
    
    if is_category_title and has_multiple_products:
        return True, f"Category page detected (H1='{h1_text}', multiple product cards)"
    
    # If we have a PID but no images for it, and no product schema
    if pid and not has_pid_images and not has_product_schema:
        return True, f"No product data found for PID {pid}"
    
    # Weak indicators combined:
    # Short generic title + no product detail container + no schema
    if is_short_generic_title and not product_detail and not has_product_schema:
        return True, f"No product content found (H1='{h1_text}')"
    
    # ========== VALID INDICATORS ==========
    # If we have Product schema, it's likely valid
    if has_product_schema and product_name_from_schema:
        return False, "Valid: Product schema found"
    
    # If we have product detail container and PID images
    if product_detail and has_pid_images:
        return False, "Valid: Product detail page with images"
    
    # If we have add-to-cart button specific to this product
    add_to_cart = soup.select_one("button.add-to-cart, .addToCartActionButton button")
    if add_to_cart and product_detail:
        return False, "Valid: Product page with add-to-cart"
    
    # Default: if nothing strongly indicates invalid, assume valid
    # But log a warning
    return False, "Uncertain: defaulting to valid"


# =========================
# Oxylabs client
# =========================
def oxy_post(payload: dict) -> dict:
    r = requests.post(
        "https://realtime.oxylabs.io/v1/queries",
        auth=(OXY_USER, OXY_PASS),
        json=payload,
        timeout=90
    )
    r.raise_for_status()
    return r.json()

def oxy_fetch_html(url: str, geo: str = "United Kingdom") -> str:
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
        "geo_location": geo,
        "headers": {"User-Agent": UA, "Accept-Language": ACCEPT_LANG},
    }
    data = oxy_post(payload)
    results = data.get("results") or []
    if not results or "content" not in results[0]:
        raise RuntimeError("Oxylabs: no HTML content returned")
    html = results[0]["content"] or ""
    if "<html" not in html.lower():
        raise RuntimeError("Oxylabs: returned payload is not HTML")
    return html

# =========================
# Parser
# =========================
def parse_currys(html: str, url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    pid = _currys_pid_from_url(url) or ""
    
    # ========== CHECK FOR INVALID LINK FIRST ==========
    is_invalid, invalid_reason = _check_invalid_product_page(soup, url, pid)
    
    if is_invalid:
        print(f"[Currys] ⚠️ INVALID LINK: {url}")
        print(f"[Currys] Reason: {invalid_reason}")
        return {
            "name": "Invalid Link - Product Not Available",
            "price": "N/A",
            "price_source": "none",
            "in_stock": False,
            "stock_text": invalid_reason,
            "description": "",
            "image_urls": [],
            "listing_status": "invalid",
            "invalid_reason": invalid_reason,
        }
    # ===================================================

    # Name & JSON-LD
    name = ""
    jld: Dict[str, Any] = {}
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(tag.string or "")
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("@type") == "Product":
            jld = obj
            break
        if isinstance(obj, list):
            for e in obj:
                if isinstance(e, dict) and e.get("@type") == "Product":
                    jld = e
                    break
        if jld:
            break

    if jld:
        name = _clean(jld.get("name") or "")
    if not name:
        h1 = soup.select_one("#js-product-detail h1") or soup.find("h1")
        if h1:
            name = _clean(h1.get_text(" ", strip=True))
    name = name or "Unknown Product"

    # Price
    price, price_source = "N/A", "none"
    if jld and isinstance(jld.get("offers"), dict) and jld["offers"].get("price"):
        try:
            val = float(str(jld["offers"]["price"]).replace(",", ""))
            price, price_source = f"{val:.2f} GBP", "jsonld"
        except Exception:
            pass
    if price == "N/A":
        el = soup.select_one(
            '[data-component="product-price"] h2, '
            '[data-test="product-price-primary"] h2, '
            '.pdp-price h2, .price h2'
        )
        if el:
            m = re.search(r"£\s*([\d,]+(?:\.\d{1,2})?)", el.get_text(" ", strip=True))
            if m:
                val = m.group(1).replace(",", "")
                if "." not in val:
                    val += ".00"
                price, price_source = f"{val} GBP", "onsite"

    # Stock
    in_stock, stock_text = _detect_stock(soup)

    # Description
    desc = ""
    if jld and jld.get("description"):
        desc = _clean(jld["description"])
    if not desc:
        for sel in (
            '[data-component="product-description"]',
            "#js-product-detail [data-auto='product-description']",
            ".productDescription",
            ".pdp-description",
        ):
            el = soup.select_one(sel)
            if el:
                desc = el.get_text("\n", strip=True)
                desc = re.sub(r"[ \t]+\n", "\n", desc)
                desc = _clean(desc)
                break

    # Images (strict to PID 0..6)
    image_urls: List[str] = _collect_images(soup, pid) if pid else []

    return {
        "name": name,
        "price": price,
        "price_source": price_source,
        "in_stock": (False if in_stock is None else in_stock),
        "stock_text": stock_text or ("In stock" if in_stock else "Unavailable"),
        "description": desc,
        "image_urls": image_urls,
        "listing_status": "active",
    }

# =========================
# Image downloader
# =========================
def download_images_jpg(urls: List[str], folder: Path, referer: str,
                        pid: Optional[str] = None,
                        max_images: Optional[int] = None) -> List[str]:
    if max_images is not None:
        urls = urls[:max_images]
    saved: List[str] = []
    folder.mkdir(parents=True, exist_ok=True)
    h = {
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Referer": referer,
        "Connection": "keep-alive",
    }
    for i, u in enumerate(urls, 1):
        try:
            # Belt-and-braces PID filter
            if pid and not _is_pdp_image(u, pid):
                continue
            r = requests.get(u, headers=h, timeout=30)
            if r.status_code == 200 and r.content:
                ext = ".jpg"
                ct = (r.headers.get("Content-Type") or "").lower()
                if "webp" in ct:
                    ext = ".webp"
                elif "png" in ct:
                    ext = ".png"
                out = folder / f"{i:02d}{ext}"
                out.write_bytes(r.content)
                saved.append(str(out))
            else:
                print("  ! image HTTP", r.status_code, u)
        except Exception as e:
            print("  ! image error:", u, e)
    return saved

# =========================
# Orchestrator
# =========================
def scrape_currys_with_oxylabs(url: str,
                               download_images_flag: bool = True,
                               max_images: Optional[int] = None) -> Dict[str, Any]:
    html = oxy_fetch_html(url, geo="United Kingdom")
    parsed = parse_currys(html, url)
    
    # ========== HANDLE INVALID LINK ==========
    if parsed.get("listing_status") == "invalid":
        return {
            "url": url,
            "name": parsed["name"],
            "price": parsed["price"],
            "price_source": parsed["price_source"],
            "in_stock": parsed["in_stock"],
            "stock_text": parsed["stock_text"],
            "description": parsed["description"],
            "image_count": 0,
            "image_urls": [],
            "images_downloaded": [],
            "folder": "",
            "mode": "oxylabs-universal",
            "listing_status": "invalid",
            "invalid_reason": parsed.get("invalid_reason", "Product not available"),
        }
    # =========================================

    pid = _currys_pid_from_url(url) or _stable_id_from_url(url)
    
    # FIXED: Limit folder name length to prevent Windows path issues
    safe_product_name = _safe_name(parsed['name'], max_len=40)
    safe_pid = pid[:12] if len(pid) > 12 else pid
    folder = DATA_DIR / f"currys_{safe_product_name}_{safe_pid}"
    folder.mkdir(parents=True, exist_ok=True)

    images_downloaded: List[str] = []
    if download_images_flag and parsed["image_urls"]:
        print(f"Downloading {min(len(parsed['image_urls']), max_images) if max_images else len(parsed['image_urls'])} images …")
        images_downloaded = download_images_jpg(
            parsed["image_urls"], folder, referer=url, pid=_currys_pid_from_url(url), max_images=max_images
        )

    return {
        "url": url,
        "name": parsed["name"],
        "price": parsed["price"],
        "price_source": parsed["price_source"],
        "in_stock": parsed["in_stock"],
        "stock_text": parsed["stock_text"],
        "description": parsed["description"],
        "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
        "image_urls": parsed["image_urls"],
        "images_downloaded": images_downloaded,
        "folder": str(folder),
        "mode": "oxylabs-universal",
        "listing_status": "active",
    }

# # =========================
# # CLI / quick test
# # =========================
# if __name__ == "__main__":
#     TEST_URL = "https://www.currys.co.uk/products/vq-dexter-portable-dabfm-radio-laura-ashley-elveden-navy-10220700.html"
#     data = scrape_currys_with_oxylabs(TEST_URL, download_images_flag=True, max_images=None)
#     print(json.dumps(data, indent=2, ensure_ascii=False))