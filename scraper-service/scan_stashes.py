import os
import json
import csv

def scan_exports():
    exports_dir = "/Users/ethanatchley/Desktop/foretrust/scraper-service/exports"
    
    print("Scanning local historical exports for 4-bedroom pre-foreclosures...")
    print("-" * 70)
    
    matches = []
    
    # 1. Scan JSON files in best-deals and portal-intel
    for root, dirs, files in os.walk(exports_dir):
        for file in files:
            if file.endswith(".json"):
                path = os.path.join(root, file)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        
                        # Handle list of items or single dictionary
                        items = data if isinstance(data, list) else [data]
                        
                        for item in items:
                            # Recursive check inside nested structures
                            addr = item.get("property_address") or item.get("address")
                            jur = item.get("jurisdiction") or item.get("county") or ""
                            
                            if not addr or "SCOTT" not in str(jur).upper() and "WOODFORD" not in str(jur).upper():
                                continue
                                
                            payload_str = json.dumps(item).upper()
                            
                            is_4_bed = any(x in payload_str for x in ["4 BED", "4BR", "4-BED", "4.0 BED", "BEDROOMS: 4", "4 BEDROOMS", "4 BEDROOM"])
                            # Check numerical keys if any
                            if str(item.get("bedrooms")) == "4" or str(item.get("year_built")) == "4":
                                is_4_bed = True
                                
                            is_pre_foreclosure = any(x in payload_str for x in ["PRE_FORECLOSURE", "LP", "LIS PENDENS", "FORECLOSURE"])
                            
                            if is_4_bed and is_pre_foreclosure:
                                matches.append({
                                    "address": addr,
                                    "owner": item.get("owner_name") or item.get("grantor") or "Unknown",
                                    "county": jur,
                                    "source": file
                                })
                except Exception as e:
                    pass
                    
            elif file.endswith(".csv"):
                path = os.path.join(root, file)
                try:
                    with open(path, mode="r", encoding="utf-8-sig", errors="ignore") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            row_str = json.dumps(row).upper()
                            
                            addr = row.get("property_address") or row.get("address") or row.get("location")
                            county = row.get("county") or row.get("jurisdiction") or ""
                            
                            if not addr or "SCOTT" not in str(county).upper() and "WOODFORD" not in str(county).upper():
                                continue
                                
                            is_4_bed = any(x in row_str for x in ["4 BED", "4BR", "4-BED", "4.0 BED", "BEDROOMS: 4", "4 BEDROOMS", "4 BEDROOM"])
                            is_pre_foreclosure = any(x in row_str for x in ["PRE_FORECLOSURE", "LP", "LIS PENDENS", "FORECLOSURE"])
                            
                            if is_4_bed and is_pre_foreclosure:
                                matches.append({
                                    "address": addr,
                                    "owner": row.get("owner_name") or row.get("grantor") or "Unknown",
                                    "county": county,
                                    "source": file
                                })
                except Exception as e:
                    pass

    # Deduplicate
    unique_matches = {}
    for m in matches:
        unique_matches[m["address"].upper()] = m
        
    print(f"Found {len(unique_matches)} unique 4-bedroom pre-foreclosures in historical backups:")
    print("=" * 70)
    for i, (addr, m) in enumerate(unique_matches.items()):
        print(f"{i+1}. 🏡 {m['address'].title()} ({m['county'].title()})")
        print(f"   Owner: {m['owner'].title()}")
        print(f"   Source Backup: {m['source']}")
        print("-" * 70)

if __name__ == "__main__":
    scan_exports()
