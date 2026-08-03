from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Source(BaseModel):
    url: str = ""
    title: str = ""
    note: str = ""
    accessed_at: str = Field(default_factory=now_iso)


class ResearchItem(BaseModel):
    text: str
    kind: str = "fact"  # fact(事実) | inference(推測) | creative(演出・創作)
    topic: str = ""  # 深掘りリサーチのサブトピック名
    sources: list[Source] = Field(default_factory=list)
    verified_by_human: bool = False


class ScriptSection(BaseModel):
    key: str  # hook / thesis / background / progression / turning_point / result / lesson / closing
    name: str
    narration: str = ""
    on_screen_text: str = ""
    visual_direction: str = ""
    speaker: str = ""  # 話者(CAST_JSONのキャラ名。空=既定ナレーター)


class Scene(BaseModel):
    no: int
    section_key: str = ""
    type: str = "still_motion"  # ai_video | still_motion | diagram | text | genga_interp
    duration_sec: float = 5.0
    narration: str = ""
    visual_prompt: str = ""
    audio_duration_sec: float = 0.0  # TTS後に確定
    speaker: str = ""  # 話者(キャラ毎の固定声で読み上げる)
    # 絵コンテ駆動(docs/09)。type=genga_interp のカットで使う
    # cast は「画面に映るキャラ」で speaker(喋るキャラ)とは別概念。
    # ツヅリのように映るが喋らないキャラがいるため分けている(docs/07)
    cast: list[str] = Field(default_factory=list)
    acting: str = ""  # 演技指示(日本語)「栞が顔を上げて手を振る」
    camera: str = ""  # カメラワーク「slow push-in」など
    keyframe_a_prompt: str = ""  # 原画Aの生成指示
    keyframe_b_prompt: str = ""  # 原画Bの生成指示(原画Aからの差分として書く)
    # 図解モーションエンジンの表示指定(演出プランナーが生成)
    # 例: {"template": "bullets", "title": "...", "items": ["...", "..."]}
    display: dict = Field(default_factory=dict)


class Asset(BaseModel):
    id: str = Field(default_factory=new_id)
    stage: str = ""
    scene_no: Optional[int] = None
    version: int = 1
    kind: str = ""  # image | video | narration | bgm | subtitle | thumbnail | render | preview_html
    path: str = ""  # ローカル相対パス or gs:// URI
    cost_jpy: float = 0.0
    adopted: bool = True
    created_at: str = Field(default_factory=now_iso)
    meta: dict[str, Any] = Field(default_factory=dict)


class CostEntry(BaseModel):
    service: str
    quantity: float
    unit_jpy: float
    cost_jpy: float
    stage: str
    at: str = Field(default_factory=now_iso)


class ApprovalRecord(BaseModel):
    stage: str  # どの承認か(台本確認 / 品質確認 / 公開承認 など)
    decision: str  # approved | rejected
    approver: str
    reason: str = ""
    checklist: dict[str, bool] = Field(default_factory=dict)
    rollback_to: str = ""
    decided_at: str = Field(default_factory=now_iso)


class RollbackRecord(BaseModel):
    from_status: str
    to_status: str
    reason: str
    fix_target: str = ""
    reusable_assets: list[str] = Field(default_factory=list)
    invalidated_assets: list[str] = Field(default_factory=list)
    at: str = Field(default_factory=now_iso)


class HistoryEntry(BaseModel):
    action: str
    actor: str = "system"
    ok: bool = True
    note: str = ""
    at: str = Field(default_factory=now_iso)


class PublishInfo(BaseModel):
    title: str = ""
    description: str = ""
    chapters: str = ""
    hashtags: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    ai_disclosure: bool = True
    ai_disclosure_note: str = ""
    sources_text: str = ""
    youtube_video_id: str = ""


class Project(BaseModel):
    id: str = Field(default_factory=new_id)
    title: str = ""
    theme: str = ""
    audience: str = ""
    purpose: str = ""
    status: str = "企画中"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    cost_limit_jpy: float = 0.0
    cost_limit_override_approved: bool = False
    cost_stop_reason: str = ""  # 上限停止中の理由(空なら停止していない)

    planning: dict[str, Any] = Field(default_factory=dict)
    research: list[ResearchItem] = Field(default_factory=list)
    script: list[ScriptSection] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    costs: list[CostEntry] = Field(default_factory=list)
    approvals: list[ApprovalRecord] = Field(default_factory=list)
    rollbacks: list[RollbackRecord] = Field(default_factory=list)
    history: list[HistoryEntry] = Field(default_factory=list)
    publish_info: PublishInfo = Field(default_factory=PublishInfo)
    uniqueness_note: str = ""  # この動画の独自要素(要件6.4)

    def log(self, action: str, actor: str = "system", ok: bool = True, note: str = "") -> None:
        self.history.append(HistoryEntry(action=action, actor=actor, ok=ok, note=note))
        self.updated_at = now_iso()

    def total_cost(self) -> float:
        return round(float(sum(c.cost_jpy for c in self.costs)), 1)

    def next_asset_version(self, stage: str, scene_no: Optional[int], kind: str) -> int:
        versions = [
            a.version
            for a in self.assets
            if a.stage == stage and a.scene_no == scene_no and a.kind == kind
        ]
        return (max(versions) + 1) if versions else 1
