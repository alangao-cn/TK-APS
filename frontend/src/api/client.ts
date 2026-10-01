// API 客户端：同源 Cookie 鉴权；401 统一跳登录（HashRouter）
export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const opts: RequestInit = { credentials: 'same-origin', ...options }
  if (options.body && !(options.body instanceof FormData)) {
    opts.headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  }
  const resp = await fetch(path, opts)
  if (resp.status === 401) {
    if (!location.hash.startsWith('#/login')) location.hash = '#/login'
    throw new Error('未登录')
  }
  if (!resp.ok) {
    let detail = `${resp.status}`
    try {
      const data = await resp.json()
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data)
    } catch { /* ignore */ }
    throw new Error(detail)
  }
  const ct = resp.headers.get('content-type') || ''
  return (ct.includes('json') ? resp.json() : resp.blob()) as Promise<T>
}

export const post = (path: string, body?: any) =>
  api(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
export const put = (path: string, body: any) =>
  api(path, { method: 'PUT', body: JSON.stringify(body) })
export const patch = (path: string, body: any) =>
  api(path, { method: 'PATCH', body: JSON.stringify(body) })

export async function login(username: string, password: string) {
  const body = new URLSearchParams({ username, password })
  const resp = await fetch('/api/auth/login', {
    method: 'POST', body, credentials: 'same-origin',
  })
  if (!resp.ok) throw new Error('账号或密码错误')
  return resp.json()
}

// 下载类（blob 触发浏览器保存）
export async function downloadBlob(path: string, body: any, filename: string) {
  const resp = await fetch(path, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) throw new Error('下载失败')
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
