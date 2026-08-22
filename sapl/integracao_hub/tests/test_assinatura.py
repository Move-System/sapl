import hashlib
import os
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

from django.contrib.contenttypes.models import ContentType

from sapl.base.models import Autor, OperadorAutor
from sapl.integracao_hub.models import (AssinaturaRecebida,
                                        DocumentoParaAssinatura)
from sapl.materia.models import Autoria, MateriaLegislativa
from sapl.parlamentares.models import Parlamentar, Votante

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


def criar_autor_parlamentar(titular, assessores=(), com_votante=True):
    """Autor de parlamentar como no dado real de Franco (CESINHA).

    O titular é o Votante do parlamentar; assessores são só operadores. Sem
    votante e com >1 operador, o titular fica indeterminável de propósito.
    """
    parlamentar = baker.make(Parlamentar, nome_parlamentar=titular.upper())
    ct = ContentType.objects.get_for_model(Parlamentar)
    autor = baker.make(Autor, nome=titular.upper(),
                       content_type=ct, object_id=parlamentar.pk)
    user_titular = baker.make('auth.User', username=titular)
    baker.make(OperadorAutor, autor=autor, user=user_titular)
    if com_votante:
        baker.make(Votante, parlamentar=parlamentar, user=user_titular)
    for assessor in assessores:
        user_assessor = baker.make('auth.User', username=assessor)
        baker.make(OperadorAutor, autor=autor, user=user_assessor)
    return autor, parlamentar


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


# ---------------------------------------------------------------------------
# Titular (autoria jurídica) vs operador (rastro) — regra do arquiteto 20/08
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=False)
def test_multi_operador_assina_como_titular_nao_como_assessor(cliente_hub):
    """Assinatura é ato pessoal e indelegável (dado real: CESINHA).

    O autor tem dois operadores — o vereador 'cesinha' (Votante) e a assessora
    'juciana'. signed_by TEM que ser o titular, mesmo que a assessora dispare o
    ato. Escolher 'primeiro por id' gravaria a assessora como signatária.
    """
    materia, _ = criar_materia_com_alvo()
    autor, _ = criar_autor_parlamentar('cesinha', assessores=['juciana'])
    baker.make(Autoria, materia=materia, autor=autor)

    resposta = cliente_hub.post(
        URL_ASSINATURAS,
        corpo_assinatura(materia, autor, operado_por='juciana'),
        format='multipart')

    assert resposta.status_code == 201
    materia.refresh_from_db()
    info = materia.assinatura_info[0]
    assert info['signed_by'] == 'cesinha'      # titular, nunca a assessora
    assert info['operado_por'] == 'juciana'    # rastro: quem disparou
    # assinado_por (FK) também é o titular — a autoria jurídica.
    assert materia.assinado_por.username == 'cesinha'
    # E o rastro fica durável na tabela de auditoria.
    recebida = AssinaturaRecebida.objects.get(materia=materia)
    assert recebida.operado_por == 'juciana'


@pytest.mark.django_db(transaction=False)
def test_operado_por_default_e_o_titular_quando_evento_nao_traz(cliente_hub):
    """Hoje o evento do app ainda não carrega o operador real (nota no PR):
    sem 'operado_por', o rastro recai sobre o próprio titular."""
    materia, _ = criar_materia_com_alvo()
    autor, _ = criar_autor_parlamentar('cesinha', assessores=['juciana'])
    baker.make(Autoria, materia=materia, autor=autor)

    resposta = cliente_hub.post(
        URL_ASSINATURAS, corpo_assinatura(materia, autor),
        format='multipart')

    assert resposta.status_code == 201
    materia.refresh_from_db()
    assert materia.assinatura_info[0]['operado_por'] == 'cesinha'


@pytest.mark.django_db(transaction=False)
def test_titular_indeterminavel_falha_visivel(cliente_hub):
    """Multi-operador SEM Votante titular: recusa em vez de adivinhar."""
    materia, _ = criar_materia_com_alvo()
    autor, _ = criar_autor_parlamentar(
        'cesinha', assessores=['juciana'], com_votante=False)
    baker.make(Autoria, materia=materia, autor=autor)

    resposta = cliente_hub.post(
        URL_ASSINATURAS, corpo_assinatura(materia, autor),
        format='multipart')

    assert resposta.status_code == 422
    assert 'titular indeterminável' in resposta.data['detalhe']
    materia.refresh_from_db()
    assert not materia.pdf_assinado


@pytest.mark.django_db(transaction=False)
def test_concluidas_resolve_autor_pelo_titular_votante(cliente_hub):
    """Resolução inversa signed_by → autor_id via Votante (não 'primeiro por id')."""
    materia, _ = criar_materia_com_alvo()
    autor, _ = criar_autor_parlamentar('cesinha', assessores=['juciana'])
    baker.make(Autoria, materia=materia, autor=autor)
    materia.pdf_assinado.save(
        'materia_%s_assinado_1.pdf' % materia.pk,
        ContentFile(PDF_ASSINADO), save=False)
    materia.assinatura_info = [{
        'signed_by': 'cesinha', 'nome': 'Vereador cesinha',
        'data': '2026-08-20T10:00:00', 'tipo_certificado': 'A1',
        'operado_por': 'juciana'}]
    materia.assinado_em = timezone.now()
    materia.save()

    resposta = cliente_hub.get(
        BASE + 'assinaturas-concluidas/',
        {'desde': (timezone.now() - timedelta(days=1)).isoformat(),
         'id_gt': 0})

    item = next(i for i in resposta.data['resultados']
                if i['materia']['id'] == materia.pk)
    assinatura = item['assinaturas'][0]
    assert assinatura['signed_by'] == 'cesinha'
    assert assinatura['autor_id'] == autor.pk   # resolvido via Votante
    assert assinatura['operado_por'] == 'juciana'


@pytest.mark.django_db(transaction=False)
def test_pendencia_do_titular_some_apos_assinatura_do_titular(cliente_hub):
    """Pendência por autor usa o titular: assinou o titular, some a pendência."""
    materia, _ = criar_materia_com_alvo()
    autor, _ = criar_autor_parlamentar('cesinha', assessores=['juciana'])
    baker.make(Autoria, materia=materia, autor=autor)
    materia.assinatura_info = [{'signed_by': 'cesinha'}]
    materia.save()

    resposta = cliente_hub.get(BASE + 'assinaturas-pendentes/', {'id_gt': 0})

    item = next(i for i in resposta.data['resultados']
                if i['materia']['id'] == materia.pk)
    assert autor.pk not in item['autores_pendentes']


# ---------------------------------------------------------------------------
# Arquivo referenciado no banco mas ausente do MEDIA (969 matérias em Franco)
# ---------------------------------------------------------------------------

def apagar_do_disco(campo):
    """Deixa a referência no banco e some com o binário — o estado real do dump
    restaurado sem a media. `.size`/`.read()` passam a levantar FileNotFoundError
    (subclasse de OSError)."""
    os.remove(campo.path)


@pytest.mark.django_db(transaction=False)
def test_concluidas_com_pdf_sumido_do_media_nao_derruba_o_lote(cliente_hub):
    """O bug que travava a fonte inteira: uma matéria podre respondia 500.

    Com 500 o hub segurava o cursor e NENHUMA matéria passava — uma referência
    órfã bloqueava todas as outras, para sempre. O contrato agora é: 200, o item
    aparece com `documento_assinado` nulo (o leitor avança o cursor) e as sadias
    do mesmo lote continuam completas.
    """
    podre, _ = criar_materia_com_alvo()
    sadia, _ = criar_materia_com_alvo()
    autor = criar_autor_com_operador('ver-a')
    baker.make(Autoria, materia=podre, autor=autor)
    baker.make(Autoria, materia=sadia, autor=autor)
    assinar_localmente(podre)
    assinar_localmente(sadia)
    apagar_do_disco(podre.pdf_assinado)

    resposta = cliente_hub.get(
        BASE + 'assinaturas-concluidas/',
        {'desde': (timezone.now() - timedelta(days=1)).isoformat(),
         'id_gt': 0})

    assert resposta.status_code == 200
    por_materia = {i['materia']['id']: i for i in resposta.data['resultados']}
    assert podre.pk in por_materia and sadia.pk in por_materia

    item_podre = por_materia[podre.pk]
    assert item_podre['documento_assinado'] is None
    # O resto do item continua íntegro: só o binário faltou, não a assinatura.
    assert item_podre['codigo_autenticacao'] == 'ABCD1234ABCD1234'
    assert item_podre['assinaturas'][0]['signed_by'] == 'ver-a'

    documento_sadio = por_materia[sadia.pk]['documento_assinado']
    assert documento_sadio['hash_sha256'] == \
        hashlib.sha256(PDF_ASSINADO).hexdigest()
    assert documento_sadio['tamanho_bytes'] == len(PDF_ASSINADO)


@pytest.mark.django_db(transaction=False)
def test_pendentes_com_alvo_sumido_do_media_da_documento_nulo(cliente_hub):
    """Mesma regra na outra fonte: sem o PDF-alvo em disco, `documento` é nulo —
    a pendência não vira evento no hub, mas o cursor não trava."""
    materia, _ = criar_materia_com_alvo()
    alvo = DocumentoParaAssinatura.objects.get(materia=materia)
    apagar_do_disco(alvo.arquivo)

    resposta = cliente_hub.get(BASE + 'assinaturas-pendentes/', {'id_gt': 0})

    assert resposta.status_code == 200
    item = next(i for i in resposta.data['resultados']
                if i['materia']['id'] == materia.pk)
    assert item['documento'] is None
    # Hash gravado no banco existe, mas sem o binário o bloco inteiro cai fora:
    # entregar hash sem tamanho/URL utilizável seria mentir para o consumidor.
    assert item['materia']['numero'] == materia.numero


# ---------------------------------------------------------------------------
# `id` no topo do item — o keyset que o hub usa para avançar o cursor
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=False)
def test_concluidas_traz_id_da_materia_no_topo(cliente_hub):
    """`PollerSapl.pollAssinaturasConcluidas` lê `item.path("id")` para o
    desempate do cursor composto (assinado_em|id). Sem o campo o cursor gravava
    id 0 e o instante relia a mesma página."""
    materia, _ = criar_materia_com_alvo()
    assinar_localmente(materia)

    resposta = cliente_hub.get(
        BASE + 'assinaturas-concluidas/',
        {'desde': (timezone.now() - timedelta(days=1)).isoformat(),
         'id_gt': 0})

    item = next(i for i in resposta.data['resultados']
                if i['materia']['id'] == materia.pk)
    assert item['id'] == materia.pk


@pytest.mark.django_db(transaction=False)
def test_pendentes_traz_id_da_materia_no_topo(cliente_hub):
    """`PollerSapl.pollAssinaturasPendentes` lê `item.path("id")`. Sem o campo o
    cursor virava string vazia e o ciclo seguinte estourava em
    `Long.parseLong("")`.

    E o valor tem que ser o id da MATÉRIA: o hub devolve esse número como
    `id_gt` e a view filtra `materia_id__gt`. Mandar o pk do alvo faria o hub
    pedir uma página que a view não entende — releitura eterna da primeira.
    A matéria descartada antes desalinha as sequências de propósito: com
    `alvo.pk == materia.pk` o teste passaria por coincidência.
    """
    baker.make(MateriaLegislativa, numero_protocolo=300)  # desalinha os ids
    materia, alvo = criar_materia_com_alvo()
    assert alvo.pk != materia.pk

    resposta = cliente_hub.get(BASE + 'assinaturas-pendentes/', {'id_gt': 0})

    item = next(i for i in resposta.data['resultados']
                if i['materia']['id'] == materia.pk)
    assert item['id'] == materia.pk


# ---------------------------------------------------------------------------
# Cursor composto (gerado_em, id) — a matéria que materializa TARDE
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=False)
def test_pendentes_traz_gerado_em_para_o_cursor(cliente_hub):
    """Sem o campo o hub não tem como montar `CursorPorData` e a fonte trava."""
    materia, alvo = criar_materia_com_alvo()

    resposta = cliente_hub.get(BASE + 'assinaturas-pendentes/',
                               {'desde': '1970-01-01T00:00:00+00:00',
                                'id_gt': 0})

    item = next(i for i in resposta.data['resultados']
                if i['materia']['id'] == materia.pk)
    assert item['gerado_em']


@pytest.mark.django_db(transaction=False)
def test_alvo_materializado_depois_com_id_menor_ainda_e_lido(cliente_hub):
    """O modo de falha que ia engolir as 861 matérias de Franco.

    Matéria ANTIGA (id baixo) que só materializa hoje: com keyset por id ela
    nasce abaixo do cursor e nunca mais é lida — sem erro e sem WARN. Pela
    data, ela entra normalmente.
    """
    antiga = baker.make(MateriaLegislativa, numero_protocolo=201)
    recente, alvo_recente = criar_materia_com_alvo()
    assert antiga.pk < recente.pk

    # o hub já andou até depois da matéria recente
    cursor_desde = alvo_recente.gerado_em
    cursor_id = recente.pk

    # ...e SÓ AGORA a antiga materializa (conversão DOCX voltou a funcionar)
    antiga.texto_original.save('texto.pdf', ContentFile(PDF_ALVO), save=True)
    alvo_antigo = DocumentoParaAssinatura(
        materia=antiga,
        hash_sha256=hashlib.sha256(PDF_ALVO).hexdigest(),
        hash_origem=hashlib.sha256(PDF_ALVO).hexdigest())
    alvo_antigo.arquivo.save('materia_%s_alvo.pdf' % antiga.pk,
                             ContentFile(PDF_ALVO), save=True)

    resposta = cliente_hub.get(
        BASE + 'assinaturas-pendentes/',
        {'desde': cursor_desde.isoformat(), 'id_gt': cursor_id})

    ids = [i['materia']['id'] for i in resposta.data['resultados']]
    assert antiga.pk in ids


@pytest.mark.django_db(transaction=False)
def test_empate_de_gerado_em_nao_trava_o_cursor(cliente_hub):
    """Passada de recuperação materializa em lote — timestamps empatam.

    Sem o desempate por id, uma página inteira no mesmo instante devolveria
    sempre a mesma primeira página, para sempre (mesmo racional do §1.1).
    """
    primeira, alvo_a = criar_materia_com_alvo()
    segunda, alvo_b = criar_materia_com_alvo()
    instante = alvo_a.gerado_em
    DocumentoParaAssinatura.objects.filter(
        pk__in=[alvo_a.pk, alvo_b.pk]).update(gerado_em=instante)

    resposta = cliente_hub.get(
        BASE + 'assinaturas-pendentes/',
        {'desde': instante.isoformat(), 'id_gt': primeira.pk})

    ids = [i['materia']['id'] for i in resposta.data['resultados']]
    assert primeira.pk not in ids
    assert segunda.pk in ids


@pytest.mark.django_db(transaction=False)
def test_sem_desde_mantem_o_keyset_antigo_por_id(cliente_hub):
    """Compatibilidade de subida: hub da versão anterior só manda `id_gt`."""
    primeira, _ = criar_materia_com_alvo()
    segunda, _ = criar_materia_com_alvo()

    resposta = cliente_hub.get(BASE + 'assinaturas-pendentes/',
                               {'id_gt': primeira.pk})

    ids = [i['materia']['id'] for i in resposta.data['resultados']]
    assert primeira.pk not in ids
    assert segunda.pk in ids


@pytest.mark.django_db(transaction=False)
def test_desde_invalido_e_400(cliente_hub):
    resposta = cliente_hub.get(BASE + 'assinaturas-pendentes/',
                               {'desde': 'ontem', 'id_gt': 0})

    assert resposta.status_code == 400
