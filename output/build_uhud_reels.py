"""Build a ~1 min Instagram Reel (1080x1920) from the Uhud mini-vlog clips."""
import json, subprocess, os

SRC = "/home/user/src"
OUT = f"{SRC}/render"
os.makedirs(OUT, exist_ok=True)
W, H, FPS = 1080, 1920, 30
T = 0.4  # transition length

med = json.load(open(f"{SRC}/transcript_med.json"))

# (source, start, end, kind, transition-into-this-clip, subtitle lines)
# subtitle lines: list of (src_start, src_end, corrected text)
CLIPS = [
    ("IMG_4837", 1.4, 6.3, "talk", None, [
        (1.5, 2.7, "Ассаламу алейкум"),
        (2.8, 4.7, "ва рахмату-Ллахи ва баракатух"),
        (4.7, 6.2, "Вот гора Ухуд"),
    ]),
    ("IMG_4837", 6.3, 14.95, "talk", "fade", [
        (6.4, 9.0, "Гора Ухуд, как сказал посланник Аллаха,"),
        (12.0, 13.6, "Гора Ухуд любит нас"),
        (13.7, 14.9, "и мы любим её"),
    ]),
    ("IMG_4836", 9.4, 15.0, "talk", "zoomin", [
        (9.7, 10.9, "Вот отсюда вид такой"),
        (12.2, 14.9, "Вот по этой дороге я сюда поднялся"),
    ]),
    ("IMG_4779", 66.0, 69.0, "broll", "smoothleft", []),
    ("IMG_4780", 60.0, 62.8, "broll", "smoothleft", []),
    ("IMG_4777", 9.0, 11.8, "broll", "smoothleft", []),
    ("IMG_4838", 13.4, 24.9, "talk", "fadewhite", [
        (13.6, 15.1, "Это, можно сказать, первый раз"),
        (16.4, 18.6, "В Дагестане я особо по горам не ходил"),
        (19.0, 20.5, "Особо и не любил, но…"),
        (21.4, 22.7, "Это Медина, это Ухуд"),
        (23.3, 24.7, "Это не Дагестан"),
    ]),
    ("IMG_4838", 58.3, 68.8, "talk", "slideup", [
        (58.5, 60.4, "Спускаться тяжелее, мне кажется"),
        (60.4, 63.2, "Почему? Потому что можешь поскользнуться"),
        (64.1, 66.5, "Камешек может быть под ногой"),
        (67.2, 68.6, "и скользнуть"),
    ]),
    ("IMG_4836", 22.4, 28.1, "talk", "fade", [
        (22.5, 23.3, "Ну, ин шаа Аллах"),
        (24.1, 25.3, "Просим Аллаха помочь нам"),
        (25.3, 28.0, "Как помог подняться, так же спуститься"),
    ]),
    ("IMG_4846", 2.0, 6.5, "broll", "fadewhite", []),
]

GRADE = "eq=contrast=1.06:saturation=1.18:gamma=0.98,unsharp=5:5:0.4"


def run(cmd):
    print(" ".join(cmd)[:200], flush=True)
    subprocess.run(cmd, check=True)


# 1. render each segment to a normalized intermediate
for i, (src, s, e, kind, _, _) in enumerate(CLIPS):
    d = e - s
    out = f"{OUT}/seg{i:02d}.mp4"
    if os.path.exists(out):
        continue
    if kind == "broll":
        # slow push-in for a cinematic feel
        vf = (f"scale={W}:{H},fps={FPS},"
              f"scale='{W}*(1+0.08*t/{d})':-2:eval=frame,crop={W}:{H},{GRADE}")
        af = "volume=0.6"
    else:
        vf = f"scale={W}:{H},fps={FPS},{GRADE}"
        af = "highpass=f=80,acompressor=threshold=-20dB:ratio=3:attack=5:release=100"
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(s), "-t", str(d), "-i", f"{SRC}/{src}.MOV",
         "-map", "0:v:0", "-map", "0:a:0", "-vf", vf, "-af", f"{af},aresample=48000",
         "-ac", "2", "-c:v", "libx264", "-preset", "medium", "-crf", "15", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "256k", out])

# 2. timeline offsets
offsets, t = [], 0.0
for i, c in enumerate(CLIPS):
    offsets.append(t)
    t += (c[2] - c[1]) - (T if i < len(CLIPS) - 1 else 0)
total = offsets[-1] + CLIPS[-1][2] - CLIPS[-1][1]
print("total duration", round(total, 2))

# 3. xfade chain
inputs, fc = [], []
for i in range(len(CLIPS)):
    inputs += ["-i", f"{OUT}/seg{i:02d}.mp4"]
vprev, aprev = "[0:v]", "[0:a]"
for i in range(1, len(CLIPS)):
    off = offsets[i]
    tr = CLIPS[i][4] or "fade"
    fc.append(f"{vprev}[{i}:v]xfade=transition={tr}:duration={T}:offset={off:.3f}[v{i}]")
    fc.append(f"{aprev}[{i}:a]acrossfade=d={T}[a{i}]")
    vprev, aprev = f"[v{i}]", f"[a{i}]"
n = len(CLIPS) - 1


# 4. subtitles (ASS, word-by-word pop highlight)
def ts(x):
    x = max(0, x)
    h = int(x // 3600); m = int(x % 3600 // 60); s = x % 60
    return f"{h}:{m:02d}:{s:05.2f}"


ass = [
    "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    "Style: Sub,Inter Display Black,84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,6,3,2,90,90,560,1",
    "Style: Title,Inter Display Black,96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,2,0,1,7,4,8,60,60,300,1",
    "Style: Kicker,Inter Display ExtraBold,46,&H0033CCFF,&H0033CCFF,&H00000000,&H64000000,1,0,0,0,100,100,8,0,1,4,2,8,60,60,250,1",
    "", "[Events]",
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
]
HL = "&H0033CCFF&"  # golden yellow (BGR)


def chunks(words, n=3):
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= n or w[2].endswith((",", ".", "?", "…", "!")):
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out


for i, (src, s, e, kind, _, lines) in enumerate(CLIPS):
    base = offsets[i] - s
    for (ls, le, text) in lines:
        toks = text.split()
        # spread words over the line duration, weighted by length
        weights = [len(w) + 2 for w in toks]
        tot = sum(weights); t0 = ls
        words = []
        for w, wt in zip(toks, weights):
            dur = (le - ls) * wt / tot
            words.append((t0, t0 + dur, w)); t0 += dur
        for ch in chunks(words):
            cs, ce = ch[0][0], ch[-1][1]
            for k, (ws, we, w) in enumerate(ch):
                parts = []
                for j, (_, _, ww) in enumerate(ch):
                    if j == k:
                        parts.append(r"{\c" + HL + r"\fscx108\fscy108}" + ww + r"{\c&H00FFFFFF&\fscx100\fscy100}")
                    else:
                        parts.append(ww)
                pop = r"{\fad(0,0)}" if k else r"{\t(0,90,\fscx106\fscy106)\t(90,180,\fscx100\fscy100)}"
                end = we
                ass.append(f"Dialogue: 0,{ts(base + ws)},{ts(base + end)},Sub,,0,0,0,,{pop}{' '.join(parts)}")

# titles
ass.append(f"Dialogue: 1,{ts(0.15)},{ts(4.6)},Kicker,,0,0,0,,{{\\fad(250,250)}}МЕДИНА")
ass.append(f"Dialogue: 1,{ts(0.25)},{ts(4.6)},Title,,0,0,0,,{{\\fad(250,250)\\t(0,300,\\fscx100\\fscy100)}}ГОРА УХУД")
b0 = offsets[3]
ass.append(f"Dialogue: 1,{ts(b0 + 0.3)},{ts(offsets[6])},Title,,0,0,0,,{{\\fad(300,300)}}Медина с высоты")
e0 = offsets[-1]
ass.append(f"Dialogue: 1,{ts(e0 + 0.4)},{ts(total)},Kicker,,0,0,0,,{{\\fad(300,0)}}МИНИ-ВЛОГ")
ass.append(f"Dialogue: 1,{ts(e0 + 0.5)},{ts(total)},Title,,0,0,0,,{{\\fad(300,0)}}Восхождение\\Nна Ухуд")
open(f"{OUT}/subs.ass", "w").write("\n".join(ass) + "\n")

fc.append(f"{vprev}subtitles={OUT}/subs.ass,fade=t=out:st={total-0.6:.2f}:d=0.6[vout]")
fc.append(f"{aprev}loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={total-0.6:.2f}:d=0.6[aout]")
run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc),
     "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "slow", "-crf", "20",
     "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "256k",
     "-ar", "48000", "-movflags", "+faststart", f"{OUT}/uhud_reels.mp4"])
print("done")
