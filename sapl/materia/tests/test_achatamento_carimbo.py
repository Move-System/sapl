"""Achatamento do carimbo de assinatura nos pacotes (AB#1605).

A validação ponta a ponta foi feita contra o arquivo real que o cliente
reportou (`mat_982_2026_completo.pdf`): depois do achatamento, o conteúdo da
página 4 passou a conter `1 0 0 1 57 658 cm` seguido de
`/Bloco98e5… Do` — a mesma translação do `/Rect` da anotação — e os widgets
caíram de 1 para 0.

O que estes testes cobrem é o comportamento que não dá para verificar olhando
um arquivo específico: que a função é inócua quando não há o que achatar, e
que ela nunca derruba a geração do pacote. Essa segunda parte importa mais do
que parece — o pacote é conveniência, e entregar o PDF do jeito antigo é
melhor do que devolver erro ao usuário.
"""
import io

import pytest
from PyPDF4.pdf import PdfFileReader, PdfFileWriter

from sapl.materia.achatamento_carimbo import (_retangulo, achatar_carimbos)


def _pdf_simples(paginas=1):
    escritor = PdfFileWriter()
    for _ in range(paginas):
        escritor.addBlankPage(width=595, height=842)
    buf = io.BytesIO()
    escritor.write(buf)
    return buf.getvalue()


def test_pdf_sem_anotacao_volta_identico():
    """Sem carimbo não há o que fazer — e mexer seria risco à toa."""
    original = _pdf_simples()

    assert achatar_carimbos(original) is original


def test_pdf_de_varias_paginas_sem_carimbo_tambem_volta_identico():
    original = _pdf_simples(paginas=3)

    assert achatar_carimbos(original) is original


def test_bytes_invalidos_nao_derrubam_a_geracao_do_pacote():
    """O pacote é conveniência: na dúvida, entrega o que tinha."""
    lixo = b'isto nao e um pdf'

    assert achatar_carimbos(lixo) == lixo


def test_pdf_truncado_nao_levanta_excecao():
    truncado = _pdf_simples()[:120]

    assert achatar_carimbos(truncado) == truncado


@pytest.mark.parametrize('rect,esperado', [
    # O canto de origem é o menor x e o menor y, venham na ordem que vierem.
    ([57, 658, 277, 715], (57.0, 658.0, 220.0, 57.0)),
    ([277, 715, 57, 658], (57.0, 658.0, 220.0, 57.0)),
])
def test_retangulo_normaliza_a_ordem_das_coordenadas(rect, esperado):
    """`/Rect` pode vir com os cantos invertidos; a translação não pode."""
    assert _retangulo({'/Rect': rect}) == esperado


def test_numero_de_paginas_e_preservado():
    """Achatar não pode perder nem duplicar página do pacote."""
    original = _pdf_simples(paginas=4)

    resultado = achatar_carimbos(original)

    assert PdfFileReader(io.BytesIO(resultado)).getNumPages() == 4
