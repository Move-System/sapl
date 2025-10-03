# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tce', '0002_tcearquivo_subpasta'),
    ]

    operations = [
        migrations.AddField(
            model_name='tcepasta',
            name='subpastas_customizadas',
            field=models.TextField(blank=True, default='[]', help_text='JSON: Lista de subpastas adicionadas pelo usuário além das padrões', verbose_name='Subpastas Customizadas'),
        ),
    ]
