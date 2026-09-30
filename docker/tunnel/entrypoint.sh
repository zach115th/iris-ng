#!/bin/sh
# iris-ng guest-portal tunnel agent.
#
# Every POLL_SECONDS: GET the tunnel config from IRIS-NG (shared key), and if
# the mode or token changed (or cloudflared died) restart cloudflared in that
# mode; then POST a status heartbeat (mode, connected, hostname, version,
# last error). Only the portal-only nginx server block (PORTAL_PORT) is ever
# published through the tunnel.
#
#   quick : cloudflared tunnel --url http://nginx:PORT   (random trycloudflare host)
#   named : cloudflared tunnel run --token TOKEN         (hostname set in Zero Trust)
set -u

IRIS_URL="${IRIS_URL:-http://${IRIS_UPSTREAM_SERVER:-app}:${IRIS_UPSTREAM_PORT:-8000}}"
KEY="${PORTAL_TUNNEL_AGENT_KEY:-}"
PORT="${PORTAL_PORT:-8081}"
POLL="${POLL_SECONDS:-15}"
METRICS="127.0.0.1:2000"
LOG=/tmp/cloudflared.log

if [ -z "$KEY" ]; then
    echo "tunnel-agent: PORTAL_TUNNEL_AGENT_KEY is not set; nothing to do." >&2
    exit 1
fi

cur_mode=""; cur_token=""; cf_pid=""

start_cf() {
    mode="$1"; token="$2"
    : > "$LOG"
    if [ "$mode" = "named" ]; then
        cloudflared tunnel --no-autoupdate --metrics "0.0.0.0:2000" run --token "$token" >> "$LOG" 2>&1 &
    else
        cloudflared tunnel --no-autoupdate --metrics "0.0.0.0:2000" --url "http://nginx:${PORT}" >> "$LOG" 2>&1 &
    fi
    cf_pid=$!
    cur_mode="$mode"; cur_token="$token"
    echo "tunnel-agent: started cloudflared in ${mode} mode (pid ${cf_pid})"
}

stop_cf() {
    if [ -n "$cf_pid" ] && kill -0 "$cf_pid" 2>/dev/null; then
        kill "$cf_pid" 2>/dev/null; wait "$cf_pid" 2>/dev/null || true
    fi
    cf_pid=""
}

trap 'stop_cf; exit 0' TERM INT

while true; do
    cfg=$(curl -s -m 8 -H "X-IRIS-Portal-Agent-Key: ${KEY}" "${IRIS_URL}/api/v2/portal/tunnel/config" || true)
    mode=$(printf '%s' "$cfg" | jq -r '.mode // empty' 2>/dev/null)
    token=$(printf '%s' "$cfg" | jq -r '.token // empty' 2>/dev/null)
    err=""
    if [ -z "$mode" ]; then
        err="IRIS-NG did not answer the config request (key rejected or app down)"
        echo "tunnel-agent: ${err}" >&2
    else
        if [ "$mode" = "named" ] && [ -z "$token" ]; then
            err="named mode selected but no token stored"
            stop_cf; cur_mode=""; cur_token=""
        else
            alive=0
            [ -n "$cf_pid" ] && kill -0 "$cf_pid" 2>/dev/null && alive=1
            if [ "$mode" != "$cur_mode" ] || [ "$token" != "$cur_token" ] || [ "$alive" = "0" ]; then
                stop_cf
                start_cf "$mode" "$token"
                sleep 4
            fi
        fi
    fi
    connected=false
    curl -s -f -m 3 "http://${METRICS}/ready" >/dev/null 2>&1 && connected=true
    host=""
    if [ "$cur_mode" = "quick" ]; then
        host=$(curl -s -m 3 "http://${METRICS}/quicktunnel" 2>/dev/null | jq -r '.hostname // empty' 2>/dev/null)
    fi
    # cloudflared logs "ERR <msg>" for runtime failures but a bare
    # "Provided Tunnel token is not valid." for a rejected token; report the
    # newest line that is not an INF line, whatever its shape.
    [ -z "$err" ] && err=$(grep -vE ' INF |^[[:space:]]*$|--help' "$LOG" 2>/dev/null | tail -1 | cut -c1-400)
    version=$(cloudflared --version 2>/dev/null | head -1)
    body=$(jq -n --arg mode "${cur_mode:-$mode}" --argjson connected "$connected" --arg host "$host" \
              --arg version "$version" --arg error "$err" \
              '{mode:$mode, connected:$connected, hostname:$host, version:$version, error:$error, agent:"docker/tunnel"}')
    curl -s -m 8 -o /dev/null -H "X-IRIS-Portal-Agent-Key: ${KEY}" -H 'Content-Type: application/json' \
         -X POST --data "$body" "${IRIS_URL}/api/v2/portal/tunnel/status" || true
    sleep "$POLL"
done
