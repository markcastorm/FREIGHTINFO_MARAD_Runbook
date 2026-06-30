"""
FREIGHTINFO_MARAD Runbook - Configuration
Centralized configuration for containership anchoring data pipeline.
"""

import os
from datetime import datetime

# =============================================================================
# Timestamps
# =============================================================================
RUN_TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')
RUN_DATE = datetime.now().strftime('%Y%m%d')

# =============================================================================
# Data Sources
# =============================================================================
BASE_URL = "https://www.bts.gov/freight-indicators#anchored-offshore"
WEEK_URL_TEMPLATE = "https://www.epochconverter.com/weeks/{year}"
YEARS_TO_CACHE = 3

# =============================================================================
# Project Directories
# =============================================================================
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
MASTER_DATA_DIR = os.path.join(PROJECT_ROOT, 'Master_Data')
MASTER_DATA_FILE = os.path.join(MASTER_DATA_DIR, 'Master_FREIGHTINFO_MARAD_DATA.csv')
WEEK_CACHE_FILE = os.path.join(PROJECT_ROOT, 'week_mapping.json')

DOWNLOADS_DIR = os.path.join(PROJECT_ROOT, 'downloads', RUN_TIMESTAMP)
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'output', RUN_TIMESTAMP)
LATEST_OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'output', 'latest')
LOG_DIR = os.path.join(PROJECT_ROOT, 'logs', RUN_TIMESTAMP)

# =============================================================================
# Column Mapping
# =============================================================================
OUTPUT_COLUMN_CODES = [
    'USA.CONTAINERSHIP_PORT_REGION_EAST.W',
    'USA.CONTAINERSHIP_PORT_REGION_WEST.W',
    'USA.CONTAINERSHIP_PORT_REGION_GULF.W',
]

OUTPUT_COLUMN_DESCRIPTIONS = [
    'USA.Containership port region East',
    'USA.Containership port region West',
    'USA.Containership port region Gulf',
]

REGION_TO_COLUMN = {
    'East': 'USA.CONTAINERSHIP_PORT_REGION_EAST.W',
    'West': 'USA.CONTAINERSHIP_PORT_REGION_WEST.W',
    'Gulf': 'USA.CONTAINERSHIP_PORT_REGION_GULF.W',
}

# =============================================================================
# Browser / Scraper Configuration
# =============================================================================
USE_BROWSER = True
HEADLESS_MODE = True          # False only for local debugging
WAIT_TIMEOUT = 30
PAGE_LOAD_DELAY = 3
TABLEAU_IFRAME_KEYWORD = 'ContainershipsAnchored'

# Scanning tuning
MAX_SCAN_UNIQUE_DATES = 52
MAX_SCRAPER_ATTEMPTS = 3      # retry on transient Access Denied / network errors
RETRY_DELAY_SECONDS = 45      # seconds to wait between retry attempts
CONTINUE_ON_ERROR = True

# Output retention — keep logs/downloads/output dirs for last N runs; 0 = keep all
MAX_KEEP_RUNS = 14

# Chart canvas x-pixel range for pixel-scan
# Each year ≈ 137 canvas pixels; x=5 is ~Jan 2021, x=740 is the latest data point.
CHART_X_END = 740           # Rightmost data pixel (latest week)
CHART_X_START_FULL = 5      # Full historical scan (all years)
CHART_X_START_RECENT = 640  # Incremental scan backstop (~6 months)

# =============================================================================
# File Naming Patterns
# =============================================================================
DATASET_NAME = 'FREIGHTINFO_MARAD'
DATA_FILE_PATTERN = f'FREIGHTINFO_MARAD_DATA_{RUN_DATE}.xlsx'
META_FILE_PATTERN = f'FREIGHTINFO_MARAD_META_{RUN_DATE}.xlsx'
ZIP_FILE_PATTERN = f'FREIGHTINFO_MARAD_{RUN_DATE}.zip'
LOG_FILE_PATTERN = f'freightinfo_marad_{RUN_TIMESTAMP}.log'

# =============================================================================
# Logging
# =============================================================================
DEBUG_MODE = True
LOG_LEVEL = 'DEBUG' if DEBUG_MODE else 'INFO'
LOG_TO_CONSOLE = True
LOG_TO_FILE = True

# =============================================================================
# Metadata
# =============================================================================
META_COLUMNS = [
    'CODE', 'CODE_MNEMONIC', 'DESCRIPTION', 'FREQUENCY', 'MULTIPLIER',
    'AGGREGATION_TYPE', 'UNIT_TYPE', 'DATA_TYPE', 'DATA_UNIT',
    'SEASONALLY_ADJUSTED', 'ANNUALIZED', 'PROVIDER_MEASURE_URL',
    'PROVIDER', 'SOURCE', 'SOURCE_DESCRIPTION', 'COUNTRY', 'DATASET'
]

META_ROWS = [
    {
        'CODE': 'USA.CONTAINERSHIP_PORT_REGION_EAST.W',
        'CODE_MNEMONIC': 'USA.CONTAINERSHIP_PORT_REGION_EAST.W',
        'DESCRIPTION': 'USA.Containership port region East',
        'FREQUENCY': 'W',
        'MULTIPLIER': '1',
        'AGGREGATION_TYPE': 'END_OF_PERIOD',
        'UNIT_TYPE': 'COUNT',
        'DATA_TYPE': 'STOCK',
        'DATA_UNIT': 'Vessels',
        'SEASONALLY_ADJUSTED': 'N',
        'ANNUALIZED': 'N',
        'PROVIDER_MEASURE_URL': BASE_URL,
        'PROVIDER': 'BTS',
        'SOURCE': 'Bureau of Transportation Statistics',
        'SOURCE_DESCRIPTION': 'Number of Containerships Anchored off U.S. Ports - East Coast',
        'COUNTRY': 'USA',
        'DATASET': DATASET_NAME,
    },
    {
        'CODE': 'USA.CONTAINERSHIP_PORT_REGION_WEST.W',
        'CODE_MNEMONIC': 'USA.CONTAINERSHIP_PORT_REGION_WEST.W',
        'DESCRIPTION': 'USA.Containership port region West',
        'FREQUENCY': 'W',
        'MULTIPLIER': '1',
        'AGGREGATION_TYPE': 'END_OF_PERIOD',
        'UNIT_TYPE': 'COUNT',
        'DATA_TYPE': 'STOCK',
        'DATA_UNIT': 'Vessels',
        'SEASONALLY_ADJUSTED': 'N',
        'ANNUALIZED': 'N',
        'PROVIDER_MEASURE_URL': BASE_URL,
        'PROVIDER': 'BTS',
        'SOURCE': 'Bureau of Transportation Statistics',
        'SOURCE_DESCRIPTION': 'Number of Containerships Anchored off U.S. Ports - West Coast',
        'COUNTRY': 'USA',
        'DATASET': DATASET_NAME,
    },
    {
        'CODE': 'USA.CONTAINERSHIP_PORT_REGION_GULF.W',
        'CODE_MNEMONIC': 'USA.CONTAINERSHIP_PORT_REGION_GULF.W',
        'DESCRIPTION': 'USA.Containership port region Gulf',
        'FREQUENCY': 'W',
        'MULTIPLIER': '1',
        'AGGREGATION_TYPE': 'END_OF_PERIOD',
        'UNIT_TYPE': 'COUNT',
        'DATA_TYPE': 'STOCK',
        'DATA_UNIT': 'Vessels',
        'SEASONALLY_ADJUSTED': 'N',
        'ANNUALIZED': 'N',
        'PROVIDER_MEASURE_URL': BASE_URL,
        'PROVIDER': 'BTS',
        'SOURCE': 'Bureau of Transportation Statistics',
        'SOURCE_DESCRIPTION': 'Number of Containerships Anchored off U.S. Ports - Gulf of Mexico',
        'COUNTRY': 'USA',
        'DATASET': DATASET_NAME,
    },
]
