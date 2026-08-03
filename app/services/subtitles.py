"""字幕生成と同期(要件5.5・追補7章)。

表示テキストは台本を正とし、タイミングは音声実長(TTS結果)から割り付ける。
クラウドモードではSTTの単語タイムスタンプで補正できる構造にしている。
"""

from __future__ import annotations

from app.models import Scene

MAX_LINE_CHARS = 26
_MAJOR = "。!?！？"
_MINOR = "、,・ "


def split_lines(text: str, max_chars: int = MAX_LINE_CHARS) -> list[str]:
    """句読点を優先しつつ max_chars 以下に分割する(一画面の字幕量を抑制)。"""
    text = text.strip()
    if not text:
        return []
    lines: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in _MAJOR and buf.strip():
            lines.append(buf.strip())
            buf = ""
        elif len(buf) >= max_chars:
            # 直近の弱い区切りで折り返す
            cut = max((buf.rfind(c) for c in _MINOR), default=-1)
            if cut > int(max_chars * 0.4):
                lines.append(buf[: cut + 1].strip())
                buf = buf[cut + 1:]
            else:
                lines.append(buf.strip())
                buf = ""
    if buf.strip():
        lines.append(buf.strip())
    lines = [l for l in lines if l]

    # 短い行や孤立した英単語(「Visual Studio」だけの字幕等)は前の行と結合する
    def _lonely(s: str) -> bool:
        return len(s) <= 10 or (len(s) <= 16 and all(ord(c) < 128 for c in s))

    merged: list[str] = []
    for line in lines:
        if merged and (_lonely(line) or _lonely(merged[-1])) \
                and len(merged[-1]) + len(line) <= int(max_chars * 1.3):
            merged[-1] += line
        else:
            merged.append(line)
    return merged


def fmt_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def scene_start_times(scenes: list[Scene]) -> list[tuple[Scene, float]]:
    t = 0.0
    out = []
    for sc in scenes:
        out.append((sc, t))
        t += sc.audio_duration_sec or sc.duration_sec
    return out


def build_srt(scenes: list[Scene]) -> str:
    """シーン音声の実長に比例配分して字幕タイミングを決める。"""
    entries = []
    idx = 1
    cursor = 0.0
    for scene in scenes:
        dur = scene.audio_duration_sec or scene.duration_sec
        lines = split_lines(scene.narration)
        total_chars = sum(len(l) for l in lines)
        t = cursor
        for line in lines:
            d = dur * (len(line) / total_chars) if total_chars else dur
            entries.append(f"{idx}\n{fmt_ts(t)} --> {fmt_ts(t + d)}\n{line}\n")
            idx += 1
            t += d
        cursor += dur
    return "\n".join(entries)


def align_with_stt(lines: list[str], words: list[tuple[str, float, float]]) -> list[tuple[float, float, str]]:
    """STT単語タイムスタンプ(word, start, end)に台本行を貪欲マッチさせる(クラウドQA用)。"""
    ignore = set("。、！？!?，,．.・「」『』()（）　")
    result = []
    wi = 0
    for line in lines:
        # STTの単語列に句読点は含まれないため、句読点を除いた文字数で対応付ける
        target = sum(1 for c in line if not c.isspace() and c not in ignore)
        if wi >= len(words):
            break
        start = words[wi][1]
        consumed = 0
        end = words[wi][2]
        while wi < len(words) and consumed < target:
            consumed += len(words[wi][0])
            end = words[wi][2]
            wi += 1
        result.append((start, end, line))
    return result
