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
#     bash scripts/generate_dev_certs.sh
#
# Idempotent — refuses to overwrite existing certs unless you pass --force.

set -euo pipefail

FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

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

mkdir -p "${WEB_DIR}" "${ROOTCA_DIR}" "${LDAP_DIR}"
touch "${LDAP_DIR}/.gitkeep"

if [[ -f "${WEB_CERT}" && -f "${WEB_KEY}" && -f "${ROOTCA_CERT}" && "${FORCE}" -ne 1 ]]; then
    echo "Certs already present in ${CERT_DIR}/. Pass --force to regenerate."
    exit 0
fi

echo "Generating self-signed nginx TLS cert (${WEB_CERT})..."
openssl req -x509 -newkey rsa:4096 -sha256 -days 365 -nodes \
    -keyout "${WEB_KEY}" \
    -out "${WEB_CERT}" \
    -subj "/CN=iris.app.dev/O=iris-ng-dev/C=US" \
    -addext "subjectAltName=DNS:iris.app.dev,DNS:localhost,IP:127.0.0.1" \
    >/dev/null 2>&1

chmod 644 "${WEB_CERT}"
chmod 600 "${WEB_KEY}"

echo "Generating placeholder root CA cert (${ROOTCA_CERT})..."
# IRIS mounts a root CA bundle for trusted-client-cert support. For dev this
# can just be a self-signed CA that's not actually used. The file needs to
# exist and be a valid PEM cert so mounts succeed and ca-certificates accepts it.
openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
    -keyout /tmp/iris_rootca_key.pem \
    -out "${ROOTCA_CERT}" \
    -subj "/CN=iris-ng dev rootCA/O=iris-ng-dev/C=US" \
    >/dev/null 2>&1
rm -f /tmp/iris_rootca_key.pem

chmod 644 "${ROOTCA_CERT}"

echo ""
echo "Done. Generated:"
echo "  - ${WEB_CERT}    (nginx TLS, 365-day expiry)"
echo "  - ${WEB_KEY}     (nginx TLS key)"
echo "  - ${ROOTCA_CERT}    (root CA placeholder, 3650-day expiry)"
echo "  - ${LDAP_DIR}/                        (empty, for optional LDAP CA bundle)"
echo ""
echo "Browser will warn about the self-signed cert on first visit — that's expected for dev."
echo "For production, replace these with certs from your real CA before deploying."
