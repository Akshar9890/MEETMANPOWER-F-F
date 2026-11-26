frappe.pages["jefs-wage-revision"].on_page_load = (wrapper) => {
	if (window.KesariDesk) {
		window.KesariDesk.mount(wrapper, "Minimum Wages & Increment Letters", "wage-revision", "");
	}
};

frappe.pages["jefs-wage-revision"].refresh = (wrapper) => {
	if (wrapper._jefs_refresh) wrapper._jefs_refresh();
};
