import unittest

from tools.documents import check_document


class CheckDocumentDateTests(unittest.TestCase):
    def check_expiry(self, expiry_date: str, **kwargs: str) -> dict:
        return check_document.invoke(
            {
                "doc_type": "passport",
                "holder": "Example Holder",
                "expiry_date": expiry_date,
                "as_of": "2029-01-01",
                **kwargs,
            }
        )

    def test_iso_date_is_valid(self):
        result = self.check_expiry("2030-04-24")

        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["expiry_parsed"], "2030-04-24")

    def test_mdy_date_is_valid(self):
        result = self.check_expiry("04/24/2030", date_order="MDY")

        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["expiry_parsed"], "2030-04-24")

    def test_dmy_date_is_valid(self):
        result = self.check_expiry("24/04/2030", date_order="DMY")

        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["expiry_parsed"], "2030-04-24")

    def test_german_date_is_valid(self):
        result = self.check_expiry("24.04.2030", locale="de-DE")

        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["expiry_parsed"], "2030-04-24")

    def test_ambiguous_date_without_order_is_unverifiable(self):
        result = self.check_expiry("05/04/2030")

        self.assertEqual(result["status"], "unverifiable")
        self.assertIsNone(result["expired"])
        self.assertIn("ambiguous", result["reason"])

    def test_configured_jurisdiction_supplies_date_order(self):
        result = self.check_expiry("24-04-2030", jurisdiction="DE")

        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["expiry_parsed"], "2030-04-24")

    def test_explicit_date_order_takes_precedence(self):
        result = self.check_expiry("04/05/2030", date_order="DMY", locale="en-US")

        self.assertEqual(result["expiry_parsed"], "2030-05-04")


if __name__ == "__main__":
    unittest.main()
