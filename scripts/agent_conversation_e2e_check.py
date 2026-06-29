import argparse
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select

from app.api.v1.routers.agents import create_agent_run
from app.db.session import SessionLocal, engine
from app.models.user import User
from app.schemas.agent import AgentRunCreateRequest
from app.services.agent_runtime_service import AgentModelHealthService, AgentRuntimeService


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a real Agent conversation E2E diagnostic.")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--intent", default="Reply exactly: Agent e2e ok.")
    parser.add_argument("--max-iterations", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--skip-live-health", action="store_true")
    args = parser.parse_args()

    print("db_dialect=", engine.dialect.name)
    print("db_database=", getattr(engine.url, "database", None))

    if not args.skip_live_health:
        health = AgentModelHealthService().check(live=True)
        print(
            "model_health=",
            {
                "configured": health.get("configured"),
                "reachable": health.get("reachable"),
                "first_delta_received": health.get("first_delta_received"),
                "completed": health.get("completed"),
                "model": health.get("model"),
                "finish_reason": health.get("finish_reason"),
                "error_code": health.get("error_code"),
                "latency_ms": health.get("latency_ms"),
            },
        )
        if not health.get("reachable") or not health.get("first_delta_received"):
            print("result=failed_before_run")
            return 1

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.id == args.user_id))
        if user is None:
            print("result=user_not_found")
            return 1
        response = create_agent_run(
            payload=AgentRunCreateRequest(
                project_id=args.project_id,
                intent=args.intent,
                max_iterations=args.max_iterations,
                auto_complete=False,
            ),
            db=db,
            current_user=user,
        )
        run_id = response["data"]["run_id"]
        conversation_id = response["data"]["conversation_id"]
        print("created_run_id=", run_id)
        print("conversation_id=", conversation_id)

    deadline = time.monotonic() + args.timeout_seconds
    last_sequence = 0
    event_types: list[str] = []
    delta_count = 0
    terminal_summary = None

    while time.monotonic() < deadline:
        time.sleep(args.poll_interval)
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.id == args.user_id))
            if user is None:
                print("result=user_not_found_during_poll")
                return 1
            snapshot = AgentRuntimeService(db).get_event_snapshot(
                run_id=run_id,
                after_sequence=last_sequence,
                limit=200,
                current_user=user,
            )
            for event in snapshot["events"]:
                event_types.append(event.event_type)
                if event.event_type == "model.delta":
                    delta_count += 1
                print("event=", event.event_seq, event.event_type)
            if snapshot["events"]:
                last_sequence = snapshot["next_after_sequence"]
            if snapshot["terminal"] and last_sequence >= snapshot["latest_event_sequence"]:
                terminal_summary = AgentRuntimeService(db).get_run_summary(run_id=run_id, current_user=user)
                break

    if terminal_summary is None:
        print("result=timeout")
        print("last_sequence=", last_sequence)
        print("event_types_tail=", event_types[-10:])
        return 1

    status = terminal_summary["run"].status
    assistant_message = terminal_summary["assistant_message"] or ""
    print("terminal_status=", status)
    print("assistant_visible=", terminal_summary["assistant_visible"])
    print("assistant_message_prefix=", assistant_message[:200])
    print("model_delta_count=", delta_count)
    print("latest_event_types=", terminal_summary["latest_event_types"])

    ok = (
        status == "completed"
        and terminal_summary["assistant_visible"]
        and delta_count > 0
        and "model.started" in event_types
        and "run.completed" in event_types
    )
    print("result=", "ok" if ok else "failed")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
