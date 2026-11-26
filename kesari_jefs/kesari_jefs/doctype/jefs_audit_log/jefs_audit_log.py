import frappe
from frappe.model.document import Document


class JEFSAuditLog(Document):
	def before_save(self):
		if not self.is_new():
			frappe.throw("JEFS Audit Log is append-only and cannot be modified.")

	def on_trash(self):
		frappe.throw("JEFS Audit Log is append-only and cannot be deleted.")
