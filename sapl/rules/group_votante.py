
from sapl.parlamentares import models as parlamentares
from sapl.rules import SGVP_GROUP_VOTANTE

rules_group_votante = {
    'group': SGVP_GROUP_VOTANTE,
    'rules': [
        (parlamentares.Votante, ['can_vote'], set())
    ]
}
