"""
test_playwright_highlight.py
Uses Playwright (not Selenium) to interact with the Tableau legend.

Playwright advantages:
  - .hover() fires real mouseenter/mouseover events → Tableau's CSS opacity triggers
  - frame_locator() handles iframes cleanly without switch_to.frame()
  - auto-waits for elements before acting

Install once:
    pip install playwright
    playwright install chromium

Run:
    python test_playwright_highlight.py
"""

import os
import re
import csv
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ─── Logging ──────────────────────────────────────────────────────────────────
_RUN_TS  = datetime.now().strftime('%Y%m%d_%H%M%S')
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', f'pw_{_RUN_TS}')
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, f'pw_{_RUN_TS}.log')

_fmt  = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
_root = logging.getLogger()
_root.setLevel(logging.INFO)
_root.handlers.clear()
_fh = logging.FileHandler(_LOG_FILE, encoding='utf-8')
_fh.setFormatter(_fmt)
_root.addHandler(_fh)
_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
_root.addHandler(_ch)

log = logging.getLogger(__name__)
log.info(f"Log → {_LOG_FILE}")

# ─── Constants ────────────────────────────────────────────────────────────────
BASE_URL   = "https://www.bts.gov/freight-indicators#anchored-offshore"
IFRAME_KEY = 'ContainershipsAnchored'

POLL_JS = """
(function() {
    var sels = ['.tab-tooltip', '.tab-beautified-tooltip', '.tab-glass-content'];
    for (var s of sels) {
        var el = document.querySelector(s);
        if (el && el.innerText && el.innerText.includes('Vessels')) {
            var t = el.innerText.trim();
            window._seen = window._seen || new Set();
            window.captured = window.captured || [];
            if (!window._seen.has(t)) { window._seen.add(t); window.captured.push(t); return t; }
            return '__SEEN__';
        }
    }
    return null;
})();
"""

# ─── Parser ───────────────────────────────────────────────────────────────────
def parse_tooltip(text):
    r = re.search(r'Port Region:\s*(East|West|Gulf)', text, re.I)
    d = re.search(r'Date:\s*(\d{1,2}/\d{1,2}/\d{4})', text)
    v = re.search(r'#\s*of\s*Vessels:\s*(\d+)', text)
    if r and d and v:
        return r.group(1).strip(), d.group(1).strip(), int(v.group(1))
    return None

# ─── Main ─────────────────────────────────────────────────────────────────────
def run(x_start=580, x_end=740, out_file="test_pw_results.csv"):
    log.info("=" * 60)
    log.info(f"PLAYWRIGHT HIGHLIGHT SCAN  x={x_start}→{x_end}")
    log.info("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=30,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
            ]
        )

        context = browser.new_context(
            viewport={'width': 1440, 'height': 900},
            locale='en-US',
            timezone_id='America/New_York',
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/149.0.0.0 Safari/537.36'
            ),
            extra_http_headers={
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'sec-ch-ua': '"Google Chrome";v="149", "Chromium";v="149", "Not?A_Brand";v="24"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
            }
        )

        # Mask webdriver detection before any page loads
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {}, app: {} };
            const orig = navigator.permissions.query.bind(navigator.permissions);
            navigator.permissions.query = (p) =>
                p.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : orig(p);
        """)

        page = context.new_page()

        # ── 1. Load page ───────────────────────────────────────────────────
        log.info(f"Navigating to {BASE_URL}")
        page.goto(BASE_URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(6000)

        # Scroll to chart section
        try:
            page.click('a[href="#anchored-offshore"]', timeout=5000)
            page.wait_for_timeout(3000)
        except PWTimeout:
            page.evaluate("window.location.hash='anchored-offshore'")
            page.wait_for_timeout(2000)

        # ── 2. Find the correct iframe ─────────────────────────────────────
        log.info(f"Looking for iframe with '{IFRAME_KEY}' in src ...")

        # Scroll down until it appears
        frame = None
        for _ in range(20):
            for f in page.frames:
                if IFRAME_KEY in f.url:
                    frame = f
                    log.info(f"  Found frame: {f.url[:100]}")
                    break
            if frame:
                break
            page.evaluate("window.scrollBy(0, 400)")
            page.wait_for_timeout(800)

        if not frame:
            log.error("Iframe not found — aborting")
            context.close(); browser.close()
            return {}

        # Scroll the iframe into view on the main page
        iframe_el = page.locator(f'iframe[src*="{IFRAME_KEY}"]').first
        iframe_el.scroll_into_view_if_needed()
        log.info("Waiting 15 s for Tableau to fully render ...")
        page.wait_for_timeout(15000)

        # ── 3. Find canvas ─────────────────────────────────────────────────
        log.info("Locating canvas inside iframe ...")

        # Check what's actually in the frame first
        frame_status = frame.evaluate("""() => ({
            url:     location.href,
            title:   document.title,
            canvases: Array.from(document.querySelectorAll('canvas')).map(c => ({
                w: c.offsetWidth, h: c.offsetHeight,
                cls: c.className.substring(0, 60),
                vis: c.offsetWidth > 0 && c.offsetHeight > 0
            })),
            denied: document.body.innerText.includes('Access Denied') ||
                    document.body.innerText.includes('403')
        })""")
        log.info(f"Frame status: {frame_status}")

        if frame_status.get('denied'):
            log.error("ACCESS DENIED inside iframe — Tableau blocked. Check headers/session.")
            input("Press ENTER to close browser...")
            browser.close()
            return {}

        # Find largest visible canvas
        box = None
        canvas = None
        for sel in ['.tab-tvView canvas', '.tabCanvas', 'canvas']:
            try:
                els = frame.locator(sel).all()
                for el in reversed(els):
                    b = el.bounding_box()
                    if b and b['width'] > 200 and b['height'] > 100:
                        canvas = el
                        box = b
                        log.info(f"Canvas found via '{sel}': "
                                 f"x={b['x']:.0f} y={b['y']:.0f} "
                                 f"w={b['width']:.0f} h={b['height']:.0f}")
                        break
            except Exception:
                pass
            if canvas:
                break

        if not canvas:
            log.error("No canvas found — Tableau may not have rendered.")
            input("Press ENTER to close browser...")
            browser.close()
            return {}

        # ── 4. Enable highlight mode ───────────────────────────────────────
        log.info("Enabling legend highlight mode ...")

        # Step A: hover the canvas first → activates the viz
        canvas.hover()
        page.wait_for_timeout(600)

        # Step B: hover the legend panel → makes the controls div visible
        try:
            legend_panel = frame.locator('.tabLegendPanel').first
            legend_panel.hover(timeout=5000)
            page.wait_for_timeout(500)
            log.info("  Hovered legend panel")
        except PWTimeout:
            log.warning("  .tabLegendPanel not found — trying to continue")

        # Step C: check current state of the controls
        ctrl_info = frame.evaluate("""() => {
            var ctrl = document.querySelector('.tabLegendTitleControls');
            var btn  = document.querySelector('.tabLegendHighlighterButton');
            return {
                ctrl_opacity:  ctrl ? getComputedStyle(ctrl).opacity : 'NO_CTRL',
                ctrl_pointer:  ctrl ? getComputedStyle(ctrl).pointerEvents : 'NO_CTRL',
                ctrl_display:  ctrl ? getComputedStyle(ctrl).display  : 'NO_CTRL',
                btn_pressed:   btn  ? btn.getAttribute('aria-pressed') : 'NO_BTN',
                btn_class:     btn  ? btn.className : 'NO_BTN'
            };
        }""")
        log.info(f"  Controls state: {ctrl_info}")

        # Step D: click the highlight button
        try:
            btn = frame.locator('.tabLegendHighlighterButton').first

            # If opacity is 0, force it visible then click
            frame.evaluate("""() => {
                var ctrl = document.querySelector('.tabLegendTitleControls');
                if (ctrl) {
                    ctrl.style.opacity       = '1';
                    ctrl.style.pointerEvents = 'auto';
                    ctrl.style.visibility    = 'visible';
                }
            }""")
            page.wait_for_timeout(200)

            btn.hover(timeout=3000)
            page.wait_for_timeout(300)
            btn.click(timeout=3000)
            page.wait_for_timeout(700)

            pressed = btn.get_attribute('aria-pressed')
            log.info(f"  Highlight button clicked → aria-pressed={pressed}")
        except PWTimeout as e:
            log.warning(f"  Could not click highlight button: {e}")

        # ── 5. Three-pass scan ─────────────────────────────────────────────
        frame.evaluate("window.captured=[]; window._seen=new Set();")
        all_raw = []

        for region in ['East', 'West', 'Gulf']:
            log.info(f"\n{'─'*50}")
            log.info(f"REGION PASS: {region}")
            log.info(f"{'─'*50}")

            # Click that region's legend item
            try:
                item = frame.locator('.tabLegendItem').filter(has_text=region).first
                item.scroll_into_view_if_needed()
                item.hover(timeout=5000)
                page.wait_for_timeout(300)
                item.click(timeout=5000)
                page.wait_for_timeout(1500)

                sel = item.get_attribute('aria-selected')
                log.info(f"  Clicked '{region}' item → aria-selected={sel}")
            except PWTimeout as e:
                log.warning(f"  Could not click '{region}' legend item: {e}")
                continue

            # Reset captures for this region
            frame.evaluate("window.captured=[]; window._seen=new Set();")

            # Scan: sweep x right→left at Y_POSITIONS
            w   = box['width']
            h   = box['height']
            cx  = box['x'] + w / 2
            cy  = box['y'] + h / 2

            y_positions = [390, 340, 280, 210, 140, 70, 30]
            x_values    = list(range(x_end, x_start - 1, -2))
            total       = len(x_values) * len(y_positions)
            log.info(f"  Scanning {len(x_values)} x-pos × {len(y_positions)} y-pos = {total} moves")

            region_hits = []
            done        = 0

            for x in x_values:
                for y in y_positions:
                    abs_x = box['x'] + x
                    abs_y = box['y'] + y
                    page.mouse.move(abs_x, abs_y)
                    page.wait_for_timeout(40)

                    result = frame.evaluate(POLL_JS)
                    if result and result != '__SEEN__':
                        p_parsed = parse_tooltip(result)
                        if p_parsed:
                            reg, dt, val = p_parsed
                            region_hits.append(result)
                            log.info(f"    [{region}] {dt} → {reg}={val}")
                done += len(y_positions)

                if done % (len(y_positions) * 20) == 0:
                    log.info(f"  {done}/{total} moves | {len(region_hits)} hits")

            log.info(f"  [{region}] done → {len(region_hits)} tooltips")
            all_raw.extend(region_hits)

        # ── 6. Parse & report ──────────────────────────────────────────────
        data = {}
        for text in all_raw:
            parsed = parse_tooltip(text)
            if parsed:
                region, date, value = parsed
                data.setdefault(date, {})[region] = value

        if not data:
            log.warning("No data extracted.")
            context.close(); browser.close()
            return {}

        sorted_dates = sorted(data.keys(), key=lambda d: datetime.strptime(d, "%m/%d/%Y"))
        n_ok = sum(1 for d in sorted_dates if all(r in data[d] for r in ['East','West','Gulf']))

        log.info(f"\n{'='*60}")
        log.info(f"RESULTS  {len(sorted_dates)} dates  |  {n_ok} complete")
        log.info(f"Range    {sorted_dates[0]} → {sorted_dates[-1]}")
        log.info(f"{'='*60}")
        for dt in sorted_dates:
            e   = data[dt].get('East', '?')
            w_v = data[dt].get('West', '?')
            g   = data[dt].get('Gulf', '?')
            miss = [r for r in ['East','West','Gulf'] if r not in data[dt]]
            log.info(f"  {dt:12s}  E={str(e):>3}  W={str(w_v):>3}  G={str(g):>3}  "
                     f"{'OK' if not miss else 'MISS:' + ','.join(miss)}")

        # ── 7. Save CSV ────────────────────────────────────────────────────
        with open(out_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Date','East','West','Gulf','Status'])
            for dt in sorted_dates:
                miss = [r for r in ['East','West','Gulf'] if r not in data[dt]]
                writer.writerow([
                    dt,
                    data[dt].get('East',''),
                    data[dt].get('West',''),
                    data[dt].get('Gulf',''),
                    'COMPLETE' if not miss else f'MISSING:{",".join(miss)}'
                ])
        log.info(f"Saved → {out_file}")

        input("\nPress ENTER to close browser...")
        context.close()
        browser.close()
        return data


if __name__ == "__main__":
    run(x_start=580, x_end=740, out_file="test_pw_results.csv")
