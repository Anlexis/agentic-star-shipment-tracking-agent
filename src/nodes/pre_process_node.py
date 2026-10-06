"""AgentCore Platform v1.0

pre_process slot node for RealtimeShipmentTrackingAgent.

Inline slot orchestration: runs the
pre-processing business sub-nodes in order and merges their partial dicts —
InputParse → CarrierRoute. Short-circuits on the first ERROR so a parse
failure never reaches carrier routing.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.nodes.input_parse_node import InputParseNode
from src.nodes.carrier_route_node import CarrierRouteNode


def _is_error(status: object) -> bool:
    return status in (AgentStatus.ERROR, AgentStatus.ERROR.value)


class PreProcessNode(FunctionNode):
    """Slot node: InputParse → CarrierRoute (inline, short-circuit on error)."""

    # This is the input-facing REGISTERED node — the framework trust gate
    # (BaseNode.__call__) reads required_trust_level from THIS class, not the
    # inner sub-nodes. Keep it aligned with agent.yaml (VERIFIED_EXTERNAL).
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self) -> None:
        self._input_parse = InputParseNode()
        self._carrier_route = CarrierRouteNode()

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        r1 = self._input_parse.execute(state)
        if _is_error(r1.get("status")):
            emit_trace_event(
                "pre_process_completed",
                {"outcome": "error", "step": "input_parse"},
                state,
            )
            return r1

        merged = {**state, **r1}
        r2 = self._carrier_route.execute(merged)
        if _is_error(r2.get("status")):
            emit_trace_event(
                "pre_process_completed",
                {"outcome": "error", "step": "carrier_route"},
                state,
            )
            return {**r1, **r2}

        emit_trace_event("pre_process_completed", {"outcome": "success"}, state)
        return {**r1, **r2}
