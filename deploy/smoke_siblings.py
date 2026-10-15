#!/usr/bin/env python3
"""cgm.pdhc — does every call to a SIBLING service actually work? (#708)

Run it INSIDE the container, which is the only place the real credentials and
the real network names exist:

    docker exec cgm_portal_app python deploy/smoke_siblings.py
    docker exec cgm_portal_app python deploy/smoke_siblings.py --json

READ-ONLY. It creates nothing, writes nothing, acknowledges nothing and pushes
no status, so it is safe against production at any time.

## What cgm calls, and the one thing to know about the name

ONE sibling, through ONE config key, and the key is misleading:

    REQUEST_SERVICE_URL  defaults to  https://gateway.pdhc.se/api/v1

It is called `REQUEST_SERVICE_URL` and it points at **gateway**, not at
request.pdhc. Every path below is therefore a gateway path:

    /provider/feed                  the work queue
    /provider/download/<sr>         the bundle
    /provider/report/<sr>           the report (live)
    /provider/receipt/<tok>/ack     acknowledgement
    /requests[, /<g>/status]        the LEGACY fallback gateway no longer serves

So a check that read the NAME and probed request.pdhc would be probing a
service cgm never calls, and would pass or fail for reasons unrelated to cgm.
The checks below read the configured value and report which host it actually
resolves to.

## Why a smoke here

cgm is an EXTERNAL-shaped caller: it holds a PAT (`X-Provider-Token`), not an
SSO session. Both "my credential is wrong" and "the platform moved" arrive as
a 4xx on a POST whose far side cgm cannot see — and `status_callback` turns
either into a logged warning. #708 exists because nothing inside one repo can
tell those apart.

## What is NOT probed, deliberately

No POST, anywhere: the report, the ack and the status push all WRITE to a
sibling, and against a real receipt token. Their paths are checked with a GET,
which answers 405 when the route is registered POST-only — the read-only half
of a write edge.

Exit code is 0 only if every check passed.
"""
from __future__ import annotations

import json as _json
import pathlib
import re
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

#: Every sibling path cgm builds -> the client module that builds it.
#: `%s` stands for a path parameter. Checked ANCHORED, because a truncated
#: prefix is a substring of the real path and must not pass (#804).
PROBED_PATHS = {
    "/provider/feed": "app/services/upstream_client.py",
    "/provider/download/%s": "app/services/upstream_client.py",
    "/provider/report/%s": "app/services/upstream_client.py",
    "/provider/receipt/%s/ack": "app/services/upstream_client.py",
    "/requests": "app/services/upstream_client.py",
}

#: Probed but composed inline here, with no client module to drift from:
#:   /api/v1/health  — a bare liveness ping.
INLINE_PATHS = ("/api/v1/health",)

NOBODY = "00000000-0000-4000-8000-000000000000"

RESET, RED, GRN, BOLD = "\033[0m", "\033[31m", "\033[32m", "\033[1m"

results: list[dict] = []


def check(name: str):
    def wrap(fn):
        started = time.time()
        try:
            ok, note = fn()
        except Exception as e:                      # noqa: BLE001
            ok, note = False, f"{type(e).__name__}: {e}"
        results.append({"check": name, "ok": bool(ok), "note": note,
                        "ms": int((time.time() - started) * 1000)})
        return ok
    return wrap


def _repo_root() -> pathlib.Path:
    """Where `app/` lives.

    The IMAGE flattens the package to /app/app/..., while a checkout is
    <repo>/cgm_portal/app/... — one hardcoded relative path resolves in only
    one of them, and the guard is worth most BEFORE a deploy (#804).
    """
    here = pathlib.Path(__file__).resolve().parent.parent
    for cand in (here, here / "cgm_portal", here.parent / "cgm_portal"):
        if (cand / "app" / "services").is_dir():
            return cand
    return here


def _path_appears_in_client(template: str, src: str) -> bool:
    frags = [f for f in template.split("%s") if f]
    if not frags:
        return False
    if not re.search(r"""[}"']""" + re.escape(frags[0]), src):
        return False
    return all(f in src for f in frags[1:])


def _probe(url, headers=None, params=None, timeout=10):
    """(status, short body). A transport failure is status 0, so a service
    that is DOWN and a path that MOVED stay distinguishable."""
    import requests
    try:
        r = requests.get(url, headers=headers or {}, params=params or {},
                         timeout=timeout)
        return r.status_code, (r.text or "")[:120]
    except requests.RequestException as e:
        return 0, f"{type(e).__name__}: {e}"


def _exists(code: int) -> tuple[bool, str]:
    if code == 0:
        return False, "unreachable"
    if code == 404:
        return False, ("404 — the path MOVED, and status_callback turns that "
                       "into a logged warning")
    if code in (400, 401, 403, 405, 422):
        return True, f"{code} (refused, so the path is live)"
    if 200 <= code < 300:
        return True, f"{code} (answered)"
    return False, f"{code}"


def main(as_json: bool = False) -> int:
    from app import create_app
    app = create_app()

    with app.app_context():
        from flask import current_app
        cfg = current_app.config
        up = (cfg.get("REQUEST_SERVICE_URL") or "").rstrip("/")
        PAT = {"X-Provider-Token": "smoke-not-a-real-token"}

        @check("paths: every probed path appears in its client module")
        def _():
            root = _repo_root()
            missing = []
            for template, mod in PROBED_PATHS.items():
                f = root / mod
                if not f.exists():
                    missing.append(f"{mod} is missing (looked under {root})")
                    continue
                if not _path_appears_in_client(template,
                                               f.read_text(encoding="utf-8")):
                    missing.append(f"{template} does not START a URL in {mod}")
            return (not missing), (
                f"all {len(PROBED_PATHS)} anchored to a URL boundary; "
                f"{len(INLINE_PATHS)} inline liveness path(s) unguarded by "
                f"design" if not missing else "; ".join(missing))

        @check("config: REQUEST_SERVICE_URL is set, and names which host")
        def _():
            # Reported rather than assumed, because the variable is called
            # REQUEST_SERVICE_URL and its default is GATEWAY. Anyone reading
            # the name and not the value probes the wrong service.
            if not up:
                return False, "MISSING — cgm has no upstream at all"
            host = urlsplit(up).netloc or up
            return True, f"{up}  (host: {host})"

        @check("upstream: /provider/feed EXISTS and refuses a junk PAT")
        def _():
            # The unambiguous path: no guid in it, so a 404 can only mean the
            # route is gone.
            if not up:
                return False, "REQUEST_SERVICE_URL not set"
            code, body = _probe(f"{up}/provider/feed", headers=PAT)
            if 200 <= code < 300:
                return False, (f"{code} for a junk PAT — the feed is "
                               f"unauthenticated: {body[:60]}")
            return _exists(code)

        @check("upstream: /provider/download/<sr> EXISTS")
        def _():
            if not up:
                return False, "REQUEST_SERVICE_URL not set"
            code, _b = _probe(f"{up}/provider/download/{NOBODY}", headers=PAT)
            if code == 404:
                return True, ("404 — AMBIGUOUS here: the path, or that "
                              "service request. The feed check above is the "
                              "unambiguous one")
            return _exists(code)

        @check("upstream: the LIVE report path /provider/report/<sr> EXISTS")
        def _():
            # POST-only, so GET answers 405 — which proves the route is
            # registered without submitting a report against a real service
            # request.
            if not up:
                return False, "REQUEST_SERVICE_URL not set"
            code, _b = _probe(f"{up}/provider/report/{NOBODY}", headers=PAT)
            if code == 404:
                return False, ("404 — every report would fail and "
                               "status_callback only logs a warning")
            return _exists(code)

        @check("upstream: the ack path EXISTS and refuses a junk receipt")
        def _():
            if not up:
                return False, "REQUEST_SERVICE_URL not set"
            code, _b = _probe(
                f"{up}/provider/receipt/smoke-not-a-real-receipt/ack")
            if code == 404:
                return False, ("404 — an acknowledgement would silently go "
                               "nowhere")
            return _exists(code)

        @check("upstream: the LEGACY /requests fallback is GONE, so it cannot "
               "rescue anything")
        def _():
            # Reported, not failed. `/requests` and `/requests/<g>/status` are
            # the legacy pair, and gateway serves neither under /api/v1 —
            # enumerated from its live url_map 2026-10-15. What matters is
            # that they are still REACHABLE in code (`subscription` and
            # `status_callback` fall back to them), so each would 404, raise,
            # and be swallowed into a logged warning. A fallback that cannot
            # work is worse than no fallback: the code reads as though there
            # is a safety net.
            if not up:
                return False, "REQUEST_SERVICE_URL not set"
            code, body = _probe(f"{up}/requests", headers=PAT)
            if code == 404:
                return True, ("404 as expected — the legacy fallback is dead; "
                              "it cannot succeed if it is ever reached")
            if 200 <= code < 300:
                return False, f"{code} for a junk PAT: {body[:60]}"
            return True, f"{code} — still answering something (reported)"

        @check("upstream: cgm's own client RAISES on a refused feed")
        def _():
            # Drives the real `UpstreamClient`, so a wrong header name or a
            # changed response shape is wrong here too. Raising is the
            # contract: an empty feed and a refused feed must not look alike,
            # because `subscription` would record "nothing new" for the one
            # and retry for the other.
            from app.services.upstream_client import UpstreamClient
            if not up:
                return False, "REQUEST_SERVICE_URL not set"
            client = UpstreamClient(base_url=up,
                                    provider_token="smoke-not-a-real-token")
            try:
                items = client.fetch_feed(limit=1)
            except Exception as e:                  # noqa: BLE001
                return True, f"{type(e).__name__}: {str(e)[:70]}"
            return False, (f"returned {len(items) if items is not None else '?'}"
                           f" item(s) for a junk PAT — a refused feed is "
                           f"indistinguishable from an empty one")

    failed = [r for r in results if not r["ok"]]
    if as_json:
        print(_json.dumps({"service": "cgm.pdhc", "checks": results,
                           "failed": len(failed)}, indent=2))
    else:
        print(f"\n{BOLD}cgm.pdhc — sibling smoke{RESET}\n")
        for r in results:
            mark = f"{GRN}OK{RESET}" if r["ok"] else f"{RED}FAIL{RESET}"
            print(f"  {mark:<14} {r['check']:<58}\n{' ' * 18}{r['note']}  "
                  f"({r['ms']}ms)")
        if failed:
            print(f"\n{RED}{BOLD}{len(failed)} check(s) failed.{RESET}\n")
        else:
            print(f"\n{GRN}{BOLD}All {len(results)} checks passed.{RESET}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(as_json="--json" in sys.argv))
