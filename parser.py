"""
FREIGHTINFO_MARAD Runbook - Parser
Parses the Tableau CSV export, maps dates to ISO weeks,
and manages incremental master CSV updates.
"""

import os
import json
import logging
from datetime import datetime

import config

logger = logging.getLogger(__name__)


class FREIGHTINFOParser:

    def __init__(self):
        self.week_mapping = None

    # =========================================================================
    # WEEK MAPPING
    # =========================================================================

    def load_week_mapping(self):
        """Load the week mapping JSON and build a date-to-week lookup."""
        if not os.path.exists(config.WEEK_CACHE_FILE):
            logger.error(f"Week mapping file not found: {config.WEEK_CACHE_FILE}")
            return False

        try:
            with open(config.WEEK_CACHE_FILE, 'r') as f:
                self.week_mapping = json.load(f)

            total_weeks = sum(len(weeks) for weeks in self.week_mapping.values())
            logger.info(f"Loaded week mapping: {len(self.week_mapping)} years, {total_weeks} weeks total")
            return True

        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load week mapping: {e}")
            return False

    def date_to_week_code(self, date_str):
        """
        Convert a date string to YYYY-WW week code using the cached mapping.
        date_str can be in M/D/YYYY or MM/DD/YYYY format.
        Returns e.g., "2026-08" or None if not found.
        """
        if not self.week_mapping:
            logger.error("Week mapping not loaded")
            return None

        # Parse the date
        try:
            date_obj = datetime.strptime(date_str.strip(), '%m/%d/%Y')
        except ValueError:
            try:
                date_obj = datetime.strptime(date_str.strip(), '%m/%d/%y')
            except ValueError:
                logger.warning(f"Could not parse date: {date_str}")
                return None

        date_iso = date_obj.strftime('%Y-%m-%d')

        # Search through all years in the mapping
        for year_str, weeks in self.week_mapping.items():
            for week_entry in weeks:
                if week_entry['from'] <= date_iso <= week_entry['to']:
                    week_num = week_entry['week']
                    # Use the year from the week entry's 'from' or 'to' date
                    # that matches the target year
                    week_code = f"{year_str}-{week_num:02d}"
                    return week_code

        # Fallback: try Python's isocalendar for dates outside cached range
        iso_year, iso_week, _ = date_obj.isocalendar()
        week_code = f"{iso_year}-{iso_week:02d}"
        logger.warning(f"Date {date_str} not found in cache, using isocalendar: {week_code}")
        return week_code

    # =========================================================================
    # CSV PARSING
    # =========================================================================

    def parse_downloaded_csv(self, csv_path):
        """
        Parse the Tableau crosstab CSV export.

        The CSV is UTF-16 encoded, tab-delimited with structure:
        Row 1: Header with "Date" labels for each date column
        Row 2: "Current Date - Week", "Date Week Tool Tip", "Indicator breakout", year headers...
        Rows 3+: Data rows - 3 rows per date (West, East, Gulf)
                 Each row has exactly ONE non-empty value in columns D+.

        Returns: {date_str: {"East": val, "West": val, "Gulf": val}} or None
        """
        logger.info(f"Parsing downloaded CSV: {csv_path}")

        try:
            # Try UTF-16 first (Tableau default), then UTF-8 as fallback
            content = None
            for encoding in ['utf-16', 'utf-16-le', 'utf-8-sig', 'utf-8']:
                try:
                    with open(csv_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    logger.info(f"  Successfully read CSV with encoding: {encoding}")
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue

            if content is None:
                logger.error("Failed to read CSV with any encoding")
                return None

            lines = content.strip().split('\n')
            if len(lines) < 3:
                logger.error(f"CSV has too few lines: {len(lines)}")
                return None

            logger.info(f"  CSV has {len(lines)} lines")

            # Parse data rows (skip first 2 header rows)
            parsed_data = {}
            skipped = 0

            for i, line in enumerate(lines[2:], start=3):
                fields = line.split('\t')

                if len(fields) < 4:
                    skipped += 1
                    continue

                # Column A: Current Date - Week (e.g., "2/17/2026")
                # Column B: Date Week Tool Tip (e.g., "07/27/2021")
                # Column C: Indicator breakout (e.g., "West", "East", "Gulf")
                date_tool_tip = fields[1].strip()
                indicator = fields[2].strip()

                if not date_tool_tip or not indicator:
                    skipped += 1
                    continue

                # Validate indicator is one of our expected regions
                if indicator not in config.REGION_TO_COLUMN:
                    skipped += 1
                    continue

                # Find the non-empty value in columns D onwards
                value = None
                for field in fields[3:]:
                    field = field.strip()
                    if field:
                        try:
                            value = int(float(field))
                            break
                        except (ValueError, TypeError):
                            continue

                if value is None:
                    skipped += 1
                    continue

                # Build the data structure grouped by date
                if date_tool_tip not in parsed_data:
                    parsed_data[date_tool_tip] = {}

                parsed_data[date_tool_tip][indicator] = value

            logger.info(f"  Parsed {len(parsed_data)} unique dates ({skipped} rows skipped)")

            # Log a few sample entries
            dates_sorted = sorted(parsed_data.keys(),
                                  key=lambda d: datetime.strptime(d.strip(), '%m/%d/%Y'))
            if dates_sorted:
                latest_3 = dates_sorted[-3:]
                for d in latest_3:
                    logger.debug(f"    {d}: {parsed_data[d]}")

            return parsed_data

        except Exception as e:
            logger.error(f"Error parsing CSV: {e}")
            return None

    # =========================================================================
    # WEEK MAPPING OF PARSED DATA
    # =========================================================================

    def map_dates_to_weeks(self, parsed_data):
        """
        Convert parsed date-keyed data to week-code-keyed data.

        Input:  {"07/27/2021": {"East": 22, "West": 38, "Gulf": 2}, ...}
        Output: {"2021-30": {"East": 22, "West": 38, "Gulf": 2}, ...}
        """
        if not parsed_data:
            return None

        week_data = {}
        unmapped = 0

        for date_str, values in parsed_data.items():
            week_code = self.date_to_week_code(date_str)
            if week_code is None:
                unmapped += 1
                continue

            # If multiple dates map to the same week, keep the latest one
            # (shouldn't happen since data is weekly snapshots)
            if week_code in week_data:
                logger.debug(f"  Duplicate week {week_code} for date {date_str}, overwriting")

            week_data[week_code] = values

        logger.info(f"Mapped {len(week_data)} weeks ({unmapped} dates unmapped)")
        return week_data

    # =========================================================================
    # MASTER DATA MANAGEMENT
    # =========================================================================

    def load_master_data(self):
        """
        Load the master CSV file preserving the 2-row header.
        Returns: (header_lines, data_rows) or (None, None)

        header_lines: list of 2 raw header line strings
        data_rows: list of lists [week_code, east_val, west_val, gulf_val]
        """
        if not os.path.exists(config.MASTER_DATA_FILE):
            logger.warning(f"Master file not found: {config.MASTER_DATA_FILE}")
            # Return default headers with empty data
            header1 = ',' + ','.join(config.OUTPUT_COLUMN_CODES)
            header2 = ',' + ','.join(config.OUTPUT_COLUMN_DESCRIPTIONS)
            return [header1, header2], []

        try:
            with open(config.MASTER_DATA_FILE, 'r', encoding='utf-8') as f:
                lines = f.read().strip().split('\n')

            if len(lines) < 2:
                logger.warning("Master file has fewer than 2 header lines")
                header1 = ',' + ','.join(config.OUTPUT_COLUMN_CODES)
                header2 = ',' + ','.join(config.OUTPUT_COLUMN_DESCRIPTIONS)
                return [header1, header2], []

            header_lines = lines[:2]
            data_rows = []

            for line in lines[2:]:
                parts = line.strip().split(',')
                if parts and parts[0]:
                    data_rows.append(parts)

            logger.info(f"Loaded master: {len(data_rows)} data rows")
            if data_rows:
                logger.info(f"  Date range: {data_rows[0][0]} to {data_rows[-1][0]}")

            return header_lines, data_rows

        except Exception as e:
            logger.error(f"Error loading master: {e}")
            return None, None

    def get_last_master_week(self):
        """Get the last week code from the master CSV."""
        header_lines, data_rows = self.load_master_data()
        if data_rows:
            return data_rows[-1][0]
        return None

    def get_last_data_date(self):
        """
        Returns the 'to' date of the last COMPLETE master week as the scrape cutoff.

        If the trailing rows have empty region cells (partial capture from a prior run),
        the cutoff is backed up to the last fully-complete row so those incomplete
        weeks are re-covered by the scan and their missing values can be backfilled.
        """
        _, data_rows = self.load_master_data()
        if not data_rows:
            return None

        if not self.week_mapping:
            self.load_week_mapping()
        if not self.week_mapping:
            return None

        # Find last row where all 3 region values are present
        n_cols = len(config.OUTPUT_COLUMN_CODES) + 1  # week_code + 3 regions
        last_complete_idx = len(data_rows) - 1
        while last_complete_idx >= 0:
            row = data_rows[last_complete_idx]
            padded = (row + [''] * n_cols)[:n_cols]
            if all(padded[i].strip() for i in range(1, n_cols)):
                break
            last_complete_idx -= 1

        if last_complete_idx < 0:
            return None  # no complete rows at all — trigger full scan

        incomplete_count = len(data_rows) - 1 - last_complete_idx
        if incomplete_count > 0:
            logger.info(
                f"Last {incomplete_count} master row(s) have empty cells — "
                f"cutoff backed up so they are re-scanned and backfilled"
            )

        last_complete_week = data_rows[last_complete_idx][0]
        try:
            year_str, week_num_str = last_complete_week.split('-')
            week_num = int(week_num_str)
            for w in self.week_mapping.get(year_str, []):
                if w['week'] == week_num:
                    return datetime.strptime(w['to'], '%Y-%m-%d')
        except Exception as e:
            logger.debug(f"Could not determine last data date: {e}")

        return None

    def save_master_data(self, header_lines, data_rows):
        """Save master CSV with 2-row headers and data."""
        os.makedirs(config.MASTER_DATA_DIR, exist_ok=True)

        try:
            with open(config.MASTER_DATA_FILE, 'w', encoding='utf-8', newline='') as f:
                # Write header lines
                for header in header_lines:
                    f.write(header.rstrip('\n') + '\n')

                # Write data rows
                for row in data_rows:
                    # Pad row to match column count if needed
                    while len(row) < len(config.OUTPUT_COLUMN_CODES) + 1:
                        row.append('')
                    f.write(','.join(row[:len(config.OUTPUT_COLUMN_CODES) + 1]) + '\n')

            logger.info(f"Master saved: {len(data_rows)} rows -> {config.MASTER_DATA_FILE}")

        except Exception as e:
            logger.error(f"Error saving master: {e}")

    def update_master(self, week_data):
        """
        Update master CSV with new data from the scan.

        Two operations:
        1. BACKFILL — for weeks already in master with empty region cells,
           fill in any values that the latest scan captured for them.
        2. APPEND  — add weeks that appear after the master's last week.

        week_data: {"2026-26": {"East": 5, "West": 1, "Gulf": 2}, ...}
        Returns: (header_lines, data_rows) or (None, None)
        """
        if not week_data:
            logger.warning("No week data to update master with")
            return self.load_master_data()

        header_lines, data_rows = self.load_master_data()
        if header_lines is None:
            return None, None

        last_master_week = data_rows[-1][0] if data_rows else None
        if last_master_week:
            logger.info(f"Master's last week: {last_master_week}")
        else:
            logger.info("Master is empty, will add all downloaded data")

        # Build index so we can find existing rows in O(1)
        row_index = {row[0]: i for i, row in enumerate(data_rows)}

        # Build a reverse lookup: column code → region name
        col_to_region = {v: k for k, v in config.REGION_TO_COLUMN.items()}

        new_rows = []
        backfill_count = 0

        for week_code, values in week_data.items():
            if week_code in row_index:
                # Week already exists — backfill any empty region cells
                row = data_rows[row_index[week_code]]
                filled = []
                for col_pos, col_code in enumerate(config.OUTPUT_COLUMN_CODES, start=1):
                    region = col_to_region.get(col_code)
                    if region and region in values:
                        while len(row) <= col_pos:
                            row.append('')
                        if not row[col_pos].strip():
                            row[col_pos] = str(values[region])
                            filled.append(f"{region}={values[region]}")
                if filled:
                    backfill_count += 1
                    logger.info(f"  Backfilled {week_code}: {', '.join(filled)}")

            elif last_master_week is None or week_code > last_master_week:
                # Genuinely new week — append
                row = [week_code]
                for col_code in config.OUTPUT_COLUMN_CODES:
                    region = col_to_region.get(col_code)
                    row.append(str(values[region]) if region and region in values else '')
                new_rows.append(row)
            # else: old week already complete — skip

        if backfill_count:
            logger.info(f"Backfilled {backfill_count} incomplete week(s) in master")

        if not new_rows and not backfill_count:
            logger.info("No new or incomplete weeks to update")
            return header_lines, data_rows

        if new_rows:
            logger.info(f"Adding {len(new_rows)} new week(s) to master:")
            for row in new_rows:
                east = row[1] if len(row) > 1 else ''
                west = row[2] if len(row) > 2 else ''
                gulf = row[3] if len(row) > 3 else ''
                logger.info(f"  {row[0]}: East={east}, West={west}, Gulf={gulf}")

        all_rows = data_rows + new_rows
        all_rows.sort(key=lambda r: r[0] if r else '')
        self.save_master_data(header_lines, all_rows)

        return header_lines, all_rows
