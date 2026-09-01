from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('materia', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='EventoRecebido',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name='ID')),
                ('chave_idempotencia', models.UUIDField(
                    unique=True, verbose_name='Chave de Idempotência')),
                ('recebido_em', models.DateTimeField(
                    auto_now_add=True, verbose_name='Recebido em')),
                ('proposicao', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='+',
                    to='materia.Proposicao',
                    verbose_name='Proposição')),
            ],
            options={
                'verbose_name': 'Evento Recebido do Hub',
                'verbose_name_plural': 'Eventos Recebidos do Hub',
                'permissions': (
                    ('pode_integrar', 'Pode operar a integração com o hub'),
                ),
            },
        ),
    ]
