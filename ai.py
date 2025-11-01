import json
import base64
from datetime import datetime
import httpx
import logging
import config
from schemas import MemeAnalysis

logger = logging.getLogger(__name__)


async def analyze_image_with_ai(image_path: str, prompt_content: str) -> MemeAnalysis:
    """调用AI API分析图片，如果未配置API KEY则返回模拟数据。"""
    if not config.OPENAI_API_KEY:
        logger.info(f"使用模拟数据分析图片: {image_path}")
        return MemeAnalysis(
            text_content="示例文字内容",
            description="这是一个示例梗图，展示了一个有趣的网络表情包。图片中包含了搞笑的元素和网络流行文化。",
            tags=["示例", "表情包", "搞笑", "网络梗", "测试"],
            title="示例梗图"
        )

    async with httpx.AsyncClient(proxies={"http://": config.PROXY_URL, "https://": config.PROXY_URL} if config.PROXY_URL else None) as client:
        try:
            logger.info(f"开始AI分析图片: {image_path}")
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')

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
                        {"role": "system", "content": prompt_with_time},
                        {"role": "user", "content": [
                            {"type": "text", "text": "现在，请严格按照以上规范分析提供的图片，并直接输出JSON结果，不包含任何额外说明。"},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                        ]}
                    ]
                },
                timeout=60.0
            )

            if response.status_code != 200:
                raise Exception(f"API返回错误: {response.status_code}")

            result = response.json()
            content = result['choices'][0]['message']['content']

            content = content.strip()
            if content.startswith('```json'):
                content = content[7:]
            elif content.startswith('```'):
                content = content[3:]
            if content.endswith('```'):
                content = content[:-3]
            content = content.strip()

            analysis_data = json.loads(content)
            logger.info(f"AI分析成功: {image_path}")
            return MemeAnalysis(**analysis_data)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析错误: {str(e)}, 原始内容: {content[:200]}...")
            raise Exception(f"AI返回的JSON格式错误: {str(e)}")
        except Exception as e:
            logger.error(f"AI分析错误: {str(e)}")
            raise
