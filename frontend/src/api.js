// Thin API client. The token lives in sessionStorage so closing the tab logs out.
const KEY = 'pramaan.session'

export function getSession() {
  try { return JSON.parse(sessionStorage.getItem(KEY)) } catch { return null }
}
export function setSession(s) {
  try { s ? sessionStorage.setItem(KEY, JSON.stringify(s)) : sessionStorage.removeItem(KEY) } catch { /* private mode */ }
}

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status }
}

export async function api(path, { method = 'GET', body, form } = {}) {
  const s = getSession()
  const headers = {}
  if (s?.token) headers.Authorization = `Bearer ${s.token}`
  let payload
  if (form) payload = form
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body) }
  const r = await fetch(path, { method, headers, body: payload })
  if (r.status === 401 && s) { setSession(null); window.location.assign('/') }
  const data = r.headers.get('content-type')?.includes('json') ? await r.json() : await r.text()
  if (!r.ok) {
    const msg = typeof data === 'object' ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : data
    throw new ApiError(r.status, msg || `Request failed (${r.status})`)
  }
  return data
}

// Images are fetched with the token in the query string (img tags can't send headers).
export function fileUrl(docId, kind = 'preview', page = 1) {
  const s = getSession()
  return `/api/documents/${docId}/${kind}?page=${page}&token=${encodeURIComponent(s?.token || '')}`
}
