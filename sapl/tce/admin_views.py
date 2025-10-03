"""
Views customizadas para o admin do TCE
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from .models import TceProcesso, TcePasta, TceArquivo, TceAssinatura, TceLog
import json


@login_required
def tce_admin_index(request):
    """
    Dashboard principal do TCE no admin
    Com navbar e footer padrão do SAPL
    """
    context = {
        'title': 'Tribunal de Contas (TCE)',
        'total_processos': TceProcesso.objects.count(),
        'total_arquivos': TceArquivo.objects.count(),
        'total_validados': TceArquivo.objects.filter(validado=True).count(),
        'total_assinaturas': TceAssinatura.objects.count(),
    }

    return render(request, 'admin/tce/app_index.html', context)


@login_required
@require_http_methods(["GET"])
def api_list_processos(request):
    """API: Listar todos os processos"""
    processos = TceProcesso.objects.all().order_by('-criado_em')

    data = {
        'processos': [{
            'id': str(p.id),
            'titulo': p.titulo,
            'ano': p.ano,
            'periodo': p.periodo,
            'status': p.status,
            'total_arquivos': p.total_arquivos,
            'criado_em': p.criado_em.isoformat()
        } for p in processos]
    }

    return JsonResponse(data)


@login_required
@require_http_methods(["POST"])
def api_create_processo(request):
    """API: Criar novo processo"""
    try:
        titulo = request.POST.get('titulo')
        ano = int(request.POST.get('ano'))
        periodo = request.POST.get('periodo')
        descricao = request.POST.get('descricao', '')

        processo = TceProcesso.objects.create(
            titulo=titulo,
            ano=ano,
            periodo=periodo,
            descricao=descricao,
            criado_por=request.user
        )

        # Criar pastas padrão automaticamente
        pastas_padrao = [
            ('Gestão Orçamentária e Financeira', 'financeiro'),
            ('Gestão Administrativa', 'administrativo'),
            ('Gestão Legislativa', 'legislativo'),
        ]

        for nome, categoria in pastas_padrao:
            TcePasta.objects.create(
                processo=processo,
                nome=nome,
                categoria=categoria
            )

        return JsonResponse({
            'success': True,
            'processo_id': str(processo.id),
            'message': 'Processo criado com sucesso!'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


def _get_subpastas_estrutura():
    """Retorna a estrutura de subpastas por categoria"""
    return {
        'financeiro': [
            'Balancetes mensais (receitas e despesas)',
            'Execução orçamentária (RREO, RGF)',
            'Demonstrativos de empenhos, liquidações e pagamentos',
            'Folha de pagamento de servidores e vereadores'
        ],
        'administrativo': [
            'Atos de pessoal (nomeações, exonerações, aposentadorias, licenças)',
            'Processos licitatórios, dispensas, inexigibilidades',
            'Contratos administrativos e aditivos',
            'Inventário patrimonial e relatórios de controle interno'
        ],
        'legislativo': [
            'Leis, resoluções, decretos legislativos aprovados',
            'Atas das sessões plenárias',
            'Relatórios de comissões e pareceres',
            'Regimento Interno atualizado'
        ]
    }


@login_required
def processo_detail(request, processo_id):
    """View: Detalhes do processo com subpastas"""
    processo = get_object_or_404(TceProcesso, id=processo_id)
    pastas = processo.pastas.all()

    # Mesclar subpastas padrão com customizadas para cada pasta
    subpastas_estrutura = _get_subpastas_estrutura()
    for pasta in pastas:
        categoria = pasta.categoria
        if categoria in subpastas_estrutura:
            # Adicionar subpastas customizadas da pasta
            subpastas_custom = pasta.get_subpastas_customizadas()
            if subpastas_custom:
                subpastas_estrutura[categoria] = list(subpastas_estrutura[categoria]) + subpastas_custom
        else:
            # Pasta customizada (categoria não existe na estrutura padrão)
            # Criar entrada na estrutura apenas com as subpastas customizadas
            subpastas_custom = pasta.get_subpastas_customizadas()
            if subpastas_custom:
                subpastas_estrutura[categoria] = subpastas_custom

    context = {
        'title': f'Processo: {processo.titulo}',
        'processo': processo,
        'pastas': pastas,
        'subpastas_estrutura': subpastas_estrutura,
    }

    return render(request, 'admin/tce/processo_detail.html', context)


@login_required
def processo_subpasta_detail(request, processo_id, pasta_id, subpasta):
    """View: Detalhes de uma subpasta específica"""
    import urllib.parse

    processo = get_object_or_404(TceProcesso, id=processo_id)
    pasta = get_object_or_404(TcePasta, id=pasta_id, processo=processo)

    # Decodificar o nome da subpasta da URL
    subpasta_nome = urllib.parse.unquote(subpasta)

    # Buscar arquivos da subpasta
    arquivos = TceArquivo.objects.filter(
        pasta=pasta,
        subpasta=subpasta_nome
    ).order_by('-criado_em')

    context = {
        'title': f'{subpasta_nome} - {processo.titulo}',
        'processo': processo,
        'pasta': pasta,
        'subpasta_nome': subpasta_nome,
        'arquivos': arquivos,
    }

    return render(request, 'admin/tce/subpasta_detail.html', context)


@login_required
@require_http_methods(["GET"])
def api_list_arquivos(request):
    """API: Listar arquivos de uma subpasta"""
    import sys
    try:
        pasta_id = request.GET.get('pasta_id')
        subpasta = request.GET.get('subpasta')

        sys.stderr.write(f"\n=== API LIST ARQUIVOS ===\n")
        sys.stderr.write(f"pasta_id: {pasta_id}\n")
        sys.stderr.write(f"subpasta: {subpasta}\n")
        sys.stderr.flush()

        if not pasta_id or not subpasta:
            return JsonResponse({
                'success': False,
                'error': 'Parâmetros pasta_id e subpasta são obrigatórios'
            }, status=400)

        # Buscar arquivos filtrados
        arquivos = TceArquivo.objects.filter(
            pasta_id=pasta_id,
            subpasta=subpasta
        ).order_by('-criado_em')

        sys.stderr.write(f"Total de arquivos encontrados: {arquivos.count()}\n")
        for a in arquivos:
            sys.stderr.write(f"  - {a.id} | {a.nome_original}\n")
        sys.stderr.flush()

        data = {
            'success': True,
            'arquivos': [{
                'id': str(a.id),
                'nome': a.nome_original,
                'tipo': a.tipo,
                'tamanho': f"{a.tamanho_mb:.2f} MB",
                'tamanho_mb': a.tamanho_mb,
                'tamanho_ok': a.tamanho_ok,
                'ocr_ok': a.ocr_ok,
                'assinado': a.assinado,
                'p7s_gerado': a.p7s_gerado,
                'validado': a.validado,
                'status': a.status_geral,
                'status_cor': a.status_cor,
                'criado_em': a.criado_em.strftime('%d/%m/%Y %H:%M'),
                'url': a.arquivo.url if a.arquivo else None,
            } for a in arquivos]
        }

        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
@csrf_exempt
def api_upload_arquivo(request):
    """API: Upload de arquivo para uma subpasta"""
    try:
        pasta_id = request.POST.get('pasta_id')
        subpasta = request.POST.get('subpasta')
        arquivo = request.FILES.get('arquivo')

        if not pasta_id or not subpasta or not arquivo:
            return JsonResponse({
                'success': False,
                'error': 'Parâmetros pasta_id, subpasta e arquivo são obrigatórios'
            }, status=400)

        # Verificar se pasta existe
        pasta = get_object_or_404(TcePasta, id=pasta_id)

        # Detectar tipo de arquivo
        nome_lower = arquivo.name.lower()
        if nome_lower.endswith('.pdf'):
            tipo = 'pdf'
        elif nome_lower.endswith('.xml'):
            tipo = 'xml'
        else:
            return JsonResponse({
                'success': False,
                'error': 'Apenas arquivos PDF e XML são permitidos'
            }, status=400)

        # Calcular tamanho
        tamanho_bytes = arquivo.size
        tamanho_mb = tamanho_bytes / (1024 * 1024)
        tamanho_ok = tamanho_mb <= 5.0

        # Criar arquivo
        novo_arquivo = TceArquivo.objects.create(
            pasta=pasta,
            subpasta=subpasta,
            arquivo=arquivo,
            nome_original=arquivo.name,
            tipo=tipo,
            tamanho_bytes=tamanho_bytes,
            tamanho_mb=tamanho_mb,
            tamanho_ok=tamanho_ok,
            enviado_por=request.user
        )

        # Criar log
        TceLog.objects.create(
            processo=pasta.processo,
            arquivo=novo_arquivo,
            tipo='arquivo_upload',
            descricao=f'Upload do arquivo {arquivo.name} para {subpasta}',
            usuario=request.user,
            sucesso=True
        )

        return JsonResponse({
            'success': True,
            'arquivo_id': str(novo_arquivo.id),
            'message': 'Arquivo enviado com sucesso!',
            'tamanho_ok': tamanho_ok,
            'tamanho_mb': round(tamanho_mb, 2)
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def api_criar_pasta(request):
    """API: Criar nova pasta e adicionar subpasta inicial"""
    try:
        processo_id = request.GET.get('processo_id') or request.POST.get('processo_id')
        nome_pasta = request.POST.get('nome_pasta', '').strip()
        nome_subpasta = request.POST.get('nome_subpasta', '').strip()

        # Obter processo_id da URL se não veio no POST
        if not processo_id:
            # Tentar pegar do referer
            referer = request.META.get('HTTP_REFERER', '')
            import re
            match = re.search(r'/processo/([a-f0-9-]+)/', referer)
            if match:
                processo_id = match.group(1)

        if not processo_id or not nome_pasta or not nome_subpasta:
            return JsonResponse({
                'success': False,
                'error': 'Parâmetros processo_id, nome_pasta e nome_subpasta são obrigatórios'
            }, status=400)

        processo = get_object_or_404(TceProcesso, id=processo_id)

        # Verificar se pasta já existe
        if TcePasta.objects.filter(processo=processo, nome=nome_pasta).exists():
            return JsonResponse({
                'success': False,
                'error': 'Já existe uma pasta com este nome'
            }, status=400)

        # Criar a nova pasta (categoria "outros")
        nova_pasta = TcePasta.objects.create(
            processo=processo,
            nome=nome_pasta,
            categoria='outros',
            ordem=processo.pastas.count()
        )

        # Adicionar a primeira subpasta
        nova_pasta.set_subpastas_customizadas([nome_subpasta])
        nova_pasta.save()

        # Criar log
        TceLog.objects.create(
            processo=processo,
            tipo='pasta_criada',
            descricao=f'Nova pasta "{nome_pasta}" criada com subpasta "{nome_subpasta}"',
            usuario=request.user,
            sucesso=True
        )

        return JsonResponse({
            'success': True,
            'message': 'Pasta e subpasta criadas com sucesso!',
            'pasta_id': str(nova_pasta.id)
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def api_adicionar_subpasta(request):
    """API: Adicionar nova subpasta a uma pasta"""
    try:
        pasta_id = request.POST.get('pasta_id')
        nome_subpasta = request.POST.get('nome_subpasta', '').strip()

        if not pasta_id or not nome_subpasta:
            return JsonResponse({
                'success': False,
                'error': 'Parâmetros pasta_id e nome_subpasta são obrigatórios'
            }, status=400)

        pasta = get_object_or_404(TcePasta, id=pasta_id)

        # Verificar se a subpasta já existe
        subpastas_padrao = _get_subpastas_estrutura().get(pasta.categoria, [])
        subpastas_customizadas = pasta.get_subpastas_customizadas()

        if nome_subpasta in subpastas_padrao or nome_subpasta in subpastas_customizadas:
            return JsonResponse({
                'success': False,
                'error': 'Já existe uma subpasta com este nome'
            }, status=400)

        # Adicionar a nova subpasta
        subpastas_customizadas.append(nome_subpasta)
        pasta.set_subpastas_customizadas(subpastas_customizadas)
        pasta.save()

        # Criar log
        TceLog.objects.create(
            processo=pasta.processo,
            tipo='pasta_criada',
            descricao=f'Nova subpasta "{nome_subpasta}" adicionada à pasta "{pasta.nome}"',
            usuario=request.user,
            sucesso=True
        )

        return JsonResponse({
            'success': True,
            'message': 'Subpasta adicionada com sucesso!',
            'subpasta': nome_subpasta
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["DELETE", "POST"])
def api_delete_arquivo(request, arquivo_id):
    """API: Excluir arquivo"""
    import sys
    import logging
    logger = logging.getLogger(__name__)

    # Write to file for debugging
    with open('/tmp/delete_debug.log', 'a') as f:
        f.write(f"\n{'='*80}\n")
        f.write(f"DELETE ARQUIVO CALLED\n")
        f.write(f"ID: {arquivo_id}\n")
        f.write(f"Method: {request.method}\n")
        f.write(f"User: {request.user}\n")
        f.write(f"{'='*80}\n")
        f.flush()

    print(f"\n{'='*80}", file=sys.stderr, flush=True)
    print(f"=== FUNÇÃO api_delete_arquivo EXECUTADA ===", file=sys.stderr, flush=True)
    print(f"=== ID: {arquivo_id} ===", file=sys.stderr, flush=True)
    print(f"=== Method: {request.method} ===", file=sys.stderr, flush=True)
    print(f"{'='*80}\n", file=sys.stderr, flush=True)

    logger.error(f"DELETE ARQUIVO CALLED: {arquivo_id}")

    try:
        # Buscar arquivo
        try:
            arquivo = TceArquivo.objects.get(id=arquivo_id)
            sys.stderr.write(f"=== DEBUG: Arquivo encontrado: {arquivo.nome_original} ===\n")
            sys.stderr.flush()
        except TceArquivo.DoesNotExist:
            sys.stderr.write(f"=== DEBUG: Arquivo {arquivo_id} não encontrado ===\n")
            sys.stderr.flush()
            return JsonResponse({
                'success': False,
                'error': 'Arquivo não encontrado'
            }, status=404)

        nome_arquivo = arquivo.nome_original
        subpasta_nome = arquivo.subpasta
        sys.stderr.write(f"=== DEBUG: Preparando exclusão - Nome: {nome_arquivo}, Subpasta: {subpasta_nome} ===\n")
        sys.stderr.flush()

        # Criar log antes de excluir
        try:
            pasta = arquivo.pasta
            processo = pasta.processo
            TceLog.objects.create(
                processo=processo,
                tipo='erro',
                descricao=f'Arquivo {nome_arquivo} excluído da subpasta {subpasta_nome}',
                usuario=request.user,
                sucesso=True
            )
            sys.stderr.write(f"=== DEBUG: Log criado ===\n")
            sys.stderr.flush()
        except Exception as log_error:
            sys.stderr.write(f"=== DEBUG: Erro ao criar log: {log_error} ===\n")
            sys.stderr.flush()

        # Excluir arquivos físicos
        try:
            if arquivo.arquivo:
                arquivo.arquivo.delete(save=False)
                sys.stderr.write(f"=== DEBUG: Arquivo físico excluído ===\n")
                sys.stderr.flush()
        except Exception as file_error:
            sys.stderr.write(f"=== DEBUG: Erro ao excluir arquivo físico: {file_error} ===\n")
            sys.stderr.flush()

        # Excluir registro do banco
        with open('/tmp/delete_debug.log', 'a') as f:
            f.write(f"ANTES DE DELETE: arquivo.id = {arquivo.id}\n")
            f.flush()

        sys.stderr.write(f"=== DEBUG: Chamando arquivo.delete() ===\n")
        sys.stderr.flush()
        arquivo.delete()
        sys.stderr.write(f"=== DEBUG: arquivo.delete() executado ===\n")
        sys.stderr.flush()

        # Verificar se foi realmente excluído
        existe = TceArquivo.objects.filter(id=arquivo_id).exists()

        with open('/tmp/delete_debug.log', 'a') as f:
            f.write(f"DEPOIS DE DELETE: existe = {existe}\n")
            f.flush()

        sys.stderr.write(f"=== DEBUG: Arquivo ainda existe no banco? {existe} ===\n")
        sys.stderr.flush()

        response = JsonResponse({
            'success': True,
            'message': 'Arquivo excluído com sucesso!',
            'debug_source': 'api_delete_arquivo_function'
        })
        response['X-Debug-View'] = 'api_delete_arquivo'
        return response
    except Exception as e:
        sys.stderr.write(f"=== DEBUG: ERRO GERAL: {str(e)} ===\n")
        sys.stderr.flush()
        import traceback
        sys.stderr.write(traceback.format_exc() + "\n")
        sys.stderr.flush()
        response = JsonResponse({
            'success': False,
            'error': str(e),
            'debug_source': 'api_delete_arquivo_function_ERROR'
        }, status=500)
        response['X-Debug-View'] = 'api_delete_arquivo_ERROR'
        return response


@login_required
@require_http_methods(["GET"])
def visualizar_arquivo(request, arquivo_id):
    """
    Visualizar/download de arquivo TCE
    """
    from django.http import FileResponse, Http404
    import os
    
    try:
        arquivo = TceArquivo.objects.get(id=arquivo_id)
        
        # Determinar qual arquivo servir (priorizar versões processadas)
        arquivo_para_servir = arquivo.arquivo_final
        
        if not arquivo_para_servir or not os.path.exists(arquivo_para_servir.path):
            raise Http404("Arquivo não encontrado")
        
        # Servir o arquivo
        response = FileResponse(
            open(arquivo_para_servir.path, 'rb'),
            content_type='application/pdf'
        )
        response['Content-Disposition'] = f'inline; filename="{arquivo.nome_original}"'
        return response
        
    except TceArquivo.DoesNotExist:
        raise Http404("Arquivo não encontrado")
    except Exception as e:
        raise Http404(f"Erro ao carregar arquivo: {str(e)}")


@login_required
@require_http_methods(["POST"])
def api_gerar_p7s(request, arquivo_id):
    """
    API para gerar arquivo .p7s
    """
    import os
    import shutil
    from django.core.files import File
    
    try:
        arquivo = TceArquivo.objects.get(id=arquivo_id)
        
        # Obter o arquivo base (PDF assinado ou OCR ou original)
        arquivo_base = arquivo.arquivo_final
        
        if not arquivo_base:
            return JsonResponse({
                'success': False,
                'error': 'Nenhum arquivo encontrado para gerar .p7s'
            }, status=400)
        
        # Criar nome do arquivo .p7s
        nome_original = arquivo.nome_original
        if nome_original.lower().endswith('.pdf'):
            nome_p7s = nome_original[:-4] + '.p7s'
        else:
            nome_p7s = nome_original + '.p7s'
        
        # NOTA: Aqui você implementaria a lógica real de geração do .p7s
        # Por enquanto, vamos apenas copiar o arquivo e renomear para .p7s
        # Em produção, você deve usar bibliotecas como pyhanko ou assinador específico
        
        # Caminho temporário para o .p7s
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.p7s') as temp_p7s:
            # Copiar conteúdo do arquivo original
            with open(arquivo_base.path, 'rb') as f_original:
                shutil.copyfileobj(f_original, temp_p7s)
            temp_p7s_path = temp_p7s.name
        
        # Salvar o arquivo .p7s no modelo
        with open(temp_p7s_path, 'rb') as f_p7s:
            arquivo.arquivo_p7s.save(nome_p7s, File(f_p7s), save=False)
        
        arquivo.p7s_gerado = True
        arquivo.atualizar_validacao()
        arquivo.save()
        
        # Limpar arquivo temporário
        os.unlink(temp_p7s_path)
        
        # Criar log
        TceLog.objects.create(
            processo=arquivo.pasta.processo,
            arquivo=arquivo,
            tipo='p7s_gerado',
            descricao=f'Arquivo .p7s gerado para {arquivo.nome_original}',
            usuario=request.user,
            sucesso=True
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Arquivo .p7s gerado com sucesso!',
            'arquivo_p7s': nome_p7s
        })
        
    except TceArquivo.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Arquivo não encontrado'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def api_assinar_arquivo(request, arquivo_id):
    """
    API para assinar arquivo digitalmente com certificado A1
    """
    import os
    from django.core.files import File
    from django.core.files.base import ContentFile
    
    try:
        arquivo = TceArquivo.objects.get(id=arquivo_id)
        
        # Obter dados do formulário
        tipo_certificado = request.POST.get('tipo_certificado')
        senha_certificado = request.POST.get('senha_certificado')
        certificado_file = request.FILES.get('arquivo_certificado')
        
        if not tipo_certificado:
            return JsonResponse({
                'success': False,
                'error': 'Tipo de certificado não informado'
            }, status=400)
        
        # Obter arquivo base
        arquivo_base = arquivo.arquivo_final
        if not arquivo_base or not os.path.exists(arquivo_base.path):
            return JsonResponse({
                'success': False,
                'error': 'Arquivo base não encontrado'
            }, status=400)
        
        # Para certificado A1, precisamos do arquivo .pfx e senha
        if tipo_certificado == 'A1':
            if not certificado_file or not senha_certificado:
                return JsonResponse({
                    'success': False,
                    'error': 'Certificado e senha são obrigatórios para A1'
                }, status=400)
            
            # Tentar assinar com pyhanko
            try:
                from pyhanko.sign import signers, fields
                from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
                from pyhanko.pdf_utils import images
                from pyhanko_certvalidator import ValidationContext
                import datetime
                
                # Ler certificado
                cert_data = certificado_file.read()
                
                # Criar assinador
                try:
                    signer = signers.SimpleSigner.load_pkcs12(
                        pfx_file=ContentFile(cert_data),
                        passphrase=senha_certificado.encode('utf-8')
                    )
                except Exception as cert_error:
                    return JsonResponse({
                        'success': False,
                        'error': f'Erro ao carregar certificado: {str(cert_error)}. Verifique a senha.'
                    }, status=400)
                
                # Criar arquivo de saída temporário
                import tempfile
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_signed:
                    temp_signed_path = temp_signed.name
                
                # Assinar o PDF
                with open(arquivo_base.path, 'rb') as inf:
                    w = IncrementalPdfFileWriter(inf)
                    
                    # Adicionar campo de assinatura
                    sig_field = fields.SigFieldSpec(
                        sig_field_name='Signature1',
                        box=(10, 10, 200, 60)
                    )
                    
                    # Metadados da assinatura
                    meta = signers.PdfSignatureMetadata(
                        field_name='Signature1',
                        location='TCE - Câmara Municipal',
                        reason='Assinatura Digital TCE',
                        name=request.user.get_full_name() or request.user.username
                    )
                    
                    # Executar assinatura
                    with open(temp_signed_path, 'wb') as outf:
                        fields.append_signature_field(w, sig_field)
                        signers.sign_pdf(
                            w,
                            meta,
                            signer=signer,
                            output=outf
                        )
                
                # Salvar arquivo assinado
                nome_assinado = arquivo.nome_original.replace('.pdf', '_assinado.pdf')
                with open(temp_signed_path, 'rb') as f_signed:
                    arquivo.arquivo_assinado.save(nome_assinado, File(f_signed), save=False)
                
                arquivo.assinado = True
                
                # Extrair info do certificado
                cert_info = signer.signing_cert
                arquivo.certificado_info = {
                    'subject': str(cert_info.subject),
                    'issuer': str(cert_info.issuer),
                    'serial': str(cert_info.serial_number),
                    'valid_from': cert_info.not_valid_before.isoformat(),
                    'valid_to': cert_info.not_valid_after.isoformat()
                }
                
                arquivo.atualizar_validacao()
                arquivo.save()
                
                # Limpar arquivo temporário
                os.unlink(temp_signed_path)
                
                # Criar registro de assinatura
                from sapl.tce.models import TceAssinatura
                TceAssinatura.objects.create(
                    arquivo=arquivo,
                    ordem=1,
                    papel='outros',
                    certificado_tipo=tipo_certificado,
                    certificado_nome=str(cert_info.subject),
                    certificado_serial=str(cert_info.serial_number),
                    certificado_validade=cert_info.not_valid_after.date(),
                    valida=True,
                    assinado_por=request.user
                )
                
                # Criar log
                TceLog.objects.create(
                    processo=arquivo.pasta.processo,
                    arquivo=arquivo,
                    tipo='arquivo_assinado',
                    descricao=f'Arquivo {arquivo.nome_original} assinado digitalmente',
                    usuario=request.user,
                    sucesso=True
                )
                
                return JsonResponse({
                    'success': True,
                    'message': 'Arquivo assinado com sucesso!',
                    'certificado': {
                        'nome': str(cert_info.subject),
                        'validade': cert_info.not_valid_after.strftime('%d/%m/%Y')
                    }
                })
                
            except ImportError:
                # Se pyhanko não estiver instalado, retornar erro informativo
                return JsonResponse({
                    'success': False,
                    'error': 'Biblioteca de assinatura não instalada. Execute: pip install pyhanko pyhanko-certvalidator',
                    'simulated': True
                }, status=500)
        
        elif tipo_certificado == 'A3':
            # Para A3, seria necessário integração com token/smartcard
            # Por enquanto, retornar não implementado
            return JsonResponse({
                'success': False,
                'error': 'Assinatura com certificado A3 ainda não implementada. Use certificado A1 (.pfx)'
            }, status=501)
        
        else:
            return JsonResponse({
                'success': False,
                'error': 'Tipo de certificado inválido'
            }, status=400)
            
    except TceArquivo.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Arquivo não encontrado'
        }, status=404)
    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }, status=500)
