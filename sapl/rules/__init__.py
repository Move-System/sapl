from django.utils.translation import ugettext_lazy as _

default_app_config = 'sapl.rules.apps.AppConfig'

"""
Todas as permissões do django framework seguem o padrão

        [app_label].[radical_de_permissao]_[model]

ou seja, em sapl.norma.NormaJuridica, por exemplo, o django framework cria
três permissões registadas na classe Permission:

        definição                         uso

        - add_normajuridica               norma.add_normajuridica
        - change_normajuridica            norma.change_normajuridica
        - delete_normajuridica            norma.delete_normajuridica

        - view_normajuridica              norma.view_normajuridica
        # o radical .view_ não existia no django quando a app rules foi criada
        # e portanto não é utilizada

No SGVP foram acrescidas em todos os models as duas regras abaixo, adicionadas
com o Signal post_migrate `create_proxy_permissions`
localizado em sapl.rules.apps.py.

        - list_normajuridica              norma.list_normajuridica
        - detail_normajuridica            norma.detail_normajuridica

Tanto o Crud implementado em sapl.crud.base.py quanto o Signal post_migrate
`update_groups` que é responsável por ler o mapa do
arquivo (sapl.rules.map_rules.py) e criar os grupos definidos na regra de
negócio trabalham com os cinco radiais de permissão
e com qualquer outro tipo de permissão customizada, nesta ordem de precedência.

Os cinco radicais de permissão são, portanto:

        RP_LIST, RP_DETAIL, RP_ADD, RP_CHANGE, RP_DELETE =\
            '.list_', '.detail_', '.add_', '.change_', '.delete_',

Tanto a app crud quanto a app rules estão sempre ligadas a um model. Ao lidar
com permissões, sempre é analisado se é apenas um radical ou permissão
completa, sendo apenas um radical, a permissão completa é montada com base
no model associado.

NESTE ARQUIVO ESTÃO DEFINIDOS OS RADICAIS E OS GRUPOS DEFAULT DO SGVP

"""

RP_LIST, RP_DETAIL, RP_ADD, RP_CHANGE, RP_DELETE = \
    '.list_', '.detail_', '.add_', '.change_', '.delete_',

__base__ = [RP_LIST, RP_DETAIL, RP_ADD, RP_CHANGE, RP_DELETE]
__listdetailchange__ = [RP_LIST, RP_DETAIL, RP_CHANGE]

__perms_publicas__ = {RP_LIST, RP_DETAIL}

SGVP_GROUP_ADMINISTRATIVO = _("Operador Administrativo")
SGVP_GROUP_AUDIENCIA = _("Operador de Audiência")
SGVP_GROUP_PROTOCOLO = _("Operador de Protocolo Administrativo")
SGVP_GROUP_COMISSOES = _("Operador de Comissões")
SGVP_GROUP_MATERIA = _("Operador de Matéria")
SGVP_GROUP_NORMA = _("Operador de Norma Jurídica")
SGVP_GROUP_SESSAO = _("Operador de Sessão Plenária")
SGVP_GROUP_PAINEL = _("Operador de Painel Eletrônico")
SGVP_GROUP_GERAL = _("Operador Geral")
SGVP_GROUP_AUTOR = _("Autor")
SGVP_GROUP_VOTANTE = _("Votante")
SGVP_GROUP_PRESIDENTE_MESA = _("Presidente da Mesa Diretora")
SGVP_GROUP_SETOR_LEGISLATIVO = _("Operador do Setor Legislativo")

# TODO - funcionalidade ainda não existe mas está aqui para efeito de anotação
SGVP_GROUP_LOGIN_SOCIAL = _("Usuários com Login Social")

# ANONYMOUS não é um grupo mas é uma variável usadas nas rules para anotar
# explicitamente models que podem ter ação de usuários anônimos
# como por exemplo AcompanhamentoMateria
SGVP_GROUP_ANONYMOUS = ''

SGVP_GROUPS = [
    SGVP_GROUP_ADMINISTRATIVO,
    SGVP_GROUP_PROTOCOLO,
    SGVP_GROUP_COMISSOES,
    SGVP_GROUP_MATERIA,
    SGVP_GROUP_NORMA,
    SGVP_GROUP_SESSAO,
    SGVP_GROUP_PAINEL,
    SGVP_GROUP_GERAL,
    SGVP_GROUP_AUTOR,
    SGVP_GROUP_VOTANTE,
    SGVP_GROUP_PRESIDENTE_MESA,
    SGVP_GROUP_SETOR_LEGISLATIVO,
    SGVP_GROUP_LOGIN_SOCIAL,
    SGVP_GROUP_ANONYMOUS,
]

SGVP_GROUPS_DELETE = [

]


def is_procurador_juridico(user):
    """Identifica o Procurador Jurídico pelo grupo SGVP_GROUP_NORMA.

    Customização da Câmara de Franco da Rocha: o usuário desse grupo tem a
    tela inicial reduzida ao módulo de Matérias Legislativas e recebe o
    Documento Acessório pré-preenchido como Parecer Jurídico aprovado.
    """
    return bool(user and user.is_authenticated and
                user.groups.filter(name=SGVP_GROUP_NORMA).exists())
