"""OpenCodeAgent -- wraps the `opencode` coding agent via its headless HTTP server.

Spawns ``opencode serve`` (https://opencode.ai) and drives a session over its
HTTP API, configured to use OpenJarvis's local engine through an
OpenAI-compatible provider. This keeps coding-agent work local-first: opencode
handles the agentic loop / tools, OpenJarvis supplies the model.

opencode is an external binary (install: ``npm i -g opencode-ai`` or
``brew install anomalyco/tap/opencode``). It is not bundled; :meth:`run`
raises a clear error if it is not on ``PATH``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, BaseAgent
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import ToolResult
from openjarvis.engine._stubs import InferenceEngine

logger = logging.getLogger(__name__)

_LISTENING_RE = re.compile(r"listening on\s+(https?://\S+)", re.IGNORECASE)


def is_opencode_available() -> bool:
    """Return True if the ``opencode`` binary is on PATH."""
    return shutil.which("opencode") is not None


def _derive_openai_base_url(engine: Any) -> str:
    """Best-effort OpenAI-compatible base URL for an OpenJarvis engine.

    HTTP engines (Ollama, vLLM, llama.cpp, SGLang, LM Studio, …) expose a
    ``_host`` and serve an OpenAI-compatible API at ``<host>/v1``. Returns ""
    when it cannot be derived (caller then requires an explicit base URL or a
    pre-configured opencode provider).
    """
    for attr in ("openai_base_url", "base_url"):
        val = getattr(engine, attr, "")
        if val:
            return str(val).rstrip("/")
    host = getattr(engine, "_host", "") or getattr(engine, "host", "")
    if host:
        host = str(host).rstrip("/")
        return host if host.endswith("/v1") else f"{host}/v1"
    return ""


def _extract_text(parts: List[dict]) -> str:
    """Join the assistant's text parts from an opencode message response."""
    return "".join(
        p.get("text", "")
        for p in parts
        if isinstance(p, dict) and p.get("type") == "text"
    ).strip()


def _extract_tool_results(parts: List[dict]) -> List[ToolResult]:
    """Map opencode ``tool`` parts to OpenJarvis ToolResults (best-effort)."""
    results: List[ToolResult] = []
    for p in parts:
        if not isinstance(p, dict) or p.get("type") != "tool":
            continue
        state = p.get("state", {}) if isinstance(p.get("state"), dict) else {}
        status = state.get("status", "")
        output = state.get("output")
        if output is None:
            output = state.get("title", "") or json.dumps(state) if state else ""
        results.append(
            ToolResult(
                tool_name=p.get("tool", p.get("name", "unknown")),
                content=str(output),
                success=status not in ("error", "failed"),
            )
        )
    return results


@AgentRegistry.register("opencode")
class OpenCodeAgent(BaseAgent):
    """Agent that delegates coding tasks to a local ``opencode`` server.

    The ``engine`` is used to wire opencode at an OpenAI-compatible provider so
    inference runs on OpenJarvis's selected local model. ``agent`` selects
    opencode's built-in agent: ``build`` (full access) or ``plan`` (read-only).
    """

    agent_id = "opencode"
    accepts_tools = False
    _default_temperature = 0.7
    _default_max_tokens = 1024

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        bus: Optional[EventBus] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        workspace: str = "",
        agent: str = "build",
        provider_id: str = "openjarvis",
        provider_base_url: str = "",
        model_id: str = "",
        api_key: str = "",
        hostname: str = "127.0.0.1",
        port: int = 0,
        server_password: str = "",
        timeout: int = 600,
        opencode_bin: str = "",
    ) -> None:
        super().__init__(
            engine,
            model,
            bus=bus,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._workspace = workspace or os.getcwd()
        self._agent = agent
        self._provider_id = provider_id
        self._provider_base_url = provider_base_url or _derive_openai_base_url(engine)
        self._model_id = model_id or model
        self._api_key = api_key
        self._hostname = hostname
        self._port = port
        self._server_password = server_password or os.environ.get(
            "OPENCODE_SERVER_PASSWORD", ""
        )
        self._timeout = timeout
        self._opencode_bin = opencode_bin or shutil.which("opencode") or "opencode"
        self._proc: Optional[subprocess.Popen] = None
        self._base: str = ""

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    def _write_provider_config(self) -> None:
        """Register OpenJarvis's engine as an OpenAI-compatible opencode provider.

        Written to ``<workspace>/opencode.json`` (opencode reads project config
        from its working directory). Skipped when no base URL is available — in
        that case ``model`` is assumed to name a provider opencode already
        knows (e.g. ``ollama/llama3``).
        """
        if not self._provider_base_url:
            return
        cfg_path = Path(self._workspace) / "opencode.json"
        existing: dict = {}
        if cfg_path.exists():
            try:
                existing = json.loads(cfg_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}
        options: dict = {"baseURL": self._provider_base_url}
        if self._api_key:
            options["apiKey"] = self._api_key
        providers = existing.setdefault("provider", {})
        providers[self._provider_id] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "OpenJarvis Local",
            "options": options,
            "models": {self._model_id: {"name": self._model_id}},
        }
        existing.setdefault("$schema", "https://opencode.ai/config.json")
        cfg_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    def _ensure_server(self) -> str:
        """Spawn ``opencode serve`` (once) and return its base URL."""
        if self._base and self._proc and self._proc.poll() is None:
            return self._base
        if not is_opencode_available() and not Path(self._opencode_bin).exists():
            raise RuntimeError(
                "OpenCodeAgent requires the 'opencode' binary. Install it with "
                "`npm i -g opencode-ai` or `brew install anomalyco/tap/opencode` "
                "(see https://opencode.ai)."
            )
        self._write_provider_config()
        env = dict(os.environ)
        if self._server_password:
            env["OPENCODE_SERVER_PASSWORD"] = self._server_password
        self._proc = subprocess.Popen(
            [
                self._opencode_bin,
                "serve",
                "--port",
                str(self._port),
                "--hostname",
                self._hostname,
            ],
            cwd=self._workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        # Parse the "listening on <url>" line from startup output.
        deadline = time.monotonic() + 60
        base = ""
        assert self._proc.stdout is not None
        while time.monotonic() < deadline:
            line = self._proc.stdout.readline()
            if not line:
                if self._proc.poll() is not None:
                    raise RuntimeError("opencode server exited during startup")
                continue
            m = _LISTENING_RE.search(line)
            if m:
                base = m.group(1).rstrip("/")
                break
        if not base:
            self.close()
            raise RuntimeError("opencode server did not report a listening URL")
        self._base = base
        return base

    def _client(self):
        import httpx

        headers = {}
        if self._server_password:
            import base64

            token = base64.b64encode(
                f"opencode:{self._server_password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {token}"
        return httpx.Client(base_url=self._base, headers=headers, timeout=self._timeout)

    def close(self) -> None:
        """Dispose the opencode session/server and terminate the process."""
        if self._base:
            try:
                with self._client() as c:
                    c.post("/global/dispose")
            except Exception:
                pass
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        self._base = ""

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Run a coding task through opencode and return the assistant result."""
        self._emit_turn_start(input)
        try:
            self._ensure_server()
        except RuntimeError as exc:
            self._emit_turn_end(turns=1, error=True)
            return AgentResult(
                content=str(exc), turns=1, metadata={"error": True}
            )

        try:
            with self._client() as c:
                ses = c.post("/session", json={"title": input[:80]})
                ses.raise_for_status()
                session_id = ses.json()["id"]

                body: dict = {
                    "agent": self._agent,
                    "parts": [{"type": "text", "text": input}],
                }
                if self._provider_base_url or "/" not in self._model_id:
                    body["model"] = {
                        "providerID": self._provider_id,
                        "modelID": self._model_id,
                    }
                else:
                    prov, _, mid = self._model_id.partition("/")
                    body["model"] = {"providerID": prov, "modelID": mid}

                resp = c.post(f"/session/{session_id}/message", json=body)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.error("opencode run failed: %s", exc, exc_info=True)
            self._emit_turn_end(turns=1, error=True)
            return AgentResult(
                content=f"opencode agent failed: {exc}",
                turns=1,
                metadata={"error": True},
            )

        parts = data.get("parts", []) if isinstance(data, dict) else []
        info = data.get("info", {}) if isinstance(data, dict) else {}
        content = _extract_text(parts)
        tool_results = _extract_tool_results(parts)

        self._emit_turn_end(turns=1)
        return AgentResult(
            content=content,
            tool_results=tool_results,
            turns=1,
            metadata={
                "finish": info.get("finish"),
                "tokens": info.get("tokens"),
                "provider_id": info.get("providerID", self._provider_id),
                "model_id": info.get("modelID", self._model_id),
                "session_id": info.get("sessionID", ""),
                "agent": self._agent,
            },
        )


__all__ = ["OpenCodeAgent", "is_opencode_available"]
