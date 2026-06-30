"""
FREIGHTINFO_MARAD Runbook - Orchestrator
Main entry point: 5-step pipeline for weekly containership data collection.
"""

import os
import sys
import time
import logging
import shutil

import config
from logger_setup import setup_logging
from scraper import FREIGHTINFOScraper
from parser import FREIGHTINFOParser
from file_generator import FREIGHTINFOFileGenerator

logger = logging.getLogger(__name__)


def print_banner():
    print()
    print('=' * 70)
    print(' FREIGHTINFO_MARAD - Freight Information Maritime Administration')
    print(' Number of Containerships Anchored off U.S. Ports (Weekly)')
    print('=' * 70)
    print()


def print_configuration():
    print('Configuration:')
    print('-' * 70)
    print(f'  Source URL:    {config.BASE_URL}')
    print(f'  Week Source:   {config.WEEK_URL_TEMPLATE.format(year="[current+2]")}')
    print(f'  Master Data:   {config.MASTER_DATA_FILE}')
    print(f'  Output Dir:    {config.OUTPUT_DIR}')
    print(f'  Downloads Dir: {config.DOWNLOADS_DIR}')
    print(f'  Timestamp:     {config.RUN_TIMESTAMP}')
    print(f'  Browser Mode:  {"Selenium" if config.USE_BROWSER else "HTTP"}')
    print(f'  Headless:      {config.HEADLESS_MODE}')
    print('-' * 70)
    print()


def main():
    """Execute the 5-step pipeline."""
    log_file = setup_logging()
    print_banner()
    print_configuration()

    scraper = FREIGHTINFOScraper()
    parser = FREIGHTINFOParser()
    generator = FREIGHTINFOFileGenerator()

    # =========================================================================
    # STEP 1: Check Master Data
    # =========================================================================
    print()
    logger.info('=' * 70)
    logger.info('STEP 1: Checking Master Data')
    logger.info('=' * 70)

    last_week = parser.get_last_master_week()
    if last_week:
        logger.info(f"Last week in master: {last_week}")
    else:
        logger.info("Master is empty or missing - will create fresh")

    # =========================================================================
    # STEP 2: Fetch/Verify Week Mapping
    # =========================================================================
    print()
    logger.info('=' * 70)
    logger.info('STEP 2: Fetching Week Mapping Data')
    logger.info('=' * 70)

    if not scraper.fetch_week_data():
        logger.error("Failed to fetch week mapping data")
        if not config.CONTINUE_ON_ERROR:
            return 1

    if not parser.load_week_mapping():
        logger.error("Failed to load week mapping")
        return 1

    # =========================================================================
    # STEP 3: Fetch Chart Data from BTS Tableau (with retries)
    # =========================================================================
    print()
    logger.info('=' * 70)
    logger.info('STEP 3: Fetching Chart Data from BTS')
    logger.info('=' * 70)

    last_date = parser.get_last_data_date()

    csv_path = None
    for attempt in range(1, config.MAX_SCRAPER_ATTEMPTS + 1):
        if attempt > 1:
            logger.info(
                f"Waiting {config.RETRY_DELAY_SECONDS}s before retry "
                f"(attempt {attempt}/{config.MAX_SCRAPER_ATTEMPTS}) ..."
            )
            time.sleep(config.RETRY_DELAY_SECONDS)
        csv_path = scraper.fetch_chart_data(last_date=last_date)
        if csv_path is not None:
            break
        logger.warning(f"Attempt {attempt} failed")

    if csv_path == "NO_NEW_DATA":
        logger.info("Scraper confirmed no new data points on the website.")
        logger.info("Master data is already up to date.")
        # Still generate output from existing master
        header_lines, data_rows = parser.load_master_data()
        if header_lines and data_rows:
            logger.info("Generating output from current master data...")
            output_files = generator.generate_files(header_lines, data_rows)
            _print_summary(data_rows, output_files)
            return 0
        return 0

    if not csv_path:
        logger.warning("No CSV data downloaded from BTS")
        # Still generate output from existing master if available
        header_lines, data_rows = parser.load_master_data()
        if header_lines and data_rows:
            logger.info("Generating output from existing master data...")
            output_files = generator.generate_files(header_lines, data_rows)
            _print_summary(data_rows, output_files)
            return 0
        else:
            logger.error("No master data available and no new data downloaded")
            return 1

    # =========================================================================
    # STEP 4: Parse CSV & Update Master
    # =========================================================================
    print()
    logger.info('=' * 70)
    logger.info('STEP 4: Parsing Data & Updating Master')
    logger.info('=' * 70)

    # Parse the downloaded CSV
    parsed_data = parser.parse_downloaded_csv(csv_path)
    if not parsed_data:
        logger.error("Failed to parse downloaded CSV")
        return 1

    # Map dates to week codes
    week_data = parser.map_dates_to_weeks(parsed_data)
    if not week_data:
        logger.error("Failed to map dates to weeks")
        return 1

    # Update master with new weeks
    header_lines, data_rows = parser.update_master(week_data)
    if header_lines is None:
        logger.error("Failed to update master data")
        return 1

    # =========================================================================
    # STEP 5: Generate Output Files
    # =========================================================================
    print()
    logger.info('=' * 70)
    logger.info('STEP 5: Generating Output Files')
    logger.info('=' * 70)

    output_files = generator.generate_files(header_lines, data_rows)
    _print_summary(data_rows, output_files)
    _prune_old_runs()

    return 0


def _print_summary(data_rows, output_files):
    """Print execution summary."""
    print()
    logger.info('=' * 70)
    logger.info('EXECUTION SUMMARY')
    logger.info('=' * 70)
    logger.info(f"  Master data rows: {len(data_rows)}")
    if data_rows:
        logger.info(f"  Date range: {data_rows[0][0]} to {data_rows[-1][0]}")
    logger.info(f"  Output files:")
    for file_type, filepath in output_files.items():
        if filepath:
            logger.info(f"    {file_type}: {filepath}")
    logger.info('=' * 70)


def _prune_old_runs():
    """
    Remove the oldest timestamped run directories from logs/, downloads/, and output/,
    keeping only the most recent MAX_KEEP_RUNS entries. Skips 'latest/' in output/.
    Does nothing if MAX_KEEP_RUNS is 0.
    """
    if not config.MAX_KEEP_RUNS:
        return

    dirs_to_prune = [
        config.LOG_DIR.rsplit(os.sep, 1)[0],       # .../logs/
        config.DOWNLOADS_DIR.rsplit(os.sep, 1)[0],  # .../downloads/
        config.OUTPUT_DIR.rsplit(os.sep, 1)[0],     # .../output/
    ]

    for parent in dirs_to_prune:
        if not os.path.isdir(parent):
            continue
        # Collect timestamped dirs (numeric names like 20260630_143845), skip 'latest'
        entries = sorted([
            e for e in os.listdir(parent)
            if os.path.isdir(os.path.join(parent, e)) and e != 'latest'
        ])
        to_delete = entries[:-config.MAX_KEEP_RUNS] if len(entries) > config.MAX_KEEP_RUNS else []
        for name in to_delete:
            path = os.path.join(parent, name)
            try:
                shutil.rmtree(path)
                logger.debug(f"Pruned old run dir: {path}")
            except Exception as e:
                logger.warning(f"Could not prune {path}: {e}")

    if any(os.path.isdir(d.rsplit(os.sep, 1)[0]) for d in dirs_to_prune):
        logger.info(f"Run history pruned — kept last {config.MAX_KEEP_RUNS} runs")


if __name__ == '__main__':
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)
