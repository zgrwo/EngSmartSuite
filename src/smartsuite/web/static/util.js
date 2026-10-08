// util.js — 无依赖工具函数：HTML 转义、数值展示、页内提示。
//
// 审查 2026-09-24（P3-3）：从 app.js 抽出。此模块**不依赖任何其他模块**，
// 也不触碰 DOM 全局状态，便于单独复用与审查。

/**
 * HTML 转义 —— 所有插入 innerHTML 的外部字符串必须先经此函数。
 *
 * 覆盖 `& < > " '` 五个字符：前四个防标签/属性注入，单引号防属性值用 `'`
 * 包裹时被提前闭合。服务端返回的列名、消息、summary 都走这里。
 */
export const escHtml = (s) =>
  String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

// 页内提示（替代原生 alert；3.2s 自动消失，无 DOM 时回退 alert）
let _toastTimer = null;

/**
 * 页内 toast 提示。
 *
 * 无 `#toast` 元素时回退到浏览器原生弹窗 —— 这是全项目**唯一**允许调用原生
 * 弹窗的位置（由 tests/guards/test_web_ui_guards.py 断言其出现次数 ≤1）。
 */
export function showToast(msg) {
  const el = document.getElementById('toast');
  if (!el) {
    alert(msg);
    return;
  }
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove('show'), 3200);
}

/**
 * 表格数值展示 —— 量纲感知。
 *
 * 审查 2026-09-16 B-5：固定 `toFixed(4)` 会把微尺度值（<5e-5）整列显示为
 * `0.0000`（抵消引擎 `round_for_display` 的尺度感知口径）；微尺度改用
 * 4 位有效数字科学计数，常规量级行为不变。
 */
export function fmtCellNum(v) {
  if (typeof v !== 'number' || !Number.isFinite(v)) return String(v);
  if (v === 0) return '0.0000';
  return Math.abs(v) < 5e-5 ? v.toExponential(3) : v.toFixed(4);
}
