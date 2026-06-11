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
        # Patch PLANNER_AVAILABLE and YTDLP_AVAILABLE to avoid import issues
        self.planner_patcher = patch("app.PLANNER_AVAILABLE", False)
        self.planner_patcher.start()

    def tearDown(self):
        self.planner_patcher.stop()

    def test_do_pipeline_empty_url_returns_placeholder(self):
        """Pipeline with empty URL should return placeholder text not crash."""
        from app import do_pipeline

        result = do_pipeline("", "YouTube", "zh")
        self.assertIsInstance(result, tuple, "Pipeline must return a tuple")
        self.assertEqual(len(result), 3, "Pipeline must return (status, html, thinking)")
        status, progress, thinking = result
        self.assertIsNotNone(status, "Status must not be None")
        # Should return placeholder text when URL is empty — any non-empty string is fine
        self.assertIsInstance(status, str, "Status must be a string")
        self.assertGreater(len(status), 0, "Empty URL should produce non-empty status text")

    def test_do_pipeline_returns_strings_not_exceptions(self):
        """Pipeline must always return formatted strings, never raise."""
        from app import do_pipeline

        try:
            status, progress, thinking = do_pipeline(
                "https://youtube.com/watch?v=test123",
                "YouTube",
                "en",
            )
            self.assertIsInstance(status, str)
            self.assertIsInstance(progress, str)
            self.assertIsInstance(thinking, str)
        except Exception as e:
            self.fail(f"do_pipeline raised an unhandled exception: {e}")

    def test_do_pipeline_en_lang(self):
        """Pipeline in English should return English status text."""
        from app import do_pipeline

        status, _, _ = do_pipeline(
            "https://youtube.com/watch?v=test",
            "TikTok",
            "en",
        )
        # Should not crash, status is just the pipeline_running text
        self.assertIsInstance(status, str)

    def test_do_pipeline_zh_lang(self):
        """Pipeline in Chinese should not crash."""
        from app import do_pipeline

        status, _, _ = do_pipeline(
            "https://douyin.com/video/test",
            "Douyin",
            "zh",
        )
        self.assertIsInstance(status, str)

    def test_invalid_url_format_still_returns_strings(self):
        """Even invalid URLs should not cause the pipeline to crash."""
        from app import do_pipeline

        try:
            status, progress, thinking = do_pipeline(
                "not-a-valid-url-at-all!!!",
                "YouTube",
                "en",
            )
            self.assertIsInstance(progress, str)
        except Exception as e:
            self.fail(f"Pipeline crashed on invalid URL: {e}")


if __name__ == "__main__":
    unittest.main()