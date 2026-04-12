# 🍺 Wiesn-Agent

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Microsoft Agent Framework](https://img.shields.io/badge/Microsoft-Agent_Framework-5C2D91.svg?logo=microsoft)](https://github.com/microsoft/agent-framework)
[![MCP](https://img.shields.io/badge/MCP-compatible-purple.svg)](https://modelcontextprotocol.io)
[![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688.svg)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-dashboard-61DAFB.svg)](https://react.dev)

AI-powered Oktoberfest reservation monitor — watches 38 beer tent portals, alerts you when slots open, and helps you book before anyone else.

### 💬 Example Prompts

> "Check all portals and tell me which tents have evening slots on September 25th."

> "Go to the Hacker-Festzelt and fill out the reservation form for me."

> "Keep monitoring all portals and send me a notification when new dates appear."

> "What tents currently have open reservations? Show me a summary."

## ⚙️ How It Works

Three ways to use Wiesn-Agent:

**Option A — Web Dashboard** (`wiesn-agent web` / Docker)

```mermaid
graph LR
    SCAN["🔍 Scanner\nauto every 30 min"] -->|new slots| ALERT["📲 Push + 🔔 Toast"]
    SCAN -->|results| DASH["🍺 Dashboard"]
    DASH -->|chat: fill form| FILL["🤖 AI pre-fills"]
    FILL -->|never submits| YOU["✋ You click submit"]
```

**Option B — MCP Tools** (VS Code Copilot, Claude Desktop, Cursor, …)

```mermaid
graph LR
    AI["💬 AI Client"] -->|MCP| TOOLS["🛠️ 15 tools\nscan · fill · notify"]
    TOOLS -->|browser actions| PORTAL["🌐 Portal"]
    PORTAL -->|never auto-submits| YOU["✋ You confirm"]
```

**Option C — CLI Workflow** (`wiesn-agent once/watch`)

```mermaid
graph LR
    MON["Monitor"] --> ANA["Analyzer"] --> NOT["Notifier\n+ approval prompt"]
    NOT -->|approved| FILL["Filler"]
    NOT -->|declined| END["End run"]
```

> In `watch` mode, the workflow repeats every N minutes.

All three options share the same scanner, tools, and config. Forms are **never submitted automatically**.

> ⚠️ **Continuous monitoring** requires a running process. For Option A, keep `wiesn-agent web` running (or use `docker compose up -d` for background). For Option C, use `wiesn-agent watch`. The scanner checks every 30 minutes and sends push notifications when new slots appear — but only while the process is alive.

## 🚀 Quick Start

### 1. Docker (recommended — zero setup)

```bash
git clone https://github.com/annawiewer/wiesn-agent.git && cd wiesn-agent
cp config.example.yaml config.yaml   # edit with your details
cp .env.example .env                 # edit tokens if needed
docker compose up                    # → http://localhost:5000
```

The dashboard includes a chat window — ask questions, trigger scans, or fill forms directly from the browser. Add a `GITHUB_TOKEN` to `.env` for LLM-powered chat (see [Agent Workflow](#agent-workflow-optional)).

### 2. Manual

**Prerequisites:** Python 3.10+, [Node.js 18+](https://nodejs.org/) (for building the frontend)

```bash
git clone https://github.com/annawiewer/wiesn-agent.git && cd wiesn-agent
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows:     .venv\Scripts\activate
pip install -e ".[web]"
playwright install chromium        # Linux: add --with-deps if missing system libs
cp config.example.yaml config.yaml   # edit with your details
cp .env.example .env                 # edit tokens if needed
cd web && npm install && npm run build && cd ..
wiesn-agent web                      # → http://localhost:5000
```

> **Note:** The backend (`wiesn-agent web`) must be running before the frontend works. It serves both the API and the built React app on port 5000. For development, start the backend first (`wiesn-agent web`), then the frontend dev server (`cd web && npm run dev`) — the Vite dev server on :5173 proxies API calls to :5000.

## 🔌 MCP Server

Connect any AI assistant (Copilot, Claude, Cursor, etc.) to 15 MCP tools via the [Model Context Protocol](https://modelcontextprotocol.io).

**Prerequisites:** Install the package and Playwright browser first:
```bash
cd wiesn-agent
pip install -e .
playwright install chromium
cp config.example.yaml config.yaml   # edit with your details
```

### Install in VS Code

Add to `.vscode/mcp.json`:
```json
{
  "servers": {
    "wiesn-agent": {
      "command": "python",
      "args": ["-m", "wiesn_agent.mcp_server"],
      "cwd": "${workspaceFolder}"
    }
  }
}
```

### Install in Claude Desktop

Add to your Claude MCP config (set `cwd` to the repo directory where `config.yaml` lives):
```json
{
  "mcpServers": {
    "wiesn-agent": {
      "command": "python",
      "args": ["-m", "wiesn_agent.mcp_server"],
      "cwd": "/path/to/wiesn-agent"
    }
  }
}
```

### 🛠️ Available Tools

| Tool | Description | Input Parameters |
|------|-------------|------------------|
| `check_portal` | Navigate to a portal and check for changes | `url` (string), `name` (string, optional) |
| `check_all_portals` | Scan all configured portals at once | — |
| `detect_forms` | Detect form fields, selects, and buttons on the page | — |
| `fill_field` | Fill a text input field | `selector` (string), `value` (string) |
| `select_option` | Select a dropdown option (with Livewire support) | `selector` (string), `value` (string) |
| `click_element` | Click a button or element | `selector` (string), `force` (bool, optional) |
| `fill_reservation_form` | Auto-fill entire reservation form with user data | — |
| `switch_to_iframe` | Switch context to an iframe (for Käfer, Tradition) | `selector` (string) |
| `run_js` | Execute JavaScript on the page | `script` (string) |
| `wait_for_element` | Wait for an element to appear | `selector` (string), `timeout` (int, optional), `state` (string, optional) |
| `navigate_to` | Navigate to a URL | `url` (string), `wait_until` (string, optional) |
| `take_screenshot` | Take a screenshot of the current page | `name` (string, optional) |
| `get_page_content` | Get the text content of the page | `selector` (string, optional) |
| `monitor_availability` | Scan all portals and compare with last snapshot | `portal_name` (string, optional), `check_date` (string, optional), `notify` (bool, optional) |
| `send_notification` | Send notification via 130+ services (ntfy, Telegram, etc.) | `title` (string), `message` (string), `notify_type` (string, optional) |

> **Note:** The web dashboard chat exposes 14 of these tools — `run_js` is excluded from chat agents for safety. It remains available via direct MCP connection.

**Resources:** `wiesn://config` · `wiesn://portale` · `wiesn://slots`

**Prompts:** Check all portals · Monitor availability · Check single portal · FestZelt OS Wizard

## 🤖 Agent Workflow (Optional — requires GITHUB_TOKEN)

Built on Microsoft's <a href="https://github.com/microsoft/agent-framework"><img src="https://raw.githubusercontent.com/Azure-Samples/Agentic-AI-Investment-Analysis-Sample/main/_assets/agentframework.svg" height="20" alt="Microsoft Agent Framework" style="vertical-align: middle;" /></a> [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) — instead of one monolithic LLM prompt, the system uses **4 specialized agents** that each have their own instructions and tools. A **triage layer** routes every message to the right agent automatically.

### 🔀 What is Triage?

The `TriageExecutor` is a custom routing layer built on top of the Agent Framework's `Executor` base class. The framework provides the **workflow graph infrastructure** (executors, edges, context passing), and we implement the routing logic:

- **No LLM call needed** — uses fast keyword matching (e.g. "slot", "available" → Scanner; "fill", "form" → Form Agent)
- **Context-aware** — "Fill the form for Sep 25" routes to **Form Agent** (not Scanner), even though a date is present
- **Bilingual** — recognizes both German and English keywords
- **Structured handoffs** — agents signal follow-up intent via invisible markers, so "Ja" correctly routes to the offered action
- **Cancel handling** — "Nein", "Stop", "Cancel" resets pending actions and routes to Chat
- **Zero latency** — routing happens instantly, only the chosen agent calls the LLM

### ⚡ Why Multi-Agent?

| Single Prompt | Multi-Agent (Wiesn-Agent) |
|--------------|--------------------------|
| One LLM sees all 15 tools | Each agent sees only **its** tools |
| Long, unfocused system prompt | Short, expert prompt per agent |
| Can accidentally call form tools while scanning | Scanner **cannot** access form tools |
| Hard to debug | Triage log shows exactly which agent ran |

### 🏗️ Architecture

```
User Message
     ↓
┌────────────────────────┐
│    TriageExecutor      │  keyword classification (no LLM needed)
│    "Evening slots?"    │  → detected: scan intent
└────────────┬───────────┘
             ↓ routes to one of 4 agents:

┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Scanner    │  │  Form       │  │  Notifier   │  │  Chat       │
│  Agent      │  │  Agent      │  │  Agent      │  │  Agent      │
│             │  │             │  │             │  │             │
│ Tools:      │  │ Tools:      │  │ Tools:      │  │ No tools    │
│ • monitor   │  │ • navigate  │  │ • send      │  │ (text only) │
│ • check     │  │ • fill      │  │   notif.    │  │             │
│ • check_all │  │ • select    │  │             │  │             │
│             │  │ • click     │  │             │  │             │
│             │  │ • detect    │  │             │  │             │
└─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
```

### 🧩 Framework Building Blocks

| Component | What it does |
|-----------|-------------|
| **Agent** | LLM with own system prompt + own tools |
| **TriageExecutor** | Routes user messages by keyword (no LLM cost) |
| **WorkflowBuilder** | Defines the agent graph (who talks to whom) |
| **WorkflowAgent** | Wraps the graph as a session-aware agent API |
| **InMemoryHistoryProvider** | Conversation memory across turns |
| **MCPStdioTool** | Connects Playwright MCP tools to agents |
| **OpenAIChatCompletionClient** | LLM via [GitHub Models](https://github.com/marketplace/models) (GPT-4o) |

### 🔄 Two Workflow Modes

**Web Chat** (`wiesn-agent web`) — star graph with triage:

```mermaid
graph LR
    USER["💬 User"] --> TRIAGE["🔀 Triage"]
    TRIAGE -->|scan| SCANNER["🔍 Scanner"]
    TRIAGE -->|form| FORM["📝 Form Agent"]
    TRIAGE -->|notify| NOTIFY["🔔 Notifier"]
    TRIAGE -->|chat| CHAT["💭 Chat Agent"]
```

**CLI Pipeline** (`wiesn-agent once/watch`) — linear graph:

```mermaid
graph LR
    MON["Monitor"] --> ANA["Analyzer"] --> NOT["Notifier\n+ approval"]
    NOT -->|approved| FILL["Filler"]
    NOT -->|declined| END["End run"]
```

> In `watch` mode, the pipeline repeats automatically every N minutes.

### 🧠 Follow-up Intelligence

The triage layer uses **structured handoff signals** — agents append invisible markers to their responses that tell the triage what action was offered:

- Scanner found **no** matching slots → offers notification test `<!-- handoff:notify -->` → user says "Ja" → routes to **Notifier**
- Scanner found matching slots → offers form fill `<!-- handoff:form -->` → user says "Ja" → routes to **Form Agent**
- User says "Nein" or "Cancel" → **resets** pending action, routes to Chat

This works in both German and English, no LLM call needed for routing.

<details>
<summary>Setup & Usage</summary>

```bash
pip install -e ".[web]"
playwright install chromium
echo "GITHUB_TOKEN=ghp_..." > .env   # github.com/settings/tokens (models:read)

wiesn-agent web       # web dashboard + chat at :5000
wiesn-agent web --host 0.0.0.0 --port 8080  # LAN access on custom port
wiesn-agent once      # single CLI run
wiesn-agent watch     # continuous CLI monitoring (interactive — prompts for approval)
```

> **Note:** `watch` mode is **interactive** — it prompts via stdin when a matching slot is found. It is not suitable as an unattended background daemon. For unattended monitoring, use `wiesn-agent web` which runs the scanner automatically and sends push/web notifications.

> **Without `GITHUB_TOKEN`**, the dashboard chat falls back to keyword-based responses (scan, status, matches, portals) — no LLM required.

</details>

## 📊 Dashboard

`wiesn-agent web` → **Dashboard** (live results, scan trigger) · **Portals** (38 tents, filter) · **Statistics** (charts) · **Settings** (config editor)

Background scanner runs automatically with deep-scan on your preferred dates.

## ⚙️ Configuration

```yaml
# config.yaml — keys use German field names (keep them unchanged)
user:
  vorname: "Max"
  nachname: "Mustermann"
  email: "max@example.com"
  telefon: "+49 170 1234567"
  personen: 10

reservierung:
  wunsch_tage: ["2026-09-19", "2026-09-25", "2026-09-26"]
  slots:
    morgens:  { enabled: true, von: "10:00", bis: "12:00", prioritaet: 3 }
    mittags:  { enabled: true, von: "12:00", bis: "16:00", prioritaet: 2 }
    abends:   { enabled: true, von: "16:00", bis: "23:00", prioritaet: 1 }

notifications:
  desktop: true
  apprise_urls:
    - "ntfy://wiesn-alert"    # free phone push via ntfy.sh
```

All 38 tents are pre-configured. Enable/disable in the `portale` section or via the Dashboard.

## 🏕️ Portal Architectures

Auto-detected: **Livewire** (Löwenbräu, Fischer-Vroni…) · **WordPress** (Hacker, Schottenhamel…) · **iFrame** (Käfer, Tradition) · **Standard** (Augustiner, Paulaner…)

Custom per-portal adapters can be registered for high-value tents that use non-standard UI patterns (see `portal_adapters.py`).

## 🔔 Notifications

[Apprise](https://github.com/caronc/apprise)-powered — ntfy (recommended), Telegram, Slack, Email, [130+ more](https://github.com/caronc/apprise/wiki).

### 📲 Phone Push Notifications (ntfy — free, 2 minutes)

1. **Install the ntfy app** on your phone:
   - [iOS (App Store)](https://apps.apple.com/app/ntfy/id1625396347)
   - [Android (Google Play)](https://play.google.com/store/apps/details?id=io.heckel.ntfy)

2. **Open the app** → tap **"+"** → enter your channel name (e.g. `wiesn-alert`)

3. **Add the channel to your config** (`config.yaml` → notifications → apprise_urls):
   ```yaml
   notifications:
     apprise_urls:
       - "ntfy://wiesn-alert"    # must match your app subscription
   ```

4. **Done!** You'll receive push notifications when new evening slots are found.

> **Tip:** Your channel name is public on ntfy.sh. Use something unique like `wiesn-yourname-2026` for privacy. Or [self-host ntfy](https://docs.ntfy.sh/install/) for full control.

> **No app?** Open `https://ntfy.sh/your-channel` in any browser to see notifications.

### Other Notification Channels

Add any [Apprise URL](https://github.com/caronc/apprise/wiki) to `apprise_urls`:

| Service | Config Example |
|---------|---------------|
| Telegram | `tgram://BOT_TOKEN/CHAT_ID` |
| Slack | `slack://TOKEN_A/TOKEN_B/TOKEN_C` |
| Discord | `discord://WEBHOOK_ID/WEBHOOK_TOKEN` |
| Email | `mailtos://user:pass@gmail.com` |
| WhatsApp | `whatsapp://TOKEN@PHONE/TARGET` |

### 🌙 Quiet Hours

Notifications are suppressed during quiet hours (default: 22:00–08:00). Alerts found overnight are **queued** and delivered as a morning digest when quiet hours end. Web browser toasts are always shown immediately.

## 🔒 Security

- **API Auth**: Set `WIESN_API_TOKEN` in `.env` to require bearer token auth on all `/api/` endpoints (except `/api/health`). When not set, the API is open (localhost-only use).
- **PII Redaction**: Config endpoints and MCP resources automatically redact email, phone, notification secrets, and tokens. Personal names are kept (needed for form filling).
- **Human-in-the-Loop**: Forms are **never auto-submitted**. The CLI workflow prompts for approval via stdin before pre-filling. In web mode, form filling is chat-driven — the agent pre-fills, you review and submit manually.
- **run_js Gating**: The `run_js` tool (arbitrary JS execution) is excluded from chat agent tools. It remains available via direct MCP connection for expert users. All executed scripts are logged.
- **Prompt Injection Defense**: Agent instructions explicitly treat portal page content as untrusted and ignore any instructions found in page text.
- **Audit Log**: Scan events and notifications are logged to `data/audit.log` (append-only, not subject to ring buffer limits).
- **Atomic Snapshots**: Availability snapshots use temp-file + rename to prevent corruption from concurrent writes.

## 📁 Project Structure

```
src/wiesn_agent/
├── mcp_server.py        # MCP Server (15 tools)
├── api.py               # FastAPI backend + background scanner
├── scanner.py           # Portal scanner (deep scan, snapshots)
├── chat_agent.py        # Multi-agent chat workflow (TriageExecutor)
├── workflow.py          # CLI agent workflow graph (once/watch)
├── portal_adapters.py   # Per-portal scanning adapters (extensible)
├── agents/              # 4 AI agents (CLI workflow)
└── tools/               # Browser + notification tools
web/src/                 # React dashboard (Vite + Tailwind)
```

## ❓ Troubleshooting

| Issue | Solution |
|-------|----------|
| `playwright install chromium` fails | Run with `sudo` on Linux, or use `playwright install --with-deps chromium` for missing system libraries |
| Livewire forms don't populate next selects | Increase wait time between `select_option` calls (Livewire needs 2–3s for server roundtrip) |
| CSS selector fails on FestZelt OS portals | IDs contain dots — use `run_js` with `document.getElementById()` instead |
| iframe portals (Käfer, Tradition) show no forms | Call `switch_to_iframe` first to enter the iframe context |
| `GITHUB_TOKEN` errors in chat | Create a token at github.com/settings/tokens with `models:read` scope, add to `.env` |
| Scanner finds no dates | Most portals only open reservations ~3 months before Oktoberfest (mid-June 2026) |
| API returns 401 Unauthorized | Set `Authorization: Bearer <token>` header, or remove `WIESN_API_TOKEN` from `.env` |

## 📄 License

MIT
