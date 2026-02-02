# 🤖 copilot-cli-telegram

**Using GitHub Copilot CLI on your Telegram.**

Interact with your development environment, navigate your codebase, and architect solutions directly from Telegram. This bot wraps the official `github-copilot-sdk` to provide a mobile-optimized, secure, and context-aware coding assistant that feels like a real CLI.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![SDK](https://img.shields.io/badge/Copilot-SDK-black)
![Manager](https://img.shields.io/badge/uv-managed-purple)

## ✨ Features

- **📱 Mobile-First Experience**: Compact ASCII art, optimized message layouts, and distinct "System" vs "Chat" formatting.
- **🚀 Smart Streaming**: Debounced, buffered text output ensures smooth, flicker-free responses on Telegram (even on bad networks).
- **📂 Workspace Confinement**: 
  - Strictly sandbox execution to a `WORKSPACE_ROOT`.
  - Each subdirectory is treated as an isolated **Project**.
  - **Seamless Switching**: Changing projects automatically restarts the underlying Copilot agent in the new directory context.
- **🧠 Plan vs. Chat Mode**:
  - **Chat Mode**: Standard coding assistance and implementation.
  - **Plan Mode**: Forces the agent to think at a high level (architecture, design patterns) before coding.
- **🛡️ Secure Access**: strict User ID whitelisting ensures only *you* can access your machine.

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
    ```
    > **Note:** `ALLOWED_USER_ID` is mandatory. The bot will print your ID on the first run if you try to access it without setup.

4.  **Run the Bot**
    ```bash
    uv run main.py
    ```

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
| `/model` | Hot-swap the underlying LLM (e.g., `o1-preview`). |
| `/context` | Show files currently loaded in the agent's memory. |
| `/tools` | List enabled MCP tools (`list_files`, `read_file`). |
| `/info` | Display debug session information. |

## 🏗️ Architecture

- **`main.py`**: Telegram bot entry point. Handles UI, menus, and message routing.
- **`copilot_service.py`**: The "Backend". Manages the `CopilotClient` lifecycle.
  - *Crucial:* When switching projects, this service **restarts** the SDK process with the new `cwd` to ensure true context isolation.
- **`ux_utils.py`**: `SmartStreamer` class. Handles markdown parsing, cursor animation (` ▋`), and message pagination.

## 🔒 Security Model

- **Authorization**: The bot ignores all messages unless the sender's ID matches `ALLOWED_USER_ID`.
- **Filesystem Access**: The bot uses custom MCP tools (`list_files`, `read_file`) which are strictly scoped to the `WORKSPACE_ROOT`. It cannot access files outside this directory.

## 🤝 Contributing

Managed by `uv`.
1.  Fork & Clone
2.  `uv sync` to setup environment.
3.  `uv run main.py` to dev.

## License

MIT
