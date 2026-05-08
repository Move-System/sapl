import logging

from django.utils.translation import ugettext_lazy as _

from sapl.utils import google_recaptcha_configured as \
    google_recaptcha_configured_utils, sapn_is_enabled, cached_call, get_base_url
from sapl.utils import mail_service_configured as mail_service_configured_utils


def parliament_info(request):
    from sapl.base.views import get_casalegislativa
    casa = get_casalegislativa()
    if casa:
        return casa.__dict__
    else:
        return {}


def mail_service_configured(request):
    if not mail_service_configured_utils(request):
        logger = logging.getLogger(__name__)
        logger.warning(_('Servidor de email não configurado.'))
        return {'mail_service_configured': False}
    return {'mail_service_configured': True}


def google_recaptcha_configured(request):
    if not google_recaptcha_configured_utils():
        logger = logging.getLogger(__name__)
        logger.warning(_('Google Recaptcha não configurado.'))
        return {'google_recaptcha_configured': False}
    return {'google_recaptcha_configured': True}


def pendencias_assinatura(request):
    """Injeta contagem e URL de matérias pendentes de assinatura para o usuário logado."""
    if not request.user.is_authenticated:
        return {'pendencias_assinatura_total': 0, 'pendencias_assinatura_url': ''}

    from django.core.cache import cache
    cache_key = f'pendencias_assinatura_user_{request.user.pk}'
    cached = cache.get(cache_key)

    if cached is None:
        try:
            from django.db.models import Q
            from django.urls import reverse
            from sapl.materia.models import MateriaLegislativa
            from sapl.base.models import OperadorAutor

            # Busca o Autor vinculado ao usuário
            try:
                autor = OperadorAutor.objects.get(user=request.user).autor
                autor_pk = autor.pk
            except OperadorAutor.DoesNotExist:
                autor_pk = None

            if autor_pk:
                total = MateriaLegislativa.objects.filter(
                    autoria__autor_id=autor_pk,
                    texto_original__isnull=False,
                ).exclude(
                    texto_original=''
                ).filter(
                    Q(pdf_assinado__isnull=True) | Q(pdf_assinado='')
                ).distinct().count()
                url = (
                    reverse('sapl.materia:pesquisar_materia')
                    + f'?autoria__autor={autor_pk}&status_assinatura=pendente'
                )
            else:
                total = 0
                url = ''
        except Exception:
            total = 0
            url = ''

        cached = {'total': total, 'url': url}
        cache.set(cache_key, cached, 120)  # cache de 2 minutos

    return {
        'pendencias_assinatura_total': cached['total'],
        'pendencias_assinatura_url': cached['url'],
    }


@cached_call("site-title", timeout=60 * 2)
def enable_sapn(request):
    verbose_name = _('SGVP') \
        if not sapn_is_enabled() \
        else _('Sistema de Gestão e Votação Parlamentar')

    from sapl.base.models import CasaLegislativa
    casa_legislativa = CasaLegislativa.objects.first()
    nome_casa = casa_legislativa.nome if casa_legislativa and casa_legislativa.nome else ''

    return {
        'sapl_as_sapn': sapn_is_enabled(),
        'nome_sistema': verbose_name,
        'nome_casa': nome_casa,
        'base_url': get_base_url(request),
    }
