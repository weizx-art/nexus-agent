from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from utils.deps import get_current_user
from utils.response import success_json, success_message
from models import Account, Segment
from schemas.dataset import (
    CreateDatasetReq,
    CreateDocumentReq,
    CreateSegmentReq,
    DatasetOut,
    DocumentOut,
    DocumentStatusItem,
    RetrievalReq,
    SegmentOut,
    UpdateDatasetReq,
    UpdateDocumentReq,
    UpdateSegmentReq,
)
from services.dataset_service import DatasetService
from services.document_service import DocumentService
from services.segment_service import SegmentService

router = APIRouter(prefix="/datasets", tags=["知识库"])


def _sanitize_error(error: str | None) -> str:
    """清理错误信息，避免暴露内部细节"""
    if not error:
        return ""
    error_lower = error.lower()
    if any(kw in error_lower for kw in ("timeout", "连接", "网络", "服务")):
        return "处理超时，请稍后重试"
    if any(kw in error_lower for kw in ("格式错误", "解析失败", "内容无效")):
        return error
    return "处理失败，请检查文件内容或联系管理员"


def _dataset_out(ds, stats: dict) -> dict:
    return DatasetOut(
        id=str(ds.id), name=ds.name, icon=ds.icon, description=ds.description,
        created_at=ds.created_at, updated_at=ds.updated_at, **stats,
    ).model_dump()


def _document_out(doc, stats: dict) -> dict:
    return DocumentOut(
        id=str(doc.id), dataset_id=str(doc.dataset_id), name=doc.name,
        position=doc.position, character_count=doc.character_count,
        token_count=doc.token_count, enabled=doc.enabled,
        disabled_at=doc.disabled_at, status=doc.status, error=_sanitize_error(doc.error),
        created_at=doc.created_at, updated_at=doc.updated_at, **stats,
    ).model_dump()


def _segment_out(seg: Segment) -> dict:
    return SegmentOut(
        id=str(seg.id), document_id=str(seg.document_id),
        dataset_id=str(seg.dataset_id), content=seg.content,
        position=seg.position, keywords=seg.keywords or [],
        character_count=seg.character_count, token_count=seg.token_count,
        hit_count=seg.hit_count, hash=seg.hash or "",
        enabled=seg.enabled, disabled_at=seg.disabled_at,
        status=seg.status, error=_sanitize_error(seg.error),
        created_at=seg.created_at, updated_at=seg.updated_at,
    ).model_dump()


# ====================== Dataset ======================
@router.get("")
async def list_datasets(
    current_page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search_keyword: str = Query("", alias="search"),
    account: Account = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = DatasetService(db)
    page = await svc.list_datasets(account.id, current_page, page_size, search_keyword)
    all_stats = await svc.batch_dataset_stats([str(d.id) for d in page.items])
    data = [_dataset_out(d, all_stats[str(d.id)]) for d in page.items]
    return success_json({"list": data, "paginator": page.paginator.model_dump()})


@router.post("")
async def create_dataset(req: CreateDatasetReq, account: Account = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ds = await DatasetService(db).create_dataset(account.id, req)
    return success_json({"id": str(ds.id)})


@router.get("/{dataset_id}")
async def get_dataset(dataset_id: str, account: Account = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    svc = DatasetService(db)
    ds = await svc.get_dataset(account.id, dataset_id)
    return success_json(_dataset_out(ds, await svc.dataset_stats(dataset_id)))


@router.patch("/{dataset_id}")
async def update_dataset(dataset_id: str, req: UpdateDatasetReq, account: Account = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await DatasetService(db).update_dataset(account.id, dataset_id, req)
    return success_message("更新知识库成功")


@router.delete("/{dataset_id}")
async def delete_dataset(dataset_id: str, account: Account = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await DatasetService(db).delete_dataset(account.id, dataset_id)
    return success_message("删除知识库成功")


@router.get("/{dataset_id}/queries")
async def dataset_queries(dataset_id: str, account: Account = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await DatasetService(db).recent_queries(account.id, dataset_id)
    return success_json([{"query": r.query, "created_at": r.created_at} for r in rows])


@router.post("/{dataset_id}/retrieval")
async def retrieval(dataset_id: str, req: RetrievalReq, account: Account = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """召回测试：支持 semantic / full_text / hybrid 三种检索策略"""
    return success_json(await DatasetService(db).hit(account.id, dataset_id, req))


# ====================== Document ======================
@router.get("/{dataset_id}/documents")
async def list_documents(
    dataset_id: str,
    current_page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search_keyword: str = Query("", alias="search"),
    account: Account = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = DocumentService(db)
    page = await svc.list_documents(account.id, dataset_id, current_page, page_size, search_keyword)
    all_stats = await svc.batch_doc_stats([str(d.id) for d in page.items])
    data = [_document_out(d, all_stats[str(d.id)]) for d in page.items]
    return success_json({"list": data, "paginator": page.paginator.model_dump()})


@router.post("/{dataset_id}/documents")
async def create_documents(
    dataset_id: str,
    req: CreateDocumentReq,
    background: BackgroundTasks,
    account: Account = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.indexing_service import build_document

    doc_ids, batch = await DocumentService(db).create_documents(
        account.id, dataset_id, req.upload_file_ids,
        process_type=req.process_type, rule=req.rule,
    )
    for doc_id in doc_ids:
        background.add_task(build_document, doc_id)
    return success_json({"documents": doc_ids, "batch": batch})


@router.get("/{dataset_id}/documents/batch/{batch}")
async def documents_status(dataset_id: str, batch: str, account: Account = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await DocumentService(db).documents_by_batch(account.id, dataset_id, batch)
    return success_json([
        DocumentStatusItem(
            id=str(d.id), name=d.name, status=d.status, enabled=d.enabled,
            error=_sanitize_error(d.error),
            processing_started_at=d.processing_started_at,
            parsing_completed_at=d.parsing_completed_at,
            splitting_completed_at=d.splitting_completed_at,
            indexing_completed_at=d.indexing_completed_at,
            completed_at=d.completed_at,
            stopped_at=d.stopped_at,
            created_at=d.created_at,
        ).model_dump()
        for d in rows
    ])


@router.get("/{dataset_id}/documents/{document_id}")
async def get_document(dataset_id: str, document_id: str, account: Account = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    svc = DocumentService(db)
    d = await svc.get_document(account.id, dataset_id, document_id)
    return success_json(_document_out(d, await svc.doc_stats(document_id)))


@router.patch("/{dataset_id}/documents/{document_id}")
async def update_document(
    dataset_id: str,
    document_id: str,
    req: UpdateDocumentReq,
    account: Account = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """部分更新文档（name / enabled 均可选，至少传一个）"""
    svc = DocumentService(db)
    if req.name is not None:
        await svc.update_name(account.id, dataset_id, document_id, req.name)
    if req.enabled is not None:
        await svc.update_enabled(account.id, dataset_id, document_id, req.enabled)
    return success_message("更新文档成功")


@router.delete("/{dataset_id}/documents/{document_id}")
async def delete_document(dataset_id: str, document_id: str, account: Account = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await DocumentService(db).delete_document(account.id, dataset_id, document_id)
    return success_message("删除文档成功")


# ====================== Segment ======================
@router.get("/{dataset_id}/documents/{document_id}/segments")
async def list_segments(
    dataset_id: str, document_id: str,
    current_page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search_keyword: str = Query("", alias="search"),
    account: Account = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    page = await SegmentService(db).list_segments(account.id, dataset_id, document_id, current_page, page_size, search_keyword)
    return success_json({"list": [_segment_out(s) for s in page.items], "paginator": page.paginator.model_dump()})


@router.post("/{dataset_id}/documents/{document_id}/segments")
async def create_segment(dataset_id: str, document_id: str, req: CreateSegmentReq, account: Account = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await SegmentService(db).create_segment(account.id, dataset_id, document_id, req)
    return success_message("创建文档片段成功")


@router.get("/{dataset_id}/documents/{document_id}/segments/{segment_id}")
async def get_segment(dataset_id: str, document_id: str, segment_id: str, account: Account = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return success_json(_segment_out(await SegmentService(db).get_segment(account.id, dataset_id, document_id, segment_id)))


@router.patch("/{dataset_id}/documents/{document_id}/segments/{segment_id}")
async def update_segment(
    dataset_id: str,
    document_id: str,
    segment_id: str,
    req: UpdateSegmentReq,
    account: Account = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """部分更新文档片段（content / keywords / enabled 均可选，至少传一个）"""
    svc = SegmentService(db)
    # enabled 单独处理（可能只改启用状态而不改内容）
    if req.enabled is not None and req.content is None and req.keywords is None:
        await svc.update_enabled(account.id, dataset_id, document_id, segment_id, req.enabled)
        return success_message("更新文档片段启用状态成功")

    # 有内容或关键词更新时，走完整更新流程
    if req.content is not None or req.keywords is not None:
        await svc.update_segment(account.id, dataset_id, document_id, segment_id, req)

    # 如果同时传了 enabled，再单独处理启用状态
    if req.enabled is not None:
        await svc.update_enabled(account.id, dataset_id, document_id, segment_id, req.enabled)

    return success_message("更新文档片段成功")


@router.delete("/{dataset_id}/documents/{document_id}/segments/{segment_id}")
async def delete_segment(dataset_id: str, document_id: str, segment_id: str, account: Account = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await SegmentService(db).delete_segment(account.id, dataset_id, document_id, segment_id)
    return success_message("删除文档片段成功")
