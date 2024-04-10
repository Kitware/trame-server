import json
import sys

from . import logger


def share(obj, attr_name, default_value):
    if obj and hasattr(obj, attr_name):
        return getattr(obj, attr_name)

    return default_value


def _isascii_36(s):
    # For Python < 3.7, we have to use our own isascii() function.
    # This works for both bytes and strings.
    try:
        if isinstance(s, str):
            s.encode("ascii")
        else:
            # Assume bytes
            s.decode("ascii")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False
    else:
        return True


def _isascii_37(s):
    # For Python >= 3.7, use the built-in function
    return s.isascii()


if sys.version_info >= (3, 7):
    isascii = _isascii_37
else:
    isascii = _isascii_36


def is_dunder(s):
    # Check if this is a double underscore (dunder) name
    return len(s) > 4 and isascii(s) and s[:2] == s[-2:] == "__"


def is_private(s):
    return isascii(s) and s[0] == "_"


def clean_state(state):
    cleaned = {}
    str_values = {}
    for key in state:
        value = clean_value(state[key])
        if isinstance(value, bytes):
            cleaned[key] = value
            str_values[key] = value
        else:
            try:
                str_value = json.dumps(value)
                cleaned[key] = value
                str_values[key] = str_value
            except TypeError:
                logger.error(
                    f"Skip state value for '{key}' since its content is not serializable"
                )

    return cleaned, str_values


def clean_value(value):
    if isinstance(value, dict) and "_filter" in value.keys():
        subset = {}
        subset.update(value)
        keys_to_filter = value.get("_filter")
        for key in keys_to_filter:
            subset.pop(key, None)
        return subset

    if isinstance(value, list):
        return list(map(clean_value, value))

    return value


def update_dict(destination, source):
    for key, value in source.items():
        if isinstance(value, dict):
            # get node or create one
            container = destination.setdefault(key, {})
            update_dict(container, value)
        else:
            destination[key] = value

    return destination


def reduce_vue_use(state):
    _order = []
    _options = {}
    _reduced = []

    # Merge options
    for item in state.trame__vue_use:
        options = {}
        if isinstance(item, str):
            name = item
        else:
            name, options = item

        _options.setdefault(name, {})
        if name not in _order:
            _order.append(name)

        update_dict(_options[name], options)

    # Generate new content
    for name in _order:
        if len(_options[name]):
            _reduced.append((name, _options[name]))
        else:
            _reduced.append(name)

    # Update state.trame__vue_use with cleaned up version
    state.trame__vue_use = _reduced
