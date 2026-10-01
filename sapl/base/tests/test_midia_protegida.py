"""Controle de acesso aos arquivos de mídia (AB#1583).

O que estes testes protegem é um vazamento real: antes, `/media/` era servido
por alias no nginx e qualquer pessoa com a URL baixava o arquivo. Em Franco da
Rocha isso expôs processos ainda em tramitação, encontrados por robô.

A regra mais importante aqui é a do default: modelo que ninguém classificou
precisa cair em "restrito". Um teste que falhe para o lado permissivo devolve o
vazamento sem ninguém perceber, então há caso explícito para isso.
"""
import datetime

import pytest
from model_bakery import baker

from sapl.base.midia_protegida import pode_acessar
from sapl.materia.models import DocumentoAcessorio, MateriaLegislativa


ONTEM = datetime.date.today() - datetime.timedelta(days=1)
AMANHA = datetime.date.today() + datetime.timedelta(days=1)


class UsuarioAnonimo:
    is_authenticated = False
    username = 'anonimo'


class UsuarioLogado:
    is_authenticated = True
    username = 'operador'


ANONIMO = UsuarioAnonimo()
LOGADO = UsuarioLogado()


def _materia_com_texto(caminho):
    return baker.make(MateriaLegislativa, texto_original=caminho)


def _pauta(materia, data, modelo='sessao.ExpedienteMateria'):
    baker.make(modelo, materia=materia, data_ordem=data, numero_ordem=1)


# --- faixa 1: público sempre -------------------------------------------------

@pytest.mark.parametrize('caminho', [
    'sapl/public/casalegislativa/1/brasao.png',
    'sapl/public/partido/3/logo.png',
    'sapl/public/normajuridica/2026/10/lei.pdf',
    'sapl/public/anexonormajuridica/5/anexo.pdf',
    'sapl/public/sessaoplenaria/21/ata.pdf',
    'sapl/public/audienciapublica/2/pauta.pdf',
])
def test_arquivo_publico_dispensa_login(caminho, db):
    """Brasão, norma publicada, ata e audiência são transparência.

    Fechá-los quebraria o cabeçalho de todas as páginas e criaria problema
    legal — a Casa é obrigada a publicar.
    """
    assert pode_acessar(ANONIMO, caminho) is True


# --- faixa 2: liberado pelo plenário ----------------------------------------

def test_materia_sem_pauta_e_negada_a_anonimo(db):
    caminho = 'sapl/public/materialegislativa/2026/1/texto.pdf'
    _materia_com_texto(caminho)

    assert pode_acessar(ANONIMO, caminho) is False


def test_materia_com_sessao_futura_ainda_e_negada(db):
    """O caso que motivou o card.

    A pauta é montada dias antes da sessão. Liberar na montagem exporia
    exatamente o que o cliente não quer: assunto que ainda não foi a plenário.
    """
    caminho = 'sapl/public/materialegislativa/2026/2/texto.pdf'
    materia = _materia_com_texto(caminho)
    _pauta(materia, AMANHA)

    assert pode_acessar(ANONIMO, caminho) is False


def test_materia_apos_a_sessao_fica_publica(db):
    caminho = 'sapl/public/materialegislativa/2026/3/texto.pdf'
    materia = _materia_com_texto(caminho)
    _pauta(materia, ONTEM)

    assert pode_acessar(ANONIMO, caminho) is True


def test_ordem_do_dia_tambem_libera(db):
    """Matéria pode ir a plenário pelo expediente ou pela ordem do dia."""
    caminho = 'sapl/public/materialegislativa/2026/4/texto.pdf'
    materia = _materia_com_texto(caminho)
    _pauta(materia, ONTEM, modelo='sessao.OrdemDia')

    assert pode_acessar(ANONIMO, caminho) is True


def test_pdf_assinado_da_materia_segue_a_mesma_regra(db):
    """O PDF assinado é o documento que mais interessa a quem está garimpando."""
    caminho = 'sapl/public/materialegislativa/2026/5/assinado.pdf'
    materia = baker.make(MateriaLegislativa, pdf_assinado=caminho)

    assert pode_acessar(ANONIMO, caminho) is False

    _pauta(materia, ONTEM)
    assert pode_acessar(ANONIMO, caminho) is True


def test_documento_acessorio_acompanha_a_materia(db):
    """Parecer segue a matéria: quem acompanha a sessão lê o que foi votado."""
    caminho = 'sapl/public/documentoacessorio/2026/9/parecer.pdf'
    materia = baker.make(MateriaLegislativa)
    baker.make(DocumentoAcessorio, materia=materia, arquivo=caminho)

    assert pode_acessar(ANONIMO, caminho) is False

    _pauta(materia, ONTEM)
    assert pode_acessar(ANONIMO, caminho) is True


def test_documento_acessorio_de_comissao_nao_vaza_pela_colisao(db):
    """`documentoacessorio` existe em `materia` e em `comissoes`.

    Os dois modelos gravam na mesma pasta, então o caminho sozinho não
    distingue. Não achando em matéria, a resposta tem que ser "restrito" — o
    contrário faria o arquivo de comissão herdar a liberação do plenário.
    """
    caminho = 'sapl/public/documentoacessorio/2026/777/doc-de-comissao.pdf'

    assert pode_acessar(ANONIMO, caminho) is False


# --- faixa 3: sempre restrito ------------------------------------------------

@pytest.mark.parametrize('caminho', [
    'sapl/private/proposicao/2026/7/texto.pdf',
    'sapl/public/anexoproposicao/2026/7/anexo.pdf',
    'sapl/private/documentoadministrativo/2026/8/doc.pdf',
    'sapl/public/justificativaausencia/4/atestado.pdf',
    'sapl/public/tcearquivo/12/prestacao.pdf',
])
def test_arquivo_restrito_exige_login(caminho, db):
    """Inclui a justificativa de ausência, que pode conter atestado médico."""
    assert pode_acessar(ANONIMO, caminho) is False


def test_modelo_desconhecido_e_restrito_por_padrao(db):
    """O default precisa ser fechado.

    Modelo novo que ninguém classificar entra como restrito. Se o default
    fosse aberto, cada feature futura reabriria o vazamento em silêncio.
    """
    assert pode_acessar(ANONIMO, 'sapl/public/modelo_que_nao_existe/1/x.pdf') is False
    assert pode_acessar(ANONIMO, 'qualquer/coisa/fora/do/padrao.pdf') is False


def test_usuario_logado_acessa_restrito(db):
    assert pode_acessar(LOGADO, 'sapl/private/proposicao/2026/7/texto.pdf') is True
    assert pode_acessar(LOGADO, 'sapl/public/materialegislativa/2026/1/t.pdf') is True


# --- view: o que chega ao navegador -----------------------------------------

def test_anonimo_e_mandado_ao_login_e_nao_recebe_o_arquivo(client, db):
    """Negar precisa ser um desvio para o login, não um 200 com o PDF."""
    caminho = 'sapl/public/materialegislativa/2026/6/texto.pdf'
    _materia_com_texto(caminho)

    resposta = client.get('/media/' + caminho)

    assert resposta.status_code == 302
    assert '/login' in resposta.url
    assert 'X-Accel-Redirect' not in resposta


def test_arquivo_liberado_sai_por_x_accel_e_nao_pelo_python(tmpdir, client, db):
    """O Django autoriza; quem lê o disco é o nginx.

    Importa porque a Casa sobe PDFs de mais de 100 MB — passar esse conteúdo
    pelo processo Python desperdiçaria memória a cada download.
    """
    from django.test import override_settings

    caminho = 'sapl/public/casalegislativa/1/brasao.png'
    destino = tmpdir.join('sapl', 'public', 'casalegislativa', '1')
    destino.ensure_dir()
    destino.join('brasao.png').write('conteudo')

    with override_settings(MEDIA_ROOT=str(tmpdir), DEBUG=False):
        resposta = client.get('/media/' + caminho)

    assert resposta.status_code == 200
    assert resposta['X-Accel-Redirect'] == '/midia-protegida/' + caminho
    assert resposta.content == b''


def test_path_traversal_nao_escapa_do_media_root(client, db):
    """`../` não pode virar leitura de /etc/passwd."""
    resposta = client.get('/media/../../etc/passwd')

    assert resposta.status_code in (301, 302, 404)
    assert 'X-Accel-Redirect' not in resposta
