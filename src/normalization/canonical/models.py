"""Canonical, provider-neutral records.

Design rules (rationale in docs/DECISIONS.md):

* Every record has a stable ``id`` (``provider:scope:kind:source_id``), a
  ``source`` pointer back to the provider record, and its own ``issues`` list.
* Every value mapped from a provider code is a ``Coded[...]``: canonical enum +
  the untouched raw value, so mappings are auditable and never lossy.
* Money is ``Decimal`` (serialised as a string in JSON) — never float.
* Dates are ``date`` (no time component); providers that send datetimes for
  calendar dates are truncated by the adapters.
* Provider fields that have no canonical home are preserved verbatim in
  ``provider_fields`` so "all available employee fields" survive normalisation.
* Sensitive identifiers (SSN, bank account numbers) are stored masked only.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    AllocationMethod, BankAccountType, ClassificationBasis, CompanyStatus,
    DeductionCalcMethod, DeductionCategory, DeductionKind, DeductionStatus,
    DirectDepositStatus, EarningCategory, EmploymentStatus, EmploymentType,
    FlsaStatus, Gender, IssueCode, LimitPeriod, MaritalStatus, NationalIdType,
    PaycheckStatus, PaymentMethod, PayFrequency, PayrollRunStatus, PayrollType,
    PayType, PercentBasis, Provider, RatePeriod, Severity, TaxPayer,
    TaxTreatment, TaxType, TotalsBasis,
)

E = TypeVar("E")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ------------------------------------------------------------------ building blocks
class Coded(_Model, Generic[E]):
    """A canonical enum value plus the raw provider value it came from."""
    value: E
    raw: Optional[str] = None
    description: Optional[str] = Field(None, description="Provider's label for the raw value, if any")


class Issue(_Model):
    severity: Severity
    code: IssueCode
    field: Optional[str] = Field(None, description="Canonical field path the issue concerns")
    message: str
    raw_value: Optional[Any] = None


class SourceRef(_Model):
    provider: Provider
    scope: str = Field(description="Provider tenant/company scope the source id is unique within")
    record_type: str = Field(description="Provider endpoint/object the record came from")
    source_id: Optional[str] = None


class Address(_Model):
    line1: Optional[str] = None
    line2: Optional[str] = None
    line3: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = Field(None, description="State/province code as supplied (US: 2-letter)")
    postal_code: Optional[str] = None
    county: Optional[str] = None
    country: Optional[str] = Field(None, description="ISO 3166-1 alpha-3 when known, else as supplied")


class Phone(_Model):
    type: str = Field(description="home | mobile | work | fax | other")
    number: str
    extension: Optional[str] = None


class Email(_Model):
    type: str = Field(description="personal | work | other")
    address: str


class NationalId(_Model):
    type: Coded[NationalIdType]
    last4: Optional[str] = Field(None, description="Only the last four digits are retained")


class PersonName(_Model):
    first: Optional[str] = None
    middle: Optional[str] = None
    last: Optional[str] = None
    preferred: Optional[str] = None
    prefix: Optional[str] = None
    suffix: Optional[str] = None


class Record(_Model):
    id: str
    source: SourceRef
    issues: List[Issue] = Field(default_factory=list)
    provider_fields: Dict[str, Any] = Field(
        default_factory=dict,
        description="Provider fields with no canonical home, preserved verbatim (masked if sensitive)")


# ------------------------------------------------------------------ company
class PayGroup(_Model):
    id: str
    name: Optional[str] = None
    frequency: Optional[Coded[PayFrequency]] = None
    periods_per_year: Optional[int] = None


class Company(Record):
    parent_id: Optional[str] = Field(None, description="Provider account above the legal employer (isolved client, UKG company)")
    parent_name: Optional[str] = None
    code: Optional[str] = None
    legal_name: Optional[str] = None
    dba_name: Optional[str] = None
    federal_ein: Optional[str] = Field(None, description="As supplied; may be provider-masked")
    status: Coded[CompanyStatus]
    status_date: Optional[date] = None
    service_type: Optional[str] = None
    industry_naics: Optional[str] = None
    industry_sic: Optional[str] = None
    address: Optional[Address] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    pay_groups: List[PayGroup] = Field(default_factory=list)


# ------------------------------------------------------------------ employee
class Employment(_Model):
    status: Coded[EmploymentStatus]
    status_effective_date: Optional[date] = None
    employment_type: Coded[EmploymentType]
    original_hire_date: Optional[date] = None
    hire_date: Optional[date] = Field(None, description="Start of the current employment spell")
    rehire_date: Optional[date] = None
    termination_date: Optional[date] = None
    termination_reason: Optional[str] = None
    last_worked_date: Optional[date] = None
    seniority_date: Optional[date] = None
    is_rehire_eligible: Optional[bool] = None


class Job(_Model):
    title: Optional[str] = None
    code: Optional[str] = None
    effective_date: Optional[date] = None
    flsa_status: Coded[FlsaStatus]
    department: Optional[str] = None
    division: Optional[str] = None
    location: Optional[str] = None
    cost_centers: List[str] = Field(default_factory=list)
    manager_employee_id: Optional[str] = Field(None, description="Canonical id of the manager")
    union_code: Optional[str] = None
    workers_comp_code: Optional[str] = None
    is_remote: Optional[bool] = None


class Compensation(_Model):
    """Current pay. ``rate`` + ``rate_period`` are the provider's own figure;
    ``annual_amount``/``hourly_rate`` are provider-supplied or derived (see issues)."""
    pay_type: Coded[PayType]
    pay_frequency: Coded[PayFrequency]
    periods_per_year: Optional[int] = None
    rate: Optional[Decimal] = None
    rate_period: RatePeriod = RatePeriod.UNKNOWN
    annual_amount: Optional[Decimal] = None
    hourly_rate: Optional[Decimal] = None
    standard_hours_per_period: Optional[Decimal] = None
    currency: str = "USD"
    effective_date: Optional[date] = None
    pay_group: Optional[str] = None


class CompensationChange(_Model):
    effective_date: Optional[date] = None
    rate: Optional[Decimal] = None
    rate_period: RatePeriod = RatePeriod.UNKNOWN
    annual_amount: Optional[Decimal] = None
    hourly_rate: Optional[Decimal] = None
    pay_type: Optional[Coded[PayType]] = None
    reason: Optional[str] = None
    currency: str = "USD"


class Employee(Record):
    company_id: str
    employee_number: Optional[str] = None
    external_ids: Dict[str, str] = Field(default_factory=dict)
    name: PersonName
    birth_date: Optional[date] = None
    gender: Coded[Gender]
    marital_status: Coded[MaritalStatus]
    ethnicity: Optional[str] = Field(None, description="Provider label, not normalised (code sets differ)")
    national_id: Optional[NationalId] = None
    home_address: Optional[Address] = None
    mailing_address: Optional[Address] = None
    emails: List[Email] = Field(default_factory=list)
    phones: List[Phone] = Field(default_factory=list)
    employment: Employment
    job: Job
    compensation: Optional[Compensation] = None
    compensation_history: List[CompensationChange] = Field(default_factory=list)


# ------------------------------------------------------------------ direct deposit
class DirectDeposit(Record):
    company_id: str
    employee_id: str
    priority: Optional[int] = Field(None, description="Processing order; remainder accounts last")
    account_type: Coded[BankAccountType]
    routing_number: Optional[str] = None
    account_last4: Optional[str] = None
    bank_name: Optional[str] = None
    method: Coded[AllocationMethod]
    amount: Optional[Decimal] = None
    percent: Optional[Decimal] = Field(None, description="0-100")
    percent_basis: PercentBasis = PercentBasis.UNKNOWN
    amount_limit: Optional[Decimal] = Field(None, description="Cap on a percentage allocation")
    status: Coded[DirectDepositStatus]
    prenote_status: Optional[str] = None
    effective_start: Optional[date] = None
    effective_end: Optional[date] = None
    applies_to: Optional[str] = Field(None, description="Which pay/voucher types use this account, raw")


# ------------------------------------------------------------------ deductions
class Limit(_Model):
    amount: Decimal
    period: LimitPeriod


class EmployerMatch(_Model):
    method: Coded[DeductionCalcMethod]
    amount: Optional[Decimal] = None
    percent: Optional[Decimal] = None


class DeductionSetup(Record):
    company_id: str
    employee_id: str
    code: str
    description: Optional[str] = None
    kind: DeductionKind
    category: Coded[DeductionCategory]
    category_basis: ClassificationBasis
    tax_treatment: TaxTreatment = TaxTreatment.UNKNOWN
    is_catch_up: bool = False
    calc_method: Coded[DeductionCalcMethod]
    amount: Optional[Decimal] = None
    percent: Optional[Decimal] = None
    limits: List[Limit] = Field(default_factory=list)
    frequency: Optional[str] = Field(None, description="Provider schedule/periods, raw")
    status: DeductionStatus = DeductionStatus.UNKNOWN
    start_date: Optional[date] = None
    stop_date: Optional[date] = None
    benefit_plan_id: Optional[str] = None
    payee: Optional[str] = None
    employer_match: Optional[EmployerMatch] = None


# ------------------------------------------------------------------ payroll
class PayrollRun(Record):
    company_id: str
    name: Optional[str] = None
    run_type: Coded[PayrollType]
    status: Coded[PayrollRunStatus]
    pay_date: Optional[date] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    run_date: Optional[date] = None
    run_number: Optional[int] = None
    pay_groups: List[str] = Field(default_factory=list)


class EarningLine(_Model):
    code: Optional[str] = None
    description: Optional[str] = None
    category: Coded[EarningCategory]
    category_basis: ClassificationBasis
    hours: Optional[Decimal] = None
    rate: Optional[Decimal] = None
    amount: Decimal
    is_cash: bool = Field(True, description="False for imputed/memo amounts that are not paid out")
    work_date_start: Optional[date] = None
    work_date_end: Optional[date] = None
    department: Optional[str] = None
    location: Optional[str] = None
    job_code: Optional[str] = None


class TaxLine(_Model):
    code: Optional[str] = None
    description: Optional[str] = None
    tax_type: Coded[TaxType]
    payer: TaxPayer
    jurisdiction: Optional[str] = Field(None, description="FED, a state code, or a locality label")
    amount: Decimal
    taxable_wages: Optional[Decimal] = None


class DeductionLine(_Model):
    code: Optional[str] = None
    description: Optional[str] = None
    category: Coded[DeductionCategory]
    category_basis: ClassificationBasis
    tax_treatment: TaxTreatment = TaxTreatment.UNKNOWN
    employee_amount: Decimal
    employer_amount: Optional[Decimal] = None
    benefit_plan_id: Optional[str] = None


class EmployerContributionLine(_Model):
    code: Optional[str] = None
    description: Optional[str] = None
    category: Coded[DeductionCategory]
    category_basis: ClassificationBasis
    amount: Decimal
    benefit_plan_id: Optional[str] = None


class DepositLine(_Model):
    account_last4: Optional[str] = None
    routing_number: Optional[str] = None
    account_type: Optional[Coded[BankAccountType]] = None
    amount: Decimal


class Paycheck(Record):
    company_id: str
    employee_id: str
    payroll_run_id: Optional[str] = None
    check_number: Optional[str] = None
    pay_type: Coded[PayrollType]
    status: Coded[PaycheckStatus]
    pay_date: Optional[date] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    payment_method: PaymentMethod = PaymentMethod.UNKNOWN
    gross_pay: Decimal = Field(description="Cash earnings (excludes imputed income)")
    gross_wages: Optional[Decimal] = Field(None, description="Gross incl. imputed income, when known")
    net_pay: Decimal
    employee_taxes: Decimal
    employer_taxes: Optional[Decimal] = None
    employee_deductions: Decimal
    employer_contributions: Optional[Decimal] = None
    total_hours: Optional[Decimal] = None
    totals_basis: TotalsBasis
    earnings: List[EarningLine] = Field(default_factory=list)
    taxes: List[TaxLine] = Field(default_factory=list)
    deductions: List[DeductionLine] = Field(default_factory=list)
    employer_contribution_lines: List[EmployerContributionLine] = Field(default_factory=list)
    deposits: List[DepositLine] = Field(default_factory=list)
