import argparse
import asyncio

from trame_server.client import Client


async def main(url):
    # Connect to the remote server
    client = Client()
    task = asyncio.create_task(client.connect(url, secret="wslink-secret"))
    await client.ready

    # Read current values in the server state
    print("Current server counter: ", client.state.counter)

    # Write values in the server state
    with client.state:
        client.state.counter += 5

    # Invoke method inside the trame app
    await client.call_trigger(
        "my_method", ["arg0", "arg1", "arg2"], {"kwarg0": 1.234, "kwarg1": 5.678}
    )

    await client.diconnect()
    await task


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()

    asyncio.run(main(args.url))
