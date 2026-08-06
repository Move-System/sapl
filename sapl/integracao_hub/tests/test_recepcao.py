import uuid

import pytest
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from model_bakery import baker
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from sapl.base.models import AppConfig, Autor
from sapl.integracao_hub.models import EventoRecebido
from sapl.materia.models import Proposicao, TipoProposicao

URL = '/api/integracao/proposicoes/'


@pytest.fixture()
def app_config(db):
    return AppConfig.objects.create()


@pytest.fixture()
def cliente_hub(db):
    usuario = baker.make('auth.User')
    permissao = Permission.objects.get(
        content_type__app_label='integracao_hub', codename='pode_integrar')
    usuario.user_permissions.add(permissao)
    token = Token.objects.create(user=usuario)
    cliente = APIClient()
    cliente.credentials(HTTP_AUTHORIZATION='Token %s' % token.key)
    return cliente


@pytest.fixture()
def autor(db):
    return baker.make(Autor)


@pytest.fixture()
def tipo(db):
    return baker.make(TipoProposicao)


def corpo(autor, tipo, **extras):
    dados = {
        'chave_idempotencia': str(uuid.uuid4()),
        'autor': autor.pk,
        'tipo': tipo.pk,
        'ementa': 'Indica a revitalização da praça central',
    }
    dados.update(extras)
    return dados


@pytest.mark.django_db(transaction=False)
def test_cria_proposicao_como_rascunho(cliente_hub, app_config, autor, tipo):
    resposta = cliente_hub.post(URL, corpo(autor, tipo))

    assert resposta.status_code == 201
    proposicao = Proposicao.objects.get(pk=resposta.data['proposicao_id'])
    assert proposicao.autor == autor
    assert proposicao.tipo == tipo
    assert proposicao.descricao == 'Indica a revitalização da praça central'
    assert proposicao.data_envio is None  # nasce rascunho — spec §3
    assert proposicao.numero_proposicao == 1


@pytest.mark.django_db(transaction=False)
def test_reentrega_devolve_200_sem_duplicar(cliente_hub, app_config, autor,
                                            tipo):
    dados = corpo(autor, tipo)

    primeira = cliente_hub.post(URL, dados)
    segunda = cliente_hub.post(URL, dados)

    assert primeira.status_code == 201
    assert segunda.status_code == 200
    assert segunda.data['proposicao_id'] == primeira.data['proposicao_id']
    assert Proposicao.objects.count() == 1
    assert EventoRecebido.objects.count() == 1


@pytest.mark.django_db(transaction=False)
def test_texto_e_justificativa_viram_observacao(cliente_hub, app_config,
                                                autor, tipo):
    resposta = cliente_hub.post(URL, corpo(
        autor, tipo, texto='Texto da proposição',
        justificativa='Porque sim'))

    assert resposta.status_code == 201
    proposicao = Proposicao.objects.get(pk=resposta.data['proposicao_id'])
    assert 'Texto da proposição' in proposicao.observacao
    assert 'Justificativa: Porque sim' in proposicao.observacao


@pytest.mark.django_db(transaction=False)
def test_arquivo_vira_texto_original(cliente_hub, app_config, autor, tipo):
    arquivo = SimpleUploadedFile(
        'proposicao.pdf', b'%PDF-1.4 conteudo', 'application/pdf')

    resposta = cliente_hub.post(
        URL, corpo(autor, tipo, arquivos=arquivo), format='multipart')

    assert resposta.status_code == 201
    proposicao = Proposicao.objects.get(pk=resposta.data['proposicao_id'])
    assert proposicao.texto_original


@pytest.mark.django_db(transaction=False)
def test_mais_de_um_arquivo_e_rejeitado(cliente_hub, app_config, autor, tipo):
    arquivos = [
        SimpleUploadedFile('a.pdf', b'%PDF-1.4 a', 'application/pdf'),
        SimpleUploadedFile('b.pdf', b'%PDF-1.4 b', 'application/pdf'),
    ]

    resposta = cliente_hub.post(
        URL, corpo(autor, tipo, arquivos=arquivos), format='multipart')

    assert resposta.status_code == 422
    assert Proposicao.objects.count() == 0


@pytest.mark.django_db(transaction=False)
def test_autor_inexistente_da_422(cliente_hub, app_config, tipo):
    autor_fantasma = type('A', (), {'pk': 99999})()

    resposta = cliente_hub.post(URL, corpo(autor_fantasma, tipo))

    assert resposta.status_code == 422
    assert 'autor' in resposta.data['detalhe']


@pytest.mark.django_db(transaction=False)
def test_tipo_inexistente_da_422_com_erros_do_form(cliente_hub, app_config,
                                                   autor):
    tipo_fantasma = type('T', (), {'pk': 99999})()

    resposta = cliente_hub.post(URL, corpo(autor, tipo_fantasma))

    assert resposta.status_code == 422
    assert 'erros' in resposta.data


@pytest.mark.django_db(transaction=False)
def test_chave_invalida_da_422(cliente_hub, app_config, autor, tipo):
    resposta = cliente_hub.post(
        URL, corpo(autor, tipo, chave_idempotencia='nao-e-uuid'))

    assert resposta.status_code == 422


@pytest.mark.django_db(transaction=False)
def test_sem_permissao_da_403(db, app_config, autor, tipo):
    usuario = baker.make('auth.User')
    token = Token.objects.create(user=usuario)
    cliente = APIClient()
    cliente.credentials(HTTP_AUTHORIZATION='Token %s' % token.key)

    resposta = cliente.post(URL, corpo(autor, tipo))

    assert resposta.status_code == 403


@pytest.mark.django_db(transaction=False)
def test_sem_token_da_401(db, app_config, autor, tipo):
    resposta = APIClient().post(URL, corpo(autor, tipo))

    assert resposta.status_code == 401
