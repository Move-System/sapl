"""
Testes das duas regressões de assinatura corrigidas juntas:

1. A 2ª assinatura via microserviço precisa reenviar o `codigo_autenticacao`
   emitido na 1ª (o hash não é recalculável a partir do PDF já assinado). O
   parâmetro existia em `_assinar_pdf_com_pagina_auth` mas nenhuma view o
   passava, e o microserviço respondia 400.

2. Pendência é POR AUTOR: a matéria que um coautor já assinou continua pendente
   para os demais. O SAPL web olhava `pdf_assinado` e a escondia de todo mundo
   na primeira assinatura.
"""
import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from model_bakery import baker

from sapl.base.models import Autor, OperadorAutor
from sapl.materia.models import Autoria, MateriaLegislativa
from sapl.parlamentares.models import Parlamentar, Votante

PDF = b'%PDF-1.4 documento'


def _autor_parlamentar(nome, username):
    """Autor com titular resolvível por Votante — o vínculo real do SAPL."""
    user = baker.make('auth.User', username=username)
    parlamentar = baker.make(Parlamentar, nome_parlamentar=nome, ativo=True)
    baker.make(Votante, parlamentar=parlamentar, user=user)
    autor = baker.make(
        Autor, nome=nome,
        content_type=ContentType.objects.get_for_model(Parlamentar),
        object_id=parlamentar.pk)
    baker.make(OperadorAutor, autor=autor, user=user)
    return autor, user


@pytest.fixture()
def materia_coautoria(db):
    """Matéria de dois autores, assinada só pelo primeiro."""
    materia = baker.make(
        MateriaLegislativa,
        numero=820, ano=2026,
        texto_original=SimpleUploadedFile('texto.pdf', PDF),
    )
    autor_a, user_a = _autor_parlamentar('KINHO ANDRADE', 'kinho')
    autor_b, user_b = _autor_parlamentar('ERIC VALINI', 'eric')
    baker.make(Autoria, materia=materia, autor=autor_a, primeiro_autor=True)
    baker.make(Autoria, materia=materia, autor=autor_b)

    materia.pdf_assinado.save('assinado.pdf', ContentFile(PDF), save=False)
    materia.assinatura_info = [{'signed_by': 'kinho', 'nome_assinante': 'KINHO'}]
    materia.codigo_autenticacao = 'D6BF54DFA21C2CD2'
    materia.save()
    return materia, (autor_a, user_a), (autor_b, user_b)


# =============================================================================
# 1. codigo_autenticacao na 2ª assinatura
# =============================================================================

def test_segunda_assinatura_reenvia_codigo_autenticacao(
        materia_coautoria, client, monkeypatch):
    """Sem o código, o microserviço recusa com 400: ele não recalcula o hash."""
    from sapl.materia import assinatura_api_client, views_assinatura

    materia, _, (_, user_b) = materia_coautoria
    enviado = {}

    class _Resultado:
        pdf = b'%PDF-1.4 assinado-2x'
        codigo_autenticacao = 'D6BF54DFA21C2CD2'
        signature_index = 1
        auth_page_aplicada = False
        auth_page_suportado = True

    def _fake_assinar(pdf_bytes, **kwargs):
        enviado.update(kwargs)
        return _Resultado()

    monkeypatch.setattr(views_assinatura, '_usar_api_externa', lambda: True)
    monkeypatch.setattr(views_assinatura, '_metadados_certificado_via_api',
                        lambda *a, **k: {})
    monkeypatch.setattr(views_assinatura, '_ler_brasao', lambda: None)
    monkeypatch.setattr(assinatura_api_client,
                        'assinar_pdf_com_pagina_autenticacao', _fake_assinar)

    client.force_login(user_b)
    resposta = client.post(
        f'/materia/{materia.pk}/assinar/a1/',
        {'certificado': SimpleUploadedFile('cert.pfx', b'pfx'), 'senha': 'x'},
    )

    assert resposta.status_code == 200, resposta.content
    assert enviado['codigo_autenticacao'] == 'D6BF54DFA21C2CD2'


def test_primeira_assinatura_nao_manda_codigo(db, client, monkeypatch):
    """Na 1ª o microserviço deriva o código do próprio PDF — mandar seria errado."""
    from sapl.materia import assinatura_api_client, views_assinatura

    materia = baker.make(
        MateriaLegislativa, numero=821, ano=2026,
        texto_original=SimpleUploadedFile('texto.pdf', PDF))
    _, user = _autor_parlamentar('KINHO ANDRADE', 'kinho1')
    enviado = {}

    class _Resultado:
        pdf = b'%PDF-1.4 assinado'
        codigo_autenticacao = 'NOVOCODIGO123456'
        signature_index = 0
        auth_page_aplicada = True
        auth_page_suportado = True

    monkeypatch.setattr(views_assinatura, '_usar_api_externa', lambda: True)
    monkeypatch.setattr(views_assinatura, '_metadados_certificado_via_api',
                        lambda *a, **k: {})
    monkeypatch.setattr(views_assinatura, '_ler_brasao', lambda: None)
    monkeypatch.setattr(views_assinatura, '_gerar_pdf_da_materia',
                        lambda *a, **k: (PDF, None))
    monkeypatch.setattr(
        assinatura_api_client, 'assinar_pdf_com_pagina_autenticacao',
        lambda pdf_bytes, **kw: (enviado.update(kw), _Resultado())[1])

    client.force_login(user)
    resposta = client.post(
        f'/materia/{materia.pk}/assinar/a1/',
        {'certificado': SimpleUploadedFile('cert.pfx', b'pfx'), 'senha': 'x'})

    assert resposta.status_code == 200, resposta.content
    assert enviado['codigo_autenticacao'] is None
    materia.refresh_from_db()
    assert materia.codigo_autenticacao == 'NOVOCODIGO123456'


# =============================================================================
# 2. Pendência por autor
# =============================================================================

def test_coautor_que_nao_assinou_segue_pendente(materia_coautoria):
    from sapl.materia.pendencias import autores_pendentes, filtrar_pendentes

    materia, (autor_a, _), (autor_b, _) = materia_coautoria
    qs = MateriaLegislativa.objects.all()

    assert autores_pendentes(materia) == [autor_b.pk]
    assert filtrar_pendentes(qs, autores=[autor_b]).filter(pk=materia.pk).exists()
    assert not filtrar_pendentes(qs, autores=[autor_a]).filter(pk=materia.pk).exists()


def test_pendente_e_assinada_sao_complementares(materia_coautoria):
    from sapl.materia.pendencias import filtrar_assinadas, filtrar_pendentes

    materia, (autor_a, _), (autor_b, _) = materia_coautoria
    qs = MateriaLegislativa.objects.all()

    assert filtrar_assinadas(qs, autores=[autor_a]).filter(pk=materia.pk).exists()
    assert not filtrar_assinadas(qs, autores=[autor_b]).filter(pk=materia.pk).exists()


def test_badge_do_coautor_nao_zera_apos_primeira_assinatura(materia_coautoria):
    from django.core.cache import cache
    from django.test import RequestFactory

    from sapl.context_processors import pendencias_assinatura

    materia, (_, user_a), (_, user_b) = materia_coautoria
    cache.clear()

    def _total(user):
        cache.clear()
        pedido = RequestFactory().get('/')
        pedido.user = user
        return pendencias_assinatura(pedido)['pendencias_assinatura_total']

    assert _total(user_b) == 1   # Eric ainda deve assinar
    assert _total(user_a) == 0   # Kinho já assinou


def test_filtro_da_pesquisa_acompanha_o_badge(materia_coautoria):
    """Badge e resultado da pesquisa precisam contar a mesma coisa."""
    from sapl.materia.forms import MateriaLegislativaFilterSet

    materia, (autor_a, _), (autor_b, _) = materia_coautoria
    qs = MateriaLegislativa.objects.all()

    def _pks(autor_pk, status):
        fs = MateriaLegislativaFilterSet(
            data={'autoria__autor': str(autor_pk), 'status_assinatura': status},
            queryset=qs)
        return list(fs.qs.values_list('pk', flat=True))

    assert materia.pk in _pks(autor_b.pk, 'pendente')
    assert materia.pk not in _pks(autor_a.pk, 'pendente')
    assert materia.pk in _pks(autor_a.pk, 'assinada')


def test_forma_agregada_sem_autor_no_contexto(materia_coautoria):
    """Pesquisa livre: ainda falta assinatura de autor → pendente."""
    from sapl.materia.pendencias import filtrar_assinadas, filtrar_pendentes

    materia, _, _ = materia_coautoria
    qs = MateriaLegislativa.objects.all()

    assert filtrar_pendentes(qs).filter(pk=materia.pk).exists()
    assert not filtrar_assinadas(qs).filter(pk=materia.pk).exists()


def test_materia_sem_autoria_e_sem_assinatura_continua_pendente(db):
    """Comportamento antigo preservado: `max(autores, 1)` na forma agregada."""
    from sapl.materia.pendencias import filtrar_pendentes

    materia = baker.make(
        MateriaLegislativa, numero=999, ano=2026,
        texto_original=SimpleUploadedFile('texto.pdf', PDF))
    assert filtrar_pendentes(
        MateriaLegislativa.objects.all()).filter(pk=materia.pk).exists()


def test_titular_indeterminavel_conta_como_pendente(db):
    """Sem como confirmar que assinou, a matéria fica visível — não some calada."""
    from sapl.materia.pendencias import filtrar_pendentes, resolver_titular

    materia = baker.make(
        MateriaLegislativa, numero=998, ano=2026,
        texto_original=SimpleUploadedFile('texto.pdf', PDF))
    parlamentar = baker.make(Parlamentar, nome_parlamentar='AMBIGUO', ativo=True)
    baker.make(Votante, parlamentar=parlamentar,
               user=baker.make('auth.User', username='v1'))
    baker.make(Votante, parlamentar=parlamentar,
               user=baker.make('auth.User', username='v2'))
    autor = baker.make(
        Autor, nome='AMBIGUO',
        content_type=ContentType.objects.get_for_model(Parlamentar),
        object_id=parlamentar.pk)
    baker.make(Autoria, materia=materia, autor=autor)
    materia.assinatura_info = [{'signed_by': 'v1'}]
    materia.save()

    assert resolver_titular(autor) is None
    assert filtrar_pendentes(
        MateriaLegislativa.objects.all(),
        autores=[autor]).filter(pk=materia.pk).exists()


def test_assinatura_info_no_formato_legado_dict(db):
    """O campo tem dois formatos no banco; a regra precisa ler os dois."""
    from sapl.materia.pendencias import filtrar_pendentes

    materia = baker.make(
        MateriaLegislativa, numero=997, ano=2026,
        texto_original=SimpleUploadedFile('texto.pdf', PDF))
    autor, _ = _autor_parlamentar('LEGADO', 'legado')
    baker.make(Autoria, materia=materia, autor=autor)
    materia.assinatura_info = {'signed_by': 'legado'}  # dict, não lista
    materia.save()

    assert not filtrar_pendentes(
        MateriaLegislativa.objects.all(),
        autores=[autor]).filter(pk=materia.pk).exists()
