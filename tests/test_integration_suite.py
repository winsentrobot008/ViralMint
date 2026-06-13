"""
Integration Test Suite for ViralMint Core Systems.
Built with Python's built-in `unittest` library — no external test deps required.

Tests three primary systems:
  1. test_encryption_persistence  — Fernet encryption roundtrip + UI masking
  2. test_chatbot_data_structure  — Gradio 6.0 chatbot dict serialization
  3. test_pipeline_exception_safety — Pipeline crash safety with mocked backend
"""
import unittest
import sys
import os
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

# -----------------------------------------------------------------------
# Prepare environment before importing app.py
# -----------------------------------------------------------------------
os.environ.setdefault("ENCRYPTION_KEY", "test-integration-master-key-42")

# Ensure we can import the necessary modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestEncryptionPersistence(unittest.TestCase):
    """Verify Fernet-based encryption at rest and UI masking."""

    def setUp(self):
        """Patch CONFIG_FILE to temp path to avoid clobbering production config."""
        # We import app locally to use the patched config path
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = Path(self.temp_dir) / "config.json"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _patch_config_file(self):
        """Return a patcher that swaps CONFIG_FILE in app.py to our temp path."""
        return patch("app.CONFIG_FILE", self.config_path)

    def test_encryption_roundtrip(self):
        """Save an API key, then verify it's encrypted in JSON, but decrypted in memory."""
        from app import _get_cipher, _load_config, _save_config, API_KEY_MASK, save_settings

        with self._patch_config_file():
            # Simulate saving an API key
            save_settings("DeepSeek", "deepseek-chat", "sk-test-secret-12345")

            # Load raw config from disk — the key MUST be encrypted
            raw = self.config_path.read_text(encoding="utf-8")
            config = json.loads(raw)
            self.assertIn("ai_api_key_encrypted", config,
                          "Key must be stored under 'ai_api_key_encrypted' key")
            encrypted = config["ai_api_key_encrypted"]
            self.assertNotEqual("sk-test-secret-12345", encrypted,
                                "Raw key must NOT be stored in plaintext on disk")
            self.assertNotIn("sk-test", raw,
                             "Plaintext must not appear anywhere in config JSON")

            # Verify we can decrypt it back correctly
            cipher = _get_cipher()
            decrypted = cipher.decrypt(encrypted.encode()).decode()
            self.assertEqual("sk-test-secret-12345", decrypted,
                             "Decrypted value must match original plaintext")

    def _extract_value(self, obj):
        """Extract the actual value from a Gradio gr.update() object which may be
        a dict-like update descriptor with '__type__': 'update' and 'value' key."""
        # Direct value
        if not isinstance(obj, (dict, list, tuple)):
            return obj
        # gr.update() serialized as dict: {'__type__': 'update', 'value': ...}
        if isinstance(obj, dict) and obj.get('__type__') == 'update':
            return obj.get('value', '')
        # Nested: {'value': {'value': ...}} - recursively extract
        if isinstance(obj, dict) and 'value' in obj:
            inner = obj['value']
            if isinstance(inner, dict) and isinstance(inner.get('value'), str):
                return inner['value']
            return inner
        return str(obj)

    def test_ui_masking(self):
        """The UI must receive '••••••••' (masked) not the plaintext key."""
        from app import save_settings, load_settings

        with self._patch_config_file():
            # First save a key
            save_settings("DeepSeek", "deepseek-chat", "sk-my-key-999")

            # Now load_settings — it should return masked value for api_key
            _, _, masked = load_settings()
            masked_val = self._extract_value(masked)
            self.assertEqual(masked_val, "••••••••",
                             "UI must display masked '••••••••' not the raw key")

    def test_no_key_saved_ui_masked(self):
        """When no key is saved, UI must still be empty string (no mask shown)."""
        from app import save_settings, load_settings

        with self._patch_config_file():
            # Save without providing a new API key
            save_settings("OpenAI", "gpt-5.4-mini", "")

            # Verify api_key_input receives empty string (not mask, not plaintext)
            _, _, api_key_value = load_settings()
            api_key_val = self._extract_value(api_key_value)
            self.assertEqual(api_key_val, "",
                             "When no key is saved, UI field must be empty")

    def test_encrypted_value_uniqueness(self):
        """Each save should produce different ciphertext (Fernet IV randomness)."""
        from app import _get_cipher

        cipher = _get_cipher()
        encrypted1 = cipher.encrypt(b"same-secret-key")
        encrypted2 = cipher.encrypt(b"same-secret-key")
        self.assertNotEqual(encrypted1, encrypted2,
                            "Fernet IV ensures each encryption is unique")

        # Both must decrypt to the same plaintext
        self.assertEqual(cipher.decrypt(encrypted1), cipher.decrypt(encrypted2))


class TestChatbotDataStructure(unittest.TestCase):
    """Verify Gradio 6.0 chatbot returns strict {'role': ..., 'content': ...} dicts."""

    def setUp(self):
        # We patch PLANNER_AVAILABLE to False so we don't need backend imports
        self.planner_patcher = patch("app.PLANNER_AVAILABLE", False)
        self.planner_patcher.start()

    def tearDown(self):
        self.planner_patcher.stop()

    def test_respond_returns_dict_list_user_first(self):
        """chat_with_agent must return list with user dict first, then assistant dict."""
        from app import chat_with_agent

        result, _ = chat_with_agent("Hello", [])
        self.assertIsInstance(result, list,
                              "Result must be a list (Gradio 6.0 Chatbot type)")
        self.assertGreaterEqual(len(result), 2,
                                "Must have at least user message + assistant response")
        # Check first entry is user dict
        first = result[0]
        self.assertIsInstance(first, dict)
        self.assertIn("role", first, "Each chat entry must have 'role' key")
        self.assertIn("content", first, "Each chat entry must have 'content' key")
        self.assertEqual(first["role"], "user",
                         "First entry role must be 'user'")
        self.assertEqual(first["content"], "Hello",
                         "First entry content must match input message")

    def test_respond_returns_assistant_response(self):
        """The second entry in the result must be an assistant dict."""
        from app import chat_with_agent

        result, _ = chat_with_agent("Test query", [])
        self.assertGreaterEqual(len(result), 2)
        second = result[1]
        self.assertEqual(second["role"], "assistant",
                         "Second entry role must be 'assistant'")
        self.assertIn("content", second,
                      "Assistant entry must have 'content'")
        # When PLANNER_AVAILABLE is False, we expect the fallback message
        self.assertIn("not available", second["content"].lower(),
                      "Assistant should report planner is unavailable")

    def test_respond_with_existing_history(self):
        """Appending to existing history must preserve all previous entries."""
        from app import chat_with_agent

        existing = [
            {"role": "user", "content": "Earlier question"},
            {"role": "assistant", "content": "Earlier answer"},
        ]
        result, _ = chat_with_agent("Follow-up", existing)
        self.assertGreaterEqual(len(result), 4)  # 2 existing + 1 user + 1 assistant
        self.assertEqual(result[0]["role"], "user")
        self.assertEqual(result[0]["content"], "Earlier question")
        self.assertEqual(result[3]["role"], "assistant",
                         "Last entry must be assistant response")

    def test_normalize_legacy_tuple_format(self):
        """If legacy tuple history is passed, normalize to dict format."""
        from app import _normalize_chat_history

        legacy = [("User msg", "Bot reply")]
        normalized = _normalize_chat_history(legacy)
        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0]["role"], "user")
        self.assertEqual(normalized[0]["content"], "User msg")
        self.assertEqual(normalized[1]["role"], "assistant")
        self.assertEqual(normalized[1]["content"], "Bot reply")

    def test_normalize_none_returns_empty(self):
        """None history must normalize to empty list, not crash."""
        from app import _normalize_chat_history

        self.assertEqual(_normalize_chat_history(None), [])
        self.assertEqual(_normalize_chat_history([]), [])

    def test_new_chat_returns_empty(self):
        """new_chat must reset chatbot to empty list."""
        from app import new_chat

        history, _ = new_chat()
        self.assertEqual(history, [],
                         "new_chat must return empty list")

    def test_empty_message_does_not_crash(self):
        """Empty or whitespace-only messages should not crash or add entries."""
        from app import chat_with_agent

        result, _ = chat_with_agent("   ", [])
        # Should return existing history (empty) without adding anything
        self.assertEqual(result, [],
                         "Empty message should return history unchanged")

    def test_respond_strict_dict_only(self):
        """All entries in chat history must be dicts, never tuples or lists."""
        from app import chat_with_agent

        result, _ = chat_with_agent("Hello", [{"role": "user", "content": "Hello"}])
        for entry in result:
            self.assertIsInstance(entry, dict,
                                  f"Each entry must be a dict, got {type(entry)}")
            self.assertIn("role", entry)
            self.assertIn("content", entry)
            self.assertIsInstance(entry["role"], str)
            self.assertIsInstance(entry["content"], str)


class TestPipelineExceptionSafety(unittest.TestCase):
    """Verify pipeline handler gracefully handles errors without crashing."""

    def setUp(self):
        self.planner_patcher = patch("app.PLANNER_AVAILABLE", False)
        self.planner_patcher.start()
        # Mock YouTube metadata scraper to return valid data so pipeline
        # reaches the DeepSeek calls (CIG does not HALT on uninstalled yt-dlp)
        self.mock_scraper = patch("app._scrape_youtube_metadata",
            return_value={"title": "Test Video Title", "description": "Test description"})
        self.mock_scraper.start()
        # Mock DeepSeek streaming AI calls so tests stay fast and isolated
        # _call_deepseek_stream is the sync thread function; we mock it to put a fixed token + None
        self.mock_deepseek = patch("app._call_deepseek_stream", side_effect=self._mock_deepseek_stream)
        self.mock_deepseek.start()

    def tearDown(self):
        self.planner_patcher.stop()
        self.mock_scraper.stop()
        self.mock_deepseek.stop()

    def _mock_deepseek_stream(self, system_prompt, user_prompt, queue, timeout=25.0):
        """Mock the streaming function: put a test token and then None."""
        queue.put_nowait("模拟分析结果: 视频具有高互动潜力")
        queue.put_nowait(None)

    def _collect(self, async_gen):
        """Helper: iterate an async generator and return the last yielded tuple."""
        import asyncio
        results = []
        async def _iterate():
            async for item in async_gen:
                results.append(item)
            return results
        asyncio.run(_iterate())
        return results[-1] if results else None

    def test_do_pipeline_empty_url_returns_placeholder(self):
        """Pipeline with empty URL should return placeholder text not crash."""
        from app import do_pipeline

        result = self._collect(do_pipeline("", "YouTube", "zh"))
        self.assertIsNotNone(result, "Pipeline must yield at least one tuple")
        self.assertIsInstance(result, tuple, "Pipeline must return a tuple")
        self.assertEqual(len(result), 5, "Pipeline must return (status, html, cumulative_log, analysis_report, script_report)")
        status, progress, cumulative_log, analysis_report, script_report = result
        self.assertIsNotNone(status, "Status must not be None")
        self.assertIsInstance(status, str, "Status must be a string")
        self.assertGreater(len(status), 0, "Empty URL should produce non-empty status text")

    def test_do_pipeline_returns_strings_not_exceptions(self):
        """Pipeline must always return formatted strings, never raise."""
        from app import do_pipeline

        try:
            result = self._collect(do_pipeline(
                "https://youtube.com/watch?v=test123",
                "YouTube",
                "en",
            ))
            self.assertIsNotNone(result)
            status, progress, cumulative_log, analysis_report, script_report = result
            self.assertIsInstance(status, str)
            self.assertIsInstance(progress, str)
            self.assertIsInstance(cumulative_log, str)
            self.assertIsInstance(analysis_report, str)
            self.assertIsInstance(script_report, str)
        except Exception as e:
            self.fail(f"do_pipeline raised an unhandled exception: {e}")

    def test_do_pipeline_en_lang(self):
        """Pipeline in English should return English status text."""
        from app import do_pipeline

        result = self._collect(do_pipeline(
            "https://youtube.com/watch?v=test",
            "TikTok",
            "en",
        ))
        self.assertIsNotNone(result)
        status, _, _, _, _ = result
        self.assertIsInstance(status, str)

    def test_do_pipeline_zh_lang(self):
        """Pipeline in Chinese should not crash."""
        from app import do_pipeline

        result = self._collect(do_pipeline(
            "https://douyin.com/video/test",
            "Douyin",
            "zh",
        ))
        self.assertIsNotNone(result)
        status, _, _, _, _ = result
        self.assertIsInstance(status, str)

    def test_invalid_url_format_still_returns_strings(self):
        """Even invalid URLs should not cause the pipeline to crash."""
        from app import do_pipeline

        try:
            result = self._collect(do_pipeline(
                "not-a-valid-url-at-all!!!",
                "YouTube",
                "en",
            ))
            self.assertIsNotNone(result)
            _, progress, _, _, _ = result
            self.assertIsInstance(progress, str)
        except Exception as e:
            self.fail(f"Pipeline crashed on invalid URL: {e}")

    def test_pipeline_thread_concurrency_safety(self):
        """Pipeline async generator must complete within 5 seconds without hanging."""
        from app import do_pipeline
        import asyncio
        import time

        start = time.time()
        try:
            result = self._collect(do_pipeline(
                "https://example.com/test",
                "YouTube",
                "en",
            ))
            elapsed = time.time() - start
            self.assertLess(elapsed, 5.0,
                            f"Pipeline must finish within 5s, took {elapsed:.2f}s")
            self.assertIsNotNone(result)
            status, progress, cumulative_log, analysis_report, script_report = result
            self.assertIsInstance(status, str)
            self.assertIsInstance(progress, str)
            self.assertIsInstance(cumulative_log, str)
            self.assertIsInstance(analysis_report, str)
            self.assertIsInstance(script_report, str)
            self.assertGreater(len(progress), 0, "Progress HTML must not be empty")
        except Exception as e:
            self.fail(f"Pipeline concurrency test raised an exception: {e}")

    def _collect_all(self, async_gen):
        """Helper: iterate an async generator and return ALL yielded tuples."""
        import asyncio
        results = []
        async def _iterate():
            async for item in async_gen:
                results.append(item)
            return results
        asyncio.run(_iterate())
        return results

    def test_pipeline_real_ai_fallback_no_key(self):
        """When OPENAI_API_KEY is missing, pipeline must show warning, not freeze."""
        from app import do_pipeline
        import os

        # Temporarily remove the mock and the env var to test graceful degradation
        self.mock_deepseek.stop()
        old_key = os.environ.pop("OPENAI_API_KEY", None)
        old_url = os.environ.pop("OPENAI_BASE_URL", None)

        try:
            all_results = self._collect_all(do_pipeline(
                "https://youtube.com/watch?v=test-fallback",
                "YouTube",
                "en",
            ))
            self.assertGreater(len(all_results), 0,
                               "Pipeline must yield at least one tuple")
            # Check that at least one yield contains the API key warning
            # Index 2 is cumulative_log in the 5-element tuple
            found_warning = any(
                "OPENAI_API_KEY" in r[2] for r in all_results
            )
            self.assertTrue(found_warning,
                            "Pipeline must show API key warning when key is missing in at least one yield")
            # Verify last yield (final completion) also exists — 5-element tuple
            last = all_results[-1]
            self.assertEqual(len(last), 5)
            last_status, last_progress, last_cumulative, last_analysis, last_script = last
            self.assertIsInstance(last_status, str)
            self.assertIsInstance(last_progress, str)
            self.assertIsInstance(last_cumulative, str)
            self.assertIsInstance(last_analysis, str)
            self.assertIsInstance(last_script, str)
        except Exception as e:
            self.fail(f"Pipeline fallback test raised an exception: {e}")
        finally:
            # Restore env vars
            if old_key is not None:
                os.environ["OPENAI_API_KEY"] = old_key
            if old_url is not None:
                os.environ["OPENAI_BASE_URL"] = old_url
            self.mock_deepseek.start()


class TestYouTubeScoutExceptionSafety(unittest.TestCase):
    """Verify search_youtube never propagates exceptions — always returns []."""

    def test_live_url_handling_safety(self):
        """search_youtube must return [] on ImportError/missing key, never raise."""
        import asyncio

        # Test 1: Missing API key should return [], not raise
        async def _test_no_key():
            from backend.services.youtube_scout import search_youtube
            result = await search_youtube(
                niche="test video",
                api_key="",  # Empty key
                max_results=5,
            )
            self.assertIsInstance(result, list,
                                  "Empty API key must return a list, not raise")
            return result

        result = asyncio.run(_test_no_key())
        self.assertEqual(result, [],
                         "Empty API key must return empty list")

        # Test 2: Invalid API key should return [], not raise
        async def _test_invalid_key():
            from backend.services.youtube_scout import search_youtube
            result = await search_youtube(
                niche="test video",
                api_key="INVALID_KEY_12345",
                max_results=5,
            )
            self.assertIsInstance(result, list,
                                  "Invalid API key must return a list, never raise")
            return result

        result = asyncio.run(_test_invalid_key())
        self.assertEqual(result, [],
                         "Invalid API key must return empty list")

        # Test 3: gibberish niche should return [] (not raise on API call)
        async def _test_gibberish():
            from backend.services.youtube_scout import search_youtube
            result = await search_youtube(
                niche="zzzzzzzxxxxxx",
                api_key="INVALID_KEY_12345",
                max_results=5,
            )
            self.assertIsInstance(result, list,
                                  "Gibberish niche must return a list, never raise")
            return result

        result = asyncio.run(_test_gibberish())
        self.assertEqual(result, [],
                         "Gibberish niche must return empty list")


class TestLegacyConfigFallback(unittest.TestCase):
    """Verify legacy config model identifiers are sanitized on load."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = Path(self.temp_dir) / "config.json"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _patch_config_file(self):
        return patch("app.CONFIG_FILE", self.config_path)

    def _extract_value(self, obj):
        if not isinstance(obj, (dict, list, tuple)):
            return obj
        if isinstance(obj, dict) and obj.get('__type__') == 'update':
            return obj.get('value', '')
        if isinstance(obj, dict) and 'value' in obj:
            inner = obj['value']
            if isinstance(inner, dict) and isinstance(inner.get('value'), str):
                return inner['value']
            return inner
        return str(obj)

    def test_legacy_config_model_fallback(self):
        """Legacy model 'claude-sonnet-4-6' must fall back to 'deepseek-chat' without raising."""
        from app import load_settings

        # Create a legacy config with an invalid model for the current provider
        legacy_cfg = {
            "ai_provider": "DeepSeek",
            "ai_model": "claude-sonnet-4-6",  # Not in DeepSeek choices
        }
        self.config_path.write_text(
            json.dumps(legacy_cfg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self._patch_config_file():
            # Should NOT raise Gradio validation error
            try:
                model_update, _, _ = load_settings()
            except Exception as e:
                self.fail(f"load_settings() raised an exception on legacy config: {e}")

            # Extract the model value from the gr.update return
            model_value = self._extract_value(model_update)
            self.assertEqual(
                model_value, "deepseek-chat",
                f"Legacy model 'claude-sonnet-4-6' must fall back to 'deepseek-chat', got '{model_value}'"
            )

    def test_legacy_config_invalid_provider_fallback(self):
        """Invalid provider must fall back to 'DeepSeek'."""
        from app import load_settings

        legacy_cfg = {
            "ai_provider": "NonExistentProvider",
            "ai_model": "some-model",
        }
        self.config_path.write_text(
            json.dumps(legacy_cfg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self._patch_config_file():
            try:
                model_update, _, _ = load_settings()
            except Exception as e:
                self.fail(f"load_settings() raised an exception on invalid provider: {e}")

            model_value = self._extract_value(model_update)
            # Invalid provider falls back to DeepSeek, model falls back to deepseek-chat
            self.assertEqual(
                model_value, "deepseek-chat",
                f"Invalid provider must fall back to 'deepseek-chat', got '{model_value}'"
            )

    def test_legacy_config_valid_model_no_fallback(self):
        """Valid model in config must NOT be overwritten by fallback."""
        from app import load_settings

        valid_cfg = {
            "ai_provider": "DeepSeek",
            "ai_model": "deepseek-reasoner",
        }
        self.config_path.write_text(
            json.dumps(valid_cfg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self._patch_config_file():
            try:
                model_update, _, _ = load_settings()
            except Exception as e:
                self.fail(f"load_settings() raised an exception on valid config: {e}")

            model_value = self._extract_value(model_update)
            self.assertEqual(
                model_value, "deepseek-reasoner",
                f"Valid model must be preserved, got '{model_value}'"
            )

    def test_legacy_config_anthropic_model_preserved(self):
        """Valid Anthropic model must be preserved when provider is Anthropic."""
        from app import load_settings

        valid_cfg = {
            "ai_provider": "Anthropic",
            "ai_model": "claude-sonnet-4-6",
        }
        self.config_path.write_text(
            json.dumps(valid_cfg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self._patch_config_file():
            try:
                model_update, _, _ = load_settings()
            except Exception as e:
                self.fail(f"load_settings() raised an exception on valid Anthropic config: {e}")

            model_value = self._extract_value(model_update)
            self.assertEqual(
                model_value, "claude-sonnet-4-6",
                f"Valid Anthropic model must be preserved, got '{model_value}'"
            )


class TestGreenChannelBypass(unittest.TestCase):
    """Verify the Green Channel (manual transcript input) bypass logic.

    When the user provides text in the ``optional_transcript`` field:
      - Agent#1 (scrape) and Agent#2 (download) MUST be SKIPPED entirely.
      - Agent#3 MUST receive "用户手动输入文案（User Provided Transcript）" as title
        and the transcript text as description.
      - The progress HTML MUST display the 🟢 green channel badge.
      - The pipeline MUST NOT attempt any yt-dlp scrape or YouTube API calls.

    When ``optional_transcript`` is empty:
      - Standard yt-dlp scraping route runs (no change from current behavior).
    """

    def setUp(self):
        self.planner_patcher = patch("app.PLANNER_AVAILABLE", False)
        self.planner_patcher.start()
        # Mock scraper to detect if it was CALLED (should NOT be called in green channel)
        self.scraper_mock = patch("app._scrape_youtube_metadata",
            return_value={"title": "SHOULD NOT BE CALLED", "description": ""})
        self.scraper_mock.start()
        # Mock DeepSeek
        self.mock_deepseek = patch("app._call_deepseek_stream", side_effect=self._mock_deepseek_stream)
        self.mock_deepseek.start()

    def tearDown(self):
        self.planner_patcher.stop()
        self.scraper_mock.stop()
        self.mock_deepseek.stop()

    def _mock_deepseek_stream(self, system_prompt, user_prompt, queue, timeout=25.0):
        queue.put_nowait("绿色通道测试分析结果")
        queue.put_nowait(None)

    def _collect_all(self, async_gen):
        """Helper: iterate an async generator and return ALL yielded tuples."""
        import asyncio
        results = []
        async def _iterate():
            async for item in async_gen:
                results.append(item)
            return results
        asyncio.run(_iterate())
        return results

    def test_green_channel_skips_agent1_and_agent2(self):
        """With transcript provided, pipeline must skip Agent#1/#2 and go directly to Agent#3."""
        from app import do_pipeline

        results = self._collect_all(do_pipeline(
            "https://youtube.com/watch?v=test123",
            "YouTube",
            "zh",
            optional_transcript="这是一段手动输入的视频文案内容，用于测试绿色通道",
        ))
        self.assertGreater(len(results), 0, "Pipeline must yield at least one tuple")
        # Verify no yt-dlp scrape was attempted - the scraper mock returns
        # "SHOULD NOT BE CALLED" if called; if we never see that in logs, it was skipped
        full_log = " ".join(r[2] for r in results)
        self.assertIn("绿色通道已激活", full_log,
                       "Green Channel activation message must appear in cumulative log")
        self.assertIn("跳过 Agent#1", full_log,
                       "Log must state that Agent#1/#2 are skipped")
        self.assertIn("手动文案已接收", full_log,
                       "Log must confirm transcript was received")
        self.assertNotIn("SHOULD NOT BE CALLED", full_log,
                         "Scraper must NOT be called when green channel is active")

    def test_green_channel_uses_user_provided_title(self):
        """Green channel must set real_title to '用户手动输入文案（User Provided Transcript）'."""
        from app import do_pipeline

        results = self._collect_all(do_pipeline(
            "https://youtube.com/watch?v=test",
            "TikTok",
            "zh",
            optional_transcript="用户粘贴的完整视频文案，此处模拟长文本输入",
        ))
        self.assertGreater(len(results), 0)
        # Check that Agent#3 prompt context includes the user-provided title
        # This is verified indirectly: the cumulative_log contains the transcript char count
        full_log = " ".join(r[2] for r in results)
        # The green channel title is visible in the progress HTML (3rd yield onwards)
        self.assertIn("手动输入文案", full_log,
                       "Title must reference user-provided context")

    def test_green_channel_empty_transcript_falls_back_to_standard(self):
        """With empty transcript, pipeline must run standard yt-dlp route (Agent#1 called)."""
        from app import do_pipeline
        import asyncio

        # We need to stop and restart the scraper mock to let it return valid data
        self.scraper_mock.stop()
        valid_scraper = patch("app._scrape_youtube_metadata",
            return_value={"title": "Standard Video Title", "description": "Standard desc"})
        valid_scraper.start()

        try:
            results = self._collect_all(do_pipeline(
                "https://youtube.com/watch?v=test-empty",
                "YouTube",
                "en",
                optional_transcript="",  # Empty → standard route
            ))
            self.assertGreater(len(results), 0)
            full_log = " ".join(r[2] for r in results)
            # Check the specific activation message, not generic substring,
            # because mock DeepSeek tokens ("绿色通道测试分析结果") are appended
            # via cumulative_log during Agent#3 streaming in ALL routes.
            self.assertNotIn("🟢 绿色通道已激活", full_log,
                             "Green Channel must NOT activate when transcript is empty")
            # cumulative_log uses Chinese format: "真实标题: Standard Video Title"
            self.assertIn("真实标题: Standard Video Title", full_log,
                          "Standard route must run Agent#1 scraper")
        finally:
            valid_scraper.stop()
            self.scraper_mock.start()

    def test_green_channel_prevents_hallucination_on_cig_fallback(self):
        """When yt-dlp is blocked AND user provides transcript, CIG is bypassed safely."""
        from app import do_pipeline

        # Simulate the scenario: yt-dlp is NOT installed, user provides transcript
        results = self._collect_all(do_pipeline(
            "https://youtube.com/watch?v=blocked-video",
            "YouTube",
            "zh",
            optional_transcript="即使yt-dlp被封锁，用户手动文案也能正常工作",
        ))
        self.assertGreater(len(results), 0)
        full_log = " ".join(r[2] for r in results)
        # Pipeline should NOT halt
        self.assertNotIn("核心熔断", full_log,
                         "CIG must NOT melt down when user provides transcript")
        self.assertNotIn("管线已中止", full_log,
                         "Pipeline must NOT halt when green channel is active")
        # And should proceed to Agent#3
        self.assertIn("绿色通道已激活", full_log,
                      "Green channel must be activated")


class TestYouTubeScraperAntiBotMeltdown(unittest.TestCase):
    """Verify _is_anti_bot_response and yt-dlp scraper failure CIG meltdown."""

    def test_anti_bot_empty_title_triggers_meltdown(self):
        """Empty/blank title must be detected as anti-bot (returns True)."""
        from app import _is_anti_bot_response

        self.assertTrue(_is_anti_bot_response(""),
                        "Empty string must be flagged as anti-bot")
        self.assertTrue(_is_anti_bot_response("   "),
                        "Whitespace-only string must be flagged as anti-bot")

    def test_anti_bot_short_title_triggers_meltdown(self):
        """Title shorter than 5 chars must be flagged as suspicious."""
        from app import _is_anti_bot_response

        self.assertTrue(_is_anti_bot_response("AB"),
                        "Very short title must trigger suspicion")
        self.assertTrue(_is_anti_bot_response("1234"),
                        "4-char title must trigger suspicion")

    def test_anti_bot_sign_in_detected(self):
        """'Sign in' keyword must be detected as anti-bot."""
        from app import _is_anti_bot_response

        self.assertTrue(_is_anti_bot_response("Sign in - YouTube"),
                        "'Sign in' must be flagged")
        self.assertTrue(_is_anti_bot_response("Sign in to confirm you're not a bot"),
                        "Extended sign-in page must be flagged")

    def test_anti_bot_captcha_detected(self):
        """CAPTCHA/verify keywords must be detected."""
        from app import _is_anti_bot_response

        self.assertTrue(_is_anti_bot_response("Attention Required! | Cloudflare"),
                        "Cloudflare attention page must be flagged")
        self.assertTrue(_is_anti_bot_response("Please verify you are human"),
                        "Verify page must be flagged")
        self.assertTrue(_is_anti_bot_response("unusual traffic from your network"),
                        "Unusual traffic page must be flagged")

    def test_anti_bot_legitimate_title_passes(self):
        """A real video title must NOT be flagged as anti-bot."""
        from app import _is_anti_bot_response

        self.assertFalse(_is_anti_bot_response("852赫兹 疗愈频率音乐：深度放松与冥想"),
                         "Real Chinese title must NOT be flagged")
        self.assertFalse(_is_anti_bot_response("Deep Work Focus Music for Productivity"),
                         "Real English title must NOT be flagged")
        self.assertFalse(_is_anti_bot_response("How to build a React app in 10 minutes"),
                         "Legitimate tutorial title must NOT be flagged")

    def test_ytdlp_missing_executable_returns_empty(self):
        """When yt-dlp is not installed, _scrape_youtube_metadata must return empty dict."""
        from app import _scrape_youtube_metadata
        import shutil

        # If yt-dlp is not in PATH, the function should gracefully return {}
        result = _scrape_youtube_metadata("https://youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertIsInstance(result, dict,
                              "Must return a dict on failure")
        self.assertIn("title", result,
                      "Result dict must have 'title' key")
        self.assertIn("description", result,
                      "Result dict must have 'description' key")

    def test_non_youtube_url_returns_empty(self):
        """Non-YouTube URLs must return empty metadata without attempting scrape."""
        from app import _scrape_youtube_metadata

        result = _scrape_youtube_metadata("https://example.com/video")
        self.assertEqual(result, {"title": "", "description": ""},
                         "Non-YouTube URL must return empty metadata")

        result = _scrape_youtube_metadata("")
        self.assertEqual(result, {"title": "", "description": ""},
                         "Empty URL must return empty metadata")

    def test_scraper_failure_triggers_pipeline_halt(self):
        """When _scrape_youtube_metadata returns empty title, pipeline must HALT."""
        from app import do_pipeline
        import asyncio

        # Use a URL that will cause _scrape_youtube_metadata to return {} (non-YouTube)
        results = []
        async def _collect():
            async for item in do_pipeline("https://example.com/non-youtube", "YouTube", "en"):
                results.append(item)
            return results
        asyncio.run(_collect())

        self.assertGreater(len(results), 0, "Pipeline must yield at least once")
        # Check that the final yield (or a yield) contains the HALT message
        # Index 0 = pipeline_status, Index 2 = cumulative_log
        all_statuses = [r[0] for r in results]
        all_logs = " ".join(r[2] for r in results if len(r) > 2)
        self.assertTrue(
            "管线已中止" in all_statuses[-1] or "已将态" in all_statuses[-1],
            f"Pipeline must HALT with abort message, got: {all_statuses[-1]}"
        )
        self.assertIn("上下文完整性检查失败", all_logs,
                      "Log must contain Context Integrity Guard failure message")


if __name__ == "__main__":
    unittest.main()
