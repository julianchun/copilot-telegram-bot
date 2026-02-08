"""
Session Export to Markdown

Formats SDK session events into copilot-cli compatible markdown format.
"""

import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from copilot.generated.session_events import SessionEvent, SessionEventType

logger = logging.getLogger(__name__)


def format_session_markdown(events: List[SessionEvent], metadata: Dict[str, Any]) -> str:
    """
    Format session events into copilot-cli markdown format.
    
    Args:
        events: List of SessionEvent objects from session.get_messages()
        metadata: Dict with session_id, start_time, project_name, current_model
        
    Returns:
        Markdown formatted session export string
    """
    if not events:
        return "# 🤖 Copilot CLI Session\n\n> **No session history**\n"
    
    session_id = metadata.get("session_id", "unknown")
    start_time = metadata.get("start_time")
    project_name = metadata.get("project_name", "Unknown")
    
    # Filter out ephemeral events and internal events that shouldn't be displayed
    DISPLAYABLE_EVENTS = {
        SessionEventType.SESSION_START,
        SessionEventType.USER_MESSAGE,
        SessionEventType.ASSISTANT_MESSAGE,
        SessionEventType.TOOL_EXECUTION_START,
        SessionEventType.TOOL_EXECUTION_COMPLETE,
        SessionEventType.SUBAGENT_STARTED,
        SessionEventType.SUBAGENT_COMPLETED,
        SessionEventType.SESSION_MODEL_CHANGE,
        SessionEventType.SESSION_INFO,
    }
    
    # Filter events: skip ephemeral and non-displayable types
    filtered_events = []
    last_model = None
    for event in events:
        # Skip ephemeral events
        if getattr(event, 'ephemeral', False):
            continue
        
        # Only include displayable event types
        if event.type not in DISPLAYABLE_EVENTS:
            # Special case: track model changes from ASSISTANT_USAGE events
            if event.type == SessionEventType.ASSISTANT_USAGE:
                model = getattr(event.data, 'model', None)
                if model and model != last_model:
                    last_model = model
                    # Create synthetic model change event
                    filtered_events.append(('model_change', event, model))
            continue
        
        filtered_events.append(('event', event, None))
    
    # Calculate session duration from first to last event
    if filtered_events:
        first_timestamp = filtered_events[0][1].timestamp
        last_timestamp = filtered_events[-1][1].timestamp
        duration_delta = last_timestamp - first_timestamp
        duration_minutes = int(duration_delta.total_seconds() / 60)
        duration_seconds = int(duration_delta.total_seconds() % 60)
        duration_str = f"{duration_minutes}m {duration_seconds}s"
    else:
        duration_str = "0m 0s"
    
    # Format timestamps
    started_str = start_time.strftime("%m/%d/%Y, %I:%M:%S %p") if start_time else "Unknown"
    exported_str = datetime.now().strftime("%m/%d/%Y, %I:%M:%S %p")
    
    # Build markdown
    lines = [
        "# 🤖 Copilot CLI Session",
        "",
        f"> **Session ID:** `{session_id}`",
        f"> **Started:** {started_str}",
        f"> **Duration:** {duration_str}",
        f"> **Exported:** {exported_str}",
        ""
    ]
    
    # Track session start time for relative timeline
    session_start = filtered_events[0][1].timestamp if filtered_events else datetime.now()
    
    # Process each filtered event
    for entry_type, event, extra_data in filtered_events:
        # Calculate relative time from session start
        time_delta = event.timestamp - session_start
        total_seconds = int(time_delta.total_seconds())
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        timeline = f"<sub>⏱️ {minutes}m {seconds}s</sub>" if minutes > 0 or seconds > 0 else "<sub>⏱️ 0s</sub>"
        
        lines.append(timeline)
        lines.append("")
        
        # Handle synthetic model change events
        if entry_type == 'model_change':
            lines.append("### ℹ️ Info")
            lines.append("")
            lines.append(f"Model changed to: {extra_data}")
            lines.append("")
            lines.append("---")
            lines.append("")
            continue
        
        # Format based on event type
        if event.type == SessionEventType.SESSION_START:
            lines.append("### ℹ️ Info")
            lines.append("")
            model = getattr(event.data, 'selected_model', None) or metadata.get('current_model', 'Auto')
            lines.append(f"Session started with model: {model}")
            
        elif event.type == SessionEventType.USER_MESSAGE:
            lines.append("### 👤 User")
            lines.append("")
            content = getattr(event.data, 'content', '') or getattr(event.data, 'prompt', '')
            lines.append(content)
            
        elif event.type == SessionEventType.ASSISTANT_MESSAGE:
            lines.append("### 💬 Copilot")
            lines.append("")
            content = getattr(event.data, 'content', '')
            if content:
                lines.append(content)
            else:
                lines.append("_(No response)_")
                
        elif event.type == SessionEventType.TOOL_EXECUTION_START:
            tool_name = getattr(event.data, 'tool_name', None) or getattr(event.data, 'mcp_tool_name', 'unknown')
            lines.append(f"### ✅ `{tool_name}`")
            lines.append("")
            
            # Add arguments in collapsible details
            args = getattr(event.data, 'arguments', None)
            if args:
                lines.append("<details>")
                lines.append("<summary>Arguments</summary>")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(args, indent=2))
                lines.append("```")
                lines.append("")
                lines.append("</details>")
                lines.append("")
                
        elif event.type == SessionEventType.TOOL_EXECUTION_COMPLETE:
            # Show tool result
            result = getattr(event.data, 'result', None)
            if result:
                result_content = getattr(result, 'content', None)
                if result_content:
                    # Count lines in result
                    result_lines = result_content.count('\n') + 1
                    
                    lines.append("<details>")
                    lines.append(f"<summary>{result_lines} lines</summary>")
                    lines.append("")
                    lines.append("```")
                    # Truncate very long results
                    if len(result_content) > 50000:
                        lines.append(result_content[:50000])
                        lines.append(f"\n... (truncated {len(result_content) - 50000} characters)")
                    else:
                        lines.append(result_content)
                    lines.append("```")
                    lines.append("")
                    lines.append("</details>")
                    lines.append("")
                    
        elif event.type == SessionEventType.SUBAGENT_STARTED:
            agent_name = getattr(event.data, 'agent_display_name', None) or getattr(event.data, 'agent_name', 'Agent')
            lines.append("### ℹ️ Info")
            lines.append("")
            lines.append(f"🤖 {agent_name} started")
            
        elif event.type == SessionEventType.SUBAGENT_COMPLETED:
            agent_name = getattr(event.data, 'agent_display_name', None) or getattr(event.data, 'agent_name', 'Agent')
            lines.append("### ℹ️ Info")
            lines.append("")
            lines.append(f"✓ {agent_name} completed")
            
        elif event.type == SessionEventType.SESSION_MODEL_CHANGE:
            # Explicit model change event
            model = getattr(event.data, 'model', None)
            if model:
                lines.append("### ℹ️ Info")
                lines.append("")
                lines.append(f"Model changed to: {model}")
        
        elif event.type == SessionEventType.SESSION_INFO:
            # Generic session info messages
            info_message = getattr(event.data, 'message', None) or getattr(event.data, 'content', '')
            if info_message:
                lines.append("### ℹ️ Info")
                lines.append("")
                lines.append(info_message)
        
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # Add footer
    lines.append("")
    lines.append("<sub>Generated by [GitHub Copilot CLI Telegram Bot](https://github.com/julianchun/copilot-cli-telegram-bot)</sub>")
    lines.append("")
    
    return "\n".join(lines)
