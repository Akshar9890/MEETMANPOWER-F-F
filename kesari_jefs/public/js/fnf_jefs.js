frappe.ui.form.on('Full and Final Statement', {
	refresh(frm) {
		if (!frm.doc.employee) return;
		if (frm.doc.jefs_fnf_settlement) {
			frm.dashboard.set_headline_alert(
				`Linked to Kesari JEFS: <b>${frappe.utils.escape_html(frm.doc.jefs_fnf_settlement)}</b> · Status: <b>${frappe.utils.escape_html(frm.doc.jefs_status || '-')}</b> · Tenure: <b>${frappe.utils.escape_html(frm.doc.jefs_tenure || '-')}</b>`,
				frm.doc.jefs_status === 'APPROVED' ? 'green' : 'blue'
			);
		}
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__('Calculate / Sync from Kesari JEFS'), () => {
				frappe.call({
					method: 'kesari_jefs.api.sync_hrms_fnf_with_jefs',
					args: { employee: frm.doc.employee, fnf_name: frm.doc.name },
					freeze: true,
					freeze_message: __('Calculating F&F using Kesari JEFS statutory engine...'),
					callback(r) {
						if (r.message) {
							frappe.show_alert({ message: __('Synced with Kesari JEFS Engine'), indicator: 'green' });
							frm.reload_doc();
						}
					},
				});
			}, __('Kesari JEFS'));
		}
		frm.add_custom_button(__('Open Kesari F&F Workflow'), () => {
			frappe.set_route('jefs-fnf');
		}, __('Kesari JEFS'));
		frm.add_custom_button(__('Service Certificates'), () => {
			frappe.set_route('jefs-service-certificates');
		}, __('Kesari JEFS'));
		frm.add_custom_button(__('Documents Register'), () => {
			frappe.set_route('jefs-documents-register');
		}, __('Kesari JEFS'));
	},
});

frappe.ui.form.on('Employee Separation', {
	refresh(frm) {
		if (!frm.doc.employee) return;
		if (frm.doc.jefs_fnf_settlement) {
			frm.dashboard.set_headline_alert(
				`Linked JEFS F&F: <b>${frappe.utils.escape_html(frm.doc.jefs_fnf_settlement)}</b>`,
				'blue'
			);
		}
		frm.add_custom_button(__('Calculate F&F in Kesari JEFS'), () => {
			frappe.call({
				method: 'kesari_jefs.api.sync_hrms_fnf_with_jefs',
				args: { employee: frm.doc.employee },
				freeze: true,
				callback(r) {
					if (r.message) {
						frappe.show_alert({ message: __('JEFS F&F synced'), indicator: 'green' });
						frm.reload_doc();
					}
				},
			});
		}, __('Kesari JEFS'));
		frm.add_custom_button(__('Open Exits & F&F'), () => {
			frappe.set_route('jefs-fnf');
		}, __('Kesari JEFS'));
		frm.add_custom_button(__('Service Certificates'), () => {
			frappe.set_route('jefs-service-certificates');
		}, __('Kesari JEFS'));
	},
});
