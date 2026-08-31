#!/usr/bin/env bash
git pull --rebase
workon sapl
pip install -r requirements/dev-requirements.txt
./manage.py migrate
./manage.py bower install
./manage.py collectstatic --noinput
deactivate
sudo supervisorctl restart sapl
# Materializacao do PDF-alvo (ADR 0014): reinicia junto do deploy para pegar
# codigo novo. Se o programa ainda nao existe no supervisor, instalar com
# scripts/supervisor-materializacao.conf (instrucoes no cabecalho do arquivo).
sudo supervisorctl restart sapl-materializacao \
  || echo "AVISO: programa sapl-materializacao nao instalado no supervisor — sem ele, materia protocolada NAO vira pendencia no app (ver scripts/supervisor-materializacao.conf)"
