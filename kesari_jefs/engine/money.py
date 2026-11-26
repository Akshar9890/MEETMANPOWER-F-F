"""Pure integer-paise money helpers using Decimal ROUND_HALF_UP (no floats)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

PAISE_PER_RUPEE = 100


def to_decimal(value: Decimal | int | str | float) -> Decimal:
	"""Convert numeric input safely via string to Decimal."""
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value))


def rupees_to_paise(rupees: Decimal | int | str | float) -> int:
	"""Convert rupees to integer paise using ROUND_HALF_UP."""
	d = to_decimal(rupees) * Decimal(PAISE_PER_RUPEE)
	return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_paise_to_rupee_paise(paise: Decimal | int) -> int:
	"""Round a paise value (possibly fractional Decimal) to the nearest whole rupee in paise."""
	rupees = (to_decimal(paise) / Decimal(PAISE_PER_RUPEE)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
	return int(rupees) * PAISE_PER_RUPEE


def paise_to_rupees_int(paise: int) -> int:
	"""Return rounded whole rupees from integer paise."""
	rupees = (Decimal(paise) / Decimal(PAISE_PER_RUPEE)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
	return int(rupees)


def paise_to_rupees_str(paise: int) -> str:
	"""Return Indian-comma formatted whole rupees string (e.g. '1,01,634')."""
	rupees = paise_to_rupees_int(paise)
	return format_indian_int(rupees)


def format_indian_int(n: int) -> str:
	"""Format an integer using Indian comma grouping (12,34,567)."""
	sign = "-" if n < 0 else ""
	s = str(abs(n))
	if len(s) <= 3:
		return sign + s
	last3 = s[-3:]
	rest = s[:-3]
	groups = []
	while len(rest) > 2:
		groups.append(rest[-2:])
		rest = rest[:-2]
	if rest:
		groups.append(rest)
	return sign + ",".join(reversed(groups)) + "," + last3


_ONES = [
	"",
	"One",
	"Two",
	"Three",
	"Four",
	"Five",
	"Six",
	"Seven",
	"Eight",
	"Nine",
	"Ten",
	"Eleven",
	"Twelve",
	"Thirteen",
	"Fourteen",
	"Fifteen",
	"Sixteen",
	"Seventeen",
	"Eighteen",
	"Nineteen",
]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two_digits(n: int) -> str:
	if n < 20:
		return _ONES[n]
	return (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")).strip()


def _three_digits(n: int) -> str:
	if n < 100:
		return _two_digits(n)
	rem = n % 100
	return (_ONES[n // 100] + " Hundred" + (" " + _two_digits(rem) if rem else "")).strip()


def amount_in_words_inr(paise: int) -> str:
	"""Convert integer paise (rounded to rupees) into Indian English words."""
	rupees = abs(paise_to_rupees_int(paise))
	if rupees == 0:
		return "Rupees Zero Only"
	parts = []
	crores = rupees // 10000000
	rupees %= 10000000
	lakhs = rupees // 100000
	rupees %= 100000
	thousands = rupees // 1000
	rupees %= 1000
	if crores:
		parts.append(f"{_three_digits(crores)} Crore")
	if lakhs:
		parts.append(f"{_two_digits(lakhs)} Lakh")
	if thousands:
		parts.append(f"{_two_digits(thousands)} Thousand")
	if rupees:
		parts.append(_three_digits(rupees))
	prefix = "Minus " if paise < 0 else ""
	return f"{prefix}Rupees {' '.join(parts)} Only"
