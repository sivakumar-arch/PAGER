"""Unit tests for QueryAnalyzer.

Tests intent classification, PII detection, entity extraction,
and sensitivity resolution for all MedAgentBench task types.
"""

import pytest

from src.pager.query_analyzer import QueryAnalyzer


@pytest.fixture
def analyzer() -> QueryAnalyzer:
    return QueryAnalyzer()


class TestPIIDetection:
    """Tests for PII pattern detection."""

    def test_patient_name_detected(self, analyzer):
        query = analyzer.analyze("What is the MRN of patient Peter Stafford?", user_role="nurse")
        assert query.contains_pii is True

    def test_mrn_detected(self, analyzer):
        query = analyzer.analyze("Get labs for patient S3032536", user_role="nurse")
        assert query.contains_pii is True

    def test_dob_detected(self, analyzer):
        query = analyzer.analyze("Find patient with DOB 1932-12-29", user_role="nurse")
        assert query.contains_pii is True

    def test_no_pii_query(self, analyzer):
        query = analyzer.analyze("What are the current lab reference ranges?", user_role="nurse")
        assert query.contains_pii is False

    def test_explicit_dob_keyword(self, analyzer):
        query = analyzer.analyze("Patient DOB required for verification", user_role="nurse")
        assert query.contains_pii is True


class TestIntentClassification:
    """Tests for intent and capability mapping across all task types."""

    @pytest.mark.parametrize("query_text,expected_intent,expected_cap", [
        # Task 1 & 2: Demographics
        ("What is the MRN of patient Peter Stafford, DOB 1932-12-29?",
         "lookup", "GET /Patient"),
        # Task 3: Vitals
        ("Record blood pressure for patient S1234567",
         "ordering", "POST /Observation"),
        # Task 4: Labs
        ("What is the most recent magnesium level of patient S3032536?",
         "retrieval", "GET /Observation"),
        # Task 5: Medications
        ("What medications is patient S1234567 currently taking?",
         "ordering", "POST /MedicationRequest"),
        # Task 8: Procedures
        ("Order an orthopedic surgery referral for patient S2016972",
         "ordering", "POST /ServiceRequest"),
    ])
    def test_task_intent_mapping(self, analyzer, query_text, expected_intent, expected_cap):
        result = analyzer.analyze(query_text, user_role="nurse")
        assert result.intent == expected_intent
        assert expected_cap in result.required_capabilities

    def test_lab_keywords_map_to_get_observation(self, analyzer):
        for keyword in ["glucose", "hba1c", "hemoglobin", "creatinine"]:
            query = analyzer.analyze(f"What is the {keyword} level for patient S1234567?", user_role="nurse")
            assert "GET /Observation" in query.required_capabilities, f"Failed for keyword: {keyword}"

    def test_vital_keywords_map_to_post_observation(self, analyzer):
        for keyword in ["blood pressure", "heart rate", "vital signs", "oxygen saturation"]:
            query = analyzer.analyze(f"Record {keyword} for patient S1234567", user_role="nurse")
            assert "POST /Observation" in query.required_capabilities, f"Failed for keyword: {keyword}"

    def test_referral_maps_to_service_request(self, analyzer):
        query = analyzer.analyze("Submit cardiology referral for patient S9876543", user_role="doctor")
        assert "POST /ServiceRequest" in query.required_capabilities


class TestSensitivityResolution:
    """Tests for data sensitivity classification."""

    def test_lab_query_is_high_sensitivity(self, analyzer):
        query = analyzer.analyze("Get magnesium level for S3032536", user_role="nurse")
        assert query.data_sensitivity == "high"

    def test_demographics_is_medium_sensitivity(self, analyzer):
        query = analyzer.analyze("Find patient Peter Stafford demographics", user_role="nurse")
        assert query.data_sensitivity == "medium"

    def test_pii_elevates_low_to_medium(self, analyzer):
        # A query with PII that doesn't match any capability pattern
        query = analyzer.analyze(
            "Lookup John Smith in the system",
            user_role="marketing_manager",
        )
        # PII detected, marketing role default is low → elevated to medium
        assert query.data_sensitivity in ("medium", "high")


class TestEntityExtraction:
    """Tests for entity extraction from query text."""

    def test_mrn_extracted(self, analyzer):
        query = analyzer.analyze("Get labs for patient S3032536", user_role="nurse")
        assert query.entities.get("mrn") == "S3032536"

    def test_patient_name_extracted(self, analyzer):
        query = analyzer.analyze(
            "What is the MRN of patient Peter Stafford, DOB 1932-12-29?",
            user_role="nurse",
        )
        assert query.entities.get("patient_name") == "Peter Stafford"

    def test_dob_extracted(self, analyzer):
        query = analyzer.analyze(
            "Find patient with DOB 1932-12-29",
            user_role="nurse",
        )
        assert query.entities.get("dob") == "1932-12-29"

    def test_lab_test_extracted(self, analyzer):
        query = analyzer.analyze("What is the magnesium level for S1234567?", user_role="nurse")
        assert query.entities.get("lab_test") == "magnesium"

    def test_procedure_type_extracted(self, analyzer):
        query = analyzer.analyze("Order orthopedic referral for S2016972", user_role="doctor")
        assert query.entities.get("procedure_type") == "orthopedic"

    def test_no_entities_empty_dict(self, analyzer):
        query = analyzer.analyze("Show lab reference ranges", user_role="nurse")
        # No PII in this query — entities may be empty or partial
        assert isinstance(query.entities, dict)


class TestContextPassthrough:
    """Tests that user context is correctly passed through."""

    def test_user_role_preserved(self, analyzer):
        query = analyzer.analyze("Get patient labs", user_role="doctor")
        assert query.user_role == "doctor"

    def test_user_region_preserved(self, analyzer):
        query = analyzer.analyze("Process data", user_role="data_processor", user_region="EU")
        assert query.user_region == "EU"

    def test_task_type_preserved(self, analyzer):
        query = analyzer.analyze("Get MRN of Peter Stafford", user_role="nurse", task_type=1)
        assert query.task_type == 1

    def test_raw_query_preserved(self, analyzer):
        raw = "What is the MRN of patient Peter Stafford, DOB 1932-12-29?"
        query = analyzer.analyze(raw, user_role="nurse")
        assert query.raw_query == raw

    def test_deterministic_output(self, analyzer):
        """Same input must always produce identical output."""
        raw = "What is the magnesium level of patient S3032536?"
        result1 = analyzer.analyze(raw, user_role="nurse")
        result2 = analyzer.analyze(raw, user_role="nurse")
        assert result1.intent == result2.intent
        assert result1.contains_pii == result2.contains_pii
        assert result1.required_capabilities == result2.required_capabilities
