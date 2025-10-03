"""
URLs do módulo TCE
"""
from django.urls import path
from . import admin_views

app_name = 'tce'

urlpatterns = [
    # Dashboard admin customizado
    path('admin/', admin_views.tce_admin_index, name='admin_index'),

    # APIs - Processos
    path('api/processos/', admin_views.api_list_processos, name='api_list_processos'),
    path('api/processos/create/', admin_views.api_create_processo, name='api_create_processo'),

    # APIs - Arquivos
    path('api/arquivos/', admin_views.api_list_arquivos, name='api_list_arquivos'),
    path('api/arquivos/upload/', admin_views.api_upload_arquivo, name='api_upload_arquivo'),
    path('api/arquivos/<uuid:arquivo_id>/delete/', admin_views.api_delete_arquivo, name='api_delete_arquivo'),
    path('api/arquivos/<uuid:arquivo_id>/assinar/', admin_views.api_assinar_arquivo, name='api_assinar_arquivo'),
    path('api/arquivos/<uuid:arquivo_id>/gerar-p7s/', admin_views.api_gerar_p7s, name='api_gerar_p7s'),

    # Visualização de arquivo
    path('arquivo/<uuid:arquivo_id>/visualizar/', admin_views.visualizar_arquivo, name='visualizar_arquivo'),

    # APIs - Pastas e Subpastas
    path('api/pastas/criar/', admin_views.api_criar_pasta, name='api_criar_pasta'),
    path('api/subpastas/adicionar/', admin_views.api_adicionar_subpasta, name='api_adicionar_subpasta'),

    # Visualização de processo
    path('processo/<uuid:processo_id>/', admin_views.processo_detail, name='processo_detail'),
    path('processo/<uuid:processo_id>/pasta/<uuid:pasta_id>/<path:subpasta>/', admin_views.processo_subpasta_detail, name='processo_subpasta_detail'),
]
