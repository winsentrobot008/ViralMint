# 🛡️ ViralMint 系统核心开发规范 (SDLC Meta-Rules)

- **Phase 1 (Design)**: Before modifying production code, update `docs/DEVELOPMENT_LOG.md` with the blueprint and breaking-change impact analysis.
- **Phase 2 (Coding)**: Never hardcode secret keys. Any Gradio 6.0 data flow (like Chatbot arrays) must strictly follow the `{"role": "...", "content": "..."}` dictionary schema. All network/API requests must have a hard timeout (e.g., `timeout=20.0`) and handle exceptions gracefully.
- **Phase 3 (Testing)**: Run `python -m unittest discover tests/` before every deployment. The pipeline must pass with Exit Code 0.
- **Phase 4 (Deployment)**: Push sequentially to GitHub (`origin`) and Hugging Face (`hf`) only after tests pass.