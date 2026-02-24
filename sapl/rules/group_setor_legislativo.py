from sapl.compilacao import models as compilacao
from sapl.materia import models as materia
from sapl.rules import SGVP_GROUP_SETOR_LEGISLATIVO, RP_LIST, RP_DETAIL, RP_CHANGE, \
    __listdetailchange__, __perms_publicas__

rules_group_setor_legislativo = {
    'group': SGVP_GROUP_SETOR_LEGISLATIVO,
    'rules': [
        (materia.Proposicao, __listdetailchange__ +
         ['detail_proposicao_enviada',
          'detail_proposicao_devolvida',
          'detail_proposicao_incorporada',
          'detail_proposicao_em_revisao_setor'], set()),
        (materia.HistoricoProposicao, [RP_LIST, RP_DETAIL], set()),
        (compilacao.TextoArticulado, ['view_restricted_textoarticulado'], __perms_publicas__),
    ]
}
