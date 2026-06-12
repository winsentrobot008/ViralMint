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
