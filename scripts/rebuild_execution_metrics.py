from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.services.execution_metrics_service import ExecutionMetricsService  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild one project's execution metric bucket"
    )
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--bucket", required=True, help="ISO hour or day")
    parser.add_argument("--granularity", choices=("hour", "day"), default="hour")
    args = parser.parse_args()
    bucket = datetime.fromisoformat(args.bucket.replace("Z", "+00:00")).replace(
        tzinfo=None
    )
    with SessionLocal() as db:
        service = ExecutionMetricsService(db)
        if args.granularity == "hour":
            count = service.rebuild_hour(project_id=args.project_id, bucket=bucket)
        else:
            count = service.rebuild_day(project_id=args.project_id, bucket=bucket)
        db.commit()
    print(f"rebuilt_rows={count}")


if __name__ == "__main__":
    main()
