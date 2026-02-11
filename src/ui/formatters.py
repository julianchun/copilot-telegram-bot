import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def format_tool_start(tool_name: str, arguments: dict) -> str:
    """Format tool start message with tool-specific argument display."""
    if not arguments:
        return f"🔧 {tool_name}"
    
    # Tool-specific formatting
    if tool_name == "report_intent":
        intent = arguments.get('intent', '')
        return f"🔧 report_intent - {intent}"
    
    elif tool_name == "task":
        description = arguments.get('description', '')
        return f"🔧 task - {description}" if description else "🔧 task"
    
    elif tool_name == "update_todo":
        todos = arguments.get('todos', '')
        if todos:
            # Parse todos and format with emojis
            lines = todos.strip().split('\n')
            formatted_lines = []
            for line in lines:
                line = line.strip()
                if line.startswith('- [x]'):
                    # Completed task
                    task = line[5:].strip()
                    formatted_lines.append(f"✅ {task}")
                elif line.startswith('- [ ]'):
                    # Incomplete task
                    task = line[5:].strip()
                    formatted_lines.append(f"☐ {task}")
                elif line:
                    # Other format, keep as-is
                    formatted_lines.append(line)
            
            todo_list = '\n'.join(formatted_lines)
            return f"🔧 update_todo\n\n{todo_list}"
        return "🔧 update_todo"
    
    elif tool_name == "bash":
        description = arguments.get('description', '')
        command = arguments.get('command', '')
        
        if not command:
            return f"🔧 bash - {description}" if description else "🔧 bash"
        
        truncated_cmd = truncate_command(command)
        
        if description:
            return f"🔧 bash - {description}\n    {truncated_cmd}"
        else:
            return f"🔧 bash\n    {truncated_cmd}"
    
    elif tool_name in ["view", "list_files", "read_file"]:
        path = arguments.get('path', arguments.get('file', ''))
        # Extract filename/folder from path for readability
        try:
            display_name = Path(path).name if path else path
        except Exception:
            display_name = path
        return f"🔧 {tool_name} - {display_name}"
    
    elif tool_name == "create":
        path = arguments.get('path', '')
        file_text = arguments.get('file_text', '')
        
        # Extract filename
        try:
            filename = Path(path).name if path else 'file'
        except Exception:
            filename = 'file'
        
        # Show file content preview if available
        if file_text:
            preview = truncate_text(file_text, max_length=200)
            return f"🔧 create - {filename}\n    Preview: {preview}"
        else:
            return f"🔧 create - {filename}"
    
    elif tool_name in ["edit", "grep"]:
        path = arguments.get('path', arguments.get('pattern', ''))
        if path:
            try:
                display_name = Path(path).name if '/' in path else path
            except Exception:
                display_name = path
            return f"🔧 {tool_name} - {display_name}"
        return f"🔧 {tool_name}"
    
    # Default: just tool name (don't show raw args)
    return f"🔧 {tool_name}"


def format_tool_complete(tool_name: str, result_content: Optional[str], success: bool = True) -> str:
    """Format tool completion message with optional result summary."""
    if not success:
        return f"❌ {tool_name}"
    
    # Skip unknown tool names (SDK doesn't always provide tool name in complete event)
    if tool_name == "unknown":
        return ""
    
    # Don't show result for tools that don't produce meaningful output
    silent_tools = ["report_intent", "bash", "create", "task", "update_todo"]
    
    # Filter out non-meaningful results
    if not result_content:
        return ""  # Don't send completion message
    
    # Skip if result is "None" string or just exit code info
    result_lower = result_content.lower().strip()
    if result_lower == "none" or result_lower.startswith("<exited with"):
        return ""  # Don't send completion message
    
    # Don't show completion for silent tools
    if tool_name in silent_tools:
        return ""  # Don't send completion message
    
    # Show truncated result for meaningful tools
    truncated = truncate_text(result_content, max_length=100)
    return f"✓ {tool_name} → {truncated}"


def truncate_command(cmd: str, max_lines: int = 4, max_chars: int = 250) -> str:
    """Truncate long bash commands intelligently, especially heredocs."""
    # Check for heredoc pattern
    heredoc_match = re.search(r"<<\s*['\"]?(\w+)['\"]?", cmd)
    
    if heredoc_match:
        # Split at heredoc start
        parts = cmd.split(heredoc_match.group(0), 1)
        prefix = parts[0].strip()
        heredoc_content = parts[1] if len(parts) > 1 else ""
        
        # Get first few lines of heredoc
        lines = heredoc_content.split('\n')
        total_lines = len([l for l in lines if l.strip()])  # Count non-empty lines
        
        # Build result
        result = f"$ {prefix} << '{heredoc_match.group(1)}'\n"
        
        # Show first 2-3 lines of content
        content_lines = []
        for line in lines[:3]:
            if line.strip():  # Skip empty lines at start
                content_lines.append(line)
            if len(content_lines) >= 2:
                break
        
        result += '\n'.join(content_lines)
        
        if total_lines > 2:
            result += f"\n└ {total_lines - len(content_lines)} more lines..."
        
        return result
    
    # Non-heredoc: truncate long commands
    if len(cmd) <= max_chars:
        return f"$ {cmd}"
    
    # Multi-line command
    lines = cmd.split('\n')
    if len(lines) > max_lines:
        result = '\n'.join(lines[:max_lines])
        result += f"\n└ {len(lines) - max_lines} more lines..."
        return f"$ {result}"
    
    # Single long line - just truncate
    return f"$ {cmd[:max_chars]}..."


def truncate_text(text: str, max_length: int = 150) -> str:
    """Truncate text with ellipsis, cleaning up whitespace."""
    if not text:
        return ""
    
    # Replace multiple newlines/spaces with single space
    cleaned = re.sub(r'\s+', ' ', text.strip())
    
    if len(cleaned) <= max_length:
        return cleaned
    
    return cleaned[:max_length] + "..."


# ── Helpers relocated from handlers/commands.py ──────────────────────────────

def escape_md_v1(text: str) -> str:
    """Escape Markdown V1 special characters for Telegram."""
    for char in ['_', '*', '[', ']', '(', ')', '~', '`']:
        text = text.replace(char, '\\' + char)
    return text


def format_tokens(n: int) -> str:
    """Format token count for display (e.g., 12500 → '12.5k')."""
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def format_percentage(used: int, limit: int) -> str:
    """Calculate and format percentage."""
    if limit == 0:
        return "0%"
    pct = (used / limit) * 100
    return f"{pct:.0f}%"


def get_model_context_limit(model_name: str) -> int:
    """Lookup context window size for a model via service's SDK-cached data."""
    from src.core.service import service
    return service.get_model_context_limit(model_name)
