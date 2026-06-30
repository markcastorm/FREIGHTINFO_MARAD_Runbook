# FREIGHTINFO_MARAD Runbook

Automated weekly pipeline that extracts containership anchoring data from the
BTS Tableau chart and delivers clean Excel output files.

---

## What It Does

The Bureau of Transportation Statistics (BTS) publishes weekly counts of
containerships anchored off U.S. ports at
`https://www.bts.gov/freight-indicators#anchored-offshore`.

The chart shows three series — **East Coast**, **West Coast**, and **Gulf of
Mexico** — updated weekly. Because BTS embeds the chart inside a Tableau
iframe with no download option, this pipeline:

1. Drives a real Chromium browser (headless) to load the chart
2. Uses pixel-color analysis on the HTML canvas to locate each data line
3. Reads Tableau's own tooltip text to capture vessel counts
4. Maps each date to its ISO week code and appends new weeks to a master CSV
5. Generates XLSX DATA + XLSX META + ZIP output files ready for delivery

---

## Output

Every run produces three files in `output/latest/`:

| File | Contents |
|------|----------|
| `FREIGHTINFO_MARAD_DATA_YYYYMMDD.xlsx` | Weekly vessel counts — East, West, Gulf |
| `FREIGHTINFO_MARAD_META_YYYYMMDD.xlsx` | Series metadata (code, description, units, source) |
| `FREIGHTINFO_MARAD_YYYYMMDD.zip` | Both XLSX files bundled for delivery |

Timestamped copies are also kept in `output/YYYYMMDD_HHMMSS/` for the last
14 runs (configurable).

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Run the pipeline

```bash
python orchestrator.py
```

On the first run (empty master) the pipeline performs a full historical scan
covering all data since January 2021. Every subsequent run is incremental —
it only scans far enough back to find weeks not yet in the master.

### 3. Deliver

Copy `output/latest/FREIGHTINFO_MARAD_YYYYMMDD.zip` to the destination.

---

## Daily Deployment

The pipeline is designed to run once per day via a scheduler (Windows Task
Scheduler, cron, or any CI runner).

**Typical daily behaviour:**

- **BTS has published new data** → new week(s) appended to master, fresh
  output files generated.
- **BTS has not yet updated the chart** → scraper detects no dates beyond the
  master cutoff, logs `NO_NEW_DATA`, and regenerates output from the existing
  master unchanged.
- **Transient network / Access Denied error** → pipeline retries up to 3 times
  (45-second gap between attempts). If all retries fail, output is regenerated
  from the existing master and the run exits cleanly with code 0.

BTS typically publishes Tuesday morning (Eastern time). Running the pipeline
daily at 10:00 ET ensures new data is captured on publication day.

### Windows Task Scheduler example

```
Program:   C:\Python311\python.exe
Arguments: orchestrator.py
Start in:  D:\Projects\SIMBA-RUNBOOKS\FREIGHTINFO_MARAD_Runbook
```

---

## Project Structure

```
FREIGHTINFO_MARAD_Runbook/
│
├── orchestrator.py          ← Entry point — 5-step pipeline
├── scraper.py               ← Playwright browser + canvas pixel scan
├── parser.py                ← CSV parsing, week mapping, master management
├── file_generator.py        ← XLSX DATA, XLSX META, ZIP generation
├── config.py                ← All tunable constants in one place
├── logger_setup.py          ← Dual file + console logging
├── requirements.txt         ← pip dependencies
├── week_mapping.json        ← Auto-generated date→week cache
│
├── Master_Data/
│   └── Master_FREIGHTINFO_MARAD_DATA.csv   ← Running history (source of truth)
│
├── output/
│   ├── latest/              ← Most recent output (overwritten each run)
│   └── YYYYMMDD_HHMMSS/    ← Per-run timestamped archive
│
├── downloads/
│   └── YYYYMMDD_HHMMSS/
│       └── Scanned_Chart_Data.csv   ← Raw scan result before parsing
│
├── logs/
│   └── YYYYMMDD_HHMMSS/
│       └── freightinfo_marad_YYYYMMDD_HHMMSS.log
│
├── CLAUDE.md                ← Full technical reference for AI-assisted development
│
└── Project_information/
    ├── FREIGHTINFO_MARAD_DATA_20260623 - DATA.csv  ← Validated reference dataset
    ├── FREIGHTINFO_MARAD_Runbook.docx               ← Original specification
    └── tests/               ← Historical test and exploration scripts
```

---

## Pipeline Steps

### Step 1 — Check Master Data

Reads `Master_Data/Master_FREIGHTINFO_MARAD_DATA.csv` to find the last week
code (e.g., `2026-26`). This becomes the baseline — only weeks strictly after
this are appended.

If the master is empty or missing, all steps run in full-history mode.

### Step 2 — Fetch Week Mapping

Downloads ISO week calendars from `epochconverter.com` for the current year
and the next two years, caches them in `week_mapping.json`. Used in Step 4 to
convert tooltip dates (`6/23/2026`) into week codes (`2026-26`).

The cache is reused on subsequent runs as long as the current year is present.

### Step 3 — Scrape BTS Tableau Chart

Opens the BTS page in a headless Chromium browser, waits for the Tableau
iframe to fully render, then runs a **three-pass pixel scan**:

For each region (East → West → Gulf):
1. Click the legend item to highlight that region's line (dims the other two)
2. Scan canvas columns right-to-left using `getImageData()` — the highlighted
   line has noticeably higher colour saturation than dimmed lines
3. Move the mouse to the vivid pixel; Tableau fires a tooltip with the date
   and vessel count
4. If Tableau's voronoi fires the wrong region's tooltip, hunt ±30 px
   vertically to find the target region's nearest marker
5. Stop scanning as soon as a confirmed old date is encountered after at least
   one new date has been collected (early exit — keeps incremental runs fast)

Retries up to 3 times on failure with a 45-second gap.

### Step 4 — Parse & Update Master

- Parses the UTF-16 tab-delimited CSV written by the scraper
- Maps each date to its ISO week code via the week mapping cache
- **Appends** new weeks to the master
- **Backfills** any existing master rows that have empty region cells (in case
  a prior run captured only partial data for a week)
- Saves the updated master, sorted by week code

### Step 5 — Generate Output Files

Creates `FREIGHTINFO_MARAD_DATA_*.xlsx`, `FREIGHTINFO_MARAD_META_*.xlsx`, and
`FREIGHTINFO_MARAD_*.zip` in a timestamped output directory, then copies all
three to `output/latest/`. Old run directories beyond the last 14 are
automatically pruned.

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

- Row 1: machine-readable column codes
- Row 2: human-readable column descriptions
- Rows 3+: `YYYY-WW,East,West,Gulf` — one row per ISO week

**Gaps in week numbers are expected.** BTS does not publish data every single
week (e.g., weeks 2025-41 through 2025-46 are absent). The pipeline preserves
these gaps rather than filling them with zeroes.

---

## Configuration

All tunable values are in `config.py`. The most commonly changed ones:

| Setting | Default | Notes |
|---------|---------|-------|
| `HEADLESS_MODE` | `True` | Set `False` to watch the browser during debugging |
| `MAX_SCRAPER_ATTEMPTS` | `3` | Retries on transient failure |
| `RETRY_DELAY_SECONDS` | `45` | Gap between retry attempts |
| `MAX_KEEP_RUNS` | `14` | Timestamped dirs retained; `0` keeps all |
| `CHART_X_END` | `740` | Rightmost canvas pixel (latest data point) |
| `CHART_X_START_RECENT` | `640` | Left-edge backstop for incremental scans |
| `CHART_X_START_FULL` | `5` | Left edge for full-history scan (empty master) |
| `CONTINUE_ON_ERROR` | `True` | Regenerate output from existing master if scrape fails |

---

## Logging

Every run writes a full log to `logs/YYYYMMDD_HHMMSS/freightinfo_marad_*.log`
and echoes the same output to the console.

Key log lines to look for:

```
Last week in master: 2026-26          ← Step 1 — baseline
fetch_chart_data: x=640→740           ← Step 3 — scan range
  [East] early exit at x=701          ← Scan stopped after finding all new data
Incremental: 1 new date(s) beyond ... ← How many new dates passed the filter
Adding 1 new week(s) to master:       ← Step 4 — what was written
  2026-27: East=3, West=1, Gulf=2     ← The actual values
Run history pruned — kept last 14 runs ← Step 5 — cleanup
```

If the scrape returns no data on attempt 1, you will see:

```
Attempt 1 failed
Waiting 45s before retry (attempt 2/3) ...
```

If all retries fail:

```
No CSV data downloaded from BTS
Generating output from existing master data...
```

The pipeline still exits 0 and delivers files from the existing master.

---

## Accuracy

The pixel scan reliably captures all three regions for the vast majority of
weeks. Occasional misses occur when:

- The highlighted line is anti-aliased below the colour-saturation threshold
  at a specific x position (the hunt logic in adjacent columns usually recovers
  the value)
- Two series overlap tightly at a data point and Tableau's voronoi zone fires
  the wrong region (the ±30 px vertical hunt resolves most of these)

Any week written to master with a missing region cell (e.g., `2026-27,3,1,`)
is automatically re-scanned on the next run and backfilled if the pixel scan
captures the missing value.

---

## Troubleshooting

**`Access Denied` inside Tableau iframe**
BTS's CDN occasionally blocks the first connection. The pipeline retries
automatically. If it fails consistently, try setting `HEADLESS_MODE = False`
in `config.py` and running manually to see the browser state.

**`Tableau iframe not found`**
The BTS page took too long to load or the iframe URL changed. Check
`config.TABLEAU_IFRAME_KEYWORD` matches the current embed URL.
Current expected pattern: `ContainershipsAnchored`

**`0 tooltips captured` for all regions**
Tableau rendered but the legend highlight button didn't activate. This is the
most common transient failure — the 45-second retry resolves it.

**New week not picked up after BTS publishes**
The scan's right edge is `CHART_X_END = 740`. If BTS ever widens the chart
canvas, new data points may appear beyond pixel 740. Check the log line:
`Canvas: page_x=... w=744` — if the width has grown, update `CHART_X_END`.

**Week mapping out of date**
Delete `week_mapping.json` to force a fresh download from epochconverter.com
on the next run.

---

## Dependencies

```
requests>=2.31.0       # HTTP for epochconverter.com week calendar
beautifulsoup4>=4.12.0 # HTML parsing of the week table
playwright>=1.40.0     # Headless Chromium browser automation
openpyxl>=3.1.0        # XLSX file generation
```

Install:
```bash
pip install -r requirements.txt
playwright install chromium
```

---

## Data Source

**Bureau of Transportation Statistics (BTS)**
U.S. Department of Transportation

- Chart: https://www.bts.gov/freight-indicators#anchored-offshore
- Series: Number of Containerships Anchored off U.S. Ports
- Regions: East Coast · West Coast · Gulf of Mexico
- Frequency: Weekly
- Unit: Vessel count
- Provider code prefix: `USA.CONTAINERSHIP_PORT_REGION_`
