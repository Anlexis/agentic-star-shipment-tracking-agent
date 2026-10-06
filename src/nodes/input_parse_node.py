"""AgentCore Platform v1.0

Step 1 — InputParse node.

Extracts and validates a tracking number and identifies the carrier from the
tracking-number format.

Two input channels, in priority order:

  1. ``input_context["tracking_number"]`` — the structured channel. A caller
     that already knows the tracking number should send it here.
  2. The natural-language query — scanned for a token that matches a known
     carrier format.

The structured channel exists because the narrative channel is not lossless.
Free-text input passes through a personal-data mask before any node sees it,
and a bare 12-digit run is indistinguishable from a national identification
number — so a 12-digit consignment reference sent inside a sentence arrives
already masked and cannot be recovered. The structured field is validated
against the same inert pattern and carries no such ambiguity.

Security:
  - Empty input refused (→ AgentStatus.ERROR).
  - The query is screened for instruction-injection BEFORE parsing, both as
    received and after markup is stripped, so neither a control-token payload
    nor a directive spliced through markup survives.
  - The tracking number is locked to an inert alphanumeric identifier and
    rejected unless it matches a known carrier / internal format, so no
    unbounded caller string flows downstream.
  - Rejected values are never echoed back; refusals name the field only.
"""

import re
from typing import Any, ClassVar, Optional

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# Carrier detection from the sanitized (alphanumeric) tracking number.
# Order matters: more specific patterns first.
#   yamato : 12-digit numeric
#   sagawa : 11-digit numeric
#   jppost : 13 chars, optional 2-letter prefix + digits + 2-letter suffix
#   internal : transport-management reference — "TMS" prefix + 6-12 digits
_CARRIER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("tms", re.compile(r"^TMS[0-9]{6,12}$", re.IGNORECASE)),
    ("jppost", re.compile(r"^[A-Z]{2}[0-9]{9}[A-Z]{2}$", re.IGNORECASE)),
    ("yamato", re.compile(r"^[0-9]{12}$")),
    ("sagawa", re.compile(r"^[0-9]{11}$")),
    ("jppost", re.compile(r"^[0-9]{13}$")),
]

# Candidates are whitespace-delimited tokens. Each token is sanitized
# (internal separators like "-" / "/" stripped) before format matching, so
# "1234-5678-9012" collapses to a 12-digit consignment number. A sanitized
# token longer than the max known format is rejected.
_MAX_TRACKING_LEN = 18

# The inert identifier the structured channel is locked to. Deliberately the
# same alphabet the sanitizer produces, so both channels converge on one shape.
_TRACKING_ID_RE = re.compile(r"^[A-Za-z0-9]{1,18}$")

_VALID_DEPLOYMENT_MODES = ("coordinator", "customer_facing")

# --- injection screen -------------------------------------------------------
# Chat-template control tokens, screened as a CLASS rather than as a list of
# known phrases. A payload wrapped in these markers is a framing attack whether
# or not the words that follow look like an instruction.
_CONTROL_TOKEN_RE = re.compile(r"<\|[^|>]{0,64}\|>|\[/?INST\]|<</?SYS>>", re.IGNORECASE)

# Directive forms, anchored at both ends so ordinary logistics prose does not
# trip them. "Disregard the damaged carton" must pass; "disregard all previous
# instructions" must not.
_DIRECTIVE_RE = re.compile(
    r"(?i)\b(?:ignore|disregard|forget|override|bypass)\s+"
    r"(?:all\s+|any\s+|your\s+|the\s+)*"
    r"(?:(?:previous|prior|above|earlier|system|preceding)\s+)+"
    r"(?:instructions?|rules?|prompts?|directives?|messages?)\b"
)

# Role-reassignment, likewise anchored on a privileged role so that domain
# phrases such as "act as a freight agent" are unaffected.
_ROLE_RE = re.compile(
    r"(?i)\b(?:you\s+are\s+now|act\s+as|pretend\s+to\s+be|roleplay\s+as)\s+"
    r"(?:an?\s+|the\s+)?(?:system|admin(?:istrator)?|developer|root|operator)\b"
)

# Markup stripped before the second screening pass, so a directive spliced
# through tags ("ig<b>nore all previous instructions") is caught once the text
# is re-assembled.
_MARKUP_RE = re.compile(r"<[^<>]{0,200}>")

_INJECTION_PATTERNS = (_CONTROL_TOKEN_RE, _DIRECTIVE_RE, _ROLE_RE)


def _strip_markup(text: str) -> str:
    return _MARKUP_RE.sub("", text)


def _is_injection(text: str) -> bool:
    """Screen a caller string both as received and after markup removal.

    Order matters. Control tokens are matched on the raw text, because a markup
    strip can silently delete them and forward the directive residue as
    innocuous plain text. Directives are matched on both forms, because
    stripping is also what re-assembles a spliced one.
    """
    if not text:
        return False
    for form in (text, _strip_markup(text)):
        if any(p.search(form) for p in _INJECTION_PATTERNS):
            return True
    return False


def _sanitize(token: str) -> str:
    """Strip everything that is not alphanumeric."""
    return re.sub(r"[^A-Za-z0-9]", "", token)


def _identify_carrier(tracking_number: str) -> Optional[str]:
    for carrier, pattern in _CARRIER_PATTERNS:
        if pattern.match(tracking_number):
            return carrier
    return None


class InputParseNode(FunctionNode):
    """Validate + parse the user request; extract tracking number & carrier."""

    # Input-facing node; agent.yaml declares VERIFIED_EXTERNAL for the agent.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def _refuse(self, state: dict[str, Any], reason: str, **extra: object) -> dict[str, Any]:
        emit_trace_event("tracking_input_refused", {"reason": reason}, state)
        refusal = {
            "status": AgentStatus.ERROR,
            "error": reason,
            "error_log": [f"InputParseNode: {reason}"],
        }
        refusal.update(extra)
        return refusal

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        raw_query = state.get("user_input", "")
        context = state.get("input_context") or {}
        if not isinstance(context, dict):
            context = {}

        # deployment_mode defaults to the SAFER mode: redaction is on unless a
        # caller explicitly opts into the internal-operator view.
        requested_mode = context.get("deployment_mode")
        deployment_mode = requested_mode if requested_mode in _VALID_DEPLOYMENT_MODES else "coordinator"

        if not raw_query or not raw_query.strip():
            return self._refuse(state, "empty_input", deployment_mode=deployment_mode)

        raw_query = raw_query.strip()

        # Screen before parsing. A refused query never reaches routing, the
        # transport, or the response text.
        if _is_injection(raw_query):
            return self._refuse(state, "injection_detected", deployment_mode=deployment_mode)

        # Channel 1 — the structured tracking number.
        tracking_number = ""
        carrier_code: Optional[str] = None
        supplied = context.get("tracking_number")
        if supplied is not None:
            if not isinstance(supplied, str) or not _TRACKING_ID_RE.match(supplied):
                # Name the field, never the value.
                return self._refuse(
                    state,
                    "invalid_tracking_number_field",
                    deployment_mode=deployment_mode,
                    raw_query=raw_query,
                )
            carrier_code = _identify_carrier(supplied)
            if carrier_code is None:
                return self._refuse(
                    state,
                    "unrecognised_tracking_number_format",
                    deployment_mode=deployment_mode,
                    raw_query=raw_query,
                )
            tracking_number = supplied

        # Channel 2 — scan the narrative for a format-valid token.
        if not tracking_number:
            for token in raw_query.split():
                candidate = _sanitize(token)
                if not candidate or len(candidate) > _MAX_TRACKING_LEN:
                    continue
                carrier = _identify_carrier(candidate)
                if carrier is not None:
                    tracking_number = candidate
                    carrier_code = carrier
                    break

        if not tracking_number:
            return self._refuse(
                state,
                "no_tracking_number",
                raw_query=raw_query,
                deployment_mode=deployment_mode,
            )

        emit_trace_event(
            "tracking_input_parsed",
            {"carrier_code": carrier_code, "mode": deployment_mode},
            state,
        )
        return {
            "status": AgentStatus.SUCCESS,
            "raw_query": raw_query,
            "tracking_number": tracking_number,
            "carrier_code": carrier_code,
            "deployment_mode": deployment_mode,
            "validated_input": raw_query,
        }
