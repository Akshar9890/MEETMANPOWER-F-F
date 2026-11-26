"""Whitelisted REST/RPC APIs for Kesari Manpower JEFS."""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import uuid
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import frappe
from frappe.utils import getdate, now_datetime

from kesari_jefs.engine.fnf import FnfInput, ManualLine, calc_fnf, calc_payment_due_date
from kesari_jefs.engine.money import (
	amount_in_words_inr,
	paise_to_rupees_int,
	paise_to_rupees_str,
	rupees_to_paise,
)
from kesari_jefs.engine.tenure import calc_tenure
from kesari_jefs.engine.validators import (
	clean_aadhaar,
	mask_aadhaar,
	mask_bank_account,
	mask_pan,
	parse_date,
	validate_nominee_shares,
)
from kesari_jefs.engine.wage_revision import (
	MinWageEntry,
	WageRevisionEmployee,
	propose_wage_revision,
)
from kesari_jefs.services.crypto import decrypt_field, encrypt_field
from kesari_jefs.services.doc_service import (
	ALLOWED_PLACEHOLDERS,
	convert_docx_to_pdf,
	convert_html_to_pdf,
	extract_docx_placeholders,
	extract_pdf_text,
	merge_pdfs,
	render_docx_bytes,
	sha256_bytes,
)
from kesari_jefs.services.excel_service import (
	FEED_FIELD_ALIASES,
	build_sample_feed_xlsx,
	build_xlsx_bytes,
	read_tabular_rows,
	suggest_column_mapping,
	validate_mapped_rows,
)
from kesari_jefs.services.hrms_bridge import (
	sync_all_hrms_records,
	sync_fnf_to_hrms,
	sync_jefs_bonus_to_hrms,
	sync_jefs_leave_to_hrms,
	sync_jefs_salary_to_hrms,
	sync_wage_revision_to_hrms,
)
from kesari_jefs.services.jefs_core import (
	get_files_root,
	get_user_jefs_roles,
	next_ref_no,
	require_jefs_role,
	resolve_fnf_settings,
	resolve_site_rule,
	sync_to_frappe_employee,
	write_audit_log,
)
from kesari_jefs.services.pdf_layouts import render_fnf_statement_html, render_id_card_html
from kesari_jefs.services.watcher_service import check_watcher_source

ALL_JEFS_ROLES = (
	"JEFS Admin",
	"JEFS HR Onboarding",
	"JEFS Payroll Specialist",
	"JEFS Exit Desk",
	"JEFS Approver",
	"JEFS Auditor",
)


def _fmt_date(val: Any) -> str:
	if not val:
		return ""
	d = parse_date(val)
	return d.strftime("%d-%m-%Y") if d else str(val)


def _binary_response(data: bytes, filename: str, content_type: str) -> None:
	frappe.local.response.filename = filename
	frappe.local.response.filecontent = data
	frappe.local.response.type = "download"
	frappe.local.response.content_type = content_type


def _company_dict() -> dict[str, Any]:
	p = frappe.get_single("JEFS Company Profile")
	return {
		"legal_name": p.legal_name or "KESARI MANPOWER SOLUTIONS",
		"short_name": p.short_name or "Kesari Manpower",
		"address": p.address or "",
		"phone": p.phone or "",
		"email": p.email or "",
		"website": p.website or "",
		"pf_code": p.pf_code or "",
		"esi_code": p.esi_code or "",
		"signatory_name": p.signatory_name or "Meet Vyas",
		"signatory_designation": p.signatory_designation or "Partner",
		"signature_image_path": p.signature_image_path or "",
		"seal_image_path": p.seal_image_path or "",
		"logo_image_path": p.logo_image_path or "",
		"default_state": p.default_state or "Gujarat",
		"ref_prefix": p.ref_prefix or "KM",
		"gotenberg_url": p.gotenberg_url or "http://gotenberg:3000",
		"working_days": p.working_days or "0,1,2,3,4,5",
	}


def _employee_readiness(emp: dict[str, Any], latest_sal: dict[str, Any] | None, nominee_count: int) -> dict[str, Any]:
	"""Compute readiness & exact missing fields for all 6 joining/police documents."""
	missing_common = []
	for fld in ("full_name", "date_of_joining", "designation", "client_site"):
		if not emp.get(fld):
			missing_common.append(fld)

	offer_miss = list(missing_common)
	if not latest_sal:
		offer_miss.append("salary_record (DOC_SALARY_MISSING)")

	appt_miss = list(offer_miss)
	if not emp.get("father_or_husband_name"):
		appt_miss.append("father_or_husband_name")
	if not emp.get("dob"):
		appt_miss.append("dob")

	gratuity_miss = list(missing_common)
	if nominee_count == 0:
		gratuity_miss.append("nominees (DOC_NOMINEE_MISSING)")

	epfo_miss = list(missing_common)
	if not emp.get("father_or_husband_name"):
		epfo_miss.append("father_or_husband_name")
	if not emp.get("dob"):
		epfo_miss.append("dob")

	id_miss = list(missing_common)
	if not emp.get("photo_path") or not os.path.exists(str(emp.get("photo_path") or "")):
		id_miss.append("photo (DOC_PHOTO_MISSING)")

	police_miss = list(missing_common)
	if not emp.get("father_or_husband_name"):
		police_miss.append("father_or_husband_name")
	if not emp.get("present_address"):
		police_miss.append("present_address")
	if not emp.get("permanent_address"):
		police_miss.append("permanent_address")

	return {
		"OFFER_LETTER": {"ready": len(offer_miss) == 0, "missing": offer_miss},
		"APPOINTMENT_LETTER": {"ready": len(appt_miss) == 0, "missing": appt_miss},
		"GRATUITY_FORM_F": {"ready": len(gratuity_miss) == 0, "missing": gratuity_miss},
		"ID_CARD": {"ready": len(id_miss) == 0, "missing": id_miss},
		"EPFO_FORM_2": {"ready": len(epfo_miss) == 0, "missing": epfo_miss},
		"POLICE_VERIFICATION": {"ready": len(police_miss) == 0, "missing": police_miss},
	}


@frappe.whitelist()
def get_bootstrap() -> dict[str, Any]:
	require_jefs_role(ALL_JEFS_ROLES)
	today = dt.date.today()
	month_start = today.replace(day=1)

	active_count = frappe.db.count("JEFS Employee", {"status": "ACTIVE"})
	exited_count = frappe.db.count("JEFS Employee", {"status": "EXITED"})
	joiners_month = frappe.db.count("JEFS Employee", {"date_of_joining": [">=", month_start.isoformat()]})

	exited_emps = frappe.get_all(
		"JEFS Employee",
		filters={"status": "EXITED"},
		fields=["employee_code", "full_name", "date_of_exit", "last_working_day"],
	)
	fnfs = frappe.get_all(
		"JEFS FnF Settlement",
		fields=["name", "employee_code", "status", "payment_due_date", "net_payable_rupees"],
	)
	fnf_by_emp = {f["employee_code"]: f for f in fnfs}

	pending_fnf = 0
	overdue_fnf = 0
	awaiting_approval = 0
	settings = resolve_fnf_settings(today)
	for e in exited_emps:
		fnf = fnf_by_emp.get(e["employee_code"])
		if not fnf or fnf["status"] in ("DRAFT", "SUBMITTED"):
			pending_fnf += 1
			ex_dt = parse_date(e.get("date_of_exit"))
			if ex_dt:
				due = calc_payment_due_date(ex_dt, settings.payment_due_working_days, settings.working_weekdays)
				if today > due:
					overdue_fnf += 1
		if fnf and fnf["status"] == "SUBMITTED":
			awaiting_approval += 1

	last_uploads = {}
	for feed in ("EMPLOYEE", "SALARY", "BONUS", "LEAVE"):
		b = frappe.get_all(
			"JEFS Upload Batch",
			filters={"feed": feed, "status": "COMMITTED"},
			fields=["name", "file_name", "ok_rows", "uploaded_by", "committed_at"],
			order_by="committed_at desc",
			limit=1,
		)
		last_uploads[feed] = b[0] if b else None

	# Missing data count across active employees
	emps_all = frappe.get_all("JEFS Employee", fields=["employee_code", "full_name", "father_or_husband_name", "dob", "present_address", "permanent_address", "designation", "client_site", "date_of_joining", "photo_path"])
	missing_data_count = 0
	for e in emps_all:
		if not e.get("father_or_husband_name") or not e.get("dob") or not e.get("present_address"):
			missing_data_count += 1

	docs_total = frappe.db.count("JEFS Generated Document", {"is_void": 0})

	return {
		"user": frappe.session.user,
		"roles": sorted(get_user_jefs_roles()),
		"company": _company_dict(),
		"stats": {
			"active_employees": active_count,
			"exited_employees": exited_count,
			"joiners_this_month": joiners_month,
			"pending_fnf": pending_fnf,
			"overdue_fnf": overdue_fnf,
			"awaiting_approval": awaiting_approval,
			"docs_generated": docs_total,
			"missing_data_count": missing_data_count,
		},
		"last_uploads": last_uploads,
		"site_rules": frappe.get_all("JEFS Client Site Rule", fields=["site_code", "site_name", "include_bonus", "include_leave", "include_gratuity"]),
	}


@frappe.whitelist()
def download_sample_template(feed: str) -> None:
	require_jefs_role(("JEFS HR Onboarding", "JEFS Payroll Specialist", "JEFS Exit Desk"))
	f_up = feed.strip().upper()
	if f_up not in FEED_FIELD_ALIASES:
		frappe.throw("Invalid feed type")
	data = build_sample_feed_xlsx(f_up)
	_binary_response(
		data,
		f"kesari_{f_up.lower()}_sample.xlsx",
		"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
	)


@frappe.whitelist()
def upload_feed_file(feed: str, period: str = "", fy: str = "") -> dict[str, Any]:
	require_jefs_role(("JEFS HR Onboarding", "JEFS Payroll Specialist", "JEFS Exit Desk"))
	f_up = feed.strip().upper()
	if f_up not in FEED_FIELD_ALIASES:
		frappe.throw("Invalid feed type")
	if not frappe.request.files or "file" not in frappe.request.files:
		frappe.throw("No file uploaded")

	file_obj = frappe.request.files["file"]
	file_bytes = file_obj.read()
	filename = file_obj.filename or f"{f_up.lower()}.xlsx"

	headers, rows = read_tabular_rows(file_bytes, filename)
	saved_map_str = frappe.db.get_value("JEFS Column Mapping", f_up, "mapping_json")
	saved_map = json.loads(saved_map_str) if saved_map_str else {}
	mapping = suggest_column_mapping(f_up, headers, saved_map)

	existing_codes = set(frappe.get_all("JEFS Employee", pluck="employee_code"))
	valid_rows, error_rows, missing_req = validate_mapped_rows(
		f_up,
		rows,
		mapping,
		existing_employee_codes=existing_codes if f_up != "EMPLOYEE" else None,
		default_period=period,
		default_fy=fy,
	)

	uploads_dir = get_files_root() / "uploads"
	batch_uid = uuid.uuid4().hex[:10]
	saved_path = uploads_dir / f"{f_up}_{batch_uid}_{os.path.basename(filename)}"
	saved_path.write_bytes(file_bytes)
	file_hash = sha256_bytes(file_bytes)

	batch = frappe.get_doc(
		{
			"doctype": "JEFS Upload Batch",
			"feed": f_up,
			"file_name": filename,
			"file_path": str(saved_path),
			"sha256": file_hash,
			"period": period,
			"fy": fy,
			"total_rows": len(rows),
			"ok_rows": len(valid_rows),
			"error_rows": len(error_rows),
			"status": "VALIDATED",
			"column_mapping_json": json.dumps(mapping),
			"valid_rows_json": json.dumps(valid_rows, default=str),
			"error_rows_json": json.dumps(error_rows, default=str),
			"missing_required_json": json.dumps(missing_req),
			"uploaded_by": frappe.session.user,
		}
	)
	batch.insert(ignore_permissions=True)
	write_audit_log("UPLOAD_VALIDATE", "JEFS Upload Batch", batch.name, after={"feed": f_up, "sha256": file_hash, "total": len(rows), "ok": len(valid_rows), "errors": len(error_rows)})
	frappe.db.commit()

	return {
		"batch_id": batch.name,
		"feed": f_up,
		"file_name": filename,
		"headers": headers,
		"mapping": mapping,
		"system_fields": list(FEED_FIELD_ALIASES[f_up].keys()),
		"missing_required": missing_req,
		"total_rows": len(rows),
		"ok_rows": len(valid_rows),
		"error_rows": len(error_rows),
		"preview_valid": valid_rows[:25],
		"preview_errors": error_rows[:50],
		"status": batch.status,
	}


@frappe.whitelist()
def update_batch_mapping(batch_id: str, mapping_json: str) -> dict[str, Any]:
	require_jefs_role(("JEFS HR Onboarding", "JEFS Payroll Specialist", "JEFS Exit Desk"))
	batch = frappe.get_doc("JEFS Upload Batch", batch_id)
	if batch.status != "VALIDATED":
		frappe.throw("UPL_ALREADY_COMMITTED: Batch cannot be modified after commit/discard.")
	mapping = json.loads(mapping_json)
	file_bytes = Path(batch.file_path).read_bytes()
	headers, rows = read_tabular_rows(file_bytes, batch.file_name)

	existing_codes = set(frappe.get_all("JEFS Employee", pluck="employee_code"))
	valid_rows, error_rows, missing_req = validate_mapped_rows(
		batch.feed,
		rows,
		mapping,
		existing_employee_codes=existing_codes if batch.feed != "EMPLOYEE" else None,
		default_period=batch.period or "",
		default_fy=batch.fy or "",
	)

	if frappe.db.exists("JEFS Column Mapping", batch.feed):
		frappe.db.set_value("JEFS Column Mapping", batch.feed, "mapping_json", json.dumps(mapping))
	else:
		frappe.get_doc({"doctype": "JEFS Column Mapping", "feed": batch.feed, "mapping_json": json.dumps(mapping)}).insert(ignore_permissions=True)

	batch.column_mapping_json = json.dumps(mapping)
	batch.valid_rows_json = json.dumps(valid_rows, default=str)
	batch.error_rows_json = json.dumps(error_rows, default=str)
	batch.missing_required_json = json.dumps(missing_req)
	batch.ok_rows = len(valid_rows)
	batch.error_rows = len(error_rows)
	batch.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		"batch_id": batch.name,
		"headers": headers,
		"mapping": mapping,
		"missing_required": missing_req,
		"total_rows": len(rows),
		"ok_rows": len(valid_rows),
		"error_rows": len(error_rows),
		"preview_valid": valid_rows[:25],
		"preview_errors": error_rows[:50],
	}


@frappe.whitelist()
def download_batch_errors(batch_id: str) -> None:
	require_jefs_role(("JEFS HR Onboarding", "JEFS Payroll Specialist", "JEFS Exit Desk", "JEFS Auditor"))
	batch = frappe.get_doc("JEFS Upload Batch", batch_id)
	error_rows = json.loads(batch.error_rows_json or "[]")
	all_keys: list[str] = []
	for er in error_rows:
		for k in (er.get("raw") or {}).keys():
			if k not in all_keys:
				all_keys.append(k)
	headers = ["Row", "Status", "Errors"] + all_keys
	data_rows = []
	for er in error_rows:
		raw = er.get("raw") or {}
		data_rows.append([er.get("row_num"), "ERROR", er.get("errors")] + [raw.get(k, "") for k in all_keys])
	xlsx = build_xlsx_bytes([("Validation Errors", headers, data_rows)])
	_binary_response(
		xlsx,
		f"{batch.name}_errors.xlsx",
		"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
	)


@frappe.whitelist()
def list_upload_batches() -> list[dict[str, Any]]:
	require_jefs_role(ALL_JEFS_ROLES)
	return frappe.get_all(
		"JEFS Upload Batch",
		fields=["name", "feed", "file_name", "period", "fy", "total_rows", "ok_rows", "error_rows", "status", "uploaded_by", "committed_at", "creation"],
		order_by="creation desc",
		limit=50,
	)


@frappe.whitelist()
def commit_batch(batch_id: str) -> dict[str, Any]:
	require_jefs_role(("JEFS HR Onboarding", "JEFS Payroll Specialist", "JEFS Exit Desk"))
	batch = frappe.get_doc("JEFS Upload Batch", batch_id)
	if batch.status != "VALIDATED":
		frappe.throw("UPL_ALREADY_COMMITTED: This batch is already committed or discarded.")
	missing_req = json.loads(batch.missing_required_json or "[]")
	if missing_req:
		frappe.throw(f"UPL_REQUIRED_COLUMN_UNMAPPED: Map required column(s): {', '.join(missing_req)}")

	valid_rows = json.loads(batch.valid_rows_json or "[]")
	inserted = 0
	updated = 0

	if batch.feed == "EMPLOYEE":
		for r in valid_rows:
			code = r["employee_code"]
			is_existing = frappe.db.exists("JEFS Employee", code)
			emp = frappe.get_doc("JEFS Employee", code) if is_existing else frappe.new_doc("JEFS Employee")
			emp.employee_code = code
			changes: dict[str, list[Any]] = {}

			plain_fields = [
				"full_name", "first_name", "middle_name", "last_name", "father_or_husband_name",
				"gender", "dob", "marital_status", "blood_group", "mobile", "email",
				"present_address", "permanent_address", "present_city", "present_state", "present_pin",
				"uan", "esic_ip_no", "ifsc", "bank_name", "designation", "department",
				"skill_category", "work_location", "client_site", "employment_type",
				"contract_end_date", "date_of_joining", "notice_period_days",
				"date_of_exit", "last_working_day", "exit_reason", "conduct",
				"emergency_contact_name", "emergency_contact_phone", "police_station", "id_proof_type",
			]
			for pf in plain_fields:
				if pf in r and r[pf] not in (None, ""):
					old_v = emp.get(pf)
					new_v = r[pf]
					if pf in ("dob", "contract_end_date", "date_of_joining", "date_of_exit", "last_working_day"):
						new_v = str(new_v)
					if pf == "gender":
						g_up = str(new_v).strip().upper()
						new_v = "Female" if g_up.startswith("F") else ("Other" if g_up.startswith("O") else "Male")
					if pf == "employment_type":
						et = str(new_v).strip().upper().replace("-", "_").replace(" ", "_")
						new_v = et if et in ("PERMANENT", "FIXED_TERM", "CONTRACT") else "PERMANENT"
					if str(old_v or "") != str(new_v):
						if is_existing:
							changes[pf] = [str(old_v or ""), str(new_v)]
						emp.set(pf, new_v)

			if not emp.first_name and emp.full_name:
				parts = emp.full_name.split()
				emp.first_name = parts[0]
				emp.last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

			if r.get("aadhaar"):
				digits = clean_aadhaar(r["aadhaar"])
				emp.aadhaar_encrypted = encrypt_field(digits)
				emp.aadhaar_masked = mask_aadhaar(digits)
			if r.get("pan"):
				p_str = str(r["pan"]).strip().upper()
				emp.pan_encrypted = encrypt_field(p_str)
				emp.pan_masked = mask_pan(p_str)
			if r.get("bank_account"):
				b_str = str(r["bank_account"]).strip()
				emp.bank_account_encrypted = encrypt_field(b_str)
				emp.bank_account_masked = mask_bank_account(b_str)
			if r.get("id_proof_number"):
				id_str = str(r["id_proof_number"]).strip()
				emp.id_proof_encrypted = encrypt_field(id_str)
				emp.id_proof_masked = mask_bank_account(id_str)

			emp.status = "EXITED" if emp.date_of_exit else "ACTIVE"
			emp.source_batch = batch.name

			if r.get("nominee_name"):
				# Upsert single nominee from Excel if provided
				existing_noms = [n for n in emp.nominees if n.nominee_name == r["nominee_name"]]
				if not existing_noms:
					emp.append(
						"nominees",
						{
							"purpose": "GRATUITY",
							"nominee_name": r["nominee_name"],
							"relationship": r.get("nominee_relation") or "Family",
							"dob": parse_date(r.get("nominee_dob")) or None,
							"share_pct": float(r.get("nominee_share_pct") or 100),
						},
					)

			if is_existing and changes:
				emp.append(
					"history",
					{
						"batch_id": batch.name,
						"changed_fields_json": json.dumps(changes),
						"changed_at": now_datetime(),
					},
				)

			emp.save(ignore_permissions=True)
			frappe_emp = sync_to_frappe_employee(emp)
			if frappe_emp and emp.frappe_employee != frappe_emp:
				frappe.db.set_value("JEFS Employee", emp.name, "frappe_employee", frappe_emp)

			if is_existing:
				updated += 1
			else:
				inserted += 1

	elif batch.feed == "SALARY":
		for r in valid_rows:
			existing_name = frappe.db.get_value(
				"JEFS Salary Record",
				{"employee_code": r["employee_code"], "period": r["period"]},
				"name",
			)
			doc = frappe.get_doc("JEFS Salary Record", existing_name) if existing_name else frappe.new_doc("JEFS Salary Record")
			doc.employee_code = r["employee_code"]
			doc.batch_id = batch.name
			doc.period = r["period"]
			for k in (
				"basic_paise", "da_paise", "hra_paise", "conveyance_paise",
				"special_allowance_paise", "gross_paise", "pf_ee_paise",
				"esi_ee_paise", "pt_paise", "net_paise", "days_in_month", "days_paid",
			):
				doc.set(k, r.get(k, 0))
			doc.save(ignore_permissions=True)
			sync_jefs_salary_to_hrms(r["employee_code"], period=r["period"], gross_paise=r.get("gross_paise", 0))
			if existing_name:
				updated += 1
			else:
				inserted += 1

	elif batch.feed == "BONUS":
		for r in valid_rows:
			existing_name = frappe.db.get_value(
				"JEFS Bonus Record",
				{"employee_code": r["employee_code"], "fy": r["fy"]},
				"name",
			)
			doc = frappe.get_doc("JEFS Bonus Record", existing_name) if existing_name else frappe.new_doc("JEFS Bonus Record")
			doc.employee_code = r["employee_code"]
			doc.batch_id = batch.name
			doc.fy = r["fy"]
			doc.eligible = r["eligible"]
			doc.working_days = r["working_days"]
			doc.bonus_wage_paise = r["bonus_wage_paise"]
			doc.bonus_pct = r["bonus_pct"]
			doc.bonus_calculated_paise = r["bonus_calculated_paise"]
			doc.bonus_paid_paise = r["bonus_paid_paise"]
			doc.save(ignore_permissions=True)
			sync_jefs_bonus_to_hrms(r["employee_code"], r["fy"], r["bonus_calculated_paise"], r["eligible"])
			if existing_name:
				updated += 1
			else:
				inserted += 1

	elif batch.feed == "LEAVE":
		for r in valid_rows:
			existing_name = frappe.db.get_value(
				"JEFS Leave Record",
				{"employee_code": r["employee_code"], "as_of_date": r["as_of_date"], "leave_type": r["leave_type"]},
				"name",
			)
			doc = frappe.get_doc("JEFS Leave Record", existing_name) if existing_name else frappe.new_doc("JEFS Leave Record")
			doc.employee_code = r["employee_code"]
			doc.batch_id = batch.name
			doc.as_of_date = r["as_of_date"]
			doc.leave_type = r["leave_type"]
			doc.opening = r["opening"]
			doc.accrued = r["accrued"]
			doc.taken = r["taken"]
			doc.encashed = r["encashed"]
			doc.balance = r["balance"]
			doc.save(ignore_permissions=True)
			sync_jefs_leave_to_hrms(r["employee_code"], r["as_of_date"], r["leave_type"], r["balance"])
			if existing_name:
				updated += 1
			else:
				inserted += 1

	batch.status = "COMMITTED"
	batch.committed_at = now_datetime()
	batch.save(ignore_permissions=True)
	write_audit_log("UPLOAD_COMMIT", "JEFS Upload Batch", batch.name, after={"inserted": inserted, "updated": updated, "skipped": batch.error_rows})
	frappe.db.commit()
	return {"batch_id": batch.name, "inserted": inserted, "updated": updated, "skipped": batch.error_rows}


@frappe.whitelist()
def discard_batch(batch_id: str) -> dict[str, Any]:
	require_jefs_role(("JEFS HR Onboarding", "JEFS Payroll Specialist", "JEFS Exit Desk"))
	batch = frappe.get_doc("JEFS Upload Batch", batch_id)
	batch.status = "DISCARDED"
	batch.save(ignore_permissions=True)
	write_audit_log("UPLOAD_DISCARD", "JEFS Upload Batch", batch.name)
	frappe.db.commit()
	return {"batch_id": batch.name, "status": "DISCARDED"}


@frappe.whitelist()
def upload_photos_zip() -> dict[str, Any]:
	require_jefs_role(("JEFS HR Onboarding",))
	if not frappe.request.files or "file" not in frappe.request.files:
		frappe.throw("No ZIP file uploaded")
	data = frappe.request.files["file"].read()
	photos_dir = get_files_root() / "photos"
	matched = []
	unmatched = []
	with zipfile.ZipFile(io.BytesIO(data)) as z:
		for member in z.infolist():
			if member.is_dir():
				continue
			base = os.path.basename(member.filename)
			if "." not in base:
				continue
			code, ext = base.rsplit(".", 1)
			ext = ext.lower()
			if ext not in ("jpg", "jpeg", "png"):
				continue
			code_clean = code.strip().upper()
			if frappe.db.exists("JEFS Employee", code_clean):
				img_bytes = z.read(member.filename)
				dest = photos_dir / f"{code_clean}.{ext}"
				dest.write_bytes(img_bytes)
				frappe.db.set_value("JEFS Employee", code_clean, "photo_path", str(dest))
				matched.append(code_clean)
			else:
				unmatched.append(base)
	write_audit_log("PHOTOS_UPLOAD", "JEFS Employee", "", after={"matched": len(matched), "unmatched": unmatched})
	frappe.db.commit()
	return {"matched": matched, "unmatched": unmatched}


@frappe.whitelist()
def list_employees(q: str = "", status: str = "", site: str = "", joined_from: str = "", joined_to: str = "") -> list[dict[str, Any]]:
	require_jefs_role(ALL_JEFS_ROLES)
	filters: dict[str, Any] = {}
	if status:
		filters["status"] = status
	if site:
		filters["client_site"] = ["like", f"%{site}%"]

	rows = frappe.get_all(
		"JEFS Employee",
		filters=filters,
		fields=[
			"employee_code", "full_name", "father_or_husband_name", "dob", "mobile",
			"aadhaar_masked", "pan_masked", "designation", "department", "skill_category",
			"client_site", "work_location", "employment_type", "date_of_joining",
			"date_of_exit", "last_working_day", "present_address", "permanent_address",
			"photo_path", "status", "frappe_employee",
		],
		order_by="date_of_joining desc",
		limit=500,
	)

	sals = frappe.get_all("JEFS Salary Record", fields=["employee_code", "period", "gross_paise"], order_by="period desc")
	sal_map: dict[str, dict[str, Any]] = {}
	for s in sals:
		sal_map.setdefault(s["employee_code"], s)

	noms = frappe.db.sql("SELECT parent, COUNT(*) AS cnt FROM `tabJEFS Employee Nominee` GROUP BY parent", as_dict=True)
	nom_map = {n["parent"]: n["cnt"] for n in noms}

	q_low = q.strip().lower()
	jf = parse_date(joined_from)
	jt = parse_date(joined_to)
	out = []
	for r in rows:
		if q_low and q_low not in f"{r['employee_code']} {r['full_name']} {r.get('client_site','')} {r.get('designation','')}".lower():
			continue
		doj = parse_date(r.get("date_of_joining"))
		if jf and doj and doj < jf:
			continue
		if jt and doj and doj > jt:
			continue
		readiness = _employee_readiness(r, sal_map.get(r["employee_code"]), nom_map.get(r["employee_code"], 0))
		r["readiness"] = readiness
		r["kit_ready"] = all(v["ready"] for v in readiness.values())
		r["latest_gross_rupees"] = paise_to_rupees_int(sal_map[r["employee_code"]]["gross_paise"]) if r["employee_code"] in sal_map else None
		out.append(r)
	return out


@frappe.whitelist()
def get_employee_detail(employee_code: str) -> dict[str, Any]:
	require_jefs_role(ALL_JEFS_ROLES)
	emp = frappe.get_doc("JEFS Employee", employee_code)
	salaries = frappe.get_all("JEFS Salary Record", filters={"employee_code": employee_code}, fields=["*"], order_by="period desc")
	bonuses = frappe.get_all("JEFS Bonus Record", filters={"employee_code": employee_code}, fields=["*"], order_by="fy desc")
	leaves = frappe.get_all("JEFS Leave Record", filters={"employee_code": employee_code}, fields=["*"], order_by="as_of_date desc")
	docs = frappe.get_all("JEFS Generated Document", filters={"employee_code": employee_code}, fields=["*"], order_by="generated_at desc")
	fnfs = frappe.get_all("JEFS FnF Settlement", filters={"employee_code": employee_code}, fields=["*"], order_by="version desc")

	return {
		"employee": {
			"employee_code": emp.employee_code,
			"full_name": emp.full_name,
			"father_or_husband_name": emp.father_or_husband_name,
			"gender": emp.gender,
			"dob": str(emp.dob or ""),
			"marital_status": emp.marital_status,
			"blood_group": emp.blood_group,
			"mobile": emp.mobile,
			"email": emp.email,
			"present_address": emp.present_address,
			"permanent_address": emp.permanent_address,
			"present_city": emp.present_city,
			"present_state": emp.present_state,
			"present_pin": emp.present_pin,
			"aadhaar_masked": emp.aadhaar_masked,
			"pan_masked": emp.pan_masked,
			"bank_account_masked": emp.bank_account_masked,
			"ifsc": emp.ifsc,
			"bank_name": emp.bank_name,
			"uan": emp.uan,
			"esic_ip_no": emp.esic_ip_no,
			"designation": emp.designation,
			"department": emp.department,
			"skill_category": emp.skill_category,
			"work_location": emp.work_location,
			"client_site": emp.client_site,
			"zone": emp.zone,
			"employment_type": emp.employment_type,
			"date_of_joining": str(emp.date_of_joining or ""),
			"notice_period_days": emp.notice_period_days,
			"date_of_exit": str(emp.date_of_exit or ""),
			"last_working_day": str(emp.last_working_day or ""),
			"exit_reason": emp.exit_reason,
			"conduct": emp.conduct,
			"emergency_contact_name": emp.emergency_contact_name,
			"emergency_contact_phone": emp.emergency_contact_phone,
			"police_station": emp.police_station,
			"id_proof_type": emp.id_proof_type,
			"id_proof_masked": emp.id_proof_masked,
			"has_photo": bool(emp.photo_path and os.path.exists(emp.photo_path)),
			"status": emp.status,
			"source_batch": emp.source_batch,
		},
		"nominees": [
			{
				"purpose": n.purpose,
				"nominee_name": n.nominee_name,
				"relationship": n.relationship,
				"dob": str(n.dob or ""),
				"address": n.address,
				"share_pct": n.share_pct,
				"is_minor": n.is_minor,
				"guardian_name": n.guardian_name,
			}
			for n in emp.nominees
		],
		"history": [
			{"batch_id": h.batch_id, "changed_fields_json": h.changed_fields_json, "changed_at": str(h.changed_at)}
			for h in emp.history
		],
		"salaries": salaries,
		"bonuses": bonuses,
		"leaves": leaves,
		"documents": docs,
		"fnfs": fnfs,
	}


@frappe.whitelist()
def reveal_employee_pii(employee_code: str) -> dict[str, str]:
	require_jefs_role(("JEFS Admin", "JEFS HR Onboarding", "JEFS Approver"))
	emp = frappe.get_doc("JEFS Employee", employee_code)
	write_audit_log("PII_REVEAL", "JEFS Employee", employee_code)
	frappe.db.commit()
	return {
		"aadhaar": decrypt_field(emp.aadhaar_encrypted),
		"pan": decrypt_field(emp.pan_encrypted),
		"bank_account": decrypt_field(emp.bank_account_encrypted),
		"id_proof_number": decrypt_field(emp.id_proof_encrypted),
	}


@frappe.whitelist()
def save_employee(employee_code: str, data_json: str) -> dict[str, Any]:
	require_jefs_role(("JEFS HR Onboarding", "JEFS Exit Desk"))
	data = json.loads(data_json)
	emp = frappe.get_doc("JEFS Employee", employee_code)
	for fld in (
		"full_name", "father_or_husband_name", "gender", "dob", "marital_status", "blood_group",
		"mobile", "email", "present_address", "permanent_address", "designation", "department",
		"skill_category", "work_location", "client_site", "zone", "employment_type",
		"date_of_joining", "notice_period_days", "uan", "esic_ip_no", "ifsc", "bank_name",
		"emergency_contact_name", "emergency_contact_phone", "police_station", "conduct",
	):
		if fld in data:
			emp.set(fld, data[fld])
	if data.get("aadhaar"):
		d = clean_aadhaar(data["aadhaar"])
		emp.aadhaar_encrypted = encrypt_field(d)
		emp.aadhaar_masked = mask_aadhaar(d)
	if data.get("pan"):
		p = str(data["pan"]).strip().upper()
		emp.pan_encrypted = encrypt_field(p)
		emp.pan_masked = mask_pan(p)
	if data.get("bank_account"):
		b = str(data["bank_account"]).strip()
		emp.bank_account_encrypted = encrypt_field(b)
		emp.bank_account_masked = mask_bank_account(b)
	emp.save(ignore_permissions=True)
	sync_to_frappe_employee(emp)
	write_audit_log("EMPLOYEE_UPDATE", "JEFS Employee", employee_code)
	frappe.db.commit()
	return {"employee_code": emp.employee_code, "status": "saved"}


@frappe.whitelist()
def save_nominees(employee_code: str, nominees_json: str) -> dict[str, Any]:
	require_jefs_role(("JEFS HR Onboarding",))
	items = json.loads(nominees_json)
	by_purpose: dict[str, list[Decimal]] = {}
	for it in items:
		by_purpose.setdefault(it.get("purpose") or "GRATUITY", []).append(Decimal(str(it.get("share_pct") or 0)))
	for purpose, shares in by_purpose.items():
		if not validate_nominee_shares(shares):
			frappe.throw(f"Nominee shares for {purpose} must total 100%")

	emp = frappe.get_doc("JEFS Employee", employee_code)
	emp.nominees = []
	for it in items:
		emp.append(
			"nominees",
			{
				"purpose": it.get("purpose") or "GRATUITY",
				"nominee_name": it["nominee_name"],
				"relationship": it.get("relationship") or "Family",
				"dob": it.get("dob") or None,
				"address": it.get("address") or "",
				"share_pct": float(it.get("share_pct") or 100),
				"is_minor": 1 if it.get("is_minor") else 0,
				"guardian_name": it.get("guardian_name") or "",
			},
		)
	emp.save(ignore_permissions=True)
	write_audit_log("NOMINEES_UPDATE", "JEFS Employee", employee_code, after={"count": len(items)})
	frappe.db.commit()
	return {"employee_code": employee_code, "count": len(items)}


@frappe.whitelist()
def record_employee_exit(
	employee_code: str,
	exit_date: str,
	last_working_day: str = "",
	exit_reason: str = "RESIGNATION",
	conduct: str = "Good",
) -> dict[str, Any]:
	require_jefs_role(("JEFS Exit Desk", "JEFS HR Onboarding"))
	emp = frappe.get_doc("JEFS Employee", employee_code)
	ex_dt = parse_date(exit_date)
	if not ex_dt:
		frappe.throw("FNF_NO_EXIT_DATE: Valid exit date is required")
	lwd_dt = parse_date(last_working_day) or ex_dt
	emp.date_of_exit = ex_dt.isoformat()
	emp.last_working_day = lwd_dt.isoformat()
	emp.exit_reason = exit_reason
	emp.conduct = conduct or "Good"
	emp.status = "EXITED"
	emp.save(ignore_permissions=True)
	sync_to_frappe_employee(emp)
	write_audit_log("EMPLOYEE_EXIT", "JEFS Employee", employee_code, after={"exit_date": emp.date_of_exit, "exit_reason": exit_reason})
	frappe.db.commit()
	return initiate_fnf(employee_code)


def _build_doc_context(emp: Any, sal: dict[str, Any] | None, ref_no: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
	comp = _company_dict()
	basic_p = int(sal["basic_paise"]) if sal else 0
	da_p = int(sal["da_paise"]) if sal else 0
	hra_p = int(sal["hra_paise"]) if sal else 0
	conv_p = int(sal["conveyance_paise"]) if sal else 0
	spec_p = int(sal["special_allowance_paise"]) if sal else 0
	gross_p = int(sal["gross_paise"]) if sal else 0

	doj = parse_date(emp.date_of_joining)
	lwd = parse_date(emp.last_working_day or emp.date_of_exit)
	tenure_str = calc_tenure(doj, lwd).display if doj and lwd and lwd >= doj else ""

	ctx: dict[str, Any] = {
		"ref_no": ref_no,
		"issue_date": dt.date.today().strftime("%d-%m-%Y"),
		"company_name": comp["legal_name"],
		"company_short_name": comp["short_name"],
		"company_address": comp["address"],
		"company_phone": comp["phone"],
		"company_email": comp["email"],
		"company_pf_code": comp["pf_code"],
		"company_esi_code": comp["esi_code"],
		"signatory_name": comp["signatory_name"],
		"signatory_designation": comp["signatory_designation"],
		"employee_code": emp.employee_code,
		"employee_name": emp.full_name,
		"first_name": emp.first_name or "",
		"middle_name": emp.middle_name or "",
		"last_name": emp.last_name or "",
		"father_or_husband_name": emp.father_or_husband_name or "",
		"gender": emp.gender or "",
		"dob": _fmt_date(emp.dob),
		"marital_status": emp.marital_status or "",
		"blood_group": emp.blood_group or "",
		"mobile": emp.mobile or "",
		"email": emp.email or "",
		"present_address": emp.present_address or "",
		"permanent_address": emp.permanent_address or emp.present_address or "",
		"aadhaar_masked": emp.aadhaar_masked or "",
		"aadhaar_full": decrypt_field(emp.aadhaar_encrypted) or emp.aadhaar_masked or "",
		"pan_masked": emp.pan_masked or "",
		"pan_full": decrypt_field(emp.pan_encrypted) or emp.pan_masked or "",
		"uan": emp.uan or "",
		"esic_ip_no": emp.esic_ip_no or "",
		"bank_account_masked": emp.bank_account_masked or "",
		"bank_account_full": decrypt_field(emp.bank_account_encrypted) or emp.bank_account_masked or "",
		"ifsc": emp.ifsc or "",
		"bank_name": emp.bank_name or "",
		"designation": emp.designation or "",
		"department": emp.department or "General",
		"skill_category": emp.skill_category or "Unskilled",
		"work_location": emp.work_location or emp.present_city or "Vadodara",
		"principal_employer": emp.client_site or comp["legal_name"],
		"employment_type": emp.employment_type or "PERMANENT",
		"contract_end_date": _fmt_date(emp.contract_end_date),
		"date_of_joining": _fmt_date(emp.date_of_joining),
		"notice_period_days": emp.notice_period_days or 30,
		"date_of_exit": _fmt_date(emp.date_of_exit),
		"last_working_day": _fmt_date(emp.last_working_day or emp.date_of_exit),
		"exit_reason": emp.exit_reason or "RESIGNATION",
		"conduct": emp.conduct or "Good",
		"tenure": tenure_str,
		"emergency_contact_name": emp.emergency_contact_name or "",
		"emergency_contact_phone": emp.emergency_contact_phone or "",
		"police_station": emp.police_station or "Local Police Station",
		"id_proof_type": emp.id_proof_type or "Aadhaar",
		"id_proof_masked": emp.id_proof_masked or emp.aadhaar_masked or "",
		"basic_wage": paise_to_rupees_str(basic_p),
		"da_wage": paise_to_rupees_str(da_p),
		"hra_wage": paise_to_rupees_str(hra_p),
		"other_allowances": paise_to_rupees_str(conv_p + spec_p),
		"gross_wage": paise_to_rupees_str(gross_p),
		"daily_wage": paise_to_rupees_str(round(gross_p / 26)) if gross_p else "0",
		"nominees": [
			{
				"purpose": n.purpose,
				"name": n.nominee_name,
				"relationship": n.relationship,
				"dob": _fmt_date(n.dob),
				"address": n.address or emp.permanent_address or "",
				"share_pct": n.share_pct,
			}
			for n in emp.nominees
		],
	}
	if extra:
		ctx.update(extra)
	return ctx


def _generate_single_doc(
	emp: Any,
	doc_type: str,
	sal: dict[str, Any] | None,
	extra_ctx: dict[str, Any] | None = None,
) -> tuple[str, bytes, bytes | None, str]:
	"""Generate PDF (+ optional DOCX), assert zero unresolved placeholders, save JEFS Generated Document."""
	comp = _company_dict()
	tpl_name = frappe.db.get_value("JEFS Template", {"doc_type": doc_type, "is_active": 1}, "name")
	if not tpl_name:
		raise ValueError(f"DOC_TEMPLATE_MISSING: No active template for {doc_type}")
	tpl = frappe.get_doc("JEFS Template", tpl_name)

	ref_no = next_ref_no(doc_type)
	ctx = _build_doc_context(emp, sal, ref_no, extra_ctx)
	docx_bytes: bytes | None = None

	if doc_type == "ID_CARD" or tpl.engine == "HTML":
		html_str = render_id_card_html(
			[
				{
					"employee_code": emp.employee_code,
					"full_name": emp.full_name,
					"designation": emp.designation,
					"principal_employer": ctx["principal_employer"],
					"dob": ctx["dob"],
					"date_of_joining": ctx["date_of_joining"],
					"blood_group": emp.blood_group,
					"uan": emp.uan,
					"esic_ip_no": emp.esic_ip_no,
					"present_address": emp.present_address,
					"emergency_contact_name": emp.emergency_contact_name,
					"emergency_contact_phone": emp.emergency_contact_phone,
					"issue_date": ctx["issue_date"],
					"photo_path": emp.photo_path,
					"ref_no": ref_no,
				}
			],
			comp,
		)
		pdf_bytes = convert_html_to_pdf(html_str)
	else:
		docx_bytes = render_docx_bytes(
			tpl.file_path,
			ctx,
			signature_path=comp.get("signature_image_path"),
			photo_path=emp.photo_path,
			qr_payload=f"KM|{emp.employee_code}|{ref_no}",
		)
		pdf_bytes = convert_docx_to_pdf(docx_bytes, f"{doc_type.lower()}.docx")

	# Verify no unresolved {{ placeholders remain
	pdf_txt = extract_pdf_text(pdf_bytes)
	if "{{" in pdf_txt:
		raise ValueError(f"DOC_PLACEHOLDER_UNKNOWN: Unresolved placeholder found in generated {doc_type}")

	gen_dir = get_files_root() / "generated"
	safe_ref = ref_no.replace("/", "_")
	pdf_path = gen_dir / f"{safe_ref}.pdf"
	pdf_path.write_bytes(pdf_bytes)
	docx_path_str = ""
	if docx_bytes:
		d_path = gen_dir / f"{safe_ref}.docx"
		d_path.write_bytes(docx_bytes)
		docx_path_str = str(d_path)

	snap = {
		"employee_batch": emp.source_batch,
		"salary_batch": sal.get("batch_id") if sal else None,
		"salary_period": sal.get("period") if sal else None,
	}
	prev_v = frappe.db.count("JEFS Generated Document", {"employee_code": emp.employee_code, "doc_type": doc_type})
	doc_rec = frappe.get_doc(
		{
			"doctype": "JEFS Generated Document",
			"ref_no": ref_no,
			"doc_type": doc_type,
			"employee_code": emp.employee_code,
			"employee_name": emp.full_name,
			"template_id": tpl.name,
			"version": prev_v + 1,
			"pdf_path": str(pdf_path),
			"docx_path": docx_path_str,
			"sha256": sha256_bytes(pdf_bytes),
			"source_snapshot_json": json.dumps(snap),
			"generated_by": frappe.session.user,
			"generated_at": now_datetime(),
		}
	)
	doc_rec.insert(ignore_permissions=True)
	return ref_no, pdf_bytes, docx_bytes, doc_rec.name


@frappe.whitelist()
def generate_documents(employee_codes_json: str, doc_types_json: str, merge_kit: int = 1) -> dict[str, Any]:
	require_jefs_role(("JEFS HR Onboarding", "JEFS Payroll Specialist", "JEFS Exit Desk"))
	codes = json.loads(employee_codes_json)
	doc_types = json.loads(doc_types_json)

	generated: list[dict[str, Any]] = []
	skipped: list[dict[str, str]] = []
	zip_buf = io.BytesIO()

	with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
		for code in codes:
			if not frappe.db.exists("JEFS Employee", code):
				skipped.append({"employee_code": code, "doc_type": "ALL", "reason": "Employee not found"})
				continue
			emp = frappe.get_doc("JEFS Employee", code)
			sals = frappe.get_all("JEFS Salary Record", filters={"employee_code": code}, fields=["*"], order_by="period desc", limit=1)
			sal = sals[0] if sals else None
			readiness = _employee_readiness(emp.as_dict(), sal, len(emp.nominees))

			emp_pdfs: list[bytes] = []
			for dtype in doc_types:
				r_info = readiness.get(dtype)
				if r_info and not r_info["ready"]:
					skipped.append({
						"employee_code": code,
						"doc_type": dtype,
						"reason": f"Missing: {', '.join(r_info['missing'])}",
					})
					continue
				try:
					ref_no, pdf_bytes, _, doc_id = _generate_single_doc(emp, dtype, sal)
					emp_pdfs.append(pdf_bytes)
					zf.writestr(f"{code}/{dtype}_{ref_no.replace('/', '_')}.pdf", pdf_bytes)
					generated.append({"doc_id": doc_id, "ref_no": ref_no, "employee_code": code, "doc_type": dtype})
				except Exception as exc:
					skipped.append({"employee_code": code, "doc_type": dtype, "reason": str(exc)})

			if int(merge_kit) and emp_pdfs:
				merged = merge_pdfs(emp_pdfs)
				zf.writestr(f"{code}/Joining_Kit_{code}.pdf", merged)

	zip_token = ""
	if generated:
		zip_token = f"kit_{uuid.uuid4().hex[:10]}.zip"
		(get_files_root() / "generated" / zip_token).write_bytes(zip_buf.getvalue())

	write_audit_log("DOCS_GENERATE", "JEFS Generated Document", zip_token, after={"generated": len(generated), "skipped": len(skipped)})
	frappe.db.commit()
	return {"generated": generated, "skipped": skipped, "zip_token": zip_token}


@frappe.whitelist()
def generate_id_card_sheet(employee_codes_json: str) -> dict[str, Any]:
	require_jefs_role(("JEFS HR Onboarding",))
	codes = json.loads(employee_codes_json)
	comp = _company_dict()
	cards = []
	skipped = []
	for code in codes:
		emp = frappe.get_doc("JEFS Employee", code)
		if not emp.photo_path or not os.path.exists(emp.photo_path):
			skipped.append({"employee_code": code, "reason": "DOC_PHOTO_MISSING: photo not uploaded"})
			continue
		ref_no = next_ref_no("ID_CARD")
		cards.append({
			"employee_code": emp.employee_code,
			"full_name": emp.full_name,
			"designation": emp.designation,
			"principal_employer": emp.client_site or comp["legal_name"],
			"dob": _fmt_date(emp.dob),
			"date_of_joining": _fmt_date(emp.date_of_joining),
			"blood_group": emp.blood_group,
			"uan": emp.uan,
			"esic_ip_no": emp.esic_ip_no,
			"present_address": emp.present_address,
			"emergency_contact_name": emp.emergency_contact_name,
			"emergency_contact_phone": emp.emergency_contact_phone,
			"issue_date": dt.date.today().strftime("%d-%m-%Y"),
			"photo_path": emp.photo_path,
			"ref_no": ref_no,
		})
	if not cards:
		frappe.throw("No employees with photos selected for ID card sheet.")
	pdf_bytes = convert_html_to_pdf(render_id_card_html(cards, comp))
	token = f"id_sheet_{uuid.uuid4().hex[:10]}.pdf"
	(get_files_root() / "generated" / token).write_bytes(pdf_bytes)
	write_audit_log("ID_SHEET_GENERATE", "JEFS Generated Document", token, after={"cards": len(cards)})
	frappe.db.commit()
	return {"file_token": token, "count": len(cards), "skipped": skipped}


@frappe.whitelist()
def download_generated_artifact(token: str) -> None:
	require_jefs_role(ALL_JEFS_ROLES)
	safe_name = os.path.basename(token)
	path = get_files_root() / "generated" / safe_name
	if not path.exists():
		frappe.throw("NOT_FOUND: File does not exist", frappe.DoesNotExistError)
	ctype = "application/zip" if safe_name.endswith(".zip") else "application/pdf"
	write_audit_log("ARTIFACT_DOWNLOAD", "JEFS Generated Document", safe_name)
	frappe.db.commit()
	_binary_response(path.read_bytes(), safe_name, ctype)


@frappe.whitelist()
def list_documents(q: str = "", doc_type: str = "") -> list[dict[str, Any]]:
	require_jefs_role(ALL_JEFS_ROLES)
	filters: dict[str, Any] = {}
	if doc_type:
		filters["doc_type"] = doc_type
	rows = frappe.get_all(
		"JEFS Generated Document",
		filters=filters,
		fields=["name", "ref_no", "doc_type", "employee_code", "employee_name", "version", "generated_by", "generated_at", "downloaded_count", "is_void", "void_reason"],
		order_by="generated_at desc",
		limit=500,
	)
	q_low = q.strip().lower()
	if q_low:
		rows = [r for r in rows if q_low in f"{r['ref_no']} {r['employee_code']} {r.get('employee_name','')} {r['doc_type']}".lower()]
	return rows


@frappe.whitelist()
def download_document(doc_id: str, fmt: str = "pdf") -> None:
	require_jefs_role(ALL_JEFS_ROLES)
	doc = frappe.get_doc("JEFS Generated Document", doc_id)
	path_str = doc.docx_path if fmt == "docx" and doc.docx_path else doc.pdf_path
	if not path_str or not os.path.exists(path_str):
		frappe.throw("NOT_FOUND: Requested format not available", frappe.DoesNotExistError)
	frappe.db.set_value("JEFS Generated Document", doc.name, "downloaded_count", int(doc.downloaded_count or 0) + 1)
	write_audit_log("DOC_DOWNLOAD", "JEFS Generated Document", doc.name, after={"format": fmt})
	frappe.db.commit()
	ext = "docx" if fmt == "docx" and doc.docx_path else "pdf"
	ctype = (
		"application/vnd.openxmlformats-officedocument.wordprocessingml.document"
		if ext == "docx"
		else "application/pdf"
	)
	_binary_response(Path(path_str).read_bytes(), f"{doc.ref_no.replace('/', '_')}.{ext}", ctype)


@frappe.whitelist()
def void_document(doc_id: str, reason: str) -> dict[str, Any]:
	require_jefs_role(("JEFS Admin",))
	doc = frappe.get_doc("JEFS Generated Document", doc_id)
	doc.is_void = 1
	doc.void_reason = reason
	doc.save(ignore_permissions=True)
	write_audit_log("DOC_VOID", "JEFS Generated Document", doc.name, after={"reason": reason})
	frappe.db.commit()
	return {"doc_id": doc.name, "is_void": 1}


def _compute_and_populate_fnf(fnf_doc, emp, manual_lines: list[ManualLine] | None = None) -> None:
	ex_dt = parse_date(emp.date_of_exit or fnf_doc.exit_date)
	lwd_dt = parse_date(emp.last_working_day or fnf_doc.last_working_day or ex_dt)
	doj_dt = parse_date(emp.date_of_joining)
	if not ex_dt or not lwd_dt or not doj_dt:
		frappe.throw("FNF_NO_EXIT_DATE: Employee must have joining date and exit date")

	sals = frappe.get_all("JEFS Salary Record", filters={"employee_code": emp.employee_code}, fields=["*"], order_by="period desc", limit=1)
	if not sals:
		frappe.throw("FNF_SALARY_MISSING: No salary record found for this employee. Upload Salary Excel first.")
	sal = sals[0]

	leaves = frappe.get_all("JEFS Leave Record", filters={"employee_code": emp.employee_code}, fields=["*"], order_by="as_of_date desc", limit=1)
	el_bal = Decimal(str(leaves[0]["balance"])) if leaves else None

	bonuses = frappe.get_all("JEFS Bonus Record", filters={"employee_code": emp.employee_code}, fields=["*"], order_by="fy desc", limit=1)
	bonus_rec = bonuses[0] if bonuses else None

	settings = resolve_fnf_settings(ex_dt)
	site_rule = resolve_site_rule(emp.client_site)

	# Lookup applicable min wage for bonus calculation cap
	mw_rows = frappe.get_all(
		"JEFS Min Wage Rate",
		filters={"state": emp.present_state or "Gujarat", "skill_category": emp.skill_category or "Unskilled"},
		fields=["total_paise"],
		order_by="effective_from desc",
		limit=1,
	)
	mw_paise = int(mw_rows[0]["total_paise"]) if mw_rows else 0

	if manual_lines is None:
		manual_lines = [
			ManualLine(l.code, l.line_type, int(l.amount_paise), l.note or "")
			for l in fnf_doc.lines
			if l.is_manual
		]

	exit_period = lwd_dt.strftime("%Y-%m")
	days_worked = Decimal(str(sal["days_paid"])) if sal.get("period") == exit_period and sal.get("days_paid") else None
	days_in_month = int(sal["days_in_month"]) if sal.get("period") == exit_period and sal.get("days_in_month") else None

	inp = FnfInput(
		employee_code=emp.employee_code,
		employment_type=emp.employment_type or "PERMANENT",
		exit_reason=emp.exit_reason or "RESIGNATION",
		doj=doj_dt,
		lwd=lwd_dt,
		exit_date=ex_dt,
		basic_paise=int(sal["basic_paise"]),
		da_paise=int(sal["da_paise"]),
		gross_paise=int(sal["gross_paise"]),
		days_worked_in_exit_month=days_worked,
		days_in_exit_month=days_in_month,
		el_balance=el_bal,
		fy_working_days=int(bonus_rec["working_days"]) if bonus_rec else None,
		fy_bonus_wage_paise=int(bonus_rec["bonus_wage_paise"]) if bonus_rec and bonus_rec.get("bonus_wage_paise") else None,
		min_wage_monthly_paise=mw_paise,
		bonus_already_paid_paise=int(bonus_rec["bonus_paid_paise"]) if bonus_rec else 0,
		bonus_eligible_override=(bool(bonus_rec["eligible"]) if bonus_rec else None),
		deduct_pf=bool(int(sal.get("pf_ee_paise") or 0) > 0 or emp.uan),
		deduct_esi=bool(int(sal.get("esi_ee_paise") or 0) > 0),
		pt_paise=int(sal.get("pt_paise") or 0),
		site_rule=site_rule,
		manual_lines=tuple(manual_lines),
	)
	res = calc_fnf(inp, settings)

	fnf_doc.employee_name = emp.full_name
	fnf_doc.exit_date = ex_dt.isoformat()
	fnf_doc.last_working_day = lwd_dt.isoformat()
	fnf_doc.exit_reason = emp.exit_reason or "RESIGNATION"
	fnf_doc.employment_type = emp.employment_type or "PERMANENT"
	fnf_doc.client_site = emp.client_site or ""
	fnf_doc.service_years = res.tenure.years
	fnf_doc.service_months = res.tenure.months
	fnf_doc.service_days = res.tenure.days
	fnf_doc.counted_years = res.tenure.counted_years
	fnf_doc.tenure_display = res.tenure.display
	fnf_doc.total_earnings_paise = res.total_earnings_paise
	fnf_doc.total_deductions_paise = res.total_deductions_paise
	fnf_doc.net_payable_paise = res.net_payable_paise
	fnf_doc.net_payable_rupees = paise_to_rupees_int(res.net_payable_paise)
	fnf_doc.payment_due_date = res.payment_due_date.isoformat()
	fnf_doc.is_overdue = 1 if dt.date.today() > res.payment_due_date else 0
	fnf_doc.warnings_json = json.dumps(list(res.warnings))
	fnf_doc.errors_json = json.dumps(list(res.errors))
	fnf_doc.inputs_snapshot_json = json.dumps(
		{
			"salary_period": sal.get("period"),
			"salary_batch": sal.get("batch_id"),
			"leave_as_of": str(leaves[0]["as_of_date"]) if leaves else None,
			"leave_batch": leaves[0]["batch_id"] if leaves else None,
			"bonus_fy": bonus_rec["fy"] if bonus_rec else None,
			"bonus_batch": bonus_rec["batch_id"] if bonus_rec else None,
			"site_rule": site_rule.site_code,
		}
	)

	fnf_doc.lines = []
	for l in res.lines:
		fnf_doc.append(
			"lines",
			{
				"code": l.code,
				"label": l.label,
				"line_type": l.line_type,
				"amount_paise": l.amount_paise,
				"amount_rupees": paise_to_rupees_int(l.amount_paise),
				"formula_text": l.formula_text,
				"is_manual": 1 if l.is_manual else 0,
				"note": l.note,
			},
		)


@frappe.whitelist()
def list_fnf_settlements() -> dict[str, Any]:
	require_jefs_role(("JEFS Exit Desk", "JEFS Approver", "JEFS Auditor"))
	rows = frappe.get_all("JEFS FnF Settlement", fields=["*"], order_by="modified desc", limit=200)
	hrms_map: dict[str, str] = {}
	if frappe.get_meta("Full and Final Statement").has_field("jefs_fnf_settlement"):
		for h in frappe.get_all(
			"Full and Final Statement",
			filters={"docstatus": ["<", 2]},
			fields=["name", "jefs_fnf_settlement"],
		):
			if h.get("jefs_fnf_settlement"):
				hrms_map[h["jefs_fnf_settlement"]] = h["name"]
	for r in rows:
		r["hrms_fnf_statement"] = hrms_map.get(r["name"], "")
	exited = frappe.get_all("JEFS Employee", filters={"status": "EXITED"}, fields=["employee_code", "full_name", "date_of_exit", "client_site", "designation"])
	fnf_codes = {r["employee_code"] for r in rows if r["status"] != "CANCELLED"}
	uninitiated = [e for e in exited if e["employee_code"] not in fnf_codes]
	return {"settlements": rows, "uninitiated_exits": uninitiated}


@frappe.whitelist()
def initiate_fnf(employee_code: str) -> dict[str, Any]:
	require_jefs_role(("JEFS Exit Desk",))
	existing = frappe.get_all(
		"JEFS FnF Settlement",
		filters={"employee_code": employee_code, "status": ["in", ["DRAFT", "SUBMITTED", "APPROVED"]]},
		pluck="name",
	)
	if existing:
		return get_fnf_detail(existing[0])

	emp = frappe.get_doc("JEFS Employee", employee_code)
	fnf = frappe.new_doc("JEFS FnF Settlement")
	fnf.employee_code = employee_code
	fnf.version = 1
	fnf.status = "DRAFT"
	fnf.prepared_by = frappe.session.user
	_compute_and_populate_fnf(fnf, emp, manual_lines=[])
	fnf.insert(ignore_permissions=True)
	write_audit_log("FNF_CREATE", "JEFS FnF Settlement", fnf.name, after={"net_rupees": fnf.net_payable_rupees})
	frappe.db.commit()
	return get_fnf_detail(fnf.name)


@frappe.whitelist()
def get_fnf_detail(fnf_id: str) -> dict[str, Any]:
	require_jefs_role(("JEFS Exit Desk", "JEFS Approver", "JEFS Auditor"))
	fnf = frappe.get_doc("JEFS FnF Settlement", fnf_id)
	docs = frappe.get_all(
		"JEFS Generated Document",
		filters={"employee_code": fnf.employee_code, "doc_type": ["in", ["FNF_STATEMENT", "SERVICE_CERTIFICATE"]], "is_void": 0},
		fields=["name", "ref_no", "doc_type", "generated_at"],
		order_by="generated_at desc",
	)
	return {
		"fnf": fnf.as_dict(),
		"warnings": json.loads(fnf.warnings_json or "[]"),
		"errors": json.loads(fnf.errors_json or "[]"),
		"inputs_snapshot": json.loads(fnf.inputs_snapshot_json or "{}"),
		"net_words": amount_in_words_inr(int(fnf.net_payable_paise or 0)),
		"documents": docs,
	}


@frappe.whitelist()
def add_fnf_manual_line(fnf_id: str, code: str, line_type: str, amount_rupees: float, note: str = "") -> dict[str, Any]:
	require_jefs_role(("JEFS Exit Desk",))
	fnf = frappe.get_doc("JEFS FnF Settlement", fnf_id)
	if fnf.status in ("APPROVED", "REVISED"):
		frappe.throw("FNF_LOCKED: Approved F&F cannot be modified.")
	emp = frappe.get_doc("JEFS Employee", fnf.employee_code)
	manual = [
		ManualLine(l.code, l.line_type, int(l.amount_paise), l.note or "")
		for l in fnf.lines
		if l.is_manual
	]
	manual.append(ManualLine(code.strip().upper(), line_type.strip().upper(), rupees_to_paise(amount_rupees), note))
	_compute_and_populate_fnf(fnf, emp, manual_lines=manual)
	fnf.save(ignore_permissions=True)
	write_audit_log("FNF_ADD_LINE", "JEFS FnF Settlement", fnf.name, after={"code": code, "amount_rupees": amount_rupees})
	frappe.db.commit()
	return get_fnf_detail(fnf.name)


@frappe.whitelist()
def delete_fnf_manual_line(fnf_id: str, line_name: str) -> dict[str, Any]:
	require_jefs_role(("JEFS Exit Desk",))
	fnf = frappe.get_doc("JEFS FnF Settlement", fnf_id)
	if fnf.status in ("APPROVED", "REVISED"):
		frappe.throw("FNF_LOCKED: Approved F&F cannot be modified.")
	emp = frappe.get_doc("JEFS Employee", fnf.employee_code)
	manual = [
		ManualLine(l.code, l.line_type, int(l.amount_paise), l.note or "")
		for l in fnf.lines
		if l.is_manual and l.name != line_name
	]
	_compute_and_populate_fnf(fnf, emp, manual_lines=manual)
	fnf.save(ignore_permissions=True)
	frappe.db.commit()
	return get_fnf_detail(fnf.name)


@frappe.whitelist()
def recalculate_fnf(fnf_id: str) -> dict[str, Any]:
	require_jefs_role(("JEFS Exit Desk",))
	fnf = frappe.get_doc("JEFS FnF Settlement", fnf_id)
	if fnf.status in ("APPROVED", "REVISED"):
		frappe.throw("FNF_LOCKED: Approved F&F cannot be modified.")
	emp = frappe.get_doc("JEFS Employee", fnf.employee_code)
	_compute_and_populate_fnf(fnf, emp)
	fnf.save(ignore_permissions=True)
	frappe.db.commit()
	return get_fnf_detail(fnf.name)


@frappe.whitelist()
def submit_fnf(fnf_id: str) -> dict[str, Any]:
	require_jefs_role(("JEFS Exit Desk",))
	fnf = frappe.get_doc("JEFS FnF Settlement", fnf_id)
	if fnf.status != "DRAFT":
		frappe.throw("Only DRAFT F&F can be submitted.")
	errs = json.loads(fnf.errors_json or "[]")
	if errs:
		frappe.throw("; ".join(errs))
	fnf.status = "SUBMITTED"
	fnf.submitted_by = frappe.session.user
	fnf.submitted_at = now_datetime()
	fnf.save(ignore_permissions=True)
	write_audit_log("FNF_SUBMIT", "JEFS FnF Settlement", fnf.name)
	frappe.db.commit()
	return get_fnf_detail(fnf.name)


@frappe.whitelist()
def approve_fnf(fnf_id: str, remarks: str = "") -> dict[str, Any]:
	require_jefs_role(("JEFS Approver",))
	fnf = frappe.get_doc("JEFS FnF Settlement", fnf_id)
	if fnf.status != "SUBMITTED":
		frappe.throw("F&F must be SUBMITTED before approval.")
	if fnf.prepared_by == frappe.session.user or fnf.submitted_by == frappe.session.user:
		frappe.throw(
			"FNF_SELF_APPROVAL: Maker-checker enforced — you cannot approve an F&F you prepared/submitted. "
			"Sign in as an Approver (e.g. approver@kesari.local) to approve."
		)

	fnf.status = "APPROVED"
	fnf.approved_by = frappe.session.user
	fnf.approved_at = now_datetime()
	fnf.remarks = remarks
	fnf.save(ignore_permissions=True)

	emp = frappe.get_doc("JEFS Employee", fnf.employee_code)
	comp = _company_dict()
	fnf_ref = next_ref_no("FNF_STATEMENT")
	fnf_html = render_fnf_statement_html(
		{**fnf.as_dict(), "warnings": json.loads(fnf.warnings_json or "[]")},
		emp.as_dict(),
		comp,
		fnf_ref,
	)
	fnf_pdf = convert_html_to_pdf(fnf_html)
	fnf_pdf_path = get_files_root() / "generated" / f"{fnf_ref.replace('/', '_')}.pdf"
	fnf_pdf_path.write_bytes(fnf_pdf)
	frappe.get_doc(
		{
			"doctype": "JEFS Generated Document",
			"ref_no": fnf_ref,
			"doc_type": "FNF_STATEMENT",
			"employee_code": emp.employee_code,
			"employee_name": emp.full_name,
			"version": fnf.version,
			"pdf_path": str(fnf_pdf_path),
			"sha256": sha256_bytes(fnf_pdf),
			"source_snapshot_json": fnf.inputs_snapshot_json,
			"generated_by": frappe.session.user,
			"generated_at": now_datetime(),
		}
	).insert(ignore_permissions=True)

	# Auto-generate Service Certificate on F&F approval (M5)
	sals = frappe.get_all("JEFS Salary Record", filters={"employee_code": emp.employee_code}, fields=["*"], order_by="period desc", limit=1)
	sc_ref, _, _, _ = _generate_single_doc(
		emp,
		"SERVICE_CERTIFICATE",
		sals[0] if sals else None,
		extra_ctx={
			"fnf_net_payable": paise_to_rupees_str(int(fnf.net_payable_paise)),
			"fnf_net_payable_words": amount_in_words_inr(int(fnf.net_payable_paise)),
			"payment_due_date": _fmt_date(fnf.payment_due_date),
		},
	)

	write_audit_log("FNF_APPROVE", "JEFS FnF Settlement", fnf.name, after={"fnf_ref": fnf_ref, "service_cert_ref": sc_ref})
	frappe.db.commit()
	return get_fnf_detail(fnf.name)


@frappe.whitelist()
def reject_fnf(fnf_id: str, remarks: str = "") -> dict[str, Any]:
	require_jefs_role(("JEFS Approver",))
	fnf = frappe.get_doc("JEFS FnF Settlement", fnf_id)
	if fnf.status != "SUBMITTED":
		frappe.throw("Only SUBMITTED F&F can be rejected.")
	fnf.status = "DRAFT"
	fnf.remarks = remarks
	fnf.save(ignore_permissions=True)
	write_audit_log("FNF_REJECT", "JEFS FnF Settlement", fnf.name, after={"remarks": remarks})
	frappe.db.commit()
	return get_fnf_detail(fnf.name)


@frappe.whitelist()
def revise_fnf(fnf_id: str) -> dict[str, Any]:
	require_jefs_role(("JEFS Approver", "JEFS Exit Desk"))
	old_fnf = frappe.get_doc("JEFS FnF Settlement", fnf_id)
	if old_fnf.status != "APPROVED":
		frappe.throw("Only APPROVED F&F requires a revision.")
	old_fnf.status = "REVISED"
	old_fnf.save(ignore_permissions=True)

	emp = frappe.get_doc("JEFS Employee", old_fnf.employee_code)
	new_fnf = frappe.new_doc("JEFS FnF Settlement")
	new_fnf.employee_code = old_fnf.employee_code
	new_fnf.version = int(old_fnf.version or 1) + 1
	new_fnf.status = "DRAFT"
	new_fnf.prepared_by = frappe.session.user
	manual = [
		ManualLine(l.code, l.line_type, int(l.amount_paise), l.note or "")
		for l in old_fnf.lines
		if l.is_manual
	]
	_compute_and_populate_fnf(new_fnf, emp, manual_lines=manual)
	new_fnf.insert(ignore_permissions=True)
	write_audit_log("FNF_REVISE", "JEFS FnF Settlement", new_fnf.name, before={"old": old_fnf.name})
	frappe.db.commit()
	return get_fnf_detail(new_fnf.name)


@frappe.whitelist()
def export_fnf_excel() -> None:
	"""Export client-compatible 4-sheet F&F statement workbook (MEET MANPOWER SOLUTIONS layout)."""
	require_jefs_role(("JEFS Exit Desk", "JEFS Approver", "JEFS Auditor"))
	fnfs = frappe.get_all("JEFS FnF Settlement", fields=["*"], order_by="modified desc")
	fnf_rows = []
	grat_rows = []
	for idx, f in enumerate(fnfs, 1):
		doc = frappe.get_doc("JEFS FnF Settlement", f["name"])
		line_map = {l.code: paise_to_rupees_int(int(l.amount_paise)) for l in doc.lines}
		fnf_rows.append([
			idx, doc.employee_code, doc.employee_name, "", str(doc.last_working_day or ""),
			line_map.get("EARNED_SALARY", 0), line_map.get("LEAVE_ENCASH", 0),
			line_map.get("BONUS", 0), line_map.get("GRATUITY", 0), doc.net_payable_rupees,
		])
		grat_rows.append([idx, doc.employee_code, doc.employee_name, "", str(doc.last_working_day or ""), doc.counted_years, line_map.get("GRATUITY", 0)])

	xlsx = build_xlsx_bytes([
		("F and F", ["Sr.No", "Emp.Code", "Name of Employee", "DOJ", "Date of Leaving", "Earned Salary", "Leave Salary", "Bonus", "Gratuity", "Total F & F Payable"], fnf_rows),
		("Gratuity", ["Sr. No.", "Emp Code", "NAME", "DOJ", "Date of Leaving", "Gratuity Years", "Gratuity Amount"], grat_rows),
	])
	_binary_response(xlsx, "kesari_fnf_statement.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@frappe.whitelist()
def list_min_wages() -> list[dict[str, Any]]:
	require_jefs_role(ALL_JEFS_ROLES)
	return frappe.get_all("JEFS Min Wage Rate", fields=["*"], order_by="effective_from desc, state asc")


@frappe.whitelist()
def save_min_wage(state: str, zone: str, skill_category: str, effective_from: str, basic_rupees: float, vda_rupees: float, source_reference: str = "") -> dict[str, Any]:
	require_jefs_role(("JEFS Payroll Specialist",))
	b_p = rupees_to_paise(basic_rupees)
	v_p = rupees_to_paise(vda_rupees)
	doc = frappe.get_doc(
		{
			"doctype": "JEFS Min Wage Rate",
			"state": state,
			"zone": zone,
			"skill_category": skill_category,
			"effective_from": effective_from,
			"basic_paise": b_p,
			"vda_paise": v_p,
			"total_paise": b_p + v_p,
			"source_reference": source_reference,
		}
	)
	doc.insert(ignore_permissions=True)
	write_audit_log("MIN_WAGE_SAVE", "JEFS Min Wage Rate", doc.name)
	frappe.db.commit()
	return doc.as_dict()


@frappe.whitelist()
def list_wage_revisions() -> list[dict[str, Any]]:
	require_jefs_role(("JEFS Payroll Specialist", "JEFS Approver", "JEFS Auditor"))
	return frappe.get_all("JEFS Wage Revision", fields=["*"], order_by="creation desc")


@frappe.whitelist()
def create_wage_revision(revision_name: str, effective_from: str, policy: str = "RAISE_TO_MIN", vda_delta_rupees: float = 0, custom_pct: float = 0, letter_for_all: int = 0) -> dict[str, Any]:
	require_jefs_role(("JEFS Payroll Specialist",))
	eff_dt = parse_date(effective_from) or dt.date.today()

	rate_rows = frappe.get_all(
		"JEFS Min Wage Rate",
		filters={"effective_from": ["<=", eff_dt.isoformat()]},
		fields=["*"],
		order_by="effective_from asc",
	)
	rates: dict[tuple[str, str, str], MinWageEntry] = {}
	for r in rate_rows:
		key = (r["state"].strip().lower(), r["zone"].strip().lower(), r["skill_category"].strip().lower())
		rates[key] = MinWageEntry(r["state"], r["zone"], r["skill_category"], int(r["basic_paise"]), int(r["vda_paise"]), int(r["total_paise"]))

	emps = frappe.get_all("JEFS Employee", filters={"status": "ACTIVE"}, fields=["employee_code", "full_name", "present_state", "zone", "skill_category"])
	sals = frappe.get_all("JEFS Salary Record", fields=["employee_code", "period", "basic_paise", "da_paise", "gross_paise"], order_by="period desc")
	sal_map = {}
	for s in sals:
		sal_map.setdefault(s["employee_code"], s)

	rev_emps = []
	for e in emps:
		sal = sal_map.get(e["employee_code"])
		if not sal:
			continue
		rev_emps.append(
			WageRevisionEmployee(
				employee_code=e["employee_code"],
				employee_name=e["full_name"],
				state=e.get("present_state") or "Gujarat",
				zone=e.get("zone") or "Zone-A",
				skill_category=e.get("skill_category") or "Unskilled",
				old_basic_paise=int(sal["basic_paise"]),
				old_da_paise=int(sal["da_paise"]),
				old_gross_paise=int(sal["gross_paise"]),
			)
		)

	proposals = propose_wage_revision(
		rev_emps,
		rates,
		policy=policy,
		vda_delta_paise=rupees_to_paise(vda_delta_rupees),
		custom_pct=Decimal(str(custom_pct)),
		letter_for_all=bool(int(letter_for_all)),
	)

	rev = frappe.new_doc("JEFS Wage Revision")
	rev.revision_name = revision_name
	rev.effective_from = eff_dt.isoformat()
	rev.policy = policy
	rev.vda_delta_paise = rupees_to_paise(vda_delta_rupees)
	rev.custom_pct = float(custom_pct)
	rev.letter_for_all = int(letter_for_all)
	rev.status = "DRAFT"
	rev.prepared_by = frappe.session.user
	for p in proposals:
		rev.append(
			"items",
			{
				"employee_code": p.employee_code,
				"employee_name": p.employee_name,
				"skill_category": p.skill_category,
				"old_total_paise": p.old_total_paise,
				"min_wage_paise": p.min_wage_paise or 0,
				"proposed_total_paise": p.proposed_total_paise,
				"delta_paise": p.delta_paise,
				"needs_letter": 1 if p.needs_letter else 0,
				"reason": p.error or p.reason,
				"edited": 0,
			},
		)
	rev.insert(ignore_permissions=True)
	write_audit_log("WAGE_REVISION_CREATE", "JEFS Wage Revision", rev.name, after={"items": len(proposals)})
	frappe.db.commit()
	return rev.as_dict()


@frappe.whitelist()
def get_wage_revision(revision_id: str) -> dict[str, Any]:
	require_jefs_role(("JEFS Payroll Specialist", "JEFS Approver", "JEFS Auditor"))
	return frappe.get_doc("JEFS Wage Revision", revision_id).as_dict()


@frappe.whitelist()
def update_revision_item(revision_id: str, item_name: str, proposed_rupees: float) -> dict[str, Any]:
	require_jefs_role(("JEFS Payroll Specialist",))
	rev = frappe.get_doc("JEFS Wage Revision", revision_id)
	if rev.status == "APPROVED":
		frappe.throw("WAGE_REVISION_LOCKED: Approved revision cannot be edited.")
	prop_p = rupees_to_paise(proposed_rupees)
	for it in rev.items:
		if it.name == item_name:
			if it.min_wage_paise and prop_p < int(it.min_wage_paise):
				frappe.throw(f"WAGE_BELOW_MINIMUM: New wage ₹{proposed_rupees} is below minimum ₹{paise_to_rupees_int(it.min_wage_paise)}")
			it.proposed_total_paise = prop_p
			it.delta_paise = prop_p - int(it.old_total_paise)
			it.needs_letter = 1 if (it.delta_paise > 0 or rev.letter_for_all) else 0
			it.edited = 1
			it.reason = "Manually edited"
			break
	rev.save(ignore_permissions=True)
	frappe.db.commit()
	return rev.as_dict()


@frappe.whitelist()
def approve_wage_revision(revision_id: str) -> dict[str, Any]:
	require_jefs_role(("JEFS Approver",))
	rev = frappe.get_doc("JEFS Wage Revision", revision_id)
	if rev.status == "APPROVED":
		return {"revision": rev.as_dict(), "generated": 0}
	if rev.prepared_by == frappe.session.user:
		frappe.throw("WAGE_SELF_APPROVAL: Maker-checker enforced — use an Approver account to approve.")

	rev.status = "APPROVED"
	rev.approved_by = frappe.session.user
	rev.approved_at = now_datetime()
	rev.save(ignore_permissions=True)

	generated = []
	zip_buf = io.BytesIO()
	with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
		for it in rev.items:
			if not it.needs_letter:
				continue
			emp = frappe.get_doc("JEFS Employee", it.employee_code)
			sals = frappe.get_all("JEFS Salary Record", filters={"employee_code": it.employee_code}, fields=["*"], order_by="period desc", limit=1)
			sal = sals[0] if sals else None
			ref_no, pdf_bytes, _, doc_id = _generate_single_doc(
				emp,
				"INCREMENT_LETTER",
				sal,
				extra_ctx={
					"effective_from": _fmt_date(rev.effective_from),
					"effective_to": _fmt_date(rev.effective_from),
					"old_wage": paise_to_rupees_str(int(it.old_total_paise)),
					"new_wage": paise_to_rupees_str(int(it.proposed_total_paise)),
					"vda_increase": paise_to_rupees_str(int(it.delta_paise)),
				},
			)
			zf.writestr(f"Increment_{emp.employee_code}_{ref_no.replace('/', '_')}.pdf", pdf_bytes)
			generated.append({"doc_id": doc_id, "ref_no": ref_no, "employee_code": emp.employee_code})

	zip_token = ""
	if generated:
		zip_token = f"increments_{uuid.uuid4().hex[:10]}.zip"
		(get_files_root() / "generated" / zip_token).write_bytes(zip_buf.getvalue())

	sync_wage_revision_to_hrms(rev)
	write_audit_log("WAGE_REVISION_APPROVE", "JEFS Wage Revision", rev.name, after={"letters": len(generated)})
	frappe.db.commit()
	return {"revision": rev.as_dict(), "generated": generated, "zip_token": zip_token}


@frappe.whitelist()
def export_wage_revision_excel(revision_id: str) -> None:
	require_jefs_role(("JEFS Payroll Specialist", "JEFS Approver", "JEFS Auditor"))
	rev = frappe.get_doc("JEFS Wage Revision", revision_id)
	rows = [
		[
			it.employee_code, it.employee_name, it.skill_category,
			paise_to_rupees_int(int(it.old_total_paise)),
			paise_to_rupees_int(int(it.min_wage_paise)),
			paise_to_rupees_int(int(it.proposed_total_paise)),
			paise_to_rupees_int(int(it.delta_paise)),
			"Yes" if it.needs_letter else "No",
			it.reason,
		]
		for it in rev.items
	]
	xlsx = build_xlsx_bytes([("Revised Wages", ["Employee Code", "Name", "Skill", "Old Wage", "Min Wage", "New Wage", "Delta", "Increment Letter", "Reason"], rows)])
	_binary_response(xlsx, f"{rev.name}_revised_wages.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@frappe.whitelist()
def get_settings_data() -> dict[str, Any]:
	require_jefs_role(ALL_JEFS_ROLES)
	return {
		"company": _company_dict(),
		"statutory": frappe.get_all("JEFS Statutory Setting", fields=["*"], order_by="setting_key asc, effective_from desc"),
		"site_rules": frappe.get_all("JEFS Client Site Rule", fields=["*"], order_by="site_code asc"),
		"templates": frappe.get_all("JEFS Template", fields=["*"], order_by="doc_type asc, version desc"),
		"placeholders": ALLOWED_PLACEHOLDERS,
		"watcher_sources": frappe.get_all("JEFS Wage Watcher Source", fields=["*"]),
	}


@frappe.whitelist()
def save_company_profile(data_json: str) -> dict[str, Any]:
	require_jefs_role(("JEFS Admin",))
	data = json.loads(data_json)
	p = frappe.get_single("JEFS Company Profile")
	for k in ("legal_name", "short_name", "address", "phone", "email", "website", "pf_code", "esi_code", "signatory_name", "signatory_designation", "default_state", "ref_prefix", "working_days"):
		if k in data:
			p.set(k, data[k])
	p.save(ignore_permissions=True)
	write_audit_log("COMPANY_SETTINGS_UPDATE", "JEFS Company Profile", "JEFS Company Profile")
	frappe.db.commit()
	return _company_dict()


@frappe.whitelist()
def save_statutory_setting(setting_key: str, setting_value: str, effective_from: str, note: str = "", is_verified: int = 1) -> dict[str, Any]:
	require_jefs_role(("JEFS Admin", "JEFS Payroll Specialist"))
	doc = frappe.get_doc(
		{
			"doctype": "JEFS Statutory Setting",
			"setting_key": setting_key,
			"setting_value": setting_value,
			"effective_from": effective_from,
			"note": note,
			"is_verified": int(is_verified),
		}
	)
	doc.insert(ignore_permissions=True)
	write_audit_log("STATUTORY_UPDATE", "JEFS Statutory Setting", doc.name, after={"key": setting_key, "value": setting_value})
	frappe.db.commit()
	return doc.as_dict()


@frappe.whitelist()
def save_client_site_rule(site_code: str, site_name: str, include_bonus: int, include_leave: int, include_gratuity: int, notes: str = "") -> dict[str, Any]:
	require_jefs_role(("JEFS Admin", "JEFS Payroll Specialist"))
	code = site_code.strip().upper()
	doc = frappe.get_doc("JEFS Client Site Rule", code) if frappe.db.exists("JEFS Client Site Rule", code) else frappe.new_doc("JEFS Client Site Rule")
	doc.site_code = code
	doc.site_name = site_name
	doc.include_bonus = int(include_bonus)
	doc.include_leave = int(include_leave)
	doc.include_gratuity = int(include_gratuity)
	doc.notes = notes
	doc.save(ignore_permissions=True)
	write_audit_log("SITE_RULE_SAVE", "JEFS Client Site Rule", code)
	frappe.db.commit()
	return doc.as_dict()


@frappe.whitelist()
def upload_docx_template(doc_type: str, template_name: str) -> dict[str, Any]:
	require_jefs_role(("JEFS Admin",))
	if not frappe.request.files or "file" not in frappe.request.files:
		frappe.throw("No .docx file uploaded")
	f_obj = frappe.request.files["file"]
	data = f_obj.read()
	fname = f_obj.filename or f"{doc_type.lower()}.docx"
	if not fname.lower().endswith(".docx") or data[:4] != b"PK\x03\x04":
		frappe.throw("Only .docx files (macros rejected) are allowed.")

	known, unknown = extract_docx_placeholders(data)
	tpl_dir = get_files_root() / "templates"
	prev_v = frappe.db.count("JEFS Template", {"doc_type": doc_type})
	new_v = prev_v + 1
	dest = tpl_dir / f"{doc_type.lower()}_v{new_v}.docx"
	dest.write_bytes(data)

	if not unknown:
		frappe.db.sql("UPDATE `tabJEFS Template` SET is_active = 0 WHERE doc_type = %s", (doc_type,))

	tpl = frappe.get_doc(
		{
			"doctype": "JEFS Template",
			"doc_type": doc_type,
			"template_name": template_name,
			"engine": "DOCX",
			"version": new_v,
			"file_path": str(dest),
			"placeholders_json": json.dumps(known),
			"unknown_placeholders_json": json.dumps(unknown),
			"is_active": 0 if unknown else 1,
		}
	)
	tpl.insert(ignore_permissions=True)
	write_audit_log("TEMPLATE_UPLOAD", "JEFS Template", tpl.name, after={"doc_type": doc_type, "unknown": unknown})
	frappe.db.commit()
	return tpl.as_dict()


@frappe.whitelist()
def preview_template(template_id: str, employee_code: str) -> dict[str, str]:
	require_jefs_role(("JEFS Admin", "JEFS HR Onboarding"))
	tpl = frappe.get_doc("JEFS Template", template_id)
	emp = frappe.get_doc("JEFS Employee", employee_code)
	sals = frappe.get_all("JEFS Salary Record", filters={"employee_code": employee_code}, fields=["*"], order_by="period desc", limit=1)
	sal = sals[0] if sals else None
	comp = _company_dict()
	ctx = _build_doc_context(emp, sal, "PREVIEW/000001")
	if tpl.engine == "HTML" and tpl.doc_type == "ID_CARD":
		pdf_bytes = convert_html_to_pdf(render_id_card_html([
			{
				"employee_code": emp.employee_code, "full_name": emp.full_name, "designation": emp.designation,
				"principal_employer": ctx["principal_employer"], "dob": ctx["dob"], "date_of_joining": ctx["date_of_joining"],
				"blood_group": emp.blood_group, "uan": emp.uan, "esic_ip_no": emp.esic_ip_no,
				"present_address": emp.present_address, "emergency_contact_name": emp.emergency_contact_name,
				"emergency_contact_phone": emp.emergency_contact_phone, "issue_date": ctx["issue_date"],
				"photo_path": emp.photo_path, "ref_no": "PREVIEW/IC/0001",
			}
		], comp))
	else:
		docx_bytes = render_docx_bytes(tpl.file_path, ctx, signature_path=comp.get("signature_image_path"), photo_path=emp.photo_path, qr_payload=f"PREVIEW|{emp.employee_code}")
		pdf_bytes = convert_docx_to_pdf(docx_bytes, "preview.docx")
	token = f"preview_{uuid.uuid4().hex[:8]}.pdf"
	(get_files_root() / "generated" / token).write_bytes(pdf_bytes)
	return {"file_token": token}


@frappe.whitelist()
def activate_template(template_id: str) -> dict[str, Any]:
	require_jefs_role(("JEFS Admin",))
	tpl = frappe.get_doc("JEFS Template", template_id)
	unknown = json.loads(tpl.unknown_placeholders_json or "[]")
	if unknown:
		frappe.throw(f"DOC_PLACEHOLDER_UNKNOWN: Unknown placeholders: {', '.join(unknown)}")
	frappe.db.sql("UPDATE `tabJEFS Template` SET is_active = 0 WHERE doc_type = %s", (tpl.doc_type,))
	tpl.is_active = 1
	tpl.save(ignore_permissions=True)
	frappe.db.commit()
	return tpl.as_dict()


@frappe.whitelist()
def run_watcher_check(source_name: str = "") -> list[dict[str, Any]]:
	require_jefs_role(("JEFS Admin", "JEFS Payroll Specialist"))
	names = [source_name] if source_name else frappe.get_all("JEFS Wage Watcher Source", pluck="name")
	res = [check_watcher_source(n) for n in names]
	frappe.db.commit()
	return res


@frappe.whitelist()
def download_report(report_type: str) -> None:
	require_jefs_role(ALL_JEFS_ROLES)
	rt = report_type.strip().lower()
	if rt == "joiners":
		emps = frappe.get_all("JEFS Employee", fields=["employee_code", "full_name", "designation", "client_site", "date_of_joining", "employment_type", "status"], order_by="date_of_joining desc")
		xlsx = build_xlsx_bytes([("Joiners", ["Code", "Name", "Designation", "Client Site", "DOJ", "Type", "Status"], [[e[k] for k in ("employee_code", "full_name", "designation", "client_site", "date_of_joining", "employment_type", "status")] for e in emps])])
	elif rt == "exits":
		emps = frappe.get_all("JEFS Employee", filters={"status": "EXITED"}, fields=["employee_code", "full_name", "client_site", "date_of_joining", "date_of_exit", "last_working_day", "exit_reason"])
		xlsx = build_xlsx_bytes([("Exits", ["Code", "Name", "Client Site", "DOJ", "Exit Date", "LWD", "Reason"], [[e[k] for k in ("employee_code", "full_name", "client_site", "date_of_joining", "date_of_exit", "last_working_day", "exit_reason")] for e in emps])])
	elif rt == "documents-generated":
		docs = frappe.get_all("JEFS Generated Document", fields=["ref_no", "doc_type", "employee_code", "employee_name", "version", "generated_by", "generated_at", "downloaded_count", "is_void"])
		xlsx = build_xlsx_bytes([("Documents", ["Ref No", "Type", "Code", "Name", "Version", "Generated By", "Generated At", "Downloads", "Void"], [[d[k] for k in ("ref_no", "doc_type", "employee_code", "employee_name", "version", "generated_by", "generated_at", "downloaded_count", "is_void")] for d in docs])])
	elif rt in ("fnf-register", "pending-fnf"):
		filters = {"status": ["in", ["DRAFT", "SUBMITTED"]]} if rt == "pending-fnf" else {}
		fnfs = frappe.get_all("JEFS FnF Settlement", filters=filters, fields=["name", "employee_code", "employee_name", "version", "status", "exit_date", "payment_due_date", "is_overdue", "net_payable_rupees"])
		xlsx = build_xlsx_bytes([("FnF", ["ID", "Code", "Name", "Version", "Status", "Exit Date", "Payment Due", "Overdue", "Net Payable (INR)"], [[f[k] for k in ("name", "employee_code", "employee_name", "version", "status", "exit_date", "payment_due_date", "is_overdue", "net_payable_rupees")] for f in fnfs])])
	elif rt == "missing-data":
		emps = list_employees()
		rows = []
		for e in emps:
			miss = []
			for doc_k, info in e["readiness"].items():
				if not info["ready"]:
					miss.append(f"{doc_k}: {', '.join(info['missing'])}")
			if miss:
				rows.append([e["employee_code"], e["full_name"], e.get("client_site"), " | ".join(miss)])
		xlsx = build_xlsx_bytes([("Missing Data", ["Code", "Name", "Client Site", "Missing Fields"], rows)])
	else:
		revs = frappe.get_all("JEFS Wage Revision", fields=["name", "revision_name", "effective_from", "policy", "status", "approved_by"])
		xlsx = build_xlsx_bytes([("Wage Revisions", ["ID", "Name", "Effective From", "Policy", "Status", "Approved By"], [[r[k] for k in ("name", "revision_name", "effective_from", "policy", "status", "approved_by")] for r in revs])])

	write_audit_log("REPORT_EXPORT", "Report", rt)
	frappe.db.commit()
	_binary_response(xlsx, f"kesari_{rt}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@frappe.whitelist()
def list_audit_logs(limit: int = 100) -> list[dict[str, Any]]:
	require_jefs_role(("JEFS Admin", "JEFS Auditor"))
	return frappe.get_all("JEFS Audit Log", fields=["*"], order_by="logged_at desc", limit=int(limit))


@frappe.whitelist()
def get_ff_apps() -> list[dict[str, Any]]:
	"""Override frappe.apps.get_apps so only F&F (rebranded HRMS) appears in app launchers."""
	return [
		{
			"name": "hrms",
			"logo": "/assets/kesari_jefs/images/ff-logo.svg",
			"title": "F&F",
			"route": "/desk/kesari-jefs/jefs-dashboard",
			"setup_wizard_text": "Employee Joining & Exit Formality Software",
		}
	]


@frappe.whitelist()
def sync_all_with_hrms() -> dict[str, Any]:
	"""Run full bidirectional synchronization between Kesari JEFS and Frappe HR tables."""
	require_jefs_role(ALL_JEFS_ROLES)
	res = sync_all_hrms_records()
	write_audit_log("HRMS_FULL_SYNC", "System", "HRMS", after=res)
	frappe.db.commit()
	return res


@frappe.whitelist()
def get_employee_jefs_summary(frappe_employee: str) -> dict[str, Any]:
	"""Return linked JEFS status summary for native Frappe HR Employee form banner."""
	require_jefs_role(ALL_JEFS_ROLES)
	jefs_name = frappe.db.get_value("Employee", frappe_employee, "jefs_employee") or frappe.db.get_value(
		"JEFS Employee", {"frappe_employee": frappe_employee}, "name"
	)
	if not jefs_name or not frappe.db.exists("JEFS Employee", jefs_name):
		return {"linked": False}
	emp = frappe.get_doc("JEFS Employee", jefs_name)
	sals = frappe.get_all("JEFS Salary Record", filters={"employee_code": jefs_name}, fields=["*"], order_by="period desc", limit=1)
	nom_count = frappe.db.count("JEFS Employee Nominee", {"parent": jefs_name})
	readiness = _employee_readiness(emp.as_dict(), sals[0] if sals else None, nom_count)
	ready_count = sum(1 for v in readiness.values() if v["ready"])
	docs_count = frappe.db.count("JEFS Generated Document", {"employee_code": jefs_name, "is_void": 0})
	fnfs = frappe.get_all(
		"JEFS FnF Settlement",
		filters={"employee_code": jefs_name, "status": ["!=", "CANCELLED"]},
		fields=["name", "status", "net_payable_rupees"],
		order_by="version desc",
		limit=1,
	)
	return {
		"linked": True,
		"employee_code": emp.employee_code,
		"client_site": emp.client_site,
		"aadhaar_masked": emp.aadhaar_masked,
		"ready_count": ready_count,
		"kit_ready": ready_count == len(readiness),
		"docs_count": docs_count,
		"fnf_name": fnfs[0]["name"] if fnfs else "",
		"fnf_status": fnfs[0]["status"] if fnfs else "",
		"fnf_net_rupees": fnfs[0]["net_payable_rupees"] if fnfs else 0,
	}


@frappe.whitelist()
def sync_hrms_fnf_with_jefs(employee: str, fnf_name: str = "") -> dict[str, Any]:
	"""Triggered from native Full and Final Statement or Employee Separation to run JEFS F&F engine."""
	require_jefs_role(("JEFS Exit Desk", "JEFS Approver", "JEFS HR Onboarding", "JEFS Admin"))
	from kesari_jefs.services.hrms_bridge import on_hr_employee_update

	hr_doc = frappe.get_doc("Employee", employee)
	on_hr_employee_update(hr_doc)
	jefs_code = frappe.db.get_value("Employee", employee, "jefs_employee") or frappe.db.get_value(
		"JEFS Employee", {"frappe_employee": employee}, "name"
	)
	if not jefs_code:
		frappe.throw("Employee is not linked to Kesari JEFS yet.")
	emp = frappe.get_doc("JEFS Employee", jefs_code)
	if not emp.date_of_exit:
		ex_dt = str(hr_doc.relieving_date or "")
		if not ex_dt and fnf_name and frappe.db.exists("Full and Final Statement", fnf_name):
			ex_dt = str(frappe.db.get_value("Full and Final Statement", fnf_name, "relieving_date") or "")
		if not ex_dt:
			frappe.throw("Set Relieving Date on Employee or Full and Final Statement first.")
		emp.date_of_exit = ex_dt
		emp.last_working_day = ex_dt
		emp.status = "EXITED"
		emp.save(ignore_permissions=True)

	detail = initiate_fnf(jefs_code)
	fnf_doc = frappe.get_doc("JEFS FnF Settlement", detail["fnf"]["name"])
	if fnf_doc.status == "DRAFT":
		_compute_and_populate_fnf(fnf_doc, emp)
		fnf_doc.save(ignore_permissions=True)
	bridge_out = sync_fnf_to_hrms(fnf_doc)
	frappe.db.commit()
	return {"jefs_fnf": fnf_doc.name, "hrms": bridge_out}
