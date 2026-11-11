"""
api/app.py

FastAPI application served on the Raspberry Pi (frontend <-> robot bridge).

REST
  POST /api/missions                       receive + validate + store mission -> ack
  GET  /api/missions                       recent missions
  GET  /api/missions/current               ACTIVE/PAUSED mission (or null)
  GET  /api/missions/{mission_id}          status + progress
  POST /api/missions/{mission_id}/start    explicit start authorisation
  POST /api/missions/{mission_id}/pause
  POST /api/missions/{mission_id}/resume
  POST /api/missions/{mission_id}/abort    emergency stop + abort
  POST /api/emergency-stop                 zero motors now (no mission id needed)
  GET  /api/telemetry                      latest live telemetry frame
  GET  /api/sensor-records                 recent local sensor snapshots
  GET  /api/health                         backend + hardware health (no auth)

WebSocket
  /ws/telemetry?token=<API_AUTH_TOKEN>     telemetry frame every TELEMETRY_INTERVAL_S

Auth: if API_AUTH_TOKEN is set, every route except /api/health requires
"Authorization: Bearer <token>" or "X-API-Key: <token>".
"""

from __future__ import annotations

import asyncio
import hmac
import time
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.settings import settings
from mission.manager import MissionError
from mission.validator import MissionValidationError
from monitoring.logger import get_logger

logger = get_logger(__name__)


def _token_ok(token: Optional[str]) -> bool:
    if not settings.API_AUTH_TOKEN:
        return True
    return bool(token) and hmac.compare_digest(token, settings.API_AUTH_TOKEN)


def require_auth(authorization: Optional[str] = Header(default=None),
                 x_api_key: Optional[str] = Header(default=None)) -> None:
    token = x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not _token_ok(token):
        raise HTTPException(status_code=401, detail="invalid or missing API token")


def _origin_allowed(origin: Optional[str]) -> bool:
    allowed = settings.CORS_ALLOWED_ORIGINS
    return origin is None or "*" in allowed or origin in allowed


def create_app(ctx) -> FastAPI:
    """`ctx` is the Application (main.py) exposing missions, telemetry, health, db, stm32."""
    app = FastAPI(title="Lake Bot Autonomous Backend", version="2.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.CORS_ALLOWED_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "X-API-Key", "Content-Type"],
    )
    if not settings.API_AUTH_TOKEN:
        logger.warning("API_AUTH_TOKEN is empty — API is UNAUTHENTICATED (development only)")

    @app.exception_handler(MissionValidationError)
    async def _validation(_req, exc: MissionValidationError):
        return JSONResponse(status_code=422, content={"ok": False, "error": "validation_failed",
                                                      "errors": exc.errors})

    @app.exception_handler(MissionError)
    async def _mission_error(_req, exc: MissionError):
        return JSONResponse(status_code=exc.status_code,
                            content={"ok": False, "error": str(exc), "errors": exc.errors})

    auth = [Depends(require_auth)]

    # ---------------------------------------------------------------- missions
    @app.post("/api/missions", status_code=201, dependencies=auth)
    async def create_mission(request: Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            raise MissionValidationError(["body must be valid JSON"])
        # SQLite + fsync work happens off the event loop.
        return await asyncio.to_thread(ctx.missions.load_mission, body)

    @app.get("/api/missions", dependencies=auth)
    def list_missions(limit: int = Query(default=20, ge=1, le=200)):
        rows = ctx.db.list_missions(limit=limit)
        return {"missions": [ctx.missions.status(r["mission_id"]) for r in rows]}

    @app.get("/api/missions/current", dependencies=auth)
    def current_mission():
        mid = ctx.missions.current_mission_id()
        return {"mission": ctx.missions.status(mid) if mid else None}

    @app.get("/api/missions/{mission_id}", dependencies=auth)
    def get_mission(mission_id: str):
        return ctx.missions.status(mission_id)

    @app.get("/api/missions/{mission_id}/waypoints", dependencies=auth)
    def get_waypoints(mission_id: str):
        ctx.missions.status(mission_id)  # 404 if unknown
        return {"mission_id": mission_id, "waypoints": ctx.db.get_waypoints(mission_id)}

    @app.post("/api/missions/{mission_id}/start", dependencies=auth)
    def start_mission(mission_id: str):
        return ctx.missions.start(mission_id)

    @app.post("/api/missions/{mission_id}/pause", dependencies=auth)
    def pause_mission(mission_id: str):
        return ctx.missions.pause(mission_id)

    @app.post("/api/missions/{mission_id}/resume", dependencies=auth)
    def resume_mission(mission_id: str):
        return ctx.missions.resume(mission_id)

    @app.post("/api/missions/{mission_id}/abort", dependencies=auth)
    def abort_mission(mission_id: str):
        return ctx.missions.abort(mission_id, reason="operator abort / emergency stop")

    @app.post("/api/emergency-stop", dependencies=auth)
    def emergency_stop():
        return ctx.missions.abort(None, reason="emergency stop")

    # ---------------------------------------------------------------- data
    @app.get("/api/telemetry", dependencies=auth)
    def telemetry():
        return ctx.telemetry.frame()

    @app.get("/api/sensor-records", dependencies=auth)
    def sensor_records(mission_id: Optional[str] = None, limit: int = Query(default=100, ge=1, le=1000)):
        return {"records": ctx.db.recent_sensor_records(mission_id=mission_id, limit=limit),
                "counts": ctx.db.sensor_sync_counts()}

    @app.get("/api/health")
    def health():
        snap = ctx.health.snapshot()
        stm = ctx.stm32
        return {
            "status": "ok",
            "device_id": settings.DEVICE_ID,
            "time": time.time(),
            "stm32": {
                "port": settings.STM32_SERIAL_PORT,
                "port_open": bool(stm and stm.connected),
                "link_alive": bool(stm and stm.link_alive),
                "packets_received": getattr(stm, "packets_received", 0),
                "packets_malformed": getattr(stm, "packets_malformed", 0),
                "motor_packets_sent": ctx.motor.packets_sent,
                "motor_send_failures": ctx.motor.send_failures,
            },
            "sqlite_ok": ctx.db.ping(),
            "sensor_records": ctx.db.sensor_sync_counts(),
            "health": snap,
        }

    # ---------------------------------------------------------------- websocket
    clients: set[WebSocket] = set()

    @app.websocket("/ws/telemetry")
    async def ws_telemetry(websocket: WebSocket, token: Optional[str] = None):
        if not _origin_allowed(websocket.headers.get("origin")) or not _token_ok(token):
            await websocket.close(code=1008)
            return
        if len(clients) >= settings.WS_MAX_CLIENTS:
            await websocket.close(code=1013)
            return
        await websocket.accept()
        clients.add(websocket)
        logger.info("WebSocket client connected (%d total)", len(clients))

        async def _drain():  # consume client pings / detect disconnect
            while True:
                await websocket.receive_text()

        reader = asyncio.create_task(_drain())
        try:
            while not reader.done():
                frame = await asyncio.to_thread(ctx.telemetry.frame)
                await websocket.send_json(frame)
                try:
                    await asyncio.wait_for(asyncio.shield(reader), timeout=max(0.5, settings.TELEMETRY_INTERVAL_S))
                except asyncio.TimeoutError:
                    pass
        except (WebSocketDisconnect, RuntimeError):
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("WebSocket error: %s", exc)
        finally:
            reader.cancel()
            clients.discard(websocket)
            logger.info("WebSocket client disconnected (%d total)", len(clients))

    return app
