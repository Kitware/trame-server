import logging

from trame_server.core import State

logger = logging.getLogger(__name__)


def test_translation():
    root_state = State()
    a_state = State(internal=root_state)
    b_state = State(internal=root_state)

    root_state.ready()
    a_state.ready()
    b_state.ready()

    # Since the translator doesn't have a prefix or any translation,
    # changing a piece of state on any of the 3 states applies to all
    root_state.value = 123
    assert root_state.value == 123
    assert a_state.value == 123
    assert b_state.value == 123

    a_state.value = 456
    assert root_state.value == 456
    assert a_state.value == 456
    assert b_state.value == 456

    b_state.value = 789
    assert root_state.value == 789
    assert a_state.value == 789
    assert b_state.value == 789

    # Add translations for a_state and b_state which will cause
    # "value" to point to a different key
    a_state.translator.add_translation("value", "a_value")
    b_state.translator.add_translation("value", "b_value")
    root_state.value = 123
    a_state.value = 456
    b_state.value = 789
    assert root_state.value == 123
    assert a_state.value == 456
    assert b_state.value == 789
    assert root_state.a_value == 456
    assert root_state.b_value == 789

    expected_state = {
        "value": 123,
        "a_value": 456,
        "b_value": 789,
    }
    assert expected_state == root_state.to_dict()


def test_prefix():
    root_state = State()
    a_state = State(internal=root_state)
    b_state = State(internal=root_state)

    root_state.ready()
    a_state.ready()
    b_state.ready()

    a_state.translator.set_prefix("a_")
    b_state.translator.set_prefix("b_")

    root_state.value = 123
    a_state.value = 456
    b_state.value = 789
    assert root_state.value == 123
    assert a_state.value == 456
    assert b_state.value == 789
    assert root_state.a_value == 456
    assert root_state.b_value == 789

    expected_state = {
        "value": 123,
        "a_value": 456,
        "b_value": 789,
    }
    assert expected_state == root_state.to_dict()


def test_prefix_and_translation():
    root_state = State()
    a_state = State(internal=root_state)
    b_state = State(internal=root_state)

    root_state.ready()
    a_state.ready()
    b_state.ready()

    # The states will be isolated by default
    a_state.translator.set_prefix("a_")
    b_state.translator.set_prefix("b_")

    # But by adding translations for a_state and b_state
    # that point to a common key they are still able to interact
    root_state.translator.add_translation("shared_value", "common_shared_value")
    a_state.translator.add_translation("shared_value", "common_shared_value")
    b_state.translator.add_translation("shared_value", "common_shared_value")

    root_state.value = 123
    a_state.value = 456
    b_state.value = 789
    assert root_state.value == 123
    assert a_state.value == 456
    assert b_state.value == 789
    assert root_state.a_value == 456
    assert root_state.b_value == 789

    root_state.shared_value = 123
    assert root_state.shared_value == 123
    assert a_state.shared_value == 123
    assert b_state.shared_value == 123

    a_state.shared_value = 456
    assert root_state.shared_value == 456
    assert a_state.shared_value == 456
    assert b_state.shared_value == 456

    b_state.shared_value = 789
    assert root_state.shared_value == 789
    assert a_state.shared_value == 789
    assert b_state.shared_value == 789

    expected_state = {
        "value": 123,
        "a_value": 456,
        "b_value": 789,
        "common_shared_value": 789,
    }
    assert expected_state == root_state.to_dict()
