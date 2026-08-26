from django.contrib.postgres.fields import JSONField
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

    operado_por = models.CharField(
        max_length=150,
        blank=True,
        verbose_name=_('Operado por'),
        help_text=_(
            'Rastro operacional: quem DISPAROU o ato (o próprio vereador ou um '
            'assessor agindo por ele). NÃO é a autoria jurídica — o signatário '
            'é sempre o vereador titular (assinatura é ato pessoal e '
            'indelegável). Hoje o evento do app ainda não carrega a identidade '
            'do assessor logado; até lá recebe o próprio titular.'))

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



class PassadaMaterializacao(models.Model):
    """Uma linha por passada do `materializar_pdfs_para_assinatura`.

    Existe porque a falha desta rotina é MUDA: matéria protocolada simplesmente
    não vira pendência no app, sem erro em lugar nenhum. Até 25/08/2026 o único
    jeito de saber o que ela fez era abrir o shell da VPS — o diagnóstico daquele
    dia consumiu três idas e voltas com o operador para descobrir o valor de uma
    variável de ambiente.

    O comando JÁ apurava todos estes contadores; eles morriam no `stdout` do
    processo. Aqui eles ficam, e a tela lê daqui.

    **`em_andamento` é o lock entre processos, não um mero estado.** É
    `NullBooleanField(unique=True)` e assume DOIS valores apenas: `True`
    enquanto a passada roda, `NULL` quando termina — nunca `False`. Em Postgres
    `NULL` não colide em índice único, então o banco garante sozinho que existe
    no máximo UMA passada em curso, seja ela do laço ou do botão. É esta
    garantia que permite disparar a rotina pela tela sem risco de duas
    conversões concorrentes do mesmo documento.
    """

    DISPARO_LACO = 'laco'
    DISPARO_MANUAL = 'manual'
    DISPARO_CHOICES = (
        (DISPARO_LACO, _('Laço automático')),
        (DISPARO_MANUAL, _('Disparo manual pela tela')),
    )

    iniciada_em = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Iniciada em'))

    terminada_em = models.DateTimeField(
        null=True, blank=True,
        verbose_name=_('Terminada em'))

    em_andamento = models.NullBooleanField(
        unique=True,
        default=True,
        verbose_name=_('Em andamento'),
        help_text=_('True enquanto roda, NULL quando termina. Nunca False: o '
                    'índice único sobre este campo é o que impede duas '
                    'passadas simultâneas.'))

    disparo = models.CharField(
        max_length=10,
        choices=DISPARO_CHOICES,
        default=DISPARO_LACO,
        verbose_name=_('Origem do disparo'))

    disparada_por = models.CharField(
        max_length=150,
        blank=True,
        verbose_name=_('Disparada por'),
        help_text=_('Usuário que clicou em "Rodar agora". Vazio no laço.'))

    somente_novos = models.BooleanField(
        default=False,
        verbose_name=_('Somente novos'),
        help_text=_('Passada que só gera alvo ausente e nunca retifica.'))

    gerados = models.IntegerField(default=0, verbose_name=_('Gerados'))
    retificados = models.IntegerField(default=0, verbose_name=_('Retificados'))
    em_dia = models.IntegerField(default=0, verbose_name=_('Em dia'))
    falhas = models.IntegerField(default=0, verbose_name=_('Falhas'))
    adiados = models.IntegerField(default=0, verbose_name=_('Adiados'))

    motivos = JSONField(
        default=dict, blank=True,
        verbose_name=_('Falhas por motivo'),
        help_text=_('Dicionário motivo -> quantas. É o que transforma 861 '
                    'logger.error dispersos numa linha que se lê.'))

    abandonada = models.BooleanField(
        default=False,
        verbose_name=_('Abandonada'),
        help_text=_('Passada cujo processo morreu sem fechar a linha (kill, '
                    'reboot). Fechada pela passada seguinte para destravar o '
                    'lock — os contadores dela ficam incompletos.'))

    class Meta:
        verbose_name = _('Passada de Materialização')
        verbose_name_plural = _('Passadas de Materialização')
        ordering = ('-iniciada_em',)

    def __str__(self):
        return 'Passada %s (%s)' % (self.pk, self.iniciada_em)

    @property
    def duracao(self):
        if not self.terminada_em:
            return None
        return self.terminada_em - self.iniciada_em

    @property
    def motivo_predominante(self):
        """O motivo que derruba o lote — o que precisa gritar na tela.

        Falha isolada é ruído esperado (§5.1); o que interessa ao operador é o
        motivo único que explica a maioria das falhas.
        """
        if not self.motivos:
            return None, 0
        return max(self.motivos.items(), key=lambda par: par[1])


class MateriaComFalhaMaterializacao(models.Model):
    """As matérias travadas AGORA — uma linha por matéria, não por tentativa.

    Deliberadamente NÃO é histórico: a passada seguinte reescreve a linha e o
    sucesso a apaga. A pergunta que o operador faz é "quais estão travadas e
    por quê", e um log de tentativas responde isso mal — com 861 matérias
    falhando a cada 5 minutos, histórico vira ruído que cresce sozinho.
    """

    materia = models.OneToOneField(
        'materia.MateriaLegislativa',
        on_delete=models.CASCADE,
        related_name='falha_materializacao',
        verbose_name=_('Matéria Legislativa'))

    motivo = models.TextField(verbose_name=_('Motivo'))

    ocorrido_em = models.DateTimeField(
        auto_now=True,
        verbose_name=_('Última ocorrência'))

    class Meta:
        verbose_name = _('Matéria com Falha de Materialização')
        verbose_name_plural = _('Matérias com Falha de Materialização')
        ordering = ('materia_id',)

    def __str__(self):
        return 'Matéria %s: %s' % (self.materia_id, self.motivo)
