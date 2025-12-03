import logging

import requests
from django.apps.registry import apps
from django.conf import settings
from django.urls import reverse
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from drfautoapi.drfautoapi import ApiViewSetConstrutor, \
    customize, wrapper_queryset_response_for_drf_action
from sapl.api.serializers import ChoiceSerializer,\
    SessaoPlenariaECidadaniaSerializer
from sapl.materia.models import MateriaLegislativa, Tramitacao
from sapl.sessao.models import (ExpedienteMateria, ExpedienteSessao, OrdemDia,
                                SessaoPlenaria)
from sapl.utils import choice_anos_com_sessaoplenaria


logger = logging.getLogger(__name__)

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

    def _build_materias_payload(self, request, sessao: SessaoPlenaria,
                                include_momento_meta=False,
                                include_momentos_block=False):
        pk = sessao.pk
        data_ref = sessao.data_fim or sessao.data_inicio

        def autores_info(m: MateriaLegislativa):
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

        def material_item(m: MateriaLegislativa, status_sessao: str,
                          extra: dict = None):
            extra = extra or {}
            pdf_url = None
            try:
                if m.documentoacessorio_set.filter(arquivo__iendswith='pdf').exists():
                    pdf_url = request.build_absolute_uri(
                        reverse('sapl.materia:merge_docacessorios', kwargs={'pk': m.pk})
                    )
            except Exception:
                pdf_url = None

            status_tram, fase_materia = tramitacao_info(m)

            return {
                'id_materia': m.pk,
                'nome_documento': str(m),
                'autoria': autores_info(m),
                'tipo_materia': {
                    'id': m.tipo_id,
                    'nome': getattr(m.tipo, 'descricao', None)
                },
                'ementa': m.ementa,
                'status': status_sessao,
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

        expediente_items = []
        momentos_items = []
        for em in ExpedienteMateria.objects.select_related('materia', 'materia__tipo').filter(sessao_plenaria_id=pk):
            m = em.materia
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
            exp_item = {
                'materia': material_item(
                    m,
                    status_sessao,
                    extra={
                        'tipo_votacao': em.get_tipo_votacao_display(),
                    }
                )
            }
            if include_momento_meta:
                exp_item.update({
                    'momento_id': em.pk,
                    'numero_ordem': em.numero_ordem,
                })
            expediente_items.append(exp_item)

            if include_momentos_block:
                momentos_items.append({
                    'momento_sessao_id': em.pk,
                    'momento_sessao': 'expediente',
                    'materias': [{
                        'momento_id': em.pk,
                        'numero_ordem': em.numero_ordem,
                        'tipo_votacao': em.get_tipo_votacao_display(),
                        'materia': exp_item['materia'],
                    }]
                })

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
            mat_item = material_item(
                m,
                status_sessao,
                extra={
                    'tipo_votacao': od.get_tipo_votacao_display(),
                }
            )

            ord_item = {
                'numero_ordem': od.numero_ordem,
                'materia': mat_item
            }
            if include_momento_meta:
                ord_item.update({
                    'momento_id': od.pk,
                })
            ordem_items.append(ord_item)

            if include_momentos_block:
                momentos_items.append({
                    'momento_sessao_id': od.pk,
                    'momento_sessao': 'ordem_dia',
                    'materias': [{
                        'momento_id': od.pk,
                        'numero_ordem': od.numero_ordem,
                        'tipo_votacao': od.get_tipo_votacao_display(),
                        'materia': mat_item,
                    }]
                })

        payload = {
            'sessao': pk,
            'sessao_nome': str(sessao),
            'tipo_sessao': {
                'id': sessao.tipo_id,
                'nome': getattr(sessao.tipo, 'nome', None)
            },
            'expediente': expediente_items,
            'ordem_dia': ordem_items
        }

        if include_momentos_block:
            payload['momentos'] = momentos_items

        return payload

    @action(detail=True, methods=['get'], url_path='materias')
    def materias(self, request, *args, **kwargs):
        sessao: SessaoPlenaria = self.get_object()
        payload = self._build_materias_payload(
            request,
            sessao,
            include_momento_meta=False,
            include_momentos_block=False
        )
        return Response(payload)

    @action(detail=True, methods=['post'], url_path='materias/enviar',
            permission_classes=[IsAuthenticated])
    def materias_enviar(self, request, *args, **kwargs):
        sessao: SessaoPlenaria = self.get_object()
        payload = self._build_materias_payload(
            request,
            sessao,
            include_momento_meta=False,
            include_momentos_block=False
        )

        base_url = request.data.get('url') or getattr(settings, 'SESSAO_MATERIAS_API_URL', '')
        api_key = request.data.get('api_key') or getattr(settings, 'SESSAO_MATERIAS_API_KEY', '')

        if not base_url:
            return Response({
                'detail': 'Configurar SESSAO_MATERIAS_API_URL ou enviar "url" no body da requisição.'
            }, status=400)

        target_url = f"{base_url.rstrip('/')}/api/integracaoLegisSessao"

        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['x-api-key'] = api_key

        body = payload

        try:
            resp = requests.post(target_url, json=body, headers=headers, timeout=15)
        except requests.RequestException as exc:
            logger.exception('Erro ao enviar materias da sessão %s para API externa', sessao.pk)
            return Response({
                'detail': 'Erro ao enviar para API externa',
                'error': str(exc)
            }, status=502)

        try:
            resp_body = resp.json()
        except ValueError:
            resp_body = resp.text

        return Response({
            'sessao': sessao.pk,
            'target_url': target_url,
            'remote_status_code': resp.status_code,
            'remote_response': resp_body,
            'sent_payload': body
        }, status=200 if resp.ok else 502)
