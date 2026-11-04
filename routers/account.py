from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from utils.deps import get_current_user
from utils.response import success_json, success_message
from models import Account
from schemas.account import CurrentUserOut, UpdateAccountReq
from services.account_service import AccountService

router = APIRouter(prefix="/account", tags=["账号设置"])


@router.get("")
async def get_current_user_info(account: Account = Depends(get_current_user)):
    return success_json(
        CurrentUserOut(
            id=str(account.id),
            name=account.name,
            username=account.username,
            avatar=account.avatar,
            last_login_at=account.last_login_at,
            last_login_ip=account.last_login_ip or "",
            created_at=account.created_at,
        ).model_dump()
    )


@router.patch("")
async def update_account(
    req: UpdateAccountReq,
    account: Account = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """部分更新账号信息（name / avatar / password 均可选，至少传一个）"""
    svc = AccountService(db)
    updates = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.avatar is not None:
        updates["avatar"] = req.avatar
    if updates:
        await svc.update_account(account, **updates)
    if req.password is not None:
        await svc.update_password(account, req.password)
    return success_message("更新账号信息成功")
