"""
FREIGHTINFO_MARAD Runbook - Orchestrator
Main entry point: 5-step pipeline for weekly containership data collection.
"""

import sys
import logging

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
    # STEP 3: Fetch Chart Data from BTS Tableau
    # =========================================================================
    print()
    logger.info('=' * 70)
    logger.info('STEP 3: Fetching Chart Data from BTS')
    logger.info('=' * 70)

    csv_path = scraper.fetch_chart_data()

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
