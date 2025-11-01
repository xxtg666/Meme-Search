from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from typing import Optional
import asyncio
import logging
import os
from datetime import datetime

import config
from models import SessionLocal, MemeImage
from schemas import RemoteFetchRequest, MemeResponse, SearchResponse
from progress import progress_tracker
from tasks import scheduler, fetch_discord_memes, retry_failed_analyses, process_remote_images
from auth import verify_admin_key
from pydantic import BaseModel, Field
from typing import List

# 日志配置（保留原有设置位置与格式）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('meme_search.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# 应用生命周期：启动时启用调度器并注册任务，关闭时停止
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("系统启动，初始化调度器...")
    scheduler.start()
    # 注册定时任务
    scheduler.add_job(fetch_discord_memes, 'interval', minutes=config.FETCH_INTERVAL_MINUTES, id='fetch_discord')
    scheduler.add_job(retry_failed_analyses, 'interval', minutes=config.RETRY_INTERVAL_MINUTES, id='retry_failed')
    # 立即执行一次抓取任务（后台）
    asyncio.create_task(fetch_discord_memes())
    try:
        yield
    finally:
        logger.info("系统关闭，停止调度器...")
        scheduler.shutdown()


app = FastAPI(title="梗图搜索API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=config.UPLOAD_DIR), name="uploads")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
async def root():
    return HTMLResponse(open("index.html", encoding="utf-8").read())


@app.get("/admin")
async def admin():
    return HTMLResponse(open("admin.html", encoding="utf-8").read())


@app.get("/api/search", response_model=SearchResponse)
async def search_memes(
    q: str = Query(..., min_length=1, description="搜索关键词，支持空格分隔多个关键词"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    last_id: Optional[int] = Query(None, description="用于无限滚动的最后一个ID"),
    db = Depends(get_db)
):
    # 由于原实现使用简单的内存过滤（全文拼接匹配），这里保持一致以不改变行为
    session = db
    query = session.query(MemeImage).filter(MemeImage.analysis_status == "success")
    keywords = [keyword.lower().strip() for keyword in q.split() if keyword.strip()]
    all_memes = query.all()
    filtered_memes = []
    for meme in all_memes:
        searchable_text = " ".join([
            (meme.title or "").lower(),
            (meme.description or "").lower(),
            (meme.text_content or "").lower(),
            " ".join(tag.lower() for tag in (meme.tags or []))
        ])
        if all(keyword in searchable_text for keyword in keywords):
            filtered_memes.append(meme)

    filtered_memes.sort(key=lambda x: (x.upload_time, x.id), reverse=True)
    total = len(filtered_memes)
    if last_id:
        last_meme = next((m for m in filtered_memes if m.id == last_id), None)
        if last_meme:
            last_index = filtered_memes.index(last_meme)
            filtered_memes = filtered_memes[last_index + 1:]

    items = filtered_memes[:page_size]
    has_more = len(filtered_memes) > page_size
    results = [
        MemeResponse(
            id=m.id,
            filename=m.filename,
            filepath=m.filepath,
            text_content=m.text_content,
            description=m.description,
            tags=m.tags,
            title=m.title,
            upload_time=m.upload_time,
            discord_url=m.discord_url
        ) for m in items
    ]

    return SearchResponse(total=total, items=results, has_more=has_more)


@app.get("/api/memes", response_model=SearchResponse)
async def list_memes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    last_id: Optional[int] = Query(None, description="用于无限滚动的最后一个ID"),
    sort: str = Query("time", description="排序方式: time(时间) 或 random(随机)"),
    db = Depends(get_db)
):
    session = db
    query = session.query(MemeImage).filter(MemeImage.analysis_status == "success")
    
    total = session.query(MemeImage).filter(MemeImage.analysis_status == "success").count()
    
    if sort == "random":
        # 随机排序：使用数据库的随机函数
        from sqlalchemy import func
        query = query.order_by(func.random())
        memes = query.limit(page_size).all()
        has_more = len(memes) == page_size and total > page_size
    else:
        # 时间排序（默认）
        query = query.order_by(MemeImage.upload_time.desc(), MemeImage.id.desc())
        if last_id:
            last_meme = session.query(MemeImage).filter(MemeImage.id == last_id).first()
            if last_meme:
                query = query.filter((MemeImage.upload_time < last_meme.upload_time) | ((MemeImage.upload_time == last_meme.upload_time) & (MemeImage.id < last_meme.id)))
        memes = query.limit(page_size).all()
        has_more = len(memes) == page_size
    
    results = [
        MemeResponse(
            id=meme.id,
            filename=meme.filename,
            filepath=meme.filepath,
            text_content=meme.text_content,
            description=meme.description,
            tags=meme.tags,
            title=meme.title,
            upload_time=meme.upload_time,
            discord_url=meme.discord_url
        ) for meme in memes
    ]
    return SearchResponse(total=total, items=results, has_more=has_more)


@app.get("/api/memes/{meme_id}", response_model=MemeResponse)
async def get_meme(meme_id: int, db = Depends(get_db)):
    session = db
    meme = session.query(MemeImage).filter(MemeImage.id == meme_id).first()
    if not meme:
        raise HTTPException(status_code=404, detail="梗图不存在")
    return MemeResponse(
        id=meme.id,
        filename=meme.filename,
        filepath=meme.filepath,
        text_content=meme.text_content,
        description=meme.description,
        tags=meme.tags,
        title=meme.title,
        upload_time=meme.upload_time,
        discord_url=meme.discord_url
    )


@app.delete("/api/memes/{meme_id}")
async def delete_meme(meme_id: int, db = Depends(get_db), admin_key = Depends(verify_admin_key)):
    session = db
    meme = session.query(MemeImage).filter(MemeImage.id == meme_id).first()
    if not meme:
        raise HTTPException(status_code=404, detail="梗图不存在")
    file_path = os.path.join(config.UPLOAD_DIR, meme.filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    session.delete(meme)
    session.commit()
    return {"message": "删除成功"}


@app.get("/api/stats")
async def get_stats(db = Depends(get_db)):
    session = db
    total = session.query(MemeImage).count()
    success = session.query(MemeImage).filter(MemeImage.analysis_status == "success").count()
    failed = session.query(MemeImage).filter(MemeImage.analysis_status == "failed").count()
    pending = session.query(MemeImage).filter(MemeImage.analysis_status == "pending").count()
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "pending": pending,
        "last_fetch": datetime.utcnow().isoformat()
    }


@app.get("/api/progress")
async def get_progress():
    return progress_tracker.get_status()


@app.get("/api/trigger-fetch")
async def trigger_fetch(admin_key = Depends(verify_admin_key)):
    if progress_tracker.status == "running":
        return {"error": "已有任务正在运行", "status": "busy"}
    asyncio.create_task(fetch_discord_memes())
    return {"message": "抓取任务已启动", "status": "started"}


@app.get("/api/trigger-retry")
async def trigger_retry(admin_key = Depends(verify_admin_key)):
    if progress_tracker.status == "running":
        return {"error": "已有任务正在运行", "status": "busy"}
    asyncio.create_task(retry_failed_analyses())
    return {"message": "重试任务已启动", "status": "started"}


@app.post("/api/trigger-remote-fetch")
async def remote_fetch(request: RemoteFetchRequest, admin_key = Depends(verify_admin_key)):
    try:
        if not request.image_urls:
            raise HTTPException(status_code=400, detail="图片URL列表不能为空")
        valid_urls = []
        for url in request.image_urls:
            if not url.strip():
                continue
            url = url.strip()
            if not (url.startswith("http://") or url.startswith("https://")):
                continue
            valid_urls.append(url)
        if not valid_urls:
            raise HTTPException(status_code=400, detail="没有找到有效的图片URL")
        logger.info(f"收到远程抓取请求，共 {len(valid_urls)} 个URL")
        asyncio.create_task(process_remote_images(valid_urls))
        return {"status": "success", "message": f"已接收 {len(valid_urls)} 个图片URL，正在后台处理", "total_urls": len(valid_urls)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"远程抓取接口错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


# 管理员API
class MemeUpdateRequest(BaseModel):
    title: str = Field(max_length=30)
    description: str
    text_content: str = ""
    tags: List[str] = Field(min_items=1, max_items=15)


class MemeAdminResponse(BaseModel):
    id: int
    filename: str
    filepath: str
    text_content: str
    description: str
    tags: List[str]
    title: str
    upload_time: datetime
    discord_url: Optional[str] = None
    analysis_status: str


class AdminSearchResponse(BaseModel):
    total: int
    items: List[MemeAdminResponse]
    has_more: bool


@app.get("/api/admin/memes", response_model=AdminSearchResponse)
async def get_admin_memes(
    status: Optional[str] = Query(None, description="筛选状态: success/failed/pending"),
    q: Optional[str] = Query(None, description="搜索关键词"),
    page_size: int = Query(20, ge=1, le=100),
    last_id: Optional[int] = Query(None, description="用于无限滚动的最后一个ID"),
    db = Depends(get_db),
    admin_key = Depends(verify_admin_key)
):
    """管理员查询接口，支持状态筛选和搜索"""
    session = db
    query = session.query(MemeImage)
    
    # 状态筛选
    if status:
        query = query.filter(MemeImage.analysis_status == status)
    
    # 搜索功能
    if q:
        keywords = [keyword.lower().strip() for keyword in q.split() if keyword.strip()]
        all_memes = query.all()
        filtered_memes = []
        for meme in all_memes:
            searchable_text = " ".join([
                (meme.title or "").lower(),
                (meme.description or "").lower(),
                (meme.text_content or "").lower(),
                " ".join(tag.lower() for tag in (meme.tags or []))
            ])
            if all(keyword in searchable_text for keyword in keywords):
                filtered_memes.append(meme)
        
        filtered_memes.sort(key=lambda x: (x.upload_time, x.id), reverse=True)
        total = len(filtered_memes)
        
        if last_id:
            last_meme = next((m for m in filtered_memes if m.id == last_id), None)
            if last_meme:
                last_index = filtered_memes.index(last_meme)
                filtered_memes = filtered_memes[last_index + 1:]
        
        items = filtered_memes[:page_size]
        has_more = len(filtered_memes) > page_size
    else:
        # 无搜索，使用分页查询
        query = query.order_by(MemeImage.upload_time.desc(), MemeImage.id.desc())
        
        if last_id:
            last_meme = session.query(MemeImage).filter(MemeImage.id == last_id).first()
            if last_meme:
                query = query.filter(
                    (MemeImage.upload_time < last_meme.upload_time) | 
                    ((MemeImage.upload_time == last_meme.upload_time) & (MemeImage.id < last_meme.id))
                )
        
        # 计算总数
        count_query = session.query(MemeImage)
        if status:
            count_query = count_query.filter(MemeImage.analysis_status == status)
        total = count_query.count()
        
        items = query.limit(page_size).all()
        has_more = len(items) == page_size
    
    results = [
        MemeAdminResponse(
            id=meme.id,
            filename=meme.filename,
            filepath=meme.filepath,
            text_content=meme.text_content or "",
            description=meme.description,
            tags=meme.tags,
            title=meme.title,
            upload_time=meme.upload_time,
            discord_url=meme.discord_url,
            analysis_status=meme.analysis_status
        ) for meme in items
    ]
    
    return AdminSearchResponse(total=total, items=results, has_more=has_more)


@app.put("/api/admin/memes/{meme_id}")
async def update_meme(meme_id: int, update: MemeUpdateRequest, db = Depends(get_db), admin_key = Depends(verify_admin_key)):
    """更新梗图信息"""
    session = db
    meme = session.query(MemeImage).filter(MemeImage.id == meme_id).first()
    if not meme:
        raise HTTPException(status_code=404, detail="梗图不存在")
    
    meme.title = update.title
    meme.description = update.description
    meme.text_content = update.text_content
    meme.tags = update.tags
    meme.analysis_status = "success"  # 手动编辑后标记为成功
    
    session.commit()
    logger.info(f"更新梗图 {meme_id}: {update.title}")
    return {"message": "更新成功"}


@app.post("/api/admin/memes/{meme_id}/reanalyze")
async def reanalyze_meme(meme_id: int, db = Depends(get_db), admin_key = Depends(verify_admin_key)):
    """重新分析单个梗图"""
    session = db
    meme = session.query(MemeImage).filter(MemeImage.id == meme_id).first()
    if not meme:
        raise HTTPException(status_code=404, detail="梗图不存在")
    
    # 标记为待重试
    meme.analysis_status = "failed"
    meme.retry_count = 0
    session.commit()
    
    # 异步执行重新分析
    asyncio.create_task(retry_failed_analyses())
    logger.info(f"触发重新分析梗图 {meme_id}")
    return {"message": "已加入重新分析队列"}


if __name__ == "__main__":
    import uvicorn
    logger.info(f"启动梗图搜索系统 - {config.API_HOST}:{config.API_PORT}")
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)