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
