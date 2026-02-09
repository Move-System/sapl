"""
Views e utilitários para integração com OnlyOffice Document Server
para Documento Administrativo
"""
import hashlib
import json
import logging
import time
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib import messages

from sapl.protocoloadm.models import DocumentoAdministrativo
from sapl.utils import build_onlyoffice_url, get_onlyoffice_browser_url

logger = logging.getLogger(__name__)


def generate_file_key(doc_id, user_id):
    """
    Gera uma chave única para o documento no OnlyOffice
    A chave muda a cada edição para forçar o OnlyOffice a recarregar
    """
    timestamp = str(int(time.time()))
    string_to_hash = f"docadm_{doc_id}_user_{user_id}_{timestamp}"
    return hashlib.md5(string_to_hash.encode()).hexdigest()


@login_required
@require_http_methods(["GET"])
def docadm_onlyoffice_config(request, pk):
    """
    Retorna a configuração JSON para inicializar o editor OnlyOffice
    """
    documento = get_object_or_404(DocumentoAdministrativo, pk=pk)

    # Verifica permissão de edição
    can_edit = request.user.has_perm('protocoloadm.change_documentoadministrativo')

    # URLs para o OnlyOffice acessar (dentro da rede Docker)
    download_url = build_onlyoffice_url(
        request,
        reverse('sapl.protocoloadm:docadm_onlyoffice_download', kwargs={'pk': pk})
    )
    callback_url = build_onlyoffice_url(
        request,
        reverse('sapl.protocoloadm:docadm_onlyoffice_callback', kwargs={'pk': pk})
    )


    # Configuração do documento
    document_config = {
        "fileType": "docx",
        "key": generate_file_key(documento.pk, request.user.pk),
        "title": f"DocAdm_{documento.pk}.docx",
        "url": download_url,
    }

    # Configuração do editor
    editor_config = {
        "mode": "edit" if can_edit else "view",
        "lang": "pt-BR",
        "callbackUrl": callback_url,
        "user": {
            "id": str(request.user.pk),
            "name": request.user.get_full_name() or request.user.username,
        },
        "customization": {
            "autosave": True,
            "forcesave": True,
            "comments": True,
            "chat": False,
        },
    }

    config = {
        "documentType": "word",
        "document": document_config,
        "editorConfig": editor_config,
        "height": "600px",
        "width": "100%",
    }

    # Adiciona JWT se estiver habilitado
    if settings.ONLYOFFICE_JWT_ENABLED and settings.ONLYOFFICE_JWT_SECRET:
        import jwt
        token = jwt.encode(config, settings.ONLYOFFICE_JWT_SECRET, algorithm='HS256')
        config['token'] = token

    return JsonResponse(config)


@require_http_methods(["GET"])
def docadm_onlyoffice_download(request, pk):
    """
    Endpoint para o OnlyOffice baixar o documento
    Se não existe arquivo, retorna um documento em branco
    """
    documento = get_object_or_404(DocumentoAdministrativo, pk=pk)

    # Se já tem arquivo, retorna ele
    if documento.texto_integral:
        try:
            with open(documento.texto_integral.path, 'rb') as f:
                content = f.read()
            response = HttpResponse(content, content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            response['Content-Disposition'] = f'attachment; filename="DocAdm_{pk}.docx"'
            return response
        except Exception as e:
            logger.error(f"Erro ao ler arquivo: {e}")

    # Tenta criar documento usando template
    try:
        from sapl.utils_template import criar_documento_com_template, criar_documento_em_branco

        # Busca tipo específico do documento administrativo (TipoDocumentoAdministrativo)
        tipo_especifico = documento.tipo if documento.tipo else None

        file_stream = criar_documento_com_template(
            'docadm',
            tipo_especifico,
            {
                'titulo': f'{documento.tipo} {documento.numero}/{documento.ano}',
                'descricao': documento.assunto,
                'tipo_display': 'Documento Administrativo'
            }
        )

        # Se não encontrou template, cria documento em branco
        if not file_stream:
            file_stream = criar_documento_em_branco(
                f'{documento.tipo} {documento.numero}/{documento.ano}',
                documento.assunto,
                'Documento Administrativo'
            )

        if file_stream:
            response = HttpResponse(
                file_stream.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
            response['Content-Disposition'] = f'attachment; filename="DocAdm_{pk}.docx"'
            return response

    except Exception as e:
        logger.error(f"Erro ao criar documento: {e}")

    # Fallback: Se python-docx não está instalado ou houve erro
    try:
        from docx import Document
        from io import BytesIO

        doc = Document()
        doc.add_heading(f'Documento Administrativo {documento.tipo}', 0)
        doc.add_paragraph(f'Número: {documento.numero}/{documento.ano}')
        doc.add_paragraph(f'Assunto: {documento.assunto}')
        doc.add_paragraph('')
        doc.add_paragraph('Digite o texto do documento abaixo:')
        doc.add_paragraph('')

        file_stream = BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)

        response = HttpResponse(
            file_stream.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        response['Content-Disposition'] = f'attachment; filename="DocAdm_{pk}.docx"'
        return response

    except ImportError:
        logger.error("python-docx não está instalado")
        return HttpResponse("Erro: python-docx não instalado", status=500)


@csrf_exempt
@require_http_methods(["POST"])
def docadm_onlyoffice_callback(request, pk):
    """
    Callback chamado pelo OnlyOffice quando o documento é salvo
    """
    try:
        body = json.loads(request.body.decode('utf-8'))
        status = body.get('status')
        download_url = body.get('url')

        logger.info(f"OnlyOffice callback para documento administrativo {pk}: status={status}, url={download_url}")

        # Status 2 ou 6 significa que o documento foi salvo
        if status in [2, 6] and download_url:

            documento = get_object_or_404(DocumentoAdministrativo, pk=pk)

            # Baixa o documento do OnlyOffice
            import requests
            try:
                response = requests.get(download_url, timeout=30)
            except Exception as e:
                logger.error(f"Erro ao fazer requisição de download: {e}")
                return JsonResponse({"error": 1})

            if response.status_code == 200:
                from django.core.files.base import ContentFile

                filename = f"docadm_{pk}_{int(time.time())}.docx"

                # Remove arquivo antigo se existir
                if documento.texto_integral:
                    documento.texto_integral.delete(save=False)

                try:
                    documento.texto_integral.save(
                        filename,
                        ContentFile(response.content),
                        save=True
                    )
                    logger.info(f"Documento salvo com sucesso: {filename}")
                    return JsonResponse({"error": 0})
                except Exception as e:
                    logger.error(f"Erro ao salvar arquivo: {e}")
                    return JsonResponse({"error": 1})
            else:
                logger.error(f"Erro ao baixar documento: status={response.status_code}")
                return JsonResponse({"error": 1})

        return JsonResponse({"error": 0})

    except Exception as e:
        logger.error(f"Erro no callback OnlyOffice: {e}")
        return JsonResponse({"error": 1})


@login_required
def docadm_onlyoffice_editor(request, pk):
    """
    Renderiza a página com o editor OnlyOffice integrado
    """
    documento = get_object_or_404(DocumentoAdministrativo, pk=pk)

    # Verifica se o usuário tem permissão
    if not request.user.has_perm('protocoloadm.change_documentoadministrativo'):
        messages.error(request, 'Você não tem permissão para editar este documento.')
        return redirect('sapl.protocoloadm:documentoadministrativo_detail', pk=pk)

    # URL do OnlyOffice acessível pelo navegador do usuário
    onlyoffice_url = get_onlyoffice_browser_url(request)

    context = {
        'documento': documento,
        'documento_tipo': 'Documento Administrativo',
        'documento_titulo': f'{documento.tipo} {documento.numero}/{documento.ano}',
        'documento_descricao': documento.assunto,
        'onlyoffice_url': onlyoffice_url,
        'config_url': reverse('sapl.protocoloadm:docadm_onlyoffice_config', kwargs={'pk': pk}),
        'voltar_url': reverse('sapl.protocoloadm:documentoadministrativo_detail', kwargs={'pk': pk}),
    }

    return render(request, 'onlyoffice/onlyoffice_editor.html', context)
