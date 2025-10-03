# Generated manually on 2025-10-02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tce', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='tcearquivo',
            name='subpasta',
            field=models.CharField(blank=True, help_text='Nome da subpasta dentro da pasta (ex: Balancetes mensais)', max_length=255, verbose_name='Subpasta'),
        ),
    ]
