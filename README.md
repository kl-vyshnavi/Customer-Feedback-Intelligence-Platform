# Customer Feedback Intelligence Platform

A local-first MVP for small businesses that need to turn customer reviews and support feedback into evidence-backed priorities. It is not a chatbot: the main workflow is upload, validate, classify, group, rank, review, and export.

## Product scope

- **Target user:** owner-operators and small customer-experience teams without a dedicated analytics function.
- **Problem:** feedback is split across reviews, surveys, and support tools; recurring issues are hard to quantify and prioritize.
- **MVP:** CSV preview/import, deterministic feedback classification, similarity-based issue groups, transparent priority scores, corrections, evidence-linked recommendations, dashboard filters, and CSV export.
- **Alternatives and trade-offs:** spreadsheets are flexible but make recurring patterns and repeatable scoring manual; general-purpose sentiment dashboards often stop at sentiment; a hosted LLM can give richer labels but adds cost and dependency. This MVP starts with explainable rules and makes an optional LLM provider explicit.
- **Assumptions:** one local workspace, CSV is the first source, ratings are on a 1–5 scale, and customers can interpret a transparent score better than an opaque model-generated priority.
- **Success measures to instrument:** import success/rejection/duplicate rates, classification corrections, time to process an import, and measured label quality on the evaluation set. No performance or quality results are claimed until measured.

## Architecture

```text
frontend/  React + TypeScript + Vite + Tailwind CSS + Recharts
    │ typed REST calls (VITE_API_URL)
backend/   FastAPI + Pydantic + SQLAlchemy + SQLite
    ├── services/imports.py       CSV validation and staging
    ├── services/classifier.py    validated AI response / deterministic fallback
    └── services/prioritization.py TF-IDF cosine clusters and explainable scores
```

Original feedback is stored separately from derived classifications. A classification keeps both the initial prediction and current corrected values; each manual change is recorded in correction history. Import batches retain a preview until the user confirms it. Issue membership connects a group to the actual feedback records used as evidence.

### Priority formula

Every component is normalized to 0–1, then the weighted components are normalized to sum to 1:

`score = 100 × (0.30 × frequency + 0.25 × severity + 0.15 × recency + 0.20 × negative_sentiment + 0.10 × rating)`

- Frequency is issue count divided by the largest issue count in the same ranking.
- Severity maps low/medium/high to 1/3, 2/3, and 1.
- Recency is the mean of `1 / (1 + age_days / 30)` for dated records; missing dates use 0.5.
- Negative sentiment is the negative share within the issue.
- Rating is the mean of `(5 - rating) / 4`; missing ratings use 0.5.
- Thresholds are high ≥ 70, medium ≥ 45, otherwise low.

Weights and the TF-IDF cosine threshold are environment-configurable. The score is a prioritization aid, not a measured business outcome.

## Setup

Requirements: Python 3.11+ and Node.js 20+.

1. Copy `.env.example` to `.env` in the project root (PowerShell: `Copy-Item .env.example .env`); keep the default rule provider for offline use.
2. In `backend/`, create and activate a virtual environment, then install:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements-dev.txt
   uvicorn app.main:app --reload
   ```

3. In a separate terminal, install and start the frontend:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

4. Open `http://localhost:5173`. FastAPI's Swagger UI is at `http://localhost:8000/docs`.

The SQLite database is created on first backend startup. Set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL when migrating; this MVP does not include production migrations.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./feedback.db` | SQLAlchemy database |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | Single allowed browser origin |
| `UPLOAD_MAX_BYTES` | `5242880` | CSV upload size limit |
| `LLM_PROVIDER` | `rule` | Set to `openai` to enable optional provider |
| `OPENAI_API_KEY` | unset | Provider credential; never commit it |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model used with the OpenAI-compatible provider |
| `CLUSTERING_THRESHOLD` | `0.30` | TF-IDF cosine similarity threshold |
| `PRIORITY_WEIGHT_*` | `0.30, 0.25, 0.15, 0.20, 0.10` | Frequency, severity, recency, negative sentiment, rating |

When AI is enabled, provider calls time out, use bounded retries, validate returned JSON with Pydantic, and reject evidence that is not copied from the original feedback. Provider failures fall back to deterministic rules; the API records which provider produced the classification. Uploaded feedback is sent to the configured provider only when AI is explicitly enabled.

## API overview

All routes are under `/api/v1`; request and response schemas are documented in Swagger.

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/imports/sample.csv` | Download a sample CSV |
| POST | `/imports/preview` | Validate CSV, stage rows, return preview |
| POST | `/imports/confirm` | Import a preview by `batch_id` |
| GET | `/imports` | Import history |
| GET | `/feedback` | Filter and paginate feedback |
| GET/PATCH | `/feedback/{id}` | View/correct a classification |
| GET | `/dashboard` | Filter-aware summary and issue rankings |
| GET | `/issues`, `/issues/{id}` | Priorities, supporting feedback, recommendations |
| GET | `/recommendations` | Evidence-linked actions and feedback record IDs |
| GET | `/exports/feedback.csv` | Export feedback with the active filters |
| GET | `/exports/issues.csv` | Export issue priorities and actions |

CSV text aliases include `feedback`, `review`, `comment`, `message`, and `content`. For other column names, pass a multipart `mapping` JSON object, for example `{"text":"review_body","date":"submitted_on","rating":"stars"}`.

## Tests and evaluation

```powershell
cd backend
pip install -r requirements-dev.txt
pytest
cd ..\frontend
npm install
npm test
npm run build
```

`backend/evaluation/labels.csv` is a small manually labeled starter dataset. Run `python -m evaluation.run_evaluation` from `backend/` to calculate accuracy and macro precision/recall/F1 for sentiment, category, and severity. On the included four examples, the current rule baseline measured 1.000 accuracy and macro-F1 for each of the three tasks. This tiny, deliberately illustrative set is a smoke test—not a statistically representative quality claim.

## Limitations and next steps

- This is a local MVP, not a hosted multi-tenant service. There is no authentication, authorization, migrations, or production deployment hardening.
- The keyword classifier is deliberately modest; its labels and confidence are only a baseline, not calibrated probabilities.
- TF-IDF cosine similarity is a lexical baseline and can miss paraphrases or over-group generic wording. The current issue editor/merge/split workflow is not implemented.
- Recommendation text is a hypothesis and must be reviewed by a person. It does not claim that a business outcome changed.
- Dashboard plots summarize dated records; missing dates cannot contribute to trends.
- Future improvements: user-managed issue merges/splits, configurable weighting UI, a measured classification evaluation report, background jobs for larger imports, PostgreSQL migrations, and authenticated multi-user workspaces.
