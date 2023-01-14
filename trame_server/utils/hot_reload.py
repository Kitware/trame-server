"""Automatically reload function code each time it is called

This module provides a `hot_reload` decorator where the decorated function
is reloaded from source every time the function is called. This works
primarily for global functions and class methods, but it also has
limited support for nested functions as well*.

This module also provides a `reload` function that can be used to reload
a function on demand, i. e. `new_func = reload(old_func)`.

This module is based upon Julian Vossen's reloading library:
https://github.com/julvo/reloading

But it is heavily modified, and includes additional support for things
like class methods. The license for the original library is pasted at
the bottom of this file.

* Nested functions have the following issues:

1. You cannot use the `nonlocal` statement in nested functions. When
the code is reloaded, Python treats it as a global function, and
therefore the `nonlocal` keyword is not allowed.
2. You cannot add capture variables during reloading. Whatever was
captured when the function was first defined is what will continue
to be captured. This is because the outer function is never reloaded,
and the outer function's local scope may potentially be gone at the
time of decorating.
3. If some of the capture variables share the same name as global
variables, but are different, then references to the global variable
within the function or functions it calls may end up referring to
the capture variable instead.
"""

import ast
import functools
import inspect
import site
import sys
import traceback
import types

try:
    from trame_client.ui.core import AbstractLayout
    from trame_client.widgets.core import AbstractElement

    # Skip any methods whose classes inherit from these
    SKIP_CLASSES = [AbstractElement, AbstractLayout]
except ImportError:
    SKIP_CLASSES = []


# Strip any decorators with these names
STRIP_DECORATORS = ["ctrl", "state"]


# We don't actually have logic right now to reload lambdas anyways
SKIP_LAMBDA_FUNCS = True

# If this is True, then skip any functions that are located under any
# site packages directories.
# This essentially means to skip any functions that are not located
# in editable environments.
SKIP_SITE_PACKAGES = True


def hot_reload(func):
    """Decorator to reload the function on every call

    If there are multiple decorators on this function, only the
    decorators after the `@hot_reload` decorator will be reloaded
    """
    if getattr(func, "__is_hot_reload_func", False):
        # It is already a hot_reload function. Just return it.
        # This prevents multiple hot_reload wrappers.
        return func

    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        # If the user decorated the function manually, make sure we
        # don't perform checks and reload every time.
        new_func = reload(func, perform_checks=False)
        return new_func(*args, **kwargs)

    wrapped.__is_hot_reload_func = True

    return wrapped


def reload(func, perform_checks=True):
    """Attempt to reload the provided function

    This works by locating the file the function was defined in, reloading its
    body of code, and returning the reloaded function.

    If perform_checks is True, then several checks will be performed beforehand
    to determine whether or not the function should be skipped.
    """
    if perform_checks:
        if not isinstance(func, (types.FunctionType, types.MethodType)):
            # We only allow reloading of function and method types
            return func

        if isinstance(func, types.MethodType):
            if isinstance(func.__self__, tuple(SKIP_CLASSES)):
                # We need to skip reloading methods on this class
                return func

        if SKIP_LAMBDA_FUNCS and "<lambda>" in func.__qualname__:
            # Skip lambda functions. It is harder to reload them.
            return func

        if SKIP_SITE_PACKAGES and _func_in_site_packages(func):
            # Skip any packages that were not installed in editable mode
            return func

    while True:
        try:
            return _reload_func(func)
        except Exception:
            _handle_exception(func)


def _reload_func(func):
    func_locals = _find_function_locals(func)
    code = _recompile_function(func)

    # Unfortunately, exec is a little challenging here for non-global
    # functions.
    # Since the source function is compiled by itself, it is treated as
    # a global function, and therefore cannot have closure variables.
    # Because of this, the function will not have read access to the locals
    # we pass in (even though it can still write the function to the locals).
    # To work around this, we copy the locals to the globals (and some globals
    # may be over-written as a result).
    # An alternative work-around would be to add AST code to put a small
    # wrapper function around the function before compiling, such as:
    # def _wrapper():
    #     <func_code>
    # _wrapper()
    # This may get the function to capture the local variables.
    globals_copy = func.__globals__.copy()
    globals_copy.update(func_locals)
    exec(code, globals_copy)

    new_func = globals_copy[func.__name__]

    if isinstance(func, types.MethodType):
        # This is a bound method. Make the new method bound as well.
        new_func = types.MethodType(new_func, func.__self__)

    return new_func


def _find_function_locals(func):
    # First, look at the qualified name.
    # If <locals> is not in the qualified name, then the locals should be
    # the same as the globals. This is much easier for reloading.
    if "<locals>" not in func.__qualname__:
        return func.__globals__

    # If <locals> is in the qualified name, then we may need captured closure
    # variables to run the function correctly. We will use these as the locals.
    # Note that this means that new closure variables cannot be added when
    # reloading the function.
    return inspect.getclosurevars(func).nonlocals


def _recompile_function(func):
    tree = _parse_func_file_until_successful(func)
    if not _isolate_function_def(func.__name__, tree):
        path = inspect.getfile(func)
        raise Exception(f"Failed to find '{func.__qualname__}' in file '{path}'")

    return compile(tree, filename="", mode="exec")


def _parse_func_file_until_successful(func):
    path = inspect.getfile(func)
    while True:
        source = _load_file(path)
        try:
            return ast.parse(source)
        except SyntaxError:
            _handle_exception(func)


def _load_file(path):
    src = ""
    # while loop here since while saving, the file may sometimes be empty.
    while src == "":
        with open(path, "r") as f:
            src = f.read()
    return src + "\n"


def _isolate_function_def(funcname, tree):
    """Strip everything but the function definition from the ast in-place.
    Also strips the hot_reload decorator (including all decorators before it)
    from the function definition"""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == funcname:
            decorator_names = [_get_decorator_name(dec) for dec in node.decorator_list]
            if "hot_reload" in decorator_names:
                _strip_hot_reload_decorator(node)

            # Remove any decorators that we have indicated to strip
            _strip_decorators(node, STRIP_DECORATORS)

            tree.body = [node]
            return True

    return False


def _handle_exception(func):
    fpath = inspect.getfile(func)
    exc = traceback.format_exc()
    exc = exc.replace('File "<string>"', f'File "{fpath}"')
    sys.stderr.write(exc + "\n")
    print(f"Edit '{func.__qualname__}' in '{fpath}' and press return to continue")
    sys.stdin.readline()


def _get_decorator_name(dec_node):
    if hasattr(dec_node, "id"):
        return dec_node.id
    elif hasattr(dec_node.func, "id"):
        return dec_node.func.id

    return dec_node.func.value.id


def _strip_hot_reload_decorator(func):
    """Remove the 'hot_reload' decorator and all decorators before it"""
    decorator_names = [_get_decorator_name(dec) for dec in func.decorator_list]
    hot_reload_idx = decorator_names.index("hot_reload")
    func.decorator_list = func.decorator_list[hot_reload_idx + 1 :]


def _strip_decorators(func, blacklist):
    """Strip only specific decorators"""
    func.decorator_list = [
        dec for dec in func.decorator_list if _get_decorator_name(dec) not in blacklist
    ]


def _func_in_site_packages(func):
    """Return whether a function is in any site-packages directories"""
    path = inspect.getfile(func)
    return any(path.startswith(x) for x in site.getsitepackages())


JULVO_RELOADING_LICENSE = """MIT License
Copyright (c) 2019 Julian Vossen
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
