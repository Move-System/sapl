from django.db import models
from django.utils.translation import ugettext_lazy as _


class EventoRecebido(models.Model):
    """Dedupe do Componente A (spec §3): uma linha por evento entregue pelo hub.

    Chave repetida significa reentrega — a resposta devolve a proposição já
    criada, sem efeito colateral. Nada além do mínimo do dedupe persiste aqui
    (spec §6).
    """

    chave_idempotencia = models.UUIDField(
        unique=True,
        verbose_name=_('Chave de Idempotência'))

    proposicao = models.ForeignKey(
        'materia.Proposicao',
        on_delete=models.PROTECT,
        related_name='+',
        verbose_name=_('Proposição'))

    recebido_em = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Recebido em'))

    class Meta:
        verbose_name = _('Evento Recebido do Hub')
        verbose_name_plural = _('Eventos Recebidos do Hub')
        permissions = (
            ('pode_integrar', _('Pode operar a integração com o hub')),
        )

    def __str__(self):
        return str(self.chave_idempotencia)


def _caminho_anexo(instancia, nome):
    return 'integracao_hub/proposicao_%s/%s' % (instancia.proposicao_id, nome)


def _caminho_pdf_alvo(instancia, nome):
    return 'integracao_hub/materia_%s/%s' % (instancia.materia_id, nome)


class DocumentoParaAssinatura(models.Model):
    """O PDF-alvo persistido da matéria — o invariante do documento único (§5).

    O PDF que o SAPL assina, o que o app exibe e o que aparece assinado são o
    MESMO binário: gerado uma única vez pela materialização (management command
    `materializar_pdfs_para_assinatura`) e referenciado por hash em cada salto.
    Vive neste app isolado, não em `MateriaLegislativa`, pelo mesmo racional do
    `AnexoProposicao`: custo zero de rebase do fork (refinamento §10).

    `hash_origem` é o sha256 do `texto_original` usado na geração — é ele que
    detecta retificação: mudou o texto depois da conversão, o alvo está defasado
    e o processo de assinatura zera (decisão do arquiteto 19/08, §5.1).
    """

    materia = models.OneToOneField(
        'materia.MateriaLegislativa',
        on_delete=models.PROTECT,
        related_name='documento_para_assinatura',
        verbose_name=_('Matéria Legislativa'))

    arquivo = models.FileField(
        upload_to=_caminho_pdf_alvo,
        verbose_name=_('PDF-alvo da assinatura'))

    hash_sha256 = models.CharField(
        max_length=64,
        verbose_name=_('SHA-256 do PDF-alvo'))

    hash_origem = models.CharField(
        max_length=64,
        verbose_name=_('SHA-256 do texto_original usado na geração'))

    gerado_em = models.DateTimeField(
        auto_now=True,
        verbose_name=_('Gerado em'))

    class Meta:
        verbose_name = _('Documento para Assinatura')
        verbose_name_plural = _('Documentos para Assinatura')

    def __str__(self):
        return 'PDF-alvo da matéria %s' % self.materia_id


class AssinaturaRecebida(models.Model):
    """Dedupe do `POST /api/integracao/assinaturas/` — padrão do EventoRecebido.

    Uma linha por assinatura entregue pelo hub; chave repetida é reentrega e
    devolve a mesma resposta sem efeito colateral. `hash_assinado` fica aqui
    para a reentrega responder o que a primeira entrega respondeu. A linha
    também marca a ORIGEM da gravação (anti-eco do refinamento §5.1): o hub
    correlaciona o que ele mesmo entregou.
    """

    chave_idempotencia = models.UUIDField(
        unique=True,
        verbose_name=_('Chave de Idempotência'))

    materia = models.ForeignKey(
        'materia.MateriaLegislativa',
        on_delete=models.PROTECT,
        related_name='+',
        verbose_name=_('Matéria Legislativa'))

    hash_assinado = models.CharField(
        max_length=64,
        verbose_name=_('SHA-256 do PDF assinado recebido'))

    recebido_em = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Recebido em'))

    class Meta:
        verbose_name = _('Assinatura Recebida do Hub')
        verbose_name_plural = _('Assinaturas Recebidas do Hub')

    def __str__(self):
        return str(self.chave_idempotencia)


class AnexoProposicao(models.Model):
    """Anexo GERAL vindo do app (foto, vídeo, qualquer mídia) — não é o texto oficial.

    Decisão do arquiteto (17/08/2026): o que o vereador anexa no app é evidência da
    demanda (foto da rua, vídeo da indicação), não o documento legislativo — este o SAPL
    continua gerando pelo fluxo próprio (texto_original). Por ora só GRAVA, sem tela: a
    consulta vem depois. Vive neste app isolado para custo zero de rebase do fork.

    O hash é calculado AQUI, dos bytes recebidos: é o SAPL dizendo o que ele guardou,
    fechando a cadeia app -> hub -> legislativo (o hub confere o hash do app antes de
    entregar; nós registramos o que chegou).
    """

    proposicao = models.ForeignKey(
        'materia.Proposicao',
        on_delete=models.PROTECT,
        related_name='anexos_do_app',
        verbose_name=_('Proposição'))

    arquivo = models.FileField(
        upload_to=_caminho_anexo,
        verbose_name=_('Arquivo'))

    nome_original = models.CharField(
        max_length=255,
        verbose_name=_('Nome original'))

    mime = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_('Tipo MIME'))

    tamanho_bytes = models.BigIntegerField(
        verbose_name=_('Tamanho (bytes)'))

    hash_sha256 = models.CharField(
        max_length=64,
        verbose_name=_('SHA-256 dos bytes recebidos'))

    recebido_em = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Recebido em'))

    class Meta:
        verbose_name = _('Anexo de Proposição (app)')
        verbose_name_plural = _('Anexos de Proposição (app)')

    def __str__(self):
        return '%s (%s)' % (self.nome_original, self.proposicao_id)

