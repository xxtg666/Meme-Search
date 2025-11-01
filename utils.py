import re
import asyncio
import os
import aiofiles
import hashlib
import httpx
from pathlib import Path
from typing import List, Optional
from datetime import datetime
import logging
import config
from progress import progress_tracker

logger = logging.getLogger(__name__)

# 代理设置
proxies = {}
if config.PROXY_URL:
    proxies = {"http://": config.PROXY_URL, "https://": config.PROXY_URL}


def parse_discord_url(url: str) -> tuple:
    pattern = r'https://discord\.com/channels/(\d+)/(\d+)(?:/threads/(\d+))?'
    match = re.match(pattern, url)
    if match:
        return match.groups()
    return None, None, None


async def download_discord_images(discord_url: str) -> List[str]:
    """从Discord帖子下载所有图片，返回保存的文件名列表"""
    server_id, channel_id, thread_id = parse_discord_url(discord_url)
    if not all([server_id, channel_id]):
        logger.warning(f"无效的Discord URL: {discord_url}")
        return []

    message_channel_id = thread_id if thread_id else channel_id
    logger.info(f"开始从Discord频道下载图片: {message_channel_id}")

    saved_files = []
    async with httpx.AsyncClient(proxies=proxies) as client:
        try:
            headers = {"Authorization": f"Bot {config.DISCORD_BOT_TOKEN}"}
            all_messages = []
            before = None
            while True:
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
                    break

                all_messages.extend(messages)
                before = messages[-1]["id"]
                if len(messages) < 100:
                    break
                await asyncio.sleep(0.5)

            # 提取并下载附件
            total_images = sum(
                len([a for a in msg.get("attachments", []) if a.get("content_type", "").startswith("image/")])
                for msg in all_messages
            )

            if total_images == 0:
                progress_tracker.update_progress(message="未发现图片")
                return []

            image_count = 0
            for message in all_messages:
                for attachment in message.get("attachments", []):
                    if attachment.get("content_type", "").startswith("image/"):
                        image_count += 1
                        progress_tracker.update_progress(message=f"下载图片 {image_count}/{total_images}: {attachment['filename']}")
                        try:
                            img_response = await client.get(attachment["url"])
                            if img_response.status_code == 200:
                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                file_ext = attachment["filename"].split(".")[-1]
                                filename = f"discord_{timestamp}_{attachment['id']}.{file_ext}"
                                filepath = os.path.join(config.UPLOAD_DIR, filename)
                                async with aiofiles.open(filepath, 'wb') as f:
                                    await f.write(img_response.content)
                                saved_files.append(filename)
                                logger.info(f"保存图片: {filename}")
                            else:
                                error_msg = f"下载图片失败: {attachment['filename']} - {img_response.status_code}"
                                logger.error(error_msg)
                                progress_tracker.add_error(error_msg)
                        except Exception as e:
                            error_msg = f"下载单个图片错误: {attachment.get('filename')} - {str(e)}"
                            logger.error(error_msg)
                            progress_tracker.add_error(error_msg)
                            continue
                        await asyncio.sleep(0.1)

            logger.info(f"成功下载 {len(saved_files)} 张图片")
            return saved_files
        except Exception as e:
            error_msg = f"下载Discord图片错误: {str(e)}"
            logger.error(error_msg, exc_info=True)
            progress_tracker.add_error(error_msg)
            return []


def calculate_file_hash(file_path: str) -> str:
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


async def download_remote_image(image_url: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(proxies=proxies) as client:
            response = await client.get(image_url, timeout=30.0)
            if response.status_code != 200:
                logger.error(f"下载图片失败: {image_url} - HTTP {response.status_code}")
                return None

            file_ext = "jpg"
            content_type = response.headers.get("content-type", "")
            if "png" in content_type.lower():
                file_ext = "png"
            elif "gif" in content_type.lower():
                file_ext = "gif"
            elif "webp" in content_type.lower():
                file_ext = "webp"
            else:
                url_ext = image_url.split(".")[-1].lower()
                if url_ext in ["jpg", "jpeg", "png", "gif", "webp"]:
                    file_ext = url_ext

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            url_hash = hashlib.md5(image_url.encode()).hexdigest()[:8]
            filename = f"remote_{timestamp}_{url_hash}.{file_ext}"
            filepath = os.path.join(config.UPLOAD_DIR, filename)
            async with aiofiles.open(filepath, 'wb') as f:
                await f.write(response.content)
            logger.info(f"成功下载远程图片: {filename}")
            return filename
    except Exception as e:
        logger.error(f"下载远程图片错误: {image_url} - {str(e)}")
        return None
