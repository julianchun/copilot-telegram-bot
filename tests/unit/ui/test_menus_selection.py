"""Unit tests for numbered selection menu helpers in src/ui/menus.py."""

from src.ui.menus import get_input_selection_menu, get_model_menu, get_reasoning_menu


def test_get_input_selection_menu_shows_full_text_with_numbered_buttons():
    text, keyboard = get_input_selection_menu(
        "Choose an environment",
        [
            "Production - Singapore region, autoscaling enabled",
            "Production - Tokyo region, autoscaling disabled",
        ],
        "abcd1234",
    )

    assert "1. Production - Singapore region, autoscaling enabled" in text
    assert "2. Production - Tokyo region, autoscaling disabled" in text
    assert "Reply with text or select an option:" in text

    rows = keyboard.inline_keyboard
    assert rows[0][0].text == "1"
    assert rows[0][1].text == "2"
    assert rows[-1][0].text == "❌ Cancel"


def test_get_input_selection_menu_paginates_long_lists():
    options = [f"Option {i}" for i in range(1, 11)]

    text, keyboard = get_input_selection_menu("Choose a project", options, "abcd1234")

    assert "Page 1/2" in text
    flat_texts = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "1" in flat_texts
    assert "9" in flat_texts
    assert "Next ▶" in flat_texts


def test_get_model_menu_marks_current_model_in_text_and_button():
    text, keyboard = get_model_menu(
        [
            {"id": "gpt-4.1", "multiplier": "1x"},
            {"id": "claude-sonnet-4.5", "multiplier": "2x"},
        ],
        current_model="claude-sonnet-4.5",
    )

    assert "1. gpt-4.1 (1x)" in text
    assert "2. claude-sonnet-4.5 (2x) ✅" in text

    flat = [button for row in keyboard.inline_keyboard for button in row]
    selected = next(button for button in flat if button.callback_data == "model:claude-sonnet-4.5")
    assert selected.text == "2 ✅"
    assert flat[-1].text == "❌ Cancel"


def test_get_input_selection_menu_without_choices_prompts_for_reply():
    text, keyboard = get_input_selection_menu(
        "Describe the bug you want fixed",
        [],
        "abcd1234",
        allow_freeform=True,
    )

    assert "Reply with your answer below." in text
    assert keyboard.inline_keyboard[-1][0].text == "❌ Cancel"


def test_get_reasoning_menu_hides_reset_warning_and_default_option():
    text, keyboard = get_reasoning_menu(
        "gpt-5.4",
        ["low", "medium", "high"],
        default_effort="medium",
    )

    assert "Session will be reset" not in text
    assert "1. Low" in text
    assert "2. Medium (model default) ✅" in text
    assert "3. High" in text
    assert "Default" not in text

    callback_data = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "reasoning:gpt-5.4:low" in callback_data
    assert "reasoning:gpt-5.4:default" in callback_data
    assert "reasoning:gpt-5.4:high" in callback_data
    assert "reasoning:gpt-5.4:medium" not in callback_data


def test_get_reasoning_menu_marks_explicit_effort_over_model_default():
    text, _ = get_reasoning_menu(
        "gpt-5.4",
        ["low", "medium", "high"],
        default_effort="medium",
        current_effort="high",
    )

    assert "2. Medium (model default)" in text
    assert "2. Medium (model default) ✅" not in text
    assert "3. High ✅" in text
