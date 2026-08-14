import json
from typing import Any
from urllib import error, request


class TextToSqlClient:
    """HTTP client wrapper for an external text-to-sql service."""

    def __init__(self, base_url: str | None, timeout_seconds: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._base_url)

    def query(
        self,
        datasource: str,
        question: str,
    ) -> dict[str, Any]:
        if not self._base_url:
            return {
                "status": "failed",
                "message": "尚未配置 TEXT_TO_SQL_BASE_URL，无法调用语义查询服务。",
                "data": {},
                "error_code": "TEXT_TO_SQL_NOT_CONFIGURED",
            }

        body = {
            "datasource": datasource,
            "question": question
        }
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self._base_url}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return {
                "status": "failed",
                "message": f"语义查询服务返回 HTTP {exc.code}：{body or exc.reason}",
                "data": {"status_code": exc.code, "body": body},
                "error_code": "TEXT_TO_SQL_REQUEST_FAILED",
            }
        except error.URLError as exc:
            return {
                "status": "failed",
                "message": f"语义查询服务调用失败：{exc}",
                "data": {},
                "error_code": "TEXT_TO_SQL_REQUEST_FAILED",
            }

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {
                "status": "failed",
                "message": "语义查询服务返回了非 JSON 响应。",
                "data": {"raw": raw},
                "error_code": "TEXT_TO_SQL_INVALID_RESPONSE",
            }

        return {
            "status": "success",
            "message": "语义查询完成。",
            "data": parsed,
        }
