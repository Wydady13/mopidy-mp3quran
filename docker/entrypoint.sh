#!/bin/bash
set -e

mkdir -p /audio
[ -p /audio/snapfifo ] || mkfifo /audio/snapfifo

snapserver -c /etc/snapserver.conf &

exec "$@"
