"""AgentCore Platform v1.0

Step 6 — ResponseValidate node. The output gate.

Responsibilities:
  - Scope-out detection: if the original query is a policy / claims question
        (not a tracking lookup) → set scope_out=True and route out to the
        logistics policy assistant. This node never interprets carrier policies.
  - PII redaction: when deployment_mode == "customer_facing", redact consignee
        details, internal shipment IDs, and internal route info before output.
  - Output validation: refuse (→ ERROR) if the response is empty, or if ANY
        output-bearing field carries a credential-shaped value.

Containment contract
--------------------
A refusal must withhold the whole answer, not just the field the violation was
noticed in. ``AgentBaseGraph.get_output`` reads several state fields, and a
falsy ``formatted_output`` falls back to ``result`` — so a gate that replaces
only the narrative text still ships the refused value in a sibling field. Two
rules follow, and both are enforced here:

  1. The credential scan covers EVERY output-bearing field, not just the
     narrative. The carrier-supplied ``eta`` is caller-visible output just as
     much as ``nl_response`` is.
  2. On violation the node clears every output-bearing field and sets a TRUTHY
     withheld notice. A blank notice would re-activate the fallback it exists
     to prevent.

The credential scan delegates to the framework's own ``detect_credentials``
and adds domain patterns on top. It is deliberately never narrower than the
framework's set: a value the framework catches and this gate misses would make
the framework raise *inside* post-processing, and the wrapper then discards
this node's clearing along with the rest of its delta.
"""

import re
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from framework.security.credential_detector import detect_credentials
from shared.utils.audit_logger import emit_trace_event

# Policy / claims keywords → out of scope (route to the policy assistant).
_POLICY_KEYWORDS = (
    "damage claim",
    "claim process",
    "claims process",
    "file a claim",
    "compensation",
    "refund policy",
    "return policy",
    "insurance",
    "policy",
    "liability",
    "補償",
    "保険",
    "ポリシー",
    "返品",
)

# Domain credential markers layered ON TOP of the framework's detector.
# These are intentionally broader than the framework's thresholds for shapes
# the framework only matches at a longer minimum length, plus the labelled
# "key: value" form the framework does not model at all. They are additive —
# never a replacement for detect_credentials().
_EXTRA_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9]{8,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*\S+"),
]

# PII / internal-field markers to redact in customer_facing mode.
_PII_PATTERNS = [
    (re.compile(r"(?i)\bconsignee\b[^.\n]*"), "[redacted]"),
    (re.compile(r"(?i)\binternal route\b[^.\n]*"), "[redacted]"),
    (re.compile(r"\bTMS[0-9]{6,12}\b"), "[redacted]"),
    (re.compile(r"(?i)\b\d{3}-\d{4}-\d{4}\b"), "[redacted]"),
]

# Every field this agent can surface to a caller. The scan covers all of them
# and a refusal clears all of them. Keep in sync with the graph's get_output —
# tests/proof_of_boundary/test_output_containment.py pins the two together so a
# newly surfaced field cannot quietly skip the gate.
OUTPUT_BEARING_FIELDS = (
    "nl_response",
    "formatted_output",
    "result",
    "eta",
    "unified_status",
    "exception_flags",
    "data_timestamp",
    "live_data_response",
)

# Truthy on purpose: a falsy notice re-activates get_output's `or result`
# fallback, which is the leak this gate exists to prevent.
WITHHELD_NOTICE = "[refused: response withheld for safety]"


def _is_policy_question(query: str) -> bool:
    q = (query or "").lower()
    return any(k in q for k in _POLICY_KEYWORDS)


def _scan_value(value: Any) -> bool:
    """True when any string leaf of ``value`` looks like a credential.

    Mirrors the framework's own recursion so this gate's block set is a strict
    superset of the framework's — never a narrower approximation that could
    drift away from it.
    """
    if isinstance(value, str):
        if detect_credentials(value):
            return True
        return any(p.search(value) for p in _EXTRA_SECRET_PATTERNS)
    if isinstance(value, dict):
        return any(_scan_value(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_scan_value(v) for v in value)
    return False


def _violating_fields(candidate: dict[str, Any]) -> list[str]:
    """Names of output-bearing fields carrying a credential shape.

    Returns FIELD NAMES ONLY — never the matched value, which would re-leak the
    secret into the error log and trip the framework gate on the way out.
    """
    return [f for f in OUTPUT_BEARING_FIELDS if _scan_value(candidate.get(f))]


def _redact_pii(text: str) -> str:
    for pattern, repl in _PII_PATTERNS:
        text = pattern.sub(repl, text)
    return text


class ResponseValidateNode(FunctionNode):
    """Output gate: scope-out, PII redaction, credential refusal, containment."""

    # Output gate also touches caller-facing content — keep the agent's trust floor.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def _withhold(self, state: dict[str, Any], reason: str, fields: list[str]) -> dict[str, Any]:
        """Refuse and CLEAR every output-bearing field.

        Returning ERROR is not on its own containment: the graph's output
        assembly reads state fields directly, so anything left populated still
        reaches the caller inside the error envelope.
        """
        emit_trace_event(
            "tracking_output_withheld",
            {"reason": reason, "fields": fields},
            state,
        )
        cleared: dict[str, Any] = {
            "status": AgentStatus.ERROR,
            "error": reason,
            "scope_out": False,
            "nl_response": WITHHELD_NOTICE,
            "formatted_output": WITHHELD_NOTICE,
            "result": None,
            "eta": None,
            "unified_status": None,
            "exception_flags": [],
            "data_timestamp": "",
            "live_data_response": {},
            "error_log": [f"ResponseValidateNode: output withheld ({reason})"],
        }
        return cleared

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        raw_query = state.get("raw_query", state.get("user_input", ""))
        nl_response = state.get("nl_response", "")
        deployment_mode = state.get("deployment_mode", "coordinator")

        # Scope-out: policy question → do not answer with carrier data.
        if _is_policy_question(raw_query):
            notice = (
                "This is a policy/claims question, which is out of scope for "
                "tracking. Routing to the logistics policy assistant."
            )
            emit_trace_event("tracking_scope_out", {"reason": "policy_question"}, state)
            return {
                "status": AgentStatus.SUCCESS,
                "scope_out": True,
                "nl_response": notice,
                "formatted_output": notice,
                "eta": None,
                "unified_status": None,
                "exception_flags": [],
                "data_timestamp": "",
                "live_data_response": {},
            }

        # Empty output → refuse.
        if not nl_response or not nl_response.strip():
            return self._withhold(state, "empty_output", [])

        # Credential scan across EVERY output-bearing field. The narrative is
        # only one of them: a carrier-supplied eta is caller-visible too, and
        # scanning the narrative alone is how a refused value ships anyway.
        candidate = dict(state)
        candidate["nl_response"] = nl_response
        violating = _violating_fields(candidate)
        if violating:
            return self._withhold(state, "secret_in_output", violating)

        # PII redaction in customer-facing mode.
        sanitized = nl_response
        if deployment_mode == "customer_facing":
            sanitized = _redact_pii(sanitized)
            if sanitized != nl_response:
                emit_trace_event(
                    "tracking_output_pii_redacted",
                    {"mode": deployment_mode},
                    state,
                )

        emit_trace_event(
            "tracking_output_released",
            {"mode": deployment_mode, "unified_status": state.get("unified_status")},
            state,
        )
        return {
            "status": AgentStatus.SUCCESS,
            "scope_out": False,
            "nl_response": sanitized,
            "formatted_output": sanitized,
        }
