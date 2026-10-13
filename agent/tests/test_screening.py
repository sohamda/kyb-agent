import unittest
from unittest.mock import patch

from tools.screening import screen_name


class ScreenNameTests(unittest.TestCase):
    def test_transliterated_applicant_spellings_match_sanctions_data(self):
        cases = [
            ("Youssef Ben Haddou", "DSL-0023"),
            ("Muhammad Alqasimar", "DSL-0022"),
            ("Sergej Waldurin", "DSL-0029"),
            ("Michail Twerdochlebow", "DSL-0033"),
        ]
        for name, entry_id in cases:
            with self.subTest(name=name):
                result = screen_name.invoke(
                    {"name": name, "dob": "1986-04-18", "nationality": "FR"}
                )
                hits = [hit for hit in result["sanctions_hits"] if hit["entry_id"] == entry_id]
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["match_basis"], "transliteration")
                self.assertIn("dob", hits[0])
                self.assertIn("nationality", hits[0])

    def test_aliases_use_shared_matcher_for_sanctions_and_pep(self):
        listed_names = [
            ("Yusuf Benhaddou", "Youssef Ben Haddou"),
            ("Mohammed Al-Qasimar", "Muhammad Alqasimar"),
            ("Sergei Valdurin", "Sergej Waldurin"),
            ("Mikhail Tverdokhlebov", "Michail Twerdochlebow"),
        ]
        for listed_name, alias in listed_names:
            with self.subTest(alias=alias):
                sanctions_entry = {
                    "entry_id": "DSL-ALIAS",
                    "name": "Unrelated Sanctions Name",
                    "aliases": [listed_name],
                }
                pep_entry = {
                    "pep_id": "PEP-ALIAS",
                    "name": "Unrelated PEP Name",
                    "aliases": [listed_name],
                }
                with patch("tools.screening._watchlist", return_value=[sanctions_entry]), patch(
                    "tools.screening.load",
                    side_effect=lambda filename: [pep_entry] if filename == "pep.json" else [],
                ):
                    result = screen_name.invoke({"name": alias})
                self.assertEqual(result["sanctions_hits"][0]["match_basis"], "transliteration")
                self.assertEqual(result["pep_hits"][0]["match_basis"], "transliteration")

    def test_unicode_punctuation_spacing_and_order_normalize(self):
        listed_entry = {
            "entry_id": "DSL-NORMALIZED",
            "name": "Maria Élodie",
            "aliases": [],
        }
        with patch("tools.screening._watchlist", return_value=[listed_entry]), patch(
            "tools.screening.load", return_value=[]
        ):
            result = screen_name.invoke({"name": "Elodie-Maria"})
        self.assertEqual(len(result["sanctions_hits"]), 1)
        self.assertEqual(result["sanctions_hits"][0]["match_basis"], "normalized")

    def test_attached_and_separated_particles_normalize(self):
        for listed_name, query in [
            ("Youssef Benhaddou", "Youssef Ben Haddou"),
            ("Muhammad Alqasimar", "Muhammad Al Qasimar"),
        ]:
            with self.subTest(query=query):
                listed_entry = {"entry_id": "DSL-PARTICLE", "name": listed_name, "aliases": []}
                with patch("tools.screening._watchlist", return_value=[listed_entry]), patch(
                    "tools.screening.load", return_value=[]
                ):
                    result = screen_name.invoke({"name": query})
                self.assertEqual(len(result["sanctions_hits"]), 1)
                self.assertEqual(result["sanctions_hits"][0]["match_basis"], "normalized")

    def test_unrelated_names_do_not_match_after_normalization(self):
        unrelated_entry = {
            "entry_id": "DSL-UNRELATED",
            "name": "Samuel MacTavish",
            "aliases": [],
        }
        with patch("tools.screening._watchlist", return_value=[unrelated_entry]), patch(
            "tools.screening.load", return_value=[]
        ):
            result = screen_name.invoke({"name": "Samuel Mitchell"})
        self.assertEqual(result["sanctions_hits"], [])
        self.assertEqual(result["pep_hits"], [])

    def test_particle_normalization_does_not_match_different_name(self):
        unrelated_entry = {
            "entry_id": "DSL-PARTICLE",
            "name": "Youssef Haddou",
            "aliases": [],
        }
        with patch("tools.screening._watchlist", return_value=[unrelated_entry]), patch(
            "tools.screening.load", return_value=[]
        ):
            result = screen_name.invoke({"name": "Youssef Ben Haddou"})
        self.assertEqual(result["sanctions_hits"], [])


if __name__ == "__main__":
    unittest.main()
