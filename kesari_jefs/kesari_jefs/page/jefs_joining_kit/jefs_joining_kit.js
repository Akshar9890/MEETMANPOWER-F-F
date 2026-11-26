frappe.pages["jefs-joining-kit"].on_page_load = (wrapper) => {
	if (window.KesariDesk) {
		window.KesariDesk.mount(wrapper, "Joining Kit & Police Verification", "joining-kit", "");
	}
};

frappe.pages["jefs-joining-kit"].refresh = (wrapper) => {
	if (wrapper._jefs_refresh) wrapper._jefs_refresh();
};
