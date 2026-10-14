"""Canonical enums shared by every provider adapter.

Every enum that is filled from a provider code carries ``UNKNOWN`` (the source
value was absent or not recognised) and, where a meaningful bucket exists,
``OTHER`` (the source value is recognised but has no canonical equivalent).
The raw provider value is always kept next to the canonical one (see
``Coded`` in ``models.py``), so an ``UNKNOWN`` never loses information.
"""
from enum import Enum


class _StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


class Provider(_StrEnum):
    PRISMHR = "prismhr"
    ISOLVED = "isolved"
    UKG_READY = "ukg-ready"


class Severity(_StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class IssueCode(_StrEnum):
    UNMAPPED_CODE = "UNMAPPED_CODE"          # provider value not in our mapping table
    MISSING_REQUIRED = "MISSING_REQUIRED"    # field needed for the canonical record is absent
    INVALID_VALUE = "INVALID_VALUE"          # value present but unparseable (date, number…)
    DERIVED_VALUE = "DERIVED_VALUE"          # canonical value computed, not read directly
    UNIT_CONVERTED = "UNIT_CONVERTED"        # unit conversion applied with documented evidence
    TOTALS_MISMATCH = "TOTALS_MISMATCH"      # provider totals disagree with line items
    SENTINEL_VALUE = "SENTINEL_VALUE"        # placeholder such as 1900-12-31 / 2099-12-31
    UNRESOLVED_REFERENCE = "UNRESOLVED_REFERENCE"  # link to another record could not be made
    PROVIDER_GAP = "PROVIDER_GAP"            # provider does not expose this data
    ANOMALY = "ANOMALY"                      # value is valid but suspicious


# ---------------------------------------------------------------- company
class CompanyStatus(_StrEnum):
    ACTIVE = "ACTIVE"
    PENDING = "PENDING"
    INACTIVE = "INACTIVE"
    TERMINATING = "TERMINATING"   # PrismHR 'C' (client cancelling, pre-termination)
    TERMINATED = "TERMINATED"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------- employee
class EmploymentStatus(_StrEnum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"         # isolved "Inactive": not terminated, not working
    TERMINATED = "TERMINATED"
    PENDING = "PENDING"           # pending hire / onboarding
    UNKNOWN = "UNKNOWN"


class EmploymentType(_StrEnum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    TEMPORARY = "TEMPORARY"
    SEASONAL = "SEASONAL"
    CONTRACTOR = "CONTRACTOR"     # 1099 / consultant
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class FlsaStatus(_StrEnum):
    EXEMPT = "EXEMPT"
    NON_EXEMPT = "NON_EXEMPT"
    UNKNOWN = "UNKNOWN"


class Gender(_StrEnum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    NON_BINARY = "NON_BINARY"     # PrismHR 'X'
    NOT_DISCLOSED = "NOT_DISCLOSED"  # PrismHR 'D' (declined), UKG UNDEFINED
    UNKNOWN = "UNKNOWN"


class MaritalStatus(_StrEnum):
    SINGLE = "SINGLE"
    MARRIED = "MARRIED"
    DIVORCED = "DIVORCED"
    WIDOWED = "WIDOWED"
    SEPARATED = "SEPARATED"
    CIVIL_UNION = "CIVIL_UNION"
    NOT_DISCLOSED = "NOT_DISCLOSED"   # isolved "Chose not to answer"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class NationalIdType(_StrEnum):
    SSN = "SSN"
    ITIN = "ITIN"
    SIN = "SIN"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------- compensation
class PayType(_StrEnum):
    SALARY = "SALARY"
    HOURLY = "HOURLY"
    COMMISSION = "COMMISSION"
    CONTRACTOR = "CONTRACTOR"     # isolved pay type "1099"
    OTHER = "OTHER"               # e.g. PrismHR 'D' driver pay
    UNKNOWN = "UNKNOWN"


class PayFrequency(_StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    SEMIMONTHLY = "SEMIMONTHLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class RatePeriod(_StrEnum):
    """The unit a pay *rate* is expressed in (not how often the employee is paid)."""
    HOUR = "HOUR"
    DAY = "DAY"
    WEEK = "WEEK"
    BIWEEK = "BIWEEK"
    SEMIMONTH = "SEMIMONTH"
    MONTH = "MONTH"
    YEAR = "YEAR"
    PAY_PERIOD = "PAY_PERIOD"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------- direct deposit
class BankAccountType(_StrEnum):
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"
    PAY_CARD = "PAY_CARD"
    OTHER = "OTHER"               # e.g. PrismHR 'IP' instant pay
    UNKNOWN = "UNKNOWN"


class AllocationMethod(_StrEnum):
    FIXED_AMOUNT = "FIXED_AMOUNT"
    PERCENT = "PERCENT"
    REMAINDER = "REMAINDER"       # receives whatever is left (PrismHR 'B', isolved seq 0, UKG FULL)
    UNKNOWN = "UNKNOWN"


class PercentBasis(_StrEnum):
    """What a percentage allocation is a percentage *of*."""
    NET_PAY = "NET_PAY"
    GROSS_PAY = "GROSS_PAY"
    REMAINING_NET = "REMAINING_NET"   # net left after fixed allocations
    UNKNOWN = "UNKNOWN"


class DirectDepositStatus(_StrEnum):
    ACTIVE = "ACTIVE"
    PRENOTE = "PRENOTE"           # pre-notification / verification pending
    INACTIVE = "INACTIVE"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------- deductions
class DeductionCategory(_StrEnum):
    RETIREMENT = "RETIREMENT"             # 401(k)/403(b)/457/pension contributions
    RETIREMENT_LOAN = "RETIREMENT_LOAN"
    MEDICAL = "MEDICAL"
    DENTAL = "DENTAL"
    VISION = "VISION"
    HEALTH_BENEFIT = "HEALTH_BENEFIT"     # section 125 / health plan, line not specific
    LIFE_DISABILITY = "LIFE_DISABILITY"
    FSA = "FSA"
    DEPENDENT_CARE_FSA = "DEPENDENT_CARE_FSA"
    HSA = "HSA"
    COMMUTER = "COMMUTER"                 # section 132
    GARNISHMENT = "GARNISHMENT"
    LOAN = "LOAN"                         # non-retirement employee loan
    UNION_DUES = "UNION_DUES"
    CHARITY = "CHARITY"
    VOLUNTARY = "VOLUNTARY"               # provider says voluntary, nothing more specific
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class TaxTreatment(_StrEnum):
    PRE_TAX = "PRE_TAX"
    POST_TAX = "POST_TAX"
    ROTH = "ROTH"                         # post-tax with qualified tax-free withdrawal
    UNKNOWN = "UNKNOWN"


class DeductionCalcMethod(_StrEnum):
    FIXED_AMOUNT = "FIXED_AMOUNT"
    PERCENT = "PERCENT"
    RATE_PER_HOUR = "RATE_PER_HOUR"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class DeductionKind(_StrEnum):
    RECURRING = "RECURRING"
    ONE_TIME = "ONE_TIME"
    GARNISHMENT = "GARNISHMENT"
    UNKNOWN = "UNKNOWN"


class DeductionStatus(_StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SCHEDULED = "SCHEDULED"       # start date in the future
    ENDED = "ENDED"               # stop date in the past
    UNKNOWN = "UNKNOWN"


class LimitPeriod(_StrEnum):
    PAY_PERIOD = "PAY_PERIOD"
    MONTH = "MONTH"
    QUARTER = "QUARTER"
    YEAR = "YEAR"
    LIFETIME = "LIFETIME"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------- payroll
class PayrollType(_StrEnum):
    REGULAR = "REGULAR"
    SUPPLEMENTAL = "SUPPLEMENTAL"   # special / bonus / off-cycle
    MANUAL = "MANUAL"
    ADJUSTMENT = "ADJUSTMENT"
    REVERSAL = "REVERSAL"           # void / reversal
    CONVERSION = "CONVERSION"       # historical data load (isolved "Data Conversion")
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class PayrollRunStatus(_StrEnum):
    SCHEDULED = "SCHEDULED"         # on the calendar, not processed
    OPEN = "OPEN"                   # being prepared / editable
    PROCESSING = "PROCESSING"       # submitted, not final
    COMPLETED = "COMPLETED"         # processed / finalized / posted
    FAILED = "FAILED"
    VOIDED = "VOIDED"
    UNKNOWN = "UNKNOWN"


class PaycheckStatus(_StrEnum):
    ISSUED = "ISSUED"
    PENDING = "PENDING"             # in an open / unfinalized payroll
    VOIDED = "VOIDED"
    UNKNOWN = "UNKNOWN"


class PaymentMethod(_StrEnum):
    CHECK = "CHECK"
    DIRECT_DEPOSIT = "DIRECT_DEPOSIT"
    MIXED = "MIXED"
    NONE = "NONE"                   # zero net
    UNKNOWN = "UNKNOWN"


class EarningCategory(_StrEnum):
    REGULAR = "REGULAR"
    OVERTIME = "OVERTIME"
    DOUBLE_TIME = "DOUBLE_TIME"
    HOLIDAY = "HOLIDAY"
    PTO = "PTO"                     # vacation / sick / personal
    BONUS = "BONUS"
    COMMISSION = "COMMISSION"
    TIPS = "TIPS"
    REIMBURSEMENT = "REIMBURSEMENT"
    IMPUTED_INCOME = "IMPUTED_INCOME"   # taxable, non-cash (GTL, fringe)
    SEVERANCE = "SEVERANCE"
    CONTRACTOR = "CONTRACTOR"       # 1099 non-employee compensation
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class ClassificationBasis(_StrEnum):
    """How a category was assigned — lets consumers judge confidence."""
    PROVIDER_TYPE = "PROVIDER_TYPE"         # typed provider field (e.g. PrismHR deductionType)
    PROVIDER_FLAG = "PROVIDER_FLAG"         # provider boolean (e.g. isolved isMemoEarning)
    CODE_HEURISTIC = "CODE_HEURISTIC"       # keyword match on tenant-configured code/name
    UNCLASSIFIED = "UNCLASSIFIED"


class TaxType(_StrEnum):
    FEDERAL_INCOME = "FEDERAL_INCOME"
    SOCIAL_SECURITY = "SOCIAL_SECURITY"
    MEDICARE = "MEDICARE"
    ADDITIONAL_MEDICARE = "ADDITIONAL_MEDICARE"
    FEDERAL_UNEMPLOYMENT = "FEDERAL_UNEMPLOYMENT"
    STATE_INCOME = "STATE_INCOME"
    STATE_UNEMPLOYMENT = "STATE_UNEMPLOYMENT"
    STATE_DISABILITY = "STATE_DISABILITY"     # SDI / PFML / FLI
    LOCAL_INCOME = "LOCAL_INCOME"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class TaxPayer(_StrEnum):
    EMPLOYEE = "EMPLOYEE"
    EMPLOYER = "EMPLOYER"
    UNKNOWN = "UNKNOWN"


class TotalsBasis(_StrEnum):
    PROVIDER = "PROVIDER"           # totals read from provider fields
    DERIVED = "DERIVED"             # computed from line items (provider gives none)
