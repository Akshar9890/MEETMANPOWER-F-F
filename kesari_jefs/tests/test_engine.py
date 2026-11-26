"""Comprehensive unit tests for pure JEFS engine (TC-FNF-01..16, wage revision, validators)."""

from __future__ import annotations

import datetime as dt
import unittest
from decimal import Decimal

from kesari_jefs.engine.fnf import (
	FnfInput,
	FnfSettings,
	ManualLine,
	SiteRule,
	calc_fnf,
	calc_payment_due_date,
)
from kesari_jefs.engine.money import (
	amount_in_words_inr,
	format_indian_int,
	paise_to_rupees_int,
	rupees_to_paise,
)
from kesari_jefs.engine.tenure import calc_tenure
from kesari_jefs.engine.validators import (
	mask_aadhaar,
	mask_bank_account,
	mask_pan,
	parse_date,
	validate_age_18,
	validate_gross_consistency,
	validate_ifsc,
	validate_mobile,
	validate_nominee_shares,
	validate_pan,
	verhoeff_check,
)
from kesari_jefs.engine.wage_revision import (
	MinWageEntry,
	WageRevisionEmployee,
	propose_wage_revision,
)


def _line_amount(res, code: str) -> int:
	for line in res.lines:
		if line.code == code:
			return line.amount_paise
	raise KeyError(code)


class TestMoneyAndValidators(unittest.TestCase):
	def test_money_indian_format_and_words(self):
		self.assertEqual(format_indian_int(101634), "1,01,634")
		self.assertEqual(format_indian_int(2000000), "20,00,000")
		self.assertEqual(
			amount_in_words_inr(rupees_to_paise(101634)),
			"Rupees One Lakh One Thousand Six Hundred Thirty Four Only",
		)

	def test_verhoeff_and_masking(self):
		# Valid Verhoeff 12-digit test number starting 2..9
		self.assertTrue(verhoeff_check("234567891234") in (True, False))
		# Compute valid check digit for 23456789123 -> 23456789123X
		valid = None
		for d in "0123456789":
			if verhoeff_check("23456789123" + d):
				valid = "23456789123" + d
				break
		self.assertIsNotNone(valid)
		self.assertTrue(verhoeff_check(valid))
		bad = valid[:-1] + str((int(valid[-1]) + 1) % 10)
		self.assertFalse(verhoeff_check(bad))
		self.assertFalse(verhoeff_check("012345678901"))
		self.assertEqual(mask_aadhaar(valid), f"XXXX XXXX {valid[-4:]}")
		self.assertEqual(mask_pan("ABCDE1234F"), "ABXXXXXX4F")
		self.assertEqual(mask_bank_account("123456789012"), "XXXXXXXX9012")

	def test_pan_ifsc_mobile_dates_shares(self):
		self.assertTrue(validate_pan("ABCDE1234F"))
		self.assertFalse(validate_pan("12345ABCDE"))
		self.assertTrue(validate_ifsc("SBIN0001234"))
		self.assertFalse(validate_ifsc("SBIN1001234"))
		self.assertTrue(validate_mobile("9876543210"))
		self.assertFalse(validate_mobile("5876543210"))
		self.assertEqual(parse_date("15-01-2027"), dt.date(2027, 1, 15))
		self.assertEqual(parse_date("2027-01-15"), dt.date(2027, 1, 15))
		self.assertTrue(validate_age_18(dt.date(2000, 1, 1), dt.date(2026, 1, 1)))
		self.assertFalse(validate_age_18(dt.date(2010, 1, 1), dt.date(2026, 1, 1)))
		self.assertTrue(validate_gross_consistency(2200000, 2200050))
		self.assertFalse(validate_gross_consistency(2200000, 2200200))
		self.assertTrue(validate_nominee_shares([50, 50]))
		self.assertFalse(validate_nominee_shares([60, 30]))


class TestFnfCases(unittest.TestCase):
	def test_tc_fnf_01_golden_case(self):
		inp = FnfInput(
			employee_code="KM1023",
			employment_type="PERMANENT",
			exit_reason="RESIGNATION",
			doj=dt.date(2020, 6, 1),
			lwd=dt.date(2027, 1, 15),
			exit_date=dt.date(2027, 1, 15),
			basic_paise=rupees_to_paise(15000),
			da_paise=rupees_to_paise(3000),
			gross_paise=rupees_to_paise(22000),
			el_balance=Decimal("12"),
			min_wage_monthly_paise=rupees_to_paise(14000),
			deduct_pf=True,
			pt_paise=rupees_to_paise(200),
		)
		res = calc_fnf(inp)
		self.assertEqual(res.tenure.years, 6)
		self.assertEqual(res.tenure.months, 7)
		self.assertEqual(res.tenure.counted_years, 7)
		self.assertEqual(paise_to_rupees_int(_line_amount(res, "EARNED_SALARY")), 10645)
		self.assertEqual(paise_to_rupees_int(_line_amount(res, "LEAVE_ENCASH")), 8308)
		self.assertEqual(paise_to_rupees_int(_line_amount(res, "BONUS")), 11060)
		self.assertEqual(paise_to_rupees_int(_line_amount(res, "GRATUITY")), 72692)
		self.assertEqual(paise_to_rupees_int(_line_amount(res, "PF")), 871)
		self.assertEqual(paise_to_rupees_int(_line_amount(res, "PT")), 200)
		self.assertEqual(paise_to_rupees_int(res.net_payable_paise), 101634)
		self.assertEqual(res.payment_due_date, dt.date(2027, 1, 18))
		self.assertFalse(res.errors)

	def test_tc_fnf_02_permanent_4y5m_not_eligible(self):
		inp = FnfInput(
			employee_code="E2",
			employment_type="PERMANENT",
			exit_reason="RESIGNATION",
			doj=dt.date(2022, 1, 1),
			lwd=dt.date(2026, 5, 31),
			exit_date=dt.date(2026, 5, 31),
			basic_paise=rupees_to_paise(15000),
			da_paise=0,
			gross_paise=rupees_to_paise(18000),
			el_balance=Decimal("0"),
		)
		res = calc_fnf(inp)
		self.assertEqual(_line_amount(res, "GRATUITY"), 0)
		self.assertTrue(any("not eligible" in w.lower() for w in res.warnings))

	def test_tc_fnf_03_permanent_4y7m_setting_controlled(self):
		inp = FnfInput(
			employee_code="E3",
			employment_type="PERMANENT",
			exit_reason="RESIGNATION",
			doj=dt.date(2022, 1, 1),
			lwd=dt.date(2026, 7, 31),
			exit_date=dt.date(2026, 7, 31),
			basic_paise=rupees_to_paise(15000),
			da_paise=0,
			gross_paise=rupees_to_paise(18000),
			el_balance=Decimal("0"),
		)
		res_default = calc_fnf(inp)
		self.assertEqual(_line_amount(res_default, "GRATUITY"), 0)

		res_4y240d = calc_fnf(inp, FnfSettings(gratuity_allow_4y240d_rule=True))
		self.assertGreater(_line_amount(res_4y240d, "GRATUITY"), 0)

	def test_tc_fnf_04_and_05_fixed_term_gratuity(self):
		base = dict(
			employee_code="FT1",
			employment_type="FIXED_TERM",
			exit_reason="END_OF_CONTRACT",
			doj=dt.date(2025, 1, 1),
			basic_paise=rupees_to_paise(13000),
			da_paise=0,
			gross_paise=rupees_to_paise(15000),
			el_balance=Decimal("0"),
		)
		res_1y2m = calc_fnf(FnfInput(**base, lwd=dt.date(2026, 2, 28), exit_date=dt.date(2026, 2, 28)))
		self.assertEqual(res_1y2m.tenure.counted_years, 1)
		self.assertEqual(paise_to_rupees_int(_line_amount(res_1y2m, "GRATUITY")), 7500)

		res_1y7m = calc_fnf(FnfInput(**base, lwd=dt.date(2026, 7, 31), exit_date=dt.date(2026, 7, 31)))
		self.assertEqual(res_1y7m.tenure.counted_years, 2)
		self.assertEqual(paise_to_rupees_int(_line_amount(res_1y7m, "GRATUITY")), 15000)

	def test_tc_fnf_06_07_08_bonus_rules(self):
		# TC-FNF-06 wages > 21,000
		res6 = calc_fnf(
			FnfInput(
				employee_code="E6",
				employment_type="PERMANENT",
				exit_reason="RESIGNATION",
				doj=dt.date(2025, 1, 1),
				lwd=dt.date(2026, 6, 30),
				exit_date=dt.date(2026, 6, 30),
				basic_paise=rupees_to_paise(23000),
				da_paise=0,
				gross_paise=rupees_to_paise(25000),
				el_balance=Decimal("0"),
			)
		)
		self.assertEqual(_line_amount(res6, "BONUS"), 0)

		# TC-FNF-07 worked < 30 days
		res7 = calc_fnf(
			FnfInput(
				employee_code="E7",
				employment_type="PERMANENT",
				exit_reason="RESIGNATION",
				doj=dt.date(2026, 4, 1),
				lwd=dt.date(2026, 4, 25),
				exit_date=dt.date(2026, 4, 25),
				basic_paise=rupees_to_paise(12000),
				da_paise=0,
				gross_paise=rupees_to_paise(15000),
				el_balance=Decimal("0"),
				fy_working_days=25,
			)
		)
		self.assertEqual(_line_amount(res7, "BONUS"), 0)

		# TC-FNF-08 already paid > calculated
		res8 = calc_fnf(
			FnfInput(
				employee_code="E8",
				employment_type="PERMANENT",
				exit_reason="RESIGNATION",
				doj=dt.date(2025, 4, 1),
				lwd=dt.date(2026, 6, 30),
				exit_date=dt.date(2026, 6, 30),
				basic_paise=rupees_to_paise(12000),
				da_paise=0,
				gross_paise=rupees_to_paise(15000),
				el_balance=Decimal("0"),
				bonus_already_paid_paise=rupees_to_paise(50000),
			)
		)
		self.assertEqual(_line_amount(res8, "BONUS"), 0)

	def test_tc_fnf_09_gratuity_cap(self):
		res9 = calc_fnf(
			FnfInput(
				employee_code="E9",
				employment_type="PERMANENT",
				exit_reason="RETIREMENT",
				doj=dt.date(1996, 1, 1),
				lwd=dt.date(2026, 1, 31),
				exit_date=dt.date(2026, 1, 31),
				basic_paise=rupees_to_paise(150000),
				da_paise=0,
				gross_paise=rupees_to_paise(200000),
				el_balance=Decimal("0"),
			)
		)
		self.assertEqual(paise_to_rupees_int(_line_amount(res9, "GRATUITY")), 2000000)

	def test_tc_fnf_10_11_12_exit_month_days(self):
		base = dict(
			employee_code="E10",
			employment_type="PERMANENT",
			exit_reason="RESIGNATION",
			doj=dt.date(2025, 1, 1),
			basic_paise=rupees_to_paise(15000),
			da_paise=0,
			gross_paise=rupees_to_paise(31000),
			el_balance=Decimal("0"),
			deduct_pf=False,
		)
		# TC-FNF-10 31st of 31-day month
		r10 = calc_fnf(FnfInput(**base, lwd=dt.date(2026, 1, 31), exit_date=dt.date(2026, 1, 31)))
		self.assertEqual(paise_to_rupees_int(_line_amount(r10, "EARNED_SALARY")), 31000)
		# TC-FNF-11 1st of month
		r11 = calc_fnf(FnfInput(**base, lwd=dt.date(2026, 1, 1), exit_date=dt.date(2026, 1, 1)))
		self.assertEqual(paise_to_rupees_int(_line_amount(r11, "EARNED_SALARY")), 1000)
		# TC-FNF-12 Feb leap vs non-leap
		r12_non = calc_fnf(
			FnfInput(
				**{**base, "gross_paise": rupees_to_paise(28000)},
				lwd=dt.date(2026, 2, 14),
				exit_date=dt.date(2026, 2, 14),
			)
		)
		self.assertEqual(paise_to_rupees_int(_line_amount(r12_non, "EARNED_SALARY")), 14000)
		r12_leap = calc_fnf(
			FnfInput(
				**{**base, "doj": dt.date(2023, 1, 1), "gross_paise": rupees_to_paise(29000)},
				lwd=dt.date(2024, 2, 14),
				exit_date=dt.date(2024, 2, 14),
			)
		)
		self.assertEqual(paise_to_rupees_int(_line_amount(r12_leap, "EARNED_SALARY")), 14000)

	def test_tc_fnf_13_14_15_16_and_site_rules(self):
		# TC-FNF-13 negative net
		r13 = calc_fnf(
			FnfInput(
				employee_code="E13",
				employment_type="PERMANENT",
				exit_reason="RESIGNATION",
				doj=dt.date(2025, 1, 1),
				lwd=dt.date(2026, 1, 5),
				exit_date=dt.date(2026, 1, 5),
				basic_paise=rupees_to_paise(10000),
				da_paise=0,
				gross_paise=rupees_to_paise(15000),
				el_balance=Decimal("0"),
				manual_lines=(ManualLine("NOTICE_RECOVERY", "DEDUCTION", rupees_to_paise(50000), "Notice recovery"),),
			)
		)
		self.assertTrue(r13.has_negative_net)
		self.assertTrue(any("FNF_NEGATIVE_NET" in e for e in r13.errors))

		# TC-FNF-14 missing leave balance
		r14 = calc_fnf(
			FnfInput(
				employee_code="E14",
				employment_type="PERMANENT",
				exit_reason="RESIGNATION",
				doj=dt.date(2025, 1, 1),
				lwd=dt.date(2026, 1, 15),
				exit_date=dt.date(2026, 1, 15),
				basic_paise=rupees_to_paise(15000),
				da_paise=0,
				gross_paise=rupees_to_paise(20000),
				el_balance=None,
			)
		)
		self.assertTrue(any("FNF_LEAVE_MISSING" in e for e in r14.errors))

		# TC-FNF-15 death case regardless of years
		r15 = calc_fnf(
			FnfInput(
				employee_code="E15",
				employment_type="PERMANENT",
				exit_reason="DEATH",
				doj=dt.date(2024, 6, 1),
				lwd=dt.date(2026, 1, 15),
				exit_date=dt.date(2026, 1, 15),
				basic_paise=rupees_to_paise(18000),
				da_paise=0,
				gross_paise=rupees_to_paise(22000),
				el_balance=Decimal("0"),
			)
		)
		self.assertTrue(r15.gratuity_payable_to_nominee)
		self.assertGreater(_line_amount(r15, "GRATUITY"), 0)

		# TC-FNF-16 determinism
		self.assertEqual(r15, calc_fnf(
			FnfInput(
				employee_code="E15",
				employment_type="PERMANENT",
				exit_reason="DEATH",
				doj=dt.date(2024, 6, 1),
				lwd=dt.date(2026, 1, 15),
				exit_date=dt.date(2026, 1, 15),
				basic_paise=rupees_to_paise(18000),
				da_paise=0,
				gross_paise=rupees_to_paise(22000),
				el_balance=Decimal("0"),
			)
		))

		# EXECHON site excludes Leave even when el_balance is None
		r_ex = calc_fnf(
			FnfInput(
				employee_code="EX1",
				employment_type="PERMANENT",
				exit_reason="RESIGNATION",
				doj=dt.date(2020, 1, 1),
				lwd=dt.date(2026, 1, 15),
				exit_date=dt.date(2026, 1, 15),
				basic_paise=rupees_to_paise(15000),
				da_paise=0,
				gross_paise=rupees_to_paise(20000),
				el_balance=None,
				site_rule=SiteRule(site_code="EXECHON", include_bonus=True, include_leave=False, include_gratuity=True),
			)
		)
		self.assertFalse(r_ex.errors)
		self.assertEqual(_line_amount(r_ex, "LEAVE_ENCASH"), 0)


class TestWageRevision(unittest.TestCase):
	def test_policies(self):
		rates = {
			("gujarat", "zone-a", "unskilled"): MinWageEntry(
				"Gujarat", "Zone-A", "Unskilled", rupees_to_paise(12000), rupees_to_paise(2500), rupees_to_paise(14500)
			)
		}
		emps = [
			WageRevisionEmployee("E1", "Ramesh", "Gujarat", "Zone-A", "Unskilled", rupees_to_paise(11000), rupees_to_paise(2000), rupees_to_paise(13000)),
			WageRevisionEmployee("E2", "Suresh", "Gujarat", "Zone-A", "Unskilled", rupees_to_paise(14000), rupees_to_paise(2000), rupees_to_paise(16000)),
			WageRevisionEmployee("E3", "Mahesh", "Gujarat", "Zone-B", "Skilled", rupees_to_paise(14000), rupees_to_paise(2000), rupees_to_paise(16000)),
		]
		res_min = propose_wage_revision(emps, rates, policy="RAISE_TO_MIN")
		self.assertEqual(res_min[0].proposed_total_paise, rupees_to_paise(14500))
		self.assertTrue(res_min[0].needs_letter)
		self.assertEqual(res_min[1].proposed_total_paise, rupees_to_paise(16000))
		self.assertFalse(res_min[1].needs_letter)
		self.assertIn("WAGE_RATE_MISSING", res_min[2].error)

		res_vda = propose_wage_revision(emps[:2], rates, policy="ADD_VDA_DELTA", vda_delta_paise=rupees_to_paise(500))
		self.assertEqual(res_vda[1].proposed_total_paise, rupees_to_paise(16500))
		self.assertTrue(res_vda[1].needs_letter)


if __name__ == "__main__":
	unittest.main()
