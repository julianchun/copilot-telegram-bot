*This is a submission for the [GitHub Copilot CLI Challenge](https://dev.to/challenges/github-2026-01-21)*

## What I Built

**copilot-telegram-bot** — a Telegram bot that brings the full GitHub Copilot CLI experience to your phone. Instead of being tethered to a terminal, you can plan architecture, write code, debug errors, run shell commands, and manage files across your projects — all from a Telegram chat, anywhere you have a phone signal.

The idea came from a simple frustration: I often think about code when I'm away from my desk — on transit, at a coffee shop, waiting in line. I wanted a way to interact with Copilot from my phone without SSH-ing into a machine or opening a laptop. This bot solves that by acting as a bridge between Telegram's chat interface and the `github-copilot-sdk`, translating taps and messages into full Copilot sessions.

### Core Capabilities

- **Dual Operation Modes:** A *Plan Mode* for high-level architecture and brainstorming (using curated system prompts), and an *Edit Mode* for hands-on coding, debugging, and command execution.
- **Mobile-First UX via Inline Keyboards:** No typing long commands — project switching, tool permissions, model selection, and agent questions are all handled through tap-friendly Telegram buttons.
- **Multimodal Vision:** Send a photo of a whiteboard sketch, a UI mockup, or an error screenshot, and Copilot reasons over it visually — turning sketches into boilerplate or debugging from screenshots.
- **Human-in-the-Loop Security:** A two-tier permission model auto-approves safe read-only tools (`list_files`, `read_file`, `glob`, etc.) for seamless flow, while dangerous operations (`bash`, `edit`, `create`) pause and present inline "Allow / Deny" buttons. Workspace confinement ensures all file access stays within configured project paths.
- **Developer HUD:** Every response includes a real-time context footer showing the active project, git branch (with dirty status), model name, billing multiplier, and current mode — so you always know exactly where you are.
- **Rich Tool Displays:** Shell commands show syntax-highlighted output, file edits render as diffs, long outputs auto-truncate, and sub-agent activity surfaces in real-time.
- **Hot-Swappable Models:** Switch between LLMs mid-session via `/model` — see billing multipliers, pick reasoning effort for supported models, and the session seamlessly restarts.
- **Session Export:** `/share` exports the full conversation history to a formatted Markdown file, so nothing is lost when the session ends.

### Architecture

The bot follows a three-layer, event-driven design:

- **Core Layer** (`src/core/`): A `CopilotService` singleton wraps the `github-copilot-sdk`'s `CopilotClient` (JSON-RPC over stdio). An `EventHandlerMixin` routes 12+ SDK event types (`ASSISTANT_MESSAGE`, `TOOL_EXECUTION_START/COMPLETE`, `SUBAGENT_STARTED/COMPLETED`, `SESSION_USAGE_INFO`, context compaction, etc.) through an async queue. A `SessionMixin` manages client lifecycle — creation, expiration detection, automatic recovery, and model switching.
- **Handlers Layer** (`src/handlers/`): Telegram command handlers for 13 commands (`/start`, `/plan`, `/model`, `/cancel`, `/usage`, etc.), a message handler for chat + file attachments, and a callback handler that resolves `asyncio.Future` objects when users tap inline buttons — bridging Telegram's UI with the SDK's permission system.
- **UI Layer** (`src/ui/`): A `MessageSender` that auto-splits responses at Telegram's 4096-char limit with safe code-block handling, specialized formatters for each tool type (bash, edit, create, grep, view, todo), and menu generators for cockpit displays and keyboard layouts.

The entire system is **zero-database** — all state lives in-memory, making it lightweight and portable. A single `.env` file configures everything.

### Tech Stack

- **Python 3.10+** with async/await throughout
- **`github-copilot-sdk`** (v0.1.23) — the official SDK for Copilot CLI integration
- **`python-telegram-bot`** (v20+) — async Telegram Bot API wrapper
- **`pydantic`** — for tool parameter validation
- **`uv`** — fast Python package manager

## Demo

**GitHub Repository:** [github.com/julianchun/copilot-telegram-bot](https://github.com/julianchun/copilot-telegram-bot)

<!-- TODO: Replace with your actual screenshot/video links -->

![Project Selection & Cockpit](https://placeholder-for-screenshot-1.png)
*The startup splash shows CLI/SDK versions and auth status, followed by a project selection keyboard. After selecting a project, the cockpit displays model, mode, branch, and workspace stats.*

![Permission Flow & Tool Execution](https://placeholder-for-screenshot-2.png)
*When Copilot wants to run a shell command or edit a file, an inline keyboard appears asking for approval. Safe operations like file reads proceed automatically.*

![Plan Mode & Code Generation](https://placeholder-for-screenshot-3.png)
*Plan Mode helps brainstorm architecture and outline project structures. Edit Mode handles implementation — writing code, running tests, and executing commands.*

<!-- TODO: Add a video walkthrough link (e.g., YouTube, Loom) -->
<!-- 📹 **Video Walkthrough:** [Watch the demo](https://your-video-link-here) -->

## My Experience with GitHub Copilot CLI

Building this project was an exercise in *building with the tool you're extending*. GitHub Copilot CLI was integral to the development process from start to finish.

### How I Used Copilot CLI

**Architecture & Planning:** Before writing any code, I used Copilot CLI in plan mode to reason through the three-layer architecture. I asked it to evaluate trade-offs between streaming vs. blocking message delivery in Telegram, and it helped me settle on the blocking approach with a "Working..." indicator — which turned out to be more reliable given Telegram's rate limits and message-editing constraints.

**SDK Integration:** The `github-copilot-sdk` is relatively new, with limited documentation outside of the source code. Copilot CLI was invaluable for exploring the SDK's API surface — I'd ask it to read through the SDK source, explain event types, and suggest how to wire up the `on_pre_tool_use` hook for the permission bridge. It effectively served as live documentation for the SDK itself.

**Event-Driven Refactoring:** The original codebase started as a single large file. Copilot CLI helped me decompose it into the mixin pattern (`EventHandlerMixin`, `SessionMixin`) and the layered architecture. I described what I wanted, and it generated the refactored module structure, moved methods into the right files, and updated all imports — a task that would have been tedious and error-prone manually.

**Telegram-Specific Edge Cases:** Telegram has subtle constraints: a 4096-character message limit, Markdown V2 escaping quirks, rate limiting on message edits, and code blocks that must be properly closed when splitting across messages. Copilot CLI helped me write the `_split_message` logic that tracks open/close code fences across chunks, and the `_ensure_safe_markdown` helper that handles edge cases I wouldn't have caught on my own.

**Tool Formatter Development:** Each tool type (bash, edit, create, grep, view, todo) needed its own display format. I'd describe what the output should look like — "show the command in a code block, truncate output after 50 lines, add a fold indicator" — and Copilot CLI would generate the formatter function, handling heredoc truncation, path extraction, and diff rendering.

### Impact on Development

The most significant impact was **velocity on unfamiliar territory**. I knew Python and Telegram, but the Copilot SDK was brand new to me. Copilot CLI bridged that knowledge gap by reading SDK source code, explaining patterns, and generating integration code — all without leaving the terminal.

It also changed how I approach debugging. Instead of adding print statements and re-running, I'd describe the symptom to Copilot CLI and have it inspect the relevant code paths, identify the issue, and apply the fix — often in a single interaction.

The recursive nature of this project — using Copilot CLI to build a Copilot CLI client — created a tight feedback loop. Every improvement I made to the bot, I could immediately test by using Copilot CLI to build the next feature. It was genuinely fun to watch the tool help build its own mobile interface.
