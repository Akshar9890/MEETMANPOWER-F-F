"""Bidirectional backend & DocType bridge between Kesari JEFS and Frappe HR."""

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
from typing import Any

import frappe
from frappe.utils import flt, getdate, today


@contextmanager
def _jefs_sync_guard():
	prev = bool(getattr(frappe.flags, "in_jefs_sync", False))
	frappe.flags.in_jefs_sync = True
	try:
		yield
	finally:
		frappe.flags.in_jefs_sync = prev


def get_default_company() -> str | None:
	legal = frappe.db.get_single_value("JEFS Company Profile", "legal_name") or ""
	if legal and frappe.db.exists("Company", legal):
		return legal
	companies = frappe.get_all("Company", pluck="name", order_by="creation asc")
	return companies[0] if companies else None


def ensure_hrms_custom_fields() -> None:
	"""Create idempotent Custom Fields linking Employee, Full and Final Statement, and Separation to JEFS."""
	defs = [
		("Employee", "jefs_section", "Section Break", "Kesari JEFS Profile", None, 0, "employment_type"),
		("Employee", "jefs_employee", "Link", "JEFS Employee", "JEFS Employee", 1, "jefs_section"),
		("Employee", "jefs_client_site", "Data", "Client Site", None, 0, "jefs_employee"),
		("Employee", "jefs_employment_type", "Select", "JEFS Employment Type", "\nPERMANENT\nFIXED_TERM\nCONTRACT", 0, "jefs_client_site"),
		("Employee", "jefs_skill_category", "Data", "Skill Category", None, 0, "jefs_employment_type"),
		("Employee", "jefs_aadhaar_masked", "Data", "Masked Aadhaar", None, 1, "jefs_skill_category"),
		("Employee", "jefs_pan_masked", "Data", "Masked PAN", None, 1, "jefs_aadhaar_masked"),
		("Full and Final Statement", "jefs_section", "Section Break", "Kesari JEFS Settlement", None, 0, "total_asset_recovery_cost"),
		("Full and Final Statement", "jefs_fnf_settlement", "Link", "JEFS FnF Settlement", "JEFS FnF Settlement", 1, "jefs_section"),
		("Full and Final Statement", "jefs_status", "Data", "JEFS Approval Status", None, 1, "jefs_fnf_settlement"),
		("Full and Final Statement", "jefs_tenure", "Data", "JEFS Service Tenure", None, 1, "jefs_status"),
		("Full and Final Statement", "jefs_payment_due_date", "Date", "Payment Due Date (2 Working Days)", None, 1, "jefs_tenure"),
		("Full and Final Statement", "jefs_net_payable", "Currency", "JEFS Verified Net Payable (INR)", None, 1, "jefs_payment_due_date"),
		("Employee Separation", "jefs_section", "Section Break", "Kesari JEFS", None, 0, "exit_interview"),
		("Employee Separation", "jefs_fnf_settlement", "Link", "JEFS FnF Settlement", "JEFS FnF Settlement", 1, "jefs_section"),
	]
	changed_dts = set()
	for dt_name, fieldname, fieldtype, label, options, read_only, insert_after in defs:
		if not frappe.db.exists("DocType", dt_name):
			continue
		cf_name = f"{dt_name}-{fieldname}"
		if not frappe.db.exists("Custom Field", cf_name):
			try:
				frappe.get_doc(
					{
						"doctype": "Custom Field",
						"dt": dt_name,
						"fieldname": fieldname,
						"label": label,
						"fieldtype": fieldtype,
						"options": options,
						"read_only": read_only,
						"insert_after": insert_after,
						"module": "Kesari JEFS",
					}
				).insert(ignore_permissions=True)
				changed_dts.add(dt_name)
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"JEFS Custom Field {cf_name}")
	for dt_name in changed_dts:
		frappe.clear_cache(doctype=dt_name)


def _ensure_salary_component(name: str, abbr: str, comp_type: str = "Earning") -> str:
	if frappe.db.exists("Salary Component", name):
		return name
	doc = frappe.get_doc(
		{
			"doctype": "Salary Component",
			"salary_component": name,
			"salary_component_abbr": abbr,
			"type": comp_type,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_salary_structure(company: str) -> str | None:
	if not company:
		return None
	abbr = frappe.db.get_value("Company", company, "abbr") or "KM"
	struct_name = f"Kesari Monthly Structure - {abbr}"
	if frappe.db.exists("Salary Structure", struct_name):
		return struct_name
	try:
		basic = _ensure_salary_component("Basic", "B", "Earning")
		doc = frappe.get_doc(
			{
				"doctype": "Salary Structure",
				"name": struct_name,
				"__newname": struct_name,
				"company": company,
				"is_active": "Yes",
				"currency": "INR",
				"payroll_frequency": "Monthly",
				"earnings": [{"salary_component": basic, "amount_based_on_formula": 1, "formula": "base"}],
			}
		)
		doc.insert(ignore_permissions=True)
		doc.submit()
		return doc.name
	except Exception:
		frappe.log_error(frappe.get_traceback(), "JEFS Ensure Salary Structure")
		existing = frappe.get_all("Salary Structure", filters={"company": company, "docstatus": 1, "is_active": "Yes"}, pluck="name", limit=1)
		return existing[0] if existing else None


def _map_leave_type(code: str) -> str:
	c = (code or "EL").strip().upper()
	if c in ("EL", "PL", "EARNED LEAVE", "PRIVILEGE LEAVE") and frappe.db.exists("Leave Type", "Privilege Leave"):
		return "Privilege Leave"
	if c in ("CL", "CASUAL LEAVE") and frappe.db.exists("Leave Type", "Casual Leave"):
		return "Casual Leave"
	if c in ("SL", "SICK LEAVE") and frappe.db.exists("Leave Type", "Sick Leave"):
		return "Sick Leave"
	if frappe.db.exists("Leave Type", c):
		return c
	try:
		doc = frappe.get_doc(
			{
				"doctype": "Leave Type",
				"leave_type_name": c,
				"is_carry_forward": 1,
				"allow_encashment": 1,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception:
		return "Privilege Leave" if frappe.db.exists("Leave Type", "Privilege Leave") else c


def _ensure_leave_period(company: str, ref_date: dt.date) -> tuple[str, dt.date, dt.date] | tuple[None, dt.date, dt.date]:
	fy_start_year = ref_date.year if ref_date.month >= 4 else ref_date.year - 1
	from_d = dt.date(fy_start_year, 4, 1)
	to_d = dt.date(fy_start_year + 1, 3, 31)
	existing = frappe.get_all(
		"Leave Period",
		filters={"company": company, "from_date": ["<=", ref_date], "to_date": [">=", ref_date]},
		fields=["name", "from_date", "to_date"],
		limit=1,
	)
	if existing:
		row = existing[0]
		return row["name"], getdate(row["from_date"]), getdate(row["to_date"])
	try:
		lp = frappe.get_doc(
			{
				"doctype": "Leave Period",
				"from_date": from_d,
				"to_date": to_d,
				"company": company,
				"is_active": 1,
			}
		)
		lp.insert(ignore_permissions=True)
		return lp.name, from_d, to_d
	except Exception:
		frappe.log_error(frappe.get_traceback(), "JEFS Ensure Leave Period")
		return None, from_d, to_d


def sync_jefs_to_hr_employee(jefs_emp) -> str | None:
	"""Sync JEFS Employee (plus latest salary CTC) to native Frappe HR Employee."""
	if getattr(frappe.flags, "in_jefs_sync", False):
		return jefs_emp.frappe_employee
	with _jefs_sync_guard():
		try:
			company_name = get_default_company()
			if not company_name:
				return None

			if jefs_emp.designation and not frappe.db.exists("Designation", jefs_emp.designation):
				frappe.get_doc({"doctype": "Designation", "designation_name": jefs_emp.designation}).insert(ignore_permissions=True)

			dept_name = None
			if jefs_emp.department:
				dept_name = frappe.db.get_value("Department", {"department_name": jefs_emp.department, "company": company_name}, "name")
				if not dept_name:
					try:
						d = frappe.get_doc({"doctype": "Department", "department_name": jefs_emp.department, "company": company_name}).insert(ignore_permissions=True)
						dept_name = d.name
					except Exception:
						dept_name = None

			branch_name = None
			if jefs_emp.work_location:
				if frappe.db.exists("Branch", jefs_emp.work_location):
					branch_name = jefs_emp.work_location
				else:
					try:
						b = frappe.get_doc({"doctype": "Branch", "branch": jefs_emp.work_location}).insert(ignore_permissions=True)
						branch_name = b.name
					except Exception:
						branch_name = None

			emp_name = jefs_emp.frappe_employee or frappe.db.get_value("Employee", {"employee_number": jefs_emp.employee_code}, "name")
			gender = jefs_emp.gender if jefs_emp.gender in ("Male", "Female", "Other") else "Male"
			if not frappe.db.exists("Gender", gender):
				frappe.get_doc({"doctype": "Gender", "gender": gender}).insert(ignore_permissions=True)

			status = "Left" if jefs_emp.status == "EXITED" else "Active"
			dob = jefs_emp.dob or "1995-01-01"
			latest_sal = frappe.get_all("JEFS Salary Record", filters={"employee_code": jefs_emp.employee_code}, fields=["gross_paise"], order_by="period desc", limit=1)
			annual_ctc = round((int(latest_sal[0]["gross_paise"]) / 100.0) * 12.0, 2) if latest_sal else 0

			if emp_name and frappe.db.exists("Employee", emp_name):
				doc = frappe.get_doc("Employee", emp_name)
			else:
				doc = frappe.new_doc("Employee")
				doc.employee_number = jefs_emp.employee_code
				doc.company = company_name

			doc.first_name = jefs_emp.first_name or jefs_emp.full_name
			doc.last_name = jefs_emp.last_name or ""
			doc.gender = gender
			doc.date_of_birth = dob
			doc.date_of_joining = jefs_emp.date_of_joining
			doc.status = status
			if jefs_emp.date_of_exit:
				doc.relieving_date = jefs_emp.date_of_exit
			if jefs_emp.exit_reason:
				doc.reason_for_leaving = jefs_emp.exit_reason
			if jefs_emp.designation:
				doc.designation = jefs_emp.designation
			if dept_name:
				doc.department = dept_name
			if branch_name:
				doc.branch = branch_name
			doc.cell_number = jefs_emp.mobile or doc.cell_number or ""
			if jefs_emp.email:
				doc.personal_email = jefs_emp.email
			if jefs_emp.uan and frappe.get_meta("Employee").has_field("provident_fund_account"):
				doc.provident_fund_account = jefs_emp.uan
			if jefs_emp.ifsc and frappe.get_meta("Employee").has_field("ifsc_code"):
				doc.ifsc_code = jefs_emp.ifsc
			if jefs_emp.bank_name and frappe.get_meta("Employee").has_field("bank_name"):
				doc.bank_name = jefs_emp.bank_name
			if annual_ctc > 0:
				doc.ctc = annual_ctc
				doc.salary_currency = "INR"

			emp_meta = frappe.get_meta("Employee")
			cf_updates = {
				"jefs_employee": jefs_emp.name,
				"jefs_client_site": jefs_emp.client_site or "",
				"jefs_employment_type": jefs_emp.employment_type or "PERMANENT",
				"jefs_skill_category": jefs_emp.skill_category or "",
				"jefs_aadhaar_masked": jefs_emp.aadhaar_masked or "",
				"jefs_pan_masked": jefs_emp.pan_masked or "",
			}
			for k, v in cf_updates.items():
				if emp_meta.has_field(k):
					doc.set(k, v)

			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)
			if jefs_emp.frappe_employee != doc.name and frappe.db.exists("JEFS Employee", jefs_emp.name):
				frappe.db.set_value("JEFS Employee", jefs_emp.name, "frappe_employee", doc.name, update_modified=False)
			return doc.name
		except Exception:
			frappe.log_error(frappe.get_traceback(), "JEFS Frappe Employee Sync")
			return jefs_emp.frappe_employee


def on_jefs_employee_event(doc, method: str | None = None) -> None:
	if getattr(frappe.flags, "in_jefs_sync", False):
		return
	sync_jefs_to_hr_employee(doc)


def on_hr_employee_update(doc, method: str | None = None) -> None:
	"""Bidirectional hook: keep JEFS Employee synced when HR edits/adds Employee in Frappe HR Desk."""
	if getattr(frappe.flags, "in_jefs_sync", False):
		return
	with _jefs_sync_guard():
		try:
			code = (doc.get("jefs_employee") or doc.employee_number or doc.name or "").strip().upper()
			if not code:
				return
			jefs_name = doc.get("jefs_employee") if (doc.get("jefs_employee") and frappe.db.exists("JEFS Employee", doc.get("jefs_employee"))) else (
				frappe.db.get_value("JEFS Employee", {"frappe_employee": doc.name}, "name")
				or (code if frappe.db.exists("JEFS Employee", code) else None)
			)
			is_new = jefs_name is None
			if is_new:
				jefs = frappe.new_doc("JEFS Employee")
				jefs.employee_code = code
			else:
				jefs = frappe.get_doc("JEFS Employee", jefs_name)

			full = doc.employee_name or f"{doc.first_name or ''} {doc.last_name or ''}".strip() or code
			jefs.full_name = full
			jefs.first_name = doc.first_name or full
			jefs.last_name = doc.last_name or ""
			if doc.gender:
				jefs.gender = doc.gender
			if doc.date_of_birth:
				jefs.dob = str(doc.date_of_birth)
			if doc.date_of_joining:
				jefs.date_of_joining = str(doc.date_of_joining)
			jefs.mobile = doc.cell_number or jefs.mobile or ""
			jefs.email = doc.personal_email or doc.company_email or doc.prefered_email or jefs.email or ""
			if doc.designation:
				jefs.designation = doc.designation
			if doc.department:
				dept_label = frappe.db.get_value("Department", doc.department, "department_name") or doc.department
				jefs.department = dept_label
			if doc.branch:
				jefs.work_location = doc.branch
			if doc.get("jefs_client_site"):
				jefs.client_site = doc.get("jefs_client_site")
			if doc.get("jefs_employment_type") in ("PERMANENT", "FIXED_TERM", "CONTRACT"):
				jefs.employment_type = doc.get("jefs_employment_type")
			if doc.get("jefs_skill_category"):
				jefs.skill_category = doc.get("jefs_skill_category")
			if doc.get("provident_fund_account"):
				jefs.uan = doc.get("provident_fund_account")
			if doc.get("ifsc_code"):
				jefs.ifsc = doc.get("ifsc_code")
			if doc.get("bank_name"):
				jefs.bank_name = doc.get("bank_name")

			jefs.frappe_employee = doc.name
			jefs.status = "EXITED" if doc.status == "Left" else "ACTIVE"
			if doc.relieving_date:
				jefs.date_of_exit = str(doc.relieving_date)
				jefs.last_working_day = str(doc.relieving_date)
			if doc.reason_for_leaving and not jefs.exit_reason:
				up = doc.reason_for_leaving.strip().upper()
				if up in ("RESIGNATION", "RETIREMENT", "END_OF_CONTRACT", "TERMINATION", "ABSCONDING", "DEATH"):
					jefs.exit_reason = up

			jefs.save(ignore_permissions=True)
			if frappe.get_meta("Employee").has_field("jefs_employee") and doc.get("jefs_employee") != jefs.name:
				frappe.db.set_value("Employee", doc.name, "jefs_employee", jefs.name, update_modified=False)

			if jefs.status == "EXITED" and jefs.date_of_exit:
				has_sal = frappe.db.exists("JEFS Salary Record", {"employee_code": jefs.employee_code})
				existing_fnf = frappe.db.exists(
					"JEFS FnF Settlement",
					{"employee_code": jefs.employee_code, "status": ["in", ["DRAFT", "SUBMITTED", "APPROVED"]]},
				)
				if has_sal and not existing_fnf:
					from kesari_jefs.api import initiate_fnf

					frappe.flags.in_jefs_sync = False
					initiate_fnf(jefs.employee_code)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "JEFS HR Employee Reverse Sync")


def sync_jefs_salary_to_hrms(employee_code: str, period: str = "", gross_paise: int = 0) -> str | None:
	"""Sync JEFS Salary Record to HRMS Employee CTC + Salary Structure Assignment."""
	with _jefs_sync_guard():
		try:
			jefs = frappe.get_doc("JEFS Employee", employee_code)
			hr_emp = sync_jefs_to_hr_employee(jefs)
			if not hr_emp or not gross_paise:
				return None
			company = frappe.db.get_value("Employee", hr_emp, "company") or get_default_company()
			if not company:
				return None
			gross_inr = round(int(gross_paise) / 100.0, 2)
			frappe.db.set_value("Employee", hr_emp, {"ctc": round(gross_inr * 12.0, 2), "salary_currency": "INR"}, update_modified=False)

			struct = _ensure_salary_structure(company)
			if not struct:
				return None

			from_dt = f"{period}-01" if (period and len(period) == 7) else str(jefs.date_of_joining or today())
			if frappe.db.get_value("Employee", hr_emp, "date_of_joining") and getdate(from_dt) < getdate(frappe.db.get_value("Employee", hr_emp, "date_of_joining")):
				from_dt = str(frappe.db.get_value("Employee", hr_emp, "date_of_joining"))

			existing = frappe.get_all(
				"Salary Structure Assignment",
				filters={"employee": hr_emp, "from_date": from_dt, "docstatus": ["<", 2]},
				fields=["name", "docstatus", "base"],
				limit=1,
			)
			if existing:
				row = existing[0]
				if row["docstatus"] == 0:
					doc = frappe.get_doc("Salary Structure Assignment", row["name"])
					doc.salary_structure = struct
					doc.base = gross_inr
					doc.save(ignore_permissions=True)
					doc.submit()
					return doc.name
				elif abs(flt(row["base"]) - gross_inr) > 0.01:
					old_doc = frappe.get_doc("Salary Structure Assignment", row["name"])
					old_doc.flags.ignore_permissions = True
					old_doc.cancel()
				else:
					return row["name"]

			ssa = frappe.get_doc(
				{
					"doctype": "Salary Structure Assignment",
					"employee": hr_emp,
					"company": company,
					"salary_structure": struct,
					"from_date": from_dt,
					"base": gross_inr,
					"currency": "INR",
				}
			)
			ssa.flags.ignore_permissions = True
			ssa.insert(ignore_permissions=True)
			ssa.submit()
			return ssa.name
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"JEFS Salary Sync {employee_code}")
			return None


def sync_jefs_leave_to_hrms(employee_code: str, as_of_date: Any, leave_type_code: str, balance: float) -> str | None:
	"""Sync JEFS Leave Record balance into native HRMS Leave Period + Leave Allocation."""
	with _jefs_sync_guard():
		try:
			jefs = frappe.get_doc("JEFS Employee", employee_code)
			hr_emp = sync_jefs_to_hr_employee(jefs)
			if not hr_emp:
				return None
			company = frappe.db.get_value("Employee", hr_emp, "company") or get_default_company()
			if not company:
				return None
			ref_dt = getdate(as_of_date) if as_of_date else getdate(today())
			_, from_d, to_d = _ensure_leave_period(company, ref_dt)
			leave_type = _map_leave_type(leave_type_code)

			existing = frappe.get_all(
				"Leave Allocation",
				filters={"employee": hr_emp, "leave_type": leave_type, "from_date": ["<=", to_d], "to_date": [">=", from_d], "docstatus": ["<", 2]},
				fields=["name", "docstatus", "total_leaves_allocated"],
				limit=1,
			)
			bal_f = max(0.0, float(balance or 0))
			if existing:
				row = existing[0]
				doc = frappe.get_doc("Leave Allocation", row["name"])
				if row["docstatus"] == 0:
					doc.new_leaves_allocated = bal_f
					doc.total_leaves_allocated = bal_f
					doc.save(ignore_permissions=True)
					if bal_f > 0:
						doc.submit()
					return doc.name
				if abs(flt(row["total_leaves_allocated"]) - bal_f) > 0.01:
					doc.new_leaves_allocated = bal_f
					doc.flags.ignore_permissions = True
					doc.save(ignore_permissions=True)
				return doc.name

			if bal_f <= 0:
				return None
			la = frappe.get_doc(
				{
					"doctype": "Leave Allocation",
					"employee": hr_emp,
					"company": company,
					"leave_type": leave_type,
					"from_date": from_d,
					"to_date": to_d,
					"new_leaves_allocated": bal_f,
				}
			)
			la.flags.ignore_permissions = True
			la.insert(ignore_permissions=True)
			la.submit()
			return la.name
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"JEFS Leave Sync {employee_code}")
			return None


def sync_jefs_bonus_to_hrms(employee_code: str, fy: str, bonus_calculated_paise: int, eligible: int = 1) -> str | None:
	"""Sync JEFS Bonus Record into HRMS Additional Salary (for Active employees)."""
	with _jefs_sync_guard():
		try:
			jefs = frappe.get_doc("JEFS Employee", employee_code)
			hr_emp = sync_jefs_to_hr_employee(jefs)
			if not hr_emp or not eligible or not bonus_calculated_paise:
				return None
			if frappe.db.get_value("Employee", hr_emp, "status") != "Active":
				return None
			company = frappe.db.get_value("Employee", hr_emp, "company") or get_default_company()
			if not company:
				return None
			comp_name = _ensure_salary_component("Statutory Bonus", "SBON", "Earning")
			amount_inr = round(int(bonus_calculated_paise) / 100.0, 2)
			year_hint = str(fy or "").split("-")[0]
			payroll_date = f"{year_hint}-10-15" if year_hint.isdigit() and len(year_hint) == 4 else today()

			if frappe.db.exists("Additional Salary", {"employee": hr_emp, "salary_component": comp_name, "payroll_date": payroll_date, "docstatus": ["<", 2]}):
				return None

			ads = frappe.get_doc(
				{
					"doctype": "Additional Salary",
					"employee": hr_emp,
					"company": company,
					"salary_component": comp_name,
					"payroll_date": payroll_date,
					"amount": amount_inr,
					"currency": "INR",
					"overwrite_salary_structure_amount": 0,
				}
			)
			ads.flags.ignore_permissions = True
			ads.insert(ignore_permissions=True)
			ads.submit()
			return ads.name
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"JEFS Bonus Sync {employee_code}")
			return None


def sync_fnf_to_hrms(fnf_doc) -> dict[str, str | None]:
	"""Sync JEFS FnF Settlement into HRMS Employee Separation + Full and Final Statement."""
	if getattr(frappe.flags, "in_jefs_sync", False):
		return {}
	ensure_hrms_custom_fields()
	jefs = frappe.get_doc("JEFS Employee", fnf_doc.employee_code)
	hr_emp = sync_jefs_to_hr_employee(jefs)
	if not hr_emp:
		return {}

	with _jefs_sync_guard():
		out: dict[str, str | None] = {"employee": hr_emp, "separation": None, "fnf_statement": None}
		try:
			company = frappe.db.get_value("Employee", hr_emp, "company") or get_default_company()
			rel_dt = str(fnf_doc.last_working_day or fnf_doc.exit_date or today())
			frappe.db.set_value("Employee", hr_emp, {"status": "Left", "relieving_date": rel_dt}, update_modified=False)

			# 1. Sync Employee Separation (non-blocking if Holiday List is missing for future date)
			try:
				sep_name = frappe.db.get_value("Employee Separation", {"employee": hr_emp, "docstatus": ["<", 2]}, "name")
				if sep_name:
					sep = frappe.get_doc("Employee Separation", sep_name)
				else:
					sep = frappe.new_doc("Employee Separation")
					sep.employee = hr_emp
					sep.company = company
				sep.boarding_begins_on = str(fnf_doc.exit_date or rel_dt)
				sep.resignation_letter_date = str(fnf_doc.exit_date or rel_dt)
				sep.boarding_status = "Completed" if fnf_doc.status == "APPROVED" else "In Process"
				if frappe.get_meta("Employee Separation").has_field("jefs_fnf_settlement"):
					sep.jefs_fnf_settlement = fnf_doc.name
				sep.flags.ignore_permissions = True
				if sep.docstatus == 0:
					sep.save(ignore_permissions=True)
					if fnf_doc.status == "APPROVED":
						try:
							sep.submit()
						except Exception:
							pass
				out["separation"] = sep.name
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"JEFS Separation Link {fnf_doc.name}")

			# 2. Sync native HRMS Full and Final Statement
			fnf_meta = frappe.get_meta("Full and Final Statement")
			existing_fnf_name = None
			if fnf_meta.has_field("jefs_fnf_settlement"):
				existing_fnf_name = frappe.db.get_value(
					"Full and Final Statement",
					{"jefs_fnf_settlement": fnf_doc.name, "docstatus": ["<", 2]},
					"name",
				)
			if not existing_fnf_name:
				existing_fnf_name = frappe.db.get_value(
					"Full and Final Statement",
					{"employee": hr_emp, "docstatus": ["<", 2]},
					"name",
				)

			if existing_fnf_name:
				hrms_fnf = frappe.get_doc("Full and Final Statement", existing_fnf_name)
				if hrms_fnf.docstatus == 1:
					if fnf_doc.status != "APPROVED":
						hrms_fnf.flags.ignore_permissions = True
						hrms_fnf.cancel()
						hrms_fnf = frappe.new_doc("Full and Final Statement")
					else:
						out["fnf_statement"] = hrms_fnf.name
						return out
			else:
				hrms_fnf = frappe.new_doc("Full and Final Statement")

			hrms_fnf.employee = hr_emp
			hrms_fnf.company = company
			hrms_fnf.relieving_date = rel_dt
			hrms_fnf.transaction_date = str((fnf_doc.approved_at.date() if getattr(fnf_doc, "approved_at", None) and hasattr(fnf_doc.approved_at, "date") else fnf_doc.exit_date) or today())
			hrms_fnf.flags.ignore_permissions = True
			if hrms_fnf.is_new():
				# Run initial insert so before_insert defaults are created once before exact JEFS lines override them
				hrms_fnf.insert(ignore_permissions=True)

			row_status = "Settled" if fnf_doc.status == "APPROVED" else "Unsettled"
			hrms_fnf.set("payables", [])
			hrms_fnf.set("receivables", [])
			for line in fnf_doc.lines:
				amt = flt(line.amount_rupees)
				if amt <= 0:
					continue
				row = {
					"component": line.label or line.code,
					"reference_document_type": "JEFS FnF Settlement",
					"reference_document": fnf_doc.name,
					"amount": amt,
					"status": row_status,
					"remark": line.formula_text or line.note or "",
				}
				if line.line_type == "EARNING":
					hrms_fnf.append("payables", row)
				else:
					hrms_fnf.append("receivables", row)

			if fnf_meta.has_field("jefs_fnf_settlement"):
				hrms_fnf.jefs_fnf_settlement = fnf_doc.name
			if fnf_meta.has_field("jefs_status"):
				hrms_fnf.jefs_status = fnf_doc.status
			if fnf_meta.has_field("jefs_tenure"):
				hrms_fnf.jefs_tenure = fnf_doc.tenure_display or ""
			if fnf_meta.has_field("jefs_payment_due_date") and fnf_doc.payment_due_date:
				hrms_fnf.jefs_payment_due_date = str(fnf_doc.payment_due_date)
			if fnf_meta.has_field("jefs_net_payable"):
				hrms_fnf.jefs_net_payable = flt(fnf_doc.net_payable_rupees)

			hrms_fnf.save(ignore_permissions=True)
			if fnf_doc.status == "APPROVED" and hrms_fnf.docstatus == 0 and (hrms_fnf.payables or hrms_fnf.receivables):
				hrms_fnf.submit()
			out["fnf_statement"] = hrms_fnf.name
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"JEFS FnF HRMS Sync {fnf_doc.name}")
		return out


def on_jefs_fnf_event(doc, method: str | None = None) -> None:
	if getattr(frappe.flags, "in_jefs_sync", False):
		return
	sync_fnf_to_hrms(doc)


def on_hr_separation_event(doc, method: str | None = None) -> None:
	"""When HR creates/updates Employee Separation, record exit & draft JEFS FnF."""
	if getattr(frappe.flags, "in_jefs_sync", False):
		return
	try:
		hr_emp_doc = frappe.get_doc("Employee", doc.employee)
		on_hr_employee_update(hr_emp_doc)
		jefs_name = frappe.db.get_value("Employee", doc.employee, "jefs_employee") or frappe.db.get_value("JEFS Employee", {"frappe_employee": doc.employee}, "name")
		if not jefs_name:
			return
		ex_dt = str(doc.boarding_begins_on or doc.resignation_letter_date or today())
		with _jefs_sync_guard():
			jefs = frappe.get_doc("JEFS Employee", jefs_name)
			jefs.date_of_exit = ex_dt
			jefs.last_working_day = ex_dt
			jefs.status = "EXITED"
			jefs.save(ignore_permissions=True)
		frappe.db.set_value("Employee", doc.employee, {"status": "Left", "relieving_date": ex_dt}, update_modified=False)

		if frappe.db.exists("JEFS Salary Record", {"employee_code": jefs_name}):
			existing_fnf = frappe.db.get_value(
				"JEFS FnF Settlement",
				{"employee_code": jefs_name, "status": ["in", ["DRAFT", "SUBMITTED", "APPROVED"]]},
				"name",
			)
			if not existing_fnf:
				from kesari_jefs.api import initiate_fnf

				res = initiate_fnf(jefs_name)
				existing_fnf = res["fnf"]["name"]
			if existing_fnf and frappe.get_meta("Employee Separation").has_field("jefs_fnf_settlement"):
				frappe.db.set_value("Employee Separation", doc.name, "jefs_fnf_settlement", existing_fnf, update_modified=False)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"JEFS Separation Sync {doc.name}")


def on_hr_offer_event(doc, method: str | None = None) -> None:
	"""Sync Job Offer / Appointment Letter designation & dates to matching JEFS Employee if present."""
	if getattr(frappe.flags, "in_jefs_sync", False):
		return
	with _jefs_sync_guard():
		try:
			hr_emp = frappe.db.get_value("Employee", {"job_offer": doc.get("job_offer") or doc.name}, "name")
			if not hr_emp and doc.get("applicant_email"):
				hr_emp = frappe.db.get_value("Employee", {"personal_email": doc.get("applicant_email")}, "name")
			if hr_emp:
				jefs_name = frappe.db.get_value("JEFS Employee", {"frappe_employee": hr_emp}, "name")
				if jefs_name:
					updates = {}
					if doc.get("designation"):
						updates["designation"] = doc.designation
					if doc.get("appointment_date"):
						updates["date_of_joining"] = str(doc.appointment_date)
					if updates:
						frappe.db.set_value("JEFS Employee", jefs_name, updates, update_modified=False)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"JEFS Offer/Appt Sync {doc.name}")


def sync_wage_revision_to_hrms(rev_doc) -> None:
	"""Apply approved JEFS Wage Revision back to Employee CTC & Salary Structure Assignments."""
	eff = str(rev_doc.effective_from or today())[:7]
	for it in rev_doc.items:
		if int(it.proposed_total_paise or 0) > 0:
			sync_jefs_salary_to_hrms(it.employee_code, period=eff, gross_paise=int(it.proposed_total_paise))


def sync_all_hrms_records() -> dict[str, int]:
	"""Backfill and synchronize all JEFS and Frappe HR entities bidirectionally."""
	ensure_hrms_custom_fields()
	counts = {"employees": 0, "salaries": 0, "leaves": 0, "bonuses": 0, "fnf_statements": 0}

	for code in frappe.get_all("JEFS Employee", pluck="employee_code"):
		emp = frappe.get_doc("JEFS Employee", code)
		if sync_jefs_to_hr_employee(emp):
			counts["employees"] += 1

	for hr_name in frappe.get_all("Employee", pluck="name"):
		hr_doc = frappe.get_doc("Employee", hr_name)
		if not hr_doc.get("jefs_employee"):
			on_hr_employee_update(hr_doc)

	sals = frappe.get_all("JEFS Salary Record", fields=["employee_code", "period", "gross_paise"], order_by="period asc")
	for s in sals:
		if sync_jefs_salary_to_hrms(s["employee_code"], period=s["period"], gross_paise=s["gross_paise"]):
			counts["salaries"] += 1

	leaves = frappe.get_all("JEFS Leave Record", fields=["employee_code", "as_of_date", "leave_type", "balance"], order_by="as_of_date asc")
	for lv in leaves:
		if sync_jefs_leave_to_hrms(lv["employee_code"], lv["as_of_date"], lv["leave_type"], lv["balance"]):
			counts["leaves"] += 1

	bonuses = frappe.get_all("JEFS Bonus Record", fields=["employee_code", "fy", "bonus_calculated_paise", "eligible"])
	for b in bonuses:
		if sync_jefs_bonus_to_hrms(b["employee_code"], b["fy"], b["bonus_calculated_paise"], b["eligible"]):
			counts["bonuses"] += 1

	for fnf_name in frappe.get_all("JEFS FnF Settlement", filters={"status": ["in", ["DRAFT", "SUBMITTED", "APPROVED"]]}, pluck="name", order_by="version asc"):
		res = sync_fnf_to_hrms(frappe.get_doc("JEFS FnF Settlement", fnf_name))
		if res.get("fnf_statement"):
			counts["fnf_statements"] += 1

	return counts
