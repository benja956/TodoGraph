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

1. **Config file** — create `~/todograph/.env`:
   ```
   CLIENT_ID=your_azure_app_client_id
   TENANT_ID=consumers
   ```
   > For Azure AD / work accounts use `TENANT_ID=organizations`.
   > See [Azure setup guide](#azure-setup) below if CLIENT_ID is missing.

2. **First run** triggers device-code auth:
   - Start auth with `auth` or `auth-start` to get the URL + code immediately.
   - After the user finishes authorization, run `auth-poll` to finish token exchange.
   - Token is cached at `~/todograph/.token_cache.json` — subsequent runs are silent.
   - Pending auth state is cached at `~/todograph/.device_flow.json` until authorization completes or expires.

## Commands

All commands output clean JSON to **stdout**.

| Command | Description |
|---------|-------------|
| `auth` | Alias of `auth-start` |
| `auth-start` | Start device-code auth and return URL/code immediately |
| `auth-poll [max_wait_seconds]` | Poll for auth completion without blocking too long |
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
python ~/todograph/scripts/todograph.py <command> [args...]
```

## Authentication Flow for Agents

Token is cached after first login — most runs need no auth at all.

**When stdout contains `auth_required: true`:**

```json
{"auth_required": true, "started": true, "pending": true, "url": "https://microsoft.com/devicelogin", "url_complete": "https://microsoft.com/devicelogin?otc=ABCD1234", "code": "ABCD1234", "interval": 5, "expires_in": 900}
```

1. Run `python ~/todograph/scripts/todograph.py auth-start`
2. If `url_complete` is present (normal case): tell the user "请点击以下链接完成授权（验证码已自动填入）：**[url_complete]**"
3. If `url_complete` is empty (fallback): tell the user "请访问 [url] 并输入代码 **[code]** 完成登录"
4. After the user says they have finished authorizing, run `python ~/todograph/scripts/todograph.py auth-poll 15`
5. If poll returns `{"authenticated": true}`, continue the original business command
6. If poll returns `{"authenticated": false, "pending": true}`, wait and poll again
7. If poll returns `{"authenticated": false, "expired": true}`, restart with `auth-start`

**Important:** after `auth-start` has returned a URL/code, **do not** run `auth` or `auth-start` again when the user replies "已授权".

- Running `auth` / `auth-start` again will create a **new** device code, and the user's previous authorization may no longer match the current pending session.
- The correct next step after the user finishes authorization is always `python ~/todograph/scripts/todograph.py auth-poll 15`.
- Only restart with `auth-start` if `auth-poll` returns `expired`, `failed`, or there is no pending auth session.

To authenticate proactively before running other commands:
```bash
python ~/todograph/scripts/todograph.py auth-start
python ~/todograph/scripts/todograph.py auth-poll 15
```
`auth-start` returns the login URL/code immediately.
`auth-poll` returns `{"authenticated": true}` when login finishes.

## Typical Workflow

When the user asks about their tasks:

1. Run `lists` to get list IDs
2. Run `tasks <list_id>` for the relevant list
3. Present results in a readable format (not raw JSON)
4. For create/complete/delete: confirm success from the returned JSON
5. If a business command returns `{"error": "AUTH_REQUIRED"}`, start the two-step auth flow above and then retry the original command

## Azure Setup

If `CLIENT_ID` is not configured, guide the user:

1. Go to [Azure App Registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. **New registration** → any name → supported account types: "Personal Microsoft accounts"
3. Copy the **Application (client) ID**
4. **API permissions** → Add → Microsoft Graph → Delegated → `Tasks.ReadWrite`
5. **Authentication (Preview)** → Advanced settings → **Allow public client flows** → Yes → Save
6. Paste the ID into `~/todograph/.env` as `CLIENT_ID`
