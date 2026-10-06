# LOG-C2-030 — Unit Tests: ResponseGenerate (#7) + ResponseValidate (#7)

from src.nodes.response_generate_node import ResponseGenerateNode
from src.nodes.response_validate_node import ResponseValidateNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel


class TestResponseGenerateNode:
    def setup_method(self):
        self.node = ResponseGenerateNode()

    def test_includes_tracking_number_eta_and_as_of(self):
        state = {
            "tracking_number": "123456789012",
            "unified_status": "in_transit",
            "eta": "2026-06-09 18:00",
            "exception_flags": [],
            "data_timestamp": "2026-06-08 09:15",
            "live_data_response": {"_available": True},
        }
        r = self.node.execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert "123456789012" in r["nl_response"]  # tracking-number echo
        assert "2026-06-09 18:00" in r["nl_response"]  # ETA
        assert "data as of 09:15" in r["nl_response"]  # data freshness

    def test_no_delivery_promise_framing(self):
        state = {
            "tracking_number": "123456789012",
            "unified_status": "in_transit",
            "eta": "2026-06-09 18:00",
            "exception_flags": [],
            "data_timestamp": "2026-06-08 09:15",
            "live_data_response": {"_available": True},
        }
        r = self.node.execute(state)
        # Conservative framing: estimate, not a guarantee.
        assert "estimate" in r["nl_response"].lower()
        assert "will arrive by" not in r["nl_response"].lower()

    def test_exception_flags_summarized(self):
        state = {
            "tracking_number": "11122233344",
            "unified_status": "exception",
            "eta": None,
            "exception_flags": ["delay"],
            "data_timestamp": "2026-06-08 08:40",
            "live_data_response": {"_available": True},
        }
        r = self.node.execute(state)
        assert "delay" in r["nl_response"]

    def test_unavailable_data_message(self):
        state = {
            "tracking_number": "TMS99999",
            "data_timestamp": "",
            "live_data_response": {"_available": False},
        }
        r = self.node.execute(state)
        assert "temporarily unavailable" in r["nl_response"]


class TestResponseValidateNode:
    def setup_method(self):
        self.node = ResponseValidateNode()

    def test_trust_floor(self):
        assert ResponseValidateNode.required_trust_level == TrustLevel.VERIFIED_EXTERNAL

    def test_policy_question_scopes_out(self):
        """Scope boundary: a policy question scopes out with no carrier data."""
        state = {
            "raw_query": "what is the damage claim process?",
            "nl_response": "Tracking number 123456789012: status is delivered.",
            "deployment_mode": "coordinator",
        }
        r = self.node.execute(state)
        assert r["scope_out"] is True
        assert "123456789012" not in r["nl_response"]
        assert "out of scope" in r["nl_response"]

    def test_empty_output_refused(self):
        r = self.node.execute({"raw_query": "track 123456789012", "nl_response": "   "})
        assert r["status"] == AgentStatus.ERROR
        assert r["error"] == "empty_output"

    def test_secret_in_output_refused(self):
        """A credential pattern in the output is refused outright."""
        state = {
            "raw_query": "track 123456789012",
            "nl_response": "Your tracking key is sk-abcd1234efgh5678",
            "deployment_mode": "coordinator",
        }
        r = self.node.execute(state)
        assert r["status"] == AgentStatus.ERROR
        assert r["error"] == "secret_in_output"
        assert "sk-abcd1234efgh5678" not in r["nl_response"]

    def test_pii_redacted_in_customer_facing(self):
        """customer_facing mode redacts internal ids and consignee details."""
        state = {
            "raw_query": "track 123456789012",
            "nl_response": "Status delivered. Consignee Taro Yamada at 123 Main St. Internal id TMS000042.",
            "deployment_mode": "customer_facing",
        }
        r = self.node.execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert "TMS000042" not in r["nl_response"]
        assert "Taro Yamada" not in r["nl_response"]
        assert "[redacted]" in r["nl_response"]

    def test_coordinator_mode_keeps_internal_fields(self):
        """Coordinator mode does NOT redact (internal operators need the detail)."""
        state = {
            "raw_query": "track 123456789012",
            "nl_response": "Status delivered. Internal id TMS000042.",
            "deployment_mode": "coordinator",
        }
        r = self.node.execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert "TMS000042" in r["nl_response"]
        assert r["scope_out"] is False

    def test_clean_response_passes(self):
        state = {
            "raw_query": "track 123456789012",
            "nl_response": "Tracking number 123456789012: status is in transit.",
            "deployment_mode": "coordinator",
        }
        r = self.node.execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert r["formatted_output"] == r["nl_response"]
