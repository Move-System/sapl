from django.conf.urls import url

from .views import (ProposicoesCadastradasPollView,
                    ProposicoesDevolvidasPollView,
                    ProposicoesEnviadasPollView,
                    ProposicoesRecebidasPollView,
                    RecepcaoProposicaoView,
                    TramitacoesPollView)

urlpatterns = [
    url(r'^api/integracao/proposicoes/$',
        RecepcaoProposicaoView.as_view(),
        name='integracao_hub_recepcao_proposicao'),

    url(r'^api/integracao/poll/proposicoes-cadastradas/$',
        ProposicoesCadastradasPollView.as_view(),
        name='integracao_hub_poll_cadastradas'),

    url(r'^api/integracao/poll/proposicoes-enviadas/$',
        ProposicoesEnviadasPollView.as_view(),
        name='integracao_hub_poll_enviadas'),

    url(r'^api/integracao/poll/proposicoes-recebidas/$',
        ProposicoesRecebidasPollView.as_view(),
        name='integracao_hub_poll_recebidas'),

    url(r'^api/integracao/poll/proposicoes-devolvidas/$',
        ProposicoesDevolvidasPollView.as_view(),
        name='integracao_hub_poll_devolvidas'),

    url(r'^api/integracao/poll/tramitacoes/$',
        TramitacoesPollView.as_view(),
        name='integracao_hub_poll_tramitacoes'),
]
