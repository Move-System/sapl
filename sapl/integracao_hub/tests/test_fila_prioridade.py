"""Fila de prioridade da materialização (ADR 0014).

O contrato sob teste: o save da matéria protocolada com texto MARCA (post_save,
custo de um upsert), e só o tick da rotina CONVERTE (`--fila` é o tick avulso).
O request nunca paga conversão; a matéria vira pendência em segundos; a
varredura completa segue existindo como rede de segurança.
"""
import hashlib

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command
from model_bakery import baker

from sapl.integracao_hub.models import (DocumentoParaAssinatura,
                                        MateriaParaMaterializar,
                                        PassadaMaterializacao)
from sapl.materia.models import MateriaLegislativa

PDF = b'%PDF-1.4 conteudo-original'


@pytest.fixture(autouse=True)
def base_url_configurada(settings):
    settings.SAPL_INTERNAL_URL = 'http://sapl-interno:8000'
    settings.SITE_URL = ''


def criar_materia(protocolo=100, conteudo=PDF, nome='texto.pdf'):
    materia = baker.make(MateriaLegislativa, numero_protocolo=protocolo)
    if conteudo is not None:
        materia.texto_original.save(nome, ContentFile(conteudo), save=True)
    return materia


# ---------------------------------------------------------------------------
# O evento marca — e só marca o que a materialização enxerga
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=False)
def test_save_de_materia_protocolada_com_texto_entra_na_fila(db):
    materia = criar_materia()

    assert MateriaParaMaterializar.objects.filter(materia=materia).exists()


@pytest.mark.django_db(transaction=False)
def test_materia_sem_protocolo_ou_sem_texto_fica_fora_da_fila(db):
    criar_materia(protocolo=None)
    baker.make(MateriaLegislativa, numero_protocolo=101)  # sem texto

    assert not MateriaParaMaterializar.objects.exists()


@pytest.mark.django_db(transaction=False)
def test_dois_saves_da_mesma_materia_sao_uma_marca_so(db):
    materia = criar_materia()
    materia.save()

    assert MateriaParaMaterializar.objects.filter(
        materia=materia).count() == 1


# ---------------------------------------------------------------------------
# O tick converte — só as marcadas, e esvazia a fila
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=False)
def test_tick_materializa_so_as_marcadas_e_esvazia_a_fila(db):
    marcada = criar_materia(protocolo=100)
    fora_da_fila = criar_materia(protocolo=101)
    MateriaParaMaterializar.objects.filter(materia=fora_da_fila).delete()

    call_command('materializar_pdfs_para_assinatura', '--fila')

    alvo = DocumentoParaAssinatura.objects.get(materia=marcada)
    assert alvo.hash_sha256 == hashlib.sha256(PDF).hexdigest()
    # A não marcada fica para a varredura completa — o tick não varre acervo.
    assert not DocumentoParaAssinatura.objects.filter(
        materia=fora_da_fila).exists()
    assert not MateriaParaMaterializar.objects.exists()

    passada = PassadaMaterializacao.objects.get()
    assert passada.disparo == PassadaMaterializacao.DISPARO_PRIORIDADE
    assert passada.gerados == 1
    assert passada.terminada_em is not None


@pytest.mark.django_db(transaction=False)
def test_tick_com_fila_vazia_nao_grava_passada(db):
    call_command('materializar_pdfs_para_assinatura', '--fila')

    assert not PassadaMaterializacao.objects.exists()


@pytest.mark.django_db(transaction=False)
def test_retificacao_pelo_tick_regenera_e_nao_realimenta_a_fila(db):
    """O save que a retificação faz (zerar assinatura) não pode remarcar.

    Sem a supressão, cada passada de retificação realimentaria a fila que ela
    mesma consome — a matéria nunca sairia do tick.
    """
    materia = criar_materia()
    call_command('materializar_pdfs_para_assinatura', '--fila')
    assert not MateriaParaMaterializar.objects.exists()

    retificado = b'%PDF-1.4 texto-retificado'
    materia.texto_original.save('texto.pdf', ContentFile(retificado),
                                save=True)
    assert MateriaParaMaterializar.objects.filter(materia=materia).exists()

    call_command('materializar_pdfs_para_assinatura', '--fila')

    alvo = DocumentoParaAssinatura.objects.get(materia=materia)
    assert alvo.hash_origem == hashlib.sha256(retificado).hexdigest()
    assert not MateriaParaMaterializar.objects.exists()


@pytest.mark.django_db(transaction=False)
def test_falha_desmarca_para_nao_martelar_o_onlyoffice(db, monkeypatch):
    """Falha registra a matéria travada e sai da fila — retenta na varredura.

    Manter a marca faria o tick retentar a cada 15s com o ambiente quebrado.
    """
    materia = criar_materia(nome='texto.docx', conteudo=b'docx-qualquer')

    monkeypatch.setattr(
        'sapl.integracao_hub.management.commands.'
        'materializar_pdfs_para_assinatura._origem_servida_confere',
        lambda materia, hash_origem: (True, None))
    monkeypatch.setattr(
        'sapl.materia.views_assinatura._gerar_pdf_da_materia',
        lambda materia, request: (None, 'OnlyOffice fora do ar'))

    call_command('materializar_pdfs_para_assinatura', '--fila')

    assert not DocumentoParaAssinatura.objects.filter(
        materia=materia).exists()
    assert not MateriaParaMaterializar.objects.exists()
    assert materia.falha_materializacao.motivo == 'OnlyOffice fora do ar'


@pytest.mark.django_db(transaction=False)
def test_lock_ocupado_dispensa_o_tick_e_preserva_a_marca(db):
    """Varredura no meio: o tick é dispensado e a fila espera o próximo.

    É o mesmo lock único de `em_andamento` — a marca não pode se perder só
    porque a varredura estava rodando na hora.
    """
    materia = criar_materia()
    PassadaMaterializacao.objects.create()  # em_andamento=True (lock)

    call_command('materializar_pdfs_para_assinatura', '--fila')

    assert not DocumentoParaAssinatura.objects.filter(
        materia=materia).exists()
    assert MateriaParaMaterializar.objects.filter(materia=materia).exists()


@pytest.mark.django_db(transaction=False)
def test_materia_que_saiu_do_filtro_desmarca_sem_converter(db):
    """Protocolo anulado entre o evento e o tick: desmarca, não processa.

    Processar seria materializar matéria fora do filtro da rotina; manter a
    marca seria fila que nunca esvazia.
    """
    materia = criar_materia()
    materia.numero_protocolo = None
    materia.save()  # o receiver ignora (sem protocolo), a marca antiga fica

    call_command('materializar_pdfs_para_assinatura', '--fila')

    assert not DocumentoParaAssinatura.objects.filter(
        materia=materia).exists()
    assert not MateriaParaMaterializar.objects.exists()
