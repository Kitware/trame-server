import os
import json
from pathlib import Path

OUTPUT_LOG = False


class EscapeEncoder(json.JSONEncoder):
    """Custom encoder for numpy data types"""

    def default(self, obj):
        if isinstance(
            obj,
            (bytes,),
        ):
            return str(type(obj))

        return json.JSONEncoder.default(self, obj)


def initialize_logger(config):
    global OUTPUT_LOG
    OUTPUT_LOG = config.get("log_network", False)
    if OUTPUT_LOG and Path(OUTPUT_LOG).exists():
        os.remove(OUTPUT_LOG)


class StateExchangeType:
    STATE_INITIAL = "----------- INITIAL STATE -----------\n"
    STATE_CLIENT_TO_SERVER = "----------- STATE: Client => Server -----------\n"
    STATE_SERVER_TO_CLIENT = "----------- STATE: Server => Client -----------\n"
    ACTION_CLIENT_TO_SERVER = "----------- EVENT: Client => Server -----------\n"
    ACTION_SERVER_TO_CLIENT = "----------- EVENT: Server => Client -----------\n"


def state_exchange(exchange, data):
    if OUTPUT_LOG:
        with open(OUTPUT_LOG, "a") as f:
            f.write(exchange)
            f.write(json.dumps(data, indent=2, cls=EscapeEncoder))
            f.write("\n")
            f.write("-" * 60)
            f.write("\n")


def initial_state(data):
    state_exchange(StateExchangeType.STATE_INITIAL, data)


def state_c2s(data):
    state_exchange(StateExchangeType.STATE_CLIENT_TO_SERVER, data)


def state_s2c(data):
    state_exchange(StateExchangeType.STATE_SERVER_TO_CLIENT, data)


def action_s2c(data):
    state_exchange(StateExchangeType.ACTION_SERVER_TO_CLIENT, data)


def action_c2s(data):
    state_exchange(StateExchangeType.ACTION_CLIENT_TO_SERVER, data)


def error(message):
    print(f"Error: {message}", flush=True)
    if OUTPUT_LOG:
        with open(OUTPUT_LOG, "a") as f:
            f.write("-" * 60)
            f.write("\nERROR: ")
            f.write(message)
            f.write("\n")
            f.write("-" * 60)
            f.write("\n")
