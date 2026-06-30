"""
test_full_scan.py — Reliable Tableau chart tooltip scanner.

Root cause of previous failures:
  1. Scan range was only 250px from right → missed all pre-2025 data
  2. MutationObserver only watched childList → Tableau REUSES the tooltip
     element and just changes its text, so text-only updates were invisible
     to the observer.

Fixes applied:
  - In-browser setInterval polls for tooltip every 20ms (catches all text changes)
  - Full-width scan (configurable: 2025 only or full history)
  - Moves batched in chunks of 300 with .pause() so browser handles timing
  - Direct Python poll() as safety net between batches
  - Detailed completeness report per date
"""

import re
import time
import csv
import logging
from datetime import datetime

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

BASE_URL = "https://www.bts.gov/freight-indicators#anchored-offshore"
IFRAME_KEY = 'ContainershipsAnchored'

# Pixel positions of Jan 1 for each year (from iframe SVG axis analysis)
# Canvas width = 744px, each year ≈ 137px, each week ≈ 2.63px
YEAR_X = {2021: 25, 2022: 162, 2023: 299, 2024: 437, 2025: 574, 2026: 711}

# ─── JS snippets ──────────────────────────────────────────────────────────────

INJECT_JS = """
// Reset state
window.capturedTooltips = [];
window._ttSeen = new Set();

// All selectors Tableau uses for the tooltip element
function readTooltip() {
    var sels = [
        '.tab-tooltip',
        '.tab-glass-content',
        '.tab-beautified-tooltip',
        '[class*="tab-"][class*="tooltip"]'
    ];
    for (var s of sels) {
        var el = document.querySelector(s);
        if (el && el.innerText && el.innerText.includes('Vessels')) {
            return el.innerText.trim();
        }
    }
    return null;
}

function captureNow() {
    var t = readTooltip();
    if (t && !window._ttSeen.has(t)) {
        window._ttSeen.add(t);
        window.capturedTooltips.push(t);
    }
}

// Method 1: MutationObserver — catches DOM additions AND attribute/text changes
if (window._mo) { try { window._mo.disconnect(); } catch(e){} }
window._mo = new MutationObserver(captureNow);
window._mo.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    characterData: true
});

// Method 2: Polling timer — catches cases where observer fires between frames
if (window._pollTimer) clearInterval(window._pollTimer);
window._pollTimer = setInterval(captureNow, 20);

return 'Injected: observer + 20ms poll active';
"""

COLLECT_JS = "return window.capturedTooltips || [];"

STOP_JS = """
if (window._pollTimer) clearInterval(window._pollTimer);
if (window._mo) try { window._mo.disconnect(); } catch(e){}
return (window.capturedTooltips || []).length;
"""

# ─── Parsing ──────────────────────────────────────────────────────────────────

def parse_tooltip(text):
    r = re.search(r'Port Region:\s*(East|West|Gulf)', text, re.I)
    d = re.search(r'Date:\s*(\d{1,2}/\d{1,2}/\d{4})', text)
    v = re.search(r'#\s*of\s*Vessels:\s*(\d+)', text)
    if r and d and v:
        return r.group(1).strip(), d.group(1).strip(), int(v.group(1))
    return None

def build_data(raw_list):
    data = {}
    for text in raw_list:
        parsed = parse_tooltip(text)
        if parsed:
            region, date, value = parsed
            data.setdefault(date, {})[region] = value
    return data

# ─── Scanner ──────────────────────────────────────────────────────────────────

def scan(driver, canvas, x_start, x_end, x_step=2, y_step=6, pause_ms=45, batch_size=300):
    """
    Sweep x=[x_start, x_end] with full vertical coverage.
    Batches moves in chunks so Python can collect & log between them.
    """
    w, h = canvas.size['width'], canvas.size['height']
    cx, cy = w // 2, h // 2
    pause_s = pause_ms / 1000.0

    # Build move list
    moves = [
        (x - cx, y - cy)
        for x in range(x_start, x_end + 1, x_step)
        for y in range(8, h - 8, y_step)
    ]
    total = len(moves)
    log.info(f"Scan: {total} moves @ {pause_ms}ms each ≈ {total * pause_ms / 1000:.0f}s")

    done = 0
    for i in range(0, total, batch_size):
        chunk = moves[i : i + batch_size]
        chain = ActionChains(driver)
        for ox, oy in chunk:
            chain.move_to_element_with_offset(canvas, ox, oy).pause(pause_s)
        chain.perform()
        done += len(chunk)
        count = driver.execute_script("return (window.capturedTooltips||[]).length;")
        pct = done / total * 100
        log.info(f"  [{pct:5.1f}%] {done}/{total} moves — {count} tooltips captured")

    time.sleep(1)

# ─── Main ─────────────────────────────────────────────────────────────────────

def run(year_start=2025, year_end=None, out_file=None):
    """
    Run the scan for a year range.
    year_start: first year to scan (default 2025 for testing)
    year_end:   last year boundary (default = year_start + 1)
    out_file:   CSV output path
    """
    if year_end is None:
        year_end = year_start + 1
    if out_file is None:
        out_file = f"test_scan_{year_start}.csv"

    x_start = max(YEAR_X.get(year_start, 574) - 5, 5)
    x_end   = min(YEAR_X.get(year_end,   744) + 5, 740)

    log.info("=" * 60)
    log.info(f"TARGET: {year_start} data (x={x_start}→{x_end})")
    log.info("=" * 60)

    options = uc.ChromeOptions()
    options.add_argument('--window-size=1920,1080')
    # images disabled speeds up page load
    options.add_argument('--blink-settings=imagesEnabled=false')
    # Pin major version to match installed Chrome (149); avoids cached wrong-version driver
    driver = uc.Chrome(options=options, version_main=149)

    try:
        # 1. Load page
        log.info(f"Loading {BASE_URL}")
        driver.get(BASE_URL)
        time.sleep(5)

        # 2. Navigate to chart section
        try:
            link = driver.find_element(By.CSS_SELECTOR, 'a[href="#anchored-offshore"]')
            driver.execute_script("arguments[0].click();", link)
            time.sleep(3)
        except Exception:
            driver.execute_script("window.location.hash='anchored-offshore';")
            time.sleep(2)

        # 3. Find the Tableau iframe
        iframe = None
        for attempt in range(20):
            for f in driver.find_elements(By.TAG_NAME, 'iframe'):
                if IFRAME_KEY in (f.get_attribute('src') or ''):
                    iframe = f
                    break
            if iframe:
                break
            driver.execute_script("window.scrollBy(0, 400);")
            time.sleep(1)

        if not iframe:
            log.error("Iframe not found — chart may not have loaded")
            return {}

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", iframe)
        driver.switch_to.frame(iframe)
        log.info("Inside iframe — waiting 8s for Tableau to initialize...")
        time.sleep(8)

        # 4. Find the main data canvas (inside .tab-tvView)
        canvas = None
        for _ in range(15):
            candidates = driver.find_elements(By.CSS_SELECTOR, '.tab-tvView canvas')
            if not candidates:
                candidates = driver.find_elements(By.TAG_NAME, 'canvas')
            for c in reversed(candidates):
                if c.is_displayed() and c.size['width'] > 200:
                    canvas = c
                    break
            if canvas:
                break
            time.sleep(1)

        if not canvas:
            log.error("Canvas not found inside iframe")
            return {}

        log.info(f"Canvas found: {canvas.size['width']}×{canvas.size['height']}px")

        # 5. Inject capture net
        msg = driver.execute_script(INJECT_JS)
        log.info(f"Capture net: {msg}")
        time.sleep(0.5)

        # 6. Scan
        scan_start = time.time()
        scan(driver, canvas, x_start, x_end)
        elapsed = time.time() - scan_start

        # 7. Stop timers and collect
        total_captured = driver.execute_script(STOP_JS)
        raw = driver.execute_script(COLLECT_JS)
        log.info(f"Scan done in {elapsed:.0f}s — {total_captured} unique tooltips")

        # 8. Parse
        data = build_data(raw)

        # 9. Report
        if not data:
            log.warning("No parseable data found. Check if chart loaded and tooltips appeared.")
            return {}

        sorted_dates = sorted(data.keys(), key=lambda d: datetime.strptime(d, "%m/%d/%Y"))
        n_complete = sum(1 for d in sorted_dates if all(r in data[d] for r in ['East', 'West', 'Gulf']))

        log.info("")
        log.info("=" * 60)
        log.info(f"RESULTS: {len(sorted_dates)} dates  |  {n_complete} complete (all 3 regions)")
        log.info(f"Range:   {sorted_dates[0]}  →  {sorted_dates[-1]}")
        log.info("=" * 60)
        for dt in sorted_dates:
            e = data[dt].get('East', '?')
            w_val = data[dt].get('West', '?')
            g = data[dt].get('Gulf', '?')
            missing = [r for r in ['East', 'West', 'Gulf'] if r not in data[dt]]
            status = "OK" if not missing else f"MISSING {missing}"
            log.info(f"  {dt:12s}  E={str(e):>3}  W={str(w_val):>3}  G={str(g):>3}  [{status}]")

        # 10. Save CSV
        with open(out_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Date', 'East', 'West', 'Gulf', 'Status'])
            for dt in sorted_dates:
                missing = [r for r in ['East', 'West', 'Gulf'] if r not in data[dt]]
                writer.writerow([
                    dt,
                    data[dt].get('East', ''),
                    data[dt].get('West', ''),
                    data[dt].get('Gulf', ''),
                    'COMPLETE' if not missing else f'MISSING:{",".join(missing)}'
                ])
        log.info(f"\nSaved → {out_file}")
        return data

    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    # ── PHASE 1: Test with 2025 data only ──
    # 2025 x range: 574→711 (≈137px, ≈52 weeks)
    # Estimated time: ~4 minutes
    log.info("PHASE 1 — Scanning 2025 data (testing extraction)")
    result = run(year_start=2025, year_end=2026, out_file="test_scan_2025.csv")

    if result:
        log.info(f"\n✓ PHASE 1 PASS — {len(result)} weeks extracted")
        log.info("If results look good, run Phase 2 by changing year_start=2021")
    else:
        log.info("\n✗ PHASE 1 FAILED — No data extracted")
        log.info("Check: 1) Chrome is open  2) Chart loaded  3) Tooltip visible")
