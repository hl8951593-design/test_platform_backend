import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.errors import register_exception_handlers
from app.core.request_logging import register_request_logging_middleware


def build_test_app() -> FastAPI:
    app = FastAPI()
    register_request_logging_middleware(app)
    register_exception_handlers(app)

    @app.get("/ok")
    def ok():
        return {"ok": True}

    @app.get("/string-error")
    def string_error():
        raise HTTPException(status_code=400, detail="bad request")

    @app.get("/dict-error")
    def dict_error():
        raise HTTPException(
            status_code=409,
            detail={"message": "version conflict", "current_version": 3},
        )

    @app.get("/list-error")
    def list_error():
        raise HTTPException(
            status_code=400,
            detail=[{"field": "dataset_id", "message": "invalid"}],
        )

    @app.get("/validated")
    def validated(limit: int):
        return {"limit": limit}

    @app.get("/crash")
    def crash():
        raise RuntimeError("database password must not leak")

    return app


class ErrorResponseTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(build_test_app(), raise_server_exceptions=False)

    def test_string_http_error_uses_standard_envelope(self):
        with patch("app.core.errors.logger.warning"):
            response = self.client.get("/string-error")

        self.assertEqual(response.status_code, 400)
        self.assertIn("X-Request-ID", response.headers)
        self.assertEqual(response.json(), {
            "code": 400,
            "message": "bad request",
            "data": "bad request",
        })

    def test_dict_http_error_preserves_focus_data(self):
        response = self.client.get("/dict-error")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["message"], "version conflict")
        self.assertEqual(response.json()["data"]["current_version"], 3)

    def test_non_dict_http_detail_does_not_crash_handler(self):
        response = self.client.get("/list-error")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["message"], "bad request")
        self.assertEqual(response.json()["data"][0]["field"], "dataset_id")

    def test_validation_error_uses_standard_envelope(self):
        with patch("app.core.errors.logger.warning") as warning:
            response = self.client.get("/validated", params={"limit": "not-an-int"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("X-Request-ID", response.headers)
        self.assertTrue(warning.called)
        body = response.json()
        self.assertEqual(body["code"], 422)
        self.assertEqual(body["message"], "request validation failed")
        self.assertEqual(body["data"][0]["loc"], ["query", "limit"])

    def test_success_response_includes_request_id_header(self):
        response = self.client.get("/ok", headers={"X-Request-ID": "request-ok"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "request-ok")

    def test_framework_404_uses_standard_envelope(self):
        response = self.client.get("/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {
            "code": 404,
            "message": "Not Found",
            "data": "Not Found",
        })

    def test_unhandled_error_is_safe_and_traceable(self):
        with patch("app.core.errors.logger.error"):
            response = self.client.get(
                "/crash", headers={"X-Request-ID": "request-123"}
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["X-Request-ID"], "request-123")
        self.assertEqual(response.json(), {
            "code": 500,
            "message": "internal server error",
            "data": {
                "error": "internal_server_error",
                "request_id": "request-123",
            },
        })
        self.assertNotIn("password", response.text)

    def test_main_openapi_declares_standard_error_schema(self):
        from app.main import create_app

        schema = create_app().openapi()
        operation = schema["paths"]["/api/v1/test-cases"]["get"]

        for status_code in ("400", "401", "403", "404", "409", "422", "500"):
            self.assertIn(status_code, operation["responses"])
        error_schema = schema["components"]["schemas"]["ErrorResponse"]
        self.assertEqual(set(error_schema["required"]), {"code", "message"})


if __name__ == "__main__":
    unittest.main()
