from django import template

register = template.Library()

@register.filter(name='get_item')
def get_item(dictionary, key):
    """Template filter para acessar itens de dicionário"""
    return dictionary.get(key, [])
