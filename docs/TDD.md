# Foretrust MVP v1.0 - Technical Design Document

## 1. System Architecture

### 1.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (React)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Dashboard   │  │  New Deal    │  │    Deal Detail       │  │
│  │  /foretrust  │  │  /new        │  │    /:id              │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Backend API (Express/Node)                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Deal Routes  │  │ OpenAI Svc   │  │   Database Service   │  │
│  │ /api/foretrust│ │ (GPT-4)      │  │   (Supabase/Mock)    │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Data Layer                                  │
│  ┌──────────────────────┐    ┌─────────────────────────────┐   │
│  │   Supabase (Postgres) │    │   In-Memory Mock Store     │   │
│  │   - 10 Tables         │    │   (Fallback for Demo)      │   │
│  │   - RLS Policies      │    │                            │   │
│  └──────────────────────┘    └─────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Frontend | React 18 + TypeScript | UI components |
| Styling | Tailwind CSS | Utility-first CSS |
| Routing | React Router v6 | Client-side routing |
| Backend | Express.js + TypeScript | REST API server |
| Database | Supabase (PostgreSQL) | Primary data store |
| AI/LLM | OpenAI GPT-4 Turbo | Document parsing, scoring, memo generation |
| Build | Vite | Frontend bundling |
| Runtime | Node.js 18+ | Server runtime |

## 2. Database Schema

### 2.1 Entity Relationship Diagram

```
ft_organizations (1) ──── (N) ft_users
        │
        │ (1)
        │
        ▼ (N)
   ft_deals (1) ─────┬──── (1) ft_deal_property_attributes
        │            │
        │            ├──── (1) ft_deal_lease_terms
        │            │
        │            ├──── (1) ft_deal_scores
        │            │
        │            ├──── (1) ft_deal_financials
        │            │
        │            ├──── (1) ft_deal_enrichment
        │            │
        │            ├──── (N) ft_deal_documents
        │            │
        │            └──── (N) ft_deal_memos
```

### 2.2 Table Definitions

#### ft_organizations
| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | Organization ID |
| name | VARCHAR(255) | Organization name |
| created_at | TIMESTAMPTZ | Creation timestamp |
| updated_at | TIMESTAMPTZ | Last update timestamp |

#### ft_users
| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | User ID |
| organization_id | UUID (FK) | Parent organization |
| email | VARCHAR(255) | User email (unique) |
| name | VARCHAR(255) | Display name |
| role | VARCHAR(50) | admin, analyst, viewer |

#### ft_deals
| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | Deal ID |
| organization_id | UUID (FK) | Parent organization |
| name | VARCHAR(255) | Deal/property name |
| status | VARCHAR(50) | draft, ingested, enriched, underwritten, memo_generated, archived |
| source_type | VARCHAR(50) | pdf, url, manual |
| source_url | TEXT | Source URL if applicable |
| created_by | UUID (FK) | Creating user |

#### ft_deal_property_attributes
| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | Record ID |
| deal_id | UUID (FK, unique) | Parent deal |
| address_line1 | VARCHAR(255) | Street address |
| city | VARCHAR(100) | City |
| state | VARCHAR(50) | State |
| postal_code | VARCHAR(20) | ZIP code |
| latitude | DECIMAL(10,8) | Geocoded latitude |
| longitude | DECIMAL(11,8) | Geocoded longitude |
| property_type | VARCHAR(100) | Retail - NNN, Industrial, etc. |
| building_sqft | INTEGER | Building square footage |
| land_acres | DECIMAL(10,4) | Land acreage |
| year_built | INTEGER | Year constructed |

#### ft_deal_lease_terms
| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | Record ID |
| deal_id | UUID (FK, unique) | Parent deal |
| tenant_name | VARCHAR(255) | Tenant company name |
| lease_type | VARCHAR(100) | Absolute NNN, NNN, NN, etc. |
| lease_start_date | DATE | Lease commencement |
| lease_end_date | DATE | Lease expiration |
| base_rent_annual | DECIMAL(15,2) | Annual base rent |
| rent_psf | DECIMAL(10,2) | Rent per square foot |
| rent_escalations | JSONB | Escalation schedule |
| options | JSONB | Renewal/purchase options |

#### ft_deal_scores
| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | Record ID |
| deal_id | UUID (FK, unique) | Parent deal |
| lci_score | INTEGER (0-100) | Lease Credit Index |
| tenant_credit_score | INTEGER (0-100) | Tenant creditworthiness |
| downside_score | INTEGER (0-100) | Downside protection |
| market_depth_score | INTEGER (0-100) | Market liquidity |
| overall_score | INTEGER (0-100) | Weighted composite |
| risk_flags | JSONB | Array of risk items |
| scored_at | TIMESTAMPTZ | Scoring timestamp |

#### ft_deal_financials
| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | Record ID |
| deal_id | UUID (FK, unique) | Parent deal |
| purchase_price | DECIMAL(15,2) | Acquisition price |
| noi_year1 | DECIMAL(15,2) | Year 1 NOI |
| cap_rate | DECIMAL(5,4) | Going-in cap rate |
| ltv_assumed | DECIMAL(5,4) | Loan-to-value ratio |
| interest_rate | DECIMAL(5,4) | Debt interest rate |
| io_years | INTEGER | Interest-only period |
| amort_years | INTEGER | Amortization period |
| exit_cap_rate | DECIMAL(5,4) | Exit cap assumption |
| hold_period_years | INTEGER | Investment horizon |
| levered_irr | DECIMAL(5,4) | Levered IRR |
| unlevered_irr | DECIMAL(5,4) | Unlevered IRR |
| dscr_min | DECIMAL(5,2) | Minimum DSCR |
| cash_on_cash_year1 | DECIMAL(5,4) | Year 1 CoC |

#### ft_deal_memos
| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | Memo ID |
| deal_id | UUID (FK) | Parent deal |
| version | INTEGER | Memo version number |
| content_markdown | TEXT | Full memo content |
| recommendation | VARCHAR(50) | approve, approve_with_conditions, decline |
| generated_at | TIMESTAMPTZ | Generation timestamp |

## 3. API Design

### 3.1 Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/foretrust/deals | List all deals |
| GET | /api/foretrust/deals/:id | Get complete deal |
| POST | /api/foretrust/deals | Create new deal |
| DELETE | /api/foretrust/deals/:id | Delete deal |
| POST | /api/foretrust/deals/:id/ingest | Run ingestion pipeline |
| POST | /api/foretrust/deals/:id/enrich | Run enrichment |
| POST | /api/foretrust/deals/:id/underwrite | Run underwriting |
| POST | /api/foretrust/deals/:id/memo | Generate IC memo |
| POST | /api/foretrust/deals/:id/pipeline | Run full pipeline |

### 3.2 Request/Response Examples

#### Create Deal
```json
POST /api/foretrust/deals
{
  "name": "Walgreens - Austin TX",
  "source_type": "pdf",
  "content": "Offering Memorandum text content..."
}

Response:
{
  "success": true,
  "data": {
    "id": "uuid-here",
    "name": "Walgreens - Austin TX",
    "status": "draft",
    "source_type": "pdf",
    "created_at": "2025-11-20T10:00:00Z"
  }
}
```

#### Get Complete Deal
```json
GET /api/foretrust/deals/:id

Response:
{
  "success": true,
  "data": {
    "deal": { ... },
    "propertyAttributes": { ... },
    "leaseTerms": { ... },
    "scores": { ... },
    "financials": { ... },
    "enrichment": { ... },
    "memos": [ ... ]
  }
}
```

## 4. LLM Integration

### 4.1 Prompt Architecture

Six specialized prompts power the AI pipeline:

| Prompt | Input | Output |
|--------|-------|--------|
| OM/URL Parsing | Raw document text | Structured JSON (property, tenant, financials) |
| Data Enrichment | Parsed data | Market, geocode, tenant credit data |
| Underwriting | All deal data | Scores, metrics, risk flags |
| IC Memo | Complete deal | Markdown memo with recommendation |
| Portfolio Insights | Multiple deals | Portfolio-level analysis |
| Score Explainability | Scores | Human-readable explanations |

### 4.2 OpenAI Configuration

```typescript
{
  model: "gpt-4-turbo-preview",
  temperature: 0.3,  // Lower for consistency
  max_tokens: 4000,
  response_format: { type: "json_object" }  // For structured outputs
}
```

## 5. File Structure

```
foretrust/
├── backend/
│   ├── db/
│   │   └── schema.sql          # PostgreSQL schema
│   ├── prompts/
│   │   └── index.ts            # LLM prompt templates
│   ├── routes/
│   │   └── deals.ts            # API route handlers
│   ├── services/
│   │   ├── database.ts         # Supabase + mock fallback
│   │   └── openai.ts           # OpenAI integration
│   └── index.ts                # Express router setup
├── docs/
│   ├── PRD.md                  # Product requirements
│   └── TDD.md                  # Technical design (this file)
└── frontend/                   # (located in src/foretrust/)

src/foretrust/
├── components/                 # Shared UI components
├── hooks/
│   └── useForetrust.ts        # API hooks
├── pages/
│   ├── ForetrustDashboard.tsx # Deal list view
│   ├── ForetrustNewDeal.tsx   # Create deal form
│   └── ForetrustDealDetail.tsx# Deal detail view
└── types/
    └── index.ts               # TypeScript interfaces
```

## 6. Data Flow

### 6.1 Full Pipeline Flow

```
1. CREATE DEAL
   User submits PDF content/URL/manual data
   └─> POST /api/foretrust/deals
       └─> Creates deal with status "draft"

2. INGEST
   └─> POST /api/foretrust/deals/:id/ingest
       └─> LLM parses document
       └─> Saves property attributes, lease terms, financials
       └─> Status → "ingested"

3. ENRICH
   └─> POST /api/foretrust/deals/:id/enrich
       └─> LLM generates enrichment data
       └─> Saves geocode, market, tenant data
       └─> Status → "enriched"

4. UNDERWRITE
   └─> POST /api/foretrust/deals/:id/underwrite
       └─> LLM calculates scores and metrics
       └─> Saves scores, financials, risk flags
       └─> Status → "underwritten"

5. MEMO
   └─> POST /api/foretrust/deals/:id/memo
       └─> LLM generates IC memo
       └─> Saves memo with recommendation
       └─> Status → "memo_generated"
```

### 6.2 Mock Data Fallback

When Supabase is unreachable (e.g., proxy-blocked environments):

```typescript
async function getClient(): Promise<SupabaseClient | null> {
  // Test connection first
  const canConnect = await testSupabaseConnection();
  if (!canConnect) {
    console.log('🔶 Supabase blocked, using mock data');
    useMockData = true;
    return null;
  }
  // ... create Supabase client
}
```

Mock store provides 3 sample deals with complete data for demonstration.

## 7. Security Considerations

### 7.1 Row-Level Security (Production)

```sql
-- Enable RLS
ALTER TABLE ft_deals ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only access their organization's deals
CREATE POLICY "org_isolation" ON ft_deals
  FOR ALL USING (organization_id = get_user_org_id());
```

### 7.2 MVP Security (Disabled for Demo)

```sql
-- Disable RLS for MVP testing
ALTER TABLE ft_deals DISABLE ROW LEVEL SECURITY;

-- Grant anon access
GRANT ALL ON ft_deals TO anon;
```

### 7.3 Environment Variables

```env
VITE_SUPABASE_URL=https://xxx.supabase.co
VITE_SUPABASE_ANON_KEY=eyJ...
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-4-turbo-preview
```

## 8. Deployment

### 8.1 Development

```bash
npm install
npm run dev  # Starts frontend (5000) + backend (3001)
```

### 8.2 Production Checklist

- [ ] Enable RLS policies
- [ ] Remove anon grants
- [ ] Set production Supabase project
- [ ] Configure rate limiting
- [ ] Set up error monitoring (Sentry)
- [ ] Configure CORS for production domain

## 9. Future Enhancements

| Feature | Priority | Description |
|---------|----------|-------------|
| PDF Upload | P1 | Direct PDF file upload with OCR |
| Real API Integration | P1 | CoStar, D&B, Google Maps APIs |
| Portfolio Analytics | P2 | Cross-deal analysis and reporting |
| Deal Comparison | P2 | Side-by-side deal comparison |
| Email Alerts | P3 | Notifications for deal updates |
| Mobile App | P3 | React Native companion app |

---

*Document Version: 1.0*
*Last Updated: November 2025*
