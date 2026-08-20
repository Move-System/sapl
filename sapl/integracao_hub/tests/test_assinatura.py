import hashlib
import uuid
from datetime import timedelta

import pytest
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from model_bakery import baker
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from sapl.base.models import Autor, OperadorAutor
from sapl.integracao_hub.models import (AssinaturaRecebida,
                                        DocumentoParaAssinatura)
from sapl.materia.models import Autoria, MateriaLegislativa

BASE = '/api/integracao/poll/'
URL_ASSINATURAS = '/api/integracao/assinaturas/'

PDF_ALVO = b'%PDF-1.4 alvo-oficial'
PDF_ASSINADO = b'%PDF-1.4 alvo-oficial-com-assinatura'


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


def criar_materia_com_alvo(conteudo=PDF_ALVO):
    materia = baker.make(MateriaLegislativa, numero_protocolo=200)
    materia.texto_original.save(
        'texto.pdf', ContentFile(conteudo), save=True)
    alvo = DocumentoParaAssinatura(
        materia=materia,
        hash_sha256=hashlib.sha256(conteudo).hexdigest(),
        hash_origem=hashlib.sha256(conteudo).hexdigest())
    alvo.arquivo.save('materia_%s_alvo.pdf' % materia.pk,
                      ContentFile(conteudo), save=True)
    return materia, alvo


def criar_autor_com_operador(username):
    autor = baker.make(Autor, nome='Vereador %s' % username)
    usuario = baker.make('auth.User', username=username)
    baker.make(OperadorAutor, autor=autor, user=usuario)
    return autor


# ---------------------------------------------------------------------------
# Poll de pendentes (refinamento §2/§3/§5.1)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=False)
def test_pendentes_so_devolve_materia_com_pdf_alvo(cliente_hub):
    """§5.1: DOCX não convertido não sai do SAPL — sem alvo, sem pendência."""
    com_alvo, _ = criar_materia_com_alvo()
    sem_alvo = baker.make(MateriaLegislativa, numero_protocolo=201)
    sem_alvo.texto_original.save(
        'texto.docx', ContentFile(b'docx-nao-convertido'), save=True)

    resposta = cliente_hub.get(BASE + 'assinaturas-pendentes/', {'id_gt': 0})

    assert resposta.status_code == 200
    ids = [item['materia']['id'] for item in resposta.data['resultados']]
    assert com_alvo.pk in ids
    assert sem_alvo.pk not in ids


@pytest.mark.django_db(transaction=False)
def test_pendencia_e_por_autor_um_assinou_outro_segue_pendente(cliente_hub):
    """Refinamento §2: a primeira assinatura NAO some com a pendência dos demais."""
    materia, _ = criar_materia_com_alvo()
    assinante = criar_autor_com_operador('ver-a')
    pendente = criar_autor_com_operador('ver-b')
    baker.make(Autoria, materia=materia, autor=assinante)
    baker.make(Autoria, materia=materia, autor=pendente)
    materia.assinatura_info = [{'signed_by': 'ver-a',
                                'nome_assinante': 'Vereador ver-a'}]
    materia.save()

    resposta = cliente_hub.get(BASE + 'assinaturas-pendentes/', {'id_gt': 0})

    item = next(i for i in resposta.data['resultados']
                if i['materia']['id'] == materia.pk)
    assert item['autores_pendentes'] == [pendente.pk]


@pytest.mark.django_db(transaction=False)
def test_pendentes_traz_documento_com_hash_e_url(cliente_hub):
    materia, alvo = criar_materia_com_alvo()

    resposta = cliente_hub.get(BASE + 'assinaturas-pendentes/', {'id_gt': 0})

    documento = resposta.data['resultados'][0]['documento']
    assert documento['mime'] == 'application/pdf'
    assert documento['tamanho_bytes'] == len(PDF_ALVO)
    assert documento['hash_sha256'] == hashlib.sha256(PDF_ALVO).hexdigest()
    assert documento['url'].endswith(
        '/api/integracao/documentos-assinatura/%s/alvo/' % materia.pk)


@pytest.mark.django_db(transaction=False)
def test_pendentes_cursor_avanca_por_id_de_materia(cliente_hub):
    primeira, _ = criar_materia_com_alvo()
    segunda, _ = criar_materia_com_alvo()

    resposta = cliente_hub.get(BASE + 'assinaturas-pendentes/',
                               {'id_gt': primeira.pk})

    ids = [item['materia']['id'] for item in resposta.data['resultados']]
    assert primeira.pk not in ids
    assert segunda.pk in ids


# ---------------------------------------------------------------------------
# Poll de concluídas (cursor composto assinado_em|id)
# ---------------------------------------------------------------------------

def assinar_localmente(materia, username='ver-a'):
    materia.pdf_assinado.save(
        'materia_%s_assinado_1.pdf' % materia.pk,
        ContentFile(PDF_ASSINADO), save=False)
    materia.assinatura_info = [{
        'signed_by': username,
        'nome_assinante': 'Vereador %s' % username,
        'data_assinatura': '19/08/2026 10:00',
        'tipo_certificado': 'A1',
    }]
    materia.assinado_em = timezone.now()
    materia.codigo_autenticacao = 'ABCD1234ABCD1234'
    materia.save()


@pytest.mark.django_db(transaction=False)
def test_concluidas_devolve_documento_assinado_e_autor_resolvido(cliente_hub):
    materia, _ = criar_materia_com_alvo()
    autor = criar_autor_com_operador('ver-a')
    baker.make(Autoria, materia=materia, autor=autor)
    assinar_localmente(materia)
    nao_assinada, _ = criar_materia_com_alvo()

    resposta = cliente_hub.get(
        BASE + 'assinaturas-concluidas/',
        {'desde': (timezone.now() - timedelta(days=1)).isoformat(),
         'id_gt': 0})

    assert resposta.status_code == 200
    ids = [item['materia']['id'] for item in resposta.data['resultados']]
    assert materia.pk in ids
    assert nao_assinada.pk not in ids

    item = next(i for i in resposta.data['resultados']
                if i['materia']['id'] == materia.pk)
    documento = item['documento_assinado']
    assert documento['hash_sha256'] == \
        hashlib.sha256(PDF_ASSINADO).hexdigest()  # calculado do arquivo
    assert documento['tamanho_bytes'] == len(PDF_ASSINADO)
    assert documento['url'].endswith(
        '/api/integracao/documentos-assinatura/%s/assinado/' % materia.pk)
    assert item['codigo_autenticacao'] == 'ABCD1234ABCD1234'
    assinatura = item['assinaturas'][0]
    assert assinatura['signed_by'] == 'ver-a'
    assert assinatura['nome'] == 'Vereador ver-a'
    assert assinatura['tipo_certificado'] == 'A1'
    # Contrato documento-assinado: autor resolvido de signed_by via
    # OperadorAutor — é por ele que o consumidor marca a pendência fechada.
    assert assinatura['autor_id'] == autor.pk


@pytest.mark.django_db(transaction=False)
def test_concluidas_cursor_composto_nao_repete_no_empate(cliente_hub):
    instante = timezone.now()
    primeira, _ = criar_materia_com_alvo()
    segunda, _ = criar_materia_com_alvo()
    for materia in (primeira, segunda):
        assinar_localmente(materia)
        MateriaLegislativa.objects.filter(pk=materia.pk).update(
            assinado_em=instante)

    resposta = cliente_hub.get(
        BASE + 'assinaturas-concluidas/',
        {'desde': instante.isoformat(), 'id_gt': primeira.pk})

    ids = [item['materia']['id'] for item in resposta.data['resultados']]
    assert primeira.pk not in ids
    assert segunda.pk in ids


# ---------------------------------------------------------------------------
# Download dos bytes (token + pode_integrar)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=False)
def test_download_do_alvo_e_do_assinado(cliente_hub):
    materia, _ = criar_materia_com_alvo()
    assinar_localmente(materia)

    alvo = cliente_hub.get(
        '/api/integracao/documentos-assinatura/%s/alvo/' % materia.pk)
    assinado = cliente_hub.get(
        '/api/integracao/documentos-assinatura/%s/assinado/' % materia.pk)

    assert alvo.status_code == 200
    assert b''.join(alvo.streaming_content) == PDF_ALVO
    assert assinado.status_code == 200
    assert b''.join(assinado.streaming_content) == PDF_ASSINADO


@pytest.mark.django_db(transaction=False)
def test_download_sem_documento_da_404(cliente_hub):
    materia = baker.make(MateriaLegislativa)

    resposta = cliente_hub.get(
        '/api/integracao/documentos-assinatura/%s/alvo/' % materia.pk)

    assert resposta.status_code == 404


@pytest.mark.django_db(transaction=False)
def test_download_sem_token_da_401(db):
    materia, _ = criar_materia_com_alvo()

    resposta = APIClient().get(
        '/api/integracao/documentos-assinatura/%s/alvo/' % materia.pk)

    assert resposta.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/integracao/assinaturas/ (refinamento §5, F2)
# ---------------------------------------------------------------------------

def corpo_assinatura(materia, autor, **extras):
    dados = {
        'chave_idempotencia': str(uuid.uuid4()),
        'materia': materia.pk,
        'autor': autor.pk,
        'hash_alvo_esperado': hashlib.sha256(PDF_ALVO).hexdigest(),
        'nome': 'Vereador ver-a',
        'tipo_certificado': 'A1',
        'pdf_assinado': SimpleUploadedFile(
            'assinado.pdf', PDF_ASSINADO, 'application/pdf'),
    }
    dados.update(extras)
    return dados


@pytest.fixture()
def materia_pronta(db):
    materia, _ = criar_materia_com_alvo()
    autor = criar_autor_com_operador('ver-a')
    baker.make(Autoria, materia=materia, autor=autor)
    return materia, autor


@pytest.mark.django_db(transaction=False)
def test_grava_assinatura_no_formato_da_sprint(cliente_hub, materia_pronta):
    materia, autor = materia_pronta

    resposta = cliente_hub.post(
        URL_ASSINATURAS, corpo_assinatura(materia, autor),
        format='multipart')

    assert resposta.status_code == 201
    assert resposta.data['materia_id'] == materia.pk
    assert resposta.data['hash_assinado'] == \
        hashlib.sha256(PDF_ASSINADO).hexdigest()

    materia.refresh_from_db()
    assert 'materia_%s_assinado_' % materia.pk in materia.pdf_assinado.name
    materia.pdf_assinado.open('rb')
    assert materia.pdf_assinado.read() == PDF_ASSINADO
    info = materia.assinatura_info[0]
    assert info['signed_by'] == 'ver-a'  # username do OperadorAutor do autor
    assert info['nome'] == 'Vereador ver-a'
    assert info['tipo_certificado'] == 'A1'
    assert materia.assinado_em is not None
    # Primeira assinatura gera o código público, como no fluxo local.
    assert materia.codigo_autenticacao == \
        hashlib.sha256(PDF_ALVO).hexdigest()[:16].upper()


@pytest.mark.django_db(transaction=False)
def test_append_preserva_multiassinatura(cliente_hub, materia_pronta):
    materia, autor = materia_pronta
    materia.assinatura_info = [{'signed_by': 'ver-x',
                                'nome_assinante': 'Vereador X'}]
    materia.save()

    resposta = cliente_hub.post(
        URL_ASSINATURAS, corpo_assinatura(materia, autor),
        format='multipart')

    assert resposta.status_code == 201
    materia.refresh_from_db()
    assert [a['signed_by'] for a in materia.assinatura_info] == \
        ['ver-x', 'ver-a']


@pytest.mark.django_db(transaction=False)
def test_reentrega_devolve_200_sem_duplicar(cliente_hub, materia_pronta):
    materia, autor = materia_pronta
    chave = str(uuid.uuid4())

    primeira = cliente_hub.post(
        URL_ASSINATURAS,
        corpo_assinatura(materia, autor, chave_idempotencia=chave),
        format='multipart')
    segunda = cliente_hub.post(
        URL_ASSINATURAS,
        corpo_assinatura(materia, autor, chave_idempotencia=chave),
        format='multipart')

    assert primeira.status_code == 201
    assert segunda.status_code == 200
    assert segunda.data['hash_assinado'] == primeira.data['hash_assinado']
    assert AssinaturaRecebida.objects.count() == 1
    materia.refresh_from_db()
    assert len(materia.assinatura_info) == 1  # reentrega não duplica o append


@pytest.mark.django_db(transaction=False)
def test_hash_divergente_da_409(cliente_hub, materia_pronta):
    """Retificação no meio do caminho (§5.1): o alvo mudou entre o poll e a
    entrega — assinar binário defasado é impossível por construção."""
    materia, autor = materia_pronta

    resposta = cliente_hub.post(
        URL_ASSINATURAS,
        corpo_assinatura(materia, autor,
                         hash_alvo_esperado='0' * 64),
        format='multipart')

    assert resposta.status_code == 409
    assert resposta.data['hash_atual'] == \
        hashlib.sha256(PDF_ALVO).hexdigest()
    materia.refresh_from_db()
    assert not materia.pdf_assinado
    assert materia.assinatura_info is None


@pytest.mark.django_db(transaction=False)
def test_autor_fora_da_autoria_da_422(cliente_hub, materia_pronta):
    materia, _ = materia_pronta
    intruso = criar_autor_com_operador('ver-z')

    resposta = cliente_hub.post(
        URL_ASSINATURAS, corpo_assinatura(materia, intruso),
        format='multipart')

    assert resposta.status_code == 422
