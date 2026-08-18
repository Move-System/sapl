from datetime import timedelta

import pytest
from django.contrib.auth.models import Permission
from django.utils import timezone
from model_bakery import baker
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from sapl.base.models import Autor
from sapl.materia.models import (Proposicao, StatusTramitacao,
                                 Tramitacao)

BASE = '/api/integracao/poll/'


@pytest.fixture()
def cliente_hub(db):
    usuario = baker.make('auth.User', username='hub-teste')
    permissao = Permission.objects.get(
        content_type__app_label='integracao_hub', codename='pode_integrar')
    usuario.user_permissions.add(permissao)
    # get_or_create: sapl/api/signals.py:8 ja cria o token no post_save do usuario.
    # Um create() aqui colide com a UNIQUE de authtoken_token.
    token, _ = Token.objects.get_or_create(user=usuario)
    cliente = APIClient()
    cliente.credentials(HTTP_AUTHORIZATION='Token %s' % token.key)
    return cliente


@pytest.mark.django_db(transaction=False)
def test_cadastradas_por_cursor_de_id_inclui_rascunho(cliente_hub):
    autor = baker.make(Autor)
    rascunho = baker.make(
        Proposicao, autor=autor, data_envio=None, cancelado=False)

    resposta = cliente_hub.get(BASE + 'proposicoes-cadastradas/',
                               {'id_gt': 0})

    assert resposta.status_code == 200
    ids = [p['id'] for p in resposta.data['resultados']]
    assert rascunho.pk in ids
    encontrado = next(p for p in resposta.data['resultados']
                      if p['id'] == rascunho.pk)
    assert encontrado['rascunho'] is True
    assert encontrado['autor'] == autor.pk


@pytest.mark.django_db(transaction=False)
def test_cadastradas_cursor_avanca(cliente_hub):
    primeira = baker.make(Proposicao, cancelado=False)
    segunda = baker.make(Proposicao, cancelado=False)

    resposta = cliente_hub.get(BASE + 'proposicoes-cadastradas/',
                               {'id_gt': primeira.pk})

    ids = [p['id'] for p in resposta.data['resultados']]
    assert primeira.pk not in ids
    assert segunda.pk in ids


@pytest.mark.django_db(transaction=False)
def test_cadastradas_ignora_cancelada(cliente_hub):
    cancelada = baker.make(Proposicao, cancelado=True)

    resposta = cliente_hub.get(BASE + 'proposicoes-cadastradas/',
                               {'id_gt': 0})

    ids = [p['id'] for p in resposta.data['resultados']]
    assert cancelada.pk not in ids


@pytest.mark.django_db(transaction=False)
def test_enviadas_por_data_ordenadas(cliente_hub):
    agora = timezone.now()
    antiga = baker.make(
        Proposicao, data_envio=agora - timedelta(days=10), cancelado=False)
    recente = baker.make(
        Proposicao, data_envio=agora - timedelta(hours=1), cancelado=False)
    nunca_enviada = baker.make(Proposicao, data_envio=None, cancelado=False)

    resposta = cliente_hub.get(
        BASE + 'proposicoes-enviadas/',
        {'desde': (agora - timedelta(days=30)).isoformat()})

    assert resposta.status_code == 200
    ids = [p['id'] for p in resposta.data['resultados']]
    assert ids == [antiga.pk, recente.pk]
    assert nunca_enviada.pk not in ids


@pytest.mark.django_db(transaction=False)
def test_enviadas_desde_corta_o_passado(cliente_hub):
    agora = timezone.now()
    antiga = baker.make(
        Proposicao, data_envio=agora - timedelta(days=10), cancelado=False)
    recente = baker.make(
        Proposicao, data_envio=agora - timedelta(hours=1), cancelado=False)

    resposta = cliente_hub.get(
        BASE + 'proposicoes-enviadas/',
        {'desde': (agora - timedelta(days=1)).isoformat()})

    ids = [p['id'] for p in resposta.data['resultados']]
    assert ids == [recente.pk]
    assert antiga.pk not in ids


@pytest.mark.django_db(transaction=False)
def test_devolvidas_trazem_justificativa(cliente_hub):
    agora = timezone.now()
    devolvida = baker.make(
        Proposicao, data_devolucao=agora, cancelado=False,
        justificativa_devolucao='Fora do escopo regimental')

    resposta = cliente_hub.get(
        BASE + 'proposicoes-devolvidas/',
        {'desde': (agora - timedelta(days=1)).isoformat()})

    encontrada = next(p for p in resposta.data['resultados']
                      if p['id'] == devolvida.pk)
    assert encontrada['justificativa_devolucao'] == \
        'Fora do escopo regimental'


@pytest.mark.django_db(transaction=False)
def test_desde_invalido_da_400(cliente_hub):
    resposta = cliente_hub.get(BASE + 'proposicoes-enviadas/',
                               {'desde': 'ontem'})

    assert resposta.status_code == 400


@pytest.mark.django_db(transaction=False)
def test_tramitacoes_por_cursor_de_id(cliente_hub):
    # status explicito: o envelope canonico exige situacao.id_origem + descricao,
    # entao tramitacao sem status nao exercita o que importa.
    tramitacao = baker.make(Tramitacao, status=baker.make(StatusTramitacao))

    resposta = cliente_hub.get(BASE + 'tramitacoes/', {'id_gt': 0})

    assert resposta.status_code == 200
    encontrada = next(t for t in resposta.data['resultados']
                      if t['id'] == tramitacao.pk)
    assert encontrada['materia'] == tramitacao.materia_id
    assert encontrada['status']['sigla'] == tramitacao.status.sigla


@pytest.mark.django_db(transaction=False)
def test_limite_e_respeitado(cliente_hub):
    baker.make(Proposicao, cancelado=False, _quantity=3)

    resposta = cliente_hub.get(BASE + 'proposicoes-cadastradas/',
                               {'id_gt': 0, 'limite': 2})

    assert len(resposta.data['resultados']) == 2


@pytest.mark.django_db(transaction=False)
def test_poll_sem_permissao_da_403(db):
    usuario = baker.make('auth.User', username='hub-teste')
    # get_or_create: sapl/api/signals.py:8 ja cria o token no post_save do usuario.
    # Um create() aqui colide com a UNIQUE de authtoken_token.
    token, _ = Token.objects.get_or_create(user=usuario)
    cliente = APIClient()
    cliente.credentials(HTTP_AUTHORIZATION='Token %s' % token.key)

    resposta = cliente.get(BASE + 'proposicoes-cadastradas/', {'id_gt': 0})

    assert resposta.status_code == 403
