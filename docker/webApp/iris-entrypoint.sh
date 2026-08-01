#!/bin/bash

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




target=${1-:app}

if [[ -z $LOG_LEVEL ]]; then
  LOG_LEVEL='info'
fi

printf "Running ${target} ...\n"

if [[ "${target}" == iris-worker ]] ; then
    if [[ -z $NUMBER_OF_CHILD ]]; then
        celery -A app.celery worker -E -B -l $LOG_LEVEL &
    else
        celery -A app.celery worker -c $NUMBER_OF_CHILD -E -B -l $LOG_LEVEL &
    fi
elif [[ "${target}" == iris-ai-worker ]] ; then
    # iris-next: dedicated async-AI worker (docs/19 §5b.3). Consumes ONLY the
    # ai_queue with concurrency 1 so exactly one model call is in flight at a
    # time — the single LM Studio GPU stream is the bottleneck, so this queue
    # is the load bound. Separate from the default worker so AI jobs never
    # compete with MISP-sync / module hooks. No beat (-B) here — that's the
    # default worker's job.
    celery -A app.celery worker -E -Q ai_queue --concurrency=1 -n ai-worker@%h -l $LOG_LEVEL &
else
    gunicorn app:app --bind 0.0.0.0:8000 --timeout 600 --worker-connections 1000 --threads 100 -w 1 --log-level=info &
fi

while true; do sleep 2; done

