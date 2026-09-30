# iris-ng guest-portal tunnel agent: cloudflared plus a small loop that asks
# the IRIS-NG instance which tunnel mode to run (quick / named) and reports
# the tunnel's status back. The official cloudflared image has no shell, so
# the binary is copied into a minimal Alpine with curl + jq.
FROM cloudflare/cloudflared:latest AS cf

FROM alpine:3.20
RUN apk add --no-cache curl jq ca-certificates
COPY --from=cf /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
