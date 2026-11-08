import re
import uuid as _uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from entity.dataset_entity import RetrievalStrategy


# ---------------- 知识库 Dataset ----------------
class CreateDatasetReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="知识库名称")
    icon: str = Field(default="", description="图标 URL")
    description: Optional[str] = Field(default="", max_length=2000, description="描述")

    @field_validator("icon")
    @classmethod
    def _validate_icon(cls, v: str) -> str:
        if v and not re.match(r"^https?://", v):
            raise ValueError("图标必须是合法的 URL 地址")
        return v


class UpdateDatasetReq(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    icon: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("icon")
    @classmethod
    def _validate_icon(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r"^https?://", v):
            raise ValueError("图标必须是合法的 URL 地址")
        return v

    @model_validator(mode="after")
    def _at_least_one_field(self):
        if self.name is None and self.icon is None and self.description is None:
            raise ValueError("至少需要提供一个更新字段")
        return self


class DatasetOut(BaseModel):
    id: str
    name: str
    icon: str
    description: str
    document_count: int = 0
    hit_count: int = 0
    character_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None


# ---------------- 文档 Document ----------------
class CreateDocumentReq(BaseModel):
    upload_file_ids: list[str] = Field(..., description="上传文件 id 列表")
    process_type: str = Field(default="automatic", description="处理模式: automatic / custom")
    rule: Optional[dict] = Field(default=None, description="处理规则（custom 模式必填）")

    @field_validator("upload_file_ids")
    @classmethod
    def _validate_ids(cls, v: list[str]) -> list[str]:
        if not v or len(v) > 10:
            raise ValueError("文档数量须在 1-10 之间")
        deduped = list(dict.fromkeys(v))
        for uid in deduped:
            try:
                _uuid.UUID(uid)
            except ValueError:
                raise ValueError(f"文件 id 格式不合法: {uid}")
        return deduped


class UpdateDocumentReq(BaseModel):
    """文档部分更新请求（name 和 enabled 均为可选，至少传一个）"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=100, description="文档名称")
    enabled: Optional[bool] = Field(default=None, description="是否启用")

    @model_validator(mode="after")
    def _at_least_one_field(self):
        if self.name is None and self.enabled is None:
            raise ValueError("至少需要提供 name 或 enabled 中的一个")
        return self


class DocumentOut(BaseModel):
    id: str
    dataset_id: Optional[str] = None
    name: str
    position: int = 0
    character_count: int = 0
    token_count: int = 0
    enabled: bool = False
    disabled_at: Optional[datetime] = None
    status: str = ""
    error: str = ""
    segment_count: int = 0
    hit_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None


class DocumentStatusItem(BaseModel):
    id: str
    name: str
    status: str
    enabled: bool
    error: str = ""
    processing_started_at: Optional[datetime] = None
    parsing_completed_at: Optional[datetime] = None
    splitting_completed_at: Optional[datetime] = None
    indexing_completed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


# ---------------- 片段 Segment ----------------
class CreateSegmentReq(BaseModel):
    content: str = Field(..., min_length=1, description="片段内容")
    keywords: Optional[list[str]] = Field(default=None, description="关键词")

    @field_validator("keywords")
    @classmethod
    def _validate_keywords(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        if len(v) > 10:
            raise ValueError("关键词数量不能超过 10 个")
        for kw in v:
            if not isinstance(kw, str):
                raise ValueError("关键词必须是字符串")
        return list(dict.fromkeys(v))


class UpdateSegmentReq(BaseModel):
    """片段部分更新请求（content/keywords/enabled 均为可选，至少传一个）"""

    content: Optional[str] = Field(default=None, min_length=1, description="片段内容")
    keywords: Optional[list[str]] = Field(default=None, description="关键词")
    enabled: Optional[bool] = Field(default=None, description="是否启用")

    @field_validator("keywords")
    @classmethod
    def _validate_keywords(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        if len(v) > 10:
            raise ValueError("关键词数量不能超过 10 个")
        for kw in v:
            if not isinstance(kw, str):
                raise ValueError("关键词必须是字符串")
        return list(dict.fromkeys(v))

    @model_validator(mode="after")
    def _at_least_one_field(self):
        if self.content is None and self.keywords is None and self.enabled is None:
            raise ValueError("至少需要提供一个更新字段")
        return self


class SegmentOut(BaseModel):
    id: str
    document_id: Optional[str] = None
    dataset_id: Optional[str] = None
    position: int = 0
    content: str = ""
    keywords: list[str] = []
    character_count: int = 0
    token_count: int = 0
    hit_count: int = 0
    hash: str = ""
    enabled: bool = False
    disabled_at: Optional[datetime] = None
    status: str = ""
    error: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------- 召回测试 Retrieval ----------------
class RetrievalReq(BaseModel):
    query: str = Field(..., min_length=1, max_length=200, description="检索 query")
    retrieval_strategy: str = Field(
        default=RetrievalStrategy.HYBRID,
        description="检索策略: semantic / full_text / hybrid",
    )
    k: int = Field(default=4, ge=1, le=10, description="最大召回数量")
    score: float = Field(default=0.0, ge=0, le=0.99, description="最小匹配度阈值")

    @field_validator("retrieval_strategy")
    @classmethod
    def _validate_strategy(cls, v: str) -> str:
        valid = {item.value for item in RetrievalStrategy}
        if v not in valid:
            raise ValueError(f"检索策略必须是 {valid} 之一")
        return v
