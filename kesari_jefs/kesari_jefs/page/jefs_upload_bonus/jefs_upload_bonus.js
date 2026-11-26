frappe.pages["jefs-upload-bonus"].on_page_load = (wrapper) => {
	if (window.KesariDesk) {
		window.KesariDesk.mount(wrapper, "Upload \u2014 Bonus Report", "upload", "BONUS");
	}
};

frappe.pages["jefs-upload-bonus"].refresh = (wrapper) => {
	if (wrapper._jefs_refresh) wrapper._jefs_refresh();
};
