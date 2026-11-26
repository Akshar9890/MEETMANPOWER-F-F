frappe.pages["jefs-fnf"].on_page_load = (wrapper) => {
	if (window.KesariDesk) {
		window.KesariDesk.mount(wrapper, "Exits & Full and Final Settlement", "fnf", "");
	}
};

frappe.pages["jefs-fnf"].refresh = (wrapper) => {
	if (wrapper._jefs_refresh) wrapper._jefs_refresh();
};
