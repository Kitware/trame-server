def is_dunder(s):
    # Check if this is a double underscore (dunder) name
    return len(s) > 4 and s.isascii() and s[:2] == s[-2:] == "__"


def is_private(s):
    return s.isascii() and s[0] == "_"


def clean_state(state):
    cleaned = {}
    for key in state:
        cleaned[key] = clean_value(state[key])

    return cleaned


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
