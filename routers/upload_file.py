from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from utils.deps import get_current_user
from utils.exception import FailException
from utils.response import success_json
from models import Account
from schemas.upload_file import UploadFileOut
from services.storage_service import ALLOWED_IMAGE, MAX_FILE_SIZE, StorageService
from services.upload_file_service import UploadFileService

router = APIRouter(prefix="/upload-files", tags=["文件上传"])


@router.post("/file")
async def upload_file(
    file: UploadFile = File(...),
    account: Account = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise FailException("上传文件大小不能超过 15MB")
    info = await StorageService.put_object(file.filename, content, file.content_type or "application/octet-stream")
    uf = await UploadFileService(db).create_upload_file(account=account, name=file.filename, **info)
    return success_json(UploadFileOut(id=str(uf.id), name=uf.name, size=uf.size, extension=uf.extension, mime_type=uf.mime_type).model_dump())


@router.post("/image")
async def upload_image(
    file: UploadFile = File(...),
    account: Account = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    extension = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if extension not in ALLOWED_IMAGE:
        raise FailException("请上传正确的图片文件")
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise FailException("上传文件大小不能超过 15MB")
    info = await StorageService.put_object(file.filename, content, file.content_type or "image/png")
    await UploadFileService(db).create_upload_file(account=account, name=file.filename, **info)
    return success_json({"image_url": StorageService.get_public_url(info["key"])})
