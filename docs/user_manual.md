# cgm.pdhc — User manual

cgm.pdhc is the **CGM (continuous glucose monitor) provider portal** for the
PDHC platform — the "provider side" for glucose-monitoring devices (Abbott
FreeStyle and similar). When the platform needs a patient's glucose monitored
over a period, it sends this service an order; the provider acknowledges it,
collects glucose readings across the monitoring window, and streams them back
into the platform.

Live at **https://cgm.pdhc.se**. It has two faces: a **web portal** for human
operators, and a **REST API** for device/system integration.

---

## 1. What it does, in plain terms

```
request.pdhc ──(monitoring order)──►  cgm.pdhc  ──(glucose readings, in batches)──►  gateway.pdhc ──► platform dashboards
```

1. **An order arrives.** `request.pdhc` pushes a monitoring order — a patient
   who needs continuous glucose monitoring over a window (e.g. 14 days).
2. **The provider acknowledges it** and monitoring begins.
3. **Readings are collected and submitted in batches** for the whole window.
4. **Each batch is forwarded to `gateway.pdhc`**, which validates, enriches,
   and stores it so it shows up on the platform's dashboards.
5. **When the window ends, a "completed" status is sent.**

Each deployment is **one provider** (its identity is fixed in configuration).

### Built-in glucose simulator (out of the box)

This instance ships with a **glucose simulator**. The moment you acknowledge
an order, it **automatically starts generating one realistic reading per
minute** (a gentle random walk around 5.5 mmol/L, clamped to a safe range) and
submitting it, until you complete monitoring. So readings flow **without a
real device** — handy for demos and testing. An operator can also push real
readings via the API instead.

---

## 2. Using the web portal

Log in at `https://cgm.pdhc.se/login` (username + key; the first admin is
bootstrapped at deploy). The portal gives you:

- **Dashboard** (`/`) — tasks by state (dispatched / monitoring / completed),
  receipts, active glucose streams, and sync status at a glance.
- **Tasks** (`/tasks`) — incoming monitoring orders; open one to see its audit
  trail, the original request, live stream status, and the batch log.
  - **Acknowledge** — the key action: starts monitoring (and the simulated
    stream). Flash: *"Task acknowledged — glucose stream started."*
  - **Complete monitoring** — stops the stream and sends the final status.
- **Receipts / Gateway receipts** — proof each batch was accepted downstream.
- **Audit** — full operation log.
- **Docs** — the technical guide (downloadable).
- **Users** (admin) and **Trigger sync**.

**Task lifecycle:** `dispatched → acknowledged → monitoring → completed`.

---

## 3. Using the API (integrators)

All API calls use the `X-API-Key` header (keys are scoped `read` / `write`).
Base path `/api/v1`. The essentials:

| Do this | Call |
|---|---|
| Check health (no auth) | `GET /api/v1/health` → `{status, database, service}` |
| List my tasks | `GET /api/v1/provider-tasks/my` |
| Acknowledge / start monitoring | `POST /api/v1/provider-tasks/<token>/accept` |
| **Submit a batch of readings** | `POST /api/v1/provider-tasks/<token>/observe` |
| End monitoring | `POST /api/v1/provider-tasks/<token>/observe/complete` |
| Stream status / batch log | `GET …/observe/status`, `GET …/observe/log` |

A reading batch looks like this — send `transaction_guid`, `value`,
`recorded_at`; **do not** send the concept or unit, the gateway derives those
from the care plan:

```
POST /api/v1/provider-tasks/<token>/observe
X-API-Key: <write-key>
{ "observations": [
    { "transaction_guid": "tx-glucose-001", "value": 5.6,
      "recorded_at": "2026-04-01T08:00:00Z" } ] }
```

Manage keys with `POST /api/v1/api-keys` (and `/revoke`, `/rotate`). A new
key's raw value is shown **once** — store it securely.

---

## 4. Access & onboarding

- **Human operators** log into the portal with a username + key.
- **API clients** use `X-API-Key` (create/rotate/revoke via the API).
- **Registering the provider instance itself** (its identity, provider access
  token, and push secret) is done by PDHC operations via the provider wire-up
  tooling — not something the day-to-day operator does.

---

## 5. Good to know

- The **only actions that matter operationally** are *Acknowledge* (start) and
  *Complete* (stop) — everything in between is automatic (simulator) or
  pushed by your device integration.
- Glucose readings carry a `transaction_guid` linking each one to the care
  plan; the platform derives the glucose concept and unit (mmol/L) from that
  context, so you never send them.
- Every batch is acknowledged by the gateway with a **receipt** — check the
  Receipts page (or `GET /api/v1/provider-receipts`) if you need proof.
- For endpoints, the ingest/forward chain, config, and deployment, see the
  **technical manual** (link at the top of this page — with a **Download
  (Markdown)** button).
