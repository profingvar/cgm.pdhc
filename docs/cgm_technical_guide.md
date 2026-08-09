# CGM Portal — Technical Integration Guide

> Continuous Glucose Monitoring provider for the PDHC ecosystem.
> Receives ServiceRequests describing monitoring procedures, delivers
> continuous observation batches via gateway.pdhc.

---

## 1) Architecture overview

```
                    PDHC Platform                         CGM Provider Side
                    ─────────────                         ─────────────────

              ┌──────────────────┐
              │  request.pdhc    │
              │  (orchestrator)  │
              └──────┬───────────┘
                     │
           ┌─────────┴──────────┐
           │                    │
      Push delivery        Poll/Subscribe
      (Type 1)             (Type 2)
           │                    │
           ▼                    ▼
    POST /inbound/push    GET /provider/feed  ──►  GET /provider/download/<sr>
           │                    │                          │
           └────────┬───────────┘                          │
                    │                                      │
                    ▼                                      ▼
              ┌──────────────────┐              ┌──────────────────┐
              │  cgm.pdhc        │              │  FHIR Bundle     │
              │  (portal)        │              │  + grant_token   │
              └──────┬───────────┘              └──────────────────┘
                     │
                     │  Continuous observation batches
                     │  (multiple over monitoring period)
                     │
                     ▼
              POST /provider/report/<sr>
              status='in-progress' (each batch)
              status='completed' (final)
                     │
                     ▼
              ┌──────────────────┐
              │  gateway.pdhc    │  ◄── validates, enriches, stores
              │  derives context │      observation data for dashboard
              └──────────────────┘
```

---

## 2) How CGM differs from other providers

| Aspect | provider.pdhc | 1177.pdhc | cgm.pdhc |
|--------|--------------|-----------|----------|
| Input | ServiceRequest + CarePlan | ServiceRequest + Questionnaire | ServiceRequest + Procedure |
| Output | One-shot report | QuestionnaireResponse | Continuous observation batches |
| Task lifecycle | dispatched → acknowledged → completed | pending → opened → completed | dispatched → acknowledged → monitoring → completed |
| Gateway status | `completed` (once) | `completed` (once) | `in-progress` (per batch) → `completed` (final) |
| Observation count | Single batch | N/A (FHIR QR) | Multiple batches over monitoring period |

---

## 3) Task lifecycle

```
dispatched ──► acknowledged ──► monitoring ──► completed
                                   │
                          (submit batches via
                           POST /observe)
```

- **dispatched** — SR received, not yet acknowledged
- **acknowledged** — CGM device activated, ready to collect data
- **monitoring** — Active data collection; observation batches being submitted
- **completed** — Monitoring period ended; final status sent to gateway

---

## 4) Authentication

Identical to provider.pdhc. See provider_technical_guide.md Section 2.

- **Local API keys** — `X-API-Key` header, bcrypt-hashed, scoped (read/write)
- **PAT** — `X-Provider-Token` for upstream communication
- **Push secret** — `X-Push-Secret` for inbound FHIR Bundle reception
- **Gateway service key** — `X-Service-Key` for receipt ingestion

---

## 5) Submitting observations (continuous)

### 5.1 Submit an observation batch

```http
POST /api/v1/provider-tasks/{receipt_token}/observe
X-API-Key: <local-key>
Content-Type: application/json

{
  "observations": [
    {
      "transaction_guid": "tx-glucose-001",
      "value": 5.6,
      "recorded_at": "2026-04-01T08:00:00Z"
    },
    {
      "transaction_guid": "tx-glucose-001",
      "value": 6.1,
      "recorded_at": "2026-04-01T08:15:00Z"
    },
    {
      "transaction_guid": "tx-glucose-001",
      "value": 5.8,
      "recorded_at": "2026-04-01T08:30:00Z",
      "notes": "Post-meal reading"
    }
  ]
}
```

**Response** (202):

```json
{
  "batch_number": 3,
  "observation_count": 3,
  "gateway_status": "delivered",
  "task_status": "monitoring",
  "total_observations_submitted": 3
}
```

**Per observation, send only:**

| Field | Required | Description |
|-------|----------|-------------|
| `transaction_guid` | yes | Links to a transaction in the SR's CarePlan |
| `value` | yes | The measured value |
| `recorded_at` | yes | ISO-8601 timestamp of measurement |
| `notes` | no | Free-text note (omit if empty) |

**Do NOT send** `concept_guid` or `unit` — gateway derives these from SR context.

### 5.2 Complete monitoring

```http
POST /api/v1/provider-tasks/{receipt_token}/observe/complete
X-API-Key: <local-key>
Content-Type: application/json

{
  "notes": "14-day monitoring period completed normally"
}
```

### 5.3 View observation batch log

```http
GET /api/v1/provider-tasks/{receipt_token}/observe/log?limit=50
X-API-Key: <local-key>
```

---

## 6) Gateway submission details

Each observation batch is submitted to gateway.pdhc as a **minimal payload**:

```json
{
  "patient_guid": "pat-001",
  "grant_token": "a1b2c3...",
  "status": "in-progress",
  "report_payload": {
    "observations": [
      {
        "transaction_guid": "tx-glucose-001",
        "value": 5.6,
        "recorded_at": "2026-04-01T08:00:00Z"
      }
    ]
  }
}
```

- Batches use `status: "in-progress"` — this skips obligatory concept enforcement
- Final completion uses `status: "completed"` with a monitoring summary
- Gateway validates each batch through its 10-step chain (PAT → grant → SR context → enrich → validate → scope → store)

---

## 7) Data model extensions

### ObservationLog (new)

| Column | Type | Purpose |
|--------|------|---------|
| `guid` | UUID | Unique identifier |
| `receipt_token` | String | Links to task |
| `batch_number` | Integer | Sequential per task |
| `observation_count` | Integer | Items in this batch |
| `payload_hash` | SHA-256 | Deduplication |
| `gateway_status` | String | delivered/failed/pending |
| `gateway_error` | Text | Error message if failed |
| `submitted_at` | DateTime | When batch was sent |

### ProviderTask extensions

| Column | Type | Purpose |
|--------|------|---------|
| `monitoring_interval_seconds` | Integer | Expected submission interval |
| `monitoring_until` | DateTime | End of monitoring period (from SR occurrencePeriod.end) |
| `last_observation_at` | DateTime | Most recent batch timestamp |
| `total_observations_submitted` | Integer | Running batch count |

---

## 8) Configuration

### Environment variables

```bash
# Instance identity
PROVIDER_GUID=<assigned-by-admin>
PROVIDER_NAME="CGM Device Provider"

# Flask
FLASK_PORT=9080
DATABASE_URL=postgresql://cgm_portal:cgm_portal_dev@localhost:9081/cgm_portal_db

# Upstream
REQUEST_SERVICE_URL=https://request.pdhc.se/api/v1
PROVIDER_TOKEN=<pat-from-admin>

# Push reception
PUSH_SECRET=<shared-secret>

# Gateway receipt ingestion
GATEWAY_SERVICE_KEY=<internal-key>

# Sync
SYNC_ENABLED=true
SYNC_INTERVAL_SECONDS=60

# Bootstrap
BOOTSTRAP_API_KEY=<initial-admin-key>
```

### Ports

| Service | Port | Purpose |
|---------|------|---------|
| cgm_portal_app | 9080 | Flask REST API |
| cgm_portal_db | 9081 | PostgreSQL |

---

## 9) API endpoint reference

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET | `/api/v1/health` | — | Health check |
| GET | `/api/v1/provider-tasks/my` | read | List tasks |
| GET | `/api/v1/provider-tasks/{token}` | read | Get task |
| POST | `/api/v1/provider-tasks/{token}/accept` | write | Acknowledge task |
| **POST** | **`/api/v1/provider-tasks/{token}/observe`** | **write** | **Submit observation batch** |
| **POST** | **`/api/v1/provider-tasks/{token}/observe/complete`** | **write** | **End monitoring** |
| **GET** | **`/api/v1/provider-tasks/{token}/observe/log`** | **read** | **Batch history** |
| POST | `/api/v1/provider-tasks/{token}/report` | write | Final report (alternative) |
| GET | `/api/v1/provider-tasks/{token}/careplan-details` | read | Get careplan |
| GET | `/api/v1/provider-receipts` | read | Submission receipts |
| GET | `/api/v1/audit-log` | read | Audit trail |
| POST | `/api/v1/api-keys` | write | Create API key |
| POST | `/api/v1/api-keys/{guid}/revoke` | write | Revoke key |
| POST | `/api/v1/api-keys/{guid}/rotate` | write | Rotate key |
| POST | `/api/v1/inbound/push` | — | Push receiver (X-Push-Secret) |
| POST | `/api/v1/receipts/ingest` | — | Gateway receipt (X-Service-Key) |

Bold rows are CGM-specific endpoints.


---

## Onboarding & operations

This guide covers the **internals** of this service. The cross-cutting
integration with PDHC (SSO organisation registration, push secret,
Provider Access Token, contract binding, restart on env changes) is
handled by the wire-up tool described in:

- **`tools/ADDING_A_PROVIDER.md`** — step-by-step procedure for
  PDHC operations to bring a provider online or rotate its credentials.
- **`tools/wire_provider.py`** + **`tools/providers.yaml`** —
  the idempotent registry-driven tool that performs the wire-up.
- **`tools/NOTES.md`** — operational findings and pitfalls
  (gunicorn HUP, docker restart vs compose, nginx symlink edits,
  SSRF blocks).

When reasoning about deployment changes that affect environment
variables, restart pattern, or upstream auth, start there — the
registry entry for this provider should always reflect reality.

## Port Allocation

All ports bind to `127.0.0.1` (loopback only); external traffic arrives
via the reverse proxy.

| Port | Service |
|------|---------|
| 9080 | Flask application (Gunicorn) |
| 9081 | PostgreSQL database |
