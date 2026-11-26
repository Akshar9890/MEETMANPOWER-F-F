"""DOCX template placeholder validator, renderer, Gotenberg PDF converter & atomic ref sequences."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import os
import re
import zipfile
from typing import Any

import qrcode
import requests
from docxtpl import DocxTemplate, InlineImage
from docx.shared import Mm
from pypdf import PdfReader, PdfWriter

DOC_TYPE_PREFIX = {
	"OFFER_LETTER": "OL",
	"APPOINTMENT_LETTER": "AL",
	"GRATUITY_FORM_F": "GF",
	"ID_CARD": "IC",
	"EPFO_FORM_2": "EPF",
	"POLICE_VERIFICATION": "PV",
	"INCREMENT_LETTER": "INC",
	"FNF_STATEMENT": "FNF",
	"SERVICE_CERTIFICATE": "SC",
}

ALLOWED_PLACEHOLDERS: dict[str, str] = {
	"ref_no": "Unique generated document reference number",
	"issue_date": "Document issue date (DD-MM-YYYY)",
	"company_name": "Legal company name",
	"company_short_name": "Company short name",
	"company_address": "Registered company address",
	"company_phone": "Company phone",
	"company_email": "Company email",
	"company_pf_code": "Company PF code",
	"company_esi_code": "Company ESI code",
	"signatory_name": "Authorized signatory name",
	"signatory_designation": "Authorized signatory designation",
	"signature_image": "Inline image of signatory signature & seal",
	"seal_image": "Inline image of company seal",
	"employee_code": "Employee code",
	"employee_name": "Full name",
	"first_name": "First name",
	"middle_name": "Middle name",
	"last_name": "Last name",
	"father_or_husband_name": "Father or husband name",
	"gender": "Gender",
	"dob": "Date of birth (DD-MM-YYYY)",
	"marital_status": "Marital status",
	"blood_group": "Blood group",
	"mobile": "10-digit mobile number",
	"email": "Email address",
	"present_address": "Present full address",
	"permanent_address": "Permanent full address",
	"aadhaar_masked": "Masked Aadhaar (XXXX XXXX 1234)",
	"aadhaar_full": "Full Aadhaar (official statutory forms only)",
	"pan_masked": "Masked PAN",
	"pan_full": "Full PAN (official statutory forms only)",
	"uan": "EPFO UAN",
	"esic_ip_no": "ESIC IP Number",
	"bank_account_masked": "Masked bank account number",
	"bank_account_full": "Full bank account number (statutory forms only)",
	"ifsc": "Bank IFSC code",
	"bank_name": "Bank name",
	"designation": "Designation",
	"department": "Department",
	"skill_category": "Skill category (Unskilled/Semi-Skilled/Skilled/Highly Skilled)",
	"work_location": "Work location",
	"principal_employer": "Principal employer / client site",
	"employment_type": "PERMANENT / FIXED_TERM / CONTRACT",
	"contract_end_date": "Contract end date",
	"date_of_joining": "Date of joining (DD-MM-YYYY)",
	"notice_period_days": "Notice period in days",
	"date_of_exit": "Date of exit (DD-MM-YYYY)",
	"last_working_day": "Last working day (DD-MM-YYYY)",
	"exit_reason": "Reason for separation",
	"conduct": "Conduct description",
	"tenure": "Service tenure (e.g. 6y 7m 15d)",
	"emergency_contact_name": "Emergency contact name",
	"emergency_contact_phone": "Emergency contact phone",
	"police_station": "Local police station name",
	"id_proof_type": "ID proof type",
	"id_proof_masked": "Masked ID proof number",
	"basic_wage": "Monthly basic wage (INR formatted)",
	"da_wage": "Monthly DA/VDA (INR formatted)",
	"hra_wage": "Monthly HRA (INR formatted)",
	"other_allowances": "Other allowances (INR formatted)",
	"gross_wage": "Monthly gross wage (INR formatted)",
	"daily_wage": "Daily wage rate (INR formatted)",
	"old_wage": "Old wage (INR formatted)",
	"new_wage": "New wage (INR formatted)",
	"vda_increase": "Wage / VDA delta (INR formatted)",
	"effective_from": "Effective from date (DD-MM-YYYY)",
	"effective_to": "Effective to date (DD-MM-YYYY)",
	"nominees": "List of nominees for Form IV / Form 2 loops",
	"photo_image": "Employee photo inline image",
	"qr_image": "Verification QR code inline image",
	"fnf_net_payable": "Net F&F payable (INR formatted)",
	"fnf_net_payable_words": "Net F&F payable in words",
	"payment_due_date": "F&F payment due date",
}

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)(?:\.[a-zA-Z0-9_]+)?\s*\}\}")
_FOR_VAR_RE = re.compile(r"\{%[-\s]*(?:tr\s+)?for\s+[a-zA-Z0-9_]+\s+in\s+([a-zA-Z0-9_]+)")
_LOOP_LOCALS = {"n", "nominee", "item", "row", "loop"}


def extract_docx_placeholders(docx_bytes: bytes) -> tuple[list[str], list[str]]:
	"""Inspect all XML parts in .docx for Jinja/Mustache variables and validate vs ALLOWED_PLACEHOLDERS."""
	text_chunks: list[str] = []
	with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
		for name in z.namelist():
			if name.startswith("word/") and name.endswith(".xml"):
				raw = z.read(name).decode("utf-8", errors="ignore")
				clean = re.sub(r"<[^>]+>", "", raw)
				text_chunks.append(clean)

	combined = "\n".join(text_chunks)
	found: set[str] = set()
	for m in _VAR_RE.finditer(combined):
		var = m.group(1)
		if var not in _LOOP_LOCALS:
			found.add(var)
	for m in _FOR_VAR_RE.finditer(combined):
		found.add(m.group(1))

	known = sorted(v for v in found if v in ALLOWED_PLACEHOLDERS)
	unknown = sorted(v for v in found if v not in ALLOWED_PLACEHOLDERS)
	return known, unknown


def build_qr_png_bytes(payload: str) -> bytes:
	img = qrcode.make(payload)
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	return buf.getvalue()


def render_docx_bytes(
	template_path: str,
	context: dict[str, Any],
	signature_path: str | None = None,
	photo_path: str | None = None,
	qr_payload: str | None = None,
) -> bytes:
	doc = DocxTemplate(template_path)
	ctx = dict(context)

	if signature_path and os.path.exists(signature_path):
		ctx["signature_image"] = InlineImage(doc, signature_path, width=Mm(42))
		ctx["seal_image"] = InlineImage(doc, signature_path, width=Mm(42))
	else:
		ctx.setdefault("signature_image", "")
		ctx.setdefault("seal_image", "")

	if photo_path and os.path.exists(photo_path):
		ctx["photo_image"] = InlineImage(doc, photo_path, width=Mm(24))
	else:
		ctx.setdefault("photo_image", "")

	if qr_payload:
		qr_buf = io.BytesIO(build_qr_png_bytes(qr_payload))
		ctx["qr_image"] = InlineImage(doc, qr_buf, width=Mm(20))
	else:
		ctx.setdefault("qr_image", "")

	doc.render(ctx)
	out = io.BytesIO()
	doc.save(out)
	return out.getvalue()


def get_gotenberg_url() -> str:
	env_url = os.environ.get("GOTENBERG_URL", "").strip()
	if env_url:
		return env_url.rstrip("/")
	try:
		import frappe
		url = frappe.db.get_single_value("JEFS Company Profile", "gotenberg_url")
		if url:
			return str(url).rstrip("/")
	except Exception:
		pass
	return "http://gotenberg:3000"


def convert_docx_to_pdf(docx_bytes: bytes, filename: str = "document.docx") -> bytes:
	url = f"{get_gotenberg_url()}/forms/libreoffice/convert"
	resp = requests.post(
		url,
		files={"files": (filename, docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
		timeout=60,
	)
	if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
		raise RuntimeError(f"DOC_PDF_CONVERSION_FAILED: Gotenberg returned {resp.status_code}")
	return resp.content


def convert_html_to_pdf(
	html_content: str,
	paper_width: str = "8.27",
	paper_height: str = "11.69",
	margin_top: str = "0.35",
	margin_bottom: str = "0.35",
	margin_left: str = "0.35",
	margin_right: str = "0.35",
) -> bytes:
	url = f"{get_gotenberg_url()}/forms/chromium/convert/html"
	resp = requests.post(
		url,
		files={"files": ("index.html", html_content.encode("utf-8"), "text/html")},
		data={
			"paperWidth": paper_width,
			"paperHeight": paper_height,
			"marginTop": margin_top,
			"marginBottom": margin_bottom,
			"marginLeft": margin_left,
			"marginRight": margin_right,
			"printBackground": "true",
		},
		timeout=60,
	)
	if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
		raise RuntimeError(f"DOC_PDF_CONVERSION_FAILED: Gotenberg HTML returned {resp.status_code}")
	return resp.content


def merge_pdfs(pdf_list: list[bytes]) -> bytes:
	writer = PdfWriter()
	for pdf_bytes in pdf_list:
		reader = PdfReader(io.BytesIO(pdf_bytes))
		for page in reader.pages:
			writer.add_page(page)
	out = io.BytesIO()
	writer.write(out)
	return out.getvalue()


def sha256_bytes(data: bytes) -> str:
	return hashlib.sha256(data).hexdigest()


def extract_pdf_text(pdf_bytes: bytes) -> str:
	reader = PdfReader(io.BytesIO(pdf_bytes))
	return "\n".join((page.extract_text() or "") for page in reader.pages)
