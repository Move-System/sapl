from decouple import config
from django.db import migrations, models

# Até aqui a integração lia o .env (SESSAO_MATERIAS_API_URL/KEY) e anexava
# o caminho do SGVP à URL. A configuração passa para a tela; esta carga leva
# os valores que existirem, para a Casa não perder o envio no deploy.
CAMINHO_SGVP = '/api/integracaoLegisSessao'


def carrega_do_ambiente(apps, schema_editor):
    url_base = config('SESSAO_MATERIAS_API_URL', default='').strip()
    if not url_base:
        return

    api_key = config('SESSAO_MATERIAS_API_KEY', default='').strip()

    AppConfig = apps.get_model('base', 'AppConfig')
    appconfig = AppConfig.objects.order_by('-id').first() or AppConfig()
    appconfig.painel_externo_url = url_base.rstrip('/') + CAMINHO_SGVP
    appconfig.painel_externo_api_key = api_key
    # o SGVP recusa o envio sem chave; sem ela, a Casa liga pela tela
    appconfig.painel_externo_ativo = bool(api_key)
    appconfig.save()


class Migration(migrations.Migration):

    dependencies = [
        ('base', '0066_appconfig_tramitacao_automatica'),
    ]

    operations = [
        migrations.AddField(
            model_name='appconfig',
            name='painel_externo_ativo',
            field=models.BooleanField(
                choices=[(True, 'Sim'), (False, 'Não')],
                default=False,
                verbose_name='Enviar a pauta da sessão a painel de votação externo?'),
        ),
        migrations.AddField(
            model_name='appconfig',
            name='painel_externo_url',
            field=models.URLField(
                blank=True,
                default='',
                help_text='Endereço completo do endpoint do painel que recebe a pauta, por exemplo https://painel.exemplo.leg.br/api/pauta.',
                max_length=256,
                verbose_name='URL do painel de votação externo'),
        ),
        migrations.AddField(
            model_name='appconfig',
            name='painel_externo_api_key',
            field=models.CharField(
                blank=True,
                default='',
                max_length=256,
                verbose_name='Chave de acesso ao painel externo (API key)'),
        ),
        migrations.RunPython(carrega_do_ambiente, migrations.RunPython.noop),
    ]
