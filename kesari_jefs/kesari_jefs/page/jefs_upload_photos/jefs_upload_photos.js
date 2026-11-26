frappe.pages["jefs-upload-photos"].on_page_load = (wrapper) => {
	if (window.KesariDesk) {
		window.KesariDesk.mount(wrapper, "Upload \u2014 Employee Photos ZIP", "upload", "PHOTOS");
	}
};

frappe.pages["jefs-upload-photos"].refresh = (wrapper) => {
	if (wrapper._jefs_refresh) wrapper._jefs_refresh();
};
