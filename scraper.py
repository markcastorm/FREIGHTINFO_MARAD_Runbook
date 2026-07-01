"""
FREIGHTINFO_MARAD Runbook - Scraper
Extracts weekly vessel count data via Playwright pixel-scan of the BTS Tableau chart.

Strategy: Tableau "Highlight Selected Items" legend button is activated so only
one region's line is vivid (high colour saturation) at a time. For each x column
canvas.getImageData() finds the highest-saturation pixel (= highlighted line) and
the mouse is moved exactly there. Three passes (East / West / Gulf) give clean,
region-specific tooltips without any y-position guessing.
"""

import os
import re
import json
import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import config

logger = logging.getLogger(__name__)

# ── JS: find highest-saturation pixel in canvas column x (= highlighted line) ──
_FIND_LINE_JS = """
(colX) => {
    var best = null, bestArea = 0;
    document.querySelectorAll('canvas').forEach(function(c) {
        var a = c.width * c.height;
        if (a > bestArea) { bestArea = a; best = c; }
    });
    if (!best) return null;
    var ctx = best.getContext('2d');
    if (!ctx) return null;
    var h = best.height;
    var data = ctx.getImageData(colX, 0, 1, h).data;
    var bestY = -1, bestSat = -1, bestR = 0, bestG = 0, bestB = 0;
    for (var y = 5; y < h - 5; y++) {
        var i = y * 4;
        var r = data[i], g = data[i+1], b = data[i+2], a = data[i+3];
        if (a < 80) continue;
        var mx = Math.max(r, g, b), mn = Math.min(r, g, b);
        if (mx === 0) continue;
        var sat  = (mx - mn) / mx;
        var luma = (r * 299 + g * 587 + b * 114) / 1000;
        if (sat > 0.15 && luma < 230 && sat > bestSat) {
            bestSat = sat; bestY = y; bestR = r; bestG = g; bestB = b;
        }
    }
    if (bestY < 0) return null;
    return { y: bestY, r: bestR, g: bestG, b: bestB, sat: Math.round(bestSat * 100) };
}
"""

# ── JS: poll tooltip for vessel data ──────────────────────────────────────────
_POLL_JS = """
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


class FREIGHTINFOScraper:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

    # =========================================================================
    # WEEK MAPPING (epochconverter.com)
    # =========================================================================

    def fetch_week_data(self):
        """Fetch and cache week mapping data."""
        if os.path.exists(config.WEEK_CACHE_FILE):
            try:
                with open(config.WEEK_CACHE_FILE, 'r') as f:
                    data = json.load(f)
                # Require all three years to be present — this catches the case
                # where the cache was built in a prior year and is now missing
                # current+1 or current+2 (needed for late-year ISO week mapping).
                yr = datetime.now().year
                if all(str(yr + i) in data for i in range(3)):
                    logger.info("Using cached week mapping data")
                    return True
                logger.info("Week mapping cache is stale — refreshing ...")
            except Exception:
                pass

        logger.info("Fetching week mapping data from epochconverter.com...")
        current_year = datetime.now().year
        years = [current_year, current_year + 1, current_year + 2]
        week_data = {}

        for year in years:
            url = config.WEEK_URL_TEMPLATE.format(year=year)
            try:
                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, 'html.parser')
                table = soup.find('table', class_='infotable')
                if not table:
                    continue
                weeks = []
                for row in table.find('tbody').find_all('tr'):
                    cells = row.find_all('td')
                    if len(cells) < 3:
                        continue
                    try:
                        wk_match = re.match(r'Week\s+(\d+)', cells[0].get_text(strip=True))
                        if not wk_match:
                            continue
                        wk_num = int(wk_match.group(1))
                        f_date = datetime.strptime(
                            cells[1].get_text(separator=' ', strip=True), '%B %d, %Y'
                        ).strftime('%Y-%m-%d')
                        t_date = datetime.strptime(
                            cells[2].get_text(separator=' ', strip=True), '%B %d, %Y'
                        ).strftime('%Y-%m-%d')
                        weeks.append({'week': wk_num, 'from': f_date, 'to': t_date})
                    except Exception:
                        continue
                if weeks:
                    week_data[str(year)] = weeks
            except Exception as e:
                logger.warning(f"Failed to fetch week data for {year}: {e}")

        if week_data:
            with open(config.WEEK_CACHE_FILE, 'w') as f:
                json.dump(week_data, f, indent=2)
            return True
        return False

    # =========================================================================
    # BROWSER SETUP (Playwright)
    # =========================================================================

    def _make_browser(self, p):
        """Launch Playwright Chromium with anti-detection settings."""
        browser = p.chromium.launch(
            headless=config.HEADLESS_MODE,
            slow_mo=20,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
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

    # =========================================================================
    # TOOLTIP PARSING
    # =========================================================================

    def _parse_tooltip(self, text):
        """Parse tooltip text → (region, date_str, value) or None."""
        r = re.search(r'Port Region:\s*(East|West|Gulf)', text, re.I)
        d = re.search(r'Date:\s*(\d{1,2}/\d{1,2}/\d{4})', text)
        v = re.search(r'#\s*of\s*Vessels:\s*(\d+)', text)
        if r and d and v:
            return r.group(1).strip(), d.group(1).strip(), int(v.group(1))
        return None

    # =========================================================================
    # THREE-PASS PIXEL SCAN
    # =========================================================================

    def _pixel_scan(self, page, frame, box, x_start, x_end, last_date=None):
        """
        Highlight each region in turn and scan the chart pixel-by-pixel (right→left).

        For each x column, getImageData() identifies the vivid (high-saturation)
        pixel which is the highlighted line; the mouse moves exactly there and
        the tooltip is read. Per-region dedup prevents duplicate date entries.

        When last_date is provided, each region pass exits as soon as we've collected
        at least one new date AND the target-region tooltip crosses into already-known
        territory (date ≤ last_date). This keeps incremental runs to the minimum
        necessary x range rather than always scanning a fixed historical window.

        Returns: {date_str: {"East": val, "West": val, "Gulf": val}}
        """
        all_raw = []

        for region in ['East', 'West', 'Gulf']:
            logger.info(f"  Region pass: {region}")

            # Select this region in the legend — Playwright click first, JS fallback.
            # Headless Chromium can time out on hover/click for iframe elements even
            # when they are visible; the JS click bypasses coordinate translation.
            item = frame.locator('.tabLegendItem').filter(has_text=region).first
            selected = False
            for method in ('playwright', 'js'):
                try:
                    if method == 'playwright':
                        item.scroll_into_view_if_needed(timeout=3000)
                        page.wait_for_timeout(200)
                        item.click(timeout=5000)
                    else:
                        frame.evaluate("""
                            (region) => {
                                for (var el of document.querySelectorAll('.tabLegendItem')) {
                                    if (el.textContent.includes(region)) { el.click(); break; }
                                }
                            }
                        """, region)
                    page.wait_for_timeout(1500)
                    selected = True
                    break
                except PWTimeout:
                    pass
            if not selected:
                logger.warning(f"  Could not select legend item '{region}' — skipping pass")
                continue
            logger.debug(f"  Legend '{region}' selected")

            region_seen = set()
            found_target = set()      # dates where we captured the correct target region
            new_target_dates = set()  # subset that are strictly after last_date
            hits = 0
            canvas_h = int(box['height'])
            exit_early = False        # set from inside hunt to break the outer x loop

            for x in range(x_end, x_start - 1, -1):
                if exit_early:
                    logger.debug(
                        f"    [{region}] early exit at x={x} "
                        f"(old target date found in hunt, {len(new_target_dates)} new collected)"
                    )
                    break

                pixel = frame.evaluate(_FIND_LINE_JS, x)
                if not pixel:
                    continue

                y = pixel['y']
                abs_x = box['x'] + x

                page.mouse.move(abs_x, box['y'] + y)
                page.wait_for_timeout(35)

                result = frame.evaluate(_POLL_JS)
                if result and result not in region_seen:
                    region_seen.add(result)
                    parsed = self._parse_tooltip(result)
                    if parsed:
                        reg_found, dt, val = parsed
                        all_raw.append(result)
                        hits += 1
                        logger.debug(f"    [{region}] x={x} {dt} {reg_found}={val}")

                        if reg_found == region:
                            found_target.add(dt)
                            if last_date:
                                try:
                                    dt_obj = datetime.strptime(dt, "%m/%d/%Y")
                                    if dt_obj > last_date:
                                        new_target_dates.add(dt)
                                    elif new_target_dates:
                                        logger.debug(
                                            f"    [{region}] early exit at x={x} "
                                            f"(crossed into old dates after "
                                            f"{len(new_target_dates)} new)"
                                        )
                                        break
                                except ValueError:
                                    pass

                        elif dt not in found_target:
                            # Tooltip fired for wrong region — hunt ±30 px vertically
                            # to find where the target region's marker actually fires.
                            hunted = False
                            for dy in range(1, 31):
                                for sign in (1, -1):
                                    test_y = y + dy * sign
                                    if not (5 <= test_y < canvas_h - 5):
                                        continue
                                    page.mouse.move(abs_x, box['y'] + test_y)
                                    page.wait_for_timeout(20)
                                    retry = frame.evaluate(_POLL_JS)
                                    if retry and retry not in region_seen:
                                        region_seen.add(retry)
                                        rparsed = self._parse_tooltip(retry)
                                        if rparsed:
                                            rreg, rdt, rval = rparsed
                                            all_raw.append(retry)
                                            hits += 1
                                            logger.debug(f"    [{region}] HUNT x={x}"
                                                         f" y={test_y} {rdt} {rreg}={rval}")
                                            if rreg == region:
                                                found_target.add(rdt)
                                                if last_date:
                                                    try:
                                                        rdt_obj = datetime.strptime(rdt, "%m/%d/%Y")
                                                        if rdt_obj > last_date:
                                                            new_target_dates.add(rdt)
                                                        elif new_target_dates:
                                                            # Old target date found in hunt
                                                            # after collecting new data —
                                                            # signal the outer loop to exit
                                                            exit_early = True
                                                    except ValueError:
                                                        pass
                                                hunted = True
                                if hunted or exit_early:
                                    break

            logger.info(
                f"    {region}: {hits} tooltips, {len(new_target_dates)} new dates"
                if last_date else f"    {region}: {hits} tooltips captured"
            )

        # Merge all three passes into {date: {region: value}}
        data = {}
        for text in all_raw:
            parsed = self._parse_tooltip(text)
            if parsed:
                reg, dt, val = parsed
                data.setdefault(dt, {})[reg] = val

        return data

    # =========================================================================
    # CSV OUTPUT (format expected by parser.parse_downloaded_csv)
    # =========================================================================

    def _save_csv(self, data, path):
        """Save scan results as UTF-16 tab-delimited file for the parser."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-16', newline='') as f:
            f.write("Scanned Data\r\nWeek\tTooltip\tIndicator\tValue\r\n")
            for ds in sorted(data.keys(), key=lambda x: datetime.strptime(x, "%m/%d/%Y")):
                for reg in ['East', 'West', 'Gulf']:
                    f.write(f"{ds}\t{ds}\t{reg}\t{data[ds].get(reg, '')}\r\n")

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def fetch_chart_data(self, last_date=None):
        """
        Load the BTS Tableau chart and extract vessel counts via pixel-scan.

        Args:
            last_date: datetime of the latest date already in master CSV.
                       None → full historical scan from x=CHART_X_START_FULL.
                       Provided → incremental scan from x=CHART_X_START_RECENT.

        Returns:
            str          — path to the saved CSV file
            "NO_NEW_DATA" — all captured dates are ≤ last_date
            None         — scrape failed
        """
        x_end   = config.CHART_X_END   # overridden below with dynamic canvas width
        x_start = config.CHART_X_START_RECENT if last_date else config.CHART_X_START_FULL
        logger.info(
            f"fetch_chart_data: x={x_start}→{x_end} "
            f"({'incremental' if last_date else 'full history'})"
        )

        data = None

        with sync_playwright() as p:
            browser, context = self._make_browser(p)
            page = context.new_page()

            try:
                # ── Load page ─────────────────────────────────────────────
                logger.info(f"Navigating → {config.BASE_URL}")
                page.goto(config.BASE_URL, wait_until='domcontentloaded', timeout=60000)
                page.wait_for_timeout(6000)

                try:
                    page.click('a[href="#anchored-offshore"]', timeout=5000)
                    page.wait_for_timeout(3000)
                except PWTimeout:
                    page.evaluate("window.location.hash='anchored-offshore'")
                    page.wait_for_timeout(2000)

                # ── Find iframe ───────────────────────────────────────────
                logger.info("Searching for Tableau iframe ...")
                frame = None
                for _ in range(25):
                    for f in page.frames:
                        if config.TABLEAU_IFRAME_KEYWORD in f.url:
                            frame = f
                            logger.info(f"  Found: {f.url[:80]}")
                            break
                    if frame:
                        break
                    page.evaluate("window.scrollBy(0, 300)")
                    page.wait_for_timeout(800)

                if not frame:
                    logger.error("Tableau iframe not found")
                    return None

                page.locator(f'iframe[src*="{config.TABLEAU_IFRAME_KEYWORD}"]').first \
                    .scroll_into_view_if_needed()
                logger.info("Waiting 15 s for Tableau to render ...")
                page.wait_for_timeout(15000)

                # ── Verify frame loaded ───────────────────────────────────
                info = frame.evaluate("""() => ({
                    denied:   document.body.innerText.includes('Access Denied'),
                    canvases: document.querySelectorAll('canvas').length
                })""")
                if info.get('denied'):
                    logger.error("Access Denied inside Tableau iframe")
                    return None
                logger.info(f"  Frame OK — {info['canvases']} canvas(es)")

                # ── Locate canvas bounding box ────────────────────────────
                canvas_el, box = None, None
                for sel in ['.tab-tvView canvas', '.tabCanvas', 'canvas']:
                    for el in reversed(frame.locator(sel).all()):
                        b = el.bounding_box()
                        if b and b['width'] > 200 and b['height'] > 100:
                            canvas_el, box = el, b
                            break
                    if canvas_el:
                        break

                if not canvas_el:
                    logger.error("Chart canvas not found in Tableau frame")
                    return None

                # Read the canvas's internal pixel width (not CSS width).
                # This becomes x_end for the scan so we always reach the true
                # rightmost data point regardless of chart size changes.
                canvas_px_w = frame.evaluate("""() => {
                    var best = null, bestArea = 0;
                    document.querySelectorAll('canvas').forEach(function(c) {
                        var a = c.width * c.height;
                        if (a > bestArea) { bestArea = a; best = c; }
                    });
                    return best ? best.width : 0;
                }""")
                x_end = (canvas_px_w - 5) if canvas_px_w > 200 else config.CHART_X_END
                logger.info(
                    f"Canvas: page_x={box['x']:.0f} page_y={box['y']:.0f} "
                    f"css_w={box['width']:.0f} h={box['height']:.0f} "
                    f"px_w={canvas_px_w} scan_to=x={x_end}"
                )

                # ── Enable legend highlight mode ───────────────────────────
                logger.info("Enabling legend highlight mode ...")
                canvas_el.hover()
                page.wait_for_timeout(500)

                try:
                    frame.locator('.tabLegendPanel').first.hover(timeout=5000)
                    page.wait_for_timeout(400)
                except PWTimeout:
                    pass

                # Force the controls visible so the highlight button is reachable
                frame.evaluate("""() => {
                    var c = document.querySelector('.tabLegendTitleControls');
                    if (c) {
                        c.style.opacity      = '1';
                        c.style.pointerEvents= 'auto';
                        c.style.visibility   = 'visible';
                    }
                }""")
                page.wait_for_timeout(200)

                # Activate highlight mode.
                # In headless Chromium, Playwright's hover can time out due to
                # iframe coordinate translation issues even when the element IS
                # visible. Fall back to a direct JS click which bypasses that.
                btn = frame.locator('.tabLegendHighlighterButton').first
                activated = False
                for method in ('playwright', 'js'):
                    try:
                        if method == 'playwright':
                            btn.scroll_into_view_if_needed(timeout=3000)
                            page.wait_for_timeout(200)
                            btn.click(timeout=5000)
                        else:
                            frame.evaluate(
                                "document.querySelector('.tabLegendHighlighterButton')?.click()"
                            )
                        page.wait_for_timeout(800)
                        if btn.get_attribute('aria-pressed') == 'true':
                            activated = True
                            break
                    except PWTimeout:
                        pass
                logger.info(
                    f"  Highlight btn: aria-pressed={btn.get_attribute('aria-pressed')}"
                    f" ({'OK' if activated else 'FAILED — continuing without highlight'})"
                )

                # ── Three-pass pixel scan ─────────────────────────────────
                data = self._pixel_scan(page, frame, box, x_start, x_end, last_date=last_date)

            except Exception as e:
                logger.error(f"Scrape error: {e}", exc_info=True)
                return None
            finally:
                try:
                    context.close()
                    browser.close()
                except Exception:
                    pass

        if not data:
            logger.warning("No data captured from chart")
            return None

        # ── Incremental filter ────────────────────────────────────────────
        if last_date:
            new_data = {
                dt: vals for dt, vals in data.items()
                if datetime.strptime(dt, "%m/%d/%Y") > last_date
            }
            if not new_data:
                logger.info("All captured dates are already in master — no new data")
                return "NO_NEW_DATA"
            logger.info(f"Incremental: {len(new_data)} new date(s) beyond {last_date.date()}")
            data = new_data

        logger.info(f"Captured {len(data)} date(s) for downstream processing")

        path = os.path.join(config.DOWNLOADS_DIR, 'Scanned_Chart_Data.csv')
        self._save_csv(data, path)
        logger.info(f"Saved → {path}")
        return path
