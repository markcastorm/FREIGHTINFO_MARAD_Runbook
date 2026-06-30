# FREIGHTINFO_MARAD Runbook — CLAUDE.md

Complete technical reference for the automated weekly pipeline that extracts
containership anchoring data from the BTS Tableau chart.

---

## Project Purpose

The Bureau of Transportation Statistics (BTS) publishes weekly counts of
containerships anchored off U.S. ports at:

    https://www.bts.gov/freight-indicators#anchored-offshore

The chart ("Number of Containerships Anchored off U.S. Ports") shows three
series — **East Coast**, **West Coast**, and **Gulf of Mexico** — updated
weekly. BTS provides no direct data download; all data lives inside an embedded
Tableau iframe. This pipeline automates the full extraction-to-delivery cycle
every week.

---

## Directory Structure

```
FREIGHTINFO_MARAD_Runbook/
│
├── orchestrator.py          ← Entry point — runs the 5-step pipeline
├── scraper.py               ← Playwright browser automation + pixel scan
├── parser.py                ← CSV parsing, week mapping, master management
├── file_generator.py        ← XLSX DATA, XLSX META, ZIP output generation
├── config.py                ← All configuration constants
├── logger_setup.py          ← Dual file+console logging setup
├── requirements.txt         ← pip dependencies
├── week_mapping.json        ← Cached date→week-code lookup (auto-refreshed)
│
├── Master_Data/
│   └── Master_FREIGHTINFO_MARAD_DATA.csv   ← Running history (source of truth)
│
├── output/
│   ├── latest/              ← Most recent run's output files (overwritten each run)
│   └── YYYYMMDD_HHMMSS/    ← Timestamped copy of every run's output
│
├── downloads/
│   └── YYYYMMDD_HHMMSS/
│       └── Scanned_Chart_Data.csv   ← Raw scan result saved before parsing
│
├── logs/
│   └── YYYYMMDD_HHMMSS/
│       └── freightinfo_marad_YYYYMMDD_HHMMSS.log
│
└── Project_information/
    ├── CLAUDE.md            ← (legacy, superseded by root CLAUDE.md)
    ├── FREIGHTINFO_MARAD_DATA_20260623 - DATA.csv  ← Reference/validated dataset
    └── tests/               ← Historical test and exploration scripts (not production)
```

---

## How to Run

```bash
python orchestrator.py
```

Runs the full 5-step pipeline. Typically takes 60–90 seconds total — most of
that is waiting for the Tableau iframe to render (~15 s) and the pixel scan
itself (~30–40 s for an incremental run).

**First run** (empty master): full historical scan, x=5→740, covers all data
since Jan 2021.

**Subsequent runs** (master exists): incremental scan, x=640→740, with early
exit per region as soon as old dates are encountered (see Scan Strategy below).

---

## 5-Step Pipeline

### Step 1 — Check Master Data (`parser.get_last_master_week`)

Reads `Master_Data/Master_FREIGHTINFO_MARAD_DATA.csv` and finds the last
week code (e.g., `2026-26`). This is the baseline: the pipeline will only
append weeks that come **after** this.

If the master is missing or empty, all subsequent steps run in full-history
mode.

### Step 2 — Fetch/Verify Week Mapping (`scraper.fetch_week_data`)

Downloads ISO week calendars from `epochconverter.com` for the current year
and the next two years, then saves them to `week_mapping.json`. On subsequent
runs the cache is reused as long as the current year's data is present.

The mapping provides `{week: N, from: YYYY-MM-DD, to: YYYY-MM-DD}` entries
used in Step 4 to convert raw tooltip dates (e.g., `6/23/2026`) into week
codes (e.g., `2026-26`).

### Step 3 — Scrape BTS Tableau Chart (`scraper.fetch_chart_data`)

This is the core step. Full detail in **Scan Strategy** below.

Returns either:
- A path to the downloaded `Scanned_Chart_Data.csv`
- `"NO_NEW_DATA"` if all captured dates are already in the master
- `None` if the scrape failed

When `last_date` is provided (master is not empty), only dates strictly after
`last_date` are kept. The scraper also applies early-exit per region to avoid
scanning data that is already in the master.

### Step 4 — Parse & Update Master

**`parser.parse_downloaded_csv`** reads the UTF-16 tab-delimited CSV written
by the scraper and produces:
```python
{"6/23/2026": {"East": 5, "West": 1, "Gulf": 2}, ...}
```

**`parser.map_dates_to_weeks`** converts each date to a week code using the
cached `week_mapping.json`:
```python
{"2026-26": {"East": 5, "West": 1, "Gulf": 2}, ...}
```

**`parser.update_master`** appends only weeks strictly after the master's
last week (`week_code > last_master_week` via string comparison — safe because
all codes are zero-padded `YYYY-WW`). The master is re-sorted and saved.

### Step 5 — Generate Output Files (`file_generator.generate_files`)

Produces three files in `output/YYYYMMDD_HHMMSS/` and copies them to
`output/latest/`:

| File | Contents |
|------|----------|
| `FREIGHTINFO_MARAD_DATA_YYYYMMDD.xlsx` | All master rows as a spreadsheet |
| `FREIGHTINFO_MARAD_META_YYYYMMDD.xlsx` | Static metadata for each series |
| `FREIGHTINFO_MARAD_YYYYMMDD.zip` | ZIP containing both XLSX files |

---

## Scan Strategy (The Hard Part)

Tableau embeds the chart inside an iframe with no public API. All data is
rendered onto an HTML `<canvas>` element. The pipeline extracts data by
controlling the browser with Playwright and reading pixel colors + tooltip text.

### Why Three Passes

The chart has three overlapping line series (East, West, Gulf). When all three
are visible at once, their lines cross and the Tableau voronoi hit-detection
fires for whichever data point is geometrically nearest to the cursor — not
necessarily the one you want.

**Solution**: Tableau's legend has a "Highlight Selected Items" button. When
active, clicking a legend item dims the other two series to ~30% saturation
while the selected series stays vivid (~65–73% saturation). The pipeline runs
three separate passes, one per region, exploiting this contrast.

### Pixel Saturation Detection (`_FIND_LINE_JS`)

For each x column in the scan range, JavaScript reads the canvas pixel data
(`getImageData`) and scans top-to-bottom looking for the highest-saturation
pixel in that column. The highlighted line's pixel has saturation > 0.15;
background, axes, and dimmed lines are all below this threshold.

```
threshold: saturation > 0.15 AND luma < 230
```

When a qualifying pixel is found, the mouse is moved to exactly that
`(abs_x, canvas_y)` coordinate so Tableau fires the tooltip.

### Tooltip Polling (`_POLL_JS`)

After each mouse move, JavaScript polls three Tableau tooltip selectors:
`.tab-tooltip`, `.tab-beautified-tooltip`, `.tab-glass-content`. The first one
that contains the word "Vessels" is returned. The tooltip text is then parsed
with regex to extract:

- `Port Region:` → East / West / Gulf
- `Date:` → M/D/YYYY
- `# of Vessels:` → integer count

### Right-to-Left Scan with Early Exit

The scan runs **right-to-left** (newest data first, x=740→640). For each
region pass, two sets are maintained:

- `found_target`: all dates for which the correct-region tooltip was obtained
- `new_target_dates`: subset of `found_target` where date > `last_date`

**Early-exit rule**: once `new_target_dates` is non-empty AND the next
correct-region tooltip shows a date ≤ `last_date`, break the x-loop for that
region. This means an incremental run only scans the handful of pixels
corresponding to genuinely new weeks, rather than a fixed historical window.

Example with master at `2026-24` (cutoff = June 14):
```
x=709 → East=5, date=6/23/2026  (new)  → new_target_dates = {6/23}
x=705 → East=2, date=6/9/2026   (old)  → early exit ✓  (scanned only 5 pixels)
```

### Hunt Logic (Cross-Region Voronoi Contamination)

Even with one region highlighted, at certain x positions the voronoi fires for
a different region because the other series' data point marker is geometrically
closer to the cursor. When this happens the pipeline "hunts" ±30 px vertically:

```python
for dy in range(1, 31):
    for sign in (1, -1):
        test_y = y + dy * sign
        move mouse to (abs_x, test_y)
        poll tooltip
        if tooltip is for target region → record and break
```

The hunt captures the correct-region value for dates that would otherwise be
missed due to overlapping voronoi zones.

### Null-Column Fallback (test_pixel_scan.py only)

At some x positions, the highlighted line's pixel is anti-aliased below the
0.15 saturation threshold, so `_FIND_LINE_JS` returns null. The production
scraper skips these columns (the hunt logic in adjacent columns usually
captures the date anyway via Tableau's voronoi). A null-column fallback (coarse
y-sweep at step=30px) exists in `Project_information/tests/test_pixel_scan.py`
but has not been promoted to production because its benefit is marginal and it
occasionally causes regressions by pre-consuming `region_seen` slots.

---

## Master Data Format

`Master_Data/Master_FREIGHTINFO_MARAD_DATA.csv` is a plain UTF-8 CSV:

```
,USA.CONTAINERSHIP_PORT_REGION_EAST.W,USA.CONTAINERSHIP_PORT_REGION_WEST.W,USA.CONTAINERSHIP_PORT_REGION_GULF.W
,USA.Containership port region East,USA.Containership port region West,USA.Containership port region Gulf
2025-01,16,3,4
2025-02,11,5,3
...
2026-26,5,1,2
```

- **Row 1**: column codes (machine-readable identifiers)
- **Row 2**: column descriptions (human-readable labels)
- **Rows 3+**: one row per ISO week, format `YYYY-WW,East,West,Gulf`

Week codes are zero-padded (e.g., `2026-05` not `2026-5`) so string
comparison correctly orders weeks within and across years.

Gaps in week numbering are normal — BTS does not publish data for every week
(e.g., weeks 2025-41 through 2025-46 are absent from the chart).

Empty cells (e.g., `2026-13,6,,2`) mean that region's value was not captured
for that week. This can happen when the pixel scan misses one of the three
passes for a date.

---

## Configuration (`config.py`)

| Constant | Value | Purpose |
|----------|-------|---------|
| `BASE_URL` | bts.gov/freight-indicators#anchored-offshore | Chart page URL |
| `TABLEAU_IFRAME_KEYWORD` | `ContainershipsAnchored` | Used to identify the Tableau iframe among all frames |
| `CHART_X_END` | 740 | Rightmost canvas pixel (latest data point) |
| `CHART_X_START_FULL` | 5 | Left edge for full-history scan (empty master) |
| `CHART_X_START_RECENT` | 640 | Left edge backstop for incremental scan |
| `HEADLESS_MODE` | False | Set True to run browser without a visible window |
| `MAX_SCAN_UNIQUE_DATES` | 52 | Safety cap on unique dates per scan |
| `CONTINUE_ON_ERROR` | True | If True, pipeline generates output from existing master even when scrape fails |
| `YEARS_TO_CACHE` | 3 | How many years of week mappings to cache (current + 2) |

### Canvas X-Pixel Geometry

The Tableau canvas is approximately 744 px wide. The chart data starts around
January 2021 (x≈5) and extends to the latest published week (x≈740). The
spacing is approximately **2.6–2.7 pixels per week**, but this shifts slightly
as new data is added to the right edge.

Known reference points (measured empirically):
- `x=594` ≈ Aug 26, 2025
- `x=640` ≈ Dec 2025 (incremental scan backstop)
- `x=709` ≈ Jun 23, 2026
- `x=740` = right edge (latest week)

---

## Anti-Bot / Anti-Detection

The Playwright browser context is configured to avoid Tableau's bot checks:

- `--disable-blink-features=AutomationControlled` launch arg
- `navigator.webdriver = undefined` via `add_init_script`
- Realistic `user-agent`, `sec-ch-ua`, and `Accept-Language` headers
- `viewport`: 1440×900, locale `en-US`, timezone `America/New_York`
- `slow_mo=20` to avoid unnaturally fast interactions
- 15-second wait after iframe load before any interaction

---

## Key Data Flow

```
orchestrator.py
    │
    ├─ parser.get_last_master_week()   → "2026-26" (or None)
    ├─ scraper.fetch_week_data()       → week_mapping.json (cached)
    ├─ parser.load_week_mapping()
    ├─ parser.get_last_data_date()     → datetime(2026, 6, 28)  [end of week 26]
    │
    ├─ scraper.fetch_chart_data(last_date=datetime(2026,6,28))
    │       │
    │       ├─ Playwright: load bts.gov, find Tableau iframe
    │       ├─ Wait 15s for render
    │       ├─ Find largest canvas + bounding box
    │       ├─ Enable legend highlight mode (aria-pressed=true)
    │       │
    │       └─ _pixel_scan(x_start=640, x_end=740, last_date=...)
    │               │
    │               ├─ Pass 1 (East):  highlight East → scan right→left → early exit
    │               ├─ Pass 2 (West):  highlight West → scan right→left → early exit
    │               └─ Pass 3 (Gulf):  highlight Gulf → scan right→left → early exit
    │               │
    │               └─ merge all_raw → {date: {East, West, Gulf}}
    │       │
    │       ├─ post-filter: keep only dates > last_date
    │       └─ _save_csv() → downloads/TIMESTAMP/Scanned_Chart_Data.csv
    │
    ├─ parser.parse_downloaded_csv()   → {"6/30/2026": {"East":3,"West":1,"Gulf":2}}
    ├─ parser.map_dates_to_weeks()     → {"2026-27": {"East":3,"West":1,"Gulf":2}}
    ├─ parser.update_master()          → appends only weeks > "2026-26", saves CSV
    │
    └─ file_generator.generate_files() → DATA.xlsx, META.xlsx, ZIP → output/latest/
```

---

## Scanned CSV Format (Internal)

`downloads/TIMESTAMP/Scanned_Chart_Data.csv` is written by `_save_csv()` in
UTF-16 encoding (required by `parse_downloaded_csv`). Format:

```
Scanned Data
Week	Tooltip	Indicator	Value
6/30/2026	6/30/2026	East	3
6/30/2026	6/30/2026	West	1
6/30/2026	6/30/2026	Gulf	2
```

Tab-delimited. Column B (Tooltip) is the date string used by the parser.
Column C is East/West/Gulf. Column D is the vessel count integer.

---

## Dependencies

```
requests>=2.31.0       # HTTP client for epochconverter.com week data
beautifulsoup4>=4.12.0 # HTML parsing for week table extraction
playwright>=1.40.0     # Headless/headed browser automation
openpyxl>=3.1.0        # XLSX file generation
```

Install with:
```bash
pip install -r requirements.txt
playwright install chromium
```

---

## Known Limitations & Accuracy

The pixel scan achieves approximately **93–97% accuracy** across all
date-region combinations in a typical full-history scan.

**Root causes of occasional misses:**

1. **Anti-aliased pixels**: At a small number of x positions, the highlighted
   line's pixel is anti-aliased below the 0.15 saturation threshold.
   `_FIND_LINE_JS` returns null and the column is skipped. Adjacent columns'
   hunt logic usually recovers the value anyway.

2. **Voronoi zone competition**: When two series have very similar y-values at
   a given x, the "wrong" series' voronoi zone extends over the pixel. The hunt
   logic (±30 px vertical sweep) recovers most of these.

3. **Rendering variance**: Tableau's exact canvas pixel layout shifts slightly
   between page loads (sub-pixel font rendering, DPI scale). A date captured
   cleanly on one run may be at a slightly different pixel on the next.

**Incremental accuracy**: For the typical weekly case (1–2 new weeks), the scan
is highly reliable because the new data points are at the far right of the
chart where lines are well-separated and anti-aliasing is minimal.

---

## Week Mapping Logic

BTS Tableau tooltips show a specific calendar date (e.g., `6/23/2026`) which
is the Monday or Tuesday of the week. The pipeline maps this to an ISO week
code using `epochconverter.com`'s week calendar.

`date_to_week_code("6/23/2026")` searches `week_mapping.json` for a week
entry where `from ≤ 2026-06-23 ≤ to`, returning `"2026-26"`.

The cache covers the current year and next two years. As of 2026, it covers
2026, 2027, and 2028. The cache is refreshed automatically when a run detects
the current year is not in the file.

---

## Typical Weekly Workflow

1. BTS publishes new week data (usually Tuesday morning)
2. Run `python orchestrator.py`
3. Pipeline detects last master week, calculates cutoff date
4. Scraper opens browser, loads chart, runs 3-pass pixel scan
5. Each pass exits immediately after crossing into already-known dates
6. New week(s) appended to master, output files generated in `output/latest/`
7. Deliver `output/latest/FREIGHTINFO_MARAD_YYYYMMDD.zip`

If BTS has not yet updated the chart, the scraper returns `"NO_NEW_DATA"` and
output files are regenerated from the existing master without modifying it.
