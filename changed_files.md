# cgm.pdhc — Changed Files Log

Per Rule 17, all edited files are noted here with full path.

---

## 2026-04-11 — Receipt ingress fallback + gunicorn restart

| File | Change |
|------|--------|
| `/Users/martiningvar/T7_sidewinder/cgm.pdhc/cgm_portal/app/api/receipts.py` | Modified — `/api/v1/receipts/ingest` now accepts either `GATEWAY_SERVICE_KEY` **or** `PUSH_SECRET` as valid `X-Service-Key`. Previously returned 503 `not_configured` because `GATEWAY_SERVICE_KEY` was empty in prod `.env` while `PUSH_SECRET` was set. Now only returns 503 when *both* are empty. |
| `miserver:/usr/local/www/cgm.pdhc/cgm_portal/app/api/receipts.py` | Deployed via `scp` over the existing file. |
| `miserver:` gunicorn process | Manual restart — old master pid 13786 was stuck in a SIGKILL/worker-respawn loop after SIGHUP (same "Perhaps out of memory?" pattern seen earlier on gateway). `kill -TERM 13786`, then relaunched `gunicorn ... --daemon` from `/usr/local/www/cgm.pdhc/cgm_portal` with the same args. Fresh master pid 80568 with workers 80570/80571. nginx 504 on `https://cgm.pdhc.se/api/v1/receipts/ingest` cleared immediately after. |

### Verification

End-to-end replay of CGM → gateway.pdhc → cgm.pdhc receipt flow for SR `523d1227-132b-4d2a-8129-fdbb1519b039`:

- Gateway ingest POST returned HTTP 202.
- Gateway stored observation with `concept_guid = 1c34a590-fc2d-430c-92e6-d123b95fe392` (B-glucos measurement) and `resolution_status = resolved` — proves goal-concept enrichment works.
- cgm `gateway_receipts` table received receipt `31c6ccb5-0c8e-4e1e-a3d6-bb65377a0875` with `observations_stored: 1`.

## 2026-04-14 — CORS on health endpoint (ticket #38)

| File | Change |
|------|--------|
| `cgm_portal/app/__init__.py` | `/api/v1/health` now returns `Access-Control-Allow-Origin: *` and `Cache-Control: no-store`, plus a `service` field. Lets status dashboards (sso.pdhc landing, www.pdhc.se/services.html) read the JSON body cross-origin and drive their dots from the real `status` / `database` fields instead of opaque no-cors reachability. |

## 2026-04-15 — Hardened gunicorn launch in start.sh (ticket #41)

| File | Change |
|------|--------|
| `start.sh` | (1) Added graceful-stop block via pid file: `kill -TERM` on the previous master, wait up to 10 s, escalate to `KILL` only if needed. (2) Rewrote launch block to use `--daemon --pid` instead of `nohup ... &`, plus `--graceful-timeout 30`, `--max-requests 500`, `--max-requests-jitter 50` — the proven anti-OOM-loop flags. |
| `miserver:/usr/local/www/cgm.pdhc/start.sh` | Same file deployed; backup at `start.sh.bak-20260415T084207Z`. Exercised live: old master 69131 TERM'd cleanly, new master 1602 came up with workers 1604/1605, external health 200, no SIGKILL loop in error.log. |
| `cgm_portal/app/__init__.py` | Registered missing Jinja `\|local` template filter (UTC datetime → Europe/Stockholm). 5 templates (`dashboard.html`, `tasks.html`, `gateway_receipts.html`, `receipts.html`, `audit.html`) were using it, but the filter function was never shipped — every authenticated UI page returned HTTP 500 with `jinja2.exceptions.TemplateRuntimeError: No filter named 'local' found`. `/api/v1/health` kept returning 200, which masked the outage on services.html (CLAUDE.md §10 false-green). Added `_format_local()` with safe-None handling, registered via `app.add_template_filter()`. Deployed + restarted; smoke-test confirms filter resolves 2026-04-16 12:00Z → "2026-04-16 14:00:00" (CEST). Server backup at `/tmp/cgm_app_init.py.bak.20260416T143903Z`. |
| `cgm_portal/app/__init__.py` | Ticket #70 / CLAUDE.md §10: tightened existing CORS from `Access-Control-Allow-Origin: *` to the specific `https://www.pdhc.se`, added `Access-Control-Allow-Methods: GET` and `Vary: Origin`. Verified via `curl -I -H 'Origin: https://www.pdhc.se'`: all three headers + `cache-control: no-store`, body unchanged `{"database":"connected","service":"cgm.pdhc","status":"ok"}`. Server backup at `/tmp/cgm_init_batch2.py.bak.20260416T185418Z`. |

| 2026-07-13 | docs/user_manual.md (new) | Authored layman user manual (technical guide already existed); published on pdhc.se/documentation.html. |
- cgm.pdhc/docs/cgm_technical_guide.md (Port Allocation section)
