"""Excel / CSV parsing, column mapping, row validation & formula-safe Excel export."""

from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal
from typing import Any

import openpyxl
import xlrd

from kesari_jefs.engine.money import rupees_to_paise
from kesari_jefs.engine.validators import (
	clean_aadhaar,
	normalize_mobile,
	parse_date,
	validate_age_18,
	validate_gross_consistency,
	validate_ifsc,
	validate_mobile,
	validate_pan,
	verhoeff_check,
)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_ROWS = 20000

FEED_FIELD_ALIASES: dict[str, dict[str, list[str]]] = {
	"EMPLOYEE": {
		"employee_code": ["employee code", "emp code", "emp_code", "emp.code", "emp. code", "code", "emp id", "employee_code"],
		"full_name": ["full name", "employee name", "emp name", "name of employee", "name", "full_name"],
		"first_name": ["first name", "first_name"],
		"middle_name": ["middle name", "middle_name"],
		"last_name": ["last name", "last_name"],
		"father_or_husband_name": ["father name", "father's name", "fathers name", "father/husband name", "father or husband name", "father_or_husband_name", "spouse name"],
		"gender": ["gender", "sex"],
		"dob": ["dob", "date of birth", "d.o.b", "d.o.b.", "birth date", "date_of_birth"],
		"mobile": ["mobile", "mobile no", "mobile no.", "phone", "contact", "contact no"],
		"email": ["email", "email id", "e-mail", "email_id"],
		"present_address": ["present address", "current address", "local address", "present_address", "address"],
		"permanent_address": ["permanent address", "perm address", "permanent_address"],
		"present_city": ["city", "present city", "present_city"],
		"present_state": ["state", "present state", "present_state"],
		"present_pin": ["pin", "pincode", "pin code", "present_pin"],
		"aadhaar": ["aadhaar", "aadhar", "aadhaar no", "aadhar no", "aadhaar number", "aadhar number"],
		"pan": ["pan", "pan no", "pan number"],
		"uan": ["uan", "uan no", "pf uan"],
		"esic_ip_no": ["esic", "esic no", "esic ip", "esic ip no", "esi no"],
		"bank_account": ["bank account", "bank a/c", "account no", "a/c no", "bank_account"],
		"ifsc": ["ifsc", "ifsc code"],
		"bank_name": ["bank name", "bank"],
		"designation": ["designation", "post", "role", "title"],
		"department": ["department", "dept"],
		"skill_category": ["skill", "skill category", "skill_category", "category"],
		"work_location": ["work location", "location", "work_location"],
		"client_site": ["client site", "principal employer", "site", "company", "client_site"],
		"employment_type": ["employment type", "emp type", "type", "employment_type"],
		"contract_end_date": ["contract end date", "contract_end_date"],
		"date_of_joining": ["date of joining", "doj", "d.o.j", "d.o.j.", "joining date", "date_of_joining"],
		"notice_period_days": ["notice period", "notice days", "notice_period_days"],
		"blood_group": ["blood group", "blood_group"],
		"marital_status": ["marital status", "marital_status"],
		"emergency_contact_name": ["emergency contact name", "emergency contact", "emergency_contact_name"],
		"emergency_contact_phone": ["emergency contact phone", "emergency phone", "emergency mobile", "emergency_contact_phone"],
		"police_station": ["police station", "police_station", "thana"],
		"id_proof_type": ["id proof type", "id_proof_type"],
		"id_proof_number": ["id proof number", "id_proof_number"],
		"nominee_name": ["nominee name", "nominee", "nominee_name"],
		"nominee_relation": ["nominee relation", "nominee relationship", "relationship", "nominee_relation"],
		"nominee_dob": ["nominee dob", "nominee age", "nominee_dob"],
		"nominee_share_pct": ["nominee share", "share %", "nominee share %", "nominee_share_pct"],
		"date_of_exit": ["date of exit", "date of leaving", "exit date", "dol", "d.o.l", "date_of_exit"],
		"last_working_day": ["last working day", "lwd", "last_working_day"],
		"exit_reason": ["exit reason", "reason for leaving", "separation reason", "exit_reason"],
		"conduct": ["conduct"],
	},
	"SALARY": {
		"employee_code": ["employee code", "emp code", "emp_code", "emp.code", "code"],
		"period": ["period", "month", "salary month"],
		"basic": ["basic", "basic salary", "basic wage"],
		"da": ["da", "vda", "da/vda", "da / vda", "dearness allowance"],
		"hra": ["hra", "house rent allowance"],
		"conveyance": ["conveyance", "conv"],
		"special_allowance": ["special allowance", "special", "other allowance", "special_allowance"],
		"gross": ["gross", "gross salary", "total gross", "gross wage"],
		"pf_ee": ["pf", "pf ee", "epf", "pf_ee"],
		"esi_ee": ["esi", "esic", "esi ee", "esi_ee"],
		"pt": ["pt", "professional tax"],
		"net": ["net", "net salary", "net pay"],
		"days_in_month": ["days in month", "month days", "days_in_month"],
		"days_paid": ["days paid", "paid days", "days worked", "days", "days_paid"],
	},
	"BONUS": {
		"employee_code": ["employee code", "emp code", "emp_code", "emp.code", "code"],
		"fy": ["fy", "financial year", "year"],
		"eligible": ["eligible", "eligible (y/n)", "is eligible"],
		"working_days": ["working days", "payable days", "total(d)", "total days", "working_days"],
		"bonus_wage": ["bonus wage", "totalbasic", "total basic", "bonus basic", "bonus_wage"],
		"bonus_pct": ["bonus %", "bonus pct", "pct", "bonus_pct"],
		"bonus_calculated": ["bonus calculated", "bonus @ 8.33%", "calculated bonus", "bonus_calculated"],
		"bonus_paid": ["bonus already paid", "bonus paid", "paid bonus", "bonus_paid"],
	},
	"LEAVE": {
		"employee_code": ["employee code", "emp code", "emp_code", "emp.code", "code"],
		"as_of_date": ["as of date", "as-of date", "as_of_date", "date"],
		"leave_type": ["leave type", "leave_type", "type"],
		"opening": ["opening", "opening balance"],
		"accrued": ["accrued", "earned"],
		"taken": ["taken", "availed"],
		"encashed": ["encashed"],
		"balance": ["el balance", "balance", "leave balance", "leave"],
	},
}

REQUIRED_FIELDS: dict[str, list[str]] = {
	"EMPLOYEE": ["employee_code", "full_name", "date_of_joining"],
	"SALARY": ["employee_code", "basic", "gross"],
	"BONUS": ["employee_code", "working_days"],
	"LEAVE": ["employee_code", "balance"],
}


def sanitize_excel_cell(val: Any) -> Any:
	"""Formula-injection protection per 10_SECURITY.md §4."""
	if isinstance(val, str) and val and val[0] in ("=", "+", "-", "@"):
		return "'" + val
	return val


def detect_file_type(file_bytes: bytes, filename: str) -> str:
	if len(file_bytes) > MAX_UPLOAD_BYTES:
		raise ValueError("UPL_FILE_TOO_LARGE: Max file size is 25 MB.")
	ext = (filename or "").rsplit(".", 1)[-1].lower()
	if file_bytes[:4] == b"PK\x03\x04" and ext in ("xlsx", "xlsm"):
		return "xlsx"
	if file_bytes[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" and ext == "xls":
		return "xls"
	if ext == "csv":
		return "csv"
	raise ValueError("UPL_FILE_TYPE: Only .xlsx / .xls / .csv files are allowed.")


def read_tabular_rows(file_bytes: bytes, filename: str) -> tuple[list[str], list[dict[str, Any]]]:
	kind = detect_file_type(file_bytes, filename)
	raw_rows: list[list[Any]] = []
	if kind == "xlsx":
		wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
		ws = wb.active
		for idx, row in enumerate(ws.iter_rows(values_only=True)):
			if idx > MAX_ROWS + 5:
				break
			raw_rows.append(list(row))
		wb.close()
	elif kind == "xls":
		wb = xlrd.open_workbook(file_contents=file_bytes)
		sh = wb.sheet_by_index(0)
		for r in range(min(sh.nrows, MAX_ROWS + 5)):
			row_vals = []
			for c in range(sh.ncols):
				cell = sh.cell(r, c)
				if cell.ctype == xlrd.XL_CELL_DATE:
					dt_tuple = xlrd.xldate_as_tuple(cell.value, wb.datemode)
					row_vals.append(dt.date(dt_tuple[0], dt_tuple[1], dt_tuple[2]))
				else:
					row_vals.append(cell.value)
			raw_rows.append(row_vals)
	else:
		text = file_bytes.decode("utf-8-sig", errors="replace")
		reader = csv.reader(io.StringIO(text))
		for idx, row in enumerate(reader):
			if idx > MAX_ROWS + 5:
				break
			raw_rows.append(row)

	# Find first non-empty header row (handle title rows like MEET MANPOWER SOLUTIONS)
	header_idx = None
	for i, row in enumerate(raw_rows[:15]):
		non_empty = [str(c).strip() for c in row if c is not None and str(c).strip() != ""]
		if len(non_empty) >= 2:
			header_idx = i
			break
	if header_idx is None:
		raise ValueError("UPL_NO_HEADER: Header row not found. Put column names in row 1.")

	headers = [
		str(c).strip() if c is not None and str(c).strip() != "" else f"Column_{idx + 1}"
		for idx, c in enumerate(raw_rows[header_idx])
	]
	rows: list[dict[str, Any]] = []
	for r_idx, row in enumerate(raw_rows[header_idx + 1 :], start=header_idx + 2):
		if len(rows) >= MAX_ROWS:
			break
		if not any(c is not None and str(c).strip() != "" for c in row):
			continue
		rec: dict[str, Any] = {"__row_num": r_idx}
		for c_idx, h in enumerate(headers):
			rec[h] = row[c_idx] if c_idx < len(row) else None
		rows.append(rec)
	return headers, rows


def suggest_column_mapping(feed: str, headers: list[str], saved_mapping: dict[str, str] | None = None) -> dict[str, str]:
	aliases = FEED_FIELD_ALIASES.get(feed, {})
	mapping: dict[str, str] = {}
	saved = saved_mapping or {}
	for h in headers:
		if h in saved and saved[h]:
			mapping[h] = saved[h]
			continue
		norm = h.strip().lower()
		matched = ""
		for sys_field, opts in aliases.items():
			if norm == sys_field or norm in opts:
				matched = sys_field
				break
		mapping[h] = matched
	return mapping


def _to_dec_str(val: Any) -> Decimal | None:
	if val is None or str(val).strip() == "":
		return None
	s = str(val).strip().replace(",", "").replace("₹", "")
	return Decimal(s)


def validate_mapped_rows(
	feed: str,
	rows: list[dict[str, Any]],
	mapping: dict[str, str],
	existing_employee_codes: set[str] | None = None,
	default_period: str = "",
	default_fy: str = "",
	default_as_of: dt.date | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
	"""Validate rows for a feed, returning (valid_rows, error_rows, missing_required_fields)."""
	rev_map = {sys_f: col for col, sys_f in mapping.items() if sys_f}
	missing_req = [f for f in REQUIRED_FIELDS.get(feed, []) if f not in rev_map]
	# Allow first_name + last_name instead of full_name
	if feed == "EMPLOYEE" and "full_name" in missing_req and "first_name" in rev_map:
		missing_req.remove("full_name")

	seen_codes: set[str] = set()
	valid_rows: list[dict[str, Any]] = []
	error_rows: list[dict[str, Any]] = []
	today = dt.date.today()

	for raw in rows:
		row_num = raw.get("__row_num", 0)
		mapped: dict[str, Any] = {"__row_num": row_num}
		for col, sys_f in mapping.items():
			if sys_f:
				mapped[sys_f] = raw.get(col)

		errs: list[str] = []
		code = str(mapped.get("employee_code") or "").strip().upper()
		if not code:
			errs.append("employee_code: missing")
		else:
			mapped["employee_code"] = code
			if feed == "EMPLOYEE":
				if code in seen_codes:
					errs.append(f"employee_code: duplicate code {code} in file")
				seen_codes.add(code)
			else:
				if existing_employee_codes is not None and code not in existing_employee_codes:
					errs.append(f"employee_code: unknown employee {code} (upload Employee Excel first)")

		if feed == "EMPLOYEE":
			full_name = str(mapped.get("full_name") or "").strip()
			if not full_name:
				fn = str(mapped.get("first_name") or "").strip()
				mn = str(mapped.get("middle_name") or "").strip()
				ln = str(mapped.get("last_name") or "").strip()
				full_name = " ".join(p for p in (fn, mn, ln) if p)
			if not full_name:
				errs.append("full_name: missing")
			else:
				mapped["full_name"] = full_name

			doj = parse_date(mapped.get("date_of_joining"))
			if not doj:
				errs.append("date_of_joining: missing or invalid date")
			elif doj > today + dt.timedelta(days=365):
				errs.append("date_of_joining: unreasonable future date")
			else:
				mapped["date_of_joining"] = doj.isoformat()

			dob_val = mapped.get("dob")
			if dob_val is not None and str(dob_val).strip() != "":
				dob = parse_date(dob_val)
				if not dob:
					errs.append("dob: invalid date")
				elif not validate_age_18(dob, doj or today):
					errs.append("dob: age below 18")
				else:
					mapped["dob"] = dob.isoformat()

			mob_val = mapped.get("mobile")
			if mob_val is not None and str(mob_val).strip() != "":
				if not validate_mobile(str(mob_val)):
					errs.append("mobile: must be 10 digits starting 6-9")
				else:
					mapped["mobile"] = normalize_mobile(str(mob_val))

			aad_val = mapped.get("aadhaar")
			if aad_val is not None and str(aad_val).strip() != "":
				digits = clean_aadhaar(str(aad_val))
				if not verhoeff_check(digits):
					errs.append("aadhaar: invalid Aadhaar checksum")
				else:
					mapped["aadhaar"] = digits

			pan_val = mapped.get("pan")
			if pan_val is not None and str(pan_val).strip() != "":
				if not validate_pan(str(pan_val)):
					errs.append("pan: invalid PAN format")
				else:
					mapped["pan"] = str(pan_val).strip().upper()

			ifsc_val = mapped.get("ifsc")
			if ifsc_val is not None and str(ifsc_val).strip() != "":
				if not validate_ifsc(str(ifsc_val)):
					errs.append("ifsc: invalid IFSC format")
				else:
					mapped["ifsc"] = str(ifsc_val).strip().upper()

			share_val = mapped.get("nominee_share_pct")
			if share_val is not None and str(share_val).strip() != "":
				try:
					sh = _to_dec_str(share_val)
					if sh is not None and (sh <= 0 or sh > 100):
						errs.append("nominee_share_pct: must be between 1 and 100")
					else:
						mapped["nominee_share_pct"] = float(sh) if sh is not None else 100
				except Exception:
					errs.append("nominee_share_pct: invalid number")

			exit_val = mapped.get("date_of_exit")
			if exit_val is not None and str(exit_val).strip() != "":
				ex = parse_date(exit_val)
				if not ex:
					errs.append("date_of_exit: invalid date")
				else:
					mapped["date_of_exit"] = ex.isoformat()

			lwd_val = mapped.get("last_working_day")
			if lwd_val is not None and str(lwd_val).strip() != "":
				lw = parse_date(lwd_val)
				if not lw:
					errs.append("last_working_day: invalid date")
				else:
					mapped["last_working_day"] = lw.isoformat()

		elif feed == "SALARY":
			period = str(mapped.get("period") or default_period or "").strip()
			if not period:
				errs.append("period: missing (YYYY-MM)")
			mapped["period"] = period
			try:
				basic_p = rupees_to_paise(_to_dec_str(mapped.get("basic")) or Decimal("0"))
				da_p = rupees_to_paise(_to_dec_str(mapped.get("da")) or Decimal("0"))
				hra_p = rupees_to_paise(_to_dec_str(mapped.get("hra")) or Decimal("0"))
				conv_p = rupees_to_paise(_to_dec_str(mapped.get("conveyance")) or Decimal("0"))
				spec_p = rupees_to_paise(_to_dec_str(mapped.get("special_allowance")) or Decimal("0"))
				gross_dec = _to_dec_str(mapped.get("gross"))
				if gross_dec is None:
					errs.append("gross: missing")
					gross_p = 0
				else:
					gross_p = rupees_to_paise(gross_dec)
					comp_sum = basic_p + da_p + hra_p + conv_p + spec_p
					if not validate_gross_consistency(comp_sum, gross_p):
						errs.append("gross: does not equal sum of components (±₹1)")
				mapped.update(
					basic_paise=basic_p,
					da_paise=da_p,
					hra_paise=hra_p,
					conveyance_paise=conv_p,
					special_allowance_paise=spec_p,
					gross_paise=gross_p,
					pf_ee_paise=rupees_to_paise(_to_dec_str(mapped.get("pf_ee")) or Decimal("0")),
					esi_ee_paise=rupees_to_paise(_to_dec_str(mapped.get("esi_ee")) or Decimal("0")),
					pt_paise=rupees_to_paise(_to_dec_str(mapped.get("pt")) or Decimal("0")),
				)
				net_dec = _to_dec_str(mapped.get("net"))
				mapped["net_paise"] = (
					rupees_to_paise(net_dec)
					if net_dec is not None
					else max(0, gross_p - mapped["pf_ee_paise"] - mapped["esi_ee_paise"] - mapped["pt_paise"])
				)
				mapped["days_in_month"] = int(_to_dec_str(mapped.get("days_in_month")) or 0)
				mapped["days_paid"] = float(_to_dec_str(mapped.get("days_paid")) or 0)
			except Exception as exc:
				errs.append(f"salary numbers: invalid ({exc})")

		elif feed == "BONUS":
			mapped["fy"] = str(mapped.get("fy") or default_fy or "").strip()
			if not mapped["fy"]:
				errs.append("fy: missing financial year")
			try:
				mapped["working_days"] = int(_to_dec_str(mapped.get("working_days")) or 0)
				mapped["bonus_wage_paise"] = rupees_to_paise(_to_dec_str(mapped.get("bonus_wage")) or Decimal("0"))
				mapped["bonus_pct"] = float(_to_dec_str(mapped.get("bonus_pct")) or Decimal("8.33"))
				mapped["bonus_calculated_paise"] = rupees_to_paise(_to_dec_str(mapped.get("bonus_calculated")) or Decimal("0"))
				mapped["bonus_paid_paise"] = rupees_to_paise(_to_dec_str(mapped.get("bonus_paid")) or Decimal("0"))
				elig_str = str(mapped.get("eligible") or "Y").strip().upper()
				mapped["eligible"] = 0 if elig_str in ("N", "NO", "FALSE", "0") else 1
			except Exception as exc:
				errs.append(f"bonus numbers: invalid ({exc})")

		elif feed == "LEAVE":
			as_of = parse_date(mapped.get("as_of_date")) or default_as_of or today
			mapped["as_of_date"] = as_of.isoformat()
			mapped["leave_type"] = str(mapped.get("leave_type") or "EL").strip().upper()
			try:
				bal = _to_dec_str(mapped.get("balance"))
				if bal is None:
					errs.append("balance: missing EL balance")
				else:
					mapped["balance"] = float(bal)
				mapped["opening"] = float(_to_dec_str(mapped.get("opening")) or Decimal("0"))
				mapped["accrued"] = float(_to_dec_str(mapped.get("accrued")) or Decimal("0"))
				mapped["taken"] = float(_to_dec_str(mapped.get("taken")) or Decimal("0"))
				mapped["encashed"] = float(_to_dec_str(mapped.get("encashed")) or Decimal("0"))
			except Exception as exc:
				errs.append(f"leave numbers: invalid ({exc})")

		if errs:
			error_rows.append({"row_num": row_num, "errors": "; ".join(errs), "raw": {k: v for k, v in raw.items() if k != "__row_num"}})
		else:
			valid_rows.append(mapped)

	return valid_rows, error_rows, missing_req


def build_xlsx_bytes(sheets: list[tuple[str, list[str], list[list[Any]]]]) -> bytes:
	wb = openpyxl.Workbook()
	wb.remove(wb.active)
	for title, headers, rows in sheets:
		ws = wb.create_sheet(title=title[:31])
		ws.append([sanitize_excel_cell(h) for h in headers])
		for r in rows:
			ws.append([sanitize_excel_cell(c) for c in r])
	buf = io.BytesIO()
	wb.save(buf)
	return buf.getvalue()


def build_sample_feed_xlsx(feed: str) -> bytes:
	if feed == "EMPLOYEE":
		headers = [
			"Employee Code", "Full Name", "Father's Name", "Gender", "Date of Birth",
			"Mobile", "Email", "Present Address", "Permanent Address", "City", "State", "PIN",
			"Aadhaar", "PAN", "UAN", "ESIC IP No", "Bank A/c", "IFSC", "Bank Name",
			"Designation", "Department", "Skill Category", "Work Location", "Client Site",
			"Employment Type", "Date of Joining", "Notice Period", "Blood Group",
			"Marital Status", "Emergency Contact Name", "Emergency Contact Phone",
			"Police Station", "Nominee Name", "Nominee Relation", "Nominee DOB", "Nominee Share %",
		]
		sample = [[
			"KM1023", "Rameshbhai Patel", "Kantilal Patel", "Male", "15-05-1992",
			"9876543210", "ramesh@example.com", "Akota, Vadodara", "Village Padra, Vadodara",
			"Vadodara", "Gujarat", "390020", "234567891234", "ABCDE1234F", "100123456789",
			"3812345678", "123456789012", "SBIN0001234", "State Bank of India",
			"Machine Operator", "Production", "Skilled", "Makarpura", "CONMAT",
			"PERMANENT", "01-06-2020", "30", "B+", "Married", "Suresh Patel", "9876500001",
			"Makarpura Police Station", "Meenaben Patel", "Wife", "10-08-1995", "100",
		]]
	elif feed == "SALARY":
		headers = ["Employee Code", "Period", "Basic", "DA", "HRA", "Conveyance", "Special Allowance", "Gross", "PF", "ESI", "PT", "Net", "Days in Month", "Paid Days"]
		sample = [["KM1023", "2027-01", 15000, 3000, 2500, 1000, 500, 22000, 1800, 0, 200, 20000, 31, 31]]
	elif feed == "BONUS":
		headers = ["Employee Code", "Financial Year", "Eligible", "Working Days", "Bonus Wage", "Bonus %", "Bonus Calculated", "Bonus Already Paid"]
		sample = [["KM1023", "2026-27", "Y", 260, 132774, 8.33, 11060, 0]]
	else:
		headers = ["Employee Code", "As-of Date", "Leave Type", "Opening", "Accrued", "Taken", "Encashed", "EL Balance"]
		sample = [["KM1023", "15-01-2027", "EL", 6, 10, 4, 0, 12]]
	return build_xlsx_bytes([(feed.title(), headers, sample)])
