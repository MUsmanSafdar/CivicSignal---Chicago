"""Funded projects tab: FEMA record parsing, county matching, download paging and page assembly.

No network and no Streamlit. REAL_* are records copied from FEMA's public API; the Illinois rows are made-up test
fixtures in the same shape and are never shown in the app.
"""
import json
import re
from pathlib import Path

import pytest

import funded_projects_ui as fp

ROOT = Path(__file__).resolve().parent.parent
SITE = (ROOT / "site.html").read_text(encoding="utf-8")
TPL = (ROOT / "projects_view.html").read_text(encoding="utf-8")

REAL_CLOSED = {"projectIdentifier": "DR-4339-0024-R", "programArea": "HMGP", "programFy": 2017, "state": "Puerto Rico",
               "county": "Bayamon", "projectCounties": "BAYAMON", "projectType": "601.1: Generators", "status": "Closed",
               "subrecipient": "Bayamon (Municipio)", "dateApproved": None, "dateClosed": "2025-09-22T00:00:00.000Z",
               "projectAmount": 1076952.08, "federalShareObligated": None}
REAL_APPROVED = {"projectIdentifier": "DR-4460-0005-P", "programArea": "HMGP", "programFy": 2019, "state": "Arkansas",
                 "county": "Statewide", "projectCounties": "STATEWIDE", "projectType": "95.2: Planning Related Activities",
                 "status": "Approved", "subrecipient": "ARKANSAS DEPARTMENT OF ENVIRONMENTAL QUALITY",
                 "dateApproved": "2021-01-04T00:00:00.000Z", "dateClosed": None, "projectAmount": 17828,
                 "federalShareObligated": 13371}


def _il(i, county, counties=None, status="Approved", closed=None, fy=2022, fed=1000.0):
    return {"projectIdentifier": f"TEST-{i}", "programArea": "HMGP", "programFy": fy, "state": "Illinois", "county": county,
            "projectCounties": counties, "projectType": "200.1: Acquisition of Private Real Property", "status": status,
            "subrecipient": "Test Village", "dateClosed": closed, "projectAmount": fed * 2, "federalShareObligated": fed}


def test_open_means_no_close_date_and_not_an_ended_status():
    assert fp.is_open(REAL_APPROVED)
    assert not fp.is_open(REAL_CLOSED)
    assert not fp.is_open({"status": "Approved", "dateClosed": "2024-01-01T00:00:00.000Z"})
    for ended in ("Closed", "Completed", "Withdrawn", "Void", "Denied"):
        assert not fp.is_open({"status": ended, "dateClosed": None})
    assert fp.is_open({"status": "Obligated", "dateClosed": None})


def test_project_type_drops_fema_codes_and_duplicates():
    assert fp.project_type("601.1: Generators") == "Generators"
    assert fp.project_type("95.2: Planning Related Activities; 95.2: Planning Related Activities") == "Planning Related Activities"
    assert fp.project_type(None) == "Type not stated"


def test_clean_handles_missing_money_and_keeps_fema_wording():
    c = fp.clean(REAL_CLOSED)
    assert c == {"id": "DR-4339-0024-R", "program": "HMGP", "fy": 2017, "type": "Generators", "status": "Closed",
                 "who": "Bayamon (Municipio)", "amount": 1076952.08, "fed": 0.0, "open": False}
    assert fp.clean({"federalShareObligated": "n/a", "projectAmount": -5})["fed"] == 0.0


@pytest.mark.parametrize("a,b", [("De Kalb", "DeKalb"), ("ST. CLAIR", "St. Clair"), ("Saint Clair", "St. Clair"),
                                 ("DU PAGE", "DuPage"), ("La Salle (County)", "LaSalle"), ("Cook County", "Cook")])
def test_county_names_match_across_spellings(a, b):
    assert fp.norm_county(a) == fp.norm_county(b)


def test_grouping_by_county_statewide_and_unmatched():
    names = [c["n"] for c in fp.load_counties(SITE)["counties"]]
    recs = [_il(1, "Cook"), _il(2, "Cook", status="Closed", closed="2020-01-01T00:00:00.000Z", fy=2015),
            _il(3, "Du Page", counties="DU PAGE; COOK", fy=2024), _il(4, "Statewide", counties="STATEWIDE"),
            _il(5, "Atlantis")]
    g = fp.group_projects(recs, names)
    assert [p["id"] for p in g["by"]["Cook"]] == ["TEST-3", "TEST-1", "TEST-2"]   # open first, newest first
    assert [p["id"] for p in g["by"]["DuPage"]] == ["TEST-3"]
    assert [p["id"] for p in g["statewide"]] == ["TEST-4"]
    assert g["unmatched"] == 1


def test_query_asks_fema_for_illinois_only():
    url = fp.query_url(5000)
    assert url.startswith(fp.API + "?$filter=state%20eq%20'Illinois'&$select=")
    assert "$top=5000" in url and "$skip=5000" in url and " " not in url


def test_fetch_pages_until_a_short_page_and_drops_other_states():
    calls = []

    def opener(url):
        calls.append(url)
        n = fp.PAGE_SIZE if len(calls) == 1 else 2
        rows = [_il(len(calls) * 10000 + i, "Cook") for i in range(n)] + ([REAL_CLOSED] if len(calls) == 2 else [])
        return json.dumps({"metadata": {"rundate": "2026-06-04T03:56:33.667Z"}, fp.ENTITY: rows}).encode()

    out = fp.fetch_projects(opener)
    assert len(calls) == 2 and "$skip=0" in calls[0] and f"$skip={fp.PAGE_SIZE}" in calls[1]
    assert len(out["records"]) == fp.PAGE_SIZE + 2 and out["rundate"].startswith("2026-06-04")


def test_fetch_rejects_an_unexpected_response():
    with pytest.raises(ValueError):
        fp.fetch_projects(lambda url: b'{"error": "nope"}')


def test_payload_when_fema_is_unreachable_has_no_projects():
    p = fp.build_payload(SITE, None)
    assert p["ok"] is False and p["by"] == {} and p["statewide"] == [] and p["total"] == 0
    assert len(p["counties"]) == 102


def test_page_carries_the_payload_and_stays_one_script():
    recs = [_il(1, "Cook"), dict(_il(2, "Cook"), subrecipient="x</script><script>alert(1)")]
    page = fp.build_page(TPL, fp.build_payload(SITE, {"records": recs, "rundate": "2026-06-04T03:56:33.667Z"}))
    assert page.count("<script>") == 1 and page.count("</script>") == 1
    back = json.loads(re.search(r"const DATA = (\{.*?\});\n\(function", page, re.S).group(1))
    assert back["ok"] and back["total"] == 2 and len(back["by"]["Cook"]) == 2 and back["rundate"] == "2026-06-04"
    assert "not a federal standard" in page and "sample data" in page


def test_template_without_marker_is_an_error():
    with pytest.raises(ValueError):
        fp.build_page("<html></html>", {})
