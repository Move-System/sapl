from django import template

register = template.Library()

@register.filter(name='get_item')
def get_item(dictionary, key):
    """Template filter para acessar itens de dicionário"""
    return dictionary.get(key, [])


@register.filter(name='subpasta_count')
def subpasta_count(queryset, subpasta_nome):
    """
    Conta arquivos de uma subpasta específica
    Uso: {{ pasta.arquivos.all|subpasta_count:subpasta }}
    """
    if not queryset:
        return 0
    return queryset.filter(subpasta=subpasta_nome).count()
