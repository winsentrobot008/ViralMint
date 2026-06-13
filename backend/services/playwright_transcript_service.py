# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2025-2026 ViralMint Contributors
"""
Playwright-based YouTube transcript & audio downloader.
Replaces yt-dlp text-scraping route for Agent#1.

Pipeline:
  1. Open YouTube URL with Playwright (stealth plugin) in headless Chrome.
  2. Try to extract auto-generated captions from the page DOM directly.
  3. If no text transcript is found on the page, download the audio stream
     via yt-dlp (audio-only, minimal) and pass it to faster-whisper for
     CPU-based transcription.

CPU-only — never attempts GPU/CUDA. Designed for legacy 2 GB VRAM hardware.
"""
import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)

# ── Playwright imports (lazy to avoid import overhead if service not used) ────

_PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    logger.warning("playwright not installed — playwright_transcript_service unavailable")

_STEALTH_AVAILABLE = False
try:
    from playwright_stealth import stealth_async
    _STEALTH_AVAILABLE = True
except ImportError:
    logger.warning("playwright-stealth not installed — YouTube bot detection evasion disabled")

# ── Constants ──────────────────────────────────────────────────────────────────

# How long to wait for the YouTube page to load captions
_PAGE_LOAD_TIMEOUT = 30_000       # 30 seconds
_CAPTION_PANEL_WAIT = 8_000       # Wait up to 8s for caption panel to appear
_AUDIO_DOWNLOAD_TIMEOUT = 600     # 10 minutes max for audio download

# YouTube caption DOM selectors — robust against minor YouTube UI changes
_CAPTION_SELECTORS = [
    "ytd-player ytp-caption-segment",                          # Classic player
    "#ytp-caption-window-container .ytp-caption-segment",     # Legacy
    ".caption-window .caption-visual-line",                   # Alternative layout
    "ytd-transcript-renderer .segment-text",                  # Transcript panel
    "ytd-transcript-body-renderer .ytd-transcript-segment-renderer span",
    "#segments-container .segment",                           # Newer transcript layout
]

# Fallback: click the "..." menu → "Show transcript" path
_TRANSCRIPT_BUTTON_SELECTORS = [
    "button[aria-label='More actions']",
    "yt-icon-button#button[aria-label='More actions']",
    "#menu-button button",
    "ytd-menu-renderer yt-icon-button",
]

_TRANSCRIPT_MENU_ITEM = [
    "ytd-menu-service-item-renderer:has-text('Show transcript')",
    "tp-yt-paper-item:has-text('Show transcript')",
    "ytd-menu-service-item-renderer:has-text('Transcript')",
]

# YouTube audio stream format for yt-dlp fallback
_YTDLP_AUDIO_FORMAT = "bestaudio/best"


class YouTubeTranscriptError(Exception):
    """Raised when transcript extraction fails via all methods."""
    pass


class YouTubeTranscriptService:
    """
    Extracts YouTube video transcripts using Playwright+stealth for DOM scraping,
    falling back to faster-whisper CPU transcription if no captions are available.
    """

    # ── Public API ──────────────────────────────────────────────────────────

    async def get_transcript(
        self,
        video_url: str,
        language: Optional[str] = None,
        audio_download_dir: Optional[Path] = None,
    ) -> dict:
        """
        Get video transcript. Tries DOM extraction first, then Whisper fallback.

        Args:
            video_url: Full YouTube video URL.
            language: Preferred language code (e.g. "en", "zh"). If None, auto-detect.
            audio_download_dir: Directory to store downloaded audio (fallback path).

        Returns:
            {
                "text": "Full transcript text",
                "language": "en",
                "source": "auto_captions" | "manual_captions" | "whisper",
                "segments": [{"start": float, "end": float, "text": str}, ...],
            }

        Raises:
            YouTubeTranscriptError if both DOM and Whisper fallback fail.
        """
        if not _PLAYWRIGHT_AVAILABLE:
            raise YouTubeTranscriptError("playwright is not installed — cannot scrape YouTube")

        logger.info("YT_TRANSCRIPT | Getting transcript for %s", video_url[:80])

        # Step 1: Try DOM extraction via Playwright
        try:
            result = await self._extract_from_dom(video_url, language)
            if result and result.get("text", "").strip():
                logger.info(
                    "YT_TRANSCRIPT | DOM extraction succeeded (%s, %d chars, source=%s)",
                    result.get("language", "?"), len(result["text"]), result.get("source"),
                )
                return result
        except Exception as e:
            logger.warning("YT_TRANSCRIPT | DOM extraction failed: %s", e)

        # Step 2: Fallback — download audio and transcribe with faster-whisper (CPU)
        try:
            logger.info("YT_TRANSCRIPT | DOM extraction empty — falling back to Whisper CPU transcription")
            result = await self._transcribe_with_whisper(
                video_url, language, audio_download_dir,
            )
            if result and result.get("text", "").strip():
                logger.info(
                    "YT_TRANSCRIPT | Whisper transcription succeeded (%s, %d chars)",
                    result.get("language", "?"), len(result["text"]),
                )
                return result
        except Exception as e:
            logger.warning("YT_TRANSCRIPT | Whisper fallback also failed: %s", e)

        raise YouTubeTranscriptError(
            f"Failed to extract transcript for {video_url[:60]} — "
            "no captions available and audio transcription failed."
        )

    # ── DOM Extraction via Playwright + Stealth ────────────────────────────

    async def _extract_from_dom(
        self,
        video_url: str,
        language: Optional[str] = None,
    ) -> Optional[dict]:
        """Open YouTube in headless Chrome with stealth, try to extract captions from DOM."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",                # CPU-only: no GPU acceleration
                    "--disable-accelerated-2d-canvas",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/148.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="en-US" if not language else language,
            )

            # Apply stealth plugin to evade YouTube bot detection
            page = await context.new_page()
            if _STEALTH_AVAILABLE:
                try:
                    await stealth_async(page)
                    logger.debug("YT_TRANSCRIPT | Stealth plugin applied")
                except Exception as e:
                    logger.debug("YT_TRANSCRIPT | Stealth plugin failed (non-fatal): %s", e)

            try:
                # Navigate to video
                logger.debug("YT_TRANSCRIPT | Navigating to %s", video_url[:80])
                await page.goto(video_url, wait_until="networkidle", timeout=_PAGE_LOAD_TIMEOUT)
                await page.wait_for_timeout(2_000)  # Allow JS to settle

                # Strategy A: Try direct caption segments on the page
                result = await self._try_direct_captions(page)
                if result:
                    return result

                # Strategy B: Click "Show transcript" from the menu
                result = await self._try_transcript_menu(page)
                if result:
                    return result

                # Strategy C: Set language param and retry
                if language:
                    lang_url = f"{video_url}&hl={language}"
                    await page.goto(lang_url, wait_until="networkidle", timeout=_PAGE_LOAD_TIMEOUT)
                    await page.wait_for_timeout(2_000)
                    result = await self._try_direct_captions(page)
                    if result:
                        return result
                    result = await self._try_transcript_menu(page)
                    if result:
                        return result

                logger.info("YT_TRANSCRIPT | No captions found on page for %s", video_url[:60])
                return None

            except PlaywrightTimeout:
                logger.warning("YT_TRANSCRIPT | Page load timeout for %s", video_url[:60])
                return None
            except Exception as e:
                logger.warning("YT_TRANSCRIPT | Playwright error: %s", e)
                return None
            finally:
                await browser.close()

    async def _try_direct_captions(self, page) -> Optional[dict]:
        """Try to find caption segments already visible in the DOM."""
        for selector in _CAPTION_SELECTORS:
            try:
                elements = await page.query_selector_all(selector)
                if elements and len(elements) > 0:
                    texts = []
                    for el in elements:
                        text = await el.inner_text()
                        if text and text.strip():
                            texts.append(text.strip())

                    if texts:
                        full_text = " ".join(texts)
                        logger.debug(
                            "YT_TRANSCRIPT | Found %d caption segments via '%s'",
                            len(texts), selector,
                        )
                        return {
                            "text": full_text,
                            "language": self._detect_language(full_text),
                            "source": "auto_captions",
                            "segments": self._segments_from_plain(texts),
                        }
            except Exception as e:
                logger.debug("YT_TRANSCRIPT | Selector '%s' error: %s", selector, e)
                continue
        return None

    async def _try_transcript_menu(self, page) -> Optional[dict]:
        """Click 'Show transcript' from the YouTube menu and extract the panel content."""
        try:
            # First, ensure video is playing / page is interactive — click the player
            try:
                player = await page.wait_for_selector("video", timeout=5_000)
                if player:
                    await page.evaluate("document.querySelector('video')?.play()")
                    await page.wait_for_timeout(1_000)
            except Exception:
                pass  # Non-critical

            # Click "More actions" (...) button
            more_btn = None
            for sel in _TRANSCRIPT_BUTTON_SELECTORS:
                try:
                    more_btn = await page.wait_for_selector(sel, timeout=3_000)
                    if more_btn:
                        logger.debug("YT_TRANSCRIPT | Found 'More actions' via '%s'", sel)
                        break
                except Exception:
                    continue

            if not more_btn:
                logger.debug("YT_TRANSCRIPT | 'More actions' button not found")
                return None

            await more_btn.click()
            await page.wait_for_timeout(1_500)

            # Click "Show transcript" from the dropdown
            transcript_item = None
            for sel in _TRANSCRIPT_MENU_ITEM:
                try:
                    transcript_item = await page.wait_for_selector(sel, timeout=3_000)
                    if transcript_item:
                        logger.debug("YT_TRANSCRIPT | Found 'Show transcript' via '%s'", sel)
                        break
                except Exception:
                    continue

            if not transcript_item:
                logger.debug("YT_TRANSCRIPT | 'Show transcript' menu item not found")
                return None

            await transcript_item.click()
            await page.wait_for_timeout(3_000)  # Wait for transcript panel to load

            # Now extract from the transcript panel
            # YouTube renders transcript as a scrollable panel with segment-text spans
            panel_selectors = [
                "ytd-transcript-segment-renderer .segment-text",
                "ytd-transcript-body-renderer .ytd-transcript-segment-renderer span",
                "#segments-container .segment-text",
                ".ytd-transcript-segment-renderer",
            ]

            for sel in panel_selectors:
                try:
                    segments = await page.query_selector_all(sel)
                    if segments and len(segments) >= 3:
                        texts = []
                        for seg in segments:
                            text = await seg.inner_text()
                            if text and text.strip():
                                texts.append(text.strip())

                        if texts:
                            full_text = " ".join(texts)
                            logger.debug(
                                "YT_TRANSCRIPT | Transcript panel: %d segments via '%s'",
                                len(texts), sel,
                            )
                            return {
                                "text": full_text,
                                "language": self._detect_language(full_text),
                                "source": "auto_captions",
                                "segments": self._segments_from_plain(texts),
                            }
                except Exception as e:
                    logger.debug("YT_TRANSCRIPT | Panel selector '%s' error: %s", sel, e)
                    continue

            # Fallback: try to extract raw text from the whole transcript panel
            try:
                panel = await page.query_selector("ytd-transcript-renderer")
                if panel:
                    raw_text = await panel.inner_text()
                    if raw_text and len(raw_text.strip()) > 50:
                        lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
                        # Skip timestamp lines, keep text lines
                        text_lines = [
                            l for l in lines
                            if not re.match(r"^\d{1,2}:\d{2}", l)
                        ]
                        if text_lines:
                            logger.debug(
                                "YT_TRANSCRIPT | Raw transcript panel: %d lines",
                                len(text_lines),
                            )
                            return {
                                "text": " ".join(text_lines),
                                "language": self._detect_language(" ".join(text_lines)),
                                "source": "auto_captions",
                                "segments": self._segments_from_plain(text_lines),
                            }
            except Exception as e:
                logger.debug("YT_TRANSCRIPT | Raw panel extraction error: %s", e)

        except Exception as e:
            logger.debug("YT_TRANSCRIPT | Transcript menu flow error: %s", e)

        return None

    # ── Whisper Fallback (CPU) ──────────────────────────────────────────────

    async def _transcribe_with_whisper(
        self,
        video_url: str,
        language: Optional[str] = None,
        audio_download_dir: Optional[Path] = None,
    ) -> Optional[dict]:
        """
        Download audio from YouTube (via yt-dlp audio-only) and transcribe
        with faster-whisper in pure CPU mode (int8 quantization).
        """
        if audio_download_dir is None:
            audio_download_dir = settings.AUDIO_DIR
        audio_download_dir.mkdir(parents=True, exist_ok=True)

        # Generate a safe filename from the URL
        video_id = self._extract_video_id(video_url) or str(int(time.time()))
        audio_path = audio_download_dir / f"{video_id}_audio.mp3"
        whisper_dir = audio_download_dir / f"{video_id}_whisper_chunks"
        whisper_dir.mkdir(parents=True, exist_ok=True)

        # Step A: Download audio stream using yt-dlp (audio-only, minimal)
        try:
            await self._download_audio_only(video_url, audio_path)
        except Exception as e:
            logger.warning("YT_TRANSCRIPT | Audio download failed: %s", e)
            return None

        if not audio_path.exists() or audio_path.stat().st_size == 0:
            logger.warning("YT_TRANSCRIPT | Downloaded audio file is empty/missing")
            return None

        file_size_mb = audio_path.stat().st_size / (1024 * 1024)
        logger.info(
            "YT_TRANSCRIPT | Audio downloaded (%.1f MB) — starting CPU Whisper transcription",
            file_size_mb,
        )

        # Step B: Transcribe with faster-whisper (CPU, int8)
        try:
            result = await self._run_whisper_cpu(audio_path, language)
            if result:
                # Tag source as whisper
                result["source"] = "whisper"
                return result
        except Exception as e:
            logger.warning("YT_TRANSCRIPT | Whisper transcription failed: %s", e)
        finally:
            # Cleanup audio file after transcription
            try:
                if audio_path.exists():
                    audio_path.unlink()
            except Exception:
                pass
            try:
                if whisper_dir.exists():
                    import shutil
                    shutil.rmtree(whisper_dir, ignore_errors=True)
            except Exception:
                pass

        return None

    async def _download_audio_only(self, video_url: str, output_path: Path) -> None:
        """
        Download only the audio stream from YouTube using yt-dlp.
        This is a minimal download — no video, no subtitles, just the best audio.
        """
        import yt_dlp

        def _dl():
            opts = {
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "format": "bestaudio/best",
                "outtmpl": str(output_path.with_suffix("")),
                "extract_flat": False,
                "socket_timeout": 30,
                "retries": 3,
                "fragment_retries": 3,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }],
                # Minimal headers — less likely to trigger bot detection for audio-only
                "http_headers": {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/148.0.0.0 Safari/537.36"
                    ),
                    "Referer": "https://www.google.com/",
                },
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(video_url, download=True)

        await asyncio.to_thread(_dl)

        # Verify output exists (yt-dlp may have added .mp3 or kept .m4a/.webm)
        if not output_path.exists():
            # Check alternate extensions
            for ext in [".mp3", ".m4a", ".webm", ".opus"]:
                alt = output_path.with_suffix(ext)
                if alt.exists():
                    # Rename to expected .mp3
                    import shutil
                    shutil.move(str(alt), str(output_path))
                    break

    async def _run_whisper_cpu(
        self,
        audio_path: Path,
        language: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Transcribe audio with faster-whisper in pure CPU mode.
        Uses "base" model with int8 quantization for minimal memory footprint.
        """
        from faster_whisper import WhisperModel

        def _transcribe():
            # Force CPU execution with lightweight quantized model
            model = WhisperModel(
                "base",        # ~150 MB — fits comfortably on 2 GB VRAM-less systems
                device="cpu",
                compute_type="int8",   # int8 quantization: ~half the memory of float16
                cpu_threads=4,
                num_workers=2,
            )

            segments_gen, info = model.transcribe(
                str(audio_path),
                beam_size=3,           # Reduced from 5 for faster CPU inference
                language=language,
                word_timestamps=False,  # Faster without word timestamps
                vad_filter=True,       # Voice Activity Detection: skip silent parts
                vad_parameters=dict(
                    threshold=0.5,
                    min_speech_duration_ms=250,
                    max_speech_duration_s=30,
                ),
            )
            segments = list(segments_gen)
            text = " ".join([s.text.strip() for s in segments if s.text.strip()])

            return {
                "text": text,
                "language": info.language,
                "language_probability": info.language_probability,
                "duration_seconds": info.duration,
                "segments": [
                    {
                        "start": s.start,
                        "end": s.end,
                        "text": s.text.strip(),
                    }
                    for s in segments
                    if s.text and s.text.strip()
                ],
            }

        # Run in thread to avoid blocking async loop
        return await asyncio.to_thread(_transcribe)

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_language(text: str) -> str:
        """Simple language detection based on character ranges."""
        if not text:
            return "en"
        cjk = 0
        latin = 0
        total = 0
        for ch in text:
            name = None
            try:
                import unicodedata
                name = unicodedata.name(ch, "")
            except Exception:
                continue
            if "CJK" in name or "HIRAGANA" in name or "KATAKANA" in name:
                cjk += 1
            elif "LATIN" in name:
                latin += 1
            total += 1
        if total == 0:
            return "en"
        if cjk > total * 0.3:
            return "zh"
        return "en"

    @staticmethod
    def _extract_video_id(url: str) -> Optional[str]:
        """Extract YouTube video ID from various URL formats."""
        patterns = [
            r"v=([a-zA-Z0-9_-]{11})",
            r"youtu\.be/([a-zA-Z0-9_-]{11})",
            r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})",
            r"youtube\.com/embed/([a-zA-Z0-9_-]{11})",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _segments_from_plain(texts: list[str]) -> list[dict]:
        """Convert plain text lines to segment format (no timestamps)."""
        # If texts are from transcript panel, they may contain timestamps
        segments = []
        for i, text in enumerate(texts):
            # Try to extract timestamp prefix like "0:05" or "1:23"
            ts_match = re.match(r"^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)$", text)
            if ts_match:
                segments.append({
                    "start": _parse_timestamp(ts_match.group(1)),
                    "end": _parse_timestamp(ts_match.group(1)) + 3.0,  # approximate 3s duration
                    "text": ts_match.group(2).strip(),
                })
            else:
                segments.append({
                    "start": i * 3.0,
                    "end": (i + 1) * 3.0,
                    "text": text.strip(),
                })
        return segments


# ── Module-level helper ──────────────────────────────────────────────────────

def _parse_timestamp(ts: str) -> float:
    """Parse timestamp like '1:23' or '0:05' or '1:23:45' to seconds."""
    parts = [int(p) for p in ts.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0.0


# ── Singleton ────────────────────────────────────────────────────────────────

transcript_service = YouTubeTranscriptService()