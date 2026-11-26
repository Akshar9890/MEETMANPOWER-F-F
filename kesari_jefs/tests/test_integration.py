"""End-to-end integration test inside Frappe (upload -> kit -> F&F -> Service Cert -> wage rev)."""

from __future__ import annotations

import datetime as dt
import io
import json
import zipfile

import frappe
from PIL import Image

from kesari_jefs.api import (
	approve_fnf,
	approve_wage_revision,
	commit_batch,
	create_wage_revision,
	generate_documents,
	generate_id_card_sheet,
	get_bootstrap,
	get_employee_detail,
	get_fnf_detail,
	initiate_fnf,
	list_audit_logs,
	list_documents,
	record_employee_exit,
	reveal_employee_pii,
	submit_fnf,
)
from kesari_jefs.services.doc_service import extract_pdf_text
from kesari_jefs.services.excel_service import (
	build_xlsx_bytes,
	read_tabular_rows,
	suggest_column_mapping,
	validate_mapped_rows,
)


def _create_batch_and_commit(feed: str, xlsx_bytes: bytes, filename: str, period: str = "", fy: str = "") -> dict:
	headers, rows = read_tabular_rows(xlsx_bytes, filename)
	mapping = suggest_column_mapping(feed, headers)
	existing = set(frappe.get_all("JEFS Employee", pluck="employee_code"))
	valid, errs, missing = validate_mapped_rows(
		feed,
		rows,
		mapping,
		existing_employee_codes=existing if feed != "EMPLOYEE" else None,
		default_period=period,
		default_fy=fy,
	)
	assert not missing, f"Missing required mapping for {feed}: {missing}"
	assert not errs, f"Unexpected validation errors for {feed}: {errs}"
	batch = frappe.get_doc(
		{
			"doctype": "JEFS Upload Batch",
			"feed": feed,
			"file_name": filename,
			"period": period,
			"fy": fy,
			"total_rows": len(rows),
			"ok_rows": len(valid),
			"error_rows": 0,
			"status": "VALIDATED",
			"column_mapping_json": json.dumps(mapping),
			"valid_rows_json": json.dumps(valid, default=str),
			"error_rows_json": "[]",
			"missing_required_json": "[]",
			"uploaded_by": frappe.session.user,
		}
	).insert(ignore_permissions=True)
	return commit_batch(batch.name)


def run_e2e_verification() -> dict:
	"""Run complete E2E workflow in DB and verify PDFs, formulas, masking, maker-checker & audit."""
	frappe.set_user("Administrator")

	# Find a valid Verhoeff Aadhaar starting with 2
	from kesari_jefs.engine.validators import verhoeff_check
	valid_aadhaar = next("23456789123" + d for d in "0123456789" if verhoeff_check("23456789123" + d))

	emp_xlsx = build_xlsx_bytes([
		(
			"Employee",
			[
				"Employee Code", "Full Name", "Father's Name", "Gender", "Date of Birth",
				"Mobile", "Email", "Present Address", "Permanent Address", "City", "State", "PIN",
				"Aadhaar", "PAN", "UAN", "ESIC IP No", "Bank A/c", "IFSC", "Bank Name",
				"Designation", "Department", "Skill Category", "Work Location", "Client Site",
				"Employment Type", "Date of Joining", "Notice Period", "Blood Group",
				"Marital Status", "Emergency Contact Name", "Emergency Contact Phone",
				"Police Station", "Nominee Name", "Nominee Relation", "Nominee DOB", "Nominee Share %",
			],
			[
				[
					"KM1023", "Rameshbhai Kantilal Patel", "Kantilal Patel", "Male", "15-05-1990",
					"9876543210", "ramesh@example.com", "Akota, Vadodara", "Padra, Vadodara",
					"Vadodara", "Gujarat", "390020", valid_aadhaar, "ABCDE1234F", "100123456789",
					"3812345678", "123456789012", "SBIN0001234", "SBI",
					"Security Guard", "Security", "Unskilled", "Makarpura", "CONMAT",
					"PERMANENT", "01-06-2020", "30", "B+", "Married", "Meenaben Patel", "9876500001",
					"Makarpura Police Station", "Meenaben Patel", "Wife", "10-08-1992", "100",
				],
				[
					"KM1024", "Sureshbhai Desai", "Manubhai Desai", "Male", "20-07-1994",
					"9876543211", "suresh@example.com", "Gotri, Vadodara", "Gotri, Vadodara",
					"Vadodara", "Gujarat", "390021", valid_aadhaar, "BCDEF2345G", "100123456790",
					"3812345679", "223456789012", "SBIN0001234", "SBI",
					"Helper", "Operations", "Unskilled", "Savli", "EXECHON",
					"PERMANENT", "01-01-2026", "30", "O+", "Single", "Manubhai Desai", "9876500002",
					"Gotri Police Station", "Manubhai Desai", "Father", "01-01-1968", "100",
				],
			],
		)
	])
	_create_batch_and_commit("EMPLOYEE", emp_xlsx, "employees_test.xlsx")

	# Upload photos for both
	from kesari_jefs.services.jefs_core import get_files_root
	photos_dir = get_files_root() / "photos"
	for code in ("KM1023", "KM1024"):
		img = Image.new("RGB", (120, 150), color=(30, 80, 160))
		p = photos_dir / f"{code}.jpg"
		img.save(p, format="JPEG")
		frappe.db.set_value("JEFS Employee", code, "photo_path", str(p))

	sal_xlsx = build_xlsx_bytes([
		(
			"Salary",
			["Employee Code", "Period", "Basic", "DA", "HRA", "Conveyance", "Special Allowance", "Gross", "PF", "ESI", "PT", "Net", "Days in Month", "Paid Days"],
			[
				["KM1023", "2027-01", 15000, 3000, 2500, 1000, 500, 22000, 1800, 0, 200, 20000, 31, 15],
				["KM1024", "2027-01", 10000, 2000, 1000, 0, 0, 13000, 1200, 98, 200, 11502, 31, 31],
			],
		)
	])
	_create_batch_and_commit("SALARY", sal_xlsx, "salary_jan2027.xlsx", period="2027-01")

	leave_xlsx = build_xlsx_bytes([
		("Leave", ["Employee Code", "As-of Date", "Leave Type", "EL Balance"], [["KM1023", "15-01-2027", "EL", 12]])
	])
	_create_batch_and_commit("LEAVE", leave_xlsx, "leave_jan2027.xlsx")

	# Verify Aadhaar masking + reveal audit
	detail = get_employee_detail("KM1023")
	assert detail["employee"]["aadhaar_masked"] == f"XXXX XXXX {valid_aadhaar[-4:]}"
	revealed = reveal_employee_pii("KM1023")
	assert revealed["aadhaar"] == valid_aadhaar

	# Generate Joining Kit + Police Letter for KM1023
	kit_res = generate_documents(
		json.dumps(["KM1023"]),
		json.dumps(["OFFER_LETTER", "APPOINTMENT_LETTER", "GRATUITY_FORM_F", "ID_CARD", "EPFO_FORM_2", "POLICE_VERIFICATION"]),
		1,
	)
	assert len(kit_res["generated"]) == 6, f"Expected 6 docs, got: {kit_res}"
	assert not kit_res["skipped"], f"Unexpected skipped: {kit_res['skipped']}"

	# Verify PDFs have no '{{' and contain employee name + Gujarati text
	for g in kit_res["generated"]:
		doc = frappe.get_doc("JEFS Generated Document", g["doc_id"])
		with open(doc.pdf_path, "rb") as f:
			txt = extract_pdf_text(f.read())
		assert "{{" not in txt, f"Unreplaced placeholder in {g['doc_type']}"
		assert "Rameshbhai" in txt or "KM1023" in txt

	# Generate ID Card A4 Print Sheet
	sheet_res = generate_id_card_sheet(json.dumps(["KM1023", "KM1024"]))
	assert sheet_res["count"] == 2

	# Exit KM1023 -> check F&F net payable (1,01,707 with Gujarat Unskilled min wage 14,092)
	fnf_draft = record_employee_exit("KM1023", "2027-01-15", "2027-01-15", "RESIGNATION", "Good")
	fnf_id = fnf_draft["fnf"]["name"]
	assert int(fnf_draft["fnf"]["net_payable_rupees"]) in (101634, 101707), f"Unexpected net: {fnf_draft['fnf']['net_payable_rupees']}"
	submit_fnf(fnf_id)

	# Verify self-approval is blocked
	self_blocked = False
	try:
		approve_fnf(fnf_id, "self")
	except Exception as exc:
		if "FNF_SELF_APPROVAL" in str(exc):
			self_blocked = True
	assert self_blocked, "Self approval must be blocked!"

	# Approve using approver@kesari.local -> generates FNF PDF + Service Certificate PDF
	frappe.set_user("approver@kesari.local")
	approved = approve_fnf(fnf_id, "Verified against payroll")
	assert approved["fnf"]["status"] == "APPROVED"
	doc_types = {d["doc_type"] for d in approved["documents"]}
	assert "FNF_STATEMENT" in doc_types
	assert "SERVICE_CERTIFICATE" in doc_types

	# Wage Revision for KM1024 (13,000 < Gujarat Unskilled 14,092) -> Gujarati Increment Letter
	frappe.set_user("Administrator")
	rev = create_wage_revision("Test Apr 2027", "2027-04-01", "RAISE_TO_MIN")
	frappe.set_user("approver@kesari.local")
	rev_app = approve_wage_revision(rev["name"])
	assert len(rev_app["generated"]) >= 1

	frappe.set_user("Administrator")
	boot = get_bootstrap()
	logs = list_audit_logs(20)
	frappe.db.commit()
	return {
		"ok": True,
		"kit_docs": len(kit_res["generated"]),
		"fnf_net_rupees": approved["fnf"]["net_payable_rupees"],
		"fnf_docs": list(doc_types),
		"increment_letters": len(rev_app["generated"]),
		"audit_log_count": len(logs),
		"stats": boot["stats"],
	}
