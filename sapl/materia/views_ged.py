"""
View pública para acesso ao acervo histórico via GED (sistema legado).
Issue #1326 / Task #1348 – Adicionar tela do GED dentro do Legislativo.
"""
from decouple import config
from django.shortcuts import render
from django.views.decorators.cache import cache_control

# Sem default: se GED_URL não estiver no .env, retorna string vazia.
GED_URL = config('GED_URL', default='')


@cache_control(public=True, max_age=300)
def ged_historico(request):
    """
    Exibe o sistema GED (acervo histórico – matérias anteriores a 2026)
    incorporado em iframe. Acesso público, sem autenticação.
    Se GED_URL não estiver configurado, exibe mensagem informativa.
    """
    return render(request, 'materia/ged_historico.html', {
        'ged_url': GED_URL or '',
    })
