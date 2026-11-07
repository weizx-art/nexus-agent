"""数据库初始化脚本：重置所有数据并填充完整链路测试数据。

数据链路：Account → Dataset → Document → Segment → Weaviate Vector

运行方式：python scripts/seed.py
"""
import asyncio
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# 知识库名称列表
DATASET_NAMES = [
    "产品使用手册", "客户服务FAQ", "技术文档库", "市场营销资料", "人力资源政策",
    "财务报销指南", "行政管理制度", "安全操作规范", "质量控制标准", "项目管理模板",
    "数据分析报告", "用户研究资料", "竞品分析文档", "品牌设计规范", "销售话术库",
    "培训教材", "法律法规汇编", "行业标准文档", "内部知识库", "外部参考资料",
    "会议纪要归档", "周报月报合集", "OKR目标管理", "流程规范文档", "应急预案手册",
    "设备操作指南", "维护保养手册", "供应链资料", "合作伙伴信息", "客户案例库",
    "市场调研报告", "产品需求文档", "技术架构说明", "API接口文档", "测试用例库",
    "运维手册", "安全合规文档", "隐私政策说明", "用户协议条款", "开源项目文档",
    "行业趋势分析", "竞争对手情报", "战略规划文档", "年度总结报告", "新员工入职指南",
    "团队协作规范", "代码审查标准", "发布流程说明", "故障排查手册", "知识图谱资料",
]

# 文档模板（每个知识库会创建这些文档）
DOCUMENT_TEMPLATES = [
    "{name} - 概述",
    "{name} - 详细说明",
    "{name} - 常见问题",
]

# 片段内容模板（每个文档会创建5个片段）
SEGMENT_CONTENTS = [
    "这是关于{doc_name}的第一部分内容。主要介绍了基本概念和核心要点，帮助读者快速了解相关知识框架。在实际应用中，这些基础知识非常重要，能够为后续深入学习奠定坚实基础。",
    "第二部分重点讲解了{doc_name}的实施方法和操作步骤。通过详细的流程说明，确保每个环节都能准确执行。建议按照顺序逐步完成，避免遗漏关键步骤。",
    "本章节分析了{doc_name}在实际场景中的应用案例。通过真实案例的展示，帮助读者理解理论知识如何转化为实践成果。每个案例都包含了背景、实施过程和效果评估。",
    "这里总结了{doc_name}的常见问题和解决方案。针对用户反馈的高频问题，提供了详细的解答和操作指导。如果遇到问题，可以先查阅本部分寻找答案。",
    "最后一部分提供了{doc_name}的进阶学习资源和参考资料。包括相关文档、教程、视频等，帮助有深入需求的用户继续学习。持续学习是掌握知识的关键。",
]


async def main():
    from core.database import Base, engine, AsyncSessionLocal
    from models import Account, Dataset, Document, Segment
    from utils.security import generate_password_salt_and_hash
    from services.embedding_service import EmbeddingService
    from services.vector_service import VectorService

    logger.info("=" * 60)
    logger.info("开始重置数据库并生成完整链路测试数据...")
    logger.info("=" * 60)

    # 1. 重置 PostgreSQL
    logger.info("[1/5] 重置 PostgreSQL 数据库...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✓ 数据库表已重建")

    # 2. 清除 Weaviate
    logger.info("[2/5] 清除 Weaviate 向量数据...")
    try:
        collection_name = "Dataset"
        client = VectorService.client()
        logger.info("Weaviate 客户端已连接")
        if client.collections.exists(collection_name):
            logger.info("删除现有集合...")
            client.collections.delete(collection_name)
            logger.info("集合已删除")
        logger.info("创建新集合...")
        VectorService._ensure_collection()
        logger.info("✓ Weaviate 集合已重建")
    except Exception as e:
        logger.error(f"✗ Weaviate 操作失败: {e}", exc_info=True)
        return

    # 3. 创建管理员账号
    logger.info("[3/5] 创建管理员账号...")
    async with AsyncSessionLocal() as db:
        salt, hashed = generate_password_salt_and_hash("admin123")
        admin = Account(
            username="admin",
            name="管理员",
            password_salt=salt,
            password=hashed,
            avatar="",
        )
        db.add(admin)
        await db.commit()
        await db.refresh(admin)
        logger.info(f"✓ 管理员账号: admin / admin123 (ID: {admin.id})")

        # 4. 创建知识库、文档、片段
        logger.info("[4/5] 生成知识库完整数据链路...")
        total_datasets = len(DATASET_NAMES)
        total_documents = 0
        total_segments = 0

        for ds_idx, ds_name in enumerate(DATASET_NAMES, 1):
            # 创建 Dataset
            dataset = Dataset(
                account_id=admin.id,
                name=ds_name,
                description=f"这是{ds_name}的知识库，包含相关的文档和资料。",
                icon="",
            )
            db.add(dataset)
            await db.flush()

            # 为每个知识库创建 3 个文档
            for doc_idx, doc_template in enumerate(DOCUMENT_TEMPLATES, 1):
                doc_name = doc_template.format(name=ds_name)
                document = Document(
                    account_id=admin.id,
                    dataset_id=dataset.id,
                    name=doc_name,
                    position=doc_idx,
                    character_count=sum(len(s.format(doc_name=doc_name)) for s in SEGMENT_CONTENTS),
                    token_count=0,
                    status="complete",
                    enabled=True,
                    processing_started_at=datetime.now(),
                    parsing_completed_at=datetime.now(),
                    splitting_completed_at=datetime.now(),
                    indexing_completed_at=datetime.now(),
                    completed_at=datetime.now(),
                )
                db.add(document)
                await db.flush()
                total_documents += 1

                # 为每个文档创建 5 个片段
                for seg_idx, seg_template in enumerate(SEGMENT_CONTENTS, 1):
                    seg_content = seg_template.format(doc_name=doc_name)
                    node_id = uuid.uuid4()
                    segment = Segment(
                        account_id=admin.id,
                        dataset_id=dataset.id,
                        document_id=document.id,
                        node_id=node_id,
                        position=seg_idx,
                        content=seg_content,
                        character_count=len(seg_content),
                        token_count=len(seg_content) // 2,  # 粗略估计
                        keywords=[ds_name, doc_name.split(" - ")[-1] if " - " in doc_name else doc_name],
                        hash=uuid.uuid4().hex,
                        hit_count=0,
                        enabled=True,
                        status="complete",
                        processing_started_at=datetime.now(),
                        indexing_completed_at=datetime.now(),
                        completed_at=datetime.now(),
                    )
                    db.add(segment)
                    await db.flush()
                    total_segments += 1

                    # 生成 embedding 并存入 Weaviate
                    try:
                        vector = await EmbeddingService.embed_query(seg_content)
                        await VectorService.add_segment(
                            node_id=str(node_id),
                            text=seg_content,
                            vector=vector,
                            props={
                                "account_id": str(admin.id),
                                "dataset_id": str(dataset.id),
                                "document_id": str(document.id),
                                "segment_id": str(segment.id),
                                "document_enabled": True,
                                "segment_enabled": True,
                            },
                        )
                    except Exception as e:
                        logger.warning(f"片段 {segment.id} 向量化失败: {e}")

            if ds_idx % 10 == 0:
                logger.info(f"  进度: {ds_idx}/{total_datasets} 个知识库")

        await db.commit()
        logger.info(f"✓ 已创建 {total_datasets} 个知识库")
        logger.info(f"✓ 已创建 {total_documents} 个文档")
        logger.info(f"✓ 已创建 {total_segments} 个片段")
        logger.info(f"✓ 已生成 {total_segments} 条向量数据")

    logger.info("[5/5] 初始化完成！")
    logger.info("=" * 60)
    logger.info("数据概览:")
    logger.info(f"  - 管理员账号: admin / admin123")
    logger.info(f"  - 知识库数量: {total_datasets}")
    logger.info(f"  - 文档数量: {total_documents}")
    logger.info(f"  - 片段数量: {total_segments}")
    logger.info(f"  - 向量数量: {total_segments}")
    logger.info("=" * 60)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
