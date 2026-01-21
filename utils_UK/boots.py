
# # boots.py — Boots (UK) product scraper via Oxylabs Universal
# # Credentials must be in oxylabs_secrets.py: OXY_USER, OXY_PASS
# # Version: 2.4 - Fixed page loading timeout

# from __future__ import annotations
# import re, json, time, random, hashlib
# from io import BytesIO
# from pathlib import Path
# from typing import Optional, List, Dict, Any
# from urllib.parse import urlparse, urldefrag

# import requests
# from requests.exceptions import RequestException
# from bs4 import BeautifulSoup
# from PIL import Image

# __version__ = "2.4"

# # ---------- optional AVIF support ----------
# try:
#     import pillow_avif  # noqa: F401
# except Exception:
#     pass

# # ---------- credentials ----------
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS
# except Exception as e:
#     raise RuntimeError("Create oxylabs_secrets.py with OXY_USER, OXY_PASS") from e
# if not (OXY_USER and OXY_PASS):
#     raise RuntimeError("OXY_USER/OXY_PASS empty in oxylabs_secrets.py")

# # ---------- config ----------
# UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
# ACCEPT_LANG = "en-GB,en;q=0.9"
# GEO = "United Kingdom"
# OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"

# BASE_DIR = Path(__file__).resolve().parent
# DATA_DIR = BASE_DIR / "data_boots"
# DATA_DIR.mkdir(parents=True, exist_ok=True)

# # ---------- helpers ----------
# def _clean(s: Optional[str]) -> str:
#     return re.sub(r"\s+", " ", (s or "")).strip()


# def _clean_multiline(s: str) -> str:
#     s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
#     s = re.sub(r"[ \t]+\n", "\n", s)
#     s = re.sub(r"\n{3,}", "\n\n", s)
#     return s.strip()


# def _safe_name(s: str) -> str:
#     s = _clean(s)
#     return re.sub(r"[^\w.\-]+", "_", s)[:120] or "product"


# def _retailer_slug(u: str) -> str:
#     host = urlparse(u).netloc.lower()
#     host = re.sub(r"^www\.", "", host)
#     return (host.split(".")[0] or "site")


# def _stable_id_from_url(u: str) -> str:
#     m = re.search(r"(\d{7,})", u)
#     return m.group(1) if m else hashlib.sha1(u.encode("utf-8")).hexdigest()[:10]


# def _parse_gbp_from_node_text(text: str) -> Optional[str]:
#     m = re.search(r"£\s*([\d,]+(?:\.\d{1,2})?)", text)
#     if not m:
#         return None
#     val = m.group(1).replace(",", "")
#     if "." not in val:
#         val = f"{val}.00"
#     return f"{val} GBP"


# def _img_to_jpg_bytes(raw: bytes) -> bytes:
#     with Image.open(BytesIO(raw)) as im:
#         if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
#             bg = Image.new("RGB", im.size, (255, 255, 255))
#             im_rgba = im.convert("RGBA")
#             bg.paste(im_rgba, mask=im_rgba.split()[-1])
#             out = BytesIO()
#             bg.save(out, format="JPEG", quality=92, optimize=True, progressive=True)
#             return out.getvalue()
#         if im.mode != "RGB":
#             im = im.convert("RGB")
#         out = BytesIO()
#         im.save(out, format="JPEG", quality=92, optimize=True, progressive=True)
#         return out.getvalue()


# # ---------- oxylabs client ----------
# def _build_context(session_id: Optional[str]) -> list[dict]:
#     ctx: list[dict] = []
#     if session_id:
#         ctx.append({"key": "session_id", "value": session_id})
#     ctx.append({"key": "headers", "value": {"User-Agent": UA, "Accept-Language": ACCEPT_LANG}})
#     return ctx


# def oxy_post(payload: dict, timeout: int = 120, retries: int = 6, base_sleep: float = 2.0) -> dict:
#     last_err = None
#     for attempt in range(retries + 1):
#         try:
#             r = requests.post(OXY_ENDPOINT, auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
#             if r.status_code == 200:
#                 data = r.json()
#                 res = data.get("results") or []
#                 if not res:
#                     raise RuntimeError("Oxylabs: empty results")
#                 html = res[0].get("content", "")
#                 if "<html" not in (html or "").lower() and "<body" not in (html or "").lower():
#                     raise RuntimeError("Oxylabs: non-HTML content")
#                 return data

#             if r.status_code in (429, 500, 502, 503, 504):
#                 sleep_s = min((base_sleep * (2 ** attempt)) + random.uniform(0.25, 0.75), 30.0)
#                 time.sleep(sleep_s)
#                 continue

#             try:
#                 err = r.json()
#                 raise RuntimeError(f"Oxylabs HTTP {r.status_code}: {err}")
#             except ValueError:
#                 raise RuntimeError(f"Oxylabs HTTP {r.status_code}: {r.text[:500]}")

#         except (RequestException, ValueError, RuntimeError) as e:
#             last_err = e
#             if attempt < retries:
#                 sleep_s = min((base_sleep * (2 ** attempt)) + random.uniform(0.25, 0.75), 10.0)
#                 time.sleep(sleep_s)
#                 continue
#             raise RuntimeError(f"Oxylabs failed after {retries+1} attempts: {e}") from e
#     raise last_err or RuntimeError("Oxylabs unknown error")


# def oxy_fetch_html(url: str, geo: str = GEO) -> str:
#     url, _ = urldefrag(url)
#     session_id = f"boots-{int(time.time())}-{random.randint(1000,9999)}"
#     payload = {
#         "source": "universal",
#         "url": url,
#         "render": "html",
#         "geo_location": geo,
#         "user_agent_type": "desktop",
#         "context": _build_context(session_id),
#         # Wait for JavaScript to execute
#         "rendering_wait": 5000,  # 5 seconds
#     }
    
#     last_err = None
#     for attempt in range(3):
#         try:
#             timeout = 120 + (attempt * 30)
#             print(f"Attempt {attempt + 1}/3 (timeout: {timeout}s)...")
            
#             data = oxy_post(payload, timeout=timeout)
#             html = data["results"][0]["content"]
            
#             # Check if we got a real page (not a blocked/error page)
#             if len(html) < 5000:
#                 print(f"  ⚠ Short response ({len(html)} bytes), retrying...")
#                 last_err = RuntimeError(f"Short response: {len(html)} bytes")
#                 # Increase rendering wait for next attempt
#                 payload["rendering_wait"] = 8000
#                 time.sleep(3)
#                 continue
            
#             # Check for block indicators
#             html_lower = html.lower()
#             if "access denied" in html_lower and len(html) < 10000:
#                 print(f"  ⚠ Access denied, retrying...")
#                 last_err = RuntimeError("Access denied")
#                 time.sleep(5)
#                 continue
            
#             print(f"✓ Fetched {len(html):,} bytes of HTML")
#             return html
            
#         except Exception as e:
#             last_err = e
#             print(f"  ⚠ Error: {e}")
#             if attempt < 2:
#                 time.sleep(3)
#                 continue
    
#     raise RuntimeError(f"Failed after 3 attempts: {last_err}")


# # ---------- parsing ----------
# def _extract_pid(url: str, soup: BeautifulSoup) -> Optional[str]:
#     """Extract product ID from URL or page content."""
#     # From URL (most reliable)
#     m = re.search(r"(\d{7,})", url)
#     if m:
#         return m.group(1)
    
#     # From add2Cart payload
#     btn = soup.select_one("#add2CartBtn")
#     if btn and btn.has_attr("data-value"):
#         try:
#             obj = json.loads(btn["data-value"].replace("&quot;", '"'))
#             iid = obj.get("id") or ""
#             pm = re.search(r"(\d{7,})", iid)
#             if pm:
#                 return pm.group(1)
#         except Exception:
#             pass
    
#     # From JSON-LD
#     for tag in soup.find_all("script", type="application/ld+json"):
#         try:
#             obj = json.loads(tag.string or "")
#             if isinstance(obj, dict):
#                 sku = obj.get("sku") or obj.get("mpn")
#                 if sku and re.fullmatch(r"\d{7,}", str(sku)):
#                     return str(sku)
#         except Exception:
#             continue
    
#     return None


# def _collect_images_from_aria_labels(html: str, pid: Optional[str]) -> List[str]:
#     """
#     Extract image IDs from aria-label attributes in the HTML.
#     This is the most reliable method for Boots Scene7 viewer.
#     """
#     found_ids: List[str] = []
    
#     # Pattern: aria-label="10349405" or aria-label="10349405_1"
#     for m in re.finditer(r'aria-label="(\d{7,}(?:_\d+)?)"', html):
#         img_id = m.group(1)
        
#         # If we have a PID, only accept matching image IDs
#         if pid:
#             if img_id == pid or img_id.startswith(f"{pid}_"):
#                 if img_id not in found_ids:
#                     found_ids.append(img_id)
#         else:
#             if img_id not in found_ids:
#                 found_ids.append(img_id)
    
#     # Sort to ensure consistent order: base PID first, then _1, _2, etc.
#     def sort_key(img_id: str) -> tuple:
#         if "_" in img_id:
#             base, suffix = img_id.rsplit("_", 1)
#             return (base, int(suffix))
#         return (img_id, -1)
    
#     found_ids.sort(key=sort_key)
    
#     return [f"https://boots.scene7.com/is/image/Boots/{img_id}?wid=1500&hei=1500&fmt=jpg" 
#             for img_id in found_ids]


# def _probe_scene7_sequence(pid: str, max_suffix: int = 15) -> List[str]:
#     """
#     Probe Scene7 CDN directly to find valid images.
#     Detects placeholder images by size (Scene7 placeholders are typically ~16KB).
#     Real product images are usually 50KB+ at 1500x1500.
#     """
#     valid_urls: List[str] = []
#     headers = {"User-Agent": UA, "Accept": "image/*,*/*;q=0.8"}
    
#     # Candidates: pid, pid_1, pid_2, ... pid_N
#     candidates = [pid] + [f"{pid}_{i}" for i in range(1, max_suffix + 1)]
    
#     # Minimum size for a real product image (in bytes)
#     MIN_REAL_IMAGE_SIZE = 25000  # 25KB threshold
    
#     consecutive_small = 0
    
#     for img_id in candidates:
#         url = f"https://boots.scene7.com/is/image/Boots/{img_id}?wid=1500&hei=1500&fmt=jpg"
#         try:
#             r = requests.head(url, headers=headers, timeout=10, allow_redirects=True)
#             ct = (r.headers.get("Content-Type") or "").lower()
#             cl = int(r.headers.get("Content-Length", "0"))
            
#             if r.status_code == 200 and ct.startswith("image/"):
#                 if cl >= MIN_REAL_IMAGE_SIZE:
#                     # Real image
#                     valid_urls.append(url)
#                     consecutive_small = 0
#                 else:
#                     # Small image - likely placeholder
#                     consecutive_small += 1
#                     # Stop after 2 consecutive small images
#                     if consecutive_small >= 2:
#                         break
#             else:
#                 # Non-200 or non-image response
#                 break
                
#         except Exception:
#             break
    
#     return valid_urls


# def parse_boots(html: str, url: str) -> Dict[str, Any]:
#     soup = BeautifulSoup(html, "lxml")

#     # ----- Product ID -----
#     pid = _extract_pid(url, soup)

#     # ----- Name -----
#     name = ""
    
#     # Try itemprop="name" first (most reliable)
#     name_el = soup.select_one('[itemprop="name"]')
#     if name_el:
#         name = _clean(name_el.get_text(" ", strip=True))
    
#     # Try H1
#     if not name:
#         h1 = soup.find("h1")
#         if h1:
#             name = _clean(h1.get_text(" ", strip=True))
    
#     # Try product title div
#     if not name:
#         title_div = soup.select_one("#estore_product_title h1, .pdpTitle")
#         if title_div:
#             name = _clean(title_div.get_text(" ", strip=True))
    
#     # Try og:title
#     if not name:
#         og = soup.find("meta", property="og:title")
#         if og and og.get("content"):
#             name = _clean(og["content"])
    
#     # Try page title
#     if not name and soup.title:
#         name = _clean(soup.title.get_text())
    
#     name = name or "Unknown Product"

#     # ----- Price -----
#     price, price_source = "N/A", "none"
    
#     # Try visible price element first
#     price_el = soup.select_one("#PDP_productPrice, .price, .productPrice")
#     if price_el:
#         gbp = _parse_gbp_from_node_text(price_el.get_text(" ", strip=True))
#         if gbp:
#             price, price_source = gbp, "onsite"
    
#     # Try itemprop="price"
#     if price == "N/A":
#         meta_price = soup.select_one('[itemprop="price"][content]')
#         if meta_price and meta_price.get("content"):
#             try:
#                 val = float(str(meta_price["content"]).strip())
#                 price = f"{val:.2f} GBP"
#                 price_source = "itemprop"
#             except Exception:
#                 pass
    
#     # Try schemaOrgPrice hidden span
#     if price == "N/A":
#         schema_price = soup.select_one("#schemaOrgPrice")
#         if schema_price:
#             try:
#                 val = float(_clean(schema_price.get_text()).replace(",", ""))
#                 price = f"{val:.2f} GBP"
#                 price_source = "schema"
#             except Exception:
#                 pass
    
#     # Try add2CartBtn data-value
#     if price == "N/A":
#         btn = soup.select_one("#add2CartBtn")
#         if btn and btn.has_attr("data-value"):
#             try:
#                 data_val = btn["data-value"].replace("&quot;", '"')
#                 obj = json.loads(data_val)
#                 if "price" in obj:
#                     val = float(str(obj["price"]).replace(",", ""))
#                     price = f"{val:.2f} GBP"
#                     price_source = "button-data"
#             except Exception:
#                 pass
    
#     # Try JSON-LD
#     if price == "N/A":
#         for tag in soup.find_all("script", type="application/ld+json"):
#             try:
#                 obj = json.loads(tag.string or "")
#                 if isinstance(obj, dict):
#                     offers = obj.get("offers")
#                     if isinstance(offers, dict) and offers.get("price"):
#                         val = float(str(offers["price"]).replace(",", ""))
#                         price = f"{val:.2f} GBP"
#                         price_source = "jsonld"
#                         break
#             except Exception:
#                 continue

#     # ----- Availability -----
#     in_stock: Optional[bool] = None
#     availability_message = None
    
#     # Check add to basket button
#     cta = soup.select_one("#add2CartBtn, a[title*='Add to basket' i], button[title*='Add to basket' i]")
#     if cta:
#         disabled = cta.has_attr("disabled") or str(cta.get("aria-disabled", "")).lower() == "true"
#         txt = _clean(cta.get_text(" ", strip=True)).lower()
#         looks_add = "add to basket" in txt or cta.get("id") == "add2CartBtn"
#         if looks_add:
#             in_stock = not disabled
#             availability_message = "in_stock" if in_stock else "add to basket disabled"
    
#     # Check data-shop5 for stock info
#     if in_stock is None:
#         btn = soup.select_one("#add2CartBtn")
#         if btn and btn.has_attr("data-shop5"):
#             try:
#                 data_shop5 = btn["data-shop5"].replace("&quot;", '"')
#                 obj = json.loads(data_shop5)
#                 if obj.get("InStockHomeDel") == "Y":
#                     in_stock = True
#                     availability_message = "in_stock"
#             except Exception:
#                 pass
    
#     # Check page text
#     if in_stock is None:
#         page_txt = _clean(soup.get_text(" ", strip=True)).lower()
#         if "sorry, this product is currently out of stock" in page_txt or "out of stock" in page_txt:
#             in_stock, availability_message = False, "out of stock"
#         elif "temporarily unavailable online" in page_txt:
#             in_stock, availability_message = False, "temporarily unavailable online"
#         elif "stock coming soon" in page_txt:
#             in_stock, availability_message = False, "stock coming soon"

#     # ----- Description -----
#     desc = ""
    
#     # Try product_long_description paragraph
#     desc_p = soup.select_one("#product_long_description")
#     if desc_p:
#         desc = _clean_multiline(desc_p.get_text("\n", strip=True))
    
#     # Try other selectors
#     if not desc:
#         for sel in ["#estore_product_longdesc", ".productDescription_content", "#pdpDescription", ".productDescription"]:
#             el = soup.select_one(sel)
#             if el:
#                 desc = _clean_multiline(el.get_text("\n", strip=True))
#                 break
    
#     # Try meta description
#     if not desc:
#         meta = soup.find("meta", {"name": "description"})
#         if meta and meta.get("content"):
#             desc = _clean(meta["content"])
    
#     description = desc or ""

#     # ----- Images -----
#     # Primary method: Extract from aria-label attributes
#     imgs = _collect_images_from_aria_labels(html, pid)
    
#     # Fallback: Probe Scene7 CDN if HTML parsing found few/no images
#     if pid and len(imgs) < 2:
#         probed = _probe_scene7_sequence(pid, max_suffix=15)
#         if len(probed) > len(imgs):
#             imgs = probed
    
#     # Deduplicate while preserving order
#     seen = set()
#     imgs = [u for u in imgs if not (u in seen or seen.add(u))]

#     return {
#         "pid": pid,
#         "name": name,
#         "price": price,
#         "price_source": price_source,
#         "in_stock": False if in_stock is None else in_stock,
#         "availability_message": availability_message or ("in_stock" if in_stock else "unknown"),
#         "description": description,
#         "image_urls": imgs
#     }


# # ---------- download (JPG only) ----------
# def download_images_jpg(urls: List[str], folder: Path, referer: str, max_images: Optional[int] = None) -> List[str]:
#     if max_images is not None:
#         urls = urls[:max_images]
#     saved: List[str] = []
#     folder.mkdir(parents=True, exist_ok=True)
#     h = {
#         "User-Agent": UA,
#         "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#         "Accept-Language": ACCEPT_LANG,
#         "Referer": referer,
#     }
#     for i, u in enumerate(urls, 1):
#         try:
#             with requests.get(u, headers=h, timeout=40) as r:
#                 ct = (r.headers.get("Content-Type") or "").lower()
#                 if r.status_code == 200 and (ct.startswith("image/") or r.content):
#                     out = folder / f"{i:02d}.jpg"
#                     try:
#                         out.write_bytes(_img_to_jpg_bytes(r.content))
#                         saved.append(str(out))
#                     except Exception:
#                         if ct.startswith(("image/jpeg", "image/jpg")):
#                             out.write_bytes(r.content)
#                             saved.append(str(out))
#                         else:
#                             print(f"  ! convert error: {u}")
#                 else:
#                     print(f"  ! image HTTP {r.status_code} {u} {ct}")
#         except Exception as e:
#             print(f"  ! image error: {u} {e}")
#     return saved


# # ---------- orchestrator ----------
# def scrape_boots_with_oxylabs(url: str,
#                               download_images_flag: bool = True,
#                               max_images: Optional[int] = None) -> Dict[str, Any]:
#     html = oxy_fetch_html(url, geo=GEO)
#     parsed = parse_boots(html, url)

#     folder = DATA_DIR / f"{_retailer_slug(url)}_{_safe_name(parsed['name'])}_{_stable_id_from_url(url)}"
#     folder.mkdir(parents=True, exist_ok=True)

#     images_downloaded: List[str] = []
#     if download_images_flag and parsed["image_urls"]:
#         count = len(parsed['image_urls']) if not max_images else min(len(parsed['image_urls']), max_images)
#         print(f"Downloading {count} images ...")
#         images_downloaded = download_images_jpg(parsed["image_urls"], folder, referer=url, max_images=max_images)

#     return {
#         "url": url,
#         "pid": parsed["pid"],
#         "name": parsed["name"],
#         "price": parsed["price"],
#         "price_source": parsed["price_source"],
#         "in_stock": parsed["in_stock"],
#         "availability_message": parsed["availability_message"],
#         "description": parsed["description"],
#         "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
#         "image_urls": parsed["image_urls"],
#         "images_downloaded": images_downloaded,
#         "folder": str(folder),
#         "mode": "oxylabs-universal"
#     }


# # ---------- CLI ----------
# if __name__ == "__main__":
#     TEST_URL = "https://www.boots.com/vq-monty-dab-daband-digital-radio-and-bluetooth-speaker-laura-ashley-china-rose-10346137"
#     data = scrape_boots_with_oxylabs(TEST_URL, download_images_flag=True, max_images=50)
#     print(json.dumps(data, indent=2, ensure_ascii=False))




# boots.py — Boots (UK) product scraper via Oxylabs Universal
# Credentials must be in oxylabs_secrets.py: OXY_USER, OXY_PASS
# Version: 2.5 - Added invalid link detection for removed/unavailable products

from __future__ import annotations
import re, json, time, random, hashlib
from io import BytesIO
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse, urldefrag

import requests
from requests.exceptions import RequestException
from bs4 import BeautifulSoup
from PIL import Image

__version__ = "2.7"

# ---------- optional AVIF support ----------
try:
    import pillow_avif  # noqa: F401
except Exception:
    pass

# ---------- credentials ----------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception as e:
    raise RuntimeError("Create oxylabs_secrets.py with OXY_USER, OXY_PASS") from e
if not (OXY_USER and OXY_PASS):
    raise RuntimeError("OXY_USER/OXY_PASS empty in oxylabs_secrets.py")

# ---------- config ----------
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
ACCEPT_LANG = "en-GB,en;q=0.9"
GEO = "United Kingdom"
OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data_boots"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------- helpers ----------
def _clean(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _clean_multiline(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _safe_name(s: str) -> str:
    s = _clean(s)
    return re.sub(r"[^\w.\-]+", "_", s)[:120] or "product"


def _retailer_slug(u: str) -> str:
    host = urlparse(u).netloc.lower()
    host = re.sub(r"^www\.", "", host)
    return (host.split(".")[0] or "site")


def _stable_id_from_url(u: str) -> str:
    m = re.search(r"(\d{7,})", u)
    return m.group(1) if m else hashlib.sha1(u.encode("utf-8")).hexdigest()[:10]


def _parse_gbp_from_node_text(text: str) -> Optional[str]:
    m = re.search(r"£\s*([\d,]+(?:\.\d{1,2})?)", text)
    if not m:
        return None
    val = m.group(1).replace(",", "")
    if "." not in val:
        val = f"{val}.00"
    return f"{val} GBP"


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


# ---------- oxylabs client ----------
def _build_context(session_id: Optional[str]) -> list[dict]:
    ctx: list[dict] = []
    if session_id:
        ctx.append({"key": "session_id", "value": session_id})
    ctx.append({"key": "headers", "value": {"User-Agent": UA, "Accept-Language": ACCEPT_LANG}})
    return ctx


def oxy_post(payload: dict, timeout: int = 60, retries: int = 3, base_sleep: float = 2.0) -> dict:
    """
    Post to Oxylabs API with retry logic.
    
    Returns dict with results on success.
    Raises RuntimeError on failure with error details.
    
    Special cases:
    - HTTP 204: No content (page might not exist)
    - HTTP 400 with "session failed": Oxylabs couldn't render the page
    """
    last_err = None
    consecutive_204 = 0
    session_failed = False
    
    for attempt in range(retries + 1):
        try:
            r = requests.post(OXY_ENDPOINT, auth=(OXY_USER, OXY_PASS), json=payload, timeout=timeout)
            
            if r.status_code == 200:
                data = r.json()
                res = data.get("results") or []
                if not res:
                    raise RuntimeError("Oxylabs: empty results")
                html = res[0].get("content", "")
                if "<html" not in (html or "").lower() and "<body" not in (html or "").lower():
                    raise RuntimeError("Oxylabs: non-HTML content")
                return data
            
            # HTTP 204 - No Content (often means page doesn't exist or blocked)
            if r.status_code == 204:
                consecutive_204 += 1
                if consecutive_204 >= 2:
                    # Multiple 204s = page likely doesn't exist
                    raise RuntimeError("INVALID_PAGE:HTTP_204_NO_CONTENT")
                print(f"    HTTP 204 (No Content), retrying...")
                time.sleep(base_sleep)
                continue
            
            # HTTP 400 - Check if session failed (common for removed/blocked pages)
            if r.status_code == 400:
                try:
                    err_data = r.json()
                    err_msg = err_data.get("message", "")
                    if "failed" in err_msg.lower() or "session" in err_msg.lower():
                        session_failed = True
                        # If we already had a 204, this confirms the page is invalid
                        if consecutive_204 > 0:
                            raise RuntimeError("INVALID_PAGE:SESSION_FAILED_AFTER_204")
                        print(f"    HTTP 400: {err_msg}, retrying with new session...")
                        # Generate new session ID for retry
                        if "context" in payload:
                            for ctx in payload["context"]:
                                if ctx.get("key") == "session_id":
                                    ctx["value"] = f"boots-{int(time.time())}-{random.randint(1000,9999)}"
                        time.sleep(base_sleep * 2)
                        continue
                except ValueError:
                    pass
                raise RuntimeError(f"Oxylabs HTTP 400: {r.text[:200]}")

            if r.status_code in (429, 500, 502, 503, 504):
                sleep_s = min((base_sleep * (2 ** attempt)) + random.uniform(0.25, 0.75), 15.0)
                print(f"    HTTP {r.status_code}, sleeping {sleep_s:.1f}s...")
                time.sleep(sleep_s)
                continue

            try:
                err = r.json()
                raise RuntimeError(f"Oxylabs HTTP {r.status_code}: {err}")
            except ValueError:
                raise RuntimeError(f"Oxylabs HTTP {r.status_code}: {r.text[:500]}")

        except (RequestException, ValueError, RuntimeError) as e:
            last_err = e
            err_str = str(e)
            
            # Check if this is our special "invalid page" signal
            if "INVALID_PAGE:" in err_str:
                raise  # Re-raise immediately, don't retry
            
            if attempt < retries:
                sleep_s = min((base_sleep * (2 ** attempt)) + random.uniform(0.25, 0.75), 8.0)
                print(f"    Error: {e}, retrying in {sleep_s:.1f}s...")
                time.sleep(sleep_s)
                continue
            
            # Final failure - check if pattern suggests invalid page
            if consecutive_204 >= 2 or (consecutive_204 > 0 and session_failed):
                raise RuntimeError("INVALID_PAGE:FETCH_FAILED_PATTERN")
            
            raise RuntimeError(f"Oxylabs failed after {retries+1} attempts: {e}") from e
    
    # If we exhausted retries with 204s or session failures, likely invalid page
    if consecutive_204 >= 2 or session_failed:
        raise RuntimeError("INVALID_PAGE:EXHAUSTED_RETRIES")
    
    raise last_err or RuntimeError("Oxylabs unknown error")


def oxy_fetch_html(url: str, geo: str = GEO) -> str:
    """
    Fetch HTML via Oxylabs.
    
    Returns HTML string on success.
    Returns special "INVALID_PAGE" marker HTML if Oxylabs can't fetch (likely removed product).
    Raises RuntimeError on other failures.
    """
    url, _ = urldefrag(url)
    session_id = f"boots-{int(time.time())}-{random.randint(1000,9999)}"
    payload = {
        "source": "universal",
        "url": url,
        "render": "html",
        "geo_location": geo,
        "user_agent_type": "desktop",
        "context": _build_context(session_id),
        # Reduced rendering wait - error pages load fast
        "rendering_wait": 3000,  # 3 seconds
    }
    
    last_err = None
    for attempt in range(3):
        try:
            # Shorter timeouts - error pages shouldn't take long
            timeout = 60 + (attempt * 20)  # 60s, 80s, 100s
            print(f"Attempt {attempt + 1}/3 (timeout: {timeout}s)...")
            
            # Update session ID for each outer attempt
            for ctx in payload["context"]:
                if ctx.get("key") == "session_id":
                    ctx["value"] = f"boots-{int(time.time())}-{random.randint(1000,9999)}"
            
            data = oxy_post(payload, timeout=timeout, retries=2)  # Fewer inner retries
            html = data["results"][0]["content"]
            
            # EARLY CHECK: If it's an error page, accept it immediately
            html_lower = html.lower()
            if "wc_genericerror" in html_lower or "this product has either been removed" in html_lower:
                print(f"✓ Fetched error page ({len(html):,} bytes) - product likely removed")
                return html
            
            # Check if we got a real page (not a blocked/error page)
            if len(html) < 5000:
                # But accept small pages if they contain error indicators
                if "error" in html_lower or "not found" in html_lower or "removed" in html_lower:
                    print(f"✓ Fetched small error page ({len(html):,} bytes)")
                    return html
                    
                print(f"  ⚠ Short response ({len(html)} bytes), retrying...")
                last_err = RuntimeError(f"Short response: {len(html)} bytes")
                payload["rendering_wait"] = 5000
                time.sleep(2)
                continue
            
            # Check for block indicators (but not error pages)
            if "access denied" in html_lower and len(html) < 10000:
                if "wc_genericerror" not in html_lower:
                    print(f"  ⚠ Access denied, retrying...")
                    last_err = RuntimeError("Access denied")
                    time.sleep(3)
                    continue
            
            print(f"✓ Fetched {len(html):,} bytes of HTML")
            return html
            
        except RuntimeError as e:
            err_str = str(e)
            
            # Check if Oxylabs signaled an invalid page
            if "INVALID_PAGE:" in err_str:
                reason = err_str.split("INVALID_PAGE:")[-1]
                print(f"✓ Oxylabs cannot fetch page (likely removed): {reason}")
                # Return a synthetic error page HTML that our parser will recognize
                return f'''<!DOCTYPE html>
<html><head><title>Product Not Found</title></head>
<body>
<div id="WC_GenericError_5" class="content">
    <div id="WC_GenericError_6" class="info">
        <span>This product has either been removed or is no longer available for sale.</span>
        <span>Oxylabs fetch failed: {reason}</span>
    </div>
</div>
</body></html>'''
            
            last_err = e
            print(f"  ⚠ Error: {e}")
            if attempt < 2:
                time.sleep(2)
                continue
    
    raise RuntimeError(f"Failed after 3 attempts: {last_err}")


# ---------- parsing ----------
def _extract_pid(url: str, soup: BeautifulSoup) -> Optional[str]:
    """Extract product ID from URL or page content."""
    # From URL (most reliable)
    m = re.search(r"(\d{7,})", url)
    if m:
        return m.group(1)
    
    # From add2Cart payload
    btn = soup.select_one("#add2CartBtn")
    if btn and btn.has_attr("data-value"):
        try:
            obj = json.loads(btn["data-value"].replace("&quot;", '"'))
            iid = obj.get("id") or ""
            pm = re.search(r"(\d{7,})", iid)
            if pm:
                return pm.group(1)
        except Exception:
            pass
    
    # From JSON-LD
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(tag.string or "")
            if isinstance(obj, dict):
                sku = obj.get("sku") or obj.get("mpn")
                if sku and re.fullmatch(r"\d{7,}", str(sku)):
                    return str(sku)
        except Exception:
            continue
    
    return None


def _collect_images_from_aria_labels(html: str, pid: Optional[str]) -> List[str]:
    """
    Extract image IDs from aria-label attributes in the HTML.
    This is the most reliable method for Boots Scene7 viewer.
    """
    found_ids: List[str] = []
    
    # Pattern: aria-label="10349405" or aria-label="10349405_1"
    for m in re.finditer(r'aria-label="(\d{7,}(?:_\d+)?)"', html):
        img_id = m.group(1)
        
        # If we have a PID, only accept matching image IDs
        if pid:
            if img_id == pid or img_id.startswith(f"{pid}_"):
                if img_id not in found_ids:
                    found_ids.append(img_id)
        else:
            if img_id not in found_ids:
                found_ids.append(img_id)
    
    # Sort to ensure consistent order: base PID first, then _1, _2, etc.
    def sort_key(img_id: str) -> tuple:
        if "_" in img_id:
            base, suffix = img_id.rsplit("_", 1)
            return (base, int(suffix))
        return (img_id, -1)
    
    found_ids.sort(key=sort_key)
    
    return [f"https://boots.scene7.com/is/image/Boots/{img_id}?wid=1500&hei=1500&fmt=jpg" 
            for img_id in found_ids]


def _probe_scene7_sequence(pid: str, max_suffix: int = 15) -> List[str]:
    """
    Probe Scene7 CDN directly to find valid images.
    Detects placeholder images by size (Scene7 placeholders are typically ~16KB).
    Real product images are usually 50KB+ at 1500x1500.
    """
    valid_urls: List[str] = []
    headers = {"User-Agent": UA, "Accept": "image/*,*/*;q=0.8"}
    
    # Candidates: pid, pid_1, pid_2, ... pid_N
    candidates = [pid] + [f"{pid}_{i}" for i in range(1, max_suffix + 1)]
    
    # Minimum size for a real product image (in bytes)
    MIN_REAL_IMAGE_SIZE = 25000  # 25KB threshold
    
    consecutive_small = 0
    
    for img_id in candidates:
        url = f"https://boots.scene7.com/is/image/Boots/{img_id}?wid=1500&hei=1500&fmt=jpg"
        try:
            r = requests.head(url, headers=headers, timeout=10, allow_redirects=True)
            ct = (r.headers.get("Content-Type") or "").lower()
            cl = int(r.headers.get("Content-Length", "0"))
            
            if r.status_code == 200 and ct.startswith("image/"):
                if cl >= MIN_REAL_IMAGE_SIZE:
                    # Real image
                    valid_urls.append(url)
                    consecutive_small = 0
                else:
                    # Small image - likely placeholder
                    consecutive_small += 1
                    # Stop after 2 consecutive small images
                    if consecutive_small >= 2:
                        break
            else:
                # Non-200 or non-image response
                break
                
        except Exception:
            break
    
    return valid_urls


# ---------- INVALID LINK DETECTION ----------
def _check_invalid_product_page(soup: BeautifulSoup, html: str, url: str, verbose: bool = False) -> tuple:
    """
    Check if a Boots product URL has actually returned an error/removed page.
    Returns (is_invalid, reason) tuple.
    
    Boots shows a generic error page when products are removed:
    - WC_GenericError_5/6 div with "removed or is no longer available" message
    - Page still returns 200 OK, not 404
    
    Detection layers (in priority order):
    1. Generic error div (WC_GenericError_*)
    2. Error message patterns in page text
    3. Error page classes with no product name
    4. Missing all product content indicators
    5. Category/search page redirect detection
    """
    page_text = html.lower()
    body_text = _clean(soup.get_text(" ", strip=True)).lower() if soup.body else ""
    
    # ===== Check 1: Generic error div (MOST RELIABLE for Boots) =====
    error_div = soup.select_one("#WC_GenericError_5, #WC_GenericError_6, .genericError, #genericErrorPage")
    if error_div:
        error_text = _clean(error_div.get_text(" ", strip=True)).lower()
        if any(phrase in error_text for phrase in ["removed", "no longer available", "not found"]):
            if verbose:
                print(f"  ⚠ INVALID: Generic error div found - '{error_text[:80]}'")
            return True, "product_removed_error_div"
    
    # ===== Check 2: Error message patterns in page text =====
    error_patterns = [
        "this product has either been removed or is no longer available",
        "this product has been removed",
        "product is no longer available for sale",
        "sorry, this page could not be found",
        "page not found",
        "product not found",
        "we can't find that page",
        "the page you requested cannot be found",
    ]
    for pattern in error_patterns:
        if pattern in body_text:
            if verbose:
                print(f"  ⚠ INVALID: Error pattern found - '{pattern}'")
            return True, f"error_message:{pattern[:40]}"
    
    # ===== Check 3: Error page class with no product name =====
    name_el = soup.select_one('[itemprop="name"], #estore_product_title h1, .pdpTitle')
    h1 = soup.find("h1")
    has_valid_h1 = h1 and len(_clean(h1.get_text())) > 3
    
    error_page_selectors = ".errorPage, .error-page, #errorPage, .genericErrorPage, #WC_GenericError"
    if soup.select_one(error_page_selectors):
        if not name_el and not has_valid_h1:
            if verbose:
                print(f"  ⚠ INVALID: Error page class found with no product name")
            return True, "error_page_no_product"
    
    # ===== Check 4: Missing ALL product content indicators =====
    has_price = bool(soup.select_one('#PDP_productPrice, [itemprop="price"], #schemaOrgPrice, .price, .productPrice'))
    has_add_btn = bool(soup.select_one('#add2CartBtn, [title*="Add to basket" i], button.add-to-basket'))
    has_product_images = bool(soup.select_one('.productImage, #productMainImage, [itemprop="image"], .s7thumb'))
    has_description = bool(soup.select_one('#product_long_description, .productDescription, #pdpDescription'))
    
    # Product detail page indicators in raw HTML
    product_indicators = [
        'product_long_description', 
        'productDescription', 
        'pdpDescription', 
        'scene7viewer',
        'add2CartBtn',
        'PDP_productPrice',
        'estore_product_title'
    ]
    has_any_product_content = any(ind in page_text for ind in product_indicators)
    
    if not has_price and not has_add_btn and not has_product_images and not has_description:
        if not has_any_product_content:
            if verbose:
                print(f"  ⚠ INVALID: No price, no add button, no images, no description, no product content")
            return True, "no_product_content"
    
    # ===== Check 5: Category/search page redirect detection =====
    # Boots category pages have pagination and multiple product cards
    pagination = soup.select_one('.pagination, .paging, #pagination, [class*="pagination"]')
    product_lister = soup.select_one('#productLister, .productLister, .searchResults, .categoryProducts')
    
    if pagination or product_lister:
        product_cards = soup.select('.productCard, .product-card, .productListItem, .product-list-item, [class*="productCard"]')
        if len(product_cards) >= 3:
            if verbose:
                print(f"  ⚠ INVALID: Category/search page detected ({len(product_cards)} product cards)")
            return True, f"category_page:{len(product_cards)}_products"
    
    # ===== All checks passed - page is valid =====
    return False, "valid"


def parse_boots(html: str, url: str, verbose: bool = False) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    # ----- Check for invalid/removed product page FIRST -----
    is_invalid, invalid_reason = _check_invalid_product_page(soup, html, url, verbose=verbose)
    
    if is_invalid:
        if verbose:
            print(f"  ✗ Product page invalid: {invalid_reason}")
        
        # Extract PID from URL even for invalid pages (for logging/tracking)
        pid = None
        m = re.search(r"(\d{7,})", url)
        if m:
            pid = m.group(1)
        
        return {
            "pid": pid or _stable_id_from_url(url),
            "name": "INVALID LINK - Product removed or no longer available",
            "price": "N/A",
            "price_source": "none",
            "in_stock": False,
            "availability_message": invalid_reason,
            "description": "",
            "image_urls": [],
            "is_invalid": True,
            "invalid_reason": invalid_reason
        }

    # ----- Product ID -----
    pid = _extract_pid(url, soup)

    # ----- Name -----
    name = ""
    
    # Try itemprop="name" first (most reliable)
    name_el = soup.select_one('[itemprop="name"]')
    if name_el:
        name = _clean(name_el.get_text(" ", strip=True))
    
    # Try H1
    if not name:
        h1 = soup.find("h1")
        if h1:
            name = _clean(h1.get_text(" ", strip=True))
    
    # Try product title div
    if not name:
        title_div = soup.select_one("#estore_product_title h1, .pdpTitle")
        if title_div:
            name = _clean(title_div.get_text(" ", strip=True))
    
    # Try og:title
    if not name:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            name = _clean(og["content"])
    
    # Try page title
    if not name and soup.title:
        name = _clean(soup.title.get_text())
    
    name = name or "Unknown Product"

    # ----- Price -----
    price, price_source = "N/A", "none"
    
    # Try visible price element first
    price_el = soup.select_one("#PDP_productPrice, .price, .productPrice")
    if price_el:
        gbp = _parse_gbp_from_node_text(price_el.get_text(" ", strip=True))
        if gbp:
            price, price_source = gbp, "onsite"
    
    # Try itemprop="price"
    if price == "N/A":
        meta_price = soup.select_one('[itemprop="price"][content]')
        if meta_price and meta_price.get("content"):
            try:
                val = float(str(meta_price["content"]).strip())
                price = f"{val:.2f} GBP"
                price_source = "itemprop"
            except Exception:
                pass
    
    # Try schemaOrgPrice hidden span
    if price == "N/A":
        schema_price = soup.select_one("#schemaOrgPrice")
        if schema_price:
            try:
                val = float(_clean(schema_price.get_text()).replace(",", ""))
                price = f"{val:.2f} GBP"
                price_source = "schema"
            except Exception:
                pass
    
    # Try add2CartBtn data-value
    if price == "N/A":
        btn = soup.select_one("#add2CartBtn")
        if btn and btn.has_attr("data-value"):
            try:
                data_val = btn["data-value"].replace("&quot;", '"')
                obj = json.loads(data_val)
                if "price" in obj:
                    val = float(str(obj["price"]).replace(",", ""))
                    price = f"{val:.2f} GBP"
                    price_source = "button-data"
            except Exception:
                pass
    
    # Try JSON-LD
    if price == "N/A":
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                obj = json.loads(tag.string or "")
                if isinstance(obj, dict):
                    offers = obj.get("offers")
                    if isinstance(offers, dict) and offers.get("price"):
                        val = float(str(offers["price"]).replace(",", ""))
                        price = f"{val:.2f} GBP"
                        price_source = "jsonld"
                        break
            except Exception:
                continue

    # ----- Availability -----
    in_stock: Optional[bool] = None
    availability_message = None
    
    # Check add to basket button
    cta = soup.select_one("#add2CartBtn, a[title*='Add to basket' i], button[title*='Add to basket' i]")
    if cta:
        disabled = cta.has_attr("disabled") or str(cta.get("aria-disabled", "")).lower() == "true"
        txt = _clean(cta.get_text(" ", strip=True)).lower()
        looks_add = "add to basket" in txt or cta.get("id") == "add2CartBtn"
        if looks_add:
            in_stock = not disabled
            availability_message = "in_stock" if in_stock else "add to basket disabled"
    
    # Check data-shop5 for stock info
    if in_stock is None:
        btn = soup.select_one("#add2CartBtn")
        if btn and btn.has_attr("data-shop5"):
            try:
                data_shop5 = btn["data-shop5"].replace("&quot;", '"')
                obj = json.loads(data_shop5)
                if obj.get("InStockHomeDel") == "Y":
                    in_stock = True
                    availability_message = "in_stock"
            except Exception:
                pass
    
    # Check page text
    if in_stock is None:
        page_txt = _clean(soup.get_text(" ", strip=True)).lower()
        if "sorry, this product is currently out of stock" in page_txt or "out of stock" in page_txt:
            in_stock, availability_message = False, "out of stock"
        elif "temporarily unavailable online" in page_txt:
            in_stock, availability_message = False, "temporarily unavailable online"
        elif "stock coming soon" in page_txt:
            in_stock, availability_message = False, "stock coming soon"

    # ----- Description -----
    desc = ""
    
    # Try product_long_description paragraph
    desc_p = soup.select_one("#product_long_description")
    if desc_p:
        desc = _clean_multiline(desc_p.get_text("\n", strip=True))
    
    # Try other selectors
    if not desc:
        for sel in ["#estore_product_longdesc", ".productDescription_content", "#pdpDescription", ".productDescription"]:
            el = soup.select_one(sel)
            if el:
                desc = _clean_multiline(el.get_text("\n", strip=True))
                break
    
    # Try meta description
    if not desc:
        meta = soup.find("meta", {"name": "description"})
        if meta and meta.get("content"):
            desc = _clean(meta["content"])
    
    description = desc or ""

    # ----- Images -----
    # Primary method: Extract from aria-label attributes
    imgs = _collect_images_from_aria_labels(html, pid)
    
    # Fallback: Probe Scene7 CDN if HTML parsing found few/no images
    if pid and len(imgs) < 2:
        probed = _probe_scene7_sequence(pid, max_suffix=15)
        if len(probed) > len(imgs):
            imgs = probed
    
    # Deduplicate while preserving order
    seen = set()
    imgs = [u for u in imgs if not (u in seen or seen.add(u))]

    return {
        "pid": pid,
        "name": name,
        "price": price,
        "price_source": price_source,
        "in_stock": False if in_stock is None else in_stock,
        "availability_message": availability_message or ("in_stock" if in_stock else "unknown"),
        "description": description,
        "image_urls": imgs,
        "is_invalid": False,
        "invalid_reason": None
    }


# ---------- download (JPG only) ----------
def download_images_jpg(urls: List[str], folder: Path, referer: str, max_images: Optional[int] = None) -> List[str]:
    if max_images is not None:
        urls = urls[:max_images]
    saved: List[str] = []
    folder.mkdir(parents=True, exist_ok=True)
    h = {
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Referer": referer,
    }
    for i, u in enumerate(urls, 1):
        try:
            with requests.get(u, headers=h, timeout=40) as r:
                ct = (r.headers.get("Content-Type") or "").lower()
                if r.status_code == 200 and (ct.startswith("image/") or r.content):
                    out = folder / f"{i:02d}.jpg"
                    try:
                        out.write_bytes(_img_to_jpg_bytes(r.content))
                        saved.append(str(out))
                    except Exception:
                        if ct.startswith(("image/jpeg", "image/jpg")):
                            out.write_bytes(r.content)
                            saved.append(str(out))
                        else:
                            print(f"  ! convert error: {u}")
                else:
                    print(f"  ! image HTTP {r.status_code} {u} {ct}")
        except Exception as e:
            print(f"  ! image error: {u} {e}")
    return saved


# ---------- orchestrator ----------
def scrape_boots_with_oxylabs(url: str,
                              download_images_flag: bool = True,
                              max_images: Optional[int] = None,
                              verbose: bool = False) -> Dict[str, Any]:
    html = oxy_fetch_html(url, geo=GEO)
    parsed = parse_boots(html, url, verbose=verbose)
    
    # If invalid link, return early without creating folder or downloading
    if parsed.get("is_invalid"):
        print(f"✗ Invalid link detected: {parsed.get('invalid_reason')}")
        return {
            "url": url,
            "pid": parsed["pid"],
            "name": parsed["name"],
            "price": parsed["price"],
            "price_source": parsed["price_source"],
            "in_stock": parsed["in_stock"],
            "availability_message": parsed["availability_message"],
            "description": parsed["description"],
            "image_count": 0,
            "image_urls": [],
            "images_downloaded": [],
            "folder": None,
            "mode": "oxylabs-universal",
            "is_invalid": True,
            "invalid_reason": parsed["invalid_reason"]
        }

    folder = DATA_DIR / f"{_retailer_slug(url)}_{_safe_name(parsed['name'])}_{_stable_id_from_url(url)}"
    folder.mkdir(parents=True, exist_ok=True)

    images_downloaded: List[str] = []
    if download_images_flag and parsed["image_urls"]:
        count = len(parsed['image_urls']) if not max_images else min(len(parsed['image_urls']), max_images)
        print(f"Downloading {count} images ...")
        images_downloaded = download_images_jpg(parsed["image_urls"], folder, referer=url, max_images=max_images)

    return {
        "url": url,
        "pid": parsed["pid"],
        "name": parsed["name"],
        "price": parsed["price"],
        "price_source": parsed["price_source"],
        "in_stock": parsed["in_stock"],
        "availability_message": parsed["availability_message"],
        "description": parsed["description"],
        "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
        "image_urls": parsed["image_urls"],
        "images_downloaded": images_downloaded,
        "folder": str(folder),
        "mode": "oxylabs-universal",
        "is_invalid": False,
        "invalid_reason": None
    }


# # ---------- CLI ----------
# if __name__ == "__main__":
#     import sys
    
#     # Test with both valid and invalid URLs
#     if len(sys.argv) > 1:
#         TEST_URL = sys.argv[1]
#     else:
#         # Default test: invalid link
#         TEST_URL = "https://www.boots.com/vq-halo-bluetooth-speaker-sapphire-noir-10346134"
    
#     print(f"\n{'='*60}")
#     print(f"Testing: {TEST_URL}")
#     print(f"{'='*60}\n")
    
#     data = scrape_boots_with_oxylabs(TEST_URL, download_images_flag=True, max_images=50, verbose=True)
#     print("\n" + json.dumps(data, indent=2, ensure_ascii=False))
    
#     # If running without args, also test a valid link
#     if len(sys.argv) == 1:
#         VALID_URL = "https://www.boots.com/vq-monty-dab-daband-digital-radio-and-bluetooth-speaker-laura-ashley-china-rose-10346137"
#         print(f"\n{'='*60}")
#         print(f"Testing VALID: {VALID_URL}")
#         print(f"{'='*60}\n")
        
#         data2 = scrape_boots_with_oxylabs(VALID_URL, download_images_flag=False, verbose=True)
#         print("\n" + json.dumps(data2, indent=2, ensure_ascii=False))