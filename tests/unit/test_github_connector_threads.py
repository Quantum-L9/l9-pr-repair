from typing import Any

from pr_repair.connectors.github import GitHubConnector


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _FakeSession:
    """Records the last POST and returns a canned payload keyed by URL."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, json: dict[str, Any], timeout: int) -> _FakeResponse:
        self.calls.append((url, json))
        if url.endswith("/graphql"):
            mutation = (
                "resolveReviewThread"
                if "unresolve" not in json["query"]
                else "unresolveReviewThread"
            )
            resolved = mutation == "resolveReviewThread"
            return _FakeResponse(
                {
                    "data": {
                        mutation: {
                            "thread": {"id": json["variables"]["threadId"], "isResolved": resolved}
                        }
                    }
                }
            )
        return _FakeResponse({"id": 999, "body": json["body"]})


def _connector() -> tuple[GitHubConnector, _FakeSession]:
    connector = GitHubConnector(token="t")
    session = _FakeSession()
    connector._session = session  # type: ignore[assignment]
    return connector, session


def test_reply_to_review_comment_hits_replies_endpoint() -> None:
    connector, session = _connector()

    result = connector.reply_to_review_comment("owner", "repo", 7, 123, "**Fixed** in abc123")

    url, body = session.calls[0]
    assert url.endswith("/repos/owner/repo/pulls/7/comments/123/replies")
    assert body == {"body": "**Fixed** in abc123"}
    assert result["body"] == "**Fixed** in abc123"


def test_resolve_review_thread_returns_resolved_thread() -> None:
    connector, session = _connector()

    thread = connector.resolve_review_thread("PRRT_abc")

    url, body = session.calls[0]
    assert url.endswith("/graphql")
    assert "resolveReviewThread" in body["query"]
    assert body["variables"] == {"threadId": "PRRT_abc"}
    assert thread == {"id": "PRRT_abc", "isResolved": True}


def test_unresolve_review_thread_reopens() -> None:
    connector, session = _connector()

    thread = connector.unresolve_review_thread("PRRT_abc")

    _, body = session.calls[0]
    assert "unresolveReviewThread" in body["query"]
    assert thread["isResolved"] is False
