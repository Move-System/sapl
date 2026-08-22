import hashlib
import logging
import os
import time

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
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

    def handle(self, *args, **options):
        intervalo = options['intervalo']
        if intervalo <= 0:
            self._passada()
            return
        self.stdout.write(
            'materializar_pdfs: laco a cada %ss (Ctrl-C para sair)' % intervalo)
        while True:
            try:
                self._passada()
            except Exception as exc:  # noqa — o laco NUNCA morre: se morrer,
                # a materializacao para de vez e ninguem percebe ate a materia
                # nao aparecer para assinar.
                logger.exception('materializar_pdfs: passada falhou: %s', exc)
            time.sleep(intervalo)

    def _passada(self):
        materias = (MateriaLegislativa.objects
                    .filter(numero_protocolo__isnull=False,
                            texto_original__isnull=False)
                    .exclude(texto_original='')
                    .order_by('id'))

        gerados = retificados = pulados = falhas = 0
        for materia in materias.iterator():
            try:
                resultado = self._materializar(materia)
            except Exception as exc:  # noqa — uma matéria não trava as demais (§5.1)
                logger.exception(
                    'materializar_pdfs: falha inesperada na matéria %s: %s',
                    materia.pk, exc)
                falhas += 1
                continue
            if resultado == 'gerado':
                gerados += 1
            elif resultado == 'retificado':
                retificados += 1
            elif resultado == 'falha':
                falhas += 1
            else:
                pulados += 1

        self.stdout.write(
            'materializar_pdfs: %s gerados, %s retificados, %s em dia, '
            '%s falhas' % (gerados, retificados, pulados, falhas))

    def _materializar(self, materia):
        materia.texto_original.open('rb')
        try:
            conteudo_origem = materia.texto_original.read()
        finally:
            materia.texto_original.close()
        hash_origem = hashlib.sha256(conteudo_origem).hexdigest()

        alvo = DocumentoParaAssinatura.objects.filter(materia=materia).first()
        if alvo is not None and alvo.hash_origem == hash_origem:
            return 'em dia'  # idempotência: nada mudou desde a geração

        # Reuso da rotina da sprint: PDF copia os bytes, DOCX converte no
        # OnlyOffice — a conversão acontece UMA vez, aqui, fora do caminho
        # quente das requisições (§5.1).
        from sapl.materia.views_assinatura import _gerar_pdf_da_materia
        pdf_bytes, erro = _gerar_pdf_da_materia(
            materia, _RequisicaoDeSistema())
        if erro:
            logger.error(
                'materializar_pdfs: matéria %s não convertida (%s) — segue '
                'visível só na tela do SAPL até o próximo ciclo', materia.pk,
                erro)
            return 'falha'

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
                return 'gerado'

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
        return 'retificado'
