"""Marca a matéria para materialização imediata — o lado 'evento' do ADR 0014.

O `post_save` de `MateriaLegislativa` é deliberadamente o ÚNICO ponto de escuta:
todos os caminhos que interessam (protocolo efetivado, texto_original salvo ou
retificado, proposição incorporada, edição pelo CRUD) terminam num save da
matéria. Escutar cada view seria uma lista que envelhece; escutar o modelo é uma
linha que não envelhece.

O receiver só grava a marca (um upsert) — quem converte é o laço do
`materializar_pdfs_para_assinatura`, no tick de prioridade. O request nunca
paga a conversão OnlyOffice (§5.1: a conversão tem UM dono).
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from sapl.materia.models import MateriaLegislativa

logger = logging.getLogger(__name__)


@receiver(post_save, sender=MateriaLegislativa,
          dispatch_uid='integracao_hub_marcar_para_materializar')
def marcar_para_materializar(sender, instance, raw=False, **kwargs):
    # A retificação feita pela PRÓPRIA rotina salva a matéria (zera a
    # assinatura, §5.1) — remarcar aqui criaria um ciclo: cada passada
    # alimentaria a fila que ela mesma consome.
    if getattr(instance, '_materializacao_em_curso', False):
        return
    if raw:  # loaddata/fixtures não é evento de negócio
        return
    # Só matéria que a materialização enxerga (mesmo filtro da varredura):
    # protocolada e com texto. As demais entrariam na fila para o tick
    # descartar — ruído puro.
    if not instance.numero_protocolo or not instance.texto_original:
        return
    from sapl.integracao_hub.models import MateriaParaMaterializar
    try:
        MateriaParaMaterializar.objects.update_or_create(
            materia=instance,
            defaults={'marcada_em': timezone.now()})
    except Exception as exc:  # noqa — a marca é aceleração, não requisito:
        # falhar aqui NUNCA pode derrubar o save da matéria; a varredura
        # completa (rede de segurança) materializa no ciclo dela.
        logger.warning(
            'integracao_hub: falha ao marcar matéria %s para materialização '
            '(%s) — a varredura completa cobre', instance.pk, exc)
