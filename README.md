# TodoGraph

An agent skill for reading and managing Microsoft Todo via the Microsoft Graph API.

---

## Directory Structure

```
TodoGraph/
├── SKILL.md                  # Skill instructions for AI agents
├── README.md                 # This file
├── .env                      # Your credentials (CLIENT_ID, TENANT_ID)
├── .token_cache.json         # OAuth token cache (auto-generated after first login)
└── scripts/
    └── todograph.py          # CLI tool used by agents
```

---

## Setup

### 1. Register an Azure app (one-time)

1. Open [Azure App Registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. Click **New registration**
   - Name: anything (e.g. `todograph`)
   - Supported account types: **Personal Microsoft accounts**
3. Copy the **Application (client) ID**
4. Go to **API permissions** → Add → Microsoft Graph → Delegated → add `Tasks.ReadWrite`
5. Go to **Authentication (Preview)** → Advanced settings → set **Allow public client flows** to **Yes** → Save

### 2. Create `.env`

Create a `.env` file in this directory:

```
CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
TENANT_ID=consumers
```

> Use `TENANT_ID=consumers` for personal Microsoft accounts (Outlook, Hotmail).  
> Use `TENANT_ID=organizations` for work or school accounts.

### 3. First run

The first time any command runs, a device-code prompt appears on **stderr**:

```
{"auth_required": true, "url": "https://microsoft.com/devicelogin", "code": "ABCD1234"}
```

Visit the URL, enter the code, and sign in. The token is then cached locally and reused automatically.

---

## Commands

All commands output JSON to **stdout**. Auth prompts go to **stderr** only.

| Command | Description |
|---------|-------------|
| `python .../todograph.py auth` | Authenticate and cache token (run once) |
| `python .../todograph.py lists` | Get all Todo lists |
| `python .../todograph.py create-list <name>` | Create a new Todo list |
| `python .../todograph.py rename-list <list_id> <new_name>` | Rename a Todo list |
| `python .../todograph.py delete-list <list_id>` | Delete a Todo list |
| `python .../todograph.py tasks <list_id>` | Get tasks in a list |
| `python .../todograph.py create <list_id> <title> [YYYY-MM-DD]` | Create a task (optional due date) |
| `python .../todograph.py complete <list_id> <task_id>` | Mark a task as completed |
| `python .../todograph.py reopen <list_id> <task_id>` | Reopen a completed task (set back to not started) |
| `python .../todograph.py update <list_id> <task_id> <new_title>` | Rename a task |
| `python .../todograph.py delete <list_id> <task_id>` | Delete a task |

---

---

# TodoGraph（中文说明）

通过 Microsoft Graph API 读取和管理 Microsoft Todo 的 Agent Skill。

---

## 目录结构

```
TodoGraph/
├── SKILL.md                  # AI Agent 的 skill 指令文件
├── README.md                 # 本文件
├── .env                      # 你的凭据（CLIENT_ID、TENANT_ID）
├── .token_cache.json         # OAuth Token 缓存（首次登录后自动生成）
└── scripts/
    └── todograph.py          # Agent 调用的 CLI 工具
```

---

## 配置步骤

### 1. 在 Azure 注册应用（只需一次）

1. 打开 [Azure 应用注册](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. 点击**新注册**
   - 名称：随意（如 `todograph`）
   - 受支持的账户类型：**个人 Microsoft 账户**
3. 复制**应用程序（客户端）ID**
4. 进入 **API 权限** → 添加 → Microsoft Graph → 委托权限 → 搜索并添加 `Tasks.ReadWrite`
5. 进入 **Authentication (Preview)**（身份验证）→ 高级设置 → 将**允许公共客户端流**设为**是** → 保存

### 2. 创建 `.env` 文件

在本目录下创建 `.env`：

```
CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
TENANT_ID=consumers
```

> 个人账户（Outlook、Hotmail）使用 `TENANT_ID=consumers`  
> 企业/学校账户使用 `TENANT_ID=organizations`

### 3. 首次运行

第一次执行任意命令时，脚本会将设备码授权提示输出到 **stderr**：

```
{"auth_required": true, "url": "https://microsoft.com/devicelogin", "code": "ABCD1234"}
```

访问链接，输入代码并登录即可。Token 会自动缓存，后续运行无需重复操作。

---

## 命令列表

所有命令均以 JSON 格式输出到 **stdout**，授权提示仅在 **stderr** 中出现。

| 命令 | 功能 |
|------|------|
| `python .../todograph.py auth` | 授权并缓存 Token（首次运行）|
| `python .../todograph.py lists` | 获取所有 Todo 清单 |
| `python .../todograph.py create-list <name>` | 新建 Todo 清单 |
| `python .../todograph.py rename-list <list_id> <new_name>` | 重命名 Todo 清单 |
| `python .../todograph.py delete-list <list_id>` | 删除 Todo 清单 |
| `python .../todograph.py tasks <list_id>` | 获取清单中的任务 |
| `python .../todograph.py create <list_id> <title> [YYYY-MM-DD]` | 新建任务（可选截止日期）|
| `python .../todograph.py complete <list_id> <task_id>` | 标记任务为完成 |
| `python .../todograph.py reopen <list_id> <task_id>` | 重新打开任务（改回未完成）|
| `python .../todograph.py update <list_id> <task_id> <new_title>` | 修改任务标题 |
| `python .../todograph.py delete <list_id> <task_id>` | 删除任务 |
