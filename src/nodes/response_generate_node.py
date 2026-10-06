"""AgentCore Platform v1.0

Step 5 — ResponseGenerate node.

Builds the user-facing tracking answer grounded in the normalized live data.
Always includes: tracking-number echo, data timestamp ("data as of HH:MM"),
ETA (if available), exception-flag summary, and a recommended next action.
Conservative framing: reports the ETA from data, never promises delivery.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

_STATUS_TEXT = {
    "in_transit": "in transit",
    "delivered": "delivered",
    "exception": "needs attention",
    "pending": "pending pickup / not yet scanned",
}

_NEXT_ACTION = {
    "in_transit": "No action needed — the shipment is moving normally.",
    "delivered": "No action needed — the shipment has been delivered.",
    "exception": "Review the exception flags below and contact the carrier if needed.",
    "pending": "Allow time for the first scan; re-check later if status does not update.",
}


def _as_of(data_timestamp: str) -> str:
    if not data_timestamp:
        return "data as of unknown time"
    # Show HH:MM if present, else the raw timestamp.
    parts = data_timestamp.split(" ")
    if len(parts) == 2 and ":" in parts[1]:
        return f"data as of {parts[1][:5]}"
    return f"data as of {data_timestamp}"


class ResponseGenerateNode(FunctionNode):
    """Generate the natural-language tracking summary from normalized data."""

    # Input-facing node; agent.yaml declares VERIFIED_EXTERNAL for the agent.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        tracking_number = state.get("tracking_number", "")
        unified_status = state.get("unified_status", "pending")
        eta = state.get("eta")
        exception_flags = state.get("exception_flags", [])
        data_timestamp = state.get("data_timestamp", "")
        live = state.get("live_data_response", {})

        as_of = _as_of(data_timestamp)

        # Graceful-degradation path: carrier data was unavailable.
        if not live.get("_available"):
            nl = (
                f"Tracking for {tracking_number}: tracking is temporarily "
                f"unavailable. Please try again shortly. ({as_of})"
            )
            emit_trace_event(
                "tracking_response_generated",
                {"available": False, "unified_status": unified_status},
                state,
            )
            return {
                "status": AgentStatus.SUCCESS,
                "nl_response": nl,
                "data_timestamp": data_timestamp,
            }

        status_text = _STATUS_TEXT.get(unified_status, unified_status)
        lines = [
            f"Tracking number {tracking_number}: status is {status_text}.",
        ]
        if eta:
            # Conservative: report the carrier's ETA, do not promise delivery.
            lines.append(f"Carrier-estimated delivery: {eta} (estimate, not guaranteed).")
        if exception_flags:
            lines.append("Exception flags: " + ", ".join(exception_flags) + ".")
        lines.append(_NEXT_ACTION.get(unified_status, ""))
        lines.append(f"({as_of})")

        nl = " ".join(part for part in lines if part)

        emit_trace_event(
            "tracking_response_generated",
            {
                "available": True,
                "unified_status": unified_status,
                "has_eta": bool(eta),
                "exception_flags": exception_flags,
            },
            state,
        )
        return {
            "status": AgentStatus.SUCCESS,
            "nl_response": nl,
            "data_timestamp": data_timestamp,
        }
