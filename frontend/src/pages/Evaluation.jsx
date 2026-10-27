import { Band, Loading, Status, human, useApi, VER_STATUS } from '../ui'

const pct = x => x == null ? '—' : `${(x * 100).toFixed(1)}%`

export default function Evaluation() {
  const r = useApi('/api/evaluation')
  if (!r.data) return <Loading error={r.error} />
  const e = r.data
  const faults = Object.entries(e.fault_detection_by_type).sort((a, b) => b[1].injected - a[1].injected)
  const det = Object.values(e.fault_detection_by_type).reduce((s, v) => s + v.detected, 0)
  const inj = Object.values(e.fault_detection_by_type).reduce((s, v) => s + v.injected, 0)
  const ver = Object.entries(e.verification_status_counts)
  const verTotal = ver.reduce((s, [, n]) => s + n, 0)
  const me = e.manual_effort
  return (
    <>
      <Band>
        <div style={{ width: '100%' }}>
          <h1>Evaluation</h1>
          <p className="lede">{e.applications_evaluated} synthetic applications with {inj} deliberately injected faults, run through the full pipeline by <span className="mono">scripts/evaluate.py</span>. {e.note}</p>
          <div className="figures">
            <div><b>{det}/{inj}</b><span>injected faults detected</span></div>
            <div><b>{pct(e.discrepancy_precision)}</b><span>of high/medium flags were real problems</span></div>
            <div><b>{pct(e.field_extraction_accuracy.ocr_scanned)}</b><span>fields read correctly from scans</span></div>
            <div><b>{me ? `${Math.round(me.estimated_reduction * 100)}%` : '—'}</b><span>less manual effort (estimate)</span></div>
          </div>
        </div>
      </Band>
      <div className="page lift" style={{ maxWidth: 1180 }}>
        <div className="two-col">
          <div className="sheet lift-first">
            <div className="sheet-head"><h3>Detection by fault type</h3><span className="small muted">detected / injected</span></div>
            <div className="sheet-body">
              {faults.map(([k, v]) => (
                <div className="hbar" key={k}>
                  <span>{human(k)}</span>
                  <span className="track"><i style={{ width: `${v.detected / v.injected * 100}%` }} /></span>
                  <span className="num">{v.detected}/{v.injected}</span>
                </div>
              ))}
              <p className="small muted" style={{ marginTop: 10 }}>{e.clean_applications_with_false_alarm} of {e.clean_applications} clean applications received a high or medium flag.</p>
            </div>
          </div>
          <div style={{ display: 'grid', gap: 20 }}>
            {me && <div className="sheet lift-first">
              <div className="sheet-head"><h3>Manual effort</h3><span className="small muted">model with assumed minutes</span></div>
              <div className="sheet-body">
                <div className="hbar"><span>By hand</span><span className="track"><i style={{ width: '100%', background: '#9AA0AB' }} /></span><span className="num">{Math.round(me.minutes_by_hand / 60)} h</span></div>
                <div className="hbar"><span>With Pramaan</span><span className="track"><i style={{ width: `${me.minutes_with_pramaan / me.minutes_by_hand * 100}%` }} /></span><span className="num">{Math.round(me.minutes_with_pramaan / 60)} h</span></div>
                <p className="small muted" style={{ marginTop: 10 }}>Assumed minutes per task: {Object.entries(me.assumed_minutes).map(([k, v]) => `${human(k)} ${v}`).join(' · ')}. Replace with AICTE time-and-motion figures before quoting.</p>
              </div>
            </div>}
            <div className="sheet">
              <div className="sheet-head"><h3>Reading documents</h3><span className="small muted">alert raised {((e.time_to_first_alert_ms || e.avg_validation_ms) / 1000).toFixed(1)} s after submission</span></div>
              <div className="sheet-body">
                <dl className="kv">
                  <dt>Document type recognised</dt><dd>{pct(e.classification_accuracy)}</dd>
                  <dt>Fields, digital PDFs</dt><dd>{pct(e.field_extraction_accuracy.text_layer)}</dd>
                  <dt>Fields, scanned pages</dt><dd>{pct(e.field_extraction_accuracy.ocr_scanned)}</dd>
                  <dt>Fields compared</dt><dd>{e.field_extraction_accuracy.fields_checked.toLocaleString('en-IN')}</dd>
                </dl>
              </div>
            </div>
            <div className="sheet">
              <div className="sheet-head"><h3>Issuing-authority checks</h3><span className="small muted">{pct(e.automated_verification_rate)} resolved automatically</span></div>
              <div className="sheet-body">
                <div style={{ display: 'flex', height: 10, borderRadius: 5, overflow: 'hidden', marginBottom: 12 }}>
                  {ver.map(([k, n]) => <i key={k} title={`${VER_STATUS[k]?.label}: ${n}`} style={{ width: `${n / verTotal * 100}%`, background: `var(--${{ ok: 'ok', danger: 'danger', warn: 'warn', accent: 'accent', info: 'faint' }[VER_STATUS[k]?.tone] || 'faint'})` }} />)}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 16px', fontSize: 13 }}>
                  {ver.map(([k, n]) => <Status key={k} tone={VER_STATUS[k]?.tone}><span style={{ color: 'var(--ink-2)', fontWeight: 400 }}>{VER_STATUS[k]?.label} {n}</span></Status>)}
                </div>
                <p className="small muted" style={{ marginTop: 12 }}>{pct(e.documents_cleared_without_manual_recheck)} of documents needed no manual re-check.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
