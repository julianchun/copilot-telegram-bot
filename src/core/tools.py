import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from copilot.tools import define_tool
from src.core.context import ctx
from src.config import FILE_CONTENT_LIMIT

logger = logging.getLogger(__name__)

# --- Tool Definitions ---

class ListFilesParams(BaseModel):
    path: str = Field(description="The directory path to list files from. Defaults to current directory ('.').")

@define_tool(description="List files and directories in the project.")
async def list_files(params: ListFilesParams) -> str:
    target_path = Path(params.path)
    root = ctx.root_path
    
    if target_path.is_absolute():
        abs_target = target_path.resolve()
    else:
        abs_target = (root / target_path).resolve()
    
    # Security Check: Ensure path is within root (using Path.relative_to for robustness)
    try:
        abs_target.relative_to(root)
    except ValueError:
        return "Error: Access denied. Cannot access files outside workspace."
    
    try:
        items = os.listdir(abs_target)
        # Removed ctx.report_status() - SDK handles this via TOOL_EXECUTION_COMPLETE
        
        formatted_items = []
        for item in items:
            if (abs_target / item).is_dir():
                formatted_items.append(f"{item}/")
            else:
                formatted_items.append(item)
        return "\n".join(sorted(formatted_items))
    except Exception as e:
        return f"Error listing files: {str(e)}"

class ReadFileParams(BaseModel):
    path: str = Field(description="The relative path of the file to read.")

@define_tool(description="Read the content of a file.")
async def read_file(params: ReadFileParams) -> str:
    target_path = Path(params.path)
    root = ctx.root_path
    
    if target_path.is_absolute():
        abs_target = target_path.resolve()
    else:
        abs_target = (root / target_path).resolve()
    
    # Security Check: Ensure path is within root (using Path.relative_to for robustness)
    try:
        abs_target.relative_to(root)
    except ValueError:
        return "Error: Access denied. Cannot read files outside workspace."
        
    try:
        if not abs_target.exists():
            return f"Error: File not found: {params.path}"

        with open(abs_target, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            content = "".join(lines)
            
            # Removed ctx.report_status() - SDK handles this via TOOL_EXECUTION_COMPLETE
            ctx.track_file(params.path)
            
            if len(content) > FILE_CONTENT_LIMIT:
                return content[:FILE_CONTENT_LIMIT] + "\n... (File truncated)"
            return content
    except UnicodeDecodeError:
        return "Error: Binary or unsupported file encoding."
    except Exception as e:
        return f"Error reading file: {str(e)}"
