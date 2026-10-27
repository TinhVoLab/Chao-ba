"""Offline stand-in for a Gemini Live session (google.genai.live.AsyncSession), for tests and the muted demo.

Enabled on the server with ``CHAOBA_GEMINI_FAKE=1``. No network, no keys, no sound: the "audio" it streams is
digital silence (all-zero 16-bit PCM at 24 kHz), so even an unmuted browser would play nothing audible.

Behaviour, close to the real protocol (messages are real ``google.genai.types`` objects):
  * text sent with ``send_realtime_input(text=...)`` (typed / simulated elder line) or a call to ``elder_speaks`` (test
    helper: streams ``input_transcription`` chunks like the real server does for audio) ends an elder turn; the model
    then calls the blocking ``next_step`` tool;
  * a ``next_step`` / ``flag_emergency`` tool response is "spoken": ``output_transcription`` chunks + silent audio frames + ``turn_complete``
    (mode "silent" -> just ``turn_complete``); after the goodbye line it calls ``end_call``;
  * ``send_client_content(..., turn_complete=True)`` interrupts any running generation (``interrupted``) and, when
    the text contains «…», says what is inside;
  * a new elder turn while speaking = barge-in (``interrupted``);
  * ``usage_metadata`` is sent after every generation (token counts estimated at 25 tokens/s of audio).
Everything sent to the session is kept in ``sent`` so tests can check, e.g., that the recall answer never reaches the
model and that audio bytes are only counted.
"""
from __future__ import annotations

import asyncio
import contextlib
import re
from typing import Any

from google.genai import types

FRAME_MS = 100
FRAME_BYTES = 2 * 24000 * FRAME_MS // 1000      # 16-bit mono PCM @ 24 kHz
SESSIONS: list["FakeLiveSession"] = []            # every session opened in this process (tests inspect the last one)


def _text_of(turns: Any) -> str:
    items = turns if isinstance(turns, list) else [turns]
    out = []
    for c in items:
        parts = c.get("parts") if isinstance(c, dict) else getattr(c, "parts", None)
        for p in parts or []:
            t = p.get("text") if isinstance(p, dict) else getattr(p, "text", None)
            if t:
                out.append(t)
    return " ".join(out)


class FakeLiveSession:
    def __init__(self, config: dict, chunk_delay: float = 0.0, misbehave: str | None = None,
                 words_per_frame: float = 1.0, call_end_tool: bool = True):
        self.config = config
        self.chunk_delay = chunk_delay
        self.misbehave = misbehave            # forbidden phrase appended (once) to the next spoken line
        self.words_per_frame = words_per_frame
        self.call_end_tool = call_end_tool
        self.sent: list[tuple[str, Any]] = []
        self.queue: asyncio.Queue = asyncio.Queue()
        self.closed = False
        self._speaking: asyncio.Task | None = None
        self._n = 0
        self.audio_in_bytes = 0

    # ------------------------------------------------------------------ helpers
    def _put(self, **kw) -> None:
        self.queue.put_nowait(types.LiveServerMessage(**kw))

    def _content(self, **kw) -> None:
        self._put(server_content=types.LiveServerContent(**kw))

    def _interrupt(self) -> None:
        if self._speaking is not None and not self._speaking.done():
            self._speaking.cancel()
            self._content(interrupted=True)
        self._speaking = None

    def _call_tool(self, name: str, args: dict | None = None) -> None:
        self._n += 1
        self._put(tool_call=types.LiveServerToolCall(function_calls=[
            types.FunctionCall(id=f"fc{self._n}", name=name, args=args or {})]))

    def _speak(self, text: str, then_end: bool = False) -> None:
        self._interrupt()
        self._speaking = asyncio.create_task(self._speak_run(text, then_end))

    async def _speak_run(self, text: str, then_end: bool) -> None:
        words = text.split()
        if self.misbehave:
            words += self.misbehave.split()
            self.misbehave = None
        frames = 0
        for i in range(0, len(words), 4):
            chunk = " ".join(words[i:i + 4])
            n = max(1, round(len(words[i:i + 4]) / self.words_per_frame))
            for _ in range(n):
                self._content(model_turn=types.Content(role="model", parts=[types.Part(
                    inline_data=types.Blob(data=bytes(FRAME_BYTES), mime_type="audio/pcm;rate=24000"))]))
            frames += n
            self._content(output_transcription=types.Transcription(text=(" " if i else "") + chunk))
            if self.chunk_delay:
                await asyncio.sleep(self.chunk_delay)
            else:
                await asyncio.sleep(0)
        tokens = int(frames * FRAME_MS / 1000 * 25)
        self._put(usage_metadata=types.UsageMetadata(
            prompt_token_count=40, response_token_count=tokens, total_token_count=40 + tokens,
            prompt_tokens_details=[types.ModalityTokenCount(modality=types.MediaModality.TEXT, token_count=40)],
            response_tokens_details=[types.ModalityTokenCount(modality=types.MediaModality.AUDIO, token_count=tokens)]))
        if then_end and self.call_end_tool:
            self._call_tool("end_call")
        self._content(turn_complete=True)

    # ------------------------------------------------------------------ AsyncSession API
    async def send_realtime_input(self, *, audio=None, text=None, audio_stream_end=None, **kw) -> None:
        if audio is not None:
            data = audio.get("data") if isinstance(audio, dict) else getattr(audio, "data", b"")
            self.audio_in_bytes += len(data or b"")
            self.sent.append(("audio", len(data or b"")))      # length only: the fake never keeps audio either
        if audio_stream_end:
            self.sent.append(("audio_stream_end", True))
        if text:
            self.sent.append(("realtime_text", text))
            self._interrupt()
            self._call_tool("next_step")

    async def send_client_content(self, *, turns=None, turn_complete: bool = True) -> None:
        text = _text_of(turns) if turns is not None else ""
        self.sent.append(("client_content", text))
        if turn_complete:
            self._interrupt()
            m = re.search(r"«(.+?)»", text, re.S)
            if m:
                self._speak(m.group(1))
            else:
                self._content(turn_complete=True)

    async def send_tool_response(self, *, function_responses) -> None:
        items = function_responses if isinstance(function_responses, list) else [function_responses]
        for fr in items:
            name = fr.get("name") if isinstance(fr, dict) else fr.name
            resp = (fr.get("response") if isinstance(fr, dict) else fr.response) or {}
            self.sent.append(("tool_response", {"name": name, "response": resp}))
            if name in ("next_step", "flag_emergency"):
                if resp.get("mode") in ("exact", "adapt") and resp.get("line"):
                    self._speak(resp["line"], then_end=bool(resp.get("end_call_after")))
                else:
                    self._content(turn_complete=True)

    async def receive(self):
        while not self.closed:
            msg = await self.queue.get()
            if msg is None:
                return
            yield msg
            sc = msg.server_content
            if sc is not None and sc.turn_complete:
                return

    async def close(self) -> None:
        self.closed = True
        self._interrupt()
        self.queue.put_nowait(None)

    # ------------------------------------------------------------------ test helpers
    async def elder_speaks(self, text: str, chunks: int = 3, respond: bool = True, gap: float = 0.0) -> None:
        """Stream the elder's words as input transcription (as the real server does for mic audio)."""
        self._interrupt()                                     # barge-in
        words = text.split()
        size = max(1, -(-len(words) // chunks))
        for i in range(0, len(words), size):
            self._content(input_transcription=types.Transcription(text=(" " if i else "") + " ".join(words[i:i + size])))
            await asyncio.sleep(gap)
        if respond:
            self._call_tool("next_step")

    def model_calls(self, name: str, args: dict | None = None) -> None:
        self._call_tool(name, args)

    def all_text_sent(self, include_elder: bool = False) -> str:
        """Everything the system sent to the model (system instruction, system notes, tool results); the elder's own
        typed/simulated words only with include_elder=True."""
        out = [str(self.config.get("system_instruction", ""))]
        for kind, v in self.sent:
            if kind == "client_content" or (include_elder and kind == "realtime_text"):
                out.append(str(v))
            elif kind == "tool_response":
                out.append(repr(v))
        return "\n".join(out)


def fake_connector(**opts):
    @contextlib.asynccontextmanager
    async def connect(config: dict):
        s = FakeLiveSession(config, **opts)
        SESSIONS.append(s)
        del SESSIONS[:-20]
        try:
            yield s
        finally:
            await s.close()
    return connect
