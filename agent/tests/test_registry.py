import unittest
from unittest.mock import patch

from tools.registry import compute_effective_ownership


class EffectiveOwnershipTests(unittest.TestCase):
    def test_two_company_cycle_is_reported(self):
        registry = {
            "US:A": {
                "jurisdiction": "US",
                "shareholders": [
                    {
                        "type": "company",
                        "jurisdiction": "GB",
                        "registration_number": "B",
                        "ownership": "50",
                    },
                    {
                        "type": "person",
                        "name": "Direct Owner",
                        "dob": "1980-01-01",
                        "nationality": "US",
                        "ownership": "50",
                    },
                ],
            },
            "GB:B": {
                "jurisdiction": "GB",
                "shareholders": [
                    {
                        "type": "company",
                        "jurisdiction": "US",
                        "registration_number": "A",
                        "ownership": "50",
                    }
                ],
            },
        }

        with patch("tools.registry._registry", return_value=registry):
            result = compute_effective_ownership.invoke(
                {"jurisdiction": "US", "registration_number": "A"}
            )

        self.assertTrue(result["found"])
        self.assertTrue(result["has_circular_ownership"])
        self.assertEqual(result["cycle_companies"], ["US:A"])
        self.assertEqual(result["all_owners"][0]["effective_ownership_pct"], 50.0)

    def test_acyclic_ownership_math_is_unchanged(self):
        registry = {
            "US:A": {
                "jurisdiction": "US",
                "shareholders": [
                    {
                        "type": "company",
                        "jurisdiction": "GB",
                        "registration_number": "B",
                        "ownership": "50",
                    },
                    {
                        "type": "person",
                        "name": "Direct Owner",
                        "dob": "1980-01-01",
                        "nationality": "US",
                        "ownership": "50",
                    },
                ],
            },
            "GB:B": {
                "jurisdiction": "GB",
                "shareholders": [
                    {
                        "type": "person",
                        "name": "Indirect Owner",
                        "dob": "1985-01-01",
                        "nationality": "GB",
                        "ownership": "50",
                    }
                ],
            },
        }

        with patch("tools.registry._registry", return_value=registry):
            result = compute_effective_ownership.invoke(
                {"jurisdiction": "US", "registration_number": "A"}
            )

        self.assertFalse(result["has_circular_ownership"])
        self.assertEqual(result["cycle_companies"], [])
        self.assertEqual(
            {
                owner["name"]: owner["effective_ownership_pct"]
                for owner in result["all_owners"]
            },
            {"Direct Owner": 50.0, "Indirect Owner": 25.0},
        )


if __name__ == "__main__":
    unittest.main()
