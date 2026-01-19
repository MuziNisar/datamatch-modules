


# range.py  (The Range via Oxylabs + Playwright Hybrid)
# Python 3.10+
# pip install requests bs4 lxml pillow playwright
# playwright install chromium
# Version: 2.0 - Fixed variant filtering and image downloads

from __future__ import annotations
import os, re, time, json, html, hashlib, base64
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from urllib.parse import urlsplit, urljoin
from io import BytesIO

import requests
from requests.exceptions import RequestException, ReadTimeout, ConnectionError
from bs4 import BeautifulSoup
from PIL import Image

# Playwright for browser-based image downloads
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("⚠ Playwright not installed. Install with: pip install playwright && playwright install chromium")

# Suppress SSL warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

__version__ = "2.0"

# =========================
# Config / Paths
# =========================
UA_STR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)
ACCEPT_LANG = "en-GB,en;q=0.9"

try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()

SAVE_DIR = BASE_DIR / "data1"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

BASE_HOST = "https://www.therange.co.uk"

# =========================
# Small helpers
# =========================
def _clean(s: str) -> str:
    s = html.unescape(s or "")
    s = s.replace("\r", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _safe_name(name: str) -> str:
    n = re.sub(r"[^\w\s-]", "", name or "").strip().replace(" ", "_")
    return n[:100] or "NA"

def _retailer_slug(u: str) -> str:
    host = urlsplit(u).netloc.lower()
    host = re.sub(r"^www\.", "", host)
    return (host.split(".")[0] or "site")

def _stable_id_from_url(u: str) -> str:
    m = re.search(r"#(\d{5,})\b", u) or re.search(r"(\d{7,})", u)
    return m.group(1) if m else hashlib.sha1(u.encode("utf-8")).hexdigest()[:10]

def _abs(u: str) -> str:
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http"):
        return u
    return urljoin(BASE_HOST, u)

def _dedupe_preserve(urls: List[str]) -> List[str]:
    seen, out = set(), []
    for u in urls:
        k = re.sub(r"\?.*$", "", u or "")
        if k and k not in seen:
            seen.add(k)
            out.append(u)
    return out

GBP_RX = re.compile(r"£\s*([0-9][\d,]*(?:\.\d{1,2})?)")

def _parse_price(text: str) -> Optional[str]:
    m = GBP_RX.search(text or "")
    if not m:
        return None
    return f"{m.group(1).replace(',', '')} GBP"

def _normalize_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return u
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    u = re.sub(r"\s+", "%20", u)
    return u

def _is_valid_image(data: bytes) -> bool:
    """Check if bytes are valid image data by magic bytes."""
    if not data or len(data) < 4:
        return False
    return data[:4] in [
        b'\xff\xd8\xff\xe0', b'\xff\xd8\xff\xe1', b'\xff\xd8\xff\xe2', b'\xff\xd8\xff\xe3',
        b'\x89PNG', b'GIF8',
    ] or data[:2] == b'\xff\xd8'

def _save_as_jpg(data: bytes, out_path: Path) -> bool:
    """Convert any image format to JPEG and save."""
    try:
        img = Image.open(BytesIO(data))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(out_path, format="JPEG", quality=92, optimize=True)
        return True
    except Exception:
        return False

# =========================
# Oxylabs creds + client
# =========================
def _oxy_creds() -> Tuple[str, str]:
    try:
        from oxylabs_secrets import OXY_USER, OXY_PASS
        if OXY_USER and OXY_PASS:
            return OXY_USER, OXY_PASS
    except Exception:
        pass

    user = os.getenv("OXYLABS_USERNAME") or os.getenv("OXY_USER", "")
    pwd  = os.getenv("OXYLABS_PASSWORD") or os.getenv("OXY_PASS", "")
    if not user or not pwd:
        raise RuntimeError(
            "Missing Oxylabs credentials. Set OXYLABS_USERNAME / OXYLABS_PASSWORD "
            "or provide oxylabs_secrets.py with OXY_USER/OXY_PASS."
        )
    return user, pwd

def _oxy_call(
    payload: dict,
    *,
    connect_timeout: int = 25,
    read_timeout: int = 45,
    retries: int = 2,
    backoff: float = 1.5,
) -> dict:
    """Low-level Oxylabs call with retries and timeouts."""
    user, pwd = _oxy_creds()
    last_err: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            r = requests.post(
                "https://realtime.oxylabs.io/v1/queries",
                auth=(user, pwd),
                json=payload,
                timeout=(connect_timeout, read_timeout),
            )
            r.raise_for_status()
            return r.json()

        except (ReadTimeout, ConnectionError) as e:
            last_err = e
            if attempt >= retries:
                raise RuntimeError(
                    f"Oxylabs request timed out after {retries} attempts. Last error: {e}"
                ) from e
            sleep_for = backoff ** attempt
            print(f"[OXY] Timeout, retry {attempt}/{retries} in {sleep_for:.1f}s…")
            time.sleep(sleep_for)

        except RequestException as e:
            raise RuntimeError(f"Oxylabs HTTP error: {e}") from e

    if last_err:
        raise RuntimeError(f"Oxylabs failed: {last_err}")
    raise RuntimeError("Oxylabs unknown error")

def oxy_fetch_html(url: str, accept_lang: str = ACCEPT_LANG, timeout: int = 60) -> str:
    """Fetch rendered HTML using Oxylabs Web Scraper API."""
    url = _normalize_url(url)
    payload = {
        "source": "universal",
        "url": url,
        "parse": False,
        "render": "html",
        "geo_location": "United Kingdom",
        "user_agent_type": "desktop",
        "headers": {
            "User-Agent": UA_STR,
            "Accept-Language": accept_lang,
        },
    }

    resp = _oxy_call(payload, connect_timeout=25, read_timeout=timeout)
    content = (resp.get("results") or [{}])[0].get("content") or ""
    if not content or not re.search(r"<html|<head|<body", content, re.I):
        raise RuntimeError("Oxylabs returned non-HTML / empty content")
    return content

# =========================
# The Range HTML parsers
# =========================
def _extract_name(soup: BeautifulSoup) -> str:
    el = soup.select_one("#product-dyn-title")
    if el:
        return _clean(el.get_text(" ", strip=True))
    h1 = soup.select_one("h1")
    if h1:
        return _clean(h1.get_text(" ", strip=True))
    t = soup.title.string if soup.title else ""
    return _clean((t or "").split("|")[0]) or "Unknown_Product"

def _extract_price(soup: BeautifulSoup) -> Tuple[str, str]:
    price_el = soup.select_one(
        "#min_price, [itemprop='price'], .price .amount, .product-price"
    )
    if price_el:
        p = _parse_price(price_el.get_text(" ", strip=True))
        if p:
            return p, "onsite"
    p = _parse_price(soup.get_text(" ", strip=True))
    if p:
        return p, "page"
    return "N/A", "none"

def _extract_stock(soup: BeautifulSoup) -> Tuple[Optional[bool], Optional[str]]:
    # Check for out of stock button first
    out_btn = soup.select_one("#product-dyn-out-of-stock-btn")
    if out_btn and out_btn.get("style", "").find("inline-block") != -1:
        return False, "Out of stock"
    
    # Check for add to basket button (if visible, item is in stock)
    add_btn = soup.select_one("#product-dyn-add-to-bskt-btn")
    if add_btn:
        style = add_btn.get("style", "")
        # If button is visible (display: inline-block), item is in stock
        if "inline-block" in style or not style or "none" not in style:
            # Check if button is not disabled
            if not add_btn.get("disabled"):
                return True, "In stock"
    
    # Fallback: check for generic add to basket/cart buttons
    btn = soup.find(
        lambda t: t.name == "button"
        and re.search(r"add to basket|add to cart|buy now", t.get_text(" ", strip=True), re.I)
        and not t.get("disabled")
        and "none" not in t.get("style", "")
    )
    if btn:
        return True, "In stock"

    # Check text content
    body = soup.get_text(" ", strip=True).lower()
    if "out of stock" in body or "unavailable" in body or "sold out" in body:
        return False, "Out of stock"
    if "in stock" in body or "available" in body:
        return True, "In stock"
    
    return None, None


def _get_selected_variant_id(soup: BeautifulSoup, url: str) -> Optional[str]:
    """
    Determine which variant is currently selected on the page.
    The Range uses data-variant attributes to track which color/variant is active.
    """
    # Method 1: Find the currently selected thumbnail (has class 'rsNavSelected')
    selected_thumb = soup.select_one(".rsThumbsContainer .rsNavItem.rsNavSelected img.rsTmb[data-variant]")
    if selected_thumb:
        variant = selected_thumb.get("data-variant")
        if variant:
            return variant
    
    # Method 2: Check which variant appears most in the visible slider thumbnails
    # The slider typically shows only the selected variant's images
    variant_counts: Dict[str, int] = {}
    for img in soup.select(".rsThumbsContainer img.rsTmb[data-variant]"):
        vid = img.get("data-variant")
        if vid:
            variant_counts[vid] = variant_counts.get(vid, 0) + 1
    
    if variant_counts:
        # Return variant with most images in the visible slider
        return max(variant_counts.items(), key=lambda x: x[1])[0]
    
    # Method 3: Get first variant from available-imgs as fallback
    first_li = soup.select_one("#available-imgs li[data-variant]")
    if first_li:
        return first_li.get("data-variant")
    
    return None


def _extract_description_and_images(
    soup: BeautifulSoup, max_images: Optional[int], url: str = ""
) -> Tuple[str, List[str], Optional[str]]:
    """
    Extract description and images for the SELECTED variant only.
    Returns: (description, image_urls, variant_id)
    """
    # ----- Description -----
    parts: List[str] = []

    desc_box = soup.select_one(
        "#product-description, .product-description, #product-description-tab"
    )
    if desc_box:
        text = _clean(desc_box.get_text("\n", strip=True))
        if text and len(text) > 40:
            parts.append(text)

    # Features / bullets
    features = soup.select(
        "#product-dyn-features-ul li span, "
        "#product-dyn-features-ul li, "
        ".product-features li"
    )
    bullets, seen = [], set()
    for li in features:
        t = _clean(li.get_text(" ", strip=True))
        tl = t.lower()
        if t and tl not in seen:
            seen.add(tl)
            bullets.append(f"• {t}")
    if bullets:
        parts.append("\n".join(bullets))

    if parts:
        all_lines, seen_lines = [], set()
        for block in parts:
            for line in block.splitlines():
                L = line.strip()
                if not L:
                    all_lines.append("")
                    continue
                if L.lower() in seen_lines:
                    continue
                seen_lines.add(L.lower())
                all_lines.append(L)
        description = re.sub(r"\n{3,}", "\n\n", "\n".join(all_lines)).strip()
    else:
        description = ""

    # ----- Determine selected variant -----
    selected_variant = _get_selected_variant_id(soup, url)
    
    # ----- Get all available variants for logging -----
    all_variants = set()
    variant_image_counts: Dict[str, int] = {}
    for li in soup.select("#available-imgs li[data-variant]"):
        vid = li.get("data-variant")
        if vid:
            all_variants.add(vid)
            variant_image_counts[vid] = variant_image_counts.get(vid, 0) + 1
    
    if selected_variant and len(all_variants) > 1:
        print(f"  [Variant] Selected: {selected_variant}")
        print(f"  [Variant] Available: {dict(variant_image_counts)}")

    # ----- Images (filtered by variant) -----
    urls: List[str] = []

    # Primary gallery: big images from #available-imgs, filtered by variant
    for li in soup.select("#available-imgs li"):
        # Filter by variant if we have one and there are multiple variants
        if selected_variant and len(all_variants) > 1:
            li_variant = li.get("data-variant")
            if li_variant and li_variant != selected_variant:
                continue  # Skip images from other variants
        
        a = li.select_one("a.rsImg")
        if not a:
            continue
        u = a.get("data-rsbigimg") or a.get("href") or ""
        if u:
            urls.append(_abs(u))

    # Fallback: if no variant filter worked or no images found, try thumbnails
    if not urls:
        for img in soup.select(".rsThumbsContainer img.rsTmb[src]"):
            # Also filter thumbnails by variant
            if selected_variant and len(all_variants) > 1:
                img_variant = img.get("data-variant")
                if img_variant and img_variant != selected_variant:
                    continue
            u = img.get("data-src") or img.get("src") or ""
            if u:
                urls.append(_abs(u))

    # Clean and dedupe
    cleaned = []
    seen_u = set()
    for u in urls:
        if not u:
            continue
        base = re.sub(r"\?.*$", "", u)
        if "/media/" not in base:
            continue
        if base in seen_u:
            continue
        seen_u.add(base)
        cleaned.append(base)

    cleaned = _dedupe_preserve(cleaned)
    
    if max_images is not None:
        cleaned = cleaned[:max_images]

    return description, cleaned, selected_variant


# =========================
# Image download methods
# =========================

def _download_images_via_oxylabs(
    img_urls: List[str],
    folder: Path,
    page_url: str,
    verbose: bool = True,
) -> List[str]:
    """
    Download images using Oxylabs proxy to bypass hotlink protection.
    This makes individual requests through Oxylabs for each image.
    """
    folder.mkdir(parents=True, exist_ok=True)
    saved: List[str] = []
    
    user, pwd = _oxy_creds()
    
    for idx, url in enumerate(img_urls, 1):
        out_path = folder / f"image_{idx}.jpg"
        
        try:
            # Use Oxylabs universal source to fetch the image
            payload = {
                "source": "universal",
                "url": url,
                "render": "html",  # Need render to handle any JS
                "geo_location": "United Kingdom",
                "user_agent_type": "desktop",
                "headers": {
                    "Referer": page_url,
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                },
            }
            
            r = requests.post(
                "https://realtime.oxylabs.io/v1/queries",
                auth=(user, pwd),
                json=payload,
                timeout=30,
            )
            
            if r.status_code == 200:
                data = r.json()
                results = data.get("results", [])
                if results:
                    content = results[0].get("content", "")
                    # Check if content is base64 encoded image or raw
                    if content:
                        # Try to decode if base64
                        try:
                            img_bytes = base64.b64decode(content)
                        except Exception:
                            # Maybe it's raw bytes or HTML - skip
                            img_bytes = content.encode() if isinstance(content, str) else content
                        
                        if _is_valid_image(img_bytes):
                            if _save_as_jpg(img_bytes, out_path):
                                saved.append(str(out_path))
                                if verbose:
                                    print(f"  ✓ image_{idx} ({len(img_bytes):,} bytes)")
                                continue
            
            if verbose:
                print(f"  ✗ image_{idx}: Failed via Oxylabs")
                
        except Exception as e:
            if verbose:
                print(f"  ✗ image_{idx}: {str(e)[:40]}")
    
    return saved


def _download_images_playwright(
    img_urls: List[str],
    folder: Path,
    page_url: str,
    verbose: bool = True,
) -> List[str]:
    """
    Download images using Playwright by forcing the browser to load them.
    The Range uses hotlink protection, so we must load images through the actual page.
    """
    if not PLAYWRIGHT_AVAILABLE:
        print("⚠ Playwright not available, skipping image downloads")
        return []
    
    folder.mkdir(parents=True, exist_ok=True)
    
    # Create mappings for URL matching
    wanted_urls = set()
    url_to_index = {}
    for idx, url in enumerate(img_urls, 1):
        base = re.sub(r"\?.*$", "", url)
        wanted_urls.add(base)
        url_to_index[base] = idx
    
    captured_images: Dict[int, bytes] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=UA_STR,
            locale="en-GB",
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        
        # Intercept ALL image responses
        def handle_response(response):
            try:
                resp_url = response.url
                base_url = re.sub(r"\?.*$", "", resp_url)
                
                if base_url in wanted_urls and response.status == 200:
                    content_type = response.headers.get("content-type", "")
                    if "image" in content_type:
                        body = response.body()
                        if body and len(body) > 1000 and _is_valid_image(body):
                            idx = url_to_index.get(base_url, 0)
                            if idx and idx not in captured_images:
                                captured_images[idx] = body
                                if verbose:
                                    print(f"  ✓ Captured image_{idx} ({len(body):,} bytes)")
            except Exception:
                pass
        
        page.on("response", handle_response)
        
        try:
            if verbose:
                print(f"  Loading product page...")
            
            # Load page and wait for network to settle
            page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
            
            # Wait for gallery to be ready
            try:
                page.wait_for_selector(".rsThumbsContainer", timeout=10000)
            except Exception:
                pass
            
            time.sleep(2)
            
            if verbose:
                print(f"  Initial load captured {len(captured_images)} images")
            
            # Try to trigger all images by interacting with the gallery
            # Method 1: Click on each thumbnail image directly
            thumb_images = page.query_selector_all(".rsThumbsContainer img.rsTmb")
            if verbose:
                print(f"  Found {len(thumb_images)} thumbnail images, clicking each...")
            
            for i, img in enumerate(thumb_images):
                if len(captured_images) >= len(img_urls):
                    break
                try:
                    # Get parent clickable element
                    parent = img.evaluate_handle("el => el.closest('.rsNavItem')")
                    if parent:
                        parent.as_element().click(timeout=2000)
                        time.sleep(0.6)
                except Exception:
                    pass
            
            # Method 2: Use RoyalSlider API if available
            try:
                page.evaluate("""
                    () => {
                        const slider = jQuery('#product-gallery').data('royalSlider');
                        if (slider) {
                            const numSlides = slider.numSlides;
                            for (let i = 0; i < numSlides; i++) {
                                slider.goTo(i);
                            }
                        }
                    }
                """)
                time.sleep(2)
            except Exception:
                pass
            
            # Method 3: Scroll through thumbnails container
            try:
                thumbs_container = page.query_selector(".rsThumbsContainer")
                if thumbs_container:
                    # Scroll to end and back
                    page.evaluate("""
                        (container) => {
                            container.scrollLeft = container.scrollWidth;
                        }
                    """, thumbs_container)
                    time.sleep(1)
            except Exception:
                pass
            
            if verbose:
                print(f"  After interactions: {len(captured_images)}/{len(img_urls)} images")
            
            # Final report
            if len(captured_images) < len(img_urls):
                missing = set(range(1, len(img_urls) + 1)) - set(captured_images.keys())
                if verbose:
                    print(f"  Missing: {sorted(missing)}")
        
        except Exception as e:
            if verbose:
                print(f"  ⚠ Browser error: {str(e)[:80]}")
        
        finally:
            context.close()
            browser.close()
    
    # Save captured images
    saved = []
    for idx in sorted(captured_images.keys()):
        out_path = folder / f"image_{idx}.jpg"
        if _save_as_jpg(captured_images[idx], out_path):
            saved.append(str(out_path))
    
    return saved


def _download_images_direct(
    img_urls: List[str],
    folder: Path,
    page_url: str,
    verbose: bool = True,
) -> List[str]:
    """
    Try direct download with proper headers. Usually fails for protected sites.
    """
    folder.mkdir(parents=True, exist_ok=True)
    saved: List[str] = []
    
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA_STR,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Referer": page_url,
    })
    
    for idx, url in enumerate(img_urls, 1):
        out_path = folder / f"image_{idx}.jpg"
        if out_path.exists():
            continue  # Skip already downloaded
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 200 and _is_valid_image(r.content):
                if _save_as_jpg(r.content, out_path):
                    saved.append(str(out_path))
                    if verbose:
                        print(f"  ✓ image_{idx} ({len(r.content):,} bytes)")
            else:
                if verbose:
                    print(f"  ✗ image_{idx}: HTTP {r.status_code}")
        except Exception as e:
            if verbose:
                print(f"  ✗ image_{idx}: {str(e)[:40]}")
    
    return saved


# =========================
# Public API
# =========================
def scrape_therange_product(
    url: str,
    download_images: bool = True,
    max_images: Optional[int] = 25,
    use_browser: bool = True,
    verbose: bool = True,
) -> Dict:
    """
    Scrape a TheRange product page using Oxylabs (HTML) + Playwright/Oxylabs (images).
    """
    result = {
        "url": url,
        "name": "N/A",
        "price": "N/A",
        "in_stock": None,
        "description": "N/A",
        "stock_text": None,
        "variant_id": None,
        "image_count": 0,
        "image_urls": [],
        "images": [],
        "folder": "",
        "mode": "oxylabs",
    }

    # Fetch HTML via Oxylabs
    if verbose:
        print("Fetching product page via Oxylabs...")
    html_doc = oxy_fetch_html(url, accept_lang=ACCEPT_LANG, timeout=60)
    soup = BeautifulSoup(html_doc, "lxml")

    # Extract product data
    name = _extract_name(soup)
    price, _price_src = _extract_price(soup)
    in_stock, stock_txt = _extract_stock(soup)
    description, img_urls, variant_id = _extract_description_and_images(soup, max_images, url)

    if verbose:
        print(f"  Found {len(img_urls)} images for variant {variant_id}")

    # Create folder
    folder = SAVE_DIR / f"{_retailer_slug(url)}_{_safe_name(name)}_{_stable_id_from_url(url)}"
    folder.mkdir(parents=True, exist_ok=True)

    result.update({
        "name": name,
        "price": price,
        "in_stock": in_stock,
        "stock_text": stock_txt,
        "variant_id": variant_id,
        "description": description,
        "image_urls": img_urls,
        "folder": str(folder),
    })

    # Download images
    if download_images and img_urls:
        if verbose:
            print(f"\nDownloading {len(img_urls)} images...")
        
        saved = []
        saved_indices = set()
        
        # Try Playwright first (only if available AND browsers are installed)
        playwright_ok = False
        if use_browser and PLAYWRIGHT_AVAILABLE:
            try:
                # Quick check if browser exists
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    browser_path = p.chromium.executable_path
                    if browser_path and Path(browser_path).exists():
                        playwright_ok = True
            except Exception as e:
                if verbose:
                    print(f"  ⚠ Playwright check failed: {str(e)[:60]}")
                playwright_ok = False
        
        if playwright_ok:
            if verbose:
                print("\n[Method 1] Playwright browser capture...")
            result["mode"] = "oxylabs(html)+playwright(images)"
            try:
                saved = _download_images_playwright(img_urls, folder, page_url=url, verbose=verbose)
                for path in saved:
                    m = re.search(r"image_(\d+)\.jpg$", path)
                    if m:
                        saved_indices.add(int(m.group(1)))
            except Exception as e:
                if verbose:
                    print(f"  ⚠ Playwright failed: {str(e)[:60]}")
                saved = []
                saved_indices = set()
        else:
            if verbose:
                print("  Playwright not available, using Oxylabs for images...")
            result["mode"] = "oxylabs(html+images)"
        
        # Use Oxylabs proxy for any missing images
        missing_indices = [idx for idx in range(1, len(img_urls) + 1) if idx not in saved_indices]
        
        if missing_indices:
            if verbose:
                print(f"\n[Method 2] Oxylabs proxy for {len(missing_indices)} images...")
            
            user, pwd = _oxy_creds()
            
            for idx in missing_indices:
                img_url = img_urls[idx - 1]
                out_path = folder / f"image_{idx}.jpg"
                
                try:
                    # Use Oxylabs proxy endpoint for direct image fetch
                    proxies = {
                        "http": f"http://{user}:{pwd}@realtime.oxylabs.io:60000",
                        "https": f"http://{user}:{pwd}@realtime.oxylabs.io:60000",
                    }
                    
                    headers = {
                        "User-Agent": UA_STR,
                        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
                        "Accept-Language": ACCEPT_LANG,
                        "Referer": url,
                    }
                    
                    r = requests.get(img_url, proxies=proxies, headers=headers, timeout=30, verify=False)
                    
                    if r.status_code == 200 and r.content and len(r.content) > 1000:
                        if _is_valid_image(r.content):
                            if _save_as_jpg(r.content, out_path):
                                saved.append(str(out_path))
                                saved_indices.add(idx)
                                if verbose:
                                    print(f"  ✓ image_{idx} ({len(r.content):,} bytes)")
                                continue
                    
                    if verbose:
                        print(f"  ✗ image_{idx}: HTTP {r.status_code if r else 'N/A'}")
                        
                except Exception as e:
                    if verbose:
                        print(f"  ✗ image_{idx}: {str(e)[:50]}")
        
        # Sort and finalize
        saved.sort(key=lambda p: int(re.search(r"image_(\d+)", p).group(1)) if re.search(r"image_(\d+)", p) else 0)
        
        result["images"] = saved
        result["image_count"] = len(saved)
        
        if verbose:
            print()
            if len(saved) == len(img_urls):
                print(f"✓ Downloaded all {len(saved)} images successfully!")
            elif len(saved) > 0:
                print(f"⚠ Downloaded {len(saved)}/{len(img_urls)} images")
            else:
                print(f"✗ Failed to download any images")
    else:
        result["image_count"] = len(img_urls)

    return result


# # =========================
# # CLI quick test
# # =========================
# if __name__ == "__main__":
#     print("=" * 70)
#     print(f"TheRange Scraper v{__version__} - Oxylabs + Playwright Hybrid")
#     print("=" * 70)
    
#     TEST_URL = "https://www.therange.co.uk/cooking-and-dining/kitchen-appliances/kettles/laura-ashley-1-7l-dome-kettle#9345635"
    
#     if not PLAYWRIGHT_AVAILABLE:
#         print("\n⚠ Playwright not installed!")
#         print("Install with: pip install playwright && playwright install chromium\n")
    
#     data = scrape_therange_product(
#         TEST_URL,
#         download_images=True,
#         max_images=25,
#         use_browser=True,
#         verbose=True
#     )
    
#     print("\n" + "=" * 70)
#     print("RESULTS:")
#     print("=" * 70)
#     print(json.dumps(data, indent=2, ensure_ascii=False))



