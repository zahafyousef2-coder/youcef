import os
import sys
import asyncio
import time
import json
import traceback
from pathlib import Path
from typing import Dict, Any, Optional

ROOT = Path(__file__).parent.resolve()

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "WeBSiTe"))
sys.path.insert(0, str(ROOT / "Source Code GeNeRaToR"))
sys.path.insert(0, str(ROOT / "ReqAddBoT"))
sys.path.insert(0, str(ROOT / "InFoBoT"))
sys.path.insert(0, str(ROOT / "BoT LvL UDPxTCP"))

os.environ.setdefault("PYTHONUNBUFFERED", "1")
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import dashboard as web_dashboard
from dashboard import bot_state, start_web_dashboard

try:
    import gen as generator
except Exception as e:
    generator = None
    print(f"[RunBoT] gen.py import failed: {e}")

try:
    import InFoBoT as info_module
except Exception as e:
    info_module = None
    print(f"[RunBoT] InFoBoT.py import failed: {e}")

try:
    import ReqAddBoT as friend_module
except Exception as e:
    friend_module = None
    print(f"[RunBoT] ReqAddBoT.py import failed: {e}")

try:
    import br as bot_engine
except Exception as e:
    bot_engine = None
    print(f"[RunBoT] br.py import failed: {e}")

ACCOUNTS_FILE = ROOT / "Source Code GeNeRaToR" / "accounts.json"
BOTS_FILE = ROOT / "bots.json"

BOT_REGISTRY: Dict[str, Dict[str, Any]] = {}
REGISTRY_LOCK = asyncio.Lock()


def log(msg):
    print(f"[RunBoT] {msg}", flush=True)

def flow_debug(stage, detail=""):
    suffix = f" | {detail}" if detail else ""
    log(f"[FLOW DEBUG] {stage}{suffix}")


def _load_bots() -> Dict[str, Dict]:
    if not BOTS_FILE.exists():
        return {}
    try:
        with open(BOTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_bots():
    try:
        with open(BOTS_FILE, "w", encoding="utf-8") as f:
            json.dump(BOT_REGISTRY, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log(f"save bots error: {e}")


async def _generate_account(bot_name: str, region: str = "ME") -> Optional[Dict]:
    if generator is None:
        log("generator not available")
        return None
    loop = asyncio.get_running_loop()
    try:
        flow_debug("GENERATE_START", f"name={bot_name!r} region={region}")
        acc = await loop.run_in_executor(
            None,
            lambda: generator.generate_account(name=bot_name, region=region, target=1, threads=2)
        )
        if acc:
            flow_debug("GENERATE_SUCCESS", f"uid={acc.get('uid')} account_id={acc.get('account_id')}")
        else:
            flow_debug("GENERATE_FAILED", "generator returned None")
        return acc
    except Exception as e:
        flow_debug("GENERATE_EXCEPTION", f"{type(e).__name__}: {e}")
        return None


async def _fetch_info(uid: str, password: str) -> Optional[Dict]:
    if info_module is None:
        log("InFoBoT not available")
        return None
    loop = asyncio.get_running_loop()
    try:
        flow_debug("INFO_START", f"uid={uid}")
        result = await loop.run_in_executor(
            None,
            lambda: info_module.show_bot_sync(uid, password)
        )
        if result and result.get("ok"):
            flow_debug("INFO_SUCCESS", f"uid={result.get('uid', uid)} region={result.get('region', '')}")
        else:
            flow_debug("INFO_FAILED", f"result={result}")
        return result
    except Exception as e:
        flow_debug("INFO_EXCEPTION", f"{type(e).__name__}: {e}")
        return None


async def _send_friend_request(uid: str, password: str, target_uid: str) -> Dict:
    if friend_module is None:
        return {"ok": False, "error": "ReqAddBoT not available"}
    try:
        flow_debug("FRIEND_START", f"account={uid} target={target_uid}")
        result = await friend_module.send_friend_request_async(uid, password, target_uid)
        result = result or {"ok": False, "error": "no result"}
        if result.get("ok"):
            flow_debug("FRIEND_SUCCESS", f"target={target_uid}")
        else:
            flow_debug("FRIEND_FAILED", f"target={target_uid} error={result.get('error', '')}")
        return result
    except Exception as e:
        flow_debug("FRIEND_EXCEPTION", f"{type(e).__name__}: {e}")
        return {"ok": False, "error": str(e)}


async def _start_bot_worker(uid: str):
    if bot_engine is None:
        log("br.py not available")
        return
    entry = BOT_REGISTRY.get(uid)
    if not entry:
        log(f"no registry entry for {uid}")
        return

    uid_str = str(entry.get("auth_uid") or entry.get("uid"))
    password = entry.get("password")

    log(f"starting worker for {uid_str}")

    bot_state.update_status(uid, "CONNECTING")
    _sync_to_state(uid)

    try:
        account_data = await bot_engine.process_account_uid_pass(uid_str, password)
        if not account_data:
            log(f"login failed for {uid_str}")
            bot_state.update_status(uid, "ERROR")
            _sync_to_state(uid)
            return

        real_uid = str(account_data["account_id"])

        bot_state.register_account(
            uid=real_uid,
            nickname=account_data.get("nickname", entry.get("bot_name", "BOT")),
            region=account_data.get("region", entry.get("region", "ME")),
            level=account_data.get("level", 2),
            exp=account_data.get("exp", 0),
            likes=0
        )

        acc = bot_state.accounts[real_uid]
        acc["banner_png"] = entry.get("banner_png", "")
        acc["banner_mime"] = entry.get("banner_mime", "image/png")
        acc["target"] = entry.get("target", 0)
        acc["password"] = password

        bot_state.account_credentials[real_uid] = account_data

        if real_uid != uid:
            BOT_REGISTRY[real_uid] = BOT_REGISTRY.pop(uid, entry)
            BOT_REGISTRY[real_uid]["uid"] = real_uid
            _save_bots()

        async def update_callback():
            try:
                await bot_engine.refresh_account_profile(account_data)
                bot_state.update_exp(
                    real_uid,
                    account_data.get("exp", 0),
                    account_data.get("level", 1)
                )
                _sync_to_state(real_uid)
            except Exception:
                pass

        bot_state.refresh_callbacks[f"refresh_{real_uid}"] = update_callback

        bot_state.update_status(real_uid, "RUNNING")
        _sync_to_state(real_uid)

        await bot_engine.run_account_worker(account_data, real_uid)

    except asyncio.CancelledError:
        log(f"worker cancelled for {uid}")
        bot_state.update_status(uid, "STOPPED")
        _sync_to_state(uid)
        raise
    except Exception as e:
        log(f"worker error for {uid}: {e}")
        traceback.print_exc()
        bot_state.update_status(uid, "ERROR")
        _sync_to_state(uid)


def _sync_to_state(uid: str):
    uid = str(uid)
    entry = BOT_REGISTRY.get(uid)
    if not entry:
        return
    if uid in bot_state.accounts:
        acc = bot_state.accounts[uid]
        entry["nickname"] = acc.get("nickname", entry.get("bot_name", "BOT"))
        entry["level"] = acc.get("level", 1)
        entry["exp"] = acc.get("exp", 0)
        entry["likes"] = acc.get("likes", 0)
        entry["region"] = acc.get("region", "ME")
        entry["status"] = acc.get("status", "OFFLINE")
        entry["banner_png"] = acc.get("banner_png", "")
        entry["banner_mime"] = acc.get("banner_mime", "image/png")
    _save_bots()


def _banner_from_info(info: Optional[Dict]) -> Dict:
    if not info or not info.get("ok"):
        return {"banner_png": "", "banner_mime": "image/png"}
    return {
        "banner_png": info.get("card_png", "") or "",
        "banner_mime": info.get("card_mime", "image/png") or "image/png"
    }


async def flow_generate_bot(bot_name: str, target_uid: str, region: str = "ME") -> Dict:
    log(f"flow start: name={bot_name} target={target_uid} region={region}")
    flow_debug("FLOW_START", f"name={bot_name!r} target={target_uid} region={region}")

    if not bot_name or not target_uid:
        return {"ok": False, "error": "missing parameters"}

    async with REGISTRY_LOCK:
        generated = await _generate_account(bot_name, region)
        if not generated:
            flow_debug("FLOW_STOP", "account generation failed")
            log("generation failed")
            return {"ok": False, "error": "generation failed"}

        uid = str(generated["uid"])
        password = generated["password"]
        flow_debug("ACCOUNT_CREATED", f"auth_uid={uid} account_id={generated.get('account_id')}")
        log(f"generated account uid={uid}")

        info = await _fetch_info(uid, password)
        banner = _banner_from_info(info)

        nickname = bot_name
        level = 1
        exp = 0
        real_region = region
        real_account_id = str(generated.get("account_id") or uid)

        if info and info.get("ok"):
            nickname = info.get("name") or bot_name
            level = int(info.get("level", 1) or 1)
            real_region = info.get("region") or region
            real_account_id = str(info.get("uid") or real_account_id)
        else:
            flow_debug("INFO_OPTIONAL_FAILED", "account was created but profile info was unavailable; continuing")

        friend_result = await _send_friend_request(uid, password, target_uid)
        friend_ok = bool(friend_result.get("ok"))
        flow_debug("FLOW_FRIEND_RESULT", f"friend_ok={friend_ok}")

        entry = {
            "uid": real_account_id,
            "auth_uid": uid,
            "password": password,
            "bot_name": bot_name,
            "nickname": nickname,
            "region": real_region,
            "level": level,
            "exp": exp,
            "likes": 0,
            "target": target_uid,
            "status": "CONNECTING",
            "friend_sent": friend_ok,
            "friend_error": friend_result.get("error", ""),
            "created_at": time.time()
        }

        BOT_REGISTRY[real_account_id] = entry
        _save_bots()

        bot_state.register_account(
            uid=real_account_id,
            nickname=nickname,
            region=real_region,
            level=level,
            exp=exp,
            likes=0
        )

        acc = bot_state.accounts[real_account_id]
        acc["banner_png"] = banner["banner_png"]
        acc["banner_mime"] = banner["banner_mime"]
        acc["target"] = target_uid
        acc["password"] = password
        acc["status"] = "CONNECTING"

        bot_state.exp_targets_ref[real_account_id] = 0

        task = asyncio.create_task(_start_bot_worker(real_account_id))
        bot_state.account_workers[real_account_id] = task

        log(f"bot {real_account_id} started, friend_ok={friend_ok}")

        flow_debug("FLOW_SUCCESS", f"account={real_account_id} friend_sent={friend_ok}")
        return {
            "ok": True,
            "uid": real_account_id,
            "password": password,
            "nickname": nickname,
            "friend_sent": friend_ok
        }


async def on_account_login_only(payload: Dict):
    pass


async def on_start_account(uid: str):
    uid = str(uid)
    entry = BOT_REGISTRY.get(uid)
    if not entry:
        raise RuntimeError(f"bot {uid} not found")

    task = bot_state.account_workers.get(uid)
    if task and not task.done():
        return

    task = asyncio.create_task(_start_bot_worker(uid))
    bot_state.account_workers[uid] = task


async def on_stop_account(uid: str):
    uid = str(uid)
    task = bot_state.account_workers.get(uid)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    bot_state.account_workers.pop(uid, None)
    bot_state.update_status(uid, "STOPPED")
    _sync_to_state(uid)


async def on_halt_account(uid: str):
    await on_stop_account(uid)
    uid = str(uid)
    if uid in bot_state.accounts:
        bot_state.accounts[uid]["status"] = "STOPPED"


async def on_delete_account(uid: str):
    uid = str(uid)
    await on_stop_account(uid)
    bot_state.accounts.pop(uid, None)
    bot_state.account_credentials.pop(uid, None)
    bot_state.account_workers.pop(uid, None)
    BOT_REGISTRY.pop(uid, None)
    _save_bots()


async def on_add_friend(uid: str, target_uid: str):
    uid = str(uid)
    entry = BOT_REGISTRY.get(uid)
    if not entry:
        return {"ok": False, "error": "bot not found"}
    auth_uid = entry.get("auth_uid") or entry.get("uid")
    password = entry.get("password")
    if not password:
        return {"ok": False, "error": "no credentials"}
    result = await _send_friend_request(auth_uid, password, target_uid)
    return result


async def on_set_target(uid: str, target: int):
    uid = str(uid)
    if uid in bot_state.accounts:
        bot_state.accounts[uid]["target"] = int(target)
    if uid in BOT_REGISTRY:
        BOT_REGISTRY[uid]["target"] = int(target)
        _save_bots()


def register_callbacks():
    bot_state.refresh_callbacks["on_account_login_only"] = on_account_login_only
    bot_state.refresh_callbacks["on_start_account"] = on_start_account
    bot_state.refresh_callbacks["on_stop_account"] = on_stop_account
    bot_state.refresh_callbacks["on_halt_account"] = on_halt_account
    bot_state.refresh_callbacks["on_delete_account"] = on_delete_account
    bot_state.refresh_callbacks["on_add_friend"] = on_add_friend
    bot_state.refresh_callbacks["on_set_target"] = on_set_target
    bot_state.refresh_callbacks["on_generate_bot"] = flow_generate_bot


async def restore_bots():
    global BOT_REGISTRY
    BOT_REGISTRY = _load_bots()
    if not BOT_REGISTRY:
        return

    log(f"restoring {len(BOT_REGISTRY)} bots from disk")

    for uid, entry in list(BOT_REGISTRY.items()):
        try:
            bot_state.register_account(
                uid=uid,
                nickname=entry.get("nickname", entry.get("bot_name", "BOT")),
                region=entry.get("region", "ME"),
                level=entry.get("level", 1),
                exp=entry.get("exp", 0),
                likes=entry.get("likes", 0)
            )
            acc = bot_state.accounts[uid]
            acc["banner_png"] = entry.get("banner_png", "")
            acc["banner_mime"] = entry.get("banner_mime", "image/png")
            acc["target"] = entry.get("target", 0)
            acc["password"] = entry.get("password", "")
            acc["status"] = "STOPPED"

            task = asyncio.create_task(_start_bot_worker(uid))
            bot_state.account_workers[uid] = task
        except Exception as e:
            log(f"restore error for {uid}: {e}")


async def periodic_sync():
    while True:
        await asyncio.sleep(15)
        try:
            for uid in list(BOT_REGISTRY.keys()):
                _sync_to_state(uid)
        except Exception:
            pass


async def main():
    log("starting RunBoT...")
    register_callbacks()
    bot_state.bind_loop()

    runner = await start_web_dashboard(host="0.0.0.0", port=11006)

    await restore_bots()

    sync_task = asyncio.create_task(periodic_sync())

    log("system ready")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        sync_task.cancel()
        try:
            await sync_task
        except (asyncio.CancelledError, Exception):
            pass
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[RunBoT] stopped.")