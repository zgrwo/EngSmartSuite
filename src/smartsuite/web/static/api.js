// api.js — 与后端交互的薄封装：CSRF token 获取与带 token 的 fetch。
//
// 审查 2026-09-24（P3-3）：从 app.js 抽出。此处集中"怎么发请求"，
// 业务语义（哪些端点、请求体形状）留在调用方。

let csrfToken = '';

/**
 * 获取 CSRF token（带缓存；`force=true` 时强制重取）。
 *
 * 后端把 token 存在 session 里，`/api/csrf-token` 是唯一出口
 * （见 web/app.py 的 `_generate_csrf_token`）。网络错误时留空并返回 `''`，
 * 由调用方按 403 分支处理，不在此处抛异常。
 */
export async function getCsrfToken(force) {
  if (csrfToken && !force) return csrfToken;
  try {
    const r = await fetch('/api/csrf-token');
    const d = await r.json();
    csrfToken = d.token || '';
  } catch (e) {
    /* 网络错误时留空：调用方会拿到 403 并给出中文提示 */
  }
  return csrfToken;
}

/**
 * 带 CSRF token 的 fetch；403 时刷新 token 重试一次。
 *
 * 审查 2026-08-19 M5（Round-2 接线）：会话过期后服务端返回 403，
 * 前端刷新 token 重试一次即可恢复，无需用户手动刷新页面。
 *
 * 注意 `Content-Type` 只对**字符串 body** 设置：`FormData`（文件上传）必须由
 * 浏览器自动生成 multipart boundary，显式设置会破坏上传。
 */
export async function fetchWithCsrf(url, options) {
  const doFetch = async (token) => {
    const headers = { 'X-CSRF-Token': token, ...(options.headers || {}) };
    if (typeof options.body === 'string') headers['Content-Type'] = 'application/json';
    return fetch(url, { ...options, headers });
  };
  let r = await doFetch(await getCsrfToken());
  if (r.status === 403) {
    csrfToken = '';
    const fresh = await getCsrfToken(true);
    if (fresh) r = await doFetch(fresh);
  }
  return r;
}

// 页面加载时预取 token，避免首次请求多一次往返
getCsrfToken();
