import { useEffect, useState } from 'react'
import { Link2, Link2Off, ShieldCheck, RefreshCw } from 'lucide-react'
import { api } from '../api'
import { Band, Loading } from '../ui'
import { Timeline } from './case/Tabs'

export default function Audit() {
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [chain, setChain] = useState(null)
  const [busy, setBusy] = useState(false)
  const [lastUpdated, setLastUpdated] = useState(new Date())

  async function fetchAudit(silent = false) {
    try {
      if (!silent) setLoading(true)
      const data = await api('/api/audit?limit=400')
      setEntries(data)
      setLastUpdated(new Date())
      setError(null)
    } catch (err) {
      if (!silent) setError(err.message)
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => {
    fetchAudit()
    const timer = setInterval(() => {
      fetchAudit(true)
    }, 2500)
    return () => clearInterval(timer)
  }, [])

  async function verify() {
    setBusy(true)
    try {
      setChain(await api('/api/audit/verify'))
    } finally {
      setBusy(false)
    }
  }

  if (loading && entries.length === 0) return <Loading error={error} />

  return (
    <>
      <Band>
        <div style={{ flex: '1 1 460px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 4 }}>
            <h1 style={{ margin: 0 }}>Audit Trail</h1>
            <span style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '2px 9px',
              borderRadius: 999,
              fontSize: 12,
              fontWeight: 600,
              background: '#ECFDF5',
              color: '#065F46',
              border: '1px solid #A7F3D0'
            }}>
              <span style={{
                width: 7,
                height: 7,
                borderRadius: '50%',
                background: '#10B981',
                boxShadow: '0 0 0 2px rgba(16, 185, 129, 0.3)'
              }} />
              Live Feed Active
            </span>
          </div>
          <p className="lede">
            Live, tamper-evident cryptographic log of all sign-ins, uploads, freeze actions, reviews, authority checks, and PII unmasking.
            Each entry carries the SHA-256 hash of the previous one, forming an unbroken verifiable chain.
          </p>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
            Auto-syncing every 2.5s · {entries.length} {entries.length === 1 ? 'event' : 'events'} recorded
          </div>
        </div>
        <div className="next-card" style={{ width: 340, gridTemplateColumns: '1fr' }}>
          <span className="kick"><ShieldCheck size={13} style={{ verticalAlign: -2 }} /> Tamper evidence</span>
          {chain ? (chain.intact
            ? <><h3><Link2 size={15} style={{ verticalAlign: -2 }} /> Chain intact</h3><p>{chain.entries} entries verified · head <span className="mono">{chain.head?.slice(0, 16)}…</span></p></>
            : <><h3 style={{ color: '#B02A16' }}><Link2Off size={15} style={{ verticalAlign: -2 }} /> Broken at entry {chain.broken_at_id}</h3><p>An entry was changed or removed after it was written.</p></>)
            : <><h3>Cryptographic Verification</h3><p>Recomputes every SHA-256 hash from genesis to the latest event in the log.</p></>}
          <span style={{ display: 'flex', gap: 8 }}>
            <button className="btn primary sm" onClick={verify} disabled={busy}>
              {busy ? 'Verifying…' : 'Verify chain'}
            </button>
            <button className="btn quiet sm" onClick={() => fetchAudit(false)} title="Force reload">
              <RefreshCw size={13} />
            </button>
          </span>
        </div>
      </Band>
      <div className="page lift" style={{ maxWidth: 980 }}>
        <div className="sheet lift-first">
          <div className="sheet-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
            <Timeline entries={entries} />
          </div>
        </div>
      </div>
    </>
  )
}
