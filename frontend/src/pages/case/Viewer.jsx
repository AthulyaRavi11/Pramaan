import { useEffect, useMemo, useState } from 'react'
import { ExternalLink, FileText, Maximize2, Minimize2, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { api, fileUrl } from '../../api'

/* Which printed values an issue is about, so they can be highlighted on the page. */
export function valuesFor(f, doc) {
  const ev = f.evidence || {}
  const fields = doc?.extraction?.fields || {}
  const out = []
  if (ev.value) out.push(ev.value)
  if (ev.found_value) out.push(ev.found_value)
  ;(ev.comparison || []).filter(c => !c.match && c.document).forEach(c => out.push(String(c.document)))
  if (!out.length && f.module === 'verification') {
    const ref = fields.certificate_no || fields.transaction_id
    if (ref) out.push(ref.value)
  }
  if (!out.length && f.rule_id === 'ANOM-DATE') {
    ;['issue_date', 'valid_until'].forEach(k => fields[k] && out.push(fields[k].value))
  }
  if (!out.length && f.rule_id === 'DOC-LOWCONF') {
    ;(ev.fields || []).forEach(k => fields[k] && out.push(fields[k].value))
  }
  return [...new Set(out.filter(Boolean))]
}

/* A document page with every issue on it marked like a reviewer's highlighter. */
export default function Viewer({ doc, docLabel, issues = [], selectedId, onSelect, note, sidebarOpen = true, onToggleSidebar, openCount }) {
  const [actual, setActual] = useState(false)
  const [page, setPage] = useState(1)
  const [loaded, setLoaded] = useState(false)
  const [boxes, setBoxes] = useState({})
  const pages = doc?.extraction?.page_count || 1
  const isPhoto = doc?.declared_type === 'infra_photo'

  const wanted = useMemo(() => [...new Set(issues.flatMap(i => i.values || []))], [issues])
  const key = `${doc?.id}|${wanted.join('|')}`

  useEffect(() => { setLoaded(false); setPage(1) }, [doc?.id])
  useEffect(() => {
    if (!doc || isPhoto || !wanted.length) { setBoxes({}); return }
    let live = true
    const qs = wanted.map(v => `q=${encodeURIComponent(v)}`).join('&')
    api(`/api/documents/${doc.id}/locate?${qs}`).then(r => live && setBoxes(r)).catch(() => {})
    return () => { live = false }
  }, [key]) // eslint-disable-line

  if (!doc) return null
  // One highlight per printed value; one margin pin per line listing every issue that points at it.
  const byBox = new Map()
  for (const i of issues) for (const v of i.values || []) for (const b of (boxes[v] || []).filter(b => b.page === page)) {
    const k = b.box.map(x => x.toFixed(3)).join(',')
    const m = byBox.get(k) || { box: b.box, issues: [] }
    if (!m.issues.includes(i)) m.issues.push(i)
    byBox.set(k, m)
  }
  const marks = [...byBox.values()]
  const pins = new Map()
  for (const m of marks) {
    const row = Math.round(((m.box[1] + m.box[3]) / 2) * 200)
    const p = pins.get(row) || { y: (m.box[1] + m.box[3]) / 2, issues: [] }
    m.issues.forEach(i => !p.issues.includes(i) && p.issues.push(i))
    pins.set(row, p)
  }

  return (
    <>
      <div className="viewer-bar">
        {onToggleSidebar && (
          <button
            type="button"
            className="btn-sidebar-toggle"
            onClick={onToggleSidebar}
            title={sidebarOpen ? 'Hide sidebar (PDF occupies full space)' : 'Show issues sidebar'}
            style={{ marginRight: 2 }}
          >
            {sidebarOpen ? <PanelLeftClose size={14} /> : <PanelLeftOpen size={14} />}
            {!sidebarOpen && typeof openCount === 'number' && (
              <span>{openCount} to review</span>
            )}
          </button>
        )}
        <FileText size={15} className="faint" />
        <span className="name">{docLabel}</span>
        <span className="muted">{doc.original_name}{doc.ocr_used ? ' · scanned' : ''}</span>
        <span className="spacer" />
        {pages > 1 && <span className="seg">{Array.from({ length: Math.min(pages, 3) }, (_, i) => (
          <button key={i} className={page === i + 1 ? 'on' : ''} onClick={() => setPage(i + 1)}>p{i + 1}</button>))}</span>}
        <button className="btn quiet sm" onClick={() => setActual(a => !a)} title={actual ? 'Fit to pane' : 'Actual size'}>
          {actual ? <Minimize2 size={14} /> : <Maximize2 size={14} />}{actual ? 'Fit' : 'Zoom'}
        </button>
        <a className="btn quiet sm" href={fileUrl(doc.id, 'file')} target="_blank" rel="noreferrer"><ExternalLink size={14} />Original</a>
      </div>
      <div className="viewer-stage">
        <div className={`paper ${actual ? 'actual' : ''}`}>
          {!loaded && <div className="paper-loading">Rendering page…</div>}
          <img src={fileUrl(doc.id, 'preview', page)} alt={`${docLabel}, page ${page}`} onLoad={() => setLoaded(true)}
               style={loaded ? null : { position: 'absolute', opacity: 0 }} />
          {loaded && marks.map((m, k) => {
            const [x0, y0, x1, y1] = m.box
            const on = m.issues.some(i => i.id === selectedId)
            return <span key={k} className={`mark ${on ? 'on' : ''}`} onClick={() => onSelect?.((m.issues.find(i => i.id !== selectedId) || m.issues[0]).id)}
                         title={m.issues.map(i => `${i.n}. ${i.title}`).join('\n')}
                         style={{ left: `${x0 * 100 - 0.4}%`, top: `${y0 * 100 - 0.3}%`, width: `${(x1 - x0) * 100 + 0.8}%`, height: `${(y1 - y0) * 100 + 0.6}%` }} />
          })}
          {loaded && [...pins.values()].map((p, k) => (
            <span key={k} className="margin-pins" style={{ top: `${p.y * 100}%` }}>
              {p.issues.map(i => <button key={i.id} className={`pin ${i.id === selectedId ? 'on' : ''}`} onClick={() => onSelect?.(i.id)} title={i.title}>{i.n}</button>)}
            </span>
          ))}
          {loaded && note && <div className="viewer-note">{note}</div>}
        </div>
      </div>
    </>
  )
}

export function PhotoPair({ a, b, caption }) {
  return (
    <div className="viewer-stage">
      <div style={{ width: '100%', maxWidth: 1000 }}>
        <div className="photo-pair">
          <figure><img src={fileUrl(a.id)} alt={a.tag} /><figcaption><b>{a.tag}</b><span className="muted">{a.name}</span></figcaption></figure>
          <figure><img src={fileUrl(b.id)} alt={b.tag} /><figcaption><b>{b.tag}</b><span className="muted">{b.name}</span></figcaption></figure>
        </div>
        {caption && <p className="small muted" style={{ marginTop: 12, textAlign: 'center' }}>{caption}</p>}
      </div>
    </div>
  )
}
