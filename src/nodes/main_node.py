"""AgentCore Platform v1.0

main slot node for RealtimeShipmentTrackingAgent.

Inline slot orchestration: runs the
core business sub-nodes in order and merges their partial dicts —
TrackingAPICall (act) → StatusNormalize (observe). Short-circuits on ERROR
(e.g. missing carrier credential) so normalization never runs on a refused call.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.nodes.tracking_api_call_node import TrackingAPICallNode
from src.nodes.status_normalize_node import StatusNormalizeNode


def _is_error(status: object) -> bool:
    return status in (AgentStatus.ERROR, AgentStatus.ERROR.value)


class MainNode(FunctionNode):
    """Slot node: TrackingAPICall → StatusNormalize (inline, short-circuit)."""

    # Input-facing node; agent.yaml declares VERIFIED_EXTERNAL for the agent.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self) -> None:
        self._tracking_api_call = TrackingAPICallNode()
        self._status_normalize = StatusNormalizeNode()

    def execute(self, state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        # Backbone edges into "main" are unconditional, so an upstream
        # pre_process ERROR still reaches this slot — pass it through untouched.
        if _is_error(state.get("status")):
            emit_trace_event("main_completed", {"outcome": "upstream_error"}, state)
            return {"status": state["status"]}

        r1 = self._tracking_api_call.execute(state, config)
        if _is_error(r1.get("status")):
            emit_trace_event("main_completed", {"outcome": "error", "step": "tracking_api_call"}, state)
            return r1

        merged = {**state, **r1}
        r2 = self._status_normalize.execute(merged)
        if _is_error(r2.get("status")):
            emit_trace_event("main_completed", {"outcome": "error", "step": "status_normalize"}, state)
            return {**r1, **r2}

        emit_trace_event("main_completed", {"outcome": "success"}, state)
        return {**r1, **r2}
