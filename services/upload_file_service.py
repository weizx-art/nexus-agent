from sqlalchemy.ext.asyncio import AsyncSession

from core.database import auto_commit
from models import Account, UploadFile


class UploadFileService:
    """文件上传服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_upload_file(
        self, account: Account, name: str, key: str, size: int, extension: str, mime_type: str, hash: str
    ) -> UploadFile:
        upload_file = UploadFile(
            account_id=account.id,
            name=name,
            key=key,
            size=size,
            extension=extension,
            mime_type=mime_type,
            hash=hash,
        )
        async with auto_commit(self.db):
            self.db.add(upload_file)
        await self.db.refresh(upload_file)
        return upload_file
