"""
Admin do módulo TCE
"""
from django.contrib import admin
from django.utils.html import format_html
from .models import TceProcesso, TcePasta, TceArquivo, TceAssinatura, TceLog


@admin.register(TceProcesso)
class TceProcessoAdmin(admin.ModelAdmin):
    """Admin para Processos TCE"""
    change_list_template = 'admin/tce/change_list.html'
    change_form_template = 'admin/tce/change_form.html'
    list_display = ['titulo', 'ano', 'periodo', 'status_badge', 'progresso_bar',
                    'total_arquivos', 'criado_em']
    list_filter = ['status', 'ano', 'criado_em']
    search_fields = ['titulo', 'descricao', 'numero_protocolo']
    readonly_fields = ['criado_em', 'atualizado_em', 'progresso_percent']

    fieldsets = (
        ('Informações Básicas', {
            'fields': ('titulo', 'descricao', 'ano', 'periodo', 'status')
        }),
        ('Protocolo TCE', {
            'fields': ('numero_protocolo', 'data_envio', 'recibo_tce', 'hash_envio'),
            'classes': ('collapse',)
        }),
        ('Auditoria', {
            'fields': ('criado_em', 'atualizado_em', 'criado_por', 'progresso_percent'),
            'classes': ('collapse',)
        }),
    )

    def status_badge(self, obj):
        cores = {
            'rascunho': 'gray',
            'em_preparacao': 'orange',
            'validado': 'blue',
            'enviado': 'green',
            'devolvido': 'red',
            'aprovado': 'darkgreen'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">● {}</span>',
            cores.get(obj.status, 'gray'),
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    def progresso_bar(self, obj):
        percent = obj.progresso_percent
        cor = 'success' if percent == 100 else 'warning' if percent >= 50 else 'danger'
        return format_html(
            '<div style="width:100px; background:#eee; border-radius:3px;">'
            '<div style="width:{}%; background:{}; color:white; text-align:center; border-radius:3px;">{}</div>'
            '</div>',
            percent, cor, f'{percent}%'
        )
    progresso_bar.short_description = 'Progresso'


@admin.register(TcePasta)
class TcePastaAdmin(admin.ModelAdmin):
    """Admin para Pastas TCE"""
    change_list_template = 'admin/tce/change_list.html'
    change_form_template = 'admin/tce/change_form.html'
    list_display = ['nome', 'processo', 'categoria', 'total_arquivos', 'criado_em']
    list_filter = ['categoria', 'criado_em']
    search_fields = ['nome', 'processo__titulo']


@admin.register(TceArquivo)
class TceArquivoAdmin(admin.ModelAdmin):
    """Admin para Arquivos TCE"""
    change_list_template = 'admin/tce/change_list.html'
    change_form_template = 'admin/tce/change_form.html'
    list_display = ['nome_original', 'pasta', 'tipo', 'tamanho_mb', 'status_badge',
                    'checks', 'criado_em']
    list_filter = ['tipo', 'tamanho_ok', 'ocr_ok', 'assinado', 'p7s_gerado', 'validado']
    search_fields = ['nome_original', 'pasta__nome', 'pasta__processo__titulo']
    readonly_fields = ['criado_em', 'atualizado_em', 'hash_sha256']

    def status_badge(self, obj):
        return format_html(
            '<span class="badge" style="background:{}; color:white; padding:3px 8px; border-radius:3px;">{}</span>',
            obj.status_cor,
            obj.status_geral.replace('_', ' ').title()
        )
    status_badge.short_description = 'Status'

    def checks(self, obj):
        checks = [
            ('✓' if obj.tamanho_ok else '✗', 'green' if obj.tamanho_ok else 'red', '≤5MB'),
            ('✓' if obj.ocr_ok else '✗', 'green' if obj.ocr_ok else 'red', 'OCR'),
            ('✓' if obj.assinado else '✗', 'green' if obj.assinado else 'red', 'Assinado'),
            ('✓' if obj.p7s_gerado else '✗', 'green' if obj.p7s_gerado else 'red', '.p7s'),
        ]
        html = ''.join([
            f'<span style="color:{cor}; font-weight:bold;" title="{titulo}">{check}</span> '
            for check, cor, titulo in checks
        ])
        return format_html(html)
    checks.short_description = 'Checklist'


@admin.register(TceAssinatura)
class TceAssinaturaAdmin(admin.ModelAdmin):
    """Admin para Assinaturas"""
    change_list_template = 'admin/tce/change_list.html'
    change_form_template = 'admin/tce/change_form.html'
    list_display = ['arquivo', 'ordem', 'papel', 'certificado_tipo', 'valida_badge', 'assinado_em']
    list_filter = ['papel', 'certificado_tipo', 'valida', 'assinado_em']
    search_fields = ['arquivo__nome_original', 'certificado_nome']

    def valida_badge(self, obj):
        return format_html(
            '<span style="color: {};">● {}</span>',
            'green' if obj.valida else 'red',
            'Válida' if obj.valida else 'Inválida'
        )
    valida_badge.short_description = 'Validação'


@admin.register(TceLog)
class TceLogAdmin(admin.ModelAdmin):
    """Admin para Logs (somente leitura)"""
    change_list_template = 'admin/tce/change_list.html'
    change_form_template = 'admin/tce/change_form.html'
    list_display = ['processo', 'tipo', 'descricao_resumida', 'sucesso_icon', 'usuario', 'ocorrido_em']
    list_filter = ['tipo', 'sucesso', 'ocorrido_em']
    search_fields = ['processo__titulo', 'descricao']
    readonly_fields = ['processo', 'arquivo', 'tipo', 'descricao', 'dados', 'sucesso',
                       'erro_mensagem', 'ocorrido_em', 'usuario', 'ip']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def descricao_resumida(self, obj):
        return obj.descricao[:100] + '...' if len(obj.descricao) > 100 else obj.descricao
    descricao_resumida.short_description = 'Descrição'

    def sucesso_icon(self, obj):
        return format_html(
            '<span style="color: {}; font-size: 16px;">{}</span>',
            'green' if obj.sucesso else 'red',
            '✓' if obj.sucesso else '✗'
        )
    sucesso_icon.short_description = 'Status'
