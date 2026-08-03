"""コスト管理(要件10章)。生成呼び出し前に課金予測し、上限超過なら停止する。"""

from __future__ import annotations

from app.config import settings
from app.models import CostEntry, Project

# 概算単価(円)。実勢に合わせて COST_TABLE_JSON 環境変数で上書き可
DEFAULT_COST_TABLE: dict[str, float] = {
    "gemini_call": 2.0,      # 1呼び出し
    "imagen_image": 6.0,     # 1枚
    "veo_second": 60.0,      # 生成動画1秒
    "tts_1k_chars": 2.5,     # 1,000文字
    "stt_minute": 4.0,       # 音声1分
    "lyria_track": 10.0,     # 1トラック
}


class CostLimitExceeded(Exception):
    def __init__(self, message: str, needed: float, limit: float):
        super().__init__(message)
        self.needed = needed
        self.limit = limit


class CostMeter:
    def __init__(self, project: Project):
        self.project = project
        self.table = {**DEFAULT_COST_TABLE, **settings.cost_table_override}
        self.limit = project.cost_limit_jpy or settings.default_cost_limit_jpy

    def charge(self, service: str, quantity: float, stage: str) -> float:
        """生成実行の直前に呼ぶ。上限超過が予測される場合は実行前に停止する。"""
        unit = self.table[service]
        cost = round(unit * quantity, 1)
        projected = self.project.total_cost() + cost
        if not self.project.cost_limit_override_approved and projected > self.limit:
            reason = (
                f"コスト上限停止: {service} x{quantity} (+¥{cost}) を実行すると "
                f"累計¥{projected} となり上限¥{self.limit} を超えます"
            )
            self.project.cost_stop_reason = reason
            raise CostLimitExceeded(reason, projected, self.limit)
        self.project.costs.append(
            CostEntry(service=service, quantity=quantity, unit_jpy=unit,
                      cost_jpy=cost, stage=stage)
        )
        return cost
