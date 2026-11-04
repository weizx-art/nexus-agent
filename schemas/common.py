import math

from pydantic import BaseModel, Field


class Paginator(BaseModel):
    total_page: int = 0
    total_record: int = 0
    current_page: int = 1
    page_size: int = 20


class PageData(BaseModel):
    """分页列表响应"""

    items: list = Field(default_factory=list)
    paginator: Paginator = Field(default_factory=Paginator)


def make_paginator(total: int, current_page: int, page_size: int) -> Paginator:
    return Paginator(
        total_record=total,
        total_page=math.ceil(total / page_size) if page_size else 0,
        current_page=current_page,
        page_size=page_size,
    )
