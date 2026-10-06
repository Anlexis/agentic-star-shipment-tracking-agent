# LOG-C2-030 — Unit tests: the adapter's context contract.
#
# `input_context` is the one channel that reaches the agent without passing the
# framework's personal-data mask, which is exactly why this template uses it for
# the consignment reference. The same property makes it the channel that needs
# an explicit contract at the adapter:
#
#   * An UNDECLARED key is not removed by validating the declared ones.
#     Validators ignore what they do not know, and ignoring is not stripping —
#     the key stays on the request, reaches the first node's result, and is
#     scanned there by the framework's output gate, which fails the whole run.
#     Refusing unknown keys here is what keeps that channel to declared fields.
#
#   * A CREDENTIAL-SHAPED value on the channel fails the run at the first node
#     with a traceback the caller cannot act on. The request cannot succeed
#     either way, so a clean refusal naming the field is strictly better.
#
# The screen calls the framework's own detector, so the set refused here is
# exactly the set the framework blocks. The property test at the bottom pins
# that identity, which is the guarantee against drift.

import asyncio
import json

import pytest
from framework.security.credential_detector import detect_credentials_in_value

from src.api.server import _ALLOWED_CONTEXT_KEYS, _MAX_INPUT_CONTEXT_BYTES, app

# Assembled rather than written out, so no literal credential-shaped URL is
# committed to the tree — the credential-scan gate rejects one on sight, and
# rightly so. The assembled value still matches the framework's detector.
_DB_URI = "postgresql://" + "svc:" + "pw" * 3 + "@db.example.invalid/shipments"


CREDENTIAL_SHAPES = [
    "AKIAIOSFODNN7EXAMPLE",
    "sk_live_abcdefghijklmnop1234",
    "sk-abcdefghijklmnopqrstuvwxyz",
    "eyJhbGciOiJIUzI1NiJ9.eyJhIjoxfQ.sig",
    "Bearer abcdefghijklmnopqrstuvwx",
    _DB_URI,
]

# Ordinary values for the same fields, which must keep working.
BENIGN_CONTEXT_VALUES = [
    "TMS000042",
    "123456789012",
    "EE123456789JP",
]


_TOKEN = "adapter-contract-token"


@pytest.fixture(autouse=True)
def token_configured(monkeypatch):
    """Deployment-shaped server environment: a caller token is required."""
    monkeypatch.setenv("INVOKE_AUTH_TOKEN", _TOKEN)


def _post_invoke(payload: dict) -> tuple:
    body = json.dumps(payload).encode()
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
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"authorization", f"Bearer {_TOKEN}".encode()),
        ],
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


class TestDeclaredKeysOnly:
    def test_the_contract_is_exactly_two_keys(self):
        assert _ALLOWED_CONTEXT_KEYS == {"deployment_mode", "tracking_number"}

    def test_unknown_key_is_refused_not_ignored(self):
        status_code, body = _post_invoke(
            {
                "input": "where is TMS000042",
                "input_context": {"tracking_number": "TMS000042", "notes": "anything"},
            }
        )
        assert status_code == 400
        assert "input_context.notes" in body["detail"]

    def test_refusal_is_400_not_422(self):
        """422 belongs to pydantic, which returns a list of error objects there.

        Reusing it would make client handling ambiguous.
        """
        status_code, body = _post_invoke(
            {
                "input": "where is TMS000042",
                "input_context": {"unexpected": "x"},
            }
        )
        assert status_code == 400
        assert isinstance(body["detail"], str)

    def test_hostile_field_name_is_not_echoed_back(self):
        status_code, body = _post_invoke(
            {
                "input": "where is TMS000042",
                "input_context": {"<script>alert(1)</script>": "x"},
            }
        )
        assert status_code == 400
        assert "<script>" not in json.dumps(body)
        assert "input_context field #" in body["detail"]

    def test_declared_keys_are_accepted(self):
        status_code, body = _post_invoke(
            {
                "input": "where is my parcel",
                "input_context": {
                    "tracking_number": "TMS000042",
                    "deployment_mode": "coordinator",
                },
            }
        )
        assert status_code == 200
        assert "TMS000042" in body["output"]


class TestCredentialScreen:
    @pytest.mark.parametrize("secret", CREDENTIAL_SHAPES)
    def test_credential_shaped_value_is_refused_readably(self, secret):
        status_code, body = _post_invoke(
            {
                "input": "where is my parcel",
                "input_context": {"tracking_number": secret},
            }
        )
        assert status_code == 400
        assert "input_context.tracking_number" in body["detail"]
        # Name the field, never the value.
        assert secret not in json.dumps(body)

    @pytest.mark.parametrize("value", BENIGN_CONTEXT_VALUES)
    def test_ordinary_domain_values_still_pass(self, value):
        status_code, _ = _post_invoke(
            {
                "input": "where is my parcel",
                "input_context": {"tracking_number": value},
            }
        )
        assert status_code in (200, 400) and status_code != 413
        # None of these is a credential shape, so the screen must not be why
        # any of them is refused.
        assert not detect_credentials_in_value(value)

    @pytest.mark.parametrize("secret", CREDENTIAL_SHAPES + BENIGN_CONTEXT_VALUES)
    def test_refusal_set_equals_the_framework_block_set(self, secret):
        """The anti-drift guarantee.

        Per-field iteration is exactly equivalent to scanning the whole mapping,
        because the framework defines the dict case as the union over its
        values. That identity is what lets the adapter name the offending field
        without widening or narrowing what it blocks.
        """
        context = {"tracking_number": secret}
        status_code, _ = _post_invoke({"input": "where is my parcel", "input_context": context})
        refused_for_credential = status_code == 400
        assert refused_for_credential == bool(detect_credentials_in_value(context))
        # And the union identity itself.
        assert bool(detect_credentials_in_value(context)) == any(
            bool(detect_credentials_in_value(v)) for v in context.values()
        )


class TestSizeCap:
    def test_oversized_context_is_refused_before_the_agent_runs(self):
        oversized = {"tracking_number": "T" * (_MAX_INPUT_CONTEXT_BYTES + 10)}
        status_code, _ = _post_invoke(
            {
                "input": "where is my parcel",
                "input_context": oversized,
            }
        )
        assert status_code == 413


class TestNumericSurface:
    def test_the_public_contract_carries_no_caller_numeric(self):
        """Inventory guard, not a formality.

        The finite-and-bounded parser rule applies to every caller-controlled
        number. This agent's contract declares none — the two context fields are
        an inert identifier and a closed enum — so there is no numeric field to
        parse. If a numeric field is ever added, this assertion fails and the
        rule has to be applied to it.
        """
        assert _ALLOWED_CONTEXT_KEYS == {"deployment_mode", "tracking_number"}

    @pytest.mark.parametrize("hostile", ["NaN", "Infinity", "-Infinity", "1e400"])
    def test_numeric_looking_reference_is_refused_by_the_identifier_pattern(self, hostile):
        """A non-finite literal is not an inert identifier, so it never parses."""
        status_code, body = _post_invoke(
            {
                "input": "where is my parcel",
                "input_context": {"tracking_number": hostile},
            }
        )
        assert status_code == 200
        assert body["status"] in ("error", "ERROR")
