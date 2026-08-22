import hashlib
import logging
import os
import time

import requests as http_requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sapl.integracao_hub.models import DocumentoParaAssinatura
from sapl.materia.models import MateriaLegislativa

logger = logging.getLogger(__name__)


class _RequisicaoDeSistema:
    """Substituto mínimo de request para reusar `_gerar_pdf_da_materia` fora do HTTP.

    A rotina da sprint só usa o request em dois pontos do caminho DOCX:
    `build_onlyoffice_url` (que prefere `SAPL_INTERNAL_URL` e só cai no request
    sem ela — aqui caímos em `SITE_URL`) e `generate_file_key` (pk do usuário,
    que num cron não existe — 0 identifica o sistema). O caminho PDF não toca
    o request. Reuso em vez de cópia: a conversão OnlyOffice tem UM dono (§5.1).
    """

    class _UsuarioDeSistema:
        pk = 0

    user = _UsuarioDeSistema()

    def build_absolute_uri(self, caminho):
        base = getattr(settings, 'SITE_URL', '') or ''
        return base.rstrip('/') + caminho


def _origem_servida_confere(materia, hash_origem):
    """A URL entregue ao OnlyOffice serve MESMO o documento que acabamos de ler?

    `SAPL_INTERNAL_URL` e configuracao de operador e nao ha de onde deduzi-la: so
    quem opera sabe qual URL o servidor do OnlyOffice alcanca. O risco nao e ela
    ser fixa — e ela apontar para OUTRA instancia sem ninguem perceber. Ai o
    `hash_origem` sai do arquivo local e o PDF-alvo sai do arquivo do outro SAPL,
    e como e justamente esse hash que dispara a retificacao (§5.1), o alvo
    defasado nunca mais e regenerado: assina-se um PDF que nao corresponde ao
    texto da materia.

    Baixar a propria URL e comparar o sha256 fecha isso sem exigir adivinhacao:
    seja qual for o valor configurado, ele so passa se servir este documento.
    Retorna (ok, motivo).
    """
    from django.urls import reverse
    from sapl.utils import build_onlyoffice_url
    url = build_onlyoffice_url(
        _RequisicaoDeSistema(),
        reverse('sapl.materia:materia_onlyoffice_download',
                kwargs={'pk': materia.pk}))
    try:
        resposta = http_requests.get(url, timeout=60)
    except Exception as exc:  # noqa — rede e diagnostico, nao excecao de dominio
        return False, ('a URL entregue ao OnlyOffice nao respondeu (%s) — '
                       'confira SAPL_INTERNAL_URL' % type(exc).__name__)
    if resposta.status_code != 200:
        return False, ('a URL entregue ao OnlyOffice respondeu %s — o servidor '
                       'dele tambem nao vai conseguir baixar'
                       % resposta.status_code)
    if hashlib.sha256(resposta.content).hexdigest() != hash_origem:
        return False, ('a URL entregue ao OnlyOffice serve OUTRO documento — '
                       'SAPL_INTERNAL_URL aponta para outra instancia do SAPL. '
                       'Converter assim gera um PDF-alvo que nao corresponde ao '
                       'texto desta materia')
    return True, None


def _base_url_de_sistema():
    """URL que o OnlyOffice usa para BAIXAR o documento de origem, no caminho cron.

    `build_onlyoffice_url` prefere `SAPL_INTERNAL_URL` e so cai no request sem
    ela — e no cron o "request" e o `_RequisicaoDeSistema`, que monta a partir de
    `SITE_URL`. Sem nenhuma das duas, a URL sai SEM HOST, o OnlyOffice nao
    consegue baixar e TODA materia DOCX falha na conversao. Descoberto em
    22/08/2026 num acervo real: 0 de 861 DOCX materializaram, cada uma virando um
    logger.error que ninguem le, enquanto os 7 PDF passavam (PDF nao converte, so
    copia bytes) e davam a impressao de que a rotina estava viva.
    """
    return (getattr(settings, 'SAPL_INTERNAL_URL', '')
            or getattr(settings, 'SITE_URL', '') or '')


class Command(BaseCommand):
    help = ('Materializa o PDF-alvo da assinatura (refinamento §5/§5.1): varre '
            'matérias protocoladas com texto_original, gera o PDF uma única '
            'vez e, em retificação do texto, regenera o alvo e ZERA o processo '
            'de assinatura (decisão do arquiteto, 19/08/2026). Idempotente — '
            'feito para cron.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--intervalo',
            type=int,
            default=0,
            metavar='SEGUNDOS',
            help=('Segundos entre passadas. 0 (padrao) roda uma vez e sai — '
                  'o modo para invocacao manual. Maior que zero fica em laco, '
                  'que e como o container sobe a rotina (start.sh): sem isso a '
                  'materializacao vira passo manual e materia protocolada NUNCA '
                  'vira pendencia no app, em silencio.'))
        parser.add_argument(
            '--somente-novos',
            action='store_true',
            help=('Gera apenas o PDF-alvo AUSENTE; nunca entra na retificacao. '
                  'E o modo da passada de recuperacao: quando um acervo inteiro '
                  'materializa de uma vez (o dia em que a conversao DOCX volta '
                  'a funcionar), retificar em lote apagaria assinatura ja feita '
                  '— e a decisao de zerar assinatura (§5.1) foi tomada para o '
                  'ato isolado de retificar um texto, nao para uma varredura. '
                  'A retificacao adiada aparece no resumo e roda no ciclo '
                  'normal, uma a uma.'))

    def handle(self, *args, **options):
        # Erro de CONFIGURACAO morre aqui, alto e cedo — nao vira 861 falhas por
        # materia num log que ninguem le. Vale para a passada unica e para o laco:
        # o container que sobe sem isso nunca materializa nada.
        if not _base_url_de_sistema():
            raise CommandError(
                'materializar_pdfs: nem SAPL_INTERNAL_URL nem SITE_URL estao '
                'configuradas. A conversao DOCX->PDF passa pelo OnlyOffice, que '
                'BAIXA o documento de origem por URL absoluta — sem host ele '
                'responde erro e NENHUMA materia DOCX vira pendencia de '
                'assinatura. Configure SAPL_INTERNAL_URL com uma URL deste SAPL '
                'que o servidor do OnlyOffice alcance.')

        intervalo = options['intervalo']
        somente_novos = options['somente_novos']
        if intervalo <= 0:
            self._passada(somente_novos)
            return
        self.stdout.write(
            'materializar_pdfs: laco a cada %ss (Ctrl-C para sair)' % intervalo)
        while True:
            try:
                self._passada(somente_novos)
            except Exception as exc:  # noqa — o laco NUNCA morre: se morrer,
                # a materializacao para de vez e ninguem percebe ate a materia
                # nao aparecer para assinar.
                logger.exception('materializar_pdfs: passada falhou: %s', exc)
            time.sleep(intervalo)

    def _passada(self, somente_novos=False):
        materias = (MateriaLegislativa.objects
                    .filter(numero_protocolo__isnull=False,
                            texto_original__isnull=False)
                    .exclude(texto_original='')
                    .order_by('id'))

        gerados = retificados = pulados = falhas = adiados = 0
        motivos = {}
        for materia in materias.iterator():
            try:
                resultado, motivo = self._materializar(materia, somente_novos)
            except Exception as exc:  # noqa — uma matéria não trava as demais (§5.1)
                logger.exception(
                    'materializar_pdfs: falha inesperada na matéria %s: %s',
                    materia.pk, exc)
                falhas += 1
                motivos[type(exc).__name__] = motivos.get(
                    type(exc).__name__, 0) + 1
                continue
            if resultado == 'gerado':
                gerados += 1
            elif resultado == 'retificado':
                retificados += 1
            elif resultado == 'falha':
                falhas += 1
                motivos[motivo] = motivos.get(motivo, 0) + 1
            elif resultado == 'adiado':
                adiados += 1
            else:
                pulados += 1

        self.stdout.write(
            'materializar_pdfs: %s gerados, %s retificados, %s em dia, '
            '%s falhas' % (gerados, retificados, pulados, falhas))

        # Adiada nao e "em dia": e trabalho pendente que este modo se recusou a
        # fazer. Some do resumo comum e vira surpresa quando alguem estranhar
        # que o alvo nao acompanhou o texto.
        if adiados:
            self.stdout.write(
                'materializar_pdfs: %s retificacao(oes) ADIADA(S) por '
                '--somente-novos — o texto mudou e o PDF-alvo segue defasado. '
                'Rodar sem a flag para regenerar (zera a assinatura da materia, '
                '§5.1).' % adiados)

        # Falha em MASSA por um motivo so nao e materia podre avulsa: e o
        # ambiente parado. O contador sozinho nao dizia isso — `2 gerados, 873
        # falhas` passava por linha de rotina, e as 873 eram todas o MESMO erro.
        # Agrupar por motivo transforma 873 logger.error dispersos em uma linha
        # que se le e se age. Em 22/08/2026 essas 873 eram um unico `codigo -8`.
        self._relatar_motivos(motivos, falhas)

    def _relatar_motivos(self, motivos, falhas):
        if not motivos:
            return
        motivo, quantas = max(motivos.items(), key=lambda par: par[1])
        # Uma falha isolada e ruido esperado (§5.1); o que precisa gritar e o
        # motivo unico que derruba um lote inteiro.
        if quantas < 2:
            return
        aviso = ('materializar_pdfs: %s de %s falhas pelo MESMO motivo: %s'
                 % (quantas, falhas, motivo))
        # O -8 do OnlyOffice e "token invalido", e a leitura natural (URL ruim)
        # manda consertar a variavel errada: JWT desligado AQUI e exatamente o
        # que produz -8 quando o SERVIDOR do OnlyOffice exige token.
        if 'codigo -8' in motivo or 'código -8' in motivo:
            if not getattr(settings, 'ONLYOFFICE_JWT_ENABLED', False):
                aviso += (
                    ' | -8 e erro de TOKEN, nao de URL: o servidor em %s exige '
                    'JWT e ONLYOFFICE_JWT_ENABLED esta False. Configure '
                    'ONLYOFFICE_JWT_ENABLED=True e ONLYOFFICE_JWT_SECRET com o '
                    'mesmo segredo do servidor do OnlyOffice.'
                    % getattr(settings, 'ONLYOFFICE_URL', '<ausente>'))
        self.stderr.write(aviso)
        logger.error(aviso)

    def _materializar(self, materia, somente_novos=False):
        materia.texto_original.open('rb')
        try:
            conteudo_origem = materia.texto_original.read()
        finally:
            materia.texto_original.close()
        hash_origem = hashlib.sha256(conteudo_origem).hexdigest()

        alvo = DocumentoParaAssinatura.objects.filter(materia=materia).first()
        if alvo is not None and alvo.hash_origem == hash_origem:
            return 'em dia', None  # idempotência: nada mudou desde a geração

        # A passada de recuperação não retifica — e decide isso ANTES de gastar
        # a conversão, não depois. Alvo defasado é um problema; apagar
        # assinatura já feita, em lote e sem ninguém pedir, é um problema pior e
        # irreversível. A decisão de zerar (§5.1) foi tomada para o ato isolado
        # de retificar um texto, não para uma varredura de acervo inteiro.
        if alvo is not None and somente_novos:
            logger.info(
                'materializar_pdfs: matéria %s precisa de retificação — ADIADA '
                'por --somente-novos (sem conversão)', materia.pk)
            return 'adiado', None

        # Reuso da rotina da sprint: PDF copia os bytes, DOCX converte no
        # OnlyOffice — a conversão acontece UMA vez, aqui, fora do caminho
        # quente das requisições (§5.1).
        # Só o caminho DOCX passa pelo OnlyOffice; PDF copia bytes e não depende
        # de URL nenhuma. Conferir a origem servida antes de gastar a conversão.
        if not materia.texto_original.name.lower().endswith('.pdf'):
            ok, motivo = _origem_servida_confere(materia, hash_origem)
            if not ok:
                logger.error(
                    'materializar_pdfs: matéria %s — %s', materia.pk, motivo)
                return 'falha', motivo

        from sapl.materia.views_assinatura import _gerar_pdf_da_materia
        pdf_bytes, erro = _gerar_pdf_da_materia(
            materia, _RequisicaoDeSistema())
        if erro:
            logger.error(
                'materializar_pdfs: matéria %s não convertida (%s) — segue '
                'visível só na tela do SAPL até o próximo ciclo', materia.pk,
                erro)
            return 'falha', erro

        nome = 'materia_%s_alvo.pdf' % materia.pk
        hash_alvo = hashlib.sha256(pdf_bytes).hexdigest()

        with transaction.atomic():
            if alvo is None:
                alvo = DocumentoParaAssinatura(
                    materia=materia, hash_sha256=hash_alvo,
                    hash_origem=hash_origem)
                alvo.arquivo.save(nome, ContentFile(pdf_bytes), save=True)
                logger.info(
                    'materializar_pdfs: PDF-alvo da matéria %s gerado (%s)',
                    materia.pk, hash_alvo)
                return 'gerado', None

            # RETIFICAÇÃO (§5.1, decisão do arquiteto 19/08): texto_original
            # mudou depois da conversão → o alvo está defasado. Regenera E zera
            # o processo de assinatura — mesmo efeito da rotina
            # `materia_remover_assinatura` que o SAPL já tem. Assinatura sobre
            # texto retificado é impossível por construção.
            alvo.arquivo.delete(save=False)
            alvo.hash_sha256 = hash_alvo
            alvo.hash_origem = hash_origem
            alvo.arquivo.save(nome, ContentFile(pdf_bytes), save=True)

            if materia.pdf_assinado:
                materia.pdf_assinado.delete(save=False)
            materia.pdf_assinado = None
            materia.assinatura_info = None
            materia.assinado_em = None
            materia.assinado_por = None
            materia.codigo_autenticacao = None
            materia.save()

        logger.info(
            'materializar_pdfs: matéria %s RETIFICADA — alvo regenerado (%s) '
            'e assinaturas zeradas', materia.pk, hash_alvo)
        return 'retificado', None
