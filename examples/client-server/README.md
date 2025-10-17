## Control a trame application through another trame application

```bash
python ./server.py --port 1234 --server &
python ./client.py --port 1235 --url ws://localhost:1234/ws --server
```

## Control a trame application through an external script

```bash
python ./server.py --port 1234 --server &
python ./script.py --url ws://localhost:1234/ws
```
