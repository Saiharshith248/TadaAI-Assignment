# Source discovery: endpoints, fields and evidence per provider

This is the discovery record behind the adapters. It lists, for each data type,
which provider endpoints carry the data, which fields matter, what the contract
says about codes/units, and what is missing. Field paths are dotted response paths
(`[]` = array item). "Evidence" means the contract text itself; anything not
evidenced is called out as an assumption in `DECISIONS.md`.

Sources: PrismHR OpenAPI 3.0.1 (2025.09), isolved Swagger 2.0 v6 **primary**
snapshot only, UKG Ready cached HTML + `reference-schemas.json`.

---

## 1. Company

| | PrismHR | isolved | UKG Ready |
|---|---|---|---|
| List | `GET /clientMaster/v1/getClientList` → `clientListResult.clientList[]` (clientId, clientName, legalName, status) | `GET /api/clients` and `GET /api/clients/{clientId}/legals` | `GET /v2/companies/{cid}/lookup/eins` (legal entities); company itself = `cid` |
| Detail | `GET /clientMaster/v1/getClientMaster` → `clientMaster.*` | `GET /api/clients/{clientId}/legals/{id}` (LegalModel) | none in v2 reference beyond EIN lookup |
| Key fields | id, clientName (DBA), legalName, federalIdNumber, status (+statusClass), serviceType, address (city/stateCode/zipCode), mainPhone, emailAddress, sicCode, corporationType | Client: id, clientCode, clientName. Legal: id, legalCode, legalName, dbaName, federalEIN, legalAddress.*, naicsCode, status, payGroups[] (id, payGroupName, payFrequency) | ein.id, ein_name, ein_tax_id (also embedded on payrolls/pay-periods) |
| Codes | `statusClass` A/P/I/C/T and `serviceType` ASO/PEO/PAY/ASA/COR/HRN documented in lookup-reference | `status` free text, no enum | none |

**Hierarchy note.** isolved has two levels: *client* (tenant account) → *legal
company* (EIN). Employees, checks and payrolls are all scoped under
`/clients/{clientId}/legals/{legalId}`. UKG has *company* (`cid`) → *EIN*
(multi-EIN companies). PrismHR has a flat *client* that already carries the FEIN.

## 2. Employee

| Area | PrismHR (`GET /employee/v1/getEmployee?options=…`, ≤20 ids/call; ids from `getEmployeeList`) | isolved (`GET /api/clients/{c}/legals/{l}/employees/{id}`, list = same path w/o id) | UKG Ready (`GET /v2/companies/{cid}/employees/{aid}` + `/pay-info`, `/demographics`, `/compensation/history`) |
|---|---|---|---|
| IDs | id, client.clientEmployeeId, client.clockNum, person.legacyEmployeeId | id (int), employeeNumber, uniqueId, timeclockId | id (account id), employee_id, external_id, username |
| Name | firstName, lastName, middleInitial, preferredName, person.nickname | nameAddress.firstName/middleName/lastName/prefix/suffix/preferredName | first_name, middle_name, last_name, nickname, salutation, suffix |
| Personal | person.birthDate, gender (M/F/X/D), maritalStatus (S/M/D/W/C…), ethnicCode, veteran flags Y/N/D, handicapped, smoker | birthDate, gender (description text), maritalStatus (code), ethnicOrigin (text), citizenship, protectedVeteran, disabled, tobaccoUse | dates.birthday; demographics.gender MALE/FEMALE/UNDEFINED, ethnicity enum, citizenship enum |
| National id | compensation.ssn (masked by default) | ssn + idType (only on `employeesWithSSN`) | national_id_numbers[] {type: SSN/SIN/…, value, primary}, social_security |
| Contact | contactInformation.addressLine1/2, city, state, zipcode, zipSuffix, county, homePhone, mobilePhone, emailAddress; client.workEmail, client.workPhone(+Ext) | nameAddress.address1/2, city, state, zipCode; personal.homePhone/mobilePhone/officePhone/personalEmailAddress; emailAddress | address{address_line_1..3, city, state/state_code, zip, country}, mailing_address, phones.{home,cell,work}_phone, primary_email, secondary_email |
| Status | client.employeeStatus (tenant code), client.statusClass **A/L/T** (documented), statusDate, client.employeeType + typeClass | employmentStatus (description, deprecated), statusDate; history via `/statuses` | status (string, undocumented values) |
| Dates | client.firstHireDate, lastHireDate, jobStartDate, seniorityDate, statusDate (term date when T), compensation.lastWorkedDate | originalHireDate, hireDate, rehireDate, terminationDate, terminationReason/Type, adjustedServiceDate | dates.hired, re_hired, started, terminated, seniority, retired, deceased |
| Job / org | client.jobCode, homeDivision, homeDepartment, homeLocation, workGroupCode, manager, reportsTo, flsaExempt, unionCode | jobCode, jobTitle, jobId, jobFLSAExempt, jobEffectiveDate, workLocation, organizations[] {title,value}, assignedManager/Supervisor, employmentCategoryCode (FT/PT…), isRemoteWorker | pay-info.default_job.id, cost_centers_info, managers[], employee_type.id, union.id, ein |
| Compensation | compensation.payMethod S/H/C/D, salary (per pay period), hourlyPay, hourlyPayRate+hourlyPayPeriod, annualPay, payGroup, payPeriod, standardHours, effectiveDate; history: `getPayRateHistory` | payType (text), annualSalary, perPaySalary, hourlyRate, payFrequency (int, undocumented), payGroup, normalHours, salaryEffectiveDate; history: `/salaries` | compensation/history: amount + amount_period YEAR/MONTH/WEEK/HOUR/PAY_PERIOD, hourly_pay, currency, effective_from, num_pp_in_year; pay-info.pay_type.id |
| Tax setup | fedFilingStatus, fedWithholdAllowance, stateTax[] … | taxes.federal/residentState… (with includeTaxes) | tax-info |

## 3. Direct deposit

| | PrismHR (`getEmployee?options=DirectDeposit`) | isolved (`GET …/employees/{e}/directdeposits`, also embedded in employee) | UKG Ready (`GET …/employees/{aid}/direct-deposits`) |
|---|---|---|---|
| Record | `directDeposit.achVoucher[]` (no id, order = priority) | `[]` with id, sequenceNumber (**0 = Net Pay / remainder**) | `deposits[]` with id, sequence |
| Account | transitNum, accountNum, bankName, accountType **C / S / IP …** (C,S,IP documented for updates) | routingNumber, accountNumber, bankName, accountType (description text) | routing_number, account_number, account_type CHECKING/SAVINGS, routing_type |
| Allocation | method **F** fixed, **P** percent, **FS**, **PN**, **B** balance (documented), amount, limit (cap for P) | amount XOR percent; sequence 0 = remainder | calc_method.type FULL / FLAT_AMOUNT / GROSS_EARNING / NET_PAY / DIRECT_DEPOSIT_PER_OF_REMAINDER, amount, percentage |
| Status | per-account status **P** prenote, **D** active, **I** inactive; plus record-level achStatus A/I | status (description text) | active bool, active_from/active_to, pre_note_status enum |
| Dates | none | none | active_from, active_to, pre_note_sent_date |

## 4. Deductions (setup + recorded in payroll)

**Setup**

| | PrismHR | isolved | UKG Ready |
|---|---|---|---|
| Endpoints | `deductions/v1/getDeductions` (all recurring), `getVoluntaryRecurringDeductions`, `employee/v1/getScheduledDeductions` (one-time/temporary), code catalog `codeFiles/v1/getDeductionCodeDetails` | `GET …/employees/{e}/payItems` (filter payItemType = deduction), corestream `…/employees/{e}/deductions`; catalog `GET /api/clients/{c}/payItems?payItemFilter=Deduction`; garnishments separate | `GET …/employees/{aid}/deductions` (list: code/name/dates only), `…/deductions/{id}` (detail with calc), catalog `lookup/deduction-codes` |
| Fields | deductionCode, deductionType (code → documented: V, C, P, F, G, L, K, KC, KE, KL, KR, KCR), description, usePercent, amount, period, limit, maximum + basis M/Q/A/L, startDate, stopDate, benefitPlanId, matchMethod/matchAmount, trackArrears | payItemCode, payItemName, payItemType, calcParams[] {paramType, paramValue} (types undocumented), startDate, stopDate, referenceNumber | deduction.code/name, effective_from/to, ee_calc_method {method.type, amount, percent}, ee_max/min, annual_max_amount, ee/er_frequency.type enum, vendor |

**Recorded in payroll** — see paycheck deductions in §5.

## 5. Payroll runs and paychecks

| | PrismHR | isolved | UKG Ready |
|---|---|---|---|
| Runs | `payroll/v1/getBatchListByDate` → batchList[] {batchId, payDate, batchType R/M/S/V, batchStatus, payGroup[] {payGroupId, payPeriodStartDate, payPeriodEndDate}}; `getBatchInfo` | `GET …/legals/{l}/paygroupId/{pg}/payrollRunHistory` → id, payDate, periodBeginDate, periodEndDate, payrollRunType, status, runNumber, runDate | `GET /v2/companies/{cid}/payrolls` → id, name, start_date, end_date, pay_date, type{id,display_name}, status (NEW…FINALIZED enum), ein |
| Paychecks | `payroll/v1/getPayrollVouchers` (by pay date, paginated) / `getPayrollVoucherForBatch` → payrollVouchers[] | `GET …/legals/{l}/checks?includeDetails=true` / `…/employees/{e}/checks/{id}` | `GET …/payrolls/{id}/pay-statements` (list) + `…/pay-statements/{id}` (detail) |
| Link to run | voucher.batchId | `payrollRunNumber` + check date (no explicit run id on check — see DECISIONS) | statement is nested under payroll id |
| Link to employee | employeeId | employeeId, employeeNumber | employee.account_id |
| Totals | totalEarnings, netPay, checkAmt | grossPay, grossWages, netPay, checkAmount, directDepositAmount | **none** — gross/net must be derived from lines |
| Earnings | earning[] {payCode, payClass, hoursUnits, hoursWorked, payAmount, unitRate…} + otherEarningsDetail[] | earnings[] {itemCode, itemDescription, checkDollars, checkHours, checkUnits, ytd*, isMemoEarning} | earnings[] {earning.code/name, hours (unit undocumented), base_rate, quantity, ee_amount} |
| Taxes | employeeTax[] {empTaxDeductCode, empTaxableAmount, empTaxAmount}; companyTax[] (employer) | taxes[] {itemCode, checkDollars, checkTaxableWages, isEmployeeTax} | taxes[] {company_tax.code/name, ee_amount, er_amount, ee_subject_wage…} |
| Deductions | deduction[] {deductCode, deductAmount, deductType, planId}; otherDeduction[] | deductions[] {itemCode, checkDollars}; garnishments[] | deductions[] {deduction.code/name, ee_amount, er_amount} |
| Benefits / ER | benefit[] {planId, empContrib, empDeduct, premiumAmt}; employerContributions[] {code, amount}; retirement{…} | benefits[] {benefitTitle, checkEmployeeDeduction, checkEmployerContribution} | deductions[].er_amount |
| Deposits | directDeposit[] {accountNum, amount} | directDeposits[] {account, depositAmount} | payments[] |
| Voids | voidDate, voidVoucherId, type | reissueCheckNumber/Date, checkTypeDescription | status INVALID |

---

## Cross-cutting findings that drive design

1. **Hierarchy differs** — Prism client ≈ isolved legal company ≈ UKG company/EIN.
2. **Code evidence is very uneven.** PrismHR documents letter codes in field
   descriptions (not enums); UKG has real JSON-schema enums for many fields;
   isolved returns *descriptions* (e.g. account type, DD status, pay type) whose
   values are not listed anywhere in the contract. Mappers must keep the raw value
   and fall back to `UNKNOWN`/`OTHER` with a diagnostic rather than guess.
3. **Tenant-configured codes** (Prism status/type/pay/deduction codes, isolved pay
   items, UKG earning/deduction codes) are not universal — canonical categories are
   only assigned where the provider gives a typed signal (Prism `deductionType`,
   UKG enum, isolved `payItemType`), otherwise `OTHER` + raw code.
4. **Units.** Prism `salary` is *per pay period* (field doc), not annual. UKG
   compensation has explicit `amount_period`. UKG `standard_work_day` and
   `compensations[].time` are milliseconds (documented). UKG pay-statement
   `hours` has **no documented unit** (integer) — not converted without evidence.
5. **Missing data types:** UKG pay statements have no gross/net/check totals; UKG
   employee deduction list has no amounts (detail endpoint does); isolved checks
   have no explicit payroll-run id; isolved direct deposits and PrismHR ACH have
   no effective dates; PrismHR ACH vouchers have no id.
6. **PII masking.** PrismHR masks SSN/DOB/account numbers by default; isolved only
   returns SSN on `*WithSSN` endpoints. Canonical model should store only masked
   identifiers (last 4).

---

## Live demo validation (2026-10-12)

Read-only calls against the organizer's demo tenants (PrismHR client 132,
isolved client 4046 / legals 5797 + 5806, UKG company 33704016). Raw responses
were inspected locally and **not** committed. What they confirmed or contradicted:

### Contract drift (live ≠ spec)

| Provider | Spec says | Live returns | Handling |
|---|---|---|---|
| PrismHR | `getPayrollVouchers` → `payrollVouchers[]` | `payrollVoucher[]` | adapter accepts both keys |
| PrismHR | `person.employerIds`, `person.autoPolicies` | `person.employerId`, `person.autoPolicy` | accept both |
| PrismHR | errors via HTTP status | HTTP 200 with `errorCode != "0"` (bad option → 400 + body) | check `errorCode` |
| PrismHR | `getEmployee` contact data | only returned with option `ContactInformation` (not listed in field schema) | request that option |
| isolved | employee/check lists are `PagedModelItemListOf…` envelopes (documented; an early flattening pass missed it) | same `{results, totalItems, totalPages, nextPageUrl}` | not drift — follow pages |
| isolved | — | `GET …/directdeposits` with no accounts → **404 empty body** | treat as empty list |
| UKG | base path | live base is `{base_url}/rest/v2/companies/{cid}` | — |
| UKG | `GET /employees/{aid}/deductions` documented | **404 "Unresolvable URL"** on live tenant | employee deduction setup unavailable; deductions come from pay statements only |
| UKG | pay statement has `deductions[].deduction.code/name` | also `deduction.id`, `ee_gross_wage`…; `calcUpto`, `emptyEarning` extras | ignore extras |

### Semantics confirmed

* **PrismHR `compensation.salary` is per pay period**: weekly 400.00 → `annualPay`
  20,800 (×52); monthly 50,000 → 600,000 (×12). `hourlyPayRate` is expressed in
  `hourlyPayPeriod` units (H/W/S/M). `annualPay` is the provider's own annualisation.
* **PrismHR voucher net**: `netPay = totalEarnings − otherEarnAmount(FRINGE) − Σ empTaxAmount − Σ deductAmount`.
  FRINGE "other earnings" are imputed (taxable, not paid). `checkAmt` is 0 when paid
  fully by direct deposit, so `netPay` is the authoritative net.
* **PrismHR DD**: live values `accountType` S/C, `method` B (balance) / F (fixed),
  status D; voucher DD status is composite `"D*C"` / `"D*S"` (status*accountType).
* **PrismHR codes seen**: `statusClass` A, `typeClass` F, `employeeType` FT,
  `maritalStatus` S/M/O/'' (O = Other per `Person` schema; '' = not set), gender F/M, `payMethod` S/H,
  `batchStatus` COMP, voucher `status` PRNT, `deductionType` K/KE/KC/KR/KCR/V/C.
* **isolved `payFrequency` = pay periods per year** (12 Monthly, 24 semi-monthly
  "Salary" group, 26 Biweekly, 52 Weekly; one record shows **23** — anomaly).
  `annualSalary = perPaySalary × payFrequency`; hourly `perPaySalary = hourlyRate × normalHours`.
* **isolved values seen**: employmentStatus Active/Inactive; payType Salary/Hourly/1099;
  gender Male/Female; maritalStatus Married/Single; DD accountType Checking/Savings,
  status Active, frequency "Every Pay"; payItemType Earning/Deduction/Memo Calc;
  `systemBenefitType` (401(k), Medical/Dental/Vision Pre-Tax 125, FSA Medical, FSA
  Dependent Care, Health Savings Account, Group Term Life, Leave Accrual).
* **isolved DD**: `sequenceNumber 0` with null amount/percent = **net remainder**;
  sequence ≥1 carries amount or percent (e.g. 30.0 = 30 %).
* **isolved check math**: `grossPay` = Σ non-memo earnings (cash);
  `grossWages = grossPay + imputed (GTL)`; memo earnings ("401k Match", "ER Dental")
  are employer contributions; `netPay = grossPay − Σ taxes[isEmployeeTax] − Σ deductions`.
* **isolved check → run link**: check has no run id, but `(legal, checkDate,
  payrollRunNumber)` matches run history `(payDate, runNumber)`. Run history mixes
  "Completed Payroll Run" with scheduled "Payroll Not Processed" rows.
* **UKG units**: `compensations[].time` 7,488,000,000 ms = 2080 h/yr; pay-statement
  `earnings[].hours` 144,000,000 = **40 h in milliseconds** (OT: 40 h × 94.8269 × 1.5 = 5,689.61).
* **UKG pay statement math**: gross = Σ earnings.ee_amount; net = gross − Σ taxes.ee_amount
  − Σ deductions.ee_amount = Σ payments.ee_amount (5,978.50 ✓). `er_amount` on
  deductions = employer contribution (401k match); on taxes = employer tax.
* **UKG sentinels**: compensation `effective_from 1900-12-31` with amount 0 (placeholder
  row); DD `active_to 2099-12-31` (open-ended). Pay/employee type are ids resolved
  via `lookup/pay-types` (Hourly/Salaried) and `lookup/employee-types`
  (FT Exempt, FT Non-Exempt, PT Hourly, Temp, Consultant).
* **UKG PII**: `social_security` / `national_id_numbers[].value` are **unmasked** →
  canonical masks to last 4.
* **UKG EINs**: `lookup/eins` returned only "Primary EIN", but payrolls/employees
  also reference "2nd EIN" (id 35419521) — EIN list must be unioned from payrolls/employees.
* **UKG payroll status**: all 49 demo payrolls are `OPEN` (none finalized).

### End-to-end live runs (`python -m normalization fetch … --normalize`, 2026-10-12)

Running the full fetch → normalise pipeline against the demo tenants surfaced
further behaviour the specs do not describe; each is now handled in the adapters
and mirrored in the fixtures where relevant:

| Provider | Observation | Handling |
|---|---|---|
| PrismHR | `totalEarnings` includes **reported tips** (`TIPS` earning) that are taxed but not paid; `earnAmount` is the cash figure (net reconciles from it) — same pattern as FRINGE other-earnings | cash gross = first of `earnAmount` / `totalEarnings − otherEarnAmount` / `totalEarnings` that reconciles to `netPay`; the lines explaining the difference are marked `is_cash=false` |
| PrismHR | live batch statuses `INITFAIL`, `TS.READY`, `INITCOMP`, `TSOKCOMP`, `COMP` (undocumented) | mapped by name (FAILED, OPEN, PROCESSING, OPEN, COMPLETED) and labelled as inferred |
| isolved | `GET …/employees/{id}/payItems` returns the **whole client catalog**; non-enrolled items have negative ids, no dates and all-zero calc params | treated as "not enrolled" and skipped (INFO issue with the count) |
| isolved | legal-level check list (even `includeDetails=true`) returns **`taxes: []`**; per-check detail has them | employee tax total derived as gross − deductions − net (PROVIDER_GAP); fetcher pulls detail for the latest N checks |
| isolved | check list pages with the documented 0-based **`filter.page`**; its `nextPageUrl` appends an ignored `page=` parameter, so following it returns page 0 repeatedly (found by the duplicate-id check: 600 records, 430 real) | fetcher pages with `filter.page` up to `totalPages`; adapter drops records repeated across pages (ANOMALY warning); a canonical id produced twice is an ERROR |
| isolved | check list returns **404 when the date window has no checks**; demo's processed checks are all 2018 | 404 = empty; `fetch --days` widens the window |
| isolved | `grossPay` excludes non-taxable reimbursements (e.g. "Mileage") present in earnings | difference equal to reimbursement lines is expected (INFO), not a mismatch |
| isolved | values `maritalStatus` "Chose not to answer", `payType` "Guarantee" | NOT_DISCLOSED (new canonical value), PayType OTHER |
| UKG | imputed earnings are typed: `type_name` **"Earning (Fringe, Auto)"** | provider flag used before name heuristics |
| UKG | in this tenant **payments include fringe earnings** (net = Σ all earnings − taxes − deductions) | cash reading chosen by reconciliation against `payments` |
| UKG | `national_id_numbers[].type` **NO_ID_NEEDED** (documented enum) | no national id recorded |
| UKG | pay statements carry provider messages ("Missing company bank settings.", "Live check payment settings are disabled.") | surfaced as ANOMALY warnings |

### Full employee data (live check, 2026-10-12)

| Provider | Extra source | Live result | Where it lands |
|---|---|---|---|
| PrismHR | `getEmployee` with all 14 options | accepted; returns `employeeEvents`, `health`, `skillsAndEducation`, `hsa`, `newHireQuestions`, `enrollmentInProgress`, `benefitEnrollmentCompleted`, `absenceJournalId` (empty blocks still returned) | `provider_fields` (empty blocks skipped) |
| isolved | `GET …/employees/{id}` with `includeMiscFields/MiscDataSets/Labors/Organizations/I9Details/AlternateRates/Taxes` | ~23 fields absent from the list: `taxes` (federal/state withholding), `protectedVeteran`, `militaryStatus`, `disabled…`, `tobaccoUse`, `assignedSupervisor`, `jobEeoCategory`, `acaEmploymentStatus`, `i9Documents`, `payRates` … | detail supersedes list record; extras in `provider_fields` (blobs scrubbed) |
| isolved | `…/salaries`, `…/statuses` | salary rows with pay type, frequency, change reason; status spells with effective/end dates | `compensation_history`; `provider_fields.employment_status_history` |
| UKG | `…/profiles`, `…/tax-info`, `…/hr-custom-fields`, `…/contacts` | profile assignments (1900-12-31 effective dates), W2/1099 tax type, custom fields, emergency/dependent contacts | `provider_fields` (contact permission flags dropped) |
