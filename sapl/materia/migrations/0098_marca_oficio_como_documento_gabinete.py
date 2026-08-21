import unicodedata

from django.db import migrations


# Tipos de proposição que já nascem como documento de gabinete, sem
# necessidade de configuração manual em Tabelas Auxiliares.
DESCRICOES_GABINETE = {'oficio'}


def _normalizar(descricao):
    """Remove acentos, espaços das pontas e caixa, para comparar descrições.

    A descrição é digitada pelo usuário em cada Casa, então aparece como
    'Ofício', 'OFICIO', 'oficio' etc.
    """
    texto = unicodedata.normalize('NFKD', descricao or '')
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return texto.strip().lower()


def _aplicar(apps, valor):
    TipoProposicao = apps.get_model('materia', 'TipoProposicao')
    for tipo in TipoProposicao.objects.all():
        if _normalizar(tipo.descricao) in DESCRICOES_GABINETE:
            tipo.dispensa_protocolo = valor
            tipo.save(update_fields=['dispensa_protocolo'])


def marcar(apps, schema_editor):
    _aplicar(apps, True)


def desmarcar(apps, schema_editor):
    _aplicar(apps, False)


class Migration(migrations.Migration):

    dependencies = [
        ('materia', '0097_add_dispensa_protocolo_tipoproposicao'),
    ]

    operations = [
        migrations.RunPython(marcar, desmarcar),
    ]
