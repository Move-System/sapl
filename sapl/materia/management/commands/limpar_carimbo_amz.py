"""
Management command: limpar_carimbo_amz

Esvazia o desenho do carimbo com a marca da AMZ nos PDFs ja assinados.

Por que aqui, e nao no deploy
=============================

Os PDFs vivem no storage de midia do SAPL (`materia.pdf_assinado`), nao no
repositorio do microservico de assinatura — e reescrever ato oficial e operacao
deliberada, nao efeito colateral de subir codigo. Um passo de deploy rodaria em
todo ambiente, sem revisao, sem backup e sem registro de quais documentos mudaram.
Este comando roda uma vez, quando alguem decide, e deixa rastro.

O que a alteracao custa
=======================

O carimbo esta dentro da faixa de bytes que as assinaturas cobrem, entao tira-lo
acrescenta uma revisao ao PDF. Medido no autografo 77/2026 da Camara de Franco da
Rocha, e conferido no validador do ITI:

    antes    intact=True valid=True docmdp_ok=True   mod=FORM_FILLING/NONE
    depois   intact=True valid=True docmdp_ok=False  mod=OTHER

Nenhuma assinatura e rompida: o hash de cada uma sobre a sua faixa continua
fechando e os certificados continuam validando. O que muda e a classificacao da
revisao nova pela politica padrao da pyHanko.

Nada de conteudo se perde: o bloco do signatario — nome, cargo, data e hash — ja
esta impresso na pagina de autenticacao. O carimbo na pagina do corpo era duplicata
com o logotipo de fornecedor por cima do texto.

A contagem de assinaturas do binario nao muda (o campo e o `/V` ficam intactos),
entao a guarda de encadeamento do hub (ADR-0013, `contar_assinaturas_no_pdf`)
continua valendo: documento limpo aceita nova assinatura normalmente.

Uso
===

    python manage.py limpar_carimbo_amz                  # so relata (padrao)
    python manage.py limpar_carimbo_amz --aplicar
    python manage.py limpar_carimbo_amz --aplicar --pk 1177 --tipo materia

Opcoes:
    --aplicar     Grava. Sem isto, apenas lista o que seria alterado.
    --pk          Restringe a um documento (use com --tipo).
    --tipo        materia | docacessorio | todos (padrao: todos).
    --sem-backup  Nao guarda o original em `<arquivo>.antes-da-limpeza`.
"""
import io
import logging

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)

SUFIXO_BACKUP = '.antes-da-limpeza'


def _stream_tem_imagem(stream, vistos):
    recursos = stream.get('/Resources') or {}
    xobjects = recursos.get('/XObject') or {}
    for nome in xobjects.keys():
        filho = xobjects[nome]
        if id(filho) in vistos:
            continue
        vistos.add(id(filho))
        if filho.get('/Subtype') == '/Image':
            return True
        if _stream_tem_imagem(filho, vistos):
            return True
    return False


def _aparencia_com_imagem(widget):
    """
    A referencia do `/AP /N` quando ele desenha imagem.

    E o detector: so o carimbo generico antigo desenhava imagem dentro da aparencia
    da assinatura. O bloco da casa e texto puro (Helvetica 7, moldura de 1pt), e
    nenhuma assinatura nova produz imagem — a marca saiu do microservico.
    """
    from pyhanko.pdf_utils import generic

    aparencia = widget.get('/AP')
    if aparencia is None or '/N' not in aparencia:
        return None
    try:
        ref = aparencia.raw_get('/N')
    except KeyError:
        return None
    if not isinstance(ref, generic.IndirectObject):
        return None
    if not _stream_tem_imagem(ref.get_object(), set()):
        return None
    return ref


def esvaziar_carimbos(pdf_bytes):
    """
    Devolve (bytes novos, campos alterados). Sem alvo, devolve (None, []).

    A alteracao mais estreita que apaga o desenho: o stream de aparencia e trocado
    por um form XObject vazio NO MESMO numero de objeto e com a mesma `/BBox`. O
    dicionario do campo, o widget, o `/Rect`, o `/Annots` da pagina e o objeto `/V`
    ficam byte a byte como estavam.
    """
    from pyhanko.pdf_utils import generic
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign.fields import enumerate_sig_fields

    escritor = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes), strict=False)
    alterados = []

    for nome, _sig, ref in enumerate_sig_fields(escritor, filled_status=True):
        ap_ref = _aparencia_com_imagem(ref.get_object())
        if ap_ref is None:
            continue

        antigo = ap_ref.get_object()
        vazio = generic.StreamObject(
            dict_data={
                generic.pdf_name('/Type'): generic.pdf_name('/XObject'),
                generic.pdf_name('/Subtype'): generic.pdf_name('/Form'),
                generic.pdf_name('/BBox'): antigo.raw_get('/BBox'),
            },
            stream_data=b'',
        )
        escritor.objects[(ap_ref.generation, ap_ref.idnum)] = vazio
        alterados.append(nome)

    if not alterados:
        return None, []

    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue(), alterados


class Command(BaseCommand):
    help = 'Esvazia o desenho do carimbo da marca AMZ nos PDFs ja assinados'

    def add_arguments(self, parser):
        parser.add_argument(
            '--aplicar', action='store_true', default=False,
            help='Grava a alteracao. Sem isto, apenas relata.',
        )
        parser.add_argument(
            '--pk', type=int, default=None,
            help='Restringe a um documento (use com --tipo).',
        )
        parser.add_argument(
            '--tipo', choices=['materia', 'docacessorio', 'todos'], default='todos',
            help='Que acervo varrer (padrao: todos).',
        )
        parser.add_argument(
            '--sem-backup', action='store_true', default=False,
            help=f'Nao guarda o original em <arquivo>{SUFIXO_BACKUP}.',
        )

    def handle(self, *args, **options):
        from sapl.materia.models import DocumentoAcessorio, MateriaLegislativa

        aplicar = options['aplicar']
        pk = options['pk']
        tipo = options['tipo']
        guardar_backup = not options['sem_backup']

        if pk is not None and tipo == 'todos':
            raise CommandError('--pk exige --tipo materia ou --tipo docacessorio.')

        acervos = []
        if tipo in ('materia', 'todos'):
            acervos.append(('materia', MateriaLegislativa))
        if tipo in ('docacessorio', 'todos'):
            acervos.append(('docacessorio', DocumentoAcessorio))

        if not aplicar:
            self.stdout.write(self.style.WARNING(
                'Modo relatorio: nada sera gravado. Use --aplicar para gravar.'
            ))

        total_com_carimbo = 0
        total_limpos = 0
        total_falhas = 0

        for rotulo, modelo in acervos:
            consulta = modelo.objects.exclude(pdf_assinado='').exclude(
                pdf_assinado__isnull=True
            )
            if pk is not None:
                consulta = consulta.filter(pk=pk)

            for obj in consulta.iterator():
                try:
                    tem, limpou = self._processar(
                        rotulo, obj, aplicar, guardar_backup
                    )
                except Exception as exc:
                    total_falhas += 1
                    logger.exception(
                        'limpar_carimbo_amz: %s %s falhou', rotulo, obj.pk
                    )
                    self.stderr.write(self.style.ERROR(
                        f'  {rotulo} {obj.pk}: falhou — {exc}'
                    ))
                    continue

                total_com_carimbo += 1 if tem else 0
                total_limpos += 1 if limpou else 0

        self.stdout.write('')
        self.stdout.write(f'Documentos com o carimbo da AMZ: {total_com_carimbo}')
        self.stdout.write(f'Documentos limpos: {total_limpos}')
        if total_falhas:
            self.stdout.write(self.style.ERROR(f'Falhas: {total_falhas}'))

    def _processar(self, rotulo, obj, aplicar, guardar_backup):
        """Devolve (tinha carimbo, foi limpo)."""
        arquivo = obj.pdf_assinado
        try:
            with arquivo.open('rb') as f:
                pdf_bytes = f.read()
        except FileNotFoundError:
            # Registro aponta para arquivo que nao existe mais. E informacao util
            # sobre o acervo, nao motivo para abortar a varredura.
            self.stderr.write(self.style.WARNING(
                f'  {rotulo} {obj.pk}: arquivo ausente ({arquivo.name})'
            ))
            return False, False

        novo, alterados = esvaziar_carimbos(pdf_bytes)
        if not alterados:
            return False, False

        self.stdout.write(
            f'  {rotulo} {obj.pk}: carimbo em {", ".join(alterados)} '
            f'({arquivo.name})'
        )

        if not aplicar:
            return True, False

        from django.core.files.base import ContentFile

        if guardar_backup:
            # O original e a unica versao sem a revisao extra. Guardar antes de
            # sobrescrever e o que torna a operacao reversivel. O `exists` importa:
            # rodar o comando duas vezes nao pode substituir o original guardado
            # pela versao ja limpa.
            destino_backup = f'{arquivo.name}{SUFIXO_BACKUP}'
            if not arquivo.storage.exists(destino_backup):
                arquivo.storage.save(destino_backup, ContentFile(pdf_bytes))
                self.stdout.write(f'    original guardado em {destino_backup}')

        # OverwriteStorage (sapl.utils) apaga o arquivo de mesmo nome e devolve o
        # nome intacto, entao gravar por cima mantem o caminho — nenhum registro do
        # banco precisa ser tocado, e o `codigo_autenticacao` continua valendo.
        arquivo.storage.save(arquivo.name, ContentFile(novo))

        logger.info(
            'limpar_carimbo_amz: %s %s limpo (campos: %s)',
            rotulo, obj.pk, ', '.join(alterados),
        )
        self.stdout.write(self.style.SUCCESS('    limpo'))
        return True, True
