// state.js — 列数据、Y/X/类别选择、文件上传与列渲染。
//
// 审查 2026-09-24（P3-3）：从 app.js 抽出。
//
// 设计取舍：三个选择集合以 `const` 导出、**原地增删**（不重新赋值）。
// ES module 的导入绑定对 `let` 的重新赋值是只读的，若导出 `let` 会让
// 其他模块无法更新选择状态；`const` + 原地操作既满足只读绑定语义，
// 也避免引入 setter 样板。

import { escHtml, showToast } from './util.js';
import { fetchWithCsrf } from './api.js';

export let columnData = [];
export let lastFile = null;

export const selectedY = new Set();
export const selectedX = new Set();
export const selectedCat = new Set();

// 按列名关键词猜测"类别列"与"目标列"——中文工艺数据集的常见命名
const catKw = ['日期', '班次', '车间', '机台', '模具', '编号', '操作', '检验',
  '原料', '类型', '批号', '冷却', '循环', '模式', '分区', '保养', '环境',
  '产品代码', '色母', '嵌件', '首件', '外观', '尺寸', '需返工', '报警', '换料'];
const yKw = ['不良', '强度', '伸长', '冲击', '粗糙', '偏差', '波动', '效率'];

/** 统一的列选择状态文案（左栏底部）。 */
export function updateStatus() {
  document.getElementById('col-status').textContent =
    `Y=${selectedY.size} X=${selectedX.size} 类别=${selectedCat.size}`;
}

/**
 * 渲染列清单。
 *
 * 使用 `data-*` 属性 + `addEventListener`，不生成内联处理器 ——
 * 内联 `onclick` 会迫使 CSP 开放 `script-src 'unsafe-inline'`。
 */
export function renderCols() {
  document.getElementById('col-list').innerHTML = columnData.map((c, i) => {
    const safeName = escHtml(c.name);
    return `
    <div class="col-row">
      <span class="col-name" title="${safeName} (${escHtml(c.dtype)}, ${escHtml(c.nunique)} unique, ${escHtml(c.missing)} NA)">${safeName}</span>
      <input type="checkbox" id="cat${i}" data-col="${safeName}" data-role="cat"
        ${selectedCat.has(c.name) ? 'checked' : ''}>
      <span class="tag cat">类</span>
      <input type="checkbox" id="x${i}" data-col="${safeName}" data-role="x"
        ${selectedX.has(c.name) ? 'checked' : ''}>
      <span class="tag x">X</span>
      <input type="checkbox" id="y${i}" data-col="${safeName}" data-role="y"
        ${selectedY.has(c.name) ? 'checked' : ''}>
      <span class="tag y">Y</span>
    </div>`;
  }).join('');

  // 绑定事件 —— 避免内联处理器带来的 XSS 面
  columnData.forEach((c, i) => {
    ['cat', 'x', 'y'].forEach((role) => {
      const cb = document.getElementById(role + i);
      if (cb) {
        cb.addEventListener('change', function () {
          toggle(c.name, role, this.checked);
        });
      }
    });
  });
  updateStatus();
}

/** 勾选/取消某一列的角色（y / x / cat）。 */
export function toggle(name, role, on) {
  const m = role === 'y' ? selectedY : role === 'x' ? selectedX : selectedCat;
  if (on) m.add(name);
  else m.delete(name);
  updateStatus();
}

/**
 * 按列名/类型自动识别角色。
 *
 * pandas 3 起字符串列 dtype 报 `"str"`（与后端 `_is_text_dtype` 口径一致）。
 */
export function autoDetect() {
  selectedY.clear();
  selectedX.clear();
  selectedCat.clear();
  columnData.forEach((c) => {
    const lo = c.name.toLowerCase();
    const isCat = catKw.some((k) => lo.includes(k.toLowerCase()))
      || ['object', 'string', 'str', 'bool'].includes(c.dtype);
    if (isCat) selectedCat.add(c.name);
    if (yKw.some((k) => lo.includes(k.toLowerCase()))) {
      selectedY.add(c.name);
      return;
    }
    if (['float64', 'int64'].includes(c.dtype) && !isCat) selectedX.add(c.name);
  });
  renderCols();
}

/** 全选 Y 或全选 X（仅数值列；选 X 时排除已作 Y 的列）。 */
export function setAll(role) {
  columnData.forEach((c) => {
    if (['float64', 'int64'].includes(c.dtype)) {
      if (role === 'y') selectedY.add(c.name);
      if (role === 'x' && !selectedY.has(c.name)) selectedX.add(c.name);
    }
  });
  renderCols();
}

/** 清空全部列选择。 */
export function clearAll() {
  selectedY.clear();
  selectedX.clear();
  selectedCat.clear();
  renderCols();
}

/** 重置到"未选择文件"的界面状态。 */
export function resetFileUi() {
  document.getElementById('filename').textContent = '未选择文件';
  document.getElementById('shape').textContent = '';
}

/**
 * 上传数据文件（含前端预检与编码声明）。
 *
 * 审查 2026-08-19 M3：前端预检 50MB，避免 413 HTML 响应被显示为"网络错误"。
 * ADR-0004：可选显式编码；空值 = 后端自动（BOM → utf-8-sig → utf-8 → gbk）。
 *
 * `onLoaded` 在列数据更新后回调（由 app.js 传入以刷新参数面板，避免本模块
 * 反向依赖参数面板模块）。
 */
export async function uploadFile(f, onLoaded) {
  lastFile = f;
  document.getElementById('filename').textContent = f.name;
  document.getElementById('shape').textContent = '上传中...';
  if (f.size > 50 * 1024 * 1024) {
    showToast('文件超过 50MB 限制，请减少数据量后重试');
    document.getElementById('file-input').value = '';
    lastFile = null;
    resetFileUi();
    return;
  }
  const fd = new FormData();
  fd.append('file', f);
  const enc = document.getElementById('encoding').value;
  if (enc) fd.append('encoding', enc);
  try {
    const r = await fetchWithCsrf('/api/upload', { method: 'POST', body: fd });
    let d = {};
    try {
      d = await r.json();
    } catch (err) {
      /* 非 JSON 响应（如 413 HTML） */
    }
    if (!r.ok) {
      showToast('上传失败: ' + (d.error || (r.status === 413 ? '文件超过 50MB 限制' : '未知错误')));
      resetFileUi();
      return;
    }
    columnData = d.columns || [];
    document.getElementById('shape').textContent = d.shape ? `(${d.shape.join(' × ')})` : '';
    renderCols();
    autoDetect();
    if (typeof onLoaded === 'function') onLoaded();
  } catch (err) {
    showToast('上传失败: 网络错误或服务器不可达');
    resetFileUi();
  }
}
