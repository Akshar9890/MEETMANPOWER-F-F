frappe.pages["jefs-reports"].on_page_load = (wrapper) => {
	if (window.KesariDesk) {
		window.KesariDesk.mount(wrapper, "JEFS Reports", "reports", "");
	}
};

frappe.pages["jefs-reports"].refresh = (wrapper) => {
	if (wrapper._jefs_refresh) wrapper._jefs_refresh();
};
