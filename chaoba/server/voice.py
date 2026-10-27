"""Optional Gemini Live voice engine: HTTP config + the WebSocket proxy (browser <-> server <-> Gemini Live).

    GET /api/voice/config      -> which engines are available (never any secret)
    WS  /ws/voice/{call_id}    -> protocol in CONTRACT.md ("Voice WebSocket"); the call must have been started with
                                  POST /api/calls {"engine": "gemini"} and got voice.engine == "gemini-live".

The bridge itself (safety interception, tool calls, latency metrics) is chaoba/agent/gemini_live.py. Audio frames are
relayed and counted, never stored.
"""
from __future__ import annotations

import json
import logging

from fastapi import FastAPI, WebSocket

from chaoba.agent import gemini_live as gl

log = logging.getLogger("chaoba.voice")

# Test hook: tests may replace this with a function (creds) -> connector to inject a fake with options.
CONNECTOR_FACTORY = None
BRIDGE_OPTIONS: dict = {}


def register(app: FastAPI) -> None:
    @app.get("/api/voice/config")
    def voice_config():
        return gl.public_voice_config()

    @app.websocket("/ws/voice/{call_id}")
    async def ws_voice(websocket: WebSocket, call_id: str):
        await websocket.accept()
        svc = websocket.app.state.svc
        if call_id not in svc.active or not svc.is_live_call(call_id):
            await websocket.send_text(json.dumps({"type": "error", "error": "unknown_call"}))
            await websocket.close(code=4404)
            return
        creds = gl.gemini_credentials()
        if not creds["available"]:
            await websocket.send_text(json.dumps({"type": "fallback", "reason": "no_credentials",
                                                  "note_vi": "Gemini Live chưa được cấu hình – dùng giọng trình duyệt",
                                                  "note_en": "Gemini Live is not configured – using the browser voice"},
                                                 ensure_ascii=False))
            svc.active[call_id].engine_used = f"{gl.ENGINE_NAME}>browser"
            await websocket.close()
            return

        async def send_json(d: dict) -> None:
            await websocket.send_text(json.dumps(d, ensure_ascii=False))

        async def send_bytes(b: bytes) -> None:
            await websocket.send_bytes(b)

        async def recv():
            try:
                m = await websocket.receive()
            except Exception:
                return None
            if m.get("type") == "websocket.disconnect":
                return None
            if m.get("bytes") is not None:
                return m["bytes"]
            try:
                d = json.loads(m.get("text") or "{}")
            except ValueError:
                return {}
            return d if isinstance(d, dict) else {}

        connector = CONNECTOR_FACTORY(creds) if CONNECTOR_FACTORY else gl.connector_for(creds)
        bridge = gl.LiveBridge(svc, call_id, send_json, send_bytes, connector, mode=creds["mode"], **BRIDGE_OPTIONS)
        try:
            await bridge.run(recv)
        except Exception as e:  # pragma: no cover
            log.exception("voice bridge failed for %s: %s", call_id, e)
        finally:
            try:
                await websocket.close()
            except Exception:
                pass
