from __future__ import annotations

import pytest
from voizy_agent.http_tool import TRUNCATED, HttpToolExecutor
from voizy_core.domain.agent_config import HttpTool
from voizy_core.security.ssrf import STRICT, SsrfPolicy

pytestmark = pytest.mark.asyncio
DEV = SsrfPolicy(allow_loopback=True)


def tool(port: int, path: str, **over: object) -> HttpTool:
    fields: dict[str, object] = {
        "name": "t",
        "description": "d",
        "url": f"http://127.0.0.1:{port}{path}",
        "method": "GET",
        **over,
    }
    return HttpTool.model_validate(fields)


async def test_get_sends_args_as_query_and_returns_body(clinic_port: int) -> None:
    r = await HttpToolExecutor(DEV).execute(
        tool(clinic_port, "/availability"), {"date": "2026-11-10"}
    )
    assert r.ok and r.status == 200 and '"open":true' in r.text.replace(" ", "")


async def test_post_sends_json_and_4xx_is_a_clean_failure(clinic_port: int) -> None:
    t = tool(clinic_port, "/appointments", method="POST")
    body = {"name": "Sam", "phone": "5559990000", "date": "2026-11-11", "time": "09:00"}
    ex = HttpToolExecutor(DEV)
    first = await ex.execute(t, body)
    assert first.ok and "BS-" in first.text
    second = await ex.execute(t, body)
    assert not second.ok and second.status == 409 and "already booked" in second.text


async def test_large_responses_are_truncated_to_the_tools_limit(clinic_port: int) -> None:
    r = await HttpToolExecutor(DEV).execute(tool(clinic_port, "/big", max_result_chars=300), {})
    assert r.ok and len(r.text) <= 300 and r.text.endswith(TRUNCATED)


async def test_response_bytes_are_capped_before_decoding(clinic_port: int) -> None:
    ex = HttpToolExecutor(DEV, max_response_bytes=1000)
    r = await ex.execute(tool(clinic_port, "/big", max_result_chars=20000), {})
    assert r.ok and len(r.text) <= 1000


async def test_timeout_is_enforced_and_reported_generically(clinic_port: int) -> None:
    r = await HttpToolExecutor(DEV).execute(tool(clinic_port, "/slow", timeout_s=0.3), {"ms": 3000})
    assert not r.ok and r.text == "the request timed out" and r.duration_s < 2


async def test_redirects_are_never_followed(clinic_port: int) -> None:
    r = await HttpToolExecutor(DEV).execute(tool(clinic_port, "/redirect"), {})
    assert not r.ok and r.status == 302 and "not followed" in r.text
    assert "169.254" not in r.text


async def test_strict_policy_blocks_loopback_and_hides_the_address(clinic_port: int) -> None:
    r = await HttpToolExecutor(STRICT).execute(tool(clinic_port, "/availability"), {"date": "x"})
    assert not r.ok and r.text == "that address is not allowed"
    assert "127.0.0.1" not in r.text and str(clinic_port) not in r.text


async def test_connection_is_pinned_to_the_validated_ip(clinic_port: int) -> None:
    """clinic.test only exists in our fake resolver; success proves the pinned IP was used."""
    calls: list[str] = []

    def resolver(host: str, port: int) -> list[str]:
        calls.append(host)
        return ["127.0.0.1"]

    ex = HttpToolExecutor(DEV, resolver=resolver)
    t = tool(clinic_port, "/availability")
    t = t.model_copy(update={"url": f"http://localhost:{clinic_port}/availability"})
    r = await ex.execute(t, {"date": "2026-11-10"})
    assert r.ok and calls == ["localhost"]  # resolved exactly once, by us


async def test_non_scalar_get_arguments_rejected(clinic_port: int) -> None:
    r = await HttpToolExecutor(DEV).execute(
        tool(clinic_port, "/availability"), {"date": {"$ne": 1}}
    )
    assert not r.ok and "simple values" in r.text


async def test_connection_failure_does_not_leak_details() -> None:
    r = await HttpToolExecutor(DEV).execute(tool(1, "/nothing"), {})  # nothing listens on port 1
    assert not r.ok and r.text == "could not connect"
    assert "127.0.0.1" not in r.text and "Errno" not in r.text
