#!/usr/bin/env bash
# Generate self-signed certificates for an iris-ng dev deployment.
#
# The dev compose stack expects:
#   ./certificates/web_certificates/iris_dev_cert.pem    (nginx TLS cert)
#   ./certificates/web_certificates/iris_dev_key.pem     (nginx TLS key)
#   ./certificates/rootCA/irisRootCACert.pem             (root CA bundle)
#   ./certificates/ldap/                                 (LDAP CA dir, can be empty)
#
# Run from the repo root:
#
#     bash scripts/generate_dev_certs.sh                       # auto-detect LAN IPs
#     bash scripts/generate_dev_certs.sh --ip 10.0.0.5         # add a specific IP
#     bash scripts/generate_dev_certs.sh --ip 10.0.0.5 --ip 10.0.0.6
#     bash scripts/generate_dev_certs.sh --no-auto-ip          # localhost-only
#     bash scripts/generate_dev_certs.sh --force               # overwrite existing
#
# LAN IPs detected from the host's network interfaces are added to the cert's
# subjectAltName so the browser doesn't yell about a hostname mismatch when you
# browse to https://<lan-ip>/. localhost + 127.0.0.1 are always included.
#
# Idempotent — refuses to overwrite existing certs unless you pass --force.

set -euo pipefail

FORCE=0
AUTO_IP=1
EXPLICIT_IPS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)
            FORCE=1
            shift
            ;;
        --ip)
            if [[ -z "${2:-}" ]]; then
                echo "ERROR: --ip requires an argument." >&2
                exit 1
            fi
            EXPLICIT_IPS+=("$2")
            shift 2
            ;;
        --no-auto-ip)
            AUTO_IP=0
            shift
            ;;
        -h|--help)
            sed -n '2,19p' "$0"
            exit 0
            ;;
        *)
            echo "ERROR: unknown option: $1" >&2
            echo "Run with -h for help." >&2
            exit 1
            ;;
    esac
done

CERT_DIR="./certificates"
WEB_DIR="${CERT_DIR}/web_certificates"
ROOTCA_DIR="${CERT_DIR}/rootCA"
LDAP_DIR="${CERT_DIR}/ldap"

WEB_CERT="${WEB_DIR}/iris_dev_cert.pem"
WEB_KEY="${WEB_DIR}/iris_dev_key.pem"
ROOTCA_CERT="${ROOTCA_DIR}/irisRootCACert.pem"

if ! command -v openssl >/dev/null 2>&1; then
    echo "ERROR: openssl is not installed. Install it (e.g. apt install openssl, brew install openssl, or git-bash on Windows)." >&2
    exit 1
fi

# Prevent MSYS / git-bash on Windows from rewriting `-subj "/CN=..."` into a
# Windows path (turns into `C:/Program Files/Git/CN=...`). No-op on Linux/macOS.
export MSYS_NO_PATHCONV=1

# ---------------------------------------------------------------------------
# Detect LAN IPv4 addresses across Linux / macOS / git-bash-on-Windows / WSL.
# Returns deduped IPv4 addresses, one per line, excluding 127.x and link-local.
# ---------------------------------------------------------------------------
detect_lan_ips() {
    local raw=""
    # Linux: `ip` (iproute2)
    if command -v ip >/dev/null 2>&1; then
        raw="$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 || true)"
    fi
    # macOS / BSD / some Linux: `ifconfig`
    if [[ -z "$raw" ]] && command -v ifconfig >/dev/null 2>&1; then
        raw="$(ifconfig 2>/dev/null | awk '/inet / {print $2}' || true)"
    fi
    # Windows (git-bash / MSYS): `ipconfig`
    if [[ -z "$raw" ]] && command -v ipconfig >/dev/null 2>&1; then
        raw="$(ipconfig 2>/dev/null | grep -i 'IPv4' | awk -F: '{print $2}' | tr -d ' \r' || true)"
    fi
    echo "$raw" \
        | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' \
        | grep -v '^127\.' \
        | grep -v '^169\.254\.' \
        | sort -u
}

# Build the subjectAltName string.
SAN_PARTS=("DNS:iris.app.dev" "DNS:localhost" "IP:127.0.0.1")

# Auto-detected LAN IPs.
DETECTED_IPS=()
if [[ "$AUTO_IP" -eq 1 ]]; then
    while IFS= read -r ip; do
        [[ -z "$ip" ]] && continue
        DETECTED_IPS+=("$ip")
        SAN_PARTS+=("IP:${ip}")
    done < <(detect_lan_ips || true)
fi

# Explicit --ip flags.
for ip in "${EXPLICIT_IPS[@]}"; do
    SAN_PARTS+=("IP:${ip}")
done

# Join with commas.
SAN_STR="$(IFS=, ; echo "${SAN_PARTS[*]}")"

mkdir -p "${WEB_DIR}" "${ROOTCA_DIR}" "${LDAP_DIR}"
touch "${LDAP_DIR}/.gitkeep"

if [[ -f "${WEB_CERT}" && -f "${WEB_KEY}" && -f "${ROOTCA_CERT}" && "${FORCE}" -ne 1 ]]; then
    echo "Certs already present in ${CERT_DIR}/. Pass --force to regenerate."
    exit 0
fi

echo "Generating self-signed nginx TLS cert (${WEB_CERT})..."
echo "  subjectAltName: ${SAN_STR}"
openssl req -x509 -newkey rsa:4096 -sha256 -days 365 -nodes \
    -keyout "${WEB_KEY}" \
    -out "${WEB_CERT}" \
    -subj "/CN=iris.app.dev/O=iris-ng-dev/C=US" \
    -addext "subjectAltName=${SAN_STR}" \
    2>/dev/null

chmod 644 "${WEB_CERT}"
# 644 (not the textbook 600) because the key is bind-mounted into the nginx
# container, which runs as www-data (UID 33) — a different UID than the host
# user that runs this script. 600 would mean only the host owner can read the
# file, and nginx-in-container gets EACCES. This is a self-signed dev cert,
# not a real secret; for production, ship a real cert and tighten perms via
# Docker secrets or a build-time COPY with chown.
chmod 644 "${WEB_KEY}"

echo "Generating placeholder root CA cert (${ROOTCA_CERT})..."
# IRIS mounts a root CA bundle for trusted-client-cert support. For dev this
# can just be a self-signed CA that's not actually used. The file needs to
# exist and be a valid PEM cert so mounts succeed and ca-certificates accepts it.
openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
    -keyout /tmp/iris_rootca_key.pem \
    -out "${ROOTCA_CERT}" \
    -subj "/CN=iris-ng dev rootCA/O=iris-ng-dev/C=US" \
    2>/dev/null
rm -f /tmp/iris_rootca_key.pem

chmod 644 "${ROOTCA_CERT}"

echo ""
echo "Done. Generated:"
echo "  - ${WEB_CERT}    (nginx TLS, 365-day expiry)"
echo "  - ${WEB_KEY}     (nginx TLS key)"
echo "  - ${ROOTCA_CERT}    (root CA placeholder, 3650-day expiry)"
echo "  - ${LDAP_DIR}/                        (empty, for optional LDAP CA bundle)"
echo ""
echo "Cert valid for: localhost, 127.0.0.1$(
    if [[ ${#DETECTED_IPS[@]} -gt 0 ]]; then
        printf ', %s' "${DETECTED_IPS[@]}"
    fi
)$(
    if [[ ${#EXPLICIT_IPS[@]} -gt 0 ]]; then
        printf ', %s' "${EXPLICIT_IPS[@]}"
    fi
)"
echo "Browser will warn about the self-signed cert on first visit — that's expected for dev."
echo "For production, replace these with certs from your real CA before deploying."
