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
