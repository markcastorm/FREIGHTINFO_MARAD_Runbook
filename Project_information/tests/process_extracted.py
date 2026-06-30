
import re
import json

def process_extracted():
    with open("extracted_data.txt", "r", encoding="utf-8") as f:
        content = f.read()
    
    entries = content.split("--------------------")
    parsed = {}
    
    for entry in entries:
        entry = entry.strip()
        if not entry: continue
        
        region_match = re.search(r"Port Region:\s+(East|West|Gulf)", entry, re.I)
        date_match = re.search(r"Date:\s+(\d{1,2}/\d{1,2}/\d{4})", entry)
        value_match = re.search(r"# of Vessels:\s+(\d+)", entry)
        
        if region_match and date_match and value_match:
            region = region_match.group(1).strip()
            date_str = date_match.group(1)
            value = int(value_match.group(1))
            
            if date_str not in parsed:
                parsed[date_str] = {}
            parsed[date_str][region] = value

    # Sort dates
    from datetime import datetime
    sorted_dates = sorted(parsed.keys(), key=lambda x: datetime.strptime(x, "%m/%d/%Y"))
    
    print(f"Total unique dates: {len(sorted_dates)}")
    if sorted_dates:
        print(f"Date range: {sorted_dates[0]} to {sorted_dates[-1]}")
        
        # Show recent dates
        print("\nRecent entries:")
        for d in sorted_dates[-5:]:
            print(f"{d}: {parsed[d]}")

if __name__ == "__main__":
    process_extracted()
