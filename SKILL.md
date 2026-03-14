---
name: todograph
description: >-
  Read and manage Microsoft Todo lists and tasks via Microsoft Graph API.
  Use when the user asks about their Microsoft Todo, tasks, to-do lists,
  wants to add/complete/delete tasks, or mentions Microsoft Todo / MS Todo.
---

# todograph

Interact with Microsoft Todo using the CLI script at `scripts/todograph.py`.

## Prerequisites

1. **Config file** — create `~/.cursor/skills/todograph/.env`:
   ```
   CLIENT_ID=your_azure_app_client_id
   TENANT_ID=consumers
   ```
   > For Azure AD / work accounts use `TENANT_ID=organizations`.
   > See [Azure setup guide](#azure-setup) below if CLIENT_ID is missing.

2. **First run** triggers device-code auth. The script prints a URL + code:
   - Visit the URL, enter the code, sign in.
   - Token is cached at `~/.cursor/skills/todograph/.token_cache.json` — subsequent runs are silent.

## Commands

All commands output clean JSON to **stdout**. Auth prompts go to **stderr** only.

| Command | Description |
|---------|-------------|
| `auth` | Authenticate and cache token (run once) |
| `lists` | Get all Todo lists |
| `create-list <name>` | Create a new Todo list |
| `rename-list <list_id> <new_name>` | Rename a Todo list |
| `delete-list <list_id>` | Delete a Todo list |
| `tasks <list_id>` | Get tasks in a list |
| `create <list_id> <title> [YYYY-MM-DD]` | Create a task (optional due date) |
| `complete <list_id> <task_id>` | Mark a task as completed |
| `reopen <list_id> <task_id>` | Reopen a completed task (set back to not started) |
| `update <list_id> <task_id> <new_title>` | Rename a task |
| `delete <list_id> <task_id>` | Delete a task |

```bash
python ~/.cursor/skills/todograph/scripts/todograph.py <command> [args...]
```

## Authentication Flow for Agents

Token is cached after first login — most runs need no auth at all.

**When stderr contains `auth_required: true`:**

```json
{"auth_required": true, "url": "https://microsoft.com/devicelogin", "url_complete": "https://microsoft.com/devicelogin?otc=ABCD1234", "code": "ABCD1234"}
```

1. If `url_complete` is present (normal case): tell the user "请点击以下链接完成授权（验证码已自动填入）：**[url_complete]**"
2. If `url_complete` is empty (fallback): tell the user "请访问 [url] 并输入代码 **[code]** 完成登录"
3. **Do not exit** — the script is still running and polling in the background
4. Wait for the script to finish (it exits automatically once the user logs in)
5. stdout then contains the command's JSON result as usual

To authenticate proactively before running other commands:
```bash
python ~/.cursor/skills/todograph/scripts/todograph.py auth
```
Returns `{"authenticated": true}` on success.

## Typical Workflow

When the user asks about their tasks:

1. Run `lists` to get list IDs
2. Run `tasks <list_id>` for the relevant list
3. Present results in a readable format (not raw JSON)
4. For create/complete/delete: confirm success from the returned JSON

## Azure Setup

If `CLIENT_ID` is not configured, guide the user:

1. Go to [Azure App Registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. **New registration** → any name → supported account types: "Personal Microsoft accounts"
3. Copy the **Application (client) ID**
4. **API permissions** → Add → Microsoft Graph → Delegated → `Tasks.ReadWrite`
5. **Authentication (Preview)** → Advanced settings → **Allow public client flows** → Yes → Save
6. Paste the ID into `~/.cursor/skills/todograph/.env` as `CLIENT_ID`
