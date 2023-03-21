import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)


class ArgumentParser(argparse.ArgumentParser):
    """Custom argument parser for Trame

    We will skip argument parsing under certain conditions, such as if
    pytest is running or the "TRAME_ARGS_DISABLED" environment variable
    is set.
    """

    def parse_known_args(self, args=None, namespace=None):
        if args is None and self._default_parsing_disabled:
            # If default parsing is disabled, don't allow it to parse sys.argv.
            # Pass it an empty list instead.
            logger.debug("Skipping default argument parsing...")
            args = []

        return super().parse_known_args(args, namespace)

    @property
    def _default_parsing_disabled(self):
        args_disabled_env = "TRAME_ARGS_DISABLED"
        if args_disabled_env in os.environ:
            falsy_values = (None, "", "0", "false")
            return os.environ[args_disabled_env] not in falsy_values

        # If TRAME_ARGS_DISABLED was not set and we are in pytest, then
        # also disable parsing.
        # Assume we are in pytest if pytest was imported
        # See discussion: https://github.com/pytest-dev/pytest/issues/9502
        if "pytest" in sys.modules:
            return True

        return False
