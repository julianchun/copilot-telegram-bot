# copilot-telegram-bot

**Take GitHub Copilot anywhere on Telegram.**

Work from anywhere—coffee shops, transit, home—with real-time access to GitHub Copilot. This bot brings the Copilot CLI experience to Telegram. Built on the `github-copilot-sdk`, it's mobile-first, permission-aware, and security-focused.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![SDK](https://img.shields.io/badge/Copilot_SDK-v0.2.0-black)
![Manager](https://img.shields.io/badge/uv-managed-purple)
![License](https://img.shields.io/badge/License-MIT-green.svg)

---

## ✨ Key Features

### 🤖 Flexible AI Behaviors (Modes, Agents, & Skills)
- **3 Native Operation Modes:** Switch instantly between **Edit** (coding), **Plan** (architecting), and **Autopilot** (autonomous execution) while preserving your conversation history.
- **Custom Agents:** Load and switch between specialized agents (`/agent`) tailored for specific tasks, independent of your current mode.
- **Skills System:** Load reusable prompt modules from `skills/` directories globally or per-project to extend Copilot's capabilities (`/skills`).
- **Project Instructions:** Native support for `.github/copilot-instructions.md` with inline actions to view, clear, or auto-generate them based on project analysis (`/instructions`).

### 📱 Mobile-First UX
Forget typing long commands. We use **Telegram Inline Keyboards** for high-frequency actions:
- **Project Switcher:** Instantly switch between defined projects in your workspace via `/start`.
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
>🤖 gpt-5.2 (1.00x)
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
    | `local` / `stdio` | `command`, `args`, `env`, `cwd` | Local process (spawned as subprocess) |
    | `http` / `sse` | `url`, `headers` | Remote HTTP or SSE endpoint |
    
    Set `"tools": ["*"]` to expose all tools from a server, or list specific tool names. If the config file is missing or has no `mcpServers` key, the bot starts normally without MCP.
    
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
- Current model + billing multiplier
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
| `/model` | Hot-swap the underlying LLM (e.g., `gpt-4.1`). Conversation history is preserved. |
| `/clear` | Reset conversation memory. |
| `/share` | Export full session to Markdown file. |
| `/session` | Show session info and workspace summary. |
| `/usage` | Display detailed session metrics — per-model token breakdown, cost, quota snapshots. |
| `/context` | Display model context and token usage info. |

**Configuration & Extensions**
| Command | Description |
| :--- | :--- |
| `/allowall` | Toggle auto-approval for tool permission prompts in the current session. |
| `/instructions` | Show custom instruction status and inline actions for view, clear, and generate. |
| `/init` | Ask Copilot to generate `.github/copilot-instructions.md` for the active project. |
| `/skills` | List skills, inspect a skill, or reload skills from registered skill roots. |

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
- The bot loads skills from the following directories:
  - **Global/Personal:** `~/.copilot/skills/`, `~/.claude/skills/`, `~/.agents/skills/`
  - **Project-specific:** `.github/skills/`, `.claude/skills/`, `.agents/skills/`, and `skills/`
- `/skills reload` asks the SDK to rescan those registered roots, which lets newly added project skill folders show up without reselecting the project.

## 🔧 Under the Hood
<details>
<summary><strong>Click to expand technical details</strong></summary>

This bot is built on top of the **`github-copilot-sdk` v0.2.0**, which manages a `CopilotClient` process communicating via JSON-RPC over stdio.
- **Event-Driven:** Processes SDK events (`ASSISTANT_MESSAGE`, `TOOL_EXECUTION_START`, `SESSION_IDLE`, `SESSION_USAGE_INFO`) through an async event handler registered via `on_event` in `create_session()`, ensuring early events like `SESSION_START` are never missed.
- **Native Mode Switching:** Plan/Autopilot/Edit modes are implemented using the native SDK Mode API (`session.rpc.mode.set()`). This cleanly separates operational modes from Custom Agents, preserving conversation history across mode switches while allowing you to simultaneously use a custom agent (via `/agent`).
- **Session Lifecycle:** Manages session creation, expiration detection, context compaction, and automatic recovery. Model changes use `session.set_model()` with graceful fallback to session reset.
- **Multimodal Encoding:** Encodes image attachments for the Copilot API, enabling visual reasoning capabilities.
- **Permission Bridge:** Intercepts tool invocations via `on_pre_tool_use` hook, routing dangerous operations through Telegram inline keyboards for human approval. The same callback-safe interaction path is used for normal chats and inline actions like `/instructions` → `Generate`.
</details>

## ⚡ How Permissions Work

The bot uses a **two-tier permission model**:

**Auto-approved tools** (seamless, no interruption):
`list_files`, `read_file`, `view`, `glob`, `report_intent`, `task`, `update_todo`, `ask_user`, `fetch_copilot_cli_documentation`

**Requires explicit approval** (inline keyboard prompt):
`bash`, `edit`, `create`, and any other tool not in the allowlist.

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

Safe, read-only operations proceed automatically so you're not tapping "Allow" on every file read. Dangerous operations always pause and wait for your explicit approval.

**Permission Dialog Examples:**
- **Shell Command**: "🛡️ Permission request: **bash** with: `npm install` — Allow?"
- **File Write**: "🛡️ Permission request: **edit** with: `['src/app.ts']` — Allow?"
- **Model Selection**: Click `/model` → buttons appear → select your LLM → reasoning effort picker (for supported models) → model switches without losing conversation
- **Agent Questions**: "❓ **Copilot Asks:** What's your preferred testing framework? [Jest] [Vitest] [Cancel]"

This keeps you **in the loop** on critical actions while maintaining a smooth flow for safe operations.

### 🤖 True "Hands-Free" Autopilot
By default, Autopilot mode still pauses to ask for your permission before executing dangerous commands (like `npm install`). 

For a fully autonomous, hands-free experience:
1. Type `/allowall` (Tells the bot: "Auto-approve all security prompts").
2. Type `/autopilot build me a react login page` (Tells the AI: "Take initiative and build this").

With both active, Copilot will plan the feature, create the files, install dependencies, and run tests continuously without stopping to ask you for a single button tap!

## 🏗️ Architecture
<details>
<summary><strong>Click to expand architecture details</strong></summary>

Three-layer, event-driven design under [src/](src/):

- **[src/main.py](src/main.py)**: Telegram bot entry point. Initializes handlers and polling.
  
- **[src/core/](src/core/)** — SDK & State Management:
  - **[service.py](src/core/service.py)**: `CopilotService` singleton. Manages high-level chat flow with 4 callbacks, mode switching via the native SDK Mode API (`set_mode()`), custom agent selection via the SDK Agent API, and project info display.
  - **[session.py](src/core/session.py)**: `SessionMixin` — manages `CopilotClient` lifecycle, registers SDK event handlers via `on_event`, implements the **permission bridge** with tool allowlist + `on_pre_tool_use` hook. Configures system message customization and handles loading custom agent profiles and skills from the workspace.
  - **[events.py](src/core/events.py)**: SDK event dispatcher. Handles `ASSISTANT_MESSAGE`, `TOOL_EXECUTION_START/COMPLETE`, `SESSION_IDLE`, `SESSION_USAGE_INFO`, `SUBAGENT_STARTED/COMPLETED`, context compaction, and more.
  - **[context.py](src/core/context.py)**: `SessionContext` singleton — holds shared state (working directory, temp files, tracked files).
  - **[usage.py](src/core/usage.py)**: Per-model token/cost tracking, quota snapshots, session duration.
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


## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
