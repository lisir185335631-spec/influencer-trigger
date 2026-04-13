from typing import Any
from pydantic import BaseModel


class ColumnMappingItem(BaseModel):
    csv_column: str        # column name as it appears in the file
    field: str | None      # target field name, None = skip


class ImportPreviewResponse(BaseModel):
    rows: list[dict[str, Any]]          # first 10 rows (raw values)
    columns: list[str]                  # all column names from file
    suggested_mapping: list[ColumnMappingItem]
    total_rows: int                     # total rows excluding header


class ImportRowResult(BaseModel):
    row_index: int
    email: str
    status: str        # "imported" | "duplicate" | "invalid_email" | "skipped"
    message: str | None = None


class ImportConfirmResponse(BaseModel):
    imported: int
    duplicates: int
    invalid: int
    total: int
    errors: list[str]
