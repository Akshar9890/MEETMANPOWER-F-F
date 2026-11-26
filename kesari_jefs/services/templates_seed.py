"""Generate starter .docx templates using the real Kesari Manpower Solutions formats + seal PNG."""

from __future__ import annotations

import os
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Mm, Pt, RGBColor

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "docx"
SEAL_IMG_PATH = Path(__file__).resolve().parent.parent / "templates" / "assets" / "kesari_seal_sig.png"


def _add_letterhead(doc: Document) -> None:
	h1 = doc.add_paragraph()
	h1.alignment = WD_ALIGN_PARAGRAPH.CENTER
	r1 = h1.add_run("{{company_name}}")
	r1.bold = True
	r1.font.size = Pt(15)
	r1.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)

	h2 = doc.add_paragraph()
	h2.alignment = WD_ALIGN_PARAGRAPH.CENTER
	r2 = h2.add_run("{{company_address}}\nPH: {{company_phone}} | E-mail: {{company_email}}")
	r2.font.size = Pt(9)

	ref_p = doc.add_paragraph()
	ref_p.add_run("Ref No: {{ref_no}}").bold = True
	ref_p.add_run("                                                Date / તારીખ: {{issue_date}}")


def _add_signatory(doc: Document, label: str = "For, {{company_name}}") -> None:
	p = doc.add_paragraph()
	p.add_run(f"\n{label}\n")
	p.add_run("{{signature_image}}\n")
	r = p.add_run("{{signatory_name}}\n{{signatory_designation}}")
	r.bold = True


def _build_offer_letter(out_path: Path) -> None:
	doc = Document()
	_add_letterhead(doc)
	t = doc.add_paragraph()
	t.alignment = WD_ALIGN_PARAGRAPH.CENTER
	rt = t.add_run("OFFER LETTER")
	rt.bold = True
	rt.underline = True
	rt.font.size = Pt(13)

	doc.add_paragraph("પ્રતિ,\nશ્રી/શ્રીમતી {{employee_name}} ({{employee_code}})\n{{present_address}}\nમોબાઈલ નં.: {{mobile}}")
	doc.add_paragraph(
		"તમારી અરજી અને અમારી સાથેના તમારા ઇન્ટરવ્યૂના સંદર્ભમાં, {{company_name}} નું મેનેજમેન્ટ તમને અમારી ક્લાયન્ટ સાઇટ "
		"{{principal_employer}} પર \"{{designation}}\" ({{skill_category}}) તરીકે તા. {{date_of_joining}} થી અમારી સંસ્થામાં રોજગાર ઓફર કરવામાં ખુશ છે."
	)
	doc.add_paragraph("તમારી નોકરીની મુખ્ય શરતો નીચે મુજબ રહેશે:")
	terms = [
		"માસિક/દૈનિક વેતન: ₹{{gross_wage}} (Basic: ₹{{basic_wage}}, DA: ₹{{da_wage}}, HRA: ₹{{hra_wage}}) Gross Salary.",
		"કામનું સ્થળ: {{work_location}} ({{principal_employer}}).",
		"કામનો સમય: કંપનીના નિયમો મુજબ (૮ કલાક) રહેશે.",
		"સાપ્તાહિક રજા અને અન્ય રજાઓ કંપનીના નિયમો તથા લાગુ કાયદા મુજબ મળશે.",
		"કંપનીના નિયમો, શિસ્ત અને સલામતીના નિયમોનું પાલન કરવું ફરજિયાત રહેશે.",
		"PF (UAN: {{uan}}), ESIC ({{esic_ip_no}}) તથા અન્ય કાયદાકીય લાભો લાગુ પડતા નિયમો મુજબ આપવામાં આવશે.",
		"નોકરી દરમિયાન કંપનીની કોઈપણ ગુપ્ત માહિતી બહાર જાહેર કરવી નહીં.",
	]
	for item in terms:
		doc.add_paragraph(f"• {item}")
	doc.add_paragraph("જો ઉપરોક્ત શરતો સ્વીકાર્ય હોય તો આ પત્ર પર સહી કરીને તેની એક નકલ કંપનીને પરત આપશો.")
	_add_signatory(doc, "કેસરી મેનપાવર સોલ્યુસન્સ વતી,")
	doc.add_paragraph("\nકર્મચારીની સ્વીકૃતિ:\nહું, શ્રી/શ્રીમતી {{employee_name}}, ઉપર જણાવેલ તમામ શરતો વાંચી, સમજી અને સ્વીકારું છું.\nકર્મચારીની સહી: ____________________   તારીખ: ______________")
	doc.save(out_path)


def _build_appointment_letter(out_path: Path) -> None:
	doc = Document()
	_add_letterhead(doc)
	t = doc.add_paragraph()
	t.alignment = WD_ALIGN_PARAGRAPH.CENTER
	r1 = t.add_run("નિમણુક પત્ર (APPOINTMENT LETTER)\n")
	r1.bold = True
	r1.font.size = Pt(13)
	t.add_run("Section 6(1)(f) OSHWC Code, 2020 & See Rule 10").italic = True

	doc.add_paragraph("પ્રતિ,\n{{employee_name}} ({{employee_code}})\n{{present_address}}\nમોબાઈલ નં.:- {{mobile}}")
	doc.add_paragraph(
		"આથી તમોને તમારા ઇન્ટરવ્યૂના અનુસંધાનમાં આ નિમણુક પત્ર આપી આપની નિમણૂક, આપણી સંસ્થાના {{principal_employer}} "
		"કંપની (પ્રિન્સિપલ એમ્પ્લોયર) ખાતે ચાલતા કોન્ટ્રાક્ટમાં કરવામાં આવે છે."
	)
	doc.add_paragraph("શરતો અને નિયમો:")
	clauses = [
		"શ્રી/શ્રીમતી {{employee_name}} ની નિમણૂક સંસ્થામાં તા. {{date_of_joining}} થી {{employment_type}} પ્રકારમાં {{designation}} હોદ્દા પર ({{skill_category}}) તરીકે કરવામાં આવે છે. જન્મ તારીખ: {{dob}}, પિતાનું/પતિનું નામ: {{father_or_husband_name}}, આધાર નં.: {{aadhaar_masked}}, કર્મચારી કોડ: {{employee_code}}, UAN: {{uan}}.",
		"તમારો માસિક પગાર: બેઝીક ₹{{basic_wage}}, DA/VDA ₹{{da_wage}}, HRA ₹{{hra_wage}}, કુલ Gross ₹{{gross_wage}} રહેશે. કોડ ઓન વેજીસ, ૨૦૧૯ અને કોડ ઓન સોશિયલ સિક્યોરિટી, ૨૦૨૦ મુજબ લાભ મળશે.",
		"તમને જયારે અને જે કામ તમારા સુપરવાઈઝર અથવા પ્રિન્સીપલ એમ્પ્લોયરના અધિકારી દ્વારા સોંપવામાં આવે તે નિભાવવાનું રહેશે.",
		"કામની જરૂરિયાત મુજબ કોઈપણ પાળીમાં નિમણુક તથા અન્ય સાઇટ પર બદલી સ્વીકાર્ય રહેશે.",
		"તમારી દૈનિક કામની મુદત આંઠ (૮) કલાકની રહેશે. નોટિસ સમય: {{notice_period_days}} દિવસ.",
		"નોકરી છોડવાના સમયે કંપની પ્રોપર્ટી (સેફ્ટિ શૂઝ, યુનિફોર્મ, ID કાર્ડ) પરત કરવાની રહેશે; નહીંતર F&F માંથી કપાત કરવામાં આવશે.",
	]
	for i, c in enumerate(clauses, 1):
		doc.add_paragraph(f"{i}. {c}")
	_add_signatory(doc, "કેસરી મેનપાવર સોલ્યુસન્સ વતી,")
	doc.add_paragraph("\n- કર્મચારી દ્વારા સ્વીકૃતી -\nહું {{employee_name}} ઉપરોક્ત નિયમો તથા શરતો સમજી સ્વીકારું છું.\nતારીખ: ____________   કર્મચારીની સહી: __________________")
	doc.save(out_path)


def _build_gratuity_form_iv(out_path: Path) -> None:
	doc = Document()
	_add_letterhead(doc)
	t = doc.add_paragraph()
	t.alignment = WD_ALIGN_PARAGRAPH.CENTER
	t.add_run("FORM-IV / FORM F\n").bold = True
	t.add_run("[See rule 6(1), (2), (3) and (4) — Code on Social Security, 2020]\nNomination / Fresh Nomination / Modification of Nomination")

	doc.add_paragraph("To,\n{{company_name}}\n{{company_address}}")
	doc.add_paragraph(
		"I, Shri/Shrimati/Kumari {{employee_name}} (Emp Code: {{employee_code}}), whose particulars are given below, "
		"hereby nominate the person(s) mentioned below to receive the gratuity payable after my death under the Code on Social Security, 2020."
	)

	tbl = doc.add_table(rows=4, cols=4)
	tbl.style = "Table Grid"
	hdr = tbl.rows[0].cells
	hdr[0].text = "Name & Address of Nominee(s)"
	hdr[1].text = "Relationship with Employee"
	hdr[2].text = "DOB / Age"
	hdr[3].text = "Proportion / Share (%)"
	tbl.rows[1].cells[0].text = "{%tr for n in nominees %}"
	row = tbl.rows[2].cells
	row[0].text = "{{n.name}} ({{n.address}})"
	row[1].text = "{{n.relationship}}"
	row[2].text = "{{n.dob}}"
	row[3].text = "{{n.share_pct}}%"
	tbl.rows[3].cells[0].text = "{%tr endfor %}"

	doc.add_paragraph("\nStatement of Employee Particulars:")
	details = [
		("Employee Name", "{{employee_name}}"),
		("Father's / Husband's Name", "{{father_or_husband_name}}"),
		("Gender / Marital Status", "{{gender}} / {{marital_status}}"),
		("Department / Designation", "{{department}} / {{designation}}"),
		("Date of Appointment", "{{date_of_joining}}"),
		("Permanent Address", "{{permanent_address}}"),
		("Mobile / Email", "{{mobile}} / {{email}}"),
	]
	st_tbl = doc.add_table(rows=len(details), cols=2)
	st_tbl.style = "Table Grid"
	for idx, (k, v) in enumerate(details):
		st_tbl.rows[idx].cells[0].text = k
		st_tbl.rows[idx].cells[1].text = v

	doc.add_paragraph("\nSignature/Thumb-impression of Employee: __________________   Place: Vadodara   Date: {{issue_date}}")
	doc.add_paragraph("\nCERTIFICATE BY THE EMPLOYER\nCertified that the particulars of the above nomination have been verified and recorded (Ref: {{ref_no}}).")
	_add_signatory(doc)
	doc.save(out_path)


def _build_epfo_form_11(out_path: Path) -> None:
	doc = Document()
	_add_letterhead(doc)
	t = doc.add_paragraph()
	t.alignment = WD_ALIGN_PARAGRAPH.CENTER
	t.add_run("EMPLOYEES' PROVIDENT FUND ORGANISATION\nNew Form: 11 Declaration Form (EPF Scheme 1952 & EPS 1995)").bold = True

	fields = [
		("1. Name of Member (Aadhaar Name)", "{{employee_name}}"),
		("2. Father's / Spouse's Name", "{{father_or_husband_name}}"),
		("3. Date of Birth", "{{dob}}"),
		("4. Gender / Marital Status", "{{gender}} / {{marital_status}}"),
		("5. Mobile / Email ID", "{{mobile}} / {{email}}"),
		("6. Aadhaar Number", "{{aadhaar_full}}"),
		("7. PAN", "{{pan_full}}"),
		("8. Bank A/c & IFSC", "{{bank_account_full}} / {{ifsc}}"),
		("9. Previous UAN (if any)", "{{uan}}"),
	]
	tbl = doc.add_table(rows=len(fields), cols=2)
	tbl.style = "Table Grid"
	for i, (k, v) in enumerate(fields):
		tbl.rows[i].cells[0].text = k
		tbl.rows[i].cells[1].text = v

	doc.add_paragraph("\nNominee Details (Form 2 Revised / PF & EPS):")
	ntbl = doc.add_table(rows=4, cols=4)
	ntbl.style = "Table Grid"
	nh = ntbl.rows[0].cells
	nh[0].text = "Purpose"
	nh[1].text = "Nominee Name"
	nh[2].text = "Relationship"
	nh[3].text = "Share %"
	ntbl.rows[1].cells[0].text = "{%tr for n in nominees %}"
	nr = ntbl.rows[2].cells
	nr[0].text = "{{n.purpose}}"
	nr[1].text = "{{n.name}}"
	nr[2].text = "{{n.relationship}}"
	nr[3].text = "{{n.share_pct}}%"
	ntbl.rows[3].cells[0].text = "{%tr endfor %}"

	doc.add_paragraph(
		"\nUNDERTAKING: Certified that the particulars are true to the best of my knowledge.\n"
		"Date: {{issue_date}}   Signature of Member: __________________"
	)
	doc.add_paragraph(
		"\nDECLARATION BY PRESENT EMPLOYER\n"
		"The member Mr./Ms./Mrs. {{employee_name}} ({{employee_code}}) has joined on {{date_of_joining}} "
		"at {{principal_employer}} (PF Code: {{company_pf_code}}, UAN: {{uan}})."
	)
	_add_signatory(doc)
	doc.save(out_path)


def _build_police_verification(out_path: Path) -> None:
	doc = Document()
	_add_letterhead(doc)
	t = doc.add_paragraph()
	t.alignment = WD_ALIGN_PARAGRAPH.CENTER
	t.add_run("POLICE VERIFICATION LETTER & EMPLOYER DECLARATION").bold = True

	doc.add_paragraph(
		"To,\nThe Officer In-Charge,\n{{police_station}}\n\n"
		"Subject: Request for Character & Antecedent Verification — {{employee_name}} ({{employee_code}})"
	)
	rows = [
		("Full Name", "{{employee_name}}"),
		("Father's / Husband's Name", "{{father_or_husband_name}}"),
		("Date of Birth & Gender", "{{dob}} ({{gender}})"),
		("Present Address", "{{present_address}}"),
		("Permanent Address", "{{permanent_address}}"),
		("Mobile Number", "{{mobile}}"),
		("Aadhaar (Masked)", "{{aadhaar_masked}}"),
		("ID Proof", "{{id_proof_type}} {{id_proof_masked}}"),
		("Designation / Principal Employer", "{{designation}} at {{principal_employer}}"),
		("Date of Joining", "{{date_of_joining}}"),
	]
	tbl = doc.add_table(rows=len(rows), cols=2)
	tbl.style = "Table Grid"
	for i, (k, v) in enumerate(rows):
		tbl.rows[i].cells[0].text = k
		tbl.rows[i].cells[1].text = v

	doc.add_paragraph(
		"\nEMPLOYER DECLARATION\n"
		"We, {{company_name}}, hereby declare that Mr./Ms. {{employee_name}} (Employee Code: {{employee_code}}) "
		"is employed with us and deployed at {{principal_employer}}. To the best of our knowledge and based on records "
		"submitted by the employee, he/she has no past criminal record or pending criminal proceedings. "
		"Kindly issue the police verification clearance for our compliance records."
	)
	_add_signatory(doc)
	doc.save(out_path)


def _build_increment_letter(out_path: Path) -> None:
	doc = Document()
	_add_letterhead(doc)
	doc.add_paragraph("\nપ્રતિ,\nશ્રી/શ્રીમતી {{employee_name}} ({{employee_code}})\nહોદ્દો: {{designation}} | સાઇટ: {{principal_employer}}")
	subj = doc.add_paragraph()
	subj.add_run("વિષય :- પગાર વધારો (Minimum Wage / Salary Revision)").bold = True
	doc.add_paragraph("શ્રીમાન,")
	doc.add_paragraph(
		"આથી તમોને જણાવતા આનંદ થાય છે કે વેતન સંહિતા ૨૦૧૯ હેઠળ તા. {{effective_from}} થી "
		"તમારા પગારમાં ₹{{vda_increase}} નો વધારો કરવામાં આવેલ છે. "
		"તે મુજબ તમારો જૂનો પગાર ₹{{old_wage}} થી વધીને નવો માસિક પગાર ₹{{new_wage}} રહેશે."
	)
	doc.add_paragraph(
		"Wage Revision Summary:\n"
		"• Effective Date: {{effective_from}}\n"
		"• Old Monthly Wage: ₹{{old_wage}}\n"
		"• New Monthly Wage: ₹{{new_wage}}\n"
		"• Net Increment: ₹{{vda_increase}}"
	)
	doc.add_paragraph("આભાર સહ,")
	_add_signatory(doc, "કેસરી મેનપાવર સોલ્યુસન્સ વતી,")
	doc.save(out_path)


def _build_service_certificate(out_path: Path) -> None:
	doc = Document()
	_add_letterhead(doc)
	t = doc.add_paragraph()
	t.alignment = WD_ALIGN_PARAGRAPH.CENTER
	r = t.add_run("SERVICE / EXPERIENCE CERTIFICATE")
	r.bold = True
	r.underline = True
	r.font.size = Pt(14)

	doc.add_paragraph("\nTO WHOMSOEVER IT MAY CONCERN\n")
	doc.add_paragraph(
		"This is to certify that Mr./Ms. {{employee_name}} (Employee Code: {{employee_code}}) was employed with "
		"{{company_name}} and deployed at {{principal_employer}} ({{work_location}}) as {{designation}} in the "
		"{{department}} department from {{date_of_joining}} to {{last_working_day}} (Total Tenure: {{tenure}})."
	)
	details = [
		("Employee Name", "{{employee_name}}"),
		("Employee Code", "{{employee_code}}"),
		("Designation", "{{designation}}"),
		("Department / Client Site", "{{department}} / {{principal_employer}}"),
		("Date of Joining", "{{date_of_joining}}"),
		("Date of Exit / Last Working Day", "{{date_of_exit}} / {{last_working_day}}"),
		("Total Service Tenure", "{{tenure}}"),
		("Reason for Separation", "{{exit_reason}}"),
		("Conduct & Performance", "{{conduct}}"),
	]
	tbl = doc.add_table(rows=len(details), cols=2)
	tbl.style = "Table Grid"
	for i, (k, v) in enumerate(details):
		tbl.rows[i].cells[0].text = k
		tbl.rows[i].cells[1].text = v

	doc.add_paragraph("\nDuring this tenure, his/her conduct was {{conduct}}. All Full & Final settlement dues have been settled.\nWe wish him/her all the best in future endeavors.")
	_add_signatory(doc)
	doc.save(out_path)


def ensure_starter_docx_templates(force: bool = False) -> dict[str, str]:
	TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
	builders = {
		"OFFER_LETTER": ("offer_letter_kesari.docx", _build_offer_letter),
		"APPOINTMENT_LETTER": ("appointment_letter_kesari.docx", _build_appointment_letter),
		"GRATUITY_FORM_F": ("gratuity_form_iv_kesari.docx", _build_gratuity_form_iv),
		"EPFO_FORM_2": ("epfo_form_11_kesari.docx", _build_epfo_form_11),
		"POLICE_VERIFICATION": ("police_verification_kesari.docx", _build_police_verification),
		"INCREMENT_LETTER": ("increment_letter_kesari.docx", _build_increment_letter),
		"SERVICE_CERTIFICATE": ("service_certificate_kesari.docx", _build_service_certificate),
	}
	paths: dict[str, str] = {}
	for doc_type, (filename, fn) in builders.items():
		p = TEMPLATES_DIR / filename
		if force or not p.exists():
			fn(p)
		paths[doc_type] = str(p)
	return paths
