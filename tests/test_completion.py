"""Executor transition tests with SQLite and eager read stubs; no model/network access.

All awaited dependencies here return inline. The small driver fails if a coroutine
attempts asynchronous I/O, so these unit tests need no platform event-loop resources.
The HTTP transport itself is covered separately by the integration tests.
"""

import copy
import json

import pytest

from worker.config import Settings
from worker.domain import digest, parse_invoice
from worker.engine import Engine, GuardError, finish_verified_task
from worker.planner import Action, PlannerError
from worker.store import Store, now


def inline(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    finally:
        coroutine.close()
    pytest.fail("This unit-test dependency unexpectedly attempted asynchronous waiting")


class VerifyOnlyPlanner:
    def __init__(self):
        self.calls = 0

    async def choose(self, task, settings):
        self.calls += 1
        if self.calls > 1:
            raise PlannerError("Simulated provider 429 after verification")
        return Action("verify_record", {})

    def observe(self, task, result):
        pass


class NoModelPlanner(VerifyOnlyPlanner):
    async def choose(self, task, settings):
        self.calls += 1
        raise AssertionError("Verified-checkpoint recovery must not call a model")


def setup_engine(tmp_path, planner, max_steps=24):
    config = Settings(
        db_path=str(tmp_path / "completion.db"),
        mode="groq",
        groq_api_key="test-groq-secret",
        retry_delay=0,
        max_steps=max_steps,
    )
    store = Store(config.db_path)
    store.seed()
    payload = parse_invoice(store.source("acme-latest"))
    fingerprint = digest(payload)
    record_id = "inv_" + fingerprint[:24]
    with store.connect() as db:
        db.execute(
            "INSERT INTO records VALUES(?,?,?,?,?,?)",
            (
                record_id,
                payload["vendor_id"],
                payload["invoice_number"],
                fingerprint,
                json.dumps(payload),
                now(),
            ),
        )
    task = store.create_task("Record the latest Acme Supplies invoice and verify it.", "groq")
    task["memory"] = {
        "plan": ["Find", "Record", "Verify"],
        "vendor_id": "acme",
        "prepared": payload,
        "lookup_done": True,
        "record_id": record_id,
    }
    store.save(task)
    engine = Engine(store, config, company_app=None, planner=planner)
    reads = []

    async def read(method, path, **kwargs):
        assert method == "GET", "Completing/recovering this task must never write another invoice"
        reads.append(path)
        if path.startswith("/records/"):
            row = next(r for r in store.rows("records") if r["id"] == path.split("/")[-1])
            return row | {"payload": json.loads(row["payload"])}
        if path.startswith("/invoices/"):
            return store.source(path.split("/")[-1])
        raise AssertionError(f"Unexpected endpoint {path}")

    engine.request = read
    return engine, task, reads


def add_legacy_verified_checkpoint(engine, task):
    payload = task["memory"]["prepared"]
    task.update(status="interrupted", steps=9)
    task["memory"]["verified"] = {
        "record_id": task["memory"]["record_id"],
        "fingerprint": digest(payload),
        "source_sha256": payload["source_sha256"],
        "verified_at": "2026-10-25T00:00:00+00:00",
    }
    engine.store.save(task)


def test_successful_verification_completes_before_a_rate_limited_final_model_turn(tmp_path):
    planner = VerifyOnlyPlanner()
    engine, task, reads = setup_engine(tmp_path, planner)
    result = inline(engine.run(task["id"]))
    assert result["status"] == "succeeded" and planner.calls == 1
    assert len(reads) == 2 and len(engine.store.rows("records")) == 1
    assert engine.store.task(task["id"])["status"] == "succeeded"
    completed = [e for e in engine.store.events(task["id"]) if e["kind"] == "completed"]
    assert completed[0]["data"]["reason"] == "independent_verification"


def test_verification_on_last_allowed_action_still_completes(tmp_path):
    planner = VerifyOnlyPlanner()
    engine, task, _ = setup_engine(tmp_path, planner, max_steps=1)
    result = inline(engine.run(task["id"]))
    assert result["status"] == "succeeded" and result["steps"] == 1 and planner.calls == 1


def test_legacy_verified_checkpoint_is_rechecked_without_any_provider_call(tmp_path):
    planner = NoModelPlanner()
    engine, task, reads = setup_engine(tmp_path, planner)
    add_legacy_verified_checkpoint(engine, task)
    result = inline(engine.run(task["id"]))
    assert result["status"] == "succeeded" and planner.calls == 0
    assert len(reads) == 2 and result["steps"] == 10
    assert result["memory"]["verified"]["verified_at"] != "2026-10-25T00:00:00+00:00"


def test_legacy_verified_checkpoint_does_not_complete_if_ledger_changed(tmp_path):
    planner = NoModelPlanner()
    engine, task, _ = setup_engine(tmp_path, planner)
    add_legacy_verified_checkpoint(engine, task)
    with engine.store.connect() as db:
        payload = copy.deepcopy(task["memory"]["prepared"])
        payload["amount_minor"] += 1
        db.execute("UPDATE records SET payload=?", (json.dumps(payload),))
    result = inline(engine.run(task["id"]))
    assert result["status"] == "needs_input" and "verified" not in result["memory"]
    assert planner.calls == 0


@pytest.mark.parametrize("mismatch", ["missing", "record_id", "fingerprint", "source_sha256"])
def test_completion_requires_evidence_matching_the_actual_prepared_invoice(tmp_path, mismatch):
    engine, task, _ = setup_engine(tmp_path, VerifyOnlyPlanner())
    add_legacy_verified_checkpoint(engine, task)
    if mismatch == "missing":
        task["memory"].pop("verified")
    else:
        task["memory"]["verified"][mismatch] = "wrong"
    with pytest.raises(GuardError):
        finish_verified_task(task)
    assert task["status"] != "succeeded"
