"""Autossupervisão do laço de materialização (ADR 0015).

O problema que este módulo mata: o SAPL de produção roda fora de docker, e o
laço de materialização dependia de alguém LEMBRAR de subi-lo (nohup, supervisor,
cron — todos exigem um ato manual que já falhou uma vez, IND 826/2026). O único
processo cuja existência é garantida é o próprio web: o hub bate na API de
integração o tempo inteiro, e cada request é um marca-passo de graça.

Então: o laço grava um batimento no banco a cada tick (`BatimentoLaco`); este
middleware, no máximo uma vez por minuto por worker, confere o batimento e —
se ele envelheceu ou nunca existiu — ressuscita o laço como processo separado e
desgarrado (mesmo padrão do botão "Rodar agora" do painel: `start_new_session`,
processo sobrevive ao reload do worker).

Corrida entre N workers ressuscitando ao mesmo tempo: inofensiva por
construção — o laço que sobe e encontra batimento fresco de outro pid SAI na
hora (guarda de instância única no próprio comando), e o lock de passada já
impedia conversão dupla de qualquer forma.

Desligável por `MATERIALIZACAO_AUTOSSUPERVISAO=False` (ambiente onde o laço é
gerido por supervisor/systemd e não se quer o respawn automático).
"""
import logging
import os
import subprocess
import sys
import time

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed

logger = logging.getLogger(__name__)

# No máximo uma consulta ao batimento por minuto POR WORKER: o custo por
# request no caminho quente é uma comparação de monotonic.
INTERVALO_VERIFICACAO_SEGUNDOS = 60

_ultima_verificacao = 0.0


def laco_precisa_subir():
    """Batimento ausente ou envelhecido = não há laço vivo."""
    from sapl.integracao_hub.models import BatimentoLaco
    batimento = BatimentoLaco.objects.first()
    return batimento is None or not batimento.fresco


def subir_laco():
    """Sobe o laço como processo separado e desgarrado (padrão do painel).

    Intervalo/tick vêm das mesmas variáveis de ambiente do start.sh do
    container — uma configuração só, seja quem for que suba o laço.
    """
    from sapl.integracao_hub.painel import _raiz_do_projeto
    intervalo = os.environ.get('MATERIALIZACAO_INTERVALO_SEGUNDOS', '300')
    tick = os.environ.get('MATERIALIZACAO_TICK_SEGUNDOS', '15')
    comando = [
        sys.executable, '-m', 'django',
        'materializar_pdfs_para_assinatura',
        '--intervalo', intervalo,
        '--tick', tick,
    ]
    ambiente = os.environ.copy()
    ambiente.setdefault('DJANGO_SETTINGS_MODULE', 'sapl.settings')
    subprocess.Popen(
        comando,
        cwd=_raiz_do_projeto(),
        env=ambiente,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True)
    logger.warning(
        'autossupervisao: laco de materializacao sem batimento — novo laco '
        'disparado (intervalo=%ss, tick=%ss)', intervalo, tick)


class AutossupervisaoMaterializacao:
    def __init__(self, get_response):
        # Em teste, spawnar processo residente por efeito colateral de request
        # seria vazamento; quem testa as peças chama as funções deste módulo.
        if 'pytest' in sys.modules:
            raise MiddlewareNotUsed('autossupervisao desligada sob pytest')
        if not getattr(settings, 'MATERIALIZACAO_AUTOSSUPERVISAO', True):
            raise MiddlewareNotUsed('MATERIALIZACAO_AUTOSSUPERVISAO=False')
        self.get_response = get_response

    def __call__(self, request):
        self._garantir_laco()
        return self.get_response(request)

    def _garantir_laco(self):
        global _ultima_verificacao
        agora = time.monotonic()
        if _ultima_verificacao and agora - _ultima_verificacao < \
                INTERVALO_VERIFICACAO_SEGUNDOS:
            return
        _ultima_verificacao = agora
        try:
            if laco_precisa_subir():
                subir_laco()
        except Exception as exc:  # noqa — a autossupervisão NUNCA pode custar
            # um request: banco sem migração, tabela ausente, falha de spawn —
            # tudo vira log e o SAPL segue servindo.
            logger.warning('autossupervisao: verificacao falhou (%s) — '
                           'seguira tentando a cada %ss', exc,
                           INTERVALO_VERIFICACAO_SEGUNDOS)
