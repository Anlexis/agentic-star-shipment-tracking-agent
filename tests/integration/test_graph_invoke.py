# LOG-C2-030 — Integration: end-to-end graph compile + invoke

from src.graph.graph import RealtimeShipmentTrackingAgent
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from framework.secrets.base import SecretProvider
from framework.secrets.context import bound_secrets


class _FakeSecrets(SecretProvider):
    def __init__(self, mapping):
        self._m = mapping

    def get(self, key, default=None):
        return self._m.get(key, default)


def _ctx_internal():
    return InvocationContext.for_internal()


class TestGraphInvoke:
    def setup_method(self):
        self.agent = RealtimeShipmentTrackingAgent()
        self.agent.compile()

    def test_compiles_and_names_match_manifest(self):
        assert self.agent.name == "RealtimeShipmentTrackingAgent"

    def test_tms_happy_path(self):
        """End-to-end TMS lookup → in-range pending status, populated output."""
        out = self.agent.invoke("where is TMS000042", ctx=_ctx_internal())
        assert out["status"] == AgentStatus.SUCCESS.value
        assert "TMS000042" in out["output"]
        assert out["scope_out"] is False

    def test_carrier_api_happy_path_with_secret(self):
        """A 12-digit reference must be sent on the structured channel.

        The framework masks personal-data shapes in free text before any node
        runs, and a bare 12-digit run is indistinguishable from a national
        identification number — so this reference does not survive the
        narrative channel. Secrets are bound at the agent boundary
        (ContextVar), mirroring the adapter.
        """
        with bound_secrets(_FakeSecrets({"YAMATO_API_KEY": "x"})):
            out = self.agent.invoke(
                "where is my parcel",
                ctx=_ctx_internal(),
                input_context={"tracking_number": "123456789012"},
            )
        assert out["status"] == AgentStatus.SUCCESS.value
        assert "123456789012" in out["output"]
        assert out["unified_status"] == "in_transit"

    def test_twelve_digit_reference_in_narrative_is_masked_before_parsing(self):
        """The reason the structured channel exists, pinned as behaviour.

        This is a framework-level property, not a template choice: if it ever
        changes, this test fails and the operation guide needs revisiting.
        """
        with bound_secrets(_FakeSecrets({"YAMATO_API_KEY": "x"})):
            out = self.agent.invoke("track 123456789012", ctx=_ctx_internal())
        assert out["status"] == AgentStatus.ERROR.value
        assert out["error"] == "no_tracking_number"

    def test_empty_input_short_circuits_to_error(self):
        out = self.agent.invoke("   ", ctx=_ctx_internal())
        assert out["status"] == AgentStatus.ERROR.value

    def test_no_tracking_number_short_circuits(self):
        out = self.agent.invoke("hello there", ctx=_ctx_internal())
        assert out["status"] == AgentStatus.ERROR.value

    def test_policy_question_scopes_out(self):
        out = self.agent.invoke("what is the damage claim process for TMS000042", ctx=_ctx_internal())
        assert out["scope_out"] is True
        assert "out of scope" in out["output"]
        # A scoped-out answer carries no tracking data at all.
        assert out["unified_status"] is None
        assert out["eta"] is None

    def test_customer_facing_redacts_internal_id_end_to_end(self):
        """deployment_mode travels from input_context to the output gate, which
        redacts the internal reference from customer-facing output."""
        with bound_secrets(_FakeSecrets({"TMS_API_KEY": "t"})):
            out = self.agent.invoke(
                "where is TMS000042",
                ctx=_ctx_internal(),
                input_context={"deployment_mode": "customer_facing"},
            )
        assert out["status"] == AgentStatus.SUCCESS.value
        assert "TMS000042" not in out["output"]
        assert "[redacted]" in out["output"]

    def test_coordinator_mode_keeps_internal_id_end_to_end(self):
        out = self.agent.invoke("where is TMS000042", ctx=_ctx_internal())
        assert out["status"] == AgentStatus.SUCCESS.value
        assert "TMS000042" in out["output"]

    def test_trust_gate_denies_anonymous(self):
        """Input-facing nodes require VERIFIED_EXTERNAL; anonymous is denied."""
        ctx = InvocationContext(caller_trust_level=TrustLevel.ANONYMOUS)
        out = self.agent.invoke("track TMS000042", ctx=ctx)
        assert out["status"] == AgentStatus.ERROR.value
