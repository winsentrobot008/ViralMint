# 🏗️ ViralMint SDLC 架构规则与开发规范

## 项目定位

**ViralMint** — 短视频爆款内容自动化工厂。AI Agent 管线：抓取 → 分析 → 生成 → 发布。

## 核心架构哲学

### 1. 云端-手动混合框架（Cloud-Local Hybrid Framework）

```
                   ┌──────────────────────────────────┐
                   │         Gradio UI (HF Space)      │
                   │  ┌──────────────────────────┐     │
                   │  │  控制中心 (Control Center) │     │
                   │  │  ├─ YouTube URL 输入      │     │
                   │  │  ├─ 🟢 手动文案输入 (可选) │     │
                   │  │  └─ 🚀 执行全自动管线      │     │
                   │  └──────────────────────────┘     │
                   └──────────┬───────────────────────┘
                              │
                    ┌─────────▼───────────────────┐
                    │      do_pipeline()           │
                    │   (Async Generator)          │
                    └─────────┬───────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
     ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
     │ 🟢 绿色通道    │ │ 标准 yt-dlp    │ │ CIG 熔断       │
     │ (手动文案跳过  │ │ (真实元数据抓取) │ │ (反爬封锁      │
     │  Agent#1/#2)   │ │                │ │  立即 HALT)    │
     └───────┬────────┘ └───────┬────────┘ └───────┬────────┘
             │                  │                   │
             └──────────────────┼───────────────────┘
                                ▼
                    ┌──────────────────────┐
                    │  Agent#3 DeepSeek    │
                    │  爆款内容分析        │
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │  Agent#4 DeepSeek    │
                    │  60秒分镜剧本生成    │
                    └──────────────────────┘
```

### 2. 上下文完整性守卫（Context Integrity Guard — CIG）

**核心原则：** 在没有真实视频元数据的情况下，**严禁**让 LLM 自由发挥。

**三级保护：**
1. **第一级 — 反爬关键词检测**：`_is_anti_bot_response()` 检查标题是否包含 CAPTCHA/验证关键词
2. **第二级 — 哨兵值熔断**：`_scrape_youtube_metadata()` 失败时返回 `__CIG_MELTDOWN__`
3. **第三级 — 绿色通道**：用户可手动粘贴文案，完全绕过抓取

**熔断响应代码（`app.py`）**：
```python
if not real_title:
    yield "❌ 核心熔断：YouTube触发反爬虫验证，无法提取元数据"
    return  # ← 立即终止，严禁 AI 脑补
```

### 3. 绿色通道路由逻辑（GREEN CHANNEL）

```python
async def _run_pipeline_scout_async(url, platform, lang, optional_transcript=""):
    if optional_transcript and optional_transcript.strip():
        # 🟢 绿色通道激活
        real_title = "用户手动输入文案（User Provided Transcript）"
        real_description = optional_transcript.strip()
        # → 跳过 Agent#1/#2，直接进入 Agent#3
    else:
        # 标准路线：yt-dlp 抓取
        metadata = await asyncio.to_thread(_scrape_youtube_metadata, url)
        real_title = metadata.get("title", "").strip()
        if not real_title:
            # CIG 熔断
            return  # HALT
```

### 4. 输入/输出解耦架构

**输入层** — 所有管道输入通过 do_pipeline() 参数传递：
- `url: str` — YouTube/TikTok/Douyin 视频链接
- `platform: str` — 平台枚举
- `lang: str` — 语言
- `optional_transcript: str` — 手动文案（绿色通道）

**输出层** — 5 元素 yield 元组：
```python
(status: str,              # 管线状态文本
 progress_html: str,       # 实时进度 HTML
 cumulative_log: str,      # 追加式日志
 analysis_report: str,     # 📊 DeepSeek 分析报告（永久面板）
 script_report: str)       # 📝 DeepSeek 分镜剧本（永久面板）
```

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| UI 框架 | Gradio 6.0 (Blocks) | Hugging Face Spaces 原生支持 |
| AI 推理 | DeepSeek Chat API (OpenAI 兼容) | 通过 `openai` 库调用 |
| 视频元数据 | yt-dlp (子进程) | TLS 指纹绕过反爬 |
| 加密存储 | Fernet (cryptography) | API 密钥本地加密 |
| 国际化 | 内置 i18n 字典 | `i18n.py` 中英双语 |
| 测试 | unittest | 36 项集成测试 |

## 文件结构

```
ViralMint/
├── app.py                      # Gradio UI 主入口
├── i18n.py                     # 国际化翻译字典
├── config.json                 # 加密配置存储 (自动生成)
├── storage/previews/           # 脚本预览文件
├── backend/
│   ├── agents/
│   │   └── planner.py          # Planner Agent
│   └── services/
│       ├── ytdlp_service.py    # yt-dlp 封装
│       ├── video_generator.py  # 视频生成
│       └── youtube_scout.py    # YouTube 搜索
├── tests/
│   └── test_integration_suite.py  # 36 项集成测试
└── docs/
    ├── DEVELOPMENT_LOG.md      # 开发变更日志
    └── SDLC_RULES.md           # 架构规则 (本文件)
```

## 部署流程

### Hugging Face Spaces
1. 代码推送至 HF Space Git 仓库
2. Space 自动构建并安装 `requirements.txt`
3. 设置 Space Secrets：
   - `OPENAI_API_KEY`：DeepSeek API 密钥
   - `HF_SPACE_SECRET_KEY`：用于加密持久化存储
4. 访问 `https://huggingface.co/spaces/aoogoost/ViralMint`

### 环境变量
```bash
# 必须（AI 推理）
OPENAI_API_KEY=sk-your-deepseek-key
OPENAI_BASE_URL=https://api.deepseek.com  # 默认值

# 可选（加密持久化）
HF_SPACE_SECRET_KEY=your-hf-secret
# 或 .env 文件
ENCRYPTION_KEY=your-local-key
```

## 测试运行

```bash
# 运行全部 36 项测试
python -m unittest tests.test_integration_suite -v

# 运行特定测试类
python -m unittest tests.test_integration_suite.TestGreenChannelBypass -v
```

## 常见问题排查

### Q: YouTube 反爬封锁，管线 HALT 了怎么办？
**A: 使用绿色通道。** 在"手动输入视频文案/字幕（可选）"文本框中粘贴视频文案，系统会自动跳过 yt-dlp 抓取，直接进入 AI 分析。

### Q: DeepSeek API 密钥在哪里设置？
**A:**
1. **Hugging Face 云端**：在 Space Settings → Repository Secrets 设置 `OPENAI_API_KEY`
2. **本地开发**：创建 `.env` 文件，写入 `OPENAI_API_KEY=sk-xxx`

### Q: 如何添加新的翻译语言？
**A:** 在 `i18n.py` 的 `LOCALIZATION` 字典中添加新语言键，复制现有语言的完整键值对结构。

### Q: 如何为未来模块（Flux/视频渲染）预留接口？
**A:** 遵循"双通道"设计原则：
```python
def future_image_module(
    api_key: str = "",      # 自动模式：API Token
    manual_input: str = "",  # 手动模式：上传文件
):
    if manual_input:
        # 使用用户提供的资产
    else:
        # 使用 API Token 自动调用
```
所有路径作为字符串传递，不绑定本地文件系统。

## 历史幻觉 Bug 总结（吸取教训）

1. **2026-06-12 幻觉回归**：UI 参数污染导致 `scout_url` 被覆盖 + Agent#1 执行空操作 `lambda: None`
2. **2026-06-12 第二次幻觉**：`requests` 被 YouTube 反爬封锁，CAPTCHA 页面标题通过 CIG 检查
3. **2026-06-12 CIG 不完全熔断**：`{}` 字典的 `bool({}) == False` 不触发熔断，需要 `__CIG_MELTDOWN__` 哨兵值

**教训：** 永远不要在上下文为空时让 LLM 自由发挥。必须明确提供 `return` 终止语句 + 红字错误提示。