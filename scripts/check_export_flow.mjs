#!/usr/bin/env node
// 前端导出链路的半运行时冒烟：在 Node 里用 DOM/fetch 桩**真实加载** app.js，
// 调用其导出函数并断言行为。
//
// 审查 2026-09-24（P5.3，第十九轮）：
//   Playwright 在本环境不可用（未安装，且安装需下载浏览器）。而上一轮新增的
//   导出按钮当时只有**静态文本断言**，等于"从未执行过那行代码"。
//   本脚本用最小 DOM 桩把真实模块跑起来，覆盖：
//     · 未运行分析时的提示分支
//     · 成功路径：fetch 请求体 / Content-Disposition 解析 / Blob 下载 / URL 释放
//     · 失败路径：显示服务端中文原因且不下载
//     · 事件委托接线：`data-action="export-report"` 真的能被点响应
//
// 用法：node scripts/check_export_flow.mjs
// 退出码：0 = 通过；1 = 发现问题（逐条打印）

import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP_JS = resolve(HERE, '..', 'src', 'smartsuite', 'web', 'static', 'app.js');

const problems = [];
function check(ok, msg) {
  if (!ok) problems.push(msg);
  return ok;
}

// ── 最小 DOM 桩 ────────────────────────────────────────────────
// 只需支撑 app.js 的模块级副作用（getElementById + addEventListener）
// 与导出链路的调用面；不追求 DOM 语义完整。

class FakeEl {
  constructor(tag = 'div') {
    this.tagName = tag;
    this.style = {};
    this.dataset = {};
    this.children = [];
    this.value = '';
    this.innerHTML = '';
    this.textContent = '';
    this.disabled = false;
    this.href = '';
    this.download = '';
    this.clicked = false;
    this._listeners = {};
    // showToast 调 classList.add('show')；不提供会抛 TypeError（首版即如此）
    this._classes = new Set();
    this.classList = {
      add: (c) => this._classes.add(c),
      remove: (c) => this._classes.delete(c),
      contains: (c) => this._classes.has(c),
      toggle: (c) => (this._classes.has(c) ? this._classes.delete(c) : this._classes.add(c)),
    };
  }
  addEventListener(ev, fn) { (this._listeners[ev] ||= []).push(fn); }
  removeEventListener() {}
  appendChild(c) { this.children.push(c); return c; }
  remove() { this.removed = true; }
  click() { this.clicked = true; }
  closest() { return null; }
  querySelectorAll() { return []; }
  setAttribute() {}
  getAttribute() { return null; }
}

const elements = new Map();
const el = (id) => {
  if (!elements.has(id)) elements.set(id, new FakeEl());
  return elements.get(id);
};

/** document 上注册的 click 委托监听器（app.js 用事件委托统一处理交互）。 */
const clickListeners = [];

globalThis.document = {
  getElementById: el,
  querySelectorAll: () => [],
  createElement: (tag) => new FakeEl(tag),
  addEventListener: (ev, fn) => { if (ev === 'click') clickListeners.push(fn); },
  body: new FakeEl('body'),
};
globalThis.window = globalThis;

// ── fetch / URL / Blob 桩 ──────────────────────────────────────
let lastFetch = null;
let fetchResponder = () => ({
  ok: true, status: 200, headers: { get: () => '' },
  json: async () => ({ params: {} }), blob: async () => ({ size: 1 }),
});
globalThis.fetch = async (url, opts) => { lastFetch = { url, opts }; return fetchResponder(); };

const revoked = [];
const createdObjectUrls = [];
globalThis.URL = {
  createObjectURL: () => { const u = `blob:fake-${createdObjectUrls.length}`; createdObjectUrls.push(u); return u; },
  revokeObjectURL: (u) => revoked.push(u),
};
globalThis.Blob = class { constructor(parts) { this.parts = parts; } };

// ── 加载真实模块 ───────────────────────────────────────────────
let app;
try {
  app = await import(pathToFileURL(APP_JS).href);
} catch (e) {
  console.log(`FAIL: app.js 加载失败：${e.message}`);
  process.exit(1);
}

/** 驱动一次事件委托点击（模拟用户点带 data-action 的按钮）。 */
function clickAction(action, dataset = {}) {
  const target = new FakeEl('button');
  target.dataset = { action, ...dataset };
  target.closest = (sel) => (sel === '[data-action]' ? target : null);
  for (const fn of clickListeners) fn({ target });
}

const flush = () => new Promise((r) => setTimeout(r, 0));
const toast = () => String(el('toast').textContent || '');

// ── 用例 0：事件委托已接线 ─────────────────────────────────────
check(clickListeners.length > 0, '未注册 click 事件委托 —— 导出按钮永远不会响应');

// ── 用例 1：未运行分析时提示而非发请求 ─────────────────────────
lastFetch = null;
clickAction('export-report', { format: 'html' });
await flush();
check(lastFetch === null, '未运行分析时不应发导出请求');
check(toast().includes('分析'), `未运行分析时应提示，实际 toast=${toast()}`);

// ── 用例 2：成功路径 ──────────────────────────────────────────
// `rememberRequest` 是导出链路唯一的注入点（也是生产代码里记录请求的唯一入口）
app.rememberRequest({
  task: 'normality_check',
  targets: ['测量值'],
  features: [],
  categoricals: [],
  params: { alpha: 0.05 },
});
fetchResponder = () => ({
  ok: true,
  status: 200,
  headers: {
    get: (h) =>
      h === 'Content-Disposition'
        ? 'attachment; filename="normality_check.pdf"'
        : '',
  },
  blob: async () => ({ size: 1234 }),
});
lastFetch = null;
revoked.length = 0;
createdObjectUrls.length = 0;

await app.exportReport('pdf');
await flush();

if (check(lastFetch !== null, 'exportReport 未发起 /api/export 请求')) {
  check(lastFetch.url === '/api/export', `URL 应为 /api/export，实际 ${lastFetch.url}`);
  check(lastFetch.opts?.method === 'POST', '导出必须用 POST');
  const body = JSON.parse(lastFetch.opts.body || '{}');
  check(body.format === 'pdf', `请求体应含 format=pdf，实际 ${body.format}`);
  check(body.task === 'normality_check', `请求体应含 task，实际 ${body.task}`);
  check(body.params?.alpha === 0.05, '请求体应带上原分析的参数（服务端据此重跑）');
  check(
    lastFetch.opts.headers?.['X-CSRF-Token'] !== undefined,
    '导出必须带 CSRF token（经 fetchWithCsrf）'
  );
}
check(createdObjectUrls.length === 1, `应创建 1 个 blob URL，实际 ${createdObjectUrls.length}`);
check(revoked.length === 1, `blob URL 未释放（内存泄漏），revoked=${revoked.length}`);
check(toast().includes('已下载'), `成功导出后应提示已下载，实际 toast=${toast()}`);

// ── 用例 3：失败路径 → 显示服务端原因，且不下载 ─────────────────
fetchResponder = () => ({
  ok: false,
  status: 400,
  headers: { get: () => '' },
  json: async () => ({ error: '不支持的报告格式「docx」' }),
});
lastFetch = null;
revoked.length = 0;
createdObjectUrls.length = 0;

await app.exportReport('docx');
await flush();

check(
  toast().includes('不支持'),
  `失败时应显示服务端中文原因，实际 toast=${toast()}`
);
check(createdObjectUrls.length === 0, '失败时不应创建 blob URL（不该下载空文件）');

// ── 用例 4：Content-Disposition 解析（纯函数，逐个形态）──────────
const cases = [
  ['attachment; filename="a.pdf"', 'a.pdf'],
  ['attachment; filename=a.pdf', 'a.pdf'],
  ["attachment; filename*=UTF-8''b%20c.pdf", 'b%20c.pdf'],
  ['', ''],
  [null, ''],
  ['inline', ''],
];
for (const [hdr, want] of cases) {
  const got = app.parseDownloadFilename(hdr);
  check(got === want, `parseDownloadFilename(${JSON.stringify(hdr)}) → ${JSON.stringify(got)}，期望 ${JSON.stringify(want)}`);
}

// ── 用例 5：头部缺失时用任务名兜底 ─────────────────────────────
fetchResponder = () => ({
  ok: true, status: 200, headers: { get: () => '' }, blob: async () => ({ size: 1 }),
});
createdObjectUrls.length = 0;
// 用一个能捕获 download 文件名的桩
const captured = [];
const origCreate = document.createElement.bind(document);
document.createElement = (tag) => {
  const e = origCreate(tag);
  if (tag === 'a') {
    const origClick = e.click.bind(e);
    e.click = () => { captured.push(e.download); origClick(); };
  }
  return e;
};
await app.exportReport('html');
await flush();
check(
  captured.some((n) => n === 'normality_check.html'),
  `Content-Disposition 缺失时应回落到 任务名.格式，实际捕获 ${JSON.stringify(captured)}`
);

// ── 报告 ──────────────────────────────────────────────────────
if (problems.length) {
  console.log(`FAIL: 前端导出链路冒烟未通过（${problems.length} 项）`);
  for (const p of problems) console.log(`  - ${p}`);
} else {
  console.log(
    'OK: 前端导出链路冒烟通过（加载真实模块 + 事件委托接线 + 成功/失败/文件名 5 组断言）'
  );
}
process.exit(problems.length ? 1 : 0);
