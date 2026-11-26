frappe.pages["jefs-employees"].on_page_load = (wrapper) => {
	if (window.KesariDesk) {
		window.KesariDesk.mount(wrapper, "JEFS Employees (Masked PII)", "employees", "");
	}
};

frappe.pages["jefs-employees"].refresh = (wrapper) => {
	if (wrapper._jefs_refresh) wrapper._jefs_refresh();
};
