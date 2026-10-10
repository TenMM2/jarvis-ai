"""Study viral videos: analyze one by link, or find recent hits on YouTube.

``analyze_video``  downloads only the AUDIO of a public video into a temp
folder, transcribes it, returns facts (stats, caption, hook, transcript) and
deletes the temp files. Nothing is stored or republished; the model does the
interpretation. Visuals are NOT analysed (audio and metadata only).

``find_viral_videos``  uses the official YouTube Data API (YOUTUBE_API_KEY) to
list recent short videos for a topic ranked by views per day.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_ALLOWED_HOSTS = (
    "youtube.com", "youtu.be", "instagram.com", "tiktok.com", "x.com", "twitter.com",
)
_MAX_SECONDS = 180
_MAX_FRAMES = 8
_TRANSCRIPT_CLIP = 3500


def _host_allowed(url: str) -> bool:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    return p.scheme in ("http", "https") and any(
        host == h or host.endswith("." + h) for h in _ALLOWED_HOSTS
    )


def _ffmpeg() -> Optional[str]:
    explicit = os.environ.get("FFMPEG_PATH", "").strip()
    if explicit and os.path.exists(explicit):
        return explicit
    found = shutil.which("ffmpeg")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    hits = glob.glob(
        os.path.join(local, "Microsoft", "WinGet", "Packages", "**", "ffmpeg.exe"),
        recursive=True,
    )
    return hits[0] if hits else None


def _fmt(n: Any) -> str:
    return f"{int(n):,}".replace(",", ".") if isinstance(n, (int, float)) else "?"


def _ratio(a: Any, b: Any) -> str:
    try:
        return f"{100 * float(a) / float(b):.2f}%"
    except (TypeError, ValueError, ZeroDivisionError):
        return "?"


@ToolRegistry.register("analyze_video")
class AnalyzeVideoTool(BaseTool):
    tool_id = "analyze_video"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="analyze_video",
            description=(
                "Study a public short video from a link (YouTube/Shorts, Instagram "
                "Reel, TikTok, X). Returns its stats, caption, the opening hook, the "
                "transcript and a description of sampled frames (on-screen text, "
                "visual hook, style), so you can explain why it works and adapt its "
                "STRUCTURE into an original script. Frames are sampled, so fast cuts "
                "and exact timing are approximate. Max 3 minutes. Never copy its wording."
            ),
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Public video URL."}},
                "required": ["url"],
            },
            category="research",
            timeout_seconds=240.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        url = str(params.get("url", "")).strip()
        if not _host_allowed(url) or any(c.isspace() for c in url):
            return self._fail(
                "Only public links from YouTube, Instagram, TikTok or X are supported."
            )
        try:
            import yt_dlp
        except ImportError:
            return self._fail("yt-dlp is not installed in this environment.")
        ffmpeg = _ffmpeg()
        if not ffmpeg:
            return self._fail("ffmpeg was not found (set FFMPEG_PATH).")

        base_opts = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
                     "socket_timeout": 20, "retries": 2}
        with tempfile.TemporaryDirectory(prefix="jarvis-ref-") as tmp:
            try:
                with yt_dlp.YoutubeDL(base_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                duration = info.get("duration") or 0
                if duration and duration > _MAX_SECONDS:
                    return self._fail(
                        f"The video lasts {int(duration)}s; the limit is {_MAX_SECONDS}s."
                    )
                # Low-res video + audio: enough to read frames, small to download.
                dl_opts = {**base_opts,
                           "format": "bv*[height<=480]+ba/b[height<=480]/b/bv*+ba",
                           "merge_output_format": "mp4",
                           "outtmpl": str(Path(tmp) / "src.%(ext)s"),
                           "ffmpeg_location": str(Path(ffmpeg).parent)}
                with yt_dlp.YoutubeDL(dl_opts) as ydl:
                    ydl.download([url])
            except Exception as exc:  # network, private, removed, blocked...
                return self._fail(f"Could not fetch the video: {str(exc)[:200]}")

            src = next((str(p) for p in Path(tmp).glob("src.*")), None)
            if not src:
                return self._fail("Download produced no media.")
            wav = str(Path(tmp) / "audio.wav")
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [ffmpeg, "-v", "error", "-y", "-i", src, "-vn", "-t", str(_MAX_SECONDS),
                 "-ac", "1", "-ar", "16000", wav],
                capture_output=True, timeout=120,
            )
            transcript = ""
            if proc.returncode == 0 and os.path.exists(wav):
                transcript = self._transcribe(Path(wav).read_bytes())
            frames, step = self._extract_frames(ffmpeg, src, tmp, duration)
            visuals = self._describe_frames(frames, step) if frames else ""

        return ToolResult(
            tool_name=self.tool_id,
            content=self._report(info, transcript, visuals),
            success=True,
            metadata={"url": url, "title": info.get("title", "")},
        )

    @staticmethod
    def _extract_frames(ffmpeg: str, src: str, tmp: str, duration: float):
        """Up to _MAX_FRAMES evenly spaced JPEG frames; returns (bytes list, seconds apart)."""
        step = max(1.0, round((duration or 8) / _MAX_FRAMES, 1)) if duration else 1.0
        pattern = str(Path(tmp) / "frame_%02d.jpg")
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            [ffmpeg, "-v", "error", "-y", "-i", src, "-t", str(_MAX_SECONDS),
             "-vf", f"fps=1/{step},scale=512:-2", "-frames:v", str(_MAX_FRAMES), pattern],
            capture_output=True, timeout=120,
        )
        files = sorted(Path(tmp).glob("frame_*.jpg"))
        return [f.read_bytes() for f in files], step

    @staticmethod
    def _describe_frames(frames: List[bytes], step: float) -> str:
        """Ask Gemini vision to read on-screen text and describe the visual structure."""
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
        if not key:
            return "(visual analysis unavailable: no Gemini key)"
        try:
            from google import genai
            from google.genai import types

            model = os.environ.get("GEMINI_VISION_MODEL", "gemini-3.5-flash-lite")
            prompt = (
                f"These are {len(frames)} frames of a short video, in order, about {step}s apart. "
                "In English, factual and compact: (1) transcribe EXACTLY any on-screen text per frame; "
                "(2) describe what is shown and the shot type; (3) note the visual hook in the first "
                "frame; (4) text style, subtitles, effects and pacing you can infer. "
                "Do not guess what is not visible."
            )
            parts = [prompt] + [types.Part.from_bytes(data=f, mime_type="image/jpeg") for f in frames]
            client = genai.Client(api_key=key)  # keep a reference: a temporary is closed on GC
            resp = client.models.generate_content(model=model, contents=parts)
            return (resp.text or "").strip()[:2500] or "(no visual description returned)"
        except Exception as exc:
            return f"(visual analysis failed: {str(exc)[:120]})"

    def _transcribe(self, audio: bytes) -> str:
        try:
            from openjarvis.speech.gemini_stt import GeminiSpeechBackend

            backend = GeminiSpeechBackend()
            if not backend.health():
                return ""
            return backend.transcribe(audio, format="wav").text.strip()
        except Exception:
            return ""

    def _fail(self, msg: str) -> ToolResult:
        return ToolResult(tool_name=self.tool_id, content=msg, success=False)

    @staticmethod
    def _report(info: Dict[str, Any], transcript: str, visuals: str = "") -> str:
        views, likes, comments = info.get("view_count"), info.get("like_count"), info.get("comment_count")
        dur = info.get("duration")
        if transcript.strip().lower() in ("<noise>", "<music>", "[music]", "[noise]"):
            transcript = ""
        words = len(transcript.split())
        wpm = f"{words / (dur / 60):.0f}" if dur and words else "?"
        first_words = " ".join(transcript.split()[:28])
        desc = (info.get("description") or "").replace("\n", " ").strip()[:600]
        lines = [
            f"SOURCE: {info.get('extractor_key', '?')} | {info.get('uploader') or info.get('channel') or '?'}",
            f"TITLE: {info.get('title', '?')}",
            f"STATS: views {_fmt(views)} | likes {_fmt(likes)} ({_ratio(likes, views)} of views) | "
            f"comments {_fmt(comments)} ({_ratio(comments, views)}) | duration {dur or '?'}s | ~{wpm} words/min",
            f"CAPTION: {desc or '(none)'}",
            f"HOOK (first words spoken): {first_words or '(no speech detected: likely music or text-on-screen only)'}",
            f"TRANSCRIPT ({words} words): {transcript[:_TRANSCRIPT_CLIP] or '(none: music only or transcription unavailable)'}",
            f"VISUALS (from sampled frames): {visuals or '(not available)'}",
            "NOTE: visuals come from a few sampled frames, so fast cuts, motion and exact timing are only approximated.",
        ]
        return "\n".join(lines)


@ToolRegistry.register("find_viral_videos")
class FindViralVideosTool(BaseTool):
    tool_id = "find_viral_videos"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="find_viral_videos",
            description=(
                "Find recent short YouTube videos on a topic that are performing "
                "far above normal, ranked by views per day. Returns links you can "
                "pass to analyze_video. Uses the official YouTube API (needs "
                "YOUTUBE_API_KEY). YouTube only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic, e.g. 'rutina disciplina motivacion'."},
                    "limit": {"type": "integer", "description": "How many results (1-15, default 8)."},
                    "days": {"type": "integer", "description": "Only videos from the last N days (default 60)."},
                    "language": {"type": "string", "description": "Relevance language code (default 'es')."},
                },
                "required": ["query"],
            },
            category="research",
            timeout_seconds=60.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        key = os.environ.get("YOUTUBE_API_KEY", "").strip()
        if not key:
            return self._fail(
                "YOUTUBE_API_KEY is missing in .env (free key from Google Cloud: "
                "enable YouTube Data API v3 and create an API key)."
            )
        query = str(params.get("query", "")).strip()
        if not query:
            return self._fail("A query is required.")
        limit = max(1, min(int(params.get("limit", 8) or 8), 15))
        days = max(1, min(int(params.get("days", 60) or 60), 365))
        after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            search = self._get("search", key, {
                "part": "snippet", "q": query, "type": "video", "order": "viewCount",
                "videoDuration": "short", "publishedAfter": after,
                "maxResults": 25, "relevanceLanguage": str(params.get("language") or "es"),
            })
            ids = [i["id"]["videoId"] for i in search.get("items", [])]
            if not ids:
                return self._ok("No videos found for that query.")
            vids = self._get("videos", key, {"part": "statistics,snippet", "id": ",".join(ids)})
        except Exception as exc:
            return self._fail(f"YouTube API error: {str(exc)[:200]}")

        now = datetime.now(timezone.utc)
        rows: List[tuple] = []
        for v in vids.get("items", []):
            st, sn = v.get("statistics", {}), v.get("snippet", {})
            try:
                published = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            age = max(1.0, (now - published).total_seconds() / 86400)
            views = int(st.get("viewCount", 0))
            rows.append((views / age, v["id"], sn.get("title", ""), sn.get("channelTitle", ""),
                         views, st.get("likeCount"), age))
        rows.sort(reverse=True)
        out = [
            f"https://www.youtube.com/shorts/{vid} | {title[:70]} | {chan} | "
            f"{_fmt(views)} views in {age:.0f}d (~{_fmt(vpd)}/day) | likes {_fmt(likes and int(likes))}"
            for vpd, vid, title, chan, views, likes, age in rows[:limit]
        ]
        videos = [
            {"url": f"https://www.youtube.com/shorts/{vid}", "title": title, "channel": chan,
             "views": views, "views_per_day": round(vpd), "age_days": round(age)}
            for vpd, vid, title, chan, views, likes, age in rows[:limit]
        ]
        return ToolResult(
            tool_name=self.tool_id,
            content="\n".join(out) or "No usable results.",
            success=True,
            metadata={"videos": videos},
        )

    @staticmethod
    def _get(endpoint: str, key: str, params: Dict[str, Any]) -> Dict[str, Any]:
        resp = httpx.get(f"https://www.googleapis.com/youtube/v3/{endpoint}",
                         params={**params, "key": key}, timeout=30.0)
        if resp.status_code >= 400:
            try:
                msg = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                msg = resp.text
            raise RuntimeError(f"{resp.status_code}: {msg.replace(key, '***')}")
        return resp.json()

    def _ok(self, content: str) -> ToolResult:
        return ToolResult(tool_name=self.tool_id, content=content, success=True)

    def _fail(self, msg: str) -> ToolResult:
        return ToolResult(tool_name=self.tool_id, content=msg, success=False)
