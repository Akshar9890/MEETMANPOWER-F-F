"""Pure tenure calculation helpers (no DB, no clock)."""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class TenureResult:
	years: int
	months: int
	days: int
	counted_years: int
	total_days: int
	display: str


def calc_tenure(doj: dt.date, lwd: dt.date, round_up_months_over: int = 6) -> TenureResult:
	"""Calculate calendar years/months/days (inclusive of DOJ & LWD) and counted gratuity years."""
	if lwd < doj:
		raise ValueError("Last working day cannot be before date of joining")

	# Inclusive end-date for tenure display (e.g. 01-06-2020 -> 15-01-2027 = 6y 7m 15d)
	end_plus_one = lwd + dt.timedelta(days=1)

	years = end_plus_one.year - doj.year
	months = end_plus_one.month - doj.month
	days = end_plus_one.day - doj.day

	if days < 0:
		months -= 1
		prev_month = end_plus_one.month - 1 if end_plus_one.month > 1 else 12
		prev_year = end_plus_one.year if end_plus_one.month > 1 else end_plus_one.year - 1
		days += calendar.monthrange(prev_year, prev_month)[1]

	if months < 0:
		years -= 1
		months += 12

	counted_years = years + 1 if months > round_up_months_over else years
	total_days = (lwd - doj).days + 1
	display = f"{years}y {months}m {days}d"

	return TenureResult(
		years=years,
		months=months,
		days=days,
		counted_years=counted_years,
		total_days=total_days,
		display=display,
	)
