from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from utils.deps import get_current_user
from utils.response import success_json, success_message
from models import Account
from schemas.auth import PasswordLoginReq, RegisterReq
from services.account_service import AccountService

router = APIRouter(prefix="/auth", tags=["授权认证"])


@router.post("/password-login")
async def password_login(req: PasswordLoginReq, request: Request, db: AsyncSession = Depends(get_db)):
    """账号密码登录"""
    ip = request.client.host if request.client else ""
    credential = await AccountService(db).password_login(req.username, req.password, ip)
    return success_json(credential)


@router.post("/register")
async def register(req: RegisterReq, db: AsyncSession = Depends(get_db)):
    """注册新账号"""
    account = await AccountService(db).create_account(req.username, req.password, req.name)
    return success_json({"id": str(account.id), "username": account.username, "name": account.name})


@router.post("/logout")
async def logout(_: Account = Depends(get_current_user)):
    """退出登录（客户端清除 token 即可）"""
    return success_message("退出登录成功")
