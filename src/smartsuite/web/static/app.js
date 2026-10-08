// app.js — 入口模块：分析执行链与事件委托。
//
// 审查 2026-09-24（P3-3）：原为 933 行单文件、20 个顶层全局、11 处内联 onclick。
// 现拆为：
//   util.js   无依赖工具（HTML 转义 / 数值展示 / 页内 toast）
//   api.js    CSRF token 与带 token 的 fetch
//   state.js  列数据 / Y·X·类别选择 / 上传 / 列渲染
//   params.js 参数面板（默认值与元数据、控件、因子与请求行编辑器）
//   app.js    本文件：编排上面四者 + 在**一个根节点**上做事件委托
//
// 关键约束（由 tests/guards/test_web_ui_guards.py 断言）：
//   1. 全项目**不得**再有内联事件处理器 —— 模块化后函数不再是全局，
//      内联 `onclick="foo()"` 会抛 ReferenceError（点击即坏）；
//   2. 因此所有交互都走 `data-action` + 根级委托，这也使 CSP 的
//      `script-src` 得以去掉 `'unsafe-inline'`（本项重构的安全收益）。

import { escHtml, fmtCellNum, showToast } from './util.js';
import { fetchWithCsrf } from './api.js';
import {
  autoDetect,
  clearAll,
  lastFile,
  renderCols,
  selectedCat,
  selectedX,
  selectedY,
  setAll,
  uploadFile,
} from './state.js';
import {
  addFactorRow,
  addRequestRow,
  getParams,
  hasParams,
  hydrateParams,
  paramsLoadFailed,
  paramsReady,
  removeFactorRow,
  removeRequestRow,
  showParams,
} from './params.js';

// ══════════════════════════════════════════════════════════════
// 分析执行链
// ══════════════════════════════════════════════════════════════

// Analysis — 两步流程: 有参数→先显示面板, 无参数→直接运行
let _pendingTask = null; // 当前等待用户确认参数的任务
let _running = false; // 防抖标志
let _lastRequest = null; // 最近一次分析请求体（用于分组筛选重取）
let _activeGroups = new Set(); // 当前激活的分组
let _allGroups = []; // 全量分组列表（常驻，不受筛选影响）
let _pendingGroupFilter = false; // 是否有待筛选的分组

async function runAnalysis(task) {
  if (_running) return; // 防抖：上一次分析尚未完成
  // 完全无需目标列 Y 的任务（仅依赖 X 列或纯参数计算）
  const _noTargetNeeded = new Set([
    'vif', 'cohens_kappa', 'cronbach_alpha', 'power_analysis', 'multi_objective', 'doe_design',
    'inverse_solve',
  ]);
  if (!_noTargetNeeded.has(task) && !selectedY.size) {
    showToast('请至少选择一个 Y 列'); return;
  }
  // 仅需 Y 列即可运行的任务（无需选择 X 列）
  const _yOnlyTasks = new Set([
    'process_capability', 'trend_forecast',
    'power_analysis', 'doe_design', 'spc_nonparametric',
    'distribution_summary', 'proportion_ci',
    'bootstrap_ci', 'median_ci', 'tolerance_interval', 'change_point',
    'spc_cusum', 'spc_ewma',
    'grid_search',
    'inverse_solve',
  ]);
  // X 列可选的任务（引擎支持 feature_cols[0] 作为 X 轴，但不选时可回退到顺序索引）
  const _xOptionalTasks = new Set([
    'spc_xbar', 'spc_attribute', 'normality_check', 'anomaly_detect',
  ]);
  if (!_yOnlyTasks.has(task) && !_xOptionalTasks.has(task) && !selectedX.size) {
    showToast('请至少选择一个 X 列'); return;
  }
  // 有参数配置 → 第一步: 显示参数面板, 等待用户编辑后点"运行"
  // 必须先 await 默认值就绪：`/api/tasks` 是异步的，若用户在响应到达前点了任务，
  // hasParams() 会返回 false → 面板不显示、直接用引擎默认值开跑（用户以为该任务无参数）。
  await paramsReady();
  // 用 hasParams 而非 `TASK_PARAMS[task]`：服务端对无参数任务下发 `{}`，
  // 而 `!{}` 为 false —— 直接判存在会误显示只有"运行分析"按钮的空面板。
  if (hasParams(task)) {
    // 如果同一个任务已显示参数面板 → 直接执行（用户已经编辑过参数）
    const panel = document.getElementById('param-panel');
    if (_pendingTask === task && !panel.classList.contains('is-hidden')) {
      _pendingTask = null;
      await executeRequest(task);
      return;
    }
    _pendingTask = task;
    showParams(task);
    return;
  }
  // 无参数 → 直接执行
  _pendingTask = null;
  await executeRequest(task);
}

// 实际执行分析请求
async function executeRequest(task) {
  task = task || _pendingTask;
  if (!task) return;
  _pendingTask = null;
  _running = true;
  document.getElementById('param-panel').classList.add('is-hidden');
  document.querySelectorAll('.btn-analysis').forEach(b => b.disabled = true);
  document.getElementById('results').innerHTML =
    '<div class="empty-hint"><div class="spinner"></div> 分析中...</div>';
  try {
    const params = getParams(task);
    // 2026-08-21 #F1：换分类列(group_col)后，旧的常驻分组列表失效。
    // 不重置会残留旧分组名 → 筛选栏显示旧分组、点"应用"时过滤组名与当前数据
    // 不匹配被引擎回退全量 → 界面看起来"应用不刷新"。
    const prevReq = _lastRequest;
    const prevParams = prevReq ? prevReq.params : {};
    // 2026-08-21 #F2：任务或分类列变化都会使旧分组列表失效（不同任务的分组语义
    // 可能不同，即使 group_col 同名）→ 重置分组上下文，避免筛选栏残留旧分组
    const groupChanged = String(prevParams.group_col || '') !== String(params.group_col || '');
    const taskChanged = prevReq ? (prevReq.task !== task) : false;
    rememberRequest({ task, targets: [...selectedY], features: [...selectedX], categoricals: [...selectedCat], params });
    _pendingGroupFilter = !!(params.group_col) || (task === 'box_chart');  // 有分组依据时启用筛选栏（box_chart 始终有分组）
    if (!_pendingGroupFilter || groupChanged || taskChanged) { _allGroups = []; _activeGroups.clear(); }  // 无分组/分类列变化/任务切换 → 重置分组上下文
    const r = await fetchWithCsrf('/api/analyze', { method: 'POST', body: JSON.stringify(_lastRequest) });
    let d = {};
    try { d = await r.json(); } catch(err) { /* 非 JSON 响应（如 413 HTML / 502 网关错误页） */ }
    if (!r.ok) {
      // 审查 2026-08-19 M5（Round-2）：413/502 给中文提示，避免 "not json" 误报
      const statusMsg = r.status === 413 ? '请求数据过大（超过服务器限制），请减少数据量或列数'
        : r.status === 502 ? '服务器暂时不可用（502 Bad Gateway），请稍后重试' : '';
      document.getElementById('results').innerHTML =
        `<div class="empty-hint is-error">${escHtml(d.error || statusMsg || '分析请求失败')}</div>`;
      return;
    }
    renderResults(d.results || []);
    // 分析成功 → 显示导出栏（P5：报告导出入口）。
    // 报告需要服务端重新执行分析（图表无法经 JSON 往返），故导出用的是
    // `_lastRequest`（刚成功的那次请求），不是前端的结果对象。
    setExportBarVisible(true);
  } catch(e) {
    document.getElementById('results').innerHTML =
      `<div class="empty-hint is-error">错误: ${escHtml(e.message)}</div>`;
  } finally {
    _running = false;
    document.querySelectorAll('.btn-analysis').forEach(b => b.disabled = false);
  }
}

// 兼容: param面板中的"运行"按钮调用
function executeAnalysis() {
  if (_running) return;  // 审查 2026-08-19 L6：防双击并发
  executeRequest(_pendingTask);
}

// ── 分组筛选（SPC 多系列）──
function toggleGroupFilter(groupName, active) {
  if (active) { _activeGroups.add(groupName); }
  else { _activeGroups.delete(groupName); }
}
async function refetchWithFilter() {
  if (!_lastRequest) return;
  const req = { ..._lastRequest, params: { ..._lastRequest.params } };
  const filtered = [..._activeGroups];
  if (filtered.length > 0 && filtered.length < _allGroups.length) {
    req.params.filter_groups = filtered;
  } else {
    delete req.params.filter_groups;
  }
  _pendingGroupFilter = true;
  const r = await fetchWithCsrf('/api/analyze', { method: 'POST', body: JSON.stringify(req) });
  let d = {};
  try { d = await r.json(); } catch(err) { /* 非 JSON 响应 */ }
  if (r.ok) { renderResults(d.results || []); }
  else {
    // 审查 2026-08-19 L2：筛选重取失败不再静默
    document.getElementById('results').innerHTML =
      `<div class="empty-hint is-error">${escHtml(d.error || '筛选重取失败，请重试')}</div>`;
  }
}

// Result rendering
function renderResults(results) {
  if (!results.length) { document.getElementById('results').innerHTML = '<div class="empty-hint">无结果</div>'; return; }

  // ── 分组筛选栏（常驻，用 _allGroups 避免过滤后消失）──
  let filterHtml = '';
  const meta0 = results[0]?.metadata || {};
  const groups0 = meta0.groups;
  // 首次出现分组时初始化全量列表
  if (groups0 && groups0.length > 0 && _pendingGroupFilter && _allGroups.length === 0) {
    _allGroups = groups0.map(g => String(g));
    _allGroups.forEach(g => _activeGroups.add(g));
  }
  if (_pendingGroupFilter && _allGroups.length >= 1) {
    filterHtml = '<div class="filter-bar"><span class="filter-label">筛选分组: </span>';
    _allGroups.forEach(g => {
      const gs = String(g);
      const ck = _activeGroups.has(gs) ? 'checked' : '';
      filterHtml += `<label class="filter-chip"><input type="checkbox" class="group-filter-cb" data-group="${escHtml(gs)}" value="${escHtml(gs)}" ${ck}> ${escHtml(gs)}</label>`;
    });
    filterHtml += '<button class="btn-sm" id="apply-filter-btn">应用</button></div>';
  }

  // ── 合并相关矩阵：独立显示在顶部 ──
  // 审查 2026-08-19 M2（Round-2 真修复）：必须在排序前捕获。
  // 排序会改变 results 顺序，而矩阵只挂在排序前 results[0]（首个目标）的结果上
  const mergedKey = '_merged_correlation';
  const mergedTbl = results[0]?.tables?.[mergedKey] || null;

  // 排序
  results.sort((a, b) => {
    const getScore = (r) => {
      if (r.metadata?.target_correlations) {
        const vals = Object.values(r.metadata.target_correlations);
        if (vals.length) return Math.max(...vals.map(Math.abs));
      }
      if (r.metadata?.p_value != null) return 1 - Math.min(1, Math.abs(r.metadata.p_value));
      if (r.metadata?.r_squared != null) return r.metadata.r_squared;
      return 0;
    };
    return getScore(b) - getScore(a);
  });

  let html = '';

  // ── 合并相关矩阵：独立显示在顶部 ──
  if (mergedTbl) {
    const tbl = mergedTbl;
    const hdr = '<th></th>' + tbl.columns.map(c => `<th>${escHtml(String(c))}</th>`).join('');
    const rows = tbl.data.map((row, i) =>
      `<tr><td><b>${escHtml(String(tbl.index[i]||''))}</b></td>${row.map(v =>
        `<td class="${Math.abs(v)>0.2?'cell-strong':'cell-normal'}">${typeof v==='number'?v.toFixed(3):escHtml(String(v))}</td>`
      ).join('')}</tr>`
    ).join('');
    html += `<div class="result-card">
      <div class="card-header"><span>相关性合并矩阵 (${tbl.shape[0]} 目标 × ${tbl.shape[1]} 因子)</span></div>
      <div class="card-body"><div class="table-wrap">
        <table><thead><tr>${hdr}</tr></thead><tbody>${rows}</tbody></table>
      </div></div></div>`;
  }

  // ── 每个目标：结论 + 图表（不重复显示矩阵） ──
  results.forEach(r => {
    const sc = r.status === 'ok' ? 'ok' : 'error';
    // 只渲染非内部表
    let tHtml = '';
    for (const [tn, tbl] of Object.entries(r.tables || {})) {
      if (tn.startsWith('_merged')) continue; // 跳过合并表
      const hdr = tbl.columns.map(c => `<th>${escHtml(String(c))}</th>`).join('');
      const rows = tbl.data.map((row, i) =>
        `<tr><td>${escHtml(String(tbl.index[i]||''))}</td>${row.map(v =>
          `<td>${typeof v==='number'?fmtCellNum(v):escHtml(String(v))}</td>`).join('')}</tr>`
      ).join('');
      tHtml += `<div class="table-wrap"><h4>${escHtml(String(tn))} (${String(tbl.shape[0])}×${String(tbl.shape[1])})</h4>
        <table><thead><tr><th></th>${hdr}</tr></thead><tbody>${rows}</tbody></table></div>`;
    }
    let cHtml = (r.charts||[]).map(b => `<div class="chart-wrap"><img src="data:image/png;base64,${b}"></div>`).join('');
    let mHtml = r.messages?.length ? r.messages.map(m => `<div class="messages">${escHtml(String(m))}</div>`).join('') : '';

    html += `<div class="result-card"><div class="card-header">
      <span>${escHtml(String(r.target))}</span><span class="status-badge ${sc}">${r.status==='ok'?'OK':'ERR'}</span></div>
      <div class="card-body"><div class="summary">${escHtml(String(r.summary))}</div>${mHtml}${cHtml}${tHtml}</div></div>`;
  });

  document.getElementById('results').innerHTML = filterHtml + html;

  // 事件委托：分组筛选复选框和应用按钮
  const resultsEl = document.getElementById('results');
  resultsEl.querySelectorAll('.group-filter-cb').forEach(cb => {
    cb.addEventListener('change', function() {
      toggleGroupFilter(this.dataset.group, this.checked);
    });
  });
  const applyBtn = document.getElementById('apply-filter-btn');
  if (applyBtn) {
    applyBtn.addEventListener('click', refetchWithFilter);
  }
}

// ══════════════════════════════════════════════════════════════
// 事件委托 —— 全部交互的唯一入口
//
// 审查 2026-09-24（P3-3）：原实现有 11 处内联 onclick（index.html 6 处、
// params.js 原属的模板字面量 5 处）。模块化后这些函数不再是全局，
// 内联写法必然失效；移除它们同时让 CSP 的 script-src 可以收紧。
//
// 规则用一个映射表声明：{ 动作名: (元素, 事件) => void }。
// 由 document 级单一监听派发，动态插入的元素无需重新绑定。
// ══════════════════════════════════════════════════════════════

const ACTIONS = {
  // 顶栏：打开文件选择框
  'pick-file': () => document.getElementById('file-input').click(),
  // 左栏工具栏
  'auto-detect': () => autoDetect(),
  'select-all-y': () => setAll('y'),
  'select-all-x': () => setAll('x'),
  'clear-columns': () => clearAll(),
  // 工作流按钮：按 data-task 发起分析（替代内联 runAnalysis('{{ t }}')）
  'run-task': (el) => runAnalysis(el.dataset.task),
  // 参数面板（含动态生成的按钮）
  'add-factor': () => addFactorRow(),
  'remove-factor': (el) => removeFactorRow(el),
  'add-request-row': () => addRequestRow(),
  'remove-request-row': (el) => removeRequestRow(el),
  'run-analysis': () => executeAnalysis(),
  // 报告导出（P5）：按 data-format 请求 /api/export 并触发浏览器下载
  'export-report': (el) => exportReport(el.dataset.format),
};

/**
 * 显示/隐藏导出栏。
 *
 * 只在**分析成功**后显示：导出需要服务端重新执行分析，没有可复用的结果时
 * 点它只会得到 400。
 */
function setExportBarVisible(visible) {
  const bar = document.getElementById('export-bar');
  // `is-hidden` 用 `!important`，可压过 `.export-bar { display: flex }`
  if (bar) bar.classList.toggle('is-hidden', !visible);
}

/**
 * 记录最近一次分析请求体 —— 报告导出（`/api/export`）据此重跑分析。
 *
 * 收敛为函数而非散落的赋值：导出依赖"`_lastRequest` 与屏幕上的结果一致"，
 * 若有多处各自赋值，很容易出现"报告反映的是上一次的参数"这类难查的错。
 * 同时它是导出链路**唯一**的注入点，故 `scripts/check_export_flow.mjs`
 * 能在 Node 里驱动成功路径（无需真浏览器）。
 */
export function rememberRequest(req) {
  _lastRequest = req;
}

/** 取最近一次分析请求体（`null` 表示尚未成功运行过分析）。 */
export function lastRequest() {
  return _lastRequest;
}

/**
 * 从 `Content-Disposition` 响应头解析下载文件名；解析不到返回 `''`。
 *
 * 抽成导出函数是为了可测：文件名解析是导出链路里**最容易静默出错**的一环
 * （写错正则 → 下载到一个随机名或无扩展名的文件，用户很难归因）。
 * 由 `scripts/check_export_flow.mjs` 在 Node 里直接驱动真实实现。
 *
 * 兼容 `filename="x.pdf"` 与裸 `filename=x.pdf`，以及 RFC 5987 的
 * `filename*=UTF-8''x.pdf` 形态。
 */
export function parseDownloadFilename(header) {
  const h = header || '';
  // RFC 5987 优先：显式带 charset 的形态比裸 filename 更权威。
  // 它**不带引号**（`filename*=UTF-8''x.pdf`）—— 本实现首版按带引号写，
  // 被 Node 冒烟用例的这一形态抓出。
  const rfc5987 = /filename\*=\s*(?:UTF-8|utf-8)''([^;]+)/i.exec(h);
  if (rfc5987) return rfc5987[1].trim();
  const quoted = /filename\s*=\s*"([^"]+)"/i.exec(h);
  if (quoted) return quoted[1];
  const bare = /filename\s*=\s*([^;\s]+)/i.exec(h);
  return bare ? bare[1] : '';
}

/**
 * 触发浏览器下载一个 Blob，并**立即释放** object URL。
 *
 * 不释放会一直占着内存直到页面卸载（大报告可达数 MB）。
 */
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/**
 * 导出报告并下载（P5：`/api/export`）。
 *
 * 用 `fetch` + `Blob` 而非直接 `window.location`：前者能拿到失败响应体
 * （400/500 的 JSON 中文原因）并提示用户，后者只会静默跳到一张错误页。
 *
 * `_lastRequest` 是刚成功那次分析的请求体 —— 服务端据此**重跑**分析生成报告
 * （图表是 matplotlib 对象，无法经 JSON 往返，故不能复用前端结果）。
 */
export async function exportReport(format) {
  if (!_lastRequest) { showToast('请先运行一次分析'); return; }
  const label = { html: '网页', pdf: 'PDF', ppt: 'PowerPoint', xlsx: 'Excel' }[format] || format;
  showToast(`正在生成${label}报告…`);
  try {
    const r = await fetchWithCsrf('/api/export', {
      method: 'POST',
      body: JSON.stringify({ ..._lastRequest, format }),
    });
    if (!r.ok) {
      let d = {};
      try { d = await r.json(); } catch (err) { /* 非 JSON 响应 */ }
      showToast(d.error || `导出失败（HTTP ${r.status}）`);
      return;
    }
    // 文件名优先取服务端 Content-Disposition，缺失时用任务名兜底
    const name = parseDownloadFilename(r.headers.get('Content-Disposition'))
      || `${_lastRequest.task}.${format}`;
    downloadBlob(await r.blob(), name);
    showToast(`${label}报告已下载`);
  } catch (e) {
    showToast(`导出失败: ${e.message}`);
  }
}

function handleDelegatedClick(event) {
  const el = event.target.closest('[data-action]');
  if (!el) return;
  const fn = ACTIONS[el.dataset.action];
  if (!fn) return;
  fn(el, event);
}

document.addEventListener('click', handleDelegatedClick);

// ══════════════════════════════════════════════════════════════
// 初始化
// ══════════════════════════════════════════════════════════════

/**
 * 选择新文件时的处理：复位编码下拉框后上传。
 *
 * 审查 2026-09-21 R1-1：必须把编码复位为「自动识别」。否则上一次为某文件
 * 选定的编码会跨上传粘滞，把新文件静默读错（实测残留 Big5 声明读 GBK 文件
 * → 列名乱码、HTTP 200、status=ok，用户无从察觉）。
 *
 * 提取为具名函数而非内联箭头：便于静态断言直接检查处理器体，
 * 不受缩进/换行形式影响（tests/services/test_web_app_routes.py 依赖此形状）。
 */
function onNewFileSelected(e) {
  const f = e.target.files[0];
  if (!f) return;
  document.getElementById('encoding').value = '';
  uploadFile(f, refreshParamPanelIfOpen);
}

document.getElementById('file-input').addEventListener('change', onNewFileSelected);

/** 切换编码后用同一文件立即重传：否则用户看到乱码列名后必须重新选一次文件。 */
function onEncodingChanged() {
  if (lastFile) uploadFile(lastFile, refreshParamPanelIfOpen);
}

document.getElementById('encoding').addEventListener('change', onEncodingChanged);

/** 上传后回调：数据列变化时刷新已打开的参数面板（列选择器跟随新列）。 */
function refreshParamPanelIfOpen() {
  if (_pendingTask && !document.getElementById('param-panel').classList.contains('is-hidden')) {
    showParams(_pendingTask);
  }
}

// 初始渲染（列清单为空 → 显示"请先加载数据文件"）
renderCols();

// ══════════════════════════════════════════════════════════════
// 参数默认值：从服务端加载（P4 步骤④）
// ══════════════════════════════════════════════════════════════

/**
 * 拉取 `/api/tasks` 并把参数默认值灌入 params.js 缓存。
 *
 * 为什么要有这一步：前端原先自己维护一份 42 任务的默认值字典，与后端
 * `services/task_spec.py::TASK_SPECS` 逐字重复（靠门禁比对维持一致）。
 * 改由服务端下发后，后端是唯一事实源。
 *
 * 失败时给出**明确可见**的提示：此时所有任务都不会显示参数面板，
 * 用户点任务会直接运行（用引擎默认值）—— 这是可接受的降级，但必须让用户知道
 * 参数面板不可用，而不是让他以为"这个任务本来就没有参数"。
 */
async function loadTaskParams() {
  try {
    const r = await fetch('/api/tasks');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    if (!hydrateParams(await r.json())) throw new Error('响应缺少 params 字段');
  } catch (e) {
    // 必须解除等待：否则任何 `await paramsReady()` 都会永久挂起，
    // 表现为"点任务毫无反应"—— 比没有参数面板更糟。
    paramsLoadFailed();
    showToast('参数面板暂不可用（任务清单加载失败），分析将使用引擎默认参数');
    console.error('[smartsuite] /api/tasks 加载失败：', e);
  }
}

loadTaskParams();

