"""
test_highlight_scan.py
Uses Tableau's legend "Highlight Selected Items" to isolate one region at a time.

Strategy (user's idea):
  1. Click the legend highlight button  (tabLegendHighlighterButton)
  2. Click "East"  → only East line is bold, others greyed  → scan canvas
  3. Click "West"  → repeat
  4. Click "Gulf"  → repeat
  5. Merge results → CSV

Benefits over blind scan:
  - Tooltip ALWAYS shows the highlighted region → no line-proximity ambiguity
  - Only 5 y-positions needed per x (not full vertical sweep)
  - ~3× faster, much more reliable

Test range: ~11/25/2025 → 6/23/2026  (x=580 to x=740)
"""

import os
import re
import time
import csv
import logging
from datetime import datetime

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

# ─── Logging setup (file + console) ──────────────────────────────────────────
_RUN_TS  = datetime.now().strftime('%Y%m%d_%H%M%S')
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', f'test_highlight_{_RUN_TS}')
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, f'test_highlight_{_RUN_TS}.log')

_fmt     = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
_root    = logging.getLogger()
_root.setLevel(logging.INFO)
_root.handlers.clear()

_fh = logging.FileHandler(_LOG_FILE, encoding='utf-8')
_fh.setFormatter(_fmt)
_root.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
_root.addHandler(_ch)

log = logging.getLogger(__name__)
log.info(f"Log file: {_LOG_FILE}")

BASE_URL   = "https://www.bts.gov/freight-indicators#anchored-offshore"
IFRAME_KEY = 'ContainershipsAnchored'

# Y positions (pixels from top of 423px canvas) that cover the full value range 0-70 vessels
# y≈401→val=0,  y≈348→val=10,  y≈241→val=30,  y≈134→val=50,  y≈27→val=70
Y_POSITIONS = [390, 340, 280, 210, 140, 70, 30]

# ─── JS helpers ───────────────────────────────────────────────────────────────

INIT_JS = """
window.captured = [];
window._seen   = new Set();
return 'Store ready';
"""

POLL_JS = """
(function() {
    var sels = ['.tab-tooltip', '.tab-glass-content', '.tab-beautified-tooltip'];
    for (var s of sels) {
        var el = document.querySelector(s);
        if (el && el.innerText && el.innerText.includes('Vessels')) {
            var t = el.innerText.trim();
            if (!window._seen.has(t)) {
                window._seen.add(t);
                window.captured.push(t);
                return t;
            }
            return '__SEEN__';
        }
    }
    return null;
})();
"""

# ─── Parsers ──────────────────────────────────────────────────────────────────

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
        p = parse_tooltip(text)
        if p:
            region, date, value = p
            data.setdefault(date, {})[region] = value
    return data

# ─── Legend interactions ───────────────────────────────────────────────────────

def enable_highlight(driver, canvas):
    """
    Enable legend highlight mode.

    The tabLegendHighlighterButton sits inside .tabLegendTitleControls which
    has opacity:0 / pointer-events:none until Tableau detects the mouse is
    inside the viz.  Steps:
      1. Hover the chart canvas → Tableau activates the viz, shows controls
      2. Force-override CSS on the controls div so the button is always reachable
      3. Move mouse to the legend panel (keeps hover state alive)
      4. JS-click the button (bypasses any residual pointer-events restriction)
    """
    try:
        # 1. Hover canvas center to wake up the viz
        ActionChains(driver).move_to_element(canvas).perform()
        time.sleep(0.5)

        # 2. Hover the legend panel so Tableau shows the title controls
        try:
            legend = driver.find_element(By.CSS_SELECTOR, '.tabLegendPanel')
            ActionChains(driver).move_to_element(legend).perform()
            time.sleep(0.4)
        except Exception:
            pass

        # 3. Force CSS visibility in case opacity / pointer-events are still locked
        driver.execute_script("""
            var ctrl = document.querySelector('.tabLegendTitleControls');
            if (ctrl) {
                ctrl.style.opacity      = '1';
                ctrl.style.pointerEvents = 'auto';
                ctrl.style.visibility   = 'visible';
            }
        """)
        time.sleep(0.2)

        # 4. Check + click
        btn = driver.find_element(By.CSS_SELECTOR, '.tabLegendHighlighterButton')
        pressed = btn.get_attribute('aria-pressed')
        log.info(f"Highlight button aria-pressed={pressed}")

        if pressed != 'true':
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.7)
            pressed_after = btn.get_attribute('aria-pressed')
            log.info(f"→ Clicked  (aria-pressed now: {pressed_after})")
        else:
            log.info("→ Highlight mode already ON")
        return True
    except Exception as e:
        log.warning(f"Could not enable highlight mode: {e}")
        return False


def select_region(driver, region):
    """Click the legend item for the given region name."""
    try:
        items = driver.find_elements(By.CSS_SELECTOR, '.tabLegendItem')
        for item in items:
            try:
                label = item.find_element(By.CSS_SELECTOR, '.tabLegendItemLabel')
            except Exception:
                continue
            if label.text.strip() == region:
                driver.execute_script("arguments[0].click();", item)
                time.sleep(1.2)   # let chart re-render with only this region highlighted
                selected = item.get_attribute('aria-selected')
                log.info(f"Clicked '{region}' legend item (aria-selected={selected})")
                return True
        log.error(f"Legend item '{region}' not found in DOM")
        return False
    except Exception as e:
        log.error(f"select_region({region}) error: {e}")
        return False

# ─── Scanner ──────────────────────────────────────────────────────────────────

def scan_one_region(driver, canvas, region, x_start, x_end, x_step=2, delay_ms=40):
    """
    With only `region` highlighted in the legend, sweep right→left across
    the canvas collecting tooltips.  Uses individual .perform() calls so
    each round-trip is <<1 s (avoids the 120 s Selenium command timeout).
    """
    w, h    = canvas.size['width'], canvas.size['height']
    cx, cy  = w // 2, h // 2
    delay   = delay_ms / 1000.0

    x_values = list(range(x_end, x_start - 1, -x_step))
    total    = len(x_values) * len(Y_POSITIONS)
    log.info(f"[{region}] {len(x_values)} x-pos × {len(Y_POSITIONS)} y-pos = {total} moves @ {delay_ms}ms")

    region_hits = []
    done        = 0
    last_report = time.time()

    for x in x_values:
        for y in Y_POSITIONS:
            try:
                ActionChains(driver).move_to_element_with_offset(
                    canvas, x - cx, y - cy
                ).perform()
                time.sleep(delay)
                result = driver.execute_script(POLL_JS)
                if result and result != '__SEEN__':
                    p = parse_tooltip(result)
                    if p:
                        r, dt, val = p
                        region_hits.append(result)
                        log.info(f"  [{region}] {dt} → {r}={val}")
            except Exception:
                pass
            done += 1

        if time.time() - last_report > 15:
            log.info(f"  [{region}] {done}/{total} moves | {len(region_hits)} hits")
            last_report = time.time()

    log.info(f"[{region}] Scan done → {len(region_hits)} unique tooltips")
    return region_hits

# ─── Main ─────────────────────────────────────────────────────────────────────

def run(x_start=580, x_end=740, out_file="test_highlight_scan.csv"):
    """
    Run the three-pass highlight scan.
    x_start / x_end correspond to canvas pixel positions.
    Default covers approx Sep 2025 → Jun 2026.
    """
    log.info("=" * 60)
    log.info(f"HIGHLIGHT SCAN  x={x_start}→{x_end}  (East → West → Gulf)")
    log.info("=" * 60)

    options = uc.ChromeOptions()
    options.add_argument('--window-size=1920,1080')
    driver = uc.Chrome(options=options, version_main=149)

    try:
        # ── 1. Load page ──────────────────────────────────────────────
        log.info(f"Loading {BASE_URL}")
        driver.get(BASE_URL)
        time.sleep(5)

        # Navigate to chart section
        try:
            link = driver.find_element(By.CSS_SELECTOR, 'a[href="#anchored-offshore"]')
            driver.execute_script("arguments[0].click();", link)
            time.sleep(3)
        except Exception:
            driver.execute_script("window.location.hash='anchored-offshore';")
            time.sleep(2)

        # ── 2. Find Tableau iframe ─────────────────────────────────────
        iframe = None
        for _ in range(20):
            for f in driver.find_elements(By.TAG_NAME, 'iframe'):
                if IFRAME_KEY in (f.get_attribute('src') or ''):
                    iframe = f
                    break
            if iframe:
                break
            driver.execute_script("window.scrollBy(0, 400);")
            time.sleep(1)

        if not iframe:
            log.error("Iframe not found — aborting")
            return {}

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", iframe)
        driver.switch_to.frame(iframe)
        log.info("Switched to iframe — waiting 8 s for Tableau init...")
        time.sleep(8)

        # ── 3. Find main canvas ────────────────────────────────────────
        canvas = None
        for _ in range(15):
            for c in reversed(driver.find_elements(By.CSS_SELECTOR, '.tab-tvView canvas')):
                if c.is_displayed() and c.size['width'] > 200:
                    canvas = c
                    break
            if not canvas:
                for c in reversed(driver.find_elements(By.TAG_NAME, 'canvas')):
                    if c.is_displayed() and c.size['width'] > 200:
                        canvas = c
                        break
            if canvas:
                break
            time.sleep(1)

        if not canvas:
            log.error("Canvas not found — aborting")
            return {}

        log.info(f"Canvas: {canvas.size['width']}×{canvas.size['height']}px")

        # ── 4. Enable highlight mode ───────────────────────────────────
        enable_highlight(driver, canvas)

        # ── 5. Three-pass scan (one region at a time) ──────────────────
        driver.execute_script(INIT_JS)
        all_raw = []

        for region in ['East', 'West', 'Gulf']:
            log.info(f"\n{'─'*50}")
            log.info(f"PASS: {region}")
            log.info(f"{'─'*50}")

            # Reset seen set so re-captures are fresh per region
            driver.execute_script("window.captured=[]; window._seen=new Set();")

            if not select_region(driver, region):
                log.warning(f"Skipping {region}")
                continue

            hits = scan_one_region(driver, canvas, region, x_start, x_end)
            all_raw.extend(hits)

        # ── 6. Parse & build data dict ─────────────────────────────────
        data = build_data(all_raw)

        if not data:
            log.warning("No parseable data extracted.")
            log.warning("Possible causes: chart not loaded / highlight didn't work / x range wrong")
            return {}

        # ── 7. Report ──────────────────────────────────────────────────
        sorted_dates = sorted(
            data.keys(), key=lambda d: datetime.strptime(d, "%m/%d/%Y")
        )
        n_complete = sum(
            1 for d in sorted_dates
            if all(r in data[d] for r in ['East', 'West', 'Gulf'])
        )

        log.info(f"\n{'='*60}")
        log.info(f"RESULTS  {len(sorted_dates)} dates  |  {n_complete} fully complete")
        log.info(f"Range    {sorted_dates[0]}  →  {sorted_dates[-1]}")
        log.info(f"{'='*60}")
        for dt in sorted_dates:
            e   = data[dt].get('East', '?')
            w_v = data[dt].get('West', '?')
            g   = data[dt].get('Gulf', '?')
            missing = [r for r in ['East', 'West', 'Gulf'] if r not in data[dt]]
            status  = "OK" if not missing else f"MISS:{','.join(missing)}"
            log.info(f"  {dt:12s}  E={str(e):>3}  W={str(w_v):>3}  G={str(g):>3}  [{status}]")

        # ── 8. Save CSV ────────────────────────────────────────────────
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
    # Test: covers ~Sep 2025 → Jun 2026 (x=580→740)
    # Adjust x_start/x_end to narrow or widen the range.
    run(x_start=580, x_end=740, out_file="test_highlight_scan.csv")
