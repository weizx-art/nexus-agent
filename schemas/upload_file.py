from pydantic import BaseModel, ConfigDict


class UploadFileOut(BaseModel):
    """文件上传响应"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    size: int
    extension: str
    mime_type: str
