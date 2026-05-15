from django.conf.urls import include, url

from sapl.materia.views import (AcompanhamentoConfirmarView,
                                AcompanhamentoExcluirView,
                                AcompanhamentoMateriaView, AnexadaCrud,
                                AssuntoMateriaCrud, AutoriaCrud,
                                AutoriaMultiCreateView, ConfirmarProposicao,
                                CriarProtocoloMateriaView, DespachoInicialCrud,
                                DocumentoAcessorioCrud,
                                DocumentoAcessorioEmLoteView,
                                DocumentoAcessorioUploadView,
                                AnexoProposicaoUploadView,
                                MateriaAnexadaEmLoteView,
                                EtiquetaPesquisaView, FichaPesquisaView,
                                FichaSelecionaView, ImpressosView,
                                LegislacaoCitadaCrud, MateriaAssuntoCrud,
                                MateriaLegislativaCrud,
                                MateriaLegislativaPesquisaView, MateriaTaView,
                                MateriasPendentesAssinaturaView,
                                NumeracaoCrud, OrgaoCrud, OrigemCrud,
                                PrimeiraTramitacaoEmLoteView, ProposicaoCrud,
                                ProposicaoDevolvida, ProposicaoPendente,
                                ProposicaoPendenteSetor,
                                ProposicaoRecebida, ProposicaoTaView,
                                ReceberProposicao, ReciboProposicaoView,
                                RegimeTramitacaoCrud, RelatoriaCrud,
                                StatusTramitacaoCrud, TipoDocumentoCrud,
                                TipoFimRelatoriaCrud, TipoMateriaCrud,
                                TipoProposicaoCrud, TramitacaoCrud,
                                TramitacaoEmLoteView, UnidadeTramitacaoCrud,
                                proposicao_texto, recuperar_materia,
                                ExcluirTramitacaoEmLoteView,
                                RetornarProposicao, RevisarProposicaoSetor,
                                MateriaPesquisaSimplesView,
                                DespachoInicialMultiCreateView,
                                get_zip_docacessorios, get_pdf_docacessorios, get_zip_completo, get_pdf_completo,
                                get_pdf_multiplos,
                                configEtiquetaMateriaLegislativaCrud,
                                PesquisarStatusTramitacaoView, HistoricoProposicaoView)
from sapl.materia.onlyoffice_views import (onlyoffice_config, onlyoffice_download,
                                            onlyoffice_callback, onlyoffice_editor,
                                            onlyoffice_confirmar_config, onlyoffice_confirmar_editor,
                                            proposicao_check_doc, proposicao_forcesave)
from sapl.materia.onlyoffice_materia_views import (
    materia_onlyoffice_editor, materia_onlyoffice_config,
    materia_onlyoffice_download, materia_onlyoffice_callback,
    materia_check_doc, materia_forcesave,
    docacessorio_onlyoffice_editor, docacessorio_onlyoffice_config,
    docacessorio_onlyoffice_download, docacessorio_onlyoffice_callback,
    docacessorio_check_doc, docacessorio_forcesave,
    materia_gerar_pdf_assinatura, materia_gerar_pdf_previa, docacessorio_gerar_pdf_previa
)
from sapl.materia.views_assinatura import (
    materia_assinar_a1, materia_assinar_a3_preparar, materia_assinar_a3_finalizar,
    materia_pdf_assinado, materia_verificar_assinatura, materia_remover_assinatura,
    detectar_aplicacao_a3, materia_assinar_lote,
    docacessorio_assinar_a1, docacessorio_pdf_assinado,
    docacessorio_verificar_assinatura, docacessorio_remover_assinatura,
    materia_verificar_documento, docacessorio_verificar_documento
)
from sapl.norma.views import NormaPesquisaSimplesView
from sapl.protocoloadm.views import (
    FichaPesquisaAdmView, FichaSelecionaAdmView
)

from .apps import AppConfig

app_name = AppConfig.name

urlpatterns_impressos = [
    url(r'^materia/impressos/$',
        ImpressosView.as_view(),
        name='impressos'),
    url(r'^materia/impressos/etiqueta-pesquisa/$',
        EtiquetaPesquisaView.as_view(),
        name='impressos_etiqueta'),
    url(r'^materia/impressos/ficha-pesquisa/$',
        FichaPesquisaView.as_view(),
        name='impressos_ficha_pesquisa'),
    url(r'^materia/impressos/ficha-seleciona/$',
        FichaSelecionaView.as_view(),
        name='impressos_ficha_seleciona'),
    url(r'^materia/impressos/norma-pesquisa/$',
        NormaPesquisaSimplesView.as_view(),
        name='impressos_norma_pesquisa'),
    url(r'^materia/impressos/materia-pesquisa/$',
        MateriaPesquisaSimplesView.as_view(),
        name='impressos_materia_pesquisa'),
    url(r'^materia/impressos/ficha-pesquisa-adm/$',
        FichaPesquisaAdmView.as_view(),
        name='impressos_ficha_pesquisa_adm'),
    url(r'^materia/impressos/ficha-seleciona-adm/$',
        FichaSelecionaAdmView.as_view(),
        name='impressos_ficha_seleciona_adm'),
]

urlpatterns_materia = [

    # Esta customização substitui a url do crud desque que ela permaneça antes
    # da inclusão das urls de DespachoInicialCrud
    url(r'^materia/(?P<pk>\d+)/despachoinicial/create',
        DespachoInicialMultiCreateView.as_view(),
        name='despacho-inicial-multi'),

    url(r'^materia/', include(MateriaLegislativaCrud.get_urls() +
                              AnexadaCrud.get_urls() +
                              AutoriaCrud.get_urls() +
                              DespachoInicialCrud.get_urls() +
                              MateriaAssuntoCrud.get_urls() +
                              NumeracaoCrud.get_urls() +
                              LegislacaoCitadaCrud.get_urls() +
                              TramitacaoCrud.get_urls() +
                              RelatoriaCrud.get_urls() +
                              DocumentoAcessorioCrud.get_urls())),

    url(r'^materia/(?P<pk>[0-9]+)/create_simplificado$',
        CriarProtocoloMateriaView.as_view(),
        name='materia_create_simplificado'),
    url(r'^materia/recuperar-materia',
        recuperar_materia, name='recuperar_materia'),
    url(r'^materia/(?P<pk>[0-9]+)/ta$',
        MateriaTaView.as_view(), name='materia_ta'),


    url(r'^materia/pesquisar-materia$',
        MateriaLegislativaPesquisaView.as_view(), name='pesquisar_materia'),

    url(r'^materia/pendentes-assinatura$',
        MateriasPendentesAssinaturaView.as_view(), name='materias_pendentes_assinatura'),

    url(r'^materia/(?P<pk>\d+)/acompanhar-materia/$',
        AcompanhamentoMateriaView.as_view(), name='acompanhar_materia'),
    url(r'^materia/(?P<pk>\d+)/acompanhar-confirmar$',
        AcompanhamentoConfirmarView.as_view(),
        name='acompanhar_confirmar'),
    url(r'^materia/(?P<pk>\d+)/acompanhar-excluir$',
        AcompanhamentoExcluirView.as_view(),
        name='acompanhar_excluir'),

    url(r'^materia/(?P<pk>\d+)/autoria/multicreate',
        AutoriaMultiCreateView.as_view(),
        name='autoria_multicreate'),


    url(r'^materia/(?P<pk>\d+)/upload-anexos/$',
        DocumentoAcessorioUploadView.as_view(),
        name='upload_anexos_materia'),
    url(r'^materia/acessorio-em-lote', DocumentoAcessorioEmLoteView.as_view(),
        name='acessorio_em_lote'),
    url(r'^materia/(?P<pk>\d+)/anexada-em-lote', MateriaAnexadaEmLoteView.as_view(),
        name='anexada_em_lote'),
    url(r'^materia/primeira-tramitacao-em-lote',
        PrimeiraTramitacaoEmLoteView.as_view(),
        name='primeira_tramitacao_em_lote'),
    url(r'^materia/tramitacao-em-lote', TramitacaoEmLoteView.as_view(),
        name='tramitacao_em_lote'),
    url(r'^materia/excluir-tramitacao-em-lote', ExcluirTramitacaoEmLoteView.as_view(),
        name='excluir_tramitacao_em_lote'),
    url(r'^materia/docacessorio/zip/(?P<pk>\d+)$', get_zip_docacessorios,
        name='compress_docacessorios'),
    url(r'^materia/docacessorio/pdf/(?P<pk>\d+)$', get_pdf_docacessorios,
        name='merge_docacessorios'),
    url(r'^materia/zip-completo/(?P<pk>\d+)$', get_zip_completo,
        name='zip_completo_materia'),
    url(r'^materia/pdf-completo/(?P<pk>\d+)$', get_pdf_completo,
        name='pdf_completo_materia'),
    url(r'^materia/pdf-multiplos/$', get_pdf_multiplos,
        name='pdf_multiplos_materias'),

    # OnlyOffice endpoints para Matéria Legislativa
    url(r'^materia/(?P<pk>\d+)/onlyoffice/editor$', materia_onlyoffice_editor,
        name='materia_onlyoffice_editor'),
    url(r'^materia/(?P<pk>\d+)/onlyoffice/config$', materia_onlyoffice_config,
        name='materia_onlyoffice_config'),
    url(r'^materia/(?P<pk>\d+)/onlyoffice/download$', materia_onlyoffice_download,
        name='materia_onlyoffice_download'),
    url(r'^materia/(?P<pk>\d+)/onlyoffice/callback$', materia_onlyoffice_callback,
        name='materia_onlyoffice_callback'),
    url(r'^materia/(?P<pk>\d+)/check-doc$', materia_check_doc,
        name='materia_check_doc'),
    url(r'^materia/(?P<pk>\d+)/forcesave$', materia_forcesave,
        name='materia_forcesave'),
    url(r'^materia/(?P<pk>\d+)/pdf-assinatura$', materia_gerar_pdf_assinatura,
        name='materia_pdf_assinatura'),

    # Prévia de PDF da Matéria antes da assinatura (sem restrição de protocolo)
    url(r'^materia/(?P<pk>\d+)/pdf-previa$', materia_gerar_pdf_previa,
        name='materia_pdf_previa'),

    # Assinatura Digital de Matéria Legislativa
    url(r'^materia/(?P<pk>\d+)/assinar/a1/$', materia_assinar_a1,
        name='materia_assinar_a1'),
    url(r'^materia/(?P<pk>\d+)/assinar/a3/preparar/$', materia_assinar_a3_preparar,
        name='materia_assinar_a3_preparar'),
    url(r'^materia/(?P<pk>\d+)/assinar/a3/finalizar/$', materia_assinar_a3_finalizar,
        name='materia_assinar_a3_finalizar'),
    url(r'^materia/assinar-em-lote/$', materia_assinar_lote,
        name='materia_assinar_lote'),
    url(r'^materia/(?P<pk>\d+)/pdf-assinado/$', materia_pdf_assinado,
        name='materia_pdf_assinado'),
    url(r'^materia/(?P<pk>\d+)/verificar-assinatura/$', materia_verificar_assinatura,
        name='materia_verificar_assinatura'),
    url(r'^materia/(?P<pk>\d+)/remover-assinatura/$', materia_remover_assinatura,
        name='materia_remover_assinatura'),
    url(r'^materia/assinatura/detectar-a3/$', detectar_aplicacao_a3,
        name='detectar_aplicacao_a3'),

    # Verificação pública de autenticidade (sem login)
    url(r'^materia/(?P<pk>\d+)/verificar/$', materia_verificar_documento,
        name='materia_verificar_documento'),

    # OnlyOffice endpoints para Documento Acessório
    url(r'^materia/documentoacessorio/(?P<pk>\d+)/onlyoffice/editor$', docacessorio_onlyoffice_editor,
        name='docacessorio_onlyoffice_editor'),
    url(r'^materia/documentoacessorio/(?P<pk>\d+)/onlyoffice/config$', docacessorio_onlyoffice_config,
        name='docacessorio_onlyoffice_config'),
    url(r'^materia/documentoacessorio/(?P<pk>\d+)/onlyoffice/download$', docacessorio_onlyoffice_download,
        name='docacessorio_onlyoffice_download'),
    url(r'^materia/documentoacessorio/(?P<pk>\d+)/onlyoffice/callback$', docacessorio_onlyoffice_callback,
        name='docacessorio_onlyoffice_callback'),
    url(r'^materia/documentoacessorio/(?P<pk>\d+)/check-doc$', docacessorio_check_doc,
        name='docacessorio_check_doc'),
    url(r'^materia/documentoacessorio/(?P<pk>\d+)/forcesave$', docacessorio_forcesave,
        name='docacessorio_forcesave'),

    # Prévia de PDF do Documento Acessório antes da assinatura
    url(r'^materia/documentoacessorio/(?P<pk>\d+)/pdf-previa$', docacessorio_gerar_pdf_previa,
        name='docacessorio_pdf_previa'),

    # Assinatura Digital de Documento Acessório
    url(r'^materia/documentoacessorio/(?P<pk>\d+)/assinar/a1/$', docacessorio_assinar_a1,
        name='docacessorio_assinar_a1'),
    url(r'^materia/documentoacessorio/(?P<pk>\d+)/pdf-assinado/$', docacessorio_pdf_assinado,
        name='docacessorio_pdf_assinado'),
    url(r'^materia/documentoacessorio/(?P<pk>\d+)/verificar-assinatura/$', docacessorio_verificar_assinatura,
        name='docacessorio_verificar_assinatura'),
    url(r'^materia/documentoacessorio/(?P<pk>\d+)/remover-assinatura/$', docacessorio_remover_assinatura,
        name='docacessorio_remover_assinatura'),

    # Verificação pública de autenticidade de Documento Acessório (sem login)
    url(r'^materia/documentoacessorio/(?P<pk>\d+)/verificar/$', docacessorio_verificar_documento,
        name='docacessorio_verificar_documento'),
]


urlpatterns_proposicao = [
    url(r'^proposicao/', include(ProposicaoCrud.get_urls())),
    url(r'^proposicao/recibo/(?P<pk>\d+)', ReciboProposicaoView.as_view(),
        name='recibo-proposicao'),
    url(r'^proposicao/receber/', ReceberProposicao.as_view(),
        name='receber-proposicao'),
    url(r'^proposicao/pendente/', ProposicaoPendente.as_view(),
        name='proposicao-pendente'),
    url(r'^proposicao/recebida/', ProposicaoRecebida.as_view(),
        name='proposicao-recebida'),
    url(r'^proposicao/devolvida/', ProposicaoDevolvida.as_view(),
        name='proposicao-devolvida'),
    url(r'^proposicao/pendente-setor/', ProposicaoPendenteSetor.as_view(),
        name='proposicao-pendente-setor'),
    url(r'^proposicao/(?P<pk>\d+)/revisao-setor/', RevisarProposicaoSetor.as_view(),
        name='revisao-proposicao-setor'),
    # OnlyOffice endpoints para confirmação de proposição (DEVE vir antes de proposicao-confirmar)
    url(r'^proposicao/confirmar/P(?P<hash>[0-9A-Fa-f]+)/(?P<pk>\d+)/onlyoffice/editor$',
        onlyoffice_confirmar_editor,
        name='onlyoffice_confirmar_editor'),

    url(r'^proposicao/confirmar/P(?P<hash>[0-9A-Fa-f]+)/'
        r'(?P<pk>\d+)', ConfirmarProposicao.as_view(),
        name='proposicao-confirmar'),
    url(r'^sistema/proposicao/tipo/',
        include(TipoProposicaoCrud.get_urls())),

    url(r'^proposicao/(?P<pk>[0-9]+)/ta$',
        ProposicaoTaView.as_view(), name='proposicao_ta'),


    url(r'^proposicao/texto/(?P<pk>\d+)$', proposicao_texto,
        name='proposicao_texto'),
    url(r'^proposicao/(?P<pk>\d+)/retornar', RetornarProposicao.as_view(),
        name='retornar-proposicao'),
    url(r'^proposicao/historico', HistoricoProposicaoView.as_view(),
        name='historico-proposicao'),

    url(r'^proposicao/(?P<pk>\d+)/upload-anexos/$',
        AnexoProposicaoUploadView.as_view(),
        name='upload_anexos_proposicao'),

    # OnlyOffice endpoints
    url(r'^proposicao/(?P<pk>\d+)/onlyoffice/editor$', onlyoffice_editor,
        name='onlyoffice_editor'),
    url(r'^proposicao/(?P<pk>\d+)/onlyoffice/config$', onlyoffice_config,
        name='onlyoffice_config'),
    url(r'^proposicao/(?P<pk>\d+)/onlyoffice/download$', onlyoffice_download,
        name='onlyoffice_download'),
    url(r'^proposicao/(?P<pk>\d+)/onlyoffice/callback$', onlyoffice_callback,
        name='onlyoffice_callback'),
    url(r'^proposicao/(?P<pk>\d+)/check-doc$', proposicao_check_doc,
        name='proposicao_check_doc'),
    url(r'^proposicao/(?P<pk>\d+)/forcesave$', proposicao_forcesave,
        name='proposicao_forcesave'),

    url(r'^proposicao/(?P<pk>\d+)/onlyoffice/confirmar/config$',
        onlyoffice_confirmar_config,
        name='onlyoffice_confirmar_config'),

]

urlpatterns_sistema = [
    url(r'^sistema/assunto-materia/',
        include(AssuntoMateriaCrud.get_urls())),
    url(r'^sistema/proposicao/tipo/',
        include(TipoProposicaoCrud.get_urls())),
    url(r'^sistema/materia/tipoproposicao/',
        include(TipoProposicaoCrud.get_urls())),
    url(r'^sistema/materia/tipo/', include(TipoMateriaCrud.get_urls())),
    url(r'^sistema/materia/regime-tramitacao/',
        include(RegimeTramitacaoCrud.get_urls())),
    url(r'^sistema/materia/regimetramitacao/',
        include(RegimeTramitacaoCrud.get_urls())),
    url(r'^sistema/materia/tipo-documento/',
        include(TipoDocumentoCrud.get_urls())),
    url(r'^sistema/materia/tipo-fim-relatoria/',
        include(TipoFimRelatoriaCrud.get_urls())),
    url(r'^sistema/materia/unidade-tramitacao/',
        include(UnidadeTramitacaoCrud.get_urls())),
    url(r'^sistema/materia/origem/', include(OrigemCrud.get_urls())),

    url(r'^sistema/materia/status-tramitacao/', include(
        StatusTramitacaoCrud.get_urls()
    )),
    url(
        r'^sistema/materia/pesquisar-status-tramitacao/',
        PesquisarStatusTramitacaoView.as_view(),
        name="pesquisar_statustramitacao"
    ),

    url(r'^sistema/materia/orgao/', include(OrgaoCrud.get_urls())),
    url(r'^sistema/materia/config-etiqueta-materia-legislativas/',configEtiquetaMateriaLegislativaCrud, name="configEtiquetaMateriaLegislativaCrud"),
]

urlpatterns = urlpatterns_impressos + urlpatterns_materia + \
    urlpatterns_proposicao + urlpatterns_sistema
