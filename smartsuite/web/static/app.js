// SmartSuite Web UI
let columnData = [];
let selectedY = new Set(), selectedX = new Set(), selectedCat = new Set();
let csrfToken = '';
const escHtml = (s) => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');

// CSRF token 获取
async function getCsrfToken() {
  if (csrfToken) return csrfToken;
  try {
    const r = await fetch('/api/csrf-token');
    const d = await r.json();
    csrfToken = d.token || '';
  } catch(e) { /* 网络错误时留空 */ }
  return csrfToken;
}
// 页面加载时预取
getCsrfToken();
const catKw = ['日期','班次','车间','机台','模具','编号','操作','检验',
  '原料','类型','批号','冷却','循环','模式','分区','保养','环境',
  '产品代码','色母','嵌件','首件','外观','尺寸','需返工','报警','换料'];
const yKw = ['不良','强度','伸长','冲击','粗糙','偏差','波动','效率'];

// File upload
document.getElementById('file-input').addEventListener('change', async e => {
  const f = e.target.files[0]; if (!f) return;
  document.getElementById('filename').textContent = f.name;
  document.getElementById('shape').textContent = '上传中...';
  const fd = new FormData(); fd.append('file', f);
  try {
    const r = await fetch('/api/upload', { method: 'POST', body: fd,
      headers: { 'X-CSRF-Token': await getCsrfToken() } });
    const d = await r.json();
    if (!r.ok) {
      alert('上传失败: ' + (d.error || '未知错误'));
      document.getElementById('filename').textContent = '未选择文件';
      document.getElementById('shape').textContent = '';
      return;
    }
    columnData = d.columns || [];
    document.getElementById('shape').textContent = d.shape ? `(${d.shape.join(' × ')})` : '';
    renderCols(); autoDetect();
  } catch(err) {
    alert('上传失败: 网络错误或服务器不可达');
    document.getElementById('filename').textContent = '未选择文件';
    document.getElementById('shape').textContent = '';
  }
});

// Column rendering — uses data-* attributes + addEventListener (no inline handlers)
function renderCols() {
  document.getElementById('col-list').innerHTML = columnData.map((c, i) => {
    const safeName = escHtml(c.name);
    return `
    <div class="col-row">
      <span class="col-name" title="${safeName} (${c.dtype}, ${c.nunique} unique, ${c.missing} NA)">${safeName}</span>
      <input type="checkbox" id="cat${i}" data-col="${safeName}" data-role="cat"
        ${selectedCat.has(c.name)?'checked':''}>
      <span class="tag cat">类</span>
      <input type="checkbox" id="x${i}" data-col="${safeName}" data-role="x"
        ${selectedX.has(c.name)?'checked':''}>
      <span class="tag x">X</span>
      <input type="checkbox" id="y${i}" data-col="${safeName}" data-role="y"
        ${selectedY.has(c.name)?'checked':''}>
      <span class="tag y">Y</span>
    </div>`}).join('');

  // Bind event listeners — avoids XSS via inline handlers
  columnData.forEach((c, i) => {
    ['cat', 'x', 'y'].forEach(role => {
      const cb = document.getElementById(role + i);
      if (cb) {
        cb.addEventListener('change', function() {
          toggle(c.name, role, this.checked);
        });
      }
    });
  });
  updateStatus();
}

function toggle(name, role, on) {
  const m = role==='y'?selectedY : role==='x'?selectedX : selectedCat;
  on ? m.add(name) : m.delete(name); updateStatus();
}
function updateStatus() {
  document.getElementById('col-status').textContent =
    `Y=${selectedY.size} X=${selectedX.size} 类别=${selectedCat.size}`;
}

function autoDetect() {
  selectedY.clear(); selectedX.clear(); selectedCat.clear();
  columnData.forEach(c => {
    const lo = c.name.toLowerCase();
    const isCat = catKw.some(k => lo.includes(k.toLowerCase()))
      || ['object','string'].includes(c.dtype);
    if (isCat) selectedCat.add(c.name);
    if (yKw.some(k => lo.includes(k.toLowerCase()))) { selectedY.add(c.name); return; }
    if (['float64','int64'].includes(c.dtype) && !isCat) selectedX.add(c.name);
  });
  renderCols();
}

function setAll(role) {
  columnData.forEach(c => {
    if (['float64','int64'].includes(c.dtype)) {
      if (role==='y') selectedY.add(c.name);
      if (role==='x' && !selectedY.has(c.name)) selectedX.add(c.name);
    }
  });
  renderCols();
}

function clearAll() { selectedY.clear(); selectedX.clear(); selectedCat.clear(); renderCols(); }

// ── 参数配置：默认值 + 元数据（类型 & 下拉选项） ──
const TASK_PARAMS = {
  grid_search:       { ranges: '', direction: 'maximize', n_points: 10 },
  process_capability:{ usl: '', lsl: '' },
  hypothesis_test:   { test: 'ttest_ind', alpha: 0.05 },
  trend_forecast:    { forecast_steps: 5 },
  anomaly_detect:    { method: 'iqr' },
  response_surface:  { direction: 'maximize' },
  multi_objective:   { objectives: '' },
  decision_tree:     { max_depth: 5 },
  anova:             { alpha: 0.05, interactions: 0 },
  spc_nonparametric: { side: 'two-sided' },
  spc_cusum:         { k: 0.5, h: 5.0 },
  spc_ewma:          { lam: 0.2, L: 2.7 },
  spc_attribute:     { chart_type: 'p' },
  power_analysis:    { mode: 'required_n', test_type: 'ttest', effect_size: 0.5, alpha: 0.05, target_power: 0.80 },
  bootstrap_ci:      { statistic: 'mean', n_bootstrap: 2000, ci_level: 0.95 },
  median_ci:         { ci_level: 0.95 },
  quantile_regression:{ quantile: 0.5 },
  tolerance_interval:{ coverage: 0.99, confidence: 0.95, side: 'two-sided' },
  gage_rr:           { part_col: '', operator_col: '', sigma_multiplier: 5.15, tolerance: '' },
  spc_xbar:          { subgroup_col: '子组', usl: '', lsl: '', target: '' },
  logistic_regression:{ threshold: 0.5 },
  lasso_regression:  { alpha_lasso: '', l1_ratio: 1.0 },
  regression:        { model_type: 'linear' },
  change_point:      { min_segment: 10, n_changepoints: 5 },
  doe_analysis:      { alpha: 0.05 },
  variance_test:     { group_col: '', alpha: 0.05 },
  box_chart:         { mode: 'facet' },
  correlation:       { method: 'pearson' },
  contingency:       { alpha: 0.05 },
};

// 参数元数据：定义类型和下拉选项
const PARAM_META = {
  direction: {
    type: 'select', label: '优化方向',
    options: [['maximize', '最大化'], ['minimize', '最小化']]
  },
  test: {
    type: 'select', label: '检验方法',
    options: [
      ['ttest_ind', '独立样本 t 检验'], ['mannwhitney', 'Mann-Whitney U 检验'],
      ['wilcoxon_paired', 'Wilcoxon 配对检验'], ['kruskal', 'Kruskal-Wallis 检验'],
      ['ttest_1samp', '单样本 t 检验'],
    ]
  },
  method: {
    type: 'select', label: '异常检测方法',
    options: [
      ['iqr', 'IQR (四分位距法)'], ['zscore', 'Z-Score (标准差法)'],
      ['isolation_forest', 'Isolation Forest (隔离森林)'], ['grubbs', 'Grubbs 检验'],
      ['mad', 'MAD (中位数绝对偏差)'],
    ]
  },
  side: {
    type: 'select', label: '检验侧',
    options: [
      ['two-sided', '双侧'], ['upper', '上侧 (越大越好)'], ['lower', '下侧 (越小越好)']
    ]
  },
  chart_type: {
    type: 'select', label: '控制图类型',
    options: [
      ['p', 'p 图 (不良率)'], ['np', 'np 图 (不良数)'],
      ['c', 'c 图 (缺陷数)'], ['u', 'u 图 (单位缺陷率)']
    ]
  },
  mode: {
    type: 'select', label: '模式',
    options: [
      ['facet', '分面 (各 X₂ 一张子图)'], ['nested', '嵌套 (组合标签如 ABS/否)']
    ]
  },
  model_type: {
    type: 'select', label: '模型类型',
    options: [
      ['linear', '线性回归 (OLS)']
    ]
  },
  statistic: {
    type: 'select', label: '统计量',
    options: [
      ['mean', '均值'], ['median', '中位数'], ['std', '标准差'], ['var', '方差']
    ]
  },
  test_type: {
    type: 'select', label: '检验类型',
    options: [
      ['ttest', 't 检验'], ['anova', 'ANOVA'],
      ['chi2', '卡方检验'], ['correlation', '相关性检验']
    ]
  },
  'mode@power_analysis': {
    type: 'select', label: '功效分析模式',
    options: [
      ['required_n', '计算所需样本量'], ['achieved', '计算实际功效']
    ]
  },
  quantile: {
    type: 'select', label: '分位数',
    options: [['0.1','0.1'], ['0.25','0.25'], ['0.5','0.5 (中位数)'], ['0.75','0.75'], ['0.9','0.9']]
  },
  subgroup_col:   { type: 'column', label: '子组列', hint: '选择用于分组的列' },
  part_col:       { type: 'column', label: '部件列', hint: '选择部件标识列' },
  operator_col:   { type: 'column', label: '操作员列', hint: '选择操作员标识列' },
  group_col:      { type: 'column', label: '分组列', hint: '选择分组标识列' },
};

// 参数标签（中文显示名）
const PARAM_LABELS = {
  ranges: '搜索范围', objectives: '目标定义', direction: '优化方向',
  n_points: '网格点数', usl: '规格上限 (USL)', lsl: '规格下限 (LSL)',
  test: '检验方法', alpha: '显著性水平 α', interactions: '交互阶数',
  forecast_steps: '预测步数', method: '异常检测方法', side: '检验侧',
  k: 'K 值 (松弛因子)', h: 'H 值 (决策区间)', lam: 'λ (平滑系数)',
  L: 'L (控制限宽度)', chart_type: '控制图类型', mode: '模式',
  test_type: '检验类型', effect_size: '效应量', statistic: '统计量',
  n_bootstrap: 'Bootstrap 次数', ci_level: '置信水平', quantile: '分位数',
  coverage: '覆盖比例', confidence: '置信度', part_col: '部件列',
  operator_col: '操作员列', subgroup_col: '子组列', alpha_lasso: 'α (正则化强度)',
  model_type: '模型类型', min_segment: '最小段长', n_changepoints: '变点数',
  group_col: '分组列', max_depth: '最大深度',
  sigma_multiplier: 'Sigma 乘数', tolerance: '公差',
  target_power: '目标功效', l1_ratio: 'L1 比率 (ElasticNet)',
};

const PARAM_HINTS = {
  ranges: '格式: 料温:180,220; 模具温度:40,80',
  objectives: '格式: 强度:maximize; 不良率:minimize',
};

// ── 构建参数输入控件 ──
function buildParamInput(k, v, task) {
  // 支持 task.key 格式的覆盖查找（如 power_analysis.mode vs box_chart.mode）
  const meta = PARAM_META[k + '@' + task] || PARAM_META[k];
  const label = PARAM_LABELS[k] || k;
  const hint = PARAM_HINTS[k];
  const id = `param_${k}`;

  if (meta?.type === 'select') {
    const opts = meta.options.map(([val, text]) =>
      `<option value="${val}" ${String(v) === val ? 'selected' : ''}>${text}</option>`
    ).join('');
    return `<div class="param-item">
      <label class="param-label" for="${id}">${label}</label>
      <select id="${id}" class="param-select">${opts}</select>
    </div>`;
  }

  if (meta?.type === 'column') {
    const opts = columnData.map(c =>
      `<option value="${escHtml(c.name)}" ${String(v) === c.name ? 'selected' : ''}>${escHtml(c.name)}</option>`
    ).join('');
    return `<div class="param-item">
      <label class="param-label" for="${id}">${label}</label>
      <select id="${id}" class="param-select"><option value="">— 自动 —</option>${opts}</select>
    </div>`;
  }

  // 默认：文本/数字输入
  let inputType = 'text';
  let step = '';
  if (typeof v === 'number') { inputType = 'number'; step = v < 1 ? '0.01' : '1'; }
  return `<div class="param-item">
    <label class="param-label" for="${id}">${label}</label>
    ${hint ? `<div class="param-hint">${hint}</div>` : ''}
    <input type="${inputType}" id="${id}" value="${v}" step="${step}"
      class="param-input" placeholder="${hint || ''}">
  </div>`;
}

function showParams(task) {
  const panel = document.getElementById('param-panel');
  const body = document.getElementById('param-body');
  const cfg = TASK_PARAMS[task];
  if (!cfg) { panel.style.display = 'none'; return; }
  panel.style.display = 'block';
  body.innerHTML = Object.entries(cfg).map(([k, v]) => buildParamInput(k, v, task)).join('')
    + `<button onclick="executeAnalysis()" class="btn-run">▶ 运行分析</button>`;
}

function getParams(task) {
  const cfg = TASK_PARAMS[task];
  if (!cfg) return {};
  const p = {};
  Object.keys(cfg).forEach(k => {
    const el = document.getElementById('param_'+k);
    if (!el) return;
    let v = el.value.trim();
    if (v === '') return;

    if (k === 'ranges') {
      try { v = v.split(';').filter(Boolean).reduce((o, s) => { const [ky, lo, hi] = s.split(':'); o[ky.trim()] = [+lo, +hi]; return o; }, {}); if (!Object.keys(v).length) return; }
      catch(e) { return; }
    } else if (k === 'objectives') {
      try { v = v.split(';').filter(Boolean).map(s => { const [col, dir] = s.trim().split(':'); return {col:col.trim(), direction:dir?.trim()||'maximize'}; }); if (!v.length) return; }
      catch(e) { return; }
    } else if (!isNaN(v)) {
      v = Number(v);
    }
    p[k] = v;
  });
  return p;
}

// Analysis — 两步流程: 有参数→先显示面板, 无参数→直接运行
let _pendingTask = null;  // 当前等待用户确认参数的任务
let _running = false;     // 防抖标志

async function runAnalysis(task) {
  if (_running) return;  // 防抖：上一次分析尚未完成
  if (!selectedY.size) { alert('请至少选择一个 Y 列'); return; }
  // 仅需 Y 列即可运行的任务（无需选择 X 列）
  const _yOnlyTasks = new Set([
    'process_capability', 'trend_forecast', 'anomaly_detect',
    'power_analysis', 'spc_nonparametric',
    'distribution_summary', 'normality_check', 'proportion_ci',
    'bootstrap_ci', 'median_ci', 'tolerance_interval', 'change_point',
  ]);
  if (!_yOnlyTasks.has(task) && !selectedX.size) {
    alert('请至少选择一个 X 列'); return;
  }
  // 有参数配置 → 第一步: 显示参数面板, 等待用户编辑后点"运行"
  if (TASK_PARAMS[task]) {
    // 如果同一个任务已显示参数面板 → 直接执行（用户已经编辑过参数）
    if (_pendingTask === task && document.getElementById('param-panel').style.display !== 'none') {
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
  document.getElementById('param-panel').style.display = 'none';
  document.querySelectorAll('.btn-analysis').forEach(b => b.disabled = true);
  document.getElementById('results').innerHTML =
    '<div class="empty-hint"><div class="spinner"></div> 分析中...</div>';
  try {
    const r = await fetch('/api/analyze', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': await getCsrfToken() },
      body: JSON.stringify({ task, targets: [...selectedY], features: [...selectedX],
        categoricals: [...selectedCat], params: getParams(task) })
    });
    const d = await r.json();
    if (!r.ok) {
      document.getElementById('results').innerHTML =
        `<div class="empty-hint" style="color:#c62828">${escHtml(d.error || '分析请求失败')}</div>`;
      return;
    }
    renderResults(d.results || []);
  } catch(e) {
    document.getElementById('results').innerHTML =
      `<div class="empty-hint" style="color:#c62828">错误: ${escHtml(e.message)}</div>`;
  } finally {
    _running = false;
    document.querySelectorAll('.btn-analysis').forEach(b => b.disabled = false);
  }
}

// 兼容: param面板中的"运行"按钮调用
function executeAnalysis() {
  executeRequest(_pendingTask);
}

// Result rendering
function renderResults(results) {
  if (!results.length) { document.getElementById('results').innerHTML = '<div class="empty-hint">无结果</div>'; return; }
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
  const mergedKey = '_merged_correlation';
  if (results[0]?.tables?.[mergedKey]) {
    const tbl = results[0].tables[mergedKey];
    const hdr = '<th></th>' + tbl.columns.map(c => `<th>${escHtml(String(c))}</th>`).join('');
    const rows = tbl.data.map((row, i) =>
      `<tr><td><b>${escHtml(String(tbl.index[i]||''))}</b></td>${row.map(v =>
        `<td style="color:${Math.abs(v)>0.2?'#c62828':'#333'}">${typeof v==='number'?v.toFixed(3):escHtml(String(v))}</td>`
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
          `<td>${typeof v==='number'?v.toFixed(4):escHtml(String(v))}</td>`).join('')}</tr>`
      ).join('');
      tHtml += `<div class="table-wrap"><h4>${tn} (${tbl.shape[0]}×${tbl.shape[1]})</h4>
        <table><thead><tr><th></th>${hdr}</tr></thead><tbody>${rows}</tbody></table></div>`;
    }
    let cHtml = (r.charts||[]).map(b => `<div class="chart-wrap"><img src="data:image/png;base64,${b}"></div>`).join('');
    let mHtml = r.messages?.length ? r.messages.map(m => `<div class="messages">${escHtml(String(m))}</div>`).join('') : '';

    html += `<div class="result-card"><div class="card-header">
      <span>${escHtml(String(r.target))}</span><span class="status-badge ${sc}">${r.status==='ok'?'OK':'ERR'}</span></div>
      <div class="card-body"><div class="summary">${escHtml(String(r.summary))}</div>${mHtml}${cHtml}${tHtml}</div></div>`;
  });

  document.getElementById('results').innerHTML = html;
}
