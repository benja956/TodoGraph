#!/usr/bin/env python3
"""
todograph — Microsoft Todo CLI, standard library only, no third-party dependencies.

Usage:
  python todograph.py auth
  python todograph.py lists
  python todograph.py tasks <list_id>
  python todograph.py create-list <name>
  python todograph.py rename-list <list_id> <new_name>
  python todograph.py delete-list <list_id>
  python todograph.py create <list_id> <title> [due_date YYYY-MM-DD]
  python todograph.py complete <list_id> <task_id>
  python todograph.py reopen  <list_id> <task_id>
  python todograph.py delete  <list_id> <task_id>
  python todograph.py update  <list_id> <task_id> <new_title>

All output is JSON printed to stdout.
Auth token is cached in ~/.cursor/skills/todograph/.token_cache.json
Requires CLIENT_ID in ~/.cursor/skills/todograph/.env (or env var)
"""

import os
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
ENV_FILE = SKILL_DIR / ".env"
TOKEN_CACHE_FILE = SKILL_DIR / ".token_cache.json"

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPE = "Tasks.ReadWrite offline_access"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _die(msg: str):
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(1)


def _request(method: str, url: str, headers: dict = None, form: dict = None, body=None):
    """Minimal HTTP helper using urllib only."""
    data = None
    h = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        h.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif body is not None:
        data = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return json.loads(raw)
        except Exception:
            _die(f"HTTP {e.code}: {raw.decode(errors='replace')}")


# ── Auth ──────────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if TOKEN_CACHE_FILE.exists():
        try:
            return json.loads(TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_cache(data: dict):
    TOKEN_CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _token_endpoint(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


def _try_refresh(client_id: str, tenant_id: str, refresh_token: str) -> dict | None:
    result = _request("POST", _token_endpoint(tenant_id), form={
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": SCOPE,
    })
    return result if "access_token" in result else None


def _device_flow(client_id: str, tenant_id: str) -> dict:
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/devicecode"
    flow = _request("POST", url, form={"client_id": client_id, "scope": SCOPE})
    if "error" in flow:
        _die(f"Device flow error: {flow.get('error_description', flow['error'])}")

    # verification_uri_complete 是微软返回的带验证码的完整链接，用户点击即可自动填入
    # 如果微软没有返回该字段（极少数情况），则退回到手动输入方式
    url_complete = flow.get("verification_uri_complete", "")
    print(json.dumps({
        "auth_required": True,
        "url": flow["verification_uri"],
        "url_complete": url_complete,
        "code": flow["user_code"],
    }), file=sys.stderr, flush=True)

    interval = int(flow.get("interval", 5))
    deadline = time.time() + int(flow.get("expires_in", 900))

    while time.time() < deadline:
        time.sleep(interval)
        result = _request("POST", _token_endpoint(tenant_id), form={
            "client_id": client_id,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": flow["device_code"],
        })
        if "access_token" in result:
            return result
        err = result.get("error", "")
        if err == "authorization_pending":
            continue
        elif err == "slow_down":
            interval += 5
        else:
            _die(f"Auth failed: {result.get('error_description', err)}")

    _die("Authentication timed out")


def _get_token() -> str:
    _load_env()
    client_id = os.environ.get("CLIENT_ID")
    tenant_id = os.environ.get("TENANT_ID", "consumers")
    if not client_id:
        _die("CLIENT_ID not set. Add it to ~/.cursor/skills/todograph/.env")

    cache = _load_cache()

    if cache.get("refresh_token") and cache.get("client_id") == client_id:
        result = _try_refresh(client_id, tenant_id, cache["refresh_token"])
        if result:
            cache["access_token"] = result["access_token"]
            cache["refresh_token"] = result.get("refresh_token", cache["refresh_token"])
            _save_cache(cache)
            return cache["access_token"]

    result = _device_flow(client_id, tenant_id)
    cache = {
        "access_token": result["access_token"],
        "refresh_token": result.get("refresh_token", ""),
        "client_id": client_id,
        "tenant_id": tenant_id,
    }
    _save_cache(cache)
    return cache["access_token"]


# ── Graph API wrappers ────────────────────────────────────────────────────────

def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _get(token, path):
    r = _request("GET", f"{GRAPH}{path}", headers=_auth_header(token))
    if "error" in r:
        _die(r["error"].get("message", str(r["error"])))
    return r


def _post(token, path, body):
    r = _request("POST", f"{GRAPH}{path}", headers=_auth_header(token), body=body)
    if "error" in r:
        _die(r["error"].get("message", str(r["error"])))
    return r


def _patch(token, path, body):
    r = _request("PATCH", f"{GRAPH}{path}", headers=_auth_header(token), body=body)
    if "error" in r:
        _die(r["error"].get("message", str(r["error"])))
    return r


def _delete(token, path):
    _request("DELETE", f"{GRAPH}{path}", headers=_auth_header(token))
    return {"deleted": True}


# ── Commands：TaskList 增删改查 ────────────────────────────────────────────────

def cmd_lists(token):
    data = _get(token, "/me/todo/lists")
    print(json.dumps(data.get("value", []), ensure_ascii=False, indent=2))


def cmd_create_list(token, name):
    print(json.dumps(_post(token, "/me/todo/lists", {"displayName": name}), ensure_ascii=False, indent=2))


def cmd_rename_list(token, list_id, new_name):
    print(json.dumps(_patch(token, f"/me/todo/lists/{list_id}", {"displayName": new_name}), ensure_ascii=False, indent=2))


def cmd_delete_list(token, list_id):
    print(json.dumps(_delete(token, f"/me/todo/lists/{list_id}"), ensure_ascii=False, indent=2))


# ── Commands：Task 增删改查 ────────────────────────────────────────────────────


def cmd_tasks(token, list_id):
    data = _get(token, f"/me/todo/lists/{list_id}/tasks")
    print(json.dumps(data.get("value", []), ensure_ascii=False, indent=2))


def cmd_create(token, list_id, title, due_date=None):
    body = {"title": title}
    if due_date:
        body["dueDateTime"] = {"dateTime": f"{due_date}T00:00:00", "timeZone": "UTC"}
    print(json.dumps(_post(token, f"/me/todo/lists/{list_id}/tasks", body), ensure_ascii=False, indent=2))


def cmd_complete(token, list_id, task_id):
    print(json.dumps(_patch(token, f"/me/todo/lists/{list_id}/tasks/{task_id}", {"status": "completed"}), ensure_ascii=False, indent=2))


def cmd_reopen(token, list_id, task_id):
    print(json.dumps(_patch(token, f"/me/todo/lists/{list_id}/tasks/{task_id}", {"status": "notStarted"}), ensure_ascii=False, indent=2))


def cmd_update(token, list_id, task_id, new_title):
    print(json.dumps(_patch(token, f"/me/todo/lists/{list_id}/tasks/{task_id}", {"title": new_title}), ensure_ascii=False, indent=2))


def cmd_delete(token, list_id, task_id):
    print(json.dumps(_delete(token, f"/me/todo/lists/{list_id}/tasks/{task_id}"), ensure_ascii=False, indent=2))


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    token = _get_token()
    cmd = args[0]

    if cmd == "auth":
        print(json.dumps({"authenticated": True}))
    elif cmd == "create-list" and len(args) >= 2:
        cmd_create_list(token, args[1])
    elif cmd == "rename-list" and len(args) >= 3:
        cmd_rename_list(token, args[1], args[2])
    elif cmd == "delete-list" and len(args) >= 2:
        cmd_delete_list(token, args[1])
    elif cmd == "lists":
        cmd_lists(token)
    elif cmd == "tasks" and len(args) >= 2:
        cmd_tasks(token, args[1])
    elif cmd == "create" and len(args) >= 3:
        cmd_create(token, args[1], args[2], args[3] if len(args) > 3 else None)
    elif cmd == "complete" and len(args) >= 3:
        cmd_complete(token, args[1], args[2])
    elif cmd == "reopen" and len(args) >= 3:
        cmd_reopen(token, args[1], args[2])
    elif cmd == "update" and len(args) >= 4:
        cmd_update(token, args[1], args[2], args[3])
    elif cmd == "delete" and len(args) >= 3:
        cmd_delete(token, args[1], args[2])
    else:
        _die(f"Unknown command or missing arguments: {' '.join(args)}\n\n{__doc__}")


if __name__ == "__main__":
    main()
