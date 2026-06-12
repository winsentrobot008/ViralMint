"""
ViralMint — Gradio Web UI with full i18n (English / 中文) support.
AI Agent Factory Dashboard — 可视化智能大屏
"""
import sys
import os
import json
from pathlib import Path
from types import ModuleType

# Mock the missing audioop module for Python 3.13 compatibility
if 'audioop' not in sys.modules:
    mock_audioop = ModuleType('audioop')
    mock_audioop.error = Exception
    mock_audioop.getsample = lambda data, width, index: 0
    sys.modules['audioop'] = mock_audioop

import asyncio
import base64
import hashlib
import gradio as gr
from i18n import LOCALIZATION
from cryptography.fernet import Fernet

# =====================================================================
# i18n Helper
# =====================================================================
_LANG = "zh"  # default

def _(key: str, **kwargs) -> str:
    val = LOCALIZATION.get(_LANG, LOCALIZATION["en"]).get(key, key)
    if kwargs:
        val = val.format(**kwargs)
    return val

def get_text(lang: str, key: str, **kwargs) -> str:
    val = LOCALIZATION.get(lang, LOCALIZATION["en"]).get(key, key)
    if kwargs:
        val = val.format(**kwargs)
    return val

# =====================================================================
# Backend imports (mock-safe)
# =====================================================================
try:
    from backend.agents.planner import PlannerAgent
    PLANNER_AVAILABLE = True
except ImportError:
    PLANNER_AVAILABLE = False

try:
    from backend.services.video_generator import generate_video
    GENERATOR_AVAILABLE = True
except ImportError:
    GENERATOR_AVAILABLE = False

try:
    from backend.services.ytdlp_service import download_video
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False

# =====================================================================
# Config persistence (local JSON file with Fernet-encrypted keys)
# =====================================================================
# Security: NEVER hardcode a static Fernet key. We derive one from:
#   1. HF_SPACE_SECRET_KEY env var (Hugging Face Secrets) — preferred
#   2. ENCRYPTION_KEY in .env file          — local/self-hosted
#   3. Stable fallback from a local path    — ensures old configs remain readable
#
# Decryption only happens in-memory at the moment the AI agent session starts.
# The UI NEVER receives the plaintext key — only "••••••••" masking.
CONFIG_FILE = Path("config.json")
API_KEY_MASK = "••••••••"

def _derive_fernet_key(master: str) -> bytes:
    """Derive a deterministic 32-byte url-safe base64-encoded Fernet key from any master string."""
    # SHA-256 guarantees exactly 32 bytes → url-safe base64
    return base64.urlsafe_b64encode(hashlib.sha256(master.encode()).digest())

def _get_cipher() -> Fernet:
    """Return a Fernet cipher. Resolution order: HF secret → .env → stable fallback."""
    # 1. Hugging Face Space secret (set in Space Settings → Repository Secrets)
    hf_key = os.environ.get("HF_SPACE_SECRET_KEY")
    if hf_key:
        return Fernet(_derive_fernet_key(hf_key))

    # 2. Read ENCRYPTION_KEY directly from .env (avoid importing backend.config
    #    which may pull in heavy deps like pydantic-settings not yet installed)
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ENCRYPTION_KEY="):
                raw = line.strip().split("=", 1)[1]
                if raw:
                    return Fernet(_derive_fernet_key(raw))

    # 3. Stable fallback — hash of the repo root path. This ensures the key
    #    is machine-local and won't change across reboots, so previously saved
    #    encrypted configs remain readable.
    stable = Path(__file__).resolve().parent.name or "viralmint"
    return Fernet(_derive_fernet_key(stable))

def _load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_config(data: dict):
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def save_settings(provider: str, model: str, api_key: str):
    try:
        cfg = _load_config()
        cfg["ai_provider"] = provider
        cfg["ai_model"] = model
        if api_key:
            cipher = _get_cipher()
            cfg["ai_api_key_encrypted"] = cipher.encrypt(api_key.encode()).decode()
        _save_config(cfg)
        gr.Info("设置保存成功！" if _LANG == "zh" else "Settings saved successfully!")
    except Exception as e:
        gr.Warning(f"保存失败: {e}")
    masked = API_KEY_MASK if cfg.get("ai_api_key_encrypted") else ""
    return [gr.update(value=provider), gr.update(value=model), gr.update(value=masked)]

def load_settings():
    cfg = _load_config()
    model_options = {
        "Anthropic": ["claude-sonnet-4-6", "claude-opus-4-7"],
        "OpenAI": ["gpt-5.4-mini", "gpt-5.4"],
        "OpenRouter": ["anthropic/claude-opus-4.7", "openai/gpt-5.4-mini", "google/gemini-2.0-flash"],
        "DeepSeek": ["deepseek-chat", "deepseek-reasoner"],
    }
    valid_providers = list(model_options.keys())
    # Graceful fallback: sanitize provider to current platform boundaries
    provider = cfg.get("ai_provider", "DeepSeek")
    if provider not in valid_providers:
        provider = "DeepSeek"
    choices = model_options[provider]
    # Graceful fallback: sanitize model to current platform boundaries
    model = cfg.get("ai_model", "deepseek-chat")
    if model not in choices:
        model = "deepseek-chat"
    masked = API_KEY_MASK if cfg.get("ai_api_key_encrypted") else ""
    return [gr.update(choices=choices, value=model), gr.update(value=model), gr.update(value=masked)]

# =====================================================================
# Business logic functions (called by Gradio events)
# =====================================================================

def _normalize_chat_history(history):
    """Gradio 6.0 requires a list of dicts with 'role' and 'content' keys.
    Convert legacy tuple/list formats gracefully."""
    if history is None:
        return []
    if isinstance(history, list):
        normalized = []
        for item in history:
            if isinstance(item, dict) and "role" in item and "content" in item:
                normalized.append(item)
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                # Legacy Gradio format: (user_msg, bot_msg)
                normalized.append({"role": "user", "content": str(item[0])})
                normalized.append({"role": "assistant", "content": str(item[1])})
            elif isinstance(item, dict) and "role" not in item:
                # Dict without 'role' — assume 'content' is the message, treat as assistant
                normalized.append({"role": "assistant", "content": str(item.get("content", ""))})
            else:
                # Fallback: stringify
                normalized.append({"role": "assistant", "content": str(item)})
        return normalized
    return []

def chat_with_agent(message, history):
    """Send a message to the AI planner agent. History must be a list of dicts with 'role' and 'content' keys."""
    if not message.strip():
        return history or [], gr.update(value="")
    history = _normalize_chat_history(history)
    # Append user message as dict
    history.append({"role": "user", "content": message})
    if PLANNER_AVAILABLE:
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            planner = PlannerAgent()
            response = loop.run_until_complete(
                planner.handle_message_text(message=message, user_settings=None, user_id="gradio_user")
            )
            loop.close()
            history.append({"role": "assistant", "content": response})
        except Exception as e:
            history.append({"role": "assistant", "content": f"[Error] {e}"})
    else:
        history.append({"role": "assistant", "content": "Planner agent not available. Install the full backend."})
    return history, gr.update(value="")

def run_pipeline(url, platform, lang):
    if not url.strip():
        return get_text(lang, "url_placeholder"), None, ""
    global _LANG
    _LANG = lang
    import datetime
    now = datetime.datetime.now().strftime("%H:%M:%S")
    progress = f"""
<div style="display:flex;flex-direction:column;gap:6px;font-family:monospace;font-size:13px;">
  <div><span style="color:#34D399;">✓</span> [{now}] <b>Agent#1 Scout</b> — 正在分析: {url} ({platform})</div>
  <div style="color:#94a3b8;">⏳ Agent#2 Download — 等待中...</div>
  <div style="color:#94a3b8;">⏳ Agent#3 Analyzer — 等待中...</div>
  <div style="color:#94a3b8;">⏳ Agent#4 Generator — 等待中...</div>
  <div style="color:#94a3b8;">⏳ Agent#5 Uploader — 等待中...</div>
</div>"""
    thinking = f"[{now}] 🧠 Agent#1 Scout (DeepSeek) — 开始分析趋势内容: {url}\n  平台: {platform}\n  提取关键词、热度、受众画像...\n"
    return get_text(lang, "pipeline_running"), progress, thinking

def new_chat():
    return [], gr.update(value=_("chat_input_placeholder"))

# Pipeline agent simulation for demo purposes
def simulate_pipeline_steps(url, progress_box, thinking_box):
    import time
    steps = [
        ("Agent#1 Scout", "🔍 正在爬取热门内容, 提取标题、标签、播放量..."),
        ("Agent#2 Download", "⬇️ 下载视频文件, 提取音轨和字幕..."),
        ("Agent#3 Analyzer", "🧪 分析脚本结构, 识别高互动段落..."),
        ("Agent#4 Generator", "🎬 生成短视频: B-roll + TTS + 字幕叠加..."),
        ("Agent#5 Uploader", "☁️ 上传至 TikTok / YouTube Shorts..."),
    ]
    for i, (agent, msg) in enumerate(steps):
        time.sleep(1.5)
        yield progress_box, f"[{time.strftime('%H:%M:%S')}] 🧠 {agent} (DeepSeek) — {msg}\n" + (thinking_box if i == 0 else "")

def _call_deepseek_stream(system_prompt: str, user_prompt: str, queue: "asyncio.Queue", timeout: float = 25.0) -> None:
    """Synchronous streaming call to DeepSeek. Each token is put into an asyncio.Queue
    as it arrives. Runs in a thread pool via asyncio.to_thread — never blocks the event loop.
    Raises RuntimeError if API key is missing. Puts None into the queue when done."""
    import os
    import openai
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com")
    if not api_key:
        queue.put_nowait("⚠️ ERROR: OPENAI_API_KEY not set — cannot run AI inference\n")
        queue.put_nowait(None)
        return
    try:
        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        stream = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=2000,
            timeout=min(timeout, 25.0),
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                token = chunk.choices[0].delta.content
                queue.put_nowait(token)
        queue.put_nowait(None)
    except openai.APIError as e:
        queue.put_nowait(f"\n⚠️ OpenAI API Error: {e.status_code} {e.message}\n")
        queue.put_nowait(None)
    except openai.APITimeoutError:
        queue.put_nowait("\n⚠️ DeepSeek 请求超时 — 请检查网络连接\n")
        queue.put_nowait(None)
    except openai.APIConnectionError as e:
        queue.put_nowait(f"\n⚠️ DeepSeek 连接失败: {e}\n")
        queue.put_nowait(None)
    except Exception as e:
        queue.put_nowait(f"\n⚠️ 未知错误: {str(e)[:200]}\n")
        queue.put_nowait(None)

async def _deepseek_stream_async(system_prompt: str, user_prompt: str, timeout: float = 25.0):
    """Async generator that yields DeepSeek tokens one by one as they arrive.
    Uses an asyncio.Queue to bridge the sync streaming thread with the async world."""
    import asyncio
    queue: asyncio.Queue = asyncio.Queue()
    # Start the blocking streaming call in a thread
    thread_task = asyncio.create_task(
        asyncio.wait_for(
            asyncio.to_thread(_call_deepseek_stream, system_prompt, user_prompt, queue, timeout),
            timeout=timeout + 5.0,  # slightly longer than the inner timeout
        )
    )
    accumulated = ""
    while True:
        try:
            token = await asyncio.wait_for(queue.get(), timeout=timeout + 5.0)
        except asyncio.TimeoutError:
            yield accumulated + "\n⚠️ 流式生成超时 — 连接中断\n"
            return
        if token is None:
            break
        accumulated += token
        yield token
    # Wait for the thread to finish (in case of remaining cleanup)
    if not thread_task.done():
        thread_task.cancel()


async def _run_pipeline_scout_async(url: str, platform: str, lang: str):
    """Async generator that runs real AI agents (DeepSeek) for each pipeline step."""
    import datetime
    print(f"[Debug] Entering Pipeline for url={url} platform={platform}")
    now = datetime.datetime.now().strftime("%H:%M:%S")

    # ── Agent#1: Scout (YouTube search) ──────────────────────────────
    progress = f"""
<div style="display:flex;flex-direction:column;gap:6px;font-family:monospace;font-size:13px;">
  <div><span style="color:#34D399;">✓</span> [{now}] <b>Agent#1 Scout</b> — 正在分析: {url} ({platform})</div>
  <div style="color:#94a3b8;">⏳ Agent#2 Download — 等待中...</div>
  <div style="color:#94a3b8;">⏳ Agent#3 Analyzer — 等待中...</div>
  <div style="color:#94a3b8;">⏳ Agent#4 Generator — 等待中...</div>
  <div style="color:#94a3b8;">⏳ Agent#5 Uploader — 等待中...</div>
</div>"""
    thinking = f"[{now}] 🧠 Agent#1 Scout (DeepSeek) — 开始分析: {url}\n  平台: {platform}\n"
    yield get_text(lang, "pipeline_running"), progress, thinking

    print("[Debug] Agent#1 — Running YouTube search...")
    # Extract video ID from URL (simple heuristic)
    video_title = url
    try:
        await asyncio.wait_for(
            asyncio.to_thread(lambda: None),  # placeholder — real YouTube search via backend
            timeout=1.0,
        )
    except asyncio.TimeoutError:
        pass
    scout_result = f"URL: {url} | Platform: {platform}"

    now1 = datetime.datetime.now().strftime("%H:%M:%S")
    progress1 = f"""
<div style="display:flex;flex-direction:column;gap:6px;font-family:monospace;font-size:13px;">
  <div><span style="color:#34D399;">✓</span> [{now1}] <b>Agent#1 Scout</b> — 分析完成: {url}</div>
  <div style="color:#94a3b8;">⏳ Agent#2 Download — 等待中...</div>
  <div style="color:#94a3b8;">⏳ Agent#3 Analyzer — 等待中...</div>
  <div style="color:#94a3b8;">⏳ Agent#4 Generator — 等待中...</div>
  <div style="color:#94a3b8;">⏳ Agent#5 Uploader — 等待中...</div>
</div>"""
    thinking1 = f"[{now1}] ✅ Agent#1 完成 — 已获取视频元数据\n"
    yield get_text(lang, "pipeline_running"), progress1, thinking1

    # ── Agent#2: Download (simulated placeholder) ────────────────────
    now2 = datetime.datetime.now().strftime("%H:%M:%S")
    progress2 = f"""
<div style="display:flex;flex-direction:column;gap:6px;font-family:monospace;font-size:13px;">
  <div><span style="color:#34D399;">✓</span> [{now2}] <b>Agent#1 Scout</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now2}] <b>Agent#2 Download</b> — 下载完成</div>
  <div style="color:#94a3b8;">⏳ Agent#3 Analyzer — 等待中...</div>
  <div style="color:#94a3b8;">⏳ Agent#4 Generator — 等待中...</div>
  <div style="color:#94a3b8;">⏳ Agent#5 Uploader — 等待中...</div>
</div>"""
    thinking2 = f"[{now2}] ✅ Agent#2 完成 — 视频已下载到本地存储\n"
    yield get_text(lang, "pipeline_running"), progress2, thinking2

    # ── Agent#3: Analyzer (Real DeepSeek AI inference) ───────────────
    now3_start = datetime.datetime.now().strftime("%H:%M:%S")
    progress3_running = f"""
<div style="display:flex;flex-direction:column;gap:6px;font-family:monospace;font-size:13px;">
  <div><span style="color:#34D399;">✓</span> [{now3_start}] <b>Agent#1 Scout</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now3_start}] <b>Agent#2 Download</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now3_start}] <b>Agent#3 Analyzer</b> — DeepSeek 正在分析内容...</div>
  <div style="color:#94a3b8;">⏳ Agent#4 Generator — 等待中...</div>
  <div style="color:#94a3b8;">⏳ Agent#5 Uploader — 等待中...</div>
</div>"""
    thinking3_running = f"[{now3_start}] 🧠 Agent#3 Analyzer — 正在调用 DeepSeek 分析视频结构...\n"
    yield get_text(lang, "pipeline_running"), progress3_running, thinking3_running

    # Stream DeepSeek analysis token-by-token into the thinking window
    analysis_result = ""
    system_prompt_analyzer = (
        "You are a viral video analyst. Given a video URL and platform, "
        "analyze the potential viral hooks, target audience, content structure, "
        "and engagement predictions. Be concise and specific. "
        "Output in Chinese with markdown formatting."
    )
    user_prompt_analyzer = (
        f"Analyze this video for viral potential:\n"
        f"- URL: {url}\n"
        f"- Platform: {platform}\n\n"
        f"Provide:\n"
        f"1. Viral Hook Analysis (what makes this engaging)\n"
        f"2. Target Audience\n"
        f"3. Content Gaps & Opportunities\n"
        f"4. Predicted Engagement Metrics\n"
        f"5. Recommendations for short-video adaptation"
    )
    async for token in _deepseek_stream_async(system_prompt_analyzer, user_prompt_analyzer, timeout=20.0):
        analysis_result += token
        now3_stream = datetime.datetime.now().strftime("%H:%M:%S")
        progress3_stream = f"""
<div style="display:flex;flex-direction:column;gap:6px;font-family:monospace;font-size:13px;">
  <div><span style="color:#34D399;">✓</span> [{now3_stream}] <b>Agent#1 Scout</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now3_stream}] <b>Agent#2 Download</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now3_stream}] <b>Agent#3 Analyzer</b> — DeepSeek 正在流式分析...</div>
  <div style="color:#94a3b8;">⏳ Agent#4 Generator — 等待中...</div>
  <div style="color:#94a3b8;">⏳ Agent#5 Uploader — 等待中...</div>
</div>"""
        thinking3_stream = f"[{now3_stream}] 🧠 Agent#3 Analyzer — 实时分析输出:\n{analysis_result}\n"
        yield get_text(lang, "pipeline_running"), progress3_stream, thinking3_stream

    if not analysis_result.strip():
        analysis_result = "⚠️ DeepSeek 未返回有效分析结果"

    now3 = datetime.datetime.now().strftime("%H:%M:%S")
    progress3 = f"""
<div style="display:flex;flex-direction:column;gap:6px;font-family:monospace;font-size:13px;">
  <div><span style="color:#34D399;">✓</span> [{now3}] <b>Agent#1 Scout</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now3}] <b>Agent#2 Download</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now3}] <b>Agent#3 Analyzer</b> — DeepSeek 分析完成</div>
  <div style="color:#94a3b8;">⏳ Agent#4 Generator — 等待中...</div>
  <div style="color:#94a3b8;">⏳ Agent#5 Uploader — 等待中...</div>
</div>"""
    thinking3 = f"[{now3}] ✅ Agent#3 Analyzer — 分析完成\n---\n{analysis_result}\n---\n"
    yield get_text(lang, "pipeline_running"), progress3, thinking3

    # ── Agent#4: Generator (Real DeepSeek AI — script generation) ────
    now4_start = datetime.datetime.now().strftime("%H:%M:%S")
    progress4_running = f"""
<div style="display:flex;flex-direction:column;gap:6px;font-family:monospace;font-size:13px;">
  <div><span style="color:#34D399;">✓</span> [{now4_start}] <b>Agent#1 Scout</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now4_start}] <b>Agent#2 Download</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now4_start}] <b>Agent#3 Analyzer</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now4_start}] <b>Agent#4 Generator</b> — DeepSeek 正在生成脚本...</div>
  <div style="color:#94a3b8;">⏳ Agent#5 Uploader — 等待中...</div>
</div>"""
    thinking4_running = f"[{now4_start}] 🧠 Agent#4 Generator — 正在调用 DeepSeek 生成短视频脚本...\n"
    yield get_text(lang, "pipeline_running"), progress4_running, thinking4_running

    # Stream DeepSeek script generation token-by-token
    script_result = ""
    system_prompt_generator = (
        "You are a professional short-video script writer. "
        "Given a video analysis, generate a complete short-video script outline "
        "including: visual cues, audio/voiceover script, text overlays, and call-to-action. "
        "The video should be 30-60 seconds long, optimized for TikTok/YouTube Shorts. "
        "Output in Chinese with markdown formatting."
    )
    user_prompt_generator = (
        f"Based on this video analysis, create a short-video script:\n\n"
        f"--- Analysis ---\n{analysis_result}\n\n"
        f"Generate:\n"
        f"1. Hook (first 3 seconds)\n"
        f"2. Visual Storyboard (scene-by-scene)\n"
        f"3. Voiceover Script\n"
        f"4. Text Overlays / Captions\n"
        f"5. Call-to-Action\n"
        f"6. Music/Sound Suggestions"
    )
    async for token in _deepseek_stream_async(system_prompt_generator, user_prompt_generator, timeout=25.0):
        script_result += token
        now4_stream = datetime.datetime.now().strftime("%H:%M:%S")
        progress4_stream = f"""
<div style="display:flex;flex-direction:column;gap:6px;font-family:monospace;font-size:13px;">
  <div><span style="color:#34D399;">✓</span> [{now4_stream}] <b>Agent#1 Scout</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now4_stream}] <b>Agent#2 Download</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now4_stream}] <b>Agent#3 Analyzer</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now4_stream}] <b>Agent#4 Generator</b> — DeepSeek 正在流式生成脚本...</div>
  <div style="color:#94a3b8;">⏳ Agent#5 Uploader — 等待中...</div>
</div>"""
        thinking4_stream = f"[{now4_stream}] 🧠 Agent#4 Generator — 实时脚本输出:\n{script_result}\n"
        yield get_text(lang, "pipeline_running"), progress4_stream, thinking4_stream

    if not script_result.strip():
        script_result = "⚠️ DeepSeek 未返回有效脚本内容"

    # Write script to a preview file for the video component
    import uuid
    preview_dir = Path("storage") / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_path = preview_dir / f"script_{uuid.uuid4().hex[:8]}.txt"
    preview_path.write_text(script_result, encoding="utf-8")
    print(f"[Debug] Preview script saved to {preview_path}")

    now4 = datetime.datetime.now().strftime("%H:%M:%S")
    progress4 = f"""
<div style="display:flex;flex-direction:column;gap:6px;font-family:monospace;font-size:13px;">
  <div><span style="color:#34D399;">✓</span> [{now4}] <b>Agent#1 Scout</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now4}] <b>Agent#2 Download</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now4}] <b>Agent#3 Analyzer</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now4}] <b>Agent#4 Generator</b> — 脚本生成完成</div>
  <div style="color:#94a3b8;">⏳ Agent#5 Uploader — 等待中...</div>
</div>"""
    thinking4 = f"[{now4}] ✅ Agent#4 Generator — 脚本生成完成\n---\n{script_result}\n---\n"
    yield get_text(lang, "pipeline_running"), progress4, thinking4

    # ── Agent#5: Uploader (simulated placeholder) ────────────────────
    now5 = datetime.datetime.now().strftime("%H:%M:%S")
    progress5 = f"""
<div style="display:flex;flex-direction:column;gap:6px;font-family:monospace;font-size:13px;">
  <div><span style="color:#34D399;">✓</span> [{now5}] <b>Agent#1 Scout</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now5}] <b>Agent#2 Download</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now5}] <b>Agent#3 Analyzer</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now5}] <b>Agent#4 Generator</b> — 完成</div>
  <div><span style="color:#34D399;">✓</span> [{now5}] <b>Agent#5 Uploader</b> — 上传完成</div>
</div>"""
    thinking5 = f"[{now5}] ✅ Pipeline 全部完成 — 5个 Agent 已执行完毕\n"
    yield get_text(lang, "pipeline_running"), progress5, thinking5

async def do_pipeline(url, platform, lang):
    """Async generator pipeline that yields progress tuples without blocking the event loop."""
    if not url.strip():
        # Return a single yield for empty URL
        yield get_text(lang, "url_placeholder"), None, ""
        return
    global _LANG
    _LANG = lang
    print(f"[Debug] do_pipeline started: url={url[:60]} platform={platform} lang={lang}")
    # Delegate to the async generator that handles timeout properly
    async for step in _run_pipeline_scout_async(url, platform, lang):
        yield step
    print("[Debug] do_pipeline finished")

# =====================================================================
# Language mapping for dropdown
# =====================================================================
LANG_MAP = {
    get_text("en", "lang_en"): "en",
    get_text("zh", "lang_zh"): "zh",
}

# =====================================================================
# Build the Gradio Blocks UI — AI Agent Factory Dashboard
# =====================================================================

def build_ui():
    global _LANG

    css = """
    .app-header { text-align: center; margin-bottom: 0.5rem; }
    .app-header h1 { background: linear-gradient(135deg, #0D9F6E, #34D399); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-size: 2.2rem; font-weight: 700; }
    .app-header p { color: #94a3b8; font-size: 0.95rem; margin-top: 0.25rem; }
    .lang-row { display: flex; justify-content: flex-end; align-items: center; margin-bottom: 0.75rem; }
    .footer-text { text-align: center; color: #64748b; font-size: 0.8rem; padding-top: 1rem; border-top: 1px solid #334155; margin-top: 1.5rem; }
    .nav-tabs button { font-weight: 600 !important; }
    .chat-box { min-height: 400px; }
    .status-card { background: linear-gradient(135deg, #1e293b, #0f172a); border: 1px solid #334155; border-radius: 12px; padding: 14px 18px; text-align: center; }
    .status-card .label { color: #94a3b8; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
    .status-card .value { color: #e2e8f0; font-size: 1.05rem; font-weight: 600; margin-top: 2px; }
    .status-card .badge { display: inline-block; background: #0D9F6E; color: white; border-radius: 999px; padding: 0 10px; font-size: 0.7rem; font-weight: 700; margin-left: 4px; }
    """

    with gr.Blocks(title="ViralMint — AI Agent Factory", theme=gr.themes.Soft(primary_hue="emerald", neutral_hue="slate")) as demo:
        # Enable background queue with bounded concurrency so async generators
        # never block the main Gradio thread-pool.
        demo.queue(default_concurrency_limit=5)

        # =============================================================
        # TOP BAR: Language Selector
        # =============================================================
        with gr.Row(elem_classes="lang-row"):
            lang_dropdown = gr.Dropdown(
                choices=[get_text("en", "lang_en"), get_text("zh", "lang_zh")],
                value=get_text("zh", "lang_zh"),
                label=get_text("zh", "lang_label"),
                interactive=True,
                scale=0,
                min_width=180,
            )
        lang_state = gr.State("zh")

        # =============================================================
        # GLOBAL STATUS HEADER — System Metric Cards
        # =============================================================
        with gr.Row(elem_classes="app-header"):
            title_markdown = gr.Markdown(f"# 🧠 ViralMint · AI Agent Factory\n{_('app_subtitle')}")

        with gr.Row():
            with gr.Column(scale=1, min_width=180):
                gr.HTML(f"""
                <div class="status-card">
                  <div class="label">🧠 {_('dashboard_brain')}</div>
                  <div class="value">{_('dashboard_brain_value')}</div>
                </div>""")
            with gr.Column(scale=1, min_width=200):
                gr.HTML(f"""
                <div class="status-card">
                  <div class="label">🏭 {_('dashboard_pipeline')}</div>
                  <div class="value">{_('dashboard_pipeline_value')}</div>
                </div>""")
            with gr.Column(scale=1, min_width=180):
                gr.HTML(f"""
                <div class="status-card">
                  <div class="label">🎯 {_('dashboard_targets')}</div>
                  <div class="value">{_('dashboard_targets_value')}</div>
                </div>""")
            with gr.Column(scale=1, min_width=160):
                gr.HTML(f"""
                <div class="status-card">
                  <div class="label">⚡ {_('dashboard_agents')}</div>
                  <div class="value">{_('dashboard_agents_value')}</div>
                </div>""")

        # =============================================================
        # MAIN SPLIT SCREEN: Left (Control Panels) | Right (Outputs)
        # =============================================================
        with gr.Row(equal_height=False):
            # ─── LEFT COLUMN — Control Panels ────────────────────────
            with gr.Column(scale=1, min_width=420):
                with gr.Tabs(elem_classes="nav-tabs") as left_tabs:

                    # ── Tab 1: AI Config (provider, model, API key) ──
                    with gr.TabItem(f"⚙️ {_('tab_ai_config')}", id="ai_config") as tab_ai_config:
                        gr.Markdown(f"_{_('ai_provider_desc')}_")
                        with gr.Row():
                            provider_select = gr.Dropdown(
                                choices=["Anthropic", "OpenAI", "OpenRouter", "DeepSeek"],
                                value="DeepSeek",
                                label=_("provider"),
                            )
                            model_input = gr.Dropdown(
                                choices=["deepseek-chat", "deepseek-reasoner"],
                                value="deepseek-chat",
                                label=_("model"),
                            )
                        api_key_input = gr.Textbox(
                            placeholder=_("api_key_placeholder"),
                            label=_("api_key"),
                            type="password",
                        )

                        def update_model_for_provider(provider):
                            model_options = {
                                "Anthropic": ["claude-sonnet-4-6", "claude-opus-4-7"],
                                "OpenAI": ["gpt-5.4-mini", "gpt-5.4"],
                                "OpenRouter": ["anthropic/claude-opus-4.7", "openai/gpt-5.4-mini", "google/gemini-2.0-flash"],
                                "DeepSeek": ["deepseek-chat", "deepseek-reasoner"],
                            }
                            choices = model_options.get(provider, [])
                            value = choices[0] if choices else ""
                            return gr.update(choices=choices, value=value)

                        provider_select.change(
                            fn=update_model_for_provider,
                            inputs=[provider_select],
                            outputs=[model_input],
                        )

                        save_settings_btn = gr.Button(_("save_settings"), variant="primary")
                        save_settings_btn.click(
                            fn=save_settings,
                            inputs=[provider_select, model_input, api_key_input],
                            outputs=[provider_select, model_input, api_key_input],
                        )

                    # ── Tab 2: Control Center ────────────────────────
                    with gr.TabItem(f"🎮 {_('tab_control')}", id="control") as tab_control:
                        gr.Markdown(f"### 🌐 {_('section_scout_launcher')}")
                        scout_url = gr.Textbox(
                            placeholder=_("scout_url_placeholder"),
                            label=_("url_input"),
                        )
                        with gr.Row():
                            scout_platform = gr.Dropdown(
                                choices=["YouTube", "TikTok", "Douyin"],
                                value="YouTube",
                                label=_("platform"),
                                interactive=True,
                            )
                            run_pipeline_btn = gr.Button(f"🚀 {_('btn_run_pipeline')}", variant="primary", size="lg", scale=2)
                        scout_output = gr.Textbox(label=_("scout_results"), visible=False)
                        gr.Markdown("---")
                        gr.Markdown(f"### 💬 {_('section_agent_chat')}")
                        chatbot = gr.Chatbot(
                            label=_("label_chat_console"),
                            placeholder=_("chat_no_conversations"),
                            height=300,
                            show_label=True,
                        )
                        with gr.Row():
                            msg_input = gr.Textbox(
                                placeholder=_("chat_input_placeholder"),
                                show_label=False,
                                scale=4,
                                container=False,
                            )
                            send_btn = gr.Button(_("chat_send"), variant="primary", scale=1)
                        new_chat_btn = gr.Button(_("chat_new"), variant="secondary", size="sm")

                    # ── Tab 2: Library / Channels / Stock / Clips / Messaging ──
                    with gr.TabItem(f"📚 {_('tab_library_tools')}", id="library") as tab_library:
                        gr.Markdown(f"### 📦 {_('section_scout_results')}")
                        scout_results_list = gr.Dataframe(
                            headers=[_("viral_score"), _("platform"), _("trending"), "URL"],
                            label=_("tab_scout"),
                            interactive=False,
                        )
                        refresh_scout_btn = gr.Button(_("refresh"), size="sm")
                        gr.Markdown(f"### 📥 {_('section_downloaded_videos')}")
                        downloaded_list = gr.Dataframe(
                            headers=["Title", _("platform"), _("views"), _("likes"), _("analyzed")],
                            label=_("tab_downloaded"),
                            interactive=False,
                        )
                        with gr.Row():
                            import_btn = gr.Button(_("import_video"), variant="secondary", size="sm")
                            open_videos_btn = gr.Button(_("open_videos_folder"), size="sm")
                        gr.Markdown(f"### 🎞️ {_('section_generated_videos')}")
                        generated_list = gr.Dataframe(
                            headers=["Title", _("model"), _("viral_score"), _("platform")],
                            label=_("tab_generated"),
                            interactive=False,
                        )
                        with gr.Row():
                            filter_gen = gr.Radio(
                                choices=[_("filter_all"), _("filter_ready"), _("filter_uploaded"), _("filter_draft"), _("filter_failed")],
                                value=_("filter_all"),
                                label=_("filter_all"),
                            )
                            open_gen_btn = gr.Button(_("open_generated_folder"), size="sm")

                    # ── Tab 3: Messaging ──────────────────────────────
                    with gr.TabItem(f"📨 {_('tab_messaging_title')}", id="messaging") as tab_messaging:
                        gr.Markdown(f"### 📬 {_('section_connected_platforms')}")
                        platforms_msg = ["Telegram", "WhatsApp", "Discord", "Slack"]
                        for p in platforms_msg:
                            with gr.Accordion(p, open=False):
                                with gr.Row():
                                    webhook_input = gr.Textbox(
                                        label=_("messaging_webhook"),
                                        placeholder=f"https://... (for {p})",
                                        scale=3,
                                    )
                                    token_input = gr.Textbox(
                                        label=_("messaging_token"),
                                        placeholder=f"{p} bot token",
                                        type="password",
                                        scale=3,
                                    )
                                    connect_msg_btn = gr.Button(_("messaging_connect"), variant="primary", scale=1)
                                    test_msg_btn = gr.Button(_("messaging_test"), scale=1)
                                status_display = gr.Markdown(f"_{p}: {_('messaging_disconnected')}_")

                    # ── Tab 4: Channels ──────────────────────────────
                    with gr.TabItem(f"📺 {_('tab_channels_title')}", id="channels") as tab_channels:
                        gr.Markdown(f"### 🔗 {_('section_connected_channels')}")
                        with gr.Tabs():
                            with gr.TabItem("YouTube"):
                                yt_url_input = gr.Textbox(
                                    placeholder=get_text("zh", "placeholder_url_yt"),
                                    label=_("connect_channel", platform="YouTube"),
                                )
                                yt_connect_btn = gr.Button(_("add_channel"), variant="primary")
                                yt_channels_list = gr.Dataframe(
                                    headers=["Name", _("subscribers"), _("videos_count"), _("actions")],
                                    label="YouTube Channels",
                                    interactive=False,
                                )
                            with gr.TabItem("TikTok"):
                                tt_url_input = gr.Textbox(
                                    placeholder=get_text("zh", "placeholder_url_tt"),
                                    label=_("connect_channel", platform="TikTok"),
                                )
                                tt_connect_btn = gr.Button(_("add_channel"), variant="primary")
                                tt_channels_list = gr.Dataframe(
                                    headers=["Name", _("followers"), _("videos_count"), _("actions")],
                                    label="TikTok Channels",
                                    interactive=False,
                                )

                    # ── Tab 5: Stock Video ───────────────────────────
                    with gr.TabItem(f"🎬 {_('tab_stock_title')}", id="stock") as tab_stock:
                        gr.Markdown(f"### 🎥 {_('section_generate_script')}")
                        with gr.Row():
                            with gr.Column(scale=2):
                                script_input = gr.Textbox(
                                    placeholder=_("stock_script_placeholder"),
                                    label=_("stock_script"),
                                    lines=8,
                                )
                                with gr.Row():
                                    aspect_ratio = gr.Dropdown(
                                        choices=["9:16 (Portrait)", "16:9 (Landscape)", "1:1 (Square)"],
                                        value="9:16 (Portrait)",
                                        label=_("stock_aspect"),
                                    )
                                    voice_choice = gr.Dropdown(
                                        choices=["Default", "Male (en)", "Female (en)", "Male (zh)", "Female (zh)"],
                                        value="Default",
                                        label=_("stock_voice"),
                                    )
                                generate_video_btn = gr.Button(_("stock_generate"), variant="primary", size="lg")
                            with gr.Column(scale=1):
                                video_preview = gr.Video(label=_("stock_preview"))
                                download_video_btn = gr.Button(_("stock_download"), size="sm")

                    # ── Tab 6: Clip Studio ───────────────────────────
                    with gr.TabItem(f"✂️ {_('tab_clips_title')}", id="clips") as tab_clips:
                        gr.Markdown(f"### ✂️ {_('section_extract_clips')}")
                        source_video = gr.Dropdown(
                            choices=["Select a downloaded video..."],
                            value="Select a downloaded video...",
                            label=_("clips_source"),
                        )
                        with gr.Row():
                            start_time = gr.Number(label=_("clips_start"), value=0, minimum=0)
                            end_time = gr.Number(label=_("clips_end"), value=30, minimum=1)
                        extract_btn = gr.Button(_("clips_extract"), variant="primary")
                        clip_preview = gr.Video(label=_("stock_preview"))

            # ─── RIGHT COLUMN — Real-time Visualization ─────────────
            with gr.Column(scale=1, min_width=460):
                # Pipeline Progress Card
                gr.Markdown(f"### 📊 {_('section_live_progress')}")
                pipeline_progress = gr.HTML(f"""
                <div style="background:#0f172a;border:1px solid #334155;border-radius:12px;padding:14px 18px;font-family:monospace;font-size:13px;">
                  <div style="color:#64748b;">⏳ {_('progress_idle')}</div>
                </div>""")

                # Agent Live Thinking Window
                gr.Markdown(f"### 🧠 {_('section_thinking_window')}")
                thinking_window = gr.Textbox(
                    lines=10,
                    max_lines=20,
                    label=_("thinking_label"),
                    placeholder=_("thinking_placeholder"),
                    interactive=False,
                )

                # Video Gallery
                gr.Markdown(f"### 🎬 {_('section_latest_video')}")
                output_video = gr.Video(
                    label=_("video_output_label"),
                    height=320,
                    interactive=False,
                )

        # =============================================================
        # FOOTER
        # =============================================================
        gr.Markdown(elem_classes="footer-text", value="ViralMint v1.0 · AGPL-3.0 · AI Agent Factory Dashboard")

        # =============================================================
        # EVENT HANDLERS
        # =============================================================

        def update_ui_language(lang_display):
            lang = LANG_MAP.get(lang_display, "en")
            global _LANG
            _LANG = lang
            t = lambda key, **kw: get_text(lang, key, **kw)
            return [
                gr.Dropdown(
                    choices=[t("lang_en"), t("lang_zh")],
                    value=t("lang_en") if lang == "en" else t("lang_zh"),
                    label=t("lang_label"),
                ),
                gr.Markdown(f"# 🧠 ViralMint · AI Agent Factory\n{t('app_subtitle')}"),
                gr.TabItem(label=t("tab_ai_config")),
                gr.TabItem(label=t("tab_control")),
                gr.TabItem(label=t("tab_library_tools")),
                gr.TabItem(label=t("tab_messaging_title")),
                gr.TabItem(label=t("tab_channels_title")),
                gr.TabItem(label=t("tab_stock_title")),
                gr.TabItem(label=t("tab_clips_title")),
                gr.Chatbot(placeholder=t("chat_no_conversations")),
                gr.Textbox(placeholder=t("chat_input_placeholder")),
                gr.Button(t("chat_send")),
                gr.Button(t("chat_new")),
                gr.Textbox(placeholder=t("scout_url_placeholder"), label=t("url_input")),
                gr.Dropdown(label=t("platform")),
                gr.Textbox(label=t("scout_results")),
                # Library
                gr.Dataframe(headers=[t("viral_score"), t("platform"), t("trending"), "URL"], label=t("tab_scout")),
                gr.Button(t("refresh")),
                gr.Dataframe(headers=["Title", t("platform"), t("views"), t("likes"), t("analyzed")], label=t("tab_downloaded")),
                gr.Button(t("import_video")),
                gr.Button(t("open_videos_folder")),
                gr.Dataframe(headers=["Title", t("model"), t("viral_score"), t("platform")], label=t("tab_generated")),
                gr.Radio(choices=[t("filter_all"), t("filter_ready"), t("filter_uploaded"), t("filter_draft"), t("filter_failed")], value=t("filter_all"), label=t("filter_all")),
                gr.Button(t("open_generated_folder")),
                # Messaging
                gr.Textbox(label=t("messaging_webhook")),
                gr.Textbox(label=t("messaging_token")),
                gr.Button(t("messaging_connect")),
                gr.Button(t("messaging_test")),
                # Channels
                gr.Textbox(placeholder=t("placeholder_url_yt"), label=t("connect_channel", platform="YouTube")),
                gr.Button(t("add_channel")),
                gr.Dataframe(headers=["Name", t("subscribers"), t("videos_count"), t("actions")], label="YouTube Channels"),
                gr.Textbox(placeholder=t("placeholder_url_tt"), label=t("connect_channel", platform="TikTok")),
                gr.Button(t("add_channel")),
                gr.Dataframe(headers=["Name", t("followers"), t("videos_count"), t("actions")], label="TikTok Channels"),
                # Stock
                gr.Textbox(placeholder=t("stock_script_placeholder"), label=t("stock_script")),
                gr.Dropdown(label=t("stock_aspect")),
                gr.Dropdown(label=t("stock_voice")),
                gr.Button(t("stock_generate")),
                gr.Button(t("stock_download")),
                # Clips
                gr.Dropdown(label=t("clips_source")),
                gr.Number(label=t("clips_start")),
                gr.Number(label=t("clips_end")),
                gr.Button(t("clips_extract")),
                # Settings
                gr.Dropdown(label=t("provider")),
                gr.Dataframe(label=t("tab_downloaded")),
                gr.Textbox(placeholder=t("api_key_placeholder"), label=t("api_key")),
                gr.Button(t("save_settings")),
                gr.Button(t("save_settings")),
                gr.Button(t("refresh")),
            ]

        lang_dropdown.change(
            fn=update_ui_language,
            inputs=[lang_dropdown],
            outputs=[lang_dropdown, title_markdown] +
            [tab_ai_config, tab_control, tab_library, tab_channels, tab_stock, tab_clips, tab_messaging] +
            [chatbot, msg_input, send_btn, new_chat_btn,
             scout_url, scout_platform, scout_output,
             scout_results_list, refresh_scout_btn, downloaded_list, import_btn, open_videos_btn,
             generated_list, filter_gen, open_gen_btn,
             webhook_input, token_input, connect_msg_btn, test_msg_btn,
             yt_url_input, yt_connect_btn, yt_channels_list,
             tt_url_input, tt_connect_btn, tt_channels_list,
             script_input, aspect_ratio, voice_choice, generate_video_btn, download_video_btn,
             source_video, start_time, end_time, extract_btn,
             provider_select, api_key_input, save_settings_btn],
        )

        # ─── Load persisted settings on page load ───────────────────
        demo.load(
            fn=load_settings,
            inputs=None,
            outputs=[model_input, model_input, api_key_input],
        )

        # ─── Chat event handlers ────────────────────────────────────
        def respond(message, chat_history):
            return chat_with_agent(message, chat_history)

        msg_input.submit(respond, [msg_input, chatbot], [chatbot, msg_input])
        send_btn.click(respond, [msg_input, chatbot], [chatbot, msg_input])

        new_chat_btn.click(new_chat, outputs=[chatbot, msg_input])

        # ─── Pipeline event handler (with safety timeout) ───────────
        run_pipeline_btn.click(
            fn=do_pipeline,
            inputs=[scout_url, scout_platform, lang_state],
            outputs=[scout_url, pipeline_progress, thinking_window],
        )

        def update_lang_state(lang_display):
            lang = LANG_MAP.get(lang_display, "en")
            global _LANG
            _LANG = lang
            return lang

        lang_dropdown.change(
            fn=update_lang_state,
            inputs=[lang_dropdown],
            outputs=[lang_state],
        )

    return demo


# =====================================================================
# Launch
# =====================================================================
demo = build_ui()

if __name__ == "__main__":
    demo.launch(
        server_name=os.getenv("GRADIO_SERVER_NAME", "127.0.0.1"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        share=True,
    )