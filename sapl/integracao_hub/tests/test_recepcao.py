import hashlib
import uuid

import pytest
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from model_bakery import baker
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from sapl.base.models import AppConfig, Autor
from sapl.integracao_hub.models import EventoRecebido
from django.contrib.contenttypes.models import ContentType

from sapl.materia.models import (MateriaLegislativa, Proposicao,
                                 TipoProposicao)

URL = '/api/integracao/proposicoes/'


@pytest.fixture()
def app_config(db):
    return AppConfig.objects.create()


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


@pytest.fixture()
def autor(db):
    return baker.make(Autor)


@pytest.fixture()
def tipo(db):
    # content_type e NOT NULL e o baker nao preenche FK sozinho — no SAPL ele diz que
    # conteudo a proposicao gera ao ser recebida (materia, no caso).
    return baker.make(
        TipoProposicao,
        content_type=ContentType.objects.get_for_model(MateriaLegislativa))


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
def test_anexo_do_app_vira_anexo_geral_nao_texto_oficial(
        cliente_hub, app_config, autor, tipo):
    """Anexo do app e evidencia da demanda (foto, video), nao o documento legislativo.

    Decisao do arquiteto (17/08/2026): o texto_original continua sendo do fluxo
    proprio do SAPL; o que chega do app vira AnexoProposicao — gravado com hash
    dos bytes recebidos, consultavel no futuro, sem tela por ora.
    """
    conteudo = b'video-da-rua-esburacada'
    arquivo = SimpleUploadedFile('rua.mp4', conteudo, 'video/mp4')

    resposta = cliente_hub.post(
        URL, corpo(autor, tipo, arquivos=arquivo), format='multipart')

    assert resposta.status_code == 201
    proposicao = Proposicao.objects.get(pk=resposta.data['proposicao_id'])
    assert not proposicao.texto_original  # o oficial nasce no fluxo do SAPL
    anexo = proposicao.anexos_do_app.get()
    assert anexo.nome_original == 'rua.mp4'
    assert anexo.mime == 'video/mp4'
    assert anexo.tamanho_bytes == len(conteudo)
    assert anexo.hash_sha256 == hashlib.sha256(conteudo).hexdigest()


@pytest.mark.django_db(transaction=False)
def test_varios_anexos_sao_aceitos(cliente_hub, app_config, autor, tipo):
    # O limite de 1 era premissa errada (anexo != texto_original). Foto + video convivem.
    arquivos = [
        SimpleUploadedFile('foto.jpg', b'jpg-bytes', 'image/jpeg'),
        SimpleUploadedFile('video.mp4', b'mp4-bytes', 'video/mp4'),
    ]

    resposta = cliente_hub.post(
        URL, corpo(autor, tipo, arquivos=arquivos), format='multipart')

    assert resposta.status_code == 201
    proposicao = Proposicao.objects.get(pk=resposta.data['proposicao_id'])
    assert proposicao.anexos_do_app.count() == 2


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
    usuario = baker.make('auth.User', username='hub-teste')
    # get_or_create: sapl/api/signals.py:8 ja cria o token no post_save do usuario.
    # Um create() aqui colide com a UNIQUE de authtoken_token.
    token, _ = Token.objects.get_or_create(user=usuario)
    cliente = APIClient()
    cliente.credentials(HTTP_AUTHORIZATION='Token %s' % token.key)

    resposta = cliente.post(URL, corpo(autor, tipo))

    assert resposta.status_code == 403


@pytest.mark.django_db(transaction=False)
def test_sem_token_da_401(db, app_config, autor, tipo):
    resposta = APIClient().post(URL, corpo(autor, tipo))

    assert resposta.status_code == 401
