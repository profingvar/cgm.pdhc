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

## 2026-10-15 — #708 sibling smoke
- deploy/smoke_siblings.py  (NEW: 8 read-only checks against the configured upstream, which is gateway)

#930 — bare `postgresql://` DSN converted to `+psycopg2` (2026-11-05)
---------------------------------------------------------------------
/Users/martiningvar/T7_sidewinder/cgm.pdhc/cgm_portal/docker-compose.yml:25

SQLAlchemy==2.0.50 pinned. Note `requirements.txt` already carried #785's
comment block EXPLAINING this exact mitigation while the compose did not
apply it — a documented mitigation is not an applied one.

WHY. SQLAlchemy 2.1 resolves a bare `postgresql://` to psycopg **v3** (#711).
This service installs `psycopg2-binary` and not psycopg v3, so a bare scheme
lets the INSTALLED SQLAlchemy pick a driver that is absent and the app
crash-loops on the next `--build`. Verified it passes nothing to a raw
`psycopg2.connect()` (which cannot parse a `+driver` scheme) — the DSN goes to
SQLAlchemy only.

NOT DEPLOYED and nothing regresses without it: a config-only compose change
needs `docker-compose up -d` WITHOUT `--build`. The deployed compose still has
to be compared (#940) — gateway's deployed copy already said `+psycopg2` while its
repo copy did not, which is how this drift was found at all.

Guarded by `tools/audit_dsn_drivers.py` (exit 1 on any bare DSN, 20 paired
tests). The claim "all 21 services now use +psycopg2 explicitly (#711)" was
false for 11 files; a hand survey cannot be the gate here.

#941 — pdhc_keyauth is version-controlled at last (2026-11-05)
--------------------------------------------------------------
NO FILE IN THIS REPO CHANGED. Recorded here because this service's auth comes
from a directory outside it.

`cgm.pdhc/pdhc_keyauth` is a symlink to `~/T7_sidewinder/pdhc_keyauth`, which held
680 lines of Flask auth code under NO version control from 2026-04-05 until
now — tracked by no repo, invisible to `git status`. It is a git repo of its
own as of 355016e, with a README carrying the measurements.

Nothing changed at runtime: same inode, symlink untouched, and this suite is
green afterwards. No production change either — the one unreleased fix in
there (#563's idempotent `define_models`) is test-only, because a deployed
process calls `create_app()` once per gunicorn worker.

Worth knowing about this service specifically: on miserver the three consumers
have THREE INDEPENDENT real directories, not symlinks, all holding the
pre-#563 copy. So a fix made on the Mac does not propagate to production here,
and a fix made in production to one service does not reach the other two.

Open: whether to consume it as a submodule or a package. This line used to say
"#943 holds that decision, since it is the same question as the 14 modules
copied across repos". #943 was CLOSED 2026-11-06 with its premise disproved:
there is no 14-module problem (its largest group was Flask-Migrate's generated
migrations/env.py, in 14 repos), session_headers.py has ONE code variant across
seven repos rather than four, and the copies are a documented deliberate choice.
So pdhc_keyauth is now the only live instance of this question and must be
decided on its own merits. See CLAUDE.md §4.


--- 2026-11-06 — #945: key revocation/expiry had NO test coverage ---

cgm_portal/tests/test_security.py        NEW

Found while measuring #943's module duplication, not by looking for it.
cgm's app/api/auth.py, app/api/keys.py and app/models/api_key.py are
BYTE-identical to provider.pdhc's (same sha256), but cgm had 38 test functions
to provider's 97, no tests/test_security.py at all, and ZERO tests mentioning
revocation, expiry or rotation. cgm is a PUBLIC repo authenticating with API
keys.

STEP 1 FIRST, and it decided what this ticket was. The control was probed
before anything was ported: it HOLDS. AccessSessionService.authenticate()
calls ApiKey.is_valid() and raises AUTH_INVALID 401 on a revoked or expired
key, reached over a real request. So this was test debt, not an incident —
which is why nothing stronger was filed (the withdrawn #844 is the cost of
getting that order wrong).

Ported provider's six tests. Fixture names are identical in both conftests, so
no renaming was needed. Added TWO CONTROLS that provider's file does not have:

  test_CONTROL_unrevoked_unexpired_key_is_accepted
  test_CONTROL_future_expiry_is_accepted

The second is the one that matters: without it, test_expired_key_rejected would
pass unchanged against an implementation that refused ANY key carrying an
expires_at, regardless of date.

MUTATION-TESTED, three mutations, each restored under a sha256 gate:

  M1  is_valid() always True            -> 4 fail (revoked, expired, revocation, rotation)
  M2  authenticate() drops is_valid()   -> 4 fail, same four
  M3  expiry check removed only         -> 1 fail (expired only)

M3 is the sharp one: the tests discriminate between the two halves of the
control rather than asserting one blunt thing. Both CONTROL tests kept passing
under every mutation, which is correct — they assert acceptance, and the
mutations only loosen rejection.

THE MUTATION FOUND A HOLE IN PROVIDER'S ORIGINAL, which had been ported
verbatim. test_key_rotation_api did NOT fail under M1 or M2: it asserts
`api_key.revoked is True`, a FIELD VALUE, and never that the old secret is
refused. Rotation's entire security value is the latter. Strengthened here and
in provider.pdhc (same one-assertion fix).

Suite: 38 -> 46 passed. provider: 97 passed, unchanged count (an assertion was
added, not a test).

NOT done here: provider's other seven cgm-absent test files. They cover code
that has DRIFTED between the two services (23 of 46 shared files), so they are
not drop-in. #946.


--- 2026-11-06 — #946 step 1: this repo is one half of a DELIBERATE fork ---

No files changed. Measurement only, recorded because the next person to edit a
shared file needs it.

cgm.pdhc and provider.pdhc are one codebase forked into two repos: same layout
under two top names, distinct inodes, no symlinks. 46 tracked .py files share a
relative path — 23 have IDENTICAL code, 23 have DRIFTED.

Step 1 asked whether the drift is deliberate feature work or accidental edit
drift. It is deliberate, and the evidence is that the vocabularies are DISJOINT:

  monitoring     cgm 51 occurrences in 11 files   provider 0
  in_progress    cgm 0                            provider 2
  observe        cgm 25 in 6 files                provider 0
  monitoring_interval_seconds / total_observations_submitted / last_observation_at
                 cgm 5 / 15 / 9                   provider 0 / 0 / 0

A half-finished rename leaves BOTH vocabularies in one repo. These do not
overlap at all. cgm also carries four extra provider_task columns for
continuous monitoring, so converging would undo real feature work.

The three equal-length drifted files, diffed in full: tests/conftest.py differs
only in a fixture NAME, and app/models/task_audit_log.py and
app/services/report_submission.py each differ by one domain word
('observe' in VALID_ACTIONS; 'monitoring' vs 'in_progress' in the accepted
status tuple). No accidental drift among them.

TWO INSTRUMENT ERRORS WORTH NOT REPEATING. Both repos have an UNTRACKED venv/
inside <name>_portal/, so a `grep --include='*.py'` of the directory counts
pygments' own keyword lists — that is how a first pass reported 'observe' in
provider, where there is none. Count on `git ls-files`. And the first control
chosen was 'observe' itself, which appears in only one repo, so it could not
prove the reader had opened the other repo's files at all; replaced with real
positive controls (acknowledge 55, dispatched 55, receipt_token 247 in
provider) and a negative one (a nonsense symbol, 0 in both).

THE RULE THIS ESTABLISHES. The 23 identical files are shared infrastructure —
app/api/auth.py, app/api/keys.py, app/models/api_key.py, audit.py, receipt.py,
sync_state.py, access_session.py and the rest — kept byte-identical by hand with
nothing recording that they must be. MIRROR a change to those. Do NOT mirror
the drifted 23; the two services mean different things by that code.

#945 the same day is the live precedent: a test written for cgm exposed a weak
assertion in provider's identical module, and the fix went into both. Restoring
those modules produced the same sha256 in each repo (api_key.py 54b0059bf189,
access_session.py 12b3c98bbaee) — a cheap way to check a file is still shared.

RATIFIED by the operator 2026-11-06: the two services DIVERGE. The drifted 23
are deliberate domain difference, not debt, and are not to be reconciled. The
identical 23 REMAIN a hand-mirrored shared set — ratifying divergence did not
dissolve them, so "diverge" does not mean "mirror nothing". Replacing the hand
with a mechanism is a separate decision. Recorded in CLAUDE.md §4.
