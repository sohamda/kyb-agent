import unittest

from pydantic import ValidationError

from schemas import KYBDecision


class KYBDecisionSchemaTests(unittest.TestCase):
    def setUp(self):
        self.decision = {
            "application_id": "application-1",
            "decision": "approve",
            "risk_rating": "low",
            "ubos": [{"name": "Alex Example", "effective_ownership_pct": 50}],
            "screened_parties": ["Alex Example"],
            "flags": [],
            "rationale": "Registry and screening tools found no material issues.",
        }

    def test_evidence_fields_are_required_in_json_schema(self):
        required = KYBDecision.model_json_schema()["required"]

        self.assertTrue({"ubos", "screened_parties", "rationale"}.issubset(required))

    def test_missing_ubos_fails_validation(self):
        decision = self.decision.copy()
        del decision["ubos"]

        with self.assertRaises(ValidationError):
            KYBDecision.model_validate(decision)

    def test_missing_screened_parties_fails_validation(self):
        decision = self.decision.copy()
        del decision["screened_parties"]

        with self.assertRaises(ValidationError):
            KYBDecision.model_validate(decision)

    def test_empty_screened_parties_fails_validation(self):
        decision = self.decision | {"screened_parties": []}

        with self.assertRaises(ValidationError):
            KYBDecision.model_validate(decision)

    def test_empty_or_short_rationale_fails_validation(self):
        for rationale in ("", "x" * 39):
            with self.subTest(rationale=rationale):
                decision = self.decision | {"rationale": rationale}

                with self.assertRaises(ValidationError):
                    KYBDecision.model_validate(decision)

    def test_well_formed_decision_passes_validation(self):
        validated = KYBDecision.model_validate(self.decision)

        self.assertEqual(validated, KYBDecision(**self.decision))


if __name__ == "__main__":
    unittest.main()
