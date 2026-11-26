"""AES-256-GCM field encryption helper for Aadhaar, PAN, Bank Account, ID proof."""

from __future__ import annotations

import base64
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "v1:"


def _get_or_create_key() -> bytes:
	env_key = os.environ.get("FIELD_ENCRYPTION_KEY", "").strip()
	if env_key:
		raw = base64.b64decode(env_key)
		if len(raw) == 32:
			return raw

	try:
		import frappe
		conf_key = frappe.conf.get("jefs_encryption_key")
		if conf_key:
			raw = base64.b64decode(conf_key)
			if len(raw) == 32:
				return raw
		# Generate and persist key in site_config.json (never in Git)
		new_key = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
		from frappe.installer import update_site_config
		update_site_config("jefs_encryption_key", new_key)
		frappe.conf.jefs_encryption_key = new_key
		return base64.b64decode(new_key)
	except Exception:
		# Deterministic fallback only if running outside Frappe tests without env var
		fallback = base64.b64encode(b"kesari-jefs-dev-only-32-byte-key").decode("ascii")
		return base64.b64decode(fallback)


def encrypt_field(plaintext: str | None) -> str:
	if not plaintext:
		return ""
	s = str(plaintext).strip()
	if not s:
		return ""
	if s.startswith(_PREFIX):
		return s
	key = _get_or_create_key()
	nonce = secrets.token_bytes(12)
	ct = AESGCM(key).encrypt(nonce, s.encode("utf-8"), None)
	return _PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def decrypt_field(token: str | None) -> str:
	if not token:
		return ""
	s = str(token).strip()
	if not s.startswith(_PREFIX):
		return s
	raw = base64.b64decode(s[len(_PREFIX):])
	nonce, ct = raw[:12], raw[12:]
	key = _get_or_create_key()
	return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")
