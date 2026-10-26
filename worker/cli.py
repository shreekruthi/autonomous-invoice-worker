import argparse
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run and inspect sandbox invoice tasks")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("goal")
    show = sub.add_parser("show")
    show.add_argument("task_id")
    review = sub.add_parser("review")
    review.add_argument("task_id")
    review.add_argument("decision", choices=["approve", "reject"])
    review.add_argument("--reviewer", required=True)
    export = sub.add_parser("export")
    export.add_argument("task_id")
    export.add_argument("--out", required=True)
    args = parser.parse_args()
    token = (
        os.getenv("REVIEWER_TOKEN", "local-reviewer")
        if args.command == "review"
        else os.getenv("WORKER_API_TOKEN", "local-worker")
    )
    try:
        with httpx.Client(
            base_url=args.url, headers={"Authorization": f"Bearer {token}"}, timeout=240
        ) as client:
            if args.command == "run":
                response = client.post("/api/tasks", json={"goal": args.goal})
            elif args.command == "review":
                response = client.post(
                    f"/api/tasks/{args.task_id}/review",
                    json={"decision": args.decision, "reviewer": args.reviewer},
                )
            else:
                suffix = "/export" if args.command == "export" else ""
                response = client.get(f"/api/tasks/{args.task_id}{suffix}")
            response.raise_for_status()
            result = response.json()
        if args.command == "export":
            path = Path(args.out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(f"Evidence saved to {path}")
        else:
            print(json.dumps(result, indent=2))
    except (httpx.HTTPError, ValueError) as exc:
        parser.exit(1, f"Request failed: {type(exc).__name__}. Check server, credentials and task ID.\n")


if __name__ == "__main__":
    main()
