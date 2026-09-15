"""
O comando que esvazia o carimbo da AMZ nos PDFs ja assinados.

Os dois testes que valem por todos:

- `test_documento_sem_carimbo_nao_e_tocado` e a propriedade que torna seguro rodar
  isto sobre o acervo inteiro. Documento correto nao pode ganhar uma revisao a toa.
- `test_a_contagem_de_assinaturas_do_binario_nao_muda` e o que garante que o
  documento limpo continua aceitando assinatura nova: a guarda de encadeamento do
  hub (ADR-0013) decide pela contagem de campos `/Sig` preenchidos no binario, e se
  a limpeza mexesse nela o proximo signatario levaria 409.
"""

import io

import pytest

from sapl.materia.management.commands.limpar_carimbo_amz import (
    _aparencia_com_imagem,
    esvaziar_carimbos,
)

pyhanko = pytest.importorskip('pyhanko')


def _pdf_de_uma_pagina():
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont('Helvetica', 12)
    c.drawString(80, 700, 'Art. 14. A implementacao do Programa podera ocorrer.')
    c.showPage()
    c.save()
    return buf.getvalue()


def _certificado():
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'FULANO DE TAL')])
    agora = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome).issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - datetime.timedelta(days=1))
        .not_valid_after(agora + datetime.timedelta(days=365))
        .sign(chave, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        b'teste', chave, cert, None, serialization.BestAvailableEncryption(b'senha')
    )


def _assinar(pdf_bytes, visivel=True):
    import tempfile

    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers
    from pyhanko.sign.fields import SigFieldSpec

    # `load_pkcs12` quer um caminho, nao um buffer.
    with tempfile.NamedTemporaryFile(suffix='.pfx') as pfx:
        pfx.write(_certificado())
        pfx.flush()
        signer = signers.SimpleSigner.load_pkcs12(pfx.name, passphrase=b'senha')

    escritor = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes), strict=False)
    spec = SigFieldSpec(
        sig_field_name='Signature1',
        **({'on_page': 0, 'box': (56, 606, 269, 663)} if visivel else {}),
    )
    saida = signers.PdfSigner(
        signature_meta=signers.PdfSignatureMetadata(field_name='Signature1'),
        signer=signer,
        new_field_spec=spec,
    ).sign_pdf(escritor)
    saida.seek(0)
    return saida.read()


def _com_carimbo_de_imagem(pdf_assinado):
    """Reproduz o carimbo antigo: uma imagem desenhada dentro da aparencia."""
    from pyhanko.pdf_utils import generic
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign.fields import enumerate_sig_fields

    escritor = IncrementalPdfFileWriter(io.BytesIO(pdf_assinado), strict=False)
    _nome, _sig, ref = next(iter(enumerate_sig_fields(escritor, filled_status=True)))

    imagem = generic.StreamObject(
        dict_data={
            generic.pdf_name('/Type'): generic.pdf_name('/XObject'),
            generic.pdf_name('/Subtype'): generic.pdf_name('/Image'),
            generic.pdf_name('/Width'): generic.NumberObject(1),
            generic.pdf_name('/Height'): generic.NumberObject(1),
            generic.pdf_name('/ColorSpace'): generic.pdf_name('/DeviceGray'),
            generic.pdf_name('/BitsPerComponent'): generic.NumberObject(8),
        },
        stream_data=b'\x00',
    )
    aparencia = generic.StreamObject(
        dict_data={
            generic.pdf_name('/Type'): generic.pdf_name('/XObject'),
            generic.pdf_name('/Subtype'): generic.pdf_name('/Form'),
            generic.pdf_name('/BBox'): generic.ArrayObject(
                [generic.NumberObject(n) for n in (0, 0, 212, 56)]
            ),
            generic.pdf_name('/Resources'): generic.DictionaryObject({
                generic.pdf_name('/XObject'): generic.DictionaryObject({
                    generic.pdf_name('/Im0'): escritor.add_object(imagem),
                }),
            }),
        },
        stream_data=b'q 212 0 0 56 0 0 cm /Im0 Do Q',
    )
    widget = ref.get_object()
    widget[generic.pdf_name('/AP')] = generic.DictionaryObject({
        generic.pdf_name('/N'): escritor.add_object(aparencia),
    })
    escritor.mark_update(ref)
    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()


def _contar_assinaturas(pdf_bytes):
    from sapl.materia.views_assinatura import contar_assinaturas_no_pdf

    return contar_assinaturas_no_pdf(pdf_bytes)


@pytest.fixture(scope='module')
def com_carimbo():
    return _com_carimbo_de_imagem(_assinar(_pdf_de_uma_pagina()))


def test_documento_sem_carimbo_nao_e_tocado():
    """
    A propriedade que torna seguro varrer o acervo: sem imagem na aparencia, o
    comando devolve None e o arquivo nao e reescrito.
    """
    assinado = _assinar(_pdf_de_uma_pagina())

    novo, alterados = esvaziar_carimbos(assinado)

    assert alterados == []
    assert novo is None, 'documento correto nao pode ganhar uma revisao a toa'


def test_o_carimbo_com_imagem_e_encontrado_e_esvaziado(com_carimbo):
    novo, alterados = esvaziar_carimbos(com_carimbo)

    assert alterados == ['Signature1']
    assert novo is not None

    # Rodar de novo nao acha mais nada: a aparencia esvaziada nao e alvo.
    _n2, de_novo = esvaziar_carimbos(novo)
    assert de_novo == []


def test_a_contagem_de_assinaturas_do_binario_nao_muda(com_carimbo):
    """
    A guarda de encadeamento do hub (ADR-0013) conta campos `/Sig` preenchidos no
    binario. Se a limpeza mexesse nessa conta, o proximo signatario levaria 409.
    """
    novo, _alterados = esvaziar_carimbos(com_carimbo)

    assert _contar_assinaturas(novo) == _contar_assinaturas(com_carimbo) == 1


def test_a_assinatura_continua_fechando(com_carimbo):
    """
    O ponto inteiro da operacao: tirar o desenho sem romper a assinatura. `intact` e
    `valid` sao o que diz se o documento ainda prova quem assinou o que.
    """
    import asyncio

    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.fields import enumerate_sig_fields
    from pyhanko.sign.validation import (
        EmbeddedPdfSignature,
        async_validate_pdf_signature,
    )
    from pyhanko_certvalidator.context import ValidationContext

    novo, _alterados = esvaziar_carimbos(com_carimbo)

    leitor = PdfFileReader(io.BytesIO(novo), strict=False)
    nome, _sig, ref = next(iter(enumerate_sig_fields(leitor, filled_status=True)))
    emb = EmbeddedPdfSignature(leitor, ref, nome)
    status = asyncio.run(async_validate_pdf_signature(
        emb, signer_validation_context=ValidationContext(allow_fetching=False)
    ))

    assert status.intact, 'o hash da assinatura deixou de fechar'
    assert status.valid, 'a assinatura deixou de validar'


def test_detector_ignora_aparencia_so_de_texto(com_carimbo):
    """O bloco da casa e texto puro — nao pode ser confundido com o carimbo."""
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.fields import enumerate_sig_fields

    assinado = _assinar(_pdf_de_uma_pagina())
    leitor = PdfFileReader(io.BytesIO(assinado), strict=False)
    _nome, _sig, ref = next(iter(enumerate_sig_fields(leitor, filled_status=True)))

    assert _aparencia_com_imagem(ref.get_object()) is None
