#!/usr/bin/env python3
"""
todograph — Microsoft Todo CLI, standard library only, no third-party dependencies.

Usage:
  python todograph.py auth
  python todograph.py auth-start
  python todograph.py auth-poll [max_wait_seconds]
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
Auth token is cached in ~/todograph/.token_cache.json
Pending device flow is cached in ~/todograph/.device_flow.json
Requires CLIENT_ID in ~/todograph/.env (or env var)
"""

import os
import re
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

# __file__ 是当前脚本自身的路径。
# .parent 是它所在的目录（scripts/），再 .parent 是上一级（项目根目录）。
# 这样写的好处：无论从哪个目录执行脚本，路径都能正确解析。
# 新手常见坑：直接写 ".env" 或 "~/todograph/.env"，在不同工作目录下运行就会找不到文件。
SKILL_DIR = Path(__file__).parent.parent
ENV_FILE = SKILL_DIR / ".env"
TOKEN_CACHE_FILE = SKILL_DIR / ".token_cache.json"
DEVICE_FLOW_FILE = SKILL_DIR / ".device_flow.json"

# Graph API 的根地址。单独提取为常量的原因：
# 如果微软以后更换版本（v1.0 → v2.0），只需改这一处，不用全文搜索替换。
GRAPH = "https://graph.microsoft.com/v1.0"

# offline_access 是获取 refresh_token 的必要权限。
# 如果漏掉它，登录后只会得到短期 access_token（约1小时），之后每次都要重新扫码登录。
SCOPE = "Tasks.ReadWrite offline_access"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_env():
    """Load env vars from .env file. Priority: existing env vars > .env file."""
    # .env 文件是存放配置（如 CLIENT_ID）的标准做法，避免把敏感信息硬编码在代码里。
    # 使用 setdefault 而非直接赋值：如果系统环境变量里已经设置了同名变量，就保留它，
    # 不用 .env 文件里的值覆盖。这让用户可以临时用命令行环境变量覆盖配置，而不用修改文件。
    # 优先级：已有的系统环境变量 > .env 文件 > 代码中的默认值
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            # 跳过空行和注释行（以 # 开头），只处理 KEY=VALUE 格式的行
            if line and not line.startswith("#") and "=" in line:
                # split("=", 1) 中的 1 表示最多分割一次。
                # 这样即使 value 里有等号（如 BASE64 编码的密钥），也能正确解析。
                # 如果写 split("=")，遇到 KEY=abc=def 就会出错。
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _die(msg: str):
    # 将错误信息以 JSON 格式输出到 stderr（标准错误流），然后退出程序。
    # 为什么要输出到 stderr 而不是 stdout（标准输出）？
    # 因为这个脚本的正常结果都通过 stdout 输出 JSON，调用方（如 Agent）会解析 stdout。
    # 如果错误信息也混入 stdout，就会破坏 JSON 解析。
    # stderr 和 stdout 是两个独立的"管道"，可以分开捕获，这是 CLI 工具的标准约定。
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(1)


def _request(method: str, url: str, headers: dict = None, form: dict = None, body=None):
    """Minimal HTTP helper using urllib only."""
    # 这个函数统一封装了所有 HTTP 请求，整个脚本只有这一个地方真正发网络请求。
    # 好处：如果以后要加日志、重试、代理等逻辑，只需改这一处。
    # 工程常识：重复的底层操作应该收拢到一个地方，叫做"单一职责"。
    data = None
    # dict(headers or {})：如果调用方没传 headers，就用空字典，避免后面操作 None 报错。
    h = dict(headers or {})
    if form is not None:
        # 表单数据（用于 OAuth 认证请求），格式是 key=value&key2=value2，需要 URL 编码。
        data = urllib.parse.urlencode(form).encode()
        h.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif body is not None:
        # JSON 数据（用于 Graph API 请求），序列化为字节串。
        data = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        # timeout=30：如果服务器 30 秒没响应就放弃，防止程序永久卡住。
        # 没有 timeout 是新手常见遗漏，在网络不稳定时会导致脚本无响应且无法退出。
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            # 有些 API（如 DELETE）成功后返回空响应体，直接 json.loads("") 会报错，
            # 所以先判断 raw 是否有内容，没有就返回空字典。
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        # HTTPError 是服务器返回了 4xx/5xx 状态码。
        # 微软的 API 在出错时通常会在响应体里返回一个包含错误详情的 JSON，
        # 所以先尝试解析它，成功的话把这个错误 JSON 返回给上层，由上层决定如何处理。
        raw = e.read()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # 极少数情况：服务器返回了非 JSON 的错误页面（如 HTML 的 502 错误页）
            _die(f"HTTP {e.code}: invalid JSON response: {raw.decode(errors='replace')}")
        except UnicodeDecodeError:
            # 响应体不是合法的文本编码（极罕见）
            _die(f"HTTP {e.code}: response encoding error")


# ── Auth ──────────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    # 读取本地缓存的 token 信息。如果文件损坏或不存在，返回空字典而不是报错。
    # 返回空字典的好处：调用方可以统一用 cache.get("refresh_token") 来判断，
    # 不需要额外判断 cache 是否为 None，代码更简洁。
    if TOKEN_CACHE_FILE.exists():
        try:
            return json.loads(TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            # 文件损坏（如写到一半断电）时静默忽略，后续会触发重新登录。
            pass
    return {}


def _save_cache(data: dict):
    TOKEN_CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        # 0o600 是 Linux/macOS 的文件权限，表示"只有文件所有者可读写，其他人无权访问"。
        # token 文件里存着登录凭证，如果权限是默认的 0o644（其他用户可读），
        # 同一台机器上的其他账户就能读取你的 token，存在安全风险。
        # Windows 不支持这套权限模型，会抛出 NotImplementedError，捕获后静默跳过即可。
        TOKEN_CACHE_FILE.chmod(0o600)
    except NotImplementedError:
        pass  # Windows does not support POSIX permissions


def _load_device_flow() -> dict:
    if DEVICE_FLOW_FILE.exists():
        try:
            return json.loads(DEVICE_FLOW_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_device_flow(data: dict):
    DEVICE_FLOW_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        DEVICE_FLOW_FILE.chmod(0o600)
    except NotImplementedError:
        pass  # Windows does not support POSIX permissions


def _clear_device_flow():
    try:
        DEVICE_FLOW_FILE.unlink()
    except FileNotFoundError:
        pass


def _token_endpoint(tenant_id: str) -> str:
    # tenant_id 决定了登录的账户类型：
    # "consumers" → 个人微软账户（outlook.com、hotmail.com 等）
    # "organizations" → 公司/学校的 Azure AD 账户
    # "common" → 两种都支持（但有时会有限制）
    return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


def _try_refresh(client_id: str, tenant_id: str, refresh_token: str) -> dict | None:
    # refresh_token 是一个长期有效的凭证（通常有效期数天到数月），
    # 用它可以换取新的 access_token，而不需要用户重新扫码登录。
    # 这就是"静默刷新"——大多数情况下用户完全感知不到认证过程。
    result = _request("POST", _token_endpoint(tenant_id), form={
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": SCOPE,
    })
    # 刷新可能失败（如 refresh_token 也过期了，或用户在微软那边撤销了授权），
    # 此时返回 None，由调用方决定下一步（触发重新登录）。
    return result if "access_token" in result else None


def _start_device_flow(client_id: str, tenant_id: str) -> dict:
    # 两段式认证的第一步：只申请 device code，并把中间状态落盘后立即返回。
    # 这样 Agent 可以先把链接/验证码发给用户，而不是被阻塞在同一个进程里等待。
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/devicecode"
    flow = _request("POST", url, form={"client_id": client_id, "scope": SCOPE})
    if "error" in flow:
        _die(f"Device flow error: {flow.get('error_description', flow['error'])}")

    now = int(time.time())
    url_complete = flow.get("verification_uri_complete", "")
    pending = {
        "client_id": client_id,
        "tenant_id": tenant_id,
        "device_code": flow["device_code"],
        "user_code": flow["user_code"],
        "verification_uri": flow["verification_uri"],
        "url_complete": url_complete,
        "interval": int(flow.get("interval", 5)),
        "expires_in": int(flow.get("expires_in", 900)),
        "requested_at": now,
        "expires_at": now + int(flow.get("expires_in", 900)),
    }
    _save_device_flow(pending)

    return {
        "auth_required": True,
        "started": True,
        "pending": True,
        "next_step": "Run auth-poll after the user completes authorization. Do not run auth or auth-start again.",
        "url": flow["verification_uri"],
        "url_complete": url_complete,
        "code": flow["user_code"],
        "interval": pending["interval"],
        "expires_in": pending["expires_in"],
        "expires_at": pending["expires_at"],
    }


def _poll_device_flow(client_id: str, tenant_id: str, max_wait_seconds: int = 15) -> dict:
    # 第二步：读取之前保存的 device_code，做有限时间轮询。
    # 这样每次命令都能在短时间内结束，适合有超时限制的 exec 环境。
    pending = _load_device_flow()
    if not pending:
        return {
            "authenticated": False,
            "pending": False,
            "error": "NO_PENDING_AUTH",
        }

    if pending.get("client_id") != client_id or pending.get("tenant_id") != tenant_id:
        _clear_device_flow()
        return {
            "authenticated": False,
            "pending": False,
            "error": "PENDING_AUTH_MISMATCH",
        }

    if int(time.time()) >= int(pending.get("expires_at", 0)):
        _clear_device_flow()
        return {
            "authenticated": False,
            "expired": True,
        }

    interval = max(1, int(pending.get("interval", 5)))
    deadline = time.time() + max(1, max_wait_seconds)

    while time.time() < deadline:
        result = _request("POST", _token_endpoint(tenant_id), form={
            "client_id": client_id,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": pending["device_code"],
        })
        if "access_token" in result:
            cache = {
                "access_token": result["access_token"],
                "refresh_token": result.get("refresh_token", ""),
                "client_id": client_id,
                "tenant_id": tenant_id,
            }
            _save_cache(cache)
            _clear_device_flow()
            return {"authenticated": True}
        err = result.get("error", "")
        if err == "authorization_pending":
            if time.time() + interval > deadline:
                break
            time.sleep(interval)
        elif err == "slow_down":
            interval += 5
            pending["interval"] = interval
            _save_device_flow(pending)
            if time.time() + interval > deadline:
                break
            time.sleep(interval)
        elif err == "expired_token":
            _clear_device_flow()
            return {
                "authenticated": False,
                "expired": True,
            }
        elif err in {"authorization_declined", "bad_verification_code"}:
            _clear_device_flow()
            return {
                "authenticated": False,
                "failed": True,
                "error": err,
                "message": result.get("error_description", err),
            }
        else:
            return {
                "authenticated": False,
                "failed": True,
                "error": err or "AUTH_POLL_FAILED",
                "message": result.get("error_description", err or "Authentication failed"),
            }

    return {
        "authenticated": False,
        "pending": True,
        "interval": interval,
        "expires_at": pending.get("expires_at"),
    }


def _get_auth_config() -> tuple[str, str]:
    # 这是认证的总入口，对外只暴露这一个函数。
    _load_env()
    client_id = os.environ.get("CLIENT_ID")
    tenant_id = os.environ.get("TENANT_ID", "consumers")
    if not client_id:
        _die("CLIENT_ID not set. Add it to ~/todograph/.env")
    return client_id, tenant_id


def _get_token() -> str | None:
    # 现在 _get_token 只负责“静默拿 token”：读取缓存并尝试 refresh。
    # 如果做不到静默认证，就返回 None，让上层命令显式走 auth-start / auth-poll。
    client_id, tenant_id = _get_auth_config()

    cache = _load_cache()

    # 检查缓存里是否有同一个 app（client_id 一致）的 refresh_token。
    # 比对 client_id 是为了防止：用户换了一个新的 Azure App 后，
    # 用旧 app 的 refresh_token 去刷新，必然失败且报错难以理解。
    if cache.get("refresh_token") and cache.get("client_id") == client_id:
        result = _try_refresh(client_id, tenant_id, cache["refresh_token"])
        if result:
            cache["access_token"] = result["access_token"]
            # 微软有时会在刷新响应里返回新的 refresh_token（滚动刷新机制），
            # 如果没有返回新的，就保留旧的继续用。
            cache["refresh_token"] = result.get("refresh_token", cache["refresh_token"])
            _save_cache(cache)
            return cache["access_token"]

    return None


# ── Graph API wrappers ────────────────────────────────────────────────────────

def _auth_header(token: str) -> dict:
    # Bearer Token 是调用 REST API 时最常见的认证方式。
    # "Bearer" 是固定前缀，意思是"持有这个 token 的人有权访问"。
    # 格式必须严格为 "Bearer <空格> token值"，多一个空格或少一个都会报 401 未授权。
    return {"Authorization": f"Bearer {token}"}


def _get(token, path):
    r = _request("GET", f"{GRAPH}{path}", headers=_auth_header(token))
    # Graph API 的一个特点：即使请求"成功"（HTTP 200），响应体里也可能含有 "error" 字段。
    # 所以不能只靠 HTTP 状态码判断成功与否，还必须检查响应内容。
    if "error" in r:
        _die(r["error"].get("message", str(r["error"])))
    return r


def _post(token, path, body):
    r = _request("POST", f"{GRAPH}{path}", headers=_auth_header(token), body=body)
    if "error" in r:
        _die(r["error"].get("message", str(r["error"])))
    return r


def _patch(token, path, body):
    # PATCH 是"局部更新"——只修改你传入的字段，其他字段保持不变。
    # 与 PUT（完整替换整个资源）不同。Graph API 的任务/列表更新都用 PATCH。
    r = _request("PATCH", f"{GRAPH}{path}", headers=_auth_header(token), body=body)
    if "error" in r:
        _die(r["error"].get("message", str(r["error"])))
    return r


def _delete(token, path):
    # DELETE 请求成功时，Graph API 返回 HTTP 204（No Content），响应体为空。
    # _request() 遇到空响应体会返回 {}，所以这里手动构造一个有意义的返回值，
    # 让调用方能确认"删除已执行"，而不是收到一个莫名其妙的空字典。
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


def _validate_date(date_str: str) -> str:
    # 用正则表达式验证格式，而不是直接把字符串拼进请求。
    # 如果不验证，用户传入 "2024/1/5" 或 "明天" 之类的字符串，
    # 微软 API 会返回一个晦涩的 400 错误，很难看出是日期格式问题。
    # 提前校验能给出更明确的提示，减少排查时间。
    # ^ 和 $ 分别匹配字符串的开头和结尾，确保整个字符串都符合格式，不允许多余内容。
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        _die(f"Invalid date format: '{date_str}'. Use YYYY-MM-DD")
    return date_str


def cmd_create(token, list_id, title, due_date=None):
    body = {"title": title}
    if due_date:
        # Graph API 要求截止日期必须包含时间和时区信息，即使我们只关心日期。
        # T00:00:00 表示当天零点，timeZone 设为 UTC 是最通用的写法，
        # 避免因时区换算导致日期显示偏差一天。
        body["dueDateTime"] = {"dateTime": f"{_validate_date(due_date)}T00:00:00", "timeZone": "UTC"}
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
    # sys.argv 是一个列表，argv[0] 是脚本文件名本身，argv[1:] 才是用户传入的参数。
    # 例如执行 python todograph.py tasks ABC123 时，sys.argv = ["todograph.py", "tasks", "ABC123"]
    args = sys.argv[1:]
    if not args:
        # 没有传任何参数时，打印使用说明（即文件顶部的 docstring）并正常退出。
        print(__doc__)
        sys.exit(0)

    cmd = args[0]

    if cmd in {"auth", "auth-start"}:
        client_id, tenant_id = _get_auth_config()
        print(json.dumps(_start_device_flow(client_id, tenant_id), ensure_ascii=False, indent=2))
        return

    if cmd == "auth-poll":
        client_id, tenant_id = _get_auth_config()
        max_wait_seconds = int(args[1]) if len(args) >= 2 else 15
        print(json.dumps(_poll_device_flow(client_id, tenant_id, max_wait_seconds), ensure_ascii=False, indent=2))
        return

    # 业务命令只允许使用“已存在或可静默刷新”的 token。
    # 如果当前必须重新授权，就直接返回可机器识别的 JSON，让 Agent 进入两段式授权流程。
    token = _get_token()
    if not token:
        print(json.dumps({
            "error": "AUTH_REQUIRED",
            "auth_required": True,
            "next_step": "Run auth-start, then auth-poll after the user completes authorization.",
        }, ensure_ascii=False, indent=2))
        return

    # 命令分发：根据命令名和参数数量，调用对应的 cmd_ 函数。
    # 同时检查参数数量（如 len(args) >= 2），避免因参数不足导致后续 args[1] 报 IndexError。
    # 工程上这种模式叫"命令路由"，大型项目通常用 argparse 库或 click 框架来做，
    # 但本脚本刻意只用标准库，所以手写 if/elif 链。
    if cmd == "create-list" and len(args) >= 2:
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
        # due_date 是可选参数，有则传入，没有则传 None
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
        # 命令不存在或参数不足时，给出错误提示并附上完整使用说明，方便排查。
        _die(f"Unknown command or missing arguments: {' '.join(args)}\n\n{__doc__}")


if __name__ == "__main__":
    main()
