import json
from typing import Any

from app.adapters.text_to_sql import TextToSqlClient


def test_text_to_sql_client_posts_only_datasource_and_question(monkeypatch) -> None:
    requests: list[Any] = []

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"rows":[]}'

    def urlopen(req: Any, timeout: float) -> Response:
        requests.append(req)
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    result = TextToSqlClient("http://127.0.0.1:8088/ask").query(
        datasource="inspection_mysql",
        question="查询线路"
    )

    assert result["status"] == "success"
    assert json.loads(requests[0].data.decode("utf-8")) == {
        "datasource": "inspection_mysql",
        "question": "查询线路",
    }
