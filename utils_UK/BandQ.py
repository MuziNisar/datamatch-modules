
# =============================================================================
# VERSION 1 (backup) — original active code before stock detection fix
# =============================================================================

# # diy_oxylabs.py — Oxylabs universal + robust OOS detection (disabled CTA) + JPG-only images
# # Python 3.10+
# # pip install requests beautifulsoup4 lxml pillow pillow-avif-plugin

# from __future__ import annotations
# import re, json, html as htmllib, time, random, hashlib
# from pathlib import Path
# from typing import Optional, List, Dict
# from urllib.parse import urlsplit, urlunsplit, urldefrag
# from io import BytesIO
# from datetime import datetime, timezone

# import requests
# from requests.exceptions import RequestException
# from bs4 import BeautifulSoup
# from PIL import Image

# # Optional AVIF/HEIF support
# try:
#     import pillow_avif  # noqa: F401
# except Exception:
#     pass

# # -------- Oxylabs creds --------
# try:
#     from oxylabs_secrets import OXY_USER, OXY_PASS
# except Exception as e:
#     raise RuntimeError("Missing oxylabs_secrets.py with OXY_USER and OXY_PASS") from e
# if not (OXY_USER and OXY_PASS):
#     raise RuntimeError("OXY_USER/OXY_PASS in oxylabs_secrets.py must be non-empty.")

# # -------- Config --------
# UA_STR = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#     "AppleWebKit/537.36 (KHTML, like Gecko) "
#     "Chrome/128.0.0.0 Safari/537.36"
# )
# ACCEPT_LANG = "en-GB,en;q=0.9"
# OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"
# GEO = "United Kingdom"

# BASE_DIR = Path(__file__).resolve().parent
# SAVE_DIR = BASE_DIR / "data1"
# DEBUG_DIR = BASE_DIR / "debug"
# SAVE_DIR.mkdir(parents=True, exist_ok=True)
# DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# # -------- Helpers --------
# def _retailer_slug(u: str) -> str:
#     host = urlsplit(u).netloc.lower()
#     host = re.sub(r"^www\.", "", host)
#     return (host.split(".")[0] or "site")

# def _stable_id_from_url(u: str) -> str:
#     m = re.search(r"(\d{8,})", u)
#     return m.group(1) if m else hashlib.sha1(u.encode("utf-8")).hexdigest()[:8]

# def _clean_text(s: str) -> str:
#     s = htmllib.unescape(s or "")
#     s = s.replace("\r", "")
#     s = re.sub(r"[ \t]+", " ", s)
#     s = re.sub(r"\n{3,}", "\n\n", s)
#     return s.strip()

# def _html_to_text(desc_html: str) -> str:
#     if not desc_html:
#         return ""
#     s = desc_html
#     s = re.sub(r"(?i)<br\s*/?>", "\n", s)
#     s = re.sub(r"(?is)</p\s*>", "\n\n", s)
#     def _li_to_bullet(m):
#         inner = re.sub(r"<[^>]+>", " ", m.group(1))
#         inner = re.sub(r"\s+", " ", inner).strip()
#         return f"• {inner}\n"
#     s = re.sub(r"(?is)<li[^>]*>(.*?)</li>", _li_to_bullet, s)
#     s = re.sub(r"(?is)<[^>]+>", " ", s)
#     s = htmllib.unescape(s)
#     s = re.sub(r"[ \t]+\n", "\n", s)
#     s = re.sub(r"\n{3,}", "\n\n", s)
#     s = re.sub(r"[ \t]{2,}", " ", s).strip()
#     return s

# def _safe_name(name: str) -> str:
#     n = re.sub(r"[^\w\s-]", "", name or "").strip().replace(" ", "_")
#     return n or "NA"

# def _abs(url: str) -> str:
#     return "https:" + url if url.startswith("//") else url

# def _drop_query(u: str) -> str:
#     parts = list(urlsplit(u))
#     parts[3] = ""
#     parts[4] = ""
#     return urlunsplit(parts)

# def _pick_largest_from_srcset(srcset: str) -> str:
#     if not srcset:
#         return ""
#     items = [x.strip() for x in srcset.split(",") if x.strip()]
#     if not items:
#         return ""
#     last = items[-1]
#     return last.split()[0]

# def _parse_gbp_text(text: str) -> Optional[str]:
#     if not text:
#         return None
#     m = re.search(r"£\s*([\d,]+(?:\.\d{1,2})?)", text)
#     if not m:
#         m = re.search(r"\b([\d,]+(?:\.\d{1,2})?)\b", text)
#     if not m:
#         return None
#     val = m.group(1).replace(",", "")
#     if "." not in val:
#         val = f"{val}.00"
#     return f"{val} GBP"

# # -------- Oxylabs client --------
# def _build_context_array(session_id: Optional[str]) -> list[dict]:
#     ctx: list[dict] = []
#     if session_id:
#         ctx.append({"key": "session_id", "value": session_id})
#     ctx.append({
#         "key": "headers",
#         "value": {
#             "User-Agent": UA_STR,
#             "Accept-Language": ACCEPT_LANG
#         }
#     })
#     return ctx

# def _parse_retry_after(headers: Dict[str, str]) -> Optional[float]:
#     ra = headers.get("Retry-After")
#     if ra:
#         try:
#             return float(ra)
#         except ValueError:
#             try:
#                 dt = datetime.strptime(ra, "%a, %d %b %Y %H:%M:%S %Z")
#                 return max(0.0, (dt.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds())
#             except Exception:
#                 pass
#     xr = headers.get("X-RateLimit-Reset") or headers.get("X-Ratelimit-Reset")
#     if xr:
#         try:
#             return max(0.0, float(xr) - time.time())
#         except Exception:
#             pass
#     return None

# def oxy_post(payload: dict, retries: int = 6, base_sleep: float = 2.0) -> dict:
#     last_err = None
#     for attempt in range(retries + 1):
#         try:
#             r = requests.post(OXY_ENDPOINT, auth=(OXY_USER, OXY_PASS), json=payload, timeout=120)
#             if r.status_code == 200:
#                 data = r.json()
#                 results = data.get("results") or []
#                 if not results:
#                     raise RuntimeError("Oxylabs: empty results")
#                 content = results[0].get("content", "")
#                 if "<html" not in content.lower():
#                     raise RuntimeError("Oxylabs: non-HTML content")
#                 return data
#             if r.status_code in (429, 500, 502, 503, 504):
#                 wait = _parse_retry_after(r.headers)
#                 if wait is None:
#                     wait = (base_sleep * (2 ** attempt)) + random.uniform(0.25, 0.75)
#                 time.sleep(min(wait, 30.0))
#                 continue
#             try:
#                 err_json = r.json()
#                 raise RuntimeError(f"Oxylabs HTTP {r.status_code}: {err_json}")
#             except ValueError:
#                 raise RuntimeError(f"Oxylabs HTTP {r.status_code}: {r.text[:500]}")
#         except (RequestException, ValueError, RuntimeError) as e:
#             last_err = e
#             if attempt < retries:
#                 wait = (base_sleep * (2 ** attempt)) + random.uniform(0.25, 0.75)
#                 time.sleep(min(wait, 10.0))
#                 continue
#             raise RuntimeError(f"Oxylabs failed after {retries+1} attempts: {e}") from e
#     raise last_err or RuntimeError("Oxylabs unknown error")

# def oxy_fetch_html(url: str, geo: str = GEO) -> str:
#     url, _ = urldefrag(url)
#     session_id = f"diy-{int(time.time())}-{random.randint(1000,9999)}"
#     payload = {
#         "source": "universal",
#         "url": url,
#         "render": "html",
#         "geo_location": geo,
#         "user_agent_type": "desktop",
#         "context": _build_context_array(session_id),
#     }
#     data = oxy_post(payload)
#     return data["results"][0]["content"]

# # -------- Image download (ALWAYS .jpg) --------
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

# def download_images_jpg(urls: List[str], folder: Path, referer: str, max_images: Optional[int] = None) -> List[str]:
#     if max_images is not None:
#         urls = urls[:max_images]
#     saved = []
#     folder.mkdir(parents=True, exist_ok=True)
#     headers = {
#         "User-Agent": UA_STR,
#         "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
#         "Accept-Language": ACCEPT_LANG,
#         "Referer": referer,
#     }
#     for i, u in enumerate(urls, 1):
#         try:
#             u = _abs(u)
#             u = _drop_query(u)
#             with requests.get(u, headers=headers, timeout=40) as r:
#                 ct = (r.headers.get("Content-Type", "") or "").lower()
#                 if r.status_code == 200 and (ct.startswith("image/") or r.content):
#                     out = folder / f"{i:02d}.jpg"
#                     try:
#                         out.write_bytes(_img_to_jpg_bytes(r.content))
#                         saved.append(str(out))
#                     except Exception as pe:
#                         if ct.startswith(("image/jpeg", "image/jpg")):
#                             out.write_bytes(r.content)
#                             saved.append(str(out))
#                         else:
#                             print("  ! convert error:", u, pe)
#                 else:
#                     print("  ! image HTTP", r.status_code, u, ct)
#         except Exception as e:
#             print("  ! image error:", u, e)
#     return saved

# # -------- Parser (DIY/B&Q) --------
# def parse_diy(html: str, url: str) -> Dict:
#     soup = BeautifulSoup(html, "lxml")

#     # NAME
#     name = "N/A"
#     el = soup.select_one("[data-testid='product-name']")
#     if el:
#         name = _clean_text(el.get_text(" ", strip=True)) or "N/A"

#     # ======= STOCK =======
#     in_stock: Optional[bool] = None
#     page_txt = _clean_text(soup.get_text(" ", strip=True)).lower()
#     oos_phrases = [
#         "sorry, this product is currently out of stock",
#         "currently out of stock",
#         "out of stock",
#         "no longer available",
#         "discontinued",
#         "unavailable",       # TOO BROAD — matches "Home delivery unavailable" etc.
#     ]
#     if any(p in page_txt for p in oos_phrases):
#         in_stock = False
#     else:
#         cta = soup.select_one("[data-testid='product-cta-button']")
#         if cta:
#             cta_txt = _clean_text(cta.get_text(" ", strip=True)).lower()
#             is_disabled = (
#                 cta.has_attr("disabled")
#                 or str(cta.get("aria-disabled", "")).lower() == "true"
#                 or str(cta.get("aria-busy", "")).lower() == "true"
#             )
#             if is_disabled:
#                 in_stock = False
#             else:
#                 if re.search(r"\b(add to (basket|trolley)|buy now)\b", cta_txt):
#                     in_stock = True
#                 elif re.search(r"(out of stock|unavailable|notify me|pre-?order|coming soon)", cta_txt):
#                     in_stock = False

#     # PRICE
#     price = "N/A"
#     price_el = soup.select_one("[data-testid='product-price']")
#     if price_el:
#         ptxt = _clean_text(price_el.get_text(" ", strip=True))
#         gbp = _parse_gbp_text(ptxt)
#         if gbp:
#             price = gbp
#     if price == "N/A":
#         price_wrap = soup.find(lambda t: t and t.name in ("div", "section") and "price" in " ".join(t.get("class", [])).lower())
#         if price_wrap:
#             gbp = _parse_gbp_text(_clean_text(price_wrap.get_text(" ", strip=True)))
#             if gbp:
#                 price = gbp

#     # DESCRIPTION
#     description = "N/A"
#     d_el = soup.select_one("[data-testid='product-details-description']")
#     if d_el:
#         description = _html_to_text(str(d_el)) or "N/A"
#     if description == "N/A":
#         for tag in soup.find_all("script", type="application/ld+json"):
#             try:
#                 data = json.loads(tag.string or "")
#                 if isinstance(data, dict) and data.get("description"):
#                     description = _clean_text(data["description"])
#                     break
#             except Exception:
#                 continue

#     # IMAGES
#     img_urls: List[str] = []
#     for img in soup.select("[data-testid='product-gallery-thumbnail-list'] img"):
#         srcset = img.get("srcset") or ""
#         src = img.get("src") or ""
#         u = _pick_largest_from_srcset(srcset) or src
#         if u:
#             img_urls.append(_abs(u))
#     seen, ordered = set(), []
#     for u in img_urls:
#         b = _drop_query(u)
#         if b not in seen:
#             seen.add(b)
#             ordered.append(u)
#     img_urls = ordered

#     return {
#         "name": name,
#         "price": price,
#         "in_stock": in_stock,
#         "description": description,
#         "image_urls": img_urls
#     }

# # -------- Orchestrator --------
# def scrape_diy_product(url: str, save_dir: Path = SAVE_DIR,
#                        download_images_flag: bool = True,
#                        max_images: Optional[int] = None) -> Dict:
#     html = oxy_fetch_html(url, geo=GEO)
#     parsed = parse_diy(html, url)
#     folder = save_dir / f"{_retailer_slug(url)}_{_safe_name(parsed['name'])}_{_stable_id_from_url(url)}"
#     folder.mkdir(parents=True, exist_ok=True)
#     images_downloaded: List[str] = []
#     if download_images_flag and parsed["image_urls"]:
#         print(f"Downloading {len(parsed['image_urls']) if not max_images else min(len(parsed['image_urls']), max_images)} images …")
#         images_downloaded = download_images_jpg(parsed["image_urls"], folder, referer=url, max_images=max_images)
#     return {
#         "url": url,
#         "name": parsed["name"],
#         "price": parsed["price"],
#         "in_stock": parsed["in_stock"],
#         "description": parsed["description"],
#         "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
#         "image_urls": parsed["image_urls"],
#         "images_downloaded": images_downloaded,
#         "folder": str(folder),
#         "mode": "oxylabs-universal"
#     }

# # -------- CLI --------
# if __name__ == "__main__":
#     TEST_URL = "https://www.diy.com/departments/laura-ashley-elveden-navy-1-7-litre-stainless-steel-dome-kettle/5060706036906_BQ.prd"
#     data = scrape_diy_product(TEST_URL, save_dir=SAVE_DIR, download_images_flag=True, max_images=12)
#     print(json.dumps(data, indent=2, ensure_ascii=False))



























# =============================================================================
# VERSION 2 (ACTIVE) — stock detection fix applied
# FIXES:
#   - CTA button checked first (most reliable signal), text scan used only as fallback
#   - Removed bare "unavailable" and "discontinued" from OOS phrases (too generic on B&Q)
#   - Removed aria-busy from disabled check (aria-busy=true means loading, not disabled)
# =============================================================================

# diy_oxylabs.py — Oxylabs universal + robust OOS detection (disabled CTA) + JPG-only images
# Python 3.10+
# pip install requests beautifulsoup4 lxml pillow pillow-avif-plugin

from __future__ import annotations
import re, json, html as htmllib, time, random, hashlib
from pathlib import Path
from typing import Optional, List, Dict
from urllib.parse import urlsplit, urlunsplit, urldefrag
from io import BytesIO
from datetime import datetime, timezone

import requests
from requests.exceptions import RequestException
from bs4 import BeautifulSoup
from PIL import Image

# Optional AVIF/HEIF support
try:
    import pillow_avif  # noqa: F401
except Exception:
    pass

# -------- Oxylabs creds --------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception as e:
    raise RuntimeError("Missing oxylabs_secrets.py with OXY_USER and OXY_PASS") from e
if not (OXY_USER and OXY_PASS):
    raise RuntimeError("OXY_USER/OXY_PASS in oxylabs_secrets.py must be non-empty.")

# -------- Config --------
UA_STR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
ACCEPT_LANG = "en-GB,en;q=0.9"
OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"
GEO = "United Kingdom"

BASE_DIR = Path(__file__).resolve().parent
SAVE_DIR = BASE_DIR / "data1"
DEBUG_DIR = BASE_DIR / "debug"
SAVE_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# -------- Helpers --------
def _retailer_slug(u: str) -> str:
    host = urlsplit(u).netloc.lower()
    host = re.sub(r"^www\.", "", host)
    return (host.split(".")[0] or "site")

def _stable_id_from_url(u: str) -> str:
    m = re.search(r"(\d{8,})", u)
    return m.group(1) if m else hashlib.sha1(u.encode("utf-8")).hexdigest()[:8]

def _clean_text(s: str) -> str:
    s = htmllib.unescape(s or "")
    s = s.replace("\r", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _html_to_text(desc_html: str) -> str:
    if not desc_html:
        return ""
    s = desc_html
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</p\s*>", "\n\n", s)

    def _li_to_bullet(m):
        inner = re.sub(r"<[^>]+>", " ", m.group(1))
        inner = re.sub(r"\s+", " ", inner).strip()
        return f"• {inner}\n"
    s = re.sub(r"(?is)<li[^>]*>(.*?)</li>", _li_to_bullet, s)

    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = htmllib.unescape(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s).strip()
    return s

def _safe_name(name: str) -> str:
    n = re.sub(r"[^\w\s-]", "", name or "").strip().replace(" ", "_")
    return n or "NA"

def _abs(url: str) -> str:
    return "https:" + url if url.startswith("//") else url

def _drop_query(u: str) -> str:
    parts = list(urlsplit(u))
    parts[3] = ""  # query
    parts[4] = ""  # fragment
    return urlunsplit(parts)

def _pick_largest_from_srcset(srcset: str) -> str:
    if not srcset:
        return ""
    items = [x.strip() for x in srcset.split(",") if x.strip()]
    if not items:
        return ""
    last = items[-1]
    return last.split()[0]

def _parse_gbp_text(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"£\s*([\d,]+(?:\.\d{1,2})?)", text)
    if not m:
        m = re.search(r"\b([\d,]+(?:\.\d{1,2})?)\b", text)
    if not m:
        return None
    val = m.group(1).replace(",", "")
    if "." not in val:
        val = f"{val}.00"
    return f"{val} GBP"

# -------- Oxylabs client --------
def _build_context_array(session_id: Optional[str]) -> list[dict]:
    ctx: list[dict] = []
    if session_id:
        ctx.append({"key": "session_id", "value": session_id})
    ctx.append({
        "key": "headers",
        "value": {
            "User-Agent": UA_STR,
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

def oxy_fetch_html(url: str, geo: str = GEO) -> str:
    url, _ = urldefrag(url)
    session_id = f"diy-{int(time.time())}-{random.randint(1000,9999)}"
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

# -------- Image download (ALWAYS .jpg) --------
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

def download_images_jpg(urls: List[str], folder: Path, referer: str, max_images: Optional[int] = None) -> List[str]:
    if max_images is not None:
        urls = urls[:max_images]
    saved = []
    folder.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": UA_STR,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": ACCEPT_LANG,
        "Referer": referer,
    }
    for i, u in enumerate(urls, 1):
        try:
            u = _abs(u)
            u = _drop_query(u)
            with requests.get(u, headers=headers, timeout=40) as r:
                ct = (r.headers.get("Content-Type", "") or "").lower()
                if r.status_code == 200 and (ct.startswith("image/") or r.content):
                    out = folder / f"{i:02d}.jpg"
                    try:
                        out.write_bytes(_img_to_jpg_bytes(r.content))
                        saved.append(str(out))
                    except Exception as pe:
                        if ct.startswith(("image/jpeg", "image/jpg")):
                            out.write_bytes(r.content)
                            saved.append(str(out))
                        else:
                            print("  ! convert error:", u, pe)
                else:
                    print("  ! image HTTP", r.status_code, u, ct)
        except Exception as e:
            print("  ! image error:", u, e)
    return saved

# -------- Parser (DIY/B&Q) --------
def parse_diy(html: str, url: str) -> Dict:
    soup = BeautifulSoup(html, "lxml")

    # NAME
    name = "N/A"
    el = soup.select_one("[data-testid='product-name']")
    if el:
        name = _clean_text(el.get_text(" ", strip=True)) or "N/A"

    # ======= STOCK =======
    # OLD VERSION 2 — data-testid selector may not be found in Oxylabs HTML;
    # if cta is None → falls to text scan → "out of stock" matches related products on page
    # in_stock: Optional[bool] = None
    # cta = soup.select_one("[data-testid='product-cta-button']")
    # if cta:
    #     cta_txt = _clean_text(cta.get_text(" ", strip=True)).lower()
    #     is_disabled = (
    #         cta.has_attr("disabled")
    #         or str(cta.get("aria-disabled", "")).lower() == "true"
    #     )
    #     if is_disabled:
    #         in_stock = False
    #     elif re.search(r"\b(add to (basket|trolley)|buy now)\b", cta_txt):
    #         in_stock = True
    #     elif re.search(r"(out of stock|unavailable|notify me|pre-?order|coming soon)", cta_txt):
    #         in_stock = False
    # if in_stock is None:
    #     page_txt = _clean_text(soup.get_text(" ", strip=True)).lower()
    #     oos_phrases = [
    #         "sorry, this product is currently out of stock",
    #         "currently out of stock",
    #         "out of stock",      # TOO BROAD — matches OOS related products on the same page
    #         "no longer available",
    #     ]
    #     if any(p in page_txt for p in oos_phrases):
    #         in_stock = False

    # FIXED: multiple CTA selectors so we don't miss the button if data-testid is absent
    # FIXED: also match on aria-label ("Add 1 item to basket") in case get_text() is empty
    # FIXED: removed "out of stock" from text fallback — too broad (matches related products)
    in_stock: Optional[bool] = None

    cta = (
        soup.select_one("[data-testid='product-cta-button']") or
        soup.select_one("form[data-testid='product-cta-form'] button[type='submit']") or
        soup.select_one("button[aria-label*='basket' i]") or
        soup.select_one("button[aria-label*='trolley' i]")
    )
    if cta:
        cta_txt = _clean_text(cta.get_text(" ", strip=True)).lower()
        cta_label = (cta.get("aria-label") or "").lower()
        combined = cta_txt + " " + cta_label
        is_disabled = (
            cta.has_attr("disabled")
            or str(cta.get("aria-disabled", "")).lower() == "true"
        )
        if is_disabled:
            in_stock = False
        elif re.search(r"add.{0,5}(basket|trolley|cart)|buy now", combined):
            in_stock = True
        elif re.search(r"out of stock|notify me|pre-?order|coming soon", combined):
            in_stock = False

    if in_stock is None:
        page_txt = _clean_text(soup.get_text(" ", strip=True)).lower()
        oos_phrases = [
            "sorry, this product is currently out of stock",
            "currently out of stock",
            "this item is out of stock",
            "no longer available",
        ]
        if any(p in page_txt for p in oos_phrases):
            in_stock = False

    # PRICE
    price = "N/A"
    price_el = soup.select_one("[data-testid='product-price']")
    if price_el:
        ptxt = _clean_text(price_el.get_text(" ", strip=True))
        gbp = _parse_gbp_text(ptxt)
        if gbp:
            price = gbp
    if price == "N/A":
        price_wrap = soup.find(lambda t: t and t.name in ("div", "section") and "price" in " ".join(t.get("class", [])).lower())
        if price_wrap:
            gbp = _parse_gbp_text(_clean_text(price_wrap.get_text(" ", strip=True)))
            if gbp:
                price = gbp

    # DESCRIPTION
    description = "N/A"
    d_el = soup.select_one("[data-testid='product-details-description']")
    if d_el:
        description = _html_to_text(str(d_el)) or "N/A"
    if description == "N/A":
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
                if isinstance(data, dict) and data.get("description"):
                    description = _clean_text(data["description"])
                    break
            except Exception:
                continue

    # IMAGES (thumb srcset largest; dedupe by base)
    img_urls: List[str] = []
    for img in soup.select("[data-testid='product-gallery-thumbnail-list'] img"):
        srcset = img.get("srcset") or ""
        src = img.get("src") or ""
        u = _pick_largest_from_srcset(srcset) or src
        if u:
            img_urls.append(_abs(u))

    seen, ordered = set(), []
    for u in img_urls:
        b = _drop_query(u)
        if b not in seen:
            seen.add(b)
            ordered.append(u)
    img_urls = ordered

    return {
        "name": name,
        "price": price,
        "in_stock": in_stock,
        "description": description,
        "image_urls": img_urls
    }

# -------- Orchestrator --------
def scrape_diy_product(url: str, save_dir: Path = SAVE_DIR,
                       download_images_flag: bool = True,
                       max_images: Optional[int] = None) -> Dict:
    html = oxy_fetch_html(url, geo=GEO)
    parsed = parse_diy(html, url)

    folder = save_dir / f"{_retailer_slug(url)}_{_safe_name(parsed['name'])}_{_stable_id_from_url(url)}"
    folder.mkdir(parents=True, exist_ok=True)

    images_downloaded: List[str] = []
    if download_images_flag and parsed["image_urls"]:
        print(f"Downloading {len(parsed['image_urls']) if not max_images else min(len(parsed['image_urls']), max_images)} images …")
        images_downloaded = download_images_jpg(parsed["image_urls"], folder, referer=url, max_images=max_images)

    return {
        "url": url,
        "name": parsed["name"],
        "price": parsed["price"],
        "in_stock": parsed["in_stock"],
        "description": parsed["description"],
        "image_count": len(images_downloaded) if images_downloaded else len(parsed["image_urls"]),
        "image_urls": parsed["image_urls"],
        "images_downloaded": images_downloaded,
        "folder": str(folder),
        "mode": "oxylabs-universal"
    }

# # -------- CLI --------
# if __name__ == "__main__":
#     TEST_URL = "https://www.diy.com/departments/laura-ashley-elveden-navy-1-7-litre-stainless-steel-dome-kettle/5060706036906_BQ.prd"
#     data = scrape_diy_product(TEST_URL, save_dir=SAVE_DIR, download_images_flag=True, max_images=12)
#     print(json.dumps(data, indent=2, ensure_ascii=False))
