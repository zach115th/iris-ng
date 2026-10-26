# iris-ng guest-portal tunnel agent: cloudflared plus a small loop that asks
# the IRIS-NG instance which tunnel mode to run (quick / named) and reports
# the tunnel's status back. The official cloudflared image has no shell, so
# the binary is copied into a minimal Alpine with curl + jq.
# Pinned, never :latest: `up --build` does not re-pull a cached :latest, so an
# install kept the cloudflared it first built with. Dependabot tracks the tag.
# 2026.10.2+ distrusts the compromised eMudhra intermediates (Go 1.27.3).
FROM cloudflare/cloudflared:2026.10.4 AS cf

FROM alpine:3.24
RUN apk add --no-cache curl jq ca-certificates
COPY --from=cf /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
