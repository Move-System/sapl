import django.contrib.postgres.fields.jsonb
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('materia', '0094_add_anexoproposicao'),
        ('integracao_hub', '0004_assinaturarecebida_operado_por'),
    ]

    operations = [
        migrations.CreateModel(
            name='PassadaMaterializacao',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('iniciada_em', models.DateTimeField(auto_now_add=True, verbose_name='Iniciada em')),
                ('terminada_em', models.DateTimeField(blank=True, null=True, verbose_name='Terminada em')),
                ('em_andamento', models.NullBooleanField(default=True, help_text='True enquanto roda, NULL quando termina. Nunca False: o índice único sobre este campo é o que impede duas passadas simultâneas.', unique=True, verbose_name='Em andamento')),
                ('disparo', models.CharField(choices=[('laco', 'Laço automático'), ('manual', 'Disparo manual pela tela')], default='laco', max_length=10, verbose_name='Origem do disparo')),
                ('disparada_por', models.CharField(blank=True, help_text='Usuário que clicou em "Rodar agora". Vazio no laço.', max_length=150, verbose_name='Disparada por')),
                ('somente_novos', models.BooleanField(default=False, help_text='Passada que só gera alvo ausente e nunca retifica.', verbose_name='Somente novos')),
                ('gerados', models.IntegerField(default=0, verbose_name='Gerados')),
                ('retificados', models.IntegerField(default=0, verbose_name='Retificados')),
                ('em_dia', models.IntegerField(default=0, verbose_name='Em dia')),
                ('falhas', models.IntegerField(default=0, verbose_name='Falhas')),
                ('adiados', models.IntegerField(default=0, verbose_name='Adiados')),
                ('motivos', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=dict, help_text='Dicionário motivo -> quantas. É o que transforma 861 logger.error dispersos numa linha que se lê.', verbose_name='Falhas por motivo')),
                ('abandonada', models.BooleanField(default=False, help_text='Passada cujo processo morreu sem fechar a linha (kill, reboot). Fechada pela passada seguinte para destravar o lock — os contadores dela ficam incompletos.', verbose_name='Abandonada')),
            ],
            options={
                'verbose_name': 'Passada de Materialização',
                'verbose_name_plural': 'Passadas de Materialização',
                'ordering': ('-iniciada_em',),
            },
        ),
        migrations.CreateModel(
            name='MateriaComFalhaMaterializacao',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('motivo', models.TextField(verbose_name='Motivo')),
                ('ocorrido_em', models.DateTimeField(auto_now=True, verbose_name='Última ocorrência')),
                ('materia', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='falha_materializacao', to='materia.MateriaLegislativa', verbose_name='Matéria Legislativa')),
            ],
            options={
                'verbose_name': 'Matéria com Falha de Materialização',
                'verbose_name_plural': 'Matérias com Falha de Materialização',
                'ordering': ('materia_id',),
            },
        ),
    ]
