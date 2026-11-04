from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import auto_commit
from utils.exception import FailException
from utils.security import create_access_token, validate_password_strength
from models import Account
from utils.security import compare_password, generate_password_salt_and_hash


class AccountService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_username(self, username: str) -> Account | None:
        result = await self.db.execute(select(Account).where(Account.username == username))
        return result.scalar_one_or_none()

    async def create_account(self, username: str, password: str, name: str = "") -> Account:
        """注册新账号"""
        validate_password_strength(password)
        if await self.get_by_username(username):
            raise FailException("该用户名已被注册")
        salt, hashed = generate_password_salt_and_hash(password)
        account = Account(username=username, name=name or username, password_salt=salt, password=hashed)
        async with auto_commit(self.db):
            self.db.add(account)
        await self.db.refresh(account)
        return account

    async def password_login(self, username: str, password: str, ip: str = "") -> dict:
        """账号密码登录，返回 {expire_at, access_token}"""
        account = await self.get_by_username(username)
        if not account or not account.is_password_set:
            raise FailException("账号不存在或者密码错误，请核实后重试")

        if not compare_password(password, account.password, account.password_salt):
            raise FailException("账号不存在或者密码错误，请核实后重试")

        access_token, expire_at = create_access_token(account.id)

        async with auto_commit(self.db):
            account.last_login_at = datetime.now()
            account.last_login_ip = ip

        return {"expire_at": expire_at, "access_token": access_token}

    async def update_password(self, account: Account, password: str) -> None:
        salt, hashed = generate_password_salt_and_hash(password)
        async with auto_commit(self.db):
            account.password_salt = salt
            account.password = hashed

    async def update_account(self, account: Account, **fields) -> Account:
        async with auto_commit(self.db):
            for k, v in fields.items():
                setattr(account, k, v)
        await self.db.refresh(account)
        return account
