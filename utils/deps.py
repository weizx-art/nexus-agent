from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from utils.exception import UnauthorizedException
from utils.security import decode_access_token
from models.account import Account

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> Account:
    """从 Authorization: Bearer <token> 解析当前登录账号。"""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedException("未授权，请先登录")

    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        raise UnauthorizedException("token 无效或已过期")

    account_id = payload.get("sub")
    if not account_id:
        raise UnauthorizedException("token 无效")

    account = await db.get(Account, account_id)
    if account is None:
        raise UnauthorizedException("账号不存在")
    return account
