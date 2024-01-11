import logging

from trame_server.core import Controller, State, Translator

logger = logging.getLogger(__name__)


def func1():
    return 1


def func2():
    return 2


def func3():
    return 3

def test_translator():
    a_translator = Translator()
    a_translator.add_translation("foo", "a_foo")

    assert a_translator.translate_key("foo") == "a_foo"
    assert a_translator.translate_key("bar") == "bar"
    assert a_translator.reverse_translate_key("a_foo") == "foo"
    assert a_translator.reverse_translate_key("bar") == "bar"

    b_translator = Translator()
    b_translator.set_prefix("b_")

    assert b_translator.translate_key("foo") == "b_foo"
    assert b_translator.translate_key("bar") == "b_bar"
    assert b_translator.reverse_translate_key("b_foo") == "foo"
    assert b_translator.reverse_translate_key("b_bar") == "bar"


def test_state_translation():
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


def test_controller_translation():
    root_controller = Controller()
    a_controller = Controller(internal=root_controller)
    b_controller = Controller(internal=root_controller)

    root_controller.func = func1
    assert root_controller.func() == 1
    assert a_controller.func() == 1
    assert b_controller.func() == 1

    a_controller.func = func2
    assert root_controller.func() == 2
    assert a_controller.func() == 2
    assert b_controller.func() == 2

    b_controller.func = func3
    assert root_controller.func() == 3
    assert a_controller.func() == 3
    assert b_controller.func() == 3

    a_controller._translator.add_translation("func", "a_func")
    b_controller._translator.add_translation("func", "b_func")
    root_controller.func = func1
    a_controller.func = func2
    b_controller.func = func3

    assert root_controller.func() == 1
    assert a_controller.func() == 2
    assert b_controller.func() == 3
    assert root_controller.a_func() == 2
    assert root_controller.b_func() == 3

    expected_controller = {
        "func": func1,
        "a_func": func2,
        "b_func": func3,
    }
    assert all(
        func in root_controller._func_dict.keys() for func in expected_controller.keys()
    )
    assert all(
        expected_controller[func]() == root_controller[func]()
        for func in expected_controller.keys()
    )


def test_state_prefix():
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


def test_controller_prefix():
    root_controller = Controller()
    a_controller = Controller(internal=root_controller)
    b_controller = Controller(internal=root_controller)

    a_controller._translator.set_prefix("a_")
    b_controller._translator.set_prefix("b_")
    root_controller.func = func1
    a_controller.func = func2
    b_controller.func = func3

    assert root_controller.func() == 1
    assert a_controller.func() == 2
    assert b_controller.func() == 3
    assert root_controller.a_func() == 2
    assert root_controller.b_func() == 3

    expected_controller = {
        "func": func1,
        "a_func": func2,
        "b_func": func3,
    }
    assert all(
        func in root_controller._func_dict.keys() for func in expected_controller.keys()
    )
    assert all(
        expected_controller[func]() == root_controller[func]()
        for func in expected_controller.keys()
    )


def test_state_prefix_and_translation():
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


def test_controller_prefix_and_translation():
    root_controller = Controller()
    a_controller = Controller(internal=root_controller)
    b_controller = Controller(internal=root_controller)

    a_controller._translator.set_prefix("a_")
    b_controller._translator.set_prefix("b_")

    root_controller._translator.add_translation("shared_func", "common_shared_func")
    a_controller._translator.add_translation("shared_func", "common_shared_func")
    b_controller._translator.add_translation("shared_func", "common_shared_func")

    root_controller.func = func1
    a_controller.func = func2
    b_controller.func = func3
    assert root_controller.func() == 1
    assert a_controller.func() == 2
    assert b_controller.func() == 3
    assert root_controller.a_func() == 2
    assert root_controller.b_func() == 3

    root_controller.shared_func = func1
    assert root_controller.shared_func() == 1
    assert a_controller.shared_func() == 1
    assert b_controller.shared_func() == 1

    a_controller.shared_func = func2
    assert root_controller.shared_func() == 2
    assert a_controller.shared_func() == 2
    assert b_controller.shared_func() == 2

    b_controller.shared_func = func3
    assert root_controller.shared_func() == 3
    assert a_controller.shared_func() == 3
    assert b_controller.shared_func() == 3

    expected_controller = {
        "func": func1,
        "a_func": func2,
        "b_func": func3,
        "common_shared_func": func3,
    }

    assert all(
        func_name in root_controller._func_dict.keys()
        for func_name in expected_controller.keys()
    )
    assert all(
        func() == root_controller[func_name]()
        for func_name, func in expected_controller.items()
    )


def test_change_callback():
    # Ensure change callbacks are passed translated kwargs when using translations
    test_passed = False

    root_state = State()

    a_state = State(internal=root_state)
    a_state.translator.add_translation("foo", "a_foo")

    def on_a_foo_change(*args, **kwargs):
        nonlocal test_passed
        assert "foo" in kwargs
        assert "a_foo" not in kwargs
        assert kwargs["foo"] == 123
        test_passed = "foo" in kwargs and "a_foo" not in kwargs

    a_state.change("foo")(on_a_foo_change)
    a_state.ready()
    a_state.foo = 123
    root_state.foo = 456
    a_state.flush()

    assert test_passed

    # Ensure change callbacks are passed translated kwargs when using prefix
    test_passed = False

    root_state = State()

    b_state = State(internal=root_state)
    b_state.translator.set_prefix("b_")

    def on_b_foo_change(*args, **kwargs):
        nonlocal test_passed
        assert "foo" in kwargs
        assert "b_foo" not in kwargs
        assert kwargs["foo"] == 456
        test_passed = "foo" in kwargs and "b_foo" not in kwargs

    b_state.change("foo")(on_b_foo_change)

    b_state.ready()
    b_state.foo = 456
    root_state.foo = 123
    b_state.flush()

    assert test_passed
