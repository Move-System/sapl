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
    Desde o ADR 0014 o laço dorme o TICK (fila de prioridade), não o intervalo
    — a varredura completa é agendada por relógio, entre os ticks. Aqui o sleep
    corta o laço na terceira chamada para o teste terminar.
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
        call_command('materializar_pdfs_para_assinatura', intervalo=30,
                     tick=10)

    assert dormidas == [10, 10, 10]


@pytest.mark.django_db(transaction=False)
def test_laco_sobrevive_a_passada_que_estoura(db, monkeypatch):
    """Se o laço morrer, a materialização para de vez e ninguém percebe."""
    from sapl.integracao_hub.management.commands import (
        materializar_pdfs_para_assinatura as cmd)

    # Matéria marcada mantém a fila de prioridade ocupada: a segunda passada do
    # teste é um tick, e ele também não pode derrubar o laço.
    criar_materia(protocolo=702)
    passadas = []

    def passada_que_explode(self, *args, **kwargs):
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


MOD = ('sapl.integracao_hub.management.commands.'
       'materializar_pdfs_para_assinatura')


@pytest.fixture
def origem_confere(monkeypatch):
    """Neutraliza a conferência de integridade — ela tem os seus próprios testes."""
    monkeypatch.setattr(MOD + '._origem_servida_confere',
                        lambda materia, hash_origem: (True, None))


@pytest.mark.django_db(transaction=False)
def test_falha_em_massa_pelo_mesmo_motivo_grita_no_stderr(
        db, monkeypatch, capsys, origem_confere):
    """873 `logger.error` dispersos não se leem; uma linha agregada, sim.

    O contador sozinho não denunciava nada: `2 gerados, 873 falhas` passava por
    linha de rotina, e as 873 eram todas o MESMO erro (22/08/2026).
    """
    criar_materia(protocolo=201, nome='a.docx', conteudo=b'docx')
    criar_materia(protocolo=202, nome='b.docx', conteudo=b'docx')

    monkeypatch.setattr(
        'sapl.materia.views_assinatura._gerar_pdf_da_materia',
        lambda materia, request: (None, 'Erro na conversao: codigo -7'))

    call_command('materializar_pdfs_para_assinatura')

    erro = capsys.readouterr().err
    assert '2 de 2 falhas pelo MESMO motivo' in erro
    assert 'codigo -7' in erro


@pytest.mark.django_db(transaction=False)
def test_falha_isolada_nao_grita(db, monkeypatch, capsys, origem_confere):
    """Uma matéria podre é ruído esperado (§5.1) — só o lote inteiro grita."""
    criar_materia(protocolo=203, nome='a.docx', conteudo=b'docx')
    criar_materia(protocolo=204)  # PDF: passa

    def gerar(materia, request):
        if materia.numero_protocolo == 203:
            return None, 'OnlyOffice fora do ar'
        return PDF, None

    monkeypatch.setattr(
        'sapl.materia.views_assinatura._gerar_pdf_da_materia', gerar)

    call_command('materializar_pdfs_para_assinatura')

    assert 'MESMO motivo' not in capsys.readouterr().err


@pytest.mark.django_db(transaction=False)
def test_codigo_8_aponta_jwt_e_nao_url(
        db, monkeypatch, capsys, settings, origem_confere):
    """O `-8` do OnlyOffice manda consertar a variável errada se lido ao pé da letra.

    A leitura natural é "URL ruim". É token: JWT desligado AQUI é exatamente o
    que produz -8 quando o SERVIDOR do OnlyOffice exige assinatura. Provado em
    22/08/2026 com POST direto ao ConvertService, URL pública respondendo 200.
    """
    settings.ONLYOFFICE_JWT_ENABLED = False
    settings.ONLYOFFICE_URL = 'https://onlyoffice.exemplo'
    criar_materia(protocolo=205, nome='a.docx', conteudo=b'docx')
    criar_materia(protocolo=206, nome='b.docx', conteudo=b'docx')

    monkeypatch.setattr(
        'sapl.materia.views_assinatura._gerar_pdf_da_materia',
        lambda materia, request: (
            None, 'Erro na conversao do documento: codigo -8'))

    call_command('materializar_pdfs_para_assinatura')

    erro = capsys.readouterr().err
    assert 'erro de TOKEN, nao de URL' in erro
    assert 'ONLYOFFICE_JWT_ENABLED=True' in erro
    assert 'https://onlyoffice.exemplo' in erro


@pytest.mark.django_db(transaction=False)
def test_jwt_ligado_nao_repete_a_dica(
        db, monkeypatch, capsys, settings, origem_confere):
    """Com JWT já ligado o -8 é outra coisa — a dica viraria pista falsa."""
    settings.ONLYOFFICE_JWT_ENABLED = True
    criar_materia(protocolo=207, nome='a.docx', conteudo=b'docx')
    criar_materia(protocolo=208, nome='b.docx', conteudo=b'docx')

    monkeypatch.setattr(
        'sapl.materia.views_assinatura._gerar_pdf_da_materia',
        lambda materia, request: (
            None, 'Erro na conversao do documento: codigo -8'))

    call_command('materializar_pdfs_para_assinatura')

    erro = capsys.readouterr().err
    assert 'MESMO motivo' in erro
    assert 'erro de TOKEN' not in erro


# ---------------------------------------------------------------------------
# Integridade da origem: a URL entregue ao OnlyOffice serve ESTE documento?
# ---------------------------------------------------------------------------

class _RespostaFalsa:
    def __init__(self, conteudo, status_code=200):
        self.content = conteudo
        self.status_code = status_code


@pytest.mark.django_db(transaction=False)
def test_url_que_serve_outro_documento_nao_converte(db, monkeypatch, caplog):
    """O acidente que isso impede: SAPL_INTERNAL_URL apontando para outra instância.

    O `hash_origem` sairia do arquivo local e o PDF-alvo do arquivo do outro
    SAPL. Como é esse hash que dispara a retificação (§5.1), o alvo defasado
    nunca mais seria regenerado — assinaria-se um PDF que não corresponde ao
    texto da matéria. Falha em vez de converter.
    """
    materia = criar_materia(protocolo=209, nome='a.docx', conteudo=b'docx-local')
    monkeypatch.setattr(
        MOD + '.http_requests.get',
        lambda url, timeout: _RespostaFalsa(b'docx-de-outra-instancia'))
    converteu = []
    monkeypatch.setattr(
        'sapl.materia.views_assinatura._gerar_pdf_da_materia',
        lambda m, r: converteu.append(m) or (PDF, None))

    call_command('materializar_pdfs_para_assinatura')

    assert not converteu, 'não pode nem tentar converter'
    assert not DocumentoParaAssinatura.objects.filter(materia=materia).exists()
    # Uma matéria só não aciona o grito agregado (isso é ruído esperado) —
    # o motivo tem que estar no log, nomeando a variável a consertar.
    assert 'serve OUTRO documento' in caplog.text
    assert 'SAPL_INTERNAL_URL' in caplog.text


@pytest.mark.django_db(transaction=False)
def test_url_que_serve_o_documento_certo_converte(db, monkeypatch):
    materia = criar_materia(protocolo=210, nome='a.docx', conteudo=b'docx-local')
    monkeypatch.setattr(
        MOD + '.http_requests.get',
        lambda url, timeout: _RespostaFalsa(b'docx-local'))
    monkeypatch.setattr(
        'sapl.materia.views_assinatura._gerar_pdf_da_materia',
        lambda m, r: (PDF, None))

    call_command('materializar_pdfs_para_assinatura')

    assert DocumentoParaAssinatura.objects.filter(materia=materia).exists()


@pytest.mark.django_db(transaction=False)
def test_pdf_nao_passa_pela_conferencia_de_url(db, monkeypatch):
    """PDF copia bytes e não toca o OnlyOffice — não faz sentido exigir URL boa."""
    def explode(*args, **kwargs):
        raise AssertionError('PDF não deveria conferir URL')

    monkeypatch.setattr(MOD + '.http_requests.get', explode)
    materia = criar_materia(protocolo=211)

    call_command('materializar_pdfs_para_assinatura')

    assert DocumentoParaAssinatura.objects.filter(materia=materia).exists()


# ---------------------------------------------------------------------------
# --somente-novos: a passada de recuperação não pode apagar assinatura
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=False)
def test_somente_novos_gera_o_alvo_ausente(db):
    """É para isso que o modo existe: o acervo que nunca materializou.

    O dia em que a conversão DOCX voltar a funcionar, 861 matérias (Franco,
    22/08/2026) materializam de uma vez. Gerar o que falta é exatamente o que
    se quer dessa passada.
    """
    materia = criar_materia(protocolo=300)

    call_command('materializar_pdfs_para_assinatura', somente_novos=True)

    assert DocumentoParaAssinatura.objects.filter(materia=materia).exists()


@pytest.mark.django_db(transaction=False)
def test_somente_novos_adia_retificacao_e_preserva_assinatura(db):
    """A varredura não pode zerar assinatura por efeito colateral.

    Zerar em retificação (§5.1) foi decidido para o ato isolado de retificar um
    texto — quem retifica sabe o que está desfazendo. Numa passada sobre o
    acervo inteiro ninguém pediu isso, e apagar assinatura é irreversível.
    """
    materia = criar_materia(protocolo=301)
    call_command('materializar_pdfs_para_assinatura')
    alvo_antes = DocumentoParaAssinatura.objects.get(materia=materia)

    usuario = baker.make('auth.User', username='ver-b')
    materia.refresh_from_db()
    materia.pdf_assinado.save(
        'materia_%s_assinado_1.pdf' % materia.pk,
        ContentFile(b'%PDF-assinado'), save=False)
    materia.assinatura_info = [{'signed_by': 'ver-b', 'nome': 'Ver. B'}]
    materia.assinado_em = timezone.now()
    materia.assinado_por = usuario
    materia.codigo_autenticacao = 'EFGH5678EFGH5678'
    materia.save()

    materia.texto_original.save(
        'texto.pdf', ContentFile(b'%PDF-1.4 retificado'), save=True)

    call_command('materializar_pdfs_para_assinatura', somente_novos=True)

    alvo = DocumentoParaAssinatura.objects.get(materia=materia)
    assert alvo.hash_origem == alvo_antes.hash_origem  # alvo intocado
    materia.refresh_from_db()
    assert materia.pdf_assinado
    assert materia.assinatura_info == [{'signed_by': 'ver-b', 'nome': 'Ver. B'}]
    assert materia.codigo_autenticacao == 'EFGH5678EFGH5678'


@pytest.mark.django_db(transaction=False)
def test_somente_novos_decide_antes_de_gastar_a_conversao(db, monkeypatch):
    """Adiar depois de converter seria pagar o OnlyOffice para jogar fora.

    Numa passada de recuperação sobre um acervo grande isso é a diferença entre
    minutos e horas de conversão desperdiçada.
    """
    materia = criar_materia(protocolo=302, nome='a.docx', conteudo=b'docx-v1')
    monkeypatch.setattr(
        MOD + '.http_requests.get',
        lambda url, timeout: _RespostaFalsa(b'docx-v1'))
    monkeypatch.setattr(
        'sapl.materia.views_assinatura._gerar_pdf_da_materia',
        lambda m, r: (PDF, None))
    call_command('materializar_pdfs_para_assinatura')

    materia.texto_original.save('a.docx', ContentFile(b'docx-v2'), save=True)

    def nao_deveria_converter(*args, **kwargs):
        raise AssertionError('conversão gasta em matéria que seria adiada')

    monkeypatch.setattr(
        'sapl.materia.views_assinatura._gerar_pdf_da_materia',
        nao_deveria_converter)
    monkeypatch.setattr(MOD + '.http_requests.get', nao_deveria_converter)

    call_command('materializar_pdfs_para_assinatura', somente_novos=True)


@pytest.mark.django_db(transaction=False)
def test_adiada_aparece_no_resumo(db, capsys):
    """Adiada não é "em dia" — trabalho pendente calado vira surpresa depois."""
    materia = criar_materia(protocolo=303)
    call_command('materializar_pdfs_para_assinatura')
    materia.texto_original.save(
        'texto.pdf', ContentFile(b'%PDF-1.4 outro'), save=True)
    capsys.readouterr()

    call_command('materializar_pdfs_para_assinatura', somente_novos=True)

    assert 'ADIADA(S) por --somente-novos' in capsys.readouterr().out
