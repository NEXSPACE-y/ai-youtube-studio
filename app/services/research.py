"""リサーチ(要件5.2)。2段階方式: 計画(サブトピック分解) → サブトピックごとの深掘り検索。

- 事実/推測/創作を区別し、情報源を必ず記録する
- 一般論・宣伝表現を排し、数値・制約・弱点など意思決定に効く具体情報を集める
- 比較対象には強み/弱みを対称に要求する(LLM自己選好バイアス対策)
"""

from __future__ import annotations

from app import llm, prompts
from app.config import settings
from app.costs import CostMeter
from app.models import Project, ResearchItem, Source

MAX_SUBTOPICS = 8


def _stub(project: Project) -> list[ResearchItem]:
    src = [Source(url="https://example.com/dummy", title="ダミー情報源(ローカルモード)")]
    return [
        ResearchItem(topic="基本事実", text=f"{project.theme} に関する確認済みの基本事実(ダミー)。",
                     kind="fact", sources=src),
        ResearchItem(topic="原因分析", text=f"{project.theme} の原因は複数説あり、断定できない(ダミー)。",
                     kind="inference", sources=src),
        ResearchItem(topic="演出", text="冒頭は当時の状況の再現映像から入る演出とする(ダミー)。",
                     kind="creative"),
    ]


def run(project: Project) -> None:
    meter = CostMeter(project)
    if settings.is_local:
        project.research = _stub(project)
        project.log("リサーチ実行", note=f"{len(project.research)}件(ローカル)")
        return

    # 第1段階: リサーチ計画(サブトピック分解)
    meter.charge("gemini_call", 1, "research")
    plan, _ = llm.generate_json(prompts.RESEARCH_PLAN.format(
        theme=project.theme, title=project.title,
        unique_angle=project.uniqueness_note))
    subtopics = plan.get("subtopics", [])[:MAX_SUBTOPICS]

    # 第2段階: サブトピックごとに検索付き深掘り
    items: list[ResearchItem] = []
    grounding: list[Source] = []
    for st in subtopics:
        topic = st.get("topic", "")
        meter.charge("gemini_call", 1, "research")
        data, gsrc = llm.generate_json(
            prompts.RESEARCH_DEEP.format(
                theme=project.theme, topic=topic, focus=st.get("focus", "")),
            grounding=True,
        )
        for raw in data.get("items", []):
            items.append(ResearchItem(
                topic=topic,
                text=raw.get("text", ""),
                kind=raw.get("kind", "inference"),
                sources=[Source(url=s.get("url", ""), title=s.get("title", ""))
                         for s in raw.get("sources", [])],
            ))
        grounding.extend(gsrc)

    # グラウンディングで実際に参照されたURLは、モデル申告と別に必ず保全する
    if grounding:
        seen: set[str] = set()
        uniq = [s for s in grounding if s.url and not (s.url in seen or seen.add(s.url))]
        items.append(ResearchItem(
            topic="自動記録", kind="fact",
            text="(自動記録)検索グラウンディングが参照したページ一覧。",
            sources=uniq))

    project.research = items
    project.log("リサーチ実行",
                note=f"{len(subtopics)}サブトピック / {len(items)}件")
