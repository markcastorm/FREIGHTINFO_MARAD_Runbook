
import os
import time
import logging
import re
import csv
import json
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "https://www.bts.gov/freight-indicators#anchored-offshore"
IFRAME_KEY = 'ContainershipsAnchored'

def run_hybrid_perfection_scan():
    start_time = time.time()
    options = uc.ChromeOptions()
    options.add_argument('--blink-settings=imagesEnabled=false')
    driver = uc.Chrome(options=options)
    
    try:
        logger.info("Initializing Hybrid Scan...")
        driver.get(BASE_URL)
        driver.execute_script("window.location.hash = 'anchored-offshore';")
        
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
        
        if not target_iframe: return
        driver.switch_to.frame(target_iframe)
        
        # 2. Inject the "Net" (MutationObserver)
        logger.info("Injecting JS Tooltip Listener...")
        driver.execute_script("""
            window.capturedTooltips = [];
            function startNet() {
                if (!document.body) {
                    setTimeout(startNet, 100);
                    return;
                }
                window.tooltipNet = new MutationObserver((mutations) => {
                    for (let mutation of mutations) {
                        for (let node of mutation.addedNodes) {
                            if (node.nodeType === 1) {
                                let tt = (node.classList && (node.classList.contains('tab-tooltip') || node.classList.contains('tab-glass-content'))) 
                                         ? node : node.querySelector('.tab-tooltip, .tab-glass-content');
                                if (tt) {
                                    let text = tt.innerText;
                                    if (text && !window.capturedTooltips.includes(text)) {
                                        window.capturedTooltips.push(text);
                                    }
                                }
                            }
                        }
                    }
                });
                window.tooltipNet.observe(document.body, { childList: true, subtree: true });
            }
            startNet();
        """)
        time.sleep(2) # Brief wait for JS to settle

        # 3. Locate Canvas
        target_canvas = None
        for _ in range(20):
            canvases = driver.find_elements(By.TAG_NAME, 'canvas')
            for c in reversed(canvases):
                if c.is_displayed() and c.size['width'] > 200:
                    target_canvas = c
                    break
            if target_canvas: break
            time.sleep(1)

        if not target_canvas: return
        w, h = target_canvas.size['width'], target_canvas.size['height']
        actions = ActionChains(driver)

        # 4. The "Vertical Comb" Scan
        logger.info("Starting High-Speed Vertical Comb...")
        scan_start = time.time()
        
        # We scan in 3 horizontal passes with different vertical offsets to ensure hits
        for pass_num in range(2):
            logger.info(f"  Pass {pass_num+1}/2...")
            for x in range(w - 2, w - 250, -5): # Wider range to be safe
                for y in range(20, h - 20, 25): # Fast vertical sweep
                    actions.move_to_element_with_offset(target_canvas, x - w//2, y - h//2).perform()
                    # No sleep needed in Python; JS is lightning fast
        
        logger.info(f"Scan complete in {time.time() - scan_start:.2f}s")
        
        # 5. Extract and Parse
        raw_results = driver.execute_script("return window.capturedTooltips;")
        logger.info(f"JS Net captured {len(raw_results)} unique tooltips.")

        all_data = {} # {date: {region: val}}
        
        for text in raw_results:
            r_m = re.search(r"Port Region:\s+(East|West|Gulf)", text, re.I)
            d_m = re.search(r"Date:\s+(\d{1,2}/\d{1,2}/\d{4})", text)
            v_m = re.search(r"# of Vessels:\s+(\d+)", text)
            
            if r_m and d_m and v_m:
                dt = d_m.group(1)
                if "/2026" in dt:
                    reg = r_m.group(1).strip()
                    val = int(v_m.group(1))
                    if dt not in all_data: all_data[dt] = {}
                    all_data[dt][reg] = val

        # 6. Save and Verify
        csv_path = "test_2026_data.csv"
        sorted_dates = sorted(all_data.keys(), key=lambda d: datetime.strptime(d, "%m/%d/%Y"))
        
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "East", "West", "Gulf"])
            for d in sorted_dates:
                # Check for blanks and highlight
                row = [d, all_data[d].get('East', ''), all_data[d].get('West', ''), all_data[d].get('Gulf', '')]
                writer.writerow(row)
        
        logger.info("-" * 40)
        logger.info(f"RESULTS (Total 2026 Weeks: {len(all_data)})")
        for d in sorted_dates:
            missing = [r for r in ['East', 'West', 'Gulf'] if r not in all_data[d]]
            status = "PERFECT" if not missing else f"MISSING: {missing}"
            logger.info(f"{d}: {all_data[d]} -> {status}")
            
        logger.info(f"Total Execution Time: {time.time() - start_time:.2f}s")

    finally:
        driver.quit()

if __name__ == "__main__":
    run_hybrid_perfection_scan()
