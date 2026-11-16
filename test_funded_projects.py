"""Funded projects tab: FEMA record parsing, county and town matching, download paging, saved copy, page assembly.

No network and no Streamlit. REAL_* are Illinois records copied from FEMA's public API (HMA Subapplications v2,
fields trimmed to the ones the app requests). Rows built by _il() are made-up test fixtures in the same shape and
are never shown in the app.
"""
import json
import re
from pathlib import Path

import pytest

import funded_projects_ui as fp

ROOT = Path(__file__).resolve().parent.parent
SITE = (ROOT / "site.html").read_text(encoding="utf-8")
TPL = (ROOT / "projects_view.html").read_text(encoding="utf-8")
PTS = {"DIXON": [41.8425, -89.4814], "URBANA": [40.1106, -88.2073]}

REAL_CLOSED_PLAN = {"subapplicationIdentifier": "PDMC-PL-05-IL-2016-016", "program": "Pre-Disaster Mitigation", "fiscalYear": 2016,
                    "subapplicantName": "Lee County Emergency Management Agency", "subapplicantCity": "Dixon",
                    "subapplicantStateAbbreviation": "IL", "status": "Closed", "subapplicationType": "Plan",
                    "benefitingCounties": "LEE; SCOTT; BLUE EARTH; PULASKI; SOLANO; WEBSTER; VAN BUREN", "primaryActivity": "New plan",
                    "subapplicationTitle": None, "primaryHazard": None, "federalShareAmount": 51293.99, "totalObligatedAmount": 51293.99}
REAL_NOT_SELECTED = {"subapplicationIdentifier": "EMC-2023-BR-001-0030", "program": "Building Resilient Infrastructure and Communities",
                     "fiscalYear": 2023, "subapplicantName": "CHAMPAIGN, COUNTY OF", "subapplicantCity": "URBANA",
                     "subapplicantStateAbbreviation": "IL", "status": "Not Selected", "subapplicationType": "Plan",
                     "benefitingCounties": "VERMILION COUNTY; PIATT COUNTY; CHAMPAIGN COUNTY", "primaryActivity": "Plan update",
                     "subapplicationTitle": "Champaign County, Illinois-Multi-Jurisdictional Multi-Hazard Mitigation Plan",
                     "primaryHazard": "Severe storm", "federalShareAmount": 48892.8, "totalObligatedAmount": None}
REAL_INELIGIBLE = {"subapplicationIdentifier": "EMC-2020-FM-040-0007", "program": "Flood Mitigation Assistance", "fiscalYear": 2020,
                   "subapplicantName": "COUNTY OF KANE", "subapplicantCity": "GENEVA", "subapplicantStateAbbreviation": "IL",
                   "status": "Ineligible", "subapplicationType": "Project", "benefitingCounties": "DUPAGE COUNTY; KANE COUNTY",
                   "primaryActivity": "Acquisition", "subapplicationTitle": "(REDACTED), Kane County 2020", "primaryHazard": "Flooding",
                   "federalShareAmount": 299250, "totalObligatedAmount": None}
REAL = [REAL_CLOSED_PLAN, REAL_NOT_SELECTED, REAL_INELIGIBLE]


def _il(i, counties="COOK COUNTY", status="Approved", fy=2022, city="Dixon", fed=1000.0):
    return {"subapplicationIdentifier": f"TEST-{i}", "program": "Hazard Mitigation Grant Program", "fiscalYear": fy,
            "subapplicantName": "Test Village", "subapplicantCity": city, "subapplicantStateAbbreviation": "IL", "status": status,
            "subapplicationType": "Project", "benefitingCounties": counties, "primaryActivity": "Acquisition",
            "subapplicationTitle": None, "primaryHazard": "Flooding", "federalShareAmount": fed, "totalObligatedAmount": fed}


@pytest.mark.parametrize("status,want", [
    ("Approved", "open"), ("Obligated", "open"), ("Subaward Accepted", "open"), ("Awarded", "open"), ("Closeout Initiated", "open"),
    ("Closed", "closed"), ("Submitted to FEMA", "review"), ("Pending", "review"), ("Ineligible", "no"),
    ("Not Approved / Denied", "no"), ("Not Selected", "no"), (None, "review"), ("Something new", "review")])
def test_every_status_fema_uses_for_illinois_lands_in_a_stage(status, want):
    assert fp.stage(status) == want


def test_program_names_are_shortened():
    assert fp.program_short("Hazard Mitigation Grant Program") == "HMGP"
    assert fp.program_short("Building Resilient Infrastructure and Communities") == "BRIC"
    assert fp.program_short("Flood Mitigation Assistance Swift Current") == "FMA Swift Current"
    assert fp.program_short("Pre-Disaster Mitigation Congressionally Directed Spending") == "PDM Directed Spending"
    assert fp.program_short("Legislative Pre-Disaster Mitigation") == "LPDM"
    assert fp.program_short("Pre-Disaster Mitigation") == "PDM"
    assert fp.program_short(None) == "Program not stated"


def test_clean_keeps_fema_wording_and_places_the_town():
    c = fp.clean(REAL_CLOSED_PLAN, PTS)
    assert c == {"id": "PDMC-PL-05-IL-2016-016", "program": "PDM", "pf": "Pre-Disaster Mitigation", "co": [], "fy": 2016, "title": "New plan", "what": "Plan · New plan",
                 "hazard": "", "who": "Lee County Emergency Management Agency", "city": "Dixon", "status": "Closed",
                 "stage": "closed", "fed": 51293.99, "obl": 51293.99, "pt": [41.8425, -89.4814]}
    k = fp.clean(REAL_INELIGIBLE, PTS)
    assert k["title"] == "(REDACTED), Kane County 2020" and k["stage"] == "no" and k["obl"] == 0.0 and k["pt"] is None


@pytest.mark.parametrize("raw,label", [("EAST ST. LOUIS", "East St. Louis"), ("MCHENRY", "McHenry"), ("SPRINGFIELD, IL", "Springfield"),
                                       ("PEORIA,", "Peoria"), ("Dixon", "Dixon"), ("UNKNOWN", ""), (None, "")])
def test_town_labels(raw, label):
    assert fp.city_label(raw) == label


@pytest.mark.parametrize("a,b", [("DE KALB", "DeKalb"), ("ST. CLAIR COUNTY", "St. Clair"), ("Saint Clair", "St. Clair"),
                                 ("DUPAGE COUNTY", "DuPage"), ("La Salle (County)", "LaSalle"), ("COOK COUNTY", "Cook")])
def test_county_names_match_across_spellings(a, b):
    assert fp.norm_county(a) == fp.norm_county(b)


def test_grouping_uses_only_illinois_counties_and_orders_in_progress_first():
    names = [c["n"] for c in fp.load_counties(SITE)["counties"]]
    recs = REAL + [_il(1), _il(2, status="Closed", fy=2015), _il(3, counties="DUPAGE COUNTY; COOK COUNTY", fy=2024),
                   _il(4, counties=None), _il(5, counties="BLUE EARTH")]
    g = fp.group_projects(recs, names, PTS)
    assert [p["id"] for p in g["by"]["Cook"]] == ["TEST-3", "TEST-1", "TEST-2"]
    assert [p["id"] for p in g["by"]["DuPage"]] == ["TEST-3", "EMC-2020-FM-040-0007"]
    assert g["by"]["Lee"][0]["co"] == ["Lee"] and "Scott" not in g["by"] and "Pulaski" not in g["by"] and g["by"]["DuPage"][0]["co"] == ["DuPage", "Cook"]
    assert [p["id"] for p in g["by"]["Lee"]] == ["PDMC-PL-05-IL-2016-016"]          # the out-of-state names FEMA lists are ignored
    assert set(g["by"]) >= {"Vermilion", "Piatt", "Champaign", "Kane"}
    assert sorted(p["id"] for p in g["other"]) == ["TEST-4", "TEST-5"]


def test_query_asks_fema_for_illinois_only():
    url = fp.query_url(5000)
    assert url.startswith(fp.API + "?$filter=subapplicantStateAbbreviation%20eq%20'IL'&$select=")
    assert fp.API.endswith("/v2/HmaSubapplications") and "$top=5000" in url and "$skip=5000" in url and " " not in url


def test_fetch_pages_until_a_short_page_and_drops_other_states():
    calls = []

    def opener(url):
        calls.append(url)
        n = fp.PAGE_SIZE if len(calls) == 1 else 2
        rows = [_il(len(calls) * 10000 + i) for i in range(n)]
        if len(calls) == 2:
            rows.append(dict(_il(99), subapplicantStateAbbreviation="PA"))
        return json.dumps({"metadata": {"rundate": "2026-07-27T03:56:33.667Z"}, fp.ENTITY: rows}).encode()

    out = fp.fetch_projects(opener)
    assert len(calls) == 2 and "$skip=0" in calls[0] and f"$skip={fp.PAGE_SIZE}" in calls[1]
    assert len(out["records"]) == fp.PAGE_SIZE + 2 and out["rundate"].startswith("2026-07-27")


@pytest.mark.parametrize("body", [b'{"error": "nope"}', b'[]', json.dumps({"HmaSubapplications": []}).encode()])
def test_fetch_rejects_an_unexpected_or_empty_response(body):
    with pytest.raises(ValueError):
        fp.fetch_projects(lambda url: body)


def test_saved_copy_round_trip_and_bad_files(tmp_path):
    good = tmp_path / "ok.json"
    good.write_text(json.dumps({"rundate": "2026-07-27T00:00:00Z", "records": REAL}), encoding="utf-8")
    snap = fp.load_snapshot(good)
    assert snap["saved"] is True and len(snap["records"]) == 3
    p = fp.build_payload(SITE, snap, PTS)
    assert p["ok"] and p["saved"] and p["total"] == 3 and p["rundate"] == "2026-07-27"
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    empty = tmp_path / "empty.json"
    empty.write_text('{"records": []}', encoding="utf-8")
    assert fp.load_snapshot(bad) is None and fp.load_snapshot(empty) is None and fp.load_snapshot(tmp_path / "missing.json") is None


def test_payload_without_records_has_no_projects():
    p = fp.build_payload(SITE, None)
    assert p["ok"] is False and p["by"] == {} and p["other"] == [] and p["total"] == 0 and len(p["counties"]) == 102


def test_town_points_file_covers_towns_and_stays_in_illinois():
    pts = fp.load_points(ROOT / fp.POINTS)
    assert len(pts) >= 120 and "CHICAGO" in pts and "DIXON" in pts
    for name, (lat, lon) in pts.items():
        assert 36.9 <= lat <= 42.6 and -91.6 <= lon <= -87.0, name
    assert fp.load_points(ROOT / "no_such_file.json") == {}


def test_page_carries_the_payload_and_stays_one_script():
    recs = REAL + [dict(_il(2), subapplicantName="x</script><script>alert(1)")]
    page = fp.build_page(TPL, fp.build_payload(SITE, {"records": recs, "rundate": "2026-07-27T03:56:33.667Z"}, PTS))
    assert page.count("<script>") == 1 and page.count("</script>") == 1
    back = json.loads(re.search(r"const DATA = (\{.*?\});\n\(function", page, re.S).group(1))
    assert back["ok"] and back["total"] == 4 and back["rundate"] == "2026-07-27" and back["by"]["Lee"][0]["pt"] == PTS["DIXON"]
    assert "not a federal standard" in page and "does not publish project addresses" in page and "OpenStreetMap" in page


def test_template_without_marker_is_an_error():
    with pytest.raises(ValueError):
        fp.build_page("<html></html>", {})
