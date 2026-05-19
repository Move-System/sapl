"""
View pública para acesso ao acervo histórico via GED (sistema legado).
Issue #1326 / Task #1348 – Adicionar tela do GED dentro do Legislativo.
"""
from django.shortcuts import render
from django.views.decorators.cache import cache_control

GED_URL = "https://franco-ged.up.railway.app/"


@cache_control(public=True, max_age=300)
def ged_historico(request):
    """
    Exibe o sistema GED (acervo histórico – matérias anteriores a 2026)
    incorporado em iframe. Acesso público, sem autenticação.
    """
    return render(request, 'materia/ged_historico.html', {
        'ged_url': GED_URL,
    })
