frappe.pages["jefs-upload-salary"].on_page_load = (wrapper) => {
	if (window.KesariDesk) {
		window.KesariDesk.mount(wrapper, "Upload \u2014 Salary Excel", "upload", "SALARY");
	}
};

frappe.pages["jefs-upload-salary"].refresh = (wrapper) => {
	if (wrapper._jefs_refresh) wrapper._jefs_refresh();
};
