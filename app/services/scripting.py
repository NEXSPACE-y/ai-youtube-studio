"""台本作成(要件5.3)。8セクション構成・ナレーション/画面表示/映像指示を分離管理。"""

from __future__ import annotations

import json

from app import llm, prompts
from app.config import settings
from app.costs import CostMeter
from app.models import Project, ScriptSection

SECTIONS: list[tuple[str, str]] = [
    ("hook", "冒頭フック"),
    ("thesis", "テーマと結論"),
    ("background", "背景説明"),
    ("progression", "問題の進行"),
    ("turning_point", "転換点"),
    ("result", "結果"),
    ("lesson", "解説と教訓"),
    ("closing", "締め"),
]
_NAMES = dict(SECTIONS)


def _stub(project: Project) -> list[ScriptSection]:
    facts = "。".join(i.text for i in project.research if i.kind == "fact") or project.theme
    texts = {
        "hook": f"もしあなたが当事者だったら、この結末を避けられたでしょうか。今回は{project.theme}を追います。",
        "thesis": f"この動画では、{project.theme}の経緯をたどり、なぜそれが起きたのかを構造から解説します。",
        "background": f"まず背景から見ていきましょう。{facts}",
        "progression": "状況は少しずつ、しかし確実に悪化していきました。関係者はその兆候に気づけなかったのです。",
        "turning_point": "そして、決定的な転換点が訪れます。",
        "result": "結果として、この出来事は大きな影響を残すことになりました。",
        "lesson": "ここから学べる教訓は、原因は一つではなく構造にあるということです。同様の事例と比較すると共通点が見えてきます。",
        "closing": "ご視聴ありがとうございました。次回も事実から学べる事例を解説します。",
    }
    return [
        ScriptSection(
            key=k, name=_NAMES[k], narration=texts[k],
            on_screen_text=_NAMES[k],
            visual_direction="再現映像" if k in ("hook", "turning_point") else "図解・資料映像",
        )
        for k, _ in SECTIONS
    ]


def run(project: Project, feedback: str = "") -> None:
    meter = CostMeter(project)
    if settings.is_local:
        sections = _stub(project)
    else:
        meter.charge("gemini_call", 1, "script")
        research_json = json.dumps(
            [i.model_dump() for i in project.research], ensure_ascii=False
        )
        prompt = prompts.SCRIPT.format(
            theme=project.theme, title=project.title, audience=project.audience,
            unique_angle=project.uniqueness_note, research=research_json,
        )
        if feedback.strip():
            prompt += (
                "\n\n重要: 前回の台本は以下の理由で差し戻されました。"
                "この指摘を必ず修正に反映してください。\n"
                f"差し戻し理由: {feedback}"
            )
        data, _ = llm.generate_json(prompt)
        by_key = {s.get("key"): s for s in data.get("sections", [])}
        sections = []
        for key, name in SECTIONS:
            raw = by_key.get(key, {})
            sections.append(
                ScriptSection(
                    key=key, name=name,
                    narration=raw.get("narration", ""),
                    on_screen_text=raw.get("on_screen_text", ""),
                    visual_direction=raw.get("visual_direction", ""),
                )
            )
    project.script = sections
    total = sum(len(s.narration) for s in sections)
    project.log("台本を生成", note=f"ナレーション合計{total}字")
