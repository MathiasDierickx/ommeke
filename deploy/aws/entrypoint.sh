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
GRAPH_FAILED="$WRITABLE_HOME/gh.failed"

if [ ! -f "$GRAPH_CONFIG" ] || [ ! -d "$GRAPH_SOURCE" ] || [ -z "$GRAPH_JAR" ]; then
  echo "Lusmaker Lambda-image mist een voorbereid GraphHopper-regiopack" >&2
  exit 1
fi

mkdir -p "$WRITABLE_HOME"
rm -f "$GRAPH_FAILED"

# GraphHopper start op de achtergrond. De API is meteen bereikbaar: lezen van
# routes, gesprekken en downloads heeft geen router nodig. Routeringsaanroepen
# wachten in lusmaker.gh tot /health slaagt of dit merkteken verschijnt.
(
  mkdir -p "$GRAPH_TARGET"
  if cp -a "$GRAPH_SOURCE/." "$GRAPH_TARGET/"; then
    JAR="$GRAPH_JAR" JAVA_OPTS="${JAVA_OPTS:--Xms256m -Xmx2g}" \
      /opt/graphhopper/graphhopper.sh \
      -c "$GRAPH_CONFIG" \
      -o "$GRAPH_TARGET" \
      --host 127.0.0.1 || true
  fi
  echo "GraphHopper stopte" >&2
  touch "$GRAPH_FAILED"
) &

export LUSMAKER_HOME="$STATIC_HOME"
export LUSMAKER_GH_URL="http://127.0.0.1:8989"
export LUSMAKER_GH_STARTUP_WAIT_S="${LUSMAKER_GH_STARTUP_WAIT_S:-840}"
export LUSMAKER_GH_FAILED_MARKER="$GRAPH_FAILED"
exec uvicorn lusmaker.aws_app:app --host 0.0.0.0 --port 8080 --no-access-log
