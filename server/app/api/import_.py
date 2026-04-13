import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.schemas.auth import TokenData
from app.schemas.import_ import (
    ColumnMappingItem,
    ImportConfirmResponse,
    ImportPreviewResponse,
)
from app.services.import_service import confirm_import, preview_import

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/influencers", tags=["import"])

_ALLOWED_TYPES = {
    "text/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _validate_file(file: UploadFile) -> None:
    filename = file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file type '{ext}'. Allowed: .csv, .xlsx, .xls",
        )
    if file.size is not None and file.size > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large ({file.size / 1024 / 1024:.1f} MB). Maximum: 10 MB",
        )


@router.post(
    "/import/preview",
    response_model=ImportPreviewResponse,
    summary="Preview CSV/Excel import",
)
async def import_preview(
    file: UploadFile = File(...),
    _: TokenData = Depends(get_current_user),
) -> ImportPreviewResponse:
    _validate_file(file)
    try:
        return await preview_import(file)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        logger.exception("Error during import preview")
        raise HTTPException(status_code=500, detail=f"Failed to parse file: {exc}")


@router.post(
    "/import/confirm",
    response_model=ImportConfirmResponse,
    summary="Confirm and execute CSV/Excel import",
)
async def import_confirm(
    file: UploadFile = File(...),
    mapping: str = Form(...),          # JSON-encoded list of ColumnMappingItem
    overwrite_duplicates: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> ImportConfirmResponse:
    _validate_file(file)
    try:
        mapping_items = [ColumnMappingItem(**item) for item in json.loads(mapping)]
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid mapping JSON")
    try:
        return await confirm_import(file, mapping_items, overwrite_duplicates, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        logger.exception("Error during import confirm")
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")
