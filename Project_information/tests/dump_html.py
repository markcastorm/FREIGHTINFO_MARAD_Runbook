
import os
import time
import logging
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "https://www.bts.gov/freight-indicators#anchored-offshore"
TABLEAU_IFRAME_KEYWORD = 'ContainershipsAnchored'

def dump_iframe_html():
    driver = uc.Chrome()
    try:
        logger.info(f"Navigating to {BASE_URL}")
        driver.get(BASE_URL)
        time.sleep(10)
        
        target_iframe = None
        for attempt in range(10):
            iframes = driver.find_elements(By.TAG_NAME, 'iframe')
            for iframe in iframes:
                if TABLEAU_IFRAME_KEYWORD in (iframe.get_attribute('src') or ''):
                    target_iframe = iframe
                    break
            if target_iframe: break
            driver.execute_script("window.scrollBy(0, 500);")
            time.sleep(3)
        
        if not target_iframe:
            logger.error("Iframe not found")
            return

        driver.execute_to_frame = target_iframe
        driver.switch_to.frame(target_iframe)
        
        # Wait for some content
        time.sleep(5)
        
        html = driver.page_source
        with open("iframe_dump.html", "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"Dumped {len(html)} bytes to iframe_dump.html")
        
    finally:
        driver.quit()

if __name__ == "__main__":
    dump_iframe_html()
