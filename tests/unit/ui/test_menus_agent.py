"""Unit tests for get_agent_keyboard in src/ui/menus.py."""

from unittest.mock import MagicMock

from src.ui.menus import get_agent_keyboard


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
        assert "Default (No Agent) ✅" in buttons[0][0].text
        assert buttons[-1][0].text == "🔄 Reload Agents"

    def test_agents_listed(self):
        agents = [_make_agent("coder", "Coder Agent"), _make_agent("reviewer")]
        kb = get_agent_keyboard(agents, None)
        flat = [btn for row in kb.inline_keyboard for btn in row]
        texts = [b.text for b in flat]
        assert "Coder Agent" in texts
        assert "reviewer" in texts

    def test_current_agent_checkmarked(self):
        agents = [_make_agent("coder"), _make_agent("reviewer")]
        kb = get_agent_keyboard(agents, "coder")
        flat = [btn for row in kb.inline_keyboard for btn in row]
        coder_btn = next(b for b in flat if "coder" in b.text)
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
        agent_btn = next(b for b in flat if "Dict Agent" in b.text)
        assert "✅" in agent_btn.text
