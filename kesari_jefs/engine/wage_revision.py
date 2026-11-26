"""Pure Minimum Wage & Increment Revision calculation engine (no DB, no clock)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .money import paise_to_rupees_str, round_paise_to_rupee_paise


@dataclass(frozen=True)
class WageRevisionEmployee:
	employee_code: str
	employee_name: str
	state: str
	zone: str
	skill_category: str
	old_basic_paise: int
	old_da_paise: int
	old_gross_paise: int


@dataclass(frozen=True)
class MinWageEntry:
	state: str
	zone: str
	skill_category: str
	basic_paise: int
	vda_paise: int
	total_paise: int


@dataclass(frozen=True)
class WageProposal:
	employee_code: str
	employee_name: str
	skill_category: str
	old_total_paise: int
	min_wage_paise: int | None
	proposed_total_paise: int
	delta_paise: int
	needs_letter: bool
	reason: str
	error: str | None = None


def propose_wage_revision(
	employees: list[WageRevisionEmployee],
	rates: dict[tuple[str, str, str], MinWageEntry],
	policy: str = "RAISE_TO_MIN",  # RAISE_TO_MIN | ADD_VDA_DELTA | CUSTOM_PCT
	vda_delta_paise: int = 0,
	custom_pct: Decimal = Decimal("0"),
	letter_for_all: bool = False,
) -> list[WageProposal]:
	proposals: list[WageProposal] = []
	for emp in employees:
		key = (emp.state.strip().lower(), emp.zone.strip().lower(), emp.skill_category.strip().lower())
		rate = rates.get(key)
		if not rate:
			# Fallback wildcard zone
			rate = rates.get((emp.state.strip().lower(), "*", emp.skill_category.strip().lower()))
		if not rate:
			proposals.append(
				WageProposal(
					employee_code=emp.employee_code,
					employee_name=emp.employee_name,
					skill_category=emp.skill_category,
					old_total_paise=emp.old_gross_paise,
					min_wage_paise=None,
					proposed_total_paise=emp.old_gross_paise,
					delta_paise=0,
					needs_letter=False,
					reason="Missing minimum wage rate",
					error=f"WAGE_RATE_MISSING: No minimum wage for {emp.state}/{emp.zone}/{emp.skill_category}",
				)
			)
			continue

		old_total = emp.old_gross_paise
		min_total = rate.total_paise

		if policy == "ADD_VDA_DELTA":
			candidate = old_total + vda_delta_paise
			proposed = max(candidate, min_total)
			reason = (
				f"Raised to minimum (₹{paise_to_rupees_str(min_total)})"
				if proposed == min_total and candidate < min_total
				else f"Added VDA delta ₹{paise_to_rupees_str(vda_delta_paise)}"
			)
		elif policy == "CUSTOM_PCT":
			inc = round_paise_to_rupee_paise(Decimal(old_total) * custom_pct / Decimal("100"))
			candidate = old_total + inc
			proposed = max(candidate, min_total)
			reason = f"Custom +{custom_pct}%"
		else:  # RAISE_TO_MIN
			if old_total < min_total:
				proposed = min_total
				reason = f"Below minimum ₹{paise_to_rupees_str(min_total)}"
			else:
				proposed = old_total
				reason = "Already above minimum (unchanged)"

		delta = proposed - old_total
		needs_letter = delta > 0 or letter_for_all
		proposals.append(
			WageProposal(
				employee_code=emp.employee_code,
				employee_name=emp.employee_name,
				skill_category=emp.skill_category,
				old_total_paise=old_total,
				min_wage_paise=min_total,
				proposed_total_paise=proposed,
				delta_paise=delta,
				needs_letter=needs_letter,
				reason=reason,
				error=None,
			)
		)
	return proposals
