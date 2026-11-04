from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import KeywordTable, Segment


class KeywordTableService:
    """知识库关键词倒排表服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_keyword_from_dataset_id(self, dataset_id: UUID) -> KeywordTable:
        """获取知识库的关键词倒排表，不存在则创建空表"""
        result = await self.db.execute(
            select(KeywordTable).where(KeywordTable.dataset_id == dataset_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            record = KeywordTable(dataset_id=dataset_id, keyword_table={})
            self.db.add(record)
            await self.db.flush()
        return record

    async def add_keyword_table_from_ids(self, dataset_id: UUID, segment_ids: list[str]):
        """把给定 segment 的关键词合并进倒排表"""
        if not segment_ids:
            return
        record = await self.get_keyword_from_dataset_id(dataset_id)
        table: dict = {k: set(v) for k, v in (record.keyword_table or {}).items()}

        result = await self.db.execute(
            select(Segment.id, Segment.keywords).where(Segment.id.in_(segment_ids))
        )
        for seg_id, keywords in result.all():
            for kw in (keywords or []):
                table.setdefault(kw, set()).add(str(seg_id))

        record.keyword_table = {k: list(v) for k, v in table.items()}
        await self.db.flush()

    async def delete_keyword_table_from_ids(self, dataset_id: UUID, segment_ids: list[str]):
        """从倒排表移除给定 segment 的所有关键词映射，清空的关键词一并删除"""
        if not segment_ids:
            return
        record = await self.get_keyword_from_dataset_id(dataset_id)
        table: dict = dict(record.keyword_table or {})
        ids_to_remove = {str(s) for s in segment_ids}
        empty_keywords = set()

        for kw, ids in table.items():
            ids_set = set(ids)
            if ids_set & ids_to_remove:
                table[kw] = list(ids_set - ids_to_remove)
                if not table[kw]:
                    empty_keywords.add(kw)

        for kw in empty_keywords:
            del table[kw]

        record.keyword_table = table
        await self.db.flush()

    async def search_segment_ids(self, dataset_id: UUID, keywords: list[str]) -> set[str]:
        """根据关键词列表，在倒排表里命中相关 segment_id"""
        if not keywords:
            return set()
        record = await self.get_keyword_from_dataset_id(dataset_id)
        table: dict = record.keyword_table or {}
        result: set[str] = set()
        for kw in keywords:
            if kw in table:
                result.update(table[kw])
        return result
