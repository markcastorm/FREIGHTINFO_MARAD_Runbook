
import os
import time
import logging
import re
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "https://www.bts.gov/freight-indicators#anchored-offshore"
TABLEAU_IFRAME_KEYWORD = 'ContainershipsAnchored'

def map_coordinates():
    driver = uc.Chrome()
    try:
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
            time.sleep(2)
        
        if not target_iframe: return
        driver.switch_to.frame(target_iframe)
        time.sleep(5)

        all_canvases = driver.find_elements(By.TAG_NAME, 'canvas')
        target_canvas = None
        for c in reversed(all_canvases):
            if c.is_displayed() and c.size['width'] > 200:
                target_canvas = c
                break
        
        if not target_canvas: return
        
        w, h = target_canvas.size['width'], target_canvas.size['height']
        logger.info(f"Canvas size: {w}x{h}")
        actions = ActionChains(driver)
        
        # Scan X from 0 to W in larger steps to find where 2026 data is
        for x in range(10, w, 30):
            # Scan more Y points to be sure
            for y in range(h // 5, h, h // 5):
                try:
                    actions.move_to_element_with_offset(target_canvas, x - w//2, y - h//2).perform()
                    time.sleep(0.1)
                    
                    tt_elements = driver.find_elements(By.CSS_SELECTOR, ".tab-tooltip, .tab-glass-content, .tab-beautified-tooltip")
                    for tt in tt_elements:
                        if tt.is_displayed():
                            text = tt.text.strip()
                            date_match = re.search(r"Date:\s+(\d{1,2}/\d{1,2}/\d{4})", text)
                            if date_match:
                                logger.info(f"X={x}, Y={y} -> Date: {date_match.group(1)}")
                except: pass
                
    finally:
        driver.quit()

if __name__ == "__main__":
    map_coordinates()
