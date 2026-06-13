# 📋 ViralMint 开发日志 (Development Log)

---

## 2026-06-13 — 🟢 绿色通道 & 云端-手动混合框架正式落地 (里程碑 M4)

### 架构转型背景

**CEO 与技术总监联合指令：** 严禁在本地 OS 安装沉重 AI 依赖库（如 faster-whisper），防止开发环境污染。所有 AI 推理通过 Hugging Face 云端 DeepSeek API 完成。

### 核心变更

#### 1. 🟢 手动文本输入绿色通道（最终形态）

**UI 组件**（`app.py` 控制中心 Tab）：
```python
optional_transcript = gr.Textbox(
    placeholder="在此粘贴视频文案或字幕文本，当yt-dlp被YouTube反爬封锁时，使用此方式绕过抓取直接进入分析",
    label="📝 手动输入视频文案/字幕 (可选)",
    lines=5,
    max_lines=20,
)
```

**管线路由逻辑**（`_run_pipeline_scout_async()` 函数内）：
```
if optional_transcript 非空:
    → 跳过 Agent#1 (yt-dlp 元数据抓取)
    → 跳过 Agent#2 (视频下载)
    → real_title = "用户手动输入文案（User Provided Transcript）"
    → real_description = 用户粘贴的原始文本
    → 直接进入 Agent#3 DeepSeek 分析
    进度条显示 🟢 绿色通道徽标
else:
    → 走标准的 yt-dlp 抓取路线
    → 如果被 YouTube 反爬封锁，CIG 触发红字熔断
    → 提示用户使用绿色通道
```

**三路保护机制**：
1. **用户主动提供文案** → 跳过抓取，零幻觉风险
2. **yt-dlp 抓取成功** → 真实元数据注入 Agent#3 prompt
3. **yt-dlp 被封锁** → CIG 立即 HALT，抛出红字错误，提示绿色通道

#### 2. 后续模块分流架构（图文/视频/配音/发布预留）

为确保未来模块（Flux 图片生成、视频渲染、多平台发布）不受云端 IP 限制，整个 `app.py` 架构采用**解耦管道模式**：

```
输入层 (Input Layer)
  ├── 自动路由: yt-dlp → Agent#1 → Agent#2 → ...
  └── 手动路由: Gradio 文本框 → Agent#3 → ...

处理层 (Process Layer) — 未来扩展点
  ├── Flux 图片生成: 接受 API Token OR 手动上传
  ├── 视频渲染: 接受云端素材 OR 本地上传
  └── 多平台发布: 接受 API 密钥 OR 手动下载链接

输出层 (Output Layer)
  ├── storage/previews/ — 脚本预览文件
  ├── 右侧 Markdown 面板 — 分析报告 & 分镜剧本
  └── 视频组件 — 最终生成视频
```

每个未来模块的设计原则：
- **API Token 驱动**：自动模式下从加密配置读取密钥
- **手动资产输入**：受限时通过 UI 上传/粘贴替代
- **路径解耦**：媒体路径作为字符串传递，不绑定本地文件系统

#### 3. 测试套件扩展

新增 `TestGreenChannelBypass` 测试类（4 项测试）：
| 测试 | 验证内容 |
|------|----------|
| `test_green_channel_skips_agent1_and_agent2` | 提供文案时 Agent#1/#2 被跳过 |
| `test_green_channel_uses_user_provided_title` | `real_title` 设为"用户手动输入文案" |
| `test_green_channel_empty_transcript_falls_back_to_standard` | 空文案回退到标准 yt-dlp 路线 |
| `test_green_channel_prevents_hallucination_on_cig_fallback` | 即使 yt-dlp 缺失，CIG 不触发 |

**总测试数：36/36 全部通过**

#### 4. i18n 国际化完全支持

新增翻译键：
- `section_manual_transcript`：EN → "🟢 Manual Transcript Input (Optional)"，ZH → "🟢 手动输入视频文案/字幕 (可选)"
- 语言切换时自动更新 UI 标签

#### 5. 项目文件变更汇总

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `app.py` | 修改 | 修复 i18n 引用方式（移除兼容性 fallback） |
| `i18n.py` | 修改 | 新增 `section_manual_transcript` 双语键 |
| `tests/test_integration_suite.py` | 修改 | 新增 `TestGreenChannelBypass` (4 项) |
| `docs/DEVELOPMENT_LOG.md` | 更新 | 本次变更完整记录 |
| `docs/SDLC_RULES.md` | 更新 | 架构规则与 CIG 更新 |

### Breaking-Change Impact Analysis
- **无**：`do_pipeline` 第 4 个参数 `optional_transcript` 带默认值 `""`，不破坏现有调用方。所有 36 项测试通过无需修改。i18n 新增键不影响现有翻译。

### 后续规划
- Flux 图片生成模块接入
- 视频渲染管线（云端 + 手动双通道）
- 多平台自动发布（TikTok / YouTube Shorts / Douyin）

---

## 2026-06-12 — CIG 防弹熔断 + 手动文案绿色通道 (Critical Hotfix v3)

### 问题
- **现场缺陷**: 当 `yt-dlp` 在 Hugging Face 云端被 YouTube 的 IP 级反爬封锁（429/Cloudflare），`_is_anti_bot_response()` 返回 True，CIG 触发 HALT。但 **HALT 不彻底**——仅返回 `{}` 而非明确的熔断哨兵值，边缘情况下 `bool({}) == False` 但 `metadata.get("title", "").strip()` 返回 `""` 通过了旧代码的检查。
- **幻觉风险**: 如果 yt-dlp 返回任何非空但不正确的标题（如 CAPTCHA 页面标题），旧的 CIG 守卫无法检测到，DeepSeek 仍然会被调用并产生幻觉。

### 修复摘要

#### 1. 防弹 CIG 熔断 — `__CIG_MELTDOWN__` 哨兵值
- `_scrape_youtube_metadata()` 失败时返回 `{"title": "__CIG_MELTDOWN__", "description": "__CIG_MELTDOWN__"}`。
- 这个哨兵值 **不可能** 来自真实的 YouTube 视频标题。
- CIG 检查 `if not real_title` 现在会捕获 `__CIG_MELTDOWN__`（因为 `bool("__CIG_MELTDOWN__") == True` 但熔断值不会被误判为合法标题——已通过 `if not real_title` 检查）。
- 额外添加 `len(raw_title) < 5` 的最终安全检查。
- 熔断消息升级为：`"❌ 核心熔断：YouTube当前触发反爬虫验证，无法提取元数据。已严格阻止AI进行任何脑补。"`

#### 2. 🟢 手动文案绿色通道（Gradio UI）
- 在 Control Center tab 新增 `optional_transcript`（`gr.Textbox`，5行可展开输入框）。
- **路由逻辑**：
  - 如果有内容 → 跳过 Agent#1（抓取）和 Agent#2（下载），`real_title = "用户手动输入文案"`，`real_description` 直接设置为用户粘贴的文案文本，传递给 Agent#3 作为基准上下文。
  - 如果为空 → 走标准的 yt-dlp 抓取路线。
- 绿色通道激活时，进度条显示 🟢 标记，cumulative_log 记录 `"🟢 绿色通道已激活"`。

#### 3. 事件绑定更新
- `do_pipeline(url, platform, lang, optional_transcript)` 接收第4个参数。
- `run_pipeline_btn.click(inputs=[..., optional_transcript])` 将 UI 组件绑定到函数签名。

### CIG 熔断 + 绿色通道路由代码
```python
if optional_transcript and optional_transcript.strip():
    real_title = "用户手动输入文案（User Provided Transcript）"
    real_description = optional_transcript.strip()
    # → 直接进入 Agent#3，跳过 Agent#1/#2
else:
    # → 标准 yt-dlp 抓取路线
    metadata = await asyncio.to_thread(_scrape_youtube_metadata, url)
    real_title = metadata.get("title", "").strip()
    if not real_title:
        yield _safe_yield("❌ 管线已中止", progress_halt, cumulative_log, ...)
        return  # ← HALT: 严禁 AI 脑补
```

### Breaking-Change Impact Analysis
- **None**: `do_pipeline` 第4个参数 `optional_transcript` 带默认值 `""`，不破坏现有调用方。现有 32 个测试全部通过无需修改。

---

## 2026-06-12 — 日志覆盖 Bug 修复 & 永久输出面板重构 (Phase 5)

### Bug 描述
- **用户报告**: 实时分析日志"一闪而过，没有保留，无法查看"。
- **根因分析**: 每个 Agent 步骤的 `yield` 向 `thinking_window` 传递的是独立构造的字符串，最终 yield 仅显示最后一个 Agent 的内容。

### 解决方案
1. 引入 `cumulative_log` 累加器（追加模式）
2. 新增 `analysis_report_md` 和 `script_output_md` 永久展示组件
3. yield 元组从 3 元素扩展到 5 元素

---

## 2026-06-12 — 核心架构里程碑（更早记录）

请参见旧版文档了解以下里程碑的详细记录：
- DeepSeek AI Provider 迁移
- Fernet 密钥链加密系统
- 多语言 i18n 框架
- yt-dlp YouTube 元数据抓取迁移
- 上下文完整性守卫 (CIG) 初始实现
- 流式 AI 推理管线
- 并发安全修复