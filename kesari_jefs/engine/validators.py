"""Pure validation and masking utilities (no DB, no clock)."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal

_VERHOEFF_D = (
	(0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
	(1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
	(2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
	(3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
	(4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
	(5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
	(6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
	(7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
	(8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
	(9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
	(0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
	(1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
	(5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
	(8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
	(9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
	(4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
	(2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
	(7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
MOBILE_RE = re.compile(r"^[6-9][0-9]{9}$")


def clean_aadhaar(value: str | None) -> str:
	if not value:
		return ""
	return re.sub(r"[\s-]+", "", str(value).strip())


def verhoeff_check(aadhaar: str | None) -> bool:
	"""Validate 12-digit Aadhaar number with Verhoeff checksum."""
	digits = clean_aadhaar(aadhaar)
	if len(digits) != 12 or not digits.isdigit():
		return False
	if digits[0] in ("0", "1"):
		return False
	c = 0
	for i, ch in enumerate(reversed(digits)):
		c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
	return c == 0


def mask_aadhaar(aadhaar: str | None) -> str:
	digits = clean_aadhaar(aadhaar)
	if len(digits) < 4:
		return ""
	return f"XXXX XXXX {digits[-4:]}"


def mask_pan(pan: str | None) -> str:
	if not pan:
		return ""
	p = str(pan).strip().upper()
	if len(p) != 10:
		return "XXXX"
	return f"{p[:2]}XXXXXX{p[-2:]}"


def mask_bank_account(account: str | None) -> str:
	if not account:
		return ""
	s = re.sub(r"\s+", "", str(account).strip())
	if len(s) <= 4:
		return "X" * len(s)
	return "X" * (len(s) - 4) + s[-4:]


def validate_pan(pan: str | None) -> bool:
	if not pan:
		return False
	return bool(PAN_RE.match(str(pan).strip().upper()))


def validate_ifsc(ifsc: str | None) -> bool:
	if not ifsc:
		return False
	return bool(IFSC_RE.match(str(ifsc).strip().upper()))


def validate_mobile(mobile: str | None) -> bool:
	if not mobile:
		return False
	s = re.sub(r"[\s+-]+", "", str(mobile).strip())
	if s.startswith("91") and len(s) == 12:
		s = s[2:]
	elif s.startswith("0") and len(s) == 11:
		s = s[1:]
	return bool(MOBILE_RE.match(s))


def normalize_mobile(mobile: str | None) -> str:
	if not mobile:
		return ""
	s = re.sub(r"[\s+-]+", "", str(mobile).strip())
	if s.startswith("91") and len(s) == 12:
		s = s[2:]
	elif s.startswith("0") and len(s) == 11:
		s = s[1:]
	return s


def parse_date(val) -> dt.date | None:
	"""Parse common Excel / ISO / Indian date formats cleanly."""
	if val is None or val == "":
		return None
	if isinstance(val, dt.datetime):
		return val.date()
	if isinstance(val, dt.date):
		return val
	if isinstance(val, (int, float)):
		# Excel serial number (1900 date system)
		try:
			serial = int(float(val))
			if 1000 < serial < 100000:
				return dt.date(1899, 12, 30) + dt.timedelta(days=serial)
		except Exception:
			return None
	s = str(val).strip()
	if not s:
		return None
	# Numeric string serial
	if re.fullmatch(r"\d+(\.0+)?", s):
		serial = int(float(s))
		if 1000 < serial < 100000:
			return dt.date(1899, 12, 30) + dt.timedelta(days=serial)
	for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d-%b-%y", "%m/%d/%Y", "%Y/%m/%d"):
		try:
			return dt.datetime.strptime(s, fmt).date()
		except ValueError:
			continue
	return None


def validate_age_18(dob: dt.date, as_of: dt.date) -> bool:
	age = as_of.year - dob.year - ((as_of.month, as_of.day) < (dob.month, dob.day))
	return age >= 18


def validate_gross_consistency(
	earnings_sum_paise: int,
	gross_paise: int,
	tolerance_paise: int = 100,
) -> bool:
	return abs(earnings_sum_paise - gross_paise) <= tolerance_paise


def validate_nominee_shares(shares: list[Decimal | int | str | float]) -> bool:
	if not shares:
		return False
	total = sum((Decimal(str(s)) for s in shares), Decimal("0"))
	return total == Decimal("100")
