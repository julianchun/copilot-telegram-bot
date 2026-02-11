# 🤖 copilot-telegram-bot

**Take GitHub Copilot CLI anywhere on Telegram.**

Work from anywhere—coffee shops, transit, home—with real-time access to GitHub Copilot. This bot brings the Copilot CLI experience to Telegram. Built on the official `github-copilot-sdk`, it's mobile-first, permission-aware, and security-focused.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![SDK](https://img.shields.io/badge/Copilot-SDK-black)
![Manager](https://img.shields.io/badge/uv-managed-purple)

## ✨ Key Features

- **🛡️ Real-Time Permission Dialogs**: When the agent needs to read a file or make a decision, you approve it instantly via Telegram inline buttons—**you stay in full control**. No background actions without your knowledge.
- **📱 Mobile-First, Work Anywhere**: Optimized layouts, blocking (reliable) message output, and touch-friendly buttons. Use Copilot from your phone without limitations.
- **🚀 Copilot CLI Feature Parity**:
  - **Agent Mode**: Standard agent assistance
  - **Plan Mode**: Create an implementation plan before coding
  - **Model Hot-Swap** (`/model`): Switch LLMs with reasoning effort levels (low/medium/high)
  - **Usage Metrics** (`/usage`): Per-call and aggregate token costs visible in message footers
  - **Session Export** (`/share`): Export conversation history as Markdown
- **📂 Project Isolation**: Each subdirectory is a separate project with automatic SDK restart—guarantees fresh context when you switch.
- **🛡️ Security-First Design**:
  - Single-user whitelist (`ALLOWED_USER_ID`)
  - Read-only filesystem sandbox (no write/execute access)
  - Per-interaction permission bridge (agent must ask before acting)
  - **"No write access is a feature, not a limitation"** — safe for untrusted agents
- **📎 Rich File Attachments**: Upload images and documents; agent sees them as file references in a temp sandbox directory
- **💾 Zero Database**: Lightweight, portable sessions stored in-memory—no persistence layer required

## 🛠️ Prerequisites

1.  **Python 3.10+**
2.  **[uv](https://github.com/astral-sh/uv)** (Fast Python package manager)
3.  **GitHub Copilot CLI** (authenticated)
    ```bash
    npm install -g @github/copilot-cli
    copilot auth
    ```

## 🚀 Installation & Setup

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/yourusername/copilot-telegram-bot.git
    cd copilot-telegram-bot
    ```

2.  **Install Dependencies**
    ```bash
    uv sync
    ```
    
    > **⚠️ Important:** There's a permission issue with the copilot SDK binary on v0.1.23. After running `uv sync`, fix the file permissions:
    > ```bash
    > chmod +x ./.venv/lib/python3.*/site-packages/copilot/bin/copilot
    > ```
    > Adjust the Python version (3.*) to match your environment.

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
    ```
    > **ALLOWED_USER_ID** is mandatory—only this user can access the bot. Get your ID from the first bot message if not set.
    
    > **WORKSPACE_ROOT** is your project sandbox. The bot cannot access files outside this directory (or `GRANTED_PROJECTS`).
    
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
    - Print a dashboard with project selection
    - Load the Copilot CLI session (requires prior `copilot auth`)
    - Prompt for permissions on every tool invocation (read_file, list_files)
    - Store all state in-memory—no database, pure Telegram state

## 🎮 Usage

### Main Menu (`/start`)
The bot launches into a dashboard showing:
- **Authentication Status**
- **Current Directory** (Operating System CWD)
- **Active Model** (GPT-4o, Claude 3.5, etc.)
- **Project Selection List**

### Commands

| Command | Description |
| :--- | :--- |
| `/start` | Open the main dashboard and project selector. |
| `/plan` | Toggle **Plan Mode**. (Great for "How should I build X?"). |
| `/edit` | Switch back to **Chat Mode**. (Implementation focus). |
| `/model` | Hot-swap the underlying LLM (e.g., `gpt-4o`). **Note:** Changes reset the session (history cleared). |
| `/context` | Display model context and token usage info. |
| `/tools` | List enabled MCP tools (`list_files`, `read_file`). |
| `/usage` | Display session usage metrics. |
| `/share` | Export session to Markdown file. |
| `/clear` | Reset conversation memory. |
| `/ls` | List files in current directory. |
| `/cwd` | Show current working directory. |

## ⚡ How Permissions Work

**The Permission Flow** (unique to Telegram):

```
Agent wants to read a file (e.g., config.ts)
          ↓
You see inline button: "[✅ Allow] [❌ Deny]"
          ↓
You click "Allow" directly in Telegram
          ↓
Agent reads file and continues processing
```

Rather than background API calls, **every MCP tool invocation prompts you**—you never wonder what the agent is accessing.

**Permission Dialog Examples:**
- **File Read**: "🛡️ Permission request: **read_file** with: `['src/app.ts']` — Allow?"
- **Model Selection**: Click `/model` → buttons appear → select your LLM → reasoning level prompt → session restarts
- **Agent Questions**: "❓ **Copilot Asks:** What's your preferred testing framework? [Jest] [Vitest] [Cancel]"

This keeps you **in the loop** and ensures no tool executes without your approval—perfect for collaborative, untrusted, or learning-mode agents.

## 🏗️ Architecture

Three-layer, event-driven design under [src/](src/):

- **[src/main.py](src/main.py)**: Telegram bot entry point. Initializes handlers and polling.
  
- **[src/core/](src/core/)** — SDK & State Management:
  - **[service.py](src/core/service.py)**: Manages `CopilotClient` lifecycle. Registers SDK event handlers (ASSISTANT_MESSAGE_DELTA, TOOL_EXECUTION, SESSION_IDLE). **Key feature**: Permission bridge hooks (`on_pre_tool_use`) intercept tool calls before execution.
  - **[context.py](src/core/context.py)**: Holds shared session state (working directory, temp files, usage metrics).
  - **[tools.py](src/core/tools.py)**: Defines read-only MCP tools (`list_files`, `read_file`) with strict path validation.

- **[src/handlers/](src/handlers/)** — Event Handlers:
  - **[commands.py](src/handlers/commands.py)**: `/start`, `/plan`, `/model`, `/context`, etc.
  - **[messages.py](src/handlers/messages.py)**: Chat messages. **Implements interaction callback** — when agent needs permission, creates Future + inline keyboard.
  - **[callbacks.py](src/handlers/callbacks.py)**: Inline button clicks. **Resolves Futures** — when user clicks "Allow"/"Deny", unpacks interaction_id and sets `future.set_result()`.

- **[src/ui/](src/ui/)** — Output & Formatting:
  - **[streamer.py](src/ui/streamer.py)**: `MessageSender` class. Accumulates response chunks, sends tool events as permanent messages, final response with footer (cost, model, branch).
  - **[menus.py](src/ui/menus.py)**: Menu text generation, inline keyboard layouts.

### Permission Bridge (Core Innovation)

**When agent requests a tool:**

1. SDK fires `on_pre_tool_use` hook in [service.py](src/core/service.py#L369)
2. Hook calls `interaction_callback("permission", request)` 
3. Handler creates `asyncio.Future`, stores in `PENDING_INTERACTIONS[id]`, sends inline keyboard
4. Handler **awaits** the Future (blocks until user responds)
5. User clicks button → [callbacks.py](src/handlers/callbacks.py#L144) resolves Future with True/False
6. Hook returns permission decision to SDK, execution continues or stops

This pattern ensures **every tool invocation has explicit user consent**—perfect for safety and transparency.

### Data Flow: Permission Request → Button Click → Agent Resumes

```
[Agent requests: read_file('config.ts')]
         ↓ on_pre_tool_use hook
[permission_bridge → interaction_callback("permission", ...)]
         ↓ Handler creates Future + keyboard
[Sends to Telegram: "🛡️ read_file — [Allow] [Deny]"]
         ↓ Future.await()
[User clicks [Allow] button]
         ↓ Button callback
[_handle_interaction_callback resolves: future.set_result(True)]
         ↓ Future wakes, returns to permission_bridge
[SDK receives: {"permissionDecision": "allow"}]
         ↓
[Tool execution proceeds, result streamed to agent]
```

## 🔒 Security Model

**Single-User Whitelist**  
Only the Telegram user ID in `ALLOWED_USER_ID` can access the bot. All other messages are silently dropped.

**Filesystem Sandbox**  
- All file access restricted to `WORKSPACE_ROOT` + optional `GRANTED_PROJECTS` paths
- MCP tools (`list_files`, `read_file`) validate paths via `Path.relative_to(root)` — escaping the sandbox is impossible
- No write, delete, or shell-execute access — read-only by design

**Permission-Per-Tool**  
- MCP tool invocation triggers a permission dialog before execution
- User can explicitly deny any file read, preventing information leakage
- No background API calls without your knowledge

## 🤝 Contributing

Managed by `uv`.
1.  Fork & Clone
2.  `uv sync` to setup environment.
3.  `uv run main.py` to dev.

## License

MIT
