"""Send one synthetic request and print redacted diagnostics. Never prints credentials."""

import argparse
import json
import re
from urllib.parse import urlsplit

import httpx

from worker.config import Settings
from worker.groq_planner import build_request
from worker.planner import TOOLS


def redacted_error(response, secrets):
    try:
        error = response.json().get("error", {})
        if not isinstance(error, dict):
            error = {}
    except (ValueError, AttributeError):
        error = {}
    safe = {}
    for field in ("code", "type", "param", "message"):
        value = str(error.get(field) or "")
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?:gsk_|sk-)[A-Za-z0-9_-]+", "[REDACTED]", value)
        safe[field] = value[:700]
    return {"status": response.status_code, "error": safe}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        config = Settings.from_env()
        if config.mode != "groq":
            parser.exit(1, "Set WORKER_MODE=groq before running this diagnostic.\n")
        url = urlsplit(config.groq_base_url)
        if (
            url.scheme != "https"
            or url.hostname != "api.groq.com"
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            parser.exit(1, "This diagnostic only sends credentials to https://api.groq.com.\n")
        body = build_request(
            {"goal": "Record the latest invoice from Acme Supplies and verify it.", "memory": {}}, config
        )
        response = httpx.post(
            config.groq_base_url + "/chat/completions",
            json=body,
            timeout=45,
            headers={"Authorization": f"Bearer {config.groq_api_key}"},
        )
        if response.status_code >= 400:
            report = redacted_error(
                response, [config.groq_api_key, config.api_key, config.worker_token, config.reviewer_token]
            )
        else:
            choice = response.json().get("choices", [{}])[0]
            calls = choice.get("message", {}).get("tool_calls", [])
            report = {
                "status": response.status_code,
                "finish_reason": choice.get("finish_reason"),
                "tool_names": [
                    call.get("function", {}).get("name")
                    if call.get("function", {}).get("name") in TOOLS
                    else "unknown"
                    for call in calls
                ],
            }
        print(json.dumps(report, indent=2))
    except httpx.HTTPError as exc:
        parser.exit(1, f"Diagnostic connection failed: {type(exc).__name__}.\n")
    except (ValueError, KeyError, IndexError, AttributeError):
        parser.exit(1, "Configuration or provider response could not be parsed. No credentials printed.\n")


if __name__ == "__main__":
    main()
