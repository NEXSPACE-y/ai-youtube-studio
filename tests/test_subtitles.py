from app.models import Scene
from app.services.subtitles import (align_with_stt, build_srt, fmt_ts,
                                    split_lines)


def test_split_lines_max_length():
    text = "これは長いナレーションのテストです。" * 6
    lines = split_lines(text, max_chars=26)
    assert all(len(l) <= 26 for l in lines)
    assert "".join(lines).replace(" ", "") == text.replace(" ", "")


def test_split_lines_merges_short_fragments():
    # 短い断片同士は1枚の字幕に結合される(読みやすさ優先)
    lines = split_lines("短い文。次の文です。", max_chars=26)
    assert lines == ["短い文。次の文です。"]


def test_split_lines_keeps_long_sentences_separate():
    text = "これは十分に長い一つ目の文章です。こちらも十分に長い二つ目の文章です。"
    lines = split_lines(text, max_chars=26)
    assert len(lines) == 2


def test_fmt_ts():
    assert fmt_ts(0) == "00:00:00,000"
    assert fmt_ts(61.5) == "00:01:01,500"
    assert fmt_ts(3600) == "01:00:00,000"


def test_build_srt_timing_monotonic_and_total():
    scenes = [
        Scene(no=1, narration="最初のシーンです。とても大事な話をします。", audio_duration_sec=6.0),
        Scene(no=2, narration="次のシーンです。", audio_duration_sec=3.0),
    ]
    srt = build_srt(scenes)
    assert "最初のシーンです。" in srt and "次のシーンです。" in srt
    # 最後の字幕の終了時刻 ≒ 総音声長(9秒)
    assert "00:00:09,000" in srt
    # 発話終了前に字幕が消えない(区間が連続している)
    lines = [l for l in srt.splitlines() if "-->" in l]
    for prev, nxt in zip(lines, lines[1:]):
        assert prev.split(" --> ")[1] == nxt.split(" --> ")[0]


def test_build_srt_falls_back_to_estimated_duration():
    scenes = [Scene(no=1, narration="音声未生成のシーン。", duration_sec=4.0)]
    srt = build_srt(scenes)
    assert "00:00:04,000" in srt


def test_align_with_stt():
    lines = ["こんにちは。", "テストです。"]
    words = [("こんにちは", 0.0, 1.0), ("テスト", 1.2, 1.8), ("です", 1.8, 2.2)]
    aligned = align_with_stt(lines, words)
    assert aligned[0] == (0.0, 1.0, "こんにちは。")
    assert aligned[1][0] == 1.2 and aligned[1][2] == "テストです。"
