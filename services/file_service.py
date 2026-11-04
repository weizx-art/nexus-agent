import asyncio
import os
import re
import tempfile

from models import UploadFile
from services.storage_service import StorageService


def clean_extra_text(text: str) -> str:
    text = re.sub(r"<\|", "<", text)
    text = re.sub(r"\|>", ">", text)
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
    return text


class FileExtractor:
    """文件提取器：从 MinIO 下载文件并解析为纯文本。"""

    @staticmethod
    async def extract(upload_file: UploadFile) -> str:
        """下载并解析上传文件，返回纯文本"""
        with tempfile.TemporaryDirectory() as tmp:
            local_path = os.path.join(tmp, os.path.basename(upload_file.key))
            await StorageService.download_file(upload_file.key, local_path)
            return await asyncio.to_thread(FileExtractor._load, local_path)

    @staticmethod
    def _load(file_path: str) -> str:
        try:
            from langchain_unstructured import UnstructuredLoader

            loader = UnstructuredLoader(file_path)
            docs = loader.load()
            text = "\n\n".join(d.page_content for d in docs)
        except (ImportError, FileNotFoundError, OSError, ValueError):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        return clean_extra_text(text)
