"""映像構成(要件5.4)。台本をシーン分割し、種別・秒数・生成指示文を付与する。

高コストなAI動画は hook / turning_point の先頭シーンに限定する(追補2章)。
"""

from __future__ import annotations

from app.models import Project, Scene

CHARS_PER_SEC = 6.5  # 日本語ナレーションの読み上げ速度目安
MAX_SCENE_CHARS = 160
AI_VIDEO_SECTIONS = {"hook", "turning_point"}
DIAGRAM_SECTIONS = {"thesis", "lesson"}


def _split_narration(text: str, max_chars: int = MAX_SCENE_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text] if text else []
    chunks, buf = [], ""
    for part in text.replace("!", "!。").replace("?", "?。").split("。"):
        part = part.strip()
        if not part:
            continue
        candidate = f"{buf}{part}。"
        if len(candidate) > max_chars and buf:
            chunks.append(buf)
            buf = f"{part}。"
        else:
            buf = candidate
    if buf:
        chunks.append(buf)
    return chunks


# 画像プロンプトは英語のみ・題材情報なし。
# 日本語テーマや「比較/ガイド」等の語を渡すと、モデルが疑似日本語のタイトルや
# ラベル・偽ロゴを描いてしまう(試験動画1本目の教訓)。絵は抽象的な雰囲気に徹し、
# 情報はテロップと字幕(プログラム描画)が担う。
_MOODS = {
    "hook": "dramatic dark tech atmosphere, light rays breaking through, anticipation",
    "thesis": "orderly floating translucent glass panels, calm clarity",
    "background": "soft dawn gradient over a minimal horizon, sense of foundations",
    "progression": "flowing particle streams gradually gaining momentum",
    "turning_point": "sharp contrast of light and shadow, one bright path turning",
    "result": "balanced geometry settling into place, quiet resolution",
    "lesson": "warm rising light, gentle upward motion, sense of insight",
    "closing": "calm night gradient, soft glow, peaceful ending",
}

_PROHIBIT = ("Strictly no text, no letters, no numbers, no words, no captions, "
             "no labels, no logos, no icons, no emblems, no charts, no user "
             "interfaces, no keyboards, no screens with content, no human faces.")


def _visual_prompt(project: Project, section_key: str, typ: str) -> str:
    mood = _MOODS.get(section_key, "calm abstract technology atmosphere")
    if typ == "diagram":
        style = ("Minimal abstract geometric composition: translucent panels, "
                 "glowing nodes and connecting lines suggesting structure, "
                 "floating in soft space")
    elif typ == "ai_video":
        # マスコット参照生成と両立する表現(抽象縛りにしない)
        style = ("Cinematic shot, slow camera dolly, volumetric light, "
                 "soft depth of field, high production value")
    else:
        style = ("Abstract cinematic still, soft gradients, bokeh light shapes, "
                 "depth of field")
    return (f"{style}. {mood}. 16:9, muted professional color palette, "
            f"high production value. {_PROHIBIT}")


def refresh_visual_prompts(project: Project) -> None:
    """保存済みシーンの生成指示文を現行テンプレートで引き直す(素材の作り直し用)。"""
    for scene in project.scenes:
        scene.visual_prompt = _visual_prompt(project, scene.section_key, scene.type)


def build(project: Project) -> None:
    scenes: list[Scene] = []
    no = 1
    for sec in project.script:
        for i, chunk in enumerate(_split_narration(sec.narration)):
            if sec.key in AI_VIDEO_SECTIONS and i == 0:
                typ = "ai_video"
            elif sec.key in DIAGRAM_SECTIONS:
                typ = "diagram"
            else:
                typ = "still_motion"
            scenes.append(
                Scene(
                    no=no, section_key=sec.key, type=typ,
                    duration_sec=max(3.0, round(len(chunk) / CHARS_PER_SEC, 1)),
                    narration=chunk, speaker=sec.speaker,
                    visual_prompt=_visual_prompt(project, sec.key, typ),
                )
            )
            no += 1
    project.scenes = scenes
    total = round(sum(s.duration_sec for s in scenes), 1)
    project.log("映像構成を作成", note=f"{len(scenes)}シーン / 想定{total}秒")
