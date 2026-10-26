"""Real network API demo. Start the server first. All data is synthetic."""

import argparse
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv


def main():
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="http://127.0.0.1:8000")
    p.add_argument("--faults", action="store_true", help="Requires server ENABLE_FAULTS=true")
    p.add_argument(
        "--approve-demo", action="store_true", help="Explicitly authorize synthetic Orbit approval"
    )
    p.add_argument("--out", default="artifacts/demo")
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    reviewer = {"Authorization": "Bearer " + os.getenv("REVIEWER_TOKEN", "local-reviewer")}
    with httpx.Client(
        base_url=args.url,
        timeout=240,
        headers={"Authorization": "Bearer " + os.getenv("WORKER_API_TOKEN", "local-worker")},
    ) as c:

        def request(method, path, **kwargs):
            result = c.request(method, path, **kwargs)
            result.raise_for_status()
            return result.json()

        config = request("GET", "/api/config")
        print(
            f"MODE: {config['mode']}"
            + (" (deterministic; not LLM autonomy)" if config["mode"] == "demo" else "")
        )
        if args.faults:
            for name in ["read_invoice", "record_after"]:
                request("POST", "/api/faults", json={"name": name, "count": 1}, headers=reviewer)
        tasks = []
        for label, vendor in [
            ("standard", "Acme Supplies"),
            ("duplicate", "Acme Supplies"),
            ("approval", "Orbit Cloud"),
            ("missing-data", "Broken Labs"),
        ]:
            task = request("POST", "/api/tasks", json={"goal": f"Record the latest invoice from {vendor}."})
            print(f"{label}: {task['status']} - {task['summary']}")
            if task["status"] == "awaiting_approval" and args.approve_demo:
                task = request(
                    "POST",
                    f"/api/tasks/{task['id']}/review",
                    headers=reviewer,
                    json={"decision": "approve", "reviewer": "Demo script: explicit --approve-demo"},
                )
                print(f"after human-authorized demo approval: {task['status']}")
            bundle = request("GET", f"/api/tasks/{task['id']}/export")
            (out / f"{label}.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")
            tasks.append({"scenario": label, "id": task["id"], "status": task["status"]})
        records = request("GET", "/api/records")
        (out / "summary.json").write_text(
            json.dumps({"config": config, "tasks": tasks, "records": records}, indent=2), encoding="utf-8"
        )
        print(f"Ledger contains {len(records)} record(s). Evidence: {out.resolve()}")
        expected = [
            "succeeded",
            "succeeded",
            "succeeded" if args.approve_demo else "awaiting_approval",
            "needs_input",
        ]
        if [t["status"] for t in tasks] != expected:
            raise SystemExit("Scenario outcome mismatch; inspect evidence. LLM behavior may vary.")


if __name__ == "__main__":
    main()
