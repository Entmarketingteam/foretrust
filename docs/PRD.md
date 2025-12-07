# Foretrust MVP v1.0 - Product Requirements Document

## Executive Summary

Foretrust is an AI-powered real estate investment decision platform designed for private equity firms, NNN investors, CRE brokers, and banks. The platform automates deal ingestion, data enrichment, underwriting analysis, and Investment Committee (IC) memo generation, reducing the time from deal intake to IC-ready memo from days to under 2 minutes.

## Problem Statement

Real estate investment professionals spend excessive time manually:
- Extracting data from Offering Memorandums (OMs) and property listings
- Researching market data, tenant creditworthiness, and property details
- Building financial models and underwriting assumptions
- Writing Investment Committee memos

This manual process is error-prone, inconsistent, and limits deal throughput.

## Target Users

| User Type | Description | Primary Need |
|-----------|-------------|--------------|
| PE Firms | Private equity real estate investors | Rapid deal screening and IC memo generation |
| NNN Investors | Triple-net lease property buyers | Tenant credit analysis and lease term evaluation |
| CRE Brokers | Commercial real estate brokers | Quick property analysis for clients |
| Banks/Lenders | Commercial real estate lenders | Risk assessment and underwriting validation |

## Core MVP Goals

1. **Ingest** deals from PDFs, URLs, or manual entry
2. **Enrich** with external data (geocoding, market stats, tenant credit)
3. **Score** deals using automated underwriting logic
4. **Generate** Investment Committee memos in under 2 minutes

## Feature Requirements

### 1. Deal Ingestion (P0)

**User Story:** As an analyst, I want to upload an OM PDF or paste a listing URL so that the system extracts key deal information automatically.

**Acceptance Criteria:**
- [ ] Accept PDF content (text extraction)
- [ ] Accept property listing URLs
- [ ] Accept manual data entry
- [ ] Extract: property address, tenant name, lease terms, asking price, NOI, cap rate
- [ ] Create deal record with "ingested" status

**Data Extracted:**
- Property: address, type, SF, year built, land acres
- Tenant: name, lease type, term dates, rent, escalations
- Financials: asking price, NOI, cap rate

### 2. Data Enrichment (P0)

**User Story:** As an analyst, I want the system to automatically enrich deal data with external sources so I have complete information for analysis.

**Acceptance Criteria:**
- [ ] Geocode property address (lat/long)
- [ ] Fetch market data (vacancy rates, rent comps, cap rate trends)
- [ ] Retrieve tenant credit information (rating, financials)
- [ ] Update deal status to "enriched"

**Enrichment Sources (MVP - simulated via LLM):**
- Geocoding: Google Maps / Census
- Market: CoStar / REIS (simulated)
- Tenant: D&B / S&P ratings (simulated)

### 3. Underwriting Engine (P0)

**User Story:** As an investment analyst, I want the system to score deals using consistent underwriting criteria so I can quickly identify promising opportunities.

**Scoring Components (0-100 scale):**

| Score | Weight | Description |
|-------|--------|-------------|
| LCI Score | 25% | Lease Credit Index - lease term, escalations, options |
| Tenant Credit | 25% | Credit rating, financial stability, industry outlook |
| Downside Score | 25% | Vacancy risk, re-leasing probability, market depth |
| Market Depth | 25% | Liquidity, buyer pool, comparable transactions |

**Financial Metrics Calculated:**
- Levered IRR
- Unlevered IRR
- DSCR (Debt Service Coverage Ratio)
- Cash-on-Cash (Year 1 and Average)
- Exit value sensitivity

**Risk Flags:**
- Lease term < 5 years remaining
- Tenant credit below investment grade
- Cap rate compression risk
- Single-tenant concentration

### 4. IC Memo Generator (P0)

**User Story:** As an investment professional, I want to generate a formatted Investment Committee memo so I can present deals quickly.

**Memo Sections:**
1. Executive Summary
2. Investment Thesis
3. Property Overview
4. Tenant Analysis
5. Market Analysis
6. Financial Summary
7. Risk Factors
8. Recommendation (Approve / Approve with Conditions / Decline)

**Output Format:** Markdown (convertible to PDF)

### 5. Deal Dashboard (P1)

**User Story:** As a portfolio manager, I want to view all deals in a pipeline dashboard so I can track deal flow and status.

**Features:**
- Deal list with key metrics (name, tenant, score, cap rate, status)
- Filter by: status, score range, market, tenant
- Search by property name or tenant
- Sort by date, score, cap rate
- Quick stats: total deals, average score, pipeline value

### 6. Authentication (P2 - Post-MVP)

- Organization-based multi-tenancy
- User roles: Admin, Analyst, Viewer
- Row-level security per organization

## Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Ingestion to Memo | < 2 minutes |
| Concurrent Users | 10+ per organization |
| Data Retention | Indefinite |
| Availability | 99% uptime |

## Success Metrics (KPIs)

| Metric | Target |
|--------|--------|
| Time to IC Memo | < 2 minutes |
| Data Extraction Accuracy | > 90% |
| Deals Processed/Week | 50+ per user |
| User Adoption | 80% of analysts using weekly |

## Out of Scope (MVP)

- PDF file upload (text paste only for MVP)
- Real external API integrations (simulated via LLM)
- Portfolio-level analytics
- Deal comparison tools
- Email notifications
- Mobile app

## Release Criteria

1. All P0 features functional
2. End-to-end pipeline working (ingest → enrich → underwrite → memo)
3. Dashboard displaying deals with scores
4. Mock data fallback for demo environments
5. Supabase database schema deployed

---

*Document Version: 1.0*
*Last Updated: November 2025*
