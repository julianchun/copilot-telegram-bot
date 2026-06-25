# Copilot SDK v1 Upgrade Background

Date: 2026-06-06

This note captures the upgrade decisions from the Copilot SDK v1 discussion. It is the working background for the implementation pass, not the final changelog.

## Context

- The app currently targets `github-copilot-sdk==0.3.0`.
- The target upgrade is the published package `github-copilot-sdk==1.0.0`.
- The latest SDK source is already available in `.docs/copilot-sdk` and was used as the reference source for the migration survey.
- The SDK reference checkout is tag `v1.0.0`, commit `c8f1b338`.

## Upgrade Goals

- Cut directly to SDK `1.0.0`.
- Update `uv.lock` in the same implementation pass.
- Make the required migration changes plus two targeted v1 improvements:
  - v1-native exit plan pending request resolution.
  - v1 metadata naming fixes for resume/session display.
- Write code and tests first; update README and CHANGELOG only after tests pass.
- Keep the upgrade focused. Prefer v1 practice where it is required or low-risk, and defer high-impact extras with notes.

## Required API Migration

- Replace the old `CopilotClient(SubprocessConfig(...))` construction with the v1 client shape:
  - `CopilotClient(working_directory=..., github_token=..., connection=RuntimeConnection.for_stdio(...))`
- Replace session `get_messages()` calls with v1 `get_events()`.
- Normalize v1 session metadata at the core boundary:
  - v1 fields include `context.working_directory`, `git_root`, `start_time`, and `modified_time`.
  - Existing UI helpers should keep fallback reads for old field names so display code remains tolerant.
- Normalize MCP server config from old `cwd` to v1 `working_directory` defensively.
- Keep import churn minimal:
  - Use public v1 imports for new or touched v1 code.
  - Do not rewrite every existing import only for style.

## Permission Plan

- Migrate from the old `on_pre_tool_use` hook bridge to direct v1 `on_permission_request`.
- Remove the old hook permission approval path; do not keep a compatibility fallback.
- Split the old permission bridge into clearer v1 helpers:
  - `_permission_request_bridge(request, invocation)` for direct SDK permission handling.
  - `_describe_permission_request(request)` for Telegram-facing request summaries.
- Follow v1 permission request types instead of legacy tool-name allowlist semantics.
- Auto-approve low-risk read-only permission requests.
- Ask the user in Telegram for unsafe or side-effecting requests.
- Keep `/allowall` behavior the same as today:
  - When enabled, auto-approve each SDK permission request once.
  - Use `PermissionDecisionApproveOnce()`.
  - Do not introduce persistent or session-scoped approval behavior in this pass.
- "Allow" in Telegram means approve once only.
- "Deny" in Telegram returns `PermissionDecisionReject(feedback="Denied by user.")`.
- Timeout, missing callback, or unavailable Telegram UI returns `PermissionDecisionUserNotAvailable()`.
- Unsafe fallback should be deny/user-unavailable, not approve.
- URL permission requests should always ask Telegram.
- Keep `ask_user` in `on_user_input_request`; do not move it into permission allowlist behavior.

## Exit Plan Mode Plan

- Keep the current event-driven Telegram UX for `EXIT_PLAN_MODE_REQUESTED`.
- Resolve the SDK pending request through v1 pending RPC:
  - `session.rpc.ui.handle_pending_exit_plan_mode(...)`
- Button mapping:
  - Approve: `approved=True`, `selectedAction=recommendedAction` when present, else use `autopilot` or the first SDK action.
  - Reject: `approved=False`, feedback `Plan rejected by user.`
  - Edit: `approved=False`, feedback `User wants to revise the plan.`
- Keep the existing follow-up UX where the next Telegram message can provide revision feedback.
- Do not migrate to direct `on_exit_plan_mode_request` in this pass.

## Deferred Items

- `/model` should keep current model and `reasoning_effort` behavior.
- Defer `reasoning_summary` and `context_tier`; note the deferral in docs or changelog.
- Defer v1 `large_output`.
- Keep downloaded temporary file attachments; defer blob attachment migration.
- Defer richer permission approval scopes, such as session/location approvals.
- Defer broad import cleanup.
- Defer unrelated v1 surfaces unless required by the migration, such as cloud, remote, MCP apps, plugin directories, or canvas-like features.

## Test And Verification Plan

- Run dependency sync:
  - `uv sync --extra test`
- Smoke-test the upgraded import path:
  - `uv run python -c "import src.core.service"`
- Run focused tests around:
  - SDK client construction.
  - Permission request handling.
  - Exit plan pending RPC resolution.
  - Session metadata normalization and UI fallback display.
  - MCP `cwd` to `working_directory` normalization.
- Run the full test suite if it is reasonable for the environment:
  - `uv run python -m pytest tests/ -v`

## Non-goals

- No 0.3 compatibility shim unless a tiny fallback is needed for harmless display tolerance.
- No staging or committing unless explicitly requested after reviewing the diff.
- No broad UX redesign.
- No attachment storage behavior change for downloaded temp files.

## Implementation Checklist

- Bump `github-copilot-sdk` to `1.0.0`.
- Update `uv.lock`.
- Migrate client construction and runtime connection setup.
- Replace `get_messages()` with `get_events()`.
- Add metadata normalization at the boundary and retain UI fallback reads.
- Normalize MCP `cwd` to `working_directory`.
- Replace hook-based permission handling with direct v1 permission requests.
- Preserve `/allowall` as approve-once auto-approval.
- Wire exit plan buttons to pending RPC resolution.
- Rewrite permission tests around v1 request and decision classes.
- Add or update tests for exit plan, metadata, and MCP normalization.
- Run verification commands before README/CHANGELOG updates.
