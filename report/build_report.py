"""逐页生成学术报告 PDF。"""

from collections import defaultdict
from pathlib import Path
import csv
import re

from matplotlib.path import Path as MplPath
from matplotlib.patches import FancyBboxPatch, PathPatch, Rectangle

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "基于AI-Agent的HFSS天线优化方法.pdf"
S11_INIT = (
    ROOT.parent
    / "eval/archive/exams/uwb_circular_notch/runs/20260817-165848/round-000-s11.csv"
)
S11_R001 = (
    ROOT.parent
    / "eval/archive/exams/uwb_circular_notch/runs/20260817-165848/round-001-s11.csv"
)
S11_R002 = (
    ROOT.parent
    / "eval/archive/exams/uwb_circular_notch/runs/20260817-165848/round-002-s11.csv"
)
S11_R003 = (
    ROOT.parent
    / "eval/archive/exams/uwb_circular_notch/runs/20260817-165848/round-003-s11.csv"
)
S11_R004 = (
    ROOT.parent
    / "eval/archive/exams/uwb_circular_notch/runs/20260817-165848/round-004-s11.csv"
)
S11_R005 = (
    ROOT.parent
    / "eval/archive/exams/uwb_circular_notch/runs/20260817-165848/round-005-s11.csv"
)
S11_R006 = (
    ROOT.parent
    / "eval/archive/exams/uwb_circular_notch/runs/20260817-165848/round-006-s11.csv"
)
S11_R007 = (
    ROOT.parent
    / "eval/archive/exams/uwb_circular_notch/runs/20260817-165848/round-007-s11.csv"
)
S11_FINAL = (
    ROOT.parent
    / "eval/archive/exams/uwb_circular_notch/runs/20260817-165848/s11.csv"
)

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
        (14, "第三轮扫参"),
        (15, "第三轮结果"),
        (16, "修改参数"),
        (17, "第四轮扫参"),
        (18, "第四轮结果"),
        (19, "第五轮扫参"),
        (20, "第五轮结果"),
        (21, "第六轮扫参"),
        (22, "第六轮结果"),
        (23, "修改参数"),
        (24, "第七轮扫参"),
        (25, "第七轮结果"),
        (26, "修改参数"),
        (27, "交卷"),
        (28, "交卷天线俯视图"),
        (29, "与已有工作的对比"),
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
        "开场：patch_r = 5.6 mm，slot_length = 12 mm。S11 缺口在 6.0 GHz，宽约 1.7 GHz。\n"
        "第一轮：slot_length = 10、11、12 mm，sw = 0.5、0.9、1.2、1.5 mm，共 12 点。\n"
        "写入 HFSS：Optimetrics 中建立 Para_slot_sw_r001，Analyze 12 组。\n"
        "结果：12 条峰都在 5.9–6.1 GHz，缩短槽几乎不搬频 → 下一轮改扫 patch_r × slot_length。\n"
        "钉点：patch_r = 10 mm，slot_length = 19.1 mm，sw = 0.5 mm，lw = 1.75 mm。",
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


def parse_slot_sw(variation: str) -> tuple[float, float]:
    slot = float(re.search(r"slot_length='([0-9.]+)mm'", variation).group(1))
    sw = float(re.search(r"sw='([0-9.]+)mm'", variation).group(1))
    return slot, sw


def parse_patch_slot(variation: str) -> tuple[float, float]:
    patch = float(re.search(r"patch_r='([0-9.]+)mm'", variation).group(1))
    slot = float(re.search(r"slot_length='([0-9.]+)mm'", variation).group(1))
    return patch, slot


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
            "在 6.6 GHz 做出清晰阻带。\n阻带内 $S_{11}$ 最高点须在 6.6 GHz，\n且该点高于 −10 dB。",
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
            "6.6 GHz 处没有清晰窄阻带。5.0–6.7 GHz 是一段约 1.7 GHz 的宽塌陷，最高点在 6.0 GHz（−6.9 dB），"
            "6.6 GHz 处约 −9.0 dB。2.1–3.6 GHz 另有深失配，3.3 GHz 附近到 −1.3 dB，判断为匹配空洞，不是目标阻带。"
            "若把 5–7 GHz 当缺口，相对带宽约 112%。",
        ),
        (
            "变量分组",
            "slot_length 与 sw 是同一谐振器，应联合看；圆片半径只有 5.6 mm，槽长 12 mm 已接近贴片尺度。"
            "patch_r 主控低频截止，与槽同在一片金属上。馈线与部分地（lw、l1、g1 等）管 2–3.6 GHz 空洞和通带外沿，"
            "与槽不是同一套电流路径，这一轮不放进阻带矩阵。",
        ),
        (
            "第一轮打算",
            "先确认 5–7 GHz 塌陷是不是槽谐振。只扫 slot_length = 10、11、12 mm，"
            "sw = 0.5、0.9、1.2、1.5 mm，共 12 点。贴片和馈地留到槽的特征能辨认之后。",
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
    fig, ax = new_slide()
    heading(ax, "第一轮扫参")

    fill, stroke, rule = "#F3F6FA", "#1F4E79", "#C5D0DC"
    speech_bubble(ax, 0.08, 0.055, 0.84, 0.71, fill=fill, stroke=stroke)
    ax.text(0.12, 0.73, "Agent", ha="left", va="center", fontsize=13, color=stroke, zorder=2)
    ax.plot([0.12, 0.88], [0.705, 0.705], color=rule, lw=0.8, zorder=1)
    ax.text(
        0.12,
        0.66,
        "先确认 5–7 GHz 塌陷是不是槽谐振，只扫槽长和槽宽。",
        ha="left",
        va="top",
        fontsize=15,
        color="black",
        zorder=2,
    )

    col_x = (0.16, 0.42)
    headers = ("变量", "取值")
    rows = (
        ("slot_length", "10、11、12 mm"),
        ("sw", "0.5、0.9、1.2、1.5 mm"),
    )
    top, row_h, tab_w = 0.56, 0.09, 0.64
    ax.add_patch(Rectangle((0.14, top - row_h), tab_w, row_h, facecolor="#E4EAF1", edgecolor=rule, lw=0.8, zorder=1))
    for x, h in zip(col_x, headers):
        ax.text(x, top - row_h / 2, h, ha="left", va="center", fontsize=14, color=stroke, zorder=2)
    for i, (name, vals) in enumerate(rows):
        y = top - (i + 2) * row_h
        ax.add_patch(
            Rectangle((0.14, y), tab_w, row_h, facecolor=fill, edgecolor=rule, lw=0.8, zorder=1)
        )
        ax.text(col_x[0], y + row_h / 2, name, ha="left", va="center", fontsize=14, color="black", zorder=2)
        ax.text(col_x[1], y + row_h / 2, vals, ha="left", va="center", fontsize=14, color="black", zorder=2)

    ax.text(
        0.12,
        0.18,
        "3 × 4 = 12 点。其余变量保持初始值。Optimetrics：Para_slot_sw_r001。",
        ha="left",
        va="center",
        fontsize=14,
        color="black",
        zorder=2,
    )
    pdf.savefig(fig)
    plt.close(fig)


def page_11(pdf: PdfPages) -> None:
    fig = plt.figure(figsize=SLIDE, facecolor="white")
    fig.text(0.08, 0.90, "第一轮结果", ha="left", va="top", fontsize=22, color="black")

    slot_color = {10.0: "#1F4E79", 11.0: "#2A9D8F", 12.0: "#C45C26"}
    sw_style = {0.5: "-", 0.9: "--", 1.2: "-.", 1.5: ":"}

    ax = fig.add_axes((0.07, 0.14, 0.34, 0.64))
    family = load_family(S11_R001)
    for name, (freq, s11) in family.items():
        slot, sw = parse_slot_sw(name)
        ax.plot(freq, s11, color=slot_color[slot], ls=sw_style[sw], lw=1.35)
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
    overlay.text(0.425, 0.76, "slot_length", ha="left", va="center", fontsize=10, color="#1F4E79")
    overlay.text(0.425, 0.52, "sw", ha="left", va="center", fontsize=10, color="#1F4E79")
    for i, sl in enumerate((10.0, 11.0, 12.0)):
        y = 0.71 - i * 0.055
        overlay.plot([0.425, 0.455], [y, y], color=slot_color[sl], lw=2.2, solid_capstyle="butt")
        overlay.text(0.465, y, f"{sl:g} mm", ha="left", va="center", fontsize=10, color="black")
    for i, sw in enumerate((0.5, 0.9, 1.2, 1.5)):
        y = 0.46 - i * 0.055
        overlay.plot([0.425, 0.455], [y, y], color="0.2", ls=sw_style[sw], lw=1.7, solid_capstyle="butt")
        overlay.text(0.465, y, f"{sw:g} mm", ha="left", va="center", fontsize=10, color="black")

    fill, stroke, rule = "#F3F6FA", "#1F4E79", "#C5D0DC"
    speech_bubble(overlay, 0.58, 0.10, 0.38, 0.68, fill=fill, stroke=stroke)
    overlay.text(0.605, 0.73, "Agent", ha="left", va="center", fontsize=13, color=stroke, zorder=2)
    overlay.plot([0.605, 0.93], [0.705, 0.705], color=rule, lw=0.8, zorder=1)
    overlay.text(
        0.605,
        0.66,
        wrap_cn(
            "12 条曲线的峰都停在 5.9–6.1 GHz。槽从 12 mm 收到 10 mm，峰不按 1/L 走，3.3 GHz 失配也不动。"
            "sw = 0.9 mm 时只是把坑填浅，6.6 GHz 甚至回到 −10 dB 以下。"
            "这一尺度上短槽还不是 6.6 GHz 谐振器。下一轮换组：放大圆片、加长槽，扫 patch_r × slot_length；sw 钉在 0.5 mm。",
            23,
        ),
        ha="left",
        va="top",
        fontsize=13,
        color="black",
        linespacing=1.55,
        zorder=2,
    )
    pdf.savefig(fig)
    plt.close(fig)


def page_12(pdf: PdfPages) -> None:
    fig, ax = new_slide()
    heading(ax, "第二轮扫参")

    fill, stroke, rule = "#F3F6FA", "#1F4E79", "#C5D0DC"
    speech_bubble(ax, 0.08, 0.055, 0.84, 0.71, fill=fill, stroke=stroke)
    ax.text(0.12, 0.73, "Agent", ha="left", va="center", fontsize=13, color=stroke, zorder=2)
    ax.plot([0.12, 0.88], [0.705, 0.705], color=rule, lw=0.8, zorder=1)
    ax.text(
        0.12,
        0.66,
        "放大圆片、把槽加到半波长附近，看阻带会不会随槽长走动。",
        ha="left",
        va="top",
        fontsize=15,
        color="black",
        zorder=2,
    )

    col_x = (0.16, 0.42)
    headers = ("变量", "取值")
    rows = (
        ("patch_r", "7.0、9.5、12.0 mm"),
        ("slot_length", "14、18、22、26 mm"),
    )
    top, row_h, tab_w = 0.56, 0.09, 0.64
    ax.add_patch(Rectangle((0.14, top - row_h), tab_w, row_h, facecolor="#E4EAF1", edgecolor=rule, lw=0.8, zorder=1))
    for x, h in zip(col_x, headers):
        ax.text(x, top - row_h / 2, h, ha="left", va="center", fontsize=14, color=stroke, zorder=2)
    for i, (name, vals) in enumerate(rows):
        y = top - (i + 2) * row_h
        ax.add_patch(
            Rectangle((0.14, y), tab_w, row_h, facecolor=fill, edgecolor=rule, lw=0.8, zorder=1)
        )
        ax.text(col_x[0], y + row_h / 2, name, ha="left", va="center", fontsize=14, color="black", zorder=2)
        ax.text(col_x[1], y + row_h / 2, vals, ha="left", va="center", fontsize=14, color="black", zorder=2)

    ax.text(
        0.12,
        0.18,
        "3 × 4 = 12 点。sw 钉在 0.5 mm。Optimetrics：Para_patch_slot_r002。",
        ha="left",
        va="center",
        fontsize=14,
        color="black",
        zorder=2,
    )
    pdf.savefig(fig)
    plt.close(fig)


def page_13(pdf: PdfPages) -> None:
    fig = plt.figure(figsize=SLIDE, facecolor="white")
    fig.text(0.08, 0.90, "第二轮结果", ha="left", va="top", fontsize=22, color="black")

    slot_color = {14.0: "#1F4E79", 18.0: "#2A9D8F", 22.0: "#C45C26", 26.0: "#7A3E9D"}
    patch_style = {7.0: "-", 9.5: "--", 12.0: "-."}
    keep_patch = set(patch_style)
    keep_slot = set(slot_color)

    ax = fig.add_axes((0.07, 0.14, 0.34, 0.64))
    family = load_family(S11_R002)
    for name, (freq, s11) in family.items():
        patch, slot = parse_patch_slot(name)
        if patch not in keep_patch or slot not in keep_slot:
            continue
        ax.plot(freq, s11, color=slot_color[slot], ls=patch_style[patch], lw=1.35)
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
    overlay.text(0.425, 0.76, "slot_length", ha="left", va="center", fontsize=10, color="#1F4E79")
    overlay.text(0.425, 0.48, "patch_r", ha="left", va="center", fontsize=10, color="#1F4E79")
    for i, sl in enumerate((14.0, 18.0, 22.0, 26.0)):
        y = 0.71 - i * 0.055
        overlay.plot([0.425, 0.455], [y, y], color=slot_color[sl], lw=2.2, solid_capstyle="butt")
        overlay.text(0.465, y, f"{sl:g} mm", ha="left", va="center", fontsize=10, color="black")
    for i, pr in enumerate((7.0, 9.5, 12.0)):
        y = 0.42 - i * 0.055
        overlay.plot([0.425, 0.455], [y, y], color="0.2", ls=patch_style[pr], lw=1.7, solid_capstyle="butt")
        overlay.text(0.465, y, f"{pr:g} mm", ha="left", va="center", fontsize=10, color="black")

    fill, stroke, rule = "#F3F6FA", "#1F4E79", "#C5D0DC"
    speech_bubble(overlay, 0.58, 0.10, 0.38, 0.68, fill=fill, stroke=stroke)
    overlay.text(0.605, 0.73, "Agent", ha="left", va="center", fontsize=13, color=stroke, zorder=2)
    overlay.plot([0.605, 0.93], [0.705, 0.705], color=rule, lw=0.8, zorder=1)
    overlay.text(
        0.605,
        0.66,
        wrap_cn(
            "槽一加长，窄缺口就出来了，并随槽长下移：18 mm 约在 7.4 GHz，22 mm 约在 6.1 GHz。"
            "这才是槽谐振，不是开场那条 5–7 GHz 塌陷。"
            "patch_r 主要搬 2–3 GHz 和 4–5 GHz 的失配；7 mm 圆片上槽谐振和失配粘在一起。"
            "26 mm 槽相对圆片过长，曲线形状变差，不再用。"
            "下一轮同一组收窄：对准 6.6 GHz，扫 patch_r × slot_length 在 9.5 mm、20.5 mm 附近；sw 仍钉 0.5 mm。",
            23,
        ),
        ha="left",
        va="top",
        fontsize=13,
        color="black",
        linespacing=1.55,
        zorder=2,
    )
    pdf.savefig(fig)
    plt.close(fig)


def page_14(pdf: PdfPages) -> None:
    fig, ax = new_slide()
    heading(ax, "第三轮扫参")

    fill, stroke, rule = "#F3F6FA", "#1F4E79", "#C5D0DC"
    speech_bubble(ax, 0.08, 0.055, 0.84, 0.71, fill=fill, stroke=stroke)
    ax.text(0.12, 0.73, "Agent", ha="left", va="center", fontsize=13, color=stroke, zorder=2)
    ax.plot([0.12, 0.88], [0.705, 0.705], color=rule, lw=0.8, zorder=1)
    ax.text(
        0.12,
        0.66,
        "同一组收窄，把窄缺口的峰对准 6.6 GHz。",
        ha="left",
        va="top",
        fontsize=15,
        color="black",
        zorder=2,
    )

    col_x = (0.16, 0.42)
    headers = ("变量", "取值")
    rows = (
        ("patch_r", "9.0、9.5、10.0、10.5 mm"),
        ("slot_length", "19.5、20.0、20.5、21.0 mm"),
    )
    top, row_h, tab_w = 0.56, 0.09, 0.64
    ax.add_patch(Rectangle((0.14, top - row_h), tab_w, row_h, facecolor="#E4EAF1", edgecolor=rule, lw=0.8, zorder=1))
    for x, h in zip(col_x, headers):
        ax.text(x, top - row_h / 2, h, ha="left", va="center", fontsize=14, color=stroke, zorder=2)
    for i, (name, vals) in enumerate(rows):
        y = top - (i + 2) * row_h
        ax.add_patch(
            Rectangle((0.14, y), tab_w, row_h, facecolor=fill, edgecolor=rule, lw=0.8, zorder=1)
        )
        ax.text(col_x[0], y + row_h / 2, name, ha="left", va="center", fontsize=14, color="black", zorder=2)
        ax.text(col_x[1], y + row_h / 2, vals, ha="left", va="center", fontsize=14, color="black", zorder=2)

    ax.text(
        0.12,
        0.18,
        "4 × 4 = 16 点。sw 钉在 0.5 mm。Optimetrics：Para_patch_slot_r003。",
        ha="left",
        va="center",
        fontsize=14,
        color="black",
        zorder=2,
    )
    pdf.savefig(fig)
    plt.close(fig)


def page_15(pdf: PdfPages) -> None:
    fig = plt.figure(figsize=SLIDE, facecolor="white")
    fig.text(0.08, 0.90, "第三轮结果", ha="left", va="top", fontsize=22, color="black")

    slot_color = {19.5: "#1F4E79", 20.0: "#2A9D8F", 20.5: "#C45C26", 21.0: "#7A3E9D"}
    patch_style = {9.0: "-", 9.5: "--", 10.0: "-.", 10.5: ":"}
    keep_patch = set(patch_style)
    keep_slot = set(slot_color)

    ax = fig.add_axes((0.07, 0.14, 0.34, 0.64))
    family = load_family(S11_R003)
    for name, (freq, s11) in family.items():
        patch, slot = parse_patch_slot(name)
        if patch not in keep_patch or slot not in keep_slot:
            continue
        ax.plot(freq, s11, color=slot_color[slot], ls=patch_style[patch], lw=1.25)
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
    overlay.text(0.425, 0.76, "slot_length", ha="left", va="center", fontsize=10, color="#1F4E79")
    overlay.text(0.425, 0.48, "patch_r", ha="left", va="center", fontsize=10, color="#1F4E79")
    for i, sl in enumerate((19.5, 20.0, 20.5, 21.0)):
        y = 0.71 - i * 0.055
        overlay.plot([0.425, 0.455], [y, y], color=slot_color[sl], lw=2.2, solid_capstyle="butt")
        overlay.text(0.465, y, f"{sl:g} mm", ha="left", va="center", fontsize=10, color="black")
    for i, pr in enumerate((9.0, 9.5, 10.0, 10.5)):
        y = 0.42 - i * 0.055
        overlay.plot([0.425, 0.455], [y, y], color="0.2", ls=patch_style[pr], lw=1.7, solid_capstyle="butt")
        overlay.text(0.465, y, f"{pr:g} mm", ha="left", va="center", fontsize=10, color="black")

    fill, stroke, rule = "#F3F6FA", "#1F4E79", "#C5D0DC"
    speech_bubble(overlay, 0.58, 0.10, 0.38, 0.68, fill=fill, stroke=stroke)
    overlay.text(0.605, 0.73, "Agent", ha="left", va="center", fontsize=13, color=stroke, zorder=2)
    overlay.plot([0.605, 0.93], [0.705, 0.705], color=rule, lw=0.8, zorder=1)
    overlay.text(
        0.605,
        0.66,
        wrap_cn(
            "两轴都在挪缺口。槽加长，缺口下移；圆片加大，同一槽长缺口略下移、6.6 GHz 处抬得更高。"
            "对准 6.6 GHz 且宽度还在 0.5 GHz 以内的是 patch_r = 10 mm、slot_length = 19.5 mm"
            "（峰 −7.97 dB，缺口约 0.2 GHz）。钉住这组，sw 仍是 0.5 mm。"
            "4–5 GHz 和 2–3 GHz 的失配还在，不是槽能填的。"
            "下一轮换组：扫成形地 g1 × g2 × g3。",
            23,
        ),
        ha="left",
        va="top",
        fontsize=13,
        color="black",
        linespacing=1.55,
        zorder=2,
    )
    pdf.savefig(fig)
    plt.close(fig)


def page_16(pdf: PdfPages) -> None:
    fig, ax = new_slide()
    heading(ax, "修改参数")

    fill, stroke, rule = "#F3F6FA", "#1F4E79", "#C5D0DC"
    speech_bubble(ax, 0.08, 0.055, 0.84, 0.71, fill=fill, stroke=stroke)
    ax.text(0.12, 0.73, "Agent", ha="left", va="center", fontsize=13, color=stroke, zorder=2)
    ax.plot([0.12, 0.88], [0.705, 0.705], color=rule, lw=0.8, zorder=1)
    ax.text(
        0.12,
        0.66,
        "缺口已经对准 6.6 GHz，把这组写进模型。",
        ha="left",
        va="top",
        fontsize=15,
        color="black",
        zorder=2,
    )

    col_x = (0.16, 0.40, 0.64)
    headers = ("变量", "开场", "钉住")
    rows = (
        ("patch_r", "5.6 mm", "10 mm"),
        ("slot_length", "12 mm", "19.5 mm"),
        ("sw", "1.5 mm", "0.5 mm"),
    )
    top, row_h, tab_w = 0.56, 0.085, 0.68
    ax.add_patch(Rectangle((0.14, top - row_h), tab_w, row_h, facecolor="#E4EAF1", edgecolor=rule, lw=0.8, zorder=1))
    for x, h in zip(col_x, headers):
        ax.text(x, top - row_h / 2, h, ha="left", va="center", fontsize=14, color=stroke, zorder=2)
    for i, (name, old, new) in enumerate(rows):
        y = top - (i + 2) * row_h
        ax.add_patch(
            Rectangle((0.14, y), tab_w, row_h, facecolor=fill, edgecolor=rule, lw=0.8, zorder=1)
        )
        ax.text(col_x[0], y + row_h / 2, name, ha="left", va="center", fontsize=14, color="black", zorder=2)
        ax.text(col_x[1], y + row_h / 2, old, ha="left", va="center", fontsize=14, color="black", zorder=2)
        ax.text(col_x[2], y + row_h / 2, new, ha="left", va="center", fontsize=14, color="black", zorder=2)

    ax.text(
        0.12,
        0.16,
        "其余变量保持开场值。",
        ha="left",
        va="center",
        fontsize=14,
        color="black",
        zorder=2,
    )
    pdf.savefig(fig)
    plt.close(fig)


def page_17(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "第四轮扫参",
        "阻带已经对准，看成形地能不能填 2–3 GHz 和 4–5 GHz 的失配。",
        ("变量", "取值"),
        (
            ("g1", "8.5、16、24 mm"),
            ("g2", "2.0、3.9、5.8 mm"),
            ("g3", "2.6、5.2、7.8 mm"),
        ),
        "3 × 3 × 3 = 27 点。圆片与槽已钉。Optimetrics：Para_gnd_r004。",
    )


def page_18(pdf: PdfPages) -> None:
    page_family(
        pdf,
        "第四轮结果",
        S11_R004,
        "g1",
        {8.5: "#1F4E79", 16.0: "#2A9D8F", 24.0: "#C45C26"},
        "g2",
        {2.0: "-", 3.9: "--", 5.8: "-."},
        "g1 主导。8.5 mm 时 6.6 GHz 窄口还在，4–5 GHz 和 2–3 GHz 空洞仍在。"
        "地加到 16 mm 能填 4–5 GHz，但窄口被拉成约 2.7 GHz 的宽塌陷。"
        "g2、g3 填不了坑，加大还会把缺口加宽。二者留在开场。"
        "下一轮换到馈地交界：扫 g1 × l2，在 8.5 与 16 mm 之间找折中。",
        alpha_key="g3",
        alphas={2.6: 1.0, 5.2: 0.62, 7.8: 0.38},
        lw=1.05,
    )


def page_19(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "第五轮扫参",
        "g1 略加长，看 l2 能不能在填坑的同时把缺口收回去。",
        ("变量", "取值"),
        (
            ("g1", "8.5、10.5、12.5、14.5 mm"),
            ("l2", "1.0、1.6、2.2、3.0 mm"),
        ),
        "4 × 4 = 16 点。g2、g3 留在开场。Optimetrics：Para_g1_l2_r005。",
    )


def page_20(pdf: PdfPages) -> None:
    page_family(
        pdf,
        "第五轮结果",
        S11_R005,
        "g1",
        {8.5: "#1F4E79", 10.5: "#2A9D8F", 12.5: "#C45C26", 14.5: "#7A3E9D"},
        "l2",
        {1.0: "-", 1.6: "--", 2.2: "-.", 3.0: ":"},
        "g1 = 10.5 mm 能填平 4–5 GHz，但 6.6 GHz 处回到 −10 dB 以下，上沿也被砍短。"
        "再长到 12.5、14.5 mm，6–10 GHz 变成宽塌陷。"
        "l2 在 g1 = 8.5 mm 时只是微移阻带中心，填不了空洞。"
        "回到 g1 = 8.5 mm、l2 = 1.2 mm。下一轮换馈线：扫 lw × l1。",
    )


def page_21(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "第六轮扫参",
        "钉住已对准的槽和短地，用馈线填匹配空洞。",
        ("变量", "取值"),
        (
            ("lw", "1.75、3.50、5.25 mm"),
            ("l1", "8.15、16.3、24.45 mm"),
        ),
        "3 × 3 = 9 点。圆片、槽和地已钉。Optimetrics：Para_feed_r006。",
    )


def page_22(pdf: PdfPages) -> None:
    page_family(
        pdf,
        "第六轮结果",
        S11_R006,
        "lw",
        {1.75: "#1F4E79", 3.5: "#2A9D8F", 5.25: "#C45C26"},
        "l1",
        {8.15: "-", 16.3: "--", 24.45: "-."},
        "lw 收窄会填 2–3 GHz 和 4–5 GHz 的洞，也改槽的耦合。"
        "lw = 1.75 mm、l1 = 16.3 mm 时 1–6.2 GHz 连成通带，相对带宽约 175%；"
        "窄口还在，但峰在 6.5 GHz，6.6 GHz 刚回到通带。"
        "l1 再长到 24.45 mm 阻带消失。钉 lw = 1.75 mm、l1 = 16.3 mm。"
        "下一轮把槽谐振从 6.5 搬到 6.6 GHz。",
    )


def page_23(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "修改参数",
        "匹配已经拉开，把这组馈线写进模型。",
        ("变量", "此前", "钉住"),
        (
            ("lw", "5.25 mm", "1.75 mm"),
            ("l1", "10 mm", "16.3 mm"),
        ),
        "圆片、槽和地保持第三轮钉住值。",
    )


def page_24(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "第七轮扫参",
        "新馈电下把缺口从 6.5 GHz 搬回 6.6 GHz。",
        ("变量", "取值"),
        (
            ("slot_length", "18.8、19.1、19.2、19.5 mm"),
            ("sw", "0.5、0.9、1.3 mm"),
        ),
        "4 × 3 = 12 点。馈电与地已钉。Optimetrics：Para_slot_r007。",
    )


def page_25(pdf: PdfPages) -> None:
    page_family(
        pdf,
        "第七轮结果",
        S11_R007,
        "slot_length",
        {18.8: "#1F4E79", 19.1: "#2A9D8F", 19.2: "#C45C26", 19.5: "#7A3E9D"},
        "sw",
        {0.5: "-", 0.9: "--", 1.3: "-."},
        "slot_length 继续搬峰，sw 加宽会把缺口抹掉。"
        "sw = 0.5 mm 时，19.1 mm 峰在 6.6 GHz（−8.82 dB），缺口约 0.1 GHz；"
        "通带约 1–6.4 与 6.7–15 GHz，相对带宽 175%。"
        "钉住这一组，停并交卷。",
    )


def page_26(pdf: PdfPages) -> None:
    page_agent_table(
        pdf,
        "修改参数",
        "缺口已经回到 6.6 GHz，把槽长写进模型。",
        ("变量", "此前", "钉住"),
        (("slot_length", "19.5 mm", "19.1 mm"),),
        "其余保持第六轮钉住值。sw 仍是 0.5 mm。",
    )


def page_27(pdf: PdfPages) -> None:
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
        ("1. 阻带位置", "最高点在 6.6 GHz，\n该点 −8.82 dB，高于 −10 dB。"),
        ("2. 阻带宽度", "0.1 GHz，不超过 0.5 GHz。"),
        ("3. 相对带宽", "约 1–15 GHz，175%，\n高于 130%。"),
    ]
    y = 0.68
    for title, body in goals:
        fig.text(0.66, y, title, ha="left", va="top", fontsize=14, color="black")
        fig.text(0.66, y - 0.045, body, ha="left", va="top", fontsize=13, color="black", linespacing=1.45)
        y -= 0.18
    pdf.savefig(fig)
    plt.close(fig)


def page_28(pdf: PdfPages) -> None:
    fig = plt.figure(figsize=SLIDE, facecolor="white")
    fig.text(0.08, 0.90, "交卷天线俯视图", ha="left", va="top", fontsize=22, color="black")
    place_image(fig, ROOT / "figs" / "top_final.jpg", box=(0.08, 0.16, 0.84, 0.66))
    fig.text(
        0.08,
        0.07,
        "注：此时铜已超出介质范围。因为 Agent 没有被要求使用视觉能力检查天线结构，后续可改进。",
        ha="left",
        va="center",
        fontsize=13,
        color="black",
    )
    pdf.savefig(fig)
    plt.close(fig)


def page_29(pdf: PdfPages) -> None:
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
    print(OUT)


if __name__ == "__main__":
    main()
