"""Painel de operação da materialização do PDF-alvo (refinamento §5).

Por que esta tela existe, em uma frase: até 25/08/2026 a única forma de saber o
que a materialização tinha feito era abrir o shell da VPS, e o operador da casa
legislativa não tem esse acesso — nem nós.

O episódio que a motivou: as proposições fluíam normalmente, mas nenhuma
pendência de assinatura chegava ao app. O diagnóstico consumiu três idas e
voltas com o administrador do servidor para terminar num valor de variável de
ambiente (`SAPL_INTERNAL_URL` apontando para um endereço que só existia dentro
da VPS, produzindo `código -4` em 861 matérias). Todos os números necessários
para responder aquilo em dez segundos já eram calculados pela rotina — e jogados
fora no `stdout` de um processo que ninguém estava lendo.

Vive em módulo separado de `views.py` de propósito: aquele arquivo é a superfície
de API consumida pelo hub (DRF, token, `pode_integrar`), este é HTML de operação.
Misturar os dois obrigaria quem mexe na API a ler tela e vice-versa.

**A rotina é disparada como PROCESSO SEPARADO, não em thread.** Duas razões, e
nenhuma é preferência de estilo:

1. A passada é longa — um acervo de ~900 matérias a ~4s de conversão cada leva
   perto de uma hora. Não cabe num request, e uma thread do gunicorn morre com o
   worker que a hospeda, no meio da conversão, sem deixar rastro.
2. O gunicorn roda N workers. Thread por worker significaria N passadas
   convertendo a mesma matéria ao mesmo tempo.

O que serializa tudo isso é o índice único de `PassadaMaterializacao.em_andamento`
(ver o docstring do modelo): o banco recusa a segunda passada, seja ela do laço
ou de um segundo clique.
"""
import logging
import os
import subprocess
import sys

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.generic import TemplateView, View

from .models import (DocumentoParaAssinatura, MateriaComFalhaMaterializacao,
                     PassadaMaterializacao)

logger = logging.getLogger(__name__)

PERMISSAO = 'integracao_hub.pode_integrar'

# Quantas passadas o painel mostra. O laço roda a cada 300s por padrão, então
# 20 linhas cobrem em torno de uma hora e meia — o suficiente para responder
# "está rodando?" e "o que mudou desde que eu mexi na configuração?" sem virar
# um relatório que ninguém lê.
PASSADAS_NO_PAINEL = 20

# Quantas matérias travadas listar. Quando o ambiente cai, TODAS falham pelo
# mesmo motivo; listar 900 linhas idênticas esconde justamente o caso
# interessante, que é a matéria que falha sozinha.
FALHAS_NO_PAINEL = 50


def _raiz_do_projeto():
    """Diretório de onde o `manage.py` roda — e onde o `sapl.log` é escrito.

    `settings.BASE_DIR` aponta para o pacote `sapl/`; a raiz é o pai dele. O
    `cwd` importa: o handler de log do SAPL usa caminho RELATIVO
    (`settings.py`, handler `applogfile`), então rodar de outro diretório
    espalharia `sapl.log` por onde o processo tivesse sido disparado.
    """
    return os.path.dirname(str(settings.BASE_DIR))


class PainelMaterializacaoView(PermissionRequiredMixin, TemplateView):
    """O que a rotina fez, o que está travado, e por quê."""

    template_name = 'integracao_hub/painel_materializacao.html'
    permission_required = (PERMISSAO,)
    raise_exception = True

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)

        em_andamento = PassadaMaterializacao.objects.filter(
            em_andamento=True).first()

        passadas = list(PassadaMaterializacao.objects
                        .all()[:PASSADAS_NO_PAINEL])

        falhas = list(MateriaComFalhaMaterializacao.objects
                      .select_related('materia')[:FALHAS_NO_PAINEL])

        total_falhas = MateriaComFalhaMaterializacao.objects.count()

        contexto.update({
            'em_andamento': em_andamento,
            'passadas': passadas,
            # A última CONCLUÍDA é a que responde "o que a rotina fez": a linha
            # em andamento ainda tem contadores zerados e passaria a impressão
            # falsa de que nada foi feito.
            'ultima_concluida': next(
                (p for p in passadas if p.terminada_em), None),
            'nunca_rodou': not passadas,
            'falhas': falhas,
            'total_falhas': total_falhas,
            'falhas_ocultas': max(0, total_falhas - len(falhas)),
            'alvos_materializados': DocumentoParaAssinatura.objects.count(),
            # A configuração que decide o sucesso da conversão fica na tela
            # porque foi exatamente ela a causa do incidente de 25/08 — e lê-la
            # exigia shell.
            'sapl_internal_url': getattr(settings, 'SAPL_INTERNAL_URL', ''),
            'site_url': getattr(settings, 'SITE_URL', ''),
            'onlyoffice_url': getattr(settings, 'ONLYOFFICE_URL', ''),
            'onlyoffice_jwt': getattr(
                settings, 'ONLYOFFICE_JWT_ENABLED', False),
        })
        return contexto


class DispararMaterializacaoView(PermissionRequiredMixin, View):
    """Botão "Rodar agora" — sempre em modo `--somente-novos`.

    **A flag não é configurável aqui, e isso é decisão de segurança, não
    economia de campo.** Sem ela o comando entra em retificação: onde o texto
    mudou depois da conversão, ele regenera o alvo E ZERA a assinatura já feita
    (§5.1). Isso foi decidido para o ato isolado de retificar um texto — numa
    varredura de acervo inteiro, disparada por um clique, apagaria assinaturas
    válidas em lote e sem volta.

    Retificar continua possível pelo fluxo normal, matéria a matéria.
    """

    permission_required = (PERMISSAO,)
    raise_exception = True

    def post(self, request, *args, **kwargs):
        destino = reverse('integracao_hub_painel_materializacao')

        if PassadaMaterializacao.objects.filter(em_andamento=True).exists():
            messages.warning(
                request,
                'Já existe uma passada em andamento. Aguarde ela terminar — '
                'duas passadas simultâneas converteriam o mesmo documento.')
            return HttpResponseRedirect(destino)

        comando = [
            sys.executable, '-m', 'django',
            'materializar_pdfs_para_assinatura',
            '--somente-novos',
            '--disparada-por', (request.user.get_username() or '')[:150],
        ]
        ambiente = os.environ.copy()
        ambiente.setdefault('DJANGO_SETTINGS_MODULE', 'sapl.settings')

        try:
            subprocess.Popen(
                comando,
                cwd=_raiz_do_projeto(),
                env=ambiente,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                # Desliga do processo do gunicorn: sem isso um reload do worker
                # levaria a passada junto, no meio da conversão.
                start_new_session=True)
        except Exception as exc:  # noqa — falha de spawn é diagnóstico de tela
            logger.exception('painel_materializacao: falha ao disparar: %s', exc)
            messages.error(
                request,
                'Não foi possível iniciar a materialização: %s' % exc)
            return HttpResponseRedirect(destino)

        logger.info(
            'painel_materializacao: passada disparada por %s',
            request.user.get_username())
        messages.success(
            request,
            'Materialização iniciada em segundo plano. A passada varre o '
            'acervo inteiro e pode levar cerca de uma hora — atualize esta '
            'página para acompanhar. Ela leva alguns segundos para aparecer '
            'como "em andamento".')
        return HttpResponseRedirect(destino)
