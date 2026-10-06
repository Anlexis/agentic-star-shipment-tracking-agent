"""AgentCore Platform v1.0

Step 4 — StatusNormalize node. The "observe" step.

Maps carrier-specific status codes / taxonomies into the unified schema:
    in_transit | delivered | exception | pending
and extracts exception flags (delay / customs / damage / returned) + eta.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# Per-carrier status taxonomy → unified status.
_YAMATO_CODES = {
    "01": "pending",
    "03": "in_transit",
    "90": "delivered",
    "99": "exception",
}
_SAGAWA_STATES = {
    "PENDING": "pending",
    "IN_TRANSIT": "in_transit",
    "DELAYED": "exception",
    "DELIVERED": "delivered",
    "RETURNED": "exception",
}
_JPPOST_STATES = {
    "ACCEPTED": "pending",
    "IN_TRANSIT": "in_transit",
    "CUSTOMS": "exception",
    "DELIVERED": "delivered",
}
_TMS_STATES = {
    "PENDING_PICKUP": "pending",
    "IN_TRANSIT": "in_transit",
    "EXCEPTION": "exception",
    "DELIVERED": "delivered",
}

# Raw exception markers → canonical flag.
_FLAG_MAP = {
    "weather_delay": "delay",
    "delay": "delay",
    "customs_inspection": "customs",
    "customs": "customs",
    "damage": "damage",
    "returned": "returned",
}


def _canon_flags(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        flag = _FLAG_MAP.get(str(v).lower(), str(v).lower())
        if flag not in out:
            out.append(flag)
    return out


def _normalize(carrier: str, raw: dict[str, Any]) -> tuple[str, str | None, list[str]]:
    """Return (unified_status, eta, exception_flags) for one carrier response."""
    flags: list[str] = []
    eta: str | None = None

    if carrier == "yamato":
        unified = _YAMATO_CODES.get(str(raw.get("status_code")), "pending")
        eta = raw.get("delivery_estimate")
        flags = _canon_flags(raw.get("flags", []))
    elif carrier == "sagawa":
        unified = _SAGAWA_STATES.get(str(raw.get("tracking_state")).upper(), "pending")
        eta = raw.get("eta")
        flags = _canon_flags(raw.get("exceptions", []))
    elif carrier == "jppost":
        unified = _JPPOST_STATES.get(str(raw.get("state")).upper(), "pending")
        eta = raw.get("estimated_delivery")
        if raw.get("hold_reason"):
            flags = _canon_flags([raw["hold_reason"]])
    elif carrier == "tms":
        unified = _TMS_STATES.get(str(raw.get("tms_status")).upper(), "pending")
        eta = raw.get("promised_eta")
        flags = _canon_flags(raw.get("alerts", []))
    else:
        unified = "pending"

    # An exception flag forces the unified status to "exception".
    if flags and unified not in ("delivered",):
        unified = "exception"

    return unified, eta, flags


class StatusNormalizeNode(FunctionNode):
    """Normalize the raw carrier response into the canonical shipment schema."""

    # Input-facing node; agent.yaml declares VERIFIED_EXTERNAL for the agent.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        live = state.get("live_data_response", {})

        # Graceful-degradation case from TrackingAPICall: no data available.
        if not live.get("_available"):
            emit_trace_event(
                "shipment_status_normalized",
                {"available": False, "unified_status": "pending"},
                state,
            )
            return {
                "status": AgentStatus.SUCCESS,
                "unified_status": "pending",
                "eta": None,
                "exception_flags": [],
                "live_data_response": live,
            }

        carrier = live.get("_carrier")
        raw = live.get("raw", {})
        unified_status, eta, exception_flags = _normalize(carrier, raw)

        emit_trace_event(
            "shipment_status_normalized",
            {
                "available": True,
                "carrier_code": carrier,
                "unified_status": unified_status,
                "exception_flags": exception_flags,
            },
            state,
        )
        return {
            "status": AgentStatus.SUCCESS,
            "unified_status": unified_status,
            "eta": eta,
            "exception_flags": exception_flags,
            "live_data_response": {
                "_carrier": carrier,
                "_available": True,
                "unified_status": unified_status,
                "eta": eta,
                "exception_flags": exception_flags,
            },
        }
