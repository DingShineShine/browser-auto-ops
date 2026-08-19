from browser_auto_ops.network.har import to_har
from browser_auto_ops.schemas import NetworkRequestInfo


def test_to_har_writes_entries() -> None:
    item = NetworkRequestInfo(
        url="https://example.test/graphql",
        method="POST",
        resource_type="fetch",
        status=200,
        request_headers={"content-type": "application/json"},
        response_headers={"content-type": "application/json"},
        post_data='{"operationName":"Orders"}',
        response_body='{"ok":true}',
    )
    har = to_har([item])
    entries = har["log"]["entries"]
    assert len(entries) == 1
    assert entries[0]["request"]["url"] == "https://example.test/graphql"
    assert entries[0]["response"]["status"] == 200
    assert entries[0]["response"]["content"]["text"] == '{"ok":true}'
