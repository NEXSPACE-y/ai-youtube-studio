"""Gemini呼び出し(クラウドモード専用)。ローカルモードは各serviceのスタブを使う。"""

from __future__ import annotations

import json
import re

from app.config import settings
from app.models import Source


class LLMError(Exception):
    pass


def _repair_truncated(text: str):
    """出力が途中で切れたJSONを、最後の完結した要素まで巻き戻して補修する。"""
    last = text.rfind("}")
    while last > 0:
        frag = text[: last + 1]
        open_braces = frag.count("{") - frag.count("}")
        open_brackets = frag.count("[") - frag.count("]")
        if open_braces >= 0 and open_brackets >= 0:
            try:
                return json.loads(frag + "]" * open_brackets + "}" * open_braces)
            except json.JSONDecodeError:
                pass
        last = text.rfind("}", 0, last)
    return None


def _extract_json(text: str):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if starts and min(starts) > 0:
        text = text[min(starts):]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        repaired = _repair_truncated(text)
        if repaired is not None:
            return repaired
        raise LLMError(f"モデル出力をJSONとして解釈できません: {e}") from e


_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai  # 遅延import

        _client = genai.Client(
            vertexai=True, project=settings.gcp_project, location=settings.gcp_region
        )
    return _client


def generate_json(prompt: str, grounding: bool = False,
                  attempts: int = 2) -> tuple[object, list[Source]]:
    """JSON応答を要求してGeminiを呼ぶ。戻り値は (データ, 検索グラウンディングの参照元)。

    出力切断・JSON崩れに備え、失敗時は attempts 回まで再試行する。
    """
    from google.genai import types  # 遅延import

    client = _get_client()
    if grounding:
        # Google検索グラウンディング使用時はJSONモード併用不可のためテキストから抽出
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            max_output_tokens=32768,
        )
    else:
        config = types.GenerateContentConfig(
            response_mime_type="application/json", max_output_tokens=32768,
        )
    resp = None
    data = None
    last_err: Exception | None = None
    for _ in range(max(1, attempts)):
        resp = client.models.generate_content(
            model=settings.gemini_model, contents=prompt, config=config
        )
        try:
            data = _extract_json(resp.text)
            break
        except LLMError as e:
            last_err = e
    if data is None:
        raise last_err or LLMError("モデル出力を取得できません")

    sources: list[Source] = []
    try:
        gm = resp.candidates[0].grounding_metadata
        for ch, in ((c,) for c in (gm.grounding_chunks or [])):
            if getattr(ch, "web", None):
                sources.append(Source(url=ch.web.uri or "", title=ch.web.title or ""))
    except (AttributeError, IndexError):
        pass
    return data, sources
