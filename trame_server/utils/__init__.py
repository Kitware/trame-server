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
            _order.append(item)

        update_dict(_options[name], options)

    # Generate new content
    for name in _order:
        if len(_options[name]):
            _reduced.append((name, _options[name]))
        else:
            _reduced.append(name)

    # Update state.trame__vue_use with cleaned up version
    state.trame__vue_use = _reduced
