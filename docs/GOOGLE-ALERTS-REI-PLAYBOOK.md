# Playbook: Agentic Google Alerts for REI

## 1. Objective
Identify distressed homeowners via digital "Social Signals" (Obituaries, Divorce notices, Legal summons) before they are recorded as public instruments on eCCLIX.

## 2. Google Search "Motivation Queries"
Set up Google Alerts or a Search Agent with these targeted strings for your counties:

### Probate / Estate Signals
*   `"estate of" site:legacy.com "Bourbon County" KY`
*   `"passed away" "Woodford County" KY "property"`
*   `"administrator" "appointed" "probate" "Franklin County" KY`

### Divorce / Litigation Signals
*   `"civil summons" "Scott County" KY "foreclosure"`
*   `"lis pendens" "Bourbon County" KY 2026`

## 3. The Agentic Workflow
1.  **Monitor:** Agent scrapes Google Search daily for the above strings.
2.  **Match:** Agent extracts names from search snippets.
3.  **Cross-Ref:** Agent pings the PVA for the name to see if they own property in the county.
4.  **Target:** If property is owned, flag as a "High Motivation" lead and trigger the eCCLIX search for the specific address.

## 4. Automation Implementation
I have added the blueprint for this in `scraper-service/app/pipeline/agentic/google_alerts_agent.py`.
