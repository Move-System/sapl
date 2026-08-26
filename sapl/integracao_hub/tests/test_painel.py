"""Testes do painel de materialização (AB#1480).

O que estes testes protegem, em ordem de importância:

1. **O lock.** `em_andamento` é um índice único usado como semáforo entre
   processos. Se ele parar de barrar, laço e botão convertem o mesmo documento
   ao mesmo tempo — e a falha só apareceria em produção, num acervo grande.
2. **O painel dizer a verdade.** A tela existe para responder sem shell; uma
   tela que mostra número errado é pior do que não ter tela.
3. **O `--somente-novos` do botão.** Perder essa flag apaga assinatura já feita,
   em lote e sem volta (§5.1).
"""
import hashlib
from unittest import mock

import pytest
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from sapl.integracao_hub.models import (MateriaComFalhaMaterializacao,
                                        PassadaMaterializacao)
from sapl.materia.models import MateriaLegislativa

PDF = b'%PDF-1.4 conteudo-original'
CAMINHO_NO_MENU = '/sistema/integracao/materializacao/'


@pytest.fixture(autouse=True)
def base_url_configurada(settings):
    settings.SAPL_INTERNAL_URL = 'http://sapl-interno:8000'
    settings.SITE_URL = ''


def criar_materia(protocolo=100, conteudo=PDF, nome='texto.pdf'):
    materia = baker.make(MateriaLegislativa, numero_protocolo=protocolo)
    if conteudo is not None:
        materia.texto_original.save(nome, ContentFile(conteudo), save=True)
    return materia


@pytest.fixture()
def operador(db):
    """Usuário com `pode_integrar` — a permissão que já gateia a API."""
    usuario = baker.make('auth.User', username='operador-teste')
    usuario.set_password('senha-de-teste')
    usuario.save()
    usuario.user_permissions.add(Permission.objects.get(
        content_type__app_label='integracao_hub', codename='pode_integrar'))
    cliente = Client()
    cliente.force_login(usuario)
    return cliente


@pytest.fixture()
def sem_permissao(db):
    usuario = baker.make('auth.User', username='qualquer-um')
    cliente = Client()
    cliente.force_login(usuario)
    return cliente


# ---------------------------------------------------------------- a passada

@pytest.mark.django_db(transaction=False)
def test_passada_registra_contadores_e_fecha_o_lock(db):
    criar_materia()

    call_command('materializar_pdfs_para_assinatura')

    passada = PassadaMaterializacao.objects.get()
    assert passada.gerados == 1
    assert passada.terminada_em is not None
    # NULL, nunca False: é o que libera o índice único para a próxima passada.
    assert passada.em_andamento is None
    assert passada.disparo == PassadaMaterializacao.DISPARO_LACO


@pytest.mark.django_db(transaction=False)
def test_passada_manual_guarda_quem_disparou(db):
    criar_materia()

    call_command('materializar_pdfs_para_assinatura',
                 '--somente-novos', disparada_por='fulano')

    passada = PassadaMaterializacao.objects.get()
    assert passada.disparo == PassadaMaterializacao.DISPARO_MANUAL
    assert passada.disparada_por == 'fulano'
    assert passada.somente_novos is True


@pytest.mark.django_db(transaction=False)
def test_lock_dispensa_passada_concorrente(db):
    """Com uma passada aberta, a segunda não roda — nem cria linha."""
    aberta = PassadaMaterializacao.objects.create()
    criar_materia()

    call_command('materializar_pdfs_para_assinatura')

    assert PassadaMaterializacao.objects.count() == 1
    assert PassadaMaterializacao.objects.get().pk == aberta.pk
    # E, sobretudo, não converteu nada por baixo do lock.
    assert not MateriaComFalhaMaterializacao.objects.exists()


@pytest.mark.django_db(transaction=False)
def test_passada_orfa_e_fechada_e_libera_o_lock(db):
    """Processo morto sem fechar a linha travaria a rotina para sempre."""
    orfa = PassadaMaterializacao.objects.create()
    # `iniciada_em` é auto_now_add; só um UPDATE direto envelhece a linha.
    PassadaMaterializacao.objects.filter(pk=orfa.pk).update(
        iniciada_em=timezone.now() - timezone.timedelta(hours=7))
    criar_materia()

    call_command('materializar_pdfs_para_assinatura')

    orfa.refresh_from_db()
    assert orfa.abandonada is True
    assert orfa.em_andamento is None
    nova = PassadaMaterializacao.objects.exclude(pk=orfa.pk).get()
    assert nova.gerados == 1


# ------------------------------------------------------- matérias travadas

@pytest.mark.django_db(transaction=False)
def test_falha_vira_linha_e_sucesso_apaga(db):
    """A lista da tela é 'travadas agora', não histórico de tentativas."""
    # DOCX cai no caminho do OnlyOffice, que não existe no teste — falha.
    materia = criar_materia(conteudo=b'nao-e-pdf', nome='texto.docx')

    call_command('materializar_pdfs_para_assinatura')

    falha = MateriaComFalhaMaterializacao.objects.get(materia=materia)
    assert falha.motivo

    # Agora o texto vira PDF: o caminho não passa pelo OnlyOffice e funciona.
    materia.texto_original.save('texto.pdf', ContentFile(PDF), save=True)
    call_command('materializar_pdfs_para_assinatura')

    assert not MateriaComFalhaMaterializacao.objects.filter(
        materia=materia).exists()


@pytest.mark.django_db(transaction=False)
def test_motivo_predominante_aponta_o_que_derruba_o_lote(db):
    passada = PassadaMaterializacao.objects.create(
        motivos={'código -4': 861, 'outro': 2})

    motivo, quantas = passada.motivo_predominante

    assert motivo == 'código -4'
    assert quantas == 861


# ------------------------------------------------------------------- tela

@pytest.mark.django_db(transaction=False)
def test_painel_exige_pode_integrar(sem_permissao):
    resposta = sem_permissao.get(
        reverse('integracao_hub_painel_materializacao'))

    assert resposta.status_code == 403


@pytest.mark.django_db(transaction=False)
def test_painel_mostra_a_configuracao_que_decide_a_conversao(operador, settings):
    """A causa do incidente de 25/08 era um valor que exigia shell para ler."""
    settings.SAPL_INTERNAL_URL = 'https://demo.exemplo.gov.br'

    resposta = operador.get(reverse('integracao_hub_painel_materializacao'))

    assert resposta.status_code == 200
    assert b'demo.exemplo.gov.br' in resposta.content


@pytest.mark.django_db(transaction=False)
def test_painel_diz_quando_a_rotina_nunca_rodou(operador):
    """Tabela vazia É um diagnóstico — foi a resposta certa em 25/08."""
    resposta = operador.get(reverse('integracao_hub_painel_materializacao'))

    assert resposta.context['nunca_rodou'] is True


@pytest.mark.django_db(transaction=False)
def test_painel_nao_confunde_passada_aberta_com_resultado(operador):
    """Linha em andamento tem contadores zerados; não pode virar 'a última'."""
    concluida = PassadaMaterializacao.objects.create()
    concluida.gerados = 7
    concluida.em_andamento = None
    concluida.terminada_em = timezone.now()
    concluida.save()
    PassadaMaterializacao.objects.create()  # a aberta, contadores em zero

    resposta = operador.get(reverse('integracao_hub_painel_materializacao'))

    assert resposta.context['ultima_concluida'].pk == concluida.pk
    assert resposta.context['em_andamento'] is not None


# ---------------------------------------------------------------- disparo

@pytest.mark.django_db(transaction=False)
def test_disparo_roda_sempre_em_somente_novos(operador):
    """Perder esta flag apaga assinatura já feita, em lote (§5.1)."""
    with mock.patch('sapl.integracao_hub.painel.subprocess.Popen') as popen:
        resposta = operador.post(
            reverse('integracao_hub_disparar_materializacao'))

    assert resposta.status_code == 302
    comando = popen.call_args[0][0]
    assert '--somente-novos' in comando
    assert 'materializar_pdfs_para_assinatura' in comando
    assert 'operador-teste' in comando


@pytest.mark.django_db(transaction=False)
def test_disparo_recusa_com_passada_em_andamento(operador):
    PassadaMaterializacao.objects.create()

    with mock.patch('sapl.integracao_hub.painel.subprocess.Popen') as popen:
        operador.post(reverse('integracao_hub_disparar_materializacao'))

    popen.assert_not_called()


@pytest.mark.django_db(transaction=False)
def test_disparo_exige_pode_integrar(sem_permissao):
    with mock.patch('sapl.integracao_hub.painel.subprocess.Popen') as popen:
        resposta = sem_permissao.post(
            reverse('integracao_hub_disparar_materializacao'))

    assert resposta.status_code == 403
    popen.assert_not_called()


@pytest.mark.django_db(transaction=False)
def test_menu_aponta_para_a_rota_do_painel(db):
    """O menu usa caminho literal; este teste impede a divergência silenciosa.

    `templatetags/menus.py` prefixa nome de rota sem `:` com o app da página
    (`sapl.base` na tela de Tabelas Auxiliares) e levanta exceção se não
    resolver — derrubando a tela inteira. Por isso o YAML traz o caminho cru, e
    por isso ele precisa de guarda.
    """
    assert reverse(
        'integracao_hub_painel_materializacao') == CAMINHO_NO_MENU

    with open('sapl/templates/menu_tabelas_auxiliares.yaml',
              encoding='utf-8') as arquivo:
        assert CAMINHO_NO_MENU in arquivo.read()
