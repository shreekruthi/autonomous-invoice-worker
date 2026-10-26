"""Repeatable deterministic reliability evaluation; not an LLM autonomy benchmark."""

import argparse
import json
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from worker.api import create_app
from worker.config import Settings

W = {"Authorization": "Bearer local-worker"}
R = {"Authorization": "Bearer local-reviewer"}


def evaluate(temp_root=None):
    scenarios = [
        ("standard", "Acme Supplies", None, None, "succeeded", 1),
        ("read-retry", "Acme Supplies", "read_invoice", None, "succeeded", 1),
        ("lost-write-response", "Acme Supplies", "record_after", None, "succeeded", 1),
        ("duplicate", "Acme Supplies", None, "duplicate", "succeeded", 1),
        ("approval-pause", "Orbit Cloud", None, None, "awaiting_approval", 0),
        ("approval-resume", "Orbit Cloud", None, "approve", "succeeded", 1),
        ("approval-reject", "Orbit Cloud", None, "reject", "rejected", 0),
        ("missing-field", "Broken Labs", None, None, "needs_input", 0),
        ("no-invoices", "Empty Studio", None, None, "needs_input", 0),
        ("verification-mismatch", "Acme Supplies", "verify_corrupt", None, "needs_input", 1),
    ]
    rows = []
    for name, vendor, injected, action, expected, count in scenarios:
        with tempfile.TemporaryDirectory(dir=temp_root) as temp:
            settings = Settings(db_path=str(Path(temp) / "eval.db"), enable_faults=True, retry_delay=0)
            with TestClient(create_app(settings), headers=W) as client:
                start = time.monotonic()
                if injected:
                    client.post(
                        "/api/faults", json={"name": injected, "count": 1}, headers=R
                    ).raise_for_status()

                def run(vendor=vendor):
                    response = client.post(
                        "/api/tasks", json={"goal": f"Record the latest invoice from {vendor}."}
                    )
                    response.raise_for_status()
                    return response.json()

                if action == "duplicate":
                    run()
                task = run()
                if action in {"approve", "reject"}:
                    response = client.post(
                        f"/api/tasks/{task['id']}/review",
                        headers=R,
                        json={"decision": action, "reviewer": "Evaluation harness"},
                    )
                    response.raise_for_status()
                    task = response.json()
                records = client.get("/api/records").json()
                events = client.get(f"/api/tasks/{task['id']}/events").json()
                evidence = bool(task["memory"].get("verified"))
                passed = task["status"] == expected and len(records) == count
                passed = passed and (task["status"] != "succeeded" or evidence)
                rows.append(
                    {
                        "scenario": name,
                        "passed": passed,
                        "status": task["status"],
                        "expected_status": expected,
                        "record_count": len(records),
                        "verified": evidence,
                        "steps": task["steps"],
                        "tool_errors": sum(e["kind"] == "tool_error" for e in events),
                        "elapsed_ms": round((time.monotonic() - start) * 1000),
                    }
                )
    return {
        "mode": "deterministic_demo",
        "live_llm_evaluated": False,
        "passed": sum(r["passed"] for r in rows),
        "total": len(rows),
        "scenarios": rows,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default="artifacts/evaluation.json")
    p.add_argument("--temp-root", default=None)
    args = p.parse_args()
    report = evaluate(args.temp_root)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Deterministic reliability: {report['passed']}/{report['total']} passed. {path}")
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
