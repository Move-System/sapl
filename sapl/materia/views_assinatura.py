"""
Views para assinatura digital de PDFs de Matérias Legislativas.
Suporta certificados A1 (arquivo .pfx/.p12) e A3 (token USB/smartcard).
"""
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
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from sapl.base.models import AppConfig
from sapl.materia.models import DocumentoAcessorio, MateriaLegislativa

logger = logging.getLogger(__name__)


def _normalizar_assinatura_info(info):
    """Converte assinatura_info legado (dict) para lista de dicts."""
    if info is None:
        return []
    if isinstance(info, dict):
        return [info]
    return info


def _calcular_posicao_carimbo(n):
    """
    Calcula posição (x, y) do n-ésimo carimbo (n começa em 0).
    Layout em grade: 2 colunas, múltiplas linhas.
    """
    from reportlab.lib.units import mm
    col = n % 2
    row = n // 2
    x = (10 + col * 75) * mm
    y = (15 + row * 25) * mm
    return x, y


def _gerar_pdf_da_materia(materia, request):
    """
    Gera o PDF da matéria para assinatura.
    Primeiro tenta usar o PDF existente, depois converte DOCX via OnlyOffice.
    Retorna bytes do PDF ou None em caso de erro.
    """
    import requests as http_requests
    import xml.etree.ElementTree as ET
    from django.urls import reverse

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

    download_url = request.build_absolute_uri(
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

    # Permissão: qualquer usuário autenticado pode assinar
    # (a autenticação é garantida pelo decorator @login_required)

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
        from pyhanko.keys import load_cert_from_pemder
        from pyhanko_certvalidator import ValidationContext

        # Lê o certificado
        cert_data = certificado_file.read()

        # Cria o assinador - salva temporariamente o certificado
        import tempfile as tmp_module
        with tmp_module.NamedTemporaryFile(delete=False, suffix='.pfx') as tmp_cert:
            tmp_cert.write(cert_data)
            tmp_cert_path = tmp_cert.name

        try:
            signer = signers.SimpleSigner.load_pkcs12(
                pfx_file=tmp_cert_path,
                passphrase=senha.encode('utf-8')
            )
            # Limpa arquivo temporário do certificado após carregar
            if os.path.exists(tmp_cert_path):
                os.unlink(tmp_cert_path)
        except Exception as cert_error:
            logger.error(f"Erro ao carregar certificado: {cert_error}")
            # Limpa arquivo temporário do certificado
            if os.path.exists(tmp_cert_path):
                os.unlink(tmp_cert_path)
            error_msg = str(cert_error)
            if 'password' in error_msg.lower() or 'mac' in error_msg.lower():
                error_detail = 'Senha incorreta.'
            elif 'decode' in error_msg.lower() or 'parse' in error_msg.lower():
                error_detail = 'Arquivo não é um certificado válido (.pfx/.p12).'
            else:
                error_detail = f'Detalhes: {error_msg}'
            return JsonResponse({
                'success': False,
                'error': f'Erro ao carregar certificado: {error_detail}'
            }, status=400)

        if signer is None:
            return JsonResponse({
                'success': False,
                'error': 'Não foi possível carregar o certificado. Verifique se o arquivo .pfx/.p12 é válido e contém uma chave de assinatura.'
            }, status=400)

        # Verifica validade do certificado
        cert_info = signer.signing_cert
        now = timezone.now()
        # Converte datas do certificado para timezone-aware se necessário
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

        # Cria arquivo temporário para o PDF com carimbo
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_stamped:
            temp_stamped_path = temp_stamped.name

        try:
            from pyhanko.sign.fields import SigSeedSubFilter, SigFieldSpec
            from pyhanko.pdf_utils import text
            from pyhanko.sign.general import SigningError
            from PyPDF4 import PdfFileReader, PdfFileWriter
            from reportlab.pdfgen import canvas

            from reportlab.lib.units import mm
            from reportlab.lib.utils import ImageReader
            import re

            # Informações do assinante
            nome_assinante = request.user.get_full_name() or request.user.username
            data_assinatura = timezone.localtime(timezone.now())
            data_formatada = data_assinatura.strftime('%d/%m/%Y %H:%M:%S')

            # Tenta obter cargo do usuário (se for parlamentar/autor)
            cargo = "Usuário do Sistema"
            parlamentar = None
            try:
                from sapl.parlamentares.models import Parlamentar
                parlamentar = Parlamentar.objects.filter(
                    usuario=request.user
                ).first()
                if parlamentar:
                    cargo = "Vereador(a)"
                    tipo_nome = AppConfig.attr('assinatura_nome')
                    if tipo_nome == 'C':
                        nome_assinante = parlamentar.nome_completo
                    else:
                        nome_assinante = parlamentar.nome_parlamentar
            except:
                pass

            # Determina tipo de certificado baseado no issuer
            issuer_str = str(cert_info.issuer).upper()
            if 'ICP-BRASIL' in issuer_str or 'ICP BRASIL' in issuer_str:
                tipo_cert = "ICP-Brasil"
            else:
                tipo_cert = "Certificado Digital"

            # Tenta obter CPF do parlamentar ou do certificado
            cpf = ""
            try:
                if parlamentar and parlamentar.cpf:
                    cpf = parlamentar.cpf
            except:
                pass

            # Se não encontrou CPF no parlamentar, tenta extrair do certificado
            if not cpf:
                subject_str = str(cert_info.subject)
                cpf_match = re.search(r'\d{3}\.?\d{3}\.?\d{3}-?\d{2}', subject_str)
                if cpf_match:
                    cpf = cpf_match.group()

            # Formata data
            data_simples = data_assinatura.strftime('%d/%m/%Y %H:%M')

            # Número da assinatura (0-indexed)
            n_assinatura = len(assinaturas_existentes)
            sig_field_name = f'AssinaturaDigital_{n_assinatura + 1}' if n_assinatura > 0 else 'AssinaturaDigital'

            if ja_tem_pdf_assinado:
                # ===== ASSINATURA SUBSEQUENTE: Incremental sobre PDF já assinado =====

                with open(materia.pdf_assinado.path, 'rb') as f:
                    existing_pdf_bytes = f.read()

                # Criar carimbo visual via pyhanko TextStampStyle + SigFieldSpec
                x_pos, y_pos = _calcular_posicao_carimbo(n_assinatura)
                largura_carimbo = 70 * mm
                altura_carimbo = 22 * mm

                # Converter para pontos (pyhanko usa pontos)
                x1 = x_pos
                y1 = y_pos
                x2 = x_pos + largura_carimbo
                y2 = y_pos + altura_carimbo

                nome_upper = nome_assinante.upper()
                if len(nome_upper) > 28:
                    nome_upper = nome_upper[:28] + "..."

                signed_buffer = io.BytesIO()
                with io.BytesIO(existing_pdf_bytes) as inf:
                    w = IncrementalPdfFileWriter(inf)

                    # Determina a última página
                    from pyhanko.pdf_utils.reader import PdfFileReader as PyhankoReader
                    temp_reader = PyhankoReader(io.BytesIO(existing_pdf_bytes))
                    last_page_idx = temp_reader.root['/Pages']['/Count'] - 1

                    # Adiciona campo de assinatura com posição visual
                    sig_field = SigFieldSpec(
                        sig_field_name=sig_field_name,
                        on_page=last_page_idx,
                        box=(x1, y1, x2, y2)
                    )
                    fields.append_signature_field(w, sig_field)

                    # Cria stamp style para o carimbo visual
                    from pyhanko.stamp import TextStampStyle

                    stamp_text = f"Assinado digitalmente por\n{nome_upper}"
                    if cpf:
                        stamp_text += f"\nCPF: {cpf}"
                    stamp_text += f"\nData: {data_simples}"

                    stamp_style = TextStampStyle(
                        stamp_text=stamp_text,
                        background=None,
                    )

                    meta = signers.PdfSignatureMetadata(
                        field_name=sig_field_name,
                        location='Câmara Municipal',
                        reason='Documento assinado digitalmente nos termos da MP 2.200-2/2001',
                        name=nome_assinante
                    )

                    signers.sign_pdf(
                        w,
                        meta,
                        signer=signer,
                        output=signed_buffer,
                        existing_fields_only=True
                    )

                signed_buffer.seek(0)
                signed_pdf_content = signed_buffer.read()

            else:
                # ===== PRIMEIRA ASSINATURA: Carimbo ReportLab + pyhanko sign =====

                # Lê o PDF original para obter as dimensões reais da última página
                original_pdf = PdfFileReader(io.BytesIO(pdf_bytes))
                last_page = original_pdf.getPage(original_pdf.getNumPages() - 1)
                page_box = last_page.mediaBox
                page_width = float(page_box.getWidth())
                page_height = float(page_box.getHeight())

                # Cria PDF com o carimbo usando as mesmas dimensões da página original
                stamp_buffer = io.BytesIO()
                c = canvas.Canvas(stamp_buffer, pagesize=(page_width, page_height))

                # Posição do carimbo (canto inferior esquerdo) — posição 0
                x_pos, y_pos = _calcular_posicao_carimbo(0)
                largura_carimbo = 70 * mm
                altura_carimbo = 22 * mm
                logo_width = 18 * mm

                # Desenha borda fina do carimbo
                c.setStrokeColorRGB(0.5, 0.5, 0.5)
                c.setLineWidth(0.5)
                c.rect(x_pos, y_pos, largura_carimbo, altura_carimbo)

                # Texto do carimbo (lado esquerdo)
                c.setFont("Helvetica", 6)
                c.setFillColorRGB(0.3, 0.3, 0.3)
                c.drawString(x_pos + 3*mm, y_pos + 17*mm, "Assinado digitalmente por")

                c.setFont("Helvetica-Bold", 7)
                c.setFillColorRGB(0, 0, 0)
                nome_upper = nome_assinante.upper()
                if len(nome_upper) > 28:
                    nome_upper = nome_upper[:28] + "..."
                c.drawString(x_pos + 3*mm, y_pos + 12*mm, nome_upper)

                c.setFont("Helvetica", 6)
                c.setFillColorRGB(0.3, 0.3, 0.3)
                if cpf:
                    c.drawString(x_pos + 3*mm, y_pos + 7*mm, f"CPF: {cpf}")
                    c.drawString(x_pos + 3*mm, y_pos + 3*mm, f"Data: {data_simples}")
                else:
                    c.drawString(x_pos + 3*mm, y_pos + 5*mm, f"Data: {data_simples}")

                # Logo da câmara (lado direito)
                try:
                    logo_path = None
                    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

                    possible_paths = [
                        os.path.join(base_dir, 'sapl/static/sapl/frontend/img/logo-camara-padrao.png'),
                        os.path.join(base_dir, 'sapl/static/sapl/frontend/img/logo.png'),
                        os.path.join(base_dir, 'sapl/static/sapl/frontend/img/pdflogo.png'),
                        os.path.join(settings.MEDIA_ROOT, 'sapl/public/casa/logotipo/logo.png'),
                        os.path.join(settings.MEDIA_ROOT, 'sapl/public/casa/logotipo/logotipo.png'),
                    ]

                    logo_dir = os.path.join(settings.MEDIA_ROOT, 'sapl/public/casa/logotipo')
                    if os.path.exists(logo_dir):
                        for f in os.listdir(logo_dir):
                            if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                                possible_paths.insert(0, os.path.join(logo_dir, f))

                    for path in possible_paths:
                        if os.path.exists(path):
                            logo_path = path
                            break

                    if logo_path:
                        logo = ImageReader(logo_path)
                        logo_x = x_pos + largura_carimbo - logo_width - 2*mm
                        logo_y = y_pos + 2*mm
                        c.drawImage(logo, logo_x, logo_y,
                                   width=logo_width, height=logo_width,
                                   preserveAspectRatio=True, mask='auto')
                except Exception as logo_error:
                    logger.warning(f"Não foi possível adicionar logo: {logo_error}")

                c.save()
                stamp_buffer.seek(0)

                # Mescla o carimbo com o PDF original (ANTES de assinar)
                stamp_pdf = PdfFileReader(stamp_buffer)
                output_pdf = PdfFileWriter()

                for page_num in range(original_pdf.getNumPages()):
                    page = original_pdf.getPage(page_num)
                    if page_num == original_pdf.getNumPages() - 1:  # Última página
                        page.mergePage(stamp_pdf.getPage(0))
                    output_pdf.addPage(page)

                # Salva o PDF com carimbo em arquivo temporário
                with open(temp_stamped_path, 'wb') as f:
                    output_pdf.write(f)

                # Assinar o PDF que já contém o carimbo
                with open(temp_stamped_path, 'rb') as stamped_file:
                    stamped_bytes = stamped_file.read()

                signed_buffer = io.BytesIO()
                with io.BytesIO(stamped_bytes) as inf:
                    w = IncrementalPdfFileWriter(inf)

                    # Metadados da assinatura
                    meta = signers.PdfSignatureMetadata(
                        field_name='AssinaturaDigital',
                        location='Câmara Municipal',
                        reason='Documento assinado digitalmente nos termos da MP 2.200-2/2001',
                        name=nome_assinante
                    )

                    # Executa assinatura
                    signers.sign_pdf(
                        w,
                        meta,
                        signer=signer,
                        output=signed_buffer
                    )

                signed_buffer.seek(0)
                signed_pdf_content = signed_buffer.read()

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
    import hashlib

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
            # Cria o signer externo com a assinatura pré-computada
            # Nota: Esta é uma implementação simplificada
            # Em produção, seria necessário usar o ExternalSigner corretamente

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

def _gerar_pdf_do_docacessorio(docacessorio, request):
    """
    Gera o PDF do documento acessório para assinatura.
    Se já é PDF, retorna direto. Se é DOCX, converte via OnlyOffice.
    Retorna (bytes, None) ou (None, erro).
    """
    import requests as http_requests
    import xml.etree.ElementTree as ET
    from django.urls import reverse

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

    download_url = request.build_absolute_uri(
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
        from pyhanko.keys import load_cert_from_pemder
        from pyhanko_certvalidator import ValidationContext

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
            return JsonResponse({
                'success': False,
                'error': f'Erro ao carregar certificado: {error_detail}'
            }, status=400)

        if signer is None:
            return JsonResponse({
                'success': False,
                'error': 'Não foi possível carregar o certificado. Verifique se o arquivo .pfx/.p12 é válido e contém uma chave de assinatura.'
            }, status=400)

        cert_info = signer.signing_cert
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

        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_stamped:
            temp_stamped_path = temp_stamped.name

        try:
            from pyhanko.sign.fields import SigSeedSubFilter, SigFieldSpec
            from pyhanko.pdf_utils import text
            from pyhanko.sign.general import SigningError
            from PyPDF4 import PdfFileReader, PdfFileWriter
            from reportlab.pdfgen import canvas
            from reportlab.lib.units import mm
            from reportlab.lib.utils import ImageReader
            import re

            nome_assinante = request.user.get_full_name() or request.user.username
            data_assinatura = timezone.localtime(timezone.now())
            data_formatada = data_assinatura.strftime('%d/%m/%Y %H:%M:%S')

            cargo = "Usuário do Sistema"
            parlamentar = None
            try:
                from sapl.parlamentares.models import Parlamentar
                parlamentar = Parlamentar.objects.filter(
                    usuario=request.user
                ).first()
                if parlamentar:
                    cargo = "Vereador(a)"
                    tipo_nome = AppConfig.attr('assinatura_nome')
                    if tipo_nome == 'C':
                        nome_assinante = parlamentar.nome_completo
                    else:
                        nome_assinante = parlamentar.nome_parlamentar
            except:
                pass

            issuer_str = str(cert_info.issuer).upper()
            if 'ICP-BRASIL' in issuer_str or 'ICP BRASIL' in issuer_str:
                tipo_cert = "ICP-Brasil"
            else:
                tipo_cert = "Certificado Digital"

            cpf = ""
            try:
                if parlamentar and parlamentar.cpf:
                    cpf = parlamentar.cpf
            except:
                pass

            if not cpf:
                subject_str = str(cert_info.subject)
                cpf_match = re.search(r'\d{3}\.?\d{3}\.?\d{3}-?\d{2}', subject_str)
                if cpf_match:
                    cpf = cpf_match.group()

            data_simples = data_assinatura.strftime('%d/%m/%Y %H:%M')

            # Número da assinatura (0-indexed)
            n_assinatura = len(assinaturas_existentes)
            sig_field_name = f'AssinaturaDigital_{n_assinatura + 1}' if n_assinatura > 0 else 'AssinaturaDigital'

            if ja_tem_pdf_assinado:
                # ===== ASSINATURA SUBSEQUENTE: Incremental sobre PDF já assinado =====

                with open(docacessorio.pdf_assinado.path, 'rb') as f:
                    existing_pdf_bytes = f.read()

                x_pos, y_pos = _calcular_posicao_carimbo(n_assinatura)
                largura_carimbo = 70 * mm
                altura_carimbo = 22 * mm

                x1 = x_pos
                y1 = y_pos
                x2 = x_pos + largura_carimbo
                y2 = y_pos + altura_carimbo

                nome_upper = nome_assinante.upper()
                if len(nome_upper) > 28:
                    nome_upper = nome_upper[:28] + "..."

                signed_buffer = io.BytesIO()
                with io.BytesIO(existing_pdf_bytes) as inf:
                    w = IncrementalPdfFileWriter(inf)

                    from pyhanko.pdf_utils.reader import PdfFileReader as PyhankoReader
                    temp_reader = PyhankoReader(io.BytesIO(existing_pdf_bytes))
                    last_page_idx = temp_reader.root['/Pages']['/Count'] - 1

                    sig_field = SigFieldSpec(
                        sig_field_name=sig_field_name,
                        on_page=last_page_idx,
                        box=(x1, y1, x2, y2)
                    )
                    fields.append_signature_field(w, sig_field)

                    from pyhanko.stamp import TextStampStyle

                    stamp_text = f"Assinado digitalmente por\n{nome_upper}"
                    if cpf:
                        stamp_text += f"\nCPF: {cpf}"
                    stamp_text += f"\nData: {data_simples}"

                    stamp_style = TextStampStyle(
                        stamp_text=stamp_text,
                        background=None,
                    )

                    meta = signers.PdfSignatureMetadata(
                        field_name=sig_field_name,
                        location='Câmara Municipal',
                        reason='Documento assinado digitalmente nos termos da MP 2.200-2/2001',
                        name=nome_assinante
                    )

                    signers.sign_pdf(
                        w,
                        meta,
                        signer=signer,
                        output=signed_buffer,
                        existing_fields_only=True
                    )

                signed_buffer.seek(0)
                signed_pdf_content = signed_buffer.read()

            else:
                # ===== PRIMEIRA ASSINATURA: Carimbo ReportLab + pyhanko sign =====

                original_pdf = PdfFileReader(io.BytesIO(pdf_bytes))
                last_page = original_pdf.getPage(original_pdf.getNumPages() - 1)
                page_box = last_page.mediaBox
                page_width = float(page_box.getWidth())
                page_height = float(page_box.getHeight())

                stamp_buffer = io.BytesIO()
                c = canvas.Canvas(stamp_buffer, pagesize=(page_width, page_height))

                x_pos, y_pos = _calcular_posicao_carimbo(0)
                largura_carimbo = 70 * mm
                altura_carimbo = 22 * mm
                logo_width = 18 * mm

                c.setStrokeColorRGB(0.5, 0.5, 0.5)
                c.setLineWidth(0.5)
                c.rect(x_pos, y_pos, largura_carimbo, altura_carimbo)

                c.setFont("Helvetica", 6)
                c.setFillColorRGB(0.3, 0.3, 0.3)
                c.drawString(x_pos + 3*mm, y_pos + 17*mm, "Assinado digitalmente por")

                c.setFont("Helvetica-Bold", 7)
                c.setFillColorRGB(0, 0, 0)
                nome_upper = nome_assinante.upper()
                if len(nome_upper) > 28:
                    nome_upper = nome_upper[:28] + "..."
                c.drawString(x_pos + 3*mm, y_pos + 12*mm, nome_upper)

                c.setFont("Helvetica", 6)
                c.setFillColorRGB(0.3, 0.3, 0.3)
                if cpf:
                    c.drawString(x_pos + 3*mm, y_pos + 7*mm, f"CPF: {cpf}")
                    c.drawString(x_pos + 3*mm, y_pos + 3*mm, f"Data: {data_simples}")
                else:
                    c.drawString(x_pos + 3*mm, y_pos + 5*mm, f"Data: {data_simples}")

                try:
                    logo_path = None
                    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

                    possible_paths = [
                        os.path.join(base_dir, 'sapl/static/sapl/frontend/img/logo-camara-padrao.png'),
                        os.path.join(base_dir, 'sapl/static/sapl/frontend/img/logo.png'),
                        os.path.join(base_dir, 'sapl/static/sapl/frontend/img/pdflogo.png'),
                        os.path.join(settings.MEDIA_ROOT, 'sapl/public/casa/logotipo/logo.png'),
                        os.path.join(settings.MEDIA_ROOT, 'sapl/public/casa/logotipo/logotipo.png'),
                    ]

                    logo_dir = os.path.join(settings.MEDIA_ROOT, 'sapl/public/casa/logotipo')
                    if os.path.exists(logo_dir):
                        for f in os.listdir(logo_dir):
                            if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                                possible_paths.insert(0, os.path.join(logo_dir, f))

                    for path in possible_paths:
                        if os.path.exists(path):
                            logo_path = path
                            break

                    if logo_path:
                        logo = ImageReader(logo_path)
                        logo_x = x_pos + largura_carimbo - logo_width - 2*mm
                        logo_y = y_pos + 2*mm
                        c.drawImage(logo, logo_x, logo_y,
                                   width=logo_width, height=logo_width,
                                   preserveAspectRatio=True, mask='auto')
                except Exception as logo_error:
                    logger.warning(f"Não foi possível adicionar logo: {logo_error}")

                c.save()
                stamp_buffer.seek(0)

                stamp_pdf = PdfFileReader(stamp_buffer)
                output_pdf = PdfFileWriter()

                for page_num in range(original_pdf.getNumPages()):
                    page = original_pdf.getPage(page_num)
                    if page_num == original_pdf.getNumPages() - 1:
                        page.mergePage(stamp_pdf.getPage(0))
                    output_pdf.addPage(page)

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
