import frappe
from frappe.model.document import Document


class JEFSFnFSettlement(Document):
	def before_save(self):
		if not self.is_new():
			prev_status = frappe.db.get_value("JEFS FnF Settlement", self.name, "status")
			if prev_status == "APPROVED" and self.status != "REVISED":
				frappe.throw("FNF_LOCKED: Approved F&F settlement is immutable. Create a revision instead.")
