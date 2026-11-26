"""HTML-to-PDF layouts for CR-80 Form No. 18 ID Card (front/back & 10-up A4) and F&F Statement."""

from __future__ import annotations

import base64
import html
from pathlib import Path
from typing import Any

from kesari_jefs.engine.money import amount_in_words_inr, paise_to_rupees_str
from kesari_jefs.services.doc_service import build_qr_png_bytes


def _b64_img(path: str | None) -> str:
	if not path or not Path(path).exists():
		return ""
	data = Path(path).read_bytes()
	ext = path.rsplit(".", 1)[-1].lower()
	mime = "image/png" if ext == "png" else "image/jpeg"
	return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _b64_bytes(data: bytes, mime: str = "image/png") -> str:
	return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _esc(val: Any) -> str:
	return html.escape(str(val or ""))


def render_id_card_html(cards: list[dict[str, Any]], company: dict[str, Any]) -> str:
	"""Render CR-80 (54x86mm) front+back cards arranged cleanly on A4 sheet with crop marks."""
	sig_uri = _b64_img(company.get("signature_image_path"))
	card_blocks = []
	for c in cards:
		photo_uri = _b64_img(c.get("photo_path"))
		qr_uri = _b64_bytes(build_qr_png_bytes(f"KM|{c['employee_code']}|{c['full_name']}"))
		photo_html = (
			f'<img src="{photo_uri}" class="emp-photo" />'
			if photo_uri
			else '<div class="emp-photo placeholder">PHOTO</div>'
		)
		sig_html = f'<img src="{sig_uri}" class="sig-img" />' if sig_uri else ""
		card_blocks.append(
			f"""
			<div class="card-pair">
				<div class="card front">
					<div class="hdr">
						<div class="co-name">{_esc(company.get("legal_name"))}</div>
						<div class="form-tag">Form No. 18 · Sec 33 OSHWC Code 2020 · Rule 31</div>
					</div>
					<div class="top-row">
						{photo_html}
						<div class="qr-box"><img src="{qr_uri}" class="qr-img" /></div>
					</div>
					<div class="emp-name">{_esc(c.get("full_name"))}</div>
					<div class="emp-code">ID: {_esc(c.get("employee_code"))} · {_esc(c.get("designation"))}</div>
					<div class="meta">
						<div><b>Site:</b> {_esc(c.get("principal_employer"))}</div>
						<div><b>DOB:</b> {_esc(c.get("dob"))} &nbsp;|&nbsp; <b>DOJ:</b> {_esc(c.get("date_of_joining"))}</div>
						<div><b>Blood Group:</b> {_esc(c.get("blood_group") or "N/A")}</div>
						<div><b>PF / UAN:</b> {_esc(c.get("uan") or "-")} &nbsp;|&nbsp; <b>ESIC:</b> {_esc(c.get("esic_ip_no") or "-")}</div>
						<div><b>Ref:</b> {_esc(c.get("ref_no"))}</div>
					</div>
				</div>
				<div class="card back">
					<div class="back-hdr">IDENTITY CARD — BACK</div>
					<div class="meta">
						<div><b>Address:</b> {_esc(c.get("present_address"))}</div>
						<div><b>Emergency Contact:</b> {_esc(c.get("emergency_contact_name"))} ({_esc(c.get("emergency_contact_phone"))})</div>
						<div><b>Issue Date:</b> {_esc(c.get("issue_date"))}</div>
						<div class="return-box">
							<b>If found, please return to:</b><br/>
							{_esc(company.get("legal_name"))}<br/>
							{_esc(company.get("address"))}<br/>
							Ph: {_esc(company.get("phone"))}
						</div>
					</div>
					<div class="sign-row">
						<div>Card Holder Sign</div>
						<div class="right">{sig_html}<div>Sign of Contractor</div></div>
					</div>
				</div>
			</div>
			"""
		)

	return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
@page {{ size: A4; margin: 8mm; }}
* {{ box-sizing: border-box; font-family: 'Noto Sans Gujarati', 'Noto Sans', Arial, sans-serif; }}
body {{ margin: 0; padding: 0; background: #fff; }}
.sheet {{ display: flex; flex-wrap: wrap; gap: 6mm; }}
.card-pair {{ display: flex; gap: 3mm; page-break-inside: avoid; border: 0.3pt dashed #999; padding: 2mm; }}
.card {{
	width: 54mm; height: 86mm; border: 1pt solid #1b365d; border-radius: 2mm;
	padding: 2.5mm; display: flex; flex-direction: column; justify-content: space-between;
	position: relative; overflow: hidden; background: #fff;
}}
.hdr {{ background: #1b365d; color: #fff; padding: 1.5mm; margin: -2.5mm -2.5mm 1.5mm -2.5mm; text-align: center; }}
.co-name {{ font-size: 6.8pt; font-weight: 700; letter-spacing: 0.2px; }}
.form-tag {{ font-size: 5pt; opacity: 0.9; }}
.top-row {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1mm; }}
.emp-photo {{ width: 20mm; height: 24mm; object-fit: cover; border: 0.6pt solid #cbd5e1; border-radius: 1mm; }}
.emp-photo.placeholder {{ display: flex; align-items: center; justify-content: center; font-size: 6pt; color: #64748b; background: #f1f5f9; }}
.qr-img {{ width: 17mm; height: 17mm; }}
.emp-name {{ font-size: 8.5pt; font-weight: 700; color: #0f172a; line-height: 1.15; max-height: 7mm; overflow: hidden; }}
.emp-code {{ font-size: 6.5pt; font-weight: 600; color: #1b365d; margin-bottom: 1mm; }}
.meta {{ font-size: 5.8pt; line-height: 1.35; color: #334155; }}
.back-hdr {{ font-size: 7pt; font-weight: 700; color: #1b365d; border-bottom: 0.6pt solid #1b365d; padding-bottom: 1mm; text-align: center; }}
.return-box {{ margin-top: 2mm; padding: 1.5mm; background: #f8fafc; border: 0.4pt solid #cbd5e1; font-size: 5.3pt; }}
.sign-row {{ display: flex; justify-content: space-between; align-items: flex-end; font-size: 5.5pt; border-top: 0.4pt solid #cbd5e1; padding-top: 1mm; }}
.sign-row .right {{ text-align: right; }}
.sig-img {{ height: 10mm; display: block; margin-left: auto; }}
</style>
</head>
<body>
<div class="sheet">
{"".join(card_blocks)}
</div>
</body>
</html>"""


def render_fnf_statement_html(fnf: dict[str, Any], emp: dict[str, Any], company: dict[str, Any], ref_no: str) -> str:
	"""Render Full & Final Settlement Statement PDF matching 08_UI_SPEC.md §4."""
	sig_uri = _b64_img(company.get("signature_image_path"))
	sig_html = f'<img src="{sig_uri}" style="height:48px;" />' if sig_uri else ""
	earnings = [l for l in fnf.get("lines", []) if l.get("line_type") == "EARNING"]
	deductions = [l for l in fnf.get("lines", []) if l.get("line_type") == "DEDUCTION"]

	def rows_html(items: list[dict[str, Any]]) -> str:
		out = []
		for it in items:
			out.append(
				f"<tr><td>{_esc(it['label'])}</td><td class='mono'>{_esc(it['formula_text'])}</td><td class='num'>₹{paise_to_rupees_str(int(it['amount_paise']))}</td></tr>"
			)
		return "".join(out) or "<tr><td colspan='3' class='muted'>None</td></tr>"

	overdue_banner = (
		"<div class='warn'>⚠ Overdue beyond statutory 2-working-day payment deadline (Code on Wages s.17)</div>"
		if fnf.get("is_overdue")
		else ""
	)
	warnings = fnf.get("warnings", [])
	warn_html = (
		"<div class='notes'><b>Notes / Warnings:</b><ul>"
		+ "".join(f"<li>{_esc(w)}</li>" for w in warnings)
		+ "</ul></div>"
		if warnings
		else ""
	)

	net_paise = int(fnf.get("net_payable_paise", 0))
	return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
@page {{ size: A4; margin: 14mm; }}
body {{ font-family: 'Noto Sans', Arial, sans-serif; color: #0f172a; font-size: 11px; }}
.header {{ border-bottom: 2px solid #1b365d; padding-bottom: 8px; margin-bottom: 10px; display: flex; justify-content: space-between; }}
.co {{ font-size: 15px; font-weight: 700; color: #1b365d; }}
.sub {{ font-size: 9px; color: #475569; }}
.ref {{ text-align: right; font-size: 10px; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 4px 16px; background: #f8fafc; border: 1px solid #cbd5e1; padding: 8px; margin-bottom: 12px; font-size: 10.5px; }}
table {{ width: 100%; border-collapse: collapse; margin-bottom: 10px; }}
th, td {{ border: 1px solid #cbd5e1; padding: 6px 8px; text-align: left; }}
th {{ background: #e2e8f0; font-size: 10px; text-transform: uppercase; }}
.num {{ text-align: right; font-weight: 600; white-space: nowrap; }}
.mono {{ font-family: monospace; font-size: 10px; color: #334155; }}
.total-row {{ background: #f1f5f9; font-weight: 700; }}
.net-box {{ background: #1b365d; color: #fff; padding: 10px 12px; display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 700; margin: 10px 0 4px; }}
.words {{ font-size: 10.5px; font-style: italic; margin-bottom: 10px; }}
.warn {{ background: #fef2f2; border: 1px solid #ef4444; color: #b91c1c; padding: 6px 8px; margin-bottom: 8px; font-weight: 600; }}
.notes {{ background: #fffbeb; border: 1px solid #f59e0b; padding: 6px 10px; margin-bottom: 10px; font-size: 10px; }}
.sigs {{ display: flex; justify-content: space-between; margin-top: 26px; font-size: 10px; text-align: center; }}
.sigs > div {{ width: 30%; border-top: 1px solid #64748b; padding-top: 4px; }}
.muted {{ color: #64748b; text-align: center; }}
</style>
</head>
<body>
<div class="header">
  <div>
    <div class="co">{_esc(company.get("legal_name"))} — FULL &amp; FINAL SETTLEMENT</div>
    <div class="sub">{_esc(company.get("address"))}</div>
  </div>
  <div class="ref">
    <div><b>Ref:</b> {_esc(ref_no)}</div>
    <div><b>Version:</b> v{_esc(fnf.get("version", 1))} ({_esc(fnf.get("status"))})</div>
  </div>
</div>

{overdue_banner}

<div class="grid">
  <div><b>Employee:</b> {_esc(emp.get("full_name"))} ({_esc(emp.get("employee_code"))})</div>
  <div><b>Client Site:</b> {_esc(emp.get("client_site"))}</div>
  <div><b>Designation:</b> {_esc(emp.get("designation"))}</div>
  <div><b>Employment Type:</b> {_esc(emp.get("employment_type"))}</div>
  <div><b>Date of Joining:</b> {_esc(emp.get("date_of_joining"))}</div>
  <div><b>Last Working Day:</b> {_esc(fnf.get("last_working_day"))}</div>
  <div><b>Service Tenure:</b> {_esc(fnf.get("tenure_display"))} (Counted: {_esc(fnf.get("counted_years"))} yrs)</div>
  <div><b>Exit Reason:</b> {_esc(fnf.get("exit_reason"))}</div>
</div>

<table>
  <thead><tr><th style="width:42%">EARNINGS</th><th style="width:40%">Formula</th><th style="width:18%;text-align:right">Amount</th></tr></thead>
  <tbody>
    {rows_html(earnings)}
    <tr class="total-row"><td colspan="2">Total Earnings</td><td class="num">₹{paise_to_rupees_str(int(fnf.get("total_earnings_paise", 0)))}</td></tr>
  </tbody>
</table>

<table>
  <thead><tr><th style="width:42%">DEDUCTIONS</th><th style="width:40%">Formula</th><th style="width:18%;text-align:right">Amount</th></tr></thead>
  <tbody>
    {rows_html(deductions)}
    <tr class="total-row"><td colspan="2">Total Deductions</td><td class="num">₹{paise_to_rupees_str(int(fnf.get("total_deductions_paise", 0)))}</td></tr>
  </tbody>
</table>

<div class="net-box">
  <span>NET PAYABLE</span>
  <span>₹{paise_to_rupees_str(net_paise)}</span>
</div>
<div class="words">({amount_in_words_inr(net_paise)})</div>
<div style="font-size:10px;margin-bottom:8px;"><b>Payment due by:</b> {_esc(fnf.get("payment_due_date"))} (Code on Wages s.17 — 2 working days)</div>

{warn_html}

<div style="text-align:right; margin-top: 12px;">{sig_html}</div>
<div class="sigs">
  <div>Prepared by<br/>{_esc(fnf.get("prepared_by"))}</div>
  <div>Approved by<br/>{_esc(fnf.get("approved_by") or "Pending")}</div>
  <div>Employee Acknowledgement<br/>{_esc(emp.get("full_name"))}</div>
</div>
</body>
</html>"""
