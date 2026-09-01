"""Autossupervisão do laço de materialização (ADR 0015).

O contrato: o laço bate no banco a cada tick; o processo web ressuscita o laço
quando o batimento envelhece; dois laços nunca residem juntos; e um deploy faz
o laço se encerrar para renascer com o código novo.
"""
import os

import pytest
from django.core.management import call_command
from django.utils import timezone

from sapl.integracao_hub.middleware import laco_precisa_subir, subir_laco
from sapl.integracao_hub.models import BatimentoLaco, PassadaMaterializacao

CMD = ('sapl.integracao_hub.management.commands'
       '.materializar_pdfs_para_assinatura')


@pytest.fixture(autouse=True)
def base_url_configurada(settings):
    settings.SAPL_INTERNAL_URL = 'http://sapl-interno:8000'
    settings.SITE_URL = ''


def batimento(segundos_atras=0, pid=None):
    agora = timezone.now()
    return BatimentoLaco.objects.create(
        pk=1,
        visto_em=agora - timezone.timedelta(seconds=segundos_atras),
        iniciado_em=agora,
        pid=pid if pid is not None else os.getpid() + 1,
        tick_segundos=15)


# ---------------------------------------------------------------------------
# O laço bate — inclusive é este batimento que o painel exibe
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=False)
def test_modo_laco_grava_batimento(db, monkeypatch):
    def sleep_que_interrompe(segundos):
        raise KeyboardInterrupt

    monkeypatch.setattr(CMD + '.time.sleep', sleep_que_interrompe)

    with pytest.raises(KeyboardInterrupt):
        call_command('materializar_pdfs_para_assinatura', intervalo=30)

    vivo = BatimentoLaco.objects.get(pk=1)
    assert vivo.pid == os.getpid()
    assert vivo.fresco
    assert vivo.tick_segundos == 15


@pytest.mark.django_db(transaction=False)
def test_passada_avulsa_nao_bate(db):
    """O batimento mede a vida do LAÇO; passada manual não é laço."""
    call_command('materializar_pdfs_para_assinatura')

    assert not BatimentoLaco.objects.exists()


# ---------------------------------------------------------------------------
# Instância única: dois laços nunca residem juntos
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=False)
def test_segundo_laco_sai_quando_ha_batimento_fresco_de_outro_pid(db):
    batimento(segundos_atras=5)

    # Sem monkeypatch de sleep: se o guarda falhar, o laço entraria em loop
    # infinito — o retorno imediato É a asserção.
    call_command('materializar_pdfs_para_assinatura', intervalo=30)

    assert not PassadaMaterializacao.objects.exists()


@pytest.mark.django_db(transaction=False)
def test_laco_assume_quando_batimento_esta_velho(db, monkeypatch):
    batimento(segundos_atras=600)

    def sleep_que_interrompe(segundos):
        raise KeyboardInterrupt

    monkeypatch.setattr(CMD + '.time.sleep', sleep_que_interrompe)

    with pytest.raises(KeyboardInterrupt):
        call_command('materializar_pdfs_para_assinatura', intervalo=30)

    assert BatimentoLaco.objects.get(pk=1).pid == os.getpid()


# ---------------------------------------------------------------------------
# Deploy: laço defasado se encerra para renascer com o código novo
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=False)
def test_laco_sai_quando_o_codigo_muda_no_disco(db, monkeypatch):
    getmtime_real = os.path.getmtime
    contagem = {'n': 0}

    def getmtime_que_avanca(caminho):
        # Só o arquivo do comando "muda de versão"; o resto do mundo segue
        # normal — getmtime é global e outros códigos o usam no meio do teste.
        if str(caminho).endswith('materializar_pdfs_para_assinatura.py'):
            contagem['n'] += 1
            return float(contagem['n'])
        return getmtime_real(caminho)

    monkeypatch.setattr(CMD + '.os.path.getmtime', getmtime_que_avanca)

    # Retorna sozinho (sem KeyboardInterrupt): a saída limpa É a asserção.
    call_command('materializar_pdfs_para_assinatura', intervalo=30)


# ---------------------------------------------------------------------------
# O lado do processo web: decidir e ressuscitar
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=False)
def test_precisa_subir_sem_batimento_ou_com_batimento_velho(db):
    assert laco_precisa_subir()  # nunca bateu

    b = batimento(segundos_atras=600)
    assert laco_precisa_subir()  # bateu ha 10min com tick de 15s

    b.visto_em = timezone.now()
    b.save()
    assert not laco_precisa_subir()  # fresco


@pytest.mark.django_db(transaction=False)
def test_subir_laco_dispara_processo_desgarrado(db, monkeypatch):
    chamadas = []

    def popen_falso(comando, **kwargs):
        chamadas.append((comando, kwargs))

    monkeypatch.setattr(
        'sapl.integracao_hub.middleware.subprocess.Popen', popen_falso)
    monkeypatch.setenv('MATERIALIZACAO_INTERVALO_SEGUNDOS', '120')
    monkeypatch.setenv('MATERIALIZACAO_TICK_SEGUNDOS', '5')

    subir_laco()

    comando, kwargs = chamadas[0]
    assert 'materializar_pdfs_para_assinatura' in comando
    assert comando[comando.index('--intervalo') + 1] == '120'
    assert comando[comando.index('--tick') + 1] == '5'
    # Desgarrado do worker: sobrevive ao reload do gunicorn.
    assert kwargs['start_new_session'] is True


def test_middleware_nao_liga_sob_pytest():
    """Spawnar laço residente por efeito de request de teste seria vazamento."""
    from django.core.exceptions import MiddlewareNotUsed
    from sapl.integracao_hub.middleware import AutossupervisaoMaterializacao

    with pytest.raises(MiddlewareNotUsed):
        AutossupervisaoMaterializacao(lambda request: None)
