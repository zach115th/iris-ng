# Must track the runtime in docker/webApp/Dockerfile (python:3.12-slim,
# Debian trixie). A devcontainer on a different interpreter than the one
# shipped is worse than none - it fails, or passes, for reasons production
# will not reproduce. This sat on 3.9 long enough to stop importing the app
# at all (PEP 604 unions in access_controls.py and 6 other modules).
FROM mcr.microsoft.com/devcontainers/python:3.12-trixie

ENV PYTHONUNBUFFERED 1

# [Optional] If your requirements rarely change, uncomment this section to add them to the image.
# COPY requirements.txt /tmp/pip-tmp/
# RUN pip3 --disable-pip-version-check --no-cache-dir install -r /tmp/pip-tmp/requirements.txt \
#    && rm -rf /tmp/pip-tmp

# [Optional] Uncomment this section to install additional OS packages.
# RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
#     && apt-get -y install --no-install-recommends <your-package-list-here>



