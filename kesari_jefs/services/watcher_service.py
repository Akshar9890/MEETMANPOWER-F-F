"""Optional minimum-wage notification watcher (06_SCRAPING_SPEC.md).

Never modifies wages automatically; saves snapshots and alerts Payroll Specialist.
"""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

import frappe
import requests
from frappe.utils import now_datetime


class _LinkExtractor(HTMLParser):
	def __init__(self, base_url: str):
		super().__init__()
		self.base_url = base_url
		self.links: list[dict[str, str]] = []
		self._cur_href: str | None = None
		self._cur_text: list[str] = []

	def handle_starttag(self, tag, attrs):
		if tag.lower() == "a":
			href = dict(attrs).get("href")
			if href:
				self._cur_href = urljoin(self.base_url, href)
				self._cur_text = []

	def handle_data(self, data):
		if self._cur_href is not None:
			self._cur_text.append(data)

	def handle_endtag(self, tag):
		if tag.lower() == "a" and self._cur_href is not None:
			text = re.sub(r"\s+", " ", "".join(self._cur_text)).strip()
			self.links.append({"title": text or self._cur_href, "url": self._cur_href})
			self._cur_href = None
			self._cur_text = []


def check_watcher_source(source_name: str) -> dict:
	doc = frappe.get_doc("JEFS Wage Watcher Source", source_name)
	keywords = [k.strip().lower() for k in (doc.keywords or "").split(",") if k.strip()]
	try:
		resp = requests.get(
			doc.url,
			headers={"User-Agent": "KesariManpowerJEFS-WageWatcher/1.0"},
			timeout=15,
		)
		resp.raise_for_status()
		parser = _LinkExtractor(doc.url)
		parser.feed(resp.text)
		matched = [
			item
			for item in parser.links
			if item["url"].lower().endswith(".pdf")
			and (not keywords or any(k in item["title"].lower() or k in item["url"].lower() for k in keywords))
		]
		payload = json.dumps(matched, sort_keys=True)
		new_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
		changed = bool(doc.last_hash and doc.last_hash != new_hash)
		status = "NEW_NOTIFICATION" if changed else ("LAYOUT_WARNING_0_LINKS" if not matched else "NO_CHANGE")
		doc.last_hash = new_hash
		doc.last_checked_at = now_datetime()
		doc.last_status = status
		doc.latest_items_json = payload
		doc.save(ignore_permissions=True)
		return {"source_id": doc.source_id, "status": status, "count": len(matched), "changed": changed}
	except Exception as exc:
		doc.last_checked_at = now_datetime()
		doc.last_status = f"ERROR: {str(exc)[:100]}"
		doc.save(ignore_permissions=True)
		return {"source_id": doc.source_id, "status": "ERROR", "error": str(exc)}
