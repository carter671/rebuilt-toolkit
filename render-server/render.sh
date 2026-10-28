#!/usr/bin/env sh
# Linux / macOS / cloud GPU: same server. BLENDER defaults to `blender` on the PATH.
cd "$(dirname "$0")" && "${BLENDER:-blender}" -b --factory-startup -P render_server.py -- "$@"
