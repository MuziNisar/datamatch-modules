



# allegro_oxylabs.py — Single-URL Allegro scraper via Oxylabs Web Scraper API
# Python 3.10+
# pip install requests beautifulsoup4 lxml
#
# USES: Oxylabs dedicated Allegro scraper (source: "allegro")
# Docs: https://developers.oxylabs.io/scraping-solutions/web-scraper-api/targets/european-e-commerce/allegro
#
# UPDATED: Added Job ID capture for Oxylabs support troubleshooting

from __future__ import annotations
import os, re, json, html, hashlib, time, concurrent.futures as cf
from pathlib import Path
from typing import List, Optional, Dict
from urllib.parse import urlsplit, urlunsplit
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# ---------- Config ----------
WANT_IMAGES = 99          # take up to this many images if available
DOWNLOAD_IMAGES = True    # save images to disk

# ---------- Oxylabs creds ----------
try:
    from oxylabs_secrets import OXY_USER, OXY_PASS
except Exception:
    OXY_USER = os.getenv("OXYLABS_USERNAME", "")
    OXY_PASS = os.getenv("OXYLABS_PASSWORD", "")
if not OXY_USER or not OXY_PASS:
    raise RuntimeError("Set Oxylabs creds via oxylabs_secrets.py or env vars.")

OXY_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
ACCEPT_LANG = "pl-PL,pl;q=0.9,en;q=0.8"

BASE_DIR = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
DATA_DIR = BASE_DIR / os.getenv("DATA_DIR", "data_pl")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------- Job ID Logging ----------
JOB_ID_LOG_FILE = BASE_DIR / "oxylabs_job_ids.log"

def _log_job_id(job_id: str, url: str, status: str, strategy: str, http_code: int = 0, result_code: int = 0):
    """Log Job ID with context for troubleshooting with Oxylabs support."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = (
        f"[{timestamp}] "
        f"Job ID: {job_id} | "
        f"Status: {status} | "
        f"HTTP: {http_code} | "
        f"Result: {result_code} | "
        f"Strategy: {strategy} | "
        f"URL: {url}\n"
    )
    
    # Print to console
    print(f"  📋 {log_entry.strip()}")
    
    # Append to log file
    try:
        with open(JOB_ID_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"  ⚠️ Could not write to log file: {e}")

def get_recent_job_ids(n: int = 10) -> List[str]:
    """Get the most recent N job IDs from the log file."""
    if not JOB_ID_LOG_FILE.exists():
        return []
    
    try:
        with open(JOB_ID_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        job_ids = []
        for line in reversed(lines[-n*2:]):  # Read extra in case of duplicates
            match = re.search(r"Job ID: ([a-f0-9-]+)", line)
            if match and match.group(1) not in job_ids:
                job_ids.append(match.group(1))
            if len(job_ids) >= n:
                break
        
        return job_ids
    except Exception:
        return []

def print_failed_job_ids():
    """Print all failed job IDs for easy copy-paste to Oxylabs support."""
    if not JOB_ID_LOG_FILE.exists():
        print("No job ID log file found.")
        return
    
    try:
        with open(JOB_ID_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        print("\n" + "="*60)
        print("FAILED JOB IDs FOR OXYLABS SUPPORT")
        print("="*60)
        
        failed_jobs = []
        for line in lines:
            if "FAILED" in line or "BLOCKED" in line or "ERROR" in line:
                match = re.search(r"Job ID: ([a-f0-9-]+)", line)
                if match:
                    failed_jobs.append(line.strip())
        
        if failed_jobs:
            for job in failed_jobs[-20:]:  # Last 20 failures
                print(job)
            print("\nJob IDs only (copy-paste ready):")
            job_ids = [re.search(r"Job ID: ([a-f0-9-]+)", j).group(1) for j in failed_jobs[-20:]]
            print(", ".join(job_ids))
        else:
            print("No failed jobs found in log.")
        
        print("="*60 + "\n")
    except Exception as e:
        print(f"Error reading log: {e}")


ALLEGRO_IMG_HOST = "allegroimg.com"
BAD_PATH_TOKENS = (
    "action-common-", "illustration", "sprite", "icon", "logo",
    "thank-you-page", "benefits-badge", "information-common", "information-benefits"
)

# ---------- helpers ----------
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _clean_multiline(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _safe_name(s: str, max_len: int = 50) -> str:
    """
    Create a safe filename by transliterating Unicode to ASCII and removing special chars.
    
    Args:
        s: Input string (product name)
        max_len: Maximum length of output (default 50 to prevent Windows path too long errors)
    """
    s = _clean(s)
    
    # Transliterate common Unicode characters to ASCII equivalents
    transliterations = {
        'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
        'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
        'à': 'a', 'á': 'a', 'â': 'a', 'ã': 'a', 'å': 'a',
        'è': 'e', 'é': 'e', 'ê': 'e', 'ë': 'e',
        'ì': 'i', 'í': 'i', 'î': 'i', 'ï': 'i',
        'ò': 'o', 'ó': 'o', 'ô': 'o', 'õ': 'o',
        'ù': 'u', 'ú': 'u', 'û': 'u',
        'ç': 'c', 'ñ': 'n',
        'æ': 'ae', 'œ': 'oe',
        # Polish characters
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
        'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        'Ą': 'A', 'Ć': 'C', 'Ę': 'E', 'Ł': 'L', 'Ń': 'N',
        'Ó': 'O', 'Ś': 'S', 'Ź': 'Z', 'Ż': 'Z',
    }
    
    for unicode_char, ascii_equiv in transliterations.items():
        s = s.replace(unicode_char, ascii_equiv)
    
    s = s.encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r"[^\w.\-]+", "_", s)
    
    # Truncate to max_len, but try to break at underscore
    if len(s) > max_len:
        s = s[:max_len]
        # Try to break at last underscore to avoid cutting words
        last_underscore = s.rfind('_')
        if last_underscore > max_len // 2:
            s = s[:last_underscore]
    
    return s.rstrip('_') or "product"

def _strip_query(u: str) -> str:
    sp = urlsplit(u)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

def _stable_id_from_url(url: str) -> str:
    """
    Extract a short stable ID from the URL.
    For Allegro, this is the numeric product ID at the end.
    """
    try:
        path = urlsplit(url).path
        # Extract numeric product ID (e.g., 17532527096)
        m = re.search(r'(\d{10,12})$', path)
        if m:
            return m.group(1)
        # Fallback: last path segment, but shortened
        parts = [p for p in path.split("/") if p]
        token = parts[-1] if parts else ""
        if token:
            # Just take the last 20 chars to keep it short
            clean = re.sub(r"[^\w\-]+", "", token)
            return clean[-20:] if len(clean) > 20 else clean
    except Exception:
        pass
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

def _extract_product_id(url: str) -> Optional[str]:
    """
    Extract the product ID from an Allegro.pl URL.
    
    Allegro URLs have format:
    https://allegro.pl/oferta/[product-name-slug]-[PRODUCT_ID]
    
    Example:
    https://allegro.pl/oferta/laura-ashley-elveden-17532527096
    Product ID: 17532527096
    """
    # Extract from path
    path = urlsplit(url).path
    # Match the numeric ID at the end (typically 11 digits)
    m = re.search(r'-(\d{10,12})$', path)
    if m:
        return m.group(1)
    
    # Fallback: try to find any long numeric sequence at the end
    m = re.search(r'(\d{10,12})$', path)
    if m:
        return m.group(1)
    
    return None

def _unique_path(base: Path) -> Path:
    if not base.exists():
        return base
    i = 1
    while True:
        cand = base.parent / f"{base.name}_{i:02d}"
        if not cand.exists():
            return cand
        i += 1



def _check_listing_invalid(soup: BeautifulSoup) -> tuple[bool, str]:
    """
    Check if the listing is invalid (ended, 404, or unavailable).
    
    Returns:
        (is_invalid: bool, reason: str)
        
    Detects:
        1. Listing Ended - "Sale completed" / "Sprzedaż zakończona"
        2. 404 Page - "Oops, there's nothing here" / "This page does not exist"
        3. Other unavailable states
    """
    page_text = soup.get_text(" ", strip=True).lower()
    
    # ========== 404 PAGE DETECTION ==========
    not_found_indicators = [
        # English
        "oops, there's nothing here",
        "this page does not exist",
        "page not found",
        "404 not found",
        "we may have deleted or moved it",
        # Polish
        "ups, nic tu nie ma",
        "ta strona nie istnieje",
        "strona nie została znaleziona",
        "nie znaleziono strony",
        "mogliśmy ją usunąć lub przenieść",
    ]
    
    for indicator in not_found_indicators:
        if indicator in page_text:
            return True, "404 - Page not found"
    
    # Check for 404 illustration image
    img_404 = soup.select_one('img[alt*="404"], img[alt*="illustration 404"], img[alt*="ilustracja 404"]')
    if img_404:
        return True, "404 - Page not found (illustration detected)"
    
    # Check for "Return to home page" + "get help" combo (404 page pattern)
    return_home = soup.find('a', href='/')
    help_link = soup.find('a', href='/pomoc')
    if return_home and help_link:
        # Additional check - if there's no product content
        h1 = soup.select_one('h1')
        if not h1 or 'nothing here' in (h1.get_text() or '').lower():
            return True, "404 - Page not found (navigation pattern)"
    
    # ========== LISTING ENDED DETECTION ==========
    ended_indicators = [
        # English
        "sale completed",
        "listing ended",
        "this listing has ended",
        "offer has ended",
        "this offer has ended",
        # Polish
        "sprzedaż zakończona",
        "oferta zakończona",
        "ta oferta skończyła się",
        "ta oferta się zakończyła",
        "aukcja zakończona",
    ]
    
    for indicator in ended_indicators:
        if indicator in page_text:
            return True, "Listing ended (Sprzedaż zakończona)"
    
    # Check for the specific container with ended listing
    ended_container = soup.select_one('[data-analytics-view-label="Ended"]')
    if ended_container:
        return True, "Listing ended (data-analytics-view-label)"
    
    # Check for data-testid="container" with "Ended" label
    ended_testid = soup.select_one('[data-testid="container"][data-analytics-view-label="Ended"]')
    if ended_testid:
        return True, "Listing ended (testid container)"
    
    # Check for the stop sign icon (used for ended listings)
    stop_sign = soup.select_one('img[src*="information-common-stop-sign"]')
    if stop_sign:
        return True, "Listing ended (stop sign icon)"
    
    # Check for h6 with ended text
    for h6 in soup.find_all('h6'):
        h6_text = (h6.get_text() or '').lower()
        if any(ind in h6_text for ind in ['zakończona', 'completed', 'ended']):
            return True, "Listing ended (h6 header)"
    
    # ========== OTHER UNAVAILABLE STATES ==========
    unavailable_indicators = [
        # English
        "product unavailable",
        "item no longer available",
        "offer is no longer available",
        # Polish
        "produkt niedostępny",
        "przedmiot niedostępny",
        "oferta jest już niedostępna",
    ]
    
    for indicator in unavailable_indicators:
        if indicator in page_text:
            return True, "Product unavailable"
    
    return False, ""


def _check_listing_ended(soup: BeautifulSoup) -> bool:
    """
    Legacy wrapper for backward compatibility.
    Returns True if the listing is invalid/ended/404.
    """
    is_invalid, _ = _check_listing_invalid(soup)
    return is_invalid


# ---------- Global rate limiting ----------
_LAST_REQUEST_TIME = 0
_MIN_REQUEST_DELAY = 3.0  # Minimum 3 seconds between requests

def _rate_limit_delay():
    """Enforce minimum delay between requests to prevent rate limiting."""
    global _LAST_REQUEST_TIME
    elapsed = time.time() - _LAST_REQUEST_TIME
    if elapsed < _MIN_REQUEST_DELAY:
        sleep_time = _MIN_REQUEST_DELAY - elapsed
        print(f"  [Rate Limit] Waiting {sleep_time:.1f}s before next request...")
        time.sleep(sleep_time)
    _LAST_REQUEST_TIME = time.time()

# ---------- Oxylabs fetch (WITH JOB ID CAPTURE) ----------
def _fetch_html(url: str) -> str:
    """
    Fetch HTML via Oxylabs using strategies that actually work.
    
    NOW CAPTURES JOB ID for Oxylabs support troubleshooting!
    
    Based on testing:
    - 'allegro_product' with product_id: Often blocked (613)
    - 'universal' with Poland geo: Often blocked (613)  
    - 'universal' with Germany geo: WORKS! ✅
    
    Includes exponential backoff for 429 rate limiting.
    """
    
    # Enforce rate limiting BEFORE making any requests
    _rate_limit_delay()
    
    print(f"\n[Allegro] Fetching: {url[:80]}...")
    
    strategies = [
        # Strategy 1: Universal with POLAND geo (native country for Allegro)
        {
            "name": "universal (Poland)",
            "payload": {
                "source": "universal",
                "url": url,
                "render": "html",
                "geo_location": "Poland",
                "user_agent_type": "desktop",
            }
        },
        # Strategy 2: Universal with GERMANY geo (nearby, often works)
        {
            "name": "universal (Germany)",
            "payload": {
                "source": "universal",
                "url": url,
                "render": "html",
                "geo_location": "Germany",
                "user_agent_type": "desktop",
            }
        },
        # Strategy 3: Universal with France geo (backup)
        {
            "name": "universal (France)",
            "payload": {
                "source": "universal",
                "url": url,
                "render": "html",
                "geo_location": "France",
                "user_agent_type": "desktop",
            }
        },
        # Strategy 4: Universal with UK geo (last resort)
        {
            "name": "universal (UK)",
            "payload": {
                "source": "universal",
                "url": url,
                "render": "html",
                "geo_location": "United Kingdom",
                "user_agent_type": "desktop",
            }
        },
    ]
    
    last_err = None
    last_job_id = None  # Track last job ID for error reporting
    rate_limit_delay = 10  # Start with 10 seconds for rate limiting
    
    for strategy in strategies:
        strategy_name = strategy["name"]
        payload = strategy["payload"]
        
        print(f"\n[Allegro] Trying: {strategy_name}")
        
        for attempt in range(3):  # 3 attempts per strategy
            try:
                timeout = 150 + (attempt * 30)
                print(f"  Attempt {attempt + 1}/3 (timeout: {timeout}s)...")
                
                r = requests.post(
                    OXY_ENDPOINT,
                    json=payload,
                    auth=(OXY_USER, OXY_PASS),
                    timeout=timeout
                )
                
                # ========== CAPTURE JOB ID ==========
                job_id = r.headers.get('x-oxylabs-job-id', 'NOT_FOUND')
                last_job_id = job_id
                print(f"  🔑 Job ID: {job_id}")
                # =====================================
                
                # ========== RATE LIMIT HANDLING (429) ==========
                if r.status_code == 429:
                    _log_job_id(job_id, url, "RATE_LIMITED", strategy_name, http_code=429)
                    delay = rate_limit_delay * (2 ** attempt)  # 10, 20, 40 seconds
                    print(f"  ⚠️ Rate limited (429). Waiting {delay}s before retry...")
                    time.sleep(delay)
                    continue
                # ===============================================
                
                if r.status_code == 401:
                    _log_job_id(job_id, url, "UNAUTHORIZED", strategy_name, http_code=401)
                    raise RuntimeError(f"Oxylabs Unauthorized (401). Job ID: {job_id}. Check credentials.")
                
                if not r.ok:
                    _log_job_id(job_id, url, "HTTP_ERROR", strategy_name, http_code=r.status_code)
                    print(f"  ⚠ HTTP {r.status_code}: {r.text[:200]}")
                    last_err = RuntimeError(f"HTTP {r.status_code} (Job ID: {job_id})")
                    continue
                
                data = r.json()
                
                if isinstance(data, dict):
                    results = data.get("results")
                    if results and isinstance(results, list) and len(results) > 0:
                        result = results[0]
                        content = result.get("content")
                        status_code = result.get("status_code")
                        
                        print(f"  Result status: {status_code}, content: {len(content) if content else 0} bytes")
                        
                        # HTTP 613 = blocked by website, try next strategy
                        if status_code == 613:
                            _log_job_id(job_id, url, "BLOCKED_613", strategy_name, result_code=613)
                            print(f"  ⚠ Blocked (613) - Job ID: {job_id} - trying next strategy...")
                            last_err = RuntimeError(f"Blocked with {strategy_name} (Job ID: {job_id})")
                            break  # Exit retry loop, try next strategy
                        
                        # HTTP 429 inside result = rate limited
                        if status_code == 429:
                            _log_job_id(job_id, url, "RATE_LIMITED", strategy_name, result_code=429)
                            delay = rate_limit_delay * (2 ** attempt)
                            print(f"  ⚠️ Rate limited (result 429). Job ID: {job_id}. Waiting {delay}s...")
                            time.sleep(delay)
                            continue
                        
                        # HTTP 404 = Page not found - BUT we still want the HTML content!
                        # The _check_listing_invalid function will detect this and mark as invalid
                        if status_code == 404:
                            if content and isinstance(content, str) and len(content) > 1000:
                                _log_job_id(job_id, url, "PAGE_NOT_FOUND_404", strategy_name, result_code=404)
                                print(f"  ℹ️ Got 404 page ({len(content):,} bytes) - will be marked as invalid link")
                                return content  # Return the 404 page HTML for detection
                        
                        # Other 4xx/5xx errors (but not 404 which we handle above)
                        if status_code and status_code >= 400:
                            _log_job_id(job_id, url, f"ERROR_{status_code}", strategy_name, result_code=status_code)
                            print(f"  ⚠ Error status {status_code} - Job ID: {job_id}")
                            last_err = RuntimeError(f"HTTP {status_code} (Job ID: {job_id})")
                            continue
                        
                        # Validate content
                        if content and isinstance(content, str) and len(content) > 1000:
                            if "<html" in content.lower() or "<body" in content.lower():
                                _log_job_id(job_id, url, "SUCCESS", strategy_name, result_code=status_code or 200)
                                print(f"  ✓ Success! Got {len(content):,} bytes of HTML (Job ID: {job_id})")
                                return content
                        
                        _log_job_id(job_id, url, "INVALID_CONTENT", strategy_name, result_code=status_code or 0)
                        print(f"  ⚠ Invalid/empty content - Job ID: {job_id}")
                        last_err = RuntimeError(f"Invalid content (Job ID: {job_id})")
                
            except requests.exceptions.Timeout:
                _log_job_id(last_job_id or "TIMEOUT", url, "TIMEOUT", strategy_name)
                print(f"  ⚠ Timeout after {timeout}s")
                last_err = RuntimeError(f"Timeout ({timeout}s)")
            except requests.exceptions.RequestException as e:
                error_str = str(e)
                # Check for rate limiting in exception message
                if "429" in error_str or "Too Many Requests" in error_str:
                    _log_job_id(last_job_id or "RATE_LIMIT", url, "RATE_LIMITED", strategy_name)
                    delay = rate_limit_delay * (2 ** attempt)
                    print(f"  ⚠️ Rate limited (exception). Waiting {delay}s...")
                    time.sleep(delay)
                    continue
                _log_job_id(last_job_id or "NETWORK_ERROR", url, "NETWORK_ERROR", strategy_name)
                print(f"  ⚠ Network error: {e}")
                last_err = e
            except Exception as e:
                _log_job_id(last_job_id or "UNKNOWN_ERROR", url, "ERROR", strategy_name)
                print(f"  ⚠ Error: {e}")
                last_err = e
            
            # Brief delay before retry
            if attempt < 2:
                print(f"  Retrying in 5s...")
                time.sleep(5)
        
        # Delay before trying next strategy
        time.sleep(3)
    
    # All strategies failed - print helpful message with job IDs
    print("\n" + "="*60)
    print("❌ ALL STRATEGIES FAILED - SHARE THESE JOB IDs WITH OXYLABS:")
    print("="*60)
    print_failed_job_ids()
    
    raise RuntimeError(
        f"All Oxylabs strategies failed for Allegro.pl\n"
        f"URL: {url}\n"
        f"Last Job ID: {last_job_id}\n"
        f"Last error: {last_err}\n\n"
        f"📋 Check {JOB_ID_LOG_FILE} for all Job IDs\n"
        f"   Or call: print_failed_job_ids()\n\n"
        f"Troubleshooting:\n"
        f"  1. All geo locations (Germany, France, UK) are being blocked\n"
        f"  2. Wait 15-30 minutes and try again (temporary IP block)\n"
        f"  3. Share the Job IDs above with Oxylabs support\n"
        f"  4. Check Oxylabs dashboard for account issues"
    )


# ---------- price (FIXED) ----------
PLN_WORDS = {"pln", "zł", "zloty", "zlotych"}

def _extract_price_from_dom(soup: BeautifulSoup) -> Optional[float]:
    """
    Extract price directly from DOM structure.
    
    Allegro uses structure like:
    <div class="_7030e_...">
        <span>cena</span>
        <span>349,</span>
        <span class="...">99</span>
        <span class="...">zł</span>
    </div>
    
    The price is split across multiple spans: "349," + "99" + "zł"
    """
    
    # Strategy 1: Target the specific price container class pattern
    # The _7030e_ class is Allegro's price container
    price_containers = soup.select('[class*="_7030e_"]')
    
    for container in price_containers:
        # Get all text, removing "cena" label and currency
        text = container.get_text(" ", strip=True)
        
        # Skip if this looks like a payment/installment section
        if any(skip in text.lower() for skip in ['zapłać później', 'raty', 'allegropay', 'w styczniu', 'w lutym', 'w marcu']):
            continue
        
        # Clean the text
        text = text.replace("cena", "").replace("PLN", "").replace("zł", "").replace("\xa0", " ").strip()
        
        # Pattern: "349, 99" or "349,99" (with possible space between)
        m = re.search(r'(\d{1,6})\s*[.,]\s*(\d{2})\b', text)
        if m:
            try:
                price = float(f"{m.group(1)}.{m.group(2)}")
                if 0.50 < price < 100000:  # Reasonable price range
                    return price
            except ValueError:
                continue
    
    # Strategy 2: Look for price with "cena" label nearby
    cena_spans = soup.find_all('span', string=re.compile(r'cena', re.I))
    for cena_span in cena_spans:
        parent = cena_span.find_parent(['div', 'section'])
        if parent:
            text = parent.get_text(" ", strip=True)
            
            # Skip payment sections
            if any(skip in text.lower() for skip in ['zapłać później', 'raty', 'allegropay']):
                continue
            
            text = text.replace("cena", "").replace("PLN", "").replace("zł", "").replace("\xa0", " ").strip()
            
            m = re.search(r'(\d{1,6})\s*[.,]\s*(\d{2})\b', text)
            if m:
                try:
                    price = float(f"{m.group(1)}.{m.group(2)}")
                    if 0.50 < price < 100000:
                        return price
                except ValueError:
                    continue
    
    # Strategy 3: Generic selectors (fallback)
    price_selectors = [
        '[data-box-name="price"]',
        '[aria-label*="cena"]',
        '[aria-label*="price"]',
    ]
    
    for sel in price_selectors:
        for el in soup.select(sel):
            text = el.get_text(" ", strip=True)
            
            # Skip payment sections
            if any(skip in text.lower() for skip in ['zapłać później', 'raty', 'allegropay']):
                continue
            
            text = text.replace("cena", "").replace("PLN", "").replace("zł", "").replace("\xa0", " ").strip()
            
            m = re.search(r'(\d{1,6})\s*[.,]\s*(\d{2})\b', text)
            if m:
                try:
                    price = float(f"{m.group(1)}.{m.group(2)}")
                    if 0.50 < price < 100000:
                        return price
                except ValueError:
                    continue
            
            # Whole number price (no decimals)
            m = re.search(r'\b(\d{1,6})\b', text)
            if m and not re.search(r'\d{1,6}\s*[.,]\s*\d{2}', text):
                try:
                    price = float(m.group(1))
                    if 1 < price < 100000:
                        return price
                except ValueError:
                    continue
    
    return None

def _extract_price_from_jsonld(soup: BeautifulSoup) -> Optional[float]:
    """Extract price from JSON-LD structured data."""
    for sc in soup.select("script[type='application/ld+json']"):
        raw = sc.string or sc.get_text() or ""
        for cand in (raw, raw.strip().rstrip(",")):
            try:
                data = json.loads(cand)
            except Exception:
                continue
            objs = data if isinstance(data, list) else [data]
            for o in objs:
                if not isinstance(o, dict) or o.get("@type") != "Product":
                    continue
                offers = o.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                if isinstance(offers, dict):
                    p = offers.get("price")
                    cur = (offers.get("priceCurrency") or "PLN").lower()
                    if p is not None and cur in PLN_WORDS:
                        try:
                            price = float(str(p).replace(",", ".").replace(" ", ""))
                            if 0.01 < price < 100000:
                                return price
                        except ValueError:
                            continue
    return None

def _extract_price_from_scripts(soup: BeautifulSoup) -> Optional[float]:
    """Extract price from inline JavaScript data."""
    patterns = [
        re.compile(r'"presentableValue"\s*:\s*"(\d{1,6}[.,]\d{2})"'),
        re.compile(r'"priceAmount"\s*:\s*"(\d{1,6}[.,]\d{2})"'),
        re.compile(r'"amount"\s*:\s*"(\d{1,6}[.,]\d{2})"'),
        re.compile(r'"minorUnits"\s*:\s*(\d{3,8})'),
    ]
    
    for sc in soup.find_all("script"):
        raw = sc.string or sc.get_text() or ""
        if not raw or len(raw) < 50:
            continue
        
        for i, rx in enumerate(patterns):
            m = rx.search(raw)
            if m:
                try:
                    val = m.group(1)
                    if i == 3:  # minorUnits pattern (cents)
                        price = int(val) / 100.0
                    else:
                        price = float(val.replace(",", ".").replace(" ", ""))
                    
                    if 0.01 < price < 100000:
                        return price
                except ValueError:
                    continue
    
    return None

def _extract_price_from_meta(soup: BeautifulSoup) -> Optional[float]:
    """Extract price from meta tags."""
    meta_selectors = [
        ("meta[property='og:price:amount']", "content"),
        ("meta[property='product:price:amount']", "content"),
        ("meta[itemprop='price']", "content"),
    ]
    
    for sel, attr in meta_selectors:
        tag = soup.select_one(sel)
        if tag and tag.get(attr):
            try:
                price = float(tag[attr].replace(",", ".").replace(" ", ""))
                if 0.01 < price < 100000:
                    return price
            except ValueError:
                continue
    
    return None

def _extract_price(soup: BeautifulSoup) -> tuple[str, str]:
    """
    Extract price using multiple strategies in order of reliability.
    Returns (price_string, source).
    """
    # Strategy 1: DOM (most accurate for displayed price)
    price = _extract_price_from_dom(soup)
    if price:
        return f"{price:.2f} PLN", "dom"
    
    # Strategy 2: JSON-LD structured data
    price = _extract_price_from_jsonld(soup)
    if price:
        return f"{price:.2f} PLN", "jsonld"
    
    # Strategy 3: Inline scripts
    price = _extract_price_from_scripts(soup)
    if price:
        return f"{price:.2f} PLN", "script"
    
    # Strategy 4: Meta tags
    price = _extract_price_from_meta(soup)
    if price:
        return f"{price:.2f} PLN", "meta"
    
    return "N/A", "none"

# ---------- stock ----------
def _extract_stock(soup: BeautifulSoup):
    # JSON-LD first
    for sc in soup.select("script[type='application/ld+json']"):
        raw = sc.string or sc.get_text() or ""
        for cand in (raw, raw.strip().rstrip(",")):
            try:
                data = json.loads(cand)
            except Exception:
                continue
            objs = data if isinstance(data, list) else [data]
            for o in objs:
                if isinstance(o, dict) and o.get("@type") == "Product":
                    offers = o.get("offers")
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    if isinstance(offers, dict):
                        av = (offers.get("availability") or "").lower()
                        if "instock" in av:
                            return True, "In stock (schema)"
                        if "outofstock" in av or "soldout" in av or "unavailable" in av:
                            return False, "Out of stock (schema)"
    
    # Add to cart button
    btn = soup.select_one("#add-to-cart-button, button[data-analytics-interaction-label='AddToCartItem']")
    if btn:
        if btn.has_attr("disabled") or btn.get("aria-disabled", "").lower() == "true":
            return False, "Add to cart disabled"
        return True, "Add to cart available"
    
    # Text search (last resort)
    body = soup.get_text(" ", strip=True)
    if re.search(r"\b(brak|wyprzedane|out of stock|niedostępny|unavailable)\b", body, re.I):
        return False, "Out of stock"
    
    return None, ""

# ---------- name / description ----------
def _extract_name(soup: BeautifulSoup) -> str:
    h1 = soup.select_one("h1")
    if h1:
        t = _clean(h1.get_text(" ", strip=True))
        if t:
            return t
    t = _clean((soup.title.get_text() if soup.title else "")).split("|")[0]
    return t or "Unknown_Product"

def _extract_description(soup: BeautifulSoup) -> str:
    region = soup.select_one("[itemprop='description']") or soup.select_one("[data-prototype-id='allegro.showoffer.description']")
    if region:
        return _clean_multiline(html.unescape(region.get_text("\n", strip=True)))
    hdr = soup.find(string=re.compile(r"\bOpis\b", re.I))
    if hdr and getattr(hdr, "parent", None):
        return _clean_multiline(html.unescape(hdr.parent.get_text("\n", strip=True)))
    meta = soup.select_one('meta[name="description"]')
    if meta and meta.get("content"):
        return _clean(meta["content"])
    return ""

# ---------- images ----------
def _to_original(u: str) -> str:
    return re.sub(r"/s\d+/", "/original/", u)

def _is_candidate(u: str) -> bool:
    if not u:
        return False
    if "://" not in u and u.startswith("//"):
        u = "https:" + u
    return (ALLEGRO_IMG_HOST in u) and not any(tok in u.lower() for tok in BAD_PATH_TOKENS)

def _pick_from_srcset(srcset: str) -> List[str]:
    out = []
    for part in (srcset or "").split(","):
        u = part.strip().split(" ")[0]
        if not u:
            continue
        if u.startswith("//"):
            u = "https:" + u
        out.append(_to_original(u))
    return out

def _cluster_key(u: str) -> Optional[str]:
    m = re.search(r"/original/([^/]+)/", u, re.I)
    return m.group(1).lower() if m else None

def _natkey(u: str) -> tuple:
    path = urlsplit(u).path
    m = re.search(r"(\d+)(?:\.\w+)?$", path)
    if m:
        return (int(m.group(1)), path.lower())
    return (10**9, path.lower())

def _images_from_jsonld(soup: BeautifulSoup) -> List[str]:
    urls: List[str] = []
    for sc in soup.select("script[type='application/ld+json']"):
        raw = sc.string or sc.get_text() or ""
        for cand in (raw, raw.strip().rstrip(",")):
            try:
                data = json.loads(cand)
            except Exception:
                continue
            objs = data if isinstance(data, list) else [data]
            for o in objs:
                if isinstance(o, dict) and o.get("@type") == "Product":
                    imgs = o.get("image")
                    if isinstance(imgs, str):
                        imgs = [imgs]
                    if isinstance(imgs, list):
                        for u in imgs:
                            if isinstance(u, str) and _is_candidate(u):
                                uu = u if u.startswith("http") else "https:" + u
                                urls.append(_to_original(_strip_query(uu)))
    seen, out = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u); out.append(u)
    return out

def _images_from_gallery_json(soup: BeautifulSoup) -> List[str]:
    PAT_URL = re.compile(r'"((?:https?:)?//[0-9a-z]\.' + re.escape(ALLEGRO_IMG_HOST) + r'/[^\s"\'\]]+)"', re.I)
    for sc in soup.find_all("script"):
        raw = sc.string or sc.get_text() or ""
        if not raw or (ALLEGRO_IMG_HOST not in raw):
            continue
        if re.search(r'"images"\s*:\s*\[', raw) or re.search(r'"gallery"\s*:\s*\[', raw) or re.search(r'"attachments"\s*:\s*\[', raw):
            urls = PAT_URL.findall(raw)
            urls = [u if u.startswith("http") else "https:" + u for u in urls]
            urls = [_to_original(_strip_query(u)) for u in urls if _is_candidate(u)]
            if urls:
                seen, uniq = set(), []
                for u in urls:
                    if u not in seen:
                        seen.add(u); uniq.append(u)
                return uniq
    return []

def _collect_images(soup: BeautifulSoup, want: int) -> List[str]:
    strip_imgs = soup.select('[data-box-name="images-container"] img, [class*="_07951_"] img')
    dom_urls = []
    for img in strip_imgs:
        u = img.get("src") or img.get("data-src") or img.get("data-lazy") or img.get("data-lazy-img") or img.get("data-zoom")
        if not u:
            continue
        if u.startswith("//"):
            u = "https:" + u
        if _is_candidate(u):
            dom_urls.append(_to_original(_strip_query(u)))
    if dom_urls:
        seen, uniq = set(), []
        for u in dom_urls:
            if u not in seen:
                seen.add(u); uniq.append(u)
        return uniq[:want]

    urls = _images_from_jsonld(soup)
    if urls:
        return urls[:want]

    gjson = _images_from_gallery_json(soup)
    if gjson:
        return gjson[:want]

    urls = []
    for img in soup.select("img"):
        for attr in ("src", "data-src", "data-lazy", "data-lazy-img", "data-zoom"):
            u = img.get(attr)
            if not u:
                continue
            if u.startswith("//"):
                u = "https:" + u
            if _is_candidate(u):
                urls.append(_to_original(_strip_query(u)))
        ss = img.get("srcset") or img.get("data-srcset")
        if ss:
            urls.extend(_pick_from_srcset(ss))
    for src in soup.select("source"):
        ss = src.get("srcset") or src.get("data-srcset")
        if ss:
            urls.extend(_pick_from_srcset(ss))
    og = soup.select_one("meta[property='og:image']")
    if og and og.get("content"):
        u = og["content"]
        if u.startswith("//"):
            u = "https:" + u
        if _is_candidate(u):
            urls.append(_to_original(_strip_query(u)))
    for ln in soup.select("link[rel*='image'], link[as='image']"):
        u = ln.get("href") or ""
        if u.startswith("//"):
            u = "https:" + u
        if _is_candidate(u):
            urls.append(_to_original(_strip_query(u)))

    RX_ANY = re.compile(r"(?:https?:)?//[0-9a-z]\." + re.escape(ALLEGRO_IMG_HOST) + r"/[^\s\"'>)]+", re.I)
    for sc in soup.find_all("script"):
        raw = sc.string or sc.get_text() or ""
        if not raw or (ALLEGRO_IMG_HOST not in raw):
            continue
        for m in RX_ANY.finditer(raw):
            u = m.group(0)
            if u.startswith("//"):
                u = "https:" + u
            if _is_candidate(u):
                urls.append(_to_original(_strip_query(u)))

    seen, uniq = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u); uniq.append(u)
    if not uniq:
        return []

    def _cluster_pair(u: str) -> Optional[str]:
        m = re.search(r"/original/([^/]+)/([^/]+)/", u, re.I)
        if m:
            return (m.group(1) + "/" + m.group(2)).lower()
        return _cluster_key(u)

    from collections import defaultdict
    clusters: Dict[str, List[str]] = defaultdict(list)
    for u in uniq:
        ck = _cluster_pair(u) or ""
        clusters[ck].append(u)

    sizes = sorted((len(v) for v in clusters.values()), reverse=True)
    if not sizes or sizes[0] <= 2:
        return uniq[:want]
    best_key = max(clusters.keys(), key=lambda k: len(clusters[k]))
    gallery = sorted(clusters[best_key], key=_natkey)[:want]
    return gallery

# ---------- downloads ----------
def _sniff_ext(ct: str, url: str, body: bytes) -> str:
    ct = (ct or "").lower()
    if "jpeg" in ct or "jpg" in ct: return ".jpg"
    if "png" in ct: return ".png"
    if "webp" in ct: return ".webp"
    if "gif" in ct: return ".gif"
    if "svg" in ct: return ".svg"
    if "avif" in ct: return ".avif"
    p = urlsplit(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".avif"):
        if p.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    if body[:3] == b"\xFF\xD8\xFF": return ".jpg"
    if body[:8] == b"\x89PNG\r\n\x1a\n": return ".png"
    if body[:6] in (b"GIF87a", b"GIF89a"): return ".gif"
    if len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP": return ".webp"
    if len(body) >= 12 and body[4:8] == b"ftyp": return ".avif"
    return ".jpg"

def _download_images(img_urls: List[str], folder: Path, referer: Optional[str]) -> List[str]:
    saved: List[str] = []
    folder.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": ACCEPT_LANG})

    def _one(idx_url):
        idx, u = idx_url
        headers = {"Accept": "image/avif,image/webp,image/*,*/*;q=0.8", "Referer": referer or ""}
        try:
            r = session.get(u, headers=headers, timeout=40, allow_redirects=True)
            if not r.ok or not r.content:
                return None
            ext = _sniff_ext(r.headers.get("content-type", ""), u, r.content)
            if ext == ".svg":
                return None
            p = folder / f"{idx:02d}{ext}"
            p.write_bytes(r.content)
            return str(p)
        except Exception:
            return None

    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for res in ex.map(_one, enumerate(img_urls, 1)):
            if res:
                saved.append(res)
    return saved

# ---------- single-entry scraper ----------
def scrape_allegro_oxylabs(url: str) -> Dict:
    html_doc = _fetch_html(url)
    soup = BeautifulSoup(html_doc, "lxml")
    
    # ========== CHECK IF LISTING IS INVALID (404, ENDED, ETC.) ==========
    is_invalid, invalid_reason = _check_listing_invalid(soup)
    if is_invalid:
        print(f"\n[Allegro] ⚠️ INVALID LINK: {url}")
        print(f"[Allegro] Reason: {invalid_reason}")
        print("[Allegro] Returning empty result with 'Invalid Link' marker")
        
        # Determine the status based on reason
        if "404" in invalid_reason:
            status = "not_found"
            name = "Invalid Link - Page Not Found (404)"
        elif "ended" in invalid_reason.lower() or "zakończona" in invalid_reason.lower():
            status = "ended"
            name = "Invalid Link - Listing Ended"
        else:
            status = "unavailable"
            name = "Invalid Link - Product Unavailable"
        
        return {
            "url": _strip_query(url),
            "name": name,
            "price": "N/A",
            "price_source": "none",
            "in_stock": False,
            "stock_text": invalid_reason,
            "description": "",
            "image_count": 0,
            "images": [],
            "image_urls": [],
            "folder": "",
            "fetched_via": "oxylabs-allegro",
            "listing_status": status,
            "invalid_reason": invalid_reason,
        }
    # ====================================================================

    name = _extract_name(soup)
    price, price_source = _extract_price(soup)
    in_stock, stock_text = _extract_stock(soup)
    description = _extract_description(soup)
    image_urls = _collect_images(soup, want=WANT_IMAGES)

    stable = _stable_id_from_url(url)
    # Limit folder name to ~70 chars total to prevent Windows MAX_PATH issues
    safe_name = _safe_name(name, max_len=40)  # Product name: max 40 chars
    safe_id = stable[:12] if stable else "unknown"  # ID: max 12 chars
    base = DATA_DIR / f"allegro_{safe_name}_{safe_id}"
    folder = _unique_path(base)
    folder.mkdir(parents=True, exist_ok=True)

    # Save raw HTML for debugging
    try:
        (folder / "raw_html.html").write_text(html_doc, encoding="utf-8")
    except Exception:
        pass

    images = _download_images(image_urls, folder, referer=url) if DOWNLOAD_IMAGES and image_urls else []

    out = {
        "url": _strip_query(url),
        "name": name,
        "price": price,
        "price_source": price_source,
        "in_stock": in_stock,
        "stock_text": stock_text,
        "description": description,
        "image_count": len(images) if DOWNLOAD_IMAGES else len(image_urls),
        "images": images if DOWNLOAD_IMAGES else [],
        "image_urls": image_urls,
        "folder": str(folder),
        "fetched_via": "oxylabs-allegro",
        "listing_status": "active",
    }

    try:
        (folder / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    return out

# # ---------- run ONE hardcoded URL ----------
# if __name__ == "__main__":
#     URL = "https://allegro.pl/oferta/vq-laura-ashley-toster-2-plastrowy-stalowy-vintage-z-funkcja-podgrzewania-17372283850"
#     print(json.dumps(scrape_allegro_oxylabs(URL), indent=2, ensure_ascii=False))
    
#     # Print any failed job IDs at the end
#     print("\n" + "="*60)
#     print("JOB ID SUMMARY")
#     print("="*60)
#     recent = get_recent_job_ids(5)
#     if recent:
#         print("Recent Job IDs:")
#         for jid in recent:
#             print(f"  - {jid}")
#     print(f"\nFull log: {JOB_ID_LOG_FILE}")