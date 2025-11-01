> [!NOTE]
> 本项目由 Claude Sonnet 4.5 编写。

# Meme Search

智能梗图搜索和管理系统，支持自动从 Discord 抓取梗图并使用 AI 进行分析，方便搜索。

## 功能特性

### 🔍 智能搜索
- 支持多关键词搜索（空格分隔）
- 在标题、描述、文字内容和标签中进行全文搜索
- 无限滚动分页加载
- 实时搜索结果
- **支持时间/随机双模式展示**

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

### 🔐 管理后台
- 独立的管理员后台 (`/admin`)
- 基于密钥的身份验证（自动保存到浏览器）
- 支持图片编辑、删除和重新分析
- 按状态筛选（成功/失败/待处理）
- 管理员搜索功能
- 批量操作支持

## 系统架构

```
梗图搜索系统
├── 后端 (FastAPI)
│   ├── backend.py         # 主应用和路由
│   ├── models.py          # 数据库模型 (SQLAlchemy)
│   ├── schemas.py         # API数据模型 (Pydantic)
│   ├── config.py          # 配置管理
│   ├── auth.py            # 管理员身份验证
│   ├── ai.py              # AI图片分析
│   ├── utils.py           # 工具函数 (下载、哈希等)
│   ├── tasks.py           # 定时任务 (Discord抓取、重试)
│   └── progress.py        # 进度跟踪
├── 前端
│   ├── index.html         # 用户搜索界面
│   └── admin.html         # 管理员后台
└── 配置文件
    ├── config.py          # 系统配置
    ├── prompt.md          # AI分析提示词
    └── memes.txt          # Discord链接列表
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
| `ADMIN_KEY` | **管理员密钥** | **必填** |

## API接口

### 公开接口

#### 搜索接口
```http
GET /api/search?q=关键词&page=1&page_size=20&last_id=123
```

#### 获取梗图列表
```http
GET /api/memes?page=1&page_size=20&last_id=123&sort=time
# sort: time(时间排序) 或 random(随机排序)
```

#### 获取单个梗图
```http
GET /api/memes/{meme_id}
```

#### 获取统计信息
```http
GET /api/stats
```

#### 获取进度信息
```http
GET /api/progress
```

### 管理员接口（需要 X-Admin-Key 请求头）

#### 删除梗图
```http
DELETE /api/memes/{meme_id}
Headers: X-Admin-Key: your_admin_key
```

#### 管理员查询（支持筛选和搜索）
```http
GET /api/admin/memes?status=failed&q=关键词&page_size=20&last_id=123
Headers: X-Admin-Key: your_admin_key
# status: success/failed/pending (可选)
# q: 搜索关键词 (可选)
```

#### 更新梗图信息
```http
PUT /api/admin/memes/{meme_id}
Headers: X-Admin-Key: your_admin_key
Content-Type: application/json

{
    "title": "新标题",
    "description": "新描述",
    "text_content": "图片文字",
    "tags": ["标签1", "标签2"]
}
```

#### 重新分析梗图
```http
POST /api/admin/memes/{meme_id}/reanalyze
Headers: X-Admin-Key: your_admin_key
```

#### 手动触发抓取
```http
GET /api/trigger-fetch
Headers: X-Admin-Key: your_admin_key
```

#### 手动触发重试
```http
GET /api/trigger-retry
Headers: X-Admin-Key: your_admin_key
```

#### 远程抓取图片
```http
POST /api/trigger-remote-fetch
Headers: X-Admin-Key: your_admin_key
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
- **切换排序模式**：
  - 桌面端：点击「时间排序」/「随机排序」按钮
  - 移动端：点击 ⏰/🎲 图标切换

### 4. 管理后台
- 访问 `/admin` 进入管理界面
- 输入 `ADMIN_KEY`（首次输入后自动保存在浏览器）
- **功能**：
  - 查看所有图片及分析状态
  - 按状态筛选：成功/失败/待处理
  - 搜索关键词快速定位
  - 删除不需要的图片
  - 重新分析失败的图片
  - 编辑标题、描述、标签等信息
- **退出**：点击「退出」按钮清除保存的密钥

### 5. 监控进度
访问进度监控页面查看：
- 当前任务状态
- 处理进度
- 系统日志
- 错误信息

## 文件结构

```
memesearch/
├── backend.py          # 主程序入口和FastAPI应用
├── models.py           # 数据库ORM模型
├── schemas.py          # Pydantic数据验证模型
├── config.py           # 配置文件
├── auth.py             # 管理员认证模块
├── ai.py               # AI图片分析模块
├── utils.py            # 工具函数（下载、哈希计算）
├── tasks.py            # 定时任务（抓取、重试）
├── progress.py         # 进度追踪模块
├── index.html          # 用户搜索界面
├── admin.html          # 管理后台界面
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