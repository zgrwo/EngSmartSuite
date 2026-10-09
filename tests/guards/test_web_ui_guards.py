"""Web UI 布局/反馈静态守卫 — 钉住 2026-09-19 视觉检查与 2026-09-24 模块化的修复面。

对应报告 `logs/reports/web-ui-visual-check-2026-09-19.md`：
  高-1 窄屏无响应式（任务区/结果区不可达）
  中-1 VIF 标签误用「分类阈值」
  中-2 random_state 等参数标签泄漏英文键名
  低-2 favicon 404
  低-3 校验反馈仅原生 alert

对应第三轮复核 P3-3（2026-09-24）：前端由单文件拆为 ES modules。
本文件的读取方式随之改为 `static/*.js` 全量拼接，并新增
「无内联事件处理器」断言（模块化后函数不再是全局，内联 `onclick` 必然失效）。
"""

import re
from pathlib import Path

_WEB = Path(__file__).resolve().parents[2] / "src" / "smartsuite" / "web"
_CSS = _WEB / "static" / "style.css"
_STATIC = _WEB / "static"
_HTML = _WEB / "templates" / "index.html"


def _all_js() -> str:
    """拼接 `static/` 下全部 JS（模块化后单一 app.js 不再是唯一载体）。

    审查 2026-09-24（P3-3）：原实现只读 `app.js`。拆模块后
    `showToast` / `PARAM_LABELS` 等迁出，只读单文件会让本守卫**静默失效**——
    与 `verify_frontend_params.py` 同一类缺口，处理方式也一致。
    """
    files = sorted(_STATIC.glob("*.js"))
    assert files, f"static/ 下未找到任何 JS 文件: {_STATIC}"
    return "\n".join(p.read_text(encoding="utf-8") for p in files)


def _js_code_lines(js: str) -> list[str]:
    """去掉 `//` 行注释后再返回各行 —— 断言针对**代码**，不针对注释里的字样。

    审查 2026-09-24：守卫首版用裸正则/裸计数扫描全文，连续命中注释里的
    "onclick"、"alert(" 字样 → 假阳性。类似地 app.py 的 CSP docstring 里提到
    `'unsafe-inline'` 也被误判。规律：**扫代码的断言必须先剥离注释**。
    """
    return [ln.split("//", 1)[0] for ln in js.splitlines()]


def test_web_ui_has_narrow_screen_breakpoints():
    """≤900/600px 断点必须存在，否则 390px 任务区被裁、结果不可达。"""
    css = _CSS.read_text(encoding="utf-8")
    assert "@media (max-width: 900px)" in css, "缺窄屏断点：三栏需改纵向堆叠"
    assert "@media (max-width: 600px)" in css, "缺手机断点：头部需精简"
    # 窄屏下中栏/结果区不得再 overflow:hidden（否则内容不可滚动到达）
    narrow = css.split("@media (max-width: 900px)")[1].split("@media (max-width: 600px)")[0]
    assert "overflow: visible" in narrow, "窄屏中断栏/结果区应改为可见溢出（随主区滚动）"


def test_web_ui_validation_uses_in_page_toast():
    """校验反馈必须走页内 toast；原生 alert 仅允许 showToast 内部的降级兜底。"""
    js = _all_js()
    # 允许 `export function`（P3-3 起 showToast 在 util.js 中作为模块导出）
    assert re.search(r"function showToast\(", js), "未找到 showToast 定义"
    assert "showToast('请至少选择一个 Y 列')" in js
    assert "showToast('请至少选择一个 X 列')" in js
    # 剥注释后计数：注释里说明 alert 降级策略属正当文档，不应计入
    code = "\n".join(_js_code_lines(js))
    assert code.count("alert(") <= 1, (
        f"原生 alert 应仅保留 showToast 内的无 DOM 降级，实际 {code.count('alert(')} 处"
    )
    assert 'id="toast"' in _HTML.read_text(encoding="utf-8")


def test_web_ui_favicon_referenced():
    """声明图标链接，避免浏览器回退请求 /favicon.ico 产生 404。"""
    html = _HTML.read_text(encoding="utf-8")
    assert 'rel="icon"' in html
    assert (_STATIC / "favicon.svg").exists()


def test_web_ui_param_label_resolution_and_vif_override():
    """标签解析的回退链：**接口 → 键名**（手写字典与 PARAM_META 已于第二十八轮删除）。

    审查 2026-09-24（P4 步骤④，第二十八轮）：派生覆盖已达 114/114 个参数槽位，
    故 `PARAM_LABELS` / `PARAM_HINTS` / `PARAM_META` 全部删除（共 214 行）。
    本守卫随之更新为校验**当前**契约，并**反向断言**那三份手写字典不得复活。

    各层的必要性：
      - 接口层：派生自 `Spec`，是**唯一**的标签来源；
      - 键名层：最终兜底，保证接口失败时不出现空白标签。
    """
    js = _all_js()

    # ① 两个解析函数存在
    assert re.search(r"function paramLabel\(k, task\)", js), "缺少 paramLabel()"
    assert re.search(r"function paramHint\(k, task\)", js), "缺少 paramHint()"

    # ② 标签回退链：接口 → 键名
    m = re.search(r"function paramLabel\(k, task\) \{(.*?)\n\}", js, re.S)
    assert m, "paramLabel 实现未找到"
    body = m.group(1)
    assert "_apiLabels" in body, f"标签解析缺接口层: {body!r}"
    assert "|| k" in body, f"标签解析缺键名兜底: {body!r}"

    # ③ **手写平行字典不得复活**（这是本步骤的成果，需回归保护）
    for dead in ("PARAM_LABELS", "PARAM_HINTS", "PARAM_META"):
        assert f"const {dead} = {{" not in js, (
            f"{dead} 又出现在前端 —— 它与 Spec 派生重复，会再次产生"
            "「改了一处忘了另一处」的不一致（P4 步骤④ 已删除）"
        )

    # ④ 列选择器仍保留（它是纯 UI 关注点，不属于 Spec，见 COLUMN_PARAMS 的说明）
    assert "COLUMN_PARAMS" in js, "列选择器表被误删 —— 列参数会退化成文本框"

    # ⑤ VIF 的任务级标签由后端下发（不再是前端字面量）
    from smartsuite.services.param_labels import derive_param_labels

    assert derive_param_labels().get("threshold@vif") == "VIF 阈值", (
        "VIF 阈值不得显示为「分类阈值」—— 任务级覆盖必须由后端派生提供"
    )


# ── P3-3（2026-09-24）：模块化后的新契约 ──────────────────────────────


def test_no_inline_event_handlers_in_html():
    """模板中不得再有内联事件处理器（`onclick=` 等）。

    模块化后函数不再是全局，内联 `onclick="foo()"` 会抛
    `ReferenceError: foo is not defined`（点击即坏，且无浏览器测试兜底）。
    改为 `data-*` 属性 + 事件委托后，本断言保证不会回流。
    """
    html = _HTML.read_text(encoding="utf-8")
    found = re.findall(r"\son[a-z]+\s*=", html)
    assert not found, (
        f"index.html 仍有内联事件处理器 {sorted(set(found))}；"
        "请改用 data-* 属性 + 事件委托（模块化后全局函数已不存在）"
    )


def test_no_inline_event_handlers_in_js_templates():
    """JS 模板字面量里也不得生成内联处理器（动态按钮同样受影响）。

    剥注释后扫描：注释里提及 `onclick`（说明历史）不算违规。
    """
    code = "\n".join(_js_code_lines(_all_js()))
    found = re.findall(r"onclick\s*=", code)
    assert not found, f"JS 代码中仍有 {len(found)} 处 onclick= 模板；请改为 data-action + 委托"


def test_index_html_loads_entry_as_module():
    """入口脚本必须声明 `type="module"`（否则 import/export 语法直接报错）。"""
    html = _HTML.read_text(encoding="utf-8")
    m = re.search(r"<script[^>]*\ssrc=[\"'][^\"']*app\.js[^\"']*[\"'][^>]*>", html)
    assert m, "index.html 未引用 app.js 入口"
    assert 'type="module"' in m.group(0), (
        f'入口脚本缺 type="module"，模块语法不会被浏览器解析: {m.group(0)}'
    )


def test_frontend_is_modularized_into_several_files():
    """P3-3 的成果断言：前端已拆为多个模块（防止回退成单文件巨石）。"""
    files = sorted(p.name for p in _STATIC.glob("*.js"))
    assert len(files) >= 3, f"前端模块数不足（期望 ≥3）：{files}"
    assert "app.js" in files, "入口 app.js 必须存在"


def _csp_directives() -> dict[str, str]:
    """从 app.py 的**实际 CSP 字符串字面量**解析指令表。

    只取紧随 `"Content-Security-Policy",` 之后的那段字符串拼接，
    不扫 docstring —— 否则注释里提到的 `'unsafe-inline'` 会造成假阳性。
    """
    src = (_WEB / "app.py").read_text(encoding="utf-8")
    m = re.search(
        r'"Content-Security-Policy",\s*((?:"[^"]*"\s*)+)',
        src,
    )
    assert m, "app.py 中未找到 CSP 指令字符串字面量"
    csp = " ".join(re.findall(r'"([^"]*)"', m.group(1)))
    out: dict[str, str] = {}
    for part in csp.split(";"):
        part = part.strip()
        if not part:
            continue
        name, _, value = part.partition(" ")
        out[name] = value.strip()
    return out


def test_csp_allows_no_inline_script():
    """CSP 的 `script-src` 不得再含 `'unsafe-inline'`（内联脚本已清零）。

    审查 2026-09-24（P3-3）：原 CSP 被迫开 `'unsafe-inline'` 是因为有 11 处
    内联 `onclick`。这些已改为事件委托，故脚本侧的 `unsafe-inline` 可以去掉 ——
    这是本项重构的**安全收益**，用断言锁住防回退。

    `style-src` 的 `'unsafe-inline'` 另有原因（渲染结果含 `style="…"` 行内样式，
    且不属本项范围），本断言只管 script-src。
    """
    directives = _csp_directives()
    assert "script-src" in directives, f"CSP 缺 script-src 指令：{directives}"
    assert "'unsafe-inline'" not in directives["script-src"], (
        f"script-src 仍含 'unsafe-inline'（内联脚本已清零，应移除以获得 XSS 纵深）："
        f"{directives['script-src']}"
    )


def test_csp_keeps_other_hardening_directives():
    """CSP 收紧 script-src 时不得顺带丢掉既有的其它加固指令。"""
    directives = _csp_directives()
    assert directives.get("default-src") == "'self'"
    assert "data:" in directives.get("img-src", ""), "图表以 data: URI 内嵌，必须保留"
    assert directives.get("frame-ancestors") == "'none'", "缺 frame-ancestors（点击劫持防线）"


def test_csp_allows_no_inline_style():
    """CSP 的 `style-src` 不得含 `'unsafe-inline'`（内联样式已清零）。

    审查 2026-09-24（第二十九轮）：CSP3 起 `style-src` 的 `'unsafe-inline'`
    **同样覆盖行内 `style="…"` 属性**，故要收紧它必须先把行内样式全部改成 class。
    本轮做了这件事（7 处：display × 3、错误色 × 3、矩阵着色 × 1、分组背景色 × 1），
    故 `style-src` 收紧为 `'self'`。本断言锁住它防回退。
    """
    directives = _csp_directives()
    assert "style-src" in directives, f"CSP 缺 style-src 指令：{directives}"
    assert "'unsafe-inline'" not in directives["style-src"], (
        f"style-src 仍含 'unsafe-inline'（行内样式已清零，应移除以获得纵深）："
        f"{directives['style-src']}"
    )


def test_no_inline_style_attributes_anywhere():
    """模板与前端 JS 里**不得再出现**行内 `style="…"`（那是 style-src 收紧的前提）。

    扫描范围：`templates/*.html` + `static/*.js`。行内样式会让 CSP 的
    `style-src 'self'` 直接阻止该属性生效 —— 表现为"某个高亮/隐藏静默失效"，
    且**不会有任何报错**（CSP 违规只在控制台），故必须静态拦下。
    """
    import re

    offenders: list[str] = []
    targets = list((_WEB / "templates").glob("*.html")) + list(_STATIC.glob("*.js"))
    for f in targets:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            # 剥离注释后再扫（模板用 <!-- -->，JS 用 //）
            code = line.split("//", 1)[0] if f.suffix == ".js" else line
            if re.search(r"""style\s*=\s*["']""", code):
                offenders.append(f"{f.name}:{i}")
    assert not offenders, (
        f"以下位置仍有行内 style 属性，会让 CSP 的 style-src 'self' 静默失效：{offenders}"
    )


def test_wf_group_colors_match_engine():
    """`style.css` 里的分组背景色必须与引擎 `GROUP_COLORS` **逐项一致**。

    为什么需要这条：分组色原是模板经 `style="--group-bg: {{ 色值 }}"` 注入的
    （值来自引擎常量，不可能不一致）。第二十九轮为收紧 CSP 改为**静态 CSS 规则**，
    于是颜色出现了第二份来源 —— 引擎改了色值而 CSS 没跟上时，
    界面只是"颜色不好看"，**不会有任何测试失败**。本断言补上这条链路。
    """
    import re

    from smartsuite.core.constants import GROUP_COLORS

    css = _CSS.read_text(encoding="utf-8")
    for group, color in GROUP_COLORS.items():
        pattern = rf'\.wf-group\[data-group="{re.escape(group)}"\]\s*\{{\s*background:\s*{re.escape(color)};'
        assert re.search(pattern, css), (
            f"分组「{group}」的背景色 {color} 未出现在 style.css 的静态规则里 —— "
            f"引擎 GROUP_COLORS 与前端 CSS 已漂移（请同步两者）"
        )
    # 反向：CSS 里不得有引擎没有的分组色（防止删了分组却留下孤儿规则）
    css_groups = set(re.findall(r'\.wf-group\[data-group="([^"]+)"\]', css))
    assert css_groups == set(GROUP_COLORS), (
        f"CSS 分组与引擎 GROUP_COLORS 不一致：仅 CSS 有 {css_groups - set(GROUP_COLORS)}，"
        f"仅引擎有 {set(GROUP_COLORS) - css_groups}"
    )


def test_html_has_no_inline_style_block():
    """不得出现内联 `<style>` 块（那会迫使 style-src 开 unsafe-inline）。

    行内 `style="…"` 属性不受此限（CSP3 下 style-src 不覆盖行内属性）。
    """
    html = _HTML.read_text(encoding="utf-8")
    assert "<style" not in html, "index.html 含内联 <style> 块，请移入 style.css"


# ── 事件委托的静态一致性（P3-3 的主要残余风险）────────────────────────
# 委托把「哪个动作对应哪个函数」变成字符串契约：HTML/模板写
# `data-action="pick-file"`，app.js 的 ACTIONS 表必须恰好有 `'pick-file'` 键。
# 拼写不一致（pick-file vs pick_file）不会在静态检查里暴露，
# 但点击时**静默无效** —— 正是本组断言要拦的。


def _declared_actions_in_js() -> set[str]:
    """app.js 的 `ACTIONS` 映射表里声明的动作名。"""
    js = _all_js()
    m = re.search(r"const ACTIONS\s*=\s*\{(.*?)\n\};", js, re.DOTALL)
    assert m, "未找到 ACTIONS 映射表（事件委托表应集中声明）"
    body = "\n".join(_js_code_lines(m.group(1)))
    return set(re.findall(r"['\"]([a-z][\w-]*)['\"]\s*:", body))


def _used_actions_in_markup() -> set[str]:
    """模板与 JS 模板字面量里 `data-action="…"` 实际使用的动作名。"""
    html = _HTML.read_text(encoding="utf-8")
    js = "\n".join(_js_code_lines(_all_js()))
    return set(re.findall(r'data-action=["\']([\w-]+)["\']', html + "\n" + js))


def test_all_data_actions_have_handlers():
    """每个 `data-action` 都必须有对应处理函数（否则点击静默无效）。"""
    declared = _declared_actions_in_js()
    used = _used_actions_in_markup()
    missing = sorted(used - declared)
    assert not missing, (
        f"以下 data-action 在模板/JS 中使用但 ACTIONS 表未声明处理函数：{missing}；"
        f"已声明：{sorted(declared)}"
    )


def test_no_unused_action_handlers():
    """ACTIONS 表里的每个动作都必须真的被用到（防止死代码与拼写漂移残留）。"""
    declared = _declared_actions_in_js()
    used = _used_actions_in_markup()
    unused = sorted(declared - used)
    assert not unused, f"ACTIONS 表声明了但无处使用的动作：{unused}"


def test_action_names_use_kebab_case():
    """动作名统一 kebab-case（`run-task` 而非 `run_task`），与既有写作一致。"""
    for name in _declared_actions_in_js() | _used_actions_in_markup():
        assert re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", name), (
            f"动作名 {name!r} 不符合 kebab-case 约定"
        )


def test_run_task_buttons_carry_task_name():
    """工作流按钮必须带 `data-task`（委托靠它取任务名，缺失则 runAnalysis(undefined)）。"""
    html = _HTML.read_text(encoding="utf-8")
    runs = re.findall(r'<button[^>]*data-action="run-task"[^>]*>', html)
    assert runs, "index.html 未找到 run-task 按钮"
    for tag in runs:
        assert "data-task=" in tag, f"run-task 按钮缺 data-task 属性: {tag}"
    # Jinja 插值的任务名必须来自 task 循环变量
    assert re.search(r'data-task="\{\{\s*t\s*\}\}"', html), "data-task 未由 Jinja 注入任务名"


class TestStaticAssetsAreNotStronglyCached:
    """静态资源必须禁用强缓存，否则"只改了子模块"那一轮用户会跑旧面板（审查 P3-5）。

    起因：`index.html` 只给入口 `app.js?v=12` 带了版本号，而 ES module 的子模块
    import 是**静态 specifier**（`import { fmtCellNum } from './util.js'`）——
    版本号**注入不进去**。于是只改 `params.js` 时，老用户浏览器继续用缓存的旧
    params.js，而 app.js 已是新的：面板行为与代码不一致，**且无任何报错**。

    修法是釜底抽薪：`SEND_FILE_MAX_AGE_DEFAULT = 0`（等价 `Cache-Control: no-cache`
    ＋ ETag 条件请求），一次覆盖入口与全部子模块 —— 比逐个文件加 `?v=` 可靠
    （后者漏一个就复发）。
    """

    def test_flask_static_cache_is_disabled(self):
        src = (_WEB / "app.py").read_text(encoding="utf-8")
        assert re.search(r'SEND_FILE_MAX_AGE_DEFAULT"\s*\]\s*=\s*0\b', src), (
            "app.py 必须设置 SEND_FILE_MAX_AGE_DEFAULT = 0：ES module 子模块无法注入"
            "版本号，强缓存会让老用户继续跑旧的 params.js/util.js（无报错、难排查）"
        )

    def test_versioned_entry_alone_is_not_treated_as_sufficient(self):
        """反向锚点：入口带 `?v=` 是必要但不充分的 —— 若有人删掉 no-cache 只留版本号，
        上一条会红；本用例把"为什么不够"钉在测试里，防止被当作冗余配置删掉。"""
        html = _HTML.read_text(encoding="utf-8")
        assert re.search(r"app\.js\?v=", html) or re.search(r"app\.js\?v=", html), (
            "index.html 的入口仍应带版本号（缓存失效的第一道保险）"
        )
        js = "\n".join(p.read_text(encoding="utf-8") for p in sorted(_STATIC.glob("*.js")))
        # 子模块 import 是静态 specifier —— 这一行就是"版本号注不进去"的证据
        assert re.search(r"from\s+['\"]\./\w+\.js['\"]", js), (
            "预期存在静态子模块 import；若前端改为动态 import 且能注入版本号，"
            "本用例与 no-cache 的必要性都可重新评估"
        )
