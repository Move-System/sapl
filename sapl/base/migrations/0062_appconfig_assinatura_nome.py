from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('base', '0061_documenttemplate'),
    ]

    operations = [
        migrations.AddField(
            model_name='appconfig',
            name='assinatura_nome',
            field=models.CharField(
                choices=[('P', 'Nome Político (Parlamentar)'), ('C', 'Nome Civil (Real)')],
                default='P',
                max_length=1,
                verbose_name='Nome utilizado na assinatura digital',
            ),
        ),
    ]
