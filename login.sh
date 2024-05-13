#!/usr/bin/env /bin/bash
cd "/home/$USER"
set -o allexport
source /var/run/startup_environment
set +o allexport

/home/login/run_pod.py "$@"