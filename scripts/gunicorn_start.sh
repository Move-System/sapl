#!/usr/bin/env bash

# SCRIPT DE INICIALIZAÇÃO VIA SOKEFILE

# As seen in http://tutos.readthedocs.org/en/latest/source/ndg.html


SGVP_DIR="/var/interlegis/sapl"

# Seta um novo diretório foi passado como raiz para o SGVP
# caso esse tenha sido passado como parâmetro
if [ "$1" ]
then
    SGVP_DIR="$1"
fi

NAME="SGVP"                                     # Name of the application (*)
DJANGODIR="$SGVP_DIR/"                          # Django project directory (*)
SOCKFILE="$SGVP_DIR/run/gunicorn.sock"          # we will communicate using this unix socket (*)
USER=`whoami`                                   # the user to run as (*)
GROUP=`whoami`                                  # the group to run as (*)
NUM_WORKERS=3                                   # how many worker processes should Gunicorn spawn (*)
                                                # NUM_WORKERS = 2 * CPUS + 1
TIMEOUT=60
MAX_REQUESTS=100                                # number of requests before restarting worker
DJANGO_SETTINGS_MODULE=sapl.settings            # which settings file should Django use (*)
DJANGO_WSGI_MODULE=sapl.wsgi                    # WSGI module name (*)

echo "Starting $NAME as `whoami` on base dir $SGVP_DIR"

# Ativa ambiente virtual
cd $DJANGODIR
source $SGVP_DIR/../.virtualenvs/sapl/bin/activate

export DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE
export PYTHONPATH=$DJANGODIR:$PYTHONPATH

# Create the run directory if it doesn't exist
RUNDIR=$(dirname $SOCKFILE)
test -d $RUNDIR || mkdir -p $RUNDIR

# Start your Django Unicorn
# Programs meant to be run under supervisor should not daemonize themselves (do not use --daemon)
exec gunicorn ${DJANGO_WSGI_MODULE}:application \
  --name $NAME \
  --log-level debug \
  --timeout $TIMEOUT \
  --workers $NUM_WORKERS \
  --max-requests $MAX_REQUESTS \
  --user $USER \
  --access-logfile /var/log/sapl/access.log \
  --error-logfile /var/log/sapl/error.log \
  --bind=unix:$SOCKFILE
  
