# LOG-C2-030 — Boundary: output containment.
#
# The property under test: when the output gate refuses, NOTHING it refused
# reaches the caller — not in the narrative, and not in a sibling field.
#
# Two independent layers implement that, and each is tested on its own so
# neither can conceal a regression in the other:
#
#   layer 1  ResponseValidateNode clears every output-bearing field in state
#            and sets a TRUTHY withheld notice (a falsy one re-activates the
#            framework's `formatted_output or result` fallback).
#   layer 2  RealtimeShipmentTrackingAgent.get_output releases the domain
#            payload only on the success path.
#
# The full-invoke test at the bottom is the one that fails if BOTH layers are
# reverted; the two layer-specific tests are what make each layer individually
# falsifiable. See docs/02_design.md, "Output containment".

import asyncio
import json

import pytest
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from framework.security.credential_detector import detect_credentials

import src.nodes.tracking_api_call_node as tracking_api_call_node
from src.graph.graph import _DOMAIN_OUTPUT_FIELDS, RealtimeShipmentTrackingAgent
from src.nodes.response_validate_node import (
    OUTPUT_BEARING_FIELDS,
    WITHHELD_NOTICE,
    ResponseValidateNode,
    _scan_value,
)

# A credential shape the FRAMEWORK does not match but this template does, so the
# value survives every upstream framework gate and is refused for the first time
# at this template's own output gate. That is what makes the leak reachable, and
# what makes this test about the template rather than about the framework.
_TEMPLATE_ONLY_SECRET = "api_key=xyz123"

# Assembled rather than written out, so no literal credential-shaped URL is
# committed to the tree — the credential-scan gate rejects one on sight, and
# rightly so. The assembled value still matches the framework's detector.
_DB_URI = "postgresql://" + "svc:" + "pw" * 3 + "@db.example.invalid/shipments"


# A credential shape the framework DOES match, used to prove the template's
# block set is not narrower than the framework's.
_FRAMEWORK_SECRETS = [
    "AKIAIOSFODNN7EXAMPLE",
    "sk_live_abcdefghijklmnop1234",
    _DB_URI,
    "sk-abcdefghijklmnopqrstuvwxyz",
    "eyJhbGciOiJIUzI1NiJ9.eyJhIjoxfQ.sig",
    "Bearer abcdefghijklmnopqrstuvwx",
]


def _released_state() -> dict:
    """State as the pipeline actually builds it just before the gate runs."""
    return {
        "raw_query": "where is TMS000042",
        "nl_response": "Tracking number TMS000042: status is pending pickup.",
        "deployment_mode": "coordinator",
        "unified_status": "pending",
        "eta": "2026-06-09",
        "exception_flags": ["delay"],
        "data_timestamp": "2026-06-08 06:30",
        "live_data_response": {"_carrier": "tms", "_available": True},
    }


class TestDetectorParity:
    """The template's block set must never be narrower than the framework's.

    A value the framework catches and the template misses makes the framework
    raise INSIDE post-processing, and the wrapper then discards the gate's
    clearing along with the rest of its delta — so a detector gap is a
    containment bypass, not merely a missed warning.
    """

    @pytest.mark.parametrize("secret", _FRAMEWORK_SECRETS)
    def test_template_catches_everything_the_framework_catches(self, secret):
        assert detect_credentials(secret), "probe is not a framework credential shape"
        assert _scan_value(secret) is True

    def test_template_also_catches_its_own_domain_shapes(self):
        assert not detect_credentials(_TEMPLATE_ONLY_SECRET)
        assert _scan_value(_TEMPLATE_ONLY_SECRET) is True

    def test_scan_walks_nested_structures(self):
        nested = {"outer": {"inner": ["harmless", "AKIAIOSFODNN7EXAMPLE"]}}
        assert _scan_value(nested) is True
        # Control: the same shape without a credential must be clean, so a
        # blind scanner cannot pass this pair.
        assert _scan_value({"outer": {"inner": ["harmless", "also fine"]}}) is False

    def test_ordinary_shipment_text_is_not_flagged(self):
        for benign in _released_state().values():
            assert _scan_value(benign) is False


class TestLayerOneGateClearing:
    """ResponseValidateNode clears state. Falsifiable by reverting the node alone."""

    def test_violation_clears_every_output_bearing_field(self):
        state = _released_state()
        state["eta"] = f"2026-06-09 {_TEMPLATE_ONLY_SECRET}"

        result = ResponseValidateNode().execute(state)

        assert result["status"] == AgentStatus.ERROR
        assert result["error"] == "secret_in_output"
        for field in OUTPUT_BEARING_FIELDS:
            value = result[field]
            assert not _scan_value(value), f"{field} still carries the refused value"
        # Truthy notice: a falsy one re-activates the framework's fallback.
        assert result["formatted_output"] == WITHHELD_NOTICE
        assert bool(result["formatted_output"]) is True

    def test_violation_message_names_the_field_never_the_value(self):
        state = _released_state()
        state["eta"] = f"2026-06-09 {_TEMPLATE_ONLY_SECRET}"

        result = ResponseValidateNode().execute(state)

        rendered = json.dumps(result, default=str)
        assert "xyz123" not in rendered
        assert "/" not in result["error"]
        assert "Traceback" not in rendered

    def test_gate_scans_beyond_the_narrative(self):
        """The narrative is clean; the violation is in a sibling field only.

        This is the exact shape the pre-fix gate missed: it scanned
        nl_response and nothing else.
        """
        state = _released_state()
        state["eta"] = f"2026-06-09 {_TEMPLATE_ONLY_SECRET}"
        assert not _scan_value(state["nl_response"])

        assert ResponseValidateNode().execute(state)["status"] == AgentStatus.ERROR

    def test_clean_path_control_still_releases_a_real_answer(self):
        result = ResponseValidateNode().execute(_released_state())
        assert result["status"] == AgentStatus.SUCCESS
        assert "TMS000042" in result["nl_response"]
        assert result["nl_response"] != WITHHELD_NOTICE


class TestLayerTwoEnvelopeWithholding:
    """get_output withholds on non-success. Falsifiable by reverting the graph alone."""

    def test_error_envelope_withholds_the_domain_payload(self):
        agent = RealtimeShipmentTrackingAgent()
        # State as it would look if layer 1 had NOT cleared: the domain payload
        # is still populated and the status is an error.
        state = _released_state()
        state["status"] = AgentStatus.ERROR
        state["formatted_output"] = WITHHELD_NOTICE

        envelope = agent.get_output(state)

        assert envelope["output"] == WITHHELD_NOTICE
        for field in _DOMAIN_OUTPUT_FIELDS:
            assert not envelope[field], f"{field} released on an error envelope"

    def test_error_envelope_never_re_derives_the_narrative(self):
        """On a refusal nl_response is the answer the gate declined to release."""
        agent = RealtimeShipmentTrackingAgent()
        state = _released_state()
        state["status"] = AgentStatus.ERROR
        state["nl_response"] = "the un-gated answer"
        state.pop("formatted_output", None)

        envelope = agent.get_output(state)

        assert envelope["output"] is None

    def test_error_code_is_inert_or_replaced(self):
        agent = RealtimeShipmentTrackingAgent()
        state = _released_state()
        state["status"] = AgentStatus.ERROR
        state["error"] = 'Traceback: File "/srv/app/src/nodes/x.py", line 3'

        assert agent.get_output(state)["error"] == "internal_error"

    def test_success_envelope_releases_the_domain_payload(self):
        agent = RealtimeShipmentTrackingAgent()
        state = _released_state()
        state["status"] = AgentStatus.SUCCESS

        envelope = agent.get_output(state)

        assert envelope["eta"] == "2026-06-09"
        assert envelope["unified_status"] == "pending"


class TestFieldInventoriesStayAligned:
    """A newly surfaced field must not be able to skip the gate."""

    def test_every_released_domain_field_is_cleared_by_the_gate(self):
        assert set(_DOMAIN_OUTPUT_FIELDS) <= set(OUTPUT_BEARING_FIELDS)


_TOKEN = "containment-e2e-token"


@pytest.fixture(autouse=True)
def token_configured(monkeypatch):
    """Deployment-shaped server environment: a caller token is required.

    With no token configured the adapter leaves every caller ANONYMOUS and the
    nodes' trust floor denies the request, so an E2E asserting real output would
    pass for the wrong reason — or fail for one.
    """
    monkeypatch.setenv("INVOKE_AUTH_TOKEN", _TOKEN)


def _post_invoke(payload: dict, token: str | None = _TOKEN) -> tuple:
    """POST /invoke through the real ASGI app; returns (status_code, body).

    Driven through the ASGI interface directly rather than a test client, so
    this boundary test carries no extra dependency and cannot silently skip.
    """
    from src.api.server import app

    body = json.dumps(payload).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/invoke",
        "raw_path": b"/invoke",
        "root_path": "",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }
    messages: list = []
    sent = {"body": b""}

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body":
            sent["body"] += message.get("body", b"")

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    return start["status"], json.loads(sent["body"].decode() or "{}")


class TestFullInvokeContainment:
    """End to end through /invoke. Fails when the shipped pre-fix code is restored."""

    @pytest.fixture
    def leaking_transport(self, monkeypatch):
        """Fault injected on the DATA path, never on the gate.

        The transport returns a credential-shaped estimated-delivery value —
        the realistic way a secret enters this pipeline. Patching the gate
        instead would only test the patch.
        """
        poisoned = json.loads(json.dumps(tracking_api_call_node._STUB_RESPONSES))
        poisoned["tms"]["TMS000042"]["promised_eta"] = f"2026-06-09 {_TEMPLATE_ONLY_SECRET}"
        monkeypatch.setattr(tracking_api_call_node, "_STUB_RESPONSES", poisoned)

    def test_refused_value_never_reaches_the_caller(self, leaking_transport):
        status_code, body = _post_invoke({"input": "where is TMS000042"})

        assert status_code == 200
        assert body["status"] in (AgentStatus.ERROR, AgentStatus.ERROR.value)

        rendered = json.dumps(body, default=str)
        assert "xyz123" not in rendered, "the refused credential reached the caller"
        assert "api_key" not in rendered
        assert "Traceback" not in rendered
        assert "/src/nodes/" not in rendered
        # And the domain payload is withheld, not merely the narrative.
        assert not body["eta"]
        assert not body["unified_status"]
        assert not body["data_timestamp"]

    def test_block_happened_at_the_gate_not_upstream(self, leaking_transport):
        """Proves the pipeline ran and the OUTPUT gate refused it."""
        _, body = _post_invoke({"input": "where is TMS000042"})
        assert "PostProcessNode" in body["node_history"]

    def test_clean_path_still_answers(self):
        """A refuse-everything gate must not be able to pass this suite."""
        status_code, body = _post_invoke({"input": "where is TMS000042"})

        assert status_code == 200
        assert body["status"] in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value)
        assert "TMS000042" in body["output"]
        assert body["unified_status"] == "pending"


class TestTrustBoundary:
    def test_anonymous_caller_is_denied_without_a_token(self):
        status_code, _ = _post_invoke({"input": "where is TMS000042"}, token=None)
        assert status_code == 401

    def test_bearer_token_promotes_the_caller(self):
        status_code, body = _post_invoke({"input": "where is TMS000042"}, token=_TOKEN)
        assert status_code == 200
        assert body["status"] in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value)

    def test_wrong_token_is_refused_without_saying_why(self):
        status_code, body = _post_invoke({"input": "where is TMS000042"}, token="wrong-token")
        assert status_code == 401
        assert "wrong-token" not in json.dumps(body)

    def test_direct_anonymous_invoke_is_denied(self):
        agent = RealtimeShipmentTrackingAgent()
        agent.compile()
        ctx = InvocationContext(caller_trust_level=TrustLevel.ANONYMOUS)
        out = agent.invoke("where is TMS000042", ctx=ctx)
        assert out["status"] == AgentStatus.ERROR.value
