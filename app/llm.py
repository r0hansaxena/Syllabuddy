"""Atlas's AI connection: the local Claude Code login, or any OpenAI-compatible chat API,
local (Ollama, LM Studio...) or hosted (Gemini, OpenAI...)."""

import asyncio
import json
import os
import re
import shutil

import httpx

from app.config import AI_BASE_URL, AI_KEY, AI_MODEL, DATA_DIR, OFFLINE


class LLMError(Exception):
    pass


# id: (label, base URL, env var holding the key, default model). Local servers need no key.
# Claude Code is not an HTTP server: it runs through its own login on this machine (base URL "local").
PROVIDERS = {
    "claudecode": ("Claude Code", "local", None, "default"),
    "ollama": ("Ollama", "http://localhost:11434/v1", None, ""),
    "lmstudio": ("LM Studio", "http://localhost:1234/v1", None, ""),
    "gemini": ("Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemini-2.5-flash"),
    "openai": ("OpenAI", "https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4o-mini"),
    "groq": ("Groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", ""),
    "anthropic": ("Anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", ""),
    "custom": ("Custom", "", None, ""),
}

enabled = True  # the user's on/off switch, loaded from settings at startup
cfg = {"provider": "", "base_url": "", "model": "", "key": "", "auto": True}  # the active connection
detected: list[dict] = []  # what the last scan found, without keys


def label(provider: str) -> str:
    return PROVIDERS[provider][0] if provider in PROVIDERS else ""


def resolve_key(provider: str, key: str = "") -> str:
    """A key typed into Settings wins; otherwise the provider's usual environment variable."""
    env = PROVIDERS.get(provider, (None, None, None))[2]
    return key or (os.environ.get(env, "") if env else "")


def configure(provider: str, base_url: str, model: str, key: str = "", auto: bool = False) -> None:
    cfg.update(provider=provider, base_url=base_url.rstrip("/"), model=model, key=key, auto=auto)


def configured() -> bool:
    return not OFFLINE and bool(cfg["base_url"] and cfg["model"])


def available() -> bool:
    return enabled and configured()


def public_config() -> dict:
    return {"provider": cfg["provider"], "label": label(cfg["provider"]), "base_url": cfg["base_url"],
            "model": cfg["model"], "has_key": bool(resolve_key(cfg["provider"], cfg["key"])), "auto": cfg["auto"]}


def _headers(provider: str, key: str) -> dict:
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
        if provider == "anthropic":  # its model list wants these instead of a bearer token
            h.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    return h


CLAUDE_CODE_MODELS = ["default", "sonnet", "opus", "haiku"]


def claude_code_installed() -> bool:
    return shutil.which("claude") is not None


def list_models(provider: str, base_url: str, key: str = "", timeout: float = 5) -> list[str]:
    if provider == "claudecode":
        return CLAUDE_CODE_MODELS if claude_code_installed() else []
    key = resolve_key(provider, key)
    r = httpx.get(f"{base_url.rstrip('/')}/models", headers=_headers(provider, key), timeout=timeout)
    r.raise_for_status()
    return [m["id"].removeprefix("models/") for m in r.json().get("data", [])]


def detect() -> list[dict]:
    """Looks for a running local AI server and for API keys already set on this machine."""
    found = []
    if OFFLINE:
        return found
    if claude_code_installed():
        found.append({"provider": "claudecode", "label": label("claudecode"), "base_url": "local",
                      "model": "default", "models": CLAUDE_CODE_MODELS})
    for pid in ("ollama", "lmstudio"):
        try:
            models = list_models(pid, PROVIDERS[pid][1], timeout=1)
        except (httpx.HTTPError, ValueError):
            continue
        if models:
            found.append({"provider": pid, "label": label(pid), "base_url": PROVIDERS[pid][1], "model": models[0], "models": models})
    for pid, (name, url, env, default) in PROVIDERS.items():
        if env and os.environ.get(env):
            model, models = default, [default] if default else []
            if not model:
                try:
                    models = list_models(pid, url)
                    model = models[0] if models else ""
                except (httpx.HTTPError, ValueError):
                    pass
            if model:
                found.append({"provider": pid, "label": name, "base_url": url, "model": model, "models": models})
    detected[:] = found
    return found


def auto_connect() -> None:
    """Explicit STUDY_AI_* settings win; otherwise use the first AI the scan finds."""
    if AI_BASE_URL and AI_MODEL:
        configure("custom", AI_BASE_URL, AI_MODEL, AI_KEY, auto=False)
        return
    found = detect()
    if found:
        configure(found[0]["provider"], found[0]["base_url"], found[0]["model"], auto=True)
    else:
        configure("", "", "", auto=True)


def _json_from(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    try:
        data = json.loads(text[start:end + 1] if start >= 0 else text)
    except json.JSONDecodeError:
        raise LLMError("Atlas didn't return the expected format.")
    if not isinstance(data, dict):
        raise LLMError("Atlas didn't return the expected format.")
    return data


async def _chat(client: httpx.AsyncClient, payload: dict) -> dict:
    name = label(cfg["provider"])
    try:
        r = await client.post(f"{cfg['base_url']}/chat/completions", json=payload,
                              headers=_headers(cfg["provider"], resolve_key(cfg["provider"], cfg["key"])))
    except httpx.HTTPError as e:
        raise LLMError(f"Atlas couldn't reach {name} ({e.__class__.__name__}). Is it running?") from e
    if r.status_code == 400 and "response_format" in payload:  # some servers don't support JSON mode
        return await _chat(client, {k: v for k, v in payload.items() if k != "response_format"})
    if r.status_code >= 400:
        raise LLMError(f"{name} returned an error ({r.status_code}): {r.text[:200]}")
    try:
        return r.json()["choices"][0]["message"]
    except (ValueError, KeyError, IndexError):
        raise LLMError(f"{name} sent a reply Atlas couldn't read.")


async def ask(system: str, prompt: str, schema: dict | None = None, tools: list[dict] | None = None, max_turns: int = 3):
    """Returns text, or a dict when a JSON schema is given.
    `tools` are {"name", "description", "parameters", "fn"} dicts; `fn(args)` is async and returns a string."""
    if not available():
        raise LLMError("Atlas is turned off or not connected to an AI.")
    if cfg["provider"] == "claudecode":
        return await _ask_claude_code(system, prompt, schema, tools, max_turns)
    if schema:
        system += "\n\nReply with only a JSON object that matches this JSON schema, no other text:\n" + json.dumps(schema)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    payload: dict = {"model": cfg["model"], "messages": messages}
    if schema:
        payload["response_format"] = {"type": "json_object"}
    if tools:
        payload["tools"] = [{"type": "function", "function": {k: t[k] for k in ("name", "description", "parameters")}}
                            for t in tools]
    by_name = {t["name"]: t for t in tools or []}

    async with httpx.AsyncClient(timeout=180) as client:
        for _ in range(max_turns):
            msg = await _chat(client, payload)
            calls = msg.get("tool_calls") or []
            if not calls:
                text = (msg.get("content") or "").strip()
                return _json_from(text) if schema else text
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for call in calls:
                fn = call.get("function", {})
                try:
                    args = fn.get("arguments") or {}
                    args = json.loads(args) if isinstance(args, str) else args
                    tool = by_name[fn.get("name")]
                    result = await tool["fn"](args)
                except (KeyError, json.JSONDecodeError):
                    result = "Error: unknown tool or bad arguments"
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result})
    return "Done."


async def _ask_claude_code(system: str, prompt: str, schema: dict | None, tools: list[dict] | None, max_turns: int):
    """Claude through the local Claude Code login (Claude Agent SDK), so no API key is needed."""
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, create_sdk_mcp_server, query, tool

    def wrap(t):
        @tool(t["name"], t["description"], t["parameters"])
        async def run_tool(args):
            return {"content": [{"type": "text", "text": await t["fn"](args)}]}
        return run_tool

    servers, allowed = {}, []
    if tools:
        servers["app"] = create_sdk_mcp_server("app", tools=[wrap(t) for t in tools])
        allowed = [f"mcp__app__{t['name']}" for t in tools]
    options = ClaudeAgentOptions(
        system_prompt=system,
        max_turns=max_turns,
        tools=[],  # no built-in Claude Code tools (files, shell...), only ours
        mcp_servers=servers,
        allowed_tools=allowed,
        setting_sources=[],
        extra_args={"no-session-persistence": None},  # don't save every app call as a Claude Code session
        cwd=str(DATA_DIR),
        model=None if cfg["model"] in ("", "default") else cfg["model"],
        output_format={"type": "json_schema", "schema": schema} if schema else None,
    )

    async def run():
        result = None
        async for msg in query(prompt=prompt, options=options):  # read to the end so the stream closes cleanly
            if isinstance(msg, ResultMessage):
                result = msg
        return result

    try:
        result = await asyncio.wait_for(run(), timeout=180)
    except Exception as e:
        raise LLMError(f"Couldn't reach Claude Code ({e}). Is it installed and logged in?") from e
    if result is None or result.is_error:
        raise LLMError("Claude Code returned an error.")
    if schema:
        if not isinstance(result.structured_output, dict):
            raise LLMError("Atlas didn't return the expected format.")
        return result.structured_output
    return (result.result or "").strip()
