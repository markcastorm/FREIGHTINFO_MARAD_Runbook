"""
FREIGHTINFO_MARAD Runbook - Scraper
Handles two scraping tasks:
1. Week mapping from epochconverter.com (cached as JSON)
2. BTS Tableau chart data download via Selenium
"""

import os
import re
import json
import time
import glob
import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)


class FREIGHTINFOScraper:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.driver = None

    # =========================================================================
    # WEEK MAPPING (epochconverter.com)
    # =========================================================================

    def _needs_week_refresh(self):
        """Check if week_mapping.json needs to be refreshed."""
        if not os.path.exists(config.WEEK_CACHE_FILE):
            logger.info("Week mapping file not found, will fetch fresh data")
            return True

        try:
            with open(config.WEEK_CACHE_FILE, 'r') as f:
                data = json.load(f)

            current_year = datetime.now().year
            required_years = [str(current_year + i) for i in range(config.YEARS_TO_CACHE)]

            for year in required_years:
                if year not in data:
                    logger.info(f"Week mapping missing year {year}, will refresh")
                    return True

            logger.info("Week mapping cache is up to date")
            return False

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Week mapping file corrupted: {e}")
            return True

    def _parse_week_table(self, html_content, target_year):
        """Parse the week number table from epochconverter HTML."""
        soup = BeautifulSoup(html_content, 'html.parser')
        table = soup.find('table', class_='infotable')

        if not table:
            logger.error("Could not find week table in HTML")
            return None

        weeks = []
        rows = table.find('tbody').find_all('tr')

        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 3:
                continue

            week_text = cells[0].get_text(strip=True)
            from_text = cells[1].get_text(separator=' ', strip=True)
            to_text = cells[2].get_text(separator=' ', strip=True)

            # Parse week number: "Week 01" or "Week 52, 2025"
            week_match = re.match(r'Week\s+(\d+)', week_text)
            if not week_match:
                continue

            week_num = int(week_match.group(1))

            # Skip entries from other years (e.g., "Week 52, 2025" on the 2026 page)
            if ',' in week_text:
                other_year_match = re.search(r',\s*(\d{4})', week_text)
                if other_year_match and other_year_match.group(1) != str(target_year):
                    continue

            # Parse dates: "December 29, 2025" -> "2025-12-29"
            try:
                from_date = datetime.strptime(from_text, '%B %d, %Y').strftime('%Y-%m-%d')
                to_date = datetime.strptime(to_text, '%B %d, %Y').strftime('%Y-%m-%d')
            except ValueError as e:
                logger.warning(f"Could not parse date in week {week_num}: {e}")
                continue

            weeks.append({
                'week': week_num,
                'from': from_date,
                'to': to_date,
            })

        logger.info(f"  Parsed {len(weeks)} weeks for year {target_year}")
        return weeks

    def fetch_week_data(self):
        """Fetch and cache week mapping data from epochconverter.com."""
        if not self._needs_week_refresh():
            logger.info("Using cached week mapping data")
            return True

        logger.info("Fetching week mapping data from epochconverter.com...")

        current_year = datetime.now().year
        years_to_fetch = [current_year + i for i in range(config.YEARS_TO_CACHE)]

        week_data = {}

        # Load existing data if available (to preserve older years)
        if os.path.exists(config.WEEK_CACHE_FILE):
            try:
                with open(config.WEEK_CACHE_FILE, 'r') as f:
                    week_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                week_data = {}

        for year in years_to_fetch:
            url = config.WEEK_URL_TEMPLATE.format(year=year)
            logger.info(f"  Fetching week data for {year}: {url}")

            for attempt in range(1, config.MAX_RETRIES + 1):
                try:
                    response = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
                    response.raise_for_status()

                    weeks = self._parse_week_table(response.text, year)
                    if weeks:
                        week_data[str(year)] = weeks
                        break
                    else:
                        logger.warning(f"  No weeks parsed for {year}, attempt {attempt}")

                except requests.RequestException as e:
                    logger.warning(f"  Attempt {attempt}/{config.MAX_RETRIES} failed for {year}: {e}")
                    if attempt < config.MAX_RETRIES:
                        time.sleep(config.RETRY_DELAY)

        if not week_data:
            logger.error("Failed to fetch any week data")
            return False

        # Save to JSON cache
        with open(config.WEEK_CACHE_FILE, 'w') as f:
            json.dump(week_data, f, indent=2)

        logger.info(f"Week mapping saved: {len(week_data)} years cached")
        return True

    # =========================================================================
    # SELENIUM HELPERS
    # =========================================================================

    def get_chrome_version_from_registry(self):
        """Get installed Chrome version from Windows Registry."""
        import winreg

        logger.info("Checking Windows Registry for Chrome version...")

        registry_paths = [
            (winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Google\Update\Clients\{8A69D345-D564-463c-AFF1-A69D9E530F96}"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Google\Chrome\BLBeacon"),
        ]

        for hkey, path in registry_paths:
            try:
                key = winreg.OpenKey(hkey, path)
                version, _ = winreg.QueryValueEx(key, "version")
                winreg.CloseKey(key)

                major_version = int(version.split('.')[0])
                logger.info(f"Found Chrome version: {version} (major: {major_version})")
                return major_version
            except (FileNotFoundError, OSError):
                continue

        logger.warning("Chrome version not found in registry")
        return None

    def setup_driver(self):
        """Initialize undetected ChromeDriver with download directory configured."""
        import undetected_chromedriver as uc

        os.makedirs(config.DOWNLOADS_DIR, exist_ok=True)

        options = uc.ChromeOptions()

        if config.HEADLESS_MODE:
            options.add_argument('--headless=new')

        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')

        # Configure download directory
        prefs = {
            'download.default_directory': config.DOWNLOADS_DIR.replace('/', '\\'),
            'download.prompt_for_download': False,
            'download.directory_upgrade': True,
            'safebrowsing.enabled': True,
        }
        options.add_experimental_option('prefs', prefs)

        chrome_version = self.get_chrome_version_from_registry()

        try:
            if chrome_version:
                self.driver = uc.Chrome(options=options, version_main=chrome_version)
            else:
                self.driver = uc.Chrome(options=options)

            self.driver.set_page_load_timeout(config.WAIT_TIMEOUT * 2)
            logger.info("Chrome driver initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Chrome driver: {e}")
            raise

    # =========================================================================
    # BTS TABLEAU CHART SCRAPING
    # =========================================================================

    def _wait_for_tableau_load(self):
        """Wait for the Tableau chart to fully load inside its iframe."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        logger.info("Waiting for Tableau chart to load...")

        wait = WebDriverWait(self.driver, config.WAIT_TIMEOUT)

        try:
            # The URL has #anchored-offshore so the browser navigates to
            # that section on load. Wait for the page to settle.
            time.sleep(config.PAGE_LOAD_DELAY)

            # The page has 45 Tableau iframes. The viz_v1.js script populates
            # iframe src attributes as they come into view. We need to ensure
            # our target section is scrolled into view for its iframe to load.

            # Step 1: Click the nav link to scroll to the chart section
            logger.info("Clicking #anchored-offshore link to navigate to chart...")
            try:
                anchor_link = self.driver.find_element(
                    By.CSS_SELECTOR, 'a[href="#anchored-offshore"]'
                )
                self.driver.execute_script("arguments[0].click();", anchor_link)
            except Exception as e:
                logger.warning(f"Could not click anchor link: {e}")

            # Step 2: Wait and retry — Tableau JS needs time to set iframe src
            tableau_iframe = None
            for attempt in range(1, 7):
                time.sleep(config.PAGE_LOAD_DELAY)
                tableau_iframe = self._find_target_iframe(By)
                if tableau_iframe:
                    break
                logger.info(f"  Attempt {attempt}/6: iframe not ready yet, waiting...")

            if not tableau_iframe:
                logger.error(f"Could not find iframe containing '{config.TABLEAU_IFRAME_KEYWORD}'")
                return False

            logger.info(f"Target iframe found: {tableau_iframe.get_attribute('src')[:120]}")

            # Scroll the iframe into view so it's not covered by the BTS navbar
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", tableau_iframe
            )
            time.sleep(1)

            self.driver.switch_to.frame(tableau_iframe)
            logger.info("Switched to Tableau iframe")

            # Wait for the download button to be present (indicates chart has loaded)
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, config.DOWNLOAD_BUTTON_SELECTOR)
            ))
            logger.info("Tableau download button detected - chart is loaded")

            # Extra delay for complete rendering
            time.sleep(3)

            return True

        except Exception as e:
            logger.error(f"Timeout waiting for Tableau chart: {e}")
            return False

    def _find_target_iframe(self, By):
        """Search all iframes for the one matching TABLEAU_IFRAME_KEYWORD."""
        iframes = self.driver.find_elements(By.TAG_NAME, 'iframe')
        logger.info(f"Found {len(iframes)} iframes on page")

        for iframe in iframes:
            src = iframe.get_attribute('src') or ''
            if config.TABLEAU_IFRAME_KEYWORD in src:
                return iframe

        return None

    def _click_download_csv(self):
        """Navigate the Tableau download flow: Download -> Crosstab -> CSV -> Download."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        wait = WebDriverWait(self.driver, config.WAIT_TIMEOUT)

        try:
            # Step 1: Click the Download button in the toolbar
            logger.info("Clicking Download button...")
            download_btn = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, config.DOWNLOAD_BUTTON_SELECTOR)
            ))
            self.driver.execute_script("arguments[0].click();", download_btn)
            time.sleep(2)

            # Step 2: Click "Crosstab" from the flyout menu
            logger.info("Clicking Crosstab option...")
            crosstab_item = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, config.CROSSTAB_MENU_ITEM_SELECTOR)
            ))
            self.driver.execute_script("arguments[0].click();", crosstab_item)
            time.sleep(3)

            # Step 3: Wait for the Download Crosstab modal
            logger.info("Waiting for Download Crosstab modal...")
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, config.EXPORT_BUTTON_SELECTOR)
            ))

            # Step 4: Click CSV radio button
            logger.info("Selecting CSV format...")
            csv_radio = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, config.CSV_RADIO_LABEL_SELECTOR)
            ))
            self.driver.execute_script("arguments[0].click();", csv_radio)
            time.sleep(1)

            # Step 5: Click the Download/Export button
            logger.info("Clicking Export button...")
            export_btn = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, config.EXPORT_BUTTON_SELECTOR)
            ))
            self.driver.execute_script("arguments[0].click();", export_btn)

            logger.info("Download triggered, waiting for file...")
            return True

        except Exception as e:
            logger.error(f"Error during download flow: {e}")
            return False

    def _wait_for_download(self, timeout=60):
        """Wait for a CSV file to appear in the downloads directory."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Look for CSV files (not .crdownload partial files)
            csv_files = glob.glob(os.path.join(config.DOWNLOADS_DIR, '*.csv'))
            partial_files = glob.glob(os.path.join(config.DOWNLOADS_DIR, '*.crdownload'))

            if csv_files and not partial_files:
                # Return the most recent CSV file
                latest = max(csv_files, key=os.path.getmtime)
                logger.info(f"Download complete: {os.path.basename(latest)}")
                return latest

            time.sleep(1)

        logger.error(f"Download timed out after {timeout} seconds")
        return None

    def fetch_chart_data(self):
        """Main method: Navigate BTS Tableau and download CSV data."""
        logger.info("=" * 70)
        logger.info("Fetching chart data from BTS Tableau...")
        logger.info(f"URL: {config.BASE_URL}")
        logger.info("=" * 70)

        try:
            self.setup_driver()

            # Navigate to the BTS page
            logger.info(f"Navigating to: {config.BASE_URL}")
            self.driver.get(config.BASE_URL)

            # Wait for Tableau to load
            if not self._wait_for_tableau_load():
                logger.error("Failed to load Tableau chart")
                return None

            # Execute download flow
            if not self._click_download_csv():
                logger.error("Failed to complete download flow")
                return None

            # Wait for file download
            csv_path = self._wait_for_download()
            if not csv_path:
                logger.error("No CSV file downloaded")
                return None

            return csv_path

        except Exception as e:
            logger.error(f"Error fetching chart data: {e}")
            return None

        finally:
            if self.driver:
                try:
                    self.driver.quit()
                    logger.info("Browser closed")
                except Exception:
                    pass
