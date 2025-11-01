import os
import asyncio
from datetime import datetime
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import config
from models import SessionLocal, MemeImage, init_db
from progress import progress_tracker
from utils import download_discord_images, calculate_file_hash, download_remote_image
from ai import analyze_image_with_ai

logger = logging.getLogger(__name__)

# 初始化数据库（如果尚未）
init_db()

# 全局调度器
scheduler = AsyncIOScheduler()


async def process_remote_images(image_urls):
    progress_tracker.start_task("远程图片抓取", len(image_urls))
    db = SessionLocal()
    try:
        with open("prompt.md", "r", encoding="utf-8") as f:
            prompt_content = f.read()

        success_count = 0
        duplicate_count = 0
        error_count = 0

        for idx, image_url in enumerate(image_urls, 1):
            progress_tracker.update_progress(processed=idx, message=f"处理远程图片 {idx}/{len(image_urls)}: {image_url[:50]}...")
            try:
                filename = await download_remote_image(image_url)
                if not filename:
                    error_count += 1
                    continue

                file_path = os.path.join(config.UPLOAD_DIR, filename)
                file_hash = calculate_file_hash(file_path)

                existing = db.query(MemeImage).filter(MemeImage.file_hash == file_hash).first()
                if existing:
                    os.remove(file_path)
                    duplicate_count += 1
                    logger.info(f"跳过重复图片: {filename}")
                    continue

                try:
                    analysis = await analyze_image_with_ai(file_path, prompt_content)
                    status = "success"
                except Exception:
                    analysis = None
                    status = "failed"

                if analysis is None:
                    # 使用默认占位
                    from schemas import MemeAnalysis
                    analysis = MemeAnalysis(
                        text_content="",
                        description="分析中...",
                        tags=["待分析", "梗图", "远程", "未处理", "自动抓取"],
                        title="待分析"
                    )

                db_meme = MemeImage(
                    filename=filename,
                    filepath=f"/uploads/{filename}",
                    text_content=analysis.text_content,
                    description=analysis.description,
                    tags=analysis.tags,
                    title=analysis.title,
                    file_hash=file_hash,
                    discord_url=image_url,
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

        progress_tracker.update_progress(message=f"远程抓取完成: 成功 {success_count}, 重复 {duplicate_count}, 错误 {error_count}")
        progress_tracker.complete_task()
    except Exception as e:
        error_msg = f"处理远程图片任务错误: {str(e)}"
        logger.error(error_msg, exc_info=True)
        progress_tracker.add_error(error_msg)
        progress_tracker.complete_task()
    finally:
        db.close()


async def fetch_discord_memes():
    if not os.path.exists(config.MEMES_FILE):
        logger.warning(f"文件不存在: {config.MEMES_FILE}")
        return

    progress_tracker.start_task("Discord梗图抓取")
    db = SessionLocal()
    try:
        with open(config.MEMES_FILE, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip()]

        with open("prompt.md", "r", encoding="utf-8") as f:
            prompt_content = f.read()

        total_new_images = 0
        total_duplicates = 0

        for idx, discord_url in enumerate(urls, 1):
            progress_tracker.update_progress(message=f"处理链接 {idx}/{len(urls)}: {discord_url}")
            filenames = await download_discord_images(discord_url)
            for filename in filenames:
                file_path = os.path.join(config.UPLOAD_DIR, filename)
                file_hash = calculate_file_hash(file_path)
                existing = db.query(MemeImage).filter(MemeImage.file_hash == file_hash).first()
                if existing:
                    os.remove(file_path)
                    total_duplicates += 1
                    continue

                progress_tracker.update_progress(message=f"分析图片: {filename}")
                try:
                    analysis = await analyze_image_with_ai(file_path, prompt_content)
                    status = "success"
                except Exception:
                    from schemas import MemeAnalysis
                    analysis = MemeAnalysis(
                        text_content="",
                        description="分析中...",
                        tags=["待分析", "梗图", "Discord", "未处理", "自动抓取"],
                        title="待分析"
                    )
                    status = "failed"

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

        progress_tracker.update_progress(message=f"抓取完成: 新增 {total_new_images} 张图片, 跳过 {total_duplicates} 张重复图片")
        progress_tracker.complete_task()
    except Exception as e:
        error_msg = f"抓取Discord梗图错误: {str(e)}"
        logger.error(error_msg, exc_info=True)
        progress_tracker.add_error(error_msg)
        progress_tracker.complete_task()
    finally:
        db.close()


async def retry_failed_analyses():
    progress_tracker.start_task("重试失败分析")
    db = SessionLocal()
    try:
        failed_memes = db.query(MemeImage).filter(
            MemeImage.analysis_status == "failed",
            MemeImage.retry_count < config.MAX_RETRY_ATTEMPTS
        ).all()

        if not failed_memes:
            progress_tracker.update_progress(message="没有需要重试的图片")
            progress_tracker.complete_task()
            return

        progress_tracker.start_task("重试失败分析", len(failed_memes))
        with open("prompt.md", "r", encoding="utf-8") as f:
            prompt_content = f.read()

        success_count = 0
        for idx, meme in enumerate(failed_memes, 1):
            file_path = os.path.join(config.UPLOAD_DIR, meme.filename)
            progress_tracker.update_progress(processed=idx, message=f"重试分析 {idx}/{len(failed_memes)}: {meme.filename}")
            try:
                analysis = await analyze_image_with_ai(file_path, prompt_content)
                meme.text_content = analysis.text_content
                meme.description = analysis.description
                meme.tags = analysis.tags
                meme.title = analysis.title
                meme.analysis_status = "success"
                meme.last_retry = datetime.utcnow()
                success_count += 1
            except Exception as e:
                meme.retry_count += 1
                meme.last_retry = datetime.utcnow()
                error_msg = f"重试分析失败: {meme.filename} - {str(e)}"
                logger.warning(error_msg)
                progress_tracker.add_error(error_msg)
            db.commit()

        progress_tracker.update_progress(message=f"重试完成: 成功 {success_count}/{len(failed_memes)}")
        progress_tracker.complete_task()
    except Exception as e:
        error_msg = f"重试分析错误: {str(e)}"
        logger.error(error_msg, exc_info=True)
        progress_tracker.add_error(error_msg)
        progress_tracker.complete_task()
    finally:
        db.close()
