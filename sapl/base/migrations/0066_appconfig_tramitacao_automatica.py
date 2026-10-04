from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('materia', '0098_marca_oficio_como_documento_gabinete'),
        ('base', '0065_add_permite_remover_assinatura_e_permissoes'),
    ]

    operations = [
        migrations.AddField(
            model_name='appconfig',
            name='tramitacao_automatica_tipo_documento',
            field=models.ForeignKey(
                blank=True,
                default=None,
                help_text='Ao assinar digitalmente um documento acessório deste tipo, a matéria recebe uma nova tramitação automaticamente. Use, por exemplo, o Parecer Jurídico. Em branco, nada é automatizado.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='appconfig_gatilho_tramitacao',
                to='materia.TipoDocumento',
                verbose_name='Tipo de documento que dispara a tramitação'),
        ),
        migrations.AddField(
            model_name='appconfig',
            name='tramitacao_automatica_status',
            field=models.ForeignKey(
                blank=True,
                default=None,
                help_text='Status que a matéria assume quando o documento acima é assinado. Use, por exemplo, Aguardando inserção na sessão.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='appconfig_gatilho_tramitacao',
                to='materia.StatusTramitacao',
                verbose_name='Status aplicado pela tramitação automática'),
        ),
        migrations.AddField(
            model_name='appconfig',
            name='tramitacao_automatica_unidade_destino',
            field=models.ForeignKey(
                blank=True,
                default=None,
                help_text='Para onde a matéria é encaminhada. A unidade de origem não é configurável: é sempre o destino da última tramitação, para não quebrar a corrente do histórico.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='appconfig_gatilho_tramitacao',
                to='materia.UnidadeTramitacao',
                verbose_name='Unidade de destino da tramitação automática'),
        ),
    ]
