"""Pure Full & Final (F&F) Settlement calculation engine (no DB, no clock).

All money values are integer paise. Intermediate math uses Decimal and rounds each
line item to the nearest rupee (ROUND_HALF_UP).
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from .money import PAISE_PER_RUPEE, paise_to_rupees_str, round_paise_to_rupee_paise
from .tenure import TenureResult, calc_tenure


@dataclass(frozen=True)
class FnfSettings:
	day_basis: str = "CALENDAR"  # CALENDAR | FIXED_30 | FIXED_26
	leave_encash_divisor: int = 26
	leave_encash_wage: str = "BASIC_DA"  # BASIC_DA | GROSS
	bonus_eligibility_ceiling_paise: int = 2100000  # ₹21,000
	bonus_calc_ceiling_paise: int = 700000  # ₹7,000
	bonus_company_pct: Decimal = Decimal("8.33")
	bonus_min_working_days: int = 30
	gratuity_days: int = 15
	gratuity_divisor: int = 26
	gratuity_cap_paise: int = 200000000  # ₹20,00,000
	gratuity_permanent_min_years: int = 5
	gratuity_fixed_term_min_years: int = 1
	gratuity_round_up_months_over: int = 6
	gratuity_allow_4y240d_rule: bool = False
	pf_rate_pct: Decimal = Decimal("12")
	pf_wage_ceiling_paise: int = 1500000  # ₹15,000 monthly ceiling (optional cap)
	apply_pf_ceiling: bool = False
	esi_rate_pct: Decimal = Decimal("0.75")
	esi_eligibility_ceiling_paise: int = 2100000
	payment_due_working_days: int = 2
	working_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5)  # Mon-Sat


@dataclass(frozen=True)
class SiteRule:
	site_code: str = "STANDARD"
	include_bonus: bool = True
	include_leave: bool = True
	include_gratuity: bool = True
	bonus_on_min_wage_days: bool = False
	leave_on_actual_wage_days: bool = False


@dataclass(frozen=True)
class ManualLine:
	code: str
	line_type: str  # EARNING | DEDUCTION
	amount_paise: int
	note: str = ""


@dataclass(frozen=True)
class FnfInput:
	employee_code: str
	employment_type: str  # PERMANENT | FIXED_TERM | CONTRACT
	exit_reason: str  # RESIGNATION | RETIREMENT | END_OF_CONTRACT | TERMINATION | ABSCONDING | DEATH | OTHER
	doj: dt.date
	lwd: dt.date
	exit_date: dt.date
	# Latest / exit month salary
	basic_paise: int
	da_paise: int
	gross_paise: int
	days_worked_in_exit_month: Decimal | None = None
	days_in_exit_month: int | None = None
	# Leave
	el_balance: Decimal | None = None
	# Bonus
	fy_working_days: int | None = None
	fy_bonus_wage_paise: int | None = None  # direct total FY bonus wage if known
	fy_bonus_months: Decimal | None = None  # months worked in FY if computing from min_wage
	min_wage_monthly_paise: int | None = None
	bonus_already_paid_paise: int = 0
	bonus_eligible_override: bool | None = None
	# Statutory deductions
	deduct_pf: bool = True
	deduct_esi: bool = False
	pt_paise: int = 0
	# Client site rule & manual adjustments
	site_rule: SiteRule = field(default_factory=SiteRule)
	manual_lines: tuple[ManualLine, ...] = ()
	holidays: tuple[dt.date, ...] = ()
	nominee_summary: str = ""


@dataclass(frozen=True)
class FnfLine:
	code: str
	label: str
	line_type: str  # EARNING | DEDUCTION
	amount_paise: int
	formula_text: str
	is_manual: bool = False
	note: str = ""


@dataclass(frozen=True)
class FnfResult:
	employee_code: str
	tenure: TenureResult
	lines: tuple[FnfLine, ...]
	total_earnings_paise: int
	total_deductions_paise: int
	net_payable_paise: int
	payment_due_date: dt.date
	warnings: tuple[str, ...]
	errors: tuple[str, ...]
	has_negative_net: bool
	gratuity_payable_to_nominee: bool


def calc_payment_due_date(
	exit_date: dt.date,
	working_due_days: int = 2,
	working_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5),
	holidays: tuple[dt.date, ...] = (),
) -> dt.date:
	"""Code on Wages s.17: due within N working days after exit/resignation."""
	holiday_set = set(holidays)
	cur = exit_date
	remaining = max(0, working_due_days)
	while remaining > 0:
		cur = cur + dt.timedelta(days=1)
		if cur.weekday() in working_weekdays and cur not in holiday_set:
			remaining -= 1
	return cur


def _exit_month_divisor(lwd: dt.date, settings: FnfSettings, override_days: int | None) -> int:
	if settings.day_basis == "FIXED_30":
		return 30
	if settings.day_basis == "FIXED_26":
		return 26
	if override_days and override_days > 0:
		return override_days
	return calendar.monthrange(lwd.year, lwd.month)[1]


def calc_earned_salary(
	gross_paise: int,
	basic_paise: int,
	lwd: dt.date,
	days_worked: Decimal | None,
	days_in_month_override: int | None,
	settings: FnfSettings,
) -> tuple[FnfLine, int]:
	divisor = _exit_month_divisor(lwd, settings, days_in_month_override)
	worked = days_worked if days_worked is not None else Decimal(str(lwd.day))
	if worked > Decimal(str(divisor)) and settings.day_basis == "CALENDAR":
		worked = Decimal(str(divisor))
	if worked < Decimal("0"):
		worked = Decimal("0")

	earned_gross_dec = Decimal(gross_paise) * worked / Decimal(divisor)
	earned_gross_paise = round_paise_to_rupee_paise(earned_gross_dec)

	earned_basic_dec = Decimal(basic_paise) * worked / Decimal(divisor)
	earned_basic_paise = round_paise_to_rupee_paise(earned_basic_dec)

	worked_str = str(int(worked)) if worked == worked.to_integral_value() else str(worked)
	formula = f"{paise_to_rupees_str(gross_paise)} × {worked_str} ÷ {divisor}"
	line = FnfLine(
		code="EARNED_SALARY",
		label=f"Earned salary ({lwd.strftime('%b-%y')}, {worked_str}/{divisor} days)",
		line_type="EARNING",
		amount_paise=earned_gross_paise,
		formula_text=formula,
	)
	return line, earned_basic_paise


def calc_leave_encashment(
	el_balance: Decimal | None,
	basic_paise: int,
	da_paise: int,
	gross_paise: int,
	settings: FnfSettings,
	site_rule: SiteRule,
) -> tuple[FnfLine | None, str | None, str | None]:
	"""Return (FnfLine, warning, error)."""
	if not site_rule.include_leave:
		line = FnfLine(
			code="LEAVE_ENCASH",
			label="Leave encashment",
			line_type="EARNING",
			amount_paise=0,
			formula_text=f"Excluded by client site rule ({site_rule.site_code})",
			note=f"Excluded for {site_rule.site_code}",
		)
		return line, f"Leave encashment excluded by site rule ({site_rule.site_code})", None

	if el_balance is None:
		return None, None, "FNF_LEAVE_MISSING: No leave balance found. Upload Leave Report or enter 0 explicitly."

	if el_balance <= Decimal("0"):
		line = FnfLine(
			code="LEAVE_ENCASH",
			label="Leave encashment (0 EL)",
			line_type="EARNING",
			amount_paise=0,
			formula_text="0 EL",
		)
		return line, None, None

	wage_paise = gross_paise if settings.leave_encash_wage == "GROSS" else (basic_paise + da_paise)
	divisor = settings.leave_encash_divisor
	amount_paise = round_paise_to_rupee_paise(Decimal(wage_paise) * el_balance / Decimal(divisor))
	bal_str = str(int(el_balance)) if el_balance == el_balance.to_integral_value() else str(el_balance)
	line = FnfLine(
		code="LEAVE_ENCASH",
		label=f"Leave encashment ({bal_str} EL)",
		line_type="EARNING",
		amount_paise=amount_paise,
		formula_text=f"{paise_to_rupees_str(wage_paise)} × {bal_str} ÷ {divisor}",
	)
	return line, None, None


def _fy_months_and_fraction(doj: dt.date, lwd: dt.date) -> Decimal:
	"""Compute months worked in the exit Financial Year (April–March) using exact month fractions."""
	fy_start_year = lwd.year if lwd.month >= 4 else lwd.year - 1
	fy_start = dt.date(fy_start_year, 4, 1)
	effective_start = max(doj, fy_start)
	if lwd < effective_start:
		return Decimal("0")

	total = Decimal("0")
	y, m = effective_start.year, effective_start.month
	while (y, m) <= (lwd.year, lwd.month):
		dim = calendar.monthrange(y, m)[1]
		start_day = effective_start.day if (y, m) == (effective_start.year, effective_start.month) else 1
		end_day = lwd.day if (y, m) == (lwd.year, lwd.month) else dim
		days = max(0, end_day - start_day + 1)
		total += Decimal(days) / Decimal(dim)
		m += 1
		if m > 12:
			m = 1
			y += 1
	return total


def calc_statutory_bonus(
	inp: FnfInput,
	settings: FnfSettings,
) -> tuple[FnfLine, str | None]:
	"""Compute Code on Wages statutory bonus minus bonus already paid."""
	if not inp.site_rule.include_bonus:
		return (
			FnfLine(
				code="BONUS",
				label="Statutory bonus",
				line_type="EARNING",
				amount_paise=0,
				formula_text=f"Excluded by site rule ({inp.site_rule.site_code})",
			),
			f"Bonus excluded by site rule ({inp.site_rule.site_code})",
		)

	wage_for_eligibility = inp.basic_paise + inp.da_paise
	if inp.bonus_eligible_override is False or wage_for_eligibility > settings.bonus_eligibility_ceiling_paise:
		return (
			FnfLine(
				code="BONUS",
				label="Statutory bonus",
				line_type="EARNING",
				amount_paise=0,
				formula_text=f"Wages {paise_to_rupees_str(wage_for_eligibility)} > {paise_to_rupees_str(settings.bonus_eligibility_ceiling_paise)} ceiling",
				note="Not eligible",
			),
			f"Bonus not eligible: monthly wages ₹{paise_to_rupees_str(wage_for_eligibility)} exceed ₹{paise_to_rupees_str(settings.bonus_eligibility_ceiling_paise)}",
		)

	# Determine working days in FY
	if inp.fy_working_days is not None:
		working_days = inp.fy_working_days
	else:
		fy_start_year = inp.lwd.year if inp.lwd.month >= 4 else inp.lwd.year - 1
		fy_start = max(inp.doj, dt.date(fy_start_year, 4, 1))
		working_days = max(0, (inp.lwd - fy_start).days + 1)

	if working_days < settings.bonus_min_working_days:
		return (
			FnfLine(
				code="BONUS",
				label="Statutory bonus",
				line_type="EARNING",
				amount_paise=0,
				formula_text=f"Worked {working_days} days < {settings.bonus_min_working_days} min days",
				note="Not eligible",
			),
			f"Bonus not eligible: worked {working_days} days (< {settings.bonus_min_working_days} days)",
		)

	pct = settings.bonus_company_pct
	if inp.fy_bonus_wage_paise is not None:
		# Explicit FY bonus wage provided (rounded to rupee for display & calc consistency)
		bonus_wage_paise = inp.fy_bonus_wage_paise
		gross_bonus_paise = round_paise_to_rupee_paise(Decimal(bonus_wage_paise) * pct / Decimal("100"))
		formula = f"{paise_to_rupees_str(bonus_wage_paise)} × {pct}%"
	else:
		monthly_cap = max(
			settings.bonus_calc_ceiling_paise,
			inp.min_wage_monthly_paise or 0,
		)
		# Cap monthly calc wage at employee's actual Basic+DA when employee earns between 7000 and min_wage?
		# Standard Code on Wages: calculated on ₹7,000 or minimum wage whichever is higher.
		months = inp.fy_bonus_months if inp.fy_bonus_months is not None else _fy_months_and_fraction(inp.doj, inp.lwd)
		raw_fy_wage = Decimal(monthly_cap) * months
		bonus_wage_paise = round_paise_to_rupee_paise(raw_fy_wage)
		gross_bonus_paise = round_paise_to_rupee_paise(Decimal(bonus_wage_paise) * pct / Decimal("100"))
		formula = f"{paise_to_rupees_str(bonus_wage_paise)} × {pct}%"

	net_bonus_paise = gross_bonus_paise - inp.bonus_already_paid_paise
	warning = None
	note = ""
	if inp.bonus_already_paid_paise > 0:
		formula += f" − {paise_to_rupees_str(inp.bonus_already_paid_paise)} paid"
	if net_bonus_paise < 0:
		net_bonus_paise = 0
		note = "Bonus already paid exceeds calculated bonus"
		warning = "Bonus already paid exceeds calculated bonus; floored at ₹0"

	fy_year = inp.lwd.year if inp.lwd.month >= 4 else inp.lwd.year - 1
	fy_label = f"FY {fy_year}-{str(fy_year + 1)[-2:]}"
	return (
		FnfLine(
			code="BONUS",
			label=f"Statutory bonus {fy_label} ({pct}%)",
			line_type="EARNING",
			amount_paise=net_bonus_paise,
			formula_text=formula,
			note=note,
		),
		warning,
	)


def calc_gratuity(
	employment_type: str,
	exit_reason: str,
	tenure: TenureResult,
	basic_paise: int,
	da_paise: int,
	settings: FnfSettings,
	site_rule: SiteRule,
) -> tuple[FnfLine, str | None, bool]:
	"""Return (FnfLine, warning, payable_to_nominee)."""
	if not site_rule.include_gratuity:
		return (
			FnfLine(
				code="GRATUITY",
				label="Gratuity",
				line_type="EARNING",
				amount_paise=0,
				formula_text=f"Excluded by site rule ({site_rule.site_code})",
			),
			f"Gratuity excluded by site rule ({site_rule.site_code})",
			False,
		)

	wage_paise = basic_paise + da_paise
	is_death = exit_reason == "DEATH"
	emp_type = (employment_type or "PERMANENT").upper()

	if is_death:
		# Code on Social Security s.53: no minimum tenure required on death; minimum 1 year or pro-rata
		if tenure.years >= 1:
			years_factor = Decimal(tenure.counted_years)
			years_label = str(tenure.counted_years)
		else:
			months_eff = max(1, tenure.months + (1 if tenure.days >= 15 else 0))
			years_factor = Decimal(months_eff) / Decimal(12)
			years_label = f"{months_eff}/12"
		raw = Decimal(wage_paise) * Decimal(settings.gratuity_days) / Decimal(settings.gratuity_divisor) * years_factor
		amount_paise = min(round_paise_to_rupee_paise(raw), settings.gratuity_cap_paise)
		formula = f"{paise_to_rupees_str(wage_paise)} × {settings.gratuity_days} ÷ {settings.gratuity_divisor} × {years_label} (Death — payable to nominee)"
		return (
			FnfLine(
				code="GRATUITY",
				label="Gratuity (Nominee)",
				line_type="EARNING",
				amount_paise=amount_paise,
				formula_text=formula,
				note="Payable to nominee",
			),
			None,
			True,
		)

	if emp_type == "FIXED_TERM":
		min_req = settings.gratuity_fixed_term_min_years
		eligible = tenure.years >= min_req
		if not eligible:
			return (
				FnfLine(
					code="GRATUITY",
					label="Gratuity",
					line_type="EARNING",
					amount_paise=0,
					formula_text=f"Not eligible: {tenure.display} < {min_req} yr fixed-term",
					note="Not eligible",
				),
				f"Gratuity not eligible: {tenure.display} < {min_req} year fixed-term minimum",
				False,
			)
		counted = tenure.counted_years
	else:
		min_req = settings.gratuity_permanent_min_years
		eligible = tenure.years >= min_req or (
			settings.gratuity_allow_4y240d_rule and tenure.years == 4 and tenure.months >= 7
		)
		if not eligible:
			return (
				FnfLine(
					code="GRATUITY",
					label="Gratuity",
					line_type="EARNING",
					amount_paise=0,
					formula_text=f"Not eligible: {tenure.display} < {min_req} years",
					note="Not eligible",
				),
				f"Gratuity not eligible: {tenure.display} < {min_req} years",
				False,
			)
		counted = tenure.counted_years

	raw = Decimal(wage_paise) * Decimal(settings.gratuity_days) / Decimal(settings.gratuity_divisor) * Decimal(counted)
	uncapped = round_paise_to_rupee_paise(raw)
	capped = uncapped > settings.gratuity_cap_paise
	amount_paise = min(uncapped, settings.gratuity_cap_paise)
	formula = f"{paise_to_rupees_str(wage_paise)} × {settings.gratuity_days} ÷ {settings.gratuity_divisor} × {counted}"
	warning = None
	if capped:
		formula += f" (capped at ₹{paise_to_rupees_str(settings.gratuity_cap_paise)})"
		warning = f"Gratuity capped at statutory limit ₹{paise_to_rupees_str(settings.gratuity_cap_paise)}"

	return (
		FnfLine(
			code="GRATUITY",
			label="Gratuity",
			line_type="EARNING",
			amount_paise=amount_paise,
			formula_text=formula,
		),
		warning,
		False,
	)


def calc_fnf(inp: FnfInput, settings: FnfSettings | None = None) -> FnfResult:
	"""Pure deterministic Full & Final calculation entry point."""
	cfg = settings or FnfSettings()
	warnings: list[str] = []
	errors: list[str] = []
	lines: list[FnfLine] = []

	tenure = calc_tenure(inp.doj, inp.lwd, cfg.gratuity_round_up_months_over)

	# 1. Earned salary
	earned_line, earned_basic_paise = calc_earned_salary(
		inp.gross_paise,
		inp.basic_paise,
		inp.lwd,
		inp.days_worked_in_exit_month,
		inp.days_in_exit_month,
		cfg,
	)
	lines.append(earned_line)

	# 2. Leave encashment
	leave_line, leave_warn, leave_err = calc_leave_encashment(
		inp.el_balance,
		inp.basic_paise,
		inp.da_paise,
		inp.gross_paise,
		cfg,
		inp.site_rule,
	)
	if leave_err:
		errors.append(leave_err)
	elif leave_line:
		lines.append(leave_line)
	if leave_warn:
		warnings.append(leave_warn)

	# 3. Statutory bonus
	bonus_line, bonus_warn = calc_statutory_bonus(inp, cfg)
	lines.append(bonus_line)
	if bonus_warn:
		warnings.append(bonus_warn)

	# 4. Gratuity
	grat_line, grat_warn, to_nominee = calc_gratuity(
		inp.employment_type,
		inp.exit_reason,
		tenure,
		inp.basic_paise,
		inp.da_paise,
		cfg,
		inp.site_rule,
	)
	lines.append(grat_line)
	if grat_warn:
		warnings.append(grat_warn)

	# 5. Statutory deductions on earned salary
	if inp.deduct_pf and earned_basic_paise > 0:
		pf_base = (
			min(earned_basic_paise, cfg.pf_wage_ceiling_paise)
			if cfg.apply_pf_ceiling
			else earned_basic_paise
		)
		pf_paise = round_paise_to_rupee_paise(Decimal(pf_base) * cfg.pf_rate_pct / Decimal("100"))
		lines.append(
			FnfLine(
				code="PF",
				label=f"PF ({cfg.pf_rate_pct}% of earned basic {paise_to_rupees_str(pf_base)})",
				line_type="DEDUCTION",
				amount_paise=pf_paise,
				formula_text=f"{paise_to_rupees_str(pf_base)} × {cfg.pf_rate_pct}%",
			)
		)

	if inp.deduct_esi and inp.gross_paise <= cfg.esi_eligibility_ceiling_paise and earned_line.amount_paise > 0:
		esi_paise = round_paise_to_rupee_paise(
			Decimal(earned_line.amount_paise) * cfg.esi_rate_pct / Decimal("100")
		)
		lines.append(
			FnfLine(
				code="ESI",
				label=f"ESI ({cfg.esi_rate_pct}% of earned salary)",
				line_type="DEDUCTION",
				amount_paise=esi_paise,
				formula_text=f"{paise_to_rupees_str(earned_line.amount_paise)} × {cfg.esi_rate_pct}%",
			)
		)

	if inp.pt_paise > 0:
		lines.append(
			FnfLine(
				code="PT",
				label="Professional Tax",
				line_type="DEDUCTION",
				amount_paise=round_paise_to_rupee_paise(inp.pt_paise),
				formula_text="As per salary data",
			)
		)

	# 6. Manual lines (arrears, notice recovery, advances, property recovery)
	for ml in inp.manual_lines:
		lines.append(
			FnfLine(
				code=ml.code,
				label=ml.note or ml.code.replace("_", " ").title(),
				line_type=ml.line_type,
				amount_paise=round_paise_to_rupee_paise(ml.amount_paise),
				formula_text=ml.note or "Manual entry",
				is_manual=True,
				note=ml.note,
			)
		)

	total_earnings = sum(l.amount_paise for l in lines if l.line_type == "EARNING")
	total_deductions = sum(l.amount_paise for l in lines if l.line_type == "DEDUCTION")
	net_payable = total_earnings - total_deductions
	has_negative = net_payable < 0
	if has_negative:
		errors.append("FNF_NEGATIVE_NET: Deductions exceed earnings. Check recovery lines.")

	due_date = calc_payment_due_date(
		inp.exit_date,
		cfg.payment_due_working_days,
		cfg.working_weekdays,
		inp.holidays,
	)

	return FnfResult(
		employee_code=inp.employee_code,
		tenure=tenure,
		lines=tuple(lines),
		total_earnings_paise=total_earnings,
		total_deductions_paise=total_deductions,
		net_payable_paise=net_payable,
		payment_due_date=due_date,
		warnings=tuple(warnings),
		errors=tuple(errors),
		has_negative_net=has_negative,
		gratuity_payable_to_nominee=to_nominee,
	)
