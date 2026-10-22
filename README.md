# Jarvis — Personal AI Assistant

A personal portfolio project: a voice-first, Jarvis-style AI assistant built on
[OpenJarvis](https://github.com/open-jarvis/OpenJarvis) (Apache 2.0). It uses
**Google Gemini** as its AI engine (text and voice) and connects to Gmail and
Google Calendar to manage email and meetings (including Google Meet) by voice
or chat.

## Features

- **Text chat and hands-free voice calls**: click the blue core to start a
  continuous call with real silence detection (no need to press anything
  between turns), with a full-screen, black HUD-style interface during the call.
- **Optional wake word** ("Jarvis"), detected in the browser at no API cost.
- **Voice**: speech recognition (STT) runs locally with faster-whisper (no API
  quota) and speech synthesis (TTS) uses Gemini voices (e.g. `Aoede`, `Kore`).
  For a fully local voice, set `tts_backend` to `kokoro`; the browser voice is
  used as a fallback if the service runs out of quota.
- **Gmail**: search emails, read threads, list unread messages, send email.
- **Google Calendar**: today's events, event search, next meeting, create
  events with a Google Meet link.
- **Open applications** (`open_app`): "open Spotify", "open Chrome on
  youtube.com". It only opens what you approve in `~/.openjarvis/apps.json`
  (no shell, strict URL validation).
- **Content library** (`content_memory`), **video analysis** (`analyze_video`,
  `find_viral_videos`; they require `yt-dlp`, `ffmpeg` and a YouTube API key)
  and **read-only Instagram** (token in `.env`).

## Prerequisites

- [Python 3.10–3.13](https://www.python.org/) and [uv](https://docs.astral.sh/uv/)
  (Python package manager: `pip install uv` or `winget install astral-sh.uv`).
- [Node.js 18+](https://nodejs.org/) for the frontend.
- A free **Gemini API key** from
  [Google AI Studio](https://aistudio.google.com/apikey).
- (Optional) Google Cloud OAuth credentials if you want to use Gmail/Calendar
  — see below.

## Installation

```bash
git clone https://github.com/TenMM2/jarvis-ai.git
cd jarvis-ai

# Backend (installs OpenJarvis in editable mode)
uv pip install -e .

# Frontend
cd frontend
npm install
cd ..
```

## Configuration

1. Copy `.env.example` to `.env` and paste your Gemini key:

   ```bash
   cp .env.example .env
   ```

   ```
   GEMINI_API_KEY=your_key_here
   ```

   The `.env` file is never committed to the repository (see `.gitignore`).

2. (First run) check that `~/.openjarvis/config.toml` has Gemini as the default
   engine and, under `[speech]`, `backend = "faster-whisper"` with
   `model = "base"`, `device = "cpu"`, `compute_type = "int8"` (the model is
   downloaded automatically the first time, ~150 MB) and
   `tts_backend = "gemini_tts"` with a voice such as `voice_id = "Aoede"`.
   For a local voice, use `tts_backend = "kokoro"` instead; Kokoro requires
   `torch` (CPU build) and `kokoro`:
   `uv pip install torch --index-url https://download.pytorch.org/whl/cpu`
   and `uv pip install kokoro pip`. If the file does not exist, `jarvis`
   creates it with default values the first time you start it.

## Allowed applications

Create `~/.openjarvis/apps.json` with the applications Jarvis may open and add
`"open_app"` to `[tools] enabled` in `config.toml`:

```json
{
  "chrome":  {"path": "C:/Program Files/Google/Chrome/Application/chrome.exe",
              "aliases": ["browser"], "accepts_url": true},
  "spotify": {"path": "C:/Users/YOUR_USER/AppData/Local/Microsoft/WindowsApps/Spotify.exe"}
}
```

Anything not on the list cannot be opened.

## Running

```bash
jarvis gui
```

On Windows you can also use `start-jarvis.cmd` (loads `.env` automatically,
since the server does not read it), `start-jarvis-hidden.vbs` (no console
window) and `connect-gmail.cmd`. With `JARVIS_GOOGLE_SCOPES=readonly` in `.env`,
Jarvis only gets read permissions on Gmail/Calendar.

This starts the backend (`http://127.0.0.1:8000`) and the frontend
(`http://127.0.0.1:5173`) and opens the browser automatically. On startup, the
app detects the server's Gemini key and selects the cloud model with no extra
steps.

## Connect Gmail and Calendar (optional)

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/),
   enable the Gmail and Calendar APIs, and create OAuth credentials of type
   "Desktop app".
2. Run:

   ```bash
   jarvis connect gmail
   ```

   Paste the Client ID and Client Secret when prompted; the browser opens so
   you can authorize access. The same authorization also covers Calendar.

## License and provenance

This project is based on [OpenJarvis](https://github.com/open-jarvis/OpenJarvis),
published under the **Apache 2.0** license (see [LICENSE](LICENSE)). That
license is kept; the modifications in this repository (Gemini integration,
voice, Gmail/Calendar tools, call interface, etc.) are original work for this
portfolio project.
