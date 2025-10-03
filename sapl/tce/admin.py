"""
Admin do módulo TCE
"""
from django.contrib import admin
from django.utils.html import format_html
from .models import TceProcesso, TcePasta, TceArquivo, TceAssinatura, TceLog


# Modelos TCE não são mais acessíveis via Django Admin
# Acesse através de /tce/admin/ para o dashboard customizado
