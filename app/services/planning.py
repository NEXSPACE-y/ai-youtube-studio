"""企画作成(要件5.1)。"""

from __future__ import annotations

import difflib

from app import llm, prompts, states
from app.config import settings
from app.costs import CostMeter
from app.models import Project


def _stub(theme: str) -> dict:
    return {
        "theme_summary": f"「{theme}」を事実ベースで解説するミニドキュメンタリー。",
        "audience": "技術や失敗事例の背景を知りたい社会人・学生",
        "purpose": "出来事の構造と教訓を10分以内で理解できるようにする",
        "title_candidates": [
            f"{theme}は なぜ起きたのか",
            f"{theme}の全記録",
            f"検証: {theme}",
            f"{theme} 失敗の構造",
            f"{theme}が残した教訓",
        ],
        "unique_angle": "複数事例との比較と原因構造の整理(ローカルモードのダミー企画)",
    }


def make_project(theme_hint: str, existing_titles: list[str]) -> Project:
    project = Project(theme=theme_hint, cost_limit_jpy=settings.default_cost_limit_jpy)
    meter = CostMeter(project)
    if settings.is_local:
        data = _stub(theme_hint)
    else:
        meter.charge("gemini_call", 1, "planning")
        data, _ = llm.generate_json(prompts.PLANNING.format(theme=theme_hint))

    # 類似テーマとの重複確認(要件5.1)
    dup = []
    for cand in data.get("title_candidates", [])[:1]:
        for t in existing_titles:
            if t and difflib.SequenceMatcher(None, t, cand).ratio() > 0.7:
                dup.append(t)
    data["duplicate_warnings"] = dup
    data["decision"] = ""

    project.planning = data
    project.title = (data.get("title_candidates") or [theme_hint])[0]
    project.audience = data.get("audience", "")
    project.purpose = data.get("purpose", "")
    project.uniqueness_note = data.get("unique_angle", "")
    project.log("企画案を生成", note=f"重複警告 {len(dup)}件")
    return project


def decide(project: Project, decision: str, actor: str) -> None:
    """採用/保留/却下の記録(要件5.1・13章: 企画の採否は人間)。"""
    if decision not in ("採用", "保留", "却下"):
        raise ValueError(f"不明な判定: {decision}")
    project.planning["decision"] = decision
    target = {
        "採用": states.RESEARCH,
        "保留": states.ON_HOLD,
        "却下": states.CANCELLED,
    }[decision]
    states.transition(project, target, actor=actor, note=f"企画{decision}")
