"""Achata o carimbo de assinatura nos PDFs de pacote (AB#1605).

O "Todos em PDF" junta a matéria e os documentos acessórios num arquivo só.
Nos PDFs assinados, o carimbo visível ("Assinado digitalmente por …") não é
conteúdo da página: é a aparência (`/AP`) de uma anotação de campo de
assinatura. O `PdfFileMerger` descarta o `AcroForm` ao juntar, e o campo fica
órfão — o Chrome desenha a aparência de qualquer anotação e mostra, mas o
Adobe trata campo de assinatura pela camada de formulários e, sem `AcroForm`,
não desenha nada. Mesmo arquivo, carimbo só num dos visualizadores.

A saída é desenhar o carimbo no conteúdo da página, usando o mesmo XObject nas
mesmas coordenadas — nada é redesenhado nem recalculado. Depois a anotação é
removida, senão o Chrome passaria a mostrar o carimbo duas vezes.

Remover não perde nada: o campo já está morto desde que o merge levou o
`AcroForm` embora. Juntar PDFs assinados destrói as assinaturas de qualquer
forma, então no pacote o carimbo tem função de leitura, não de validação —
quem precisa de assinatura verificável baixa o documento individual.

Isto vale só para o pacote. Os PDFs assinados guardados no servidor, o
download individual e o fluxo de assinatura não passam por aqui.
"""

import io
import logging

from PyPDF4.generic import NameObject
from PyPDF4.pdf import PageObject, PdfFileReader, PdfFileWriter


logger = logging.getLogger(__name__)


def _retangulo(anotacao):
    """Canto inferior esquerdo e tamanho de `/Rect`, já normalizados."""
    x0, y0, x1, y1 = [float(v) for v in anotacao['/Rect']]
    return min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)


def _aparencia_normal(anotacao):
    """Stream `/AP /N`, ou None quando a anotação não tem aparência."""
    ap = anotacao.get('/AP')
    if not ap:
        return None
    normal = ap.get('/N')
    return normal.getObject() if normal else None


def _como_pagina(aparencia, largura, altura):
    """Embrulha o form XObject da aparência numa página.

    Permite usar `mergeTranslatedPage`, que já resolve conflito de nomes de
    recurso e concatenação de fluxo de conteúdo — bem menos frágil do que
    montar o content stream na mão.
    """
    pagina = PageObject.createBlankPage(width=largura, height=altura)
    pagina[NameObject('/Contents')] = aparencia
    recursos = aparencia.get('/Resources')
    if recursos is not None:
        pagina[NameObject('/Resources')] = recursos
    return pagina


def _achatar_pagina(pagina):
    """Desenha os carimbos no conteúdo e devolve quantos foram achatados."""
    anotacoes = pagina.get('/Annots')
    if not anotacoes:
        return 0

    sobreviventes = []
    achatados = 0

    for referencia in anotacoes:
        anotacao = referencia.getObject()
        aparencia = _aparencia_normal(anotacao)

        # Só campos de assinatura: link e demais anotações seguem como estão.
        if anotacao.get('/Subtype') != '/Widget' or aparencia is None:
            sobreviventes.append(referencia)
            continue

        try:
            x, y, largura, altura = _retangulo(anotacao)
            pagina.mergeTranslatedPage(
                _como_pagina(aparencia, largura, altura), x, y)
            achatados += 1
        except Exception as e:
            # Carimbo que não achata é melhor como anotação do que perdido:
            # pelo menos continua aparecendo onde já aparecia hoje.
            logger.warning(
                'Não foi possível achatar um carimbo de assinatura: %s', e)
            sobreviventes.append(referencia)

    if achatados:
        pagina[NameObject('/Annots')] = type(anotacoes)(sobreviventes)

    return achatados


def achatar_carimbos(pdf_bytes):
    """Devolve o PDF com os carimbos de assinatura virados conteúdo de página.

    Nunca levanta exceção: o pacote é conveniência, e entregar o PDF do jeito
    antigo é melhor do que não entregar. Falhando, devolve a entrada intacta.
    """
    try:
        leitor = PdfFileReader(io.BytesIO(pdf_bytes), strict=False)
        escritor = PdfFileWriter()

        total = 0
        for numero in range(leitor.getNumPages()):
            pagina = leitor.getPage(numero)
            total += _achatar_pagina(pagina)
            escritor.addPage(pagina)

        if not total:
            return pdf_bytes

        saida = io.BytesIO()
        escritor.write(saida)
        logger.info('%d carimbo(s) de assinatura achatado(s) no pacote.', total)
        return saida.getvalue()
    except Exception as e:
        logger.warning(
            'Achatamento de carimbos não aplicado ao pacote: %s', e)
        return pdf_bytes
