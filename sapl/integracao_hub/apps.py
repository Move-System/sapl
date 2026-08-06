from django.apps import AppConfig
from django.utils.translation import ugettext_lazy as _


class IntegracaoHubConfig(AppConfig):
    name = 'sapl.integracao_hub'
    label = 'integracao_hub'
    verbose_name = _('Integração com o Hub')
