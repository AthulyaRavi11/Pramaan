# Demo uploads: what to upload, where

Every file here is synthetic and made for the **`coromandel`** account (Coromandel Institute of Technology,
password `demo1234`). Sets 1 to 6 come out **clean (0 issues)** when uploaded as listed. Set 7 is the same
Extension of Approval with deliberate mistakes. Every set below was uploaded and checked on 26 Oct 2026.

**Before recording:** reset the database afterwards (see the recording script). Every application you
create during a rehearsal stays in the officer's worklist.

## How to upload

1. Sign in as `coromandel` → **New application** → pick the application type.
2. Type the form values from the table for that type, then **Continue to documents**.
3. Each document slot: drag in the file named in the table (or click and choose it).
4. Photos: in the photo box pick the **room type**, type the **room number**, then choose the photo.
   The file name tells you both: `classroom_101.jpg` = room type `classroom`, room `101`;
   `seminar-hall_2.jpg` = `seminar-hall`, room `2`.
5. Click **Freeze**, then confirm. The officer sees it straight away.

## Form values (same for every type unless the type's table says otherwise)

| Field | Value |
|---|---|
| Institution name | Coromandel Institute of Technology |
| AICTE Permanent ID | 1-4412870301 |
| Academic year | 2027-28 |
| Built-up area (sqm) | 12050 |
| Classrooms / Laboratories / Full-time faculty | 18 / 18 / 21 |
| Programmes (code, name, level, intake) | BE-CSE, B.E. Computer Science and Engineering, UG engineering, 120 · BE-ECE, B.E. Electronics and Communication Engineering, UG engineering, 60 · BE-MECH, B.E. Mechanical Engineering, UG engineering, 60 · ME-CSE, M.E. Computer Science and Engineering, PG engineering, 18 |

## The sets

| Folder | Application type | Extra form values | Upload into slot → file | Photos (from `photos/`) |
|---|---|---|---|---|
| `1_Extension_of_Approval` | Extension of Approval | none | Affidavit → `affidavit.pdf` · Fire Safety NOC → `fire_noc.pdf` · Building Completion → `building.pdf` · Pollution Control Board Consent → `pollution.pdf` · University Affiliation → `university.pdf` · Processing Fee (TER) Receipt → `fee_receipt.pdf` | 4: classroom_101, lab_1, library_1, seminar-hall_1 |
| `2_Increase_in_Intake` | Increase in Intake | BE-CSE intake **180** (instead of 120) | Affidavit → `affidavit.pdf` · Fire Safety NOC → `fire_noc.pdf` · Building Completion → `building.pdf` · NBA Accreditation → `nba.pdf` | 6: the 4 above + classroom_102, lab_2 |
| `3_New_Programme` | Introduction of a new programme | New programme: BE-AIDS, B.E. Artificial Intelligence and Data Science, UG engineering, intake 60 | Affidavit → `affidavit.pdf` · University Affiliation → `university.pdf` · State Government NOC → `state_govt_noc.pdf` · Building Completion → `building.pdf` · Fire Safety NOC → `fire_noc.pdf` | 6: as set 2 |
| `4_Change_of_Name` | Change in name of the institution | Proposed name: Coromandel Institute of Technology and Science · Trust: Coromandel Educational Trust · Reason: Broader programme portfolio · Resolution date: 10-07-2026 | Affidavit → `affidavit.pdf` · Society / Trust Resolution → `trust_resolution.pdf` · State Government NOC → `state_govt_noc.pdf` · University Affiliation → `university.pdf` | none needed |
| `5_New_Institution` | Establishment of New Technical Institution | Permanent ID: leave blank · Land 10.5 acres · Survey No. SY-402/1A, SY-402/1B · District Chengalpattu · State Tamil Nadu | Affidavit → `affidavit.pdf` · Land Deed → `land_deed.pdf` · Town Planning NOC → `town_planning.pdf` · Building Completion → `building.pdf` · Fire Safety NOC → `fire_noc.pdf` · Audited Balance Sheet → `balance_sheet.pdf` | 8: all eight photos |
| `6_Course_Closure` | Closure of Course / Programme | Programme to close: BE-MECH, B.E. Mechanical Engineering, UG engineering · Reason: Low demand for three consecutive years · Students: No first-year admissions; existing batches will complete | Affidavit → `affidavit.pdf` · Society / Trust Resolution → `trust_resolution.pdf` · University Affiliation → `university.pdf` | none needed |

## Set 7: Extension of Approval with mistakes

Same form values as set 1 and the same 4 photos. Upload:

| Slot | File | What Pramaan says |
|---|---|---|
| Affidavit | `affidavit.pdf` | fine |
| Fire Safety NOC | `fire_noc_EXPIRED.pdf` | **Expired:** valid until 31-03-2026, must be valid on 01-07-2027; the fire authority's record agrees it has expired |
| Building Completion | `pollution_consent_IN_BUILDING_SLOT.pdf` | **Wrong document:** it reads as a Pollution Control Board Consent, so the building certificate counts as missing |
| Pollution Control Board Consent | `pollution.pdf` | fine |
| University Affiliation | `university.pdf` | fine |
| Processing Fee (TER) Receipt | `fee_receipt.pdf` | fine |

The institution sees these as a "things to fix" list before freezing and can still freeze; the officer then
gets 3 high-severity issues and 1 medium.

**Optional swap:** put `fire_noc_OF_ANOTHER_COLLEGE.pdf` in the Fire Safety NOC slot instead. It is Sahyadri
College's certificate, so Pramaan also reports that the institution name differs and that the certificate number
belongs to another institution.

## Photos

Eight realistic photos (classroom, computer lab, library, seminar hall; two of each). Each is a different part of
the room, so no two count as "the same photo". Each carries phone camera details and a GPS position on
Coromandel's registered campus.

To regenerate this folder: `cd backend && python scripts/make_demo_uploads.py`.
