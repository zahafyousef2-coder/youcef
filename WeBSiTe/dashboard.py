import asyncio
import os
import json
import time
import secrets
from typing import Dict, Any, Optional, Callable
from aiohttp import web

ADMIN_USER = "admin"
ADMIN_PASS = "udp"


class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.account_credentials: Dict[str, Dict] = {}
        self.refresh_callbacks: Dict[str, Callable] = {}
        self.logs: list = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.exp_targets_ref: Dict[str, int] = {}
        self.start_exp_ref: Dict[str, int] = {}
        self.exp_limit_reached_ref: set = set()
        self.account_start_ref: Dict[str, float] = {}
        self.session_matches_ref: Dict[str, int] = {}
        self.max_exp_target: int = 50000
        self.default_exp_limit: int = 46000

    def bind_loop(self):
        self._loop = asyncio.get_running_loop()

    def register_account(self, uid, nickname, region, level, exp, likes=0):
        uid = str(uid)
        existing = self.accounts.get(uid, {})
        self.accounts[uid] = {
            "uid": uid,
            "nickname": nickname or existing.get("nickname") or f"Player_{uid}",
            "region": region or existing.get("region") or "ME",
            "level": int(level) if level else existing.get("level", 1),
            "exp": int(exp) if exp else existing.get("exp", 0),
            "likes": int(likes) if likes else existing.get("likes", 0),
            "status": existing.get("status", "CONNECTING"),
            "active_matches": existing.get("active_matches", 0),
            "matches_played": existing.get("matches_played", 0),
            "banner_png": existing.get("banner_png", ""),
            "banner_mime": existing.get("banner_mime", "image/png"),
            "password": existing.get("password", ""),
            "target": existing.get("target", 0),
        }

    def update_status(self, uid, status, active_matches=None):
        uid = str(uid)
        if uid in self.accounts:
            self.accounts[uid]["status"] = status
            if active_matches is not None:
                self.accounts[uid]["active_matches"] = int(active_matches)

    def update_exp(self, uid, exp, level=None):
        uid = str(uid)
        if uid in self.accounts:
            self.accounts[uid]["exp"] = int(exp)
            if level is not None:
                self.accounts[uid]["level"] = int(level)

    def update_exp_target(self, uid, target):
        uid = str(uid)
        if uid in self.accounts:
            self.accounts[uid]["target"] = int(target)

    def increment_match(self, uid):
        uid = str(uid)
        if uid in self.accounts:
            self.accounts[uid]["active_matches"] = self.accounts[uid].get("active_matches", 0) + 1
            self.accounts[uid]["matches_played"] = self.accounts[uid].get("matches_played", 0) + 1

    def log(self, message, level="info"):
        self.logs.append({"t": time.time(), "level": level, "msg": str(message)})
        self.logs = self.logs[-500:]


bot_state = BotState()

_sessions: Dict[str, float] = {}
SESSION_TTL = 8 * 3600


def _new_session():
    tok = secrets.token_urlsafe(32)
    _sessions[tok] = time.time() + SESSION_TTL
    return tok


def _valid_session(tok):
    exp = _sessions.get(tok)
    if not exp or exp < time.time():
        _sessions.pop(tok, None)
        return False
    return True


def _authed(request):
    return _valid_session(request.cookies.get("yazan_sess", ""))


async def api_login(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
    if data.get("username") == ADMIN_USER and data.get("password") == ADMIN_PASS:
        tok = _new_session()
        resp = web.json_response({"ok": True})
        resp.set_cookie("yazan_sess", tok, httponly=True, samesite="Lax", max_age=SESSION_TTL)
        return resp
    return web.json_response({"ok": False, "error": "Invalid credentials"}, status=401)


async def api_logout(request: web.Request):
    _sessions.pop(request.cookies.get("yazan_sess", ""), None)
    resp = web.json_response({"ok": True})
    resp.del_cookie("yazan_sess")
    return resp


async def api_me(request: web.Request):
    return web.json_response({"authed": _authed(request)})


async def api_generate(request: web.Request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    bot_name = str(data.get("bot_name", "")).strip()
    target_uid = str(data.get("target_uid", "")).strip()
    region = str(data.get("region", "ME")).strip().upper()

    if not bot_name:
        return web.json_response({"ok": False, "error": "Bot name is required"}, status=400)
    if not target_uid or not target_uid.isdigit():
        return web.json_response({"ok": False, "error": "Target UID must be numeric"}, status=400)
    if region not in {"BD","IND","PK","SG","ID","ME","VN","TW","CIS","TH","EU","US","SAC","LK","BR"}:
        region = "ME"

    handler = bot_state.refresh_callbacks.get("on_generate_bot")
    if not handler:
        return web.json_response({"ok": False, "error": "Generator not ready"}, status=500)

    try:
        result = await handler(bot_name, target_uid, region)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Generate failed: {e}"}, status=500)

    if not result or not result.get("ok"):
        err = (result or {}).get("error", "Unknown error")
        return web.json_response({"ok": False, "error": err}, status=502)

    return web.json_response({
        "ok": True,
        "uid": result.get("uid"),
        "nickname": result.get("nickname"),
        "friend_sent": result.get("friend_sent", False)
    })


async def api_start_account(request: web.Request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
    uid = str(data.get("uid", "")).strip()
    if not uid:
        return web.json_response({"ok": False, "error": "Missing uid"}, status=400)
    handler = bot_state.refresh_callbacks.get("on_start_account")
    if not handler:
        return web.json_response({"ok": False, "error": "Backend not ready"}, status=500)
    try:
        await handler(uid)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Start failed: {e}"}, status=500)
    return web.json_response({"ok": True, "uid": uid})


async def api_stop_account(request: web.Request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
    uid = str(data.get("uid", "")).strip()
    if not uid:
        return web.json_response({"ok": False, "error": "Missing uid"}, status=400)
    handler = bot_state.refresh_callbacks.get("on_stop_account")
    if not handler:
        return web.json_response({"ok": False, "error": "Backend not ready"}, status=500)
    try:
        await handler(uid)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Stop failed: {e}"}, status=500)
    return web.json_response({"ok": True, "uid": uid})


async def api_delete_account(request: web.Request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
    uid = str(data.get("uid", "")).strip()
    if not uid:
        return web.json_response({"ok": False, "error": "Missing uid"}, status=400)
    handler = bot_state.refresh_callbacks.get("on_delete_account")
    if not handler:
        return web.json_response({"ok": False, "error": "Backend not ready"}, status=500)
    try:
        await handler(uid)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Delete failed: {e}"}, status=500)
    return web.json_response({"ok": True, "uid": uid})


async def api_add_friend(request: web.Request):
    if not _authed(request):
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
    uid = str(data.get("uid", "")).strip()
    target = str(data.get("target", "")).strip()
    if not uid or not target:
        return web.json_response({"ok": False, "error": "Missing uid or target"}, status=400)
    if not target.isdigit():
        return web.json_response({"ok": False, "error": "Target must be numeric"}, status=400)
    handler = bot_state.refresh_callbacks.get("on_add_friend")
    if not handler:
        return web.json_response({"ok": False, "error": "Backend not ready"}, status=500)
    try:
        result = await handler(uid, target)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Add friend failed: {e}"}, status=500)
    if not result or not result.get("ok"):
        return web.json_response({"ok": False, "error": (result.get("error", "Failed") if result else "Failed")}, status=502)
    return web.json_response({"ok": True, "uid": uid, "target": target})


async def api_state(request: web.Request):
    if not _authed(request):
        return web.json_response({"accounts": []}, status=401)

    now = time.time()
    out = []
    for uid, acc in bot_state.accounts.items():
        running = False
        task = bot_state.account_workers.get(uid)
        if task and not task.done():
            running = True

        status = acc.get("status", "OFFLINE") or "OFFLINE"
        if status == "IN_MATCH":
            status = "RUNNING"

        out.append({
            "uid": uid,
            "nickname": acc.get("nickname", f"Player_{uid}"),
            "level": int(acc.get("level", 1)),
            "exp": int(acc.get("exp", 0)),
            "likes": int(acc.get("likes", 0)),
            "region": acc.get("region", "ME"),
            "status": status,
            "running": running,
            "banner_png": acc.get("banner_png", ""),
            "banner_mime": acc.get("banner_mime", "image/png"),
            "password": acc.get("password", ""),
            "target": acc.get("target", 0),
        })

    return web.json_response({"accounts": out, "server_time": now})


async def index(request: web.Request):
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "index.html")
    if not os.path.exists(path):
        return web.Response(text="index.html not found", status=404)
    return web.FileResponse(path)


async def start_web_dashboard(host="0.0.0.0", port=11006):
    app = web.Application()
    app.router.add_post("/api/login",           api_login)
    app.router.add_post("/api/logout",          api_logout)
    app.router.add_get ("/api/me",              api_me)
    app.router.add_post("/api/generate",        api_generate)
    app.router.add_post("/api/start-account",   api_start_account)
    app.router.add_post("/api/stop-account",    api_stop_account)
    app.router.add_post("/api/delete-account",  api_delete_account)
    app.router.add_post("/api/add-friend",      api_add_friend)
    app.router.add_get ("/api/state",           api_state)
    app.router.add_get ("/",                    index)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"[WEB] Dashboard on http://{host}:{port}")
    return runner