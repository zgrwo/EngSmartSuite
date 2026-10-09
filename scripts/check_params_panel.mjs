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
import { readFileSync, unlinkSync, writeFileSync } from 'node:fs';
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

// ── 浏览器取值语义（模块级：断言 6/7/8 共用）────────────────────
/** 按浏览器语义取控件当前值：select 取 selected（无则首个）option 的 value。 */
function browserValueOf(html) {
  const sel = html.match(/<select[^>]*>([\s\S]*?)<\/select>/);
  if (sel) {
    const opts = [...sel[1].matchAll(/<option value="([^"]*)"([^>]*)>/g)];
    if (!opts.length) return { tag: 'SELECT', value: '' };
    const chosen = opts.find((o) => /\bselected\b/.test(o[2])) ?? opts[0];
    return { tag: 'SELECT', value: chosen[1] };
  }
  const inp = html.match(/<input[^>]*\bvalue="([^"]*)"/);
  return { tag: 'INPUT', value: inp ? inp[1] : '' };
}

/** 该下拉框里**显式**带 `selected` 的 option 值；无则 `null`（= 浏览器会隐式选首项）。 */
function explicitlySelected(html) {
  const sel = html.match(/<select[^>]*>([\s\S]*?)<\/select>/);
  if (!sel) return null;
  const chosen = [...sel[1].matchAll(/<option value="([^"]*)"([^>]*)>/g)].filter((o) =>
    /\bselected\b/.test(o[2]),
  );
  return chosen.length === 1 ? chosen[0][1] : null;
}

// ── 断言 6：默认值往返（渲染 → 浏览器取值 → getParams → **必须等于声明默认值**）──
// 审查 2026-10-09 C-4：原判据只有"载荷被 Spec 接受"（Python 侧）—— 那是**必要不充分**：
// `Choice` 掉一个空选项后下发的 `boxcox` 也是合法选项，Spec 自然接受，于是"面板把默认值
// 悄悄换成了别的值"整条链全绿（注入 I-2 实测 23 passed + node OK）。本断言把它补上：
// **未经用户编辑时，面板回读值必须与 `DEFAULT_PARAMS[task]` 逐键相等**。
// 审查 2026-10-09 P0-1：旧断言只覆盖"渲染出来的 HTML 长什么样"，**没有一条**覆盖
// 「渲染出的默认值能被原样读回并送给引擎」。于是 `value="${v}"` 把 `None` 默认值
// 写成了字面量 `null`：`getParams` 只丢空串（`:484`），`isNaN('null')` 为真
// 使数值转换被跳过（`:509`）→ 字符串 `"null"` 原样下发 → 9 个任务默认流程失效
// （7 个硬报错：usl/lsl/group_col 无法解析；2 个静默错数：proportion_ci 0.0000、
// lasso R² 0.785 vs 0.981）。
{
  const badLiteral = [];
  const typeDrift = [];
  const defaultDrift = [];
  let roundtripped = 0;

  /**
   * 「面板回读值 == 声明默认值」的比较口径（与 Python 侧
   * `tests/scripts/test_params_panel.py::_same_default` 保持同一语义）。
   *
   * 归一化：`None`/`''`/空数组 = 「未下发」（引擎落回自己的默认值，与哨兵等价）；
   * 布尔按小写字符串比（`<input>` 里 `true` 是文本）；两侧都是数就按数比
   * （`<select>` 只能发字符串，`2` 与 `"2"` 必须视为同一个值）。
   */
  const _empty = (v) =>
    v === null || v === undefined || v === '' || (Array.isArray(v) && v.length === 0);
  const _canon = (v) => {
    if (_empty(v)) return null;
    if (typeof v === 'boolean') return v ? 'true' : 'false';
    return v;
  };
  function sameDefault(declared, sent) {
    const a = _canon(declared);
    const b = _canon(sent);
    if (a === null || b === null) return a === null && b === null;
    const ta = String(a).trim();
    const tb = String(b).trim();
    const na = Number(ta);
    const nb = Number(tb);
    if (ta !== '' && tb !== '' && Number.isFinite(na) && Number.isFinite(nb)) return na === nb;
    return String(a) === String(b);
  }

  for (const task of Object.keys(PAYLOAD.params)) {
    const cfg = PAYLOAD.params[task] || {};
    const tags = {};
    // 每个任务前清空 DOM 桩：真实浏览器里 `showParams` 会整体替换 `param-body` 的
    // innerHTML，故面板**只含当前任务**的控件。共用一份 elements 映射会让上一个
    // 任务同名键（如 method 在 correlation/doe_design/anomaly_detect 三处语义不同）
    // 的值泄漏到本任务 —— 那是桩的假象，不是产品缺陷。
    elements.clear();
    for (const [k, v] of Object.entries(cfg)) {
      const { tag, value } = browserValueOf(params.buildParamInput(k, v, task));
      tags[k] = tag;
      const node = el(`param_${k}`);
      node.tagName = tag;
      node.value = value;
    }
    const sent = params.getParams(task);
    for (const [k, v] of Object.entries(sent)) {
      roundtripped += 1;
      if (v === 'null' || v === 'undefined' || v === 'NaN') {
        badLiteral.push(`${task}.${k}=${JSON.stringify(v)}`);
      }
    }
    for (const [k, v] of Object.entries(cfg)) {
      // 仅对 `<input>` 判类型漂移：`<select>` 的 option.value 天生是字符串，
      // 其字符串形式能否被引擎接受由 Python 侧结构门禁保证
      // （tests/services/test_param_spec_registry.py::TestEveryUiSelectableValueIsAccepted）。
      if (tags[k] === 'INPUT' && typeof v === 'number' && k in sent && typeof sent[k] !== 'number') {
        typeDrift.push(`${task}.${k}: 默认 ${v}(number) → 下发 ${JSON.stringify(sent[k])}(${typeof sent[k]})`);
      }
      // C-4 核心判据：**未经用户编辑**时，回读值必须与声明默认值等价。
      // `k in sent` 为假 = 面板没下发该键 → 只有"声明值本身就是空哨兵"才允许
      // （引擎会落回自己的默认值）；非空默认值没被下发同样是漂移。
      if (!sameDefault(v, k in sent ? sent[k] : null)) {
        defaultDrift.push(
          `${task}.${k}: 声明默认值 ${JSON.stringify(v)}(${typeof v}) → 面板回读 ` +
            (k in sent ? `${JSON.stringify(sent[k])}(${typeof sent[k]})` : '「未下发」'),
        );
      }
    }
  }

  check(roundtripped > 0, '往返扫描未覆盖任何参数（断言将恒真，扫描器失效）');
  check(
    badLiteral.length === 0,
    `面板下发了字面量 null/undefined：${badLiteral.slice(0, 8).join(', ')}` +
      `${badLiteral.length > 8 ? ` …共 ${badLiteral.length} 处` : ''}`,
  );
  check(typeDrift.length === 0, `数值默认值被字符串化：${typeDrift.slice(0, 8).join('; ')}`);
  check(
    defaultDrift.length === 0,
    `面板回读值与声明默认值不一致（Web 默认流程会跑出与 CLI/手册不同的参数）：\n      ` +
      defaultDrift.slice(0, 8).join('\n      ') +
      `${defaultDrift.length > 8 ? `\n      …共 ${defaultDrift.length} 处` : ''}`,
  );
  console.log(`  · 往返覆盖 ${roundtripped} 个键`);

  // 审查 2026-10-09 P1-2：把回读结果落盘，供 Python 侧断言「面板能发出的载荷，
  // 引擎的参数契约必须接受」。JS 只能证明"没有字面量 null"，能否被引擎接受
  // 只有 Python 侧的 Spec 说了算 —— 两层合起来才是完整往返。
  const dumpPath = process.env.SMARTSUITE_PARAMS_DUMP;
  if (dumpPath) {
    const payload = {};
    for (const task of Object.keys(PAYLOAD.params)) {
      const cfg = PAYLOAD.params[task] || {};
      elements.clear(); // 同上：逐任务隔离，模拟面板整体重建
      for (const [k, v] of Object.entries(cfg)) {
        const { tag, value } = browserValueOf(params.buildParamInput(k, v, task));
        const node = el(`param_${k}`);
        node.tagName = tag;
        node.value = value;
      }
      payload[task] = params.getParams(task);
    }
    writeFileSync(dumpPath, JSON.stringify(payload, null, 1), 'utf8');
    console.log(`  · 往返载荷已落盘 ${dumpPath}`);
  }
}

// ── 断言 7：非首项默认值必须**显式** `selected`（审查 2026-10-09 C-2）──────
// 缺陷机制：`String(v) === val` 中 `val` 是 JSON 里的**数字**（`Choice((0,…),(1,…))`），
// 跨类型恒假 → `<select>` 里**没有任何 option 带 `selected`** → 浏览器按规范隐式选首项。
// 当前两个数值 `Choice` 的默认值恰好都是首项，故该缺陷**静默潜伏**（注入 I-1 实测：
// 把 `anova.interactions` 默认 0→1 后，面板仍下发 "0"，而 46 passed + node OK 全绿）。
//
// 本断言不依赖具体默认值：对每个有选项的参数，把**末项与第二项**当默认值渲染一遍，
// 断言该项真的带上了 `selected`。首项无需断言（浏览器语义下恒真）。
{
  const notSelected = [];
  let probed = 0;
  for (const [key, opts] of Object.entries(PAYLOAD.param_options || {})) {
    if (!Array.isArray(opts) || opts.length < 2) continue;
    const at = key.lastIndexOf('@');
    const name = key.slice(0, at);
    const task = key.slice(at + 1);
    for (const pick of [opts[1], opts[opts.length - 1]]) {
      const val = pick[0];
      probed += 1;
      const html = params.buildParamInput(name, val, task);
      if (!html.includes('<select')) continue; // 该键在此任务下不是下拉框（列选择器等）
      const chosen = explicitlySelected(html);
      if (chosen !== String(val)) {
        notSelected.push(
          `${key}: 默认值 ${JSON.stringify(val)}(${typeof val}) → ` +
            (chosen === null ? '无任何 option 带 selected（浏览器将隐式选首项）' : `选中的是 ${JSON.stringify(chosen)}`),
        );
      }
    }
  }
  check(probed > 0, '未枚举到任何多选项参数（断言将恒真，扫描器失效）');
  check(
    notSelected.length === 0,
    `下拉框未显式选中声明的默认值（数值型候选会静默下发首项）：\n      ` +
      notSelected.slice(0, 8).join('\n      '),
  );
  console.log(`  · 下拉框默认值显式选中探测 ${probed} 次`);
}

// ── 断言 8：自由文本参数里的哨兵字面量必须**原样下发**（审查 2026-10-09 C-3）──
// P0-1 的兜底把 `'null'`/`'undefined'`/`'NaN'` 当"未填"丢弃，但那是**数据字面量**：
// `proportion_ci.success_value='null'`（用户想算列中文本为 `null` 的占比）被吞掉后
// 引擎落回"首个类别"，实测 16.67% 静默变成 83.33% 且 status=ok / messages=[]。
// 渲染侧已由 `value="${v ?? ''}"` 根治，故这里钉住"用户真填的字面量必须原样发出"。
// 回读结果落盘，供 Python 侧做**端到端**断言（面板载荷 → 引擎 → 16.67%）。
{
  params.hydrateParams({
    params: { proportion_ci: { success_value: 'null' } },
    param_labels: { success_value: '成功取值' },
  });
  elements.clear();
  const html = params.buildParamInput('success_value', 'null', 'proportion_ci');
  const { tag, value } = browserValueOf(html);
  const node = el('param_success_value');
  node.tagName = tag;
  node.value = value;
  const sent = params.getParams('proportion_ci');
  check(value === 'null', `渲染侧应保住 'null' 字面量，实际 ${JSON.stringify(value)}`);
  check(
    sent.success_value === 'null',
    `自由文本参数中的 'null' 必须是数据（不得被当哨兵丢弃），实际 ${JSON.stringify(sent)}`,
  );
  const sentinelPath = process.env.SMARTSUITE_SENTINEL_DUMP;
  if (sentinelPath) {
    writeFileSync(sentinelPath, JSON.stringify(sent), 'utf8');
    console.log(`  · 哨兵字面量回读已落盘 ${sentinelPath}`);
  }
  params.hydrateParams(PAYLOAD); // 还原真实载荷，避免影响后续/后续运行者
}

// ── 输出 ────────────────────────────────────────────────────────
if (problems.length) {
  console.error('FAIL: 参数面板冒烟未通过');
  for (const p of problems) console.error('  - ' + p);
  process.exit(1);
}
console.log('OK: 参数面板冒烟通过（真实加载 params.js + 后端真实载荷 + 8 组断言）');
