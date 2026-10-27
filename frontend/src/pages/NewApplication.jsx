import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, X, Building, BookOpen, Layers, Landmark, AlertCircle } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../App'
import { Band, Loading, useApi } from '../ui'

const LEVELS = { UG_ENGINEERING: 'UG engineering', PG_ENGINEERING: 'PG engineering', MCA: 'MCA' }

export default function NewApplication() {
  const { session } = useAuth()
  const cfg = useApi('/api/config')
  const nav = useNavigate()
  const [f, setF] = useState({
    category: 'EOA',
    institution_name: session.user.full_name || '',
    aicte_permanent_id: '',
    academic_year: '2027-28',
    // Infrastructure
    built_up_area_sqm: '',
    classrooms: '',
    labs: '',
    faculty_count: '',
    // CHANGE_OF_NAME
    proposed_institution_name: '',
    trust_society_name: '',
    reason_for_change: '',
    resolution_date: '',
    // NEW_INSTITUTION
    land_area_acres: '',
    survey_number: '',
    district: '',
    state: '',
    // COURSE_CLOSURE
    closure_programme_name: '',
    closure_programme_code: '',
    closure_level: 'UG_ENGINEERING',
    closure_reason: '',
    students_status: '',
    // NEW_PROGRAMME
    new_prog_code: '',
    new_prog_name: '',
    new_prog_level: 'UG_ENGINEERING',
    new_prog_intake: 60,
  })

  const [progs, setProgs] = useState([
    { code: 'BE-CSE', name: 'B.E. Computer Science and Engineering', level: 'UG_ENGINEERING', intake: 60, current_intake: 60, proposed_intake: 120 }
  ])
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)

  if (!cfg.data) return <Loading error={cfg.error} />

  const set = k => e => setF({ ...f, [k]: e.target.value })
  const setP = (i, k) => e => setProgs(progs.map((p, j) => j === i ? { ...p, [k]: ['intake', 'current_intake', 'proposed_intake'].includes(k) ? +e.target.value : e.target.value } : p))
  const num = v => (v === '' || v == null) ? null : +v

  async function create(e) {
    e.preventDefault()
    setErr(null)
    setBusy(true)
    try {
      const payload = {
        ...f,
        built_up_area_sqm: num(f.built_up_area_sqm),
        classrooms: num(f.classrooms),
        labs: num(f.labs),
        faculty_count: num(f.faculty_count),
        land_area_acres: num(f.land_area_acres),
        new_prog_intake: num(f.new_prog_intake),
        aicte_permanent_id: f.category === 'NEW_INSTITUTION' && !f.aicte_permanent_id ? 'NEW-PENDING' : f.aicte_permanent_id,
        programmes: progs,
      }
      const r = await api('/api/applications', { method: 'POST', body: payload })
      nav(`/applications/${r.id}`)
    } catch (ex) {
      setErr(ex.message)
      setBusy(false)
    }
  }

  const isNameChange = f.category === 'CHANGE_OF_NAME'
  const isNewInst = f.category === 'NEW_INSTITUTION'
  const isClosure = f.category === 'COURSE_CLOSURE'
  const isNewProg = f.category === 'NEW_PROGRAMME'
  const isIntakeInc = f.category === 'INTAKE_INCREASE'
  const isEOA = f.category === 'EOA'

  return (
    <form onSubmit={create}>
      <Band>
        <div>
          <p className="kicker">Step 1 of 3 · Application Details</p>
          <h1>New Application</h1>
          <p className="lede">
            Select your regulatory application type. The form fields and subsequent document checklist update dynamically based on your category.
          </p>
        </div>
      </Band>

      <div className="page lift" style={{ maxWidth: 1040 }}>
        <div className="sheet lift-first" style={{ padding: '16px 24px' }}>
          {/* 1. Category Selection */}
          <section className="form-section">
            <header>
              <h3>Application Type</h3>
              <p>Regulatory procedure under AICTE Approval Process Handbook (APH).</p>
            </header>
            <div className="form-fields">
              <label className="field" style={{ gridColumn: '1 / -1' }}>
                <span>Application type <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                <select className="input" style={{ fontSize: '15px', fontWeight: 500 }} value={f.category} onChange={set('category')}>
                  {Object.entries(cfg.data.categories).map(([k, v]) => (
                    <option key={k} value={k}>{v.label}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Academic year <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                <input className="input" required pattern="20\d\d-\d\d" value={f.academic_year} onChange={set('academic_year')} />
                <small>Format: 2027-28</small>
              </label>
            </div>
          </section>

          {/* 2. Category-Specific Fields */}

          {/* CASE A: CHANGE OF NAME */}
          {isNameChange && (
            <>
              <section className="form-section">
                <header>
                  <h3>Existing Registered Institution</h3>
                  <p>Current record in AICTE Institution Master.</p>
                </header>
                <div className="form-fields">
                  <label className="field" style={{ gridColumn: '1 / -1' }}>
                    <span>Current Registered Institution Name <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" required value={f.institution_name} onChange={set('institution_name')} />
                  </label>
                  <label className="field">
                    <span>AICTE Permanent ID <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input mono" required placeholder="1-1234567890" value={f.aicte_permanent_id} onChange={set('aicte_permanent_id')} />
                  </label>
                  <label className="field">
                    <span>Sponsoring Society / Trust Name <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" required placeholder="e.g. Coromandel Educational Trust" value={f.trust_society_name} onChange={set('trust_society_name')} />
                  </label>
                </div>
              </section>

              <section className="form-section">
                <header>
                  <h3>Proposed New Name</h3>
                  <p>As approved in the Governing Body / Trust Resolution.</p>
                </header>
                <div className="form-fields">
                  <label className="field" style={{ gridColumn: '1 / -1' }}>
                    <span>Proposed New Institution Name <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" required placeholder="e.g. Coromandel Institute of Technology & Advanced Research" value={f.proposed_institution_name} onChange={set('proposed_institution_name')} />
                  </label>
                  <label className="field" style={{ gridColumn: '1 / -1' }}>
                    <span>Reason & Justification for Name Change <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <textarea className="input" rows={3} required placeholder="State the reason (e.g. Renaming in honour of founder, addition of multidisciplinary disciplines, trust resolution...)" value={f.reason_for_change} onChange={set('reason_for_change')} />
                  </label>
                  <label className="field">
                    <span>Resolution Date <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" placeholder="DD-MM-YYYY" value={f.resolution_date} onChange={set('resolution_date')} />
                  </label>
                </div>
              </section>
            </>
          )}

          {/* CASE B: NEW INSTITUTION */}
          {isNewInst && (
            <>
              <section className="form-section">
                <header>
                  <h3>Proposed Institution & Society</h3>
                  <p>Applicant society / trust details.</p>
                </header>
                <div className="form-fields">
                  <label className="field" style={{ gridColumn: '1 / -1' }}>
                    <span>Proposed Institution Name <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" required placeholder="Name of the new technical institute" value={f.institution_name} onChange={set('institution_name')} />
                  </label>
                  <label className="field">
                    <span>Sponsoring Society / Trust Name <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" required placeholder="Registered trust or society" value={f.trust_society_name} onChange={set('trust_society_name')} />
                  </label>
                  <label className="field">
                    <span>AICTE Permanent ID</span>
                    <input className="input mono" placeholder="Not applicable (AICTE will assign)" value={f.aicte_permanent_id} onChange={set('aicte_permanent_id')} />
                    <small>Leave blank if applying for initial establishment</small>
                  </label>
                </div>
              </section>

              <section className="form-section">
                <header>
                  <h3>Land & Location</h3>
                  <p>Must match the registered Land Deed and Town Planning NOC.</p>
                </header>
                <div className="form-fields">
                  <label className="field">
                    <span>Total Land Area (in Acres) <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" type="number" step="0.01" required placeholder="e.g. 5.5" value={f.land_area_acres} onChange={set('land_area_acres')} />
                  </label>
                  <label className="field">
                    <span>Survey / Khasra / Gat No. <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" required placeholder="e.g. Survey No. 104/2" value={f.survey_number} onChange={set('survey_number')} />
                  </label>
                  <label className="field">
                    <span>District / City <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" required value={f.district} onChange={set('district')} />
                  </label>
                  <label className="field">
                    <span>State <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" required value={f.state} onChange={set('state')} />
                  </label>
                </div>
              </section>

              <section className="form-section">
                <header>
                  <h3>Infrastructure & Initial Programmes</h3>
                  <p>Planned facilities for the inaugural academic session.</p>
                </header>
                <div className="form-fields">
                  <label className="field">
                    <span>Built-up area (sqm) <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" type="number" required value={f.built_up_area_sqm} onChange={set('built_up_area_sqm')} />
                  </label>
                  <label className="field"><span>Classrooms <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span><input className="input" type="number" required value={f.classrooms} onChange={set('classrooms')} /></label>
                  <label className="field"><span>Laboratories <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span><input className="input" type="number" required value={f.labs} onChange={set('labs')} /></label>
                  <label className="field"><span>Full-time faculty <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span><input className="input" type="number" required value={f.faculty_count} onChange={set('faculty_count')} /></label>
                </div>
              </section>
            </>
          )}

          {/* CASE C: COURSE CLOSURE */}
          {isClosure && (
            <>
              <section className="form-section">
                <header>
                  <h3>Institution</h3>
                  <p>Must match the AICTE institution master.</p>
                </header>
                <div className="form-fields">
                  <label className="field" style={{ gridColumn: '1 / -1' }}>
                    <span>Institution name <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" required value={f.institution_name} onChange={set('institution_name')} />
                  </label>
                  <label className="field">
                    <span>AICTE Permanent ID <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input mono" required placeholder="1-1234567890" value={f.aicte_permanent_id} onChange={set('aicte_permanent_id')} />
                  </label>
                </div>
              </section>

              <section className="form-section">
                <header>
                  <h3>Programme to be Closed</h3>
                  <p>Details of the course undergoing progressive or complete closure.</p>
                </header>
                <div className="form-fields">
                  <label className="field">
                    <span>Programme Code <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input mono" required placeholder="e.g. BE-CIVIL" value={f.closure_programme_code} onChange={set('closure_programme_code')} />
                  </label>
                  <label className="field">
                    <span>Programme Name <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" required placeholder="e.g. B.E. Civil Engineering" value={f.closure_programme_name} onChange={set('closure_programme_name')} />
                  </label>
                  <label className="field">
                    <span>Level <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <select className="input" value={f.closure_level} onChange={set('closure_level')}>
                      {Object.entries(LEVELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                  </label>
                  <label className="field" style={{ gridColumn: '1 / -1' }}>
                    <span>Reason for Course Closure <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <textarea className="input" rows={2} required placeholder="e.g. Zero admission in preceding 3 academic sessions and shift towards emerging technologies..." value={f.closure_reason} onChange={set('closure_reason')} />
                  </label>
                  <label className="field" style={{ gridColumn: '1 / -1' }}>
                    <span>Status of Enrolled Students <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <textarea className="input" rows={2} required placeholder="e.g. All enrolled students have completed examinations / graduated; no backlog students pending..." value={f.students_status} onChange={set('students_status')} />
                  </label>
                </div>
              </section>
            </>
          )}

          {/* CASE D: NEW PROGRAMME */}
          {isNewProg && (
            <>
              <section className="form-section">
                <header>
                  <h3>Institution</h3>
                  <p>Must match the AICTE institution master.</p>
                </header>
                <div className="form-fields">
                  <label className="field" style={{ gridColumn: '1 / -1' }}>
                    <span>Institution name <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" required value={f.institution_name} onChange={set('institution_name')} />
                  </label>
                  <label className="field">
                    <span>AICTE Permanent ID <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input mono" required placeholder="1-1234567890" value={f.aicte_permanent_id} onChange={set('aicte_permanent_id')} />
                  </label>
                </div>
              </section>

              <section className="form-section">
                <header>
                  <h3>Proposed New Programme</h3>
                  <p>New academic offering to be added under APH norms.</p>
                </header>
                <div className="form-fields">
                  <label className="field">
                    <span>Programme Code <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input mono" required placeholder="e.g. BTECH-AIDS" value={f.new_prog_code} onChange={set('new_prog_code')} />
                  </label>
                  <label className="field">
                    <span>Programme Name <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" required placeholder="e.g. B.Tech Artificial Intelligence and Data Science" value={f.new_prog_name} onChange={set('new_prog_name')} />
                  </label>
                  <label className="field">
                    <span>Level <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <select className="input" value={f.new_prog_level} onChange={set('new_prog_level')}>
                      {Object.entries(LEVELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                  </label>
                  <label className="field">
                    <span>Proposed Annual Intake <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" type="number" min="30" step="30" required value={f.new_prog_intake} onChange={set('new_prog_intake')} />
                  </label>
                </div>
              </section>

              <section className="form-section">
                <header>
                  <h3>Campus Infrastructure & Capacity</h3>
                  <p>Total campus infrastructure including new programme facilities.</p>
                </header>
                <div className="form-fields">
                  <label className="field"><span>Built-up area (sqm)</span><input className="input" type="number" value={f.built_up_area_sqm} onChange={set('built_up_area_sqm')} /></label>
                  <label className="field"><span>Classrooms</span><input className="input" type="number" value={f.classrooms} onChange={set('classrooms')} /></label>
                  <label className="field"><span>Laboratories</span><input className="input" type="number" value={f.labs} onChange={set('labs')} /></label>
                  <label className="field"><span>Full-time faculty</span><input className="input" type="number" value={f.faculty_count} onChange={set('faculty_count')} /></label>
                </div>
              </section>
            </>
          )}

          {/* CASE E: EOA & INTAKE_INCREASE (Standard/Regular applications) */}
          {(isEOA || isIntakeInc) && (
            <>
              <section className="form-section">
                <header>
                  <h3>Institution</h3>
                  <p>Must match the AICTE institution master.</p>
                </header>
                <div className="form-fields">
                  <label className="field" style={{ gridColumn: '1 / -1' }}>
                    <span>Institution name <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" required value={f.institution_name} onChange={set('institution_name')} />
                  </label>
                  <label className="field">
                    <span>AICTE Permanent ID <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input mono" required placeholder="1-1234567890" value={f.aicte_permanent_id} onChange={set('aicte_permanent_id')} />
                  </label>
                </div>
              </section>

              <section className="form-section">
                <header>
                  <h3>Infrastructure and faculty</h3>
                  <p>{isIntakeInc ? 'Checked against norms for the increased intake requested.' : 'Checked against norms for existing approved intake.'}</p>
                </header>
                <div className="form-fields">
                  <label className="field">
                    <span>Built-up area (sqm) <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span>
                    <input className="input" type="number" required value={f.built_up_area_sqm} onChange={set('built_up_area_sqm')} />
                    <small>Square metres, as on completion certificate</small>
                  </label>
                  <label className="field"><span>Classrooms <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span><input className="input" type="number" required value={f.classrooms} onChange={set('classrooms')} /></label>
                  <label className="field"><span>Laboratories <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span><input className="input" type="number" required value={f.labs} onChange={set('labs')} /></label>
                  <label className="field"><span>Full-time faculty <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></span><input className="input" type="number" required value={f.faculty_count} onChange={set('faculty_count')} /></label>
                </div>
              </section>

              <section className="form-section">
                <header>
                  <h3>Programmes</h3>
                  <p>{isIntakeInc ? 'Indicate current intake and the proposed revised intake.' : 'The annual intake for each approved programme.'}</p>
                </header>
                <div>
                  <table className="table prog-table">
                    <thead>
                      <tr>
                        <th style={{ width: '16%' }}>Code <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></th>
                        <th>Name <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></th>
                        <th style={{ width: '18%' }}>Level</th>
                        {isIntakeInc ? (
                          <>
                            <th style={{ width: '12%' }}>Current</th>
                            <th style={{ width: '12%' }}>Proposed <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></th>
                          </>
                        ) : (
                          <th style={{ width: '14%' }}>Intake <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></th>
                        )}
                        <th style={{ width: '4%' }} />
                      </tr>
                    </thead>
                    <tbody>
                      {progs.map((p, i) => (
                        <tr key={i}>
                          <td><input className="input mono" aria-label="Programme code" value={p.code} onChange={setP(i, 'code')} required /></td>
                          <td><input className="input" aria-label="Programme name" value={p.name} onChange={setP(i, 'name')} required /></td>
                          <td>
                            <select className="input" aria-label="Level" value={p.level} onChange={setP(i, 'level')}>
                              {Object.entries(LEVELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                            </select>
                          </td>
                          {isIntakeInc ? (
                            <>
                              <td><input className="input" aria-label="Current Intake" type="number" min="0" value={p.current_intake ?? p.intake} onChange={setP(i, 'current_intake')} /></td>
                              <td><input className="input" aria-label="Proposed Intake" type="number" min="0" value={p.proposed_intake ?? (p.intake * 2)} onChange={setP(i, 'proposed_intake')} required /></td>
                            </>
                          ) : (
                            <td><input className="input" aria-label="Intake" type="number" min="0" value={p.intake} onChange={setP(i, 'intake')} required /></td>
                          )}
                          <td>
                            <button type="button" className="icon-btn" aria-label="Remove programme" onClick={() => setProgs(progs.filter((_, j) => j !== i))} disabled={progs.length === 1}>
                              <X size={15} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <button
                    type="button"
                    className="btn quiet sm"
                    style={{ marginTop: 8 }}
                    onClick={() => setProgs([...progs, { code: '', name: '', level: 'UG_ENGINEERING', intake: 60, current_intake: 60, proposed_intake: 120 }])}
                  >
                    <Plus size={14} /> Add programme
                  </button>
                </div>
              </section>
            </>
          )}

          {/* Programmes for NEW_INSTITUTION */}
          {isNewInst && (
            <section className="form-section">
              <header>
                <h3>Initial Programmes Offered</h3>
                <p>New programmes to be commenced from first academic session.</p>
              </header>
              <div>
                <table className="table prog-table">
                  <thead>
                    <tr>
                      <th style={{ width: '18%' }}>Code <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></th>
                      <th>Name <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></th>
                      <th style={{ width: '22%' }}>Level</th>
                      <th style={{ width: '14%' }}>Intake <span style={{ color: '#DC2626', fontWeight: 800 }}>*</span></th>
                      <th style={{ width: '4%' }} />
                    </tr>
                  </thead>
                  <tbody>
                    {progs.map((p, i) => (
                      <tr key={i}>
                        <td><input className="input mono" aria-label="Programme code" value={p.code} onChange={setP(i, 'code')} required /></td>
                        <td><input className="input" aria-label="Programme name" value={p.name} onChange={setP(i, 'name')} required /></td>
                        <td>
                          <select className="input" aria-label="Level" value={p.level} onChange={setP(i, 'level')}>
                            {Object.entries(LEVELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                          </select>
                        </td>
                        <td><input className="input" aria-label="Intake" type="number" min="0" value={p.intake} onChange={setP(i, 'intake')} required /></td>
                        <td>
                          <button type="button" className="icon-btn" aria-label="Remove programme" onClick={() => setProgs(progs.filter((_, j) => j !== i))} disabled={progs.length === 1}>
                            <X size={15} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <button
                  type="button"
                  className="btn quiet sm"
                  style={{ marginTop: 8 }}
                  onClick={() => setProgs([...progs, { code: '', name: '', level: 'UG_ENGINEERING', intake: 60 }])}
                >
                  <Plus size={14} /> Add programme
                </button>
              </div>
            </section>
          )}
        </div>

        {err && <p className="error" style={{ marginTop: 12 }}>{err}</p>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 18 }}>
          <button type="button" className="btn" onClick={() => nav('/')}>Cancel</button>
          <button className="btn primary" disabled={busy}>
            {busy ? 'Creating…' : 'Continue to documents →'}
          </button>
        </div>
      </div>
    </form>
  )
}
