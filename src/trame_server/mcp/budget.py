"""Keeping replies small: values nobody asked for are capped, and every
reply stays within ``mcp.max_response_tokens``.

Whatever is cut short says so in a ``more`` entry, which names the call that
returns the rest when there is one.
"""

from __future__ import annotations

import json

__all__ = ["CHARS_PER_TOKEN", "MAX_ITEMS", "MAX_STRING", "cap", "shrink", "size"]

# A rough estimate, good enough to stay under clients' limits
CHARS_PER_TOKEN = 4
# Unrequested values: longer lists and strings are cut
MAX_ITEMS = 20
MAX_STRING = 400
# Below this, a string is not worth cutting to fit the budget
MIN_STRING = 40


def size(value) -> int:
    """The length of ``value`` as the compact JSON text a reply carries."""
    return len(
        json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)
    )


def _cut_string(text, length):
    return text[: max(1, length - 1)] + "…"


def cap(value):
    """``(value, note)``: ``value`` with its lists cut to ``MAX_ITEMS`` and
    its strings to ``MAX_STRING`` characters, at any depth. ``note`` says
    what was cut (None when nothing was)."""
    cut = []

    def visit(v, top):
        if isinstance(v, str):
            if len(v) > MAX_STRING:
                cut.append(f"{MAX_STRING} of {len(v)} characters shown" if top else "")
                return _cut_string(v, MAX_STRING)
            return v
        if isinstance(v, list):
            items = v
            if len(v) > MAX_ITEMS:
                cut.append(f"{MAX_ITEMS} of {len(v)} items shown" if top else "")
                items = v[:MAX_ITEMS]
            return [visit(i, False) for i in items]
        if isinstance(v, dict):
            return {k: visit(i, False) for k, i in v.items()}
        return v

    result = visit(value, True)
    if not cut:
        return result, None
    notes = [c for c in cut if c]
    return result, notes[0] if notes else "shortened"


def _cuttable(v):
    return (isinstance(v, list) and len(v) > 1) or (
        isinstance(v, str) and len(v) > MIN_STRING
    )


def _largest(value):
    """The path to the node to cut next, or None. Lists and strings are cut, and
    dicts are walked into, through their largest member each time."""
    path, node = [], value
    while True:
        if isinstance(node, dict):
            if not node:
                return None
            key = max(node, key=lambda k: size(node[k]))
            if not (_cuttable(node[key]) or isinstance(node[key], (dict, list))):
                return None
            path.append(key)
            node = node[key]
            continue
        if isinstance(node, list):
            if not node:
                return None
            sizes = [size(v) for v in node]
            big = max(range(len(node)), key=sizes.__getitem__)
            # One item holding most of the list: cut inside it instead
            inner = node[big]
            if (
                sizes[big] * 2 > sum(sizes)
                and isinstance(inner, (dict, list, str))
                and (len(node) == 1 or _cuttable(inner))
            ):
                path.append(big)
                node = inner
                continue
            return path if len(node) > 1 else None
        if isinstance(node, str) and len(node) > MIN_STRING:
            return path
        return None


def shrink(value, budget, totals=None):
    """``(value, cuts)``: ``value`` (a dict) with its largest lists and
    strings cut until its JSON fits in ``budget`` characters, or nothing is
    left to cut. ``cuts`` maps each top-level key cut into to a note.
    ``totals`` gives the full length of top-level values already cut (by
    ``cap``), for the notes."""
    value = json.loads(json.dumps(value, default=str))  # a copy we may cut
    totals, lengths, cuts = totals or {}, {}, {}
    while size(value) > budget:
        path = _largest(value)
        if not path:
            break
        parent = value
        for key in path[:-1]:
            parent = parent[key]
        node = parent[path[-1]]
        top = path[0]
        if len(path) == 1:
            lengths.setdefault(top, totals.get(top, len(node)))
        if isinstance(node, list):
            parent[path[-1]] = node[: max(1, len(node) // 2)]
        else:
            parent[path[-1]] = _cut_string(node, len(node) // 2)
        cuts[top] = None
    for top in cuts:
        node = value[top]
        if top in lengths and isinstance(node, list):
            cuts[top] = f"{len(node)} of {lengths[top]} items shown"
        elif top in lengths and isinstance(node, str):
            cuts[top] = f"{len(node) - 1} of {lengths[top]} characters shown"
        else:
            cuts[top] = "shortened"
    return value, cuts
