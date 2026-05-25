# Design Spec: eCCLIX Institutional Automation (Phase 1: Seed & Blitz)

**Date:** 2026-05-25
**Topic:** Reusable Multi-County Real Estate Distress Pipeline

## 1. Executive Summary
Build a state-aware automation engine for eCCLIX that captures "Off-Market" property signals (Foreclosures, Probates, Tax Liens). Today's goal is to "Seed" the system with all 2026 historical data for four counties (Scott, Bourbon, Woodford, Franklin) using a single 24-hour pass, while creating the schema for future automated incremental runs.

## 2. Architecture: The Atomic Queue
Instead of a monolithic script, we utilize an **Atomic Task** architecture where each extraction is a unique triplet:
`[County] + [Instrument Type] + [Date Range]`

### Components:
1.  **State Tracker (Supabase):** A new table `ft_scrape_state` tracks the "last successful date" for each triplet.
2.  **Orchestrator:** A Python service that calculates the "Gap" between the current date and the last successful run.
3.  **Parallel Workers:** Independent Playwright instances that handle one county at a time to prevent session collisions.

## 3. Data Targets (The "Signals")
| Signal | Instrument Code | Intent |
| :--- | :--- | :--- |
| **Probate** | `WILL`, `AOD`, `AOC` | Estate liquidation opportunities. |
| **Foreclosure** | `LP`, `DJ` | Highly motivated "pre-auction" leads. |
| **Tax Distress** | `SLIEN`, `FLIEN`, `DTAX` | Financial instability markers. |
| **Estate** | `DEED` (keyword filtered) | Recent transfers signaling turnover. |

## 4. Phase 1 Implementation (Today)
### Task 1: "Seed" Execution
*   Initialize data extraction from **01/01/2026** to **05/25/2026**.
*   Run parallel workers for: Bourbon, Scott, Woodford, Franklin.
*   Priority 1: Delinquent Tax Portal (high volume/immediate urgency).
*   Priority 2: Lis Pendens (LP) and Wills.

### Task 2: Persistence & Scoring
*   All records persisted to Supabase `ft_leads`.
*   Auto-deduplication using `instrument_number + county`.
*   Initialize `hot_score` based on signal stacking (e.g., LP + Tax Lien = 90+ Score).

## 5. Phase 2: Future Automation
*   **Trigger:** Automated via Railway Cron or Manual "Sweep" command.
*   **Logic:** `Start Date = last_successful_date + 1`.
*   **Scale:** Expand to all 85+ eCCLIX counties using the same modular connector.

## 6. Success Criteria
*   [ ] 100% of 2026 records captured for target counties today.
*   [ ] No duplicate leads in Supabase.
*   [ ] Each lead enriched with physical address via PVA/qPublic.
