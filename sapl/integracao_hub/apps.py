from django.apps import AppConfig
from django.utils.translation import ugettext_lazy as _


class IntegracaoHubConfig(AppConfig):
    name = 'sapl.integracao_hub'
    label = 'integracao_hub'
    verbose_name = _('Integração com o Hub')

    def ready(self):
        # Liga o receiver que alimenta a fila de prioridade da materialização
        # (ADR 0014). Padrão do sapl.base: importar registra os @receiver.
        from sapl.integracao_hub import receivers  # noqa
