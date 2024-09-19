import logging
from more_itertools import split_when

logger = logging.getLogger(__name__)

RESERVED_CONTROLLER_NAMES = {
    "on_server_start",
    "on_server_bind",
    "on_server_ready",
    "on_client_connected",
    "on_client_exited",
    "on_server_exited",
    "on_server_reload",
}

JS_DELIMITOR = {
    "'",
    '"',
    ":",
    ";",
    "(",
    ")",
    "{",
    "}",
    " ",
    ".",
    ",",
    "!",
    "[",
    "]",
    "`",
    "\n",
    "+",
    "*",
    "/",
    "-",
    "|",
    "&",
}


def js_tokenizer(a, b):
    return a in JS_DELIMITOR or b in JS_DELIMITOR


def vue_template_tokenizer(a, b):
    return a == b and a in {"{", "}"}


def is_name_reserved(name):
    if name.startswith("trame__"):
        return True

    if name in RESERVED_CONTROLLER_NAMES:
        return True

    return False


class Translator:
    """Helper for mapping or namespacing names for state or controller"""

    def __init__(self, prefix=None):
        logger.info("Translator(prefix=%s)", prefix)
        self._prefix = prefix
        self._transl = {}

    def set_prefix(self, prefix):
        self._prefix = prefix

    def add_translation(self, key, translated_key):
        self._transl[key] = translated_key

    def translate_key(self, key):
        # Reserved keys
        if is_name_reserved(key):
            return key

        if key in self._transl:
            return self._transl[key]

        if self._prefix:
            return f"{self._prefix}{key}"

        return key

    def translate_list(self, key_list):
        return [self.translate_key(v) for v in key_list]

    def translate_dict(self, key_dict):
        return {self.translate_key(k): v for k, v in key_dict.items()}

    def translate_js_expression(self, state, expression):
        tokens = []
        for token in split_when(expression, js_tokenizer):
            token = "".join(token)
            logger.info("(prefix=%s) token %s", self._prefix, token)
            if state.has(token):
                _token = self.translate_key(token)
                logger.info("(prefix=%s) translated %s", self._prefix, _token)
                tokens.append(_token)
            else:
                tokens.append(token)

        logger.info(" => %s", "".join(tokens))

        return "".join(tokens)

    def translate_vue_templating(self, state, expression):
        tokens = []
        for token in split_when(expression, vue_template_tokenizer):
            token = "".join(token)
            logger.info(" token %s", token)
            if token.startswith("{"):
                tokens.append(self.translate_js_expression(state, token))
            else:
                tokens.append(token)
        return "".join(tokens)

    def __call__(self, key):
        return self.translate_key(key)
