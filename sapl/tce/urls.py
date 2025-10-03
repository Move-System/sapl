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

    # Visualização de processo
    path('processo/<uuid:processo_id>/', admin_views.processo_detail, name='processo_detail'),
]
