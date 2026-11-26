frappe.pages["jefs-settings"].on_page_load = (wrapper) => {
	if (window.KesariDesk) {
		window.KesariDesk.mount(wrapper, "JEFS Settings & Audit", "settings", "");
	}
};

frappe.pages["jefs-settings"].refresh = (wrapper) => {
	if (wrapper._jefs_refresh) wrapper._jefs_refresh();
};
