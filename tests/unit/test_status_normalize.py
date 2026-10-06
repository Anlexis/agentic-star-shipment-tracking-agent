# LOG-C2-030 — Unit Tests: StatusNormalize node (#6)

from src.nodes.status_normalize_node import StatusNormalizeNode
from framework.schemas.agent_status import AgentStatus


def _live(carrier, raw):
    return {"live_data_response": {"_carrier": carrier, "_available": True, "raw": raw}}


class TestStatusNormalizeNode:
    def setup_method(self):
        self.node = StatusNormalizeNode()

    def test_yamato_in_transit(self):
        r = self.node.execute(
            _live("yamato", {"status_code": "03", "delivery_estimate": "2026-06-09 18:00", "flags": []})
        )
        assert r["status"] == AgentStatus.SUCCESS
        assert r["unified_status"] == "in_transit"
        assert r["eta"] == "2026-06-09 18:00"
        assert r["exception_flags"] == []

    def test_yamato_delivered(self):
        r = self.node.execute(_live("yamato", {"status_code": "90", "flags": []}))
        assert r["unified_status"] == "delivered"

    def test_sagawa_delay_becomes_exception(self):
        r = self.node.execute(
            _live("sagawa", {"tracking_state": "DELAYED", "eta": "2026-06-10", "exceptions": ["weather_delay"]})
        )
        assert r["unified_status"] == "exception"
        assert "delay" in r["exception_flags"]

    def test_jppost_customs_hold(self):
        r = self.node.execute(
            _live(
                "jppost", {"state": "CUSTOMS", "estimated_delivery": "2026-06-12", "hold_reason": "customs_inspection"}
            )
        )
        assert r["unified_status"] == "exception"
        assert "customs" in r["exception_flags"]

    def test_tms_pending(self):
        r = self.node.execute(
            _live("tms", {"tms_status": "PENDING_PICKUP", "promised_eta": "2026-06-09", "alerts": []})
        )
        assert r["unified_status"] == "pending"

    def test_unavailable_data_normalizes_to_pending(self):
        r = self.node.execute({"live_data_response": {"_carrier": "tms", "_available": False}})
        assert r["status"] == AgentStatus.SUCCESS
        assert r["unified_status"] == "pending"
        assert r["exception_flags"] == []
