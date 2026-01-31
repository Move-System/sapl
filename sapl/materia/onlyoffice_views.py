"""
Views e utilitários para integração com OnlyOffice Document Server
"""
import hashlib
import json
import logging
import os
import time
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from sapl.materia.models import Proposicao
from sapl.utils import get_base_url

logger = logging.getLogger(__name__)


def generate_file_key(proposicao_id, user_id):
    """
    Gera uma chave única para o documento no OnlyOffice
    A chave muda a cada edição para forçar o OnlyOffice a recarregar
    """
    timestamp = str(int(time.time()))
    string_to_hash = f"proposicao_{proposicao_id}_user_{user_id}_{timestamp}"
    return hashlib.md5(string_to_hash.encode()).hexdigest()


@login_required
@require_http_methods(["GET"])
def onlyoffice_config(request, pk):
    """
    Retorna a configuração JSON para inicializar o editor OnlyOffice
    """
    proposicao = get_object_or_404(Proposicao, pk=pk)

    # Verifica se o usuário tem permissão para editar
    can_edit = (
        not proposicao.data_envio and
        proposicao.autor.operadores.filter(id=request.user.id).exists()
    )

    base_url = get_base_url(request)

    # URLs para o OnlyOffice acessar (dentro da rede Docker)
    # OnlyOffice precisa acessar o container SGVP pelo nome do serviço
    download_url = request.build_absolute_uri(
        reverse('sapl.materia:onlyoffice_download', kwargs={'pk': pk})
    )
    callback_url = request.build_absolute_uri(
        reverse('sapl.materia:onlyoffice_callback', kwargs={'pk': pk})
    )

    # Substituir localhost/host externo pelo nome do container na rede Docker
    # para que o OnlyOffice consiga acessar
    host = request.get_host()
    # sapl-dev:8000 é o nome do container e porta interna do SAPL
    download_url = download_url.replace(f'http://{host}', 'http://sapl-dev:8000')
    download_url = download_url.replace(f'https://{host}', 'http://sapl-dev:8000')
    callback_url = callback_url.replace(f'http://{host}', 'http://sapl-dev:8000')
    callback_url = callback_url.replace(f'https://{host}', 'http://sapl-dev:8000')

    # Configuração do documento
    document_config = {
        "fileType": "docx",
        "key": generate_file_key(proposicao.pk, request.user.pk),
        "title": f"Proposicao_{proposicao.pk}.docx",
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
def onlyoffice_download(request, pk):
    """
    Endpoint para o OnlyOffice baixar o documento
    Se não existe arquivo, retorna um documento em branco
    NOTA: Sem @login_required pois o OnlyOffice não tem sessão do Django
    """
    proposicao = get_object_or_404(Proposicao, pk=pk)

    # Verificação de permissão apenas se houver usuário autenticado
    if request.user.is_authenticated and not proposicao.autor.operadores.filter(id=request.user.id).exists():
        return HttpResponse("Sem permissão", status=403)

    # Se já tem arquivo, retorna ele
    if proposicao.texto_original:
        try:
            with open(proposicao.texto_original.path, 'rb') as f:
                content = f.read()
            response = HttpResponse(content, content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            response['Content-Disposition'] = f'attachment; filename="Proposicao_{pk}.docx"'
            return response
        except Exception as e:
            logger.error(f"Erro ao ler arquivo: {e}")

    # Tenta criar documento usando template
    try:
        from sapl.utils_template import criar_documento_com_template, criar_documento_em_branco

        # Busca tipo específico da proposição (TipoProposicao)
        tipo_especifico = proposicao.tipo if proposicao.tipo else None

        file_stream = criar_documento_com_template(
            'proposicao',
            tipo_especifico,
            {
                'titulo': f'Proposição {proposicao.tipo}',
                'descricao': proposicao.descricao,
                'tipo_display': 'Proposição'
            }
        )

        # Se não encontrou template, cria documento em branco
        if not file_stream:
            file_stream = criar_documento_em_branco(
                f'Proposição {proposicao.tipo}',
                proposicao.descricao,
                'Proposição'
            )

        if file_stream:
            response = HttpResponse(
                file_stream.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
            response['Content-Disposition'] = f'attachment; filename="Proposicao_{pk}.docx"'
            return response

    except Exception as e:
        logger.error(f"Erro ao criar documento: {e}")

    # Fallback: Se python-docx não está instalado ou houve erro
    try:
        from docx import Document
        from io import BytesIO

        doc = Document()
        doc.add_heading(f'Proposição {proposicao.tipo}', 0)
        doc.add_paragraph(f'Ementa: {proposicao.descricao}')
        doc.add_paragraph('')
        doc.add_paragraph('Digite o texto da proposição abaixo:')
        doc.add_paragraph('')

        file_stream = BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)

        response = HttpResponse(
            file_stream.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        response['Content-Disposition'] = f'attachment; filename="Proposicao_{pk}.docx"'
        return response

    except ImportError:
        logger.error("python-docx não está instalado")
        return HttpResponse("Erro: python-docx não instalado", status=500)


@csrf_exempt
@require_http_methods(["POST"])
def onlyoffice_callback(request, pk):
    """
    Callback chamado pelo OnlyOffice quando o documento é salvo

    Status codes:
    0 - Nenhum documento com a chave identificada foi encontrado
    1 - Documento está sendo editado
    2 - Documento está pronto para salvar
    3 - Ocorreu erro ao salvar o documento
    4 - Documento está fechado sem alterações
    6 - Documento está sendo editado, mas a versão atual do documento foi salva
    7 - Ocorreu um erro de salvamento forçado ou salvamento automático
    """
    try:
        body = json.loads(request.body.decode('utf-8'))
        status = body.get('status')
        download_url = body.get('url')

        logger.info(f"OnlyOffice callback para proposição {pk}: status={status}, url={download_url}, body={body}")

        # Status 2 ou 6 significa que o documento foi salvo
        if status in [2, 6] and download_url:
            logger.info(f"URL original recebida: {download_url}")

            # Substitui URLs externas por URLs internas da rede Docker
            # O OnlyOffice pode retornar localhost:8001 ou o host externo
            import re
            # Padrão para capturar qualquer host:porta antes do path
            download_url = re.sub(
                r'https?://[^/]+',
                'http://onlyoffice:80',
                download_url
            )
            logger.info(f"URL substituída para rede Docker: {download_url}")

            logger.info(f"Iniciando download do documento de: {download_url}")
            proposicao = get_object_or_404(Proposicao, pk=pk)

            # Baixa o documento do OnlyOffice
            import requests
            try:
                response = requests.get(download_url, timeout=30)
                logger.info(f"Download response: status={response.status_code}, size={len(response.content)}")
            except Exception as e:
                logger.error(f"Erro ao fazer requisição de download: {e}")
                return JsonResponse({"error": 1})

            if response.status_code == 200:
                # Salva o arquivo
                from django.core.files.base import ContentFile

                filename = f"proposicao_{pk}_{int(time.time())}.docx"
                logger.info(f"Salvando arquivo: {filename}")

                # Remove arquivo antigo se existir
                if proposicao.texto_original:
                    old_file = proposicao.texto_original.name
                    proposicao.texto_original.delete(save=False)
                    logger.info(f"Arquivo antigo removido: {old_file}")

                try:
                    proposicao.texto_original.save(
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

        # Para outros status, apenas retorna sucesso
        return JsonResponse({"error": 0})

    except Exception as e:
        logger.error(f"Erro no callback OnlyOffice: {e}")
        return JsonResponse({"error": 1})


@login_required
def onlyoffice_editor(request, pk):
    """
    Renderiza a página com o editor OnlyOffice integrado
    """
    from django.shortcuts import render

    proposicao = get_object_or_404(Proposicao, pk=pk)

    # Verifica se o usuário tem permissão
    if not proposicao.autor.operadores.filter(id=request.user.id).exists():
        from django.contrib import messages
        from django.shortcuts import redirect
        messages.error(request, 'Você não tem permissão para editar esta proposição.')
        return redirect('sapl.materia:proposicao_detail', pk=pk)

    # Verifica se já foi enviada
    if proposicao.data_envio:
        from django.contrib import messages
        from django.shortcuts import redirect
        messages.warning(request, 'Esta proposição já foi enviada e não pode mais ser editada.')
        return redirect('sapl.materia:proposicao_detail', pk=pk)

    # URL do OnlyOffice acessível pelo navegador do usuário
    # Se ONLYOFFICE_URL contém 'onlyoffice' (nome do container), substitui pelo host da requisição
    onlyoffice_url = settings.ONLYOFFICE_URL
    if 'onlyoffice:' in onlyoffice_url or 'onlyoffice/' in onlyoffice_url:
        # É a URL interna do Docker, precisa usar a URL externa
        protocol = 'https' if request.is_secure() else 'http'
        host = request.get_host().split(':')[0]  # Remove porta se existir
        onlyoffice_url = f"{protocol}://{host}:8001"

    context = {
        'proposicao': proposicao,
        'onlyoffice_url': onlyoffice_url,
        'config_url': reverse('sapl.materia:onlyoffice_config', kwargs={'pk': pk}),
    }

    return render(request, 'materia/onlyoffice_editor.html', context)
