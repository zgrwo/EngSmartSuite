// params.js — 参数面板：默认值 / 元数据 / 标签 / 提示 + 参数控件与因子·请求行编辑器。
//
// 审查 2026-09-24（P3-3）：从 app.js 整块抽出（原第 186-760 行）。
// 本模块只负责「把 task 变成参数表单、再把表单读回参数对象」，
// 不发请求、不碰分析状态（那些属 app.js）。
//
// 依赖：util.js（转义）、state.js（列数据与类别选择，供控件生成使用）。
//
// 审查 2026-09-24（P4 步骤④）：**默认值不再在本文件维护**。
// 原先这里有一份 42 任务的 `TASK_PARAMS` 字面量，与后端
// `services/task_spec.py::TASK_SPECS` 的 `default_params` 逐字重复，
// 靠 scripts/verify_frontend_params.py 每次门禁比对来维持一致（手工一致性）。
// 现改为由 `/api/tasks` 下发 → `hydrateParams()` 灌入本模块缓存，
// 后端成为唯一事实源，**结构上不可能不一致**。

import { escHtml } from './util.js';
import { columnData, selectedCat } from './state.js';

/**
 * 各任务的参数默认值，由 `/api/tasks` 下发（键 = 任务名，值 = 默认值对象）。
 *
 * 不 export：外部只应通过 `hasParams(task)` / `defaultParams(task)` 读取，
 * 避免有代码绕过 `hydrateParams()` 的时序假设直接取用空对象。
 */
let TASK_PARAMS = {};

/** `/api/tasks` 是否已灌入。未灌入时参数面板会退化为"无参数任务"。 */
let _hydrated = false;

/** 灌入完成（或失败）时 resolve 的 Promise —— 供调用方等待，消除启动竞态。 */
let _resolveReady;
const _ready = new Promise((resolve) => {
  _resolveReady = resolve;
});

/**
 * 由 `/api/tasks` 派发的参数标签/提示/选项（来自各任务的 `Spec` 声明）。
 *
 * 审查 2026-09-24（P4 步骤④，第二十八轮）：**前端的手写平行字典已全部删除**
 * （原 `PARAM_LABELS` 36 行 + `PARAM_HINTS` 11 行 + `PARAM_META` 167 行）。
 * 前提是后端派生覆盖已达 **114/114** 个默认参数槽位 —— 断言见
 * `tests/engine/test_param_migration_batch8.py::TestDerivationCoversEverySlot`。
 *
 * 顺带修掉了手写字典里**本身就写错的提示**：
 *   - `ranges` 原写「格式: 料温:180,220; 模具温度:40,80」（字符串格式），
 *     而引擎实际要的是 **dict** `{列名: (下限, 上限)}`；
 *   - `objectives` 原写「格式: 强度:maximize; ...」（字符串），
 *     而引擎要的是**字典列表** `[{"col":..., "direction":...}]`。
 * 现两者的提示都来自 `Spec`，与引擎实际读取的形态一致。
 */
let _apiLabels = {};
let _apiHints = {};
let _apiOptions = {};
// 列需求集合（第 42 轮）：**由 /api/tasks 灌入**，命名带 `_api` 前缀以自证来源。
// 前端不得再手写这类集合 —— 见 tests/guards/test_task_requirements_ssot.py
let _apiNoTargetTasks = new Set();
let _apiYOnlyTasks = new Set();
let _apiXOptionalTasks = new Set();

/**
 * 该参数的中文标签：**接口 → 参数名本身**（最后兜底保证不空白）。
 *
 * 审查 2026-09-24（P4 步骤④，第二十八轮）：原回退链是
 * `接口 → PARAM_LABELS → 参数名`。派生覆盖已达 **114/114** 个参数槽位
 * （断言见 `tests/engine/test_param_migration_batch8.py`），
 * `PARAM_LABELS` 已成死兜底，故删除。保留键名兜底以防接口失败时界面空白。
 */
function paramLabel(k, task) {
  return _apiLabels[k + '@' + task] || _apiLabels[k] || k;
}

/** 该参数的填写提示：接口 → 空串（无提示即不显示）。`PARAM_HINTS` 已随派生覆盖满而删除。 */
function paramHint(k, task) {
  return _apiHints[k + '@' + task] || _apiHints[k] || '';
}

/**
 * 该参数的下拉选项 `[[值, 文案], ...]`：接口 → 无。
 *
 * 返回 `null`（而非空数组）表示"没有选项"——调用方据此判断该用哪种控件：
 * 有选项→下拉框，无选项→文本框/数字框。空数组会让下拉框渲染成空白。
 * 审查 2026-09-24（P4 步骤④，第二十八轮）：删除了 `PARAM_META.options` 兜底层。
 */
function paramOptions(k, task) {
  const opts = _apiOptions[k + '@' + task] || _apiOptions[k];
  return opts && opts.length ? opts : null;
}

/**
 * 等待默认值就绪（成功或失败都会 resolve，不会 reject）。
 *
 * 为什么需要：`/api/tasks` 是异步请求。若用户在响应到达前就点了任务，
 * `hasParams()` 会返回 `false` → 面板不显示、任务直接用引擎默认值开跑
 * （用户以为"这个任务没有参数"）。故点击处理需先 `await paramsReady()`。
 *
 * 失败时也会 resolve —— 此时 `paramsHydrated()` 为 `false`，调用方可据此提示，
 * **不应**无限等待。
 *
 * @returns {Promise<boolean>} 是否成功灌入
 */
/** 无需目标列 Y 的任务（后端派生）。 */
export function noTargetTasks() {
  return _apiNoTargetTasks;
}

/** 只需 Y 列即可运行的任务（后端派生）。 */
export function yOnlyTasks() {
  return _apiYOnlyTasks;
}

/** X 列可选的任务（后端派生）。 */
export function xOptionalTasks() {
  return _apiXOptionalTasks;
}

export function paramsReady() {
  return _ready;
}

/**
 * 用 `/api/tasks` 的返回体灌入默认值。
 *
 * 由 app.js 在启动时调用一次。失败时保持未灌入状态并返回 `false` ——
 * 调用方应提示用户（当前会退化为所有任务都不显示参数面板，属**明显可见**
 * 的降级，不会静默产出错误参数）。
 *
 * @param {{params?: Object}} payload `/api/tasks` 的 JSON
 * @returns {boolean} 是否成功灌入
 */
export function hydrateParams(payload) {
  const params = payload && payload.params;
  if (!params || typeof params !== 'object') {
    _resolveReady(false);
    return false;
  }
  TASK_PARAMS = params;
  // 参数标签/提示/选项（P4 步骤④，第二十八轮）：这是**唯一**来源 ——
  // 前端手写字典已全部删除，故派发缺失时只会回退到参数名本身（不空白）。
  _apiLabels = (payload && payload.param_labels) || {};
  _apiHints = (payload && payload.param_hints) || {};
  _apiOptions = (payload && payload.param_options) || {};
  // ── 运行前校验的列需求（第 42 轮）──
  // 原先这三组写死在 `app.js` 里（`_noTargetNeeded` / `_apiYOnlyTasks` /
  // `_apiXOptionalTasks`）。新增任务若忘改，表现为**静默不可用**
  // （用户看到「请至少选择一个 X 列」）—— 不报错、不失败，最难发现。
  // 现由 `services/task_spec.py::TASK_SPECS` 声明 → 派生 → `/api/tasks` 下发。
  //
  // 降级语义：本项缺失时保持空集 → 所有任务都要求 Y 与 X 都选
  // （比"放行然后后端报错"更保守，且**明显可见**：用户会看到提示）。
  _apiNoTargetTasks = new Set((payload && payload.no_target_tasks) || []);
  _apiYOnlyTasks = new Set((payload && payload.y_only_tasks) || []);
  _apiXOptionalTasks = new Set((payload && payload.x_optional_tasks) || []);
  _hydrated = true;
  _resolveReady(true);
  return true;
}

/**
 * 标记加载失败（网络错误等），让 `paramsReady()` 的等待者得以继续。
 *
 * 必须调用，否则任何 `await paramsReady()` 都会永久挂起 —— 那会导致
 * 点击任务毫无反应（比"没参数面板"更糟）。
 */
export function paramsLoadFailed() {
  _resolveReady(false);
}

/** 默认值是否已从服务端加载完成。 */
export function paramsHydrated() {
  return _hydrated;
}

/** 该任务是否有参数面板（有参数才显示面板等待用户编辑）。 */
export function hasParams(task) {
  return Boolean(TASK_PARAMS[task] && Object.keys(TASK_PARAMS[task]).length);
}

/** 该任务的默认值副本（调用方修改不应影响缓存）。 */
export function defaultParams(task) {
  return { ...(TASK_PARAMS[task] || {}) };
}

// 参数元数据：定义类型和下拉选项
// 参数标签（中文显示名）
/**
 * 需要**列选择器**（而非文本框）的参数 —— **纯 UI 关注点，不属于 `Spec`**。
 *
 * 为什么只有这一份手写表：控件类型里
 *   - 「枚举 → 下拉框」可由后端下发的 `param_options` 推出（`Choice` 字段）；
 *   - 「数值 → 数字框」可由默认值的 JS 类型推出（`typeof v === 'number'`）；
 *   - **但「该选哪一列」取决于运行时加载的数据列，`Spec` 无从知晓** ——
 *     故这一条必须留在前端，它也不是"与后端重复的事实"。
 *
 * 审查 2026-09-24（P4 步骤④，第二十八轮）：原 `PARAM_META`（167 行）里
 * 23 条 `select` 条目的标签与选项**已被后端派生完全覆盖**（114/114 个参数槽位），
 * 属死兜底，故整表删除，只保留这 4 个列选择器。
 */
const COLUMN_PARAMS = new Set(['group_col', 'part_col', 'operator_col', 'time_col']);

// inverse_solve：列角色勾选 + 反演请求行录入（角色前缀与引擎 DEFAULT_PREFIXES 一致）
export const INVERSE_ROLE_KEYS = ['incoming_cols', 'variable_cols', 'fixed_cols', 'output_cols', 'target_cols'];
export const INVERSE_PREFIXES = {
  incoming_cols: ['incoming', '来料'],
  variable_cols: ['variable', '变量', '可调'],
  fixed_cols: ['fixed', '固定'],
  output_cols: ['output', '输出'],
  target_cols: ['target', '目标'],
};

// ── DOE 因子编辑器（每个因子单独一行：因子名 + 水平）──
export function factorRowHtml(name = '', levels = '') {
  return `<div class="factor-row">
    <input class="factor-name" placeholder="因子名" value="${escHtml(name)}">
    <input class="factor-levels" placeholder="水平(逗号分隔)" value="${escHtml(levels)}">
    <button type="button" data-action="remove-factor" class="btn-sm" title="删除">✕</button>
  </div>`;
}

export function buildFactorEditor() {
  return `<div class="param-item">
    <label class="param-label">因子定义</label>
    <div class="param-hint">每个因子一行：因子名 + 水平（逗号分隔）。数值水平自动转数字，文本水平原样保留。</div>
    <div id="factor-editor">${factorRowHtml()}</div>
    <button type="button" data-action="add-factor" class="btn-sm">+ 添加因子</button>
  </div>`;
}

export function addFactorRow(name = '', levels = '') {
  const ed = document.getElementById('factor-editor');
  if (ed) ed.insertAdjacentHTML('beforeend', factorRowHtml(name, levels));
}

export function removeFactorRow(btn) {
  const ed = document.getElementById('factor-editor');
  const rows = ed ? ed.querySelectorAll('.factor-row') : [];
  if (rows.length <= 1) {
    // 至少保留一行，清空内容
    rows[0].querySelector('.factor-name').value = '';
    rows[0].querySelector('.factor-levels').value = '';
    return;
  }
  btn.closest('.factor-row').remove();
}

export function collectFactors() {
  const ed = document.getElementById('factor-editor');
  if (!ed) return [];
  return [...ed.querySelectorAll('.factor-row')]
    .map(row => {
      const name = row.querySelector('.factor-name').value.trim();
      const levels = row.querySelector('.factor-levels').value
        .split(',').map(x => {
          const t = x.trim();
          return (t !== '' && !isNaN(t)) ? Number(t) : t;
        }).filter(x => x !== '');
      return { name, levels };
    })
    .filter(f => f.name && f.levels.length >= 2);
}

// ── inverse_solve：列角色勾选 + 反演请求行录入 ──
export function buildColumnChecks(k, task) {
  const label = paramLabel(k, task);
  const hint = paramHint(k, task);
  if (!columnData.length) {
    return `<div class="param-item">
      <label class="param-label">${label}</label>
      <div class="param-hint">请先上传数据文件</div>
    </div>`;
  }
  // 默认勾选与引擎一致的前缀列（incoming/来料 等）；用户可自行改选
  const prefixes = (INVERSE_PREFIXES[k] || []).map(p => p.toLowerCase());
  const boxes = columnData.map(c => {
    const lo = String(c.name).toLowerCase();
    const checked = prefixes.some(p => lo.startsWith(p)) ? 'checked' : '';
    return `<label class="col-check"><input type="checkbox" data-col="${escHtml(c.name)}" ${checked}> <span>${escHtml(c.name)}</span></label>`;
  }).join('');
  return `<div class="param-item">
    <label class="param-label">${label}</label>
    ${hint ? `<div class="param-hint">${hint}</div>` : ''}
    <div class="col-checks" id="colchecks_${k}">${boxes}</div>
  </div>`;
}

export function inverseCheckedCols(k) {
  const box = document.getElementById('colchecks_' + k);
  if (!box) return [];
  return [...box.querySelectorAll('input:checked')].map(cb => cb.dataset.col);
}

export function buildRequestEditor() {
  return `<div class="param-item">
    <label class="param-label">反演请求行</label>
    <div class="param-hint">每行填入来料/固定条件与各输出目标值（目标可填「目标·输出列」，也可填勾选的「目标列」）；可调参数由反解计算，固定列留空按历史中位数。</div>
    <div id="request-editor"></div>
    <button type="button" class="btn-sm" data-action="add-request-row">+ 添加请求行</button>
  </div>`;
}

export function requestRowData() {
  const editor = document.getElementById('request-editor');
  if (!editor) return [];
  return [...editor.querySelectorAll('.request-card')].map(card => {
    const values = {};
    card.querySelectorAll('input[data-col]').forEach(inp => { values[inp.dataset.col] = inp.value; });
    return values;
  });
}

export function requestCardHtml(index, values, incoming, fixed, outputs, targets = []) {
  const field = (label, col) => `<div class="request-field">
      <label title="${escHtml(col)}">${escHtml(label)}</label>
      <input type="number" step="any" data-col="${escHtml(col)}" value="${escHtml(String(values[col] ?? ''))}">
    </div>`;
  return `<div class="request-card">
    <div class="request-head"><span>请求行 ${index + 1}</span>
      <button type="button" class="btn-sm" data-action="remove-request-row">✕</button></div>
    ${incoming.map(col => field(col, col)).join('')}
    ${fixed.map(col => field('固定·' + col, col)).join('')}
    ${outputs.map(col => field('目标·' + col, col)).join('')}
    ${targets.map(col => field('目标列·' + col, col)).join('')}
  </div>`;
}

export function rebuildRequestTable() {
  const editor = document.getElementById('request-editor');
  if (!editor) return;
  const saved = requestRowData();
  const incoming = inverseCheckedCols('incoming_cols');
  const fixed = inverseCheckedCols('fixed_cols');
  const outputs = inverseCheckedCols('output_cols');
  const targets = inverseCheckedCols('target_cols');
  if (!incoming.length || !outputs.length) {
    editor.innerHTML = '<div class="param-hint">请先勾选「来料列」与「输出列」，再填写请求行。</div>';
    return;
  }
  const rows = saved.length ? saved : [{}];
  editor.innerHTML = rows.map((values, i) =>
    requestCardHtml(i, values, incoming, fixed, outputs, targets)).join('');
}

export function addRequestRow() {
  const editor = document.getElementById('request-editor');
  if (!editor) return;
  const incoming = inverseCheckedCols('incoming_cols');
  const fixed = inverseCheckedCols('fixed_cols');
  const outputs = inverseCheckedCols('output_cols');
  const targets = inverseCheckedCols('target_cols');
  if (!incoming.length || !outputs.length) return;
  const index = editor.querySelectorAll('.request-card').length;
  editor.insertAdjacentHTML(
    'beforeend', requestCardHtml(index, {}, incoming, fixed, outputs, targets));
  renumberRequestRows();
}

export function removeRequestRow(btn) {
  const card = btn.closest('.request-card');
  if (card) {
    card.remove();
    renumberRequestRows();
  }
}

export function renumberRequestRows() {
  // 删除/新增后重排行号，避免出现重复或跳号（如 1,3,3）
  const editor = document.getElementById('request-editor');
  if (!editor) return;
  editor.querySelectorAll('.request-card .request-head span').forEach((el, i) => {
    el.textContent = '请求行 ' + (i + 1);
  });
}

export function collectRequestRows() {
  const editor = document.getElementById('request-editor');
  if (!editor) return [];
  return [...editor.querySelectorAll('.request-card')]
    .map(card => {
      const row = {};
      card.querySelectorAll('input[data-col]').forEach(inp => {
        const raw = inp.value.trim();
        if (raw === '') return;
        const num = Number(raw);
        row[inp.dataset.col] = isFinite(num) ? num : raw;
      });
      return row;
    })
    .filter(row => Object.keys(row).length);
}

// ── 构建参数输入控件 ──
export function buildParamInput(k, v, task) {
  if (k === 'factors') return buildFactorEditor();
  if (k === 'request_rows') return buildRequestEditor();
  if (task === 'inverse_solve' && INVERSE_ROLE_KEYS.includes(k)) return buildColumnChecks(k, task);
  // 标签/提示/选项**全部来自后端派生**（`Spec` 声明）—— 前端不再有平行字典。
  const label = paramLabel(k, task);
  const hint = paramHint(k, task);
  const id = `param_${k}`;
  const options = paramOptions(k, task);

  if (options) {
    const opts = options.map(([val, text]) =>
      `<option value="${val}" ${String(v) === val ? 'selected' : ''}>${escHtml(String(text))}</option>`
    ).join('');
    return `<div class="param-item" id="param-item_${k}">
      <label class="param-label" for="${id}">${label}</label>
      <select id="${id}" class="param-select">${opts}</select>
    </div>`;
  }

  if (COLUMN_PARAMS.has(k)) {
    const opts = columnData.map(c =>
      `<option value="${escHtml(c.name)}" ${String(v) === c.name ? 'selected' : ''}>${escHtml(c.name)}</option>`
    ).join('');
    return `<div class="param-item" id="param-item_${k}">
      <label class="param-label" for="${id}">${label}</label>
      <select id="${id}" class="param-select"><option value="">— 自动 —</option>${opts}</select>
    </div>`;
  }

  // 默认：文本/数字输入
  let inputType = 'text';
  let step = '';
  if (typeof v === 'number') { inputType = 'number'; step = v < 1 ? '0.01' : '1'; }
  // 审查 2026-10-09 P0-1：`null` 默认值（TaskSpec 用 None 表示"未指定"）若直接插值
  // 会渲染成字面量 `value="null"`，`getParams` 再把它当用户输入原样下发 →
  // 7 个任务硬报错（usl/lsl/group_col 无法解析）、2 个任务静默错数
  // （proportion_ci 点估计 0.0000、lasso R² 0.785 vs 0.981）。归一为空控件即可。
  return `<div class="param-item" id="param-item_${k}">
    <label class="param-label" for="${id}">${label}</label>
    ${hint ? `<div class="param-hint">${hint}</div>` : ''}
    <input type="${inputType}" id="${id}" value="${v ?? ''}" step="${step}"
      class="param-input" placeholder="${hint || ''}">
  </div>`;
}

export function showParams(task) {
  const panel = document.getElementById('param-panel');
  const body = document.getElementById('param-body');
  // 用 hasParams 而非 `!cfg`：服务端对无参数任务下发 `{}`，
  // 而 `!{}` 为 false —— 直接判 cfg 会误显示一个只有"运行分析"按钮的空面板。
  // `is-hidden` 而非内联 display —— 详见 style.css 里工具类的说明
  if (!hasParams(task)) { panel.classList.add('is-hidden'); return; }
  const cfg = defaultParams(task);
  panel.classList.remove('is-hidden');
  body.innerHTML = Object.entries(cfg).map(([k, v]) => buildParamInput(k, v, task)).join('')
    + `<button data-action="run-analysis" class="btn-run">▶ 运行分析</button>`;
  if (task === 'doe_design') {
    // CCD 轴向距离 α 仅中心复合设计使用（引擎只在 ccd 分支读取），按设计方法联动显隐
    const methodEl = document.getElementById('param_method');
    const alphaItem = document.getElementById('param-item_alpha');
    const syncAlpha = () => {
      if (alphaItem) alphaItem.classList.toggle('is-hidden', !(methodEl && methodEl.value === 'ccd'));
    };
    if (methodEl) methodEl.addEventListener('change', syncAlpha);
    syncAlpha();
  }
  if (task === 'inverse_solve') {
    // 列角色勾选变化 → 重建请求行编辑器（保留已填数值）
    INVERSE_ROLE_KEYS.forEach(k => {
      document.querySelectorAll(`#colchecks_${k} input`).forEach(cb =>
        cb.addEventListener('change', rebuildRequestTable));
    });
    rebuildRequestTable();
  }
}

export function getParams(task) {
  if (!hasParams(task)) return {};
  const cfg = defaultParams(task);
  const p = {};
  Object.keys(cfg).forEach(k => {
    if (k === 'factors') {
      const factors = collectFactors();
      if (factors.length) p[k] = factors;
      return;
    }
    if (k === 'request_rows') return;  // 反演请求行由 collectRequestRows 单独收集
    if (task === 'inverse_solve' && INVERSE_ROLE_KEYS.includes(k)) {
      // 角色列以勾选列表下发；全不勾选则引擎按前缀自动识别
      const cols = inverseCheckedCols(k);
      if (cols.length) p[k] = cols;
      return;
    }
    const el = document.getElementById('param_'+k);
    if (!el) return;
    let v = el.value.trim();
    // 审查 2026-10-09 P0-1：哨兵值统一视为"未填"（与空串同义）。
    // 渲染侧已归一（`value="${v ?? ''}"`），这里再兜一道 —— 任何上游把 `null`/`undefined`
    // 变成字符串的路径都不得把字面量送给引擎（`isNaN('null')` 为真会跳过数值转换，
    // 于是 `params["usl"] === "null"` → Spec 校验报"无法解析"）。
    if (v === '' || v === 'null' || v === 'undefined' || v === 'NaN') return;

    if (k === 'ranges') {
      // 审查 2026-08-19 H1：提示格式为"料温:180,220"（逗号分隔上下限），
      // 旧解析器按三段冒号拆分产生 [NaN,NaN]；同时拒绝 NaN/Inf 边界
      try { v = v.split(';').filter(Boolean).reduce((o, s) => {
        const parts = s.split(':');
        const ky = (parts[0] || '').trim();
        const bounds = (parts[1] || '').split(',');
        const lo = +bounds[0], hi = +bounds[1];
        if (ky && isFinite(lo) && isFinite(hi) && lo < hi) o[ky] = [lo, hi];
        return o;
      }, {}); if (!Object.keys(v).length) return; }
      catch(e) { return; }
    } else if (k === 'objectives') {
      try { v = v.split(';').filter(Boolean).map(s => { const [col, dir] = s.trim().split(':'); return {col:col.trim(), direction:dir?.trim()||'maximize'}; }); if (!v.length) return; }
      catch(e) { return; }
    } else if (k === 'weights') {
      // 逗号分隔权重 → 数值列表（审查 2026-08-19 L1）
      try { v = v.split(',').map(s => Number(s.trim())).filter(x => isFinite(x)); if (!v.length) return; }
      catch(e) { return; }
    } else if (k === 'control_vars') {
      // 逗号分隔列名 → 列表（审查 2026-08-19 L1）
      v = v.split(',').map(s => s.trim()).filter(Boolean);
      if (!v.length) return;
    } else if (el.tagName === 'INPUT' && !isNaN(v)) {
      // 审查 2026-08-19 M1：仅对 input 控件做数值转换；
      // select（列选择器）的值是列名，数字列名被 Number() 后 pandas 查不到
      v = Number(v);
    }
    p[k] = v;
  });
  if (task === 'inverse_solve') {
    const rows = collectRequestRows();
    if (rows.length) p.request_rows = rows;
  }
  return p;
}
