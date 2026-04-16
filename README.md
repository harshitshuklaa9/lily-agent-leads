# Lily Agent — AI Lead Generation Pipeline

An autonomous 5-agent pipeline that finds qualified B2B leads from trade show exhibitor lists, scores them against a configurable ICP, finds the right contacts, and writes personalised outreach emails.

**Built for DuPont Tedlar** — finds graphics & signage companies that buy protective overlaminate films.

🟢 **Live dashboard:** [lilyagent.vercel.app](https://lilyagent.vercel.app)

---

## How It Works

```
Trade Shows → Exhibitor Lists → ICP Scoring → Contacts → Outreach Emails
```

| Step | Agent | What it does |
|---|---|---|
| 1 | ResearchAgent | Finds relevant trade shows + MapYourShow exhibitor gallery URLs |
| 2 | DiscoveryAgent | Scrapes exhibitor pages with Playwright, extracts company names |
| 3 | EnrichmentAgent | Researches each company, scores against ICP (0.0–1.0) |
| 4 | StakeholderAgent | Finds technical + business buyer contacts via LinkedIn |
| 5 | OutreachAgent | Writes personalised cold emails (on-demand, via dashboard) |

**Sample results from first run:**

| Company | ICP Score |
|---|---|
| Avery Dennison | 1.000 |
| ORAFOL | 1.000 |
| 3M | 0.970 |
| Mimaki | 0.955 |
| Roland DG | 0.885 |
| Arlon | 0.825 |

---

## Stack

| Layer | Technology |
|---|---|
| Agents | Python + OpenAI (GPT-4o / GPT-4o-mini) |
| Web scraping | Playwright (headless Chromium) |
| Web search | Serper API |
| Database | Supabase (PostgreSQL) |
| API | FastAPI + Uvicorn |
| Dashboard | React + TypeScript + Tailwind CSS |
| Hosting — API | Railway |
| Hosting — Dashboard | Vercel |

---

## ICP Scoring

Each company gets a composite score weighted across four signals:

```
icp_score = (industry_fit       × 0.40)
           + (revenue_tier       × 0.25)
           + (event_confirmation × 0.20)
           + (product_overlap    × 0.15)
```

Companies scoring ≥ 0.7 are shown in the dashboard. All weights and thresholds are configurable in `config.json`.

---

## Adapting for a Different Industry

**Only `config.json` needs to change.** No agent code modifications required.

```json
{
  "seller": { "company": "...", "product": "...", "value_props": [...] },
  "icp": { "description": "...", "ideal_signals": [...], "icp_score_threshold": 0.7 },
  "research": { "seed_events": [...], "industry": { "verticals": [...] } },
  "stakeholders": { "technical_buyer_titles": [...], "business_buyer_titles": [...] }
}
```

Then run: `python3 main.py --fresh`

---

## Smart Mode (Idempotent Pipeline)

The pipeline checks Supabase before every step — it only processes new data.

| Step | Skipped when |
|---|---|
| ResearchAgent | Events in DB newer than 7 days |
| DiscoveryAgent | Event already has companies in DB |
| EnrichmentAgent | Company already scored within 30 days |
| StakeholderAgent | Lead already has contacts within 14 days |

Running daily costs almost nothing. Use `--fresh` to force a full re-run.

---

## Running Locally

```bash
git clone https://github.com/harshitshuklaa9/lily-agent-leads
cd lily-agent-leads

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env   # add your API keys

# Full pipeline
python3 main.py

# Stop after a specific step
python3 main.py --step enrich

# Force full re-run
python3 main.py --fresh

# API server
uvicorn api:app --reload

# Dashboard (separate terminal)
cd dashboard && npm install && npm run dev
```

---

## Environment Variables

### Railway (API server) — required:
```
OPENAI_API_KEY       = sk-proj-...
SERPER_API_KEY       = ...
SUPABASE_URL         = https://your-project.supabase.co
SUPABASE_SERVICE_KEY = eyJhbGci...
FRONTEND_URL         = * (or your Vercel URL to lock CORS)
```

### Railway — contact enrichment providers (optional):
By default the pipeline finds contacts via LinkedIn/Google search.
To upgrade to a verified data provider, set one of these keys in Railway Variables.
The pipeline uses the first one found, in priority order:

```
LINKEDIN_SALES_NAV_TOKEN = AQV...      # LinkedIn Sales Navigator API
CLAY_API_KEY             = clay_...    # Clay people search
APOLLO_API_KEY           = ...         # Apollo.io (free tier: 50 credits/mo)
```

No code changes needed — just add the key and redeploy.

### Vercel (dashboard):
```
VITE_API_URL = https://your-railway-app.up.railway.app
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/leads` | All leads with contacts, ordered by ICP score |
| POST | `/contacts/{id}/outreach` | Generate outreach email on-demand |
| PATCH | `/contacts/{id}/outreach` | Save manually edited subject/body |
| POST | `/pipeline/run` | Trigger pipeline in background |
| GET | `/pipeline/status` | `{"running": true/false}` |
| GET | `/integrations` | Which providers are connected |
| POST | `/integrations` | Connect a provider API key |
| DELETE | `/integrations/{provider}` | Disconnect a provider |

---

For full architecture details see [ARCHITECTURE.md](./ARCHITECTURE.md).
