from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.schemas.auth import TokenData
from app.schemas.template import (
    GenerateRequest,
    GeneratedTemplate,
    TemplateCreate,
    TemplateResponse,
    TemplateUpdate,
)
from app.services.template_service import (
    create_template,
    delete_template,
    generate_templates,
    get_template,
    list_templates,
    update_template,
)

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("/", response_model=list[TemplateResponse])
async def get_templates(
    industry: str | None = Query(None, description="Filter by industry"),
    include_unpublished: bool = Query(False, description="Include unpublished templates (admin only)"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    admin_include = include_unpublished and current_user.role == "admin"
    return await list_templates(db, industry=industry, include_unpublished=admin_include)


@router.post("/", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template_endpoint(
    body: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    return await create_template(db, body, created_by=current_user.user_id)


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template_endpoint(
    template_id: int,
    body: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    template = await update_template(db, template_id, body)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template_endpoint(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    deleted = await delete_template(db, template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")


@router.post("/generate", response_model=list[GeneratedTemplate])
async def generate_templates_endpoint(
    body: GenerateRequest,
    _: TokenData = Depends(get_current_user),
):
    try:
        return await generate_templates(body.industry)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
