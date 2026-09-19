"""Web UI 布局/反馈静态守卫 — 钉住 2026-09-19 视觉检查的修复面。

对应报告 `logs/reports/web-ui-visual-check-2026-09-19.md`：
  高-1 窄屏无响应式（任务区/结果区不可达）
  中-1 VIF 标签误用「分类阈值」
  中-2 random_state 等参数标签泄漏英文键名
  低-2 favicon 404
  低-3 校验反馈仅原生 alert
"""

import re
from pathlib import Path

_WEB = Path(__file__).resolve().parents[2] / "src" / "smartsuite" / "web"
_CSS = _WEB / "static" / "style.css"
_JS = _WEB / "static" / "app.js"
_HTML = _WEB / "templates" / "index.html"


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
    js = _JS.read_text(encoding="utf-8")
    assert "function showToast(" in js
    assert "showToast('请至少选择一个 Y 列')" in js
    assert "showToast('请至少选择一个 X 列')" in js
    assert js.count("alert(") <= 1, "原生 alert 应仅保留 showToast 内的无 DOM 降级"
    assert 'id="toast"' in _HTML.read_text(encoding="utf-8")


def test_web_ui_favicon_referenced():
    """声明图标链接，避免浏览器回退请求 /favicon.ico 产生 404。"""
    html = _HTML.read_text(encoding="utf-8")
    assert 'rel="icon"' in html
    assert (_WEB / "static" / "favicon.svg").exists()


def test_web_ui_param_label_resolution_and_vif_override():
    """random_state 等键需回退 PARAM_META.label；VIF 的 threshold 需任务级覆盖。"""
    js = _JS.read_text(encoding="utf-8")
    assert re.search(
        r"PARAM_LABELS\[k \+ '@' \+ task\] \|\| PARAM_LABELS\[k\] \|\| meta\?\.label \|\| k", js
    ), "标签解析需回退 meta.label，否则 random_state 等显示英文键名"
    assert "'threshold@vif': 'VIF 阈值'" in js, "VIF 阈值不得显示为「分类阈值」"
