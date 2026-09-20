"""Regression tests for the type-aware data cleaner."""

import csv
import io
import unittest
from pathlib import Path

from tools.data_cleaner import (
    _clean_phone,
    _parse_date,
    _smart_title,
    _to_number,
    clean_with_report,
    dataframe_to_bytes,
    generate_cleaning_script,
    parse_upload,
    profile_dataframe,
)

FIXTURE = Path(__file__).parent / "fixtures" / "dirty_data_test.csv"


def _clean(text: str, name: str = "t.csv", **kwargs):
    df = parse_upload(text.encode("utf-8"), name)
    return clean_with_report(df, **kwargs)


def _rows(df):
    out, _ = dataframe_to_bytes(df, "t.csv")
    return list(csv.DictReader(io.StringIO(out.decode("utf-8"))))


class HelperTests(unittest.TestCase):
    def test_phone_normalisation(self):
        self.assertEqual(_clean_phone("082 678 9012"), "+27826789012")
        self.assertEqual(_clean_phone("+27 82 345 6789"), "+27823456789")
        self.assertEqual(_clean_phone("27823456789"), "+27823456789")
        self.assertEqual(_clean_phone("073-456-7890"), "+27734567890")
        self.assertEqual(_clean_phone("+44 20 7946 0958"), "+442079460958")
        self.assertIsNone(_clean_phone("0000000000"))
        self.assertIsNone(_clean_phone("12345"))

    def test_date_parsing(self):
        self.assertEqual(_parse_date("15/01/2024", True).date().isoformat(), "2024-01-15")
        self.assertEqual(_parse_date("April 11 2024", True).date().isoformat(), "2024-04-11")
        self.assertEqual(_parse_date("01/15/2024", False).date().isoformat(), "2024-01-15")
        self.assertIsNone(_parse_date("07/2024/04", True))
        self.assertIsNone(_parse_date("31/02/2024", True))

    def test_numbers(self):
        self.assertEqual(_to_number("R1,234.50")[0], 1234.5)
        self.assertEqual(_to_number("450.00"), (450.0, True))
        self.assertIsNone(_to_number("abc"))

    def test_names_keep_particles(self):
        self.assertEqual(_smart_title("kobus van der merwe"), "Kobus van der Merwe")
        self.assertEqual(_smart_title("o'brien"), "O'Brien")


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = parse_upload(FIXTURE.read_bytes(), "dirty_data_test.csv")
        cls.cleaned, cls.report = clean_with_report(cls.raw)
        cls.rows = {r["id"]: r for r in _rows(cls.cleaned)}

    def test_duplicates_ignore_ids_and_formatting(self):
        removed = {r["row"] for r in self.report["removed_rows"]}
        self.assertEqual(removed, {12, 18, 27, 34})
        self.assertEqual(self.report["rows_after"], 36)

    def test_dates_are_iso(self):
        self.assertEqual(self.rows["2"]["signup_date"], "2024-01-15")
        self.assertEqual(self.rows["9"]["signup_date"], "2024-04-11")
        self.assertEqual(self.rows["5"]["last_login"], "2025-08-07")
        self.assertEqual(self.rows["19"]["signup_date"], "")  # 07/2024/04 is unreadable

    def test_categories_unified(self):
        self.assertEqual(self.rows["5"]["province"], "Gauteng")
        self.assertEqual(self.rows["6"]["province"], "KwaZulu-Natal")
        self.assertEqual(self.rows["29"]["province"], "North West")
        self.assertEqual(self.rows["4"]["gender"], "Female")
        self.assertEqual(self.rows["2"]["gender"], "Male")
        self.assertEqual(self.rows["8"]["gender"], "")

    def test_invalid_values_blanked_not_guessed(self):
        self.assertEqual(self.rows["6"]["email"], "")
        self.assertEqual(self.rows["13"]["email"], "")
        self.assertEqual(self.rows["18"]["age"], "")  # "abc"
        self.assertEqual(self.rows["39"]["age"], "")  # -1
        self.assertEqual(self.rows["14"]["phone"], "")

    def test_names_and_text(self):
        self.assertEqual(self.rows["2"]["first_name"], "Siphiwe")
        self.assertEqual(self.rows["4"]["last_name"], "Mokoena")
        self.assertEqual(self.rows["12"]["last_name"], "van der Merwe")
        self.assertEqual(self.rows["12"]["city"], "Bloemfontein")
        self.assertEqual(self.rows["5"]["last_name"], "Sithole")

    def test_numbers_and_email(self):
        self.assertEqual(self.rows["2"]["monthly_spend"], "320.50")
        self.assertEqual(self.rows["3"]["monthly_spend"], "510.00")
        self.assertEqual(self.rows["2"]["email"], "siphiwe.dlamini@yahoo.com")
        self.assertEqual(self.rows["2"]["phone"], "+27731234567")

    def test_ids_untouched_and_unique(self):
        ids = [r["id"] for r in _rows(self.cleaned)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_report_is_auditable(self):
        self.assertTrue(self.report["summary"])
        change = next(c for c in self.report["changes"] if c["column"] == "gender" and c["before"] == "F")
        self.assertEqual(change["after"], "Female")
        self.assertTrue(any("mostly empty" in f for f in self.report["flags"]))

    def test_input_not_mutated(self):
        again = parse_upload(FIXTURE.read_bytes(), "x.csv")
        self.assertTrue(again.equals(self.raw))

    def test_cleaning_is_idempotent(self):
        out, _ = dataframe_to_bytes(self.cleaned, "x.csv")
        second, report = clean_with_report(parse_upload(out, "x.csv"))
        self.assertEqual(report["duplicates_removed"], 0)
        self.assertEqual(_rows(second), _rows(self.cleaned))

    def test_profile_matches_cleaner(self):
        profile = profile_dataframe(self.raw)
        self.assertEqual(profile["rows"], 40)
        self.assertEqual(profile["duplicate_rows"], 4)
        self.assertGreater(profile["issue_count"], 5)
        types = {c["name"]: c["dtype"] for c in profile["column_profiles"]}
        self.assertEqual(types["email"], "email")
        self.assertEqual(types["signup_date"], "date")
        self.assertEqual(types["age"], "integer")


class EdgeCaseTests(unittest.TestCase):
    def test_empty_file_with_headers(self):
        cleaned, report = _clean("a,b\n")
        self.assertEqual(len(cleaned), 0)
        self.assertEqual(report["rows_after"], 0)

    def test_all_blank_rows_and_columns_dropped(self):
        cleaned, report = _clean("a,b,c\n1,,x\n,,\n")
        self.assertEqual(report["empty_rows_removed"], 1)
        self.assertEqual(report["empty_columns_removed"], ["b"])
        self.assertEqual(list(cleaned.columns), ["a", "c"])

    def test_leading_zero_identifiers_not_treated_as_numbers(self):
        cleaned, _ = _clean("code,name\n007,a\n012,b\n")
        self.assertEqual([r["code"] for r in _rows(cleaned)], ["007", "012"])

    def test_formula_injection_neutralised(self):
        cleaned, _ = _clean('id,note\n1,"=HYPERLINK(""http://evil"")"\n2,hello\n')
        rows = _rows(cleaned)
        self.assertTrue(rows[0]["note"].startswith("'="))
        self.assertEqual(rows[1]["note"].lower(), "hello")

    def test_month_first_dates_detected(self):
        cleaned, _ = _clean("id,signup_date\n1,01/15/2024\n2,03/04/2024\n3,12/25/2024\n")
        self.assertEqual([r["signup_date"] for r in _rows(cleaned)], ["2024-01-15", "2024-03-04", "2024-12-25"])

    def test_semicolon_delimiter_and_cp1252(self):
        raw = "id;name\n1;José\n2;Zoë\n".encode("cp1252")
        df = parse_upload(raw, "x.csv")
        self.assertEqual(list(df.columns), ["id", "name"])
        self.assertEqual(df["name"].tolist(), ["José", "Zoë"])

    def test_dedupe_can_be_disabled(self):
        text = "id,name,email\n1,Ana,a@x.com\n2,Ana,a@x.com\n"
        self.assertEqual(len(_clean(text)[0]), 1)
        self.assertEqual(len(_clean(text, dedupe=False)[0]), 2)

    def test_two_column_file_only_drops_exact_duplicates(self):
        cleaned, _ = _clean("id,name\n1,Ana\n2,Ana\n")
        self.assertEqual(len(cleaned), 2)

    def test_currency_values(self):
        cleaned, _ = _clean('item,price\na,R1 200.50\nb,"R2,000.00"\nc,15\n')
        self.assertEqual([r["price"] for r in _rows(cleaned)], ["1200.50", "2000.00", "15.00"])

    def test_hinted_numeric_column_survives_junk_on_small_files(self):
        cleaned, _ = _clean("id,age\n1,28\n2,28\n3,abc\n")
        self.assertEqual([r["age"] for r in _rows(cleaned)], ["28", "28", ""])

    def test_generated_script_is_valid_python(self):
        script = generate_cleaning_script("x.csv")
        compile(script, "script.py", "exec")
        self.assertIn("clean_with_report", script)


if __name__ == "__main__":
    unittest.main()
