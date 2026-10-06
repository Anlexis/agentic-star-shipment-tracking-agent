"""AgentCore Platform v1.0"""

# State must be a flat TypedDict — never a Pydantic BaseModel.
# LangGraph checkpoints use msgpack serialization; Pydantic objects
# cause silent corruption.  Extend AgentState with agent-specific
# fields only.  Do NOT add credentials, secrets, or Pydantic models.

from typing import Any, Literal, Optional

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """Real-time shipment tracking agent state (LOG-C2-030).

    Flat TypedDict — primitives + JSON-serializable values only (msgpack-safe).
    Shared fields (user_input, status, session_id, node_history, error_log, ...)
    are inherited from AgentState.  Carrier credentials and recipient PII are
    NEVER stored here: credentials resolve at runtime via
    ``config["configurable"]["invocation_context"]``; recipient personal data
    is redacted in the output gate, never persisted to state or checkpoints.
    """

    # --- pre_process: InputParse + CarrierRoute ---
    raw_query: str
    # original natural-language query
    tracking_number: str
    # validated tracking number (non-alphanumerics stripped, format-checked)
    carrier_code: Optional[str]
    # identified carrier ("yamato" / "sagawa" / "jppost" / "tms"); None if ambiguous
    data_source: Literal["tms", "carrier_api"]
    # routing decision produced by CarrierRoute

    # --- main: TrackingAPICall + StatusNormalize ---
    live_data_response: dict[str, Any]
    # raw normalized tool/API response (JSON-serializable; no recipient PII persisted)
    unified_status: Literal["in_transit", "delivered", "exception", "pending"]
    # cross-carrier normalized status from StatusNormalize
    eta: Optional[str]
    # estimated delivery time, if the source provides one
    exception_flags: list[str]
    # subset of: "delay" / "customs_hold" / "damage" / "returned"
    data_timestamp: str
    # "data as of HH:MM" source freshness — surfaced in every response

    # --- post_process: ResponseGenerate + ResponseValidate (output gate) ---
    nl_response: str
    # generated natural-language answer
    scope_out: bool
    # True when ResponseValidate routes a carrier-policy question to Variant A (a peer template)

    # --- runtime control ---
    deployment_mode: Literal["coordinator", "customer_facing"]
    # controls redaction; treated as "coordinator" when unset or unrecognised
    error: Optional[str]
    # short-circuit / graceful-degradation flag (e.g. invalid tracking number, API outage)
