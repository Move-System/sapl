"""
Modelos do módulo TCE - Nova versão simplificada
Estrutura: Processo → Pastas → Arquivos → Logs
"""
import uuid
from datetime import datetime
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.contrib.postgres.fields import JSONField


def get_current_year():
    """Retorna o ano atual"""
    return datetime.now().year


class TceProcesso(models.Model):
    """
    Processo principal TCE (ex: Prestação de Contas - 3º Quadrimestre/2025)
    Similar a uma pasta principal no Google Drive
    """
    STATUS_CHOICES = [
        ('rascunho', _('Rascunho')),
        ('em_preparacao', _('Em Preparação')),
        ('validado', _('Validado')),
        ('enviado', _('Enviado ao TCE')),
        ('devolvido', _('Devolvido pelo TCE')),
        ('aprovado', _('Aprovado')),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    titulo = models.CharField(_('Título do Processo'), max_length=255)
    descricao = models.TextField(_('Descrição'), blank=True)
    ano = models.IntegerField(_('Ano'), default=get_current_year)
    periodo = models.CharField(_('Período'), max_length=100, blank=True,
                               help_text=_('Ex: 3º Quadrimestre, Anual, Mensal'))

    status = models.CharField(_('Status'), max_length=20, choices=STATUS_CHOICES, default='rascunho')

    # Protocolo TCE
    numero_protocolo = models.CharField(_('Número de Protocolo TCE'), max_length=100, blank=True)
    data_envio = models.DateTimeField(_('Data de Envio'), null=True, blank=True)
    recibo_tce = models.TextField(_('Recibo TCE'), blank=True)
    hash_envio = models.CharField(_('Hash do Envio'), max_length=64, blank=True)

    # Metadados
    metadados = JSONField(_('Metadados'), default=dict, blank=True)

    # Auditoria
    criado_em = models.DateTimeField(_('Criado em'), auto_now_add=True)
    atualizado_em = models.DateTimeField(_('Atualizado em'), auto_now=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                    related_name='processos_tce_criados')

    class Meta:
        verbose_name = _('Processo TCE')
        verbose_name_plural = _('Processos TCE')
        ordering = ['-ano', '-criado_em']

    def __str__(self):
        return f"{self.titulo} - {self.ano}"

    @property
    def total_arquivos(self):
        """Total de arquivos em todas as pastas"""
        return TceArquivo.objects.filter(pasta__processo=self).count()

    @property
    def total_arquivos_prontos(self):
        """Total de arquivos prontos (≤5MB, OCR, assinados, com .p7s)"""
        return TceArquivo.objects.filter(
            pasta__processo=self,
            tamanho_ok=True,
            ocr_ok=True,
            assinado=True,
            p7s_gerado=True
        ).count()

    @property
    def progresso_percent(self):
        """Percentual de conclusão"""
        total = self.total_arquivos
        if total == 0:
            return 0
        return int((self.total_arquivos_prontos / total) * 100)


class TcePasta(models.Model):
    """
    Pasta/Categoria dentro de um processo
    (ex: Financeiro, Administrativa, Legislativa)
    """
    CATEGORIA_CHOICES = [
        ('financeiro', _('Financeiro - Gestão Orçamentária')),
        ('administrativo', _('Administrativo - Gestão Administrativa')),
        ('legislativo', _('Legislativo - Gestão Legislativa')),
        ('outros', _('Outros')),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    processo = models.ForeignKey(TceProcesso, on_delete=models.CASCADE, related_name='pastas')
    nome = models.CharField(_('Nome da Pasta'), max_length=200)
    categoria = models.CharField(_('Categoria'), max_length=20, choices=CATEGORIA_CHOICES)
    descricao = models.TextField(_('Descrição'), blank=True)
    ordem = models.IntegerField(_('Ordem de Exibição'), default=0)

    criado_em = models.DateTimeField(_('Criado em'), auto_now_add=True)

    class Meta:
        verbose_name = _('Pasta TCE')
        verbose_name_plural = _('Pastas TCE')
        ordering = ['processo', 'ordem', 'nome']
        unique_together = [['processo', 'nome']]

    def __str__(self):
        return f"{self.processo.titulo} / {self.nome}"

    @property
    def total_arquivos(self):
        return self.arquivos.count()

    @property
    def total_arquivos_prontos(self):
        return self.arquivos.filter(
            tamanho_ok=True,
            ocr_ok=True,
            assinado=True,
            p7s_gerado=True
        ).count()

    @property
    def icone(self):
        """Ícone FontAwesome baseado na categoria"""
        icones = {
            'financeiro': 'fa-coins',
            'administrativo': 'fa-building',
            'legislativo': 'fa-landmark',
            'outros': 'fa-folder'
        }
        return icones.get(self.categoria, 'fa-folder')

    @property
    def cor(self):
        """Cor do badge baseado na categoria"""
        cores = {
            'financeiro': 'primary',
            'administrativo': 'info',
            'legislativo': 'success',
            'outros': 'secondary'
        }
        return cores.get(self.categoria, 'secondary')


class TceArquivo(models.Model):
    """
    Arquivo PDF ou XML dentro de uma pasta
    Rastreia todas as etapas: tamanho, OCR, assinatura, .p7s
    """
    TIPO_CHOICES = [
        ('pdf', 'PDF'),
        ('xml', 'XML'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pasta = models.ForeignKey(TcePasta, on_delete=models.CASCADE, related_name='arquivos')
    subpasta = models.CharField(_('Subpasta'), max_length=255, blank=True,
                                help_text=_('Nome da subpasta dentro da pasta (ex: Balancetes mensais)'))

    # Arquivo original
    arquivo = models.FileField(_('Arquivo'), upload_to='tce/arquivos/%Y/%m/')
    nome_original = models.CharField(_('Nome Original'), max_length=255)
    nome_sugerido = models.CharField(_('Nome Sugerido (Padrão TCE)'), max_length=255, blank=True)
    tipo = models.CharField(_('Tipo'), max_length=10, choices=TIPO_CHOICES)

    # Tamanho
    tamanho_bytes = models.BigIntegerField(_('Tamanho (bytes)'), default=0)
    tamanho_mb = models.FloatField(_('Tamanho (MB)'), default=0)
    tamanho_ok = models.BooleanField(_('Tamanho ≤ 5MB'), default=False)

    # Arquivo reduzido (se necessário)
    arquivo_reduzido = models.FileField(_('Arquivo Reduzido'), upload_to='tce/reduzidos/%Y/%m/',
                                        blank=True, null=True)
    tamanho_reduzido_mb = models.FloatField(_('Tamanho Reduzido (MB)'), null=True, blank=True)

    # OCR
    ocr_aplicado = models.BooleanField(_('OCR Aplicado'), default=False)
    ocr_ok = models.BooleanField(_('OCR OK (Pesquisável)'), default=False)
    arquivo_ocr = models.FileField(_('Arquivo com OCR'), upload_to='tce/ocr/%Y/%m/',
                                   blank=True, null=True)

    # Assinatura Digital
    assinado = models.BooleanField(_('Assinado'), default=False)
    arquivo_assinado = models.FileField(_('Arquivo Assinado'), upload_to='tce/assinados/%Y/%m/',
                                        blank=True, null=True)
    certificado_info = JSONField(_('Informações do Certificado'), default=dict, blank=True)

    # Arquivo .p7s
    p7s_gerado = models.BooleanField(_('.p7s Gerado'), default=False)
    arquivo_p7s = models.FileField(_('Arquivo .p7s'), upload_to='tce/p7s/%Y/%m/',
                                   blank=True, null=True)

    # Hash e validação
    hash_sha256 = models.CharField(_('Hash SHA-256'), max_length=64, blank=True)
    validado = models.BooleanField(_('Validado (Pronto para Envio)'), default=False)

    # Metadados
    metadados = JSONField(_('Metadados'), default=dict, blank=True)

    # Auditoria
    criado_em = models.DateTimeField(_('Criado em'), auto_now_add=True)
    atualizado_em = models.DateTimeField(_('Atualizado em'), auto_now=True)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                     related_name='arquivos_tce_enviados')

    class Meta:
        verbose_name = _('Arquivo TCE')
        verbose_name_plural = _('Arquivos TCE')
        ordering = ['pasta', 'nome_original']

    def __str__(self):
        return f"{self.nome_original}"

    @property
    def arquivo_final(self):
        """Retorna o arquivo mais recente/processado"""
        if self.arquivo_assinado:
            return self.arquivo_assinado
        elif self.arquivo_ocr:
            return self.arquivo_ocr
        elif self.arquivo_reduzido:
            return self.arquivo_reduzido
        return self.arquivo

    @property
    def status_geral(self):
        """Status geral do arquivo para exibição"""
        if self.validado:
            return 'validado'
        elif self.assinado and self.p7s_gerado:
            return 'quase_pronto'
        elif self.tamanho_ok and self.ocr_ok:
            return 'processado'
        elif not self.tamanho_ok:
            return 'tamanho_pendente'
        elif not self.ocr_ok:
            return 'ocr_pendente'
        return 'novo'

    @property
    def status_cor(self):
        """Cor do status"""
        cores = {
            'validado': 'success',
            'quase_pronto': 'info',
            'processado': 'primary',
            'tamanho_pendente': 'warning',
            'ocr_pendente': 'warning',
            'novo': 'secondary'
        }
        return cores.get(self.status_geral, 'secondary')

    def atualizar_validacao(self):
        """Atualiza flag de validação baseado nos critérios"""
        self.validado = (
            self.tamanho_ok and
            self.ocr_ok and
            self.assinado and
            self.p7s_gerado
        )
        self.save(update_fields=['validado'])


class TceAssinatura(models.Model):
    """
    Registro de cada assinatura aplicada em um arquivo
    Suporta múltiplos signatários
    """
    PAPEL_CHOICES = [
        ('presidente', _('Presidente')),
        ('ordenador', _('Ordenador de Despesas')),
        ('contador', _('Contador')),
        ('controlador', _('Controlador Interno')),
        ('procurador', _('Procurador')),
        ('outros', _('Outros')),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    arquivo = models.ForeignKey(TceArquivo, on_delete=models.CASCADE, related_name='assinaturas')

    ordem = models.IntegerField(_('Ordem da Assinatura'), default=1)
    papel = models.CharField(_('Papel do Assinante'), max_length=20, choices=PAPEL_CHOICES)

    # Dados do certificado
    certificado_tipo = models.CharField(_('Tipo de Certificado'), max_length=10,
                                        choices=[('A1', 'A1'), ('A3', 'A3')])
    certificado_serial = models.CharField(_('Serial do Certificado'), max_length=100, blank=True)
    certificado_nome = models.CharField(_('Nome no Certificado'), max_length=255, blank=True)
    certificado_validade = models.DateField(_('Validade do Certificado'), null=True, blank=True)

    # Validação
    valida = models.BooleanField(_('Assinatura Válida'), default=True)
    cadeia_icp_ok = models.BooleanField(_('Cadeia ICP Válida'), default=False)
    carimbo_tempo = models.BooleanField(_('Carimbo de Tempo Presente'), default=False)
    ltv = models.BooleanField(_('LTV (Long Term Validation)'), default=False)

    # Hash
    hash_assinatura = models.CharField(_('Hash da Assinatura'), max_length=64, blank=True)

    # Auditoria
    assinado_em = models.DateTimeField(_('Assinado em'), auto_now_add=True)
    assinado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                      related_name='assinaturas_realizadas')

    class Meta:
        verbose_name = _('Assinatura Digital')
        verbose_name_plural = _('Assinaturas Digitais')
        ordering = ['arquivo', 'ordem']

    def __str__(self):
        return f"{self.arquivo.nome_original} - {self.get_papel_display()} ({self.ordem}ª)"


class TceLog(models.Model):
    """
    Log completo de todas as ações no processo
    Para auditoria e linha do tempo
    """
    TIPO_CHOICES = [
        ('processo_criado', _('Processo Criado')),
        ('pasta_criada', _('Pasta Criada')),
        ('arquivo_upload', _('Upload de Arquivo')),
        ('arquivo_reduzido', _('Arquivo Reduzido')),
        ('ocr_aplicado', _('OCR Aplicado')),
        ('arquivo_assinado', _('Arquivo Assinado')),
        ('p7s_gerado', _('Arquivo .p7s Gerado')),
        ('processo_validado', _('Processo Validado')),
        ('processo_enviado', _('Processo Enviado ao TCE')),
        ('recibo_recebido', _('Recibo TCE Recebido')),
        ('erro', _('Erro')),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    processo = models.ForeignKey(TceProcesso, on_delete=models.CASCADE, related_name='logs')
    arquivo = models.ForeignKey(TceArquivo, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='logs')

    tipo = models.CharField(_('Tipo de Evento'), max_length=30, choices=TIPO_CHOICES)
    descricao = models.TextField(_('Descrição'))

    # Dados adicionais
    dados = JSONField(_('Dados do Evento'), default=dict, blank=True)
    sucesso = models.BooleanField(_('Sucesso'), default=True)
    erro_mensagem = models.TextField(_('Mensagem de Erro'), blank=True)

    # Auditoria
    ocorrido_em = models.DateTimeField(_('Ocorrido em'), auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                 related_name='logs_tce')
    ip = models.GenericIPAddressField(_('Endereço IP'), null=True, blank=True)

    class Meta:
        verbose_name = _('Log TCE')
        verbose_name_plural = _('Logs TCE')
        ordering = ['-ocorrido_em']

    def __str__(self):
        return f"{self.processo.titulo} - {self.get_tipo_display()} - {self.ocorrido_em.strftime('%d/%m/%Y %H:%M')}"
