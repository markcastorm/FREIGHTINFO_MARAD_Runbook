"""
test_pixel_scan.py
──────────────────
Uses canvas.getImageData() to locate the HIGHLIGHTED line at each x position,
then hovers exactly on it. No y-guessing needed.

How it works:
  When East is highlighted → East line = vivid/saturated color, West+Gulf = grey
  When West is highlighted → West = vivid, East+Gulf = grey
  When Gulf is highlighted → Gulf = vivid, East+West = grey

  For each x column we read all pixels with JS getImageData(), find the pixel
  with highest colour saturation (= the highlighted line), then move the mouse
  exactly to that (x, y).  One hover per x → one tooltip per week.

Install (once):
    pip install playwright
    playwright install chromium

Run:
    python test_pixel_scan.py
"""

import os, re, csv, logging, time
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Logging ───────────────────────────────────────────────────────────────────
_RUN_TS  = datetime.now().strftime('%Y%m%d_%H%M%S')
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'logs', f'pixel_{_RUN_TS}')
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, f'pixel_{_RUN_TS}.log')

_fmt  = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
_root = logging.getLogger(); _root.setLevel(logging.INFO); _root.handlers.clear()
for h in [logging.FileHandler(_LOG_FILE, encoding='utf-8'), logging.StreamHandler()]:
    h.setFormatter(_fmt); _root.addHandler(h)

log = logging.getLogger(__name__)
log.info(f"Log → {_LOG_FILE}")

# ── Constants ─────────────────────────────────────────────────────────────────
BASE_URL   = "https://www.bts.gov/freight-indicators#anchored-offshore"
IFRAME_KEY = 'ContainershipsAnchored'

# ── JS: find the most-saturated pixel in column x of the main canvas ──────────
# Returns {y, r, g, b, sat} of the highlighted line pixel, or null if not found.
FIND_LINE_JS = """
(colX) => {
    // grab the largest canvas (the chart canvas)
    var best = null, bestArea = 0;
    document.querySelectorAll('canvas').forEach(function(c) {
        var a = c.width * c.height;
        if (a > bestArea) { bestArea = a; best = c; }
    });
    if (!best) return null;

    var ctx = best.getContext('2d');
    if (!ctx) return null;

    // read one pixel column
    var h    = best.height;
    var data = ctx.getImageData(colX, 0, 1, h).data;  // RGBA * h

    var bestY = -1, bestSat = -1, bestR = 0, bestG = 0, bestB = 0;

    for (var y = 5; y < h - 5; y++) {
        var i = y * 4;
        var r = data[i], g = data[i+1], b = data[i+2], a = data[i+3];

        if (a < 80) continue;          // transparent → skip

        // saturation in HSV sense: (max-min)/max
        var mx = Math.max(r, g, b);
        var mn = Math.min(r, g, b);
        if (mx === 0) continue;

        var sat  = (mx - mn) / mx;
        var luma = (r * 299 + g * 587 + b * 114) / 1000;

        // must be coloured (sat > 0.15) and not near-white background (luma < 230)
        if (sat > 0.15 && luma < 230 && sat > bestSat) {
            bestSat = sat; bestY = y; bestR = r; bestG = g; bestB = b;
        }
    }

    if (bestY < 0) return null;
    return { y: bestY, r: bestR, g: bestG, b: bestB, sat: Math.round(bestSat * 100) };
}
"""

# ── JS: poll tooltip ──────────────────────────────────────────────────────────
POLL_JS = """
() => {
    var sels = ['.tab-tooltip', '.tab-beautified-tooltip', '.tab-glass-content'];
    for (var s of sels) {
        var el = document.querySelector(s);
        if (el && el.innerText && el.innerText.includes('Vessels')) {
            return el.innerText.trim();
        }
    }
    return null;
}
"""

# ── Parser ────────────────────────────────────────────────────────────────────
def parse_tooltip(text):
    r = re.search(r'Port Region:\s*(East|West|Gulf)', text, re.I)
    d = re.search(r'Date:\s*(\d{1,2}/\d{1,2}/\d{4})', text)
    v = re.search(r'#\s*of\s*Vessels:\s*(\d+)', text)
    if r and d and v:
        return r.group(1).strip(), d.group(1).strip(), int(v.group(1))
    return None

# ── Browser setup ─────────────────────────────────────────────────────────────
def make_browser(p):
    browser = p.chromium.launch(
        headless=False,
        slow_mo=20,
        args=['--disable-blink-features=AutomationControlled', '--no-sandbox',
              '--disable-features=IsolateOrigins,site-per-process']
    )
    context = browser.new_context(
        viewport={'width': 1440, 'height': 900},
        locale='en-US',
        timezone_id='America/New_York',
        user_agent=('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/149.0.0.0 Safari/537.36'),
        extra_http_headers={
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'sec-ch-ua': '"Google Chrome";v="149", "Chromium";v="149", "Not?A_Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
        }
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins',   { get: () => [1,2,3,4,5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });
        window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {}, app: {} };
    """)
    return browser, context

# ── Main ─────────────────────────────────────────────────────────────────────
def run(x_start=580, x_end=740, out_file="test_pixel_results.csv"):
    log.info("=" * 60)
    log.info(f"PIXEL SCAN  x={x_start}→{x_end}  (pixel-exact line tracking)")
    log.info("=" * 60)

    with sync_playwright() as p:
        browser, context = make_browser(p)
        page = context.new_page()

        # ── Load page ─────────────────────────────────────────────────────
        log.info(f"Navigating → {BASE_URL}")
        page.goto(BASE_URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(6000)

        try:
            page.click('a[href="#anchored-offshore"]', timeout=5000)
            page.wait_for_timeout(3000)
        except PWTimeout:
            page.evaluate("window.location.hash='anchored-offshore'")
            page.wait_for_timeout(2000)

        # ── Find iframe ───────────────────────────────────────────────────
        log.info("Searching for Tableau iframe ...")
        frame = None
        for _ in range(25):
            for f in page.frames:
                if IFRAME_KEY in f.url:
                    frame = f
                    log.info(f"  Frame: {f.url[:100]}")
                    break
            if frame: break
            page.evaluate("window.scrollBy(0, 300)")
            page.wait_for_timeout(800)

        if not frame:
            log.error("Iframe not found"); context.close(); browser.close(); return {}

        page.locator(f'iframe[src*="{IFRAME_KEY}"]').first.scroll_into_view_if_needed()
        log.info("Waiting 15 s for Tableau to render ...")
        page.wait_for_timeout(15000)

        # ── Verify frame loaded ───────────────────────────────────────────
        info = frame.evaluate("""() => ({
            title:   document.title,
            denied:  document.body.innerText.includes('Access Denied'),
            canvases: Array.from(document.querySelectorAll('canvas'))
                         .map(c => ({ w: c.width, h: c.height, cls: c.className.substring(0,40) }))
        })""")
        log.info(f"Frame: {info}")
        if info.get('denied'):
            log.error("ACCESS DENIED in iframe"); context.close(); browser.close(); return {}

        # ── Find canvas bounding box (page coords) ────────────────────────
        canvas_el = None
        box = None
        for sel in ['.tab-tvView canvas', '.tabCanvas', 'canvas']:
            for el in reversed(frame.locator(sel).all()):
                b = el.bounding_box()
                if b and b['width'] > 200 and b['height'] > 100:
                    canvas_el = el; box = b; break
            if canvas_el: break

        if not canvas_el:
            log.error("Canvas not found"); input("ENTER"); context.close(); browser.close(); return {}

        log.info(f"Canvas: page_x={box['x']:.0f} page_y={box['y']:.0f} "
                 f"w={box['width']:.0f} h={box['height']:.0f}")

        # ── Enable highlight mode ─────────────────────────────────────────
        log.info("Enabling highlight mode ...")
        canvas_el.hover()
        page.wait_for_timeout(500)

        try:
            frame.locator('.tabLegendPanel').first.hover(timeout=5000)
            page.wait_for_timeout(400)
        except PWTimeout:
            pass

        # Force controls visible
        frame.evaluate("""() => {
            var c = document.querySelector('.tabLegendTitleControls');
            if (c) { c.style.opacity='1'; c.style.pointerEvents='auto'; c.style.visibility='visible'; }
        }""")
        page.wait_for_timeout(200)

        try:
            btn = frame.locator('.tabLegendHighlighterButton').first
            btn.hover(timeout=3000)
            page.wait_for_timeout(200)
            btn.click(timeout=3000)
            page.wait_for_timeout(600)
            log.info(f"  Highlight btn aria-pressed={btn.get_attribute('aria-pressed')}")
        except PWTimeout as e:
            log.warning(f"  Could not click highlight button: {e}")

        # ── Three-pass pixel scan ─────────────────────────────────────────
        frame.evaluate("window.captured=[]; window._seen=new Set();")
        all_raw = []

        for region in ['East', 'West', 'Gulf']:
            log.info(f"\n{'─'*50}\nREGION: {region}\n{'─'*50}")

            # Select region in legend
            try:
                item = frame.locator('.tabLegendItem').filter(has_text=region).first
                item.hover(timeout=5000)
                page.wait_for_timeout(300)
                item.click(timeout=5000)
                page.wait_for_timeout(1500)
                log.info(f"  Legend item '{region}' → aria-selected={item.get_attribute('aria-selected')}")
            except PWTimeout as e:
                log.warning(f"  Could not select '{region}': {e}"); continue

            region_hits = []
            region_seen = set()     # dedup within this region pass only
            found_target = set()    # dates for which we captured the target region
            missed = 0
            canvas_h = int(box['height'])

            x_values = list(range(x_end, x_start - 1, -1))  # right→left, step 1
            log.info(f"  Scanning {len(x_values)} columns (pixel-exact y tracking)...")

            for x in x_values:
                pixel = frame.evaluate(FIND_LINE_JS, x)
                if not pixel:
                    # No line pixel found — canvas is anti-aliased / empty at this column.
                    # Tableau's voronoi tooltip still fires for the nearest data point,
                    # so sweep y in coarse steps to capture any new date for this region.
                    abs_x = box['x'] + x
                    for test_y in range(10, canvas_h - 5, 30):
                        page.mouse.move(abs_x, box['y'] + test_y)
                        page.wait_for_timeout(15)
                        fb = frame.evaluate(POLL_JS)
                        if fb and fb not in region_seen:
                            region_seen.add(fb)
                            fparsed = parse_tooltip(fb)
                            if fparsed:
                                freg, fdt, fval = fparsed
                                region_hits.append(fb)
                                log.info(f"  [{region}] NULL_FB x={x} y={test_y}"
                                         f"  →  {fdt} {freg}={fval}")
                                if freg == region:
                                    found_target.add(fdt)
                    missed += 1
                    continue

                y = pixel['y']
                abs_x = box['x'] + x

                page.mouse.move(abs_x, box['y'] + y)
                page.wait_for_timeout(35)

                result = frame.evaluate(POLL_JS)
                if result and result not in region_seen:
                    region_seen.add(result)
                    parsed = parse_tooltip(result)
                    if parsed:
                        reg_found, dt, val = parsed
                        region_hits.append(result)
                        log.info(f"  [{region}] x={x} y={y} rgb=({pixel['r']},{pixel['g']},{pixel['b']}) "
                                 f"sat={pixel['sat']}%  →  {dt} {reg_found}={val}")

                        if reg_found == region:
                            found_target.add(dt)
                        elif dt not in found_target:
                            # Tooltip fired for wrong region — the marker for the target
                            # region is somewhere else at this x; hunt ±30 px vertically.
                            hunted = False
                            for dy in range(1, 31):
                                for sign in (1, -1):
                                    test_y = y + dy * sign
                                    if not (5 <= test_y < canvas_h - 5):
                                        continue
                                    page.mouse.move(abs_x, box['y'] + test_y)
                                    page.wait_for_timeout(20)
                                    retry = frame.evaluate(POLL_JS)
                                    if retry and retry not in region_seen:
                                        region_seen.add(retry)
                                        rparsed = parse_tooltip(retry)
                                        if rparsed:
                                            rreg, rdt, rval = rparsed
                                            region_hits.append(retry)
                                            log.info(f"  [{region}] HUNT  x={x} y={test_y}"
                                                     f"  →  {rdt} {rreg}={rval}")
                                            if rreg == region:
                                                found_target.add(rdt)
                                                hunted = True
                                if hunted:
                                    break

            log.info(f"  [{region}] done: {len(region_hits)} hits | {missed} columns no line found")
            all_raw.extend(region_hits)

        # ── Parse & merge ─────────────────────────────────────────────────
        data = {}
        for text in all_raw:
            parsed = parse_tooltip(text)
            if parsed:
                reg, dt, val = parsed
                data.setdefault(dt, {})[reg] = val

        if not data:
            log.warning("No data. Try widening x_start/x_end or check highlight worked.")
            context.close(); browser.close(); return {}

        sorted_dates = sorted(data.keys(), key=lambda d: datetime.strptime(d, "%m/%d/%Y"))
        n_ok = sum(1 for d in sorted_dates if all(r in data[d] for r in ['East','West','Gulf']))

        log.info(f"\n{'='*60}")
        log.info(f"RESULTS  {len(sorted_dates)} dates  |  {n_ok} fully complete")
        log.info(f"Range    {sorted_dates[0]}  →  {sorted_dates[-1]}")
        log.info(f"{'='*60}")
        for dt in sorted_dates:
            e   = data[dt].get('East', '?')
            wv  = data[dt].get('West', '?')
            g   = data[dt].get('Gulf', '?')
            miss = [r for r in ['East','West','Gulf'] if r not in data[dt]]
            log.info(f"  {dt:12s}  E={str(e):>3}  W={str(wv):>3}  G={str(g):>3}  "
                     f"{'OK' if not miss else 'MISS:' + ','.join(miss)}")

        # ── Save CSV ──────────────────────────────────────────────────────
        with open(out_file, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['Date','East','West','Gulf','Status'])
            for dt in sorted_dates:
                miss = [r for r in ['East','West','Gulf'] if r not in data[dt]]
                w.writerow([dt,
                            data[dt].get('East',''), data[dt].get('West',''), data[dt].get('Gulf',''),
                            'COMPLETE' if not miss else f'MISSING:{",".join(miss)}'])
        log.info(f"Saved → {out_file}")

        page.wait_for_timeout(1500)
        context.close(); browser.close()
        return data


if __name__ == "__main__":
    run(x_start=580, x_end=740, out_file="test_pixel_results.csv")
