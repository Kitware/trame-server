Example on how to test this example

```bash
python ./server.py --port 1234 --server &
python ./client.py --port 1235 --url ws://localhost:1234/ws --server
```