"""Unit tests for numbered agent selection menus in src/ui/menus.py."""

from unittest.mock import MagicMock

from src.ui.menus import get_agent_keyboard, get_agent_menu


def _make_agent(name, display_name=None, description=""):
    """Create a mock agent with required attributes."""
    a = MagicMock()
    a.name = name
    a.display_name = display_name or name
    a.description = description
    return a


class TestGetAgentKeyboard:
    def test_no_agents_shows_default_only(self):
        kb = get_agent_keyboard([], None)
        buttons = kb.inline_keyboard
        # Default + Reload
        assert len(buttons) == 2
        assert buttons[0][0].text == "1 ✅"
        assert buttons[-1][0].text == "🔄 Reload Agents"

    def test_agents_listed(self):
        agents = [_make_agent("coder", "Coder Agent"), _make_agent("reviewer")]
        kb = get_agent_keyboard(agents, None)
        flat = [btn for row in kb.inline_keyboard for btn in row]
        texts = [b.text for b in flat]
        assert "1 ✅" in texts
        assert "2" in texts
        assert "3" in texts

    def test_current_agent_checkmarked(self):
        agents = [_make_agent("coder"), _make_agent("reviewer")]
        kb = get_agent_keyboard(agents, "coder")
        flat = [btn for row in kb.inline_keyboard for btn in row]
        coder_btn = next(b for b in flat if b.callback_data == "agent:coder")
        assert "✅" in coder_btn.text
        # Default should NOT have checkmark
        default_btn = flat[0]
        assert "✅" not in default_btn.text

    def test_no_current_agent_default_checkmarked(self):
        agents = [_make_agent("coder")]
        kb = get_agent_keyboard(agents, None)
        flat = [btn for row in kb.inline_keyboard for btn in row]
        default_btn = flat[0]
        assert "✅" in default_btn.text

    def test_callback_data_format(self):
        agents = [_make_agent("my-agent")]
        kb = get_agent_keyboard(agents, None)
        flat = [btn for row in kb.inline_keyboard for btn in row]
        assert flat[0].callback_data == "agent:__default__"
        assert flat[1].callback_data == "agent:my-agent"
        assert flat[-1].callback_data == "agent:__reload__"

    def test_dict_agents_supported(self):
        """Agents passed as dicts (e.g., from JSON) should work."""
        agents = [{"name": "dict-agent", "display_name": "Dict Agent", "description": "test"}]
        kb = get_agent_keyboard(agents, "dict-agent")
        flat = [btn for row in kb.inline_keyboard for btn in row]
        agent_btn = next(b for b in flat if b.callback_data == "agent:dict-agent")
        assert "✅" in agent_btn.text

    def test_agent_menu_message_shows_full_labels(self):
        agents = [_make_agent("coder", "Coder Agent"), _make_agent("reviewer", "Security Reviewer")]

        text, _ = get_agent_menu(agents, "reviewer")

        assert "1. Default (No Agent)" in text
        assert "2. Coder Agent" in text
        assert "3. Security Reviewer ✅" in text
        assert "Select an agent:" in text
