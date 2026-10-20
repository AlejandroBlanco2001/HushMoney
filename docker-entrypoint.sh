#!/bin/sh
set -e

# Start Telegram gateway in background
hermes gateway run &

# Start HTTP gateway server for the forwarder
exec python3 -m uvicorn gateway_server:app --host 0.0.0.0 --port 8080
