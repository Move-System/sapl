"""Tramitação disparada pela assinatura do parecer jurídico (AB#1575).

O gatilho substitui um passo manual: hoje, depois que o Procurador Jurídico
assina o parecer, alguém precisa lembrar de abrir a matéria e tramitá-la para o
status de espera da sessão.

O que estes testes protegem, além do caminho feliz:

- o gatilho é opt-in — Casa sem os três parâmetros preenchidos não muda nada;
- ele não pode disparar em documento de outro tipo;
- ele é idempotente, porque um parecer pode receber mais de uma assinatura;
- ele nunca derruba a assinatura, que é o ato principal e já aconteceu;
- ele respeita a corrente do histórico: a origem da nova tramitação é o destino
  da última, invariante que o `TramitacaoForm` cobra do fluxo manual.
"""
import datetime

import pytest
from model_bakery import baker

from sapl.base.models import AppConfig
from sapl.materia.models import (DocumentoAcessorio, MateriaLegislativa,
                                 StatusTramitacao, Tramitacao)
from sapl.materia.tramitacao_automatica import (
    CRIADA, DATA_INCONSISTENTE, ERRO, JA_ESTA_NO_STATUS, SEM_CONFIGURACAO,
    SEM_TRAMITACAO_ANTERIOR, SEM_UNIDADE_DE_ORIGEM, TIPO_NAO_DISPARA,
    tramitar_por_assinatura)


@pytest.fixture(autouse=True)
def sem_email_de_acompanhamento():
    """Desliga o e-mail de acompanhamento durante estes testes.

    `sapl.base.receivers.handle_tramitacao_signal` descobre a URL base varrendo
    `inspect.stack()` atrás de uma variável local chamada `request`. Sob pytest
    ele encontra o `SubRequest` das fixtures, e o tratamento de erro do próprio
    receiver estoura em `request.user.username`.

    É ruído alheio ao que estes testes verificam — e vale como aviso: qualquer
    teste que crie uma `Tramitacao` esbarra nisso.
    """
    from django.db.models.signals import post_save

    from sapl.base.receivers import handle_tramitacao_signal

    post_save.disconnect(handle_tramitacao_signal, sender=Tramitacao)
    yield
    post_save.connect(handle_tramitacao_signal, sender=Tramitacao)


@pytest.fixture()
def cenario(db):
    """Matéria já tramitada uma vez, com o gatilho configurado."""
    tipo_parecer = baker.make('materia.TipoDocumento',
                              descricao='Parecer jurídico')
    tipo_outro = baker.make('materia.TipoDocumento', descricao='Anexo')

    status_anterior = baker.make(StatusTramitacao, descricao='Em análise',
                                 indicador='')
    status_alvo = baker.make(StatusTramitacao,
                             descricao='Aguardando inserção na sessão',
                             indicador='')

    procuradoria = baker.make('materia.UnidadeTramitacao')
    secretaria = baker.make('materia.UnidadeTramitacao')

    materia = baker.make(MateriaLegislativa, ano=2026, numero=81,
                         em_tramitacao=True)

    primeira = baker.make(
        Tramitacao, materia=materia, status=status_anterior,
        data_tramitacao=datetime.date(2026, 9, 1),
        unidade_tramitacao_local=secretaria,
        unidade_tramitacao_destino=procuradoria)

    documento = baker.make(DocumentoAcessorio, materia=materia,
                           tipo=tipo_parecer, nome='Aprovado')

    config = AppConfig.objects.first() or baker.make(AppConfig)
    config.tramitacao_automatica_tipo_documento = tipo_parecer
    config.tramitacao_automatica_status = status_alvo
    config.tramitacao_automatica_unidade_destino = secretaria
    config.save()

    return {
        'materia': materia, 'documento': documento, 'config': config,
        'status_alvo': status_alvo, 'status_anterior': status_anterior,
        'procuradoria': procuradoria, 'secretaria': secretaria,
        'primeira': primeira, 'tipo_outro': tipo_outro,
    }


def test_assinatura_do_parecer_cria_a_tramitacao(cenario):
    tramitacao, motivo = tramitar_por_assinatura(cenario['documento'])

    assert motivo == CRIADA
    assert tramitacao is not None
    assert tramitacao.status == cenario['status_alvo']
    assert tramitacao.materia == cenario['materia']


def test_origem_da_nova_e_o_destino_da_ultima(cenario):
    """A corrente do histórico não pode quebrar.

    É a mesma invariante que o `TramitacaoForm` cobra quando
    `tramitacao_origem_fixa` está ligada.
    """
    tramitacao, _ = tramitar_por_assinatura(cenario['documento'])

    assert tramitacao.unidade_tramitacao_local == cenario['procuradoria']
    assert tramitacao.unidade_tramitacao_destino == cenario['secretaria']


def test_sem_configuracao_nao_faz_nada(cenario):
    """Casa que não configurou o gatilho continua 100% manual."""
    config = cenario['config']
    config.tramitacao_automatica_status = None
    config.save()

    tramitacao, motivo = tramitar_por_assinatura(cenario['documento'])

    assert motivo == SEM_CONFIGURACAO
    assert tramitacao is None
    assert cenario['materia'].tramitacao_set.count() == 1


def test_documento_de_outro_tipo_nao_dispara(cenario):
    """Assinar um anexo qualquer não pode mover a matéria."""
    outro = baker.make(DocumentoAcessorio, materia=cenario['materia'],
                       tipo=cenario['tipo_outro'], nome='Mapa')

    tramitacao, motivo = tramitar_por_assinatura(outro)

    assert motivo == TIPO_NAO_DISPARA
    assert tramitacao is None
    assert cenario['materia'].tramitacao_set.count() == 1


def test_e_idempotente_em_multiassinatura(cenario):
    """Um parecer pode ser assinado mais de uma vez; a tramitação é uma só."""
    primeira, motivo_1 = tramitar_por_assinatura(cenario['documento'])
    segunda, motivo_2 = tramitar_por_assinatura(cenario['documento'])

    assert motivo_1 == CRIADA
    assert motivo_2 == JA_ESTA_NO_STATUS
    assert primeira is not None
    assert segunda is None
    assert cenario['materia'].tramitacao_set.count() == 2


def test_materia_sem_tramitacao_anterior_e_deixada_para_a_mao_humana(cenario):
    """Sem histórico não há de onde derivar a origem — inventar seria pior."""
    materia_nova = baker.make(MateriaLegislativa, ano=2026, numero=82)
    documento = baker.make(
        DocumentoAcessorio, materia=materia_nova,
        tipo=cenario['config'].tramitacao_automatica_tipo_documento,
        nome='Aprovado')

    tramitacao, motivo = tramitar_por_assinatura(documento)

    assert motivo == SEM_TRAMITACAO_ANTERIOR
    assert tramitacao is None
    assert materia_nova.tramitacao_set.count() == 0


def test_ultima_tramitacao_sem_destino_nao_dispara(cenario):
    """`unidade_tramitacao_destino` é nullable no modelo — base legada existe."""
    ultima = cenario['primeira']
    ultima.unidade_tramitacao_destino = None
    ultima.save()

    tramitacao, motivo = tramitar_por_assinatura(cenario['documento'])

    assert motivo == SEM_UNIDADE_DE_ORIGEM
    assert tramitacao is None


def test_data_futura_na_ultima_tramitacao_nao_dispara(cenario):
    """Data suja não vira tramitação com data menor que a anterior."""
    ultima = cenario['primeira']
    ultima.data_tramitacao = (
        datetime.date.today() + datetime.timedelta(days=30))
    ultima.save()

    tramitacao, motivo = tramitar_por_assinatura(cenario['documento'])

    assert motivo == DATA_INCONSISTENTE
    assert tramitacao is None


def test_status_de_fim_tira_a_materia_de_tramitacao(cenario):
    """Mesmo efeito do fluxo manual: indicador 'F' zera `em_tramitacao`."""
    status_alvo = cenario['status_alvo']
    status_alvo.indicador = 'F'
    status_alvo.save()

    tramitar_por_assinatura(cenario['documento'])

    cenario['materia'].refresh_from_db()
    assert cenario['materia'].em_tramitacao is False


def test_status_comum_mantem_a_materia_em_tramitacao(cenario):
    materia = cenario['materia']
    materia.em_tramitacao = False
    materia.save()

    tramitar_por_assinatura(cenario['documento'])

    materia.refresh_from_db()
    assert materia.em_tramitacao is True


def test_falha_interna_nao_derruba_a_assinatura(cenario, monkeypatch):
    """A assinatura já aconteceu quando o gatilho roda.

    Se tramitar explodir, o documento continua assinado e o operador ajusta o
    status à mão — nunca o contrário.
    """
    def explode(*args, **kwargs):
        raise RuntimeError('banco fora do ar')

    monkeypatch.setattr(
        'sapl.materia.tramitacao_automatica._tramitar', explode)

    tramitacao, motivo = tramitar_por_assinatura(cenario['documento'])

    assert motivo == ERRO
    assert tramitacao is None
