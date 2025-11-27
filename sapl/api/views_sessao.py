from django.apps.registry import apps
from rest_framework.decorators import action
from rest_framework.response import Response

from drfautoapi.drfautoapi import ApiViewSetConstrutor, \
    customize, wrapper_queryset_response_for_drf_action
from sapl.api.serializers import ChoiceSerializer,\
    SessaoPlenariaECidadaniaSerializer
from sapl.sessao.models import SessaoPlenaria, ExpedienteSessao
from sapl.utils import choice_anos_com_sessaoplenaria
# Add imports for building materias payload
from sapl.sessao.models import ExpedienteMateria, OrdemDia
from sapl.materia.models import MateriaLegislativa, Tramitacao
from django.urls import reverse


ApiViewSetConstrutor.build_class(
    [
        apps.get_app_config('sessao')
    ]
)


@customize(SessaoPlenaria)
class _SessaoPlenariaViewSet:

    @action(detail=False)
    def years(self, request, *args, **kwargs):
        years = choice_anos_com_sessaoplenaria()

        serializer = ChoiceSerializer(years, many=True)
        return Response(serializer.data)

    @action(detail=True)
    def expedientes(self, request, *args, **kwargs):
        return self.get_expedientes()

    @wrapper_queryset_response_for_drf_action(model=ExpedienteSessao)
    def get_expedientes(self):
        return self.get_queryset().filter(sessao_plenaria_id=self.kwargs['pk'])

    @action(detail=True)
    def ecidadania(self, request, *args, **kwargs):
        self.serializer_class = SessaoPlenariaECidadaniaSerializer
        return self.retrieve(request, *args, **kwargs)

    @action(detail=False, url_path='ecidadania')
    def ecidadania_list(self, request, *args, **kwargs):
        self.serializer_class = SessaoPlenariaECidadaniaSerializer
        return self.list(request, *args, **kwargs)

    # New endpoint: materias da sessão (expediente e ordem do dia)
    @action(detail=True, methods=['get'], url_path='materias')
    def materias(self, request, *args, **kwargs):
        sessao: SessaoPlenaria = self.get_object()
        pk = sessao.pk
        # Data de referência da sessão para status de tramitação
        data_ref = sessao.data_fim or sessao.data_inicio

        def autores_info(m: MateriaLegislativa):
            # retorna lista de {id, nome}
            return list(m.autores.values('id', 'nome'))

        def tramitacao_info(m: MateriaLegislativa):
            t = (Tramitacao.objects
                 .filter(materia=m, data_tramitacao__lte=data_ref)
                 .order_by('-data_tramitacao', '-id')
                 .select_related('status')
                 .first())
            status = ''
            fase = ''
            try:
                status = t.status.descricao if t and t.status else ''
            except Exception:
                status = ''
            try:
                fase = t.get_turno_display() if t and t.turno else ''
            except Exception:
                fase = ''
            return status, fase

        def material_item(m: MateriaLegislativa, status_sessao: str, extra: dict = None):
            extra = extra or {}
            pdf_url = None
            try:
                # só expõe URL se houver ao menos 1 PDF acessório
                if m.documentoacessorio_set.filter(arquivo__iendswith='pdf').exists():
                    pdf_url = request.build_absolute_uri(
                        reverse('sapl.materia:merge_docacessorios', kwargs={'pk': m.pk})
                    )
            except Exception:
                pdf_url = None

            status_tram, fase_materia = tramitacao_info(m)

            return {
                'id': m.pk,
                'nome_documento': str(m),
                'autoria': autores_info(m),  # [{id, nome}]
                'tipo_materia': {
                    'id': m.tipo_id,
                    'nome': getattr(m.tipo, 'descricao', None)
                },
                'ementa': m.ementa,
                'status': status_sessao,  # alias de status da sessão
                'status_sessao': status_sessao,
                'status_tramitacao': status_tram,
                'fase_materia': fase_materia,
                'quorum': getattr(m.tipo, 'quorum_minimo_votacao', None),
                'pdf_url': pdf_url,
                'tramitacao_pdf_url': request.build_absolute_uri(
                    reverse('sapl.relatorios:relatorio_materia_tramitacao', kwargs={'pk': m.pk})
                ),
                **extra
            }

        # Expediente
        expediente_items = []
        for em in ExpedienteMateria.objects.select_related('materia', 'materia__tipo').filter(sessao_plenaria_id=pk):
            m = em.materia
            # Determina status no contexto da sessão (votação/retirada/leitura)
            rv = em.registrovotacao_set.filter(materia=m).first()
            rp = em.retiradapauta_set.filter(materia=m).first()
            rl = em.registroleitura_set.filter(materia=m).first()
            if rv:
                status_sessao = rv.tipo_resultado_votacao.nome
            elif rp:
                status_sessao = 'Retirado'
            elif rl:
                status_sessao = 'Leitura'
            else:
                status_sessao = ''
            expediente_items.append(material_item(
                m,
                status_sessao,
                {
                    'tipo_votacao': em.get_tipo_votacao_display(),
                }
            ))

        # Ordem do Dia
        ordem_items = []
        for od in OrdemDia.objects.select_related('materia', 'materia__tipo').filter(sessao_plenaria_id=pk):
            m = od.materia
            rv = od.registrovotacao_set.filter(materia=m).first()
            rp = od.retiradapauta_set.filter(materia=m).first()
            rl = od.registroleitura_set.filter(materia=m).first()
            if rv:
                status_sessao = rv.tipo_resultado_votacao.nome
            elif rp:
                status_sessao = 'Retirado'
            elif rl:
                status_sessao = 'Leitura'
            else:
                status_sessao = ''
            ordem_items.append(material_item(
                m,
                status_sessao,
                {
                    'numero_ordem': od.numero_ordem,
                    'tipo_votacao': od.get_tipo_votacao_display(),
                }
            ))

        return Response({
            'sessao': pk,
            'sessao_nome': str(sessao),
            'tipo_sessao': {
                'id': sessao.tipo_id,
                'nome': getattr(sessao.tipo, 'nome', None)
            },
            'expediente': expediente_items,
            'ordem_dia': ordem_items
        })
