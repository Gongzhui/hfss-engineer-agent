"""逐页生成学术报告 PDF。"""

from collections import defaultdict
from pathlib import Path
import csv
import re

from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch, Rectangle

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "基于AI-Agent的HFSS天线优化方法.pdf"
RUN = ROOT.parent / "eval/exams/uwb_circular_notch/runs/20260819-222718"
if not RUN.is_dir():
    RUN = ROOT.parent / "eval/archive/exams/uwb_circular_notch/runs/20260819-222718"
S11_INIT = RUN / "round-000-s11.csv"
S11_R001 = RUN / "round-001-s11.csv"
S11_R002 = RUN / "round-002-s11.csv"
S11_R003 = RUN / "round-003-s11.csv"
S11_R004 = RUN / "round-004-s11.csv"
S11_R005 = RUN / "round-005-s11.csv"
S11_R006 = RUN / "round-006-s11.csv"
S11_R007 = RUN / "round-007-s11.csv"
S11_R008 = RUN / "round-008-s11.csv"
S11_FINAL = RUN / "s11.csv"

plt.rcParams.update(
    {
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "SimSun"],
        "axes.unicode_minus": False,
        "pdf.fonttype": 42,
    }
)

SLIDE = (13.333, 7.5)


def new_slide():
    fig = plt.figure(figsize=SLIDE, facecolor="white")
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def heading(ax, title: str) -> None:
    ax.text(0.08, 0.90, title, ha="left", va="top", fontsize=22, color="black")


def speech_bubble(ax, x, y, w, h, *, fill, stroke, lw=1.25) -> None:
    aspect = SLIDE[0] / SLIDE[1]
    rx, ry = 0.014, 0.014 * aspect
    kappa = 0.5522847498
    tip_y = y + 0.62 * h
    half = 0.028
    tip = (x - 0.038, tip_y)
    join_t = (x, tip_y + half)
    join_b = (x, tip_y - half)

    verts = [tip]
    codes = [MplPath.MOVETO]
    verts.append(join_b)
    codes.append(MplPath.LINETO)
    verts.append((x, y + ry))
    codes.append(MplPath.LINETO)
    verts.extend([(x, y + ry * (1 - kappa)), (x + rx * (1 - kappa), y), (x + rx, y)])
    codes.extend([MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4])
    verts.append((x + w - rx, y))
    codes.append(MplPath.LINETO)
    verts.extend(
        [(x + w - rx * (1 - kappa), y), (x + w, y + ry * (1 - kappa)), (x + w, y + ry)]
    )
    codes.extend([MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4])
    verts.append((x + w, y + h - ry))
    codes.append(MplPath.LINETO)
    verts.extend(
        [
            (x + w, y + h - ry * (1 - kappa)),
            (x + w - rx * (1 - kappa), y + h),
            (x + w - rx, y + h),
        ]
    )
    codes.extend([MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4])
    verts.append((x + rx, y + h))
    codes.append(MplPath.LINETO)
    verts.extend(
        [(x + rx * (1 - kappa), y + h), (x, y + h - ry * (1 - kappa)), (x, y + h - ry)]
    )
    codes.extend([MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4])
    verts.append(join_t)
    codes.append(MplPath.LINETO)
    verts.append(tip)
    codes.append(MplPath.LINETO)
    verts.append((0, 0))
    codes.append(MplPath.CLOSEPOLY)
    ax.add_patch(
        PathPatch(
            MplPath(verts, codes),
            facecolor=fill,
            edgecolor=stroke,
            lw=lw,
            joinstyle="round",
            capstyle="round",
            zorder=0,
        )
    )


def page_01(pdf: PdfPages) -> None:
    fig, ax = new_slide()
    ax.text(
        0.5,
        0.56,
        "基于AI Agent，MCP及Skill的HFSS天线优化方法（早期demo）",
        ha="center",
        va="center",
        fontsize=24,
        color="black",
    )
    ax.text(0.5, 0.36, "陈彦松", ha="center", va="center", fontsize=16, color="black")
    ax.text(0.5, 0.28, "2026年8月", ha="center", va="center", fontsize=14, color="black")
    pdf.savefig(fig)
    plt.close(fig)


def page_02(pdf: PdfPages) -> None:
    fig, ax = new_slide()
    heading(ax, "目录")
    entries = [
        (3, "Agent、MCP、Skill"),
        (4, "工作过程"),
        (5, "Agent工作实例展示"),
        (6, "天线结构"),
        (7, "初始 S11 与优化目标"),
        (8, "初始天线俯视图"),
        (9, "初始判断"),
        (10, "第一轮扫参"),
        (11, "第一轮结果"),
        (12, "第二轮扫参"),
        (13, "第二轮结果"),
        (14, "修改参数"),
        (15, "第三轮扫参"),
        (16, "第三轮结果"),
        (17, "第四轮扫参"),
        (18, "第四轮结果"),
        (19, "第五轮扫参"),
        (20, "第五轮结果"),
        (21, "修改参数"),
        (22, "第六轮扫参"),
        (23, "第六轮结果"),
        (24, "第七轮扫参"),
        (25, "第七轮结果"),
        (26, "第八轮扫参"),
        (27, "第八轮结果"),
        (28, "交卷"),
        (29, "交卷天线俯视图"),
        (30, "与已有工作的对比"),
    ]
    mid = (len(entries) + 1) // 2
    columns = (entries[:mid], entries[mid:])
    xs = ((0.08, 0.46), (0.54, 0.92))
    for (x0, x1), col in zip(xs, columns):
        y = 0.78
        for num, title in col:
            ax.text(x0, y, title, ha="left", va="center", fontsize=14, color="black")
            ax.text(x1, y, str(num), ha="right", va="center", fontsize=14, color="black")
            y -= 0.048
    pdf.savefig(fig)
    plt.close(fig)


_RUN = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    "0123456789.+-–—−×_%'=/:"
)
_UNITS = ("GHz", "dB", "mm", "MHz")
_BREAK_AFTER = set("，。；、：")


def _disp_w(s: str) -> float:
    return sum(0.55 if ord(c) < 128 else 1.0 for c in s)


def wrap_cn(text: str, width: float = 42) -> str:
    tokens: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] in _RUN:
            j = i + 1
            while j < n and text[j] in _RUN:
                j += 1
            tokens.append(text[i:j])
            i = j
            continue
        tokens.append(text[i])
        i += 1

    glued: list[str] = []
    i, m = 0, len(tokens)
    while i < m:
        tok = tokens[i]
        i += 1
        while True:
            if i + 1 < m and tokens[i] == " " and tokens[i + 1] in _UNITS:
                tok += " " + tokens[i + 1]
                i += 2
                continue
            if (
                i + 3 < m
                and tokens[i] == " "
                and tokens[i + 1] in ("=", "×")
                and tokens[i + 2] == " "
                and tokens[i + 3]
                and tokens[i + 3][0] in _RUN
            ):
                tok += " " + tokens[i + 1] + " " + tokens[i + 3]
                i += 4
                continue
            break
        glued.append(tok)

    def _punct_split(buf: str, min_ratio: float) -> tuple[str, str] | None:
        for k in range(len(buf) - 1, -1, -1):
            if buf[k] in _BREAK_AFTER:
                left, right = buf[: k + 1], buf[k + 1 :].lstrip()
                if _disp_w(left) >= width * min_ratio:
                    return left, right
        return None

    soft = width * 1.08
    lines: list[str] = []
    buf = ""
    for tok in glued:
        trial_w = _disp_w(buf) + _disp_w(tok)
        if not buf or trial_w <= width or tok in _BREAK_AFTER or tok == " ":
            buf += tok
            continue
        if trial_w <= soft and _punct_split(buf, 0.70) is None:
            buf += tok
            continue
        sp = _punct_split(buf, 0.48)
        if sp:
            lines.append(sp[0])
            buf = (sp[1] + tok).lstrip()
        else:
            lines.append(buf.rstrip())
            buf = tok.lstrip()
    if buf.strip():
        lines.append(buf.rstrip())
    return "\n".join(lines)


def page_03(pdf: PdfPages) -> None:
    fig, ax = new_slide()
    heading(ax, "Agent、MCP、Skill")
    rows = [
        (
            "Agent",
            "与传统的ChatGPT类似的“一问一答”类AI不同，Agent能连续调用工具完成任务。"
            "本项目采用 Grok 4.6：Agent负责阅读模型，决定扫参变量、范围，执行扫参，监控进度，修改参数等操作。",
        ),
        (
            "MCP",
            "Agent不能直接操作HFSS，这时需要MCP（Model Context Protocol）充当桥梁，把Agent发出的指令转换成HFSS里实际的操作。"
            "本项目的MCP为自己编写，这些操作包括阅读模型、修改参数、建立并执行扫参、监控进度、导出曲线；"
            "HFSS始终是用户已经打开的那一份。",
        ),
        (
            "Skill",
            "有了工具之后，Agent还需要知道这类天线该怎么调。本项目的Skill为自己编写，说明："
            "根据结构决定扫参变量和范围，用HFSS自带的Optimetrics做联合扫参，根据一簇曲线判断下一轮；"
            "禁止单点试探，也不使用遗传、粒子群等优化算法。Skill不提供某一副天线的尺寸答案。",
        ),
    ]
    y = 0.74
    for name, text in rows:
        ax.text(0.08, y, name, ha="left", va="top", fontsize=18, color="black")
        ax.text(
            0.08,
            y - 0.07,
            wrap_cn(text, 44),
            ha="left",
            va="top",
            fontsize=15,
            color="black",
            linespacing=1.45,
        )
        y -= 0.24
    pdf.savefig(fig)
    plt.close(fig)


def page_04(pdf: PdfPages) -> None:
    fig, ax = new_slide()
    heading(ax, "工作过程")

    labels = ["读模型", "定矩阵", "HFSS 求解", "看一簇 S11", "换组 / 钉点"]
    n = 5
    margin, gap = 0.05, 0.036
    box_w = (1 - 2 * margin - (n - 1) * gap) / n
    box_h = 0.18
    box_y = 0.56
    xs = [margin + i * (box_w + gap) for i in range(n)]
    fill, stroke, on_fill = "#1F4E79", "#1F4E79", "white"

    for i, (x, title) in enumerate(zip(xs, labels), start=1):
        ax.add_patch(
            Rectangle(
                (x, box_y),
                box_w,
                box_h,
                facecolor=fill,
                edgecolor=stroke,
                linewidth=0.8,
                zorder=2,
            )
        )
        ax.text(
            x + box_w / 2,
            box_y + box_h * 0.70,
            str(i),
            ha="center",
            va="center",
            fontsize=15,
            color=on_fill,
            zorder=3,
        )
        ax.text(
            x + box_w / 2,
            box_y + box_h * 0.32,
            title,
            ha="center",
            va="center",
            fontsize=15,
            color=on_fill,
            zorder=3,
        )

    mid_y = box_y + box_h / 2
    for i in range(n - 1):
        ax.annotate(
            "",
            xy=(xs[i + 1], mid_y),
            xytext=(xs[i] + box_w, mid_y),
            arrowprops=dict(arrowstyle="-|>", color=stroke, lw=1.6, mutation_scale=13),
            zorder=1,
        )

    loop_y = box_y - 0.065
    x_left = xs[0] + box_w / 2
    x_right = xs[-1] + box_w / 2
    ax.plot(
        [x_right, x_right, x_left, x_left],
        [box_y, loop_y, loop_y, box_y],
        color=stroke,
        lw=1.2,
    )
    ax.annotate(
        "",
        xy=(x_left, box_y),
        xytext=(x_left, loop_y + 0.008),
        arrowprops=dict(arrowstyle="-|>", color=stroke, lw=1.2, mutation_scale=11),
    )
    ax.text(0.5, loop_y - 0.012, "再扫", ha="center", va="top", fontsize=13, color=stroke)

    ax.text(0.08, 0.38, "实例", ha="left", va="top", fontsize=16, color="black")
    ax.text(
        0.08,
        0.31,
        "开场：patch_r = 5.6 mm，slot_length = 12 mm，lw = 5.25 mm。S11 在 5–7 GHz 有约 1.9 GHz 塌陷，峰在 6.0 GHz。\n"
        "第一轮：slot_length × sw × l2，27 点。槽长加 60%，峰仍停在 6.0 GHz 附近。\n"
        "写入 HFSS：Optimetrics 中建立 SlotU_R001，Analyze 27 组。\n"
        "结果：开场塌陷不是倒 U 在工作 → 下一轮改扫 patch_r × lw × g1。\n"
        "钉点：patch_r = 11.5 mm，lw = 2.32 mm，slot_length = 19.7 mm，l1 = 11.8 mm。",
        ha="left",
        va="top",
        fontsize=14,
        color="black",
        linespacing=1.65,
    )

    pdf.savefig(fig)
    plt.close(fig)


def page_05(pdf: PdfPages) -> None:
    fig, ax = new_slide()
    ax.text(
        0.5,
        0.5,
        "Agent工作实例展示",
        ha="center",
        va="center",
        fontsize=28,
        color="black",
    )
    pdf.savefig(fig)
    plt.close(fig)


def place_image(fig, path: Path, box: tuple[float, float, float, float] = (0.08, 0.06, 0.84, 0.76)) -> None:
    img = plt.imread(path)
    ih, iw = img.shape[:2]
    box_aspect = (box[2] * SLIDE[0]) / (box[3] * SLIDE[1])
    img_aspect = iw / ih
    left, bottom, width, height = box
    if img_aspect > box_aspect:
        new_h = height * box_aspect / img_aspect
        bottom += (height - new_h) / 2
        height = new_h
    else:
        new_w = width * img_aspect / box_aspect
        left += (width - new_w) / 2
        width = new_w
    ax = fig.add_axes((left, bottom, width, height))
    ax.imshow(img)
    ax.set_axis_off()


def page_06(pdf: PdfPages) -> None:
    fig = plt.figure(figsize=SLIDE, facecolor="white")
    fig.text(0.08, 0.90, "天线结构", ha="left", va="top", fontsize=22, color="black")
    place_image(fig, ROOT / "figs" / "geometry.jpg")
    pdf.savefig(fig)
    plt.close(fig)


def load_s11(path: Path) -> tuple[list[float], list[float]]:
    freq, s11 = [], []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            freq.append(float(row["freq_ghz"]))
            s11.append(float(row["s11_db"]))
    return freq, s11


def load_family(path: Path) -> dict[str, tuple[list[float], list[float]]]:
    series: dict[str, tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            freq, s11 = series[row["variation"]]
            freq.append(float(row["freq_ghz"]))
            s11.append(float(row["s11_db"]))
    return series


def parse_mm(variation: str, key: str) -> float | None:
    m = re.search(rf"{re.escape(key)}='([0-9.]+)mm'", variation)
    return float(m.group(1)) if m else None


FILL, STROKE, RULE = "#F3F6FA", "#1F4E79", "#C5D0DC"


def page_agent_table(
    pdf: PdfPages,
    title: str,
    intent: str,
    headers: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
    footer: str,
) -> None:
    fig, ax = new_slide()
    heading(ax, title)
    speech_bubble(ax, 0.08, 0.055, 0.84, 0.71, fill=FILL, stroke=STROKE)
    ax.text(0.12, 0.73, "Agent", ha="left", va="center", fontsize=13, color=STROKE, zorder=2)
    ax.plot([0.12, 0.88], [0.705, 0.705], color=RULE, lw=0.8, zorder=1)
    ax.text(0.12, 0.66, intent, ha="left", va="top", fontsize=15, color="black", zorder=2)
    if len(headers) == 2:
        col_x, tab_w = (0.16, 0.42), 0.64
    else:
        col_x, tab_w = (0.16, 0.40, 0.64), 0.68
    row_h = 0.085 if len(rows) >= 3 else 0.09
    top = 0.56
    ax.add_patch(
        Rectangle((0.14, top - row_h), tab_w, row_h, facecolor="#E4EAF1", edgecolor=RULE, lw=0.8, zorder=1)
    )
    for x, h in zip(col_x, headers):
        ax.text(x, top - row_h / 2, h, ha="left", va="center", fontsize=14, color=STROKE, zorder=2)
    for i, row in enumerate(rows):
        y = top - (i + 2) * row_h
        ax.add_patch(Rectangle((0.14, y), tab_w, row_h, facecolor=FILL, edgecolor=RULE, lw=0.8, zorder=1))
        for x, cell in zip(col_x, row):
            ax.text(x, y + row_h / 2, cell, ha="left", va="center", fontsize=14, color="black", zorder=2)
    ax.text(0.12, 0.16, footer, ha="left", va="center", fontsize=14, color="black", zorder=2)
    pdf.savefig(fig)
    plt.close(fig)


def page_family(
    pdf: PdfPages,
    title: str,
    path: Path,
    color_key: str,
    colors: dict[float, str],
    style_key: str,
    styles: dict[float, str],
    analysis: str,
    *,
    alpha_key: str | None = None,
    alphas: dict[float, float] | None = None,
    lw: float = 1.25,
) -> None:
    fig = plt.figure(figsize=SLIDE, facecolor="white")
    fig.text(0.08, 0.90, title, ha="left", va="top", fontsize=22, color="black")
    ax = fig.add_axes((0.07, 0.14, 0.34, 0.64))
    family = load_family(path)
    for name, (freq, s11) in family.items():
        cval = parse_mm(name, color_key)
        sval = parse_mm(name, style_key)
        if cval not in colors or sval not in styles:
            continue
        alpha = 1.0
        if alpha_key and alphas is not None:
            aval = parse_mm(name, alpha_key)
            if aval not in alphas:
                continue
            alpha = alphas[aval]
        ax.plot(freq, s11, color=colors[cval], ls=styles[sval], lw=lw, alpha=alpha)
    ax.axhline(-10, color="0.45", ls="--", lw=0.8)
    ax.axvline(6.6, color="0.25", ls=":", lw=1.0)
    ax.set_xlim(1, 15)
    ax.set_ylim(-22, 3)
    ax.set_xlabel("频率 / GHz", fontsize=12)
    ax.set_ylabel(r"$S_{11}$ / dB", fontsize=12)
    ax.tick_params(labelsize=10)
    ax.grid(True, color="0.88", lw=0.6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.text(6.75, 1.4, "6.6 GHz", color="0.25", fontsize=10, va="bottom")

    overlay = fig.add_axes((0, 0, 1, 1), facecolor="none")
    overlay.set_xlim(0, 1)
    overlay.set_ylim(0, 1)
    overlay.axis("off")
    overlay.text(0.425, 0.76, color_key, ha="left", va="center", fontsize=10, color=STROKE)
    for i, (val, col) in enumerate(colors.items()):
        y = 0.71 - i * 0.055
        overlay.plot([0.425, 0.455], [y, y], color=col, lw=2.2, solid_capstyle="butt")
        overlay.text(0.465, y, f"{val:g} mm", ha="left", va="center", fontsize=10, color="black")
    style_y = 0.76 - 0.055 * len(colors) - 0.07
    overlay.text(0.425, style_y, style_key, ha="left", va="center", fontsize=10, color=STROKE)
    for i, (val, ls) in enumerate(styles.items()):
        y = style_y - 0.055 - i * 0.055
        overlay.plot([0.425, 0.455], [y, y], color="0.2", ls=ls, lw=1.7, solid_capstyle="butt")
        overlay.text(0.465, y, f"{val:g} mm", ha="left", va="center", fontsize=10, color="black")

    speech_bubble(overlay, 0.58, 0.10, 0.38, 0.68, fill=FILL, stroke=STROKE)
    overlay.text(0.605, 0.73, "Agent", ha="left", va="center", fontsize=13, color=STROKE, zorder=2)
    overlay.plot([0.605, 0.93], [0.705, 0.705], color=RULE, lw=0.8, zorder=1)
    overlay.text(
        0.605,
        0.66,
        wrap_cn(analysis, 23),
        ha="left",
        va="top",
        fontsize=13,
        color="black",
        linespacing=1.55,
        zorder=2,
    )
    pdf.savefig(fig)
    plt.close(fig)


def page_07(pdf: PdfPages) -> None:
    fig = plt.figure(figsize=SLIDE, facecolor="white")
    fig.text(0.08, 0.90, "初始 $S_{11}$ 与优化目标", ha="left", va="top", fontsize=22, color="black")

    ax = fig.add_axes((0.09, 0.14, 0.50, 0.66))
    freq, s11 = load_s11(S11_INIT)
    ax.plot(freq, s11, color="black", lw=1.6)
    ax.axhline(-10, color="0.45", ls="--", lw=0.9)
    ax.axvline(6.6, color="#1F4E79", ls=":", lw=1.2)
    ax.set_xlim(1, 15)
    ax.set_ylim(-22, 3)
    ax.set_xlabel("频率 / GHz", fontsize=13)
    ax.set_ylabel(r"$S_{11}$ / dB", fontsize=13)
    ax.tick_params(labelsize=11)
    ax.grid(True, color="0.88", lw=0.6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.text(6.7, 1.6, "6.6 GHz", color="#1F4E79", fontsize=11, va="bottom")
    ax.text(1.15, -9.3, "−10 dB", color="0.35", fontsize=10, va="bottom")

    fig.text(0.66, 0.78, "优化目标", ha="left", va="top", fontsize=16, color="black")
    goals = [
        (
            "1. 阻带位置",
            "在 6.6 GHz 做出清晰阻带。\n阻带内 $S_{11}$ 最高点须在 6.6 GHz，\n且该点高于 −7 dB。",
        ),
        (
            "2. 阻带宽度",
            "不超过 0.5 GHz。",
        ),
        (
            "3. 相对带宽",
            r"阻带两侧通带外沿 $f_L$、$f_H$ 满足"
            "\n"
            r"$2(f_H-f_L)/(f_H+f_L)\geq 130\%$。当前 112%。",
        ),
    ]
    y = 0.68
    for title, body in goals:
        fig.text(0.66, y, title, ha="left", va="top", fontsize=14, color="black")
        fig.text(0.66, y - 0.045, body, ha="left", va="top", fontsize=13, color="black", linespacing=1.45)
        y -= 0.20

    pdf.savefig(fig)
    plt.close(fig)


def page_08(pdf: PdfPages) -> None:
    fig = plt.figure(figsize=SLIDE, facecolor="white")
    fig.text(0.08, 0.90, "初始天线俯视图", ha="left", va="top", fontsize=22, color="black")
    place_image(fig, ROOT / "figs" / "top_init.jpg")
    pdf.savefig(fig)
    plt.close(fig)


def page_09(pdf: PdfPages) -> None:
    fig, ax = new_slide()
    heading(ax, "初始判断")

    fill, stroke, rule = "#F3F6FA", "#1F4E79", "#C5D0DC"
    speech_bubble(ax, 0.08, 0.055, 0.84, 0.71, fill=fill, stroke=stroke)
    ax.text(0.12, 0.73, "Agent", ha="left", va="center", fontsize=13, color=stroke, zorder=2)
    ax.plot([0.12, 0.88], [0.705, 0.705], color=rule, lw=0.8, zorder=1)

    blocks = [
        (
            "看曲线",
            "6.6 GHz 处没有清晰窄阻带。5.0–6.7 GHz 是一段约 1.9 GHz 的宽塌陷，最高点在 6.0 GHz（−6.9 dB），"
            "6.6 GHz 处约 −9.0 dB，未到 −7 dB 以上。2.1–3.6 GHz 另有深失配，3.3 GHz 附近到 −1.3 dB，判断为匹配空洞，不是目标阻带。"
            "若把 3.7 / 13.1 GHz 当两侧外沿，相对带宽约 112%。",
        ),
        (
            "变量分组",
            "slot_length、sw、l2 是同一套倒 U，应联合看；圆片半径只有 5.6 mm，槽长需小于约 16 mm 才能装进现有圆。"
            "lw 开场 5.25 mm，相对 1.14 mm 基板偏宽。馈线与部分地（lw、l1、g1 等）管 2–3.6 GHz 空洞，"
            "与槽不是同一套电流路径，这一轮不放进阻带矩阵。",
        ),
        (
            "第一轮打算",
            "先确认 5–7 GHz 塌陷是不是槽谐振。扫 slot_length = 10、12、16 mm，"
            "sw = 0.5、1.0、1.5 mm，l2 = 1.0、2.0、3.0 mm，共 27 点。贴片和馈地留到槽的特征能辨认之后。",
        ),
    ]
    y = 0.68
    for title, body in blocks:
        ax.text(0.10, y, title, ha="left", va="top", fontsize=15, color=stroke, zorder=2)
        ax.text(
            0.10,
            y - 0.046,
            wrap_cn(body, 46),
            ha="left",
            va="top",
            fontsize=13,
            color="black",
            linespacing=1.4,
            zorder=2,
        )
        y -= 0.205
    pdf.savefig(fig)
    plt.close(fig)


def page_10(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "第一轮扫参",
        "先确认 5–7 GHz 塌陷是不是槽谐振，只扫倒 U 三件套。",
        ("变量", "取值"),
        (
            ("slot_length", "10、12、16 mm"),
            ("sw", "0.5、1.0、1.5 mm"),
            ("l2", "1.0、2.0、3.0 mm"),
        ),
        "3 × 3 × 3 = 27 点。其余变量保持初始值。Optimetrics：SlotU_R001。",
    )


def page_11(pdf: PdfPages) -> None:
    page_family(
        pdf,
        "第一轮结果",
        S11_R001,
        "slot_length",
        {10.0: "#1F4E79", 12.0: "#2A9D8F", 16.0: "#C45C26"},
        "sw",
        {0.5: "-", 1.0: "--", 1.5: "-."},
        "27 条曲线的峰都停在 5.9–6.1 GHz。槽从 10 mm 加到 16 mm，电长度加 60%，峰只挪了约 0.07 GHz，完全不像半波谐振器。"
        "sw 收窄没有把缺口收到 0.5 GHz 附近。l2 几乎只在深度上抖约 0.3 dB。"
        "2.1–3.6 GHz 那截抬起全程都在。开场 5–7 GHz 大塌陷不是倒 U 在工作。"
        "下一轮换组：扫 patch_r × lw × g1。",
        alpha_key="l2",
        alphas={1.0: 1.0, 2.0: 0.62, 3.0: 0.38},
        lw=1.05,
    )


def page_12(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "第二轮扫参",
        "按基板厚度估 50 Ω 微带，放大圆片，看 5–7 GHz 是不是匹配空洞。",
        ("变量", "取值"),
        (
            ("patch_r", "5.6、8.5、11.5 mm"),
            ("lw", "1.75、3.50、5.25 mm"),
            ("g1", "8.0、8.5、10.5 mm"),
        ),
        "3 × 3 × 3 = 27 点。g1 不取 16 mm：已经看见地会爬到贴片底下。Optimetrics：PatchFeed_R002。",
    )


def page_13(pdf: PdfPages) -> None:
    page_family(
        pdf,
        "第二轮结果",
        S11_R002,
        "lw",
        {1.75: "#1F4E79", 3.5: "#2A9D8F", 5.25: "#C45C26"},
        "patch_r",
        {5.6: "-", 8.5: "--", 11.5: "-."},
        "lw 是这一簇里搬匹配的主因。lw = 1.75 mm 时 5–7 GHz 大塌陷基本消失，多条曲线从约 2.2 GHz 一直匹配到 15 GHz。"
        "开场 lw = 5.25 mm 在 1.14 mm 基板上 W/h≈4.6，远宽于 50 Ω。"
        "圆加大后窄馈线下通带更完整。开场尺寸的倒 U 在这块已经匹配好的圆上打不出阻带。"
        "钉 lw = 1.75 mm、patch_r = 11.5 mm、g1 = 8.0 mm。下一轮把槽请回来。",
        alpha_key="g1",
        alphas={8.0: 1.0, 8.5: 0.62, 10.5: 0.38},
        lw=1.05,
    )


def page_14(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "修改参数",
        "匹配已经打开，把这组圆片和馈线写进模型。",
        ("变量", "开场", "钉住"),
        (
            ("patch_r", "5.6 mm", "11.5 mm"),
            ("lw", "5.25 mm", "1.75 mm"),
            ("g1", "8.5 mm", "8.0 mm"),
        ),
        "槽三件套仍是开场值，下一轮再扫。",
    )


def page_15(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "第三轮扫参",
        "匹配平台已经钉住。把倒 U 加长到能进通带的区间。",
        ("变量", "取值"),
        (
            ("slot_length", "18、24、30 mm"),
            ("sw", "0.5、1.0、1.5 mm"),
            ("l2", "1.0、2.0、3.0 mm"),
        ),
        "3 × 3 × 3 = 27 点。12 mm 已证伪，不回头扫。Optimetrics：SlotU_R003。",
    )


def page_16(pdf: PdfPages) -> None:
    page_family(
        pdf,
        "第三轮结果",
        S11_R003,
        "slot_length",
        {18.0: "#1F4E79", 24.0: "#2A9D8F", 30.0: "#C45C26"},
        "sw",
        {0.5: "-", 1.0: "--", 1.5: "-."},
        "倒 U 终于出现可辨阻带，但只活在 slot_length = 18 mm 附近。"
        "sw = 0.5 / 1.0 mm 时缺口宽 0.2–0.3 GHz，相对带宽够，峰值却只有约 −9.9 dB，中心在 7.1–7.5 GHz。"
        "24、30 mm 不是按半波把中心往下搬，而是把这道尖缺口抹掉。"
        "下一轮把互斥的馈线宽度拉进同一张表：slot_length × sw × lw。",
        alpha_key="l2",
        alphas={1.0: 1.0, 2.0: 0.62, 3.0: 0.38},
        lw=1.05,
    )


def page_17(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "第四轮扫参",
        "稍加长槽把 7.1 GHz 往 6.6 GHz 搬，同时问馈线能不能加深缺口。",
        ("变量", "取值"),
        (
            ("slot_length", "18、19.5、21 mm"),
            ("sw", "0.5、0.8、1.1 mm"),
            ("lw", "1.75、2.5、3.5 mm"),
        ),
        "3 × 3 × 3 = 27 点。不取 24 mm。l2 钉 1.0 mm。Optimetrics：SlotFeed_R004。",
    )


def page_18(pdf: PdfPages) -> None:
    page_family(
        pdf,
        "第四轮结果",
        S11_R004,
        "lw",
        {1.75: "#1F4E79", 2.5: "#2A9D8F", 3.5: "#C45C26"},
        "slot_length",
        {18.0: "-", 19.5: "--", 21.0: "-."},
        "lw 同时搬缺口深度和宽度。lw = 1.75 mm 时只有 18 mm 槽还给出可辨阻带，峰值停在 −9.9 dB；19.5 mm 鼓包正好在 6.6 GHz，但 −10.87 dB。"
        "lw = 2.5 mm 把峰值抬到 −9～−8 dB，缺口扩到 0.8–1.0 GHz。"
        "lw = 3.5 mm 能过 −7 dB，宽度却到 1.0–1.6 GHz。"
        "下一轮把悬崖收到 1.75–2.25 mm，并带上 l2。",
        alpha_key="sw",
        alphas={0.5: 1.0, 0.8: 0.62, 1.1: 0.38},
        lw=1.05,
    )


def page_19(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "第五轮扫参",
        "深度和宽度的悬崖在 1.75 与 2.5 mm 之间，开口耦合必须同表问。",
        ("变量", "取值"),
        (
            ("lw", "1.75、2.00、2.25 mm"),
            ("slot_length", "18.5、19.5、20.5 mm"),
            ("l2", "1.0、2.0、3.0 mm"),
        ),
        "3 × 3 × 3 = 27 点。sw 钉在 0.5 mm。Optimetrics：SlotOpen_R005。",
    )


def page_20(pdf: PdfPages) -> None:
    page_family(
        pdf,
        "第五轮结果",
        S11_R005,
        "lw",
        {1.75: "#1F4E79", 2.0: "#2A9D8F", 2.25: "#C45C26"},
        "slot_length",
        {18.5: "-", 19.5: "--", 20.5: "-."},
        "lw = 2.25 mm、slot_length = 20.5 mm、l2 = 3.0 mm 第一次把峰值钉在 6.6 GHz（−9.49 dB），宽 0.4 GHz，相对带宽 145%。频率、宽度都过，只差再抬约 2.5 dB 过 −7。"
        "l2 不是几乎不动：同一槽长上，开口从 1 mm 加到 3 mm 会把鼓包收成缺口，或再抹掉。"
        "钉住这一组。下一轮换到还没问过的地台阶：sw × g2 × g3。",
        alpha_key="l2",
        alphas={1.0: 1.0, 2.0: 0.62, 3.0: 0.38},
        lw=1.05,
    )


def page_21(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "修改参数",
        "频率和宽度已经就位，把这组槽和馈线写进模型。",
        ("变量", "此前", "钉住"),
        (
            ("lw", "1.75 mm", "2.25 mm"),
            ("slot_length", "12 mm", "20.5 mm"),
            ("l2", "1.2 mm", "3.0 mm"),
        ),
        "sw 钉在 0.5 mm。圆片与 g1 保持第二轮钉住值。",
    )


def page_22(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "第六轮扫参",
        "在已对准 6.6 GHz 的平台上，看槽宽和地台阶能不能把峰值抬过 −7 dB。",
        ("变量", "取值"),
        (
            ("sw", "0.5、0.7、0.9 mm"),
            ("g2", "2.0、3.9、5.85 mm"),
            ("g3", "2.6、5.2、7.8 mm"),
        ),
        "3 × 3 × 3 = 27 点。l1 仍钉 10 mm。Optimetrics：GroundSlot_R006。",
    )


def page_23(pdf: PdfPages) -> None:
    page_family(
        pdf,
        "第六轮结果",
        S11_R006,
        "g2",
        {2.0: "#1F4E79", 3.9: "#2A9D8F", 5.85: "#C45C26"},
        "sw",
        {0.5: "-", 0.7: "--", 0.9: "-."},
        "g2 是把 6.6 GHz 阻带搬走的量。只有开场 g2 = 2 mm 还把峰值留在 6.6 附近；3.9 mm 挪到 7.8 GHz，5.85 mm 再挪到 8–10 GHz。"
        "g3 几乎不加深。sw = 0.7 mm 只深零点几 dB；0.9 mm 常常把缺口抹掉。"
        "最好仍是开场台阶 + sw = 0.5 mm：6.6 GHz / −9.49 dB。"
        "l1 = 24.45 mm 会把圆推出基板，不进网格。下一轮扫 l1 × lw × slot_length。",
        alpha_key="g3",
        alphas={2.6: 1.0, 5.2: 0.62, 7.8: 0.38},
        lw=1.05,
    )


def page_24(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "第七轮扫参",
        "贴片-地间距和馈线是同一条馈缝，必须带着槽长一起问深度。",
        ("变量", "取值"),
        (
            ("l1", "8.15、10、12 mm"),
            ("lw", "2.15、2.35、2.55 mm"),
            ("slot_length", "19.5、20.5、21.5 mm"),
        ),
        "3 × 3 × 3 = 27 点。不取 16–24 mm。Optimetrics：FeedGap_R007。",
    )


def page_25(pdf: PdfPages) -> None:
    page_family(
        pdf,
        "第七轮结果",
        S11_R007,
        "l1",
        {8.15: "#1F4E79", 10.0: "#2A9D8F", 12.0: "#C45C26"},
        "lw",
        {2.15: "-", 2.35: "--", 2.55: "-."},
        "l1 是这一簇里搬深度的主因。圆贴近地（8.15 mm）把 6.6 GHz 附近的缺口抹掉。"
        "l1 = 10 mm 仍是宽 0.3–0.5 GHz、峰值约 −9.3 dB 的平台。"
        "l1 = 12 mm 第一次把峰值抬过 −7 dB（6.7 GHz / −6.86 dB），缺口却扩到 0.8 GHz；2.1–2.4 GHz 缝也被填上，相对带宽 174%。"
        "下一轮把 l1 收到 10.5–11.8 mm，同一组加密。",
        alpha_key="slot_length",
        alphas={19.5: 1.0, 20.5: 0.62, 21.5: 0.38},
        lw=1.05,
    )


def page_26(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "第八轮扫参",
        "l1 = 10 mm 窄而浅，l1 = 12 mm 深而宽。在中间找同时过 −7 dB 且宽不超过 0.5 GHz 的点。",
        ("变量", "取值"),
        (
            ("l1", "10.5、11.2、11.8 mm"),
            ("lw", "2.20、2.32、2.45 mm"),
            ("slot_length", "19.3、19.7、20.1 mm"),
        ),
        "3 × 3 × 3 = 27 点。求解累计已近 2.5 小时，这是最后一张表。Optimetrics：FeedGapFine_R008。",
    )


def page_27(pdf: PdfPages) -> None:
    page_family(
        pdf,
        "第八轮结果",
        S11_R008,
        "l1",
        {10.5: "#1F4E79", 11.2: "#2A9D8F", 11.8: "#C45C26"},
        "lw",
        {2.20: "-", 2.32: "--", 2.45: "-."},
        "l1 从 10.5 加到 11.8 继续加深，也继续摊宽。"
        "l1 = 10.5 mm 仍能给出宽 0.5 GHz 的缺口，6.6 GHz 最深只到 −8.88 dB。"
        "l1 = 11.8 mm、lw = 2.32 mm、slot_length = 19.7 mm 把 6.6 GHz 抬到 −7.49 dB，峰值正好在 6.6 GHz，宽度 0.8 GHz。"
        "没有一条同时过 −7 dB 且宽不超过 0.5 GHz。再开一轮会超过 3 小时，钉住这一组交卷。",
        alpha_key="slot_length",
        alphas={19.3: 1.0, 19.7: 0.62, 20.1: 0.38},
        lw=1.05,
    )


def page_28(pdf: PdfPages) -> None:
    fig = plt.figure(figsize=SLIDE, facecolor="white")
    fig.text(0.08, 0.90, "交卷", ha="left", va="top", fontsize=22, color="black")

    ax = fig.add_axes((0.09, 0.14, 0.50, 0.66))
    freq0, s110 = load_s11(S11_INIT)
    freq1, s111 = load_s11(S11_FINAL)
    ax.plot(freq0, s110, color="0.55", lw=1.5, label="优化前")
    ax.plot(freq1, s111, color="#1F4E79", lw=1.8, label="优化后")
    ax.axhline(-10, color="0.45", ls="--", lw=0.9)
    ax.axvline(6.6, color="0.25", ls=":", lw=1.2)
    ax.set_xlim(1, 15)
    ax.set_ylim(-22, 3)
    ax.set_xlabel("频率 / GHz", fontsize=13)
    ax.set_ylabel(r"$S_{11}$ / dB", fontsize=13)
    ax.tick_params(labelsize=11)
    ax.grid(True, color="0.88", lw=0.6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, fontsize=12, loc="lower left")
    ax.text(6.7, 1.6, "6.6 GHz", color="0.25", fontsize=11, va="bottom")
    ax.text(1.15, -9.3, "−10 dB", color="0.35", fontsize=10, va="bottom")

    fig.text(0.66, 0.78, "判卷三项", ha="left", va="top", fontsize=16, color="black")
    goals = [
        ("1. 阻带位置", "最高点在 6.6 GHz，\n该点 −7.49 dB；目标高于 −7 dB。"),
        ("2. 阻带宽度", "0.8 GHz，超过 0.5 GHz 上限。"),
        ("3. 相对带宽", "约 1.0–14.5 GHz，174%，\n高于 130%。"),
    ]
    y = 0.68
    for title, body in goals:
        fig.text(0.66, y, title, ha="left", va="top", fontsize=14, color="black")
        fig.text(0.66, y - 0.045, body, ha="left", va="top", fontsize=13, color="black", linespacing=1.45)
        y -= 0.18
    fig.text(
        0.66,
        0.16,
        "求解累计 2 h 52 min。\n再开一轮会超过 3 小时。",
        ha="left",
        va="top",
        fontsize=13,
        color="black",
        linespacing=1.4,
    )
    pdf.savefig(fig)
    plt.close(fig)


def page_29(pdf: PdfPages) -> None:
    fig = plt.figure(figsize=SLIDE, facecolor="white")
    fig.text(0.08, 0.90, "交卷天线俯视图", ha="left", va="top", fontsize=22, color="black")
    place_image(fig, ROOT / "figs" / "top_final.jpg", box=(0.08, 0.16, 0.84, 0.66))
    fig.text(
        0.08,
        0.07,
        "注：此时铜已超出介质范围。Agent 截过俯视图，仍把这组点留下了。",
        ha="left",
        va="center",
        fontsize=13,
        color="black",
    )
    pdf.savefig(fig)
    plt.close(fig)


def page_30(pdf: PdfPages) -> None:
    fig, ax = new_slide()
    heading(ax, "与已有工作的对比")
    ax.text(
        0.08,
        0.81,
        "别人要么只把天线建出来再交给程序试尺寸，要么做的根本不是 HFSS 天线。\n"
        "本工作采用和人类一样的工作方式，直接操作已经打开的 HFSS：看结构、联合扫参、看结果、改参数，一轮一轮做到设计目标。",
        ha="left",
        va="top",
        fontsize=14,
        color="black",
        linespacing=1.45,
    )

    headers = ("工作", "它实际在做的事", "尺寸怎么定下来")
    rows = (
        (
            "LADS\nEuCAP 2026",
            "让大模型在 CST 里把天线画出来",
            "画完后另有程序大量试尺寸，\n大模型并不看曲线来调",
        ),
        (
            "RFAmpDesigner",
            "用大模型安排射频功放怎么设计",
            "功放尺寸仍由原来的优化程序计算，\n不碰 HFSS",
        ),
        (
            "超构光学 MCP\n2025",
            "用 MCP 把大模型接到光学软件",
            "做的是超表面结构，\n不是 HFSS 天线的 S11",
        ),
        (
            "本工作\n（早期demo）",
            "采用和人类一样的工作方式，操作已打开的 HFSS：\n看结构、联合扫参、看结果、改参数，多轮直到达标",
            "每一轮由 Agent 决定扫哪些变量、留下哪一组；\n用 HFSS 自带扫参，直到达标",
        ),
    )
    col_x = (0.09, 0.28, 0.58)
    top, row_h, tab_w, tab_x = 0.68, 0.100, 0.83, 0.08
    ax.add_patch(
        Rectangle((tab_x, top - row_h), tab_w, row_h, facecolor="#E4EAF1", edgecolor=RULE, lw=0.8, zorder=1)
    )
    for x, h in zip(col_x, headers):
        ax.text(x, top - row_h / 2, h, ha="left", va="center", fontsize=13, color=STROKE, zorder=2)
    for i, row in enumerate(rows):
        y = top - (i + 2) * row_h
        face = "#D6E3F0" if row[0].startswith("本工作") else FILL
        ax.add_patch(Rectangle((tab_x, y), tab_w, row_h, facecolor=face, edgecolor=RULE, lw=0.8, zorder=1))
        weight = "bold" if row[0].startswith("本工作") else "normal"
        for x, cell in zip(col_x, row):
            ax.text(
                x,
                y + row_h / 2,
                cell,
                ha="left",
                va="center",
                fontsize=12,
                color="black",
                fontweight=weight,
                linespacing=1.35,
                zorder=2,
            )

    ax.text(
        0.08,
        0.06,
        "到 2026 年 8 月，还没有公开发表的工作是：在已打开的 HFSS 上，由 Agent 自己完成\n"
        "看结构、联合扫参、看结果、改参数的多轮闭环，直到达标。",
        ha="left",
        va="bottom",
        fontsize=13,
        color="black",
        linespacing=1.4,
    )
    pdf.savefig(fig)
    plt.close(fig)


def main() -> None:
    with PdfPages(OUT) as pdf:
        page_01(pdf)
        page_02(pdf)
        page_03(pdf)
        page_04(pdf)
        page_05(pdf)
        page_06(pdf)
        page_07(pdf)
        page_08(pdf)
        page_09(pdf)
        page_10(pdf)
        page_11(pdf)
        page_12(pdf)
        page_13(pdf)
        page_14(pdf)
        page_15(pdf)
        page_16(pdf)
        page_17(pdf)
        page_18(pdf)
        page_19(pdf)
        page_20(pdf)
        page_21(pdf)
        page_22(pdf)
        page_23(pdf)
        page_24(pdf)
        page_25(pdf)
        page_26(pdf)
        page_27(pdf)
        page_28(pdf)
        page_29(pdf)
        page_30(pdf)
    print(OUT)


if __name__ == "__main__":
    main()
