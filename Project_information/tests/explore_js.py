
import os
import time
import logging
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "https://www.bts.gov/freight-indicators#anchored-offshore"
IFRAME_KEY = 'ContainershipsAnchored'

def try_api_extraction():
    driver = uc.Chrome()
    try:
        driver.get(BASE_URL)
        time.sleep(10)
        
        iframes = driver.find_elements(By.TAG_NAME, 'iframe')
        target_iframe = None
        for f in iframes:
            if IFRAME_KEY in (f.get_attribute('src') or ''):
                target_iframe = f
                break
        
        if not target_iframe: return
        driver.switch_to.frame(target_iframe)
        time.sleep(5)

        logger.info("Attempting Tableau API Data Extraction...")
        
        script = """
        try {
            var viz = null;
            if (window.parent && window.parent.tableau && window.parent.tableau.VizManager) {
                viz = window.parent.tableau.VizManager.getVizs()[0];
            } else if (window.tableau && window.tableau.Vizql) {
                // Try other internal paths
            }
            
            if (viz) {
                return "Viz found! Workbook: " + viz.getWorkbook().getName();
            }
            
            // Try to find bootstrap data
            if (window.tabBootstrap && window.tabBootstrap.bootstrapData) {
                return "Bootstrap data found!";
            }
            
            return "No API viz object found directly";
        } catch(e) {
            return "Error: " + e.message;
        }
        """
        res = driver.execute_script(script)
        logger.info(f"API Search Result: {res}")

        # Let's try to just dump the text of the entire iframe body
        # Sometimes there's a hidden text representation
        body_text = driver.find_element(By.TAG_NAME, 'body').text
        logger.info(f"Body text length: {len(body_text)}")
        if "June 9, 2026" in body_text:
            logger.info("Target date found in raw body text!")

    finally:
        driver.quit()

if __name__ == "__main__":
    try_api_extraction()
