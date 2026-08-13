import importlib.util
import unittest
from pathlib import Path

from sqlalchemy.dialects import mysql, sqlite

from app.models.execution_diagnostic import ExecutionPayloadArtifact


class ExecutionArtifactCapacityTests(unittest.TestCase):
    def test_mysql_artifact_content_uses_mediumblob(self):
        column_type = ExecutionPayloadArtifact.__table__.c.content.type

        self.assertEqual(column_type.compile(dialect=mysql.dialect()).upper(), "MEDIUMBLOB")
        self.assertEqual(column_type.compile(dialect=sqlite.dialect()).upper(), "BLOB")

    def test_capacity_migration_follows_current_head(self):
        path = Path("migrations/versions/0044_execution_artifact_mediumblob.py")
        spec = importlib.util.spec_from_file_location("migration_0044", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        self.assertEqual(module.revision, "0044_execution_artifact_mediumblob")
        self.assertEqual(module.down_revision, "0043_test_report_contracts")


if __name__ == "__main__":
    unittest.main()
