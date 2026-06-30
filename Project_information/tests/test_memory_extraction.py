
import os
import time
import logging
import json
import csv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "https://www.bts.gov/freight-indicators#anchored-offshore"
IFRAME_KEY = 'ContainershipsAnchored'

def run_memory_extraction_test():
    start_time = time.time()
    options = uc.ChromeOptions()
    # options.add_argument('--headless') 
    driver = uc.Chrome(options=options)
    
    try:
        logger.info("PHASE 1: Navigation...")
        driver.get(BASE_URL)
        
        # 1. Locate Iframe
        target_iframe = None
        for _ in range(15):
            iframes = driver.find_elements(By.TAG_NAME, 'iframe')
            for f in iframes:
                if IFRAME_KEY in (f.get_attribute('src') or ''):
                    target_iframe = f
                    break
            if target_iframe: break
            time.sleep(1)
        
        if not target_iframe: 
            logger.error("Iframe not found")
            return
            
        driver.switch_to.frame(target_iframe)
        logger.info("Waiting for data model to initialize...")
        time.sleep(8) # Wait for Tableau to bootstrap

        # PHASE 2: Deep Memory Extraction via JS
        logger.info("Extracting Tableau internal data model...")
        
        # This script tries multiple paths to find the data dictionary and values
        extraction_script = """
        try {
            var data = {};
            
            // Path 1: Check for Bootstrap Data in scripts
            var scripts = document.querySelectorAll('script');
            scripts.forEach(s => {
                if (s.text && s.text.includes('bootstrapData')) {
                    data['has_bootstrap_script'] = true;
                    // We could parse the JSON out of the string if needed
                }
            });

            // Path 2: Check for global objects
            if (window.parent && window.parent.tableau) data['parent_tableau'] = true;
            if (window.tableau) data['window_tableau'] = true;
            
            // Path 3: Try to find the 'vqlBootstrap' which contains the actual data
            // This is often where the meat is
            if (window.vqlBootstrap) {
                data['vqlBootstrap'] = "Found";
            }

            // Let's look for the hidden data containers Tableau uses for accessibility
            // Sometimes the data is actually in the DOM but hidden
            var summary_data = [];
            var summary_btn = document.querySelector('button[aria-label*="View Data"]');
            if (summary_btn) data['view_data_button'] = "Present";

            return data;
        } catch(e) {
            return "Error: " + e.message;
        }
        """
        res = driver.execute_script(extraction_script)
        logger.info(f"Initial Memory Map: {res}")

        # REFINED EXTRACTION: Attempting to trigger the internal "Summary Data" model
        # Tableau often has a hidden mechanism to export data
        logger.info("Attempting to locate raw data tables in memory...")
        
        raw_data_script = """
        try {
            // Find the Viz object
            var viz = null;
            if (window.parent && window.parent.tableau && window.parent.tableau.VizManager) {
                viz = window.parent.tableau.VizManager.getVizs()[0];
            }
            
            if (viz) {
                // If the API is available, we can ask for the data directly
                // This is the cleanest 'No Mouse' way
                return "Viz API Found";
            }
            
            // Fallback: look for the 'vqlBootstrap' JSON blob which is huge
            // and contains the data dictionary
            return "Searching for bootstrap blob...";
        } catch(e) { return e.message; }
        """
        logger.info(f"Viz Search: {driver.execute_script(raw_data_script)}")

        # FINAL "NO MOUSE" FALLBACK: Accessibility Data
        # Tableau charts always have a hidden table or text for screen readers
        logger.info("Attempting extraction from accessibility layer...")
        acc_script = """
        var results = [];
        var elements = document.querySelectorAll('[aria-label*="Date"], [aria-label*="Vessels"], .sr-only');
        elements.forEach(el => {
            if (el.innerText && el.innerText.includes('2026')) {
                results.push(el.innerText);
            }
        });
        return results;
        """
        acc_results = driver.execute_script(acc_script)
        logger.info(f"Accessibility extraction found {len(acc_results)} items.")
        if acc_results:
            for item in acc_results[:5]: logger.info(f"Item: {item}")

    finally:
        driver.quit()
        logger.info(f"Total time: {time.time() - start_time:.2f}s")

if __name__ == "__main__":
    run_memory_extraction_test()
