#!/bin/bash

###############################################################################
# Script de Instalação do Módulo TCE
# Versão: 1.0
# Data: 03/10/2025
###############################################################################

set -e  # Parar em caso de erro

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Função para log
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Verificar se está rodando como root ou com sudo
if [ "$EUID" -eq 0 ]; then
    log_warn "Rodando como root. Certifique-se de que as permissões estão corretas."
fi

###############################################################################
# 1. VERIFICAÇÕES INICIAIS
###############################################################################

log_info "Verificando ambiente..."

# Verificar se o Python está disponível
if ! command -v python3 &> /dev/null; then
    log_error "Python3 não encontrado. Instale o Python 3.8 ou superior."
    exit 1
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}')
log_info "Python versão: $PYTHON_VERSION"

# Verificar se o virtualenv está ativado
if [ -z "$VIRTUAL_ENV" ]; then
    log_warn "Virtualenv não está ativado. Ativando..."

    # Tentar encontrar o virtualenv
    if [ -d "/opt/venv" ]; then
        source /opt/venv/bin/activate
        log_info "Virtualenv ativado: /opt/venv"
    elif [ -d "venv" ]; then
        source venv/bin/activate
        log_info "Virtualenv ativado: venv"
    else
        log_error "Virtualenv não encontrado. Ative manualmente antes de executar."
        exit 1
    fi
fi

# Verificar se o Django está instalado
if ! python3 -c "import django" &> /dev/null; then
    log_error "Django não encontrado. Instale o Django primeiro."
    exit 1
fi

DJANGO_VERSION=$(python3 -c "import django; print(django.get_version())")
log_info "Django versão: $DJANGO_VERSION"

###############################################################################
# 2. INSTALAR DEPENDÊNCIAS
###############################################################################

log_info "Instalando dependências do módulo TCE..."

pip install --upgrade pip

# Instalar pyhanko e dependências
log_info "Instalando pyhanko (assinatura digital)..."
pip install pyhanko==0.31.0 pyhanko-certvalidator==0.29.0

# Instalar dependências complementares
log_info "Instalando dependências complementares..."
pip install cryptography>=43.0.3 requests>=2.31.0 python-dateutil>=2.8.0 tzlocal>=5.0.0

# Verificar instalação
log_info "Verificando instalação das bibliotecas..."
python3 -c "from pyhanko.sign import signers; print('✓ PyHanko instalado com sucesso')" || {
    log_error "Falha ao instalar pyhanko"
    exit 1
}

python3 -c "from pyhanko_certvalidator import ValidationContext; print('✓ Certvalidator instalado com sucesso')" || {
    log_error "Falha ao instalar pyhanko-certvalidator"
    exit 1
}

###############################################################################
# 3. EXECUTAR MIGRAÇÕES
###############################################################################

log_info "Executando migrações do banco de dados..."

python3 manage.py migrate tce

log_info "Migrações concluídas com sucesso"

###############################################################################
# 4. CRIAR DIRETÓRIOS DE UPLOAD
###############################################################################

log_info "Criando diretórios para uploads..."

# Detectar MEDIA_ROOT do Django
MEDIA_ROOT=$(python3 -c "from django.conf import settings; print(settings.MEDIA_ROOT)" 2>/dev/null || echo "media")

mkdir -p "$MEDIA_ROOT/tce/arquivos"
mkdir -p "$MEDIA_ROOT/tce/reduzidos"
mkdir -p "$MEDIA_ROOT/tce/ocr"
mkdir -p "$MEDIA_ROOT/tce/assinados"
mkdir -p "$MEDIA_ROOT/tce/p7s"

log_info "Diretórios criados em: $MEDIA_ROOT/tce/"

# Configurar permissões
if [ -d "$MEDIA_ROOT/tce" ]; then
    # Tentar detectar o usuário do servidor web
    WEB_USER=""
    if id "www-data" &>/dev/null; then
        WEB_USER="www-data"
    elif id "apache" &>/dev/null; then
        WEB_USER="apache"
    elif id "nginx" &>/dev/null; then
        WEB_USER="nginx"
    fi

    if [ -n "$WEB_USER" ]; then
        log_info "Configurando permissões para o usuário: $WEB_USER"
        chown -R "$WEB_USER:$WEB_USER" "$MEDIA_ROOT/tce" 2>/dev/null || log_warn "Não foi possível alterar o owner. Execute com sudo se necessário."
    else
        log_warn "Usuário do servidor web não detectado. Configure as permissões manualmente."
    fi

    chmod -R 755 "$MEDIA_ROOT/tce"
    log_info "Permissões configuradas: 755"
fi

###############################################################################
# 5. COLETAR ARQUIVOS ESTÁTICOS
###############################################################################

log_info "Coletando arquivos estáticos..."

python3 manage.py collectstatic --noinput

log_info "Arquivos estáticos coletados"

###############################################################################
# 6. VERIFICAÇÕES FINAIS
###############################################################################

log_info "Realizando verificações finais..."

# Verificar se o app TCE está instalado
python3 manage.py showmigrations tce | grep -q "\[X\]" && log_info "✓ Migrações TCE aplicadas" || log_error "✗ Migrações TCE não aplicadas"

# Listar URLs do módulo TCE
log_info "URLs do módulo TCE registradas:"
python3 manage.py show_urls 2>/dev/null | grep "tce" || log_warn "Comando show_urls não disponível"

###############################################################################
# 7. REINICIAR SERVIÇOS
###############################################################################

log_info "Preparando para reiniciar serviços..."

# Detectar serviço
SERVICE=""
if systemctl list-units --type=service | grep -q "gunicorn"; then
    SERVICE="gunicorn"
elif systemctl list-units --type=service | grep -q "uwsgi"; then
    SERVICE="uwsgi"
elif systemctl list-units --type=service | grep -q "apache2"; then
    SERVICE="apache2"
elif systemctl list-units --type=service | grep -q "httpd"; then
    SERVICE="httpd"
fi

if [ -n "$SERVICE" ]; then
    log_info "Serviço detectado: $SERVICE"
    read -p "Deseja reiniciar o serviço $SERVICE agora? (s/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[SsYy]$ ]]; then
        sudo systemctl restart "$SERVICE"
        log_info "Serviço $SERVICE reiniciado"

        # Reiniciar nginx se existir
        if systemctl list-units --type=service | grep -q "nginx"; then
            sudo systemctl restart nginx
            log_info "Nginx reiniciado"
        fi
    else
        log_warn "Lembre-se de reiniciar o serviço manualmente:"
        log_warn "  sudo systemctl restart $SERVICE"
    fi
else
    log_warn "Serviço web não detectado automaticamente."
    log_warn "Reinicie manualmente seu servidor web (Apache/Nginx/Gunicorn/uWSGI)"
fi

###############################################################################
# 8. RESUMO
###############################################################################

echo ""
log_info "=========================================="
log_info "Instalação do Módulo TCE Concluída!"
log_info "=========================================="
echo ""
log_info "Próximos passos:"
echo "  1. Acesse: http://seu-servidor/tce/admin/"
echo "  2. Crie um novo processo TCE"
echo "  3. Faça upload de documentos"
echo "  4. Teste a assinatura digital (aba 4 do wizard)"
echo ""
log_info "Dependências instaladas:"
echo "  ✓ pyhanko 0.31.0"
echo "  ✓ pyhanko-certvalidator 0.29.0"
echo "  ✓ cryptography >= 43.0.3"
echo ""
log_info "Diretórios criados:"
echo "  $MEDIA_ROOT/tce/"
echo ""
log_info "Para mais informações, consulte:"
echo "  - INSTRUCOES_DEPLOY_TCE.md"
echo "  - Logs do servidor web"
echo ""
log_info "=========================================="

exit 0
