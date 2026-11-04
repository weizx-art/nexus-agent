import hashlib
import uuid
from datetime import datetime

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from core.config import settings
from utils.exception import FailException

ALLOWED_FILE = ["txt", "csv", "xls", "xlsx", "doc", "docx", "pdf", "md", "markdown", "html", "htm"]
ALLOWED_IMAGE = ["jpg", "jpeg", "png", "gif", "webp", "svg"]

MAX_FILE_SIZE = 15 * 1024 * 1024  # 15MB


class StorageService:
    """MinIO 对象存储（异步）"""

    _session = None

    @classmethod
    def _get_session(cls) -> aioboto3.Session:
        if cls._session is None:
            cls._session = aioboto3.Session(
                aws_access_key_id=settings.MINIO_ACCESS_KEY,
                aws_secret_access_key=settings.MINIO_SECRET_KEY,
            )
        return cls._session

    @classmethod
    def _client_kwargs(cls) -> dict:
        return dict(
            endpoint_url=settings.MINIO_ENDPOINT_URL,
            config=Config(
                proxies={"http": None, "https": None},
                connect_timeout=5,
                read_timeout=10,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

    @classmethod
    def _bucket(cls) -> str:
        return settings.MINIO_BUCKET

    @classmethod
    async def put_object(cls, filename: str, content: bytes, mime_type: str) -> dict:
        """上传文件到 MinIO，返回 {key, size, extension, mime_type, hash}"""
        if len(content) > MAX_FILE_SIZE:
            raise FailException("上传文件大小不能超过 15MB")

        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if extension not in (ALLOWED_FILE + ALLOWED_IMAGE):
            raise FailException(f".{extension} 文件类型不允许上传")

        now = datetime.now()
        key = f"{now.year}/{now.month:02d}/{now.day}/{uuid.uuid4()}.{extension}"

        try:
            async with cls._get_session().client("s3", **cls._client_kwargs()) as client:
                await client.put_object(
                    Bucket=cls._bucket(), Key=key, Body=content, ContentType=mime_type
                )
        except ClientError as e:
            raise FailException("上传文件失败，请稍后重试") from e

        return {
            "key": key,
            "size": len(content),
            "extension": extension,
            "mime_type": mime_type,
            "hash": hashlib.sha3_256(content).hexdigest(),
        }

    @classmethod
    def get_public_url(cls, key: str) -> str:
        """公开桶静态访问地址"""
        return f"{settings.MINIO_ENDPOINT_URL.rstrip('/')}/{cls._bucket()}/{key}"

    @classmethod
    async def download_file(cls, key: str, target_path: str):
        """下载 MinIO 文件到本地路径"""
        async with cls._get_session().client("s3", **cls._client_kwargs()) as client:
            await client.download_file(Bucket=cls._bucket(), Key=key, Filename=target_path)
