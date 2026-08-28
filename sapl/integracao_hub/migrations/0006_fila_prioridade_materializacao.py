import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('materia', '0094_add_anexoproposicao'),
        ('integracao_hub', '0005_painel_materializacao'),
    ]

    operations = [
        migrations.AlterField(
            model_name='passadamaterializacao',
            name='disparo',
            field=models.CharField(choices=[('laco', 'Laço automático'), ('manual', 'Disparo manual pela tela'), ('prioridade', 'Fila de prioridade')], default='laco', max_length=10, verbose_name='Origem do disparo'),
        ),
        migrations.CreateModel(
            name='MateriaParaMaterializar',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('marcada_em', models.DateTimeField(help_text='Avança a cada remarcação. O tick de prioridade só remove a marca se ela não avançou depois da leitura — retificação no meio da conversão não se perde.', verbose_name='Marcada em')),
                ('materia', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='materia.MateriaLegislativa', verbose_name='Matéria Legislativa')),
            ],
            options={
                'verbose_name': 'Matéria na Fila de Materialização',
                'verbose_name_plural': 'Matérias na Fila de Materialização',
                'ordering': ('marcada_em', 'materia_id'),
            },
        ),
    ]
