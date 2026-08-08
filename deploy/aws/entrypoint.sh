#!/bin/sh
set -eu

STATIC_HOME="${LUSMAKER_STATIC_HOME:-/opt/lusmaker}"
WRITABLE_HOME="${LUSMAKER_WRITABLE_HOME:-/tmp/lusmaker}"
REGION_SLUG="${LUSMAKER_REGION:?LUSMAKER_REGION ontbreekt}"
REGION_HOME="$STATIC_HOME/regions/$REGION_SLUG"
GRAPH_SOURCE="$REGION_HOME/gh/graph-cache"
GRAPH_TARGET="$WRITABLE_HOME/gh/graph-cache"
GRAPH_CONFIG="$REGION_HOME/gh/config.yml"
GRAPH_JAR="$(find /opt/graphhopper -maxdepth 1 -type f -name 'graphhopper*.jar' -print -quit)"

if [ ! -f "$GRAPH_CONFIG" ] || [ ! -d "$GRAPH_SOURCE" ] || [ -z "$GRAPH_JAR" ]; then
  echo "Lusmaker Lambda-image mist een voorbereid GraphHopper-regiopack" >&2
  exit 1
fi

mkdir -p "$GRAPH_TARGET"
cp -a "$GRAPH_SOURCE/." "$GRAPH_TARGET/"

JAR="$GRAPH_JAR" JAVA_OPTS="${JAVA_OPTS:--Xms256m -Xmx2g}" \
  /opt/graphhopper/graphhopper.sh \
  -c "$GRAPH_CONFIG" \
  -o "$GRAPH_TARGET" \
  --host 127.0.0.1 &
graphhopper_pid=$!

stop_graphhopper() {
  kill "$graphhopper_pid" 2>/dev/null || true
}
trap stop_graphhopper INT TERM EXIT

attempt=0
until curl --fail --silent --show-error http://127.0.0.1:8989/health >/dev/null; do
  if ! kill -0 "$graphhopper_pid" 2>/dev/null; then
    echo "GraphHopper stopte tijdens het opstarten" >&2
    wait "$graphhopper_pid"
    exit 1
  fi
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 1680 ]; then
    echo "GraphHopper werd niet gezond binnen 14 minuten" >&2
    exit 1
  fi
  sleep 0.5
done

trap - INT TERM EXIT
export LUSMAKER_HOME="$STATIC_HOME"
export LUSMAKER_GH_URL="http://127.0.0.1:8989"
exec uvicorn lusmaker.aws_app:app --host 0.0.0.0 --port 8080 --no-access-log
