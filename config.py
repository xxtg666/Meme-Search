# Discord Bot配置
DISCORD_BOT_TOKEN = "your_discord_bot_token"

# OpenAI API配置
OPENAI_API_KEY = "your_openai_api_key"
OPENAI_API_BASE = "https://api.openai.com/v1"
OPENAI_MODEL = "gemini-2.5-pro"

# 代理配置
PROXY_URL = "http://127.0.0.1:7890"  # 代理服务器地址，留空表示不使用代理

# 数据库配置
DB_URL = "sqlite:///./memes.db"

# 文件存储
UPLOAD_DIR = "uploads"
MEMES_FILE = "memes.txt"

# 定时任务配置
FETCH_INTERVAL_MINUTES = 1440  # 每24小时抓取一次
RETRY_INTERVAL_MINUTES = 60  # 每60分钟重试失败的图片
MAX_RETRY_ATTEMPTS = 24  # 最大重试次数

# 服务器配置
API_HOST = "0.0.0.0"
API_PORT = 5000

# 管理员鉴权
ADMIN_SECRET_KEY = "your_admin_secret_key_change_this"  # 请修改为强密码