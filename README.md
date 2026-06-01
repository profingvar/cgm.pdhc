# cgm.pdhc

Continuous-glucose-monitor (CGM) provider service for the **PDHC** platform.

This is one of the service repositories that together form
[Planned Data in Healthcare](https://pdhc.se). It provides the
provider-side portal for CGM devices (Abbott FreeStyle and similar):
receiving CarePlan requests, performing continuous batched glucose
observations, and submitting them back through the PDHC gateway.

## What this service does

- Receives `ServiceRequest` payloads pushed from `request.pdhc`
- Acknowledges, runs monitoring, and streams batched observations via
  `POST /provider-tasks/<token>/observe` / `/observe/complete`
- Submits the resulting `Observation` bundles to `gateway.pdhc` with
  HMAC-signed grant tokens
- Tracks delivery receipts and observation logs for audit

Architecture follows the same pattern as `provider.pdhc`, extended for
the continuous-monitoring use case.

## Layout

- `cgm_portal/` — Flask application, models, services, API endpoints, migrations
- `docs/cgm_technical_guide.md` — technical integration guide
- `server_configs/` — example nginx server blocks for the production host
- `start.sh` — single entry point (kills its own port block, starts compose, runs migrations, launches gunicorn)
- `.env.example` — required environment variables

## Running locally

```bash
cd cgm_portal
cp .env.example .env       # then fill in the values
docker compose up -d db    # postgres on 9081
flask db upgrade
python -m gunicorn --bind 127.0.0.1:9080 'app:create_app()'
```

See `docs/cgm_technical_guide.md` for the full integration model
and `cgm_portal/.env.example` for required environment.

## License

MIT — see [LICENSE](LICENSE).
