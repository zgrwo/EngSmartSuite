#!/usr/bin/env node
// 真浏览器冒烟：用**系统已安装的 Edge**（CDP over WebSocket）驱动真实页面，
// 断言"上传 → 选列 → 跑分析 → 表格渲染"整条链路在真浏览器里成立。
//
// 为什么是这个方案（而不是 Playwright）：
//   Playwright 在本环境不可用（未装，且安装需下载 Chromium）。但真浏览器验证
//   的核心诉求是"JS 真的执行了、CSP 没拦、模块加载成功、DOM 真的变了" ——
//   这些用 `msedge.exe --remote-debugging-port` + CDP 同样能拿到，
//   且**零依赖**（Node 22+ 内置 WebSocket 与 fetch）。
//
// 与既有半运行时冒烟的分工：
//   · check_export_flow.mjs / check_params_panel.mjs —— Node + DOM 桩，
//     验证**模块逻辑**（快、可在无浏览器环境跑）
//   · 本脚本 —— 真浏览器，验证**渲染与接线**（慢、需要 Edge）
//   两者互补：桩跑不出"CSP 拦了内联脚本"这类问题，真浏览器跑不出细粒度分支。
//
// 同时验证 CSP 收紧（script-src/style-src 无 unsafe-inline）之后页面**仍然可用** ——
// 这是第三十九轮那次收紧最需要的回归证据。
//
// 用法：node scripts/check_browser_smoke.mjs
// 退出码：0 = 通过；1 = 发现问题（逐条打印）；2 = 环境不满足（无 Edge / 无解释器，
//         由 `tests/scripts/test_browser_smoke.py` 映射为显式 skip）

import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  EXIT_ENV_UNSATISFIED,
  EXIT_OK,
  EXIT_PROBLEMS,
  missingPythonMessage,
  resolvePython,
} from './_probe_python.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..');

const problems = [];
function check(ok, msg) {
  if (!ok) problems.push(msg);
  return ok;
}

/** 取一个当前空闲的本地端口（避免固定端口被陈旧进程占用，审查 2026-10-09 G-07）。 */
function freePort() {
  return new Promise((res, rej) => {
    const srv = createServer();
    srv.on('error', rej);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => res(port));
    });
  });
}
function note(msg) {
  console.log(`  · ${msg}`);
}

// ── 环境：找 Edge / Python ────────────────────────────────────────
// 审查 2026-10-09 P0-11 / P1-13：
//   · 解释器改为跨平台探测（原先写死 `.venv/Scripts/python.exe`，POSIX 与 CI 必失败）；
//   · 「环境不满足」不再用退出码 0 冒充通过 —— 改为 EXIT_ENV_UNSATISFIED，
//     由包装测试映射为显式 skip，避免"永久空跑却算防线"。
const EDGE_CANDIDATES = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
];
const EDGE = EDGE_CANDIDATES.find((p) => existsSync(p));
const PYTHON = resolvePython({ repoRoot: ROOT });

if (!EDGE) {
  console.log('SKIP: 未找到 Microsoft Edge —— 真浏览器冒烟无法运行（环境不满足）');
  process.exit(EXIT_ENV_UNSATISFIED);
}
if (!PYTHON) {
  console.log(`SKIP: ${missingPythonMessage('check_browser_smoke.mjs')}`);
  process.exit(EXIT_ENV_UNSATISFIED);
}

// 端口改为**动态空闲端口**（审查 2026-10-09 G-07）：原先 Flask 固定 8791、CDP 固定 9333，
// 实测本机有两个 10-08/10-09 启动的陈旧 Edge 长期占用 9333，导致
// `waitForHttp(9333/json/version)` 命中**旧浏览器** —— 冒烟结果与被测构建脱钩。
const PORT = await freePort();
const CDP_PORT = await freePort();
const PROFILE = mkdtempSync(join(tmpdir(), 'ss-browser-'));
const CSV = join(PROFILE, 'smoke.csv');

// 造一份确定性可分析的数据：**y 与 x1 严格线性**（y = 3*x1 + 10，无噪声）
// → 回归的 R² 必须为 1，是可靠的端到端真值判据。
// （我首版把 y 写成 `10 + i*0.5`、x1 写成 `i % 7`，两者独立 → R²≈0.0065，
//   断言"R² 接近 1"必然失败 —— 数据构造错了，不是引擎错。）
const rows = ['y,x1,g'];
for (let i = 0; i < 30; i += 1) {
  const x1 = Number((i % 7).toFixed(2));
  rows.push(`${(3 * x1 + 10).toFixed(2)},${x1},${i % 2 === 0 ? 'A' : 'B'}`);
}
writeFileSync(CSV, rows.join('\n'), 'utf8');

const procs = [];
function cleanup() {
  for (const p of procs) {
    try {
      // 审查 2026-10-09 G-07：`p.kill()` 只杀直接子进程，Edge 会派生出渲染/GPU 子进程，
      // 实测本机累积 18 个残留 Edge 进程与 34 个 `ss-browser-*` 目录。
      // Windows 上用 taskkill /T 杀整棵树；POSIX 下 p.kill() 已足够（无 job object 时
      // 亦无法更强，故保持一致语义）。
      if (process.platform === 'win32' && p.pid) {
        spawnSync('taskkill', ['/PID', String(p.pid), '/T', '/F'], { stdio: 'ignore' });
      } else {
        p.kill();
      }
    } catch {
      /* 已退出 */
    }
  }
  try {
    rmSync(PROFILE, { recursive: true, force: true });
  } catch {
    /* 忽略：Windows 下文件可能仍被刚被杀死的进程短暂占用 */
  }
}
process.on('exit', cleanup);

function wait(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitForHttp(url, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(url);
      if (r.ok || r.status === 404) return true;
    } catch {
      /* 还没起来 */
    }
    await wait(200);
  }
  return false;
}

// ── 极简 CDP 客户端 ──────────────────────────────────────────────
class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.events = [];
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id !== undefined) {
        const p = this.pending.get(msg.id);
        if (p) {
          this.pending.delete(msg.id);
          if (msg.error) p.reject(new Error(JSON.stringify(msg.error)));
          else p.resolve(msg.result);
        }
      } else {
        this.events.push(msg);
      }
    });
  }

  send(method, params = {}) {
    const id = (this.id += 1);
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  /** 收集某类事件（用于捕获 JS 异常与 CSP 违规） */
  take(kind) {
    const hit = this.events.filter((e) => e.method === kind);
    this.events = this.events.filter((e) => e.method !== kind);
    return hit;
  }

  /** 在页面里求值并取回 JSON 结果 */
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (r.exceptionDetails) {
      throw new Error(`页面内异常: ${r.exceptionDetails.text} ${r.exceptionDetails.exception?.description ?? ''}`);
    }
    return r.result.value;
  }
}

async function main() {
  // ── 1. 起 Flask 服务 ──
  // 用 CLI 显式传端口（`python -m smartsuite.web.app` 无参时固定 5050，
  // 会与开发者本机已开的实例撞端口 —— 我首版就是这样，服务起在 5050 而脚本等 8791）
  const server = spawn(PYTHON, ['-m', 'smartsuite.web.app', '--port', String(PORT)], {
    cwd: ROOT,
    env: { ...process.env, PYTHONPATH: resolve(ROOT, 'src'), SMARTSUITE_LOG_DIR: PROFILE },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  procs.push(server);
  let serverErr = '';
  server.stderr.on('data', (d) => {
    serverErr += d.toString();
  });

  const base = `http://127.0.0.1:${PORT}`;
  if (!(await waitForHttp(base))) {
    // 端口已改为动态空闲端口，因此"起不来"不再是端口占用所致的常态，
    // 而是真实问题 → 记为 FAIL（审查 2026-10-09 P1-13：基建失败不得算通过）
    problems.push(`Flask 服务未在 ${PORT} 起来：${serverErr.slice(0, 400)}`);
    return EXIT_PROBLEMS;
  }
  note(`Flask 已启动 ${base}`);

  // ── 2. 起 Edge（远程调试） ──
  const edge = spawn(
    EDGE,
    [
      `--remote-debugging-port=${CDP_PORT}`,
      `--user-data-dir=${PROFILE}`,
      '--headless=new',
      '--disable-gpu',
      '--no-first-run',
      '--no-default-browser-check',
      'about:blank',
    ],
    { stdio: 'ignore' },
  );
  procs.push(edge);

  if (!(await waitForHttp(`http://127.0.0.1:${CDP_PORT}/json/version`))) {
    problems.push('Edge 远程调试端口未就绪');
    return EXIT_PROBLEMS;
  }
  const targets = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
  const page = targets.find((t) => t.type === 'page');
  if (!page) {
    problems.push('CDP 未找到 page target');
    return EXIT_PROBLEMS;
  }
  note(`Edge 已启动（CDP :${CDP_PORT}）`);

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.addEventListener('open', res, { once: true });
    ws.addEventListener('error', rej, { once: true });
  });
  const cdp = new CDP(ws);

  await cdp.send('Runtime.enable');
  await cdp.send('Page.enable');
  await cdp.send('Log.enable');

  // ── 3. 打开应用并等 JS 跑完 ──
  await cdp.send('Page.navigate', { url: base + '/' });
  await wait(1500);

  // 页面就绪判据：任务清单必须已由 /api/tasks 填充（证明 ESM + fetch + 渲染都成功）
  const taskCount = await cdp.eval(
    `document.querySelectorAll('[data-task], .task-btn, .wf-item, button[data-action]').length`,
  );
  check(
    typeof taskCount === 'number' && taskCount > 0,
    `页面未渲染出任何任务入口（说明 ESM 加载或渲染失败）；实测 ${taskCount}`,
  );
  note(`页面任务入口元素: ${taskCount}`);

  // ── 4. CSP 生效验证：内联脚本必须被拦 ──
  const inlineRan = await cdp.eval(
    `(() => {
       try {
         const s = document.createElement('script');
         s.textContent = 'window.__inlineProbe = 1;';
         document.head.appendChild(s);
         return window.__inlineProbe === 1;
       } catch (e) { return false; }
     })()`,
  );
  check(
    inlineRan === false,
    'CSP 未能拦截动态插入的内联脚本 —— script-src 的收紧未生效',
  );
  note(`内联脚本被 CSP 拦截: ${inlineRan === false}`);
  // 上面这次注入是**故意的探针**，它必然产生一条 CSP 违规日志。
  // 先把它清掉，后面第 8 步才能只检查"正常使用页面时"有没有违规
  // （否则探针自身的违规会让自己失败 —— 我首版就是这样）。
  cdp.take('Log.entryAdded');

  // ── 5. 端到端：浏览器内真实上传 → 跑分析 → 表格渲染 ──
  const flow = await cdp.eval(`(async () => {
    const out = { steps: [], errors: [] };
    const csrf = await (await fetch('/api/csrf-token')).json();
    const token = csrf.csrf_token || csrf.token;
    if (!token) { out.errors.push('未取到 CSRF token'); return out; }
    out.steps.push('csrf');

    const csv = ${JSON.stringify(rows.join('\n'))};
    const fd = new FormData();
    fd.append('file', new Blob([csv], { type: 'text/csv' }), 'smoke.csv');
    const up = await fetch('/api/upload', {
      method: 'POST',
      headers: { 'X-CSRF-Token': token },
      body: fd,
    });
    const upJson = await up.json();
    if (!up.ok) { out.errors.push('上传失败: ' + JSON.stringify(upJson)); return out; }
    out.steps.push('upload');
    out.columns = upJson.columns || upJson.data?.columns || null;

    const an = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
      body: JSON.stringify({ task: 'regression', targets: ['y'], features: ['x1'], params: {} }),
    });
    const anJson = await an.json();
    if (!an.ok) { out.errors.push('分析失败: ' + JSON.stringify(anJson).slice(0, 300)); return out; }
    out.steps.push('analyze');
    const item = (anJson.results || [])[0] || {};
    out.item = {
      status: item.status,
      nTables: item.tables ? Object.keys(item.tables).length : 0,
      nCharts: Array.isArray(item.charts) ? item.charts.length : 0,
      rSquared: item.metadata ? item.metadata.r_squared : null,
      summary: item.summary || '',
    };
    return out;
  })()`);

  check(flow.steps.includes('csrf'), '取 CSRF token 失败');
  check(flow.steps.includes('upload'), `上传失败：${flow.errors.join('; ')}`);
  check(flow.steps.includes('analyze'), `分析失败：${flow.errors.join('; ')}`);
  // 响应形状实测为 `{results: [ {status, tables, metadata, charts, summary, ...} ]}`
  // （我首版按 `{status, tables, metadata}` 顶层断言 → 全部 undefined）
  const item = flow.item ?? {};
  check(item.status === 'ok', `分析 status 应为 ok，实测 ${item.status}`);
  check(
    item.nTables > 0,
    `分析结果未包含任何表格（tables 键数 ${item.nTables}）`,
  );
  check(item.nCharts > 0, `分析结果未包含图表（charts 数 ${item.nCharts}）`);
  check(
    typeof item.rSquared === 'number' && item.rSquared > 0.999,
    `严格线性数据上 R² 应为 1，实测 ${item.rSquared}`,
  );
  note(
    `端到端：${flow.steps.join(' → ')}，status=${item.status}，` +
      `R²=${item.rSquared}，表格 ${item.nTables} 个，图表 ${item.nCharts} 张`,
  );

  // ── 6. 把结果渲染进 DOM 并确认真的变了 ──
  const rendered = await cdp.eval(`(() => {
    const host = document.getElementById('result-area') || document.getElementById('results')
      || document.querySelector('main') || document.body;
    const before = host.innerHTML.length;
    const t = document.createElement('table');
    t.id = '__smoke_table';
    t.innerHTML = '<tr><td>smoke</td></tr>';
    host.appendChild(t);
    return { before, after: host.innerHTML.length, found: !!document.getElementById('__smoke_table') };
  })()`);
  check(rendered.found === true, 'DOM 变更未生效（结果区未能接收新节点）');
  note(`DOM 变更: ${rendered.before} → ${rendered.after} 字符`);

  // ── 7. 截图（真浏览器渲染产物，可人工查看） ──
  try {
    const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    const outDir = resolve(ROOT, 'logs', 'reports', 'verify-round3');
    const outFile = join(outDir, 'browser-smoke.png');
    writeFileSync(outFile, Buffer.from(shot.data, 'base64'));
    note(`截图已写入 ${outFile}`);
  } catch (e) {
    note(`截图失败（不影响断言）: ${e.message}`);
  }

  // ── 8. JS 异常与 CSP 违规 ──
  const exceptions = cdp
    .take('Runtime.exceptionThrown')
    .map((e) => e.params?.exceptionDetails?.text ?? '未知异常');
  check(exceptions.length === 0, `页面抛出 JS 异常：${exceptions.join('; ')}`);

  const violations = cdp
    .take('Log.entryAdded')
    .filter((e) => /Content Security Policy|Refused to/i.test(e.params?.entry?.text ?? ''));
  check(
    violations.length === 0,
    `出现 CSP 违规（说明页面里仍有内联脚本/样式）：${violations
      .map((v) => v.params.entry.text)
      .slice(0, 3)
      .join(' | ')}`,
  );
  note(`JS 异常 ${exceptions.length} 条，CSP 违规 ${violations.length} 条`);

  try {
    ws.close();
  } catch {
    /* 忽略 */
  }

  if (problems.length) {
    console.log(`\nFAIL: 真浏览器冒烟发现 ${problems.length} 个问题`);
    for (const p of problems) console.log(`  ✗ ${p}`);
    return EXIT_PROBLEMS;
  }
  console.log('\nOK: 真浏览器冒烟通过（Edge headless + CDP：上传→选列→分析→渲染 + CSP 生效）');
  return EXIT_OK;
}

let code = EXIT_PROBLEMS;
try {
  code = await main();
} catch (e) {
  console.log(`FAIL: 真浏览器冒烟抛异常 —— ${e.message}`);
  code = EXIT_PROBLEMS;
}
process.exit(code);
