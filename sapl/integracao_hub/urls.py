from django.conf.urls import url

from .views import (AssinaturasConcluidasPollView,
                    AssinaturasPendentesPollView,
                    DocumentoAlvoView,
                    DocumentoAssinadoView,
                    InventarioView,
                    ProposicoesCadastradasPollView,
                    ProposicoesDevolvidasPollView,
                    ProposicoesEnviadasPollView,
                    ProposicoesRecebidasPollView,
                    RecepcaoAssinaturaView,
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

    url(r'^api/integracao/poll/assinaturas-pendentes/$',
        AssinaturasPendentesPollView.as_view(),
        name='integracao_hub_poll_assinaturas_pendentes'),

    url(r'^api/integracao/poll/assinaturas-concluidas/$',
        AssinaturasConcluidasPollView.as_view(),
        name='integracao_hub_poll_assinaturas_concluidas'),

    url(r'^api/integracao/documentos-assinatura/(?P<materia_id>\d+)/alvo/$',
        DocumentoAlvoView.as_view(),
        name='integracao_hub_documento_alvo'),

    url(r'^api/integracao/documentos-assinatura/(?P<materia_id>\d+)/assinado/$',
        DocumentoAssinadoView.as_view(),
        name='integracao_hub_documento_assinado'),

    url(r'^api/integracao/assinaturas/$',
        RecepcaoAssinaturaView.as_view(),
        name='integracao_hub_recepcao_assinatura'),

    url(r'^api/integracao/reconciliacao/$',
        InventarioView.as_view(),
        name='integracao_hub_reconciliacao'),
]
