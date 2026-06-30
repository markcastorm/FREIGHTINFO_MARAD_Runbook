
import os
import time
import logging
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "https://www.bts.gov/freight-indicators#anchored-offshore"
TABLEAU_IFRAME_KEYWORD = 'ContainershipsAnchored'

def setup_driver():
    options = uc.ChromeOptions()
    # options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    driver = uc.Chrome(options=options)
    return driver

def check_download_button():
    driver = setup_driver()
    try:
        logger.info(f"Navigating to {BASE_URL}")
        driver.get(BASE_URL)
        
        # Wait for initial page load
        time.sleep(5)
        
        # Scroll down to find the section or trigger lazy loading
        logger.info("Scrolling down to find the chart section...")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(2)
        
        # Try to find the iframe with a loop and wait
        target_iframe = None
        max_attempts = 10
        for attempt in range(max_attempts):
            iframes = driver.find_elements(By.TAG_NAME, 'iframe')
            logger.info(f"Attempt {attempt+1}/{max_attempts}: Found {len(iframes)} iframes")
            for iframe in iframes:
                src = iframe.get_attribute('src') or ''
                if TABLEAU_IFRAME_KEYWORD in src:
                    target_iframe = iframe
                    break
            if target_iframe:
                break
            
            # Try scrolling more if not found
            driver.execute_script("window.scrollBy(0, 500);")
            time.sleep(3)
        
        if not target_iframe:
            logger.error(f"Could not find target iframe with keyword: {TABLEAU_IFRAME_KEYWORD}")
            driver.save_screenshot("no_iframe_found.png")
            # List all iframe src for debugging
            iframes = driver.find_elements(By.TAG_NAME, 'iframe')
            for i, iframe in enumerate(iframes):
                logger.info(f"Iframe {i}: src='{iframe.get_attribute('src')[:100]}...'")
            return

        logger.info(f"Found iframe: {target_iframe.get_attribute('src')[:100]}...")
        
        # Scroll it into view properly
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_iframe)
        time.sleep(2)
        
        driver.switch_to.frame(target_iframe)
        logger.info("Switched to Tableau iframe. Waiting for content to render...")
        
        # Wait for some content inside iframe to prove it's loaded
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "canvas, svg, .tab-zone-active"))
            )
            logger.info("Chart content detected.")
        except TimeoutException:
            logger.warning("Timed out waiting for chart content, but continuing...")

        # Look for download button
        selectors = [
            '[data-tb-test-id="viz-viewer-toolbar-button-download"]',
            'button[aria-label="Download"]',
            '[aria-label="Download"]',
            '[title="Download"]'
        ]
        
        found_btn = None
        for selector in selectors:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, selector)
                if btn and btn.is_displayed():
                    logger.info(f"Found download button with selector: {selector}")
                    found_btn = btn
                    break
            except:
                continue
        
        if not found_btn:
            logger.error("Download button NOT FOUND or NOT VISIBLE")
            driver.save_screenshot("no_download_button_visible.png")
            
            # List all buttons to see what IS there
            buttons = driver.find_elements(By.TAG_NAME, 'button')
            logger.info(f"Found {len(buttons)} buttons in iframe")
            for i, b in enumerate(buttons):
                label = b.get_attribute('aria-label') or b.get_attribute('title') or b.text
                if label:
                    logger.info(f"Button {i}: label='{label}', id='{b.get_attribute('id')}', test-id='{b.get_attribute('data-tb-test-id')}'")
        else:
            logger.info("Download button is visible and present.")
        
    except Exception as e:
        logger.exception(f"An error occurred: {e}")
        driver.save_screenshot("error_state.png")
    finally:
        driver.quit()

if __name__ == "__main__":
    check_download_button()
