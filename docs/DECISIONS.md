# Assumptions and decisions

For each item I describe the issue, what I decided, and why. The evidence comes
from the provider contracts in `contracts/` and from read-only calls to the
organizer's demo tenants on 2026-10-12. The field-level evidence and the full
list of what I saw live are in [SOURCE_MAPPING.md](SOURCE_MAPPING.md). The
mapping tables are in [CANONICAL_MODEL.md](CANONICAL_MODEL.md).

Contents:

- [1 Architecture](#1-architecture)
- [2 Canonical model](#2-canonical-model-principles)
- [3 Mapping decisions](#3-mapping-decisions)
- [4 Payroll totals](#4-paycheck-totals-cash-vs-non-cash)
- [5 Data that looked wrong](#5-data-that-was-inconsistent-or-different-from-the-spec)
- [6 Provider gaps](#6-provider-gaps)
- [7 Fixtures](#7-synthetic-fixtures)
- [8 Live access](#8-live-access-and-secrets)
- [9 Write path](#9-write-path-optional-extension-canonical-employee--provider-dry-run)
- [10 Limitations](#limitations)

---

## 1. Architecture

**Python 3 with Pydantic 2.** The starter project was in Python. Pydantic gives
me typed models, validation, JSON Schema export and exact `Decimal` handling
without much code. It is the only runtime dependency, and the live access code
only uses the standard library.

**The snapshot is the unit of input.**
- Issue: the starter normalized one response per entity. In practice a canonical
  record needs several endpoints. A PrismHR paycheck needs the voucher, the batch
  list (to link runs) and the employee list (to link people). An isolved
  deduction category needs the client pay-item catalog.
- Decision: each adapter takes a snapshot, which is the raw responses of one
  provider pull, keyed by endpoint and kept in their live shape. It returns one
  linked `NormalizedBundle`. The synthetic fixtures and the live fetcher both
  produce this format.
- Why: the tests go through the same path as real data, linking is possible at
  all, and a failed call becomes a recorded gap (`{"http_status": 404, …}`)
  instead of a crash.

**The canonical "company" is the legal employer.**

| Provider | Company record | Parent |
|---|---|---|
| PrismHR | client (has the FEIN) | none |
| isolved | legal company (has the FEIN; employees, checks and runs are scoped to it) | client, in `parent_id` |
| UKG Ready | EIN | company, in `parent_id` |

Why: the legal entity is what owns the employees, pays them and files taxes, so
it is the level where the three providers can be compared.

**Canonical ids look like `provider:scope:kind:source_id`.** The scope is the
level where the provider guarantees the id is unique: PrismHR client, isolved
legal company, UKG company. This stops ids from colliding between tenants and
providers. The same input always gives the same id, so running again updates
records instead of duplicating them. The pipeline checks the whole bundle for
duplicate ids and reports an ERROR if there are any. That check found a real
pagination bug (see §5).

**Status is relative to the snapshot's `as_of` date, not today.** Statuses like
"deduction ended" or "scheduled" depend on a date. If I used today, the output
would change every day and the tests would be flaky. Every snapshot records the
date it represents (`as_of`) and statuses are worked out against that. When
there is no `as_of`, a date-based status stays `UNKNOWN` instead of being
guessed.

**isolved uses the primary snapshot only**, as the brief says. I never read the
alternate snapshot for schemas.

**For UKG the cached HTML and `reference-schemas.json` are the contract.** It is
not OpenAPI, so I took endpoint bindings from the HTML, field types and enums
from the extracted JSON Schema, and units only from explicit text (milliseconds
is stated for `time` and `standard_work_day`).

## 2. Canonical model principles

| Decision | Why |
|---|---|
| Every coded field is `Coded{value, raw, description}` | The mapping can be checked and nothing is lost. You can always see the provider's own value. |
| Every enum has `UNKNOWN`, plus `OTHER` where it makes sense. A non-blank value that isn't mapped gives `UNKNOWN` and an `UNMAPPED_CODE` warning. A blank value gives `UNKNOWN` with no warning | This separates "the provider sent something we don't understand" from "the provider sent nothing". The brief says undocumented meanings stay unknown. A test checks that every `UNKNOWN` with a raw value has a warning. |
| Each record has `issues[]` with severity, code, field, message and raw value | Problems stay attached to the data they are about. The codes (`UNMAPPED_CODE`, `TOTALS_MISMATCH`, `PROVIDER_GAP`, `SENTINEL_VALUE`, `UNIT_CONVERTED`, `DERIVED_VALUE`, `ANOMALY`, …) can be filtered and counted. |
| Fields with no canonical home go into `provider_fields` as they are | The brief asks for all available employee fields. A model with the union of three providers' fields would be huge and mostly empty, so I model the common concepts and keep the rest as-is. |
| The fetcher asks for everything each provider can return about an employee | PrismHR: all 14 `getEmployee` options (events, health, skills/education, HSA, new-hire answers, enrollment status, absence journal, …). isolved: the per-employee detail with every include flag, which adds about 23 fields the list leaves out (withholding taxes, veteran, disability, tobacco, supervisor, EEO category, I-9 status, alternate pay rates), plus `/salaries` (mapped to `compensation_history`) and `/statuses` (kept as `employment_status_history`). UKG: detail, pay-info, demographics, compensation history, direct deposits, profiles, tax-info, HR custom fields and contacts. When the isolved detail is available it replaces the list record. If the detail call fails, the list fields are used and a gap is recorded. |
| Base64 documents, photos, signed photo URLs, hypermedia links and UI permission flags are dropped | They are not employee data. Some of them carry access tickets, and I-9 attachments would put identity documents in the output. Their status is kept (for example `i9Documents.i9Completed`). A test checks that no such key shows up in any bundle. |
| Empty option blocks are not stored | PrismHR returns every option block even when it is empty (for example `health` with only `bloodDonor: false`). Storing them is noise. Top-level flags such as `benefitEnrollmentCompleted: false` are always kept. |
| Money is `Decimal`, written to JSON as a string, never a float | Payroll has to add up to the cent. Providers send floats (`2.4699999999999998`), which I round to cents on input. |
| Dates are `YYYY-MM-DD` | isolved sends midnight datetimes for calendar dates. Keeping the time would suggest a timezone that isn't there. |
| Categories have a `category_basis`: `PROVIDER_TYPE`, `PROVIDER_FLAG`, `CODE_HEURISTIC` or `UNCLASSIFIED` | Earning and deduction codes are set up per tenant. Anyone reading the data should know if "MEDICAL" came from a typed provider field or from a keyword guess. |
| Only the last 4 digits of SSNs and bank accounts are kept | Data minimization. UKG and isolved return them unmasked. A test checks that no full value from the input appears anywhere in the output. |
| A paycheck has `gross_pay` (cash), `gross_wages` (including imputed income) and `totals_basis` (`PROVIDER` or `DERIVED`) | Providers don't agree on what "gross" means (see §4). Readers should know if the totals were read from the provider or calculated. |

## 3. Mapping decisions

### Employees
- **Status.** PrismHR's `statusClass` (A/L/T, documented) is the source of the
  canonical status. `employeeStatus` is a tenant-defined code, so it is kept as
  the description. isolved and UKG return labels, which are mapped one by one.
  isolved's `isPending` maps to `PENDING`.
- **Rehire.** PrismHR has no rehire field, so when `lastHireDate` is later than
  `firstHireDate` I treat the later date as a rehire. For UKG, `hired` is the
  original hire, `re_hired` is the rehire, and the current spell starts at the
  rehire.
- **Employment type and FLSA for UKG** come from the tenant's employee type
  names ("FT Exempt", "PT Hourly", "Consultant"), looked up through
  `lookup/employee-types`. This is marked `DERIVED_VALUE` because another tenant
  could name its types differently.
- **Contractors** are PrismHR `employee1099`, isolved `payType` "1099" and UKG
  "Consultant". They map to employment type `CONTRACTOR`. A contractor is still
  an employee record, because that is how each provider stores them.
- **Gender and marital status.** PrismHR `X` maps to `NON_BINARY` and `D` to
  `NOT_DISCLOSED`. UKG `UNDEFINED` maps to `NOT_DISCLOSED`. isolved's "Chose not
  to answer" (seen live) maps to a new value, `MaritalStatus.NOT_DISCLOSED`. UKG
  has no marital status at all, so it is always `UNKNOWN` with a `PROVIDER_GAP`
  note.
- **Ethnicity** is kept as the provider's label and not normalized. The code sets
  and detail differ and none of them is documented as complete.

### Compensation
- **PrismHR `salary` is per pay period, not annual.** The field description says
  so and the live data confirms it: a weekly 400.00 gives `annualPay` 20,800. The
  adapter stores `rate` with `rate_period=PAY_PERIOD` and takes `annual_amount`
  from `annualPay`. If salary × periods differs from `annualPay` by more than $1
  it raises an `ANOMALY`.
- **isolved `payFrequency` is a number of pay periods per year.** The spec only
  says "Pay Frequency". The live data settled it: Monthly = 12, Biweekly = 26,
  and `annualSalary` = `perPaySalary` × `payFrequency`. A live value of 23 maps
  to `OTHER` and raises an `ANOMALY`, because it matches no calendar.
- **UKG** amounts have an explicit `amount_period` (YEAR, HOUR, …). For hourly
  rows annual = rate × yearly hours, where yearly hours come from `time`
  (ms ÷ 3,600,000). This is marked `DERIVED_VALUE`. The `1900-12-31` zero-amount
  placeholder history row is dropped as a sentinel.
- **Rates are not converted to one unit.** I keep the provider's own figure and
  unit (`rate` + `rate_period`) next to `annual_amount` and `hourly_rate`.
  Converting everything to annual would hide what the provider actually said and
  add rounding.

### Direct deposits
- **Allocation methods** are PrismHR F/FS/P/PN/B, isolved amount-or-percent with
  sequence 0 meaning "net pay", and UKG `calc_method`. They map to
  `FIXED_AMOUNT`, `PERCENT` (with a `percent_basis` of net, gross or remaining
  net) or `REMAINDER`. PrismHR's "FS" (skip if insufficient) is kept as a flag in
  `provider_fields`.
- **Priority** is the provider's order with remainder accounts last, so
  `priority` is always the order in which the money is allocated.
- **isolved's percent basis is not documented.** I assume percent of net pay, and
  each such record has an INFO note saying so.
- **PrismHR record-level `achStatus = I`** overrides the status of each account,
  because the whole direct deposit record is switched off.

### Deductions
- **Typed provider signals come first:**
  - PrismHR `deductionType`: K, KC, KR, KCR, KE, KL, C, F, G, L, P, V (documented).
  - isolved `systemBenefitType` from the client pay-item catalog: 401(k),
    Medical/Dental/Vision Pre-Tax 125, FSA, HSA and so on.

  Generic buckets (PrismHR C = section 125, V = voluntary) are made more specific
  using the item name when it is clear: "Dental" becomes DENTAL. The basis stays
  `PROVIDER_TYPE`.
- **Without a typed signal**, the category comes from keyword matching on the
  code and name, with `category_basis: CODE_HEURISTIC`. This applies to UKG, to
  isolved items with no `systemBenefitType`, and to undocumented PrismHR types.
  Matching uses word boundaries, so "OT" does not match "other".
- **Tax treatment.** Section 125 and retirement are `PRE_TAX`, Roth is `ROTH`,
  and garnishments, loans and charity are `POST_TAX`. PrismHR scheduled
  deductions are `POST_TAX` because the docs say they come out of net earnings
  after taxes.
- **Garnishments** are `kind=GARNISHMENT`. They come from PrismHR type G and from
  isolved's separate garnishments endpoint.

### Payroll runs and taxes
- **PrismHR batch statuses** are only described as "the processing status". The
  ones I saw live (`COMP`, `INITCOMP`, `TS.READY`, `TSOKCOMP`, `INITFAIL`) are
  mapped from their names and labelled as inferred. Any other value maps to
  `UNKNOWN` with a warning.
- **isolved run history** mixes processed runs with scheduled calendar rows
  ("Payroll Not Processed", run number 0). These map to `COMPLETED` and
  `SCHEDULED`.
- **Tax type** (federal income, Social Security, Medicare, additional Medicare,
  FUTA, SUI, SDI, state, local) comes from patterns in the code and description,
  with the jurisdiction taken from state codes or names. **Payer** comes from the
  provider's typed split: PrismHR `employeeTax`/`companyTax`, isolved
  `isEmployeeTax`, UKG `ee_amount`/`er_amount`. One UKG line can give both an
  employee and an employer tax line.
- **Employer contributions** are:
  - PrismHR: `employerContributions[]` plus the retirement match.
  - isolved: "memo" earnings (`isMemoEarning`). They are not pay, so they are
    moved out of earnings.
  - UKG: `er_amount` on deduction lines.

## 4. Paycheck totals: cash vs non-cash

**Issue:** each provider's "gross" includes amounts the employee never receives:
imputed group-term life, fringe, reported tips. If I take gross as it is, net pay
doesn't add up.

**Decision:** `gross_pay` is cash earnings and `gross_wages` includes the imputed
amounts. Which reading a provider uses is decided by checking against the
provider's own net, not assumed:

| Provider | Evidence (live) | Rule |
|---|---|---|
| PrismHR | `totalEarnings` includes FRINGE other-earnings and reported `TIPS`; `earnAmount` is the cash figure | Use the first of `earnAmount` → `totalEarnings − otherEarnAmount` → `totalEarnings` that reconciles to `netPay`. The lines that explain the difference are marked `is_cash=false`. |
| isolved | `grossPay` = cash, `grossWages` = including GTL; `grossPay` also leaves out non-taxable reimbursements | Use the provider's own totals. GTL (a typed `systemBenefitType`) is non-cash. A gap equal to the reimbursement lines is expected. |
| UKG | No totals at all; imputed earnings are typed `Earning (Fringe, Auto)`; in this tenant `payments` include fringe | Totals are derived from the lines (`totals_basis=DERIVED`). Net comes from `payments` when present. Fringe counts as cash only when that is the reading that matches the payments. |

**Why:** the same concept ("imputed income") behaves differently between
providers and even between tenants. Reconciling against the provider's net is the
one piece of evidence I have in every case. Every paycheck either reconciles to
the cent or has a `TOTALS_MISMATCH` warning, and a test checks this. The one
fixture with a $1 discrepancy on purpose is flagged and not "corrected", because
I can't know which number is wrong.

## 5. Data that was inconsistent or different from the spec

The brief asks for this explicitly. Each item below is handled in code, has a
test, and its evidence is in SOURCE_MAPPING.md.

| # | What I found | What I decided |
|---|---|---|
| 1 | PrismHR returns `payrollVoucher` (singular); the spec says `payrollVouchers` | Accept both keys. The fixtures use the live key. |
| 2 | PrismHR returns `person.employerId` / `autoPolicy`; the spec says `employerIds` / `autoPolicies` | Keep them in `provider_fields`. They are on the fixture validator's drift allowlist. |
| 3 | PrismHR reports errors in the body with HTTP 200 (`errorCode != "0"`) | Check `errorCode` on every response and record a bundle-level ERROR. |
| 4 | PrismHR contact data only appears with the `ContactInformation` option, which is not in the field schema | The fetcher asks for it. Without it the employee gets an INFO note. |
| 5 | UKG's documented `GET /employees/{id}/deductions` returns 404 "Unresolvable URL" live | Reported once per bundle as a `PROVIDER_GAP`. UKG deductions come from pay statement lines. One fixture employee keeps the documented shape so that code path is still tested. |
| 6 | UKG's `lookup/eins` returned one EIN while the payrolls refer to two | Build the set of companies from the lookup, the payrolls and the employees. A reconstructed EIN gets a `PROVIDER_GAP` warning. |
| 7 | UKG REST paths live under `{base_url}/rest/v2/…`, not `{base_url}/v2` | Only affects the fetcher. |
| 8 | The isolved check list pages with the documented 0-based `filter.page`, but its `nextPageUrl` adds an ignored `page=`, so following it repeats page 0. Found by the duplicate-id check: 600 records where there should be 430 | The fetcher pages with `filter.page`. The adapter drops records repeated across pages, with an ANOMALY warning. |
| 9 | The isolved check list returns `taxes: []` even with `includeDetails`; the per-check detail has the taxes | Employee tax total = gross − deductions − net (`PROVIDER_GAP`, `totals_basis=DERIVED`, employer taxes left unknown). The fetcher pulls the detail for the most recent N checks, and the detail is preferred when present. |
| 10 | isolved `employees/{id}/payItems` returns the whole catalog; items the employee is not enrolled in have negative ids, no dates and zero values | Treated as "not enrolled" and skipped, with a counted INFO note. On live data this took 381 apparent deductions down to 5 real ones. |
| 11 | isolved returns 404 for "no direct deposits" and "no checks in range" | For those endpoints 404 means empty. Other statuses are recorded as gaps. |
| 12 | isolved `payFrequency` 23 | `OTHER` + `ANOMALY`. Not corrected. |
| 13 | "Imputed" handling is different in isolved, UKG and PrismHR (see §4) | Decided by reconciliation. |
| 14 | UKG hours are integers with no documented unit; live 144,000,000 = 40 h (the overtime amount works out to the cent) | Convert ms to hours, marked `UNIT_CONVERTED`. The reference audit warns not to guess units from how big a number is. Here the conversion is backed by live arithmetic, not by the size of the number. |
| 15 | UKG sentinels: `1900-12-31` (placeholder compensation row) and `2099-12-31` (open-ended deposit) | Treated as "not set", with an INFO `SENTINEL_VALUE` note. |
| 16 | UKG returns SSNs unmasked and isolved returns plain bank account numbers | Masked to the last 4 digits at the adapter boundary. |
| 17 | Values that are in no reference: isolved "Chose not to answer", "Guarantee"; UKG `NO_ID_NEEDED`; PrismHR `INITFAIL`, etc. | Mapped where the meaning is clear: NOT_DISCLOSED, PayType.OTHER, no national id. Inferred mappings are labelled. Anything else gets `UNMAPPED_CODE`. |
| 18 | The isolved paged envelope (`PagedModelItemListOf…`) | Not drift. It is in the spec, and an early version of my notes wrongly said it wasn't. Recorded so it is clear. |

## 6. Provider gaps

| Data | PrismHR | isolved | UKG Ready |
|---|---|---|---|
| Company status | ✓ | ✓ | ✗ no company/EIN status in v2, so `UNKNOWN` + gap note |
| Marital status | ✓ | ✓ | ✗ not exposed |
| SSN | masked by default, so no last 4 | only on `*WithSSN` endpoints | ✓ unmasked (masked by us) |
| Direct deposit effective dates | ✗ | ✗ | ✓ |
| Direct deposit / ACH ids | ✗ (I use the array position) | ✓ | ✓ |
| Deduction setup amounts | ✓ | ✓ (calc params) | ✗ 404 live; the list shape has no amounts |
| Paycheck totals | ✓ | ✓ (taxes missing from the list, see §5) | ✗ derived from lines |
| Check → run link | ✓ `batchId` | ✗ no run id; linked on (legal, check date, run number), checked live; misses become `UNRESOLVED_REFERENCE` | ✓ nested under payroll |
| Job title | ✗ code only | ✓ | ✗ job id only |

Missing data stays `null` (with a note where it matters) and is never filled
with a default.

## 7. Synthetic fixtures

There are two folders with two roles: `src/normalization/fixture_generator/` is
the code that builds the data, and `fixtures/` is the committed data it produces
(`snapshot.json` per provider plus `manifest.json`).

- **No real data in the repo.** The fixtures come from one `random.Random(seed)`
  and a fixed anchor date (2026-01-01), so the same seed always gives
  byte-identical files (`fixtures --check`, plus a test). SSNs use the
  never-issued 9xx area and emails use example domains.
- **Shared personas, provider-specific shapes.** The same people are rendered in
  each provider's format, so the outputs can be compared across providers.
- **Every fixture object is validated against the provider contract.** Fields
  the contract doesn't define make generation fail unless they are on an explicit
  live-drift allowlist, where each entry has a reason. This stops the fixtures
  from inventing fields, and it found real mistakes in my own fixture code.
- **Edge cases are fixed, not random.** Each snapshot always has the same
  scenarios: terminated, on leave, rehired, contractor, split/prenote/inactive
  deposits, garnishment, unknown codes, void/reversal, imputed income, a totals
  mismatch, an orphan check, sentinels and gaps. They are listed in
  `fixtures/manifest.json` and checked one by one in the tests.
- **Fixtures follow the live behaviour when it differs from the spec.** For
  example UKG fringe earnings are included in payments, and isolved pay items
  include catalog placeholders. So the tests cover how the APIs really behave.
- **The fixtures are payroll-consistent.** Gross − taxes − deductions = net on
  every check except the one mismatch I added on purpose, and deposit splits go
  fixed → percent → remainder.

## 8. Live access and secrets

- Live access is optional. Nothing in the tests or in `demo` needs credentials.
- The key comes from `DEMO_SIGNIN_API_KEY` in the environment or in `.env`
  (gitignored). Tokens and session ids are only held in memory and are never
  logged or written to disk.
- Calls are read-only GETs with a limited volume (`--max-employees`, page limits,
  date window). The client signs in again on a 401, because isolved tokens last
  about 5 minutes.
- Live snapshots and bundles go to `live_snapshots/` (gitignored). An automated
  scan found no tokens, signed URLs or full SSNs in any bundle.
- On python.org macOS builds, which ship without a CA bundle, the client uses
  `certifi` if it is installed and otherwise the system `/etc/ssl/cert.pem`. TLS
  verification is never turned off.

## 9. Write path (optional extension): canonical employee → provider, dry run

`python -m normalization write --provider P --input BUNDLE_OR_SNAPSHOT --dry-run`
turns canonical employees into the create/update requests each provider
documents. It is a dry run on purpose: no network call is made and there is no
code path that sends anything. The command refuses to run without `--dry-run`.

**Scope: employees only.** The brief asks for "canonical employee data". Direct
deposits, deductions and payroll are not written, because paychecks are produced
by the provider's payroll engine and are not created through an API call.

| Provider | Create | Update |
|---|---|---|
| PrismHR | `POST /newHire/v1/importEmployees`, then `POST /newHire/v1/commitEmployees` | `updateEmployeeFields`, `updateAddressInfo` (v2), `updatePayRate`, `updateJobCode`, `updateEmployeeStatusType` |
| isolved | `POST /api/clients/{clientId}/newEmployee` (body `EmployeeModel`) | `POST /api/clients/{clientId}/updateEmployee` |
| UKG Ready | `POST /rest/v2/companies/{cid}/employees`, then `PUT .../{account_id}/demographics` and `.../pay-info` | `PUT .../employees/{account_id}`, then the same two `PUT`s |

The endpoints and field names come from the contracts in `contracts/`. The tests
check every generated create body against the contract's required and allowed
fields. UKG's schema is an extract of cached HTML pages and not an official
OpenAPI file, so its field list is "as documented".

**Fields written** (canonical → provider; the report lists the exact mapping per
employee): name, birth date, gender, marital status (not UKG), home and mailing
address, phones, emails, employee number, hire/rehire/termination dates, job
code, location, department, union, manager (as an id supplied for the tenant),
pay type, rate and period, standard hours, pay group.

**Not written, and why** (always listed per employee under "not sent"):

| Field | Reason |
|---|---|
| SSN | The canonical model only keeps the last 4 digits, so a full SSN can't be produced. It is a `<ssn>` placeholder to be supplied when sending |
| Manager | A canonical manager id belongs to the source system. The destination's own employee id has to be supplied |
| UKG: salary/rate | There is no writable rate field in the documented `pay-info` schema |
| UKG: status, termination | `status` and `dates.terminated` are documented as GET only |
| UKG: marital status | Not exposed by UKG Ready |
| UKG: title, department, location | UKG gets them from the job / cost center ids, which are tenant lookups |
| Compensation history | Provider change histories are not replayed |
| Direct deposits, deductions, payroll | Out of scope (see above) |

**Provider differences handled.** Enums are reversed (for example canonical
`NON_BINARY` → PrismHR `X`, isolved `Non-Binary`, UKG `UNDEFINED`). isolved's
`payFrequency` is periods per year while PrismHR uses a period letter
(`W/B/S/M/Y`). PrismHR create is two calls (import, then commit). PrismHR update
is several endpoints with required reason codes. isolved dates are date-times.

**Values the destination tenant must supply.** Codes and ids are set up per
tenant (PrismHR status/type codes, isolved `legalCode`, `idType`, UKG
`username`, pay type ids and so on). They show up as `<name>` placeholders and
in the "you must supply" part of the report. They can be passed with
`--target KEY=VALUE` (for example `--target clientId=9001`). Placeholders are
never silently replaced by a default.

**Assumptions.**
- A source employee can be written to any provider (a cross-provider move), so
  the source's job, location, department and pay group codes are copied as they
  are and flagged in a warning: they have to exist in the destination.
- PrismHR `peoStartDate` is assumed to be the hire date, because the canonical
  model has no service provider start date.
- isolved `annualSalary` is documented as a calculated field. It is sent but
  flagged as something the tenant may ignore.
- Canonical `SEPARATED` marital status has no PrismHR code, so it is sent as `O`
  (other) with a warning.

## Limitations

- **The write path** (canonical → provider) is implemented for employees as a
  dry run only (section 9). Nothing is sent to a provider, only employees are
  covered, and the field gaps are listed there.
- **Heuristic categories.** Earning and deduction codes that are set up per
  tenant and have no typed provider signal are classified by keywords. They are
  always labelled `CODE_HEURISTIC` or `UNCLASSIFIED` and the raw code is kept. A
  real version would use per-tenant mapping overrides.
- **Inferred status names.** PrismHR batch statuses other than `COMP` are mapped
  from their names and labelled as inferred.
- **Kept but not modelled.** Some employee data is fetched and kept in
  `provider_fields` but not mapped to canonical fields: withholding elections
  (isolved `taxes`, UKG `tax_info`), employment status history (isolved
  `/statuses`), contacts/dependents, skills and education, and health. A
  canonical `tax_withholding` block would be the natural next step. UKG deduction
  detail (`/deductions/{id}`) is supported but not fetched, because the list
  endpoint is already 404 live.
- **Out of scope:** year-to-date and quarter-to-date totals, time and attendance,
  accruals, benefit enrollment beyond deductions, and tax withholding elections.
  When providers return these they are kept in `provider_fields` but not
  modelled.
- **Live coverage.** The demo tenants have limited data: UKG payrolls are OPEN
  and isolved's processed checks are 2018 data conversions. How other statuses
  behave is based on the contracts and the fixtures.
