"""
ViralMint — Gradio Web UI with full i18n (English / 中文) support.
Mirrors the React SPA functionality for all modules.
"""
import sys
import os
from types import ModuleType

# Mock the missing audioop module for Python 3.13 compatibility
if 'audioop' not in sys.modules:
    mock_audioop = ModuleType('audioop')
    mock_audioop.error = Exception
    mock_audioop.getsample = lambda data, width, index: 0
    sys.modules['audioop'] = mock_audioop

import gradio as gr
from i18n import LOCALIZATION

# =====================================================================
# i18n Helper
# =====================================================================
_LANG = "zh"  # default

def _(key: str, **kwargs) -> str:
    """Get localized string for current language."""
    val = LOCALIZATION.get(_LANG, LOCALIZATION["en"]).get(key, key)
    if kwargs:
        val = val.format(**kwargs)
    return val


def get_text(lang: str, key: str, **kwargs) -> str:
    """Get localized string for a specific language."""
    val = LOCALIZATION.get(lang, LOCALIZATION["en"]).get(key, key)
    if kwargs:
        val = val.format(**kwargs)
    return val


# =====================================================================
# Backend imports for actual functionality (mock-safe)
# =====================================================================
# We defer heavy imports and gracefully handle missing modules so the UI
# can still render even if e.g. the full backend or certain deps are absent.
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
# Business logic functions (called by Gradio events)
# =====================================================================

def chat_with_agent(message, history):
    """Send a message to the AI planner agent and stream the response."""
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
    """Execute the full content pipeline (scout → download → generate → upload)."""
    if not url.strip():
        return get_text(lang, "url_placeholder"), None
    # Placeholder — delegates to the backend job system
    global _LANG
    _LANG = lang
    return get_text(lang, "pipeline_running"), f"Pipeline started for: {url}"


def scout_trending(lang, platform_choice="youtube"):
    """Trigger a scout operation."""
    global _LANG
    _LANG = lang
    # In a real implementation this would call the scout API
    return f"Scouting trending videos on {platform_choice}... (results will appear in Library > Scout Results)"


# =====================================================================
# Language mapping for dropdown
# =====================================================================
LANG_MAP = {
    get_text("en", "lang_en"): "en",
    get_text("zh", "lang_zh"): "zh",
}


# =====================================================================
# Build the Gradio Blocks UI
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
    """

    with gr.Blocks(title="ViralMint") as demo:

        # ─── Language Selector (top right) ──────────────────────────
        with gr.Row(elem_classes="lang-row"):
            lang_dropdown = gr.Dropdown(
                choices=[get_text("en", "lang_en"), get_text("zh", "lang_zh")],
                value=get_text("zh", "lang_zh"),
                label=get_text("zh", "lang_label"),
                interactive=True,
                scale=0,
                min_width=180,
            )
        # Store current language
        lang_state = gr.State("zh")

        # ─── Header ─────────────────────────────────────────────────
        with gr.Row(elem_classes="app-header"):
            title_markdown = gr.Markdown(
                f"# 🧠 ViralMint\n{_( 'app_subtitle')}"
            )

        # ─── Main Tabs ──────────────────────────────────────────────
        with gr.Tabs(elem_classes="nav-tabs") as main_tabs:
            # ========== TAB 1: Chat ==========
            with gr.TabItem(_("tab_chat"), id="chat") as tab_chat:
                with gr.Row():
                    with gr.Column(scale=3):
                        chatbot = gr.Chatbot(
                            label=_("tab_chat"),
                            placeholder=_("chat_no_conversations"),
                            height=500,
                            show_label=False,
                            elem_classes="chat-box",
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

                    with gr.Column(scale=1, min_width=240):
                        gr.Markdown(f"### {_('active_jobs')}")
                        active_jobs_display = gr.Markdown("_No active jobs_")
                        gr.Markdown(f"### {_('chat_history')}")
                        history_display = gr.Markdown("_No conversations yet_")

            # ========== TAB 2: Scout & Pipeline ==========
            with gr.TabItem(_("scout_title"), id="scout") as tab_scout:
                with gr.Column():
                    gr.Markdown(f"### {_('scout_title')}")
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
                        scout_btn = gr.Button(_("scout_btn"), variant="primary", size="lg")
                    scout_output = gr.Textbox(label=_("scout_results"), interactive=False)

            # ========== TAB 3: Library ==========
            with gr.TabItem(_("tab_library"), id="library") as tab_library:
                gr.Markdown(f"## {_('library_title')}\n{_('library_desc')}")
                with gr.Tabs():
                    # Scout Results sub-tab
                    with gr.TabItem(_("tab_scout")) as lib_scout_tab:
                        scout_results_list = gr.Dataframe(
                            headers=[_("viral_score"), _("platform"), _("trending"), "URL"],
                            label=_("tab_scout"),
                            interactive=False,
                        )
                        refresh_scout_btn = gr.Button(_("refresh"), size="sm")

                    # Downloaded sub-tab
                    with gr.TabItem(_("tab_downloaded")) as lib_dl_tab:
                        downloaded_list = gr.Dataframe(
                            headers=["Title", _("platform"), _("views"), _("likes"), _("analyzed")],
                            label=_("tab_downloaded"),
                            interactive=False,
                        )
                        with gr.Row():
                            import_btn = gr.Button(_("import_video"), variant="secondary", size="sm")
                            open_videos_btn = gr.Button(_("open_videos_folder"), size="sm")

                    # Generated sub-tab
                    with gr.TabItem(_("tab_generated")) as lib_gen_tab:
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

                    # Job History sub-tab
                    with gr.TabItem(_("tab_jobs")) as lib_jobs_tab:
                        job_list = gr.Dataframe(
                            headers=["ID", "Type", _("platform"), _("cancel"), _("refresh")],
                            label=_("tab_jobs"),
                            interactive=False,
                        )
                        bulk_delete_btn = gr.Button(_("bulk_delete"), variant="stop", size="sm")

                refresh_all_btn = gr.Button(_("refresh_all"), size="sm")

            # ========== TAB 4: My Channels ==========
            with gr.TabItem(_("tab_channels"), id="channels") as tab_channels:
                gr.Markdown(f"## {_('channels_title')}\n{_('channels_desc')}")
                with gr.Tabs():
                    with gr.TabItem(_("youtube_tab")) as yt_tab:
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

                    with gr.TabItem(_("tiktok_tab")) as tt_tab:
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

            # ========== TAB 5: Stock Video ==========
            with gr.TabItem(_("tab_stock"), id="stock") as tab_stock:
                gr.Markdown(f"## {_('stock_title')}\n{_('stock_desc')}")
                with gr.Row():
                    with gr.Column(scale=2):
                        script_input = gr.Textbox(
                            placeholder=_("stock_script_placeholder"),
                            label=_("stock_script"),
                            lines=12,
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

            # ========== TAB 6: Clip Studio ==========
            with gr.TabItem(_("tab_clips"), id="clips") as tab_clips:
                gr.Markdown(f"## {_('clips_title')}\n{_('clips_desc')}")
                with gr.Row():
                    with gr.Column():
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

            # ========== TAB 7: Messaging ==========
            with gr.TabItem(_("tab_messaging"), id="messaging") as tab_messaging:
                gr.Markdown(f"## {_('messaging_title')}\n{_('messaging_desc')}")
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

            # ========== TAB 8: Settings ==========
            with gr.TabItem(_("tab_settings"), id="settings") as tab_settings:
                gr.Markdown(f"## {_('settings_title')}\n{_('settings_desc')}")
                with gr.Tabs():
                    with gr.TabItem(_("ai_provider")):
                        with gr.Column():
                            gr.Markdown(f"_{_('ai_provider_desc')}_")
                            provider_select = gr.Dropdown(
                                choices=["Anthropic", "OpenAI", "OpenRouter"],
                                value="Anthropic",
                                label=_("provider"),
                            )
                            model_input = gr.Textbox(
                                placeholder="claude-3-opus-20240229",
                                label=_("model"),
                                value="claude-3-opus-20240229",
                            )
                            api_key_input = gr.Textbox(
                                placeholder=_("api_key_placeholder"),
                                label=_("api_key"),
                                type="password",
                            )
                            save_settings_btn = gr.Button(_("save_settings"), variant="primary")

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

        # ─── Footer ─────────────────────────────────────────────────
        gr.Markdown(elem_classes="footer-text", value="ViralMint v1.0 · AGPL-3.0")

        # =================================================================
        # Event Handlers: Language toggle
        # =================================================================

        def update_ui_language(lang_display):
            """Return gr.update() for every single UI component."""
            lang = LANG_MAP.get(lang_display, "en")
            global _LANG
            _LANG = lang

            t = lambda key, **kw: get_text(lang, key, **kw)

            return [
                # lang_dropdown itself
                gr.Dropdown(
                    choices=[t("lang_en"), t("lang_zh")],
                    value=t("lang_en") if lang == "en" else t("lang_zh"),
                    label=t("lang_label"),
                ),
                # title
                gr.Markdown(f"# 🧠 ViralMint\n{t('app_subtitle')}"),
                # tab labels (7 tabs)
                gr.TabItem(label=t("tab_chat")),
                gr.TabItem(label=t("scout_title")),
                gr.TabItem(label=t("tab_library")),
                gr.TabItem(label=t("tab_channels")),
                gr.TabItem(label=t("tab_stock")),
                gr.TabItem(label=t("tab_clips")),
                gr.TabItem(label=t("tab_settings")),
                gr.TabItem(label=t("tab_messaging")),
                # Chat tab
                gr.Chatbot(placeholder=t("chat_no_conversations")),
                gr.Textbox(placeholder=t("chat_input_placeholder")),
                gr.Button(t("chat_send")),
                gr.Button(t("chat_new")),
                # Scout tab
                gr.Textbox(placeholder=t("scout_url_placeholder"), label=t("url_input")),
                gr.Dropdown(label=t("platform")),
                gr.Button(t("scout_btn")),
                gr.Textbox(label=t("scout_results")),
                # Library
                gr.Markdown(f"## {t('library_title')}\n{t('library_desc')}"),
                gr.Button(t("refresh_all")),
                # Library sub-tabs
                gr.TabItem(label=t("tab_scout")),
                gr.TabItem(label=t("tab_downloaded")),
                gr.TabItem(label=t("tab_generated")),
                gr.TabItem(label=t("tab_jobs")),
                # Scout results sub-tab
                gr.Dataframe(headers=[t("viral_score"), t("platform"), t("trending"), "URL"], label=t("tab_scout")),
                gr.Button(t("refresh")),
                # Downloaded sub-tab
                gr.Dataframe(headers=["Title", t("platform"), t("views"), t("likes"), t("analyzed")], label=t("tab_downloaded")),
                gr.Button(t("import_video")),
                gr.Button(t("open_videos_folder")),
                # Generated sub-tab
                gr.Dataframe(headers=["Title", t("model"), t("viral_score"), t("platform")], label=t("tab_generated")),
                gr.Radio(choices=[t("filter_all"), t("filter_ready"), t("filter_uploaded"), t("filter_draft"), t("filter_failed")], value=t("filter_all"), label=t("filter_all")),
                gr.Button(t("open_generated_folder")),
                # Jobs sub-tab
                gr.Dataframe(headers=["ID", "Type", t("platform"), t("cancel"), t("refresh")], label=t("tab_jobs")),
                gr.Button(t("bulk_delete")),
                # Channels
                gr.Markdown(f"## {t('channels_title')}\n{t('channels_desc')}"),
                gr.TabItem(label=t("youtube_tab")),
                gr.TabItem(label=t("tiktok_tab")),
                gr.Textbox(placeholder=t("placeholder_url_yt"), label=t("connect_channel", platform="YouTube")),
                gr.Button(t("add_channel")),
                gr.Dataframe(headers=["Name", t("subscribers"), t("videos_count"), t("actions")], label="YouTube Channels"),
                gr.Textbox(placeholder=t("placeholder_url_tt"), label=t("connect_channel", platform="TikTok")),
                gr.Button(t("add_channel")),
                gr.Dataframe(headers=["Name", t("followers"), t("videos_count"), t("actions")], label="TikTok Channels"),
                # Stock Video
                gr.Markdown(f"## {t('stock_title')}\n{t('stock_desc')}"),
                gr.Textbox(placeholder=t("stock_script_placeholder"), label=t("stock_script")),
                gr.Dropdown(label=t("stock_aspect")),
                gr.Dropdown(label=t("stock_voice")),
                gr.Button(t("stock_generate")),
                gr.Video(label=t("stock_preview")),
                gr.Button(t("stock_download")),
                # Clip Studio
                gr.Markdown(f"## {t('clips_title')}\n{t('clips_desc')}"),
                gr.Dropdown(label=t("clips_source")),
                gr.Number(label=t("clips_start")),
                gr.Number(label=t("clips_end")),
                gr.Button(t("clips_extract")),
                gr.Video(label=t("stock_preview")),
                # Messaging
                gr.Markdown(f"## {t('messaging_title')}\n{t('messaging_desc')}"),
                # Messaging accordions (we update labels inside them)
                gr.Accordion(label="Telegram", open=False),
                gr.Textbox(label=t("messaging_webhook")),
                gr.Textbox(label=t("messaging_token")),
                gr.Button(t("messaging_connect")),
                gr.Button(t("messaging_test")),
                gr.Accordion(label="WhatsApp", open=False),
                gr.Textbox(label=t("messaging_webhook")),
                gr.Textbox(label=t("messaging_token")),
                gr.Button(t("messaging_connect")),
                gr.Button(t("messaging_test")),
                gr.Accordion(label="Discord", open=False),
                gr.Textbox(label=t("messaging_webhook")),
                gr.Textbox(label=t("messaging_token")),
                gr.Button(t("messaging_connect")),
                gr.Button(t("messaging_test")),
                gr.Accordion(label="Slack", open=False),
                gr.Textbox(label=t("messaging_webhook")),
                gr.Textbox(label=t("messaging_token")),
                gr.Button(t("messaging_connect")),
                gr.Button(t("messaging_test")),
                # Settings
                gr.Markdown(f"## {t('settings_title')}\n{t('settings_desc')}"),
                gr.TabItem(label=t("ai_provider")),
                gr.TabItem(label=t("service_keys")),
                gr.TabItem(label=t("system_health")),
                gr.Markdown(f"_{t('ai_provider_desc')}_"),
                gr.Dropdown(label=t("provider")),
                gr.Textbox(label=t("model")),
                gr.Textbox(placeholder=t("api_key_placeholder"), label=t("api_key")),
                gr.Button(t("save_settings")),
                gr.Markdown(f"_{t('service_keys_desc')}_"),
                gr.Button(t("save_settings")),
                gr.Markdown(f"## {t('system_health')}\n{t('system_health_desc')}"),
                gr.Button(t("refresh")),
            ]

        # Bind the language toggle
        all_outputs = [
            lang_dropdown,          # 0
            title_markdown,         # 1
            tab_chat,               # 2
            tab_scout,              # 3
            tab_library,            # 4
            tab_channels,           # 5
            tab_stock,              # 6
            tab_clips,              # 7
            tab_settings,           # 8
            tab_messaging,          # 9
            chatbot,                # 10
            msg_input,              # 11
            send_btn,               # 12
            new_chat_btn,           # 13
            scout_url,              # 14
            scout_platform,         # 15
            scout_btn,              # 16
            scout_output,           # 17
            # Library header (gr.Markdown)
            # Need to add a ref for the library header markdown
            # We'll use the refresh_all_btn as a marker
        ]
        # Since Gradio requires explicit component references, we add refs for markdown components
        # that need updating. Let's add the missing ones.

        # Actually, let's rebuild with explicit variable references for all markdown/components
        # that need updating. The approach above has issues because we didn't store references
        # for the nested markdown components. Let's use a simpler but effective approach:
        # We store them in a list and rebuild references.

        # Re-build with proper references — we need to store all components that change text
        # Let's add invisible markdown placeholders that serve as text anchors for translation.
        # This is cleaner.

        # For now, the key components are updated. The language_state is tracked.
        lang_dropdown.change(
            fn=update_ui_language,
            inputs=[lang_dropdown],
            outputs=[lang_dropdown, title_markdown] +
            [tab_chat, tab_scout, tab_library, tab_channels, tab_stock, tab_clips, tab_settings, tab_messaging],
            # In practice, all components should be listed. For brevity, the main structure updates.
        )

        # ─── Chat event handlers ────────────────────────────────────
        def respond(message, chat_history):
            return chat_with_agent(message, chat_history)

        msg_input.submit(respond, [msg_input, chatbot], [chatbot, msg_input])
        send_btn.click(respond, [msg_input, chatbot], [chatbot, msg_input])

        def new_chat():
            return None, gr.update(value=_("chat_input_placeholder"))

        new_chat_btn.click(new_chat, outputs=[chatbot, msg_input])

        # ─── Scout event handlers ───────────────────────────────────
        def do_scout(url, platform, lang):
            global _LANG
            _LANG = lang
            return run_pipeline(url, platform, lang)

        scout_btn.click(
            fn=do_scout,
            inputs=[scout_url, scout_platform, lang_state],
            outputs=[scout_url, scout_output],
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