#!/usr/bin/env node
// 参数面板的半运行时冒烟：用 DOM 桩**真实加载** params.js，灌入后端真实载荷，
// 断言渲染出的控件类型与文案。
//
// 审查 2026-09-24（P4 步骤④，第二十八轮）：
//   本轮删除了前端三份手写平行字典（PARAM_LABELS/PARAM_HINTS/PARAM_META，共 214 行），
//   参数面板的标签/提示/选项**全部改为后端派生**。静态文本断言无法证明
//   "删掉字典后面板还能正常渲染"，故本脚本把真实模块跑起来，覆盖：
//     · Choice 参数 → 下拉框，且选项文案来自 Spec（不是英文键名）
//     · 列参数（COLUMN_PARAMS）→ 列选择器，含「— 自动 —」空选项
//     · 数值参数 → 数字输入框
//     · 标签回退：接口未覆盖的键 → 键名本身（不空白）
//
// 用法：node scripts/check_params_panel.mjs
// 退出码：0 = 通过；1 = 发现问题

import { execFileSync } from 'node:child_process';
import { readFileSync, unlinkSync } from 'node:fs';
import os from 'node:os';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { missingPythonMessage, resolvePython } from './_probe_python.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..');
const STATIC = resolve(REPO_ROOT, 'src', 'smartsuite', 'web', 'static');

const problems = [];
function check(ok, msg) {
  if (!ok) problems.push(msg);
  return ok;
}

// ── 最小 DOM 桩 ────────────────────────────────────────────────
class FakeEl {
  constructor(tag = 'div') {
    this.tagName = tag;
    this.style = {};
    this.dataset = {};
    this.children = [];
    this.value = '';
    this.innerHTML = '';
    this.textContent = '';
    this._listeners = {};
    this._classes = new Set();
    this.classList = {
      add: (c) => this._classes.add(c),
      remove: (c) => this._classes.delete(c),
      contains: (c) => this._classes.has(c),
      toggle: () => {},
    };
  }
  addEventListener(ev, fn) { (this._listeners[ev] ||= []).push(fn); }
  removeEventListener() {}
  appendChild(c) { this.children.push(c); return c; }
  remove() {}
  click() {}
  closest() { return null; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  setAttribute() {}
  getAttribute() { return null; }
}

const elements = new Map();
const el = (id) => {
  if (!elements.has(id)) elements.set(id, new FakeEl());
  return elements.get(id);
};

globalThis.document = {
  getElementById: (id) => el(id),
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement: (tag) => new FakeEl(tag),
  addEventListener: () => {},
  body: new FakeEl('body'),
};
globalThis.window = { addEventListener: () => {}, location: { href: '' } };
globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });

// ── 加载真实模块 ────────────────────────────────────────────────
const state = await import(pathToFileURL(resolve(STATIC, 'state.js')).href);
// `columnData` 是 `export let` 的数组 —— 直接改内容即可（`export let` 导出的是活绑定，
// 但数组本身可变，故 push 生效；不需要 setter）
state.columnData.push({ name: 'y' }, { name: 'x1' }, { name: '组别' });

const params = await import(pathToFileURL(resolve(STATIC, 'params.js')).href);

// ── 后端真实载荷（与 /api/tasks 同构）──────────────────────────
// 由 Python 侧**真实生成**，保证与 derive_param_labels/hints/options 完全一致 ——
// 不在此处手写任何标签/选项，否则又成了一份会漂移的平行副本。
//
// 说明：`stdio: 'ignore'` + 临时文件（而非管道捕获）—— 在受限沙箱下，
// 程序无法打开命名管道，`execFileSync` 的默认 `pipe` 会 EPERM。
const PAYLOAD = (() => {
  // 审查 2026-10-09 P0-11：原先写死 `.venv/Scripts/python.exe`（Windows 专属布局），
  // 在 Linux/macOS（`.venv/bin/python`）与无仓库内 venv 的干净检出中抛未捕获 ENOENT
  // → ci.yml quick 必红。改为跨平台探测；找不到时给中文 FAIL 而非堆栈。
  const py = resolvePython({ repoRoot: REPO_ROOT });
  if (!py) {
    console.error(missingPythonMessage('check_params_panel.mjs'));
    process.exit(1);
  }
  const out = resolve(os.tmpdir(), `ss-params-payload-${process.pid}.json`);
  const code = `
import json, sys
from smartsuite.services.param_labels import (
    derive_param_labels, derive_param_hints, derive_param_options,
)
from smartsuite.services.task_spec import TASK_SPECS
from smartsuite.services.orchestrator import DEFAULT_PARAMS
payload = {
    "params": {s.key: DEFAULT_PARAMS.get(s.key, {}) for s in TASK_SPECS},
    "param_labels": derive_param_labels(),
    "param_hints": derive_param_hints(),
    "param_options": derive_param_options(),
}
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False)
`;
  execFileSync(py, ['-c', code, out], {
    cwd: REPO_ROOT,
    env: { ...process.env, PYTHONPATH: 'src' },
    stdio: 'ignore',
  });
  const data = JSON.parse(readFileSync(out, 'utf8'));
  unlinkSync(out);
  return data;
})();

check(params.hydrateParams(PAYLOAD) !== false, 'hydrateParams 应成功');
check(params.paramsHydrated() === true, 'paramsHydrated() 应为 true');

// ── 断言 1：Choice 参数 → 下拉框，文案来自 Spec ─────────────────
{
  const html = params.buildParamInput('ss_type', 2, 'anova');
  check(html.includes('<select'), `ss_type 应渲染为下拉框，实际: ${html.slice(0, 90)}`);
  check(html.includes('Type II'), `ss_type 选项应含 Spec 的中文文案，实际: ${html.slice(0, 200)}`);
  check(!html.includes('>ss_type<'), 'ss_type 标签不应回退为英文键名');
  check(html.includes('平方和类型'), `ss_type 标签应为中文，实际: ${html.slice(0, 120)}`);
}

{
  const html = params.buildParamInput('test', 'ttest_ind', 'hypothesis_test');
  check(html.includes('<select'), 'hypothesis_test.test 应渲染为下拉框');
  check(html.includes('独立样本 t 检验'), 'test 选项应含中文检验名');
  // 17 种检验方法全部可达（审查 E1-2 的历史承诺）
  const n = (html.match(/<option /g) || []).length;
  check(n === 17, `test 下拉应有 17 个选项（引擎全集），实际 ${n}`);
}

// ── 断言 2：列参数 → 列选择器（含「— 自动 —」）─────────────────
{
  const html = params.buildParamInput('group_col', null, 'spc_xbar');
  check(html.includes('— 自动 —'), `group_col 应渲染列选择器（含空选项），实际: ${html.slice(0, 120)}`);
  check(html.includes('分组依据'), `group_col 标签应为中文，实际: ${html.slice(0, 120)}`);
}

// ── 断言 3：数值参数 → 数字输入框（默认值是 number）────────────
{
  const html = params.buildParamInput('n_bootstrap', 2000, 'bootstrap_ci');
  check(html.includes('type="number"'), `n_bootstrap 应渲染数字框，实际: ${html.slice(0, 120)}`);
  check(html.includes('重抽样次数'), `n_bootstrap 标签应为中文，实际: ${html.slice(0, 120)}`);
}

// ── 断言 4：标签回退到键名（接口未覆盖时不得空白）──────────────
{
  const html = params.buildParamInput('no_such_param', 1, 'no_such_task');
  check(html.includes('>no_such_param<'), '未覆盖的键应回退为键名，不得空白');
}

// ── 断言 5：手写平行字典确实已从 params.js 移除 ────────────────
{
  const src = readFileSync(resolve(STATIC, 'params.js'), 'utf8');
  for (const dead of ['PARAM_LABELS', 'PARAM_HINTS', 'PARAM_META']) {
    check(!new RegExp(`const ${dead} = \\{`).test(src), `${dead} 不应再出现在 params.js`);
  }
  check(/COLUMN_PARAMS/.test(src), 'COLUMN_PARAMS（列选择器表）应保留');
}

// ── 输出 ────────────────────────────────────────────────────────
if (problems.length) {
  console.error('FAIL: 参数面板冒烟未通过');
  for (const p of problems) console.error('  - ' + p);
  process.exit(1);
}
console.log('OK: 参数面板冒烟通过（真实加载 params.js + 后端真实载荷 + 5 组断言）');
