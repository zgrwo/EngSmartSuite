// SmartSuite Web UI
let columnData = [];
let selectedY = new Set(), selectedX = new Set(), selectedCat = new Set();
const catKw = ['日期','班次','车间','机台','模具','编号','操作','检验',
  '原料','类型','批号','冷却','循环','模式','分区','保养','环境',
  '产品代码','色母','嵌件','首件','外观','尺寸','需返工','报警','换料'];
const yKw = ['不良','强度','伸长','冲击','粗糙','偏差','波动','效率'];

// File upload
document.getElementById('file-input').addEventListener('change', async e => {
  const f = e.target.files[0]; if (!f) return;
  document.getElementById('filename').textContent = f.name;
  const fd = new FormData(); fd.append('file', f);
  const r = await fetch('/api/upload', { method: 'POST', body: fd });
  const d = await r.json();
  columnData = d.columns || [];
  document.getElementById('shape').textContent = d.shape ? `(${d.shape.join(' × ')})` : '';
  renderCols(); autoDetect();
});

// Column rendering
function renderCols() {
  document.getElementById('col-list').innerHTML = columnData.map((c, i) => `
    <div class="col-row">
      <span class="col-name" title="${c.name} (${c.dtype}, ${c.nunique} unique, ${c.missing} NA)">${c.name}</span>
      <input type="checkbox" id="cat${i}" ${selectedCat.has(c.name)?'checked':''}
        onchange="toggle('${c.name}','cat',this.checked)">
      <span class="tag cat">类</span>
      <input type="checkbox" id="x${i}" ${selectedX.has(c.name)?'checked':''}
        onchange="toggle('${c.name}','x',this.checked)">
      <span class="tag x">X</span>
      <input type="checkbox" id="y${i}" ${selectedY.has(c.name)?'checked':''}
        onchange="toggle('${c.name}','y',this.checked)">
      <span class="tag y">Y</span>
    </div>`).join('');
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

// Parameter config per task
const TASK_PARAMS = {
  grid_search: { ranges: '', direction: 'maximize', n_points: 10 },
  process_capability: { usl: '', lsl: '' },
  hypothesis_test: { test: 'ttest_ind' },
  trend_forecast: { forecast_steps: 5 },
  anomaly_detect: { method: 'iqr' },
  response_surface: { direction: 'maximize' },
  multi_objective: { objectives: '' },
  decision_tree: { max_depth: 5 },
  anova: { alpha: 0.05, interactions: 0 },
  spc_nonparametric: { side: 'two-sided' },
  spc_cusum: { k: 0.5, h: 5.0 },
  spc_ewma: { lam: 0.2, L: 2.7 },
  spc_attribute: { chart_type: 'c' },
  power_analysis: { mode: 'required_n', test_type: 'ttest', effect_size: 0.5 },
  bootstrap_ci: { statistic: 'mean', n_bootstrap: 500 },
  median_ci: { ci_level: 0.95 },
  quantile_regression: { quantile: 0.5 },
  tolerance_interval: { coverage: 0.99, confidence: 0.95, side: 'two-sided' },
  gage_rr: { part_col: '', operator_col: '' },
};
const PARAM_HINTS = {
  ranges: '格式: 料温:180,220;模具温度:40,80',
  objectives: '格式: 强度:maximize;不良率:minimize',
  side: 'two-sided(双侧) | upper(越小越好) | lower(越大越好)',
  chart_type: 'p(不良率) | np(不良数) | c(缺陷数) | u(单位缺陷率)',
};

function showParams(task) {
  const panel = document.getElementById('param-panel');
  const body = document.getElementById('param-body');
  const cfg = TASK_PARAMS[task];
  if (!cfg) { panel.style.display = 'none'; return; }
  panel.style.display = 'block';
  body.innerHTML = Object.entries(cfg).map(([k,v]) => `
    <div style="margin:4px 0;font-size:11px">
      <label style="display:block;color:#666;margin-bottom:1px">${k}</label>
      ${PARAM_HINTS[k] ? `<div style="font-size:9px;color:#999;margin-bottom:2px">${PARAM_HINTS[k]}</div>` : ''}
      <input type="text" id="param_${k}" value="${v}" placeholder="${PARAM_HINTS[k]||''}"
        style="width:100%;padding:3px 6px;border:1px solid #ccc;border-radius:3px;font-size:11px">
    </div>`).join('');
}

function getParams(task) {
  const cfg = TASK_PARAMS[task];
  if (!cfg) return {};
  const p = {};
  Object.keys(cfg).forEach(k => {
    const el = document.getElementById('param_'+k);
    if (!el) return;
    let v = el.value.trim();
    if (v === '') return; // empty means skip this param

    if (k === 'ranges') {
      // Parse: "料温:180,220; 模具温度:40,80" -> {料温:[180,220],模具温度:[40,80]}
      try { v = v.split(';').filter(Boolean).reduce((o,s) => { const [ky,lo,hi]=s.split(':'); o[ky.trim()]=[+lo,+hi]; return o; }, {}); if (!Object.keys(v).length) return; }
      catch(e) { return; }
    } else if (k === 'objectives') {
      // Parse: "强度:maximize;不良率:minimize" -> [{col:'强度',direction:'maximize'},...]
      try { v = v.split(';').filter(Boolean).map(s => { const [col,dir] = s.trim().split(':'); return {col:col.trim(),direction:dir?.trim()||'maximize'}; }); if (!v.length) return; }
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

async function runAnalysis(task) {
  if (!selectedY.size) { alert('请至少选择一个 Y 列'); return; }
  if (task !== 'process_capability' && task !== 'trend_forecast' && task !== 'anomaly_detect'
      && task !== 'power_analysis' && task !== 'spc_nonparametric' && !selectedX.size) {
    alert('请至少选择一个 X 列'); return;
  }
  // 有参数配置 → 第一步: 显示参数面板, 等待用户编辑后点"运行"
  if (TASK_PARAMS[task]) {
    _pendingTask = task;
    showParams(task);
    // 在参数面板底部加"运行"按钮
    const body = document.getElementById('param-body');
    body.innerHTML += `<button onclick="executeAnalysis()" style="margin-top:8px;width:100%;
      padding:6px;background:#2171b5;color:white;border:none;border-radius:3px;
      font-size:12px;cursor:pointer">▶ 运行分析</button>`;
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
  document.getElementById('param-panel').style.display = 'none';
  document.querySelectorAll('.btn-analysis').forEach(b => b.disabled = true);
  document.getElementById('results').innerHTML =
    '<div class="empty-hint"><div class="spinner"></div> 分析中...</div>';
  try {
    const r = await fetch('/api/analyze', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task, targets: [...selectedY], features: [...selectedX],
        categoricals: [...selectedCat], params: getParams(task) })
    });
    const d = await r.json();
    renderResults(d.results || []);
  } catch(e) {
    document.getElementById('results').innerHTML =
      `<div class="empty-hint" style="color:#c62828">错误: ${e.message}</div>`;
  } finally {
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
    const hdr = '<th></th>' + tbl.columns.map(c => `<th>${c}</th>`).join('');
    const rows = tbl.data.map((row, i) =>
      `<tr><td><b>${tbl.index[i]}</b></td>${row.map(v =>
        `<td style="color:${Math.abs(v)>0.2?'#c62828':'#333'}">${typeof v==='number'?v.toFixed(3):v}</td>`
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
      const hdr = tbl.columns.map(c => `<th>${c}</th>`).join('');
      const rows = tbl.data.map((row, i) =>
        `<tr><td>${tbl.index[i]||''}</td>${row.map(v =>
          `<td>${typeof v==='number'?v.toFixed(4):v}</td>`).join('')}</tr>`
      ).join('');
      tHtml += `<div class="table-wrap"><h4>${tn} (${tbl.shape[0]}×${tbl.shape[1]})</h4>
        <table><thead><tr><th></th>${hdr}</tr></thead><tbody>${rows}</tbody></table></div>`;
    }
    let cHtml = (r.charts||[]).map(b => `<div class="chart-wrap"><img src="data:image/png;base64,${b}"></div>`).join('');
    let mHtml = r.messages?.length ? r.messages.map(m => `<div class="messages">${m}</div>`).join('') : '';

    html += `<div class="result-card"><div class="card-header">
      <span>${r.target}</span><span class="status-badge ${sc}">${r.status==='ok'?'OK':'ERR'}</span></div>
      <div class="card-body"><div class="summary">${r.summary}</div>${mHtml}${cHtml}${tHtml}</div></div>`;
  });

  document.getElementById('results').innerHTML = html;
}
