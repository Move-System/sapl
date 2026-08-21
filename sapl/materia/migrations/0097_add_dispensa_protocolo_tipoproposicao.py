from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('materia', '0096_add_permite_remover_assinatura_e_permissoes'),
    ]

    operations = [
        migrations.AddField(
            model_name='tipoproposicao',
            name='dispensa_protocolo',
            field=models.BooleanField(
                default=False,
                help_text='Quando marcado, proposições deste tipo não são enviadas ao Protocolo e não se tornam Matéria Legislativa. Ficam restritas ao gabinete do autor. Use para documentos de uso próprio do gabinete, como Ofícios, que não precisam de validação da Casa.',
                verbose_name='Documento de gabinete'),
        ),
    ]
