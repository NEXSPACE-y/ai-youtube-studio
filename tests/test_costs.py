import pytest

from app.costs import CostLimitExceeded, CostMeter
from app.models import Project


def test_charge_accumulates():
    p = Project(cost_limit_jpy=1000)
    meter = CostMeter(p)
    meter.charge("imagen_image", 2, "assets")
    assert p.total_cost() == 12.0
    assert p.costs[0].stage == "assets"


def test_limit_stops_before_execution():
    p = Project(cost_limit_jpy=100)
    meter = CostMeter(p)
    with pytest.raises(CostLimitExceeded):
        meter.charge("veo_second", 8, "assets")  # 480円 > 100円
    # 停止理由が記録され、コストは計上されない(実行前に停止)
    assert p.cost_stop_reason
    assert p.total_cost() == 0.0


def test_override_allows_exceeding():
    p = Project(cost_limit_jpy=100, cost_limit_override_approved=True)
    meter = CostMeter(p)
    meter.charge("veo_second", 8, "assets")
    assert p.total_cost() == 480.0


def test_regeneration_counts_add_up():
    p = Project(cost_limit_jpy=10000)
    meter = CostMeter(p)
    for _ in range(3):
        meter.charge("imagen_image", 1, "assets")
    assert len(p.costs) == 3  # 再生成回数の把握(要件10章)
