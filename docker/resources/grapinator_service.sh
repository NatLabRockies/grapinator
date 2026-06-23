#!/usr/bin/env sh
# Author: David Martin
# Launch the Grapinator GraphQL service under Gunicorn (replaces CherryPy in 2.1.12).

cd /opt/grapinator
source venv/bin/activate
exec gunicorn \
    --config /opt/grapinator/grapinator/resources/gunicorn.conf.py \
    grapinator.svc_gunicorn:application
