frappe.ui.form.on('Employee', {
	refresh(frm) {
		if (frm.is_new()) return;
		frappe.call({
			method: 'kesari_jefs.api.get_employee_jefs_summary',
			args: { frappe_employee: frm.doc.name },
			callback(r) {
				const s = r.message;
				if (!s || !s.linked) return;
				const badge = s.kit_ready ? 'green' : 'orange';
				frm.dashboard.set_headline_alert(
					`<b>Kesari JEFS (${frappe.utils.escape_html(s.employee_code)})</b> · Site: ${frappe.utils.escape_html(s.client_site || '-')} · Kit: <b>${s.ready_count}/6</b> · Aadhaar: <code>${frappe.utils.escape_html(s.aadhaar_masked || '-')}</code> · Docs: <b>${s.docs_count}</b>${s.fnf_name ? ` · F&amp;F: <b>${frappe.utils.escape_html(s.fnf_name)}</b> (${frappe.utils.escape_html(s.fnf_status)}) ₹${Number(s.fnf_net_rupees || 0).toLocaleString('en-IN')}` : ''}`,
					badge
				);
			},
		});

		frm.add_custom_button(__('Sync ↔ JEFS Profile'), () => {
			frappe.call({
				method: 'kesari_jefs.api.sync_all_with_hrms',
				freeze: true,
				callback() {
					frappe.show_alert({ message: __('Employee synced with Kesari JEFS'), indicator: 'green' });
					frm.reload_doc();
				},
			});
		}, __('Kesari JEFS'));
		frm.add_custom_button(__('Joining Kit & Police'), () => {
			frappe.set_route('jefs-joining-kit');
		}, __('Kesari JEFS'));
		frm.add_custom_button(__('Exits & F&F'), () => {
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
