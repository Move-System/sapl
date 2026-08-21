import hashlib

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone
from model_bakery import baker

from sapl.base.models import Autor
from sapl.integracao_hub.models import DocumentoParaAssinatura
from sapl.materia.models import MateriaLegislativa

PDF = b'%PDF-1.4 conteudo-original'


def criar_materia(protocolo=100, conteudo=PDF, nome='texto.pdf'):
    materia = baker.make(MateriaLegislativa, numero_protocolo=protocolo)
    if conteudo is not None:
        materia.texto_original.save(nome, ContentFile(conteudo), save=True)
    return materia


@pytest.mark.django_db(transaction=False)
def test_materializa_pdf_alvo_da_materia_protocolada(db):
    materia = criar_materia()

    call_command('materializar_pdfs_para_assinatura')

    alvo = DocumentoParaAssinatura.objects.get(materia=materia)
    assert alvo.hash_sha256 == hashlib.sha256(PDF).hexdigest()
    assert alvo.hash_origem == hashlib.sha256(PDF).hexdigest()
    alvo.arquivo.open('rb')
    assert alvo.arquivo.read() == PDF  # PDF-alvo copia os bytes do original


@pytest.mark.django_db(transaction=False)
def test_ignora_materia_sem_protocolo_ou_sem_texto(db):
    sem_protocolo = criar_materia(protocolo=None)
    sem_texto = baker.make(MateriaLegislativa, numero_protocolo=101)

    call_command('materializar_pdfs_para_assinatura')

    assert not DocumentoParaAssinatura.objects.filter(
        materia__in=[sem_protocolo, sem_texto]).exists()


@pytest.mark.django_db(transaction=False)
def test_idempotente_nao_regenera_sem_mudanca(db):
    materia = criar_materia()
    call_command('materializar_pdfs_para_assinatura')
    gerado_em = DocumentoParaAssinatura.objects.get(materia=materia).gerado_em

    call_command('materializar_pdfs_para_assinatura')

    alvo = DocumentoParaAssinatura.objects.get(materia=materia)
    assert alvo.gerado_em == gerado_em  # nada mudou, nada regerado (cron-safe)
    assert DocumentoParaAssinatura.objects.count() == 1


@pytest.mark.django_db(transaction=False)
def test_retificacao_regenera_alvo_e_zera_assinatura(db):
    """Decisão do arquiteto (19/08, refinamento §5.1): retificação ZERA.

    Texto retificado depois da conversão → alvo defasado. O command regenera o
    PDF-alvo E limpa o processo de assinatura inteiro — mesmo efeito da rotina
    `materia_remover_assinatura` do SAPL. Assinatura sobre texto retificado é
    impossível por construção.
    """
    materia = criar_materia()
    call_command('materializar_pdfs_para_assinatura')

    # Alguém assinou o alvo antigo...
    usuario = baker.make('auth.User', username='ver-a')
    materia.refresh_from_db()
    materia.pdf_assinado.save(
        'materia_%s_assinado_1.pdf' % materia.pk,
        ContentFile(b'%PDF-assinado-velho'), save=False)
    materia.assinatura_info = [{'signed_by': 'ver-a', 'nome': 'Ver. A'}]
    materia.assinado_em = timezone.now()
    materia.assinado_por = usuario
    materia.codigo_autenticacao = 'ABCD1234ABCD1234'
    materia.save()

    # ...e o texto_original foi retificado.
    retificado = b'%PDF-1.4 texto-retificado'
    materia.texto_original.save('texto.pdf', ContentFile(retificado),
                                save=True)

    call_command('materializar_pdfs_para_assinatura')

    alvo = DocumentoParaAssinatura.objects.get(materia=materia)
    assert alvo.hash_sha256 == hashlib.sha256(retificado).hexdigest()
    assert alvo.hash_origem == hashlib.sha256(retificado).hexdigest()

    materia.refresh_from_db()
    assert not materia.pdf_assinado
    assert materia.assinatura_info is None
    assert materia.assinado_em is None
    assert materia.assinado_por is None
    assert materia.codigo_autenticacao is None


@pytest.mark.django_db(transaction=False)
def test_falha_de_conversao_de_uma_materia_nao_trava_as_demais(
        db, monkeypatch):
    quebrada = criar_materia(protocolo=102, nome='texto.docx',
                             conteudo=b'docx-sem-onlyoffice')
    boa = criar_materia(protocolo=103)

    def gerar(materia, request):
        if materia.pk == quebrada.pk:
            return None, 'OnlyOffice fora do ar'
        return PDF, None

    monkeypatch.setattr(
        'sapl.materia.views_assinatura._gerar_pdf_da_materia', gerar)

    call_command('materializar_pdfs_para_assinatura')

    assert not DocumentoParaAssinatura.objects.filter(
        materia=quebrada).exists()
    assert DocumentoParaAssinatura.objects.filter(materia=boa).exists()
