> [!NOTE]
> 本项目由 Claude 4 Sonnet 编写。

# Meme Search

智能梗图搜索和管理系统，支持自动从 Discord 抓取梗图并使用 AI 进行分析，方便搜索。

## 功能特性

### 🔍 智能搜索
- 支持多关键词搜索（空格分隔）
- 在标题、描述、文字内容和标签中进行全文搜索
- 无限滚动分页加载
- 实时搜索结果

### 🤖 AI 分析
- 使用 OpenAI/Gemini API 自动分析梗图内容
- 自动提取图片中的文字内容
- 生成智能描述和标签
- 自动重试失败的分析任务

### 📥 自动抓取
- 定时从 Discord 频道抓取梗图
- 支持手动触发抓取任务
- 支持远程图片URL抓取
- 自动去重，避免重复存储

### 📊 实时监控
- 实时进度跟踪和日志记录
- 系统统计信息
- 任务状态监控
- 错误处理和重试机制

## 系统架构

```
梗图搜索系统
├── 后端 (FastAPI)
│   ├── 数据库模块 (SQLAlchemy + SQLite)
│   ├── AI分析模块 (OpenAI API)
│   ├── Discord抓取模块
│   ├── 文件管理模块
│   └── 定时任务模块 (APScheduler)
├── 前端 (原生JavaScript + HTML)
│   ├── 搜索界面
│   ├── 图片展示
│   ├── 进度监控
│   └── 管理界面
└── 配置管理 (config.py)
```

## 安装部署

### 环境要求
- Python 3.10+
- pip (Python包管理器)

### 1. 克隆项目

```bash
git clone https://github.com/xxtg666/Meme-Search
cd Meme-Search
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置系统
编辑 `config.py` 文件，配置说明在下方

### 4. 准备Discord链接
创建 `memes.txt` 文件，每行放入一个Discord频道或帖子链接：
```
https://discord.com/channels/server_id/channel_id
https://discord.com/channels/server_id/channel_id/threads/thread_id
```

### 5. 配置AI分析提示词
编辑 `prompt.md` 文件，自定义AI分析图片的提示词，当然默认提示词就很好。

### 6. 启动系统
```bash
python backend.py
```

系统将在 `http://localhost:5000` 启动。

## 配置说明

### config.py 配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `DISCORD_BOT_TOKEN` | Discord机器人令牌 | 必填 |
| `OPENAI_API_KEY` | OpenAI API密钥 | 必填 |
| `OPENAI_API_BASE` | API服务器地址 | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | 使用的AI模型 | `gemini-2.5-pro` |
| `PROXY_URL` | 代理服务器地址 | 可选，留空不使用代理 |
| `DB_URL` | 数据库连接URL | `sqlite:///./memes.db` |
| `UPLOAD_DIR` | 图片存储目录 | `uploads` |
| `MEMES_FILE` | Discord链接文件 | `memes.txt` |
| `FETCH_INTERVAL_MINUTES` | 自动抓取间隔（分钟） | `1440` (24小时) |
| `RETRY_INTERVAL_MINUTES` | 重试间隔（分钟） | `60` |
| `MAX_RETRY_ATTEMPTS` | 最大重试次数 | `24` |
| `API_HOST` | API服务器主机 | `0.0.0.0` |
| `API_PORT` | API服务器端口 | `5000` |

## API接口

### 搜索接口
```http
GET /api/search?q=关键词&page=1&page_size=20
```

### 获取梗图列表
```http
GET /api/memes?page=1&page_size=20&last_id=123
```

### 获取单个梗图
```http
GET /api/memes/{meme_id}
```

### 删除梗图
```http
DELETE /api/memes/{meme_id}
```

### 获取统计信息
```http
GET /api/stats
```

### 获取进度信息
```http
GET /api/progress
```

### 手动触发抓取
```http
GET /api/trigger-fetch
```

### 手动触发重试
```http
GET /api/trigger-retry
```

### 远程抓取图片
```http
POST /api/trigger-remote-fetch
Content-Type: application/json

{
    "image_urls": ["https://example.com/image1.jpg", "https://example.com/image2.png"]
}
```

## 使用指南

### 1. Discord机器人设置
1. 前往 [Discord Developer Portal](https://discord.com/developers/applications)
2. 创建新应用程序和机器人
3. 复制机器人令牌到 `config.py`
4. 给机器人添加 `Read Message History` 权限
5. 邀请机器人到目标服务器

### 2. 添加抓取源
在 `memes.txt` 中添加要监控的Discord频道链接：
- 频道链接：`https://discord.com/channels/server_id/channel_id`
- 帖子链接：`https://discord.com/channels/server_id/channel_id/threads/thread_id`

### 3. 搜索梗图
- 打开 `http://localhost:5000`
- 在搜索框输入关键词
- 支持多个关键词（空格分隔）
- 点击图片查看详情

### 4. 监控进度
访问进度监控页面查看：
- 当前任务状态
- 处理进度
- 系统日志
- 错误信息

## 文件结构

```
memesearch/
├── backend.py          # 主程序文件
├── config.py           # 配置文件
├── index.html          # 前端页面
├── prompt.md          # AI分析提示词
├── memes.txt          # Discord链接列表
├── requirements.txt   # Python依赖
├── README.md          # 项目文档
├── uploads/           # 图片存储目录
├── memes.db          # SQLite数据库（自动生成）
└── meme_search.log   # 系统日志（自动生成）
```

## 故障排除

### 常见问题

1. **Discord抓取失败**
   - 检查机器人令牌是否正确
   - 确认机器人有读取消息历史权限
   - 检查Discord链接格式是否正确

2. **AI分析失败**
   - 检查API密钥是否有效
   - 确认API服务器地址正确
   - 查看是否需要配置代理

3. **图片下载失败**
   - 检查网络连接
   - 确认代理配置是否正确
   - 查看防火墙设置

4. **数据库错误**
   - 确保有写入权限
   - 检查磁盘空间
   - 查看数据库文件是否损坏

### 日志查看
系统会自动记录详细日志到 `meme_search.log` 文件，包括：
- 系统启动信息
- 抓取进度
- 分析结果
- 错误信息

## 开发说明

### 技术栈
- **后端**: FastAPI, SQLAlchemy, APScheduler
- **数据库**: SQLite
- **AI分析**: OpenAI API (兼容接口)
- **前端**: 原生JavaScript, HTML, CSS
- **图片处理**: Pillow, aiofiles
- **网络请求**: httpx

### 扩展开发
1. **添加新的抓取源**: 在定时任务模块中添加新的抓取函数
2. **自定义AI分析**: 修改 `prompt.md` 和分析函数
3. **新增API接口**: 在 `backend.py` 中添加新的路由
4. **前端功能扩展**: 修改 `index.html` 添加新功能