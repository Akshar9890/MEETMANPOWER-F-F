"""Core DB-backed services: seeding, audit log, statutory resolver, atomic ref sequence, Frappe sync."""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import frappe
from frappe.utils import now_datetime

from kesari_jefs.engine.fnf import FnfSettings, SiteRule
from kesari_jefs.engine.money import rupees_to_paise
from kesari_jefs.engine.validators import mask_aadhaar, mask_bank_account, mask_pan
from kesari_jefs.services.crypto import decrypt_field, encrypt_field
from kesari_jefs.services.doc_service import DOC_TYPE_PREFIX, extract_docx_placeholders
from kesari_jefs.services.templates_seed import SEAL_IMG_PATH, ensure_starter_docx_templates

JEFS_ROLES = [
	"JEFS Admin",
	"JEFS HR Onboarding",
	"JEFS Payroll Specialist",
	"JEFS Exit Desk",
	"JEFS Approver",
	"JEFS Auditor",
]

DEFAULT_STATUTORY_SETTINGS = [
	("bonus.eligibility_ceiling_paise", "2100000", "2026-04-01", "Code on Wages Notification S.O. 4711(E) ₹21,000/month"),
	("bonus.calc_ceiling_paise", "700000", "2026-04-01", "Code on Wages Notification S.O. 4710(E) ₹7,000 or min wage"),
	("bonus.min_pct", "8.33", "2026-04-01", "Code on Wages s.26 min bonus %"),
	("bonus.max_pct", "20", "2026-04-01", "Code on Wages s.26 max bonus %"),
	("bonus.company_pct", "8.33", "2026-04-01", "Default Kesari / Conmat company bonus %"),
	("bonus.min_working_days", "30", "2026-04-01", "Minimum working days in FY for bonus eligibility"),
	("gratuity.days", "15", "2025-11-21", "Code on Social Security s.53"),
	("gratuity.divisor", "26", "2025-11-21", "Monthly wage divisor (26 working days)"),
	("gratuity.cap_paise", "200000000", "2025-11-21", "₹20,00,000 statutory cap"),
	("gratuity.permanent_min_years", "5", "2025-11-21", "Permanent employee minimum years"),
	("gratuity.fixed_term_min_years", "1", "2025-11-21", "Fixed-term employee minimum years"),
	("gratuity.round_up_months_over", "6", "2025-11-21", "Part-year > 6 months counts as full year"),
	("gratuity.allow_4y240d_rule", "false", "2025-11-21", "4y 240 days eligibility (client confirmation OQ-09)"),
	("leave.encash_divisor", "26", "2026-04-01", "Leave encashment divisor (26 or 30)"),
	("leave.encash_wage", "BASIC_DA", "2026-04-01", "BASIC_DA or GROSS"),
	("salary.day_basis", "CALENDAR", "2026-04-01", "CALENDAR | FIXED_30 | FIXED_26"),
	("fnf.payment_due_working_days", "2", "2025-11-21", "Code on Wages s.17: 2 working days deadline"),
]

DEFAULT_SITE_RULES = [
	("CONMAT", "CONMAT HEAVY INDUSTRIES PVT. LTD.", "Vadodara, Gujarat", 1, 1, 1, 1, 1, "BONUS on min wage x days; LEAVE on actual wage x days other than PH; GRATUITY (Last Drawn x 15 x Years)/26"),
	("EXECHON", "EXECHON", "Gujarat", 1, 0, 1, 1, 0, "BONUS on min wage x days; GRATUITY (Last Drawn x 15 x Years)/26; LEAVE excluded"),
	("SAT", "SAT", "Gujarat", 1, 1, 1, 1, 1, "BONUS on min wage x days; LEAVE on actual wage x days other than PH; GRATUITY (Last Drawn x 15 x Years)/26"),
]


def get_files_root() -> Path:
	site_path = Path(frappe.get_site_path("private", "jefs_files"))
	site_path.mkdir(parents=True, exist_ok=True)
	for sub in ("uploads", "photos", "generated", "templates", "watcher"):
		(site_path / sub).mkdir(parents=True, exist_ok=True)
	return site_path


def write_audit_log(
	action: str,
	entity: str,
	entity_id: str = "",
	before: Any = None,
	after: Any = None,
) -> None:
	ip = ""
	try:
		ip = frappe.local.request_ip or ""
	except Exception:
		pass
	doc = frappe.get_doc(
		{
			"doctype": "JEFS Audit Log",
			"user_id": frappe.session.user or "System",
			"action": action,
			"entity": entity,
			"entity_id": str(entity_id or ""),
			"before_json": json.dumps(before, default=str) if before is not None else "",
			"after_json": json.dumps(after, default=str) if after is not None else "",
			"ip_address": ip,
			"logged_at": now_datetime(),
		}
	)
	doc.insert(ignore_permissions=True)


def get_user_jefs_roles(user: str | None = None) -> set[str]:
	u = user or frappe.session.user
	if u == "Administrator":
		return set(JEFS_ROLES) | {"System Manager"}
	roles = set(frappe.get_roles(u))
	if "System Manager" in roles or "HR Manager" in roles:
		return roles | set(JEFS_ROLES)
	return roles


def require_jefs_role(allowed: tuple[str, ...]) -> None:
	if frappe.session.user == "Guest":
		frappe.throw("AUTH_REQUIRED: Login required", frappe.AuthenticationError)
	user_roles = get_user_jefs_roles()
	if "System Manager" in user_roles or "JEFS Admin" in user_roles:
		return
	if not user_roles.intersection(allowed):
		frappe.throw("FORBIDDEN: Insufficient role permissions for this action", frappe.PermissionError)


def next_ref_no(doc_type: str, year: int | None = None) -> str:
	yr = year or dt.date.today().year
	prefix = frappe.db.get_single_value("JEFS Company Profile", "ref_prefix") or "KM"
	short = DOC_TYPE_PREFIX.get(doc_type, "DOC")

	row = frappe.db.sql(
		"""
		SELECT name, last_no
		FROM `tabJEFS Doc Sequence`
		WHERE doc_type = %s AND year = %s
		FOR UPDATE
		""",
		(doc_type, yr),
		as_dict=True,
	)
	if not row:
		seq_doc = frappe.get_doc(
			{
				"doctype": "JEFS Doc Sequence",
				"doc_type": doc_type,
				"year": yr,
				"last_no": 1,
			}
		)
		seq_doc.insert(ignore_permissions=True)
		num = 1
	else:
		num = int(row[0]["last_no"]) + 1
		frappe.db.set_value("JEFS Doc Sequence", row[0]["name"], "last_no", num)

	return f"{prefix}/{short}/{yr}/{num:06d}"


def resolve_fnf_settings(as_of: dt.date) -> FnfSettings:
	rows = frappe.get_all(
		"JEFS Statutory Setting",
		fields=["setting_key", "setting_value", "effective_from", "effective_to"],
		order_by="effective_from asc",
	)
	vals: dict[str, str] = {}
	for r in rows:
		eff_from = r["effective_from"]
		eff_to = r["effective_to"]
		if eff_from and eff_from <= as_of and (not eff_to or as_of <= eff_to):
			vals[r["setting_key"]] = str(r["setting_value"]).strip()

	working_days_str = frappe.db.get_single_value("JEFS Company Profile", "working_days") or "0,1,2,3,4,5"
	weekdays = tuple(int(x.strip()) for x in working_days_str.split(",") if x.strip().isdigit()) or (0, 1, 2, 3, 4, 5)

	return FnfSettings(
		day_basis=vals.get("salary.day_basis", "CALENDAR"),
		leave_encash_divisor=int(vals.get("leave.encash_divisor", "26")),
		leave_encash_wage=vals.get("leave.encash_wage", "BASIC_DA"),
		bonus_eligibility_ceiling_paise=int(vals.get("bonus.eligibility_ceiling_paise", "2100000")),
		bonus_calc_ceiling_paise=int(vals.get("bonus.calc_ceiling_paise", "700000")),
		bonus_company_pct=Decimal(vals.get("bonus.company_pct", "8.33")),
		bonus_min_working_days=int(vals.get("bonus.min_working_days", "30")),
		gratuity_days=int(vals.get("gratuity.days", "15")),
		gratuity_divisor=int(vals.get("gratuity.divisor", "26")),
		gratuity_cap_paise=int(vals.get("gratuity.cap_paise", "200000000")),
		gratuity_permanent_min_years=int(vals.get("gratuity.permanent_min_years", "5")),
		gratuity_fixed_term_min_years=int(vals.get("gratuity.fixed_term_min_years", "1")),
		gratuity_round_up_months_over=int(vals.get("gratuity.round_up_months_over", "6")),
		gratuity_allow_4y240d_rule=vals.get("gratuity.allow_4y240d_rule", "false").lower() == "true",
		payment_due_working_days=int(vals.get("fnf.payment_due_working_days", "2")),
		working_weekdays=weekdays,
	)


def resolve_site_rule(client_site: str | None) -> SiteRule:
	if not client_site:
		return SiteRule()
	code = client_site.strip().upper()
	if frappe.db.exists("JEFS Client Site Rule", code):
		doc = frappe.get_doc("JEFS Client Site Rule", code)
		return SiteRule(
			site_code=doc.site_code,
			include_bonus=bool(doc.include_bonus),
			include_leave=bool(doc.include_leave),
			include_gratuity=bool(doc.include_gratuity),
			bonus_on_min_wage_days=bool(doc.bonus_on_min_wage_days),
			leave_on_actual_wage_days=bool(doc.leave_on_actual_wage_days),
		)
	# Fuzzy prefix match (e.g. "CONMAT HEAVY INDUSTRIES PVT. LTD." -> CONMAT)
	for r in frappe.get_all("JEFS Client Site Rule", fields=["name", "site_code"]):
		if r["site_code"].upper() in code:
			doc = frappe.get_doc("JEFS Client Site Rule", r["name"])
			return SiteRule(
				site_code=doc.site_code,
				include_bonus=bool(doc.include_bonus),
				include_leave=bool(doc.include_leave),
				include_gratuity=bool(doc.include_gratuity),
				bonus_on_min_wage_days=bool(doc.bonus_on_min_wage_days),
				leave_on_actual_wage_days=bool(doc.leave_on_actual_wage_days),
			)
	return SiteRule(site_code=code)


def sync_to_frappe_employee(jefs_emp) -> str | None:
	"""Keep Frappe HRMS Employee record synced for HR Desk visibility."""
	from kesari_jefs.services.hrms_bridge import sync_jefs_to_hr_employee

	return sync_jefs_to_hr_employee(jefs_emp)


def seed_defaults() -> None:
	"""Idempotent seed for roles, company profile, statutory settings, client sites & templates."""
	for role_name in JEFS_ROLES:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1}).insert(ignore_permissions=True)

	# Ensure Company Profile single has Kesari defaults + seal image
	profile = frappe.get_single("JEFS Company Profile")
	if not profile.legal_name:
		profile.legal_name = "KESARI MANPOWER SOLUTIONS"
	if not profile.short_name:
		profile.short_name = "Kesari Manpower"
	if not profile.address:
		profile.address = "FLAT NO. 2, SHYAM NIWAS, 10, LAXMI COLONY, OPP. SANDALWOOD RESIDENCY, NR. URMI CROSS ROAD, AKOTA, VADODARA, 390020"
	if not profile.phone:
		profile.phone = "0265-3542931 / 9712898946"
	if not profile.email:
		profile.email = "kesarimanpower@gmail.com"
	if not profile.signatory_name:
		profile.signatory_name = "Meet Vyas"
	if not profile.signatory_designation:
		profile.signatory_designation = "Partner"
	if not profile.ref_prefix:
		profile.ref_prefix = "KM"
	if not profile.gotenberg_url:
		profile.gotenberg_url = "http://gotenberg:3000"
	if not profile.working_days:
		profile.working_days = "0,1,2,3,4,5"
	if not profile.signature_image_path and SEAL_IMG_PATH.exists():
		profile.signature_image_path = str(SEAL_IMG_PATH)
	if not profile.seal_image_path and SEAL_IMG_PATH.exists():
		profile.seal_image_path = str(SEAL_IMG_PATH)
	profile.save(ignore_permissions=True)

	# Seed Statutory Settings
	if frappe.db.count("JEFS Statutory Setting") == 0:
		for key, val, eff, note in DEFAULT_STATUTORY_SETTINGS:
			frappe.get_doc(
				{
					"doctype": "JEFS Statutory Setting",
					"setting_key": key,
					"setting_value": val,
					"effective_from": eff,
					"note": note,
					"is_verified": 0,
				}
			).insert(ignore_permissions=True)

	# Seed Client Site Rules (CONMAT, EXECHON, SAT)
	for code, name, addr, b, l, g, b_mw, l_aw, notes in DEFAULT_SITE_RULES:
		if not frappe.db.exists("JEFS Client Site Rule", code):
			frappe.get_doc(
				{
					"doctype": "JEFS Client Site Rule",
					"site_code": code,
					"site_name": name,
					"principal_employer_address": addr,
					"include_bonus": b,
					"include_leave": l,
					"include_gratuity": g,
					"bonus_on_min_wage_days": b_mw,
					"leave_on_actual_wage_days": l_aw,
					"notes": notes,
				}
			).insert(ignore_permissions=True)

	# Seed Starter .docx Templates
	starter_paths = ensure_starter_docx_templates()
	labels = {
		"OFFER_LETTER": "Kesari Offer Letter (Gujarati)",
		"APPOINTMENT_LETTER": "Kesari Appointment Letter OSHWC Sec 6(1)(f) (Gujarati)",
		"GRATUITY_FORM_F": "Form-IV Gratuity Nomination (SS Code 2020)",
		"EPFO_FORM_2": "EPFO New Form 11 / Form 2 Declaration",
		"POLICE_VERIFICATION": "Police Verification Letter & Employer Declaration",
		"INCREMENT_LETTER": "Kesari Increment Letter (Gujarati)",
		"SERVICE_CERTIFICATE": "Kesari Service / Experience Certificate",
	}
	for doc_type, file_path in starter_paths.items():
		if not frappe.db.exists("JEFS Template", {"doc_type": doc_type}):
			with open(file_path, "rb") as f:
				known, unknown = extract_docx_placeholders(f.read())
			frappe.get_doc(
				{
					"doctype": "JEFS Template",
					"doc_type": doc_type,
					"template_name": labels.get(doc_type, doc_type),
					"engine": "DOCX",
					"version": 1,
					"file_path": file_path,
					"placeholders_json": json.dumps(known),
					"unknown_placeholders_json": json.dumps(unknown),
					"is_active": 1,
					"notes": "Seeded starter template matching Kesari Manpower Solutions format",
				}
			).insert(ignore_permissions=True)

	# Seed HTML templates metadata for ID_CARD and FNF_STATEMENT
	for html_type, html_name in (
		("ID_CARD", "Form No. 18 Identity Card (CR-80 Front/Back & A4 10-up)"),
		("FNF_STATEMENT", "Full & Final Settlement Statement (With Formulas)"),
	):
		if not frappe.db.exists("JEFS Template", {"doc_type": html_type}):
			frappe.get_doc(
				{
					"doctype": "JEFS Template",
					"doc_type": html_type,
					"template_name": html_name,
					"engine": "HTML",
					"version": 1,
					"file_path": f"builtin://{html_type.lower()}",
					"placeholders_json": "[]",
					"unknown_placeholders_json": "[]",
					"is_active": 1,
					"notes": "Built-in pixel-exact Chromium PDF layout",
				}
			).insert(ignore_permissions=True)

	# Seed default Gujarat Minimum Wage rates (so Wage Revision works immediately out of the box)
	if frappe.db.count("JEFS Min Wage Rate") == 0:
		for skill, basic_r, vda_r in (
			("Unskilled", 11752, 2340),
			("Semi-Skilled", 12350, 2340),
			("Skilled", 12974, 2340),
			("Highly Skilled", 13650, 2340),
		):
			b_p = rupees_to_paise(basic_r)
			v_p = rupees_to_paise(vda_r)
			frappe.get_doc(
				{
					"doctype": "JEFS Min Wage Rate",
					"state": "Gujarat",
					"zone": "Zone-A",
					"skill_category": skill,
					"effective_from": "2026-10-01",
					"basic_paise": b_p,
					"vda_paise": v_p,
					"total_paise": b_p + v_p,
					"source_reference": "Gujarat Labour Dept Draft Seed (Verify before Apr-2027)",
				}
			).insert(ignore_permissions=True)

	# Seed default Wage Watcher source (Gujarat)
	if not frappe.db.exists("JEFS Wage Watcher Source", "gj-min-wages"):
		frappe.get_doc(
			{
				"doctype": "JEFS Wage Watcher Source",
				"source_id": "gj-min-wages",
				"state": "Gujarat",
				"url": "https://col.gujarat.gov.in/minimum-wages.htm",
				"selector": "a[href$='.pdf']",
				"keywords": "minimum wage,VDA,special allowance",
				"last_status": "PENDING",
			}
		).insert(ignore_permissions=True)

	# Seed Role-based Trial Users (including Approver for maker-checker workflow)
	demo_users = [
		("onboarding@kesari.local", "HR Onboarding", "JEFS HR Onboarding", "Kesari@2026"),
		("payroll@kesari.local", "Payroll Specialist", "JEFS Payroll Specialist", "Kesari@2026"),
		("exitdesk@kesari.local", "Exit Desk", "JEFS Exit Desk", "Kesari@2026"),
		("approver@kesari.local", "HR Head Approver", "JEFS Approver", "Kesari@2026"),
		("auditor@kesari.local", "Steering Auditor", "JEFS Auditor", "Kesari@2026"),
	]
	for email, first_name, role, pwd in demo_users:
		if not frappe.db.exists("User", email):
			u = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": first_name,
					"enabled": 1,
					"user_type": "System User",
					"new_password": pwd,
					"roles": [{"role": role}],
				}
			)
			u.insert(ignore_permissions=True)

	# Ensure Frappe Company exists for Kesari Manpower Solutions
	if not frappe.db.exists("Company", "Kesari Manpower Solutions"):
		if frappe.db.count("Company") == 0:
			try:
				frappe.get_doc(
					{
						"doctype": "Company",
						"company_name": "Kesari Manpower Solutions",
						"abbr": "KMS",
						"default_currency": "INR",
						"country": "India",
					}
				).insert(ignore_permissions=True)
			except Exception:
				pass

	get_files_root()
	from kesari_jefs.services.hrms_bridge import sync_all_hrms_records

	_sync_frappe_hr_sidebars()
	_sync_ff_branding()
	try:
		sync_all_hrms_records()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "JEFS Initial HRMS Backfill")
	frappe.cache.delete_key("dock_layers")
	frappe.cache.delete_key("bootinfo")
	frappe.db.commit()


FF_LOGO_URL = "/assets/kesari_jefs/images/ff-logo.svg"
_ATTENDANCE_KEEP_LABELS = {
	"Home",
	"Dashboard",
	"Attendance",
	"Employee Checkin",
	"Employee Attendance Tool",
	"Attendance Request",
	"Reports",
	"Monthly Attendance Sheet",
	"Settings",
}


def extend_bootinfo(bootinfo: Any) -> None:
	"""Isolate F&F completely from ERPNext, white-label UI, and keep Attendance/JEFS sidebars."""
	try:
		app_data = bootinfo.get("app_data") or []
		kept_apps = []
		for app in app_data:
			name = app.get("app_name")
			if name == "hrms":
				app["app_title"] = "F&F"
				app["app_logo_url"] = FF_LOGO_URL
				app["app_route"] = "/desk/kesari-jefs/jefs-dashboard"
				app["on_apps_screen"] = True
				app["sequence_id"] = 1
				kept_apps.append(app)
			elif name == "kesari_jefs":
				app["app_title"] = "F&F"
				app["app_logo_url"] = FF_LOGO_URL
				app["on_apps_screen"] = False
				kept_apps.append(app)
		bootinfo["app_data"] = kept_apps
		bootinfo["studio_apps"] = []
		bootinfo["flow_enabled"] = False
		bootinfo["app_logo_url"] = FF_LOGO_URL
		bootinfo["home_page"] = "jefs-dashboard"
		bootinfo["home_shell"] = "Kesari JEFS"

		user_obj = bootinfo.get("user")
		if isinstance(user_obj, dict):
			for perm_key in ("can_read", "can_create", "can_write", "all_read"):
				if isinstance(user_obj.get(perm_key), list):
					user_obj[perm_key] = [
						dt for dt in user_obj[perm_key]
						if dt not in ("Flow Session", "Flow Provider", "Flow Model", "Flow Agent", "Flow Run")
					]

		if bootinfo.get("navbar_settings") is not None:
			nb = bootinfo["navbar_settings"]
			if hasattr(nb, "app_logo"):
				nb.app_logo = FF_LOGO_URL
			elif isinstance(nb, dict):
				nb["app_logo"] = FF_LOGO_URL
			for key in ("help_dropdown", "settings_dropdown"):
				rows = nb.get(key) if hasattr(nb, "get") else None
				if isinstance(rows, list):
					kept = [
						row for row in rows
						if "frappe" not in str(row.get("item_label") or "").lower()
						and "frappe" not in str(row.get("route") or "").lower()
						and "erpnext" not in str(row.get("route") or "").lower()
					]
					if hasattr(nb, "set"):
						nb.set(key, kept)
					elif isinstance(nb, dict):
						nb[key] = kept
		if isinstance(bootinfo.get("sysdefaults"), dict):
			bootinfo["sysdefaults"]["app_name"] = "F&F"

		# Isolate Dock to F&F (hrms + kesari_jefs) only, removing ERPNext and Framework docks
		dock = bootinfo.get("dock") or {}
		if isinstance(dock, dict):
			for dk in list(dock.keys()):
				if dk != "hrms":
					dock.pop(dk, None)
			if isinstance(dock.get("hrms"), list):
				for row in dock["hrms"]:
					if isinstance(row, dict) and row.get("link_to") in ("Shift & Attendance", "Attendance"):
						row["title"] = "Attendance"

		# Strip all ERPNext sidebars and Flow/Studio sidebars from module_sidebars
		ms = bootinfo.get("module_sidebars") or {}
		removed_modules: set[str] = set()
		if isinstance(ms, dict):
			for mod_key in list(ms.keys()):
				sb = ms.get(mod_key)
				app_owner = sb.get("app") if isinstance(sb, dict) else None
				if app_owner == "erpnext" or mod_key in ("Flow", "Studio", "Build"):
					removed_modules.add(mod_key)
					ms.pop(mod_key, None)
			for sa_key in ("Shift & Attendance", "Attendance"):
				sa = ms.get(sa_key)
				if isinstance(sa, dict):
					sa["label"] = "Attendance"
					if isinstance(sa.get("items"), list):
						sa["items"] = [it for it in sa["items"] if it.get("label") in _ATTENDANCE_KEEP_LABELS]

		# Clean canonical_shell, entity_module, and workspaces so no ERPNext shell is ever picked
		cs = bootinfo.get("canonical_shell")
		if isinstance(cs, dict):
			for kind, mapping in cs.items():
				if isinstance(mapping, dict):
					for ename in list(mapping.keys()):
						if mapping[ename] in removed_modules:
							mapping[ename] = "Kesari JEFS"
		em = bootinfo.get("entity_module")
		if isinstance(em, dict):
			for kind, mapping in em.items():
				if isinstance(mapping, dict):
					for ename in list(mapping.keys()):
						if mapping[ename] in removed_modules:
							mapping.pop(ename, None)
		if isinstance(bootinfo.get("workspaces"), list):
			bootinfo["workspaces"] = [w for w in bootinfo["workspaces"] if w not in removed_modules]
	except Exception:
		frappe.log_error(frappe.get_traceback(), "JEFS Extend Bootinfo")


def _sync_ff_branding() -> None:
	"""Persist F&F branding, strip Frappe Support & videos, and trim Shift & Attendance -> Attendance."""
	try:
		frappe.db.set_single_value("System Settings", "app_name", "F&F")
	except Exception:
		pass
	try:
		ws = frappe.get_single("Website Settings")
		ws.app_name = "F&F"
		ws.app_logo = FF_LOGO_URL
		ws.favicon = FF_LOGO_URL
		ws.splash_image = FF_LOGO_URL
		ws.save(ignore_permissions=True)
	except Exception:
		pass
	try:
		ns = frappe.get_single("Navbar Settings")
		ns.app_logo = FF_LOGO_URL
		kept_help = []
		for row in ns.get("help_dropdown", []):
			lbl = str(row.get("item_label") or "").lower()
			rt = str(row.get("route") or "").lower()
			if "frappe" in lbl or "frappe" in rt or "erpnext" in rt:
				continue
			kept_help.append(row)
		ns.set("help_dropdown", kept_help)
		ns.save(ignore_permissions=True)
	except Exception:
		pass
	try:
		frappe.db.sql("UPDATE `tabOnboarding Step` SET intro_video_url = '', video_url = ''")
		if frappe.db.exists("Module Onboarding", "Shift and Attendance Onboarding"):
			mo = frappe.get_doc("Module Onboarding", "Shift and Attendance Onboarding")
			mo.title = "Track Attendance"
			keep_steps = {
				"Create Employee Checkin",
				"Create Attendance",
				"Create Attendance Request",
				"View Monthly Attendance Sheet",
			}
			mo.set("steps", [s for s in mo.steps if s.step in keep_steps])
			mo.flags.ignore_permissions = True
			mo.save(ignore_permissions=True)
		if frappe.db.exists("Workspace", "Shift & Attendance"):
			frappe.db.set_value("Workspace", "Shift & Attendance", "title", "Attendance", update_modified=False)
		for sb_name in ("Shift & Attendance", "Attendance"):
			if frappe.db.exists("Sidebar", sb_name):
				sb = frappe.get_doc("Sidebar", sb_name)
				sb.title = "Attendance"
				for it in sb.items:
					it.hidden = 0 if it.label in _ATTENDANCE_KEEP_LABELS else 1
				sb.flags.ignore_permissions = True
				sb.save(ignore_permissions=True)
		if frappe.db.exists("Dock", "hrms"):
			dk = frappe.get_doc("Dock", "hrms")
			changed = False
			for di in dk.items:
				if di.link_to in ("Shift & Attendance", "Attendance") and getattr(di, "title", None) != "Attendance":
					di.title = "Attendance"
					changed = True
			if changed:
				dk.flags.ignore_permissions = True
				dk.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "JEFS UI Cleanup")


def _sync_frappe_hr_sidebars() -> None:
	"""Expose JEFS addons and hide unused sections in Frappe HR sidebars."""
	try:
		from frappe.desk.doctype.custom_sidebar.custom_sidebar import (
			_save_customization,
			base_items,
			item_key,
		)

		addon_items_hr_setup = [
			{
				"type": "Section Break",
				"label": "Upload",
				"icon": "upload",
				"collapsible": 1,
				"keep_closed": 0,
				"indent": 1,
				"added": 1,
				"key": "jefs_sec_upload",
			},
			{"type": "Link", "label": "Employees Excel", "link_type": "Page", "link_to": "jefs-upload-employees", "icon": "file-spreadsheet", "child": 1, "added": 1},
			{"type": "Link", "label": "Salary Excel", "link_type": "Page", "link_to": "jefs-upload-salary", "icon": "file-spreadsheet", "child": 1, "added": 1},
			{"type": "Link", "label": "Bonus Report", "link_type": "Page", "link_to": "jefs-upload-bonus", "icon": "file-spreadsheet", "child": 1, "added": 1},
			{"type": "Link", "label": "Leave Report", "link_type": "Page", "link_to": "jefs-upload-leave", "icon": "file-spreadsheet", "child": 1, "added": 1},
			{"type": "Link", "label": "Employee Photos ZIP", "link_type": "Page", "link_to": "jefs-upload-photos", "icon": "image", "child": 1, "added": 1},
			{
				"type": "Section Break",
				"label": "Kesari JEFS Addons",
				"icon": "layers",
				"collapsible": 1,
				"keep_closed": 0,
				"indent": 1,
				"added": 1,
				"key": "jefs_sec_addons",
			},
			{"type": "Link", "label": "Joining Kit & Police Verification", "link_type": "Page", "link_to": "jefs-joining-kit", "icon": "shield-check", "child": 1, "added": 1},
			{"type": "Link", "label": "Exits & F&F Settlement", "link_type": "Page", "link_to": "jefs-fnf", "icon": "calculator", "child": 1, "added": 1},
			{"type": "Link", "label": "Service Certificates", "link_type": "Page", "link_to": "jefs-service-certificates", "icon": "award", "child": 1, "added": 1},
			{"type": "Link", "label": "Minimum Wages & Increment Letters", "link_type": "Page", "link_to": "jefs-wage-revision", "icon": "trending-up", "child": 1, "added": 1},
			{"type": "Link", "label": "Documents Register", "link_type": "Page", "link_to": "jefs-documents-register", "icon": "folder-open", "child": 1, "added": 1},
		]

		def _merge(
			mod_name: str,
			extra: list[dict],
			hide_labels: tuple[str, ...] = (),
			hide_sections: tuple[str, ...] = (),
		) -> None:
			if not frappe.db.exists("Module Def", mod_name):
				return
			base = base_items(mod_name)
			extra_targets = {it.get("link_to") or it.get("key") for it in extra}
			filtered_base = []
			current_section: str | None = None
			for orig in base:
				row = dict(orig)
				row["key"] = item_key(row)
				if row.get("type") == "Section Break":
					current_section = row.get("label")
				elif not row.get("child"):
					current_section = None
				if (row.get("link_to") or row.get("key")) in extra_targets:
					continue
				should_hide = (row.get("label") in hide_labels) or (current_section in hide_sections)
				row["hidden"] = 1 if should_hide else 0
				filtered_base.append(row)
			_save_customization(mod_name, filtered_base + extra, None)

		_merge("HR Setup", addon_items_hr_setup)
		_merge(
			"Leaves",
			[
				{"type": "Section Break", "label": "Kesari JEFS", "icon": "layers", "collapsible": 1, "keep_closed": 0, "indent": 1, "added": 1, "key": "jefs_sec_leaves"},
				{"type": "Link", "label": "Leave Report Upload", "link_type": "Page", "link_to": "jefs-upload-leave", "icon": "file-spreadsheet", "child": 1, "added": 1},
				{"type": "Link", "label": "Leave Encashment (F&F)", "link_type": "Page", "link_to": "jefs-fnf", "icon": "calculator", "child": 1, "added": 1},
				{"type": "Link", "label": "JEFS Dashboard", "link_type": "Page", "link_to": "jefs-dashboard", "icon": "layout-dashboard", "child": 1, "added": 1},
			],
		)
		_merge(
			"Tenure",
			[
				{"type": "Section Break", "label": "Kesari JEFS", "icon": "layers", "collapsible": 1, "keep_closed": 0, "indent": 1, "added": 1, "key": "jefs_sec_tenure"},
				{"type": "Link", "label": "Joining Kit & Police Verification", "link_type": "Page", "link_to": "jefs-joining-kit", "icon": "shield-check", "child": 1, "added": 1},
				{"type": "Link", "label": "Full and Final Statement", "link_type": "DocType", "link_to": "Full and Final Statement", "icon": "file-check", "child": 1, "added": 1},
				{"type": "Link", "label": "Exits & F&F Settlement", "link_type": "Page", "link_to": "jefs-fnf", "icon": "calculator", "child": 1, "added": 1},
				{"type": "Link", "label": "Service Certificates", "link_type": "Page", "link_to": "jefs-service-certificates", "icon": "award", "child": 1, "added": 1},
				{"type": "Link", "label": "Documents Register", "link_type": "Page", "link_to": "jefs-documents-register", "icon": "folder-open", "child": 1, "added": 1},
			],
			hide_sections=("Templates", "Grievance", "Training"),
		)
		_merge(
			"Recruitment",
			[
				{"type": "Section Break", "label": "Kesari JEFS", "icon": "layers", "collapsible": 1, "keep_closed": 0, "indent": 1, "added": 1, "key": "jefs_sec_recruitment"},
				{"type": "Link", "label": "Employees Excel Upload", "link_type": "Page", "link_to": "jefs-upload-employees", "icon": "file-spreadsheet", "child": 1, "added": 1},
				{"type": "Link", "label": "Joining Kit & Police Verification", "link_type": "Page", "link_to": "jefs-joining-kit", "icon": "shield-check", "child": 1, "added": 1},
				{"type": "Link", "label": "Documents Register", "link_type": "Page", "link_to": "jefs-documents-register", "icon": "folder-open", "child": 1, "added": 1},
			],
			hide_labels=("Hiring Pipeline", "Job Portal"),
			hide_sections=("Templates", "Planning"),
		)
		_merge(
			"Payroll",
			[
				{"type": "Section Break", "label": "Kesari JEFS", "icon": "layers", "collapsible": 1, "keep_closed": 0, "indent": 1, "added": 1, "key": "jefs_sec_payroll"},
				{"type": "Link", "label": "Salary Excel Upload", "link_type": "Page", "link_to": "jefs-upload-salary", "icon": "file-spreadsheet", "child": 1, "added": 1},
				{"type": "Link", "label": "Bonus Report Upload", "link_type": "Page", "link_to": "jefs-upload-bonus", "icon": "file-spreadsheet", "child": 1, "added": 1},
				{"type": "Link", "label": "Minimum Wages & Increment Letters", "link_type": "Page", "link_to": "jefs-wage-revision", "icon": "trending-up", "child": 1, "added": 1},
				{"type": "Link", "label": "Exits & F&F Settlement", "link_type": "Page", "link_to": "jefs-fnf", "icon": "calculator", "child": 1, "added": 1},
				{"type": "Link", "label": "Full and Final Statement", "link_type": "DocType", "link_to": "Full and Final Statement", "icon": "file-check", "child": 1, "added": 1},
			],
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "JEFS Sidebar Customization Sync")
