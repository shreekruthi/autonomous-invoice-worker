"""Quota behavior with synthetic HTTP responses and a clock that never really sleeps."""

import httpx
import pytest

from tests.test_completion import inline
from tests.test_groq import result, settings_for
from worker.groq_planner import GroqPlanner, quota_wait_seconds, reset_seconds
from worker.planner import PlannerError


@pytest.mark.parametrize(
    "value,expected",
    [
        ("7.66s", 7.66),
        ("1m2.5s", 62.5),
        ("250ms", 0.25),
        ("1d2h3m4s", 93784),
        ("0s", 0),
        (None, None),
        ("", None),
        ("-1s", None),
        ("NaNs", None),
        ("1s1s", None),
        ("arbitrary provider text", None),
    ],
)
def test_provider_reset_duration_validation(value, expected):
    assert reset_seconds(value) == expected


def test_quota_headers_require_both_remaining_and_a_valid_reset():
    assert quota_wait_seconds(httpx.Response(200), 3000) == 0
    assert (
        quota_wait_seconds(
            httpx.Response(
                200,
                headers={"x-ratelimit-remaining-tokens": "bad", "x-ratelimit-reset-tokens": "10s"},
            ),
            3000,
        )
        == 0
    )
    assert (
        quota_wait_seconds(
            httpx.Response(
                200,
                headers={"x-ratelimit-remaining-tokens": "4000", "x-ratelimit-reset-tokens": "10s"},
            ),
            3000,
        )
        == 0
    )


class Clock:
    def __init__(self):
        self.current = 100.0
        self.delays = []

    def __call__(self):
        return self.current

    async def sleep(self, delay):
        assert 0 < delay <= 60
        self.delays.append(delay)
        self.current += delay


def task():
    return {"id": "synthetic", "goal": "Record the latest Acme Supplies invoice.", "memory": {}}


def test_success_headers_pace_the_next_task_before_another_http_request(tmp_path):
    clock, requests, waits = Clock(), [], []

    def handler(request):
        requests.append(clock())
        headers = (
            {"x-ratelimit-remaining-tokens": "1200", "x-ratelimit-reset-tokens": "12s"}
            if len(requests) == 1
            else {}
        )
        return httpx.Response(200, json=result(), headers=headers)

    config = settings_for(tmp_path)
    planner = GroqPlanner(
        config,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock,
        on_wait=lambda current, info: waits.append(info),
    )
    assert inline(planner.choose(task(), config)).name == "discover_vendors"
    # A different task shares the same model quota in this worker.
    assert inline(planner.choose(task(), config)).name == "discover_vendors"
    assert requests == [100, 112] and clock.delays == [12]
    assert waits == [{"reason": "provider_quota", "seconds": 12}]


def test_retry_uses_longest_provider_cooldown_before_sending_again(tmp_path):
    clock, requests = Clock(), []

    def handler(request):
        requests.append(clock())
        if len(requests) == 1:
            return httpx.Response(
                429,
                headers={
                    "retry-after": "7",
                    "x-ratelimit-remaining-tokens": "0",
                    "x-ratelimit-reset-tokens": "10s",
                },
            )
        return httpx.Response(200, json=result())

    config = settings_for(tmp_path)
    planner = GroqPlanner(config, transport=httpx.MockTransport(handler), sleep=clock.sleep, clock=clock)
    assert inline(planner.choose(task(), config)).name == "discover_vendors"
    assert requests == [100, 110] and clock.delays == [10]


def test_long_daily_quota_stops_without_sleeping_or_another_request(tmp_path):
    clock, requests = Clock(), []

    def handler(request):
        requests.append(clock())
        return httpx.Response(
            200,
            json=result(),
            headers={"x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-requests": "1d"},
        )

    config = settings_for(tmp_path)
    planner = GroqPlanner(config, transport=httpx.MockTransport(handler), sleep=clock.sleep, clock=clock)
    inline(planner.choose(task(), config))
    with pytest.raises(PlannerError, match="86400 seconds"):
        inline(planner.choose(task(), config))
    assert requests == [100] and clock.delays == []


def test_expired_cooldown_does_not_delay_resume(tmp_path):
    clock = Clock()
    config = settings_for(tmp_path)
    planner = GroqPlanner(
        config,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=result())),
        sleep=clock.sleep,
        clock=clock,
    )
    planner.not_before = clock() - 1
    inline(planner.choose(task(), config))
    assert clock.delays == []
