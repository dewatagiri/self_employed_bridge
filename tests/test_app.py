"""End-to-end: run the staff page on a free port and drive it like a browser would."""
import http.client
import re
import threading
import urllib.parse
from http.server import HTTPServer

import pytest

from self_employed_bridge.app import EXAMPLE, App, make_handler, parse_job
from self_employed_bridge.store import Store


@pytest.fixture
def server(demo, tmp_path):
    app = App(demo, "config/params.demo.yaml", Store(str(tmp_path / "t.db")), today=lambda: "2026-11-20")
    httpd = HTTPServer(("127.0.0.1", 0), make_handler(app))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd.server_address[1], app
    httpd.shutdown()
    httpd.server_close()


def call(port, method, path, form=None, origin=True):
    c = http.client.HTTPConnection("127.0.0.1", port)
    headers = {}
    body = None
    if form is not None:
        body = urllib.parse.urlencode(form)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        if origin:
            headers["Origin"] = f"http://127.0.0.1:{port}"
    c.request(method, path, body, headers)
    r = c.getresponse()
    return r.status, r.getheader("Location"), r.read().decode()


def example_form(**over):
    f = {k: ("on" if v is True else str(v)) for k, v in EXAMPLE.items() if v is not False}
    return {**f, **over}


def test_parse_job_from_form():
    j = parse_job(example_form())
    assert j.materials_cost == 5000 and j.borrower_registered is True and j.payer_related_to_borrower is False
    assert j.variation_order_signed is None


def test_pages_load(server):
    port, _ = server
    for path in ("/job", "/job?example=1", "/bridges", "/gates", "/log.csv"):
        status, _, body = call(port, "GET", path)
        assert status == 200, path
    assert "DEMO PARAMETERS" in call(port, "GET", "/job")[2]


def test_full_flow_decide_release_late_writeoff_gates(server):
    port, app = server
    status, _, body = call(port, "POST", "/decide", example_form())
    assert status == 200 and "RELEASE" in body and "RM3,000" in body and "S-01" in body
    status, loc, _ = call(port, "POST", "/release", {"job_id": "J-0001", "quote_hours": "3",
                                                     "supplier_paid_directly": "on"})
    assert status == 303 and loc.startswith("/bridge?id=BR00001")
    # same job again: the engine now sees the live bridge and declines a duplicate
    _, _, body = call(port, "POST", "/decide", example_form())
    assert "DUPLICATE_JOB" in body
    # goes late, then written off at day 120
    _, loc, _ = call(port, "POST", "/bridge", {"id": "BR00001", "action": "days", "value": "14"})
    _, _, body = call(port, "GET", loc)
    assert "Financier sends notice" in body and "LATE" in body
    call(port, "POST", "/bridge", {"id": "BR00001", "action": "days", "value": "120"})
    b = app.store.record("BR00001")["live"]
    assert b.state == "WRITTEN_OFF" and b.allocation["first_loss"] == 3000
    _, _, body = call(port, "GET", "/gates")
    assert "Pilot gates" in body and "NO_THRESHOLD_SET" in body
    _, _, csv_text = call(port, "GET", "/log.csv")
    assert "BR00001" in csv_text and ",lost," in csv_text


def test_bypass_blocks_then_cure_unblocks(server):
    port, app = server
    call(port, "POST", "/decide", example_form())
    call(port, "POST", "/release", {"job_id": "J-0001", "supplier_paid_directly": "on"})
    call(port, "POST", "/bridge", {"id": "BR00001", "action": "bypass"})
    _, _, body = call(port, "POST", "/decide", example_form(job_id="J-0002", payer_id="P-0002"))
    assert "BORROWER_BLOCKED" in body
    call(port, "POST", "/bridge", {"id": "BR00001", "action": "payment", "value": "3000"})
    call(port, "POST", "/bridge", {"id": "BR00001", "action": "cure"})
    _, _, body = call(port, "POST", "/decide", example_form(job_id="J-0002", payer_id="P-0002"))
    assert "BORROWER_BLOCKED" not in body and "RELEASE" in body


def test_variation_top_up(server):
    port, app = server
    call(port, "POST", "/decide", example_form())
    call(port, "POST", "/release", {"job_id": "J-0001", "supplier_paid_directly": "on"})
    _, loc, _ = call(port, "POST", "/bridge", {"id": "BR00001", "action": "topup", "value": "6500"})
    assert "Top-up" in urllib.parse.unquote(loc)
    b = app.store.record("BR00001")["live"]
    assert b.amount == 4500 and b.outstanding == 4500


def test_release_is_rechecked(server):
    port, app = server
    call(port, "POST", "/decide", example_form(pdpa_consent=""))      # blocked: no consent
    status, loc, body = call(port, "POST", "/release", {"job_id": "J-0001", "supplier_paid_directly": "on"})
    assert status == 200 and loc is None and "BLOCKED" in body and app.store.records() == []


def test_cross_site_post_refused(server):
    port, _ = server
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("POST", "/decide", urllib.parse.urlencode(example_form()),
              {"Content-Type": "application/x-www-form-urlencoded", "Origin": "http://evil.example"})
    assert c.getresponse().status == 403


def test_output_is_escaped(server):
    port, _ = server
    _, _, body = call(port, "POST", "/decide", example_form(job_id="<script>x</script>"))
    assert "<script>x</script>" not in body and "&lt;script&gt;" in body


def test_template_config_shows_missing_settings(template, tmp_path):
    app = App(template, "t", Store(str(tmp_path / "x.db")))
    httpd = HTTPServer(("127.0.0.1", 0), make_handler(app))
    t = threading.Thread(target=httpd.serve_forever, daemon=True); t.start()
    try:
        _, _, body = call(httpd.server_address[1], "POST", "/decide", example_form())
        assert "Settings missing" in body and "caps.per_bridge" in body
    finally:
        httpd.shutdown(); httpd.server_close()
