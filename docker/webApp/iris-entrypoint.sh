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

# iris-ng: each process is exec'd - it becomes the container's main process.
# Before, it ran in the background behind a `sleep` loop, so a worker that
# exited (its database not reachable at start) left its container Up with
# nothing running, and the restart policy never fired. Now the container stops
# with it and Docker / Kubernetes start it again; SIGTERM from a stop reaches
# the process itself instead of a shell that ignored it.
if [[ "${target}" == iris-worker ]] ; then
    # The default 'celery' queue only: AI jobs (ai_queue) belong to iris-ai-worker,
    # one at a time. Without -Q this worker consumed ai_queue too, so long AI
    # jobs took the slots module hooks, imports and MISP sync need. Where no AI
    # worker runs, set IRIS_WORKER_QUEUES=celery,ai_queue (the Helm chart does
    # when irisaiworker.enabled is false).
    WORKER_QUEUES="${IRIS_WORKER_QUEUES:-celery}"
    if [[ -z $NUMBER_OF_CHILD ]]; then
        exec celery -A app.celery worker -E -B -Q "$WORKER_QUEUES" -l $LOG_LEVEL
    else
        exec celery -A app.celery worker -c $NUMBER_OF_CHILD -E -B -Q "$WORKER_QUEUES" -l $LOG_LEVEL
    fi
elif [[ "${target}" == iris-ai-worker ]] ; then
    # iris-next: dedicated async-AI worker (docs/19 §5b.3). Consumes ONLY the
    # ai_queue with concurrency 1 so exactly one model call is in flight at a
    # time — the single LM Studio GPU stream is the bottleneck, so this queue
    # is the load bound. Separate from the default worker so AI jobs never
    # compete with MISP-sync / module hooks. No beat (-B) here — that's the
    # default worker's job.
    exec celery -A app.celery worker -E -Q ai_queue --concurrency=1 -n ai-worker@%h -l $LOG_LEVEL
else
    exec gunicorn app:app --bind 0.0.0.0:8000 --timeout 600 --worker-connections 1000 --threads 100 -w 1 --log-level=info
fi

