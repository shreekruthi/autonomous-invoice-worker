"""Run final offline checks and record actual results; never calls a real LLM."""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path


def source_digest(root):
    digest = hashlib.sha256()
    paths = [*root.glob("*.toml"), *root.glob("*.lock"), *root.glob("*.ps1")]
    for directory in ("worker", "scripts", "tests"):
        paths.extend((root / directory).rglob("*.py"))
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def verify(out, timeout):
    root = Path(__file__).resolve().parent.parent
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "source_sha256": source_digest(root),
        "live_llm_evaluated": False,
        "full_suite_completed": False,
        "passed": False,
        "stages": [],
    }
    stages = [
        ("lint", ["ruff", "check", "."]),
        ("format", ["ruff", "format", "--check", "."]),
        (
            "tests",
            [
                "pytest",
                "--cov=worker",
                "--cov-report=json:" + str(out / "coverage.json"),
                "--junitxml=" + str(out / "tests.xml"),
            ],
        ),
        ("reliability", ["scripts.evaluate", "--out", str(out / "evaluation.json")]),
    ]
    for name, arguments in stages:
        print(f"Checking {name}...", flush=True)
        started = time.monotonic()
        stage = {"name": name, "passed": False, "timed_out": False, "log": name + ".log"}
        with (out / stage["log"]).open("w", encoding="utf-8") as log:
            try:
                result = subprocess.run(
                    [sys.executable, "-m", *arguments],
                    cwd=root,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    check=False,
                )
                stage.update(returncode=result.returncode, passed=result.returncode == 0)
            except subprocess.TimeoutExpired:
                stage["timed_out"] = True
        stage["seconds"] = round(time.monotonic() - started, 2)
        report["stages"].append(stage)
        if name == "tests" and stage["passed"]:
            suites = ET.parse(out / "tests.xml").getroot()
            report["tests"] = {
                key: sum(int(suite.get(key, 0)) for suite in suites.iter("testsuite"))
                for key in ("tests", "failures", "errors", "skipped")
            }
            report["full_suite_completed"] = True
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"{name}: {'PASS' if stage['passed'] else 'INCOMPLETE / FAILED'}", flush=True)
        if not stage["passed"]:
            break
    report["passed"] = len(report["stages"]) == len(stages) and all(
        stage["passed"] for stage in report["stages"]
    )
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="artifacts/submission-check")
    parser.add_argument("--timeout", type=int, default=180, help="Maximum seconds for each stage")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    report = verify(args.out, args.timeout)
    status = "PASS" if report["passed"] else "INCOMPLETE / FAILED"
    print(f"RESULT: {status}. Report: {Path(args.out).resolve() / 'report.json'}")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
