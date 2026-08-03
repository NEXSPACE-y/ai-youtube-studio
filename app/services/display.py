"""演出プランナー(図解モーションエンジンの表示指定を生成)。

AIにはテンプレート名とテキストパラメータだけを出させる(コードは書かせない)。
"""

from __future__ import annotations

import json

from app import llm, prompts
from app.config import settings
from app.costs import CostMeter
from app.models import Project

TEMPLATES = {"title_card", "keyword_pop", "bullets", "compare_cards", "none"}
MAX_ITEMS = 5
MAX_TITLE = 20
MAX_ITEM_CHARS = 24


def _sanitize(raw: dict) -> dict:
    template = raw.get("template", "none")
    if template not in TEMPLATES:
        template = "none"
    title = str(raw.get("title", ""))[:MAX_TITLE]
    items = [str(i)[:MAX_ITEM_CHARS] for i in (raw.get("items") or [])][:MAX_ITEMS]
    return {"template": template, "title": title, "items": items}


def _stub(project: Project) -> None:
    for scene in project.scenes:
        key = scene.section_key
        if key in ("hook", "closing"):
            scene.display = {"template": "title_card",
                             "title": (project.title or "解説")[:MAX_TITLE],
                             "items": ["ダミー補足(ローカル)"]}
        elif key in ("thesis", "lesson"):
            scene.display = {"template": "bullets", "title": "ポイント",
                             "items": ["要点その1", "要点その2", "要点その3"]}
        elif key == "background":
            scene.display = {"template": "compare_cards", "title": "分類",
                             "items": ["カテゴリA", "カテゴリB", "カテゴリC"]}
        else:
            scene.display = {"template": "keyword_pop", "title": "キーワード",
                             "items": []}


def plan(project: Project) -> None:
    """全シーンに表示指定を付与する。"""
    if settings.is_local:
        _stub(project)
        project.log("演出プラン生成(ローカル)")
        return
    meter = CostMeter(project)
    meter.charge("gemini_call", 1, "storyboard")
    scenes_json = json.dumps(
        [{"no": s.no, "section": s.section_key, "narration": s.narration}
         for s in project.scenes],
        ensure_ascii=False,
    )
    data, _ = llm.generate_json(prompts.DISPLAY_PLAN.format(scenes=scenes_json))
    by_no = {int(e.get("no", -1)): e for e in data.get("scenes", [])}
    for scene in project.scenes:
        scene.display = _sanitize(by_no.get(scene.no, {"template": "none"}))
    planned = sum(1 for s in project.scenes
                  if s.display.get("template") not in ("none", ""))
    project.log("演出プランを生成", note=f"{planned}/{len(project.scenes)}シーンに図解表示")
