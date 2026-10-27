"""Production adapter sketch: LiveKit Agents (SIP/PSTN + WebRTC) -> the same Orchestrator.

STATUS: UNTESTED. `livekit-agents` is NOT installed in the prototype environment and no LiveKit / SIP trunk / STT /
TTS credentials exist on the build machine. This file documents the intended wiring and is import-guarded so the
rest of the package works without it. Nothing here stores audio: frames flow VAD -> STT in memory and only text plus
VAD timings reach the Orchestrator, exactly like the browser web call.

Pipeline per call (one LiveKit room per call; PSTN legs arrive via LiveKit SIP inbound/outbound trunk):

    caller audio --> Silero VAD --> STT (vi-VN, e.g. Deepgram/Google/FPT.AI) --> Orchestrator.handle_turn()
                      |  utterance start/end + internal silent gaps (pauses)                |
                      +------------------------------------------------------> Turn timings  |
    caller <-- TTS (vi-VN Southern voice, rate ~0.9) <------------------------ reply_text <---+

The Orchestrator owns phases, the emergency spotter, guardrails and the LLM call (ClaudeEngine), so LiveKit's own LLM
node is bypassed: we use the lower-level `VoicePipelineAgent`/`AgentSession` hooks to intercept final transcripts.

Outbound morning calls (production): a scheduler (cron / Supabase pg_cron) creates a room and dials the elder via
`CreateSIPParticipant`; consent and opt-out status are checked first (elder.opted_out).

Run (once credentials exist):
    pip install "livekit-agents[silero,deepgram,google]~=1.0"
    LIVEKIT_URL=... LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=... python -m chaoba.agent.livekit_agent start
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("chaoba.livekit")

try:  # pragma: no cover - optional dependency
    from livekit import agents, rtc  # type: ignore
    from livekit.agents import JobContext, WorkerOptions, cli  # type: ignore
    from livekit.plugins import silero  # type: ignore
    LIVEKIT_AVAILABLE = True
except Exception:  # ImportError when livekit is not installed (the default in this prototype)
    LIVEKIT_AVAILABLE = False


class TurnTimer:
    """Collects VAD events for one elder utterance -> (start, end, pauses) relative to call start.

    Pure Python and unit-testable without LiveKit: feed it `speech_start(t)` / `speech_end(t)` events.
    """

    def __init__(self, call_t0: float | None = None, end_of_turn_silence: float = 1.5):
        self.t0 = call_t0 if call_t0 is not None else time.monotonic()
        self.eot = end_of_turn_silence
        self.start: float | None = None
        self.end: float | None = None
        self.pauses: list[float] = []
        self._last_end: float | None = None

    def speech_start(self, t: float) -> None:
        rel = t - self.t0
        if self.start is None:
            self.start = rel
        elif self._last_end is not None:
            gap = rel - self._last_end
            if gap >= 0.4:
                self.pauses.append(round(gap, 2))
        self._last_end = None

    def speech_end(self, t: float) -> None:
        self._last_end = t - self.t0
        self.end = self._last_end

    def take(self) -> tuple[float, float, list[float]]:
        s, e, p = self.start or 0.0, self.end or (self.start or 0.0), list(self.pauses)
        self.start, self.end, self.pauses, self._last_end = None, None, [], None
        return s, e, p


if LIVEKIT_AVAILABLE:  # pragma: no cover - sketch, not executed in CI
    from .orchestrator import Orchestrator, default_engine

    async def entrypoint(ctx: "JobContext") -> None:
        """One job = one call. Room metadata carries {"elder_id": ...} set by the outbound dialer."""
        import json
        from chaoba.server.db import Store
        from chaoba.server.service import Service

        await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)
        meta = json.loads(ctx.room.metadata or "{}")
        elder_id = meta.get("elder_id", "hanh")
        svc = Service(Store(), Orchestrator(default_engine()))
        started = svc.start_call(elder_id, channel="pstn")
        call_id = started["call_id"]
        timer = TurnTimer()

        # NOTE: exact class names differ between livekit-agents 0.x (VoicePipelineAgent) and 1.x (AgentSession).
        # The shape below follows 1.x; verify against the installed version before enabling.
        from livekit.agents import AgentSession, Agent  # type: ignore
        from livekit.plugins import deepgram, google  # type: ignore

        session = AgentSession(
            vad=silero.VAD.load(min_silence_duration=0.4),
            stt=deepgram.STT(language="vi"),
            tts=google.TTS(language="vi-VN", speaking_rate=0.9),
        )

        @session.on("user_started_speaking")
        def _on_start(_ev):
            timer.speech_start(time.monotonic())

        @session.on("user_stopped_speaking")
        def _on_stop(_ev):
            timer.speech_end(time.monotonic())

        @session.on("user_input_transcribed")
        def _on_transcript(ev):
            if not getattr(ev, "is_final", False):
                return
            start, end, pauses = timer.take()
            out = svc.turn(call_id, ev.transcript, start, end, pauses)
            session.say(out["reply_text"], allow_interruptions=not out["emergency"])
            if out["end_call"]:
                svc.end_call(call_id)
                ctx.shutdown(reason=out.get("event") or "completed")

        await session.start(room=ctx.room, agent=Agent(instructions="(driven by Chào Bà orchestrator)"))
        await session.say(started["greeting_text"])

    def main() -> None:
        cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
else:
    def main() -> None:  # pragma: no cover
        raise SystemExit("livekit-agents is not installed; this adapter is an untested production sketch. "
                         "Use the web call at /call?elder=hanh for the prototype.")


if __name__ == "__main__":  # pragma: no cover
    main()
