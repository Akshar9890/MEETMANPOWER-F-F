frappe.pages["jefs-documents-register"].on_page_load = (wrapper) => {
	if (window.KesariDesk) {
		window.KesariDesk.mount(wrapper, "Documents Register", "documents-register", "");
	}
};

frappe.pages["jefs-documents-register"].refresh = (wrapper) => {
	if (wrapper._jefs_refresh) wrapper._jefs_refresh();
};
