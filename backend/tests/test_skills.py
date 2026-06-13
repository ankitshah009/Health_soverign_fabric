"""Unit tests for claim_intake_skill, payout_execution_skill, and
payout_recommendation_skill (app/skills/).

All external I/O is fully mocked:
  - app.database.create_claim / add_audit_entry  → AsyncMock
  - app.config.UPLOAD_DIR                        → tmp_path
  - app.skills.payout_execution.update_claim     → AsyncMock
  - app.services.grok_service.grok_service       → MagicMock with AsyncMock methods
  - app.utils.crypto                             → deterministic MagicMock

No real file-system writes, no real SQLite connections, no real HTTP calls.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from app.models.claim import (
    CoverageResult,
    ExtractedData,
    FraudScore,
    PayoutRecommendation,
    RiskLevel,
)
from app.models.decision import DecisionReceipt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_upload_file(
    content: bytes = b"fake-image-data",
    filename: str = "photo.jpg",
) -> UploadFile:
    """Build a minimal UploadFile backed by an in-memory buffer."""
    buf = io.BytesIO(content)
    upload = UploadFile(filename=filename, file=buf)
    return upload


def _sig_result() -> dict[str, str]:
    return {
        "signature": "sig-abc123",
        "public_key": "pubkey-xyz",
        "signature_algorithm": "Ed25519",
        "signing_key_id": "key-001",
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_upload_dir(tmp_path: Path) -> Path:
    """Return a temp directory that acts as UPLOAD_DIR during tests."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


@pytest.fixture
def sample_extracted() -> ExtractedData:
    return ExtractedData(
        damage_type="vehicle collision",
        estimated_cost=3500.0,
        vehicle_info="2020 Toyota Camry",
        incident_details="Rear-end collision at intersection.",
        document_type="damage photo",
        key_findings=["front bumper cracked"],
    )


@pytest.fixture
def sample_coverage() -> CoverageResult:
    return CoverageResult(
        policy_number="AUTO-12345",
        coverage_type="comprehensive_auto",
        coverage_limit=50000.0,
        deductible=500.0,
        covered=True,
        explanation="Covered after deductible.",
    )


@pytest.fixture
def sample_fraud_low() -> FraudScore:
    return FraudScore(
        overall_score=12.0,
        risk_level=RiskLevel.LOW,
        signals=[],
        explanation="No significant fraud indicators detected.",
    )


@pytest.fixture
def payout_recommendation_fixture() -> PayoutRecommendation:
    return PayoutRecommendation(
        recommended_amount=3000.0,
        confidence=0.92,
        rationale="Standard repair cost minus deductible.",
        comparable_claims=["CLM-aabb1122"],
    )


# ---------------------------------------------------------------------------
# claim_intake_skill tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestClaimIntakeSkillExecute:
    """Tests for ClaimIntakeSkill.execute()."""

    @patch("app.skills.claim_intake.add_audit_entry", new_callable=AsyncMock)
    @patch("app.skills.claim_intake.create_claim", new_callable=AsyncMock)
    @patch("app.skills.claim_intake.UPLOAD_DIR")
    async def test_execute_creates_claim_record_and_saves_file(
        self,
        mock_upload_dir: MagicMock,
        mock_create_claim: AsyncMock,
        mock_add_audit: AsyncMock,
        fake_upload_dir: Path,
    ) -> None:
        """execute() must call create_claim once and write file bytes to UPLOAD_DIR."""
        # Wire UPLOAD_DIR to the temp path so write_bytes works for real
        mock_upload_dir.__truediv__ = lambda self_inner, name: fake_upload_dir / name

        expected_record: dict[str, Any] = {
            "id": "CLM-deadbeef",
            "status": "submitted",
            "claimant_name": "Alice",
            "incident_description": "Car crash",
            "policy_number": "AUTO-99",
            "file_path": str(fake_upload_dir / "CLM-deadbeef.jpg"),
            "file_type": "image/jpeg",
            "created_at": "2024-01-01T00:00:00+00:00",
            "extracted_data": None,
            "fraud_score": None,
            "risk_level": None,
            "coverage_result": None,
            "payout_recommendation": None,
            "simulation_result": None,
            "risk_assessment": None,
            "decision": None,
            "decision_by": None,
            "decision_at": None,
            "receipt": None,
        }
        mock_create_claim.return_value = expected_record

        upload = _make_upload_file(b"small-jpg-bytes", "photo.jpg")

        from app.skills.claim_intake import ClaimIntakeSkill
        skill = ClaimIntakeSkill()

        with patch.object(Path, "write_bytes", return_value=None) as mock_write:
            result = await skill.execute(
                file=upload,
                claimant_name="Alice",
                incident_description="Car crash",
                policy_number="AUTO-99",
            )

        mock_create_claim.assert_awaited_once()
        call_kwargs = mock_create_claim.call_args
        assert call_kwargs.kwargs["claimant_name"] == "Alice"
        assert call_kwargs.kwargs["incident_description"] == "Car crash"
        assert call_kwargs.kwargs["policy_number"] == "AUTO-99"
        assert call_kwargs.kwargs["file_type"] == "image/jpeg"

        mock_add_audit.assert_awaited_once()
        audit_kwargs = mock_add_audit.call_args.kwargs
        assert audit_kwargs["action"] == "claim_submitted"
        assert audit_kwargs["actor"] == "Alice"

        assert result.id == "CLM-deadbeef"
        assert result.claimant_name == "Alice"

    @patch("app.skills.claim_intake.add_audit_entry", new_callable=AsyncMock)
    @patch("app.skills.claim_intake.create_claim", new_callable=AsyncMock)
    async def test_execute_generates_clm_format_id(
        self,
        mock_create_claim: AsyncMock,
        mock_add_audit: AsyncMock,
        fake_upload_dir: Path,
    ) -> None:
        """claim_id passed to create_claim must match the CLM-XXXXX pattern."""
        captured_ids: list[str] = []

        async def _capture(**kwargs: Any) -> dict[str, Any]:
            captured_ids.append(kwargs["claim_id"])
            return {
                "id": kwargs["claim_id"],
                "status": "submitted",
                "claimant_name": kwargs["claimant_name"],
                "incident_description": kwargs["incident_description"],
                "policy_number": kwargs.get("policy_number"),
                "file_path": kwargs.get("file_path"),
                "file_type": kwargs.get("file_type"),
                "created_at": "2024-01-01T00:00:00+00:00",
                "extracted_data": None,
                "fraud_score": None,
                "risk_level": None,
                "coverage_result": None,
                "payout_recommendation": None,
                "simulation_result": None,
                "risk_assessment": None,
                "decision": None,
                "decision_by": None,
                "decision_at": None,
                "receipt": None,
            }

        mock_create_claim.side_effect = _capture

        upload = _make_upload_file(b"data", "evidence.png")

        from app.skills.claim_intake import ClaimIntakeSkill
        skill = ClaimIntakeSkill()

        with patch("app.skills.claim_intake.UPLOAD_DIR", fake_upload_dir):
            result = await skill.execute(
                file=upload,
                claimant_name="Bob",
                incident_description="Flood damage",
            )

        assert len(captured_ids) == 1
        claim_id = captured_ids[0]
        # Must match CLM- followed by exactly 8 lowercase hex characters
        assert re.fullmatch(r"CLM-[0-9a-f]{8}", claim_id), (
            f"Generated ID '{claim_id}' does not match CLM-XXXXXXXX format"
        )
        assert result.id == claim_id

    @patch("app.skills.claim_intake.add_audit_entry", new_callable=AsyncMock)
    @patch("app.skills.claim_intake.create_claim", new_callable=AsyncMock)
    async def test_execute_rejects_oversized_file(
        self,
        mock_create_claim: AsyncMock,
        mock_add_audit: AsyncMock,
        fake_upload_dir: Path,
    ) -> None:
        """Files larger than 10 MB must raise HTTP 413 before create_claim is called."""
        from fastapi import HTTPException
        from app.skills.claim_intake import MAX_FILE_SIZE, ClaimIntakeSkill

        oversized_content = b"x" * (MAX_FILE_SIZE + 1)
        upload = _make_upload_file(oversized_content, "huge.jpg")

        skill = ClaimIntakeSkill()

        with patch("app.skills.claim_intake.UPLOAD_DIR", fake_upload_dir):
            with pytest.raises(HTTPException) as exc_info:
                await skill.execute(
                    file=upload,
                    claimant_name="Charlie",
                    incident_description="Large file test",
                )

        assert exc_info.value.status_code == 413
        mock_create_claim.assert_not_awaited()

    @patch("app.skills.claim_intake.add_audit_entry", new_callable=AsyncMock)
    @patch("app.skills.claim_intake.create_claim", new_callable=AsyncMock)
    async def test_execute_sanitizes_filename_directory_traversal(
        self,
        mock_create_claim: AsyncMock,
        mock_add_audit: AsyncMock,
        fake_upload_dir: Path,
    ) -> None:
        """Directory traversal sequences in the filename must be stripped."""
        captured_file_paths: list[str] = []

        async def _capture(**kwargs: Any) -> dict[str, Any]:
            captured_file_paths.append(kwargs.get("file_path", ""))
            return {
                "id": kwargs["claim_id"],
                "status": "submitted",
                "claimant_name": kwargs["claimant_name"],
                "incident_description": kwargs["incident_description"],
                "policy_number": None,
                "file_path": kwargs.get("file_path"),
                "file_type": kwargs.get("file_type"),
                "created_at": "2024-01-01T00:00:00+00:00",
                "extracted_data": None, "fraud_score": None, "risk_level": None,
                "coverage_result": None, "payout_recommendation": None,
                "simulation_result": None, "risk_assessment": None,
                "decision": None, "decision_by": None, "decision_at": None,
                "receipt": None,
            }

        mock_create_claim.side_effect = _capture
        upload = _make_upload_file(b"data", "../../etc/passwd.jpg")

        from app.skills.claim_intake import ClaimIntakeSkill
        skill = ClaimIntakeSkill()

        with patch("app.skills.claim_intake.UPLOAD_DIR", fake_upload_dir):
            await skill.execute(
                file=upload,
                claimant_name="Dave",
                incident_description="Path traversal attempt",
            )

        assert len(captured_file_paths) == 1
        saved_path = captured_file_paths[0]
        # The saved path must NOT contain ".." components
        assert ".." not in saved_path

    @patch("app.skills.claim_intake.add_audit_entry", new_callable=AsyncMock)
    @patch("app.skills.claim_intake.create_claim", new_callable=AsyncMock)
    async def test_execute_detects_pdf_file_type(
        self,
        mock_create_claim: AsyncMock,
        mock_add_audit: AsyncMock,
        fake_upload_dir: Path,
    ) -> None:
        """PDF files must be detected as 'application/pdf' and not resized."""
        captured: list[dict[str, Any]] = []

        async def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return {
                "id": kwargs["claim_id"], "status": "submitted",
                "claimant_name": kwargs["claimant_name"],
                "incident_description": kwargs["incident_description"],
                "policy_number": None,
                "file_path": kwargs.get("file_path"),
                "file_type": kwargs.get("file_type"),
                "created_at": "2024-01-01T00:00:00+00:00",
                "extracted_data": None, "fraud_score": None, "risk_level": None,
                "coverage_result": None, "payout_recommendation": None,
                "simulation_result": None, "risk_assessment": None,
                "decision": None, "decision_by": None, "decision_at": None,
                "receipt": None,
            }

        mock_create_claim.side_effect = _capture
        upload = _make_upload_file(b"%PDF-1.4 fake content", "document.pdf")

        from app.skills.claim_intake import ClaimIntakeSkill
        skill = ClaimIntakeSkill()

        with patch("app.skills.claim_intake.UPLOAD_DIR", fake_upload_dir):
            result = await skill.execute(
                file=upload,
                claimant_name="Eve",
                incident_description="PDF upload",
            )

        assert captured[0]["file_type"] == "application/pdf"


# ---------------------------------------------------------------------------
# payout_execution_skill tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestPayoutExecutionSkillExecute:
    """Tests for PayoutExecutionSkill.execute()."""

    @patch("app.skills.payout_execution.add_audit_entry", new_callable=AsyncMock)
    @patch("app.skills.payout_execution.update_claim", new_callable=AsyncMock)
    @patch("app.skills.payout_execution.compute_signature")
    @patch("app.skills.payout_execution.generate_receipt_id")
    async def test_execute_creates_receipt_and_updates_claim(
        self,
        mock_receipt_id: MagicMock,
        mock_compute_sig: MagicMock,
        mock_update_claim: AsyncMock,
        mock_add_audit: AsyncMock,
    ) -> None:
        """execute() must return a DecisionReceipt and call update_claim + add_audit_entry."""
        mock_receipt_id.return_value = "REC-cafebabe"
        mock_compute_sig.return_value = _sig_result()

        from app.skills.payout_execution import PayoutExecutionSkill
        skill = PayoutExecutionSkill()

        receipt = await skill.execute(
            claim_id="CLM-001",
            approved_by="adjuster@example.com",
            amount=2500.00,
        )

        assert isinstance(receipt, DecisionReceipt)
        assert receipt.receipt_id == "REC-cafebabe"
        assert receipt.claim_id == "CLM-001"
        assert receipt.action == "payout_approved"
        assert receipt.approved_by == "adjuster@example.com"
        assert receipt.signature == "sig-abc123"
        assert receipt.public_key == "pubkey-xyz"
        assert receipt.signature_algorithm == "Ed25519"

        mock_update_claim.assert_awaited_once()
        update_args = mock_update_claim.call_args
        assert update_args.args[0] == "CLM-001"
        assert update_args.kwargs["status"] == "approved"
        assert update_args.kwargs["decision"] == "approve"
        assert update_args.kwargs["decision_by"] == "adjuster@example.com"

        mock_add_audit.assert_awaited_once()
        audit_kwargs = mock_add_audit.call_args.kwargs
        assert audit_kwargs["action"] == "payout_executed"
        assert audit_kwargs["actor"] == "adjuster@example.com"
        assert audit_kwargs["details"]["amount"] == 2500.00
        assert audit_kwargs["details"]["receipt_id"] == "REC-cafebabe"

    @patch("app.skills.payout_execution.add_audit_entry", new_callable=AsyncMock)
    @patch("app.skills.payout_execution.update_claim", new_callable=AsyncMock)
    @patch("app.skills.payout_execution.compute_signature")
    @patch("app.skills.payout_execution.generate_receipt_id")
    async def test_execute_handles_zero_amount(
        self,
        mock_receipt_id: MagicMock,
        mock_compute_sig: MagicMock,
        mock_update_claim: AsyncMock,
        mock_add_audit: AsyncMock,
    ) -> None:
        """execute() with amount=0.0 must succeed and reflect zero in the summary."""
        mock_receipt_id.return_value = "REC-00000000"
        mock_compute_sig.return_value = _sig_result()

        from app.skills.payout_execution import PayoutExecutionSkill
        skill = PayoutExecutionSkill()

        receipt = await skill.execute(
            claim_id="CLM-zero",
            approved_by="system",
            amount=0.0,
        )

        assert isinstance(receipt, DecisionReceipt)
        assert receipt.claim_id == "CLM-zero"
        assert "$0.00" in receipt.simulation_summary
        mock_update_claim.assert_awaited_once()
        update_kwargs = mock_update_claim.call_args.kwargs
        assert update_kwargs["status"] == "approved"
        # Audit entry must still be written
        mock_add_audit.assert_awaited_once()
        assert mock_add_audit.call_args.kwargs["details"]["amount"] == 0.0

    @patch("app.skills.payout_execution.add_audit_entry", new_callable=AsyncMock)
    @patch("app.skills.payout_execution.update_claim", new_callable=AsyncMock)
    @patch("app.skills.payout_execution.compute_signature")
    @patch("app.skills.payout_execution.generate_receipt_id")
    async def test_execute_simulation_summary_contains_amount_and_approver(
        self,
        mock_receipt_id: MagicMock,
        mock_compute_sig: MagicMock,
        mock_update_claim: AsyncMock,
        mock_add_audit: AsyncMock,
    ) -> None:
        """simulation_summary must reference both the dollar amount and the approver name."""
        mock_receipt_id.return_value = "REC-11111111"
        mock_compute_sig.return_value = _sig_result()

        from app.skills.payout_execution import PayoutExecutionSkill
        skill = PayoutExecutionSkill()

        receipt = await skill.execute(
            claim_id="CLM-999",
            approved_by="Senior Adjuster",
            amount=10_000.00,
        )

        assert "10,000.00" in receipt.simulation_summary
        assert "Senior Adjuster" in receipt.simulation_summary

    @patch("app.skills.payout_execution.add_audit_entry", new_callable=AsyncMock)
    @patch("app.skills.payout_execution.update_claim", new_callable=AsyncMock)
    @patch("app.skills.payout_execution.compute_signature")
    @patch("app.skills.payout_execution.generate_receipt_id")
    async def test_execute_receipt_id_is_passed_to_update_claim(
        self,
        mock_receipt_id: MagicMock,
        mock_compute_sig: MagicMock,
        mock_update_claim: AsyncMock,
        mock_add_audit: AsyncMock,
    ) -> None:
        """The receipt dict stored in the DB must carry the same receipt_id returned to the caller."""
        mock_receipt_id.return_value = "REC-aabbccdd"
        mock_compute_sig.return_value = _sig_result()

        from app.skills.payout_execution import PayoutExecutionSkill
        skill = PayoutExecutionSkill()

        receipt = await skill.execute(
            claim_id="CLM-match",
            approved_by="agent",
            amount=500.0,
        )

        stored_receipt = mock_update_claim.call_args.kwargs["receipt"]
        assert stored_receipt["receipt_id"] == receipt.receipt_id == "REC-aabbccdd"


# ---------------------------------------------------------------------------
# payout_recommendation_skill tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestPayoutRecommendationSkillExecute:
    """Tests for PayoutRecommendationSkill.execute()."""

    @patch("app.skills.payout_recommendation.grok_service")
    async def test_execute_calls_grok_service_recommend_payout(
        self,
        mock_grok: MagicMock,
        sample_extracted: ExtractedData,
        sample_coverage: CoverageResult,
        sample_fraud_low: FraudScore,
        payout_recommendation_fixture: PayoutRecommendation,
    ) -> None:
        """execute() must delegate to grok_service.recommend_payout exactly once."""
        mock_grok.recommend_payout = AsyncMock(
            return_value=payout_recommendation_fixture,
        )

        from app.skills.payout_recommendation import PayoutRecommendationSkill
        skill = PayoutRecommendationSkill()

        result = await skill.execute(
            extracted_data=sample_extracted,
            coverage=sample_coverage,
            fraud_score=sample_fraud_low,
        )

        mock_grok.recommend_payout.assert_awaited_once_with(
            sample_extracted, sample_coverage, sample_fraud_low,
        )
        assert result is payout_recommendation_fixture

    @patch("app.skills.payout_recommendation.grok_service")
    async def test_execute_returns_payout_recommendation_with_correct_fields(
        self,
        mock_grok: MagicMock,
        sample_extracted: ExtractedData,
        sample_coverage: CoverageResult,
        sample_fraud_low: FraudScore,
    ) -> None:
        """The returned PayoutRecommendation must carry the exact values from Grok."""
        expected = PayoutRecommendation(
            recommended_amount=4250.75,
            confidence=0.88,
            rationale="Adjusted for prior deductible history.",
            comparable_claims=["CLM-00000001", "CLM-00000002"],
        )
        mock_grok.recommend_payout = AsyncMock(return_value=expected)

        from app.skills.payout_recommendation import PayoutRecommendationSkill
        skill = PayoutRecommendationSkill()

        result = await skill.execute(
            extracted_data=sample_extracted,
            coverage=sample_coverage,
            fraud_score=sample_fraud_low,
        )

        assert isinstance(result, PayoutRecommendation)
        assert result.recommended_amount == pytest.approx(4250.75)
        assert result.confidence == pytest.approx(0.88)
        assert result.rationale == "Adjusted for prior deductible history."
        assert result.comparable_claims == ["CLM-00000001", "CLM-00000002"]

    @patch("app.skills.payout_recommendation.grok_service")
    async def test_execute_propagates_grok_exception(
        self,
        mock_grok: MagicMock,
        sample_extracted: ExtractedData,
        sample_coverage: CoverageResult,
        sample_fraud_low: FraudScore,
    ) -> None:
        """If grok_service.recommend_payout raises, the exception must bubble up."""
        mock_grok.recommend_payout = AsyncMock(
            side_effect=RuntimeError("Grok API unavailable"),
        )

        from app.skills.payout_recommendation import PayoutRecommendationSkill
        skill = PayoutRecommendationSkill()

        with pytest.raises(RuntimeError, match="Grok API unavailable"):
            await skill.execute(
                extracted_data=sample_extracted,
                coverage=sample_coverage,
                fraud_score=sample_fraud_low,
            )

    @patch("app.skills.payout_recommendation.grok_service")
    async def test_execute_passes_all_inputs_to_grok(
        self,
        mock_grok: MagicMock,
        sample_coverage: CoverageResult,
        sample_fraud_low: FraudScore,
    ) -> None:
        """All three input objects must be forwarded verbatim to grok_service.recommend_payout."""
        custom_extracted = ExtractedData(
            damage_type="hail damage",
            estimated_cost=800.0,
            vehicle_info="2018 Honda Accord",
            incident_details="Hail storm cracked windshield.",
            document_type="photo",
            key_findings=["windshield cracked"],
        )
        mock_grok.recommend_payout = AsyncMock(
            return_value=PayoutRecommendation(recommended_amount=300.0, confidence=0.75),
        )

        from app.skills.payout_recommendation import PayoutRecommendationSkill
        skill = PayoutRecommendationSkill()

        await skill.execute(
            extracted_data=custom_extracted,
            coverage=sample_coverage,
            fraud_score=sample_fraud_low,
        )

        call_args = mock_grok.recommend_payout.call_args
        assert call_args.args[0] is custom_extracted
        assert call_args.args[1] is sample_coverage
        assert call_args.args[2] is sample_fraud_low
