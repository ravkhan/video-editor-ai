"""Full ~3 min Uhud vlog for Instagram Reels (1080x1920), with speed-ramped walking."""
import subprocess, os

SRC = "/home/user/src"
OUT = f"{SRC}/render4"
os.makedirs(OUT, exist_ok=True)
W, H, FPS = 1080, 1920, 30
T = 0.4
GRADE = "eq=contrast=1.06:saturation=1.18:gamma=0.98,unsharp=5:5:0.4"

# chapter: (kicker, transition, [ (src, start, end, speed, lines) ])
CH = [
    ("", None, [
        ("IMG_4837", 1.4, 6.3, 1, [(1.5, 2.7, "Ассаламу алейкум"), (2.8, 4.7, "ва рахмату-Ллахи ва баракатух"),
                                   (4.7, 6.2, "Вот гора Ухуд")]),
    ]),
    ("ДОРОГА К ГОРЕ", "smoothleft", [
        ("IMG_4777", 0.0, 21.1, 5, []),
    ]),
    ("ПОДЪЁМ", "zoomin", [
        ("IMG_4779", 0.0, 5.3, 4, []),
        ("IMG_4779", 5.3, 8.7, 1, [(5.5, 6.7, "Что это?"), (7.7, 8.5, "Порода такая")]),
        ("IMG_4779", 8.7, 16.9, 4, []),
        ("IMG_4779", 16.9, 22.4, 1, [(17.2, 19.3, "Так, поднялись мы"), (21.8, 22.3, "Пошёл")]),
        ("IMG_4779", 22.4, 38.1, 4, []),
        ("IMG_4779", 38.1, 41.3, 1, [(38.3, 38.8, "Вот она"), (40.4, 41.1, "Гора Ухуд")]),
        ("IMG_4779", 41.3, 108.8, 8, []),
        ("IMG_4780", 15.0, 105.0, 10, []),
    ]),
    ("ВЕРШИНА", "fadewhite", [
        ("IMG_4836", 0.6, 28.1, 1, [
            (0.8, 4.8, "Альхамдулиллях, поднялся я"), (5.8, 7.2, "На горе Ухуд"),
            (9.7, 10.8, "Вот отсюда вид такой"), (12.2, 14.9, "Вот по этой дороге я сюда поднялся"),
            (14.9, 16.5, "Мне сейчас нужно будет спускаться"),
            (16.8, 21.0, "А спускаться, мне кажется, порой будет тяжелее, чем подниматься"),
            (22.5, 23.3, "Ну, ин шаа Аллах"), (24.1, 25.3, "Просим Аллаха помочь нам"),
            (25.3, 27.9, "Как помог подняться, так же спуститься")]),
        ("IMG_4837", 6.3, 14.95, 1, [(6.4, 9.0, "Гора Ухуд, как сказал посланник Аллаха,"),
                                     (12.0, 13.6, "Гора Ухуд любит нас"), (13.7, 14.9, "и мы любим её")]),
    ]),
    ("СПУСК", "slideup", [
        ("IMG_4838", 0.6, 7.8, 1, [(0.8, 4.3, "Вот, бисмиллях, сейчас будем спускаться"),
                                   (4.8, 7.6, "Туда я не стал подниматься, потому что чуть рискованно")]),
        ("IMG_4838", 7.8, 13.3, 4, []),
        ("IMG_4838", 13.3, 24.9, 1, [(13.6, 15.1, "Это, можно сказать, первый раз"),
                                     (16.4, 18.6, "В Дагестане я особо по горам не ходил"),
                                     (19.0, 20.5, "Особо и не любил, но…"),
                                     (21.4, 22.7, "Это Медина, это Ухуд"), (23.3, 24.7, "Это не Дагестан")]),
        ("IMG_4838", 24.9, 58.3, 8, []),
        ("IMG_4838", 58.3, 66.7, 1, [(58.5, 60.4, "Спускаться тяжелее, мне кажется"),
                                     (60.4, 63.2, "Почему? Потому что можешь поскользнуться"),
                                     (64.1, 66.5, "Камешек может быть под ногой")]),
        ("IMG_4838", 66.7, 88.0, 6, []),
        ("IMG_4840", 2.1, 14.0, 1, [(2.3, 4.4, "Можно не прямо вот так,"),
                                    (4.5, 6.9, "а нужно вот так — в эту сторону"),
                                    (8.5, 9.9, "Обычно в горах дороги так делают"),
                                    (11.3, 13.8, "Также можно зигзагами спускаться, чтобы проще было")]),
        ("IMG_4840", 14.0, 104.2, 10, []),
    ]),
    ("ДОРОГА ДОМОЙ", "fadewhite", [
        ("IMG_4846", 0.0, 21.7, 4, []),
    ]),
    ("ХОЛОДНАЯ ВОДА", "smoothleft", [
        ("IMG_4782", 0.0, 7.0, 3, []),
        ("IMG_4782", 7.0, 16.0, 1, [(7.1, 11.0, "Вот такие аппараты стоят"), (11.0, 15.9, "в Медине с холодной водой")]),
        ("IMG_4782", 16.0, 18.5, 3, []),
        ("IMG_4782", 18.5, 28.6, 1, [(18.7, 20.9, "Здесь холодная вода,"),
                                     (21.4, 25.6, "а здесь не холодная — тёплая вода бывает"),
                                     (25.7, 28.6, "Сколько же награды получается, если такое поставить")]),
        ("IMG_4782", 28.6, 40.0, 4, []),
        ("IMG_4782", 40.0, 47.0, 1, [(40.1, 42.4, "Сейчас я пить хочу"), (44.0, 46.6, "ин шаа Аллах, попью здесь воды")]),
        ("IMG_4782", 47.0, 52.7, 2, []),
    ]),
]

MUTE = {"IMG_4780"}  # contains Quran recitation: never speed it up audibly


def run(cmd):
    subprocess.run(cmd, check=True)


def atempo(sp):
    parts = []
    while sp > 2.0:
        parts.append("atempo=2.0"); sp /= 2.0
    parts.append(f"atempo={sp:.4f}")
    return ",".join(parts)


# 1. render sub-segments, concat per chapter
chap_files, chap_durs, sub_layout = [], [], []
for ci, (_, _, subs) in enumerate(CH):
    parts, t_in = [], 0.0
    layout = []
    for si, (src, s, e, sp, lines) in enumerate(subs):
        d = e - s
        od = d / sp
        out = f"{OUT}/c{ci:02d}_{si:02d}.mp4"
        vf = f"setpts=(PTS-STARTPTS)/{sp},fps={FPS},scale={W}:{H},setsar=1,{GRADE}"
        if sp == 1:
            af = "highpass=f=80,acompressor=threshold=-20dB:ratio=3:attack=5:release=100"
        elif src in MUTE:
            af = "volume=0"
        else:
            af = f"{atempo(sp)},volume=0.35"
        if not os.path.exists(out):
            run(["ffmpeg", "-v", "error", "-y", "-ss", str(s), "-t", str(d), "-i", f"{SRC}/{src}.MOV",
                 "-map", "0:v:0", "-map", "0:a:0", "-vf", vf, "-af", f"{af},aresample=48000,asetpts=PTS-STARTPTS",
                 "-ac", "2", "-t", f"{od:.3f}", "-c:v", "libx264", "-preset", "fast", "-crf", "16",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out])
        real = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                              "-of", "csv=p=0", out]).decode())
        layout.append((t_in, src, s, sp, lines, real))
        parts.append(out)
        t_in += real
        print(f"ch{ci} {src} {s}-{e} x{sp} -> {real:.2f}s", flush=True)
    lst = f"{OUT}/c{ci:02d}.txt"
    open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
    cf = f"{OUT}/chap{ci:02d}.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
         "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", cf])
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                         "-of", "csv=p=0", cf]).decode())
    chap_files.append(cf); chap_durs.append(dur); sub_layout.append(layout)

# 2. chapter offsets with crossfades
offs, t = [], 0.0
for i, d in enumerate(chap_durs):
    offs.append(t)
    t += d - (T if i < len(chap_durs) - 1 else 0)
total = t
print("TOTAL", round(total, 2), flush=True)


# 3. subtitles
def ts(x):
    x = max(0, x)
    return f"{int(x // 3600)}:{int(x % 3600 // 60):02d}:{x % 60:05.2f}"


HL = "&H0033CCFF&"
ass = [
    "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    "Style: Sub,Inter Display Black,84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,6,3,2,90,90,560,1",
    "Style: Title,Inter Display Black,96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,2,0,1,7,4,8,60,60,300,1",
    "Style: Kicker,Inter Display ExtraBold,46,&H0033CCFF,&H0033CCFF,&H00000000,&H64000000,1,0,0,0,100,100,8,0,1,4,2,8,60,60,250,1",
    "Style: Chapter,Inter Display Black,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,6,0,1,6,3,8,60,60,260,1",
    "Style: Speed,Inter Display ExtraBold,44,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,2,0,1,4,2,9,60,60,160,1",
    "", "[Events]",
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
]


def chunks(words, n=3):
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= n or w[2].endswith((",", ".", "?", "…", "!")):
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out


for ci, layout in enumerate(sub_layout):
    for (t_in, src, s, sp, lines, real) in layout:
        base = offs[ci] + t_in
        if sp != 1:
            ass.append(f"Dialogue: 2,{ts(base + T + 0.1)},{ts(base + real - T - 0.05)},Speed,,0,0,0,,{{\\fad(150,150)}}»» ×{sp}")
            continue
        for (ls, le, text) in lines:
            toks = text.split()
            weights = [len(w) + 2 for w in toks]
            tot = sum(weights); t0 = ls; words = []
            for w, wt in zip(toks, weights):
                dur = (le - ls) * wt / tot
                words.append((t0, t0 + dur, w)); t0 += dur
            for ch in chunks(words):
                for k, (ws, we, w) in enumerate(ch):
                    parts = []
                    for j, (_, _, ww) in enumerate(ch):
                        parts.append(r"{\c" + HL + r"\fscx108\fscy108}" + ww + r"{\c&H00FFFFFF&\fscx100\fscy100}" if j == k else ww)
                    pop = "" if k else r"{\t(0,90,\fscx106\fscy106)\t(90,180,\fscx100\fscy100)}"
                    ass.append(f"Dialogue: 0,{ts(base + ws - s)},{ts(base + we - s)},Sub,,0,0,0,,{pop}{' '.join(parts)}")

for ci, (kick, _, _) in enumerate(CH):
    if kick:
        ass.append(f"Dialogue: 1,{ts(offs[ci] + 0.3)},{ts(offs[ci] + 2.8)},Chapter,,0,0,0,,{{\\fad(250,300)}}{kick}")
ass.append(f"Dialogue: 1,{ts(0.1)},{ts(4.6)},Kicker,,0,0,0,,{{\\fad(200,250)}}МЕДИНА · ПОЛНЫЙ ВЛОГ")
ass.append(f"Dialogue: 1,{ts(0.2)},{ts(4.6)},Title,,0,0,0,,{{\\fad(200,250)}}Восхождение\\Nна гору Ухуд")
ass.append(f"Dialogue: 1,{ts(total - 4.0)},{ts(total)},Kicker,,0,0,0,,{{\\fad(300,0)}}А ТЫ БЫЛ НА УХУДЕ?")
ass.append(f"Dialogue: 1,{ts(total - 3.9)},{ts(total)},Title,,0,0,0,,{{\\fad(300,0)}}Пиши\\Nв комментариях")
open(f"{OUT}/subs.ass", "w").write("\n".join(ass) + "\n")

# 4. final: crossfades + subtitles, phone-friendly encode (~4 Mbps, H.264 High@4.0)
inputs, fc = [], []
for f in chap_files:
    inputs += ["-i", f]
vp, ap = "[0:v]", "[0:a]"
for i in range(1, len(chap_files)):
    tr = CH[i][1] or "fade"
    fc.append(f"{vp}[{i}:v]xfade=transition={tr}:duration={T}:offset={offs[i]:.3f}[v{i}]")
    fc.append(f"{ap}[{i}:a]acrossfade=d={T}[a{i}]")
    vp, ap = f"[v{i}]", f"[a{i}]"
fc.append(f"{vp}subtitles={OUT}/subs.ass,fade=t=out:st={total-0.6:.2f}:d=0.6[vout]")
fc.append(f"{ap}loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={total-0.6:.2f}:d=0.6[aout]")
run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc),
     "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "slow",
     "-b:v", "4000k", "-maxrate", "5000k", "-bufsize", "10000k", "-profile:v", "high", "-level:v", "4.0",
     "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", "60", "-tag:v", "avc1",
     "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
     "-brand", "mp42", "-movflags", "+faststart", f"{OUT}/uhud_full_vlog.mp4"])
print("done", flush=True)
