"""投稿準備(要件5.7)。タイトル・概要欄・チャプター・タグ・AI申告・情報源を生成。"""

from __future__ import annotations

from app import llm, prompts
from app.config import settings
from app.costs import CostMeter
from app.models import Project, PublishInfo
from app.services import subtitles

AI_DISCLOSURE_TEXT = (
    "本動画の映像・画像・ナレーション音声・BGMの一部または全部は、"
    "生成AI(Google Veo / Imagen / Cloud Text-to-Speech / Lyria)を使用して制作しています。"
    "再現映像はイメージであり、実際の記録映像ではありません。"
)


def _fmt_chapter(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def _chapters(project: Project) -> str:
    lines = []
    seen_sections = set()
    section_names = {s.key: s.name for s in project.script}
    for scene, start in subtitles.scene_start_times(project.scenes):
        if scene.section_key not in seen_sections:
            seen_sections.add(scene.section_key)
            name = section_names.get(scene.section_key, scene.section_key)
            lines.append(f"{_fmt_chapter(start)} {name}")
    return "\n".join(lines)


def _sources_text(project: Project) -> str:
    lines = []
    for item in project.research:
        for src in item.sources:
            if src.url and src.url not in "\n".join(lines):
                title = src.title or src.url
                lines.append(f"- {title} {src.url}")
    return "\n".join(dict.fromkeys(lines))  # 順序維持で重複除去


def run(project: Project) -> None:
    meter = CostMeter(project)
    chapters = _chapters(project)
    sources = _sources_text(project)

    if settings.is_local:
        title = project.title
        body = (f"{project.planning.get('theme_summary', project.theme)}\n\n"
                f"この動画では {project.theme} の経緯と原因構造を解説します。")
        hashtags = ["#解説", "#ドキュメンタリー", "#教訓"]
        tags = [project.theme, "解説", "ドキュメンタリー", "失敗事例", "教訓"]
    else:
        meter.charge("gemini_call", 1, "publish_prep")
        summary = " / ".join(s.narration[:60] for s in project.script[:3])
        data, _ = llm.generate_json(prompts.PUBLISH.format(
            title=project.title, theme=project.theme, summary=summary))
        title = data.get("title", project.title)
        body = data.get("description_body", "")
        hashtags = data.get("hashtags", [])
        tags = data.get("tags", [])

    description = "\n\n".join(filter(None, [
        body,
        f"■ チャプター\n{chapters}" if chapters else "",
        f"■ 参考資料・情報源\n{sources}" if sources else "",
        f"■ AI生成コンテンツについて\n{AI_DISCLOSURE_TEXT}",
        " ".join(hashtags),
    ]))

    project.publish_info = PublishInfo(
        title=title, description=description, chapters=chapters,
        hashtags=hashtags, tags=tags,
        ai_disclosure=True, ai_disclosure_note=AI_DISCLOSURE_TEXT,
        sources_text=sources,
        youtube_video_id=project.publish_info.youtube_video_id,
    )
    project.log("投稿情報を生成")
