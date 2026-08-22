"""
Views para assinatura digital de PDFs de Matérias Legislativas.
Suporta certificados A1 (arquivo .pfx/.p12) e A3 (token USB/smartcard).
"""
import hashlib
import io
import json
import logging
import os
import tempfile
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from sapl.base.models import AppConfig, OperadorAutor
from sapl.materia.models import DocumentoAcessorio, MateriaLegislativa
from sapl.utils import build_onlyoffice_url

logger = logging.getLogger(__name__)


def _pode_remover_assinatura(user):
    """
    Verifica se o usuário tem permissão para remover assinaturas digitais.
    Regras (qualquer uma é suficiente):
      1. É superusuário, OU
      2. A funcionalidade está habilitada em AppConfig E o usuário possui a
         permissão granular 'materia.can_remove_assinatura'.
    """
    if user.is_superuser:
        return True
    from sapl.base.models import AppConfig
    permite = AppConfig.attr('permite_remover_assinatura')
    if permite and user.has_perm('materia.can_remove_assinatura'):
        return True
    return False


def _normalizar_assinatura_info(info):
    """Converte assinatura_info legado (dict) para lista de dicts."""
    if info is None:
        return []
    if isinstance(info, dict):
        return [info]
    return info


# =============================================================================
# Roteamento de backend de assinatura: API externa OU pyhanko local
# =============================================================================

def _usar_api_externa():
    """Retorna True se a API externa de assinatura está configurada."""
    from sapl.materia.assinatura_api_client import _api_configurada
    return _api_configurada()


def _extrair_posicao_custom(post_data):
    """
    Extrai coordenadas de posicionamento customizado do POST.
    Retorna dict com sig_left, sig_bottom, sig_width, sig_height, sig_page
    ou None se não foram enviadas / inválidas.
    """
    try:
        sig_left   = post_data.get('sig_left', '').strip()
        sig_bottom = post_data.get('sig_bottom', '').strip()
        sig_width  = post_data.get('sig_width', '').strip()
        sig_height = post_data.get('sig_height', '').strip()
        sig_page   = post_data.get('sig_page', '').strip()
        if not all([sig_left, sig_bottom, sig_width, sig_height, sig_page]):
            return None
        return {
            'sig_left':   float(sig_left),
            'sig_bottom': float(sig_bottom),
            'sig_width':  float(sig_width),
            'sig_height': float(sig_height),
            'sig_page':   int(sig_page),
        }
    except (ValueError, TypeError) as exc:
        # Descartar a posição em silêncio faz a assinatura cair no bloco automático
        # da grade em vez de onde foi pedido — diferença de layout que ninguém
        # consegue explicar depois olhando só o PDF.
        logger.warning(
            f'Posicao customizada da assinatura ignorada (valores invalidos): {exc}'
        )
        return None


class ErroAssinaturaUsuario(Exception):
    """
    Erro que o operador entende e consegue corrigir sozinho.

    Senha errada, arquivo que não é um .pfx, certificado vencido: nada disso é
    falha do sistema, e responder 500 com o texto cru do erro só assusta quem
    está assinando. Separado do Exception genérico para as views devolverem 400
    com a mensagem — que é o que o caminho local já fazia em `_validar_certificado`.
    """


def _erro_de_assinatura(exc):
    """
    Converte um AssinaturaAPIError na exceção certa para o chamador levantar.

    HTTP 400 do microserviço é recusa de validação (certificado fora da validade,
    senha incorreta, parâmetro faltando) — problema do usuário. Qualquer outra
    coisa (conexão, timeout, 5xx) é falha de infraestrutura e continua sendo erro
    genérico.
    """
    if getattr(exc, 'status_code', None) == 400:
        return ErroAssinaturaUsuario(str(exc))
    return Exception(str(exc))


def _metadados_certificado_via_api(certificado_bytes, senha):
    """
    Lê os metadados do certificado no microserviço (POST /validate-pfx).

    Existe por dois motivos:

    1. Preencher `subject`, `issuer`, `serial`, `valid_from` e `valid_to` no
       `assinatura_info`. Quando o SAPL delega a assinatura, ele não abre o PFX —
       e sem esta chamada esses campos ficavam string vazia, deixando emissor,
       série e validade em branco em tudo que lê o `assinatura_info`.
    2. Recusar certificado fora da validade antes de assinar, com a mesma
       mensagem do caminho local (`_validar_certificado`).

    A senha é usada só nesta requisição e não é persistida em lugar nenhum.

    Retorna dict com as chaves já no formato do `assinatura_info` (vazio se o
    microserviço não respondeu). Lança ErroAssinaturaUsuario para PFX recusado.
    """
    from sapl.materia.assinatura_api_client import (
        AssinaturaAPIError, validar_pfx_via_api,
    )

    try:
        info = validar_pfx_via_api(certificado_bytes, senha) or {}
    except AssinaturaAPIError as exc:
        if getattr(exc, 'status_code', None) == 400:
            # PFX ilegível ou senha incorreta: o /sign recusaria do mesmo jeito,
            # e aqui a mensagem chega antes de enviar o documento.
            raise ErroAssinaturaUsuario(str(exc))
        # Indisponibilidade do /validate-pfx não pode impedir a assinatura: o
        # /sign também recusa certificado vencido. Só perdemos os metadados.
        logger.warning(
            f'[assinatura-api] Nao foi possivel ler os metadados do certificado '
            f'(/validate-pfx): {exc}. A assinatura segue sem eles.'
        )
        return {}

    if info.get('is_valid_now') is False:
        validade = ' a '.join(
            v for v in (info.get('not_valid_before'), info.get('not_valid_after')) if v
        )
        raise ErroAssinaturaUsuario(
            'Certificado expirado ou ainda não válido.'
            + (f' Validade: {validade}.' if validade else '')
        )

    serial = info.get('serial_number')
    return {
        'subject': info.get('subject') or '',
        'issuer': info.get('issuer') or '',
        'serial': '' if serial is None else str(serial),
        'valid_from': info.get('not_valid_before') or '',
        'valid_to': info.get('not_valid_after') or '',
    }


def _nome_e_cargo_do_assinante(request):
    """
    Nome e cargo que vão IMPRESSOS no documento, via Autor.operadores → Parlamentar.

    Fonte única para os dois backends. Existia em duas cópias — uma aqui e outra
    inline no ramo da API — que hoje coincidiam por acaso: mudar o critério em uma
    faria o mesmo vereador sair com nomes diferentes conforme o backend da casa.

    Quem assina é o vereador, então o nome impresso é o dele. O operador (assessor)
    fica registrado à parte, em `signed_by`.
    """
    nome_assinante = request.user.get_full_name() or request.user.username
    cargo = 'Usuário do Sistema'

    try:
        from sapl.base.models import Autor
        from sapl.parlamentares.models import Parlamentar

        autor = Autor.objects.filter(operadores=request.user).first()
        if autor:
            # Tipo do autor vira cargo (ex.: "Parlamentar" → "Vereador(a)")
            tipo_descricao = autor.tipo.descricao if autor.tipo else ''
            if tipo_descricao == 'Parlamentar':
                cargo = 'Vereador(a)'
            elif tipo_descricao:
                cargo = tipo_descricao

            if isinstance(autor.autor_related, Parlamentar):
                parlamentar = autor.autor_related
                tipo_nome = AppConfig.attr('assinatura_nome')
                nome_assinante = (
                    parlamentar.nome_completo if tipo_nome == 'C'
                    else parlamentar.nome_parlamentar
                )
    except Exception as exc:
        # Cair no username do operador significa imprimir no PDF um nome que não é
        # o do vereador. Não derruba a assinatura, mas não pode passar em silêncio.
        logger.warning(
            f'Nao foi possivel resolver o parlamentar de {request.user.username}: '
            f'{exc}. A assinatura sai com "{nome_assinante}".'
        )

    return nome_assinante, cargo


def _tipo_certificado_pelo_emissor(issuer):
    """Rotula o certificado a partir do emissor (mesma regra nos dois backends)."""
    issuer_str = str(issuer or '').upper()
    if 'ICP-BRASIL' in issuer_str or 'ICP BRASIL' in issuer_str:
        return 'ICP-Brasil'
    return 'Certificado Digital'


def _ler_brasao():
    """
    Bytes do logotipo da casa, ou None.

    Precisa ir em TODAS as assinaturas da mesma matéria: o brasão desloca a grade
    de blocos em 3 mm, então mandá-lo só na primeira desalinharia os blocos
    seguintes com o que já está desenhado na página.
    """
    caminho = _encontrar_logo()
    if not caminho:
        return None
    try:
        with open(caminho, 'rb') as f:
            return f.read()
    except OSError as exc:
        logger.warning(f'Nao foi possivel ler o brasao em {caminho}: {exc}')
        return None


def _compor_pagina_auth_localmente(pdf_bytes, request, tipo_doc, pk_doc, blocos):
    """
    Anexa a página de autenticação ao PDF aqui mesmo (caminho pré-C3).

    Continua em uso pelo backend local (pyhanko no Django) e pelo caso de posição
    explícita, em que o microserviço não pode compor. Retorna (pdf, codigo).
    """
    from PyPDF4 import PdfFileReader, PdfFileWriter

    original_pdf = PdfFileReader(io.BytesIO(pdf_bytes))
    last_page = original_pdf.getPage(original_pdf.getNumPages() - 1)
    page_width = float(last_page.mediaBox.getWidth())
    page_height = float(last_page.mediaBox.getHeight())

    codigo = _gerar_codigo_autenticacao(pdf_bytes)
    url_verificacao = _construir_url_verificacao(request, tipo_doc, pk_doc, codigo)
    auth_page_bytes = _gerar_pagina_autenticacao(
        blocos, codigo, url_verificacao, page_width, page_height
    )

    auth_page_pdf = PdfFileReader(io.BytesIO(auth_page_bytes))
    output_pdf = PdfFileWriter()
    for page_num in range(original_pdf.getNumPages()):
        output_pdf.addPage(original_pdf.getPage(page_num))
    output_pdf.addPage(auth_page_pdf.getPage(0))

    buf = io.BytesIO()
    output_pdf.write(buf)
    return buf.getvalue(), codigo


def _assinar_pdf_com_pagina_auth(pdf_bytes, *, request, tipo_doc, pk_doc,
                                 assinaturas_existentes,
                                 certificado_bytes=None, senha=None,
                                 assinatura_a3_bytes=None, cert_chain_bytes=None,
                                 tipo_cert_input='a1',
                                 posicao_custom=None,
                                 hash_doc=''):
    """
    Orquestra a assinatura digital completa de um PDF.

    Dois backends, escolhidos por ASSINATURA_API_URL:

    - **API externa (padrão quando configurada)**: desde a fase C3 (AB#1473) quem
      compõe a página de autenticação é o microserviço. O SAPL manda os dados da
      casa legislativa (URL de verificação, nome, brasão, bloco do assinante) e
      recebe de volta o PDF já composto e assinado, mais o código impresso. Não
      manda posição: a grade é do microserviço, e é isso que faz SAPL e app do AMU
      produzirem o mesmo artefato sem reimplementar o desenho.
    - **pyhanko local (ASSINATURA_API_URL vazio)**: compõe a página aqui e assina
      no próprio Django, como sempre fez.

    posicao_custom : dict opcional com chaves sig_left, sig_bottom, sig_width,
                     sig_height (em pontos PDF) e sig_page (1-based).
                     Quando fornecido, substitui o cálculo automático de grid —
                     e, na API externa, mantém a composição local, porque
                     coordenada explícita e composição no microserviço disputam
                     o mesmo campo.
    hash_doc       : código de autenticação já emitido para o documento. Vai para
                     o carimbo visual no backend local e, na API externa, é o
                     `codigo_autenticacao` devolvido ao microserviço da 2ª
                     assinatura em diante.

    Retorna (signed_pdf_bytes, nova_assinatura_dict, codigo_autenticacao_ou_None).
      - codigo_autenticacao_ou_None é não-None apenas na 1ª assinatura.

    Lança ErroAssinaturaUsuario quando o problema é do operador (certificado
    vencido, senha incorreta) e Exception nos demais casos.
    """
    from PyPDF4 import PdfFileReader, PdfFileWriter
    import base64 as _base64

    ja_tem_pdf_assinado = bool(assinaturas_existentes)

    # ── Informações do assinante ──────────────────────────────────────────────
    # Na API externa o SAPL não abre o PFX: quem assina é o microserviço. O nome
    # que vai no PDF é o do parlamentar (relação User → Autor), e os dados do
    # certificado vêm do /validate-pfx.
    if _usar_api_externa():
        from sapl.materia.assinatura_api_client import (
            AssinaturaAPIError,
            assinar_pdf_com_pagina_autenticacao,
            assinar_pdf_via_api,
        )

        # O tipo do certificado só é conhecido de verdade pelo /validate-pfx (C3);
        # este é o rótulo de partida, sobrescrito quando os metadados chegam.
        tipo_cert_display = 'Certificado Digital'

        # Nome/cargo pela MESMA função do backend local: o vereador não pode sair
        # com nome diferente conforme a casa usa microserviço ou pyhanko.
        nome_assinante, cargo = _nome_e_cargo_do_assinante(request)

        data_assinatura = timezone.localtime(timezone.now())
        data_formatada = data_assinatura.strftime('%d/%m/%Y %H:%M:%S')
        data_simples = data_assinatura.strftime('%d/%m/%Y %H:%M')
        codigo_retorno = None

        # Metadados do certificado: o /validate-pfx responde ANTES de assinar quem
        # emitiu, qual a série e até quando vale. Sem esta chamada esses campos iam
        # vazios para o assinatura_info — e o SAPL exibia "Válido até:" em branco.
        # Ela também é a checagem de validade que o caminho local faz em
        # `_validar_certificado`: certificado vencido não chega a ser enviado.
        cert_api = _metadados_certificado_via_api(certificado_bytes, senha)

        # O bloco desta assinatura — o único que a página precisa desenhar agora.
        bloco_atual = {
            'nome_assinante': nome_assinante,
            'cargo': cargo,
            'data_assinatura': data_simples,
        }

        if posicao_custom:
            # Posição explícita pedida pelo chamador. Quando o microserviço compõe a
            # página, é ELE quem decide a posição do bloco (a grade é dele), então
            # `auth_page` e coordenada explícita não convivem: pedir os dois faria a
            # coordenada do usuário ser silenciosamente descartada. Neste caso — e só
            # nele — a composição continua sendo feita aqui, como antes da C3.
            if not ja_tem_pdf_assinado:
                pdf_para_assinar, codigo_retorno = _compor_pagina_auth_localmente(
                    pdf_bytes, request, tipo_doc, pk_doc, [bloco_atual]
                )
            else:
                pdf_para_assinar = pdf_bytes  # já inclui página de autenticação

            try:
                pdf_assinado_bytes = assinar_pdf_via_api(
                    pdf_para_assinar,
                    certificado_bytes=certificado_bytes,
                    senha=senha,
                    reason='Documento assinado digitalmente nos termos da MP 2.200-2/2001',
                    location=_obter_nome_casa_legislativa(),
                    signature_page=posicao_custom.get('sig_page'),
                    signature_left=posicao_custom.get('sig_left'),
                    signature_bottom=posicao_custom.get('sig_bottom'),
                    signature_width=posicao_custom.get('sig_width'),
                    signature_height=posicao_custom.get('sig_height'),
                )
            except AssinaturaAPIError as exc:
                raise _erro_de_assinatura(exc)
        else:
            # Caminho normal (C3): o microserviço compõe a página de autenticação —
            # código, URL de verificação, QR e os blocos — e escolhe o bloco desta
            # assinatura contando as que já existem no PDF. O SAPL só manda o que é
            # da casa legislativa. Nenhum `signature_*` vai junto, de propósito.
            try:
                resultado = assinar_pdf_com_pagina_autenticacao(
                    pdf_bytes,
                    certificado_bytes=certificado_bytes,
                    senha=senha,
                    verification_url_base=_construir_url_verificacao_base(
                        request, tipo_doc, pk_doc
                    ),
                    assinaturas=[bloco_atual],
                    casa_legislativa=_obter_nome_casa_legislativa(),
                    signer_name=nome_assinante,
                    signer_role=cargo,
                    # Da 2ª assinatura em diante o código já está impresso na página:
                    # o PDF mudou ao ser assinado e o hash de agora não o reproduz.
                    codigo_autenticacao=(hash_doc or '') if ja_tem_pdf_assinado else None,
                    brasao_bytes=_ler_brasao(),
                    brasao_filename=os.path.basename(_encontrar_logo() or 'brasao.png'),
                    reason='Documento assinado digitalmente nos termos da MP 2.200-2/2001',
                    location=_obter_nome_casa_legislativa(),
                )
            except AssinaturaAPIError as exc:
                raise _erro_de_assinatura(exc)

            if not resultado.auth_page_suportado:
                # Sem os cabeçalhos do auth_page o microserviço ignorou a composição:
                # o PDF sairia sem página de autenticação e sem código verificável.
                # Falhar aqui é melhor do que gravar um documento inverificável.
                raise Exception(
                    'O microserviço de assinatura não compôs a página de '
                    'autenticação (resposta sem X-Auth-Page-Applied). Atualize o '
                    'microserviço para a versão com suporte a auth_page.'
                )

            pdf_assinado_bytes = resultado.pdf
            if resultado.auth_page_aplicada:
                codigo_retorno = resultado.codigo_autenticacao

        nova_assinatura = {
            'tipo_certificado': tipo_cert_input.upper(),
            'tipo_certificado_display': (
                f'{_tipo_certificado_pelo_emissor(cert_api.get("issuer", ""))} – '
                f'{tipo_cert_input.upper()}'
            ),
            'subject': cert_api.get('subject', ''),
            'issuer': cert_api.get('issuer', ''),
            'serial': cert_api.get('serial', ''),
            'valid_from': cert_api.get('valid_from', ''),
            'valid_to': cert_api.get('valid_to', ''),
            'signed_by': request.user.username,
            'nome_assinante': nome_assinante,
            'cargo': cargo,
            'data_assinatura': data_formatada,
            'validade_juridica': 'Assinatura Eletrônica Qualificada',
            'backend': 'api_externa',
        }
        return pdf_assinado_bytes, nova_assinatura, codigo_retorno

    else:
        # ── Backend local: pyhanko ─────────────────────────────────────────
        from pyhanko.sign import signers, fields
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.sign.fields import SigFieldSpec
        from pyhanko.sign.signers.pdf_signer import PdfSigner
        from pyhanko.pdf_utils.reader import PdfFileReader as PyhankoReader

        # Carregar certificado A1
        import tempfile as tmp_module
        with tmp_module.NamedTemporaryFile(delete=False, suffix='.pfx') as tmp_cert:
            tmp_cert.write(certificado_bytes)
            tmp_cert_path = tmp_cert.name
        try:
            signer = signers.SimpleSigner.load_pkcs12(
                pfx_file=tmp_cert_path,
                passphrase=senha.encode('utf-8')
            )
        except Exception as cert_error:
            logger.warning(f'Falha ao abrir o PFX: {cert_error}')
            raise ErroAssinaturaUsuario(_mensagem_de_erro_do_pfx(cert_error))
        finally:
            if os.path.exists(tmp_cert_path):
                os.unlink(tmp_cert_path)

        if signer is None:
            raise ErroAssinaturaUsuario(
                'Não foi possível carregar o certificado. Verifique se o arquivo '
                '.pfx/.p12 é válido e contém uma chave de assinatura.'
            )

        cert_info = signer.signing_cert
        error_response = _validar_certificado(cert_info)
        if error_response:
            import json as _json
            data = _json.loads(error_response.content)
            # Certificado vencido é problema do operador, não falha do sistema: 400
            # com a mensagem, igual ao que o microserviço devolve no outro backend.
            raise ErroAssinaturaUsuario(data.get('error', 'Certificado inválido.'))

        # Criar objeto fake para _obter_info_assinante
        class _CertWrapper:
            def __init__(self, c): self._c = c
            @property
            def issuer(self): return self._c.issuer
            @property
            def subject(self): return self._c.subject
            @property
            def serial_number(self): return self._c.serial_number
            @property
            def not_valid_before(self): return self._c.not_valid_before
            @property
            def not_valid_after(self): return self._c.not_valid_after

        nome_assinante, cargo, tipo_cert_display = _obter_info_assinante(request, cert_info)
        data_assinatura = timezone.localtime(timezone.now())
        data_formatada = data_assinatura.strftime('%d/%m/%Y %H:%M:%S')
        data_simples = data_assinatura.strftime('%d/%m/%Y %H:%M')

        n_assinatura = len(assinaturas_existentes)
        sig_field_name = (
            f'AssinaturaDigital_{n_assinatura + 1}' if n_assinatura > 0
            else 'AssinaturaDigital'
        )
        codigo_retorno = None

        if ja_tem_pdf_assinado:
            # Assinatura subsequente (incremental)
            temp_pypdf = PdfFileReader(io.BytesIO(pdf_bytes))
            auth_page = temp_pypdf.getPage(temp_pypdf.getNumPages() - 1)
            auth_page_width = float(auth_page.mediaBox.getWidth())
            auth_page_height = float(auth_page.mediaBox.getHeight())
            x1, y1, x2, y2 = _posicao_bloco_assinatura(
                n_assinatura, auth_page_width, auth_page_height
            )

            signed_buffer = io.BytesIO()
            with io.BytesIO(pdf_bytes) as inf:
                w = IncrementalPdfFileWriter(inf)
                temp_reader = PyhankoReader(io.BytesIO(pdf_bytes))
                last_page_idx = temp_reader.root['/Pages']['/Count'] - 1

                sig_field = SigFieldSpec(
                    sig_field_name=sig_field_name,
                    on_page=last_page_idx,
                    box=(x1, y1, x2, y2)
                )
                fields.append_signature_field(w, sig_field)

                meta = signers.PdfSignatureMetadata(
                    field_name=sig_field_name,
                    location=_obter_nome_casa_legislativa(),
                    reason='Documento assinado digitalmente nos termos da MP 2.200-2/2001',
                    name=nome_assinante
                )
                # `hash_doc` vem do chamador (codigo_autenticacao gravado na 1ª
                # assinatura). Zerá-lo aqui — como se fazia — apagava o "Hash:"
                # do carimbo justamente na assinatura em que ele já existe.
                stamp_style = _criar_stamp_style(nome_assinante, cargo, hash_doc)
                pdf_signer = PdfSigner(meta, signer=signer, stamp_style=stamp_style)
                pdf_signer.sign_pdf(
                    w,
                    existing_fields_only=True,
                    appearance_text_params={'signer': nome_assinante},
                    output=signed_buffer,
                )

            signed_buffer.seek(0)
            pdf_assinado_bytes = signed_buffer.read()

        else:
            # Primeira assinatura: página de autenticação + pyhanko
            stamped_bytes, codigo = _compor_pagina_auth_localmente(
                pdf_bytes, request, tipo_doc, pk_doc,
                [{
                    'nome_assinante': nome_assinante,
                    'cargo': cargo,
                    'data_assinatura': data_simples,
                }],
            )

            signed_buffer = io.BytesIO()
            with io.BytesIO(stamped_bytes) as inf:
                w = IncrementalPdfFileWriter(inf)
                meta = signers.PdfSignatureMetadata(
                    field_name='AssinaturaDigital',
                    location=_obter_nome_casa_legislativa(),
                    reason='Documento assinado digitalmente nos termos da MP 2.200-2/2001',
                    name=nome_assinante
                )
                signers.sign_pdf(w, meta, signer=signer, output=signed_buffer)

            signed_buffer.seek(0)
            pdf_assinado_bytes = signed_buffer.read()
            codigo_retorno = codigo

        nova_assinatura = {
            'tipo_certificado': 'A1',
            'tipo_certificado_display': f'{tipo_cert_display} – A1',
            'subject': str(cert_info.subject),
            'issuer': str(cert_info.issuer),
            'serial': str(cert_info.serial_number),
            'valid_from': cert_info.not_valid_before.isoformat(),
            'valid_to': cert_info.not_valid_after.isoformat(),
            'signed_by': request.user.username,
            'nome_assinante': nome_assinante,
            'cargo': cargo,
            'data_assinatura': data_formatada,
            'validade_juridica': 'Assinatura Eletrônica Qualificada',
            'backend': 'pyhanko_local',
        }
        return pdf_assinado_bytes, nova_assinatura, codigo_retorno


# =============================================================================
# Funções auxiliares para página de autenticação
# =============================================================================

def _gerar_codigo_autenticacao(pdf_bytes):
    """Gera código de autenticação SHA-256 truncado (16 caracteres hex)."""
    return hashlib.sha256(pdf_bytes).hexdigest()[:16].upper()


def _gerar_qrcode_image(url):
    """Gera imagem PNG de QR Code em memória (BytesIO)."""
    import qrcode
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _construir_url_verificacao_base(request, tipo, pk):
    """
    URL pública de verificação SEM o `?codigo=`.

    É o que vai para o microserviço: só o SAPL sabe a URL pública da casa, mas o
    código quem gera é quem compõe a página — então a montagem final é lá.
    """
    if tipo == 'materia':
        url_name = 'sapl.materia:materia_verificar_documento'
    else:
        url_name = 'sapl.materia:docacessorio_verificar_documento'

    return request.build_absolute_uri(reverse(url_name, kwargs={'pk': pk}))


def _construir_url_verificacao(request, tipo, pk, codigo):
    """Monta URL pública de verificação."""
    return f'{_construir_url_verificacao_base(request, tipo, pk)}?codigo={codigo}'


def _obter_nome_casa_legislativa():
    """Obtém o nome da Casa Legislativa do AppConfig."""
    try:
        from sapl.base.models import CasaLegislativa
        casa = CasaLegislativa.objects.first()
        if casa:
            return casa.nome
    except Exception:
        pass
    return "Casa Legislativa"


def _encontrar_logo():
    """Procura logo da câmara para usar na página de autenticação."""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        possible_paths = [
            os.path.join(settings.MEDIA_ROOT, 'sapl/public/casa/logotipo/logo.png'),
            os.path.join(settings.MEDIA_ROOT, 'sapl/public/casa/logotipo/logotipo.png'),
            os.path.join(base_dir, 'sapl/static/sapl/frontend/img/logo-camara-padrao.png'),
            os.path.join(base_dir, 'sapl/static/sapl/frontend/img/logo.png'),
            os.path.join(base_dir, 'sapl/static/sapl/frontend/img/pdflogo.png'),
        ]

        logo_dir = os.path.join(settings.MEDIA_ROOT, 'sapl/public/casa/logotipo')
        if os.path.exists(logo_dir):
            for f in os.listdir(logo_dir):
                if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                    possible_paths.insert(0, os.path.join(logo_dir, f))

        for path in possible_paths:
            if os.path.exists(path):
                return path
    except Exception:
        pass
    return None


def _calcular_blocks_y_start(page_height):
    """Calcula posição Y onde blocos de assinatura começam na página de autenticação."""
    from reportlab.lib.units import mm
    y = page_height - 40 * mm
    if _encontrar_logo():
        y -= 3 * mm
    y -= 6 * mm   # título
    y -= 4 * mm   # subtítulo
    y -= 10 * mm  # gap separador
    return y


def _posicao_bloco_assinatura(idx, page_width, page_height):
    """
    Calcula posição (x1, y1, x2, y2) para bloco de assinatura no índice dado.
    Usa o mesmo grid da página de autenticação (ReportLab).
    """
    from reportlab.lib.units import mm

    margin = 20 * mm
    col_width = (page_width - 3 * margin) / 2
    block_height = 20 * mm
    block_spacing = 2 * mm
    col_x = [margin, margin + col_width + margin]

    y_start = _calcular_blocks_y_start(page_height)

    col = idx % 2
    row = idx // 2

    x = col_x[col]
    y_top = y_start - row * (block_height + block_spacing)

    return (x, y_top - block_height, x + col_width, y_top)


def _gerar_pagina_autenticacao(assinaturas_info, codigo, url_verificacao,
                               page_width, page_height):
    """
    Gera uma página PDF de autenticação com:
    - Cabeçalho com nome da casa legislativa
    - Blocos de assinatura em grade 2 colunas
    - Código de autenticação
    - QR Code
    - URL de verificação
    - Aviso legal (MP 2.200-2/2001)

    Retorna bytes do PDF de uma página.
    """
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_width, page_height))

    nome_casa = _obter_nome_casa_legislativa()
    center_x = page_width / 2

    # ---- Cabeçalho ----
    y = page_height - 40 * mm

    # Logo da câmara (pequeno, acima do título)
    logo_path = _encontrar_logo()
    if logo_path:
        try:
            logo = ImageReader(logo_path)
            logo_size = 15 * mm
            c.drawImage(logo, center_x - logo_size / 2, y + 2 * mm,
                        width=logo_size, height=logo_size,
                        preserveAspectRatio=True, mask='auto')
            y -= 3 * mm
        except Exception:
            pass

    c.setFont("Helvetica-Bold", 14)
    c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(center_x, y, "PÁGINA DE AUTENTICAÇÃO")
    y -= 6 * mm

    c.setFont("Helvetica", 10)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.drawCentredString(center_x, y, nome_casa)
    y -= 4 * mm

    # Linha separadora
    c.setStrokeColorRGB(0.7, 0.7, 0.7)
    c.setLineWidth(0.5)
    margin = 20 * mm
    c.line(margin, y, page_width - margin, y)
    y -= 10 * mm

    # ---- Blocos de assinatura (grade 2 colunas) ----
    # Usa mesmas dimensões de _posicao_bloco_assinatura para consistência
    # com os stamps pyhanko das assinaturas subsequentes.
    col_width = (page_width - 3 * margin) / 2
    block_height = 20 * mm
    block_spacing = 2 * mm
    col_x = [margin, margin + col_width + margin]

    # Posição mínima Y: footer fixo no rodapé
    footer_y = 68 * mm

    for idx, assinatura in enumerate(assinaturas_info):
        col = idx % 2
        row = idx // 2

        bx = col_x[col]
        by_top = y - row * (block_height + block_spacing)

        # Se vai ultrapassar a área do footer, para
        if by_top - block_height < footer_y:
            break

        # Borda do bloco
        c.setStrokeColorRGB(0.6, 0.6, 0.6)
        c.setLineWidth(0.5)
        c.rect(bx, by_top - block_height, col_width, block_height)

        # Conteúdo do bloco
        text_x = bx + 3 * mm
        text_y = by_top - 3.5 * mm

        c.setFont("Helvetica", 6)
        c.setFillColorRGB(0.3, 0.3, 0.3)
        c.drawString(text_x, text_y, "Assinado digitalmente por")

        text_y -= 3.5 * mm
        c.setFont("Helvetica-Bold", 7)
        c.setFillColorRGB(0, 0, 0)
        nome = assinatura.get('nome_assinante', 'N/A').upper()
        if len(nome) > 40:
            nome = nome[:40] + "..."
        c.drawString(text_x, text_y, nome)

        text_y -= 3 * mm
        c.setFont("Helvetica", 6)
        c.setFillColorRGB(0.3, 0.3, 0.3)
        cargo = assinatura.get('cargo', '')
        if cargo:
            c.drawString(text_x, text_y, cargo)
            text_y -= 3 * mm

        data = assinatura.get('data_assinatura', '')
        c.drawString(text_x, text_y, f"Data: {data}")

        text_y -= 3 * mm
        c.setFont("Helvetica", 5)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawString(text_x, text_y, f"Hash: {codigo}")

    # ---- Footer fixo no rodapé ----
    y_footer = footer_y

    # Código de Autenticação
    c.setFont("Helvetica-Bold", 11)
    c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(center_x, y_footer,
                        f"Código de Autenticação: {codigo}")
    y_footer -= 8 * mm

    # QR Code
    try:
        qr_buf = _gerar_qrcode_image(url_verificacao)
        qr_img = ImageReader(qr_buf)
        qr_size = 25 * mm
        c.drawImage(qr_img, center_x - qr_size / 2, y_footer - qr_size,
                    width=qr_size, height=qr_size)
        y_footer -= qr_size + 3 * mm
    except Exception as e:
        logger.warning(f"Não foi possível gerar QR Code: {e}")
        y_footer -= 3 * mm

    # URL de verificação
    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.2, 0.2, 0.8)
    c.drawCentredString(center_x, y_footer,
                        f"Verifique em: {url_verificacao}")
    y_footer -= 8 * mm

    # Aviso legal
    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawCentredString(center_x, y_footer,
                        "Documento assinado digitalmente nos termos da")
    y_footer -= 3.5 * mm
    c.drawCentredString(center_x, y_footer,
                        "Medida Provisória nº 2.200-2/2001.")

    c.save()
    buf.seek(0)
    return buf.read()


def _criar_stamp_style(nome_assinante, cargo, hash_doc=''):
    """
    Cria um TextStampStyle customizado para assinaturas subsequentes,
    mantendo visual consistente com a página de autenticação gerada
    na primeira assinatura (Helvetica, borda simples, mesmo layout).
    """
    from pyhanko.stamp import TextStampStyle, TextBoxStyle
    from pyhanko.pdf_utils.layout import SimpleBoxLayoutRule, AxisAlignment, Margins

    # Monta texto do carimbo com cargo (se houver) + hash
    linhas = ['Assinado digitalmente por', '%(signer)s']
    if cargo:
        linhas.append(cargo)
    linhas.append('Data: %(ts)s')
    if hash_doc:
        linhas.append(f'Hash: {hash_doc}')

    # Usa Helvetica para consistência com a página de autenticação (ReportLab)
    font_kwargs = {}
    try:
        from pyhanko.pdf_utils.font import SimpleFontEngineFactory
        font_kwargs['font'] = SimpleFontEngineFactory(
            name='Helvetica', avg_width=0.5
        )
    except (ImportError, Exception):
        pass  # Usa fonte padrão se Helvetica não disponível

    return TextStampStyle(
        stamp_text='\n'.join(linhas),
        text_box_style=TextBoxStyle(
            font_size=7,
            leading=10,
            border_width=0,
            **font_kwargs,
        ),
        # Borda externa = tamanho completo da annotation box (mesmo tamanho
        # dos blocos desenhados pelo ReportLab na página de autenticação)
        border_width=1,
        # Texto alinhado no topo-esquerdo com margem interna,
        # consistente com o layout do ReportLab
        inner_content_layout=SimpleBoxLayoutRule(
            x_align=AxisAlignment.ALIGN_MIN,
            y_align=AxisAlignment.ALIGN_MAX,
            margins=Margins(left=8, right=8, top=5, bottom=5),
        ),
        background=None,
        background_opacity=0,
        timestamp_format='%d/%m/%Y %H:%M',
    )


def _obter_info_assinante(request, cert_info):
    """
    Obtém informações do assinante (nome, cargo, tipo_cert).
    Retorna (nome_assinante, cargo, tipo_cert).
    """
    nome_assinante, cargo = _nome_e_cargo_do_assinante(request)
    return nome_assinante, cargo, _tipo_certificado_pelo_emissor(cert_info.issuer)


def _mensagem_de_erro_do_pfx(exc):
    """
    Traduz a falha do pyhanko ao abrir o PKCS12 para algo que o operador resolve.

    Sem isto, senha errada vira `Exception` genérica e a view responde 500 com o
    texto cru da biblioteca — quem está assinando não tem como saber que só errou
    a senha. É a mesma tradução que o caminho via microserviço faz ao converter o
    HTTP 400 em `ErroAssinaturaUsuario`; os dois backends precisam falar igual.
    """
    texto = str(exc)
    minusculo = texto.lower()
    if 'password' in minusculo or 'mac' in minusculo:
        detalhe = 'Senha incorreta.'
    elif 'decode' in minusculo or 'parse' in minusculo:
        detalhe = 'Arquivo não é um certificado válido (.pfx/.p12).'
    else:
        detalhe = f'Detalhes: {texto}'
    return f'Erro ao carregar certificado: {detalhe}'


def _validar_certificado(cert_info):
    """
    Valida datas do certificado.
    Retorna error_response ou None se válido.
    """
    now = timezone.now()
    valid_before = cert_info.not_valid_before
    valid_after = cert_info.not_valid_after
    if valid_before.tzinfo is None:
        import pytz
        valid_before = pytz.UTC.localize(valid_before)
    if valid_after.tzinfo is None:
        import pytz
        valid_after = pytz.UTC.localize(valid_after)
    if now < valid_before or now > valid_after:
        return JsonResponse({
            'success': False,
            'error': 'Certificado expirado ou ainda não válido.'
        }, status=400)
    return None


# =============================================================================
# Geração de PDFs
# =============================================================================

def _gerar_pdf_da_materia(materia, request):
    """
    Gera o PDF da matéria para assinatura.
    Primeiro tenta usar o PDF existente, depois converte DOCX via OnlyOffice.
    Retorna bytes do PDF ou None em caso de erro.
    """
    import requests as http_requests
    import xml.etree.ElementTree as ET

    # Se não tem documento, retorna None
    if not materia.texto_original:
        return None, "Matéria não possui documento de texto original."

    file_name = materia.texto_original.name.lower()

    # Se já é PDF, retorna diretamente
    if file_name.endswith('.pdf'):
        try:
            with open(materia.texto_original.path, 'rb') as f:
                return f.read(), None
        except Exception as e:
            logger.error(f"Erro ao ler arquivo PDF: {e}")
            return None, f"Erro ao ler o arquivo PDF: {e}"

    # Converter DOCX para PDF via OnlyOffice
    from sapl.materia.onlyoffice_materia_views import generate_file_key

    download_url = build_onlyoffice_url(
        request,
        reverse('sapl.materia:materia_onlyoffice_download', kwargs={'pk': materia.pk})
    )

    # URL da API de conversão do OnlyOffice
    conversion_url = f'{settings.ONLYOFFICE_URL}/ConvertService.ashx'

    conversion_data = {
        "async": False,
        "filetype": "docx",
        "key": generate_file_key("materia_sign", materia.pk, request.user.pk),
        "outputtype": "pdf",
        "title": f"Materia_{materia.tipo}_{materia.numero}_{materia.ano}.pdf",
        "url": download_url,
    }

    # Adiciona JWT se estiver habilitado
    if getattr(settings, 'ONLYOFFICE_JWT_ENABLED', False) and getattr(settings, 'ONLYOFFICE_JWT_SECRET', None):
        import jwt
        token = jwt.encode(conversion_data, settings.ONLYOFFICE_JWT_SECRET, algorithm='HS256')
        conversion_data['token'] = token

    try:
        headers = {'Content-Type': 'application/json'}

        if getattr(settings, 'ONLYOFFICE_JWT_ENABLED', False) and getattr(settings, 'ONLYOFFICE_JWT_SECRET', None):
            import jwt
            header_token = jwt.encode({"payload": conversion_data}, settings.ONLYOFFICE_JWT_SECRET, algorithm='HS256')
            headers['Authorization'] = f'Bearer {header_token}'

        conversion_response = http_requests.post(
            conversion_url,
            json=conversion_data,
            headers=headers,
            timeout=60
        )

        if conversion_response.status_code != 200:
            return None, f"Erro na conversão OnlyOffice: status={conversion_response.status_code}"

        root = ET.fromstring(conversion_response.text)

        error_elem = root.find('Error')
        if error_elem is not None:
            return None, f"Erro na conversão do documento: código {error_elem.text}"

        file_url_elem = root.find('FileUrl')
        if file_url_elem is None or not file_url_elem.text:
            return None, "URL do PDF não retornada pelo OnlyOffice"

        pdf_url = file_url_elem.text
        pdf_response = http_requests.get(pdf_url, timeout=60)

        if pdf_response.status_code != 200:
            return None, f"Erro ao baixar PDF convertido: status={pdf_response.status_code}"

        return pdf_response.content, None

    except Exception as e:
        logger.error(f"Erro na geração de PDF: {e}")
        return None, f"Erro inesperado: {e}"


def _gerar_pdf_do_docacessorio(docacessorio, request):
    """
    Gera o PDF do documento acessório para assinatura.
    Se já é PDF, retorna direto. Se é DOCX, converte via OnlyOffice.
    Retorna (bytes, None) ou (None, erro).
    """
    import requests as http_requests
    import xml.etree.ElementTree as ET

    if not docacessorio.arquivo:
        return None, "Documento acessório não possui arquivo."

    file_name = docacessorio.arquivo.name.lower()

    # Se já é PDF, retorna diretamente
    if file_name.endswith('.pdf'):
        try:
            with open(docacessorio.arquivo.path, 'rb') as f:
                return f.read(), None
        except Exception as e:
            logger.error(f"Erro ao ler arquivo PDF: {e}")
            return None, f"Erro ao ler o arquivo PDF: {e}"

    # Converter DOCX para PDF via OnlyOffice
    from sapl.materia.onlyoffice_materia_views import generate_file_key

    download_url = build_onlyoffice_url(
        request,
        reverse('sapl.materia:docacessorio_onlyoffice_download', kwargs={'pk': docacessorio.pk})
    )

    conversion_url = f'{settings.ONLYOFFICE_URL}/ConvertService.ashx'

    conversion_data = {
        "async": False,
        "filetype": "docx",
        "key": generate_file_key("docacessorio_sign", docacessorio.pk, request.user.pk),
        "outputtype": "pdf",
        "title": f"DocAcessorio_{docacessorio.pk}.pdf",
        "url": download_url,
    }

    if getattr(settings, 'ONLYOFFICE_JWT_ENABLED', False) and getattr(settings, 'ONLYOFFICE_JWT_SECRET', None):
        import jwt
        token = jwt.encode(conversion_data, settings.ONLYOFFICE_JWT_SECRET, algorithm='HS256')
        conversion_data['token'] = token

    try:
        headers = {'Content-Type': 'application/json'}

        if getattr(settings, 'ONLYOFFICE_JWT_ENABLED', False) and getattr(settings, 'ONLYOFFICE_JWT_SECRET', None):
            import jwt
            header_token = jwt.encode({"payload": conversion_data}, settings.ONLYOFFICE_JWT_SECRET, algorithm='HS256')
            headers['Authorization'] = f'Bearer {header_token}'

        conversion_response = http_requests.post(
            conversion_url,
            json=conversion_data,
            headers=headers,
            timeout=60
        )

        if conversion_response.status_code != 200:
            return None, f"Erro na conversão OnlyOffice: status={conversion_response.status_code}"

        root = ET.fromstring(conversion_response.text)

        error_elem = root.find('Error')
        if error_elem is not None:
            return None, f"Erro na conversão do documento: código {error_elem.text}"

        file_url_elem = root.find('FileUrl')
        if file_url_elem is None or not file_url_elem.text:
            return None, "URL do PDF não retornada pelo OnlyOffice"

        pdf_url = file_url_elem.text
        pdf_response = http_requests.get(pdf_url, timeout=60)

        if pdf_response.status_code != 200:
            return None, f"Erro ao baixar PDF convertido: status={pdf_response.status_code}"

        return pdf_response.content, None

    except Exception as e:
        logger.error(f"Erro na geração de PDF do doc acessório: {e}")
        return None, f"Erro inesperado: {e}"


# =============================================================================
# Assinatura Digital de Matéria Legislativa
# =============================================================================

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def materia_assinar_a1(request, pk):
    """
    Assina o PDF da matéria com certificado A1 (arquivo .pfx/.p12).

    Usa API externa de assinatura quando ASSINATURA_API_URL estiver configurado;
    caso contrário assina localmente com pyhanko.

    Parâmetros POST:
    - certificado: arquivo .pfx ou .p12
    - senha: senha do certificado
    """
    materia = get_object_or_404(MateriaLegislativa, pk=pk)

    assinaturas_existentes = _normalizar_assinatura_info(materia.assinatura_info)
    if any(a.get('signed_by') == request.user.username for a in assinaturas_existentes):
        return JsonResponse({
            'success': False,
            'error': 'Você já assinou esta matéria.'
        }, status=400)

    certificado_file = request.FILES.get('certificado')
    senha = request.POST.get('senha', '')

    if not certificado_file:
        return JsonResponse({'success': False, 'error': 'Certificado não informado.'}, status=400)
    if not senha:
        return JsonResponse({'success': False, 'error': 'Senha do certificado não informada.'}, status=400)

    # PDF a assinar: já assinado (subsequente) ou original (primeira assinatura)
    if materia.pdf_assinado:
        with open(materia.pdf_assinado.path, 'rb') as f:
            pdf_bytes = f.read()
    else:
        pdf_bytes, error = _gerar_pdf_da_materia(materia, request)
        if error:
            return JsonResponse({'success': False, 'error': error}, status=400)

    certificado_bytes = certificado_file.read()

    # Posição personalizada enviada pelo usuário (opcional)
    posicao_custom = _extrair_posicao_custom(request.POST)

    try:
        signed_pdf_bytes, nova_assinatura, codigo = _assinar_pdf_com_pagina_auth(
            pdf_bytes,
            request=request,
            tipo_doc='materia',
            pk_doc=pk,
            assinaturas_existentes=assinaturas_existentes,
            certificado_bytes=certificado_bytes,
            senha=senha,
            tipo_cert_input='a1',
            posicao_custom=posicao_custom,
            hash_doc=materia.codigo_autenticacao or '',
        )
    except ImportError:
        logger.error("pyhanko não está instalado")
        return JsonResponse({
            'success': False,
            'error': 'Biblioteca de assinatura não instalada. Contate o administrador.'
        }, status=500)
    except ErroAssinaturaUsuario as e:
        # Certificado vencido, senha incorreta: o operador resolve sozinho, então
        # a resposta é 400 com a mensagem — não 500 com o erro cru.
        logger.warning(f"Assinatura da matéria {pk} recusada: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)
    except Exception as e:
        logger.error(f"Erro ao assinar PDF da matéria {pk}: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

    filename = f"materia_{materia.pk}_assinado_{int(timezone.now().timestamp())}.pdf"
    materia.pdf_assinado.save(filename, ContentFile(signed_pdf_bytes), save=False)

    if codigo:
        materia.codigo_autenticacao = codigo

    assinaturas_existentes.append(nova_assinatura)
    materia.assinatura_info = assinaturas_existentes
    materia.assinado_em = timezone.now()
    materia.assinado_por = request.user
    materia.save()

    # Invalida o badge de TODOS os coautores, não só de quem assinou: esta
    # assinatura muda a contagem deles também (a matéria some da minha lista e
    # continua na deles) e eles ficariam com o número velho até o TTL.
    from sapl.materia.pendencias import invalidar_cache_pendencias
    invalidar_cache_pendencias(materia=materia, user=request.user)

    logger.info(
        f"Matéria {materia.pk} assinada por {request.user.username} "
        f"(backend: {nova_assinatura.get('backend', '?')})"
    )

    return JsonResponse({
        'success': True,
        'message': 'PDF assinado com sucesso!',
        'backend': nova_assinatura.get('backend', ''),
        'certificado': {
            'nome': nova_assinatura.get('subject') or nova_assinatura.get('nome_assinante', ''),
            'validade': nova_assinatura.get('valid_to', ''),
        }
    })


@login_required
@require_http_methods(["POST"])
def materia_assinar_a3_preparar(request, pk):
    """
    Prepara a assinatura A3 gerando o hash do PDF para ser assinado pelo token.

    Retorna:
    - hash: hash SHA-256 do PDF em hexadecimal
    - pdf_base64: PDF codificado em base64 (para assinatura no cliente)
    """
    import base64

    materia = get_object_or_404(MateriaLegislativa, pk=pk)

    # Verifica permissão
    if not request.user.has_perm('materia.change_materialegislativa'):
        return JsonResponse({
            'success': False,
            'error': 'Você não tem permissão para assinar esta matéria.'
        }, status=403)

    # Verifica se já está assinada
    if materia.pdf_assinado:
        return JsonResponse({
            'success': False,
            'error': 'Esta matéria já possui um PDF assinado.'
        }, status=400)

    # Gera o PDF da matéria
    pdf_bytes, error = _gerar_pdf_da_materia(materia, request)
    if error:
        return JsonResponse({
            'success': False,
            'error': error
        }, status=400)

    # Calcula o hash SHA-256
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()

    # Codifica o PDF em base64
    pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

    return JsonResponse({
        'success': True,
        'hash': pdf_hash,
        'pdf_base64': pdf_base64,
        'materia_id': materia.pk
    })


@login_required
@require_http_methods(["POST"])
@csrf_exempt
def materia_assinar_a3_finalizar(request, pk):
    """
    Finaliza a assinatura A3 incorporando a assinatura recebida do token.

    Parâmetros POST (JSON):
    - signature: assinatura em base64
    - certificate: certificado em base64
    - certificate_chain: cadeia de certificados em base64 (opcional)
    """
    import base64

    materia = get_object_or_404(MateriaLegislativa, pk=pk)

    # Verifica permissão
    if not request.user.has_perm('materia.change_materialegislativa'):
        return JsonResponse({
            'success': False,
            'error': 'Você não tem permissão para assinar esta matéria.'
        }, status=403)

    # Verifica se já está assinada
    if materia.pdf_assinado:
        return JsonResponse({
            'success': False,
            'error': 'Esta matéria já possui um PDF assinado.'
        }, status=400)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Dados inválidos.'
        }, status=400)

    signature_b64 = data.get('signature')
    certificate_b64 = data.get('certificate')

    if not signature_b64 or not certificate_b64:
        return JsonResponse({
            'success': False,
            'error': 'Assinatura ou certificado não informados.'
        }, status=400)

    # Gera o PDF da matéria
    pdf_bytes, error = _gerar_pdf_da_materia(materia, request)
    if error:
        return JsonResponse({
            'success': False,
            'error': error
        }, status=400)

    try:
        from pyhanko.sign import signers, fields
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.sign.signers.pdf_cms import ExternalSigner
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend

        # Decodifica o certificado
        cert_der = base64.b64decode(certificate_b64)
        cert = x509.load_der_x509_certificate(cert_der, default_backend())

        # Verifica validade do certificado
        now = datetime.utcnow()
        if now < cert.not_valid_before or now > cert.not_valid_after:
            return JsonResponse({
                'success': False,
                'error': 'Certificado expirado ou ainda não válido.'
            }, status=400)

        # Decodifica a assinatura
        signature = base64.b64decode(signature_b64)

        # Cria arquivo temporário para o PDF assinado
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_signed:
            temp_signed_path = temp_signed.name

        try:
            with io.BytesIO(pdf_bytes) as inf:
                w = IncrementalPdfFileWriter(inf)

                # Adiciona campo de assinatura
                sig_field = fields.SigFieldSpec(
                    sig_field_name='AssinaturaDigital',
                    box=(50, 50, 250, 100)
                )

                # Metadados da assinatura
                meta = signers.PdfSignatureMetadata(
                    field_name='AssinaturaDigital',
                    location=_obter_nome_casa_legislativa(),
                    reason='Assinatura Digital de Matéria Legislativa (A3)',
                    name=request.user.get_full_name() or request.user.username
                )

                # Para assinatura A3, precisamos de integração mais complexa
                # Por enquanto, retornamos erro informando que A3 requer aplicação local
                return JsonResponse({
                    'success': False,
                    'error': 'Assinatura A3 requer aplicação local. Use o Assinador SERPRO ou similar.'
                }, status=501)

        finally:
            if os.path.exists(temp_signed_path):
                os.unlink(temp_signed_path)

    except ImportError as e:
        logger.error(f"Biblioteca não instalada: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Biblioteca de assinatura não instalada.'
        }, status=500)
    except Exception as e:
        logger.error(f"Erro ao finalizar assinatura A3: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erro ao processar assinatura: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def materia_pdf_assinado(request, pk):
    """
    Retorna o PDF assinado da matéria para download/visualização.
    """
    materia = get_object_or_404(MateriaLegislativa, pk=pk)

    if not materia.pdf_assinado:
        messages.error(request, 'Esta matéria não possui PDF assinado.')
        return redirect('sapl.materia:materialegislativa_detail', pk=pk)

    try:
        with open(materia.pdf_assinado.path, 'rb') as f:
            content = f.read()

        filename = f"Materia_{materia.tipo}_{materia.numero}_{materia.ano}_ASSINADO.pdf"
        filename = filename.replace(' ', '_').replace('/', '-')

        response = HttpResponse(content, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response

    except Exception as e:
        logger.error(f"Erro ao ler PDF assinado: {e}")
        messages.error(request, 'Erro ao ler o arquivo PDF assinado.')
        return redirect('sapl.materia:materialegislativa_detail', pk=pk)


@login_required
@require_http_methods(["GET"])
def materia_verificar_assinatura(request, pk):
    """
    Verifica a assinatura digital do PDF da matéria.
    Retorna informações sobre as assinaturas encontradas.
    """
    materia = get_object_or_404(MateriaLegislativa, pk=pk)

    if not materia.pdf_assinado:
        return JsonResponse({
            'success': False,
            'error': 'Esta matéria não possui PDF assinado.',
            'assinado': False
        })

    try:
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko.pdf_utils.reader import PdfFileReader

        with open(materia.pdf_assinado.path, 'rb') as f:
            reader = PdfFileReader(f)

            # Lista de assinaturas encontradas
            assinaturas = []

            # Verifica cada assinatura no PDF
            for sig_field_name in reader.embedded_signatures:
                try:
                    sig = reader.embedded_signatures[sig_field_name]

                    # Informações básicas da assinatura
                    sig_info = {
                        'campo': sig_field_name,
                        'assinante': str(sig.signer_cert.subject) if sig.signer_cert else 'Desconhecido',
                        'data': sig.self_reported_timestamp.isoformat() if sig.self_reported_timestamp else None,
                    }

                    assinaturas.append(sig_info)

                except Exception as sig_error:
                    logger.warning(f"Erro ao verificar assinatura {sig_field_name}: {sig_error}")
                    assinaturas.append({
                        'campo': sig_field_name,
                        'erro': str(sig_error)
                    })

            return JsonResponse({
                'success': True,
                'assinado': True,
                'total_assinaturas': len(assinaturas),
                'assinaturas': assinaturas,
                'info_salva': materia.assinatura_info
            })

    except ImportError:
        # Se pyhanko não estiver instalado, retorna info salva no modelo
        return JsonResponse({
            'success': True,
            'assinado': True,
            'info_salva': materia.assinatura_info,
            'verificacao_disponivel': False
        })
    except Exception as e:
        logger.error(f"Erro ao verificar assinatura: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erro ao verificar assinatura: {str(e)}',
            'assinado': True,
            'info_salva': materia.assinatura_info
        })


@login_required
@require_http_methods(["POST"])
def materia_remover_assinatura(request, pk):
    """
    Remove a assinatura digital da matéria.
    Requer: superusuário OU funcionalidade habilitada em AppConfig
    E permissão 'materia.can_remove_assinatura'.
    """
    if not _pode_remover_assinatura(request.user):
        return JsonResponse({
            'success': False,
            'error': 'Você não tem permissão para remover assinaturas digitais.'
        }, status=403)

    materia = get_object_or_404(MateriaLegislativa, pk=pk)

    if not materia.pdf_assinado:
        return JsonResponse({
            'success': False,
            'error': 'Esta matéria não possui PDF assinado.'
        }, status=400)

    try:
        # Remove o arquivo
        materia.pdf_assinado.delete(save=False)

        # Limpa os campos
        materia.pdf_assinado = None
        materia.assinatura_info = None
        materia.assinado_em = None
        materia.assinado_por = None
        materia.codigo_autenticacao = None
        materia.save()

        logger.info(f"Assinatura da matéria {materia.pk} removida por {request.user.username}")

        return JsonResponse({
            'success': True,
            'message': 'Assinatura removida com sucesso.'
        })

    except Exception as e:
        logger.error(f"Erro ao remover assinatura: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erro ao remover assinatura: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def detectar_aplicacao_a3(request):
    """
    Endpoint para verificar se há uma aplicação de assinatura A3 rodando localmente.
    O frontend usa isso para decidir se mostra a opção A3.
    """
    # Lista de portas comuns usadas por aplicações de assinatura
    portas_conhecidas = [
        {'nome': 'Assinador SERPRO', 'porta': 10443},
        {'nome': 'Web PKI Local', 'porta': 5000},
        {'nome': 'Signer Local', 'porta': 8080},
    ]

    return JsonResponse({
        'success': True,
        'portas_conhecidas': portas_conhecidas,
        'instrucoes': 'O frontend deve tentar conectar a cada porta para detectar a aplicação.'
    })


# =============================================================================
# Preview de página para posicionamento de assinatura
# =============================================================================

@login_required
@require_http_methods(["GET"])
def materia_pagina_assinatura_png(request, pk):
    """
    Renderiza a última página (página de autenticação) do PDF da matéria como
    PNG e retorna JSON com:
      - png_base64  : imagem da página em base64
      - page_width  : largura em pontos PDF
      - page_height : altura em pontos PDF
      - page_number : número 1-based da página
      - grid_slots  : lista de slots do grid automático [{left,bottom,width,height}]
    """
    return _pagina_assinatura_png_response(request, 'materia', pk)


@login_required
@require_http_methods(["GET"])
def docacessorio_pagina_assinatura_png(request, pk):
    """Mesmo que materia_pagina_assinatura_png, mas para DocumentoAcessório."""
    return _pagina_assinatura_png_response(request, 'docacessorio', pk)


def _pagina_assinatura_png_response(request, tipo_doc, pk):
    """Lógica comum para gerar PNG da página de autenticação."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return JsonResponse({'error': 'PyMuPDF não instalado. Instale com: pip install pymupdf'}, status=500)

    from PyPDF4 import PdfFileReader, PdfFileWriter

    # Obter PDF
    if tipo_doc == 'materia':
        obj = get_object_or_404(MateriaLegislativa, pk=pk)
        if obj.pdf_assinado:
            with open(obj.pdf_assinado.path, 'rb') as f:
                pdf_bytes = f.read()
            # PDF já tem página de autenticação — renderizar última
            build_auth = False
        else:
            pdf_bytes, error = _gerar_pdf_da_materia(obj, request)
            if error:
                return JsonResponse({'error': error}, status=400)
            build_auth = True
    else:
        obj = get_object_or_404(DocumentoAcessorio, pk=pk)
        if obj.pdf_assinado:
            with open(obj.pdf_assinado.path, 'rb') as f:
                pdf_bytes = f.read()
            build_auth = False
        else:
            pdf_bytes, error = _gerar_pdf_do_docacessorio(obj, request)
            if error:
                return JsonResponse({'error': error}, status=400)
            build_auth = True

    # Se ainda não tem página de autenticação, criar uma temporária para preview
    if build_auth:
        original_pdf = PdfFileReader(io.BytesIO(pdf_bytes))
        last_page = original_pdf.getPage(original_pdf.getNumPages() - 1)
        page_width  = float(last_page.mediaBox.getWidth())
        page_height = float(last_page.mediaBox.getHeight())
        # Gerar página de autenticação placeholder (sem código real — só visual)
        codigo_fake = 'PREVIEW-000000'
        url_fake = request.build_absolute_uri('/')
        assinaturas_existentes = _normalizar_assinatura_info(
            obj.assinatura_info if hasattr(obj, 'assinatura_info') else None
        )
        nome = request.user.get_full_name() or request.user.username
        auth_page_bytes = _gerar_pagina_autenticacao(
            [{'nome_assinante': nome, 'cargo': '—', 'data_assinatura': ''}],
            codigo_fake, url_fake, page_width, page_height
        )
        auth_pdf = PdfFileReader(io.BytesIO(auth_page_bytes))
        output = PdfFileWriter()
        for i in range(original_pdf.getNumPages()):
            output.addPage(original_pdf.getPage(i))
        output.addPage(auth_pdf.getPage(0))
        buf = io.BytesIO()
        output.write(buf)
        pdf_bytes = buf.getvalue()
    else:
        original_pdf = PdfFileReader(io.BytesIO(pdf_bytes))
        last_page = original_pdf.getPage(original_pdf.getNumPages() - 1)
        page_width  = float(last_page.mediaBox.getWidth())
        page_height = float(last_page.mediaBox.getHeight())
        assinaturas_existentes = _normalizar_assinatura_info(
            obj.assinatura_info if hasattr(obj, 'assinatura_info') else None
        )

    # Renderizar última página como PNG via PyMuPDF
    import base64
    doc_fitz = fitz.open(stream=pdf_bytes, filetype='pdf')
    page_idx = len(doc_fitz) - 1  # última página
    page_fitz = doc_fitz[page_idx]
    mat = fitz.Matrix(2.0, 2.0)  # 2x zoom → melhor qualidade
    pix = page_fitz.get_pixmap(matrix=mat, alpha=False)
    png_bytes = pix.tobytes('png')
    doc_fitz.close()

    png_b64 = base64.b64encode(png_bytes).decode('ascii')

    # Calcular slots do grid automático para mostrar no preview
    n_existentes = len(assinaturas_existentes)
    grid_slots = []
    for i in range(n_existentes + 4):  # mostra slots já usados + 4 próximos
        try:
            x1, y1, x2, y2 = _posicao_bloco_assinatura(i, page_width, page_height)
            grid_slots.append({
                'index': i,
                'left': round(x1, 2),
                'bottom': round(y1, 2),
                'width': round(x2 - x1, 2),
                'height': round(y2 - y1, 2),
                'usado': i < n_existentes,
                'sugerido': i == n_existentes,
            })
        except Exception:
            break

    return JsonResponse({
        'png_base64': png_b64,
        'page_width': round(page_width, 2),
        'page_height': round(page_height, 2),
        'page_number': page_idx + 1,
        'render_scale': 2.0,
        'grid_slots': grid_slots,
    })


@login_required
@require_http_methods(["GET"])
def assinatura_api_status(request):
    """
    Retorna o status do microserviço de assinatura e qual backend está ativo.
    Útil para diagnóstico e para o frontend exibir informações ao usuário.
    """
    from sapl.materia.assinatura_api_client import verificar_health, _api_configurada

    usa_api = _api_configurada()

    if usa_api:
        ok, mensagem = verificar_health()
        return JsonResponse({
            'backend': 'api_externa',
            'api_url': settings.ASSINATURA_API_URL,
            'disponivel': ok,
            'mensagem': mensagem,
        })
    else:
        return JsonResponse({
            'backend': 'pyhanko_local',
            'disponivel': True,
            'mensagem': 'Usando pyhanko local (ASSINATURA_API_URL não configurado).',
        })


# =============================================================================
# Views de Assinatura Digital para Documento Acessório
# =============================================================================

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def docacessorio_assinar_a1(request, pk):
    """
    Assina o PDF do documento acessório com certificado A1 (arquivo .pfx/.p12).

    Usa API externa de assinatura quando ASSINATURA_API_URL estiver configurado;
    caso contrário assina localmente com pyhanko.
    """
    docacessorio = get_object_or_404(DocumentoAcessorio, pk=pk)

    assinaturas_existentes = _normalizar_assinatura_info(docacessorio.assinatura_info)
    if any(a.get('signed_by') == request.user.username for a in assinaturas_existentes):
        return JsonResponse({'success': False, 'error': 'Você já assinou este documento.'}, status=400)

    certificado_file = request.FILES.get('certificado')
    senha = request.POST.get('senha', '')

    if not certificado_file:
        return JsonResponse({'success': False, 'error': 'Certificado não informado.'}, status=400)
    if not senha:
        return JsonResponse({'success': False, 'error': 'Senha do certificado não informada.'}, status=400)

    if docacessorio.pdf_assinado:
        with open(docacessorio.pdf_assinado.path, 'rb') as f:
            pdf_bytes = f.read()
    else:
        pdf_bytes, error = _gerar_pdf_do_docacessorio(docacessorio, request)
        if error:
            return JsonResponse({'success': False, 'error': error}, status=400)

    certificado_bytes = certificado_file.read()

    # Posição personalizada enviada pelo usuário (opcional)
    posicao_custom = _extrair_posicao_custom(request.POST)

    try:
        signed_pdf_bytes, nova_assinatura, codigo = _assinar_pdf_com_pagina_auth(
            pdf_bytes,
            request=request,
            tipo_doc='docacessorio',
            pk_doc=pk,
            assinaturas_existentes=assinaturas_existentes,
            certificado_bytes=certificado_bytes,
            senha=senha,
            tipo_cert_input='a1',
            posicao_custom=posicao_custom,
            hash_doc=docacessorio.codigo_autenticacao or '',
        )
    except ImportError:
        logger.error("pyhanko não está instalado")
        return JsonResponse({
            'success': False,
            'error': 'Biblioteca de assinatura não instalada. Contate o administrador.'
        }, status=500)
    except ErroAssinaturaUsuario as e:
        # Certificado vencido, senha incorreta: o operador resolve sozinho, então
        # a resposta é 400 com a mensagem — não 500 com o erro cru.
        logger.warning(f"Assinatura do doc acessório {pk} recusada: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)
    except Exception as e:
        logger.error(f"Erro ao assinar PDF do doc acessório {pk}: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

    filename = f"docacessorio_{docacessorio.pk}_assinado_{int(timezone.now().timestamp())}.pdf"
    docacessorio.pdf_assinado.save(filename, ContentFile(signed_pdf_bytes), save=False)

    if codigo:
        docacessorio.codigo_autenticacao = codigo

    assinaturas_existentes.append(nova_assinatura)
    docacessorio.assinatura_info = assinaturas_existentes
    docacessorio.assinado_em = timezone.now()
    docacessorio.assinado_por = request.user
    docacessorio.save()

    logger.info(
        f"Documento acessório {docacessorio.pk} assinado por {request.user.username} "
        f"(backend: {nova_assinatura.get('backend', '?')})"
    )

    return JsonResponse({
        'success': True,
        'message': 'PDF assinado com sucesso!',
        'backend': nova_assinatura.get('backend', ''),
        'certificado': {
            'nome': nova_assinatura.get('subject') or nova_assinatura.get('nome_assinante', ''),
            'validade': nova_assinatura.get('valid_to', ''),
        }
    })


@login_required
@require_http_methods(["GET"])
def docacessorio_pdf_assinado(request, pk):
    """
    Retorna o PDF assinado do documento acessório para download/visualização.
    """
    docacessorio = get_object_or_404(DocumentoAcessorio, pk=pk)

    if not docacessorio.pdf_assinado:
        messages.error(request, 'Este documento não possui PDF assinado.')
        return redirect('sapl.materia:documentoacessorio_detail',
                        pk=docacessorio.materia.pk, dpk=pk)

    try:
        with open(docacessorio.pdf_assinado.path, 'rb') as f:
            content = f.read()

        filename = f"DocAcessorio_{docacessorio.pk}_{docacessorio.nome}_ASSINADO.pdf"
        filename = filename.replace(' ', '_').replace('/', '-')

        response = HttpResponse(content, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response

    except Exception as e:
        logger.error(f"Erro ao ler PDF assinado do doc acessório: {e}")
        messages.error(request, 'Erro ao ler o arquivo PDF assinado.')
        return redirect('sapl.materia:documentoacessorio_detail',
                        pk=docacessorio.materia.pk, dpk=pk)


@login_required
@require_http_methods(["GET"])
def docacessorio_verificar_assinatura(request, pk):
    """
    Verifica a assinatura digital do PDF do documento acessório.
    """
    docacessorio = get_object_or_404(DocumentoAcessorio, pk=pk)

    if not docacessorio.pdf_assinado:
        return JsonResponse({
            'success': False,
            'error': 'Este documento não possui PDF assinado.',
            'assinado': False
        })

    try:
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko.pdf_utils.reader import PdfFileReader

        with open(docacessorio.pdf_assinado.path, 'rb') as f:
            reader = PdfFileReader(f)

            assinaturas = []

            for sig_field_name in reader.embedded_signatures:
                try:
                    sig = reader.embedded_signatures[sig_field_name]

                    sig_info = {
                        'campo': sig_field_name,
                        'assinante': str(sig.signer_cert.subject) if sig.signer_cert else 'Desconhecido',
                        'data': sig.self_reported_timestamp.isoformat() if sig.self_reported_timestamp else None,
                    }

                    assinaturas.append(sig_info)

                except Exception as sig_error:
                    logger.warning(f"Erro ao verificar assinatura {sig_field_name}: {sig_error}")
                    assinaturas.append({
                        'campo': sig_field_name,
                        'erro': str(sig_error)
                    })

            return JsonResponse({
                'success': True,
                'assinado': True,
                'total_assinaturas': len(assinaturas),
                'assinaturas': assinaturas,
                'info_salva': docacessorio.assinatura_info
            })

    except ImportError:
        return JsonResponse({
            'success': True,
            'assinado': True,
            'info_salva': docacessorio.assinatura_info,
            'verificacao_disponivel': False
        })
    except Exception as e:
        logger.error(f"Erro ao verificar assinatura do doc acessório: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erro ao verificar assinatura: {str(e)}',
            'assinado': True,
            'info_salva': docacessorio.assinatura_info
        })


@login_required
@require_http_methods(["POST"])
def docacessorio_remover_assinatura(request, pk):
    """
    Remove a assinatura digital do documento acessório.
    Requer: superusuário OU funcionalidade habilitada em AppConfig
    E permissão 'materia.can_remove_assinatura_doc'.
    """
    if not (request.user.is_superuser or (
        AppConfig.attr('permite_remover_assinatura') and
        request.user.has_perm('materia.can_remove_assinatura_doc')
    )):
        return JsonResponse({
            'success': False,
            'error': 'Você não tem permissão para remover assinaturas digitais.'
        }, status=403)

    docacessorio = get_object_or_404(DocumentoAcessorio, pk=pk)

    if not docacessorio.pdf_assinado:
        return JsonResponse({
            'success': False,
            'error': 'Este documento não possui PDF assinado.'
        }, status=400)

    try:
        docacessorio.pdf_assinado.delete(save=False)

        docacessorio.pdf_assinado = None
        docacessorio.assinatura_info = None
        docacessorio.assinado_em = None
        docacessorio.assinado_por = None
        docacessorio.codigo_autenticacao = None
        docacessorio.save()

        logger.info(f"Assinatura do doc acessório {docacessorio.pk} removida por {request.user.username}")

        return JsonResponse({
            'success': True,
            'message': 'Assinatura removida com sucesso.'
        })

    except Exception as e:
        logger.error(f"Erro ao remover assinatura do doc acessório: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erro ao remover assinatura: {str(e)}'
        }, status=500)


# =============================================================================
# Views Públicas de Verificação de Documento
# =============================================================================

@require_http_methods(["GET"])
def materia_verificar_documento(request, pk):
    """
    Página pública de verificação de autenticidade de Matéria Legislativa.
    Valida o código de autenticação e exibe status + lista de assinaturas.
    """
    materia = get_object_or_404(MateriaLegislativa, pk=pk)
    codigo_informado = request.GET.get('codigo', '').strip().upper()

    valido = (
        bool(materia.codigo_autenticacao)
        and bool(codigo_informado)
        and materia.codigo_autenticacao == codigo_informado
    )

    assinaturas = _normalizar_assinatura_info(materia.assinatura_info)
    # Filtrar campos sensíveis das assinaturas
    assinaturas_publicas = []
    for a in assinaturas:
        assinaturas_publicas.append({
            'nome_assinante': a.get('nome_assinante', ''),
            'cargo': a.get('cargo', ''),
            'data_assinatura': a.get('data_assinatura', ''),
            'tipo_certificado_display': a.get('tipo_certificado_display', a.get('tipo_certificado', '')),
        })

    context = {
        'object': materia,
        'tipo_documento': 'Matéria Legislativa',
        'descricao_documento': str(materia),
        'ementa': materia.ementa,
        'codigo_autenticacao': materia.codigo_autenticacao or '',
        'codigo_informado': codigo_informado,
        'valido': valido,
        'assinaturas': assinaturas_publicas,
        'tem_assinatura': bool(materia.pdf_assinado),
    }

    return render(request, 'materia/verificar_assinatura.html', context)


@require_http_methods(["GET"])
def docacessorio_verificar_documento(request, pk):
    """
    Página pública de verificação de autenticidade de Documento Acessório.
    Valida o código de autenticação e exibe status + lista de assinaturas.
    """
    docacessorio = get_object_or_404(DocumentoAcessorio, pk=pk)
    codigo_informado = request.GET.get('codigo', '').strip().upper()

    valido = (
        bool(docacessorio.codigo_autenticacao)
        and bool(codigo_informado)
        and docacessorio.codigo_autenticacao == codigo_informado
    )

    assinaturas = _normalizar_assinatura_info(docacessorio.assinatura_info)
    assinaturas_publicas = []
    for a in assinaturas:
        assinaturas_publicas.append({
            'nome_assinante': a.get('nome_assinante', ''),
            'cargo': a.get('cargo', ''),
            'data_assinatura': a.get('data_assinatura', ''),
            'tipo_certificado_display': a.get('tipo_certificado_display', a.get('tipo_certificado', '')),
        })

    context = {
        'object': docacessorio,
        'tipo_documento': 'Documento Acessório',
        'descricao_documento': str(docacessorio),
        'ementa': docacessorio.ementa,
        'codigo_autenticacao': docacessorio.codigo_autenticacao or '',
        'codigo_informado': codigo_informado,
        'valido': valido,
        'assinaturas': assinaturas_publicas,
        'tem_assinatura': bool(docacessorio.pdf_assinado),
        'materia': docacessorio.materia,
    }

    return render(request, 'materia/verificar_assinatura.html', context)


# =============================================================================
# Assinatura em Lote de Matérias Legislativas
# =============================================================================

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def materia_assinar_lote(request):
    """
    Assina em lote matérias pendentes com certificado A1.

    POST multipart:
      - certificado: arquivo .pfx / .p12
      - senha: senha do certificado
      - ids: JSON array com os PKs das matérias  ex: "[1,2,3]"
             OU múltiplos campos ids[] (form-data)

    Retorna JSON com resultado por matéria:
    {
        "total": 3, "sucesso": 2, "erros": 1,
        "resultados": [
            {"pk": 1, "success": true,  "descricao": "PL 1/2025"},
            {"pk": 2, "success": false, "descricao": "PL 2/2025", "error": "..."}
        ]
    }
    """
    # Permite acesso se o usuário tem permissão Django OU é OperadorAutor de algum autor
    _tem_perm_django = request.user.has_perm('materia.change_materialegislativa')
    try:
        _autor_lote = OperadorAutor.objects.get(user=request.user).autor
    except OperadorAutor.DoesNotExist:
        _autor_lote = None

    if not (_tem_perm_django or _autor_lote):
        return JsonResponse(
            {'success': False, 'error': 'Sem permissão para assinar matérias.'},
            status=403
        )

    # ── IDs das matérias ─────────────────────────────────────────────────────
    ids_raw = request.POST.get('ids', '')
    ids_multi = request.POST.getlist('ids[]')

    if ids_multi:
        pks = [int(i) for i in ids_multi if str(i).isdigit()]
    elif ids_raw:
        try:
            parsed = json.loads(ids_raw)
            pks = [int(i) for i in parsed if str(i).isdigit() or isinstance(i, int)]
        except (json.JSONDecodeError, ValueError):
            return JsonResponse(
                {'success': False, 'error': 'Parâmetro "ids" inválido. Envie um array JSON.'},
                status=400
            )
    else:
        return JsonResponse({'success': False, 'error': 'Nenhuma matéria selecionada.'}, status=400)

    if not pks:
        return JsonResponse({'success': False, 'error': 'Lista de IDs vazia.'}, status=400)

    if len(pks) > 200:
        return JsonResponse(
            {'success': False, 'error': 'Limite máximo de 200 matérias por lote.'},
            status=400
        )

    # ── Certificado ──────────────────────────────────────────────────────────
    certificado_file = request.FILES.get('certificado')
    senha = request.POST.get('senha', '')

    if not certificado_file:
        return JsonResponse({'success': False, 'error': 'Certificado não informado.'}, status=400)
    if not senha:
        return JsonResponse({'success': False, 'error': 'Senha do certificado não informada.'}, status=400)

    cert_bytes = certificado_file.read()

    # Pré-validação do certificado apenas quando pyhanko é o backend local.
    # Na API externa a validação é feita pelo microserviço.
    if not _usar_api_externa():
        import tempfile as tmp_module
        with tmp_module.NamedTemporaryFile(delete=False, suffix='.pfx') as tmp_cert:
            tmp_cert.write(cert_bytes)
            tmp_cert_path = tmp_cert.name
        try:
            from pyhanko.sign import signers as _signers_lote
            _signer_test = _signers_lote.SimpleSigner.load_pkcs12(
                pfx_file=tmp_cert_path,
                passphrase=senha.encode('utf-8')
            )
            _cert_test = _signer_test.signing_cert
            _err = _validar_certificado(_cert_test)
            if _err:
                _d = json.loads(_err.content)
                return JsonResponse({'success': False, 'error': _d.get('error', 'Certificado inválido.')}, status=400)
        except Exception as cert_error:
            logger.error(f"[lote] Erro ao carregar certificado: {cert_error}")
            err_msg = str(cert_error)
            if 'password' in err_msg.lower() or 'mac' in err_msg.lower():
                detail = 'Senha incorreta ou arquivo inválido.'
            elif 'decode' in err_msg.lower() or 'parse' in err_msg.lower():
                detail = 'Arquivo não é um certificado válido (.pfx/.p12).'
            else:
                detail = f'Detalhes: {err_msg}'
            return JsonResponse({'success': False, 'error': f'Erro ao carregar certificado: {detail}'}, status=400)
        finally:
            if os.path.exists(tmp_cert_path):
                os.unlink(tmp_cert_path)

    # ── Assinatura por matéria ────────────────────────────────────────────────
    materias = MateriaLegislativa.objects.filter(pk__in=pks)
    materias_map = {m.pk: m for m in materias}

    resultados = []
    sucesso_count = 0
    erro_count = 0

    # ── Pré-processar: gerar PDFs, filtrar inválidos ──────────────────────────
    # itens_para_assinar: apenas matérias que passaram na pré-validação
    itens_para_assinar = []   # list of dict com metadados + pdf_bytes
    meta_map = {}             # pk → {descricao, assinaturas_existentes}

    for pk in pks:
        materia = materias_map.get(pk)
        if not materia:
            resultados.append({'pk': pk, 'success': False, 'descricao': f'ID {pk}', 'error': 'Matéria não encontrada.'})
            erro_count += 1
            continue

        descricao = f'{materia.tipo.sigla} {materia.numero}/{materia.ano}'

        if materia.pdf_assinado:
            resultados.append({'pk': pk, 'success': False, 'descricao': descricao, 'error': 'Já possui PDF assinado. Ignorada.'})
            erro_count += 1
            continue

        assinaturas_existentes = _normalizar_assinatura_info(materia.assinatura_info)
        if any(a.get('signed_by') == request.user.username for a in assinaturas_existentes):
            resultados.append({'pk': pk, 'success': False, 'descricao': descricao, 'error': 'Você já assinou esta matéria.'})
            erro_count += 1
            continue

        pdf_bytes, error = _gerar_pdf_da_materia(materia, request)
        if error:
            resultados.append({'pk': pk, 'success': False, 'descricao': descricao, 'error': error})
            erro_count += 1
            continue

        meta_map[pk] = {'descricao': descricao, 'assinaturas_existentes': assinaturas_existentes}
        itens_para_assinar.append({'pk': pk, 'pdf_bytes': pdf_bytes})

    # ── Assinatura: paralela (API externa) ou sequencial (pyhanko) ────────────
    if _usar_api_externa() and itens_para_assinar:
        from sapl.materia.assinatura_api_client import assinar_pdf_lote_via_api, AssinaturaAPIError as _APIError

        # Preparar itens com página de autenticação e coordenadas
        from PyPDF4 import PdfFileReader, PdfFileWriter
        import base64 as _base64

        nome_assinante = request.user.get_full_name() or request.user.username
        cargo = 'Usuário do Sistema'
        try:
            from sapl.base.models import Autor
            from sapl.parlamentares.models import Parlamentar
            autor = Autor.objects.filter(operadores=request.user).first()
            if autor:
                tipo_desc = autor.tipo.descricao if autor.tipo else ''
                if tipo_desc == 'Parlamentar':
                    cargo = 'Vereador(a)'
                elif tipo_desc:
                    cargo = tipo_desc
                if isinstance(autor.autor_related, Parlamentar):
                    parl = autor.autor_related
                    tipo_nome = AppConfig.attr('assinatura_nome')
                    nome_assinante = parl.nome_completo if tipo_nome == 'C' else parl.nome_parlamentar
        except Exception:
            pass

        data_assinatura = timezone.localtime(timezone.now())
        data_simples = data_assinatura.strftime('%d/%m/%Y %H:%M')
        data_formatada = data_assinatura.strftime('%d/%m/%Y %H:%M:%S')

        itens_api = []
        codigos_map = {}  # pk → codigo_autenticacao

        for item in itens_para_assinar:
            pk = item['pk']
            pdf_bytes = item['pdf_bytes']
            assinaturas_existentes = meta_map[pk]['assinaturas_existentes']
            ja_tem = bool(assinaturas_existentes)

            if not ja_tem:
                # Composição local, documento por documento — é o que torna o
                # /sign/batch utilizável: ele só carimba. Mesmo helper do caminho
                # individual local, para não existir um terceiro compositor.
                pdf_para_assinar, codigo = _compor_pagina_auth_localmente(
                    pdf_bytes, request, 'materia', pk,
                    [{
                        'nome_assinante': nome_assinante,
                        'cargo': cargo,
                        'data_assinatura': data_simples,
                    }],
                )
                codigos_map[pk] = codigo
            else:
                pdf_para_assinar = pdf_bytes

            n_assinatura = len(assinaturas_existentes)
            try:
                temp_pdf = PdfFileReader(io.BytesIO(pdf_para_assinar))
                auth_pg = temp_pdf.getPage(temp_pdf.getNumPages() - 1)
                auth_w = float(auth_pg.mediaBox.getWidth())
                auth_h = float(auth_pg.mediaBox.getHeight())
                x1, y1, x2, y2 = _posicao_bloco_assinatura(n_assinatura, auth_w, auth_h)
                sig_page = temp_pdf.getNumPages()
                sig_left, sig_bottom = x1, y1
                sig_width, sig_height = x2 - x1, y2 - y1
            except Exception:
                sig_page = sig_left = sig_bottom = sig_width = sig_height = None

            itens_api.append({
                'id': pk,
                'pdf_bytes': pdf_para_assinar,
                'signature_page': sig_page,
                'signature_left': sig_left,
                'signature_bottom': sig_bottom,
                'signature_width': sig_width,
                'signature_height': sig_height,
            })

        logger.info(f'[lote] Enviando {len(itens_api)} PDFs em paralelo para API externa...')
        resultados_api = assinar_pdf_lote_via_api(
            itens_api,
            certificado_bytes=cert_bytes,
            senha=senha,
            reason='Documento assinado digitalmente nos termos da MP 2.200-2/2001',
            location='Câmara Municipal',
        )

        for res_api in resultados_api:
            pk = res_api['id']
            materia = materias_map[pk]
            descricao = meta_map[pk]['descricao']
            assinaturas_existentes = meta_map[pk]['assinaturas_existentes']

            if not res_api['ok']:
                logger.error(f'[lote] Matéria {pk} falhou: {res_api["error"]}')
                resultados.append({'pk': pk, 'success': False, 'descricao': descricao, 'error': res_api['error']})
                erro_count += 1
                continue

            nova_assinatura = {
                'tipo_certificado': 'A1',
                'tipo_certificado_display': 'Certificado Digital – A1',
                'subject': '', 'issuer': '', 'serial': '',
                'valid_from': '', 'valid_to': '',
                'signed_by': request.user.username,
                'nome_assinante': nome_assinante,
                'cargo': cargo,
                'data_assinatura': data_formatada,
                'validade_juridica': 'Assinatura Eletrônica Qualificada',
                'backend': 'api_externa',
            }

            filename = f"materia_{pk}_assinado_{int(timezone.now().timestamp())}.pdf"
            materia.pdf_assinado.save(filename, ContentFile(res_api['pdf_bytes']), save=False)
            if pk in codigos_map:
                materia.codigo_autenticacao = codigos_map[pk]
            assinaturas_existentes.append(nova_assinatura)
            materia.assinatura_info = assinaturas_existentes
            materia.assinado_em = timezone.now()
            materia.assinado_por = request.user
            materia.save()

            logger.info(f'[lote] Matéria {pk} assinada por {request.user.username} (api_externa/paralelo)')
            resultados.append({'pk': pk, 'success': True, 'descricao': descricao})
            sucesso_count += 1

    else:
        # Backend local: pyhanko — sequencial
        for item in itens_para_assinar:
            pk = item['pk']
            materia = materias_map[pk]
            descricao = meta_map[pk]['descricao']
            assinaturas_existentes = meta_map[pk]['assinaturas_existentes']
            pdf_bytes = item['pdf_bytes']

            try:
                signed_pdf_bytes, nova_assinatura, codigo = _assinar_pdf_com_pagina_auth(
                    pdf_bytes,
                    request=request,
                    tipo_doc='materia',
                    pk_doc=pk,
                    assinaturas_existentes=assinaturas_existentes,
                    certificado_bytes=cert_bytes,
                    senha=senha,
                    tipo_cert_input='a1',
                    hash_doc=materia.codigo_autenticacao or '',
                )

                filename = f"materia_{materia.pk}_assinado_{int(timezone.now().timestamp())}.pdf"
                materia.pdf_assinado.save(filename, ContentFile(signed_pdf_bytes), save=False)
                if codigo:
                    materia.codigo_autenticacao = codigo

                assinaturas_existentes.append(nova_assinatura)
                materia.assinatura_info = assinaturas_existentes
                materia.assinado_em = timezone.now()
                materia.assinado_por = request.user
                materia.save()

                logger.info(
                    f"[lote] Matéria {pk} assinada por {request.user.username} "
                    f"(backend: {nova_assinatura.get('backend', '?')})"
                )
                resultados.append({'pk': pk, 'success': True, 'descricao': descricao})
                sucesso_count += 1

            except Exception as e:
                logger.error(f"[lote] Erro ao assinar matéria {pk}: {e}")
                resultados.append({'pk': pk, 'success': False, 'descricao': descricao, 'error': str(e)})
                erro_count += 1

    # Invalida cache de pendências uma vez ao final do lote — de quem assinou
    # e dos coautores de cada matéria assinada.
    if sucesso_count > 0:
        from sapl.materia.pendencias import invalidar_cache_pendencias
        for r in resultados:
            if r.get('success'):
                invalidar_cache_pendencias(materia=materias_map.get(r['pk']))
        invalidar_cache_pendencias(user=request.user)

    return JsonResponse({
        'success': True,
        'total': len(pks),
        'sucesso': sucesso_count,
        'erros': erro_count,
        'resultados': resultados,
    })


# =============================================================================
# Assinatura em Lote de Documentos Acessórios
# =============================================================================

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def docacessorio_assinar_lote(request):
    """
    Assina em lote documentos acessórios pendentes com certificado A1.

    POST multipart:
      - certificado: arquivo .pfx / .p12
      - senha: senha do certificado
      - ids: JSON array com os PKs dos documentos acessórios  ex: "[1,2,3]"

    Retorna JSON:
    {
        "total": 3, "sucesso": 2, "erros": 1,
        "resultados": [
            {"pk": 1, "success": true,  "descricao": "Despacho - PL 1/2025"},
            {"pk": 2, "success": false, "descricao": "...", "error": "..."}
        ]
    }
    """
    _tem_perm_django = request.user.has_perm('materia.change_documentoacessorio')
    try:
        _autor_lote = OperadorAutor.objects.get(user=request.user).autor
    except OperadorAutor.DoesNotExist:
        _autor_lote = None

    if not (_tem_perm_django or _autor_lote or request.user.is_superuser):
        return JsonResponse(
            {'success': False, 'error': 'Sem permissao para assinar documentos acessorios.'},
            status=403
        )

    # -- IDs dos documentos --
    ids_raw = request.POST.get('ids', '')
    ids_multi = request.POST.getlist('ids[]')

    if ids_multi:
        pks = [int(i) for i in ids_multi if str(i).isdigit()]
    elif ids_raw:
        try:
            parsed = json.loads(ids_raw)
            pks = [int(i) for i in parsed if str(i).isdigit() or isinstance(i, int)]
        except (json.JSONDecodeError, ValueError):
            return JsonResponse(
                {'success': False, 'error': 'Parametro "ids" invalido. Envie um array JSON.'},
                status=400
            )
    else:
        return JsonResponse({'success': False, 'error': 'Nenhum documento selecionado.'}, status=400)

    if not pks:
        return JsonResponse({'success': False, 'error': 'Lista de IDs vazia.'}, status=400)

    if len(pks) > 200:
        return JsonResponse(
            {'success': False, 'error': 'Limite maximo de 200 documentos por lote.'},
            status=400
        )

    # -- Certificado --
    certificado_file = request.FILES.get('certificado')
    senha = request.POST.get('senha', '')

    if not certificado_file:
        return JsonResponse({'success': False, 'error': 'Certificado nao informado.'}, status=400)
    if not senha:
        return JsonResponse({'success': False, 'error': 'Senha do certificado nao informada.'}, status=400)

    cert_bytes = certificado_file.read()

    # Pré-validação do certificado apenas no backend local (pyhanko).
    if not _usar_api_externa():
        import tempfile as tmp_module
        with tmp_module.NamedTemporaryFile(delete=False, suffix='.pfx') as tmp_cert:
            tmp_cert.write(cert_bytes)
            tmp_cert_path = tmp_cert.name
        try:
            from pyhanko.sign import signers as _signers_lote
            _signer_test = _signers_lote.SimpleSigner.load_pkcs12(
                pfx_file=tmp_cert_path,
                passphrase=senha.encode('utf-8')
            )
            _cert_test = _signer_test.signing_cert
            _err = _validar_certificado(_cert_test)
            if _err:
                _d = json.loads(_err.content)
                return JsonResponse({'success': False, 'error': _d.get('error', 'Certificado inválido.')}, status=400)
        except Exception as cert_error:
            logger.error(f"[lote-doc] Erro ao carregar certificado: {cert_error}")
            err_msg = str(cert_error)
            if 'password' in err_msg.lower() or 'mac' in err_msg.lower():
                detail = 'Senha incorreta ou arquivo invalido.'
            elif 'decode' in err_msg.lower() or 'parse' in err_msg.lower():
                detail = 'Arquivo nao e um certificado valido (.pfx/.p12).'
            else:
                detail = f'Detalhes: {err_msg}'
            return JsonResponse({'success': False, 'error': f'Erro ao carregar certificado: {detail}'}, status=400)
        finally:
            if os.path.exists(tmp_cert_path):
                os.unlink(tmp_cert_path)

    # -- Pré-processar: gerar PDFs, filtrar inválidos --
    docs = DocumentoAcessorio.objects.filter(pk__in=pks).select_related('materia', 'tipo', 'materia__tipo')
    docs_map = {d.pk: d for d in docs}

    resultados = []
    sucesso_count = 0
    erro_count = 0

    itens_para_assinar = []
    meta_map_doc = {}  # pk → {descricao, assinaturas_existentes}

    for pk in pks:
        doc = docs_map.get(pk)
        if not doc:
            resultados.append({'pk': pk, 'success': False, 'descricao': f'ID {pk}', 'error': 'Documento nao encontrado.'})
            erro_count += 1
            continue

        descricao = f'{doc.nome} - {doc.materia.tipo.sigla} {doc.materia.numero}/{doc.materia.ano}'

        if doc.pdf_assinado:
            resultados.append({'pk': pk, 'success': False, 'descricao': descricao, 'error': 'Ja possui PDF assinado. Ignorado.'})
            erro_count += 1
            continue

        assinaturas_existentes = _normalizar_assinatura_info(doc.assinatura_info)
        if any(a.get('signed_by') == request.user.username for a in assinaturas_existentes):
            resultados.append({'pk': pk, 'success': False, 'descricao': descricao, 'error': 'Voce ja assinou este documento.'})
            erro_count += 1
            continue

        pdf_bytes, error = _gerar_pdf_do_docacessorio(doc, request)
        if error:
            resultados.append({'pk': pk, 'success': False, 'descricao': descricao, 'error': error})
            erro_count += 1
            continue

        meta_map_doc[pk] = {'descricao': descricao, 'assinaturas_existentes': assinaturas_existentes}
        itens_para_assinar.append({'pk': pk, 'pdf_bytes': pdf_bytes})

    # -- Assinatura: /sign/batch (API externa) ou sequencial (pyhanko) --
    if _usar_api_externa() and itens_para_assinar:
        from sapl.materia.assinatura_api_client import assinar_pdf_lote_via_api, AssinaturaAPIError as _APIError
        from PyPDF4 import PdfFileReader, PdfFileWriter

        nome_assinante = request.user.get_full_name() or request.user.username
        cargo = 'Usuário do Sistema'
        try:
            from sapl.base.models import Autor
            from sapl.parlamentares.models import Parlamentar
            autor = Autor.objects.filter(operadores=request.user).first()
            if autor:
                tipo_desc = autor.tipo.descricao if autor.tipo else ''
                if tipo_desc == 'Parlamentar':
                    cargo = 'Vereador(a)'
                elif tipo_desc:
                    cargo = tipo_desc
                if isinstance(autor.autor_related, Parlamentar):
                    parl = autor.autor_related
                    tipo_nome = AppConfig.attr('assinatura_nome')
                    nome_assinante = parl.nome_completo if tipo_nome == 'C' else parl.nome_parlamentar
        except Exception:
            pass

        data_assinatura = timezone.localtime(timezone.now())
        data_simples = data_assinatura.strftime('%d/%m/%Y %H:%M')
        data_formatada = data_assinatura.strftime('%d/%m/%Y %H:%M:%S')

        itens_api = []
        codigos_map = {}

        for item in itens_para_assinar:
            pk = item['pk']
            pdf_bytes = item['pdf_bytes']
            assinaturas_existentes = meta_map_doc[pk]['assinaturas_existentes']
            ja_tem = bool(assinaturas_existentes)

            if not ja_tem:
                # Mesma composição local do lote de matéria e do caminho
                # individual local — um compositor só (ver _compor_pagina_auth_localmente).
                pdf_para_assinar, codigo = _compor_pagina_auth_localmente(
                    pdf_bytes, request, 'docacessorio', pk,
                    [{
                        'nome_assinante': nome_assinante,
                        'cargo': cargo,
                        'data_assinatura': data_simples,
                    }],
                )
                codigos_map[pk] = codigo
            else:
                pdf_para_assinar = pdf_bytes

            n_assinatura = len(assinaturas_existentes)
            try:
                temp_pdf = PdfFileReader(io.BytesIO(pdf_para_assinar))
                auth_pg = temp_pdf.getPage(temp_pdf.getNumPages() - 1)
                auth_w = float(auth_pg.mediaBox.getWidth())
                auth_h = float(auth_pg.mediaBox.getHeight())
                x1, y1, x2, y2 = _posicao_bloco_assinatura(n_assinatura, auth_w, auth_h)
                sig_page = temp_pdf.getNumPages()
                sig_left, sig_bottom = x1, y1
                sig_width, sig_height = x2 - x1, y2 - y1
            except Exception:
                sig_page = sig_left = sig_bottom = sig_width = sig_height = None

            itens_api.append({
                'id': pk,
                'pdf_bytes': pdf_para_assinar,
                'signature_page': sig_page,
                'signature_left': sig_left,
                'signature_bottom': sig_bottom,
                'signature_width': sig_width,
                'signature_height': sig_height,
            })

        logger.info(f'[lote-doc] Enviando {len(itens_api)} PDFs em batch para API externa...')
        resultados_api = assinar_pdf_lote_via_api(
            itens_api,
            certificado_bytes=cert_bytes,
            senha=senha,
            reason='Documento assinado digitalmente nos termos da MP 2.200-2/2001',
            location='Câmara Municipal',
        )

        for res_api in resultados_api:
            pk = res_api['id']
            doc = docs_map[pk]
            descricao = meta_map_doc[pk]['descricao']
            assinaturas_existentes = meta_map_doc[pk]['assinaturas_existentes']

            if not res_api['ok']:
                logger.error(f'[lote-doc] Doc {pk} falhou: {res_api["error"]}')
                resultados.append({'pk': pk, 'success': False, 'descricao': descricao, 'error': res_api['error']})
                erro_count += 1
                continue

            nova_assinatura = {
                'tipo_certificado': 'A1',
                'tipo_certificado_display': 'Certificado Digital – A1',
                'subject': '', 'issuer': '', 'serial': '',
                'valid_from': '', 'valid_to': '',
                'signed_by': request.user.username,
                'nome_assinante': nome_assinante,
                'cargo': cargo,
                'data_assinatura': data_formatada,
                'validade_juridica': 'Assinatura Eletrônica Qualificada',
                'backend': 'api_externa',
            }
            filename = f"docacessorio_{pk}_assinado_{int(timezone.now().timestamp())}.pdf"
            doc.pdf_assinado.save(filename, ContentFile(res_api['pdf_bytes']), save=False)
            if pk in codigos_map:
                doc.codigo_autenticacao = codigos_map[pk]
            assinaturas_existentes.append(nova_assinatura)
            doc.assinatura_info = assinaturas_existentes
            doc.assinado_em = timezone.now()
            doc.assinado_por = request.user
            doc.save()

            logger.info(f'[lote-doc] DocAcessorio {pk} assinado por {request.user.username} (api_externa/batch)')
            resultados.append({'pk': pk, 'success': True, 'descricao': descricao})
            sucesso_count += 1

    else:
        # Backend local: pyhanko — sequencial
        for item in itens_para_assinar:
            pk = item['pk']
            doc = docs_map[pk]
            descricao = meta_map_doc[pk]['descricao']
            assinaturas_existentes = meta_map_doc[pk]['assinaturas_existentes']
            pdf_bytes = item['pdf_bytes']

            try:
                signed_pdf_bytes, nova_assinatura, codigo = _assinar_pdf_com_pagina_auth(
                    pdf_bytes,
                    request=request,
                    tipo_doc='docacessorio',
                    pk_doc=pk,
                    assinaturas_existentes=assinaturas_existentes,
                    certificado_bytes=cert_bytes,
                    senha=senha,
                    tipo_cert_input='a1',
                    hash_doc=doc.codigo_autenticacao or '',
                )

                filename = f"docacessorio_{doc.pk}_assinado_{int(timezone.now().timestamp())}.pdf"
                doc.pdf_assinado.save(filename, ContentFile(signed_pdf_bytes), save=False)
                if codigo:
                    doc.codigo_autenticacao = codigo

                assinaturas_existentes.append(nova_assinatura)
                doc.assinatura_info = assinaturas_existentes
                doc.assinado_em = timezone.now()
                doc.assinado_por = request.user
                doc.save()

                logger.info(
                    f"[lote-doc] DocAcessorio {pk} assinado por {request.user.username} "
                    f"(backend: {nova_assinatura.get('backend', '?')})"
                )
                resultados.append({'pk': pk, 'success': True, 'descricao': descricao})
                sucesso_count += 1

            except Exception as e:
                logger.error(f"[lote-doc] Erro ao assinar docacessorio {pk}: {e}")
                resultados.append({'pk': pk, 'success': False, 'descricao': descricao, 'error': str(e)})
                erro_count += 1

    return JsonResponse({
        'success': True,
        'total': len(pks),
        'sucesso': sucesso_count,
        'erros': erro_count,
        'resultados': resultados,
    })


# (função docacessorio_assinar_lote definida acima)

