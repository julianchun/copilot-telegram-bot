# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `/agent` command to list, select, deselect, and reload specialized custom agents from `.agent.md` files.
- `/autopilot` command for highly autonomous execution mode (best paired with `/allowall`).
- `/skills` command to list and reload reusable prompt modules from global (`~/.copilot/skills/`, etc.) and project-specific (`.github/skills/`, `skills/`) directories.
- `/instructions` and `/init` commands to view, clear, or auto-generate project-specific instructions (`.github/copilot-instructions.md`).
- `/allowall` command to toggle auto-approval for tool permission prompts.
- `/ping` command for a quick health check of the bot, session, and SDK RPC state.
- MCP (Model Context Protocol) server support — connect external tools via local subprocess or remote HTTP/SSE servers. Configured through `~/.copilot/mcp-config.json` or `MCP_CONFIG_PATH` env var. ([#17](https://github.com/julianchun/copilot-telegram-bot/pull/17))
- `on_event` parameter in `create_session()` for reliable early event delivery (e.g., `SESSION_START`)
- `skip_permission=True` on read-only custom tools (`list_files`, `read_file`)
- `session.set_model()` for model changes without losing conversation history
- System message `"customize"` mode with `tone` section override for Telegram-specific formatting

### Changed
- Migrated Plan/Edit/Autopilot mode switching to use the native SDK Mode API (`session.rpc.mode.set()`), cleanly separating modes from custom agents.
- Aligned skill discovery directories with official GitHub Copilot Agent paths.
- Upgraded `github-copilot-sdk` from v0.1.30 to v0.2.0
- `CopilotClient` constructor now uses `SubprocessConfig` dataclass
- `create_session()` / `resume_session()` use keyword arguments instead of config dict
- `send_and_wait()` takes positional `prompt` string instead of dict
- Mode state centralized in `service.current_mode` instead of scattered across handler `user_data`

### Removed
- Outdated custom agent "hack" for Plan/Edit modes.
- Placeholder `skills/` folder from the project root.
- Per-message prompt injection (`_MODE_INSTRUCTIONS` / `_PLAN_PROMPT` / `_GENERAL_PROMPT`)
- `_extract_session_start_context()` workaround — replaced by `on_event` handler
- Unused `GITHUB_TOKEN` import in session.py
- Dead `_event_unsubscribe` field — `on_event` handler lifecycle is managed by the SDK

## [0.3.0] - 2026-03-04

### Changed
- Upgraded `github-copilot-sdk` from v0.1.0 to v0.1.30
- Enhanced session management with improved event handling
- Updated README with SDK version badge

### Removed
- SUBMISSION.md (no longer needed)

## [0.2.0] - 2026-02-14

### Added
- Session usage tracking and per-model token/cost metrics (`/usage` command)
- Code review cleanups and bug fixes across the codebase

### Changed
- Refactored code structure into `src/core/`, `src/handlers/`, `src/ui/` layered architecture
- Updated prompts for clarity and consistency in response formatting
- Improved readability and maintainability across all modules

### Removed
- Obsolete `test_auth.py` file

## [0.1.0] - 2026-02-08

### Added
- Security checks with `ALLOWED_USER_ID` enforcement
- Project selection and workspace confinement (`WORKSPACE_ROOT`, `GRANTED_PROJECTS`)
- Utility functions for common handler patterns

### Changed
- Refactored architecture: extracted `CopilotService` from monolithic `main.py`
- Enhanced Copilot service integration with event-driven design

## [0.0.1] - 2026-02-03

### Added
- Initial release of copilot-telegram-bot
- Telegram bot with GitHub Copilot CLI integration
- Plan Mode and Edit Mode with prompt-based switching
- Interactive permissions via Telegram inline keyboards
- Multimodal vision support (image attachments)
- Mobile-first UX with inline keyboards for project switching and tool approval
- Developer HUD footer with model, mode, branch, and cost info
