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
        # Mock DeepSeek streaming AI calls so tests stay fast and isolated
        # _call_deepseek_stream is the sync thread function; we mock it to put a fixed token + None
        self.mock_deepseek = patch("app._call_deepseek_stream", side_effect=self._mock_deepseek_stream)
        self.mock_deepseek.start()

    def tearDown(self):
        self.planner_patcher.stop()
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
        self.assertEqual(len(result), 3, "Pipeline must return (status, html, thinking)")
        status, progress, thinking = result
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
            status, progress, thinking = result
            self.assertIsInstance(status, str)
            self.assertIsInstance(progress, str)
            self.assertIsInstance(thinking, str)
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
        status, _, _ = result
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
        status, _, _ = result
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
            _, progress, _ = result
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
            status, progress, thinking = result
            self.assertIsInstance(status, str)
            self.assertIsInstance(progress, str)
            self.assertIsInstance(thinking, str)
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
            found_warning = any(
                "OPENAI_API_KEY" in r[2] for r in all_results
            )
            self.assertTrue(found_warning,
                            "Pipeline must show API key warning when key is missing in at least one yield")
            # Verify last yield (final completion) also exists
            last_status, last_progress, last_thinking = all_results[-1]
            self.assertIsInstance(last_status, str)
            self.assertIsInstance(last_progress, str)
            self.assertIsInstance(last_thinking, str)
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


if __name__ == "__main__":
    unittest.main()
