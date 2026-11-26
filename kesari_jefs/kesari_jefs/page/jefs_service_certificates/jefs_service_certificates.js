frappe.pages["jefs-service-certificates"].on_page_load = (wrapper) => {
	if (window.KesariDesk) {
		window.KesariDesk.mount(wrapper, "Service Certificates", "service-certificates", "");
	}
};

frappe.pages["jefs-service-certificates"].refresh = (wrapper) => {
	if (wrapper._jefs_refresh) wrapper._jefs_refresh();
};
