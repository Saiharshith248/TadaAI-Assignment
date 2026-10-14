# Canonical model

This describes the canonical model I designed and how each provider's values map
into it. The code is in [`src/normalization/canonical/`](../src/normalization/canonical/)
and the JSON Schema is
[`schemas/canonical-bundle.schema.json`](../schemas/canonical-bundle.schema.json).

## Shape

```
NormalizedBundle (one provider pull)
├── companies[]        Company            ← legal employer (PrismHR client, isolved legal, UKG EIN)
├── employees[]        Employee           → company_id
├── direct_deposits[]  DirectDeposit      → employee_id, company_id
├── deductions[]       DeductionSetup     → employee_id, company_id
├── payroll_runs[]     PayrollRun         → company_id
├── paychecks[]        Paycheck           → employee_id, company_id, payroll_run_id
│     ├── earnings[] / taxes[] / deductions[] / employer_contribution_lines[] / deposits[]
└── issues[]           bundle-level diagnostics (e.g. unresolved links)
```

Every record has these fields:

| Field | Purpose |
|---|---|
| `id` | `provider:scope:kind:source_id`, e.g. `isolved:5797:employee:859112`. The scope is the level where the provider's id is unique, so ids don't collide across tenants or providers. |
| `source` | The provider, scope, endpoint/object and the provider's own id. This is the trail back to the source. |
| `issues[]` | `{severity, code, field, message, raw_value}`: why something is UNKNOWN, derived, converted or suspicious. |
| `provider_fields` | Provider fields that have no canonical field, kept as they are (sensitive values masked). |

Every code-mapped field is `Coded{value, raw, description}`, which is the
canonical enum plus the provider's value unchanged. Money is `Decimal` (a JSON
string), dates are ISO `YYYY-MM-DD`, and SSNs and bank account numbers are only
kept as `last4`.

## Canonical "company" = legal employer

| Provider | Company record | `parent_id` |
|---|---|---|
| PrismHR | client (`clientMaster`), which already has the FEIN | none |
| isolved | legal company (`/legals/{id}`, has FEIN) | isolved client |
| UKG Ready | EIN (`lookup/eins`, `ein` on payrolls/employees) | UKG company (`cid`) |

## Code mappings (source → canonical)

Values that are not listed map to `UNKNOWN` (or `OTHER` where noted) with an
`UNMAPPED_CODE` warning. The raw value is always kept.

### Employment status
| Canonical | PrismHR `client.statusClass` | isolved `employmentStatus` | UKG `status` |
|---|---|---|---|
| ACTIVE | A | Active | Active |
| ON_LEAVE | L | Leave / On Leave | - |
| INACTIVE | - | Inactive | Inactive |
| TERMINATED | T | Terminated | Terminated |
| PENDING | - | `isPending=true` | - |

PrismHR `employeeStatus` is a tenant code and is kept raw. `statusClass` is the documented class.

### Employment type
| Canonical | PrismHR `typeClass` | isolved `employmentCategoryCode` | UKG `employee_type` (lookup name) |
|---|---|---|---|
| FULL_TIME | F | FT | name starts "FT" / "Full" |
| PART_TIME | P | PT | name starts "PT" / "Part" |
| TEMPORARY | - | - | "Temp…" |
| SEASONAL | - | `jobIsSeasonal` | - |
| CONTRACTOR | `employee1099=true` | payType "1099" | "Consultant" / "Contractor" |

UKG employee types are tenant lookups. Matching on the lookup name is a guess
(`CODE_HEURISTIC`) and is flagged as one.

### Pay type / frequency
| Canonical PayType | PrismHR `payMethod` | isolved `payType` | UKG `pay_type` lookup |
|---|---|---|---|
| SALARY | S | Salary | Salaried |
| HOURLY | H | Hourly | Hourly |
| COMMISSION | C | - | - |
| CONTRACTOR | - | 1099 | - |
| OTHER | D (driver) | - | - |

| Canonical PayFrequency | periods/yr | PrismHR `payPeriod` | isolved `payFrequency` (int) | UKG `num_pp_in_year` |
|---|---|---|---|---|
| WEEKLY | 52 | W | 52 | 52 |
| BIWEEKLY | 26 | B | 26 | 26 |
| SEMIMONTHLY | 24 | S | 24 | 24 |
| MONTHLY | 12 | M | 12 | 12 |
| QUARTERLY | 4 | Q | 4 | 4 |
| ANNUAL | 1 | A | 1 | 1 |
| DAILY | 260 | D | - | - |
| OTHER | n | - | any other n (e.g. 23 → ANOMALY issue) | - |

### Compensation amounts
| Provider | `rate` / `rate_period` | `annual_amount` | `hourly_rate` |
|---|---|---|---|
| PrismHR | salaried: `salary` / PAY_PERIOD (documented "pay rate associated with the pay period"); hourly: `hourlyPay` / HOUR | `annualPay` | `hourlyPay` |
| isolved | salaried: `perPaySalary` / PAY_PERIOD; hourly: `hourlyRate` / HOUR | `annualSalary` | `hourlyRate` (0 → null) |
| UKG | `amount` / `amount_period` (YEAR, MONTH, WEEK, HOUR, PAY_PERIOD) | `amount` if YEAR, else derived | `hourly_pay` |

UKG `standard_work_day` and `compensations[].time` are in milliseconds (documented), and are converted to hours.

### Gender / marital status
| Canonical | PrismHR | isolved | UKG |
|---|---|---|---|
| MALE / FEMALE | M / F | Male / Female | MALE / FEMALE |
| NON_BINARY | X | Non-Binary… | - |
| NOT_DISCLOSED | D | - | UNDEFINED |
| SINGLE/MARRIED/DIVORCED/WIDOWED | S/M/D/W | Single/Married/Divorced/Widowed | - |
| CIVIL_UNION / OTHER | C / O | - | - |
| NOT_DISCLOSED (marital) | - | Chose not to answer | - (UKG exposes no marital status) |

### Direct deposit
| Canonical | PrismHR `achVoucher` | isolved | UKG |
|---|---|---|---|
| account CHECKING | `accountType` C (doc: "checking account or pay card") | Checking | CHECKING |
| account SAVINGS | S | Savings | SAVINGS |
| account OTHER | IP (instant pay) | - | - |
| method FIXED_AMOUNT | F, FS (skip-if-short kept in raw) | `amount` set | FLAT_AMOUNT |
| method PERCENT | P (basis NET_PAY), PN (basis REMAINING_NET) | `percent` set (basis NET_PAY) | NET_PAY, GROSS_EARNING (GROSS_PAY), DIRECT_DEPOSIT_PER_OF_REMAINDER (REMAINING_NET) |
| method REMAINDER | B | `sequenceNumber 0` with no amount/percent | FULL |
| status ACTIVE | D (and record `achStatus` A) | Active | `active=true` |
| status PRENOTE | P | Prenote… | `pre_note_status` READY_TO_SEND / SENT |
| status INACTIVE | I, or record `achStatus` I | Inactive | `active=false` |

Priority: PrismHR uses the array order, isolved uses `sequenceNumber` (0 means
remainder, so it is sorted last), and UKG uses `sequence`. A UKG `active_to` of
`2099-12-31` means open-ended (stored as null, with a SENTINEL_VALUE info note).

### Deduction category
| Canonical | PrismHR `deductionType` (typed) | isolved `systemBenefitType` (typed) | UKG (code/name heuristic) |
|---|---|---|---|
| RETIREMENT, PRE_TAX | K | 401(k) | 401k, 403b, 457 |
| RETIREMENT, PRE_TAX, catch-up | KC | - | "catch" |
| RETIREMENT, ROTH | KR, KCR (catch-up) | "Roth" in pay item | "roth" |
| RETIREMENT, POST_TAX | KE | - | - |
| RETIREMENT_LOAN | KL | "401K Loan" | "loan" + 401k |
| HEALTH_BENEFIT, PRE_TAX | C (Section 125) | Medical/Dental/Vision Pre-Tax 125 → MEDICAL/DENTAL/VISION | medical/dental/vision |
| FSA / DEPENDENT_CARE_FSA | F | FSA Medical / FSA Dependent Care | fsa |
| HSA | - | Health Savings Account | hsa |
| GARNISHMENT | G | garnishments endpoint | garnish, child support, levy |
| LOAN | L | - | loan |
| POST_TAX benefit | P | - | - |
| VOLUNTARY | V | - | - |

PrismHR `voluntaryClassifications` booleans (from `getDeductionCodeDetails`) make
the V/C codes more specific when they are available. Name-based guesses are marked
`category_basis: CODE_HEURISTIC`.

### Payroll run type / status, paycheck status
| Canonical | PrismHR batch `batchType` / voucher `type` | isolved `payrollRunType` | UKG `type.display_name` |
|---|---|---|---|
| REGULAR | R | Regular Payroll | Regular |
| SUPPLEMENTAL | S (special/supplemental), V voucher (vacation) | Supplemental… | Bonus/Supplemental |
| MANUAL | M | Manual… | - |
| ADJUSTMENT | J (voucher) | Adjustment (check type) | Adjustment |
| REVERSAL | V (batch void) | Void… | - |
| CONVERSION | - | Data Conversion | - |

| Canonical run status | PrismHR `batchStatus` | isolved `status` | UKG `status` |
|---|---|---|---|
| COMPLETED | COMP | Completed Payroll Run | FINALIZED |
| PROCESSING | INITCOMP* | - | CLOSED, SUBMITTED |
| OPEN | TS.READY*, TSOKCOMP* | - | NEW, OPEN |
| FAILED | INITFAIL* | - | *_FAILED |
| SCHEDULED | - | Payroll Not Processed | - |

PrismHR batch statuses are only described as "the processing status". A * means I
saw it live and mapped it from the status name (labelled as inferred). Any other
value becomes UNKNOWN with a warning.

### Taxes
`tax_type` is worked out from the code and description:

- FIT or "Federal Income" gives FEDERAL_INCOME
- Soc Sec or OASDI gives SOCIAL_SECURITY
- Medicare gives MEDICARE (Additional Medicare gives ADDITIONAL_MEDICARE)
- FUTA or "Fed Unemployment" gives FEDERAL_UNEMPLOYMENT
- SUI, SUTA or "Unemployment" gives STATE_UNEMPLOYMENT
- SDI, PFML or FLI gives STATE_DISABILITY
- "SIT", "<State> Income" or "<STATE> WH" gives STATE_INCOME
- city, local or CIWT gives LOCAL_INCOME

`payer` comes from PrismHR `employeeTax` vs `companyTax`, isolved
`isEmployeeTax`, and UKG `ee_amount` vs `er_amount` (one UKG line can give both).

## Paycheck totals

| Provider | gross_pay (cash) | gross_wages | net_pay | totals_basis |
|---|---|---|---|---|
| PrismHR | first of `earnAmount`, `totalEarnings − otherEarnAmount`, `totalEarnings` that reconciles to `netPay` | `totalEarnings` | `netPay` | PROVIDER |
| isolved | `grossPay` (excludes GTL and non-taxable reimbursements) | `grossWages` | `netPay` | PROVIDER (DERIVED when the list response omits taxes) |
| UKG | Σ earnings, excluding fringe unless `payments` show it was paid | Σ earnings | Σ `payments`, else gross − EE taxes − EE deductions | DERIVED |

Every paycheck is checked again (`gross − employee taxes − employee deductions =
net`) and gets `TOTALS_MISMATCH` if it is off by more than one cent. The reasoning
and the live evidence are in
[DECISIONS.md §4](DECISIONS.md#4-paycheck-totals-cash-vs-non-cash).
