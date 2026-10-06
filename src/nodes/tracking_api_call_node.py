"""AgentCore Platform v1.0

Step 3 — TrackingAPICall node. The "act" / dispatch step.

Calls the routed data source (the internal transport-management endpoint or a
carrier API). In this template that dispatch is a DETERMINISTIC in-code
reference dataset keyed by carrier + tracking number — no live HTTP — so the
pipeline is exercisable end to end without external carrier agreements. Swap
_STUB_RESPONSES for a real transport to integrate a live carrier.

Security:
  - Access control: when a credential is required it is resolved at runtime
    from the InvocationContext secrets accessor passed via
    config["configurable"]["invocation_context"]. Missing credential → access
    denied (ERROR), never an unauthenticated call.
  - Secrets handling: the secret VALUE is never stored in State, logged, or
    hardcoded. Only the credential KEY NAME (from CarrierRoute) is read.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# Deterministic reference dataset standing in for the carrier APIs. Keyed by
# carrier_code → tracking_number → raw carrier-shaped response. Shapes
# intentionally differ per carrier so StatusNormalize has real reconciliation
# work to do.
_STUB_RESPONSES: dict[str, dict[str, dict[str, Any]]] = {
    "yamato": {
        "123456789012": {
            "status_code": "03",  # in transit
            "status_text": "輸送中",
            "delivery_estimate": "2026-06-09 18:00",
            "updated_at": "2026-06-08 09:15",
            "flags": [],
        },
        "999999999999": {
            "status_code": "90",  # delivered
            "status_text": "配達完了",
            "delivery_estimate": "2026-06-08 10:00",
            "updated_at": "2026-06-08 10:02",
            "flags": [],
        },
    },
    "sagawa": {
        "11122233344": {
            "tracking_state": "DELAYED",
            "eta": "2026-06-10 12:00",
            "as_of": "2026-06-08 08:40",
            "exceptions": ["weather_delay"],
        },
    },
    "jppost": {
        "EE123456789JP": {
            "state": "CUSTOMS",
            "estimated_delivery": "2026-06-12",
            "timestamp": "2026-06-08 07:00",
            "hold_reason": "customs_inspection",
        },
    },
    "tms": {
        "TMS000042": {
            "tms_status": "PENDING_PICKUP",
            "promised_eta": "2026-06-09",
            "snapshot_time": "2026-06-08 06:30",
            "alerts": [],
        },
    },
}


def _resolve_secrets(state: dict[str, Any], config: dict[str, Any] | None) -> Any:
    """Return the SecretProvider for this invocation.

    Production path: ``InvocationContext.from_state(state).secrets`` reads the
    provider bound by ``bound_secrets(agent._secrets_provider)`` at the agent
    boundary (ContextVar). A test/explicit override may pass the context via
    ``config["configurable"]["invocation_context"]``. The secret VALUE is never
    stored in State.
    """
    config = config or {}
    ctx = config.get("configurable", {}).get("invocation_context")
    if ctx is not None and getattr(ctx, "secrets", None) is not None:
        return ctx.secrets
    try:
        return InvocationContext.from_state(state).secrets
    except (KeyError, TypeError):
        return None


def _resolve_credential_key(state: dict[str, Any], config: dict[str, Any] | None) -> str | None:
    """Resolve the credential value for the selected carrier.

    Returns the credential value if available, None if a required credential is
    missing. The value is used only to gate the call — never returned in state.
    """
    routing = state.get("live_data_response", {}).get("_routing", {})
    credential_key = routing.get("credential_key")
    if not credential_key:
        return None

    secrets = _resolve_secrets(state, config)
    if secrets is None:
        return None
    value: str | None = secrets.get(credential_key)
    return value


class TrackingAPICallNode(FunctionNode):
    """Dispatch the tracking lookup against the routed data source."""

    # Input-facing node; agent.yaml declares VERIFIED_EXTERNAL for the agent.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        carrier_code = state.get("carrier_code")
        tracking_number = state.get("tracking_number", "")

        # Resolve the credential by key name via the secrets accessor. For
        # internal lookups and local runs a credential may be absent; only
        # external carrier APIs strictly require one.
        credential = _resolve_credential_key(state, config)
        data_source = state.get("data_source")
        if data_source == "carrier_api" and credential is None:
            emit_trace_event(
                "tracking_lookup_refused",
                {"reason": "missing_credential", "carrier_code": carrier_code},
                state,
            )
            return {
                "status": AgentStatus.ERROR,
                "error": "missing_credential",
                "error_log": ["TrackingAPICallNode: carrier API credential unavailable " "— call refused"],
            }

        carrier_stub = _STUB_RESPONSES.get(carrier_code or "", {})
        raw = carrier_stub.get(tracking_number)

        if raw is None:
            # Graceful degradation: surface a friendly outage/unknown signal,
            # NOT a raw tool error. Pipeline continues to normalize/respond.
            data_timestamp = ""
            live = {
                "_carrier": carrier_code,
                "_available": False,
                "_message": "tracking temporarily unavailable",
            }
        else:
            data_timestamp = (
                raw.get("updated_at") or raw.get("as_of") or raw.get("timestamp") or raw.get("snapshot_time") or ""
            )
            live = {
                "_carrier": carrier_code,
                "_available": True,
                "raw": raw,
            }

        emit_trace_event(
            "tracking_lookup_dispatched",
            {
                "carrier_code": carrier_code,
                "data_source": data_source,
                "available": bool(live.get("_available")),
            },
            state,
        )
        return {
            "status": AgentStatus.SUCCESS,
            "live_data_response": live,
            "data_timestamp": data_timestamp,
        }
