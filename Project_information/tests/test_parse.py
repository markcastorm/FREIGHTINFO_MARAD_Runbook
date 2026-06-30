
import re
import json

data = """
Containerships Anchored off U.S. Ports
Port Region:   East
Date:   5/26/2026
# of Vessels:   9
--------------------
Containerships Anchored off U.S. Ports
Port Region:   East
Date:   6/9/2026
# of Vessels:   2
--------------------
Containerships Anchored off U.S. Ports
Port Region:   East
Date:   5/12/2026
# of Vessels:   2
--------------------
Containerships Anchored off U.S. Ports
Port Region:   Gulf
Date:   5/26/2026
# of Vessels:   0
--------------------
"""

def parse_tooltips(text):
    entries = text.strip().split("--------------------")
    parsed = {}
    
    for i, entry in enumerate(entries):
        entry = entry.strip()
        if not entry: continue
        
        region_match = re.search(r"Port Region:\s+(East|West|Gulf)", entry, re.I)
        date_match = re.search(r"Date:\s+(\d{1,2}/\d{1,2}/\d{4})", entry)
        value_match = re.search(r"# of Vessels:\s+(\d+)", entry)
        
        if region_match and date_match and value_match:
            region = region_match.group(1).strip()
            date_str = date_match.group(1)
            value = int(value_match.group(1))
            
            print(f"Entry {i}: {date_str} {region} = {value}")
            
            if date_str not in parsed:
                parsed[date_str] = {}
            parsed[date_str][region] = value
        else:
            print(f"Entry {i} FAILED: region={bool(region_match)}, date={bool(date_match)}, value={bool(value_match)}")
            
    return parsed

if __name__ == "__main__":
    results = parse_tooltips(data)
    print("Final JSON:")
    print(json.dumps(results, indent=2))
