import argparse
import os
import sys


class ArgumentParser(argparse.ArgumentParser):
    """Custom argument parser for Trame

    In this class, `parse_known_args()` has a custom implementation.

    Normally, this would parse sys.argv[1:] as normal, but it will be different
    under the following conditions:

    1. A `--trame-args` argument is provided. If this is provided, then
       only the arguments supplied to this argument will be used for trame.
       For instance: `--trame-args="-p 8081 --server"` will mean the args
       parsed for trame will be `-p 8081 --server`.
    2. A `TRAME_ARGS` environment variable is set. If this is set, then
       only the arguments supplied to this environment variable will be used
       for trame.
       For instance: `TRAME_ARGS="-p 8081 --server"` will mean the args
       parsed for trame will be `-p 8081 --server`.
    3. The `pytest` module has been loaded. If this is the case, then we
       will automatically ignore `sys.argv` because `pytest` will not
       allow for arguments it does not recognize. If `pytest` has been
       loaded, the only way to specify trame arguments is through the
       `TRAME_ARGS` environment variable mentioned in #2.
    """

    def parse_known_args(self, args=None, namespace=None):
        # The trame arguments are usually specified as normal, but they
        # can be alternatively specified via an environment variable or
        # via `--trame-args="..."`.
        args = self._extract_trame_args(args)
        return super().parse_known_args(args, namespace)

    def _extract_trame_args(self, args):
        """Extract the arguments we will parse in trame"""
        if args is not None:
            # If the args is not None, then we are analyzing specific arguments.
            # Just return it the way it is.
            return args

        args = [] if self._skip_default_parsing else sys.argv[1:]

        if any(x.startswith("--trame-args") for x in sys.argv[1:]):
            # Allow argparse to handle all of the different ways this argument may be specified
            tmp_parser = argparse.ArgumentParser()
            tmp_parser.add_argument("--trame-args")
            out, _ = tmp_parser.parse_known_args([v for v in sys.argv[1:] if v != "--"])
            # Add these in
            args += out.trame_args.split()
        elif "TRAME_ARGS" in os.environ:
            # If "--trame-args" wasn't specified, check the environment variable.
            args += os.environ["TRAME_ARGS"].split()

        return args

    @property
    def _skip_default_parsing(self):
        # Skip the default parsing if the trame arguments were set another
        # way, such as the environment variable or the `--trame-args="..."` arg.
        # Also, skip the default parsing if we are in pytest, because pytest
        # will definitely not allow us to have extra arguments anyways.
        return (
            "TRAME_ARGS" in os.environ
            or any(x.startswith("--trame-args") for x in sys.argv[1:])
            or "pytest" in sys.modules
        )
