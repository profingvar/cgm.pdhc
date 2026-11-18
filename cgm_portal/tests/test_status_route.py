"""A status with no data goes to /provider/status, data goes to /provider/report.

The acknowledgement ('acknowledged', no payload) was POSTed to
/provider/report, which requires report_payload and answered 400; the
failure was swallowed. Found on the cgm_provider onboarding, 2026-11-18.
"""
from unittest.mock import MagicMock, patch

from app.services.status_callback import StatusCallbackService


def _inbound():
    i = MagicMock()
    i.request_guid, i.patient_guid, i.grant_token = "sr-1", "p-1", "g-1"
    i.contract_guid, i.organisation_guid = "c-1", None
    return i


def _run(report_payload):
    client = MagicMock()
    client.submit_report.return_value = {"ok": True}
    client.post_status.return_value = {"ok": True}
    with patch("app.services.status_callback.UpstreamClient", return_value=client), \
         patch("app.extensions.db.session.commit"):
        ok, err = StatusCallbackService._push_via_composite_key(
            "https://gw.test/api/v1", "pat", _inbound(), "org-cgm",
            "acknowledged" if report_payload is None else "in-progress",
            report_payload)
    return ok, client


def test_a_status_without_data_uses_the_status_route(app):
    with app.app_context():
        ok, client = _run(None)
    assert ok
    client.submit_report.assert_not_called()
    kw = client.post_status.call_args.kwargs
    assert kw["status"] == "acknowledged"
    assert kw["contract_guid"] == "c-1"
    assert kw["provider_org_guid"] == "org-cgm"     # falls back to the provider


def test_observations_still_use_the_report_route(app):
    with app.app_context():
        ok, client = _run({"observations": [{"transaction_guid": "t", "value": 1}]})
    assert ok
    client.post_status.assert_not_called()
    client.submit_report.assert_called_once()


def test_the_client_posts_to_provider_status():
    from app.services.upstream_client import UpstreamClient
    c = UpstreamClient(base_url="https://gw.test/api/v1", provider_token="pat")
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"ok": True}
    with patch.object(c.session, "post", return_value=resp) as post:
        c.post_status("sr-1", "p-1", "g-1", "acknowledged", "c-1", "org-cgm")
    assert post.call_args.args[0] == "https://gw.test/api/v1/provider/status/sr-1"
    assert post.call_args.kwargs["json"]["provider_org_guid"] == "org-cgm"
