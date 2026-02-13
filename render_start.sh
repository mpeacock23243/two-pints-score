#!/usr/bin/env bash
set -e

python3 -c "from app import init_db; init_db()"
gunicorn -w 2 -b 0.0.0.0:${PORT} app:app
