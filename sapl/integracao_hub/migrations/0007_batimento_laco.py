from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integracao_hub', '0006_fila_prioridade_materializacao'),
    ]

    operations = [
        migrations.CreateModel(
            name='BatimentoLaco',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('visto_em', models.DateTimeField(verbose_name='Último batimento')),
                ('iniciado_em', models.DateTimeField(verbose_name='Laço iniciado em')),
                ('pid', models.IntegerField(verbose_name='PID do processo do laço')),
                ('tick_segundos', models.IntegerField(default=15, help_text='Gravado pelo próprio laço: é a referência para decidir se o batimento envelheceu.', verbose_name='Tick configurado (s)')),
            ],
            options={
                'verbose_name': 'Batimento do Laço de Materialização',
                'verbose_name_plural': 'Batimentos do Laço de Materialização',
            },
        ),
    ]
