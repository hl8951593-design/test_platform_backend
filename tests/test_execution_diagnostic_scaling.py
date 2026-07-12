import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.execution_diagnostic import ExecutionRecordIndex
from app.schemas.execution_record import ExecutionRecordCursorPage
from app.services.execution_record_service import ExecutionRecordService


BASE_TIME = datetime(2026, 7, 13, 8, 0, 0)


class ExecutionDiagnosticScalingTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        ExecutionRecordIndex.__table__.create(engine)
        self.db = sessionmaker(bind=engine)()
        self.service = ExecutionRecordService(self.db)
        self.service.permission_service = MagicMock()
        self.user = SimpleNamespace(id=7)
        for index in range(5):
            self._insert(
                execution_id=index + 1,
                started_at=BASE_TIME - timedelta(minutes=index),
            )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _insert(self, *, execution_id: int, started_at: datetime):
        self.db.add(
            ExecutionRecordIndex(
                project_id=1,
                execution_type="http",
                execution_id=execution_id,
                object_ref=f"http:{execution_id}",
                resource_id=100 + execution_id,
                resource_name=f"case-{execution_id}",
                environment_id=4,
                status="passed",
                trigger_type="manual",
                trigger_user_id=7,
                duration_ms=10,
                total_steps=1,
                passed_steps=1,
                failed_steps=0,
                timeout_steps=0,
                skipped_steps=0,
                started_at=started_at,
                finished_at=started_at + timedelta(milliseconds=10),
                source_updated_at=started_at,
                projection_version="execution_diagnostic_projection_v1",
            )
        )

    def _page(self, *, cursor=None, include_total=False):
        return self.service.list_records_cursor(
            project_id=1,
            current_user=self.user,
            execution_type=None,
            status_filter=None,
            environment_id=None,
            trigger_user_id=None,
            started_from=None,
            started_to=None,
            keyword=None,
            cursor=cursor,
            limit=2,
            include_total=include_total,
        )

    def test_cursor_page_is_stable_when_newer_record_arrives(self):
        first = self._page()
        self.assertIsInstance(first, ExecutionRecordCursorPage)
        self.assertTrue(first.has_more)

        self._insert(execution_id=99, started_at=BASE_TIME + timedelta(minutes=1))
        self.db.commit()
        second = self._page(cursor=first.next_cursor)

        first_ids = {item.id for item in first.items}
        second_ids = {item.id for item in second.items}
        self.assertTrue(first_ids.isdisjoint(second_ids))
        self.assertNotIn("http:99", second_ids)

    def test_cursor_page_skips_exact_count_by_default(self):
        self.service.diagnostic_repository.count_records = MagicMock(
            wraps=self.service.diagnostic_repository.count_records
        )

        page = self._page(include_total=False)

        self.assertIsNone(page.total)
        self.service.diagnostic_repository.count_records.assert_not_called()

    def test_cursor_page_computes_total_only_when_requested(self):
        page = self._page(include_total=True)

        self.assertEqual(page.total, 5)
        self.assertEqual(page.returned, 2)

    def test_cursor_rejects_malformed_and_oversized_values(self):
        for cursor in ("not-base64", "x" * 513):
            with self.subTest(cursor_length=len(cursor)):
                with self.assertRaises(HTTPException) as raised:
                    self._page(cursor=cursor)
                self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
