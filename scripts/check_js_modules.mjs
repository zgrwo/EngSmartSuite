#!/usr/bin/env node
// 前端模块解析校验：每个 import 的具名符号必须被对应模块 export；无循环依赖。
//
// 审查 2026-09-24（P3-3）：本项重构把 933 行单文件拆为 5 个 ES module。
// **无浏览器测试**，而"import 了不存在的导出名"是此类重构最典型的静默失败 ——
// 浏览器会在加载时报 `SyntaxError: The requested module does not provide an
// export named 'X'`，整个应用白屏。
//
// 本脚本是**静态解析**（不执行模块，故不需要 DOM/fetch）：
//   ① 提取每个文件的 `export const|let|function|class NAME` 与
//      `import { A, B as C } from './x.js'`；
//   ② 校验每个具名 import 都能在目标文件中找到 export；
//   ③ 校验 import 的相对路径真实存在；
//   ④ 用 DFS 检测循环依赖。
//
// 用法：node scripts/check_js_modules.mjs
// 退出码：0 = 通过；1 = 发现问题（逐条打印）

import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const STATIC_DIR = resolve(HERE, '..', 'src', 'smartsuite', 'web', 'static');

/** 去掉行注释与块注释（正则扫代码前必须先剥注释，否则注释里的字样会误报）。 */
function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
}

/** 提取一个模块的导出名集合。 */
function exportsOf(src) {
  const code = stripComments(src);
  const names = new Set();
  const re =
    /^[ \t]*export\s+(?:async\s+)?(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)/gm;
  for (const m of code.matchAll(re)) names.add(m[1]);
  // export { a, b as c }
  for (const m of code.matchAll(/^[ \t]*export\s*\{([^}]*)\}/gm)) {
    for (const part of m[1].split(',')) {
      const bits = part.trim().split(/\s+as\s+/);
      const local = bits[bits.length - 1].trim();
      if (local) names.add(local);
    }
  }
  // export default
  if (/^[ \t]*export\s+default\b/m.test(code)) names.add('default');
  return names;
}

/** 提取一个模块的 import：{ source, names: [{imported, local}] } */
function importsOf(src) {
  const code = stripComments(src);
  const out = [];
  const re = /^[ \t]*import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"]/gm;
  for (const m of code.matchAll(re)) {
    const clause = m[1].trim();
    const source = m[2];
    const names = [];
    const braced = clause.match(/\{([\s\S]*)\}/);
    if (braced) {
      for (const part of braced[1].split(',')) {
        const p = part.trim();
        if (!p) continue;
        const bits = p.split(/\s+as\s+/);
        names.push({ imported: bits[0].trim(), local: (bits[1] || bits[0]).trim() });
      }
    }
    out.push({ source, names, bare: !braced && !clause.startsWith('*') });
  }
  return out;
}

const files = readdirSync(STATIC_DIR)
  .filter((f) => f.endsWith('.js'))
  .sort();

const problems = [];
const graph = new Map();

for (const file of files) {
  const full = join(STATIC_DIR, file);
  const src = readFileSync(full, 'utf8');
  const deps = [];
  for (const imp of importsOf(src)) {
    if (!imp.source.startsWith('.')) continue; // 只查相对导入
    const target = resolve(dirname(full), imp.source);
    let targetSrc;
    try {
      targetSrc = readFileSync(target, 'utf8');
    } catch {
      problems.push(`${file}: 导入路径不存在 → ${imp.source}`);
      continue;
    }
    deps.push(relative(STATIC_DIR, target).replace(/\\/g, '/'));
    const available = exportsOf(targetSrc);
    const targetName = relative(STATIC_DIR, target).replace(/\\/g, '/');
    for (const { imported } of imp.names) {
      if (!available.has(imported)) {
        problems.push(
          `${file}: 从 ${targetName} 导入了不存在的具名导出 '${imported}'` +
            `（该模块的导出：${[...available].sort().join(', ')}）`
        );
      }
    }
  }
  graph.set(file, deps);
}

// 循环依赖检测（DFS）
const WHITE = 0;
const GRAY = 1;
const BLACK = 2;
const color = new Map(files.map((f) => [f, WHITE]));
const stack = [];

function dfs(node) {
  color.set(node, GRAY);
  stack.push(node);
  for (const dep of graph.get(node) || []) {
    const c = color.get(dep);
    if (c === GRAY) {
      problems.push(`循环依赖: ${[...stack, dep].join(' → ')}`);
    } else if (c === WHITE) {
      dfs(dep);
    }
  }
  stack.pop();
  color.set(node, BLACK);
}

for (const f of files) if (color.get(f) === WHITE) dfs(f);

if (problems.length) {
  console.error(`FAIL: 前端模块解析发现 ${problems.length} 个问题`);
  for (const p of problems) console.error('  - ' + p);
  process.exit(1);
}
console.log(`OK: ${files.length} 个前端模块的导入/导出与依赖图均一致（无缺失导出、无循环依赖）`);
