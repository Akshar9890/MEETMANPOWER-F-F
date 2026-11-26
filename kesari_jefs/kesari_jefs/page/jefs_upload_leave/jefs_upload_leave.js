frappe.pages["jefs-upload-leave"].on_page_load = (wrapper) => {
	if (window.KesariDesk) {
		window.KesariDesk.mount(wrapper, "Upload \u2014 Leave Report", "upload", "LEAVE");
	}
};

frappe.pages["jefs-upload-leave"].refresh = (wrapper) => {
	if (wrapper._jefs_refresh) wrapper._jefs_refresh();
};
