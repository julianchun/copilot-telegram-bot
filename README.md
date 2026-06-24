# copilot-telegram-bot

**Take GitHub Copilot anywhere on Telegram.**

Work from anywhere—coffee shops, transit, home—with real-time access to GitHub Copilot. This bot brings the Copilot CLI experience to Telegram. Built on the `github-copilot-sdk`, it's mobile-first, permission-aware, and security-focused.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![SDK](https://img.shields.io/badge/Copilot_SDK-v1.0.0-black)
![Manager](https://img.shields.io/badge/uv-managed-purple)
![License](https://img.shields.io/badge/License-MIT-green.svg)

---

## ✨ Key Features

### 🤖 Flexible AI Behaviors (Modes, Agents, & Skills)
- **3 Native Operation Modes:** Switch instantly between **Edit** (coding), **Plan** (architecting), and **Autopilot** (autonomous execution) while preserving your conversation history.
- **Custom Agents:** Load and switch between specialized agents (`/agent`) tailored for specific tasks, independent of your current mode.
- **Skills System:** Load reusable prompt modules from Copilot CLI-compatible skill roots, including `.github/skills`, `.claude/skills`, `.agents/skills`, `~/.copilot/skills`, and `~/.agents/skills` (`/skills`).
- **Project Instructions:** Native support for `.github/copilot-instructions.md` with inline actions to view, clear, or auto-generate them based on project analysis (`/instructions`).

### 📱 Mobile-First UX
Forget typing long commands. We use **Telegram Inline Keyboards** for high-frequency actions:
- **Project Switcher:** Instantly switch between defined projects in your workspace via `/start`.
- **Session Resume Picker:** Browse previous Copilot sessions with `/resume`, inspect details, and continue one from Telegram.
- **Interactive Permissions:** "Allow" or "Deny" tool execution (e.g., file writes, shell commands) with a single tap.
- **Smart Options:** When the model asks for clarification, reply via multiple-choice buttons.

### 👁️ Support Multimodal Vision
Don't just tell Copilot about the bug—**show it**.
- **Mockup to Code:** Send a photo of a whiteboard sketch and ask Copilot to generate the boilerplate.
- **Contextual Awareness:** Images are attached seamlessly to the prompt context.

### 📊 Developer-First HUD (Heads-Up Display)
Every response is equipped with a **Real-time Context Footer**, giving you critical metadata at a glance:
>```
>📂 webproject
>🔀 feature/auth*
>🤖 gpt-5.2
>⚙️ Mode: Planning
>```

Tool executions get **specialized displays** — bash commands show syntax-highlighted output, file edits show diffs, and long outputs are auto-truncated. Sub-agent activity (when Copilot spawns workers) is surfaced in real-time.

### 🔌 MCP Server Integration
Connect external [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) servers to extend Copilot with custom tools — databases, APIs, file systems, or any service exposing an MCP interface. Supports both local subprocess servers and remote HTTP/SSE endpoints. Loaded at startup from a simple JSON config.

### 🛡️ Security & Control (Human-in-the-Loop)
- **Workspace Confinement:** Server-side enforcement of workspace paths. All file access restricted to `WORKSPACE_ROOT` + optional `GRANTED_PROJECTS` paths.
- **Two-Tier Permission Model:** Safe, read-only tools (`list_files`, `read_file`, `view`, `glob`, etc.) are **auto-approved** for seamless flow. Dangerous tools (`bash`, `edit`, `create`) require **explicit user approval** via inline buttons.
- **Transparent Tool Use:** Every tool invocation is displayed to you—auto-approved ones show inline, while dangerous ones pause and wait for your tap.
- **Chat Lock:** Prevents concurrent requests from interfering with each other.
- **Zero Database:** Lightweight, portable sessions stored in-memory—no persistence layer required.

## 🛠️ Prerequisites

1.  **Python 3.11+**
2.  **[uv](https://github.com/astral-sh/uv)** (Fast Python package manager)
3.  **GitHub Copilot CLI** (authenticated)
    ```bash
    npm install -g @github/copilot-cli
    copilot auth
    ```

## 🚀 Installation & Setup

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/julianchun/copilot-telegram-bot
    cd copilot-telegram-bot
    ```

2.  **Install Dependencies**
    ```bash
    uv sync
    ```
    
3.  **Configuration**
    Create a `.env` file in the root directory:
    ```bash
    cp .env.example .env
    ```
    
    Edit `.env` with your details:
    ```env
    TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
    ALLOWED_USER_ID=your_telegram_user_id
    WORKSPACE_ROOT=/absolute/path/to/your/projects
    GRANTED_PROJECTS=/optional/additional/paths  # Comma-separated, optional
    GITHUB_TOKEN=ghp_your_github_token_here  # Optional, see below
    MCP_CONFIG_PATH=                          # Optional, defaults to ~/.copilot/mcp-config.json
    ```
    > **ALLOWED_USER_ID** is mandatory—only this user can access the bot. Get your ID from the first bot message if not set.
    
    > **WORKSPACE_ROOT** is your project sandbox. The bot cannot access files outside this directory (or `GRANTED_PROJECTS`).
    
    ### MCP Server Support (Optional)
    
    Connect external [MCP servers](https://modelcontextprotocol.io/) to give Copilot access to additional tools (databases, APIs, custom services, etc.).
    
    Create an MCP config file at `~/.copilot/mcp-config.json` (or set `MCP_CONFIG_PATH` in `.env`):
    
    ```json
    {
      "mcpServers": {
        "my-server": {
          "type": "local",
          "command": "node",
          "args": ["./my-mcp-server.js"],
          "tools": ["*"],
          "env": { "API_KEY": "your-key" }
        },
        "remote-server": {
          "type": "http",
          "url": "https://my-mcp-endpoint.example.com",
          "headers": { "Authorization": "Bearer token" },
          "tools": ["*"]
        }
      }
    }
    ```
    
    **Server types:**
    | Type | Fields | Use case |
    | :--- | :--- | :--- |
    | `local` / `stdio` | `command`, `args`, `env`, `working_directory` | Local process (spawned as subprocess) |
    | `http` / `sse` | `url`, `headers` | Remote HTTP or SSE endpoint |
    
    Set `"tools": ["*"]` to expose all tools from a server, or list specific tool names. Legacy local-server `cwd` values are still accepted and normalized to `working_directory`. If the config file is missing or has no `mcpServers` key, the bot starts normally without MCP.
    
    ### GitHub Authentication
    
    Two options for authenticating with GitHub Copilot:
    
    1. **GitHub CLI (default)**: Run `copilot auth` before starting the bot. The SDK will use your stored credentials.
    2. **GitHub Token (optional)**: Set `GITHUB_TOKEN` in `.env` to override CLI auth. This is useful for:
       - Containerized deployments where CLI auth is difficult
       - CI/CD environments
       - Programmatic access without interactive login
    
    If `GITHUB_TOKEN` is provided, it takes priority over CLI authentication. Otherwise, the bot relies on your existing `copilot auth` session.

4.  **Run the Bot**
    ```bash
    uv run main.py
    ```
    
    The bot will:
    - Print a startup splash with CLI version, SDK version, and auth status
    - Present a project selection keyboard
    - After project selection, show a cockpit with model, mode, branch, and file/folder stats
    - Auto-approve safe tools; prompt for dangerous tool permissions via inline buttons
    - Store all state in-memory—no database, pure Telegram state

## 🎮 Usage

### Main Menu (`/start`)
The bot launches into a **startup splash** showing:
- **Copilot CLI & SDK versions**
- **Authentication status**
- **Project selection keyboard** (2-column grid with a "Create project" button)

After selecting a project, a **cockpit message** appears with:
- Current model
- Active mode (Plan/Edit)
- Branch name + dirty status
- File/folder count in workspace

### Commands

**Core Workflow**
| Command | Description |
| :--- | :--- |
| `/start` | Open the main dashboard and project selector. |
| `/plan` | Toggle **Plan Mode**. (Great for "How should I build X?"). |
| `/autopilot` | Toggle **Autopilot Mode**. (Autonomous execution). |
| `/edit` | Switch back to **Chat Mode**. (Implementation focus). |
| `/cancel` | Cancel an in-progress request. |

**Session & Context**
| Command | Description |
| :--- | :--- |
| `/model` | Hot-swap the underlying LLM. Conversation history is preserved. |
| `/clear` | Reset conversation memory. |
| `/share` | Export full session to Markdown file. |
| `/session` | Session management entry point: info, workspace files, and plan inspection. |
| `/resume` | Browse previous Copilot sessions and continue one from Telegram. |
| `/attach <session_id\|last>` | Advanced shortcut to resume a specific session ID or the latest session. |
| `/usage` | Display detailed session metrics — AI credits, per-model token breakdown, and quota snapshots. |
| `/context` | Display model context and token usage info. |

**Configuration & Extensions**
| Command | Description |
| :--- | :--- |
| `/agent` | List, select, deselect, or reload specialized custom agents discovered from `.agent.md` files. |
| `/allowall` | Toggle auto-approval for tool permission prompts in the current session. |
| `/instructions` | Show custom instruction status and inline actions for view, clear, and generate. |
| `/init` | Ask Copilot to generate `.github/copilot-instructions.md` for the active project. |
| `/skills` | List skills, inspect a skill, or reload skills from SDK-discovered roots. |

**System & Files**
| Command | Description |
| :--- | :--- |
| `/ls` | List files in current directory. |
| `/cwd` | Show current working directory. |
| `/ping` | Run a quick health check for bot, session, and SDK RPC state. |
| `/help` | Show context-aware help with live status indicators. |

### Custom Instructions
- `/instructions` opens an inline menu for project-level custom instructions stored at `.github/copilot-instructions.md`.
- `Generate` reuses the normal chat pipeline, so permission prompts and follow-up choices work from callback queries as well as slash commands.
- `Clear` removes the file and recreates the session so the absence of instructions applies immediately.

### Skills
- The bot enables SDK config discovery and also registers the Copilot CLI-compatible skill roots explicitly.
- Project skills are loaded from `.github/skills`, `.claude/skills`, and `.agents/skills` in the active workspace.
- Personal skills are loaded from `~/.copilot/skills` and `~/.agents/skills`.
- `/skills reload` asks the SDK to rescan those roots so newly added skills show up without reselecting the project.

### Custom Agents
- `/agent` opens a selector for specialized agents discovered from project and personal `.agent.md` files.
- Agents are independent of operation modes, so you can stay in Edit, Plan, or Autopilot mode while using a domain-specific agent.
- `/agent reload` asks the SDK to rescan agent definitions after adding or editing agent files.

### Session Management
- `/session` or `/session info` shows the live session summary: session ID, mode, model, LLM call count, workspace path, branch, quota, and usage totals.
- `/session files` lists artifacts stored in the session workspace `files/` directory when infinite sessions are enabled.
- `/session plan` shows the current `plan.md` inline, or sends it as a file when it is too large for a Telegram message.
- `/resume` opens a paginated resume picker for previous Copilot sessions. Each page shows six sessions with compact local timestamps, number-only detail buttons, and a detail screen with actions to attach or go back. Sessions can only attach when their workspace is inside `WORKSPACE_ROOT` or `GRANTED_PROJECTS`.
- `/attach <session_id|last>` skips the picker and resumes a specific session directly. This is useful when you already copied a session ID or just want the most recently modified session.

## 🔧 Under the Hood
<details>
<summary><strong>Click to expand technical details</strong></summary>

This bot is built on top of the **`github-copilot-sdk` v1.0.0**, with `CopilotClient` connected through the SDK's stdio runtime transport.
- **Event-Driven:** Processes SDK events (`ASSISTANT_MESSAGE`, `TOOL_EXECUTION_START`, `SESSION_IDLE`, `SESSION_USAGE_INFO`) through an async event handler registered via `on_event` in `create_session()`, ensuring early events like `SESSION_START` are never missed.
- **Native Mode Switching:** Plan/Autopilot/Edit modes are implemented using the native SDK Mode API (`session.rpc.mode.set()`). This cleanly separates operational modes from Custom Agents, preserving conversation history across mode switches while allowing you to simultaneously use a custom agent (via `/agent`).
- **Session Lifecycle:** Manages session creation, expiration detection, context compaction, automatic recovery, and previous-session resume via `resume_session()`. Model changes use `session.set_model()` and session export uses SDK event history from `get_events()`.
- **Multimodal Encoding:** Encodes image attachments for the Copilot API, enabling visual reasoning capabilities.
- **Permission Bridge:** Handles v1 `on_permission_request` events, auto-approves bounded read-only file reads, and routes URL, shell, write, MCP, memory, hook, and custom-tool requests through Telegram inline keyboards.
- **Plan Approval:** Keeps the exit-plan review UX in Telegram while resolving SDK pending plan requests through the v1 UI RPC.
</details>

## ⚡ How Permissions Work

The bot uses the SDK v1 permission model:

**Auto-approved requests** (seamless, no interruption):
bounded read-only file reads inside allowed workspace roots.

**Requires explicit approval** (inline keyboard prompt):
URL opens, shell commands, file writes, MCP tool calls, memory changes, hooks, custom tools, and any request that is not a bounded read.

**The Permission Flow** (for dangerous tools):

```
Agent wants to run a shell command (e.g., npm install)
          ↓
You see inline button: "[✅ Allow] [❌ Deny]"
          ↓
You click "Allow" directly in Telegram
          ↓
Agent executes and continues processing
```

Safe, read-only operations proceed automatically so you're not tapping "Allow" on every file read. Riskier operations pause and wait for your explicit approval.

**Permission Dialog Examples:**
- **Shell Command**: "🛡️ Permission request: **shell** with: `npm install` — Allow?"
- **File Write**: "🛡️ Permission request: **write** with: `src/app.ts` — Allow?"
- **Model Selection**: Click `/model` → buttons appear → select your LLM → reasoning effort picker (for supported models) → model switches without losing conversation
- **Agent Questions**: "❓ **Copilot Asks:** What's your preferred testing framework? [Jest] [Vitest] [Cancel]"

This keeps you **in the loop** on critical actions while maintaining a smooth flow for safe operations.

### 🤖 True "Hands-Free" Autopilot
By default, Autopilot mode still pauses to ask for your permission before executing dangerous commands (like `npm install`). 

For a fully autonomous, hands-free experience:
1. Type `/allowall` (Tells the bot: "Auto-approve non-URL security prompts for this session").
2. Type `/autopilot build me a react login page` (Tells the AI: "Take initiative and build this").

With both active, Copilot can plan the feature, create files, install dependencies, and run tests continuously. URL permission requests still pause for explicit Telegram approval.

## 🏗️ Architecture
<details>
<summary><strong>Click to expand architecture details</strong></summary>

Three-layer, event-driven design under [src/](src/):

- **[src/main.py](src/main.py)**: Telegram bot entry point. Initializes handlers and polling.
  
- **[src/core/](src/core/)** — SDK & State Management:
  - **[service.py](src/core/service.py)**: `CopilotService` singleton. Manages high-level chat flow with 4 callbacks, mode switching via the native SDK Mode API (`set_mode()`), custom agent selection via the SDK Agent API, and project info display.
  - **[session.py](src/core/session.py)**: `SessionMixin` — manages `CopilotClient` lifecycle, registers SDK event handlers via `on_event`, implements the v1 **permission bridge** with `on_permission_request`, normalizes MCP config, and configures system message customization, tools, and skill roots.
  - **[events.py](src/core/events.py)**: SDK event dispatcher. Handles `ASSISTANT_MESSAGE`, `TOOL_EXECUTION_START/COMPLETE`, `SESSION_IDLE`, `SESSION_USAGE_INFO`, `SUBAGENT_STARTED/COMPLETED`, context compaction, and more.
  - **[context.py](src/core/context.py)**: `SessionContext` singleton — holds shared state (working directory, temp files, tracked files).
  - **[usage.py](src/core/usage.py)**: Per-model token and AI-credit tracking, quota snapshots, session duration.
  - **[tools.py](src/core/tools.py)**: Read-only MCP tools (`list_files`, `read_file`) with strict path validation.
  - **[git.py](src/core/git.py)**: Branch detection and dirty-tree status for HUD footers.
  - **[filesystem.py](src/core/filesystem.py)**: Directory listing, project stats, noise-filtered file trees.

- **[src/handlers/](src/handlers/)** — Telegram Handlers:
  - **[commands.py](src/handlers/commands.py)**: Bot commands including session controls, health checks, instructions actions, and skill reload/list commands.
  - **[messages.py](src/handlers/messages.py)**: Chat messages + file attachments. Implements the interaction callback and callback-safe reply flow for permission prompts and model questions.
  - **[callbacks.py](src/handlers/callbacks.py)**: Inline button clicks. Resolves Futures — when user taps "Allow"/"Deny", resolves `future.set_result()`.

- **[src/ui/](src/ui/)** — Output & Formatting:
  - **[streamer.py](src/ui/streamer.py)**: `MessageSender` — sends tool events as permanent messages, final response with footer. Auto-splits at 4000 chars, handles code block safety, retry on rate limits.
  - **[formatters.py](src/ui/formatters.py)**: Specialized tool display (bash, edit, create, grep, view, report_intent, task, update_todo) with heredoc truncation.
  - **[menus.py](src/ui/menus.py)**: Menu text generation, inline keyboard layouts, cockpit display.
  - **[session_exporter.py](src/ui/session_exporter.py)**: Exports full sessions to formatted Markdown files.
</details>

## ⚠️ Limitations
- **Single-user only** — designed for personal use with one `ALLOWED_USER_ID`
- **Project switching restarts session** — the SDK requires a fresh `CopilotClient` process per working directory, so switching projects clears conversation history
- **Session resume is not live remote control** — `/resume` continues a previous session from Telegram, but it does not live-sync messages typed in another Copilot UI/TUI, or mirror Telegram messages back into that UI in real time.


## License
MIT
