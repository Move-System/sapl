#!/usr/bin/env bash

git_project_root=$(git rev-parse --show-toplevel)
cd ${git_project_root}

python -c "from sapl.settings import SGVP_APPS; print(*[s.split('.')[-1] for s in SGVP_APPS])" | xargs -t ./manage.py graph_models -d -g -o zzz.png -l fdp
