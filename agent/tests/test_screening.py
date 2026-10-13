import unittest
from unittest.mock import patch

from tools.screening import _normalize, _phonetic_key, screen_name


class ScreeningTests(unittest.TestCase):
    def test_transliterated_sanctions_match_returns_listed_entry(self):
        result = screen_name.invoke(
            {
                "name": "Michail Twerdochlebow",
                "dob": "1963-02-13",
                "nationality": "CN",
            }
        )

        matches = [hit for hit in result["sanctions_hits"] if hit["entry_id"] == "DSL-0033"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["match_basis"], "name")

    def test_low_similarity_match_requires_both_exact_identifiers(self):
        name = "Ivan Mikhail Tverdokhlebov"
        unrelated_result = screen_name.invoke(
            {"name": "Alexander Petrov", "dob": "1970-01-01", "nationality": "RU"}
        )
        self.assertNotIn(
            "DSL-0033", [hit["entry_id"] for hit in unrelated_result["sanctions_hits"]]
        )

        corroborated_result = screen_name.invoke(
            {"name": name, "dob": "1963-02-13", "nationality": "CN"}
        )
        corroborated_hit = next(
            hit
            for hit in corroborated_result["sanctions_hits"]
            if hit["entry_id"] == "DSL-0033"
        )
        self.assertEqual(corroborated_hit["match_basis"], "name_low+dob+nationality")

        for query in (
            {"dob": "1963-02-14", "nationality": "CN"},
            {"dob": "1963-02-13", "nationality": "US"},
            {"dob": "1963-02-13"},
            {"nationality": "CN"},
        ):
            with self.subTest(query=query):
                result = screen_name.invoke({"name": name, **query})
                self.assertNotIn(
                    "DSL-0033", [hit["entry_id"] for hit in result["sanctions_hits"]]
                )

    def test_name_only_query_keeps_strict_threshold(self):
        result = screen_name.invoke({"name": "Ivan Mikhail Tverdokhlebov"})
        self.assertNotIn("DSL-0033", [hit["entry_id"] for hit in result["sanctions_hits"]])

        exact_result = screen_name.invoke({"name": "Mikhail Tverdokhlebov"})
        hit = next(
            hit for hit in exact_result["sanctions_hits"] if hit["entry_id"] == "DSL-0033"
        )
        self.assertEqual(hit["match_basis"], "name")

    def test_pep_alias_matches_with_corroboration(self):
        pep_entry = {
            "pep_id": "PEP-1",
            "name": "Listed Person",
            "aliases": ["Mikhail Tverdokhlebov"],
            "dob": "1963-02-13",
            "nationality": "CN",
            "position": "Official",
        }

        with patch("tools.screening.load", side_effect=[[], [], [pep_entry]]):
            result = screen_name.invoke(
                {
                    "name": "Michail Twerdochlebow Smith",
                    "dob": "1963-02-13",
                    "nationality": "CN",
                }
            )

        self.assertEqual(len(result["pep_hits"]), 1)
        self.assertEqual(result["pep_hits"][0]["match_basis"], "name_low+dob+nationality")

        with patch("tools.screening.load", side_effect=[[], [], [pep_entry]]):
            name_only_result = screen_name.invoke({"name": "Michail Twerdochlebow Smith"})
        self.assertEqual(name_only_result["pep_hits"], [])

    def test_normalization_and_phonetic_key_handle_name_variants(self):
        self.assertEqual(_normalize("Jürgen O’Neil-Smith"), "jurgen o neil smith")
        self.assertEqual(_normalize("Jurgen O Neil Smith"), "jurgen o neil smith")
        self.assertEqual(
            _phonetic_key("Michail Twerdochlebow"),
            _phonetic_key("Mikhail Tverdokhlebov"),
        )


if __name__ == "__main__":
    unittest.main()
