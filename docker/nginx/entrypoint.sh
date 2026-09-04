#!/usr/bin/env bash

#  IRIS Source Code
#  Copyright (C) 2021 - Airbus CyberSecurity (SAS)
#  ir@cyberactionlab.net
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3 of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

set -e

# -----------------------------------------------------------------------------
# TLS preflight.
#
# The certificate is supplied by the operator: the directory comes from CERT_DIR
# (a compose-level bind mount onto /www/certs/, not an nginx variable) and the
# filenames from CERT_FILENAME / KEY_FILENAME, resolved relative to it.
#
# Without this check both likely misconfigurations -- wrong path, and a key
# nginx's own user cannot read -- surface only as a raw SSL error from a
# crash-looping container, which names the container path but not the variable
# that produced it or the host directory behind the mount.
# -----------------------------------------------------------------------------
CERT_PATH="/www/certs/${CERT_FILENAME}"
KEY_PATH="/www/certs/${KEY_FILENAME}"

tls_fail() {
    cat >&2 <<EOF
FATAL: $1

nginx cannot start without a readable TLS certificate and private key.

  cert : ${CERT_PATH}
         (CERT_FILENAME=${CERT_FILENAME:-<unset>})
  key  : ${KEY_PATH}
         (KEY_FILENAME=${KEY_FILENAME:-<unset>})

/www/certs/ is the container-side mount of CERT_DIR on the host
(default: ./certificates/web_certificates).

Common causes:
  * Certificates were never generated.
        bash scripts/generate_dev_certs.sh
  * CERT_DIR points at the wrong host directory. Check it in .env.
  * Let's Encrypt: the files under live/<domain>/ are SYMLINKS into
    ../../archive/. Mounting only live/<domain> leaves them dangling in the
    container. Point CERT_DIR at the whole tree instead:
        CERT_DIR=/etc/letsencrypt
        CERT_FILENAME=live/<domain>/fullchain.pem
        KEY_FILENAME=live/<domain>/privkey.pem
  * Permission denied: nginx runs here as $(id -un) (uid $(id -u)), while
    certbot creates archive/ as 0700 root:root. Grant read access on the host.

EOF
    exit 1
}

[ -n "${CERT_FILENAME}" ] || tls_fail "CERT_FILENAME is not set."
[ -n "${KEY_FILENAME}" ]  || tls_fail "KEY_FILENAME is not set."

# -L before -e: a dangling symlink fails -e, and saying so explicitly is the
# difference between a five-minute fix and an hour. This is the exact shape of
# the Let's Encrypt live/ -> archive/ mistake.
for pair in "certificate:${CERT_PATH}" "private key:${KEY_PATH}"; do
    label="${pair%%:*}"; path="${pair#*:}"
    if [ -L "${path}" ] && [ ! -e "${path}" ]; then
        tls_fail "${label} is a symlink whose target does not exist inside the container: ${path}"
    fi
    [ -e "${path}" ] || tls_fail "${label} not found: ${path}"
    [ -r "${path}" ] || tls_fail "${label} exists but is not readable by $(id -un): ${path}"
done

# envsubst substitutes every $variable it is given. The nginx config contains
# nginx's own variables ($host, $csp_header, $remote_addr ...), so the list below
# is an explicit allowlist -- without it every nginx variable would be replaced
# by an empty string and the config would be nonsense.
#
# ANY new ${PLACEHOLDER} added to nginx.conf must also be added here. An unlisted
# placeholder is left in the output verbatim; for ANALYTICS_ORIGIN that means a
# literal "${ANALYTICS_ORIGIN}" inside the Content-Security-Policy header, which
# browsers may reject wholesale -- disabling CSP entirely while nginx starts
# cleanly and every page still looks correct.
envsubst '${INTERFACE_HTTPS_PORT} ${IRIS_UPSTREAM_SERVER} ${IRIS_UPSTREAM_PORT} ${SERVER_NAME} ${KEY_FILENAME} ${CERT_FILENAME} ${IRIS_FRONTEND_SERVER} ${IRIS_FRONTEND_PORT} ${ANALYTICS_ORIGIN}' < /etc/nginx/nginx.conf > /tmp/nginx.conf
cp /tmp/nginx.conf /etc/nginx/nginx.conf
rm /tmp/nginx.conf

exec nginx -g "daemon off;"
