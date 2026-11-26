app_name = "kesari_jefs"
app_title = "F&F"
app_publisher = "Kesari Manpower / Meet Sir"
app_description = "Employee Joining & Exit Formality Software (F&F)"
app_email = "kesarimanpower@gmail.com"
app_license = "MIT"
required_apps = ["frappe/hrms"]
app_logo_url = "/assets/kesari_jefs/images/ff-logo.svg"
app_home = "/desk/kesari-jefs/jefs-dashboard"

app_include_js = ["/assets/kesari_jefs/js/jefs_desk.js"]
app_include_css = ["/assets/kesari_jefs/css/jefs_desk.css"]
doctype_js = {
	"Employee": "public/js/employee_jefs.js",
	"Full and Final Statement": "public/js/fnf_jefs.js",
	"Employee Separation": "public/js/fnf_jefs.js",
}

doc_events = {
	"Employee": {
		"after_insert": "kesari_jefs.services.hrms_bridge.on_hr_employee_update",
		"on_update": "kesari_jefs.services.hrms_bridge.on_hr_employee_update",
	},
	"Employee Separation": {
		"on_update": "kesari_jefs.services.hrms_bridge.on_hr_separation_event",
		"on_submit": "kesari_jefs.services.hrms_bridge.on_hr_separation_event",
	},
	"Job Offer": {
		"on_submit": "kesari_jefs.services.hrms_bridge.on_hr_offer_event",
	},
	"Appointment Letter": {
		"after_insert": "kesari_jefs.services.hrms_bridge.on_hr_offer_event",
		"on_update": "kesari_jefs.services.hrms_bridge.on_hr_offer_event",
	},
	"JEFS Employee": {
		"after_insert": "kesari_jefs.services.hrms_bridge.on_jefs_employee_event",
		"on_update": "kesari_jefs.services.hrms_bridge.on_jefs_employee_event",
	},
	"JEFS FnF Settlement": {
		"after_insert": "kesari_jefs.services.hrms_bridge.on_jefs_fnf_event",
		"on_update": "kesari_jefs.services.hrms_bridge.on_jefs_fnf_event",
	},
}

extend_bootinfo = "kesari_jefs.services.jefs_core.extend_bootinfo"

override_whitelisted_methods = {
	"frappe.apps.get_apps": "kesari_jefs.api.get_ff_apps",
}

after_install = "kesari_jefs.install.after_install"
after_migrate = "kesari_jefs.install.after_migrate"
