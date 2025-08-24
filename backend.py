from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, JSON, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime, timedelta
import os
import hashlib
import json
import aiofiles
from pathlib import Path
import httpx
from contextlib import asynccontextmanager
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import re
import base64
import logging
from collections import deque

# 导入配置
import config

# 配置代理
proxies = {}
if config.PROXY_URL:
    proxies = {
        "http://": config.PROXY_URL,
        "https://": config.PROXY_URL,
    }

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('meme_search.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 数据模型
Base = declarative_base()

class MemeImage(Base):
    __tablename__ = "meme_images"
    
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, unique=True, index=True)
    filepath = Column(String)
    text_content = Column(Text, nullable=True)
    description = Column(Text)
    tags = Column(JSON)
    title = Column(Text)
    upload_time = Column(DateTime, default=datetime.utcnow)
    file_hash = Column(String, unique=True)
    discord_url = Column(String, nullable=True)  # Discord消息链接
    analysis_status = Column(String, default="pending")  # pending, success, failed
    retry_count = Column(Integer, default=0)
    last_retry = Column(DateTime, nullable=True)

# Pydantic模型
class MemeAnalysis(BaseModel):
    text_content: str = ""
    description: str
    tags: List[str] = Field(min_items=5, max_items=15)
    title: str = Field(max_length=30)
    
    @field_validator('description')
    def description_not_empty(cls, v):
        if not v.strip():
            raise ValueError('描述不能为空')
        return v
    
    @field_validator('title')
    def title_not_empty(cls, v):
        if not v.strip():
            raise ValueError('标题不能为空')
        return v

class RemoteFetchRequest(BaseModel):
    image_urls: List[str] = Field(description="图片直链列表")

class MemeResponse(BaseModel):
    id: int
    filename: str
    filepath: str
    text_content: str
    description: str
    tags: List[str]
    title: str
    upload_time: datetime
    discord_url: Optional[str] = None

class SearchResponse(BaseModel):
    total: int
    items: List[MemeResponse]
    has_more: bool

# 确保上传目录存在
Path(config.UPLOAD_DIR).mkdir(exist_ok=True)

# 数据库设置
engine = create_engine(config.DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

# 全局调度器
scheduler = AsyncIOScheduler()

# 进度跟踪
class ProgressTracker:
    def __init__(self):
        self.current_task = None
        self.total_items = 0
        self.processed_items = 0
        self.status = "idle"
        self.logs = deque(maxlen=100)  # 保留最近100条日志
        self.start_time = None
        self.errors = []
    
    def start_task(self, task_name, total=0):
        self.current_task = task_name
        self.total_items = total
        self.processed_items = 0
        self.status = "running"
        self.start_time = datetime.utcnow()
        self.errors = []
        log_msg = f"开始任务: {task_name}"
        if total > 0:
            log_msg += f" (共 {total} 项)"
        self.add_log(log_msg)
        logger.info(log_msg)
    
    def update_progress(self, processed=None, message=None):
        if processed is not None:
            self.processed_items = processed
        if message:
            self.add_log(message)
            logger.info(f"[{self.current_task}] {message}")
    
    def add_error(self, error_msg):
        self.errors.append(error_msg)
        self.add_log(f"错误: {error_msg}")
        logger.error(f"[{self.current_task}] {error_msg}")
    
    def complete_task(self):
        duration = (datetime.utcnow() - self.start_time).total_seconds() if self.start_time else 0
        log_msg = f"任务完成: {self.current_task} (耗时 {duration:.1f}秒)"
        if self.errors:
            log_msg += f", {len(self.errors)} 个错误"
        self.add_log(log_msg)
        logger.info(log_msg)
        self.status = "idle"
        self.current_task = None
    
    def add_log(self, message):
        self.logs.append({
            "time": datetime.utcnow().isoformat(),
            "message": message
        })
    
    def get_status(self):
        return {
            "status": self.status,
            "current_task": self.current_task,
            "total_items": self.total_items,
            "processed_items": self.processed_items,
            "progress_percent": (self.processed_items / self.total_items * 100) if self.total_items > 0 else 0,
            "errors": len(self.errors),
            "logs": list(self.logs)
        }

progress_tracker = ProgressTracker()

# 创建FastAPI应用
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时的操作
    logger.info("系统启动，初始化调度器...")
    scheduler.start()
    # 启动定时任务
    scheduler.add_job(fetch_discord_memes, 'interval', minutes=config.FETCH_INTERVAL_MINUTES, id='fetch_discord')
    scheduler.add_job(retry_failed_analyses, 'interval', minutes=config.RETRY_INTERVAL_MINUTES, id='retry_failed')
    # 立即执行一次
    logger.info("启动时执行一次抓取任务...")
    asyncio.create_task(fetch_discord_memes())
    yield
    # 关闭时的操作
    logger.info("系统关闭，停止调度器...")
    scheduler.shutdown()

app = FastAPI(title="梗图搜索API", version="2.0.0", lifespan=lifespan)

# CORS设置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件服务
app.mount("/uploads", StaticFiles(directory=config.UPLOAD_DIR), name="uploads")

# 依赖注入
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Discord相关函数
def parse_discord_url(url: str) -> tuple:
    """解析Discord URL，返回(server_id, channel_id, thread_id)"""
    pattern = r'https://discord\.com/channels/(\d+)/(\d+)(?:/threads/(\d+))?'
    match = re.match(pattern, url)
    if match:
        return match.groups()
    return None, None, None

async def download_discord_images(discord_url: str) -> List[str]:
    """从Discord帖子下载所有图片"""
    server_id, channel_id, thread_id = parse_discord_url(discord_url)
    if not all([server_id, channel_id]):
        logger.warning(f"无效的Discord URL: {discord_url}")
        return []
    
    # 使用thread_id如果存在，否则使用channel_id
    message_channel_id = thread_id if thread_id else channel_id
    logger.info(f"开始从Discord频道下载图片: {message_channel_id}")
    
    saved_files = []
    
    async with httpx.AsyncClient(proxies=proxies) as client:
        try:
            headers = {
                "Authorization": f"Bot {config.DISCORD_BOT_TOKEN}"
            }
            
            # 获取所有消息（分页）
            all_messages = []
            before = None
            page = 0
            
            while True:
                page += 1
                logger.info(f"获取第 {page} 页消息...")
                
                params = {"limit": 100}
                if before:
                    params["before"] = before
                
                response = await client.get(
                    f"https://discord.com/api/v10/channels/{message_channel_id}/messages",
                    headers=headers,
                    params=params
                )
                
                if response.status_code != 200:
                    error_msg = f"Discord API错误: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    progress_tracker.add_error(error_msg)
                    break
                
                messages = response.json()
                
                if not messages:
                    # 没有更多消息了
                    break
                
                all_messages.extend(messages)
                logger.info(f"第 {page} 页获取到 {len(messages)} 条消息，总计 {len(all_messages)} 条")
                
                # 更新进度
                progress_tracker.update_progress(
                    message=f"获取消息中... 已获取 {len(all_messages)} 条消息"
                )
                
                # 设置下一页的before参数（最后一条消息的ID）
                before = messages[-1]["id"]
                
                # 如果返回的消息少于100条，说明已经到底了
                if len(messages) < 100:
                    break
                
                # 添加延迟避免速率限制
                await asyncio.sleep(0.5)
            
            logger.info(f"共获取到 {len(all_messages)} 条消息")
            
            # 统计图片数量
            total_images = sum(
                len([a for a in msg.get("attachments", []) 
                    if a.get("content_type", "").startswith("image/")])
                for msg in all_messages
            )
            logger.info(f"发现 {total_images} 张图片")
            
            if total_images == 0:
                progress_tracker.update_progress(message="未发现图片")
                return []
            
            # 提取并下载所有图片附件
            image_count = 0
            
            for message in all_messages:
                for attachment in message.get("attachments", []):
                    if attachment.get("content_type", "").startswith("image/"):
                        image_count += 1
                        progress_tracker.update_progress(
                            message=f"下载图片 {image_count}/{total_images}: {attachment['filename']}"
                        )
                        
                        try:
                            # 下载图片
                            img_response = await client.get(attachment["url"])
                            if img_response.status_code == 200:
                                # 生成文件名
                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                file_ext = attachment["filename"].split(".")[-1]
                                filename = f"discord_{timestamp}_{attachment['id']}.{file_ext}"
                                filepath = os.path.join(config.UPLOAD_DIR, filename)
                                
                                # 保存文件
                                async with aiofiles.open(filepath, 'wb') as f:
                                    await f.write(img_response.content)
                                
                                saved_files.append(filename)
                                logger.info(f"保存图片: {filename}")
                            else:
                                error_msg = f"下载图片失败: {attachment['filename']} - {img_response.status_code}"
                                logger.error(error_msg)
                                progress_tracker.add_error(error_msg)
                                
                        except Exception as e:
                            error_msg = f"下载单个图片错误: {attachment['filename']} - {str(e)}"
                            logger.error(error_msg)
                            progress_tracker.add_error(error_msg)
                            continue
                        
                        # 添加小延迟避免请求过快
                        await asyncio.sleep(0.1)
            
            logger.info(f"成功下载 {len(saved_files)} 张图片")
            return saved_files
            
        except Exception as e:
            error_msg = f"下载Discord图片错误: {str(e)}"
            logger.error(error_msg, exc_info=True)
            progress_tracker.add_error(error_msg)
            return []

# 辅助函数
def calculate_file_hash(file_path: str) -> str:
    """计算文件的MD5哈希值"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

async def download_remote_image(image_url: str) -> Optional[str]:
    """下载远程图片并保存到本地"""
    try:
        async with httpx.AsyncClient(proxies=proxies) as client:
            response = await client.get(image_url, timeout=30.0)
            if response.status_code != 200:
                logger.error(f"下载图片失败: {image_url} - HTTP {response.status_code}")
                return None
            
            # 从URL或Content-Type推断文件扩展名
            file_ext = "jpg"  # 默认扩展名
            content_type = response.headers.get("content-type", "")
            if "png" in content_type.lower():
                file_ext = "png"
            elif "gif" in content_type.lower():
                file_ext = "gif"
            elif "webp" in content_type.lower():
                file_ext = "webp"
            else:
                # 尝试从URL获取扩展名
                url_ext = image_url.split(".")[-1].lower()
                if url_ext in ["jpg", "jpeg", "png", "gif", "webp"]:
                    file_ext = url_ext
            
            # 生成唯一文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            url_hash = hashlib.md5(image_url.encode()).hexdigest()[:8]
            filename = f"remote_{timestamp}_{url_hash}.{file_ext}"
            filepath = os.path.join(config.UPLOAD_DIR, filename)
            
            # 保存文件
            async with aiofiles.open(filepath, 'wb') as f:
                await f.write(response.content)
            
            logger.info(f"成功下载远程图片: {filename}")
            return filename
            
    except Exception as e:
        logger.error(f"下载远程图片错误: {image_url} - {str(e)}")
        return None

async def process_remote_images(image_urls: List[str]):
    """处理远程图片列表（后台任务）"""
    progress_tracker.start_task("远程图片抓取", len(image_urls))
    db = SessionLocal()
    
    try:
        # 读取AI分析提示词
        with open("prompt.md", "r", encoding="utf-8") as f:
            prompt_content = f.read()
        
        success_count = 0
        duplicate_count = 0
        error_count = 0
        
        for idx, image_url in enumerate(image_urls, 1):
            progress_tracker.update_progress(
                processed=idx,
                message=f"处理远程图片 {idx}/{len(image_urls)}: {image_url[:50]}..."
            )
            
            try:
                # 下载图片
                filename = await download_remote_image(image_url)
                if not filename:
                    error_count += 1
                    continue
                
                file_path = os.path.join(config.UPLOAD_DIR, filename)
                file_hash = calculate_file_hash(file_path)
                
                # 检查是否已存在
                existing = db.query(MemeImage).filter(MemeImage.file_hash == file_hash).first()
                if existing:
                    os.remove(file_path)  # 删除重复文件
                    duplicate_count += 1
                    logger.info(f"跳过重复图片: {filename}")
                    continue
                
                # 尝试分析图片
                try:
                    analysis = await analyze_image_with_ai(file_path, prompt_content)
                    status = "success"
                except Exception as e:
                    # 分析失败，使用默认数据
                    logger.warning(f"图片分析失败: {filename} - {str(e)}")
                    analysis = MemeAnalysis(
                        text_content="",
                        description="分析中...",
                        tags=["待分析", "梗图", "远程", "未处理", "自动抓取"],
                        title="待分析"
                    )
                    status = "failed"
                
                # 保存到数据库
                db_meme = MemeImage(
                    filename=filename,
                    filepath=f"/uploads/{filename}",
                    text_content=analysis.text_content,
                    description=analysis.description,
                    tags=analysis.tags,
                    title=analysis.title,
                    file_hash=file_hash,
                    discord_url=image_url,  # 记录原始URL
                    analysis_status=status
                )
                
                db.add(db_meme)
                db.commit()
                success_count += 1
                
            except Exception as e:
                error_count += 1
                error_msg = f"处理远程图片错误: {image_url} - {str(e)}"
                logger.error(error_msg)
                progress_tracker.add_error(error_msg)
                continue
        
        progress_tracker.update_progress(
            message=f"远程抓取完成: 成功 {success_count}, 重复 {duplicate_count}, 错误 {error_count}"
        )
        progress_tracker.complete_task()
        
    except Exception as e:
        error_msg = f"处理远程图片任务错误: {str(e)}"
        logger.error(error_msg, exc_info=True)
        progress_tracker.add_error(error_msg)
        progress_tracker.complete_task()
    finally:
        db.close()

async def analyze_image_with_ai(image_path: str, prompt_content: str) -> MemeAnalysis:
    """调用AI API分析图片"""
    if not config.OPENAI_API_KEY:
        # 如果没有配置API密钥，返回模拟数据
        logger.info(f"使用模拟数据分析图片: {image_path}")
        return MemeAnalysis(
            text_content="示例文字内容",
            description="这是一个示例梗图，展示了一个有趣的网络表情包。图片中包含了搞笑的元素和网络流行文化。",
            tags=["示例", "表情包", "搞笑", "网络梗", "测试"],
            title="示例梗图"
        )
    
    # 实际调用OpenAI API的代码
    async with httpx.AsyncClient(proxies=proxies) as client:
        try:
            logger.info(f"开始AI分析图片: {image_path}")
            # 读取图片并转换为base64
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            
            # 在prompt后面附上当前时间
            current_time = datetime.utcnow().strftime("%Y年%m月%d日 %H:%M:%S UTC")
            prompt_with_time = f"{prompt_content}\n\n当前时间：{current_time}"
            
            response = await client.post(
                f"{config.OPENAI_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": config.OPENAI_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": prompt_with_time
                        },
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "现在，请严格按照以上规范分析提供的图片，并直接输出JSON结果，不包含任何额外说明。"
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{base64_image}"
                                    }
                                }
                            ]
                        }
                    ]
                },
                timeout=60.0
            )
            
            if response.status_code != 200:
                raise Exception(f"API返回错误: {response.status_code}")
            
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            # 清理可能的markdown代码块标记
            content = content.strip()
            if content.startswith('```json'):
                content = content[7:]
            elif content.startswith('```'):
                content = content[3:]
            if content.endswith('```'):
                content = content[:-3]
            content = content.strip()
            
            # 解析JSON响应
            analysis_data = json.loads(content)
            logger.info(f"AI分析成功: {image_path}")
            return MemeAnalysis(**analysis_data)
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析错误: {str(e)}, 原始内容: {content[:200]}...")
            raise Exception(f"AI返回的JSON格式错误: {str(e)}")
        except Exception as e:
            logger.error(f"AI分析错误: {str(e)}")
            raise

# 定时任务
async def fetch_discord_memes():
    """定时抓取Discord梗图"""
    if not os.path.exists(config.MEMES_FILE):
        logger.warning(f"文件不存在: {config.MEMES_FILE}")
        return
    
    progress_tracker.start_task("Discord梗图抓取")
    db = SessionLocal()
    
    try:
        # 读取Discord链接
        with open(config.MEMES_FILE, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip()]
        
        logger.info(f"读取到 {len(urls)} 个Discord链接")
        progress_tracker.update_progress(message=f"读取到 {len(urls)} 个Discord链接")
        
        # 读取AI分析提示词
        with open("prompt.md", "r", encoding="utf-8") as f:
            prompt_content = f.read()
        
        total_new_images = 0
        total_duplicates = 0
        
        for idx, discord_url in enumerate(urls, 1):
            progress_tracker.update_progress(
                message=f"处理链接 {idx}/{len(urls)}: {discord_url}"
            )
            
            # 下载图片
            filenames = await download_discord_images(discord_url)
            
            for filename in filenames:
                file_path = os.path.join(config.UPLOAD_DIR, filename)
                file_hash = calculate_file_hash(file_path)
                
                # 检查是否已存在
                existing = db.query(MemeImage).filter(MemeImage.file_hash == file_hash).first()
                if existing:
                    os.remove(file_path)  # 删除重复文件
                    total_duplicates += 1
                    logger.info(f"跳过重复图片: {filename}")
                    continue
                
                # 尝试分析图片
                progress_tracker.update_progress(
                    message=f"分析图片: {filename}"
                )
                
                try:
                    analysis = await analyze_image_with_ai(file_path, prompt_content)
                    status = "success"
                except Exception as e:
                    # 分析失败，使用默认数据
                    logger.warning(f"图片分析失败: {filename} - {str(e)}")
                    analysis = MemeAnalysis(
                        text_content="",
                        description="分析中...",
                        tags=["待分析", "梗图", "Discord", "未处理", "自动抓取"],
                        title="待分析"
                    )
                    status = "failed"
                
                # 保存到数据库
                db_meme = MemeImage(
                    filename=filename,
                    filepath=f"/uploads/{filename}",
                    text_content=analysis.text_content,
                    description=analysis.description,
                    tags=analysis.tags,
                    title=analysis.title,
                    file_hash=file_hash,
                    discord_url=discord_url,
                    analysis_status=status
                )
                
                db.add(db_meme)
                db.commit()
                total_new_images += 1
                
        progress_tracker.update_progress(
            message=f"抓取完成: 新增 {total_new_images} 张图片, 跳过 {total_duplicates} 张重复图片"
        )
        progress_tracker.complete_task()
        
    except Exception as e:
        error_msg = f"抓取Discord梗图错误: {str(e)}"
        logger.error(error_msg, exc_info=True)
        progress_tracker.add_error(error_msg)
        progress_tracker.complete_task()
    finally:
        db.close()

async def retry_failed_analyses():
    """重试失败的分析"""
    progress_tracker.start_task("重试失败分析")
    db = SessionLocal()
    
    try:
        # 查找需要重试的图片
        failed_memes = db.query(MemeImage).filter(
            MemeImage.analysis_status == "failed",
            MemeImage.retry_count < config.MAX_RETRY_ATTEMPTS
        ).all()
        
        if not failed_memes:
            progress_tracker.update_progress(message="没有需要重试的图片")
            progress_tracker.complete_task()
            return
        
        logger.info(f"发现 {len(failed_memes)} 个需要重试的图片")
        progress_tracker.start_task("重试失败分析", len(failed_memes))
        
        # 读取AI分析提示词
        with open("prompt.md", "r", encoding="utf-8") as f:
            prompt_content = f.read()
        
        success_count = 0
        
        for idx, meme in enumerate(failed_memes, 1):
            file_path = os.path.join(config.UPLOAD_DIR, meme.filename)
            progress_tracker.update_progress(
                processed=idx,
                message=f"重试分析 {idx}/{len(failed_memes)}: {meme.filename}"
            )
            
            try:
                # 重试分析
                analysis = await analyze_image_with_ai(file_path, prompt_content)
                
                # 更新数据库
                meme.text_content = analysis.text_content
                meme.description = analysis.description
                meme.tags = analysis.tags
                meme.title = analysis.title
                meme.analysis_status = "success"
                meme.last_retry = datetime.utcnow()
                
                success_count += 1
                logger.info(f"成功分析图片: {meme.filename}")
                
            except Exception as e:
                # 分析仍然失败
                meme.retry_count += 1
                meme.last_retry = datetime.utcnow()
                error_msg = f"重试分析失败: {meme.filename} - {str(e)}"
                logger.warning(error_msg)
                progress_tracker.add_error(error_msg)
            
            db.commit()
        
        progress_tracker.update_progress(
            message=f"重试完成: 成功 {success_count}/{len(failed_memes)}"
        )
        progress_tracker.complete_task()
        
    except Exception as e:
        error_msg = f"重试分析错误: {str(e)}"
        logger.error(error_msg, exc_info=True)
        progress_tracker.add_error(error_msg)
        progress_tracker.complete_task()
    finally:
        db.close()

# API路由
@app.get("/")
async def root():
    """API根路径"""
    return HTMLResponse(open("index.html", encoding="utf-8").read())

@app.get("/api/search", response_model=SearchResponse)
async def search_memes(
    q: str = Query(..., min_length=1, description="搜索关键词，支持空格分隔多个关键词"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    last_id: Optional[int] = Query(None, description="用于无限滚动的最后一个ID"),
    db: Session = Depends(get_db)
):
    """搜索梗图"""
    # 构建查询
    query = db.query(MemeImage).filter(MemeImage.analysis_status == "success")
    
    # 将搜索词按空格分割，并转换为小写
    keywords = [keyword.lower().strip() for keyword in q.split() if keyword.strip()]
    
    # 在标题、描述、文字内容和标签中搜索
    all_memes = query.all()
    filtered_memes = []
    
    for meme in all_memes:
        # 构建搜索文本（合并所有可搜索字段）
        searchable_text = " ".join([
            (meme.title or "").lower(),
            (meme.description or "").lower(),
            (meme.text_content or "").lower(),
            " ".join(tag.lower() for tag in meme.tags)
        ])
        
        # 检查是否所有关键词都出现在搜索文本中
        if all(keyword in searchable_text for keyword in keywords):
            filtered_memes.append(meme)
    
    # 按上传时间倒序排序，然后按ID倒序（确保稳定排序）
    filtered_memes.sort(key=lambda x: (x.upload_time, x.id), reverse=True)
    
    # 保存总数（在应用last_id过滤之前）
    total = len(filtered_memes)
    
    # 如果提供了last_id，找到对应位置
    if last_id:
        last_meme = next((m for m in filtered_memes if m.id == last_id), None)
        if last_meme:
            # 找到last_id在列表中的位置
            last_index = filtered_memes.index(last_meme)
            # 获取之后的项目
            filtered_memes = filtered_memes[last_index + 1:]
    
    # 分页
    items = filtered_memes[:page_size]
    has_more = len(filtered_memes) > page_size
    
    # 转换为响应格式
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
        )
        for meme in items
    ]
    
    return SearchResponse(total=total, items=results, has_more=has_more)

@app.get("/api/memes", response_model=SearchResponse)
async def list_memes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    last_id: Optional[int] = Query(None, description="用于无限滚动的最后一个ID"),
    db: Session = Depends(get_db)
):
    """获取梗图列表（支持无限滚动）"""
    query = db.query(MemeImage).filter(
        MemeImage.analysis_status == "success"
    ).order_by(MemeImage.upload_time.desc(), MemeImage.id.desc())
    
    # 如果提供了last_id，则获取该ID之后的数据
    if last_id:
        last_meme = db.query(MemeImage).filter(MemeImage.id == last_id).first()
        if last_meme:
            query = query.filter(
                (MemeImage.upload_time < last_meme.upload_time) | 
                ((MemeImage.upload_time == last_meme.upload_time) & (MemeImage.id < last_meme.id))
            )
    
    # 总数
    total = db.query(MemeImage).filter(MemeImage.analysis_status == "success").count()
    
    # 分页
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
        )
        for meme in memes
    ]
    
    return SearchResponse(total=total, items=results, has_more=has_more)

@app.get("/api/memes/{meme_id}", response_model=MemeResponse)
async def get_meme(meme_id: int, db: Session = Depends(get_db)):
    """获取单个梗图详情"""
    meme = db.query(MemeImage).filter(MemeImage.id == meme_id).first()
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
async def delete_meme(meme_id: int, db: Session = Depends(get_db)):
    """删除梗图"""
    meme = db.query(MemeImage).filter(MemeImage.id == meme_id).first()
    if not meme:
        raise HTTPException(status_code=404, detail="梗图不存在")
    
    # 删除文件
    file_path = os.path.join(config.UPLOAD_DIR, meme.filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    
    # 删除数据库记录
    db.delete(meme)
    db.commit()
    
    return {"message": "删除成功"}

@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    """获取统计信息"""
    total = db.query(MemeImage).count()
    success = db.query(MemeImage).filter(MemeImage.analysis_status == "success").count()
    failed = db.query(MemeImage).filter(MemeImage.analysis_status == "failed").count()
    pending = db.query(MemeImage).filter(MemeImage.analysis_status == "pending").count()
    
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "pending": pending,
        "last_fetch": datetime.utcnow().isoformat()
    }

@app.get("/api/progress")
async def get_progress():
    """获取当前进度信息"""
    return progress_tracker.get_status()

@app.get("/api/trigger-fetch")
async def trigger_fetch():
    """手动触发抓取任务"""
    if progress_tracker.status == "running":
        return {"error": "已有任务正在运行", "status": "busy"}
    
    # 异步执行任务
    asyncio.create_task(fetch_discord_memes())
    return {"message": "抓取任务已启动", "status": "started"}

@app.get("/api/trigger-retry")
async def trigger_retry():
    """手动触发重试任务"""
    if progress_tracker.status == "running":
        return {"error": "已有任务正在运行", "status": "busy"}
    
    # 异步执行任务
    asyncio.create_task(retry_failed_analyses())
    return {"message": "重试任务已启动", "status": "started"}

@app.post("/api/trigger-remote-fetch")
async def remote_fetch(request: RemoteFetchRequest):
    """远程抓取图片接口"""
    try:
        # 验证URL列表
        if not request.image_urls:
            raise HTTPException(status_code=400, detail="图片URL列表不能为空")
        
        # 验证URL格式
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
        
        # 异步启动处理任务
        asyncio.create_task(process_remote_images(valid_urls))
        
        return {
            "status": "success",
            "message": f"已接收 {len(valid_urls)} 个图片URL，正在后台处理",
            "total_urls": len(valid_urls)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"远程抓取接口错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")

# 运行应用
if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"启动梗图搜索系统 - {config.API_HOST}:{config.API_PORT}")
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)