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

from sapl.base.models import AppConfig
from sapl.materia.models import DocumentoAcessorio, MateriaLegislativa
from sapl.utils import build_onlyoffice_url

logger = logging.getLogger(__name__)


def _normalizar_assinatura_info(info):
    """Converte assinatura_info legado (dict) para lista de dicts."""
    if info is None:
        return []
    if isinstance(info, dict):
        return [info]
    return info


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


def _construir_url_verificacao(request, tipo, pk, codigo):
    """Monta URL pública de verificação."""
    if tipo == 'materia':
        url_name = 'sapl.materia:materia_verificar_documento'
    else:
        url_name = 'sapl.materia:docacessorio_verificar_documento'

    base_url = request.build_absolute_uri(
        reverse(url_name, kwargs={'pk': pk})
    )
    return f'{base_url}?codigo={codigo}'


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
            name='/Helvetica', avg_width=0.5
        )
    except (ImportError, Exception):
        pass  # Usa fonte padrão se Helvetica não disponível

    return TextStampStyle(
        stamp_text='\n'.join(linhas),
        text_box_style=TextBoxStyle(
            font_size=7,
            leading=10,
            border_width=1,
            **font_kwargs,
        ),
        border_width=0,
        background=None,
        background_opacity=0,
        timestamp_format='%d/%m/%Y %H:%M',
    )


def _obter_info_assinante(request, cert_info):
    """
    Obtém informações do assinante (nome, cargo, tipo_cert).
    Busca via Autor.operadores → Parlamentar (GenericFK).
    Retorna (nome_assinante, cargo, tipo_cert).
    """
    nome_assinante = request.user.get_full_name() or request.user.username
    cargo = "Usuário do Sistema"

    try:
        from sapl.base.models import Autor
        from sapl.parlamentares.models import Parlamentar

        autor = Autor.objects.filter(operadores=request.user).first()
        if autor:
            # Usa tipo do autor como cargo (ex: "Parlamentar" → "Vereador(a)")
            tipo_descricao = autor.tipo.descricao if autor.tipo else ''
            if tipo_descricao == 'Parlamentar':
                cargo = "Vereador(a)"
            elif tipo_descricao:
                cargo = tipo_descricao

            # Se o autor está vinculado a um Parlamentar, usa o nome dele
            if isinstance(autor.autor_related, Parlamentar):
                parlamentar = autor.autor_related
                tipo_nome = AppConfig.attr('assinatura_nome')
                if tipo_nome == 'C':
                    nome_assinante = parlamentar.nome_completo
                else:
                    nome_assinante = parlamentar.nome_parlamentar
    except Exception:
        pass

    issuer_str = str(cert_info.issuer).upper()
    if 'ICP-BRASIL' in issuer_str or 'ICP BRASIL' in issuer_str:
        tipo_cert = "ICP-Brasil"
    else:
        tipo_cert = "Certificado Digital"

    return nome_assinante, cargo, tipo_cert


def _carregar_certificado(certificado_file, senha):
    """
    Carrega certificado PKCS12 de um arquivo.
    Retorna (signer, error_response) — se error_response não é None, retornar direto.
    """
    from pyhanko.sign import signers

    cert_data = certificado_file.read()

    import tempfile as tmp_module
    with tmp_module.NamedTemporaryFile(delete=False, suffix='.pfx') as tmp_cert:
        tmp_cert.write(cert_data)
        tmp_cert_path = tmp_cert.name

    try:
        signer = signers.SimpleSigner.load_pkcs12(
            pfx_file=tmp_cert_path,
            passphrase=senha.encode('utf-8')
        )
        if os.path.exists(tmp_cert_path):
            os.unlink(tmp_cert_path)
    except Exception as cert_error:
        logger.error(f"Erro ao carregar certificado: {cert_error}")
        if os.path.exists(tmp_cert_path):
            os.unlink(tmp_cert_path)
        error_msg = str(cert_error)
        if 'password' in error_msg.lower() or 'mac' in error_msg.lower():
            error_detail = 'Senha incorreta.'
        elif 'decode' in error_msg.lower() or 'parse' in error_msg.lower():
            error_detail = 'Arquivo não é um certificado válido (.pfx/.p12).'
        else:
            error_detail = f'Detalhes: {error_msg}'
        return None, JsonResponse({
            'success': False,
            'error': f'Erro ao carregar certificado: {error_detail}'
        }, status=400)

    if signer is None:
        return None, JsonResponse({
            'success': False,
            'error': 'Não foi possível carregar o certificado. Verifique se o arquivo .pfx/.p12 é válido e contém uma chave de assinatura.'
        }, status=400)

    return signer, None


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

    Parâmetros POST:
    - certificado: arquivo .pfx ou .p12
    - senha: senha do certificado
    """
    materia = get_object_or_404(MateriaLegislativa, pk=pk)

    # Verifica se o usuário atual já assinou
    assinaturas_existentes = _normalizar_assinatura_info(materia.assinatura_info)
    if any(a.get('signed_by') == request.user.username for a in assinaturas_existentes):
        return JsonResponse({
            'success': False,
            'error': 'Você já assinou esta matéria.'
        }, status=400)

    ja_tem_pdf_assinado = bool(materia.pdf_assinado)

    # Obtém dados do formulário
    certificado_file = request.FILES.get('certificado')
    senha = request.POST.get('senha', '')

    if not certificado_file:
        return JsonResponse({
            'success': False,
            'error': 'Certificado não informado.'
        }, status=400)

    if not senha:
        return JsonResponse({
            'success': False,
            'error': 'Senha do certificado não informada.'
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

        signer, error_response = _carregar_certificado(certificado_file, senha)
        if error_response:
            return error_response

        cert_info = signer.signing_cert
        error_response = _validar_certificado(cert_info)
        if error_response:
            return error_response

        # Cria arquivo temporário para o PDF com página de autenticação
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_stamped:
            temp_stamped_path = temp_stamped.name

        try:
            from pyhanko.sign.fields import SigFieldSpec
            from PyPDF4 import PdfFileReader, PdfFileWriter
            from reportlab.lib.units import mm

            # Informações do assinante
            nome_assinante, cargo, tipo_cert = _obter_info_assinante(request, cert_info)
            data_assinatura = timezone.localtime(timezone.now())
            data_formatada = data_assinatura.strftime('%d/%m/%Y %H:%M:%S')
            data_simples = data_assinatura.strftime('%d/%m/%Y %H:%M')

            # Número da assinatura (0-indexed)
            n_assinatura = len(assinaturas_existentes)
            sig_field_name = f'AssinaturaDigital_{n_assinatura + 1}' if n_assinatura > 0 else 'AssinaturaDigital'

            if ja_tem_pdf_assinado:
                # ===== ASSINATURA SUBSEQUENTE: Incremental sobre PDF já assinado =====
                # A página de autenticação já existe (criada na 1ª assinatura).
                # Posicionar campo de assinatura na última página (autenticação).

                with open(materia.pdf_assinado.path, 'rb') as f:
                    existing_pdf_bytes = f.read()

                # Calcular posição do campo de assinatura na página de autenticação
                # Usa o mesmo grid da página gerada na primeira assinatura
                temp_pypdf = PdfFileReader(io.BytesIO(existing_pdf_bytes))
                auth_page = temp_pypdf.getPage(temp_pypdf.getNumPages() - 1)
                auth_page_width = float(auth_page.mediaBox.getWidth())
                auth_page_height = float(auth_page.mediaBox.getHeight())

                x1, y1, x2, y2 = _posicao_bloco_assinatura(
                    n_assinatura, auth_page_width, auth_page_height
                )

                signed_buffer = io.BytesIO()
                with io.BytesIO(existing_pdf_bytes) as inf:
                    w = IncrementalPdfFileWriter(inf)

                    # Determina a última página
                    from pyhanko.pdf_utils.reader import PdfFileReader as PyhankoReader
                    from pyhanko.sign.signers.pdf_signer import PdfSigner
                    temp_reader = PyhankoReader(io.BytesIO(existing_pdf_bytes))
                    last_page_idx = temp_reader.root['/Pages']['/Count'] - 1

                    # Adiciona campo de assinatura com posição visual
                    sig_field = SigFieldSpec(
                        sig_field_name=sig_field_name,
                        on_page=last_page_idx,
                        box=(x1, y1, x2, y2)
                    )
                    fields.append_signature_field(w, sig_field)

                    meta = signers.PdfSignatureMetadata(
                        field_name=sig_field_name,
                        location='Câmara Municipal',
                        reason='Documento assinado digitalmente nos termos da MP 2.200-2/2001',
                        name=nome_assinante
                    )

                    # Usa PdfSigner com stamp_style customizado para
                    # manter visual consistente com a página de autenticação
                    hash_doc = materia.codigo_autenticacao or ''
                    stamp_style = _criar_stamp_style(
                        nome_assinante, cargo, hash_doc
                    )
                    pdf_signer = PdfSigner(
                        meta,
                        signer=signer,
                        stamp_style=stamp_style,
                    )
                    pdf_signer.sign_pdf(
                        w,
                        existing_fields_only=True,
                        appearance_text_params={'signer': nome_assinante},
                        output=signed_buffer,
                    )

                signed_buffer.seek(0)
                signed_pdf_content = signed_buffer.read()

            else:
                # ===== PRIMEIRA ASSINATURA: Página de autenticação + pyhanko sign =====

                # Lê o PDF original para obter as dimensões
                original_pdf = PdfFileReader(io.BytesIO(pdf_bytes))
                last_page = original_pdf.getPage(original_pdf.getNumPages() - 1)
                page_box = last_page.mediaBox
                page_width = float(page_box.getWidth())
                page_height = float(page_box.getHeight())

                # Gerar código de autenticação
                codigo = _gerar_codigo_autenticacao(pdf_bytes)

                # Construir URL de verificação
                url_verificacao = _construir_url_verificacao(
                    request, 'materia', pk, codigo
                )

                # Nova assinatura info (para incluir na página de autenticação)
                nova_assinatura_info = {
                    'nome_assinante': nome_assinante,
                    'cargo': cargo,
                    'data_assinatura': data_simples,
                }

                # Gerar a página de autenticação
                auth_page_bytes = _gerar_pagina_autenticacao(
                    [nova_assinatura_info],
                    codigo, url_verificacao,
                    page_width, page_height
                )

                # Montar PDF: original + página de autenticação
                auth_page_pdf = PdfFileReader(io.BytesIO(auth_page_bytes))
                output_pdf = PdfFileWriter()

                for page_num in range(original_pdf.getNumPages()):
                    output_pdf.addPage(original_pdf.getPage(page_num))

                # Anexar página de autenticação
                output_pdf.addPage(auth_page_pdf.getPage(0))

                # Salvar em arquivo temporário
                with open(temp_stamped_path, 'wb') as f:
                    output_pdf.write(f)

                # Assinar o PDF combinado
                with open(temp_stamped_path, 'rb') as stamped_file:
                    stamped_bytes = stamped_file.read()

                signed_buffer = io.BytesIO()
                with io.BytesIO(stamped_bytes) as inf:
                    w = IncrementalPdfFileWriter(inf)

                    meta = signers.PdfSignatureMetadata(
                        field_name='AssinaturaDigital',
                        location='Câmara Municipal',
                        reason='Documento assinado digitalmente nos termos da MP 2.200-2/2001',
                        name=nome_assinante
                    )

                    signers.sign_pdf(
                        w,
                        meta,
                        signer=signer,
                        output=signed_buffer
                    )

                signed_buffer.seek(0)
                signed_pdf_content = signed_buffer.read()

                # Salvar código de autenticação
                materia.codigo_autenticacao = codigo

            # Salva o PDF assinado no modelo
            filename = f"materia_{materia.pk}_assinado_{int(timezone.now().timestamp())}.pdf"
            materia.pdf_assinado.save(filename, ContentFile(signed_pdf_content), save=False)

            # Salva informações da assinatura (lista de dicts)
            nova_assinatura = {
                'tipo_certificado': 'A1',
                'tipo_certificado_display': f'{tipo_cert} – A1',
                'subject': str(cert_info.subject),
                'issuer': str(cert_info.issuer),
                'serial': str(cert_info.serial_number),
                'valid_from': cert_info.not_valid_before.isoformat(),
                'valid_to': cert_info.not_valid_after.isoformat(),
                'signed_by': request.user.username,
                'nome_assinante': nome_assinante,
                'cargo': cargo,
                'data_assinatura': data_formatada,
                'validade_juridica': 'Assinatura Eletrônica Qualificada'
            }
            assinaturas_existentes.append(nova_assinatura)
            materia.assinatura_info = assinaturas_existentes
            materia.assinado_em = timezone.now()
            materia.assinado_por = request.user
            materia.save()

            logger.info(f"Matéria {materia.pk} assinada por {request.user.username}")

            return JsonResponse({
                'success': True,
                'message': 'PDF assinado com sucesso!',
                'certificado': {
                    'nome': str(cert_info.subject),
                    'validade': cert_info.not_valid_after.strftime('%d/%m/%Y')
                }
            })

        finally:
            # Remove arquivo temporário
            if os.path.exists(temp_stamped_path):
                os.unlink(temp_stamped_path)

    except ImportError:
        logger.error("pyhanko não está instalado")
        return JsonResponse({
            'success': False,
            'error': 'Biblioteca de assinatura não instalada. Contate o administrador.'
        }, status=500)
    except Exception as e:
        logger.error(f"Erro ao assinar PDF: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erro ao assinar o PDF: {str(e)}'
        }, status=500)


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
                    location='Câmara Municipal',
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
    Apenas superusuários podem executar esta ação.
    """
    if not request.user.is_superuser:
        return JsonResponse({
            'success': False,
            'error': 'Apenas administradores podem remover assinaturas.'
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
# Views de Assinatura Digital para Documento Acessório
# =============================================================================

@login_required
@csrf_exempt
@require_http_methods(["POST"])
def docacessorio_assinar_a1(request, pk):
    """
    Assina o PDF do documento acessório com certificado A1 (arquivo .pfx/.p12).
    """
    docacessorio = get_object_or_404(DocumentoAcessorio, pk=pk)

    # Verifica se o usuário atual já assinou
    assinaturas_existentes = _normalizar_assinatura_info(docacessorio.assinatura_info)
    if any(a.get('signed_by') == request.user.username for a in assinaturas_existentes):
        return JsonResponse({
            'success': False,
            'error': 'Você já assinou este documento.'
        }, status=400)

    ja_tem_pdf_assinado = bool(docacessorio.pdf_assinado)

    certificado_file = request.FILES.get('certificado')
    senha = request.POST.get('senha', '')

    if not certificado_file:
        return JsonResponse({
            'success': False,
            'error': 'Certificado não informado.'
        }, status=400)

    if not senha:
        return JsonResponse({
            'success': False,
            'error': 'Senha do certificado não informada.'
        }, status=400)

    pdf_bytes, error = _gerar_pdf_do_docacessorio(docacessorio, request)
    if error:
        return JsonResponse({
            'success': False,
            'error': error
        }, status=400)

    try:
        from pyhanko.sign import signers, fields
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

        signer, error_response = _carregar_certificado(certificado_file, senha)
        if error_response:
            return error_response

        cert_info = signer.signing_cert
        error_response = _validar_certificado(cert_info)
        if error_response:
            return error_response

        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_stamped:
            temp_stamped_path = temp_stamped.name

        try:
            from pyhanko.sign.fields import SigFieldSpec
            from PyPDF4 import PdfFileReader, PdfFileWriter
            from reportlab.lib.units import mm

            nome_assinante, cargo, tipo_cert = _obter_info_assinante(request, cert_info)
            data_assinatura = timezone.localtime(timezone.now())
            data_formatada = data_assinatura.strftime('%d/%m/%Y %H:%M:%S')
            data_simples = data_assinatura.strftime('%d/%m/%Y %H:%M')

            # Número da assinatura (0-indexed)
            n_assinatura = len(assinaturas_existentes)
            sig_field_name = f'AssinaturaDigital_{n_assinatura + 1}' if n_assinatura > 0 else 'AssinaturaDigital'

            if ja_tem_pdf_assinado:
                # ===== ASSINATURA SUBSEQUENTE =====

                with open(docacessorio.pdf_assinado.path, 'rb') as f:
                    existing_pdf_bytes = f.read()

                # Calcular posição na página de autenticação
                # Usa o mesmo grid da página gerada na primeira assinatura
                temp_pypdf = PdfFileReader(io.BytesIO(existing_pdf_bytes))
                auth_page = temp_pypdf.getPage(temp_pypdf.getNumPages() - 1)
                auth_page_width = float(auth_page.mediaBox.getWidth())
                auth_page_height = float(auth_page.mediaBox.getHeight())

                x1, y1, x2, y2 = _posicao_bloco_assinatura(
                    n_assinatura, auth_page_width, auth_page_height
                )

                signed_buffer = io.BytesIO()
                with io.BytesIO(existing_pdf_bytes) as inf:
                    w = IncrementalPdfFileWriter(inf)

                    from pyhanko.pdf_utils.reader import PdfFileReader as PyhankoReader
                    from pyhanko.sign.signers.pdf_signer import PdfSigner
                    temp_reader = PyhankoReader(io.BytesIO(existing_pdf_bytes))
                    last_page_idx = temp_reader.root['/Pages']['/Count'] - 1

                    sig_field = SigFieldSpec(
                        sig_field_name=sig_field_name,
                        on_page=last_page_idx,
                        box=(x1, y1, x2, y2)
                    )
                    fields.append_signature_field(w, sig_field)

                    meta = signers.PdfSignatureMetadata(
                        field_name=sig_field_name,
                        location='Câmara Municipal',
                        reason='Documento assinado digitalmente nos termos da MP 2.200-2/2001',
                        name=nome_assinante
                    )

                    # Usa PdfSigner com stamp_style customizado para
                    # manter visual consistente com a página de autenticação
                    hash_doc = docacessorio.codigo_autenticacao or ''
                    stamp_style = _criar_stamp_style(
                        nome_assinante, cargo, hash_doc
                    )
                    pdf_signer = PdfSigner(
                        meta,
                        signer=signer,
                        stamp_style=stamp_style,
                    )
                    pdf_signer.sign_pdf(
                        w,
                        existing_fields_only=True,
                        appearance_text_params={'signer': nome_assinante},
                        output=signed_buffer,
                    )

                signed_buffer.seek(0)
                signed_pdf_content = signed_buffer.read()

            else:
                # ===== PRIMEIRA ASSINATURA: Página de autenticação + pyhanko sign =====

                original_pdf = PdfFileReader(io.BytesIO(pdf_bytes))
                last_page = original_pdf.getPage(original_pdf.getNumPages() - 1)
                page_box = last_page.mediaBox
                page_width = float(page_box.getWidth())
                page_height = float(page_box.getHeight())

                # Gerar código de autenticação
                codigo = _gerar_codigo_autenticacao(pdf_bytes)

                # Construir URL de verificação
                url_verificacao = _construir_url_verificacao(
                    request, 'docacessorio', pk, codigo
                )

                # Nova assinatura info
                nova_assinatura_info = {
                    'nome_assinante': nome_assinante,
                    'cargo': cargo,
                    'data_assinatura': data_simples,
                }

                # Gerar a página de autenticação
                auth_page_bytes = _gerar_pagina_autenticacao(
                    [nova_assinatura_info],
                    codigo, url_verificacao,
                    page_width, page_height
                )

                # Montar PDF: original + página de autenticação
                auth_page_pdf = PdfFileReader(io.BytesIO(auth_page_bytes))
                output_pdf = PdfFileWriter()

                for page_num in range(original_pdf.getNumPages()):
                    output_pdf.addPage(original_pdf.getPage(page_num))

                output_pdf.addPage(auth_page_pdf.getPage(0))

                with open(temp_stamped_path, 'wb') as f:
                    output_pdf.write(f)

                with open(temp_stamped_path, 'rb') as stamped_file:
                    stamped_bytes = stamped_file.read()

                signed_buffer = io.BytesIO()
                with io.BytesIO(stamped_bytes) as inf:
                    w = IncrementalPdfFileWriter(inf)

                    meta = signers.PdfSignatureMetadata(
                        field_name='AssinaturaDigital',
                        location='Câmara Municipal',
                        reason='Documento assinado digitalmente nos termos da MP 2.200-2/2001',
                        name=nome_assinante
                    )

                    signers.sign_pdf(
                        w,
                        meta,
                        signer=signer,
                        output=signed_buffer
                    )

                signed_buffer.seek(0)
                signed_pdf_content = signed_buffer.read()

                # Salvar código de autenticação
                docacessorio.codigo_autenticacao = codigo

            filename = f"docacessorio_{docacessorio.pk}_assinado_{int(timezone.now().timestamp())}.pdf"
            docacessorio.pdf_assinado.save(filename, ContentFile(signed_pdf_content), save=False)

            nova_assinatura = {
                'tipo_certificado': 'A1',
                'tipo_certificado_display': f'{tipo_cert} – A1',
                'subject': str(cert_info.subject),
                'issuer': str(cert_info.issuer),
                'serial': str(cert_info.serial_number),
                'valid_from': cert_info.not_valid_before.isoformat(),
                'valid_to': cert_info.not_valid_after.isoformat(),
                'signed_by': request.user.username,
                'nome_assinante': nome_assinante,
                'cargo': cargo,
                'data_assinatura': data_formatada,
                'validade_juridica': 'Assinatura Eletrônica Qualificada'
            }
            assinaturas_existentes.append(nova_assinatura)
            docacessorio.assinatura_info = assinaturas_existentes
            docacessorio.assinado_em = timezone.now()
            docacessorio.assinado_por = request.user
            docacessorio.save()

            logger.info(f"Documento acessório {docacessorio.pk} assinado por {request.user.username}")

            return JsonResponse({
                'success': True,
                'message': 'PDF assinado com sucesso!',
                'certificado': {
                    'nome': str(cert_info.subject),
                    'validade': cert_info.not_valid_after.strftime('%d/%m/%Y')
                }
            })

        finally:
            if os.path.exists(temp_stamped_path):
                os.unlink(temp_stamped_path)

    except ImportError:
        logger.error("pyhanko não está instalado")
        return JsonResponse({
            'success': False,
            'error': 'Biblioteca de assinatura não instalada. Contate o administrador.'
        }, status=500)
    except Exception as e:
        logger.error(f"Erro ao assinar PDF do doc acessório: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Erro ao assinar o PDF: {str(e)}'
        }, status=500)


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
    Apenas superusuários podem executar esta ação.
    """
    if not request.user.is_superuser:
        return JsonResponse({
            'success': False,
            'error': 'Apenas administradores podem remover assinaturas.'
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
