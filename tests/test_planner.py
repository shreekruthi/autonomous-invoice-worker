import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import WORKER
from worker.api import create_app
from worker.config import Settings
from worker.planner import TOOLS, Action, DemoPlanner, OpenAIPlanner, PlannerError


class ScriptPlanner:
    def __init__(self, actions):
        self.actions = iter(actions)

    async def choose(self, task, settings):
        return next(self.actions, Action("finish", {}))

    def observe(self, task, result):
        pass


@pytest.mark.parametrize(
    "action",
    [
        Action("finish", {}),
        Action("record_invoice", {}),
        Action("shell", {"command": "whoami"}),
        Action("set_plan", {"steps": "not an array"}),
    ],
)
def test_adversarial_planner_cannot_bypass_guards_or_budget(tmp_path, action):
    app = create_app(
        Settings(db_path=str(tmp_path / "guards.db"), max_steps=3), planner=ScriptPlanner([action] * 3)
    )
    with TestClient(app, headers=WORKER) as client:
        task = client.post("/api/tasks", json={"goal": "Record the latest Acme Supplies invoice"}).json()
        assert task["status"] == "failed" and task["steps"] == 3
        assert not client.get("/api/records").json()
        events = client.get(f"/api/tasks/{task['id']}/events").json()
        assert len([e for e in events if e["kind"] == "guard_rejected"]) == 3


def response_for(name="discover_vendors", args=None, status="completed"):
    return {
        "status": status,
        "output": [
            {"type": "function_call", "name": name, "arguments": json.dumps(args or {}), "call_id": "call_1"}
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }


def llm_settings(tmp_path):
    return Settings(
        db_path=str(tmp_path / "llm.db"), mode="openai", api_key="test-placeholder", retry_delay=0
    )


def test_responses_api_contract_and_observation_roundtrip(tmp_path):
    settings = llm_settings(tmp_path)
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-placeholder"
        assert request.url.path == "/v1/responses"
        return httpx.Response(200, json=response_for())

    planner = OpenAIPlanner(settings, httpx.MockTransport(handler))
    task = {"goal": "Record the latest Acme Supplies invoice", "memory": {}}
    action = asyncio.run(planner.choose(task, settings))
    assert action.name == "discover_vendors"
    planner.observe(task, {"ok": True, "vendors": [{"id": "acme", "name": "Acme Supplies"}]})
    asyncio.run(planner.choose(task, settings))
    assert requests[1]["input"][-1]["type"] == "function_call_output"
    assert requests[1]["input"][-1]["call_id"] == "call_1"
    assert requests[0]["parallel_tool_calls"] is False and requests[0]["store"] is False
    for tool in requests[0]["tools"]:
        assert tool["strict"] and tool["parameters"]["additionalProperties"] is False
        assert set(tool["parameters"].get("required", [])) == set(tool["parameters"]["properties"])
    assert task["memory"]["llm_usage"][0]["total_tokens"] == 15


@pytest.mark.parametrize("code", [401, 403, 400])
def test_provider_errors_do_not_leak_body_or_switch_to_demo(tmp_path, code):
    settings = llm_settings(tmp_path)
    planner = OpenAIPlanner(settings, httpx.MockTransport(lambda r: httpx.Response(code, text="SECRET_BODY")))
    with pytest.raises(PlannerError) as exc:
        asyncio.run(planner.choose({"goal": "Test", "memory": {}}, settings))
    assert "SECRET_BODY" not in str(exc.value)


def test_provider_429_is_retried(tmp_path):
    settings = llm_settings(tmp_path)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429) if len(calls) < 3 else httpx.Response(200, json=response_for())

    planner = OpenAIPlanner(settings, httpx.MockTransport(handler))
    assert asyncio.run(planner.choose({"goal": "Test", "memory": {}}, settings)).name == "discover_vendors"
    assert len(calls) == 3


@pytest.mark.parametrize(
    "body",
    [
        {"output": []},
        response_for(status="incomplete"),
        {
            "status": "completed",
            "output": [{"type": "function_call", "name": "x", "call_id": "1", "arguments": "not json"}],
        },
    ],
)
def test_malformed_or_incomplete_llm_output_executes_nothing(tmp_path, body):
    settings = llm_settings(tmp_path)
    planner = OpenAIPlanner(settings, httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    app = create_app(settings, planner=planner)
    with TestClient(app, headers=WORKER) as client:
        task = client.post("/api/tasks", json={"goal": "Record latest Acme Supplies invoice"}).json()
        assert task["status"] == "failed" and task["steps"] == 0
        assert not client.get("/api/records").json()


def test_llm_http_adapter_drives_real_executor_end_to_end(tmp_path):
    """Scripted provider contract test, NOT a live model autonomy evaluation."""
    settings = llm_settings(tmp_path)
    actions = iter(
        [
            Action("set_plan", {"steps": ["Find invoice", "Validate and record", "Verify outcome"]}),
            Action("discover_vendors", {}),
            Action("select_vendor", {"vendor_id": "acme"}),
            Action("search_invoices", {}),
            Action("read_invoice", {"invoice_id": "acme-latest"}),
            *[
                Action(n, {})
                for n in ["prepare_invoice", "lookup_record", "record_invoice", "verify_record", "finish"]
            ],
        ]
    )

    def handler(request):
        action = next(actions)
        return httpx.Response(200, json=response_for(action.name, action.args))

    app = create_app(settings, planner=OpenAIPlanner(settings, httpx.MockTransport(handler)))
    with TestClient(app, headers=WORKER) as client:
        task = client.post("/api/tasks", json={"goal": "Record latest Acme Supplies invoice"}).json()
        assert task["status"] == "succeeded" and task["mode"] == "openai"
        assert len(task["memory"]["llm_usage"]) == 9
        assert len(client.get("/api/records").json()) == 1


def test_missing_key_is_configuration_error():
    with pytest.raises(ValueError, match="no silent demo fallback"):
        Settings(mode="openai")


def test_no_approval_or_general_execution_tools_are_exposed():
    assert "approve" not in TOOLS and "shell" not in TOOLS and "browse" not in TOOLS
    assert isinstance(DemoPlanner(), DemoPlanner)


def test_llm_approval_resume_receives_human_decision(tmp_path):
    settings = llm_settings(tmp_path)
    actions = iter(
        [
            Action("set_plan", {"steps": ["Find source", "Validate and approve", "Record and verify"]}),
            Action("discover_vendors", {}),
            Action("select_vendor", {"vendor_id": "orbit"}),
            Action("search_invoices", {}),
            Action("read_invoice", {"invoice_id": "orbit-latest"}),
            *[
                Action(n, {})
                for n in [
                    "prepare_invoice",
                    "lookup_record",
                    "request_approval",
                    "record_invoice",
                    "verify_record",
                    "finish",
                ]
            ],
        ]
    )
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        action = next(actions)
        return httpx.Response(200, json=response_for(action.name, action.args))

    app = create_app(settings, planner=OpenAIPlanner(settings, httpx.MockTransport(handler)))
    with TestClient(app, headers=WORKER) as client:
        task = client.post("/api/tasks", json={"goal": "Record latest Orbit Cloud invoice"}).json()
        assert task["status"] == "awaiting_approval"
        result = client.post(
            f"/api/tasks/{task['id']}/review",
            headers={"Authorization": "Bearer local-reviewer"},
            json={"decision": "approve", "reviewer": "Human"},
        )
        assert result.json()["status"] == "succeeded"
    assert json.loads(requests[8]["input"][-1]["content"])["decision"] == "approve"
