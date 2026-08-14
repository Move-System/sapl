from datetime import timedelta

import pytest
from django.contrib.auth.models import Permission
from django.utils import timezone
from model_bakery import baker
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from sapl.materia.models import Proposicao, Tramitacao

INVENTARIO = '/api/integracao/reconciliacao/'
ENVIADAS = '/api/integracao/poll/proposicoes-enviadas/'


@pytest.fixture()
def cliente_hub(db):
    usuario = baker.make('auth.User')
    usuario.user_permissions.add(
        Permission.objects.get(
            content_type__app_label='integracao_hub', codename='pode_integrar'))
    # get_or_create: sapl/api/signals.py:8 ja cria o token no post_save do usuario.
    # Um create() aqui colide com a UNIQUE de authtoken_token.
    token, _ = Token.objects.get_or_create(user=usuario)
    cliente = APIClient()
    cliente.credentials(HTTP_AUTHORIZATION='Token %s' % token.key)
    return cliente


# ── Inventário: a lista de conferência da reconciliação ────────────────────────


@pytest.mark.django_db(transaction=False)
def test_inventario_devolve_ids_acima_do_corte(cliente_hub):
    antiga = baker.make(Proposicao, cancelado=False)
    nova = baker.make(Proposicao, cancelado=False)

    resposta = cliente_hub.get(INVENTARIO, {'id_gt': antiga.pk})

    assert resposta.status_code == 200
    assert nova.pk in resposta.data['proposicoes']
    assert antiga.pk not in resposta.data['proposicoes']


@pytest.mark.django_db(transaction=False)
def test_inventario_ignora_cancelada(cliente_hub):
    # Sem isso a reconciliação apontaria a cancelada como ausente para sempre —
    # o poller nunca a traz, e o hub nunca a conheceria.
    cancelada = baker.make(Proposicao, cancelado=True)

    resposta = cliente_hub.get(INVENTARIO, {'id_gt': 0})

    assert cancelada.pk not in resposta.data['proposicoes']


@pytest.mark.django_db(transaction=False)
def test_inventario_avisa_quando_a_faixa_encheu(cliente_hub):
    baker.make(Proposicao, cancelado=False, _quantity=3)

    resposta = cliente_hub.get(INVENTARIO, {'id_gt': 0, 'limite': 2})

    assert len(resposta.data['proposicoes']) == 2
    assert resposta.data['truncado'] is True  # o hub sabe que falta pedir mais


@pytest.mark.django_db(transaction=False)
def test_inventario_cursores_independentes_para_tramitacao(cliente_hub):
    # Proposição e tramitação são sequências separadas: um cursor só misturaria as faixas.
    proposicao = baker.make(Proposicao, cancelado=False)
    tramitacao = baker.make(Tramitacao)

    resposta = cliente_hub.get(
        INVENTARIO, {'id_gt': proposicao.pk - 1, 'tramitacao_id_gt': tramitacao.pk})

    assert proposicao.pk in resposta.data['proposicoes']
    assert tramitacao.pk not in resposta.data['tramitacoes']


@pytest.mark.django_db(transaction=False)
def test_inventario_sem_permissao_da_403(db):
    usuario = baker.make('auth.User')
    # get_or_create: sapl/api/signals.py:8 ja cria o token no post_save do usuario.
    # Um create() aqui colide com a UNIQUE de authtoken_token.
    token, _ = Token.objects.get_or_create(user=usuario)
    cliente = APIClient()
    cliente.credentials(HTTP_AUTHORIZATION='Token %s' % token.key)

    assert cliente.get(INVENTARIO, {'id_gt': 0}).status_code == 403


# ── Keyset: o empate de timestamp que travava a fonte para sempre ──────────────


@pytest.mark.django_db(transaction=False)
def test_paginacao_por_data_desempata_por_id_e_avanca(cliente_hub):
    """O cenário que travava: uma página inteira com o MESMO timestamp.

    Com cursor só de data e `>=`, a segunda chamada devolvia exatamente a mesma
    página — o cursor não avançava e nada depois daquele instante era lido, sem
    erro nenhum. Com (data, id) a segunda página continua de onde a primeira parou.
    """
    instante = timezone.now() - timedelta(hours=1)
    tres = [baker.make(Proposicao, data_envio=instante, cancelado=False)
            for _ in range(3)]
    ids = sorted(p.pk for p in tres)

    primeira = cliente_hub.get(
        ENVIADAS, {'desde': instante.isoformat(), 'id_gt': 0, 'limite': 2})
    assert [p['id'] for p in primeira.data['resultados']] == ids[:2]

    # O hub avança o cursor para (mesmo instante, último id lido).
    segunda = cliente_hub.get(
        ENVIADAS, {'desde': instante.isoformat(), 'id_gt': ids[1], 'limite': 2})

    assert [p['id'] for p in segunda.data['resultados']] == [ids[2]]  # progrediu


@pytest.mark.django_db(transaction=False)
def test_paginacao_por_data_nao_repete_o_ja_lido_no_mesmo_instante(cliente_hub):
    instante = timezone.now() - timedelta(hours=2)
    p1 = baker.make(Proposicao, data_envio=instante, cancelado=False)

    resposta = cliente_hub.get(
        ENVIADAS, {'desde': instante.isoformat(), 'id_gt': p1.pk})

    assert p1.pk not in [p['id'] for p in resposta.data['resultados']]


@pytest.mark.django_db(transaction=False)
def test_paginacao_por_data_traz_o_que_veio_depois_do_instante(cliente_hub):
    instante = timezone.now() - timedelta(hours=3)
    depois = baker.make(
        Proposicao, data_envio=instante + timedelta(minutes=5), cancelado=False)

    resposta = cliente_hub.get(
        ENVIADAS, {'desde': instante.isoformat(), 'id_gt': 999999})

    # id_gt alto não pode esconder quem tem timestamp maior — o desempate só vale
    # dentro do mesmo instante.
    assert depois.pk in [p['id'] for p in resposta.data['resultados']]


@pytest.mark.django_db(transaction=False)
def test_paginacao_por_data_id_gt_invalido_da_400(cliente_hub):
    resposta = cliente_hub.get(
        ENVIADAS, {'desde': timezone.now().isoformat(), 'id_gt': 'abc'})

    assert resposta.status_code == 400
