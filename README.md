# Pramaan — AI-assisted validation for AICTE approval applications

Smart India Hackathon 2026 · Problem statement **SIH26261** (AICTE, Regulation Bureau) ·
*AI-Powered Application Validation, Document Authentication and Regulatory Compliance Verification*

Pramaan reads an institution's approval application and its supporting documents, checks them against
AICTE institutional records, configurable Approval Process Handbook rules and the issuing authorities, and
gives scrutiny officers a ranked list of findings, **each with the evidence behind it**. It is decision
support only: every adverse outcome needs an official's review, and the final decision stays with the
competent authority.

> All institutions, authorities, certificates and records in this repository are **synthetic**.
> Rule thresholds and infrastructure norms are **illustrative placeholders**, not values from the APH.

---

## Run it

**Needs:** Python 3.11+ and [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki).
Node 18+ is only needed if you change the frontend (a built copy is in `frontend/dist`).

| | |
|---|---|
| Windows | install Tesseract to the default folder, then double-click `run.bat` |
| macOS / Linux | `brew install tesseract` or `sudo apt install tesseract-ocr`, then `./run.sh` |

Open <http://localhost:8000>. The first run installs Python packages into `backend/.venv`.
The database ships pre-loaded with three demo applications. If Tesseract is somewhere unusual, set
`TESSERACT_CMD` to the full path of `tesseract.exe`.

**Demo accounts** (password `demo1234` for all; click a user on the login page, then type the CAPTCHA shown):

| User | Role | What you'll see |
|---|---|---|
| `officer` | Scrutiny officer | All applications, evidence, review and recommendation |
| `admin` | Administrator | Rules and sources, audit trail, evaluation metrics |
| `coromandel` | Institution | A clean application |
| `sahyadri` | Institution | Expired NOC, old affidavit, wrong file in a slot, intake above approval, unpaid fee… |
| `gangavalley` | Institution | Altered fire NOC, NBA certificate copied from another institution, re-used lab photo, fake fee receipt |

### Developing

```bash
# backend (terminal 1)
cd backend && pip install -r requirements.txt
PRAMAAN_TODAY=2026-10-21 uvicorn app.main:app --reload --port 8000     # API docs at /docs

# frontend with hot reload (terminal 2) — proxies /api to :8000
cd frontend && npm install && npm run dev                                # http://localhost:5173
npm run build                                                            # refresh frontend/dist

# data, tests, evaluation
cd backend
python scripts/generate_synthetic.py --batch 40   # new synthetic data: 3 demo + 40 evaluation apps
python scripts/make_test_certificates.py          # sample PDFs for the newer categories -> synthetic_test_certificates/
python scripts/seed.py --with-eval                # reset DB and load everything through the real API (~25 min, OCR)
python scripts/evaluate.py                        # metrics -> storage/evaluation.json (shown on the Evaluation page)
python -m pytest -q                               # 18 end-to-end tests, ~2 min
```

---

## Five-minute demo script

1. **Sign in as `officer`** (one click on the login page). The worklist groups applications by what needs attention. Each one has a five-cell *check strip*: Checklist · AICTE records · Authenticity · Issuing authority · Infrastructure.
2. **Open Ganga Valley.** The review desk has three panes: issues grouped by document, the document itself, and the evidence with your decision. Every issue is **highlighted on the page** and numbered in the margin.
3. **"Different font in 'valid until'"**: the expiry date is boxed on the fire NOC. It is set in Times-Roman while every other value uses Helvetica.
4. **"Printed details differ from the authority's signed QR code"**: the QR's Ed25519 signature is genuine, so its date (2026) can be trusted over the printed one (2028).
5. **"Same photo submitted for different rooms"**: the "ECE lab" is the "CSE lab" photo, cropped and re-coloured, shown side by side.
6. **"AICTE Permanent ID differs from the application"**: the affidavit is a scan, and OCR found the exact spot where two digits are swapped.
7. **University Affiliation Letter → "Digital signature check failed"**: the letter was digitally signed by the university, then its academic year was edited. The signature panel shows it now covers only the earlier version, and the repository copy's fingerprint differs.
8. **Report (PDF)** in the header downloads the structured validation report an official can file.
9. **Review from the keyboard:** press <kbd>R</kbd> (ask to rectify), type a remark and press <kbd>Ctrl</kbd>+<kbd>Enter</kbd>. The desk moves to the next open issue, and <kbd>J</kbd>/<kbd>K</kbd> move between issues. Then click **Record recommendation**: approval is blocked until every high-severity issue is reviewed.
10. **History tab / Audit trail**: every step is logged. **Verify chain** proves nothing was edited afterwards.
11. **Sign in as `sahyadri`**: the institution sees a plain-language "things to fix" list and the officer's rectification request, and uploads with drag and drop. Forensic flags stay hidden from the institution.
12. **Sign in as `admin`**: **Rules** (every check comes from YAML, plus the data-retention purge), **Alerts → Email notifications** and **Evaluation**.

Screenshots of these screens are in `docs/screenshots/`.

**Recording an upload:** `demo_uploads/` has a ready set of files and photos for every application type
(sign in as `coromandel`), plus one set with deliberate mistakes. Its `README.md` says what to type, which file goes
in which slot, and what Pramaan reports. Every set was uploaded and checked.

**Room photos:** the demo colleges' infrastructure photos and the four sample room photos are realistic photos
supplied by the team (`backend/data/photo_library/`). `manifest.json` there gives each college a different crop, so
no two colleges submit the same picture and no two rooms of one college overlap. Either would rightly be flagged
as re-used evidence. The random evaluation batch uses drawn rooms.

**Trying your own uploads:** `synthetic_test_certificates/` has ready-made PDFs and PNGs for every document type,
including a land deed, town-planning NOC, audited balance sheet, State Government NOC and trust resolution for the
New Institution, Change of Name and Course Closure categories. `14_balance_sheet_udin_not_found` and
`04_fire_noc_expired` are deliberately wrong. Sign in as `coromandel`, create an application and upload them.

**What stops an institution from submitting** is set in `categories.yaml → submission_gate`. By default an empty
mandatory slot or too few photos blocks the freeze; a wrong or expired document does not. It is shown to the
institution as a warning and reaches the officer as a finding, so it is never silently hidden.

## How the problem statement maps to the build

| Requirement in SIH26261 | Where it is | How |
|---|---|---|
| Identify category → applicable checklist | `config/categories.yaml`, `pipeline/rules.py` | Six application types (Extension of Approval, Increase in Intake, New Programme, Change of Name, New Institution, Course Closure), each with its own rules; 8 rule types (required document, not expired, max age, cross-document consistency, numeric tolerance, record match, record flag, intake within approval) |
| Retrieve institutional records already in AICTE systems | `pipeline/run.py`, `data/aicte_records.json` | Institution master, approved intake, previous EoA, **faculty records**, deficiencies, TER payments and **application history**. Every access is logged |
| Structured validation report | `app/report_pdf.py` | Downloadable PDF: summary, issues with evidence and review status, checklist results, verification table, records consulted, infrastructure, audit-trail hash. Institutions get their checklist view |
| OCR, classification, intelligent extraction | `pipeline/extract.py` | Text layer via pdfplumber; scanned pages rendered and read with Tesseract, with confidence scores; keyword + field-label classifier; configurable field patterns |
| Missing / incomplete / expired / inconsistent | `rules.py` | Missing slots, wrong document in a slot, missing fields, expiry against the academic-year start, name/ID/year/area consistency |
| Alterations, duplication, metadata, mismatched identifiers, irregular dates | `pipeline/anomaly.py` | Font-outlier field values (with page coordinates), PDF metadata (editor tools, mod-after-create, incremental saves), overlapping glyphs, byte-identical and near-identical files across institutions, certificate numbers reused across institutions, future/inverted/overlong date spans, error-level analysis for JPEG scans |
| Verify with original issuing authorities | `pipeline/verify.py`, `config/sources.yaml` | Four methods: (a) Ed25519-signed QR checked offline against the authority's public key; (b) reference-number lookup through a pluggable adapter (mock / authorized HTTP API / internal); (c) **PDF digital signatures (PAdES)** validated with pyHanko: integrity, signer chain to a trusted root, and **changes after signing**; (d) **digital-repository copy** (DigiLocker-style): the uploaded file's SHA-256 compared with the copy the issuer deposited. Records source, method, timestamp and field-by-field comparison |
| Statuses: verified, mismatch, expired, pending, source unavailable, manual review | `verify.py` | All six, plus routing to manual confirmation when no automated source exists |
| Infrastructure evidence, computer vision | `pipeline/infra.py`, `config/infra_norms.yaml` | Declared classrooms, labs, area and faculty against configurable norms; photo sharpness and darkness checks; **re-used photo detection** (ORB + RANSAC alignment, then fine-texture correlation, which catches crops and re-colouring); room-type coverage |
| Dashboard, alerts, audit trail | `frontend/`, `core/audit.py`, `core/notify.py` | Worklist, evidence viewer, alerts per audience with **response-time targets and overdue marking**, **email notifications** (outbox; delivered when SMTP is configured), **hash-chained audit log** (tampering with any entry is detected) |
| Role-based access, secure handling, human review before adverse action | `core/security.py`, `main.py` | JWT roles (institution / officer / admin) enforced server-side; file-type sniffing and size limits; content-addressed storage; forensic flags hidden from applicants; approval blocked until all high-severity flags are reviewed |
| Configurable to the APH | `app/config/*.yaml` | Rules, handbook references, what blocks submission (`submission_gate`), rectification window, infrastructure/land/cadre norms, photo GPS radius and each authority's reference field are all YAML. Reload from the admin screen; each run records the rule-set version and fingerprint |
| Explainable, evidence-backed flags | every module | Every finding has a reason, its evidence (document, line, value, expected value, source response) and the rule it came from |

### Architecture

```
 Institution portal ──upload──▶ FastAPI ──▶ extract (pdfplumber / pdfium / Tesseract) ──▶ classify + fields
                                   │
                         submit ───┤──▶ rules engine ◀── categories.yaml (APH-configurable)
                                   │       ▲
                                   │       └── AICTE records (authorized internal systems)
                                   ├──▶ anomaly indicators (fonts, metadata, duplicates, dates, ELA)
                                   ├──▶ source verification ──▶ signed-QR check (trust store)
                                   │                        └─▶ authority adapters (mock │ HTTP API │ internal)
                                   ├──▶ infrastructure (norms + OpenCV photo checks)
                                   ▼
                     findings · verifications · alerts · hash-chained audit log (SQLite → PostgreSQL)
                                   ▼
                     Officer dashboard: evidence viewer → review → recommendation (human decides)
```

---

## Evaluation (synthetic)

`scripts/evaluate.py` runs the pipeline on generated applications with known injected faults (20 fault types).
Latest run on 43 applications:

| Metric | Result |
|---|---|
| Injected faults detected | 75 / 75 (one more, an unpaid fee, was in an application the submission gate refused because a mandatory certificate was missing; fee status is only checked after submission) |
| Clean applications with any high/medium false alarm | 0 / 5 |
| High/medium flags that were real problems (precision) | 98.3% (the two exceptions: deliberately poor scans where OCR misread the Permanent ID or institution name) |
| Document classification accuracy | 100% |
| Field extraction: digital PDFs / scanned (OCR) | 100% / 98.1% |
| Copied seal or stamp (copy-move) | 5 / 5 in the batch; separately 102 / 105 pasted stamps caught with 0 false alarms on 331 clean documents |
| Documents edited after digital signing caught | 4 / 4 |
| Source checks resolved automatically | 98.1% |
| Time from submission to alerts | 3.6 s per application |
| Manual effort (assumed minutes per task, see script) | 113 h by hand → 8 h with Pramaan (≈93% less) |

These numbers show that the pipeline works as designed on data we generated ourselves. **They are not a
claim about field accuracy.** Real documents are messier, and judges will rightly ask about this. The honest
answer is that the architecture is built to be measured on authorized anonymized data, using the same script.

---

## Safeguards built in

- **Advisory, not adjudicative.** Forensic flags are labelled "preliminary indicator, not proof". Infrastructure findings are labelled advisory. The system status is a recommendation for the officer.
- **Human in the loop.** Every review needs a written remark. "Recommend for approval" is refused while any high-severity flag is unreviewed.
- **No access bypass.** Authority adapters only call configured, credentialed endpoints, and a missing credential becomes "source unavailable". No scraping. Sources with no API route the document to manual confirmation.
- **Least privilege.** Institutions see only their own applications and checklist findings. Forensic detail stays with officials.
- **Traceability.** The audit log covers logins, record access, document access, every source response, rule-set version and fingerprint, reviews and recommendations. It is hash-chained.
- **Data handling.** Uploads are type-sniffed (PDF/PNG/JPEG only) and size-capped. Files are stored by SHA-256. A **retention policy** (`PRAMAAN_RETENTION_DAYS`, admin screen *Rules → Data retention*) purges files and extracted text after a recommendation ages out, keeping findings, reviews and the audit trail; every purge is audited. Swap SQLite for PostgreSQL and local files for encrypted object storage in production.

## From prototype to production

- **Integrations:** DigiLocker / issuer APIs and state fire, pollution and municipal services under formal MoUs (add an `http` source in `sources.yaml`). Read AICTE records from the portal's own services instead of the JSON mock.
- **Trust roots:** replace the demo CA in `data/trust_store/` with CCA India and authority certificates; add OCSP/CRL revocation checks.
- **Models:** move to a layout-aware extractor (e.g. LayoutLMv3 / Donut) fine-tuned on authorized anonymized documents; geo-tag and EXIF checks for site photos; multilingual OCR (Hindi and regional languages).
- **Scale:** run validation in a job queue (Celery/RQ), use PostgreSQL, and serve files through short-lived signed URLs.

## Project layout

```
backend/
  app/main.py              REST API (FastAPI) + serves the built dashboard
  app/core/                config loading, SQLite, JWT/RBAC, hash-chained audit
  app/pipeline/            extract · rules · anomaly · verify · infra · run (orchestration)
  app/config/*.yaml        categories & rules, document types, sources, infra norms
  data/                    synthetic AICTE records, authority registry, trust store, demo documents
  scripts/                 generate_synthetic.py, seed.py, evaluate.py
  tests/                   end-to-end tests
frontend/                  React + Vite dashboard (src/pages/*, review desk in src/pages/case/), built copy in dist/
docs/screenshots/          screenshots for the presentation
```
