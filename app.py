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
CONFIG_FILE = Path("config.json")
API_KEY_MASK = "••••••••"

def _get_cipher() -> Fernet:
    from backend.config import settings
    return Fernet(settings.ENCRYPTION_KEY.encode())

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
    provider = cfg.get("ai_provider", "Anthropic")
    model = cfg.get("ai_model", "claude-sonnet-4-6")
    masked = API_KEY_MASK if cfg.get("ai_api_key_encrypted") else ""
    model_options = {
        "Anthropic": ["claude-sonnet-4-6", "claude-opus-4-7"],
        "OpenAI": ["gpt-5.4-mini", "gpt-5.4"],
        "OpenRouter": ["anthropic/claude-opus-4.7", "openai/gpt-5.4-mini", "google/gemini-2.0-flash"],
        "DeepSeek": ["deepseek-chat", "deepseek-reasoner"],
    }
    choices = model_options.get(provider, ["claude-sonnet-4-6", "claude-opus-4-7"])
    return [gr.update(choices=choices, value=model), gr.update(value=model), gr.update(value=masked)]

# =====================================================================
# Business logic functions (called by Gradio events)
# =====================================================================

def chat_with_agent(message, history):
    if not message.strip():
        return history, gr.update(value="")
    history = history or []
    history.append((message, None))
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
            history[-1] = (message, response)
        except Exception as e:
            history[-1] = (message, f"[Error] {e}")
    else:
        history[-1] = (message, "Planner agent not available. Install the full backend.")
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
                gr.HTML("""
                <div class="status-card">
                  <div class="label">🧠 Active Brain</div>
                  <div class="value">DeepSeek <span style="color:#34D399;font-size:1.2rem;">🟢</span></div>
                </div>""")
            with gr.Column(scale=1, min_width=200):
                gr.HTML("""
                <div class="status-card">
                  <div class="label">🏭 Pipeline Mode</div>
                  <div class="value">Automated Short-Video Factory</div>
                </div>""")
            with gr.Column(scale=1, min_width=180):
                gr.HTML("""
                <div class="status-card">
                  <div class="label">🎯 Target Platforms</div>
                  <div class="value">TikTok / YouTube Shorts</div>
                </div>""")
            with gr.Column(scale=1, min_width=160):
                gr.HTML("""
                <div class="status-card">
                  <div class="label">⚡ Agent Status</div>
                  <div class="value">5 / 5 <span class="badge">READY</span></div>
                </div>""")

        # =============================================================
        # MAIN SPLIT SCREEN: Left (Control Panels) | Right (Outputs)
        # =============================================================
        with gr.Row(equal_height=False):
            # ─── LEFT COLUMN — Control Panels ────────────────────────
            with gr.Column(scale=1, min_width=420):
                with gr.Tabs(elem_classes="nav-tabs") as left_tabs:

                    # ── Tab 1: Control Center ────────────────────────
                    with gr.TabItem("🎮 Control Center", id="control") as tab_control:
                        gr.Markdown("### 🌐 Trend Scout & Pipeline Launcher")
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
                            run_pipeline_btn = gr.Button("🚀 Run Full Pipeline", variant="primary", size="lg", scale=2)
                        gr.Markdown("---")
                        gr.Markdown("### 💬 Agent Chat")
                        chatbot = gr.Chatbot(
                            label="Agent Chat Console",
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
                    with gr.TabItem("📚 Library & Tools", id="library") as tab_library:
                        gr.Markdown("### 📦 Scout Results")
                        scout_results_list = gr.Dataframe(
                            headers=[_("viral_score"), _("platform"), _("trending"), "URL"],
                            label=_("tab_scout"),
                            interactive=False,
                        )
                        refresh_scout_btn = gr.Button(_("refresh"), size="sm")
                        gr.Markdown("### 📥 Downloaded Videos")
                        downloaded_list = gr.Dataframe(
                            headers=["Title", _("platform"), _("views"), _("likes"), _("analyzed")],
                            label=_("tab_downloaded"),
                            interactive=False,
                        )
                        with gr.Row():
                            import_btn = gr.Button(_("import_video"), variant="secondary", size="sm")
                            open_videos_btn = gr.Button(_("open_videos_folder"), size="sm")
                        gr.Markdown("### 🎞️ Generated Videos")
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
                    with gr.TabItem("📨 Messaging", id="messaging") as tab_messaging:
                        gr.Markdown("### 📬 Connected Platforms")
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
                    with gr.TabItem("📺 Channels", id="channels") as tab_channels:
                        gr.Markdown("### 🔗 Connected Channels")
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
                    with gr.TabItem("🎬 Stock Video", id="stock") as tab_stock:
                        gr.Markdown("### 🎥 Generate from Script")
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
                    with gr.TabItem("✂️ Clip Studio", id="clips") as tab_clips:
                        gr.Markdown("### ✂️ Extract Clips")
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
                gr.Markdown("### 📊 Live Pipeline Progress")
                pipeline_progress = gr.HTML("""
                <div style="background:#0f172a;border:1px solid #334155;border-radius:12px;padding:14px 18px;font-family:monospace;font-size:13px;">
                  <div style="color:#64748b;">⏳ Idle — waiting for pipeline trigger...</div>
                </div>""")

                # Agent Live Thinking Window
                gr.Markdown("### 🧠 Agent Live Thinking Window")
                thinking_window = gr.Textbox(
                    lines=10,
                    max_lines=20,
                    label="🤖 Agent Cross-Talk & CoT Log (智能体实时思考日志)",
                    placeholder="Agent reasoning will stream here in real time...",
                    interactive=False,
                )

                # Video Gallery
                gr.Markdown("### 🎬 Latest Minted Video Output")
                output_video = gr.Video(
                    label="🎬 Latest Minted Video Output",
                    height=320,
                    interactive=False,
                )

        # =============================================================
        # SETTINGS ACCORDION (At the bottom, collapsed by default)
        # =============================================================
        with gr.Accordion("⚙️ Advanced System Configurations", open=False):
            with gr.Tabs():
                with gr.TabItem(_("ai_provider")):
                    gr.Markdown(f"_{_('ai_provider_desc')}_")
                    with gr.Row():
                        provider_select = gr.Dropdown(
                            choices=["Anthropic", "OpenAI", "OpenRouter", "DeepSeek"],
                            value="DeepSeek",
                            label=_("provider"),
                            scale=1,
                        )
                        model_input = gr.Dropdown(
                            choices=["deepseek-chat", "deepseek-reasoner"],
                            value="deepseek-chat",
                            label=_("model"),
                            scale=1,
                        )
                        api_key_input = gr.Textbox(
                            placeholder=_("api_key_placeholder"),
                            label=_("api_key"),
                            type="password",
                            scale=2,
                        )
                    save_settings_btn = gr.Button(_("save_settings"), variant="primary")

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
                    save_settings_btn.click(
                        fn=save_settings,
                        inputs=[provider_select, model_input, api_key_input],
                        outputs=[provider_select, model_input, api_key_input],
                    )

                with gr.TabItem(_("service_keys")):
                    gr.Markdown(f"_{_('service_keys_desc')}_")
                    with gr.Row():
                        yt_api_key = gr.Textbox(
                            placeholder="YouTube API Key",
                            label="YouTube",
                            type="password",
                        )
                        pexels_key = gr.Textbox(
                            placeholder="Pexels API Key",
                            label="Pexels",
                            type="password",
                        )
                    save_keys_btn = gr.Button(_("save_settings"), variant="primary")

                with gr.TabItem(_("system_health")):
                    gr.Markdown(f"## {_('system_health')}\n{_('system_health_desc')}")
                    health_output = gr.Markdown("_Check system health..._")
                    check_health_btn = gr.Button(_("refresh"))

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
                gr.TabItem(label=t("tab_chat")),
                gr.TabItem(label=t("scout_title")),
                gr.TabItem(label=t("tab_library")),
                gr.TabItem(label=t("tab_channels")),
                gr.TabItem(label=t("tab_stock")),
                gr.TabItem(label=t("tab_clips")),
                gr.TabItem(label=t("tab_settings")),
                gr.TabItem(label=t("tab_messaging")),
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
            [tab_control, tab_library, tab_channels, tab_stock, tab_clips, tab_messaging] +
            [chatbot, msg_input, send_btn, new_chat_btn,
             scout_url, scout_platform, scout_output,
             scout_results_list, refresh_scout_btn, downloaded_list, import_btn, open_videos_btn,
             generated_list, filter_gen, open_gen_btn,
             webhook_input, token_input, connect_msg_btn, test_msg_btn,
             yt_url_input, yt_connect_btn, yt_channels_list,
             tt_url_input, tt_connect_btn, tt_channels_list,
             script_input, aspect_ratio, voice_choice, generate_video_btn, download_video_btn,
             source_video, start_time, end_time, extract_btn,
             provider_select, downloaded_list, api_key_input, save_settings_btn, save_keys_btn, check_health_btn],
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

        def new_chat():
            return None, gr.update(value=_("chat_input_placeholder"))

        new_chat_btn.click(new_chat, outputs=[chatbot, msg_input])

        # ─── Pipeline event handler ─────────────────────────────────
        def do_pipeline(url, platform, lang):
            status_msg, progress_html, thinking = run_pipeline(url, platform, lang)
            return status_msg, progress_html, thinking

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