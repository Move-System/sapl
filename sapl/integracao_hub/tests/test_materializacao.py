import hashlib

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from model_bakery import baker

from sapl.base.models import Autor
from sapl.integracao_hub.models import DocumentoParaAssinatura
from sapl.materia.models import MateriaLegislativa

PDF = b'%PDF-1.4 conteudo-original'


@pytest.fixture(autouse=True)
def base_url_configurada(settings):
    """Toda materializacao pressupoe uma base URL — o comando recusa rodar sem.

    Fica em autouse porque a ausencia dela nao e um caso de borda a exercitar em
    cada teste: e erro de ambiente, e tem os seus proprios dois testes abaixo.
    """
    settings.SAPL_INTERNAL_URL = 'http://sapl-interno:8000'
    settings.SITE_URL = ''


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


# ---------------------------------------------------------------------------
# Modo laço (--intervalo): a rotina sobe junto do serviço, não é passo manual
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=False)
def test_sem_intervalo_roda_uma_passada_e_sai(db):
    """O padrão continua sendo a invocação manual de uma passada só."""
    materia = criar_materia(protocolo=700)

    call_command('materializar_pdfs_para_assinatura')

    assert DocumentoParaAssinatura.objects.filter(materia=materia).exists()


@pytest.mark.django_db(transaction=False)
def test_com_intervalo_fica_em_laco_e_dorme_entre_passadas(db, monkeypatch):
    """Com --intervalo o comando NÃO retorna: é o modo que o start.sh usa.

    Sem esse laço a materialização vira passo manual de implantação, e matéria
    protocolada nunca vira pendência no app — falha muda, sem erro nenhum.
    Aqui o sleep corta o laço na terceira chamada para o teste terminar.
    """
    criar_materia(protocolo=701)
    dormidas = []

    def sleep_que_interrompe(segundos):
        dormidas.append(segundos)
        if len(dormidas) == 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(
        'sapl.integracao_hub.management.commands'
        '.materializar_pdfs_para_assinatura.time.sleep',
        sleep_que_interrompe)

    with pytest.raises(KeyboardInterrupt):
        call_command('materializar_pdfs_para_assinatura', intervalo=30)

    assert dormidas == [30, 30, 30]


@pytest.mark.django_db(transaction=False)
def test_laco_sobrevive_a_passada_que_estoura(db, monkeypatch):
    """Se o laço morrer, a materialização para de vez e ninguém percebe."""
    from sapl.integracao_hub.management.commands import (
        materializar_pdfs_para_assinatura as cmd)

    passadas = []

    def passada_que_explode(self):
        passadas.append(1)
        raise RuntimeError('banco caiu no meio da varredura')

    monkeypatch.setattr(cmd.Command, '_passada', passada_que_explode)

    def sleep_que_interrompe(segundos):
        if len(passadas) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(cmd.time, 'sleep', sleep_que_interrompe)

    with pytest.raises(KeyboardInterrupt):
        call_command('materializar_pdfs_para_assinatura', intervalo=5)

    assert len(passadas) == 2, 'o laço deve seguir apos a passada que estourou'


# ---------------------------------------------------------------------------
# Guarda de configuração: sem base URL o OnlyOffice não baixa nada
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=False)
def test_recusa_rodar_sem_nenhuma_base_url(db, settings):
    """O modo de falha que custou o acervo de Franco (22/08/2026).

    Sem SAPL_INTERNAL_URL nem SITE_URL a URL de download sai sem host, o
    OnlyOffice responde erro e TODA matéria DOCX falha na conversão — 861 delas,
    cada uma como um `logger.error` que ninguém lê, enquanto os poucos PDF
    passavam e davam a impressão de rotina viva. Erro de ambiente morre no
    começo, não em 861 falhas por documento.
    """
    settings.SAPL_INTERNAL_URL = ''
    settings.SITE_URL = ''
    materia = criar_materia()

    with pytest.raises(CommandError) as erro:
        call_command('materializar_pdfs_para_assinatura')

    assert 'SAPL_INTERNAL_URL' in str(erro.value)
    assert not DocumentoParaAssinatura.objects.filter(materia=materia).exists()


@pytest.mark.django_db(transaction=False)
def test_site_url_sozinha_basta(db, settings):
    """SITE_URL é o fallback legítimo — a guarda pega ausência das DUAS."""
    settings.SAPL_INTERNAL_URL = ''
    settings.SITE_URL = 'https://sapl.exemplo.gov.br'
    materia = criar_materia()

    call_command('materializar_pdfs_para_assinatura')

    assert DocumentoParaAssinatura.objects.filter(materia=materia).exists()


@pytest.mark.django_db(transaction=False)
def test_passada_sem_nenhum_avanco_grita_no_stderr(db, monkeypatch, capsys):
    """Falha sem nenhum gerado é ambiente parado, não documento podre avulso.

    É o resumo que passava por linha de rotina: `0 gerados, 873 falhas` não se
    distingue de um dia normal no meio do log.
    """
    criar_materia(protocolo=201, nome='a.docx', conteudo=b'docx')
    criar_materia(protocolo=202, nome='b.docx', conteudo=b'docx')

    monkeypatch.setattr(
        'sapl.materia.views_assinatura._gerar_pdf_da_materia',
        lambda materia, request: (None, 'OnlyOffice: codigo -8'))

    call_command('materializar_pdfs_para_assinatura')

    erro = capsys.readouterr().err
    assert 'NENHUM PDF-alvo gerado' in erro
    assert 'e ambiente, nao documento' in erro
