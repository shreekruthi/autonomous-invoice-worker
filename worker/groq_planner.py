"""Groq-hosted model decisions via Chat Completions, with real local tool execution.

Free-tier eligibility and quotas belong to the user's Groq account, not this adapter.
Provider response bodies and credentials are deliberately excluded from error messages.
"""

import asyncio
import json
import math
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from worker.planner import SYSTEM, TOOLS, Action, PlannerError


def retry_after_seconds(value: str | None) -> float | None:
    """Support both Retry-After formats without trusting arbitrary provider text."""
    if not value:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            delay = (stamp - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, delay) if math.isfinite(delay) else None


def groq_http_error(response: httpx.Response) -> PlannerError:
    status = response.status_code
    code = tool_failure_code(response)
    advice = {
        400: "The configured model rejected the request; check GROQ_MODEL and tool support.",
        401: "Check GROQ_API_KEY in .env; an OpenAI key cannot authenticate to Groq.",
        403: "Check model and project permissions in your Groq account.",
        404: "Check GROQ_MODEL and GROQ_BASE_URL; the requested model or endpoint was not found.",
        429: "Groq's request or token quota was reached. Free-tier limits still apply. "
        "Wait for the limit to reset, then resume this task; there is no demo fallback.",
    }.get(status, "Provider unavailable after bounded recovery; retry later.")
    if code == "tool_use_failed":
        advice = (
            "The model did not produce a valid native tool call after bounded retries. "
            "Run python -m scripts.diagnose_groq for a redacted provider diagnostic."
        )
    elif status == 400:
        advice += " Run python -m scripts.diagnose_groq for a redacted provider diagnostic."
    delay = retry_after_seconds(response.headers.get("retry-after"))
    wait = f" Provider retry delay: at least {math.ceil(delay)} seconds." if delay is not None else ""
    detail = f" [{code}]" if code else ""
    return PlannerError(f"Groq HTTP {status}{detail}. {advice}{wait}")


def tool_failure_code(response):
    """Read only allowlisted error codes; never return failed generations or raw error text."""
    try:
        code = response.json().get("error", {}).get("code")
        return (
            code
            if code
            in {
                "tool_use_failed",
                "model_not_found",
                "model_decommissioned",
                "invalid_api_key",
                "rate_limit_exceeded",
            }
            else None
        )
    except (ValueError, TypeError, AttributeError):
        return None


def tool_repair_instruction(response):
    """Explain known schema failures without replaying untrusted provider messages."""
    generic = (
        "Return exactly ONE native function call using a listed tool and its JSON argument schema. "
        "Do not write a plain-text plan or invent tool names."
    )
    try:
        message = response.json().get("error", {}).get("message", "")
        if (
            isinstance(message, str)
            and "set_plan" in message
            and ("maxItems" in message or "/steps" in message)
        ):
            bounds = TOOLS["set_plan"][0].model_json_schema()["properties"]["steps"]
            return (
                f"The previous set_plan arguments failed validation. The CURRENT schema requires "
                f"steps to be an array containing {bounds['minItems']} to {bounds['maxItems']} strings. "
                "Combine related actions if necessary and resend set_plan using this schema. " + generic
            )
    except (ValueError, TypeError, AttributeError, KeyError):
        pass
    return "The previous output was rejected as an invalid tool call. " + generic


def parse_tool_call(data: dict) -> tuple[dict, dict, dict]:
    """Reject partial, parallel, missing or malformed calls before any side effect."""
    try:
        choices = data["choices"]
        if len(choices) != 1 or choices[0]["finish_reason"] != "tool_calls":
            raise ValueError("Incomplete tool turn")
        message = choices[0]["message"]
        calls = message["tool_calls"]
        if message.get("role") != "assistant" or len(calls) != 1:
            raise ValueError("Expected one assistant function call")
        call = calls[0]
        function = call["function"]
        if call.get("type") != "function" or not isinstance(call["id"], str) or not call["id"]:
            raise ValueError("Invalid call identifier")
        if not isinstance(function["name"], str):
            raise ValueError("Invalid function name")
        args = json.loads(function["arguments"])
        if not isinstance(args, dict):
            raise ValueError("Arguments must be a JSON object")
        # Keep only protocol fields. Never persist a provider's private reasoning field.
        safe_call = {
            "id": call["id"],
            "type": "function",
            "function": {"name": function["name"], "arguments": function["arguments"]},
        }
        safe_message = {"role": "assistant", "content": None, "tool_calls": [safe_call]}
        return safe_message, safe_call, args
    except (KeyError, ValueError, TypeError, IndexError, AttributeError) as exc:
        raise PlannerError("Groq must return one complete function call; no action executed.") from exc


def build_request(task, settings):
    history = task["memory"].setdefault("llm_history", [{"role": "user", "content": task["goal"]}])
    tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": model.model_json_schema(),
            },
        }
        for name, (model, description) in TOOLS.items()
    ]
    instructions = SYSTEM + (
        f"\nApproval required above {settings.approval_threshold_minor} INR minor units. "
        "Return exactly one function call per turn. Do not emit parallel tool calls. "
        "Create the plan by CALLING set_plan, not by writing a plan as plain text."
    )
    body = {
        "model": settings.groq_model,
        "messages": [{"role": "system", "content": instructions}, *history],
        "tools": tools,
        "tool_choice": "required",
        "parallel_tool_calls": False,
        "stream": False,
        "temperature": 0.2,
        "max_completion_tokens": 2048,
    }
    if settings.groq_model.startswith("openai/gpt-oss-"):
        body["reasoning_effort"] = "low"
    return body


def accept_response(task, data):
    message, call, args = parse_tool_call(data)
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        raise PlannerError("Groq returned malformed usage metadata; no action executed.")
    counters = {
        target: usage.get(source, 0)
        for source, target in (
            ("prompt_tokens", "input_tokens"),
            ("completion_tokens", "output_tokens"),
            ("total_tokens", "total_tokens"),
        )
    }
    if any(type(value) is not int or value < 0 for value in counters.values()):
        raise PlannerError("Groq returned invalid token counts; no action executed.")
    memory = task["memory"]
    memory["llm_history"].append(message)
    memory["llm_pending_call"] = call["id"]
    memory.setdefault("llm_usage", []).append(counters)
    return Action(call["function"]["name"], args)


def retry_delay(response, attempt, settings):
    if response.status_code != 429 and response.status_code < 500:
        return None
    seconds = retry_after_seconds(response.headers.get("retry-after"))
    seconds = max(seconds or 0, settings.retry_delay * (2**attempt))
    return seconds if seconds <= 60 and attempt + 1 < settings.max_tool_attempts else None


def reset_seconds(value):
    """Groq reset headers are durations such as 7.66s or 1m2s, not timestamps."""
    if not isinstance(value, str) or not value or len(value) > 80:
        return None
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)", value)
    if not parts or "".join(number + unit for number, unit in parts) != value:
        return None
    if len({unit for _, unit in parts}) != len(parts):
        return None
    scale = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400}
    seconds = sum(float(number) * scale[unit] for number, unit in parts)
    return seconds if math.isfinite(seconds) else None


def quota_wait_seconds(response, next_tokens):
    """Use documented remaining/reset headers; missing headers retain reactive retries."""
    delays = [retry_after_seconds(response.headers.get("retry-after")) or 0]
    for resource, required in (("tokens", next_tokens), ("requests", 1)):
        try:
            remaining = int(response.headers[f"x-ratelimit-remaining-{resource}"])
        except (KeyError, ValueError):
            continue
        reset = reset_seconds(response.headers.get(f"x-ratelimit-reset-{resource}"))
        if remaining < required and reset is not None:
            delays.append(reset)
    return max(delays)


class GroqPlanner:
    def __init__(self, settings, transport=None, sleep=asyncio.sleep, clock=time.monotonic, on_wait=None):
        self.settings, self.transport, self.sleep = settings, transport, sleep
        self.clock, self.on_wait = clock, on_wait
        # Shared by tasks in this local worker; not persisted across server restarts.
        self.not_before = 0.0
        self.next_tokens = 2048 + 256

    def remember_quota(self, response):
        delay = quota_wait_seconds(response, self.next_tokens)
        if delay:
            self.not_before = max(self.not_before, self.clock() + delay)

    async def wait_for_quota(self, task):
        delay = max(0.0, self.not_before - self.clock())
        if delay > 60:
            raise PlannerError(
                f"Groq quota cooldown: at least {math.ceil(delay)} seconds remain. "
                "Automatic waits are limited to 60 seconds; resume this task after the quota resets."
            )
        if delay:
            if self.on_wait:
                self.on_wait(task, {"reason": "provider_quota", "seconds": math.ceil(delay)})
            await self.sleep(delay)
            self.not_before = 0.0

    async def choose(self, task, settings):
        body = build_request(task, settings)
        for attempt in range(settings.max_tool_attempts):
            try:
                await self.wait_for_quota(task)
                async with httpx.AsyncClient(timeout=45, transport=self.transport) as client:
                    response = await client.post(
                        settings.groq_base_url + "/chat/completions",
                        json=body,
                        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                    )
                self.remember_quota(response)
                # Bound automatic waits; never retry earlier than the provider's stated delay.
                delay = retry_delay(response, attempt, settings)
                if delay is not None:
                    self.not_before = max(self.not_before, self.clock() + delay)
                    continue
                if response.status_code >= 400:
                    if (
                        response.status_code == 400
                        and tool_failure_code(response) == "tool_use_failed"
                        and attempt + 1 < settings.max_tool_attempts
                    ):
                        # The provider did not return an executable call, so no tool has run.
                        # Ask the model to repair its call; never execute failed_generation text.
                        body["messages"] = [
                            *body["messages"],
                            {
                                "role": "user",
                                "content": tool_repair_instruction(response),
                            },
                        ]
                        continue
                    raise groq_http_error(response)
                action = accept_response(task, response.json())
                # Reserve the output budget and room for the next observation as well as input.
                # This is a forecast; actual account limits remain authoritative.
                usage = task["memory"]["llm_usage"][-1]
                self.next_tokens = usage["input_tokens"] + body["max_completion_tokens"] + 256
                self.remember_quota(response)
                return action
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt + 1 == settings.max_tool_attempts:
                    raise PlannerError(
                        "Groq unreachable after bounded retries; check your connection."
                    ) from exc
                await self.sleep(settings.retry_delay * (2**attempt))
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise PlannerError("Malformed Groq response; no action executed.") from exc
        raise PlannerError("Groq retry budget exhausted; no action executed.")

    def observe(self, task, result):
        memory = task["memory"]
        call_id = memory.pop("llm_pending_call", None)
        if call_id:
            memory["llm_history"].append(
                {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result)}
            )
