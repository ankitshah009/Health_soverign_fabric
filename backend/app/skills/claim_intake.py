"""Case Intake Skill — saves the uploaded medical bill/EOB/denial and creates the initial case record."""

from __future__ import annotations

import io
import logging
import re
import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image

from app.config import UPLOAD_DIR
from app.database import add_audit_entry, create_claim
from app.models.claim import ClaimData

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_IMAGE_DIMENSION = 4000  # px — resize if larger

logger = logging.getLogger(__name__)

SKILL_METADATA = {
    "skill_name": "claim_intake_skill",
    "action_category": "claims_processing",
    "read_or_write": "write",
    "money_movement": False,
    "reversible": True,
}


def _generate_claim_id() -> str:
    return f"CLM-{secrets.token_hex(4)}"


def _detect_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }
    return type_map.get(ext, "application/octet-stream")


class ClaimIntakeSkill:
    """Handles initial case submission: medical-document save + DB record creation."""

    async def execute(
        self,
        file: UploadFile,
        claimant_name: str,
        incident_description: str,
        policy_number: str = "",
    ) -> ClaimData:
        claim_id = _generate_claim_id()

        # Determine file info — sanitize filename
        raw_name = Path(file.filename or "upload").name  # strip directory components
        original_name = re.sub(r"[^\w.\-]", "_", raw_name)
        ext = Path(original_name).suffix or ".jpg"
        safe_filename = f"{claim_id}{ext}"
        file_path = UPLOAD_DIR / safe_filename
        file_type = _detect_file_type(original_name)

        # Read and validate file size
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large ({len(content) / 1024 / 1024:.1f} MB). Maximum is 10 MB.",
            )

        # Auto-resize large images to prevent Grok API payload issues
        if file_type.startswith("image/") and file_type != "image/gif":
            try:
                img = Image.open(io.BytesIO(content))
                w, h = img.size
                if max(w, h) > MAX_IMAGE_DIMENSION:
                    ratio = MAX_IMAGE_DIMENSION / max(w, h)
                    new_size = (int(w * ratio), int(h * ratio))
                    img = img.resize(new_size, Image.LANCZOS)
                    buf = io.BytesIO()
                    fmt = "PNG" if ext.lower() == ".png" else "JPEG"
                    img.save(buf, format=fmt, quality=85)
                    content = buf.getvalue()
                    logger.info("Resized image from %dx%d to %dx%d for %s", w, h, *new_size, claim_id)
            except Exception as exc:
                logger.warning("Image resize failed for %s: %s (using original)", claim_id, exc)

        # Save file to disk
        file_path.write_bytes(content)
        logger.info("Saved upload for %s: %s (%d bytes)", claim_id, file_path, len(content))

        # Create DB record
        record = await create_claim(
            claim_id=claim_id,
            claimant_name=claimant_name,
            incident_description=incident_description,
            policy_number=policy_number or None,
            file_path=str(file_path),
            file_type=file_type,
        )

        # Audit
        await add_audit_entry(
            claim_id=claim_id,
            action="claim_submitted",
            actor=claimant_name,
            details={
                "file_name": original_name,
                "file_type": file_type,
                "file_size": len(content),
                "policy_number": policy_number,
            },
        )

        return ClaimData(**record)


# Module-level singleton
claim_intake_skill = ClaimIntakeSkill()
