frappe.pages["jefs-upload-employees"].on_page_load = (wrapper) => {
	if (window.KesariDesk) {
		window.KesariDesk.mount(wrapper, "Upload \u2014 Employees Excel", "upload", "EMPLOYEE");
	}
};

frappe.pages["jefs-upload-employees"].refresh = (wrapper) => {
	if (wrapper._jefs_refresh) wrapper._jefs_refresh();
};
