# Generated migration for digital signature fields

from django.conf import settings
from django.contrib.postgres.fields import JSONField
from django.db import migrations, models
import django.db.models.deletion

import sapl.materia.models
import sapl.utils


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('materia', '0087_update_viewdb_materiaemtramitacao'),
    ]

    operations = [
        migrations.AddField(
            model_name='materialegislativa',
            name='pdf_assinado',
            field=models.FileField(
                blank=True,
                max_length=300,
                null=True,
                storage=sapl.utils.OverwriteStorage(),
                upload_to=sapl.materia.models.materia_upload_path,
                verbose_name='PDF Assinado'
            ),
        ),
        migrations.AddField(
            model_name='materialegislativa',
            name='assinatura_info',
            field=JSONField(
                blank=True,
                help_text='Metadados do certificado digital usado na assinatura',
                null=True,
                verbose_name='Informações da Assinatura'
            ),
        ),
        migrations.AddField(
            model_name='materialegislativa',
            name='assinado_em',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Data/Hora da Assinatura'
            ),
        ),
        migrations.AddField(
            model_name='materialegislativa',
            name='assinado_por',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='materias_assinadas',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Assinado por'
            ),
        ),
    ]
