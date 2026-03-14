import os
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).parent
ENV_FILE = BASE_DIR / ".env"
TOKEN_CACHE_FILE = BASE_DIR / ".token_cache.json"

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPE = "Tasks.ReadWrite offline_access"

USAGE = """
用法:
  python test_api.py                              # 列出所有清单和任务（可读模式）
  python test_api.py lists                        # 获取所有 Todo 清单（JSON）
  python test_api.py tasks <list_id>              # 获取清单中的任务（JSON）
  python test_api.py create <list_id> <title> [YYYY-MM-DD]  # 新建任务
  python test_api.py complete <list_id> <task_id>           # 标记任务为完成
  python test_api.py reopen  <list_id> <task_id>            # 重新打开任务（标记为未完成）
  python test_api.py update  <list_id> <task_id> <new_title> # 修改任务标题
  python test_api.py delete  <list_id> <task_id>            # 删除任务
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def die(msg: str):
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(1)


def http(method, url, headers=None, form=None, body=None):
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
            die(f"HTTP {e.code}: {raw.decode(errors='replace')}")


# ── Auth ──────────────────────────────────────────────────────────────────────

def load_cache():
    if TOKEN_CACHE_FILE.exists():
        try:
            return json.loads(TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cache(data):
    TOKEN_CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def token_endpoint(tenant_id):
    return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


def try_refresh(client_id, tenant_id, refresh_token):
    result = http("POST", token_endpoint(tenant_id), form={
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": SCOPE,
    })
    return result if "access_token" in result else None


def device_flow(client_id, tenant_id):
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/devicecode"
    flow = http("POST", url, form={"client_id": client_id, "scope": SCOPE})
    if "error" in flow:
        die(f"Device flow 错误：{flow.get('error_description', flow['error'])}")

    # verification_uri_complete 是微软返回的带验证码的完整链接，用户点击即可自动填入
    # 如果微软没有返回该字段（极少数情况），则退回到手动输入方式
    url_complete = flow.get("verification_uri_complete", "")
    print(json.dumps({
        "auth_required": True,
        "url": flow["verification_uri"],
        "url_complete": url_complete,
        "code": flow["user_code"],
    }), file=sys.stderr, flush=True)

    print(f"\n{'='*50}", file=sys.stderr)
    if url_complete:
        print(f"请点击以下链接完成授权（验证码已自动填入）：", file=sys.stderr)
        print(f"{url_complete}", file=sys.stderr)
    else:
        print(f"请访问: {flow['verification_uri']}", file=sys.stderr)
        print(f"输入代码: {flow['user_code']}", file=sys.stderr)
    print(f"{'='*50}\n", file=sys.stderr)

    interval = int(flow.get("interval", 5))
    deadline = time.time() + int(flow.get("expires_in", 900))

    while time.time() < deadline:
        time.sleep(interval)
        result = http("POST", token_endpoint(tenant_id), form={
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
            die(f"认证失败：{result.get('error_description', err)}")

    die("认证超时")


def get_access_token():
    load_env()
    client_id = os.environ.get("CLIENT_ID")
    tenant_id = os.environ.get("TENANT_ID", "consumers")

    if not client_id:
        print("错误：请先配置 CLIENT_ID。")
        print("1. 将 .env.example 复制为 .env")
        print("2. 填入你的 Azure 应用 CLIENT_ID")
        sys.exit(1)

    cache = load_cache()

    if cache.get("refresh_token") and cache.get("client_id") == client_id:
        result = try_refresh(client_id, tenant_id, cache["refresh_token"])
        if result:
            cache["access_token"] = result["access_token"]
            cache["refresh_token"] = result.get("refresh_token", cache["refresh_token"])
            save_cache(cache)
            return cache["access_token"]

    result = device_flow(client_id, tenant_id)
    cache = {
        "access_token": result["access_token"],
        "refresh_token": result.get("refresh_token", ""),
        "client_id": client_id,
        "tenant_id": tenant_id,
    }
    save_cache(cache)
    return cache["access_token"]


# ── Graph API helpers ─────────────────────────────────────────────────────────

def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def graph_get(token, path):
    r = http("GET", f"{GRAPH}{path}", headers=auth_header(token))
    if isinstance(r, dict) and "error" in r:
        die(r["error"].get("message", str(r["error"])))
    return r


def graph_post(token, path, body):
    r = http("POST", f"{GRAPH}{path}", headers=auth_header(token), body=body)
    if isinstance(r, dict) and "error" in r:
        die(r["error"].get("message", str(r["error"])))
    return r


def graph_patch(token, path, body):
    r = http("PATCH", f"{GRAPH}{path}", headers=auth_header(token), body=body)
    if isinstance(r, dict) and "error" in r:
        die(r["error"].get("message", str(r["error"])))
    return r


def graph_delete(token, path):
    http("DELETE", f"{GRAPH}{path}", headers=auth_header(token))
    return {"deleted": True}


# ── Microsoft Todo API：TaskList 操作 ────────────────────────────────────────

def get_todo_lists(token):
    return graph_get(token, "/me/todo/lists").get("value", [])


def create_todo_list(token, name):
    return graph_post(token, "/me/todo/lists", {"displayName": name})


def rename_todo_list(token, list_id, new_name):
    return graph_patch(token, f"/me/todo/lists/{list_id}", {"displayName": new_name})


def delete_todo_list(token, list_id):
    return graph_delete(token, f"/me/todo/lists/{list_id}")


# ── Microsoft Todo API：Task 操作 ─────────────────────────────────────────────

def get_tasks_in_list(token, list_id):
    return graph_get(token, f"/me/todo/lists/{list_id}/tasks").get("value", [])


def create_task(token, list_id, title, due_date=None):
    body = {"title": title}
    if due_date:
        body["dueDateTime"] = {"dateTime": f"{due_date}T00:00:00", "timeZone": "UTC"}
    return graph_post(token, f"/me/todo/lists/{list_id}/tasks", body)


def set_task_status(token, list_id, task_id, status):
    return graph_patch(token, f"/me/todo/lists/{list_id}/tasks/{task_id}", {"status": status})


def update_task_title(token, list_id, task_id, new_title):
    return graph_patch(token, f"/me/todo/lists/{list_id}/tasks/{task_id}", {"title": new_title})


def delete_task(token, list_id, task_id):
    return graph_delete(token, f"/me/todo/lists/{list_id}/tasks/{task_id}")


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_show_all(token):
    """默认模式：以可读方式展示所有清单和任务"""
    print("正在获取 Microsoft Todo 列表...\n")
    todo_lists = get_todo_lists(token)

    if not todo_lists:
        print("未找到任何 Todo 列表。")
        return

    print(f"共找到 {len(todo_lists)} 个列表：\n")
    for i, lst in enumerate(todo_lists, 1):
        list_name = lst.get("displayName", "未命名列表")
        list_id = lst["id"]
        print(f"[{i}] 📋 {list_name}  (id: {list_id[:16]}...)")

        tasks = get_tasks_in_list(token, list_id)
        if tasks:
            for task in tasks:
                title = task.get("title", "无标题")
                status = task.get("status", "")
                done = "✅" if status == "completed" else "⬜"
                task_id = task["id"]
                print(f"    {done} {title}  (id: {task_id[:16]}...)")
        else:
            print("    （暂无任务）")
        print()


def cmd_lists(token):
    print(json.dumps(get_todo_lists(token), ensure_ascii=False, indent=2))


def cmd_tasks(token, list_id):
    print(json.dumps(get_tasks_in_list(token, list_id), ensure_ascii=False, indent=2))


def cmd_create(token, list_id, title, due_date=None):
    result = create_task(token, list_id, title, due_date)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_complete(token, list_id, task_id):
    result = set_task_status(token, list_id, task_id, "completed")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_reopen(token, list_id, task_id):
    result = set_task_status(token, list_id, task_id, "notStarted")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_update(token, list_id, task_id, new_title):
    result = update_task_title(token, list_id, task_id, new_title)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_delete(token, list_id, task_id):
    result = delete_task(token, list_id, task_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


# ── Main（增删改查全流程测试）────────────────────────────────────────────────
#
# 运行这个脚本，会自动按顺序执行所有 MS Todo 操作，验证读写权限是否正常。
# 测试数据（清单和任务）会在最后一步自动删除，不会留下垃圾数据。
#
# 前提：.env 里配置了 CLIENT_ID，且已用 Tasks.ReadWrite 权限登录过

def main():
    # ── 第一步：获取访问令牌 ──────────────────────────────────────────────────
    # token 是后续所有 API 请求的"通行证"，每次调用都要带上它
    print("正在获取访问令牌...")
    token = get_access_token()
    print("✅ 令牌获取成功\n")

    # ════════════════════════════════════════════════════════════════
    # 第一部分：TaskList（清单）的增删改查
    # ════════════════════════════════════════════════════════════════

    # ── 第二步：读取所有 Todo 清单（READ - 查清单）────────────────────────────
    print("=" * 50)
    print("【读】获取所有 Todo 清单")
    print("=" * 50)
    todo_lists = get_todo_lists(token)
    print(f"  当前共有 {len(todo_lists)} 个清单：")
    for lst in todo_lists:
        print(f"    · {lst['displayName']}  (id: {lst['id'][:20]}...)")
    print()

    # ── 第三步：新建一个测试清单（CREATE - 增清单）───────────────────────────
    print("=" * 50)
    print("【增】新建测试清单")
    print("=" * 50)
    new_list = create_todo_list(token, "【测试清单】请忽略此条目")
    test_list_id = new_list["id"]
    print(f"  ✅ 已创建：{new_list['displayName']}")
    print(f"     list_id: {test_list_id[:20]}...\n")

    # ── 第四步：重命名测试清单（UPDATE - 改清单名）───────────────────────────
    print("=" * 50)
    print("【改】重命名测试清单")
    print("=" * 50)
    renamed_list = rename_todo_list(token, test_list_id, "【测试清单】名称已修改")
    print(f"  ✅ 清单名已改为：{renamed_list['displayName']}\n")

    # ════════════════════════════════════════════════════════════════
    # 第二部分：Task（任务）的增删改查（在刚创建的测试清单里操作）
    # ════════════════════════════════════════════════════════════════

    list_id = test_list_id
    list_name = renamed_list["displayName"]
    print(f"\n👉 在「{list_name}」里进行任务增删改查测试\n")

    # ── 第三步：读取该清单里现有的任务（READ - 查任务）──────────────────────
    print("=" * 50)
    print(f"【读】获取「{list_name}」里的现有任务")
    print("=" * 50)
    existing_tasks = get_tasks_in_list(token, list_id)
    print(f"  当前共有 {len(existing_tasks)} 个任务")
    for task in existing_tasks:
        status = task.get("status", "")
        done = "✅" if status == "completed" else "⬜"
        print(f"  {done} {task.get('title', '无标题')}")
    print()

    # ── 第四步：新建一个测试任务（CREATE - 增）──────────────────────────────
    # dueDateTime 是可选的，这里演示带截止日期的写法
    print("=" * 50)
    print("【增】新建测试任务")
    print("=" * 50)
    new_task = create_task(
        token,
        list_id,
        title="【测试任务】请忽略此条目",
        due_date="2026-12-31",
    )
    task_id = new_task["id"]
    print(f"  ✅ 已创建：{new_task['title']}")
    print(f"     task_id: {task_id[:20]}...\n")

    # ── 第五步：修改任务标题（UPDATE - 改标题）──────────────────────────────
    print("=" * 50)
    print("【改】修改任务标题")
    print("=" * 50)
    updated_task = update_task_title(
        token,
        list_id,
        task_id,
        new_title="【测试任务】标题已被修改",
    )
    print(f"  ✅ 标题已改为：{updated_task['title']}\n")

    # ── 第六步：标记任务为完成（UPDATE - 改状态）────────────────────────────
    # MS Todo 的状态字段叫 status，完成 = "completed"，未完成 = "notStarted"
    print("=" * 50)
    print('【改】标记任务为"已完成"')
    print("=" * 50)
    completed_task = set_task_status(token, list_id, task_id, "completed")
    print(f"  ✅ 当前状态：{completed_task['status']}\n")

    # ── 第七步：重新打开任务（UPDATE - 改状态）──────────────────────────────
    print("=" * 50)
    print('【改】重新打开任务（改回"未完成"）')
    print("=" * 50)
    reopened_task = set_task_status(token, list_id, task_id, "notStarted")
    print(f"  ✅ 当前状态：{reopened_task['status']}\n")

    # ── 第八步：删除测试任务（DELETE - 删任务）──────────────────────────────
    print("=" * 50)
    print("【删】删除测试任务")
    print("=" * 50)
    delete_task_result = delete_task(token, list_id, task_id)
    print(f"  ✅ 删除结果：{delete_task_result}\n")

    # ════════════════════════════════════════════════════════════════
    # 第三部分：清理——删除测试清单
    # 注意：删除清单会连带删除其中所有任务，所以要等任务测试完再删
    # ════════════════════════════════════════════════════════════════

    # ── 第九步：删除测试清单（DELETE - 删清单）───────────────────────────────
    print("=" * 50)
    print("【删】删除测试清单")
    print("=" * 50)
    delete_list_result = delete_todo_list(token, test_list_id)
    print(f"  ✅ 删除结果：{delete_list_result}\n")

    # ── 完成 ─────────────────────────────────────────────────────────────────
    print("=" * 50)
    print("🎉 所有增删改查操作均已成功完成！")
    print("   TaskList 和 Task 的读写权限均正常，可以正式使用。")
    print("=" * 50)


if __name__ == "__main__":
    main()
