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
