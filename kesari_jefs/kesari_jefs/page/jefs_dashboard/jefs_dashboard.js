frappe.pages["jefs-dashboard"].on_page_load = (wrapper) => {
	if (window.KesariDesk) {
		window.KesariDesk.mount(wrapper, "Kesari JEFS Dashboard", "dashboard", "");
	}
};

frappe.pages["jefs-dashboard"].refresh = (wrapper) => {
	if (wrapper._jefs_refresh) wrapper._jefs_refresh();
};
