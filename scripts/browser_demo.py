"""Record the actual local UI. Optional Playwright dependency and browser required."""

import argparse
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default="artifacts/browser")
    parser.add_argument("--channel", default=None, help="Use installed browser, e.g. msedge")
    parser.add_argument(
        "--faults", action="store_true", help="Enable read and post-commit recovery demonstration"
    )
    args = parser.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        parser.exit(1, 'Install optional browser tools first: pip install -e ".[browser]"\n')
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    token = os.getenv("WORKER_API_TOKEN", "local-worker")
    reviewer = os.getenv("REVIEWER_TOKEN", "local-reviewer")
    console_errors = []
    with httpx.Client(base_url=args.url, headers={"Authorization": f"Bearer {token}"}) as client:
        before = client.get("/api/records")
        before.raise_for_status()
        if before.json():
            parser.exit(1, "Use a fresh WORKER_DB for a clear recording; the ledger must be empty.\n")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel=args.channel)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1100},
            record_video_dir=str(out),
            record_video_size={"width": 1440, "height": 1100},
        )
        page = context.new_page()
        page.on("pageerror", lambda error: console_errors.append(str(error)))
        page.goto(args.url, wait_until="networkidle")
        page.locator(".credentials summary").click()
        page.locator("#worker-token").fill(token)
        page.locator("#reviewer-token").fill(reviewer)
        page.locator("#reviewer-name").fill("Browser demo reviewer")
        page.locator("#connect").click()
        page.wait_for_load_state("networkidle")
        page.locator(".credentials summary").click()
        page.wait_for_function("!document.querySelector('#mode').textContent.includes('Connecting')")
        if args.faults:
            page.locator("#inject").click()
            page.get_by_text("One read outage and one lost write response armed.", exact=False).wait_for()
        page.locator("#goal").fill("Find the latest invoice from Acme Supplies, enter it, and verify it.")
        page.locator("#run").click()
        page.locator(".evidence").wait_for(timeout=240000)
        page.screenshot(path=str(out / "01-verified.png"), full_page=True)
        # Brief holds are intentional for a readable recording, not test synchronization.
        page.wait_for_timeout(1200)
        page.locator('[data-tab="ledger"]').click()
        page.get_by_text("ACM-1020", exact=True).wait_for()
        page.screenshot(path=str(out / "02-ledger.png"), full_page=True)
        page.wait_for_timeout(1000)
        page.locator('[data-tab="trace"]').click()
        page.locator("#run").click()
        page.locator(".task-summary").filter(has_text="Verified existing ACM-1020").wait_for(timeout=240000)
        page.wait_for_timeout(1000)
        page.locator("#goal").fill("Record the newest invoice from Orbit Cloud.")
        page.locator("#run").click()
        page.locator(".review").wait_for(timeout=240000)
        page.screenshot(path=str(out / "03-approval.png"), full_page=True)
        page.wait_for_timeout(1200)
        page.get_by_role("button", name="Approve & resume", exact=True).click()
        page.locator(".evidence").wait_for(timeout=240000)
        page.wait_for_timeout(1200)
        page.locator("#goal").fill("Record the latest invoice from Broken Labs.")
        page.locator("#run").click()
        page.get_by_text("Expected exactly one Due field; ask for a corrected source", exact=True).wait_for(
            timeout=240000
        )
        page.screenshot(path=str(out / "04-missing-data.png"), full_page=True)
        page.wait_for_timeout(1200)
        page.locator('[data-tab="ledger"]').click()
        page.screenshot(path=str(out / "05-final-ledger.png"), full_page=True)
        video = page.video
        context.close()
        if video:
            video.save_as(str(out / "demo.webm"))
            video.delete()
        browser.close()
    with httpx.Client(base_url=args.url, headers={"Authorization": f"Bearer {token}"}) as client:
        records = client.get("/api/records").json()
        tasks = client.get("/api/tasks").json()
        assert len(records) == 2, "Duplicate or missing ledger row"
        assert {t["status"] for t in tasks} == {"succeeded", "needs_input"}
    assert not console_errors, console_errors
    (out / "browser-check.json").write_text(
        json.dumps(
            {
                "passed": True,
                "console_errors": console_errors,
                "record_count": len(records),
                "mode": tasks[0]["mode"],
                "scenarios": 4,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Browser demo verified and recorded: {out}")


if __name__ == "__main__":
    main()
