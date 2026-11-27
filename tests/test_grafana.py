import json

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DASHBOARD_PATH = (
    ROOT
    / "monitoring"
    / "grafana"
    / "dashboards"
    / "infrapulse-overview.json"
)

DATASOURCE_UID = "infrapulse-prometheus"


def load_dashboard():
    return json.loads(
        DASHBOARD_PATH.read_text(
            encoding="utf-8-sig"
        )
    )


def test_dashboard_exists():
    assert DASHBOARD_PATH.is_file()


def test_dashboard_valid_json():
    dashboard = load_dashboard()

    assert isinstance(dashboard, dict)


def test_dashboard_uid():
    dashboard = load_dashboard()

    assert dashboard["uid"] == "infrapulse-overview"


def test_dashboard_panel_count():
    dashboard = load_dashboard()

    assert len(dashboard["panels"]) >= 11


def test_unique_panel_ids():
    panels = load_dashboard()["panels"]

    ids = [panel["id"] for panel in panels]

    assert len(ids) == len(set(ids))


def test_panel_datasources():
    panels = load_dashboard()["panels"]

    for panel in panels:
        assert panel["datasource"]["type"] == "prometheus"
        assert panel["datasource"]["uid"] == DATASOURCE_UID


def test_panel_queries():
    panels = load_dashboard()["panels"]

    for panel in panels:
        assert panel["targets"]

        for target in panel["targets"]:
            assert target["expr"].strip()


def test_panel_grid_positions():
    panels = load_dashboard()["panels"]

    for panel in panels:
        grid = panel["gridPos"]

        assert grid["x"] >= 0
        assert grid["y"] >= 0
        assert grid["w"] > 0
        assert grid["h"] > 0
        assert grid["x"] + grid["w"] <= 24


def test_dashboard_refresh():
    dashboard = load_dashboard()

    assert dashboard["refresh"] == "15s"


def test_dashboard_readonly():
    dashboard = load_dashboard()

    assert dashboard["editable"] is False
