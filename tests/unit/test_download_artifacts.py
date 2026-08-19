import base64

from browser_auto_ops.downloads import DownloadManager
from browser_auto_ops.server import _filename_from_network, _latest_download_artifact, _network_artifact_bytes
from browser_auto_ops.schemas import NetworkRequestInfo


def test_download_manager_can_save_response_bytes(tmp_path) -> None:
    manager = DownloadManager(tmp_path)

    record = manager.save_bytes(
        session_id="s1",
        source_url="https://example.test/report.csv",
        filename="report.csv",
        content="Date,Value\n2026-08-17,1\n".encode("utf-8"),
    )

    assert record.status == "completed"
    assert record.final_path
    assert "Date,Value" in __import__("pathlib").Path(record.final_path).read_text(encoding="utf-8")


def test_latest_download_artifact_prefers_download_like_network_response() -> None:
    item = NetworkRequestInfo(
        url="https://example.test/a/report/download?id=1",
        method="POST",
        resource_type="fetch",
        status=200,
        response_headers={"content-type": "text/csv;charset=utf-8"},
        response_body_base64=base64.b64encode(b"Date,Value\n").decode("ascii"),
    )

    selected = _latest_download_artifact([{"url": "https://example.test/events", "method": "POST"}, item])

    assert selected
    assert _network_artifact_bytes(selected) == b"Date,Value\n"
    assert _filename_from_network(selected) == "download"


def test_filename_from_content_disposition() -> None:
    item = {
        "url": "https://example.test/proxy",
        "response_headers": {"content-disposition": 'attachment; filename="orders.csv"'},
    }

    assert _filename_from_network(item) == "orders.csv"
