from pathlib import Path

from browser_auto_ops.forge.api_scripts import write_api_scripts


def test_write_api_scripts_uses_operation_name(tmp_path: Path) -> None:
    written = write_api_scripts(
        tmp_path / "scripts",
        {
            "network": [
                {
                    "method": "POST",
                    "url": "https://example.test/graphql",
                    "path": "/graphql",
                    "operation": "SampleOrdersQuery",
                }
            ]
        },
    )
    assert written == ["api-sampleordersquery.py"]
    assert (tmp_path / "scripts" / "api-sampleordersquery.py").exists()
    source = Path(__file__).resolve().parents[2] / "src" / "browser_auto_ops" / "forge"
    blob = (source / "api_scripts.py").read_text(encoding="utf-8") + (source / "engine.py").read_text(encoding="utf-8")
    assert "OrderListExportQuery" not in blob


def test_write_api_scripts_skips_analytics_when_graphql_exists(tmp_path: Path) -> None:
    written = write_api_scripts(
        tmp_path / "scripts",
        {
            "network": [
                {"method": "POST", "url": "https://s.wayfair.com/events/single", "path": "/events/single", "operation": "single"},
                {"method": "POST", "url": "https://example.test/graphql", "path": "/graphql", "operation": "SampleOrdersQuery"},
            ]
        },
    )
    assert written == ["api-sampleordersquery.py"]


def test_write_api_scripts_skips_without_network(tmp_path: Path) -> None:
    assert write_api_scripts(tmp_path / "scripts", {"network": []}) == []
    assert not (tmp_path / "scripts").exists() or not any((tmp_path / "scripts").iterdir())
