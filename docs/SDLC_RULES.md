# 🛡️ ViralMint 系统核心开发规范 (SDLC Meta-Rules)

- **Phase 1 (Design)**: Before modifying production code, update `docs/DEVELOPMENT_LOG.md` with the blueprint and breaking-change impact analysis.
- **Phase 2 (Coding)**: Never hardcode secret keys. Any Gradio 6.0 data flow (like Chatbot arrays) must strictly follow the `{"role": "...", "content": "..."}` dictionary schema. All network/API requests must have a hard timeout (e.g., `timeout=20.0`) and handle exceptions gracefully.
- **Phase 3 (Testing)**: Run `python -m unittest discover tests/` before every deployment. The pipeline must pass with Exit Code 0.
- **Phase 4 (Deployment)**: Push sequentially to GitHub (`origin`) and Hugging Face (`hf`) only after tests pass.

## 上下文完整性守卫规则 (Context Integrity Guard)

### 规则 CIG-001: 禁止空元数据推测
- Agent#1 (Scout) 必须实际抓取 YouTube 视频页面，提取 `<title>` 和 `<meta name="description">` 作为真实元数据。
- Agent#1 **严禁** 执行空操作 (如 `lambda: None`)。
- 如果 `_scrape_youtube_metadata()` 返回空 `title`，管线必须立即中止（HALT）。

### 规则 CIG-002: 禁止无元数据 LLM 调用
- Agent#3 (Analyzer) 的 DeepSeek prompt 必须包含 Agent#1 提取的 `real_title` 和 `real_description`。
- Prompt 必须明确指示 LLM 基于真实元数据进行分析，禁止自由推测。
- 如果真实元数据缺失，Agent#3 不应被调用。

### 规则 CIG-003: UI 参数污染防护
- `run_pipeline_btn.click()` 的 `outputs` 列表：
  - ✅ `outputs[0]` → `pipeline_status` (隐藏的 Textbox)
  - ❌ `outputs[0]` → **不得** 是 `scout_url` (用户输入 URL 的文本框)
- 管线运行期间用户输入的 URL 必须保持原样，不可被瞬态文本覆盖。

### 规则 CIG-004: 实时抓取 vs API 降级
- 默认使用 `requests` + 正则表达式从 YouTube 页面提取元数据（无需 API Key）。
- 如果遇到反爬限制时考虑降级为 `yt-dlp --dump-json` 子进程。
- YouTube Data API v3 作为生产环境的可选项（需要 API Key）。
- 所有抓取操作必须设置 8 秒超时，失败时返回空字典，绝不抛出异常。
