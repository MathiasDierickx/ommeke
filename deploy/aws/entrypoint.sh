#!/bin/sh
set -eu

STATIC_HOME="${LUSMAKER_STATIC_HOME:-/opt/lusmaker}"
WRITABLE_HOME="${LUSMAKER_WRITABLE_HOME:-/tmp/lusmaker}"
REGION_SLUG="${LUSMAKER_REGION:?LUSMAKER_REGION ontbreekt}"
REGION_HOME="$STATIC_HOME/regions/$REGION_SLUG"
export LUSMAKER_GH_URL="${LUSMAKER_GH_URL:-http://127.0.0.1:8989}"
# Parseer de host: een externe URL mag nooit de lokale JVM starten.
GH_HOST="$(python -c 'import os, urllib.parse; print(urllib.parse.urlparse(os.environ["LUSMAKER_GH_URL"]).hostname or "")')"
case "$GH_HOST" in
  localhost|127.0.0.1|::1)
    GRAPH_SOURCE="$REGION_HOME/gh/graph-cache"
    GRAPH_TARGET="$WRITABLE_HOME/gh/graph-cache"
    GRAPH_CONFIG="$REGION_HOME/gh/config.yml"
    GRAPH_JAR="$(find /opt/graphhopper -maxdepth 1 -type f -name 'graphhopper*.jar' -print -quit 2>/dev/null || true)"
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
    # De graph staat als MMAP in plaats van RAM_STORE in het geheugen: de kernel
    # kan die pagina's terugwinnen, terwijl een volle Java-heap naast Python de
    # Lambda-geheugenlimiet (3008 MB) overschreed (Runtime.OutOfMemory).
    RUNTIME_CONFIG="$WRITABLE_HOME/gh/config.yml"
    (
      mkdir -p "$GRAPH_TARGET"
      awk '{ print } /^graphhopper:[[:space:]]*$/ { print "  graph.dataaccess.default_type: MMAP" }' \
        "$GRAPH_CONFIG" > "$RUNTIME_CONFIG"
      if cp -a "$GRAPH_SOURCE/." "$GRAPH_TARGET/"; then
        JAR="$GRAPH_JAR" JAVA_OPTS="${JAVA_OPTS:--Xms256m -Xmx1536m}" \
          /opt/graphhopper/graphhopper.sh \
          -c "$RUNTIME_CONFIG" \
          -o "$GRAPH_TARGET" \
          --host 127.0.0.1 || true
      fi
      echo "GraphHopper stopte" >&2
      touch "$GRAPH_FAILED"
    ) &

    export LUSMAKER_GH_FAILED_MARKER="$GRAPH_FAILED"
    ;;
  *)
    unset LUSMAKER_GH_FAILED_MARKER
    ;;
esac

export LUSMAKER_HOME="$STATIC_HOME"
export LUSMAKER_GH_STARTUP_WAIT_S="${LUSMAKER_GH_STARTUP_WAIT_S:-840}"
exec uvicorn lusmaker.aws_app:app --host 0.0.0.0 --port 8080 --no-access-log
