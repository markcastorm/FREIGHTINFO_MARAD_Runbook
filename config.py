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
YEARS_TO_CACHE = 3  # Pre-fetch 3 years of week data

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
# Column Mapping (must match master CSV exactly)
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

# Map region names from downloaded CSV to column codes
REGION_TO_COLUMN = {
    'East': 'USA.CONTAINERSHIP_PORT_REGION_EAST.W',
    'West': 'USA.CONTAINERSHIP_PORT_REGION_WEST.W',
    'Gulf': 'USA.CONTAINERSHIP_PORT_REGION_GULF.W',
}

# =============================================================================
# Selenium / Browser Configuration
# =============================================================================
USE_BROWSER = True
HEADLESS_MODE = False
WAIT_TIMEOUT = 60
PAGE_LOAD_DELAY = 5

# Tableau iframe identification
TABLEAU_IFRAME_KEYWORD = 'ContainershipsAnchored'  # URL fragment to identify the correct iframe

# Tableau element selectors
TABLEAU_TITLE_SELECTOR = 'h2.tab-tvTitle'
TABLEAU_TITLE_TEXT = 'Number of Containerships Anchored off U.S. Ports'
DOWNLOAD_BUTTON_SELECTOR = '[data-tb-test-id="viz-viewer-toolbar-button-download"]'
CROSSTAB_MENU_ITEM_SELECTOR = '[data-tb-test-id="download-flyout-download-crosstab-MenuItem"]'
CSV_RADIO_SELECTOR = '[data-tb-test-id="crosstab-options-dialog-radio-csv-RadioButton"]'
CSV_RADIO_LABEL_SELECTOR = '[data-tb-test-id="crosstab-options-dialog-radio-csv-Label"]'
EXPORT_BUTTON_SELECTOR = '[data-tb-test-id="export-crosstab-export-Button"]'
LOADING_SPINNER_SELECTOR = '#loadingSpinner'

# =============================================================================
# HTTP Configuration (for week data scraping)
# =============================================================================
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 5.0

# =============================================================================
# File Naming Patterns
# =============================================================================
DATASET_NAME = 'FREIGHTINFO_MARAD'
DATA_FILE_PATTERN = f'FREIGHTINFO_MARAD_DATA_{RUN_DATE}.xls'
META_FILE_PATTERN = f'FREIGHTINFO_MARAD_META_{RUN_DATE}.xls'
ZIP_FILE_PATTERN = f'FREIGHTINFO_MARAD_{RUN_DATE}.zip'
LOG_FILE_PATTERN = f'freightinfo_marad_{RUN_TIMESTAMP}.log'

# =============================================================================
# Logging Configuration
# =============================================================================
DEBUG_MODE = True
LOG_LEVEL = 'DEBUG' if DEBUG_MODE else 'INFO'
LOG_TO_CONSOLE = True
LOG_TO_FILE = True

# =============================================================================
# Processing
# =============================================================================
CONTINUE_ON_ERROR = True

# =============================================================================
# Metadata Configuration (17 columns matching NOAADDF_A pattern)
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
