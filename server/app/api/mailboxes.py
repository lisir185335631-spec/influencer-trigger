from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_manager_or_above
from app.models.mailbox import MailboxStatus
from app.schemas.auth import TokenData
from app.schemas.mailbox import (
    MailboxCreate,
    MailboxResponse,
    MailboxUpdate,
    TestConnectionRequest,
)
from app.services.mailbox_service import (
    create_mailbox,
    delete_mailbox,
    get_mailbox,
    list_mailboxes,
    test_smtp_connection,
    update_mailbox,
)

router = APIRouter(prefix="/mailboxes", tags=["mailboxes"])


@router.get("/", response_model=list[MailboxResponse])
async def get_mailboxes(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    return await list_mailboxes(db)


@router.post("/", response_model=MailboxResponse, status_code=status.HTTP_201_CREATED)
async def create_mailbox_endpoint(
    body: MailboxCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    try:
        return await create_mailbox(db, body)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Mailbox with email '{body.email}' already exists",
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{mailbox_id}", response_model=MailboxResponse)
async def update_mailbox_endpoint(
    mailbox_id: int,
    body: MailboxUpdate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    try:
        mailbox = await update_mailbox(db, mailbox_id, body)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    return mailbox


@router.delete("/{mailbox_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mailbox_endpoint(
    mailbox_id: int,
    db: AsyncSession = Depends(get_db),
    # SMTP/IMAP credentials are admin-provisioned company assets;
    # operators should not be able to remove send capacity. Limit to
    # manager+ per docs/SECURITY-MODEL.md W-4.
    _: TokenData = Depends(require_manager_or_above),
):
    deleted = await delete_mailbox(db, mailbox_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Mailbox not found")


@router.post("/{mailbox_id}/test")
async def test_mailbox_connection(
    mailbox_id: int,
    body: TestConnectionRequest,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    mailbox = await get_mailbox(db, mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")

    result = await test_smtp_connection(mailbox, body.test_to)

    # Update status based on test result
    mailbox.status = MailboxStatus.active if result["success"] else MailboxStatus.error
    await db.commit()

    return result
