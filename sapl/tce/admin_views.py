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


@login_required
def processo_detail(request, processo_id):
    """View: Detalhes do processo com subpastas"""
    processo = get_object_or_404(TceProcesso, id=processo_id)
    pastas = processo.pastas.all()

    # Estrutura de subpastas por categoria
    subpastas_estrutura = {
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

    context = {
        'title': f'Processo: {processo.titulo}',
        'processo': processo,
        'pastas': pastas,
        'subpastas_estrutura': subpastas_estrutura,
    }

    return render(request, 'admin/tce/processo_detail.html', context)


@login_required
@require_http_methods(["GET"])
def api_list_arquivos(request):
    """API: Listar arquivos de uma subpasta"""
    try:
        pasta_id = request.GET.get('pasta_id')
        subpasta = request.GET.get('subpasta')

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
