from kaggle_thinking_mode import (
    ThinkingModeError,
    assert_thinking_mode_off,
    load_pinned_chat_templates,
    thinking_mode_enabled,
)


def test_pinned_templates_disable_thinking():
    templates = load_pinned_chat_templates("fixtures/pinned_chat_templates.json")
    assert set(templates) == {"qwen3", "qwen35"}
    for name in templates:
        assert_thinking_mode_off(name, templates)
        assert thinking_mode_enabled(templates[name]) is False


def test_unknown_or_enabled_template_fails_closed():
    templates = {"candidate": {"temperature": 0.1}}
    try:
        assert_thinking_mode_off("missing", templates)
    except ThinkingModeError as exc:
        assert "no pinned" in str(exc)
    else:
        raise AssertionError("missing template was accepted")
    try:
        assert_thinking_mode_off("candidate", templates)
    except ThinkingModeError as exc:
        assert "not explicitly disabled" in str(exc)
    else:
        raise AssertionError("unconfigured thinking mode was accepted")
