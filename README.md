# Tada AI - HR/Payroll Data Normalization

This project takes company, employee, direct deposit, deduction and payroll data
from three providers (PrismHR, isolved and UKG Ready) and converts it into one
common model that I call the canonical model. Each value keeps the raw value from
the provider next to it. If something is unknown, derived, converted or looks
odd, it is added to the record as an issue instead of being guessed.

Other docs, in the order I'd read them:

- [docs/ASSIGNMENT.md](docs/ASSIGNMENT.md): the original assignment brief
- [docs/SOURCE_MAPPING.md](docs/SOURCE_MAPPING.md): provider field to canonical field
- [docs/CANONICAL_MODEL.md](docs/CANONICAL_MODEL.md): the full canonical model and mapping tables
- [docs/DECISIONS.md](docs/DECISIONS.md): my assumptions and decisions, and why

## Contents

- [How to run](#how-to-run)
  - [1. Set up](#1-set-up-once)
  - [2. Run the tests](#2-run-the-tests)
  - [3. Run the demo](#3-run-the-demo-normalize-all-three-providers)
  - [4. Normalize one snapshot](#4-normalize-a-single-snapshot)
  - [5. Live data](#5-optional-pull-live-data-from-the-organizers-demo-tenants)
  - [6. Fixtures](#6-regenerate-or-verify-the-synthetic-fixtures)
- [Reading the report](#reading-the-report)
- [CLI](#cli)
- [How it works](#how-it-works)
- [Repository layout](#repository-layout)
- [How I built it](#how-i-built-it)
- [Known limitations](#known-limitations)
- [Write employees to a provider (dry run)](#write-employees-to-a-provider-dry-run)
- [Troubleshooting](#troubleshooting)

## How to run

### Prerequisites

- Python 3.10 or newer (I tested on 3.10, 3.11 and 3.14). Check with
  `python3 --version`.
- Nothing else. The only dependency is Pydantic 2, which gets installed in the
  setup step. The tests and the demo don't need a network or any credentials.

### 1. Set up (once)

Run these from the repository root (the folder with this README):

```sh
python3 -m venv .venv                 # create a virtual environment
.venv/bin/pip install -e ".[dev]"     # install this package and pytest
```

On Windows use `.venv\Scripts\` instead of `.venv/bin/` in every command.

If you want, you can activate the environment so you can skip the
`.venv/bin/` prefix:

```sh
source .venv/bin/activate             # then: python -m normalization demo, pytest -q
```

### 2. Run the tests

```sh
.venv/bin/python -m pytest -q
```

You should see something like this:

```
........................................................................ [ 28%]
........................................................................ [ 56%]
........................................................................ [ 85%]
.....................................                                    [100%]
253 passed, 2997 subtests passed in 1.3s
```

`-q` is quiet mode, so each passing test is just a dot. A failing test shows as
`F` and the details are printed at the end.

The tests don't need a network or an API key. They read `fixtures/` and
`contracts/`. What they cover:

| Test file | What it checks |
|---|---|
| `test_common.py` | Parsing dates and money, masking SSNs and account numbers to the last 4 digits, code mapping, earning/deduction/tax classifiers |
| `test_prismhr.py`, `test_isolved.py`, `test_ukg_ready.py` | Every edge case in each provider's fixture (terminated and rehired employees, split deposits, garnishments, voids, imputed income, unknown codes and so on) |
| `test_cross_provider.py` | For all providers: output is deterministic, ids are unique, every link resolves, no full SSN or account number leaks, every paycheck balances or is flagged |
| `test_fixtures.py` | The committed fixtures match the generator exactly and follow the provider contracts |
| `test_robustness.py` | Failed, partial or changed API responses give issues, not crashes |
| `test_cli.py` | The `normalize`, `summary`, `demo` and `schema` commands |
| `test_writers.py` | The dry-run write path: every employee maps to every provider, request bodies follow the contracts, no SSN is written, unsupported fields are reported |
| `test_reference_integrity.py`, `test_starter.py` | The organizer's reference pack is unchanged, plus some basic checks. These make up the 2,997 subtests |

The tests don't create `output/` or change any project files. The CLI tests use
temporary folders. The only thing left behind is pytest's `.pytest_cache/`,
which is gitignored. To get the output files, run the demo in step 3.

### 3. Run the demo (normalize all three providers)

```sh
.venv/bin/python -m normalization demo
```

This also needs no network and no API key. It reads the three committed
snapshots (`fixtures/prismhr/snapshot.json`, `fixtures/isolved/snapshot.json`
and `fixtures/ukg-ready/snapshot.json`). These are fake but realistic raw API
responses. Each one goes through its provider's adapter (code mapping, linking,
PII masking, paycheck checks), a report is printed, and these files are written:

| File | Contents |
|---|---|
| `output/<provider>.bundle.json` | The canonical data: companies, employees, direct deposits, deductions, payroll runs and paychecks, linked by canonical ids. Every record has its own `issues` list |
| `output/<provider>.summary.json` | Record counts, payroll totals and issues grouped by code |

Running `demo` again overwrites these files. `output/` is gitignored, so you can
delete it any time and run again. To write somewhere else use
`demo --out some/folder`.

The report it prints, the `GENERATED FILES` list and how to read the bundle
files are explained in [Reading the report](#reading-the-report).

### 4. Normalize a single snapshot

```sh
# whole bundle to a file (here: isolved.json in the current folder)
.venv/bin/python -m normalization normalize --input fixtures/isolved/snapshot.json --output isolved.json

# one entity type to the terminal: company | employee | direct_deposit | deduction | payroll_run | paycheck
.venv/bin/python -m normalization normalize --input fixtures/ukg-ready/snapshot.json --entity paycheck --output -

# counts and issues only
.venv/bin/python -m normalization summary --input fixtures/prismhr/snapshot.json
```

The provider is read from the snapshot. Existing output files are not
overwritten unless you add `--overwrite`. The report goes to the terminal
(stderr) and a `GENERATED FILES` list shows what was written.

### 5. Optional: pull live data from the organizer's demo tenants

This needs the API key from the organizer. Put it in a `.env` file in the
repository root (it is gitignored) or export it as an environment variable. If
you don't have a `.env` yet:

```sh
echo 'DEMO_SIGNIN_API_KEY=your-key-here' > .env    # careful: '>' replaces an existing .env
# or, for the current shell only:
export DEMO_SIGNIN_API_KEY=your-key-here
```

Then fetch a read-only snapshot. Add `--normalize` to also write the canonical
bundle:

```sh
.venv/bin/python -m normalization fetch --provider ukg-ready --normalize
.venv/bin/python -m normalization fetch --provider prismhr --normalize
.venv/bin/python -m normalization fetch --provider isolved --days 3300 --normalize   # demo checks are from 2018
```

While it runs you will see `Running API calls to fetch data, it may take a few
seconds...` and a spinner with the number of API calls done so far (for example
`fetching... 173 API calls done (42s)`). The spinner only shows in a normal
terminal.

Results go to `live_snapshots/<provider>-<date>.snapshot.json` (and
`.bundle.json` with `--normalize`), and both are listed at the end. This folder
is gitignored because it has demo data. Tokens are never printed or saved.

The fetch is limited so it stays small:

- `--max-employees` (default 25) applies to all providers.
- `--days` (default 365) is how far back to look for payroll, for PrismHR and
  isolved. UKG fetches its 6 most recent payrolls instead.
- `--client ID` picks a PrismHR client. By default it is the first demo client.

Because of the employee limit you will probably see some `UNRESOLVED_REFERENCE`
warnings: paychecks or managers can belong to employees that are outside the
limited pull. Raise `--max-employees` to include more.

### 6. Regenerate or verify the synthetic fixtures

```sh
.venv/bin/python -m normalization fixtures --check   # check the committed fixtures are reproduced exactly
.venv/bin/python -m normalization fixtures           # regenerate them (validated against the provider contracts)
```

## Reading the report

Every command that normalizes data prints the same report. This is the isolved
one, shortened:

```
========================================================================
== isolved ==  NORMALIZATION REPORT
========================================================================

1. RECORDS PRODUCED
   company            2   employer entities
   employee           9   people on payroll
   ...
2. ISSUES BY SEVERITY
   ERROR       0   record unusable or dropped
   WARNING     3   record kept, but a value needs human review
   INFO       12   normal notes: a value was derived, assumed or converted

3. PAYROLL TOTALS (sum over all paychecks in the snapshot)
   gross pay: 99174.76
   net pay:   73131.37   (difference = taxes + deductions)
   paychecks not linked to a payroll run: 1  (still included in the totals)
   per company:
     isolved:8001:company:8001: 19 paychecks, gross=59594.97, net=44316.91
     isolved:8002:company:8002: 9 paychecks, gross=39579.79, net=28814.46

4. ITEMS NEEDING REVIEW (WARNING / ERROR)
   [1] WARNING UNMAPPED_CODE - provider value is not in our mapping table
       record:  isolved:8001:employee:860105
       field:   employees.marital_status
       detail:  provider value not in MaritalStatus mapping  (raw value: 'Domestic Partner')
       action:  add the value to the mapping table, or map it to an 'other' value
   ...
5. INFORMATIONAL NOTES (no action required)
   x9   DERIVED_VALUE on employees.deductions: 1 catalog placeholder pay item(s) ... treated as not enrolled
   ...
```

The parts of the report mean this:

| Section | What it means |
|---|---|
| 1. Records produced | How many canonical records of each type were created |
| 2. Issues by severity | `ERROR` means a record was unusable or dropped (should always be 0). `WARNING` means the record was kept but a value needs a look. `INFO` is a normal note that a value was derived, assumed or converted |
| 3. Payroll totals | Gross and net over all paychecks in the snapshot, a split per company, and how many paychecks could not be linked to a payroll run (they are still counted in the totals) |
| 4. Items needing review | Every WARNING and ERROR with the issue code, the record id, the field, the raw provider value and a suggested action |
| 5. Informational notes | INFO items grouped by code and field with a count. No action needed |

Issue codes:

| Code | Meaning |
|---|---|
| `UNMAPPED_CODE` | The provider value is not in our mapping table |
| `MISSING_REQUIRED` | A field needed for the canonical record is missing |
| `INVALID_VALUE` | The value is there but can't be parsed (date, number, ...) |
| `DERIVED_VALUE` | The canonical value was calculated or assumed, not read directly |
| `UNIT_CONVERTED` | A unit conversion was applied |
| `TOTALS_MISMATCH` | The provider's totals don't match its own line items |
| `SENTINEL_VALUE` | A placeholder date such as 1900-12-31 or 2099-12-31 |
| `UNRESOLVED_REFERENCE` | A link to another record could not be made |
| `PROVIDER_GAP` | The provider does not give this data |
| `ANOMALY` | The value is valid but looks suspicious |

The same data is available as JSON with `summary --json` (keys: `records`,
`issues_by_severity`, `issues`, `paychecks`, `details`).

When files are written, the command ends with a list of them as `folder/file`
and a short description of each:

```
GENERATED FILES
  output/isolved.bundle.json
      -> normalized canonical bundle for isolved (JSON)
  output/isolved.summary.json
      -> record counts, issues and payroll totals for isolved (JSON)
```

The warnings are expected. I added problem cases to the fixtures on purpose, for
example provider codes that are not documented, a paycheck whose net pay is $1
off from its own lines, or an isolved check with no matching payroll run. The
warnings show that these were caught.

To look at the results, open for example `output/isolved.bundle.json`. Each
record shows the canonical value next to the provider's raw value, plus its
issues. For example, for employee `isolved:8002:employee:860202`:

```json
"employment": {"status": {"value": "ACTIVE", "raw": "Active"}, "hire_date": "2024-01-28", …},
"issues": [{"severity": "WARNING", "code": "ANOMALY", "field": "compensation.pay_frequency",
            "message": "payFrequency 23 periods/year is not a standard calendar", "raw_value": 23}]
```

## CLI

All commands run as `python -m normalization <command>` (or
`.venv/bin/python -m normalization <command>` if the venv is not activated):

| Command | What it does | Example |
|---|---|---|
| `demo [--out DIR]` | Normalize every fixture snapshot and print the reports | `python -m normalization demo` |
| `normalize --input SNAPSHOT --output FILE\|- [--entity E] [--as-of YYYY-MM-DD] [--overwrite]` | Turn a snapshot into a bundle, or into the records of one entity. It won't overwrite an existing file unless you pass `--overwrite` | `python -m normalization normalize --input fixtures/isolved/snapshot.json --output isolved.json` |
| | Print only one entity type to the terminal | `python -m normalization normalize --input fixtures/ukg-ready/snapshot.json --entity paycheck --output -` |
| | Work out date-based statuses as of a given date | `python -m normalization normalize --input fixtures/prismhr/snapshot.json --entity deduction --as-of 2025-06-01 --output -` |
| `summary --input SNAPSHOT_OR_BUNDLE [--json]` | Record counts, payroll totals and issues grouped by code | `python -m normalization summary --input fixtures/prismhr/snapshot.json` |
| `fixtures [--check]` | Regenerate the synthetic fixtures, or check they are still reproduced exactly | `python -m normalization fixtures --check` |
| `schema [--output FILE]` | Export the canonical JSON Schema | `python -m normalization schema --output /tmp/bundle.schema.json` |
| `fetch --provider P [--normalize] [--max-employees N] [--days N] [--client ID]` | Optional, read-only pull from the organizer's demo tenant (see [How to run § 5](#5-optional-pull-live-data-from-the-organizers-demo-tenants)) | `python -m normalization fetch --provider ukg-ready --normalize` |
| `write --provider P --input BUNDLE_OR_SNAPSHOT --dry-run [--employee ID] [--operation create\|update] [--target KEY=VALUE] [--output FILE\|-]` | Optional extension: map canonical employees to a provider's create/update requests. Dry run only, nothing is sent (see [Write employees to a provider](#write-employees-to-a-provider-dry-run)) | `python -m normalization write --provider ukg-ready --input fixtures/isolved/snapshot.json --dry-run` |
| `list-providers` | Print the supported provider names | `python -m normalization list-providers` |
| `check-inputs` | Kept from the starter (reference pack readiness; exits with 2 for the unlicensed isolved/UKG packs) | `python -m normalization check-inputs` |

`E` is one of `company`, `employee`, `direct_deposit`, `deduction`,
`payroll_run` or `paycheck`. `P` is one of `prismhr`, `isolved` or `ukg-ready`.

## How it works

```
 provider APIs ──(optional) fetch──▶ snapshot.json ──adapter──▶ NormalizedBundle ──▶ JSON / summary
                                         ▲
 seeded generator ──contract-validated───┘   (fixtures/<provider>/snapshot.json)
```

The optional write flow goes the other way, as a dry run: a `NormalizedBundle`
employee goes through a writer and becomes provider create/update requests that
are printed and never sent. See
[Write employees to a provider](#write-employees-to-a-provider-dry-run).

1. Snapshot. This is the raw provider responses for one pull, kept in their
   live shape: paged responses, errors inside the body, `{"http_status": 404}`
   markers for failed calls. The fake fixtures and live pulls use the same
   format, so the tests go through the same code as real data.
2. Adapter (one per provider, in `src/normalization/adapters/`). It applies the
   source-to-canonical mapping tables, links records by canonical id, masks PII,
   converts units only when there is evidence, and checks every paycheck
   (gross - employee taxes - employee deductions = net).
3. Bundle. A `NormalizedBundle` holds `companies`, `employees`,
   `direct_deposits`, `deductions`, `payroll_runs` and `paychecks` (each
   paycheck has earnings, taxes, deductions, employer contributions and deposit
   lines), linked by ids like `isolved:5797:employee:859112`.

### In plain words: reading an employee from a provider

Take one employee, Jordan. Each provider describes the same person in a
different way: isolved says `"Male"`, PrismHR says `"M"` and UKG says `"MALE"`,
and the hire date is `hireDate` in one and `dates.hired` in another.

1. Pull: the snapshot has the provider's raw answers for Jordan.
2. Normalize: the adapter turns them into one canonical employee and keeps the
   raw value next to each translated one, e.g. `{"value": "MALE", "raw": "Male"}`.
3. Flag: anything that can't be translated cleanly (a marital status the
   provider never documented, a pay frequency of 23 periods a year) stays on the
   record as an issue instead of being guessed.

Writing Jordan to another provider is the same trip in reverse, as a dry run.

### Canonical model at a glance

| Record | Main contents |
|---|---|
| Company | The legal employer (PrismHR client, isolved legal company, UKG EIN), with parent account, FEIN, status, address and pay groups |
| Employee | Name, birth date, gender, marital status, SSN last 4, addresses, emails, phones; employment (status, type, hire/rehire/termination dates); job (title, code, FLSA, department, location, manager); compensation (pay type, frequency, rate and rate period, annual, hourly, standard hours); compensation history; `provider_fields` for everything else |
| DirectDeposit | Priority, account type, routing, account last 4, method (fixed / percent / remainder), amount or percent and its basis, status, prenote, effective dates |
| DeductionSetup | Code, kind (recurring / one-time / garnishment), category and how it was classified, tax treatment, catch-up flag, calc method, amount or percent, limits, schedule, dates, status, plan, payee, employer match |
| PayrollRun | Type, status, pay date, period, run number, pay groups |
| Paycheck | Run link, type, status, dates, payment method, gross (cash) and gross wages, net, employee/employer taxes, deductions, employer contributions, hours, `totals_basis` (provider or derived), and all line items |

The full spec and every mapping table are in
[docs/CANONICAL_MODEL.md](docs/CANONICAL_MODEL.md). The JSON Schema is
[schemas/canonical-bundle.schema.json](schemas/canonical-bundle.schema.json).

Each coded field is stored as `{"value": "ACTIVE", "raw": "A"}`. Each record has
`issues` that look like this:

```json
{"severity": "WARNING", "code": "UNMAPPED_CODE", "field": "employment.status",
 "message": "provider value not in EmploymentStatus mapping", "raw_value": "X"}
```

## Repository layout

```
src/normalization/
  canonical/          enums, Pydantic models, NormalizedBundle, id + masking helpers
  adapters/           prismhr.py, isolved.py, ukg_ready.py, _common.py (parsing, mapping, classifiers), status.py
  fixture_generator/  CODE that builds the synthetic snapshots (seeded) + contract validator (validate.py)
  live/               demo sign-in client + per-provider fetchers (optional)
  writers/            dry-run write path: base.py (WritePlan), prismhr.py, isolved.py, ukg_ready.py, report.py
  references.py       reference-pack readiness check (kept from the starter)
  report.py           the report + JSON summary
  __main__.py         CLI
fixtures/             DATA: the committed synthetic snapshots + manifest.json (seed, hashes, scenarios), made by fixture_generator/
schemas/              exported canonical JSON Schema
scripts/              generate_fixtures.py
tests/                pytest suite (unit, per-provider scenarios, cross-provider properties, robustness, CLI, writers)
contracts/            provider reference pack (unchanged from the starter)
docs/                 DECISIONS.md, SOURCE_MAPPING.md, CANONICAL_MODEL.md, ASSIGNMENT.md
pyproject.toml        package metadata and dependencies
.env                  your API key for live pulls (gitignored, never committed)
output/               demo results (generated, gitignored)
live_snapshots/       live pulls (generated, gitignored)
```

## How I built it

1. Discovery from the contracts. I listed the relevant endpoints for each
   provider and data type and flattened their response schemas into field paths.
   I took code meanings from the PrismHR field descriptions, the UKG JSON-schema
   enums and the isolved lookup reference. The result is
   [docs/SOURCE_MAPPING.md](docs/SOURCE_MAPPING.md).
2. Checking against the live demo tenants. These were read-only calls and the
   raw data never went into the repo. This answered things the specs couldn't:
   units (UKG hours are milliseconds), meaning (PrismHR salary is per pay
   period, isolved `payFrequency` is periods per year) and where the specs differ
   from the live API (for example PrismHR's `payrollVoucher` key).
3. Canonical model and enums. I followed three rules: keep the raw value, explain
   every mapping that isn't direct, and don't lose data.
4. Synthetic fixtures. A seeded generator creates one set of fake people and
   renders them in each provider's live shape. Every object is validated against
   the provider contract, and the edge cases are listed in the manifest.
5. Adapters. They do the mapping tables, linking, masking, unit handling (only
   with evidence) and paycheck checks.
6. End-to-end live runs. Running `fetch` then normalize on all three demo tenants
   showed more undocumented behaviour (isolved pagination and check lists without
   taxes, PrismHR reported tips, UKG fringe handling and others). I fixed each
   one and copied the case back into the fixtures.
7. Tests. There are 253 tests: unit tests, a test for each fixture scenario,
   cross-provider properties (determinism, integrity, no PII leaks,
   reconciliation), robustness against failed or changed responses, and the CLI.
   The tests caught three bugs, and the duplicate-id check found the isolved
   pagination bug.
8. Optional write path. A canonical employee can be mapped back into each
   provider's create/update requests as a dry run. The request shapes come from
   the contracts and the tests check them against those contracts. See
   [Write employees to a provider](#write-employees-to-a-provider-dry-run).

I used AI assistance while working on this, as the brief allows, and
checked the mappings against the contracts and the live demo data.

## Known limitations

More detail is in [DECISIONS.md](docs/DECISIONS.md#limitations).

- The write path is dry run only and only for employees. Nothing is sent to a
  provider, and direct deposits, deductions and payroll are not written. See
  [Write employees to a provider](#write-employees-to-a-provider-dry-run).
- Earning and deduction codes are configured per tenant. When a provider gives
  no typed signal, categories come from keyword guesses, and these are marked
  `category_basis: CODE_HEURISTIC`.
- UKG's per-employee deduction setup endpoint returns 404 on the live tenant, so
  UKG deductions come from pay statement lines.
- The fetcher pulls all the employee data each provider exposes. Common concepts
  are mapped to canonical fields. The rest is kept in `provider_fields` but not
  modelled: withholding elections, status history, contacts, skills.
- Year-to-date totals, time and attendance, and benefit enrollment details
  beyond deductions are out of scope.

## Write employees to a provider (dry run)

The assignment has an optional extension: a write path from canonical employee
data to a provider. I built it as a dry run. It builds the requests a provider
would receive and prints them, and it never sends anything. It works offline,
and an employee from any provider can be written to any provider.

### In plain words: moving an employee between providers

Say Jordan Nguyen works at a company that runs payroll in isolved, and the
company is moving to UKG Ready.

1. Today: Jordan exists in isolved as `isolved:8001:employee:860100`.
2. Normalize: we read Jordan and convert the record to the canonical employee.
3. Write (dry run): we ask what we would have to send to create Jordan in UKG
   Ready. The tool turns the canonical record into UKG's requests.
4. Nothing is sent. The requests are only printed so they can be checked first.

```
isolved                    canonical                     UKG Ready
Jordan (isolved shape) →   Jordan (canonical)   →   Jordan (UKG shape, printed only)
```

| In isolved | In UKG Ready (what would be sent) |
|---|---|
| `nameAddress.firstName` = Jordan | `first_name` = Jordan |
| `hireDate` = 2025-06-10 | `dates.hired` = 2025-06-10 |
| `gender` = "Male" | `gender` = MALE (a separate `demographics` call) |
| `nameAddress.address1` = 1323 Elm Way | `address.address_line_1` = 1323 Elm Way |

Things the tool can't do by itself:

- SSN: the canonical model only keeps the last 4 digits, so the full number has
  to be supplied when actually sending.
- Username: UKG needs one and isolved doesn't have one, so it is given with
  `--target username=...`.
- Salary: UKG has no documented field for writing the pay rate, so it is listed
  as not supported.

### The write flow

```
 snapshot / bundle ──normalize──▶ canonical Employee ──writer (per provider)──▶ WritePlan ──▶ report + JSON
 (any provider)                   (our model)           reverses the mapping     (dry run)     (nothing sent)
                                                        + --target values
```

1. Read: `write --input` takes a provider snapshot or a normalized bundle and
   loads its canonical employees (all of them, or the ones given with
   `--employee`).
2. Choose the destination: `--provider` picks the writer (PrismHR, isolved or
   UKG Ready) and `--operation` picks `create` or `update`. The source and the
   destination can be different providers.
3. Map: the writer reverses the normalization mapping. Canonical enums become
   the destination's codes, units are converted, and fields the destination
   can't take are recorded instead of dropped.
4. Tenant values: codes and ids that only the destination tenant knows come from
   `--target KEY=VALUE`. Anything still missing stays as a `<name>` placeholder
   and is listed in the report.
5. Plan: the result is a write plan with the ordered requests, the mapped
   fields, the unsupported fields with reasons, the values the tenant must
   supply, and warnings.
6. Output: the plan is printed as a readable report and also as JSON (to stdout,
   or to a file with `--output`). No request is ever sent, and the command
   refuses to run without `--dry-run`.

Example (an isolved employee written to UKG Ready), shortened:

```
POST /rest/v2/companies/33704016/employees
{ "first_name": "Jordan", "last_name": "Nguyen", "username": "jnguyen",
  "address": {...}, "phones": {...}, "dates": {"hired": "2025-06-10", "birthday": "1985-01-06"} }
PUT  /rest/v2/companies/33704016/employees/<account_id from the create response>/demographics
{ "gender": "MALE", "ethnicity": "HISPANIC_OR_LATINO" }
```

### Commands

```sh
# Jordan moves from isolved to UKG Ready: show the requests that would CREATE Jordan in UKG (nothing is sent)
.venv/bin/python -m normalization write --provider ukg-ready \
    --input fixtures/isolved/snapshot.json --employee isolved:8001:employee:860100 --dry-run

# Jordan moves from isolved to PrismHR: same preview, plus the PrismHR client id and status code that only the destination knows
.venv/bin/python -m normalization write --provider prismhr --input fixtures/isolved/snapshot.json \
    --employee isolved:8001:employee:860100 --target clientId=9001 --target employeeStatusCode=A --dry-run

# PrismHR employees who already exist in isolved: preview the UPDATES to apply there, and save the plan as JSON
.venv/bin/python -m normalization write --provider isolved --input fixtures/prismhr/snapshot.json \
    --operation update --dry-run --output output/isolved-update-plan.json
```

The report printed in the terminal is meant to be easy to follow. For each
employee it shows:

1. a header with who is being written, the action and the journey
   `source record → canonical employee → destination requests`, plus a short
   summary (how many fields can be sent, can't be sent, or need a value from the
   destination tenant);
2. how each value travels: the canonical field, its value, the destination field
   and what it is sent as (for example `MALE` becomes `M`);
3. the requests, in order, with their bodies;
4. what is not sent: fields the destination can't take, with the value and the
   reason;
5. what you must supply: tenant values shown as `<name>` placeholders (fill them
   with `--target KEY=VALUE`);
6. the things I assumed, and next steps.

The JSON plan is not printed in a terminal, to keep the screen readable. Add
`--output plan.json` to save it. When output is piped, the JSON goes to stdout.

| Provider | Create | Update |
|---|---|---|
| PrismHR | `importEmployees`, then `commitEmployees` | `updateEmployeeFields`, `updateAddressInfo`, `updatePayRate`, `updateJobCode`, `updateEmployeeStatusType` |
| isolved | `newEmployee` | `updateEmployee` |
| UKG Ready | `POST employees`, then `PUT demographics` and `pay-info` | `PUT employees/{account_id}`, then the same two |

The full SSN is never written (the canonical model keeps only the last 4
digits), so it is always a placeholder. The reasoning, the field table and the
limitations are in
[docs/DECISIONS.md](docs/DECISIONS.md#9-write-path-optional-extension-canonical-employee--provider-dry-run).

## Troubleshooting

| Problem | Fix |
|---|---|
| `No module named normalization` | Run the install step (1), or use `.venv/bin/python` instead of the system `python3` |
| `refusing to overwrite …` | Add `--overwrite`, or use another `--output` |
| `fetch` fails with `CERTIFICATE_VERIFY_FAILED` | The client uses `certifi` if it is installed, otherwise the macOS system bundle `/etc/ssl/cert.pem`. On other systems run `.venv/bin/pip install certifi` |
| `fetch` says `DEMO_SIGNIN_API_KEY not set` | Create `.env` as shown in step 5, in the repository root |
| The first `fetch` is slow | The hosted sign-in service goes to sleep after a while (the spinner says `signing in`). Just wait and retry |
