from app.subtitles import (
    Word,
    build_cues,
    format_timestamp,
    normalize_segments,
    normalize_style,
    parse_subtitles,
    to_ass,
    to_srt,
    to_vtt,
    wrap_lines,
)

FONTS = ["DejaVu Sans", "Inter"]


def words(text: str, start: float = 0.0, step: float = 0.4) -> list[Word]:
    result = []
    t = start
    for i, w in enumerate(text.split()):
        result.append(Word(t, t + step * 0.9, (" " if i else "") + w))
        t += step
    return result


def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(3661.5) == "01:01:01,500"
    assert format_timestamp(1.2345, ".") == "00:00:01.234" or format_timestamp(1.2345, ".") == "00:00:01.235"


def test_wrap_lines_balances_two_lines():
    text = "Это довольно длинная строка субтитров для проверки переноса"
    wrapped = wrap_lines(text, 42)
    first, second = wrapped.split("\n")
    assert abs(len(first) - len(second)) < 12
    assert wrap_lines("коротко", 42) == "коротко"


def test_build_cues_splits_on_length_and_pause():
    ws = words("один два три четыре пять шесть семь восемь девять десять", step=0.3)
    # a long pause before the last words
    ws += words("после паузы", start=10.0)
    cues = build_cues(ws, max_chars=30)
    assert cues[-1]["text"] == "после паузы"
    assert cues[-1]["start"] == 10.0
    for cue in cues:
        assert len(cue["text"].replace("\n", " ")) <= 30
        assert cue["end"] > cue["start"]
    joined = " ".join(c["text"].replace("\n", " ") for c in cues)
    assert joined.startswith("один два три")


def test_build_cues_closes_on_sentence_end():
    ws = words("Привет всем друзьям. Как дела у вас?", step=0.3)
    cues = build_cues(ws, max_chars=40)
    assert [c["text"] for c in cues] == ["Привет всем друзьям.", "Как дела у вас?"]


def test_build_cues_respects_max_duration():
    ws = words(" ".join(["a"] * 40), step=0.5)
    cues = build_cues(ws, max_chars=500, max_duration=3.0)
    assert all(c["end"] - c["start"] <= 3.0 for c in cues)


def test_srt_vtt_roundtrip():
    segments = normalize_segments([
        {"start": 1.5, "end": 3.0, "text": "Первая строка\nвторая строка"},
        {"start": 0.0, "end": 1.0, "text": "Начало"},
        {"start": 4.0, "end": 5.0, "text": "   "},  # empty: skipped on export
    ])
    assert segments[0]["text"] == "Начало"  # sorted

    srt = to_srt(segments)
    assert "1\n00:00:00,000 --> 00:00:01,000\nНачало" in srt
    assert srt.count("-->") == 2
    parsed = parse_subtitles(srt)
    assert [(s["start"], s["end"], s["text"]) for s in parsed] == [
        (0.0, 1.0, "Начало"),
        (1.5, 3.0, "Первая строка\nвторая строка"),
    ]

    vtt = to_vtt(segments)
    assert vtt.startswith("WEBVTT")
    assert [s["text"] for s in parse_subtitles(vtt)] == ["Начало", "Первая строка\nвторая строка"]


def test_parse_vtt_with_short_timestamps_and_tags():
    content = "WEBVTT\n\nintro\n00:01.000 --> 00:02.500 align:center\n<b>Hello</b> world\n"
    [seg] = parse_subtitles(content)
    assert seg["start"] == 1.0 and seg["end"] == 2.5 and seg["text"] == "Hello world"


def test_normalize_segments_fixes_bad_times():
    [seg] = normalize_segments([{"start": -1, "end": -2, "text": " x "}])
    assert seg["start"] == 0 and seg["end"] == 0.5 and seg["text"] == "x" and seg["id"]


def test_normalize_style_ignores_invalid_values():
    style = normalize_style(
        {"font": "Comic Sans", "color": "red", "size": 9999, "position": "left", "bold": 0, "unknown": 1},
        FONTS,
    )
    assert style["font"] == "DejaVu Sans"
    assert style["color"] == "#FFFFFF"
    assert style["size"] == 200
    assert style["position"] == "bottom"
    assert style["bold"] is False
    assert "unknown" not in style


def test_to_ass_scales_to_video_and_escapes():
    style = normalize_style({"size": 54, "color": "#FF8800", "position": "top", "margin": 100}, FONTS)
    ass = to_ass([{"start": 1, "end": 2.5, "text": "a {b}\nc\\d"}], style, 1280, 720)
    assert "PlayResX: 1280" in ass and "PlayResY: 720" in ass
    style_line = next(line for line in ass.splitlines() if line.startswith("Style:"))
    fields = style_line.split(",")
    assert fields[2] == "36"  # 54 * 720/1080
    assert fields[3] == "&H000088FF"  # BGR order
    assert fields[18] == "8"  # top alignment
    assert fields[21] == "67"  # margin 100 * 720/1080
    assert "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,a (b)\\Nc⧵d" in ass


def test_to_ass_box_style():
    style = normalize_style({"box": True, "box_color": "#000000", "box_opacity": 0.5}, FONTS)
    ass = to_ass([], style, 1920, 1080)
    fields = next(line for line in ass.splitlines() if line.startswith("Style:")).split(",")
    assert fields[15] == "3"
    assert fields[5] == "&H80000000"
