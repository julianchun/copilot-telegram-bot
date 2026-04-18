"""Unit tests for /skill command and skill callback handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _service_patches(mock_service):
    """Return combined patches for service in commands, callbacks, and utils modules."""
    return (
        patch("src.handlers.commands.service", mock_service),
        patch("src.handlers.callbacks.service", mock_service),
        patch("src.handlers.utils.service", mock_service),
        patch("src.handlers.utils.ALLOWED_USER_ID", 12345),
    )


SAMPLE_SKILLS = [
    {"name": "code-review", "description": "Performs thorough code reviews", "enabled": True, "source": "project"},
    {"name": "greeting", "description": "Generates personalized greetings", "enabled": True, "source": "project"},
    {"name": "experimental", "description": "Experimental feature", "enabled": False, "source": "project"},
]


# ---------------------------------------------------------------------------
# /skill command
# ---------------------------------------------------------------------------

class TestSkillCommand:
    async def test_list_skills(self, mock_update, mock_context, mock_service):
        """Skills are listed with toggle keyboard when skills exist."""
        mock_service.project_selected = True
        mock_service.list_skills = AsyncMock(return_value=SAMPLE_SKILLS)

        # reply_text returns a message object we can call edit_text on
        sent_msg = MagicMock()
        sent_msg.edit_text = AsyncMock()
        mock_update.message.reply_text = AsyncMock(return_value=sent_msg)

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import skill_command
            await skill_command(mock_update, mock_context)

        # Should have sent a loading message then edited it
        mock_update.message.reply_text.assert_called_once_with("🔄 Fetching skills...")
        sent_msg.edit_text.assert_called_once()
        call_kwargs = sent_msg.edit_text.call_args
        text = call_kwargs[0][0]
        assert "3 available" in text
        assert "code-review" in text
        assert "greeting" in text
        assert "✅" in text
        assert "❌" in text
        # Should have a keyboard
        assert "reply_markup" in call_kwargs[1]

    async def test_no_skills(self, mock_update, mock_context, mock_service):
        """Empty skill list shows guidance message without keyboard."""
        mock_service.project_selected = True
        mock_service.list_skills = AsyncMock(return_value=[])

        sent_msg = MagicMock()
        sent_msg.edit_text = AsyncMock()
        mock_update.message.reply_text = AsyncMock(return_value=sent_msg)

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import skill_command
            await skill_command(mock_update, mock_context)

        call_kwargs = sent_msg.edit_text.call_args
        text = call_kwargs[0][0]
        assert "No skills found" in text
        # No reply_markup keyword (no keyboard)
        assert call_kwargs[1] is None or "reply_markup" not in (call_kwargs[1] or {})

    async def test_requires_project(self, mock_update, mock_context, mock_service):
        """Skill command requires project selection."""
        mock_service.project_selected = False

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.commands import skill_command
            await skill_command(mock_update, mock_context)

        calls = mock_update.message.reply_text.call_args_list
        assert len(calls) == 1
        assert "project" in calls[0][0][0].lower() or "select" in calls[0][0][0].lower()


# ---------------------------------------------------------------------------
# skill: callback (toggle)
# ---------------------------------------------------------------------------

class TestSkillCallback:
    async def test_toggle_disable(self, mock_update, mock_callback_query, mock_context, mock_service):
        """Tapping an enabled skill disables it."""
        mock_callback_query.data = "skill:code-review"
        mock_update.callback_query = mock_callback_query

        # First list call returns skill as enabled, second call after toggle returns disabled
        mock_service.list_skills = AsyncMock(side_effect=[
            SAMPLE_SKILLS,
            [
                {"name": "code-review", "description": "Performs thorough code reviews", "enabled": False, "source": "project"},
                {"name": "greeting", "description": "Generates personalized greetings", "enabled": True, "source": "project"},
                {"name": "experimental", "description": "Experimental feature", "enabled": False, "source": "project"},
            ],
        ])
        mock_service.toggle_skill = AsyncMock(return_value=True)

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.callbacks import _handle_skill_callback
            await _handle_skill_callback(mock_callback_query, mock_context)

        # Should toggle with enable=False (it was enabled)
        mock_service.toggle_skill.assert_awaited_once_with("code-review", enable=False)
        # Should refresh the message
        mock_callback_query.edit_message_text.assert_called_once()

    async def test_toggle_enable(self, mock_update, mock_callback_query, mock_context, mock_service):
        """Tapping a disabled skill enables it."""
        mock_callback_query.data = "skill:experimental"
        mock_update.callback_query = mock_callback_query

        mock_service.list_skills = AsyncMock(side_effect=[
            SAMPLE_SKILLS,
            [
                {"name": "code-review", "description": "Performs thorough code reviews", "enabled": True, "source": "project"},
                {"name": "greeting", "description": "Generates personalized greetings", "enabled": True, "source": "project"},
                {"name": "experimental", "description": "Experimental feature", "enabled": True, "source": "project"},
            ],
        ])
        mock_service.toggle_skill = AsyncMock(return_value=True)

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.callbacks import _handle_skill_callback
            await _handle_skill_callback(mock_callback_query, mock_context)

        mock_service.toggle_skill.assert_awaited_once_with("experimental", enable=True)
        mock_callback_query.edit_message_text.assert_called_once()

    async def test_toggle_unknown_skill(self, mock_update, mock_callback_query, mock_context, mock_service):
        """Unknown skill name shows error."""
        mock_callback_query.data = "skill:nonexistent"
        mock_update.callback_query = mock_callback_query

        mock_service.list_skills = AsyncMock(return_value=SAMPLE_SKILLS)

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.callbacks import _handle_skill_callback
            await _handle_skill_callback(mock_callback_query, mock_context)

        text = mock_callback_query.edit_message_text.call_args[0][0]
        assert "not found" in text

    async def test_toggle_failure(self, mock_update, mock_callback_query, mock_context, mock_service):
        """Toggle returning False shows error."""
        mock_callback_query.data = "skill:code-review"
        mock_update.callback_query = mock_callback_query

        mock_service.list_skills = AsyncMock(return_value=SAMPLE_SKILLS)
        mock_service.toggle_skill = AsyncMock(return_value=False)

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.callbacks import _handle_skill_callback
            await _handle_skill_callback(mock_callback_query, mock_context)

        text = mock_callback_query.edit_message_text.call_args[0][0]
        assert "Failed" in text


# ---------------------------------------------------------------------------
# skill_reload callback
# ---------------------------------------------------------------------------

class TestSkillReloadCallback:
    async def test_reload_with_skills(self, mock_update, mock_callback_query, mock_context, mock_service):
        """Reload refreshes the skill list and updates message."""
        mock_callback_query.data = "skill_reload"
        mock_update.callback_query = mock_callback_query

        mock_service.reload_skills = AsyncMock(return_value=True)
        mock_service.list_skills = AsyncMock(return_value=SAMPLE_SKILLS)

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.callbacks import _handle_skill_reload_callback
            await _handle_skill_reload_callback(mock_callback_query, mock_context)

        mock_service.reload_skills.assert_awaited_once()
        mock_callback_query.edit_message_text.assert_called_once()
        call_kwargs = mock_callback_query.edit_message_text.call_args
        assert "reply_markup" in call_kwargs[1]

    async def test_reload_empty(self, mock_update, mock_callback_query, mock_context, mock_service):
        """Reload with no skills shows guidance message."""
        mock_callback_query.data = "skill_reload"
        mock_update.callback_query = mock_callback_query

        mock_service.reload_skills = AsyncMock(return_value=True)
        mock_service.list_skills = AsyncMock(return_value=[])

        with _service_patches(mock_service)[0], \
             _service_patches(mock_service)[1], \
             _service_patches(mock_service)[2], \
             _service_patches(mock_service)[3]:
            from src.handlers.callbacks import _handle_skill_reload_callback
            await _handle_skill_reload_callback(mock_callback_query, mock_context)

        text = mock_callback_query.edit_message_text.call_args[0][0]
        assert "No skills found" in text


# ---------------------------------------------------------------------------
# UI formatting
# ---------------------------------------------------------------------------

class TestSkillUI:
    def test_format_skill_list_with_skills(self):
        from src.ui.menus import format_skill_list
        text = format_skill_list(SAMPLE_SKILLS)
        assert "3 available" in text
        assert "✅ code-review — Performs thorough code reviews" in text
        assert "❌ experimental — Experimental feature" in text
        assert "Tap a skill" in text

    def test_format_skill_list_empty(self):
        from src.ui.menus import format_skill_list
        text = format_skill_list([])
        assert "No skills found" in text

    def test_get_skill_keyboard(self):
        from src.ui.menus import get_skill_keyboard
        keyboard = get_skill_keyboard(SAMPLE_SKILLS)
        # Flatten all buttons
        all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        names = [btn.callback_data for btn in all_buttons]
        assert "skill:code-review" in names
        assert "skill:greeting" in names
        assert "skill:experimental" in names
        assert "skill_reload" in names
        # Check icons
        labels = [btn.text for btn in all_buttons]
        assert any("✅" in l and "code-review" in l for l in labels)
        assert any("❌" in l and "experimental" in l for l in labels)
