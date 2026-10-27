"""Gemini Live voice engine (optional): server-side proxy between the browser and a Gemini Live session.

    browser (mic 16 kHz PCM, WebAudio VAD events) --WS /ws/voice/{call_id}--> LiveBridge --google-genai--> Gemini Live
    browser (plays 24 kHz PCM, captions)          <-------------------------- LiveBridge <---------------- (audio, text)

Gemini Live is only the *voice I/O*: it hears the elder, transcribes both sides and speaks. Our Orchestrator stays the
brain. The model must call ``next_step()`` after every elder utterance; the bridge then runs the elder's words (Gemini's
input transcription, or typed/simulated text) through ``Service.turn`` (= ``Orchestrator.handle_turn``: emergency tiers,
opt-out, consent, anti-scam / medication / diagnosis guardrails, phase planner, recall scoring, relay, memory book)
and hands back the line to say: ``mode="exact"`` (safety replies, relay cards, recall question/cue, consent, game,
closing with the medication reminder) or ``mode="adapt"`` (the model may warm up the short reaction, keeps the
question). The hidden recall answer never leaves the server (``build_context_block(hide_recall_answer=True)``).

Safety interception (server side, deterministic, independent of the model):
  * every input-transcription chunk is scanned with the layer-1 emergency spotter; on an *acute* hit the bridge stops
    forwarding model audio, tells the browser to flush playback, closes the mic stream to Gemini, records the turn
    (red alert via Service.turn), makes Gemini say the fixed safety message ("[HỆ THỐNG] Nói đúng nguyên văn: «…»";
    ``turn_complete=True`` interrupts any generation) and ends the call. If Gemini does not start speaking it within
    ``safety_tts_timeout`` the browser speaks it with its own TTS (``{"type":"say"}``).
  * every output-transcription chunk is post-checked (guardrails.forbidden_in_reply); a forbidden phrase interrupts the
    model and the neutral fallback sentence is said instead; the violation is logged in the call's voice metadata.
  * the model's own ``flag_emergency`` tool is layer 2 (Orchestrator.handle_flag), as with the Claude engine.

Audio is stream-through only: never written to disk or database, never kept in memory beyond the frame in flight. The
call's voice metadata (engine, model id, voice, per-turn latency, token usage, interruptions, violations) is stored in
``call_session.voice_json``.

Credentials (never sent to the browser):
  * Gemini Developer API: ``GEMINI_API_KEY`` (or ``GOOGLE_API_KEY``)
  * Vertex AI: ``GOOGLE_GENAI_USE_VERTEXAI=true``, ``GOOGLE_CLOUD_PROJECT``, ``GOOGLE_CLOUD_LOCATION`` (default
    us-central1) + Application Default Credentials (``gcloud auth application-default login`` or a service account)
  * ``CHAOBA_GEMINI_FAKE=1``: offline fake session (tests / muted demo; no network); ``CHAOBA_GEMINI_FAKE=fail``: a
    connector that always fails (fallback demo).

Settings: ``CHAOBA_VOICE_ENGINE`` (browser|gemini), ``CHAOBA_GEMINI_MODEL`` (default ``gemini-3.8-live``),
``CHAOBA_GEMINI_VOICE`` (default ``Sulafat``), ``CHAOBA_GEMINI_LANGUAGE_CODE`` (unset by default: native-audio models
choose the language themselves, the system instruction pins Vietnamese; set ``vi-VN`` to send it explicitly),
``CHAOBA_GEMINI_SILENCE_MS`` (server VAD end-of-speech silence, default 1000 ms: elders pause longer).

Docs used (checked 2026-10-28; see docs/TECHNICAL_DOCUMENTATION.md, "Gemini Live voice engine"):
  https://ai.google.dev/gemini-api/docs/live , .../live-api/get-started-sdk , .../live-api/capabilities ,
  .../live-api/tools , .../live-api/session-management , https://ai.google.dev/gemini-api/docs/ephemeral-tokens ,
  https://ai.google.dev/gemini-api/docs/pricing ,
  https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-live ,
  https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/configure-language-voice
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable

from . import guardrails as g
from .emergency import spot, EMERGENCY_LEXICON
from .orchestrator import ScriptedEngine, CallState
from .prompts import SYSTEM_PROMPT, build_context_block, DailyContext

log = logging.getLogger("chaoba.voice")

DEFAULT_MODEL = "gemini-3.8-live"          # ai.google.dev Live API docs + Vertex model page (GA 2026-09-24)
DEFAULT_VOICE = "Sulafat"                  # "Warm" in the Live API voice list; Southern accent must be judged by people
INPUT_RATE, OUTPUT_RATE = 16000, 24000     # raw 16-bit PCM little-endian, mono
INPUT_MIME = "audio/pcm;rate=16000"
ENGINE_NAME = "gemini-live"

DOC_URLS = [
    "https://ai.google.dev/gemini-api/docs/live",
    "https://ai.google.dev/gemini-api/docs/live-api/get-started-sdk",
    "https://ai.google.dev/gemini-api/docs/live-api/capabilities",
    "https://ai.google.dev/gemini-api/docs/live-api/tools",
    "https://ai.google.dev/gemini-api/docs/live-api/session-management",
    "https://ai.google.dev/gemini-api/docs/ephemeral-tokens",
    "https://ai.google.dev/gemini-api/docs/pricing",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-live",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/configure-language-voice",
]


def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


# --------------------------------------------------------------------------------------------- config / credentials
def gemini_credentials(env: dict | None = None) -> dict:
    """Which credentials are configured. Never returns the key itself.

    -> {"available": bool, "mode": "developer"|"vertex"|"fake"|"fake_fail"|None, "reason": str, ...}"""
    env = os.environ if env is None else env
    fake = (env.get("CHAOBA_GEMINI_FAKE") or "").strip().lower()
    if fake == "fail":
        return {"available": True, "mode": "fake_fail", "reason": "CHAOBA_GEMINI_FAKE=fail (connection always fails)"}
    if _truthy(fake):
        return {"available": True, "mode": "fake", "reason": "CHAOBA_GEMINI_FAKE=1 (offline fake session)"}
    if _truthy(env.get("GOOGLE_GENAI_USE_VERTEXAI")):
        project = (env.get("GOOGLE_CLOUD_PROJECT") or "").strip()
        location = (env.get("GOOGLE_CLOUD_LOCATION") or "us-central1").strip()
        if not project:
            return {"available": False, "mode": "vertex", "reason": "GOOGLE_CLOUD_PROJECT is not set"}
        return {"available": True, "mode": "vertex", "project": project, "location": location,
                "reason": "Vertex AI with Application Default Credentials"}
    if (env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY") or "").strip():
        return {"available": True, "mode": "developer", "reason": "Gemini Developer API key"}
    return {"available": False, "mode": None,
            "reason": "no credentials (set GEMINI_API_KEY, or GOOGLE_GENAI_USE_VERTEXAI=true + GOOGLE_CLOUD_PROJECT)"}


@dataclass
class LiveSettings:
    model: str = DEFAULT_MODEL
    voice: str = DEFAULT_VOICE
    language_code: str | None = None
    silence_ms: int = 1000

    @classmethod
    def from_env(cls, env: dict | None = None) -> "LiveSettings":
        env = os.environ if env is None else env
        try:
            silence = int(env.get("CHAOBA_GEMINI_SILENCE_MS") or 1000)
        except ValueError:
            silence = 1000
        return cls(model=(env.get("CHAOBA_GEMINI_MODEL") or DEFAULT_MODEL).strip(),
                   voice=(env.get("CHAOBA_GEMINI_VOICE") or DEFAULT_VOICE).strip(),
                   language_code=(env.get("CHAOBA_GEMINI_LANGUAGE_CODE") or "").strip() or None,
                   silence_ms=max(300, min(3000, silence)))


def default_voice_engine(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    v = (env.get("CHAOBA_VOICE_ENGINE") or "browser").strip().lower()
    return "gemini" if v in ("gemini", "gemini-live", "gemini_live") else "browser"


def choose_engine(requested: str | None, channel: str = "web", env: dict | None = None) -> dict:
    """Voice engine for a new call: the request (?engine=) wins over CHAOBA_VOICE_ENGINE; Gemini only when credentials
    exist and the call is a web call. -> {"engine": "gemini-live"|"browser", "requested": ..., "note_vi"/"note_en"}"""
    want = (requested or default_voice_engine(env)).strip().lower()
    want = "gemini" if want in ("gemini", "gemini-live", "gemini_live") else "browser"
    out: dict[str, Any] = {"engine": "browser", "requested": want}
    if want != "gemini":
        return out
    creds = gemini_credentials(env)
    if not creds["available"] or channel != "web":
        out["note_vi"] = "Gemini Live chưa được cấu hình – dùng giọng trình duyệt"
        out["note_en"] = "Gemini Live is not configured – using the browser voice"
        out["reason"] = creds["reason"] if not creds["available"] else "web channel only"
        return out
    st = LiveSettings.from_env(env)
    out.update({"engine": ENGINE_NAME, "model": st.model, "voice": st.voice, "mode": creds["mode"],
                "input_rate": INPUT_RATE, "output_rate": OUTPUT_RATE})
    return out


def public_voice_config(env: dict | None = None) -> dict:
    """GET /api/voice/config: what the browser may know (no secrets)."""
    creds = gemini_credentials(env)
    st = LiveSettings.from_env(env)
    default = default_voice_engine(env)
    return {"default_engine": "gemini" if default == "gemini" and creds["available"] else "browser",
            "configured_default": default,
            "gemini": {"available": creds["available"], "mode": creds["mode"], "reason": creds["reason"],
                       "model": st.model, "voice": st.voice, "input_rate": INPUT_RATE, "output_rate": OUTPUT_RATE}}


def privacy_note(env: dict | None = None) -> str:
    creds = gemini_credentials(env)
    if not creds["available"] or creds["mode"] in ("fake", "fake_fail"):
        return ("browser voice (default). Optional Gemini Live engine not configured: when it is turned on, call audio "
                "is streamed through the Chào Bà server to Google (Gemini) for recognition and speech; nothing is stored")
    return ("Gemini Live available (engine=gemini): call audio is streamed through the Chào Bà server to Google "
            f"({'Vertex AI, ' + creds.get('location', '') if creds['mode'] == 'vertex' else 'Gemini Developer API'}) "
            "for recognition and speech, processed outside Vietnam (cross-border transfer); the Chào Bà server never "
            "stores audio, only text and timings")


# --------------------------------------------------------------------------------------------- prompt + tools
LIVE_RULES = """# Live voice call rules (Gemini Live engine) - strict
RESPOND IN VIETNAMESE. YOU MUST RESPOND UNMISTAKABLY IN VIETNAMESE, Southern (miền Tây) register, warm and slow.
- The call system decides the flow of the call, not you. After EVERY time the elder finishes speaking, FIRST call the
  tool next_step() and wait for its result before saying anything. Then speak according to the result:
  * mode "exact": say `line` word for word, nothing before or after it.
  * mode "adapt": you may replace the short reaction at the start of `line` with a brief warm reaction to what the
    elder just said, then ask the question in `line` (same meaning). At most 20 words, exactly one question.
  * mode "silent": say nothing.
- Messages that start with "[HỆ THỐNG]" come from the call system. Obey them at once. When they say
  "Nói đúng nguyên văn", say exactly the sentence inside « », nothing else.
- Never ask questions of your own, never talk about money, bank accounts or codes, never name a disease.
- If the elder interrupts you, stop and listen, then call next_step() again.
- If the elder's words sound like a medical emergency (chest pain, cannot breathe, a fall, fainting, stroke signs,
  seizure, heavy bleeding, not wanting to live) happening to them, call flag_emergency instead of next_step.
- You may call report_answer to note what the elder answered (optional).
- After saying the goodbye line from next_step, call end_call()."""


def live_system_instruction(ctx: DailyContext) -> str:
    """Persona + safety rules (shared with the Claude engine) + live rules + today's context WITHOUT the recall answer."""
    return f"{SYSTEM_PROMPT}\n\n{LIVE_RULES}\n\n{build_context_block(ctx, hide_recall_answer=True)}"


TOOL_DECLARATIONS: list[dict] = [
    {"name": "next_step",
     "description": ("Call FIRST after every elder utterance, before speaking. Records what the elder said and returns "
                     "the next step of the call: {mode: exact|adapt|silent, line, phase, end_call_after}.")},
    {"name": "report_answer",
     "description": "Optional note of what the elder answered (the system scores answers itself).",
     "parameters": {"type": "OBJECT", "properties": {
         "kind": {"type": "STRING", "enum": ["consent", "wellbeing", "relay", "recall", "story", "share", "game",
                                             "other"]},
         "value": {"type": "STRING", "description": "Short summary of the answer, in Vietnamese."}},
         "required": ["kind", "value"]}},
    {"name": "flag_emergency",
     "description": ("Call immediately if the elder describes a possible medical emergency or risk of self-harm "
                     "happening to THEM. acute=true if now/today/cannot get up/self-harm; acute=false if clearly over. "
                     "Not for events that happened to someone else or for mild everyday aches."),
     "parameters": {"type": "OBJECT", "properties": {
         "category": {"type": "STRING", "enum": sorted(EMERGENCY_LEXICON.keys()) + ["other"]},
         "quote": {"type": "STRING", "description": "The elder's words, verbatim."},
         "acute": {"type": "BOOLEAN"}},
         "required": ["category", "quote", "acute"]}},
    {"name": "end_call",
     "description": "Call only after you have said the goodbye line that next_step gave you."},
]


def build_live_config(ctx: DailyContext, settings: LiveSettings | None = None) -> dict:
    """LiveConnectConfig (as a dict) for one call."""
    st = settings or LiveSettings.from_env()
    speech: dict[str, Any] = {"voice_config": {"prebuilt_voice_config": {"voice_name": st.voice}}}
    if st.language_code:
        speech["language_code"] = st.language_code
    return {
        "response_modalities": ["AUDIO"],
        "system_instruction": live_system_instruction(ctx),
        "speech_config": speech,
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "realtime_input_config": {
            "automatic_activity_detection": {"end_of_speech_sensitivity": "END_SENSITIVITY_LOW",
                                             "prefix_padding_ms": 200, "silence_duration_ms": st.silence_ms},
            "activity_handling": "START_OF_ACTIVITY_INTERRUPTS",   # barge-in: the elder can interrupt Út Thương
        },
        "tools": [{"function_declarations": TOOL_DECLARATIONS}],
    }


class LiveLineEngine(ScriptedEngine):
    """Writes the line Gemini voices (deterministic, keyless); Gemini may only warm up the reaction ("adapt")."""
    name = ENGINE_NAME


# Steps whose line must be said word for word (cards, recall question/cue, consent, game, medication reminder).
EXACT_STEPS = {"relay", "story_share", "recall_free", "recall_cue", "activity_game", "closing"}


def clean_line(text: str) -> str:
    """Drop the "(Lan nhắn)" stage prefix (the browser TTS strips it too) and squeeze spaces."""
    return re.sub(r"\s+", " ", re.sub(r"^\([^)]*\)\s*", "", (text or "").strip())).strip()


def say_exact_prompt(text: str, urgent: bool = False) -> str:
    head = "[HỆ THỐNG – KHẨN] Ngưng ngay. " if urgent else "[HỆ THỐNG] "
    return f"{head}Nói đúng nguyên văn câu sau, không thêm bớt: «{clean_line(text)}»"


# --------------------------------------------------------------------------------------------- turn timing (VAD)
class TurnTimer:
    """Elder speech segments from the browser's WebAudio VAD events (browser clock, seconds since call start)."""

    def __init__(self) -> None:
        self.segments: list[tuple[float, float]] = []
        self.open_start: float | None = None
        self.last_t: float | None = None
        self.last_end_mono: float | None = None
        self.explicit: tuple[float | None, float | None, list[float]] | None = None

    def speech(self, t: float) -> None:
        self.last_t = t
        if self.open_start is None:
            self.open_start = t

    def silence(self, t: float) -> None:
        self.last_t = t
        if self.open_start is not None:
            self.segments.append((self.open_start, max(t, self.open_start)))
            self.open_start = None
            self.last_end_mono = time.monotonic()

    def take_end_mono(self) -> float | None:
        """Server time at which the last speech segment ended (latency anchor), once."""
        out, self.last_end_mono = self.last_end_mono, None
        return out

    def has_speech(self) -> bool:
        return bool(self.segments) or self.open_start is not None or self.explicit is not None

    def consume(self) -> tuple[float | None, float | None, list[float]]:
        if self.explicit is not None:
            out, self.explicit = self.explicit, None
            self.segments, self.open_start = [], None
            return out
        segs = list(self.segments)
        if self.open_start is not None:
            segs.append((self.open_start, max(self.last_t or self.open_start, self.open_start)))
        self.segments, self.open_start = [], None
        if not segs:
            return None, None, []
        pauses = [round(b0 - a1, 2) for (_, a1), (b0, _) in zip(segs, segs[1:]) if b0 - a1 >= 0.4]
        return round(segs[0][0], 2), round(segs[-1][1], 2), pauses


# --------------------------------------------------------------------------------------------- connectors
Connector = Callable[[dict], "contextlib.AbstractAsyncContextManager[Any]"]


def make_client(creds: dict | None = None):
    """google-genai client for the configured credentials (imported lazily)."""
    from google import genai
    creds = creds or gemini_credentials()
    if creds.get("mode") == "vertex":
        return genai.Client(vertexai=True, project=creds["project"], location=creds["location"])
    return genai.Client(api_key=(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")))


def gemini_connector(settings: LiveSettings | None = None, creds: dict | None = None) -> Connector:
    st = settings or LiveSettings.from_env()

    @contextlib.asynccontextmanager
    async def connect(config: dict):
        client = make_client(creds)
        async with client.aio.live.connect(model=st.model, config=config) as session:
            yield session
    return connect


def failing_connector(reason: str = "fake connection failure") -> Connector:
    @contextlib.asynccontextmanager
    async def connect(config: dict):
        raise ConnectionError(reason)
        yield  # pragma: no cover
    return connect


def connector_for(creds: dict | None = None, settings: LiveSettings | None = None) -> Connector:
    creds = creds or gemini_credentials()
    if creds["mode"] == "fake":
        from .gemini_fake import fake_connector
        delay = float(os.environ.get("CHAOBA_GEMINI_FAKE_DELAY") or 0.02)
        return fake_connector(chunk_delay=delay)
    if creds["mode"] == "fake_fail":
        return failing_connector()
    return gemini_connector(settings, creds)


# --------------------------------------------------------------------------------------------- the bridge
SendJson = Callable[[dict], Awaitable[None]]
SendBytes = Callable[[bytes], Awaitable[None]]
Recv = Callable[[], Awaitable["dict | bytes | None"]]


def _content(text: str) -> dict:
    return {"role": "user", "parts": [{"text": text}]}


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return round(s[k], 1)


class LiveBridge:
    """One elder call on the Gemini Live engine. Transport-agnostic: the WebSocket endpoint (server/voice.py) passes
    `send_json`/`send_bytes` (to the browser) and `recv` (from the browser); `connector(config)` opens the Gemini
    session (real, fake or failing)."""

    def __init__(self, svc, call_id: str, send_json: SendJson, send_bytes: SendBytes, connector: Connector,
                 settings: LiveSettings | None = None, mode: str | None = None, silence_sec: float = 20.0,
                 safety_tts_timeout: float = 3.0, connect_timeout: float = 10.0, end_grace_sec: float = 15.0,
                 tick: float = 0.2):
        self.svc, self.call_id = svc, call_id
        self.state: CallState = svc.active[call_id]
        self._send_json, self._send_bytes = send_json, send_bytes
        self.connector = connector
        self.settings = settings or LiveSettings.from_env()
        self.silence_sec, self.safety_tts_timeout = silence_sec, safety_tts_timeout
        self.connect_timeout, self.end_grace_sec, self.tick = connect_timeout, end_grace_sec, tick
        self.config = build_live_config(self.state.ctx, self.settings)
        self.session: Any = None
        self.lock = asyncio.Lock()
        self.timer = TurnTimer()
        self.elder_buf = ""
        self.agent_buf = ""
        self.suppress = False            # drop model audio/text (interrupted generation still draining)
        self.waiting_gen_end = False     # lift `suppress` once the interrupted generation ends
        self.gen_active = False
        self.mic_closed = False          # after an emergency the mic is no longer forwarded to Gemini
        self.emergency_handled = False
        self.end_after_turn = False
        self.corrected = False
        self.finished = False
        self.client_gone = False
        self.in_tool = 0
        self.line_issued_at: float | None = None
        self.gen_had_line = False        # the current generation was asked for (tool response / say)
        self._last_elder_chunk = 0.0
        self.spoke_since_line = False
        self.safety_text: str | None = None
        self.safety_started = False
        self._turn_t0: float | None = None
        self._t_connect: float | None = None
        self._last_activity = time.monotonic()
        self._tasks: set[asyncio.Task] = set()
        self.meta: dict[str, Any] = {
            "engine": ENGINE_NAME, "model": self.settings.model, "voice": self.settings.voice,
            "language_code": self.settings.language_code, "mode": mode, "silence_ms": self.settings.silence_ms,
            "time_to_first_audio_ms": None, "latency_ms": [], "latency_p50_ms": None, "latency_p90_ms": None,
            "usage": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0},
            "tool_calls": {}, "interruptions": 0, "violations": [], "model_reports": [], "missed_next_step": 0,
            "audio_in_bytes": 0, "audio_out_bytes": 0, "audio_stored": False, "fallback": None,
            "safety_tts_fallback": False, "end_reason": None,
        }

    # ------------------------------------------------------------------ transport helpers
    async def send_json(self, d: dict) -> None:
        if self.client_gone:
            return
        try:
            await self._send_json(d)
        except Exception:   # browser went away
            self.client_gone = True

    async def send_bytes(self, b: bytes) -> None:
        if self.client_gone:
            return
        try:
            await self._send_bytes(b)
        except Exception:
            self.client_gone = True

    def _spawn(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    @property
    def h(self) -> str:
        return self.state.ev.honorific

    # ------------------------------------------------------------------ lifecycle
    async def run(self, recv: Recv) -> dict:
        cm = self.connector(self.config)
        self._t_connect = time.monotonic()
        try:
            self.session = await asyncio.wait_for(cm.__aenter__(), timeout=self.connect_timeout)
        except Exception as e:   # no network, bad credentials, quota, unknown model...
            log.warning("Gemini Live connect failed for %s: %s", self.call_id, e)
            await self._fallback(f"connect_failed: {type(e).__name__}")
            self._save_meta()
            return self.meta
        tasks: list[asyncio.Task] = []
        try:
            await self.send_json({"type": "ready", "engine": ENGINE_NAME, "model": self.settings.model,
                                  "voice": self.settings.voice, "input_rate": INPUT_RATE, "output_rate": OUTPUT_RATE})
            greeting = next((t.text for t in self.state.turns if t.speaker == "agent"), "")
            await self.send_json({"type": "transcript", "who": "agent", "text": clean_line(greeting), "final": False,
                                  "greeting": True})
            await self._say(greeting)
            tasks = [asyncio.create_task(self._client_pump(recv)), asyncio.create_task(self._model_pump()),
                     asyncio.create_task(self._watchdog())]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks + list(self._tasks):
                t.cancel()
            for t in tasks + list(self._tasks):
                with contextlib.suppress(BaseException):
                    await t
            with contextlib.suppress(BaseException):
                await cm.__aexit__(None, None, None)
            self._save_meta()
        return self.meta

    def _save_meta(self) -> None:
        lat = self.meta["latency_ms"]
        self.meta["latency_p50_ms"], self.meta["latency_p90_ms"] = _pct(lat, 0.5), _pct(lat, 0.9)
        self.meta["end_reason"] = self.meta["end_reason"] or self.state.end_reason
        try:
            self.svc.store.set_call_voice(self.call_id, self.meta)
        except Exception as e:  # pragma: no cover
            log.warning("voice meta not saved: %s", e)

    async def _fallback(self, reason: str) -> None:
        self.meta["fallback"] = reason
        self.state.engine_used = f"{ENGINE_NAME}>browser"
        self.finished = True
        await self.send_json({"type": "fallback", "reason": reason,
                              "note_vi": "Không kết nối được Gemini Live – chuyển sang giọng trình duyệt",
                              "note_en": "Could not reach Gemini Live – switched to the browser voice"})

    async def _finish(self, reason: str) -> None:
        if self.finished:
            return
        self.finished = True
        self.meta["end_reason"] = self.state.end_reason or reason
        await self.send_json({"type": "ended", "reason": reason, "end_reason": self.state.end_reason or reason})

    # ------------------------------------------------------------------ speaking
    async def _say(self, text: str, urgent: bool = False) -> None:
        """Make Gemini say `text` word for word (turn_complete=True also interrupts a running generation)."""
        self.line_issued_at, self.spoke_since_line, self.gen_had_line = time.monotonic(), False, True
        await self.session.send_client_content(turns=_content(say_exact_prompt(text, urgent)), turn_complete=True)

    def _stop_model_audio(self) -> None:
        if self.gen_active:
            self.suppress, self.waiting_gen_end = True, True
        self.agent_buf = ""

    # ------------------------------------------------------------------ browser -> Gemini
    async def _client_pump(self, recv: Recv) -> None:
        while not self.finished:
            m = await recv()
            if m is None:
                self.client_gone = True
                return
            if isinstance(m, (bytes, bytearray)):
                await self._on_client_audio(bytes(m))
            elif isinstance(m, dict):
                await self._on_client_msg(m)

    async def _on_client_audio(self, data: bytes) -> None:
        if self.mic_closed or self.finished or not data:
            return
        self.meta["audio_in_bytes"] += len(data)       # counted, never kept
        await self.session.send_realtime_input(audio={"data": data, "mime_type": INPUT_MIME})

    async def _on_client_msg(self, m: dict) -> None:
        kind = m.get("type")
        if kind == "vad":
            t = float(m.get("t") or 0.0)
            if m.get("state") == "speech":
                self.timer.speech(t)
            else:
                self.timer.silence(t)
            self._last_activity = time.monotonic()
        elif kind == "text":
            await self._on_client_text(m)
        elif kind == "playback":
            self._last_activity = time.monotonic()
        elif kind == "end":
            await self._finish("client_end")

    async def _on_client_text(self, m: dict) -> None:
        """Typed or simulated elder line: no audio, so the bridge has the text itself (no input transcription)."""
        text = re.sub(r"\s+", " ", str(m.get("text") or "")).strip()
        if not text or self.finished or self.emergency_handled:
            return
        if m.get("start") is not None or m.get("end") is not None:
            self.timer.explicit = (m.get("start"), m.get("end"), [float(p) for p in (m.get("pauses") or [])])
        self.elder_buf = text
        self._last_activity = time.monotonic()
        await self.send_json({"type": "transcript", "who": "elder", "text": text, "final": False})
        if await self._scan_input():
            return
        self._turn_t0 = time.monotonic()
        await self.session.send_realtime_input(text=text)

    # ------------------------------------------------------------------ Gemini -> browser
    async def _model_pump(self) -> None:
        try:
            while not self.finished:
                got = False
                async for msg in self.session.receive():
                    got = True
                    await self._on_model_msg(msg)
                    if self.finished:
                        return
                if not got:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("Gemini Live stream error for %s: %s", self.call_id, e)
        if not self.finished:
            await self._fallback("gemini_disconnected")

    async def _on_model_msg(self, msg: Any) -> None:
        um = getattr(msg, "usage_metadata", None)
        if um is not None:
            u = self.meta["usage"]
            u["prompt_tokens"] += int(getattr(um, "prompt_token_count", 0) or 0)
            u["response_tokens"] += int(getattr(um, "response_token_count", 0) or 0)
            u["total_tokens"] += int(getattr(um, "total_token_count", 0) or 0)
            for key, attr in (("prompt_by_modality", "prompt_tokens_details"),
                              ("response_by_modality", "response_tokens_details")):
                for d in (getattr(um, attr, None) or []):
                    mod = str(getattr(getattr(d, "modality", None), "value", getattr(d, "modality", "")) or "?")
                    bucket = u.setdefault(key, {})
                    bucket[mod] = bucket.get(mod, 0) + int(getattr(d, "token_count", 0) or 0)
        tc = getattr(msg, "tool_call", None)
        if tc is not None:
            for fc in (getattr(tc, "function_calls", None) or []):
                self.in_tool += 1
                self._spawn(self._handle_tool(fc))
        if getattr(msg, "go_away", None) is not None:
            log.info("Gemini Live go_away for %s: %s", self.call_id, getattr(msg.go_away, "time_left", None))
        sc = getattr(msg, "server_content", None)
        if sc is None:
            return
        it = getattr(sc, "input_transcription", None)
        if it is not None and getattr(it, "text", None):
            await self._on_elder_text(it.text)
        if getattr(sc, "interrupted", None):
            await self._on_interrupted()
        mt = getattr(sc, "model_turn", None)
        if mt is not None:
            for part in (getattr(mt, "parts", None) or []):
                inline = getattr(part, "inline_data", None)
                if inline is not None and getattr(inline, "data", None):
                    await self._on_audio(inline.data)
        ot = getattr(sc, "output_transcription", None)
        if ot is not None and getattr(ot, "text", None):
            await self._on_agent_text(ot.text)
        if getattr(sc, "turn_complete", None):
            await self._on_turn_complete()

    async def _on_audio(self, data: bytes) -> None:
        if self.suppress or self.finished:
            return
        self.gen_active, self.spoke_since_line = True, True
        if self.safety_text is not None:
            self.safety_started = True
        now = time.monotonic()
        if self.meta["time_to_first_audio_ms"] is None and self._t_connect is not None:
            self.meta["time_to_first_audio_ms"] = round((now - self._t_connect) * 1000, 1)
        if self._turn_t0 is not None:
            self.meta["latency_ms"].append(round((now - self._turn_t0) * 1000, 1))
            self._turn_t0 = None
        self.meta["audio_out_bytes"] += len(data)
        await self.send_bytes(data)                       # stream-through: never stored

    async def _on_elder_text(self, chunk: str) -> None:
        if self.emergency_handled or self.finished:
            return
        self.elder_buf = re.sub(r"\s+", " ", self.elder_buf + chunk)
        self._last_activity = self._last_elder_chunk = time.monotonic()
        await self.send_json({"type": "transcript", "who": "elder", "text": self.elder_buf.strip(), "final": False})
        await self._scan_input()

    async def _scan_input(self) -> bool:
        """Layer-1 emergency spotter on the streaming elder transcript; acute -> interrupt and handle now."""
        hit = spot(self.elder_buf, self.h)
        if hit is not None and hit.tier == "acute":
            await self._emergency_now()
            return True
        return False

    async def _on_agent_text(self, chunk: str) -> None:
        if self.suppress or self.finished:
            return
        self.spoke_since_line = self.gen_active = True
        if self.safety_text is not None:
            self.safety_started = True
        self.agent_buf += chunk
        await self.send_json({"type": "transcript", "who": "agent", "text": self.agent_buf.strip(), "final": False})
        bad = None if self.corrected else g.forbidden_in_reply(self.agent_buf)
        if bad:
            await self._correct(bad)

    async def _correct(self, bad: str) -> None:
        """Output post-check failed: interrupt the model and say the neutral sentence instead."""
        self.corrected = True
        quote = self.agent_buf.strip()[-200:]
        self.meta["violations"].append({"match": bad, "text": quote, "t": round(self.state.elapsed(), 1)})
        log.warning("Gemini output violation in %s: %r in %r", self.call_id, bad, quote)
        self._stop_model_audio()
        await self.send_json({"type": "interrupt", "reason": "correction"})
        fix = g.safe_fallback(self.h)
        self._set_last_agent_text(fix)
        await self._say(fix, urgent=True)

    async def _on_interrupted(self) -> None:
        self.meta["interruptions"] += 1
        self.gen_active = False
        self.agent_buf = ""
        if self.waiting_gen_end:
            self.suppress, self.waiting_gen_end = False, False
        await self.send_json({"type": "interrupt", "reason": "barge_in"})

    async def _on_turn_complete(self) -> None:
        self.gen_active = False
        if self.waiting_gen_end:                  # end of the generation we cut off; the replacement comes next
            self.suppress, self.waiting_gen_end = False, False
            self.agent_buf = ""
            return
        spoken = self.agent_buf.strip()
        self.agent_buf = ""
        if spoken:
            await self.send_json({"type": "transcript", "who": "agent", "text": spoken, "final": True})
            if not self.corrected:
                self._set_last_agent_text(spoken)
        self.corrected = False
        had_line, self.gen_had_line = self.gen_had_line, False
        if self.elder_buf.strip() and not had_line and not self.in_tool and not self.emergency_handled:
            # The model answered without calling next_step: keep the state machine in step anyway and say the
            # deterministic line when it matters (safety / guardrail / closing).
            self.meta["missed_next_step"] += 1
            async with self.lock:
                res = await self._process_elder_turn()
            if res is not None and (self._is_exact(res) or res.get("end_call")):
                await self._say(res["reply_text"], urgent=bool(res.get("emergency")))
            return
        await self.send_json({"type": "agent_done"})
        self._last_activity = time.monotonic()
        if self.end_after_turn and self.spoke_since_line:
            await self._finish("emergency" if self.state.emergency else "completed")

    def _set_last_agent_text(self, text: str) -> None:
        """The transcript keeps what was actually said (output transcription), not the planned line."""
        for t in reversed(self.state.turns):
            if t.speaker == "agent":
                t.text = text
                return

    # ------------------------------------------------------------------ elder turns -> orchestrator
    async def _process_elder_turn(self) -> dict | None:
        """Hand the elder's words (+ VAD timings) to Service.turn. Caller holds self.lock."""
        text = re.sub(r"\s+", " ", self.elder_buf).strip()
        self.elder_buf = ""
        end_mono = self.timer.take_end_mono()
        start, end, pauses = self.timer.consume()
        if self._turn_t0 is None:   # typed/sim lines set it when sent; voice turns use the VAD end of speech
            now = time.monotonic()
            self._turn_t0 = end_mono if end_mono is not None and now - end_mono < 10 else now
        try:
            res = await asyncio.to_thread(self.svc.turn, self.call_id, text, start, end, pauses)
        except KeyError:
            return None
        await self._after_turn(text, res)
        return res

    async def _after_turn(self, text: str, res: dict) -> None:
        if text:
            await self.send_json({"type": "transcript", "who": "elder", "text": text, "final": True})
        await self.send_json({"type": "turn", **res})
        if res.get("emergency"):
            await self._close_mic()
            self.emergency_handled = True
            self.safety_text = res.get("reply_text") or ""
            self._spawn(self._safety_tts_watch(self.safety_text))
        if res.get("end_call"):
            self.end_after_turn = True

    async def _close_mic(self) -> None:
        if self.mic_closed:
            return
        self.mic_closed = True
        with contextlib.suppress(Exception):
            await self.session.send_realtime_input(audio_stream_end=True)

    def _is_exact(self, res: dict) -> bool:
        ev = res.get("event")
        return bool(ev and ev != "symptom_followup") or self.state.step in EXACT_STEPS or bool(res.get("end_call"))

    def _instruction(self, res: dict) -> dict:
        line = clean_line(res.get("reply_text") or "")
        self.line_issued_at, self.spoke_since_line, self.gen_had_line = time.monotonic(), False, True
        out = {"phase": res.get("phase"), "line": line, "end_call_after": bool(res.get("end_call"))}
        if not line:
            return out | {"mode": "silent", "instruction": "Không nói gì."}
        if self._is_exact(res):
            return out | {"mode": "exact", "instruction": f"Nói đúng nguyên văn: «{line}»"}
        return out | {"mode": "adapt",
                      "instruction": ("Phản ứng thật ngắn, ấm áp với điều người cao tuổi vừa nói, rồi hỏi câu hỏi trong "
                                      f"câu này (giữ nguyên ý, tối đa 20 từ, một câu hỏi): «{line}»")}

    async def _emergency_now(self) -> None:
        """Acute emergency heard in the streaming transcript: cut the model off and handle it deterministically."""
        async with self.lock:
            if self.emergency_handled or self.finished:
                return
            self.emergency_handled = True       # set first: concurrent next_step calls go silent
            self._stop_model_audio()
            await self.send_json({"type": "interrupt", "reason": "safety"})
            await self._close_mic()
            res = await self._process_elder_turn()
            if res is None:
                return
            if not res.get("emergency"):          # pragma: no cover - layer-1 already said acute
                return
            await self._say(res["reply_text"], urgent=True)

    async def _safety_tts_watch(self, text: str) -> None:
        """If Gemini does not start saying the safety message in time, the browser says it (its own TTS)."""
        await asyncio.sleep(self.safety_tts_timeout)
        if self.finished or self.safety_started:
            return
        self.meta["safety_tts_fallback"] = True
        self.suppress, self.waiting_gen_end = True, False     # Gemini stays silent from here on
        await self.send_json({"type": "say", "text": clean_line(text), "reason": "safety_fallback"})
        await self._finish("emergency")

    # ------------------------------------------------------------------ tools
    async def _handle_tool(self, fc: Any) -> None:
        name = getattr(fc, "name", "") or ""
        args = dict(getattr(fc, "args", None) or {})
        self.meta["tool_calls"][name] = self.meta["tool_calls"].get(name, 0) + 1
        try:
            if name == "next_step":
                resp = await self._tool_next_step()
            elif name == "report_answer":
                self.meta["model_reports"].append({"kind": str(args.get("kind", "other"))[:20],
                                                   "value": str(args.get("value", ""))[:200]})
                resp = {"ok": True}
            elif name == "flag_emergency":
                resp = await self._tool_flag_emergency(args)
            elif name == "end_call":
                resp = self._tool_end_call()
            else:
                resp = {"error": f"unknown tool {name}"}
        except Exception as e:  # never leave the model waiting on a blocking call
            log.exception("tool %s failed: %s", name, e)
            resp = {"mode": "silent", "instruction": "Không nói gì."}
        finally:
            self.in_tool = max(0, self.in_tool - 1)
        with contextlib.suppress(Exception):
            await self.session.send_tool_response(function_responses=[
                {"id": getattr(fc, "id", None), "name": name, "response": resp}])

    async def _tool_next_step(self) -> dict:
        async with self.lock:
            if self.emergency_handled or self.finished:
                return {"mode": "silent", "instruction": "Không nói gì thêm."}
            for _ in range(16):   # transcription can trail the end of speech by a few hundred ms
                if self.elder_buf.strip() and time.monotonic() - self._last_elder_chunk > 0.25:
                    break
                await asyncio.sleep(0.05)
            if not self.elder_buf.strip() and not self.timer.has_speech():
                return {"mode": "silent", "instruction": "Chưa có lời mới của người cao tuổi. Im lặng chờ."}
            res = await self._process_elder_turn()
            if res is None:
                return {"mode": "silent", "instruction": "Cuộc gọi đã kết thúc."}
            return self._instruction(res)

    async def _tool_flag_emergency(self, args: dict) -> dict:
        async with self.lock:
            if self.emergency_handled or self.finished:
                return {"mode": "silent", "instruction": "Không nói gì thêm."}
            text = re.sub(r"\s+", " ", self.elder_buf).strip()
            self.elder_buf = ""
            start, end, pauses = self.timer.consume()
            try:
                res = await asyncio.to_thread(self.svc.flag_emergency, self.call_id, text,
                                              str(args.get("category", "other")), str(args.get("quote") or text),
                                              bool(args.get("acute", True)), start, end, pauses)
            except KeyError:
                return {"mode": "silent", "instruction": "Cuộc gọi đã kết thúc."}
            await self._after_turn(text, res)
            return self._instruction(res)

    def _tool_end_call(self) -> dict:
        if self.state.step == "closing" or self.state.ended or self.end_after_turn:
            self.end_after_turn = True
            if not self.gen_active and self.spoke_since_line:
                self._spawn(self._finish("completed"))
            return {"ok": True}
        return {"ok": False, "instruction": "Chưa tới lúc chào tạm biệt. Gọi next_step() sau khi người cao tuổi nói."}

    # ------------------------------------------------------------------ watchdog (silence, stuck endings)
    async def _watchdog(self) -> None:
        while not self.finished:
            await asyncio.sleep(self.tick)
            now = time.monotonic()
            if self.client_gone:
                return
            if (self.end_after_turn and self.line_issued_at is not None and not self.gen_active
                    and now - self.line_issued_at > self.end_grace_sec):
                await self._finish("emergency" if self.state.emergency else "completed")
                return
            busy = (self.gen_active or self.in_tool or self.timer.open_start is not None
                    or self.emergency_handled or self.end_after_turn)
            if not busy and now - self._last_activity > self.silence_sec:
                # The elder said nothing (or only trailing words nobody answered): same as a turn in the browser
                # pipeline that ends on silence.
                self._last_activity = now
                async with self.lock:
                    res = await self._process_elder_turn()
                if res is None:
                    return
                line = clean_line(res.get("reply_text") or "")
                if line:
                    await self._say(line, urgent=bool(res.get("emergency")))
