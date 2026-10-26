"""Groq contracts use synthetic responses. No external credentials or API calls."""

import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from scripts.diagnose_groq import redacted_error
from tests.conftest import REVIEWER, WORKER
from worker.api import create_app
from worker.config import Settings
from worker.groq_planner import (
    GroqPlanner,
    accept_response,
    build_request,
    groq_http_error,
    retry_after_seconds,
    retry_delay,
    tool_failure_code,
    tool_repair_instruction,
)
from worker.planner import TOOLS, Action, PlannerError


def settings_for(tmp_path):
    return Settings(
        db_path=str(tmp_path / "groq.db"),
        mode="groq",
        groq_api_key="test-groq-secret",
        api_key="test-openai-secret",
        retry_delay=0,
    )


def result(name="discover_vendors", args=None, call_id="groq_call_1"):
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning": "PRIVATE_REASONING",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args or {})},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


def test_groq_requires_its_own_key_and_does_not_reuse_openai_key():
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        Settings(mode="groq", api_key="test-openai-secret")
    assert Settings(mode="groq", groq_api_key="test-groq-secret").mode == "groq"


def test_groq_configuration_reads_explicit_environment(monkeypatch):
    monkeypatch.setattr("worker.config.load_dotenv", lambda: None)
    for key, value in {
        "WORKER_MODE": "groq",
        "GROQ_API_KEY": "test-groq-secret",
        "GROQ_MODEL": "custom-tool-model",
        "GROQ_BASE_URL": "https://example.test/v1/",
    }.items():
        monkeypatch.setenv(key, value)
    config = Settings.from_env()
    assert config.groq_model == "custom-tool-model"
    assert config.groq_base_url == "https://example.test/v1"


def test_request_uses_chat_protocol_and_never_sends_credentials_in_prompt(tmp_path):
    task = {"goal": "Record the latest Acme Supplies invoice.", "memory": {}}
    body = build_request(task, settings_for(tmp_path))
    assert body["model"] == "openai/gpt-oss-20b"
    assert body["tool_choice"] == "required" and body["parallel_tool_calls"] is False
    assert body["reasoning_effort"] == "low" and body["stream"] is False
    assert len(body["tools"]) == len(TOOLS)
    assert body["messages"][0]["role"] == "system"
    serialized = json.dumps(body)
    assert "test-groq-secret" not in serialized and "test-openai-secret" not in serialized
    assert "include" not in body and "input" not in body  # No Responses-only request parameters.
    for spec in body["tools"]:
        assert spec["function"]["parameters"]["additionalProperties"] is False


def test_other_models_do_not_receive_gpt_oss_reasoning_parameter(tmp_path):
    config = Settings(
        db_path=str(tmp_path / "other.db"),
        mode="groq",
        groq_api_key="test-groq-secret",
        groq_model="custom-tool-model",
    )
    assert "reasoning_effort" not in build_request({"goal": "Test", "memory": {}}, config)


def test_result_observation_roundtrip_and_private_reasoning_exclusion(tmp_path):
    config = settings_for(tmp_path)
    task = {"goal": "Record the latest invoice from Acme Supplies.", "memory": {}}
    build_request(task, config)
    action = accept_response(task, result())
    assert action.name == "discover_vendors" and action.args == {}
    assert task["memory"]["llm_usage"][0] == {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
    planner = GroqPlanner(config)
    planner.observe(task, {"ok": True, "vendors": [{"id": "acme"}]})
    message = build_request(task, config)["messages"][-1]
    assert message["role"] == "tool" and message["tool_call_id"] == "groq_call_1"
    assert "PRIVATE_REASONING" not in json.dumps(task)
    assert "llm_pending_call" not in task["memory"]


@pytest.mark.parametrize(
    "mutation", ["empty", "parallel", "truncated", "bad_json", "array_args", "missing_id", "wrong_role"]
)
def test_malformed_tool_turns_never_enter_persisted_history(tmp_path, mutation):
    body = result()
    call = body["choices"][0]["message"]["tool_calls"][0]
    if mutation == "empty":
        body["choices"] = []
    elif mutation == "parallel":
        body["choices"][0]["message"]["tool_calls"].append(copy.deepcopy(call))
    elif mutation == "truncated":
        body["choices"][0]["finish_reason"] = "length"
    elif mutation == "bad_json":
        call["function"]["arguments"] = "{"
    elif mutation == "array_args":
        call["function"]["arguments"] = "[]"
    elif mutation == "missing_id":
        del call["id"]
    else:
        body["choices"][0]["message"]["role"] = "user"
    task = {"goal": "Record latest invoice", "memory": {}}
    build_request(task, settings_for(tmp_path))
    before = copy.deepcopy(task)
    with pytest.raises(PlannerError, match="no action executed"):
        accept_response(task, body)
    assert task == before


@pytest.mark.parametrize("usage", [[1], {"prompt_tokens": -1}, {"prompt_tokens": "100"}])
def test_bad_usage_metadata_does_not_leave_a_dangling_call(tmp_path, usage):
    task = {"goal": "Record latest invoice", "memory": {}}
    build_request(task, settings_for(tmp_path))
    body = result()
    body["usage"] = usage
    with pytest.raises(PlannerError):
        accept_response(task, body)
    assert len(task["memory"]["llm_history"]) == 1


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, None),
        ("", None),
        ("4", 4),
        ("1.5", 1.5),
        ("NaN", None),
        ("inf", None),
        ("invalid", None),
        ("-5", 0),
    ],
)
def test_retry_after_numeric_validation(header, expected):
    assert retry_after_seconds(header) == expected


def test_retry_after_http_date():
    header = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    assert 28 <= retry_after_seconds(header) <= 30


def test_retry_honors_delay_and_preserves_a_bounded_wait_budget(tmp_path):
    config = settings_for(tmp_path)
    assert retry_delay(httpx.Response(429, headers={"retry-after": "20"}), 0, config) == 20
    assert retry_delay(httpx.Response(429, headers={"retry-after": "120"}), 0, config) is None
    assert retry_delay(httpx.Response(429), 2, config) is None
    assert retry_delay(httpx.Response(401), 0, config) is None


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500])
def test_error_messages_never_echo_provider_bodies(status):
    error = groq_http_error(
        httpx.Response(status, text="SECRET_RESPONSE_BODY", headers={"retry-after": "75"})
    )
    assert "SECRET_RESPONSE_BODY" not in str(error) and str(status) in str(error)
    assert "75 seconds" in str(error)


def test_api_factory_selects_groq_and_exposes_correct_model(tmp_path):
    app = create_app(settings_for(tmp_path))
    assert isinstance(app.state.engine.planner, GroqPlanner)
    config_endpoint = next(
        route.endpoint for route in app.routes if getattr(route, "path", None) == "/api/config"
    )
    config = config_endpoint()
    assert config["mode"] == "groq" and config["model"] == "openai/gpt-oss-20b"
    assert "test-groq-secret" not in json.dumps(config)


def test_provider_tool_error_code_is_visible_without_failed_generation():
    response = httpx.Response(
        400, json={"error": {"code": "tool_use_failed", "failed_generation": "PRIVATE_GENERATION"}}
    )
    assert tool_failure_code(response) == "tool_use_failed"
    error = str(groq_http_error(response))
    assert "tool_use_failed" in error and "PRIVATE_GENERATION" not in error


def test_unknown_error_codes_are_not_echoed():
    response = httpx.Response(400, json={"error": {"code": "SENSITIVE_UNKNOWN_VALUE"}})
    assert tool_failure_code(response) is None
    assert "SENSITIVE_UNKNOWN_VALUE" not in str(groq_http_error(response))


def test_diagnostic_redacts_known_credentials_and_key_patterns():
    response = httpx.Response(
        400,
        json={
            "error": {
                "code": "tool_use_failed",
                "message": "token LOCAL_SECRET and gsk_example_key_value and sk-example_key_value",
                "failed_generation": "MUST_NOT_BE_EXPORTED",
            }
        },
    )
    report = json.dumps(redacted_error(response, ["LOCAL_SECRET"]))
    assert "LOCAL_SECRET" not in report and "gsk_" not in report and "sk-" not in report
    assert "MUST_NOT_BE_EXPORTED" not in report and "tool_use_failed" in report


def test_nine_step_plan_regression_matches_user_report_and_validates_locally(tmp_path):
    steps = [
        "Find vendor",
        "Select vendor",
        "Search invoices",
        "Read source",
        "Validate fields",
        "Check duplicate",
        "Apply approval policy",
        "Record invoice",
        "Read back and verify",
    ]
    config = settings_for(tmp_path)
    task = {"goal": "Record latest Acme Supplies invoice", "memory": {}}
    request = build_request(task, config)
    plan_schema = next(
        t["function"]["parameters"] for t in request["tools"] if t["function"]["name"] == "set_plan"
    )
    assert plan_schema["properties"]["steps"]["maxItems"] >= len(steps)
    action = accept_response(task, result("set_plan", {"steps": steps}))
    validated = TOOLS[action.name][0].model_validate(action.args)
    assert validated.steps == steps


def test_plan_still_has_a_bounded_size():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TOOLS["set_plan"][0].model_validate({"steps": ["Action"] * 25})


def test_plan_repair_explains_current_constraint_without_echoing_provider_text():
    response = httpx.Response(
        400,
        json={
            "error": {
                "code": "tool_use_failed",
                "message": "parameters for tool set_plan did not match schema: "
                "`/steps`: maxItems: got 9, want 8. "
                "UNTRUSTED_INSTRUCTION",
            }
        },
    )
    correction = tool_repair_instruction(response)
    assert "3 to 24 strings" in correction and "set_plan" in correction
    assert "UNTRUSTED_INSTRUCTION" not in correction and "want 8" not in correction


def test_runtime_failed_tool_generation_is_retried_without_executing_it(tmp_path):
    config = settings_for(tmp_path)
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(
                400, json={"error": {"code": "tool_use_failed", "failed_generation": "PRIVATE_GENERATION"}}
            )
        return httpx.Response(200, json=result())

    planner = GroqPlanner(config, transport=httpx.MockTransport(handler))
    task = {"goal": "Record latest Acme invoice", "memory": {}}
    assert asyncio.run(planner.choose(task, config)).name == "discover_vendors"
    assert len(requests) == 2 and len(task["memory"]["llm_history"]) == 2
    assert "PRIVATE_GENERATION" not in json.dumps(requests)


def test_runtime_http_adapter_sends_groq_credential_only_in_header(tmp_path):
    config = settings_for(tmp_path)
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/openai/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-groq-secret"
        return httpx.Response(200, json=result())

    planner = GroqPlanner(config, transport=httpx.MockTransport(handler))
    task = {"goal": "Record latest Acme Supplies invoice", "memory": {}}
    assert asyncio.run(planner.choose(task, config)).name == "discover_vendors"
    assert "test-groq-secret" not in requests[0].content.decode()


def test_runtime_retry_after_is_respected_without_actual_sleep(tmp_path):
    config = settings_for(tmp_path)
    calls, delays = [], []

    def handler(request):
        calls.append(request)
        return (
            httpx.Response(429, headers={"retry-after": "7"})
            if len(calls) == 1
            else httpx.Response(200, json=result())
        )

    async def fake_sleep(delay):
        delays.append(delay)

    planner = GroqPlanner(config, transport=httpx.MockTransport(handler), sleep=fake_sleep)
    assert asyncio.run(planner.choose({"goal": "Test", "memory": {}}, config)).name == "discover_vendors"
    assert delays == pytest.approx([7], abs=0.05) and len(calls) == 2


def test_runtime_groq_drives_company_workflow_and_human_approval(tmp_path):
    config = settings_for(tmp_path)
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
        return httpx.Response(200, json=result(action.name, action.args, f"call_{len(requests)}"))

    app = create_app(config, planner=GroqPlanner(config, transport=httpx.MockTransport(handler)))
    with TestClient(app, headers=WORKER) as client:
        task = client.post("/api/tasks", json={"goal": "Record latest Orbit Cloud invoice."}).json()
        assert task["mode"] == "groq" and task["status"] == "awaiting_approval"
        assert client.get("/api/records").json() == []
        reviewed = client.post(
            f"/api/tasks/{task['id']}/review",
            headers=REVIEWER,
            json={"decision": "approve", "reviewer": "Test human"},
        ).json()
        assert reviewed["status"] == "succeeded" and reviewed["memory"]["verified"]
        assert len(client.get("/api/records").json()) == 1
    assert json.loads(requests[8]["messages"][-1]["content"])["decision"] == "approve"
