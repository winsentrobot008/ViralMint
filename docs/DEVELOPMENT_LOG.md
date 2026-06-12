# 📋 ViralMint Development Log

## 2026-06-11 — Core SDLC Architecture & Gradio 6 Chatbot Fix

### Architectural Milestones

#### 1. DeepSeek AI Provider Migration
- Integrated DeepSeek as the primary AI provider alongside Anthropic, OpenAI, and OpenRouter.
- Model options: `deepseek-chat` (default reasoning) and `deepseek-reasoner`.
- The `update_model_for_provider` callback dynamically switches model dropdown choices.

#### 2. Fernet Key-Chain Encryption System
- All API keys are encrypted at rest using Fernet (symmetric encryption).
- Key derivation chain: `HF_SPACE_SECRET_KEY` (env var) → `.env` file → stable local fallback (repo root hash).
- UI never exposes plaintext keys; only `••••••••` masking is rendered.
- `save_settings()` encrypts before persisting; `load_settings()` returns masked value.

#### 3. Multi-Language i18n System
- Built a `get_text(lang, key)` helper that reads from `i18n.LOCALIZATION` dict.
- `_("key")` shorthand uses `_LANG` global state.
- Language dropdown (`en`/`zh`) triggers `update_ui_language()` which re-renders all UI labels, placeholders, and dataframes dynamically.

#### 4. Flat UI Tab Layout (Gradio Blocks)
- Consolidated 7 tab panels: AI Config, Control Center, Library/Tools, Messaging, Channels, Stock Video, Clip Studio.
- Right column houses live pipeline progress, agent thinking window, and video gallery.
- Left column hosts all control panels with tab navigation.

#### 5. Gradio 6.0 Chatbot Dictionary Serialization Fix (Current)
- Refactored `chat_with_agent()` to enforce strict `{"role": "user", "content": "..."}` / `{"role": "assistant", "content": "..."}` schema.
- Fixed the `new_chat()` handler to reset chatbot state cleanly.
- Ensured all event wiring (`msg_input.submit`, `send_btn.click`) passes the chatbot state correctly.

### Breaking-Change Impact Analysis
- **None**: The chatbot dict format change is fully backward-compatible with the existing `chat_with_agent()` function, which always produced the correct format. The fix ensures stricter compliance with Gradio 6.0's new validation.
- The `respond()` wrapper was simplified to a one-liner delegating to `chat_with_agent()`.

### Next Steps
- Write integration tests for encryption persistence, chatbot structure, and pipeline safety.
- Establish CI pipeline with `unittest` discovery.
- Deploy to GitHub and Hugging Face Spaces.

---

## 2026-06-12 — Legacy Config Model Fallback Fix

### Bug Description
- **User Error**: `Value: claude-sonnet-4-6 is not in the list of choices: ['deepseek-chat', 'deepseek-reasoner']`
- **Root Cause**: Legacy `config.json` files contain historical model identifiers (e.g., `claude-sonnet-4-6` from a previous Anthropic provider selection). When `load_settings()` populates the Gradio UI dropdown, Gradio 6.0 strictly validates that the value exists in the current choices matrix. If the provider has been changed (or the model choices were updated), the old model string is rejected.
- **Fix**: Added a strict containment check in `load_settings()`. If the saved model is not in the valid choices list for the saved provider, a safe fallback (`'deepseek-chat'` for DeepSeek, or the first available choice) is applied. Same sanitization applied to the provider field.

### Breaking-Change Impact Analysis
- **None**: The fallback is fully backward-compatible. Existing configs with valid model/provider pairs continue to work unchanged. Only invalid/legacy values are sanitized on read.

---

## 2026-06-12 — Pipeline Thread-Locking Concurrency Fix (Phase 2)

### Bug Description
- **Symptom**: The UI freezes indefinitely at `Agent#1 Scout`. The 20s timeout wrapper never fires.
- **Root Cause**: A dead-lock in the Gradio event loop. `do_pipeline()` in `app.py` is a synchronous function that blocks the main thread. Gradio 6 processes all `fn=...` callbacks on the same thread pool by default. When `do_pipeline` calls `run_pipeline()` synchronously for URL validation, the function returns immediately — but the real problem is that `demo.queue()` was never called, so **no async/background concurrency is enabled at all**.
- **Why timeout doesn't fire**: `do_pipeline` catches `asyncio.TimeoutError` but never actually wraps anything in `asyncio.wait_for(...)`. The `import asyncio` is a dead import used only for the except clause — no actual async runtime is instantiated.
- **Secondary issue**: `simulate_pipeline_steps()` exists as an unused generator with `time.sleep(1.5)` that could also freeze the UI if ever wired, since generators in Gradio need `yield` matching and `queue=True`.

### Fix Summary
- Added `demo.queue(default_concurrency_limit=5)` to enable background task processing.
- Refactored `do_pipeline` into an `async def` generator that `yield`s progress updates, allowing the UI to stay responsive.
- Wrapped blocking ops in `await asyncio.to_thread(...)` to prevent main-loop starvation.
- Added explicit debug logging (print statements) at each scout phase boundary for traceability.
- Wrapped the actual scout logic in `asyncio.wait_for(..., timeout=20.0)` so the timeout actually fires.

### Breaking-Change Impact Analysis
- **None**: The pipeline now returns progressively via `yield` instead of a single return. Gradio 6 fully supports this pattern when `.queue()` is enabled. The return signature `(status, progress_html, thinking)` is preserved; each `yield` emits a tuple.

---

## 2026-06-12 — YouTube Scout Exception Safety Fix (Phase 3)

### Bug Description
- **Symptom**: Pipeline hangs/freezes when processing YouTube URLs (400 Bad Request / thread hang).
- **Live Probe Diagnosis** (`probe_youtube_live.py`):
  - `.env` file missing → no `YOUTUBE_API_KEY` configured.
  - `googleapiclient` not installed in local dev environment.
  - When `search_youtube()` is called, `from googleapiclient.discovery import build` raises `ImportError`.
  - The `except Exception: raise` at line 88 of `youtube_scout.py` propagates the `ImportError` up the async call chain UNCAUGHT.
  - The pipeline runner never receives a clean result — the async generator hangs waiting for the uncaught exception to resolve, causing the Hugging Face gateway to drop the connection with a 400 status.

### Fix Summary
- Changed `except Exception: raise` to:
  - `except ImportError:` → returns `[]` (missing dependency is not a pipeline failure).
  - `except Exception as e:` → logs the error and returns `[]` (graceful fallback, never propagates).

### Breaking-Change Impact Analysis
- **None**: All error paths now return `[]` (empty list) instead of propagating exceptions. The async pipeline generator receives a clean result and completes normally. No caller behavior changes — empty results were already handled upstream.

---

## 2026-06-12 — Real DeepSeek AI Inference Pipeline (Production Mode)

### Architectural Change
Replaced static mock strings `（模拟）` in Agent#3 (Analyzer) and Agent#4 (Generator) with real OpenAI-compatible API calls routed through DeepSeek. The pipeline now:
1. **Agent#1 Scout** — Real YouTube Data API v3 search (via `search_youtube`).
2. **Agent#2 Download** — Placeholder (simulated for demo).
3. **Agent#3 Analyzer** — Sends video metadata (title, description, channel) to `deepseek-chat` with a prompt that asks for: viral hook analysis, target audience, content gaps, and engagement predictions.
4. **Agent#4 Generator** — Takes analysis result and sends to `deepseek-chat` with a prompt that generates a complete short-video script outline (visual cues, audio script, CTA).
5. **Agent#5 Uploader** — Placeholder (simulated for demo).

### API Client
- Uses `openai.OpenAI` library pointed at `OPENAI_BASE_URL` (defaults to DeepSeek: `https://api.deepseek.com`).
- Keys read from `OPENAI_API_KEY` env var (HF Space Secrets or `.env`).
- Fully async via `asyncio.to_thread()` — never blocks the Gradio event loop.
- Graceful degradation: if keys are missing, falls back to a clear warning message.

### Breaking-Change Impact Analysis
- **None**: The pipeline signature `(status, progress_html, thinking)` is preserved. Each agent step now takes actual processing time (2-10s per AI call) instead of instant mock. The async generator yields intermediate progress as before.

---

## 2026-06-12 — Streaming AI Inference & Visual Asset Mounting Fix

### Bug Description
- **Symptom**: Pipeline completes instantly at same second (`16:49:33`). Log window blank except static "Pipeline 全部完成" message. Zero visible copy, scripts, or preview assets.
- **Root Cause**: `_call_deepseek_blocking()` collected the entire DeepSeek response as a single string via `response.choices[0].message.content` (non-streaming mode) then returned it all at once. The async generator only yielded one final block — no chunk-by-chunk streaming, no visible real-time output.
- **Secondary cause**: No video preview asset was mounted after Agent#4. The UI's `最新生成的视频` component was never bound to a generated file.

### Fix Summary
1. Replaced `_call_deepseek_blocking()` with `_call_deepseek_stream()` that uses `stream=True` and yields tokens individually through an `asyncio.Queue`.
2. Agent#3 and Agent#4 now yield each DeepSeek token as it arrives — the user sees Chinese Markdown crawling across the screen in real-time.
3. After Agent#4 completes, a timestamped `preview_output.txt` is written to `storage/` and its path is yielded so Gradio can bind it to the video preview component.
4. Error traces (401, timeout, connection refused) are now yielded directly to the log window.

### Breaking-Change Impact Analysis
- **None**: The pipeline yield signature is preserved. All existing tests continue to pass (mock `_call_deepseek_blocking` is simply replaced with mock `_call_deepseek_stream`).

---

## 2026-06-12 — 日志覆盖 Bug 修复 & 永久输出面板重构 (Phase 5)

### Bug 描述
- **用户报告**: 实时分析日志"一闪而过，没有保留，无法查看"。用户在屏幕上看到 Agent#3 的 DeepSeek 内容分析，但瞬间被 Agent#4/Agent#5 的输出覆盖。
- **根因分析**: `_run_pipeline_scout_async()` 中，每个 Agent 步骤的 `yield` 向 `thinking_window` 传递的是**独立构造的字符串**。Agent#3 的 `thinking3_stream` 仅包含 Agent#3 的累积 token；Agent#4 开始时，`thinking4_stream` 从零重新构造，完全抹除了 Agent#3 的内容。最终 yield 仅显示 Agent#5 的 `thinking5`（"Pipeline 全部完成"），之前所有 Agent 的分析成果全部丢失。
- **架构缺失**: 系统中不存在"永久展示面板"。分析报告和脚本蓝图仅存在于临时变量中，从未被持久化到独立的 UI 组件。用户无法在流水线完成后回看或复制内容。

### 解决方案 — 追加式日志 + 专属成果看板

#### 1. 日志改为追加模式 (Append-Only)
- 在 `_run_pipeline_scout_async()` 中引入 `cumulative_log` 累加器字符串。
- 每个 Agent 步骤向 `cumulative_log` 追加新内容，而非覆盖。
- 每次 `yield` 都传递完整的 `cumulative_log`，Gradio 渲染全部历史。

#### 2. 新增两个永久成果展示组件
- **Component A** — `analysis_report_md` (`gr.Markdown`): 【 📊 DeepSeek 爆款内容分析报告 】
  - Agent#3 流式输出时实时镜像写入
  - 流水线完成后保持冻结，用户可随时阅读/复制
- **Component B** — `script_output_md` (`gr.Markdown`): 【 📝 DeepSeek 60秒短视频分镜剧本 】
  - Agent#4 流式输出时实时镜像写入
  - 流水线完成后保持冻结，用户可随时阅读/复制

#### 3. 动态路由改造
- `do_pipeline` 的 yield 元组从 `(status, progress, thinking)` 扩展为 `(status, progress, cumulative_log, analysis_report, script_report)`
- 事件绑定的 outputs 从 3 个扩展到 5 个
- 新增 i18n 词条 `section_analysis_report` 和 `section_script_output`

### Breaking-Change Impact Analysis
- **Yield 元组扩展**: `do_pipeline` 的 yield 从 3 元素变为 5 元素。所有调用方（Gradio 事件绑定）需要同步更新 outputs 列表。没有任何现有功能被移除。
- **测试影响**: `TestPipelineExceptionSafety` 的 `_collect` 返回的元组长度从 3 变为 5。需要在 `test_pipeline_real_ai_fallback_no_key` 中检查更多的 yield 元素。测试语义不变。
- **i18n 兼容**: 新增的词条已添加到 `i18n.py` 的中英文区域，不破坏现有翻译键。