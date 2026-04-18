"""Unit tests for /skills command (list, info, reload subcommands)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _service_patches(mock_service):
    """Return combined patches for service in commands and utils modules."""
    return (
        patch("src.handlers.commands.service", mock_service),
        patch("src.handlers.utils.service", mock_service),
        patch("src.handlers.utils.ALLOWED_USER_ID", 12345),
    )


SAMPLE_SKILLS = [
    {"name": "code-review", "description": "Performs thorough code reviews", "enabled": True, "source": "project", "path": None},
    {"name": "greeting", "description": "Generates personalized greetings", "enabled": True, "source": "plugin", "path": None},
    {"name": "experimental", "description": "Experimental feature", "enabled": False, "source": "project", "path": None},
]


# ---------------------------------------------------------------------------
# /skills list (default)
# ---------------------------------------------------------------------------

class TestSkillsList:
    async def test_list_skills(self, mock_update, mock_context, mock_service):
        """Skills are listed grouped by source."""
        mock_service.project_selected = True
        mock_service.list_skills = AsyncMock(return_value=SAMPLE_SKILLS)
        mock_context.args = []

        sent_msg = MagicMock()
        sent_msg.edit_text = AsyncMock()
        mock_update.message.reply_text = AsyncMock(return_value=sent_msg)

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2]:
            from src.handlers.commands import skills_command
            await skills_command(mock_update, mock_context)

        text = sent_msg.edit_text.call_args[0][0]
        assert "Available Skills" in text
        assert "code-review" in text
        assert "greeting" in text
        assert "3 skills found" in text
        assert "/skills info" in text

    async def test_list_explicit(self, mock_update, mock_context, mock_service):
        """Explicit /skills list subcommand works."""
        mock_service.project_selected = True
        mock_service.list_skills = AsyncMock(return_value=SAMPLE_SKILLS)
        mock_context.args = ["list"]

        sent_msg = MagicMock()
        sent_msg.edit_text = AsyncMock()
        mock_update.message.reply_text = AsyncMock(return_value=sent_msg)

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2]:
            from src.handlers.commands import skills_command
            await skills_command(mock_update, mock_context)

        text = sent_msg.edit_text.call_args[0][0]
        assert "Available Skills" in text

    async def test_no_skills(self, mock_update, mock_context, mock_service):
        """Empty skill list shows 'No skills found'."""
        mock_service.project_selected = True
        mock_service.list_skills = AsyncMock(return_value=[])
        mock_context.args = []

        sent_msg = MagicMock()
        sent_msg.edit_text = AsyncMock()
        mock_update.message.reply_text = AsyncMock(return_value=sent_msg)

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2]:
            from src.handlers.commands import skills_command
            await skills_command(mock_update, mock_context)

        text = sent_msg.edit_text.call_args[0][0]
        assert "No skills found" in text

    async def test_requires_project(self, mock_update, mock_context, mock_service):
        """Skills command requires project selection."""
        mock_service.project_selected = False
        mock_context.args = []

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2]:
            from src.handlers.commands import skills_command
            await skills_command(mock_update, mock_context)

        calls = mock_update.message.reply_text.call_args_list
        assert len(calls) == 1
        assert "project" in calls[0][0][0].lower() or "select" in calls[0][0][0].lower()


# ---------------------------------------------------------------------------
# /skills info <name>
# ---------------------------------------------------------------------------

class TestSkillsInfo:
    async def test_info_found(self, mock_update, mock_context, mock_service, tmp_path):
        """Info shows skill details in card style when found."""
        skill_dir = tmp_path / "code-review"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("---\nname: code-review\n---\n\n# Code Review\n\nDoes reviews.")
        skills_with_path = [
            {**SAMPLE_SKILLS[0], "path": str(skill_file)},
            SAMPLE_SKILLS[1],
        ]
        mock_service.project_selected = True
        mock_service.list_skills = AsyncMock(return_value=skills_with_path)
        mock_context.args = ["info", "code-review"]

        sent_msg = MagicMock()
        sent_msg.edit_text = AsyncMock()
        mock_update.message.reply_text = AsyncMock(return_value=sent_msg)

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2]:
            from src.handlers.commands import skills_command
            await skills_command(mock_update, mock_context)

        text = sent_msg.edit_text.call_args[0][0]
        assert "🧩 code-review" in text
        assert "━━━" in text
        assert "📂 Source: Project" in text
        assert "✅ Enabled" in text
        assert "Code Review" in text
        assert "Does reviews." in text

    async def test_info_not_found(self, mock_update, mock_context, mock_service):
        """Info shows error when skill name doesn't match."""
        mock_service.project_selected = True
        mock_service.list_skills = AsyncMock(return_value=SAMPLE_SKILLS)
        mock_context.args = ["info", "nonexistent"]

        sent_msg = MagicMock()
        sent_msg.edit_text = AsyncMock()
        mock_update.message.reply_text = AsyncMock(return_value=sent_msg)

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2]:
            from src.handlers.commands import skills_command
            await skills_command(mock_update, mock_context)

        text = sent_msg.edit_text.call_args[0][0]
        assert "not found" in text

    async def test_info_missing_name(self, mock_update, mock_context, mock_service):
        """Info without skill name shows usage."""
        mock_service.project_selected = True
        mock_context.args = ["info"]

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2]:
            from src.handlers.commands import skills_command
            await skills_command(mock_update, mock_context)

        text = mock_update.message.reply_text.call_args[0][0]
        assert "Usage" in text


# ---------------------------------------------------------------------------
# /skills reload
# ---------------------------------------------------------------------------

class TestSkillsReload:
    async def test_reload_success(self, mock_update, mock_context, mock_service):
        """Reload shows refreshed skill list."""
        mock_service.project_selected = True
        mock_service.reload_skills = AsyncMock(return_value=True)
        mock_service.list_skills = AsyncMock(return_value=SAMPLE_SKILLS)
        mock_context.args = ["reload"]

        sent_msg = MagicMock()
        sent_msg.edit_text = AsyncMock()
        mock_update.message.reply_text = AsyncMock(return_value=sent_msg)

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2]:
            from src.handlers.commands import skills_command
            await skills_command(mock_update, mock_context)

        mock_service.reload_skills.assert_awaited_once()
        text = sent_msg.edit_text.call_args[0][0]
        assert "reloaded" in text

    async def test_reload_failure(self, mock_update, mock_context, mock_service):
        """Reload failure shows error."""
        mock_service.project_selected = True
        mock_service.reload_skills = AsyncMock(return_value=False)
        mock_context.args = ["reload"]

        sent_msg = MagicMock()
        sent_msg.edit_text = AsyncMock()
        mock_update.message.reply_text = AsyncMock(return_value=sent_msg)

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2]:
            from src.handlers.commands import skills_command
            await skills_command(mock_update, mock_context)

        text = sent_msg.edit_text.call_args[0][0]
        assert "Failed" in text


# ---------------------------------------------------------------------------
# UI formatting
# ---------------------------------------------------------------------------

class TestSkillUI:
    def test_format_skill_list_grouped(self):
        from src.ui.menus import format_skill_list
        text = format_skill_list(SAMPLE_SKILLS)
        assert "Available Skills" in text
        assert "📂 Project" in text
        assert "📦 Built-in" in text
        assert "┌ code-review" in text
        assert "┌ greeting" in text
        assert "3 skills found" in text
        assert "/skills info" in text

    def test_format_skill_list_empty(self):
        from src.ui.menus import format_skill_list
        text = format_skill_list([])
        assert "No skills found" in text

    def test_format_single_skill(self):
        from src.ui.menus import format_skill_list
        text = format_skill_list([SAMPLE_SKILLS[0]])
        assert "1 skill found." in text

    def test_format_truncates_long_description(self):
        from src.ui.menus import format_skill_list
        long_desc = "A" * 200
        skills = [{"name": "test", "description": long_desc, "enabled": True, "source": "project", "path": None}]
        text = format_skill_list(skills)
        assert "..." in text


# ---------------------------------------------------------------------------
# Unknown subcommand
# ---------------------------------------------------------------------------

class TestSkillsUnknown:
    async def test_unknown_subcommand(self, mock_update, mock_context, mock_service):
        """Unknown subcommand shows usage."""
        mock_service.project_selected = True
        mock_context.args = ["bogus"]

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2]:
            from src.handlers.commands import skills_command
            await skills_command(mock_update, mock_context)

        text = mock_update.message.reply_text.call_args[0][0]
        assert "Unknown subcommand" in text
