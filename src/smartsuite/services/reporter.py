"""Reporter — 多格式报告输出：Excel 图表 / PDF / PPT。"""

import io
import logging
import math
import numbers
import os
import warnings
from typing import Any

from smartsuite.core.contracts import AnalysisResult
from smartsuite.core.exceptions import OutputError

# 图表输出 DPI 常量
_CHART_DPI = 150
_PDF_DPI = 200

logger = logging.getLogger(__name__)


#: 导出格式 → (扩展名, MIME 类型)。Web 侧据此设置下载头。
#: 单一事实源：格式白名单、扩展名、MIME 三者只在这一处定义。
EXPORT_FORMATS: dict[str, tuple[str, str]] = {
    "html": (".html", "text/html; charset=utf-8"),
    "pdf": (".pdf", "application/pdf"),
    "ppt": (".pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    "xlsx": (
        ".xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
}


def export_report(
    result: AnalysisResult,
    fmt: str,
    output_path: str,
    *,
    template_path: str | None = None,
    df: Any = None,
    target_col: str = "",
    feature_cols: list[str] | None = None,
) -> str:
    """按格式分发到对应 reporter，返回实际写入的路径。

    ## 为什么需要这个分发器（阶段 P5，2026-09-24）

    三个 reporter 签名各异（`to_ppt` 多一个 `template_path`）、`export_workbook`
    还在另一个模块且需要 DataFrame + 列信息。若让 `web/` 直接分别调用，
    Web 层就要知道"哪种格式走哪个函数、参数怎么拼"——那是桥接层的职责。
    故在服务层收一处分发，调用方只传 `(result, fmt, path)`。

    ## 为什么 `xlsx` 需要额外参数

    `to_html`/`to_pdf`/`to_ppt` 都只吃 `AnalysisResult`（图表在 `result.figures`），
    而 `audit.export_workbook` 是**另一个粒度**：它按 DataFrame + 列信息**自行
    重跑**全部任务，每个任务写一个 Sheet（这样才能做出多 Sheet 工作簿）。
    故 `xlsx` 必须显式给 `df` / `target_col` / `feature_cols`；
    缺失时**明确拒绝**而非抛底层异常。

    Args:
        result: 分析结果（`html`/`pdf`/`ppt` 用；图表取自 `result.figures`）。
        fmt: `html` / `pdf` / `ppt` / `xlsx`（不区分大小写）。
        output_path: 输出文件路径（父目录会自动创建）。
        template_path: 仅 `ppt` 使用（PPT 模板）。
        df / target_col / feature_cols: 仅 `xlsx` 使用。

    Raises:
        OutputError: 格式不支持、`xlsx` 缺列信息、或写入失败。
    """
    key = (fmt or "").strip().lower()
    if key not in EXPORT_FORMATS:
        supported = " / ".join(sorted(EXPORT_FORMATS))
        raise OutputError(
            f"不支持的报告格式「{fmt}」，支持: {supported}"
            "（html=自包含网页报告、pdf=PDF、ppt=PowerPoint、xlsx=多 Sheet 工作簿）"
        )

    if key == "html":
        return to_html(result, output_path)
    if key == "pdf":
        return to_pdf(result, output_path)
    if key == "ppt":
        return to_ppt(result, output_path, template_path)

    # key == "xlsx"
    if df is None or not target_col:
        raise OutputError(
            "导出 Excel 工作簿需要数据与目标列（xlsx 会按列信息自行重跑全部任务，"
            "每个任务写入独立 Sheet），请检查调用参数"
        )
    from smartsuite.services.audit import export_workbook

    return str(export_workbook(df, target_col, feature_cols or [], output_path))


def _prepare_output_path(output_path: str) -> str:
    """把导出目标路径归一化为绝对路径，并**确保其父目录存在**。

    契约：docs/governance/boundary-contract.md（B0 拒绝）

    审查 2026-09-24（第三轮复核 P1-2）：本函数原名 `_validate_output_path`，
    docstring 写「验证输出路径安全性: 解析为绝对路径并检查是否在合理目录内」，
    但实现里**没有任何检查、没有拒绝分支**——只做 `abspath` + `makedirs`。
    函数名与文档都在承诺一件没做的事，属"虚假安全感"：未来若有人加 Web 导出
    端点，会以为已有路径防护。现改名并如实描述，同时补上真正有用的校验。

    **有意不做目录白名单限制**：三个调用方（`to_pdf`/`to_ppt`/`to_html`）都是
    CLI 导出入口，目标路径由用户显式给出——把报告写到数据盘或共享盘是合法需求，
    加白名单会制造无意义的使用障碍。真正的风险面在 Web 上传路径（另有
    `_upload_dir()` + 命名前缀 + 目录归属校验，与本函数无关）。

    本函数做的事：
      - 拒绝空/纯空白路径；
      - 拒绝**目标已是目录**的情形（`--out reports` 而 `reports/` 已存在是最常见的
        用户失误，原实现要到写文件那一步才炸，报"请检查输出路径是否可写"）；
      - 拒绝**父路径是文件**的情形（`makedirs` 必然失败）；
      - 创建缺失的父目录；失败时抛 `OutputError`（中文），不裸抛 `OSError`。

    不保证：不校验符号链接、不校验目录可写性（可写性由真正写入时判定——
    提前探测会引入 TOCTOU，且平台语义差异大）。

    Raises:
        OutputError: 路径非法或父目录无法创建。
    """
    if not isinstance(output_path, str) or not output_path.strip():
        raise OutputError("输出路径不能为空，请指定报告文件路径（如 reports/analysis.html）")

    abs_path = os.path.abspath(output_path)

    if os.path.isdir(abs_path):
        raise OutputError(
            f"输出路径「{abs_path}」是一个已存在的目录，无法作为报告文件名。"
            "请在路径末尾补上文件名（如 reports/analysis.html）。"
        )

    out_dir = os.path.dirname(abs_path)
    if not out_dir:
        return abs_path
    if os.path.exists(out_dir) and not os.path.isdir(out_dir):
        raise OutputError(
            f"输出路径的上级「{out_dir}」是一个文件，无法在其下创建目录。请检查输出路径。"
        )
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as e:
        logger.warning("创建输出目录失败: %s (%s)", out_dir, e)
        raise OutputError(f"无法创建输出目录「{out_dir}」，请检查路径是否可写") from e
    return abs_path


def close_figures(figs=None) -> None:
    """关闭 matplotlib 图窗，释放绘图后端引用（全仓唯一实现）。

    审查 2026-09-19 E19 / 5.5：`cli.py` 与 `services/audit.py` 此前各写一份
    「惰性 import pyplot + 逐个 close」逻辑，现统一到本函数，避免两处漂移。
    放在 `services/` 而非 `engine/_utils.py`：AGENTS.md 规定 cli.py 只依赖
    services/、不得直接依赖 engine/。

    参数:
        figs: 待关闭的 Figure 列表；传 `None` 表示关闭**全部**图窗
            （`plt.close("all")` 语义）；空列表为无操作。

    注意: `Figure` 无 `close()` 方法（matplotlib API），必须经 pyplot 关闭；
    2026-09-01 C-7 教训：`fig.clear()` 不释放绘图后端引用。
    """
    # 函数内导入（审查 2026-09-19 B2）：模块级导入 pyplot 会让
    # `import smartsuite.services.reporter` 在 engine 配置 Agg 之前锁定后端
    # （本机默认为 tkagg），也使只需表格输出的调用方白付绘图栈成本。
    import matplotlib.pyplot as plt

    if figs is None:
        plt.close("all")
        return
    for fig in figs:
        plt.close(fig)


def _fmt_html_cell(x) -> str:
    """HTML 表格数值格式：常规量级保留 4 位小数，微尺度改用 4 位有效数字科学计数。

    审查 2026-09-16 B-5：原 `float_format` 固定 `.4f` 把微尺度列（<5e-5）全部渲染为
    0.0000，抵消引擎 round_for_display → 与 Web/CLI 一致改为尺度感知（≥1e6 维持原 .2e）。

    审查 2026-09-19 E12：判据改用 `numbers.Real` —— `df.to_html(float_format=…)`
    实测把 numpy 标量（如 np.float32）直接传入，而 numpy 2.x 起 np.float32 不再是
    float 子类，旧判据会落入 `str(x)` 分支，把 float32 列渲染成 0.12345679（Web/CLI
    显示 0.1235）→ HTML 报告与其余入口不一致。bool 仍须显式排除（bool ⊂ numbers.Real）。
    """
    if isinstance(x, bool) or not isinstance(x, numbers.Real):
        return str(x)
    # numpy 标量先归一为 Python float：否则 float16 与 1e6 比较会 cast 溢出
    # （RuntimeWarning:“overflow encountered in cast”；本项目 filterwarnings=error
    # 把警告当失败，等同真实缺陷）。归一后下面均只涉及 Python float 运算。
    x = float(x)
    if not math.isfinite(x):
        return f"{x}"
    ax = abs(x)
    if ax >= 1e6:
        return f"{x:.2e}"
    if ax >= 0.5e-4 or ax == 0:
        return f"{x:.4f}"
    return f"{x:.4g}"


def to_excel(result: AnalysisResult, workbook, sheet_name: str = "分析结果") -> str:
    """将分析结果写入 Excel 新 Sheet。

    ⚠️ Deprecated (审查 2026-09-01 A-1)：V1 遗留，仅支持 xlwings 鸭子类型
    workbook 对象（无静态类型约束）。Web UI 和 CLI 入口均不调用此函数；
    如需导出 Excel 报告请使用 ``audit.export_workbook()``（基于 openpyxl）。
    """
    warnings.warn(
        "services.reporter.to_excel 已弃用（依赖 xlwings 运行环境），"
        "请改用 services.audit.export_workbook",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        ws = workbook.sheets.add(sheet_name, after=workbook.sheets[-1])
        r = 1
        ws.range(f"A{r}").value = "分析结论"
        ws.range(f"A{r}").font.bold = True
        r += 1
        ws.range(f"A{r}").value = result.summary
        r += 2
        for name, df in result.tables.items():
            ws.range(f"A{r}").value = name
            ws.range(f"A{r}").font.bold = True
            r += 1
            ws.range(f"A{r}").value = df
            r += len(df) + 2
        for i, fig in enumerate(result.figures):
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=_CHART_DPI, bbox_inches="tight")
            buf.seek(0)
            pic = workbook.sheets.add(f"图表_{i + 1}", after=workbook.sheets[-1])
            pic.pictures.add(
                buf, left=pic.range("A1").left, top=pic.range("A1").top, width=600, height=450
            )
            close_figures([fig])
        return sheet_name
    except Exception as e:
        logger.exception("Excel 输出失败")
        raise OutputError("Excel 输出失败，请检查工作簿是否可写") from e


def to_pdf(result: AnalysisResult, output_path: str) -> str:
    """生成 PDF 报告。"""
    try:
        # 审查 2026-09-01 C-2：路径校验移入 try 内——os.makedirs 失败时
        # 转 OutputError 中文消息，不再裸抛 PermissionError/OSError
        output_path = _prepare_output_path(output_path)
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas

        # ── 注册中文字体，避免 CJK 文本渲染为空白 ──
        _cjk_font_name = None
        _cjk_fonts = [
            ("C:/Windows/Fonts/msyh.ttc", "MSYH"),
            ("C:/Windows/Fonts/simhei.ttf", "SimHei"),
            ("/System/Library/Fonts/PingFang.ttc", "PingFang"),
            ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "NotoCJK"),
        ]
        for _fp, _fn in _cjk_fonts:
            if os.path.exists(_fp):
                try:
                    pdfmetrics.registerFont(TTFont(_fn, _fp))
                    _cjk_font_name = _fn
                    break
                except Exception as e:
                    logger.warning("中文字体注册失败: %s (%s): %s", _fn, _fp, e, exc_info=True)
                    continue

        # 字体选择: CJK 字体仅注册单一 weight, 全部文本使用同一字体;
        # 回退到 Helvetica (无 CJK 字形) 仅在无中文字体时
        _title_font = _cjk_font_name if _cjk_font_name else "Helvetica-Bold"
        _body_font = _cjk_font_name if _cjk_font_name else "Helvetica"

        c = canvas.Canvas(output_path, pagesize=A4)
        w, h = A4
        y = h - 50
        c.setFont(_title_font, 16)
        c.drawString(50, y, f"分析报告: {result.task}")
        y -= 30
        c.setFont(_body_font, 11)
        c.drawString(50, y, result.summary)
        y -= 50

        for name, df in list(result.tables.items())[:5]:
            if y < 200:
                c.showPage()
                y = h - 50
            c.setFont(_title_font, 10)
            c.drawString(50, y, name)
            y -= 18
            # 审查 2026-08-19 Round-2：表格行改用 CJK 字体，避免 Courier 中文静默丢失
            c.setFont(_body_font, 7)
            # 格式化表格行输出
            for _, row in df.head(15).iterrows():
                line = "  ".join(f"{k}={v}" for k, v in row.items())
                c.drawString(55, y, line[:120])
                y -= 12
            y -= 10

        for fig in result.figures:
            if y < 350:
                c.showPage()
                y = h - 50
            buf = io.BytesIO()
            try:
                fig.savefig(buf, format="png", dpi=_PDF_DPI, bbox_inches="tight")
                buf.seek(0)
                c.drawImage(ImageReader(buf), 50, y - 300, width=450, height=300)
            finally:
                # 审查 2026-09-01 C-6：异常路径也关闭 Figure，防止泄漏
                close_figures([fig])
            y -= 320

        c.save()
        return output_path
    except Exception as e:
        logger.exception("PDF 输出失败")
        raise OutputError("PDF 输出失败，请检查输出路径是否可写") from e


def to_ppt(result: AnalysisResult, output_path: str, template_path: str | None = None) -> str:
    """生成 PPT 报告。"""
    try:
        # 审查 2026-09-01 C-2：路径校验移入 try 内（同 to_pdf）
        output_path = _prepare_output_path(output_path)
        from pptx import Presentation
        from pptx.util import Inches

        prs = (
            Presentation(template_path)
            if template_path and os.path.exists(template_path)
            else Presentation()
        )
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

        slide = prs.slides.add_slide(prs.slide_layouts[6])
        txBox = slide.shapes.add_textbox(Inches(1), Inches(2.5), Inches(11), Inches(2))
        txBox.text_frame.text = f"分析报告: {result.task}\n\n{result.summary}"

        for fig in result.figures:
            buf = io.BytesIO()
            try:
                fig.savefig(buf, format="png", dpi=_CHART_DPI, bbox_inches="tight")
                buf.seek(0)
                slide = prs.slides.add_slide(prs.slide_layouts[6])
                slide.shapes.add_picture(buf, Inches(0.5), Inches(0.5), Inches(12), Inches(6.5))
            finally:
                # 审查 2026-09-01 C-6：异常路径也关闭 Figure，防止泄漏
                close_figures([fig])

        prs.save(output_path)
        return output_path
    except Exception as e:
        logger.exception("PPT 输出失败")
        raise OutputError("PPT 输出失败，请检查输出路径是否可写") from e


def to_html(result: AnalysisResult, output_path: str) -> str:
    """生成自包含 HTML 分析报告 (Base64 内嵌图表)。"""
    import base64
    import html as _html

    def _esc(s):
        return _html.escape(str(s))

    try:
        # 审查 2026-09-01 C-2：路径校验移入 try 内（同 to_pdf/to_ppt）
        output_path = _prepare_output_path(output_path)
        html_parts = [
            "<!DOCTYPE html><html lang='zh-CN'><head>",
            "<meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
            "<title>SmartSuite 分析报告</title>",
            "<style>",
            "body{font-family:'Microsoft YaHei','PingFang SC','Noto Sans CJK SC',sans-serif;max-width:1100px;margin:0 auto;padding:20px;color:#333}",
            "h1{color:#2171b5;border-bottom:3px solid #2171b5;padding-bottom:10px}",
            "h2{color:#2171b5;margin-top:30px;border-bottom:1px solid #deebf7}",
            ".summary{background:#deebf7;padding:15px;border-radius:5px;margin:15px 0;font-size:14px}",
            "table{border-collapse:collapse;width:100%;margin:10px 0;font-size:12px}",
            "th{background:#2171b5;color:white;padding:8px 10px;text-align:left}",
            "td{padding:6px 10px;border-bottom:1px solid #deebf7}",
            "tr:nth-child(even){background:#f7fbff}",
            "img{max-width:100%;height:auto;margin:15px 0;border:1px solid #deebf7;border-radius:3px}",
            ".meta{color:#777;font-size:11px;margin-top:30px;border-top:1px solid #deebf7;padding-top:10px}",
            ".status-ok{color:#238b45}.status-error{color:#e31a1c}.status-warn{color:#d94801}",
            "</style></head><body>",
            f"<h1>SmartSuite 分析报告: {_esc(result.task)}</h1>",
        ]

        # 状态 + 结论
        status_class = (
            f"status-{result.status}" if result.status in ("ok", "error") else "status-warn"
        )
        html_parts.append(
            f"<div class='summary'><strong>状态:</strong> "
            f"<span class='{status_class}'>{_esc(result.status)}</span><br>"
            f"<strong>结论:</strong> {_esc(result.summary)}</div>"
        )

        # 警告消息
        if result.messages:
            html_parts.append("<h2>诊断信息</h2><ul>")
            for m in result.messages:
                html_parts.append(f"<li>{_esc(m)}</li>")
            html_parts.append("</ul>")

        # 数据表
        for name, df in result.tables.items():
            html_parts.append(f"<h2>📊 {_esc(name)}</h2>")
            html_parts.append(
                df.head(50).to_html(
                    index=False,
                    classes="table",
                    border=0,
                    escape=True,
                    float_format=_fmt_html_cell,
                )
            )
            if len(df) > 50:
                html_parts.append(
                    f"<p style='color:#777;font-size:11px'>(仅显示前50行，共{len(df)}行)</p>"
                )

        # 图表 (Base64 内嵌，压缩 PNG)
        for i, fig in enumerate(result.figures):
            buf = io.BytesIO()
            try:
                fig.savefig(buf, format="png", dpi=_CHART_DPI, bbox_inches="tight")
                buf.seek(0)
                # PIL 压缩优化
                try:
                    from PIL import Image

                    img = Image.open(buf)
                    out_buf = io.BytesIO()
                    img.save(out_buf, format="PNG", optimize=True)
                    out_buf.seek(0)
                    img_b64 = base64.b64encode(out_buf.read()).decode("utf-8")
                except ImportError:  # pragma: no cover — 见下：PIL 为 matplotlib 硬依赖
                    # PIL 是 matplotlib PNG 管线（backend_agg.print_png
                    # → image.imsave）的硬依赖，savefig 成功即证明 PIL 在场，
                    # 此回退仅在 matplotlib 移除 PIL 依赖的未来版本可达
                    img_b64 = base64.b64encode(buf.read()).decode("utf-8")
                html_parts.append(
                    f"<h2>📈 图表 {i + 1}</h2>"
                    f"<img src='data:image/png;base64,{img_b64}' alt='图表{i + 1}'>"
                )
            finally:
                # 审查 2026-09-01 C-6：异常路径也关闭 Figure，防止泄漏
                close_figures([fig])

        # 元数据
        if result.metadata:
            html_parts.append("<h2>📋 元数据</h2><ul>")
            for k, v in list(result.metadata.items())[:15]:
                val_str = _esc(str(v)[:200])
                html_parts.append(f"<li><strong>{_esc(str(k))}:</strong> {val_str}</li>")
            html_parts.append("</ul>")

        html_parts.append(
            "<div class='meta'>由 SmartSuite 生成 | 工艺数据分析工具箱</div></body></html>"
        )

        html_content = "\n".join(html_parts)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        logger.info("HTML 报告已生成: %s", output_path)
        return output_path
    except Exception as e:
        logger.exception("HTML 报告生成失败")
        raise OutputError("HTML 报告生成失败，请检查输出路径是否可写以及数据格式是否正确。") from e
