# FOIA — Water Disconnect List (GMWSS / City of Georgetown)

Send to **both** (records may be split):

- **GMWSS** — rwilhite@gmwss.com | 1000 W. Main St, Georgetown KY 40324 | 502-863-7816  
- **City Clerk-Treasurer** — via [Open Records form](https://www.georgetownky.gov/2251/Open-Records-Request) | 629 N. Broadway, Georgetown KY 40324  

---

**Subject:** Open Records Request — Residential Water Service Disconnections (Last 90 Days)

Pursuant to KRS 61.870–61.884, I request copies of records showing **residential** water accounts disconnected for **non-payment** in the last **90 days**, including:

- Service address  
- Account holder name (if on record)  
- Disconnect date  
- Reconnect date (if applicable)  

Preferred format: **CSV or Excel**. Electronic delivery to: [your email].

This request is not for a commercial data broker purpose.

[Your name]  
[Your address]  
[Date]

---

After you receive the file, import:

```bash
WATER_FOIA_CSV=/path/to/gmwss-disconnects.csv bash scripts/run-signal-digest.sh
```
