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
    from sapl.materia.pendencias import CACHE_KEY, CACHE_TTL

    cache_key = CACHE_KEY.format(request.user.pk)
    cached = cache.get(cache_key)

    if cached is None:
        try:
            from django.urls import reverse
            from sapl.materia.models import MateriaLegislativa
            from sapl.materia.pendencias import (
                autores_do_usuario, filtrar_pendentes)

            # Pendência é POR AUTOR: a matéria que um coautor já assinou segue
            # pendente para os demais. Contar `pdf_assinado` vazio — como se
            # fazia aqui — zerava o badge do coautor na primeira assinatura.
            autores = autores_do_usuario(request.user)

            if autores:
                total = filtrar_pendentes(
                    MateriaLegislativa.objects.all(), autores=autores).count()
                # A URL leva ao mesmo recorte: um autor por vez na pesquisa, o
                # primeiro deles (o assessor de dois vereadores vê o total no
                # badge e refina na tela).
                url = (
                    reverse('sapl.materia:pesquisar_materia')
                    + f'?autoria__autor={autores[0].pk}&status_assinatura=pendente'
                )
            else:
                total = 0
                url = ''
        except Exception:
            logging.getLogger(__name__).exception(
                'Falha ao calcular pendências de assinatura')
            total = 0
            url = ''

        cached = {'total': total, 'url': url}
        cache.set(cache_key, cached, CACHE_TTL)

    return {
        'pendencias_assinatura_total': cached['total'],
        'pendencias_assinatura_url': cached['url'],
    }


def ged_configurado(request):
    """Injeta flag indicando se o GED (acervo histórico) está configurado."""
    from sapl.materia.views_ged import GED_URL
    return {'ged_configurado': bool(GED_URL)}


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
