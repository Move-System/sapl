
from django.apps.registry import apps
from django.db.models import Q
from django.utils import timezone

from drfautoapi.drfautoapi import ApiViewSetConstrutor, \
    customize, wrapper_queryset_response_for_drf_action
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from sapl.comissoes.models import Comissao, Composicao, Participacao
from sapl.materia.models import MateriaEmTramitacao
from sapl.parlamentares.models import Legislatura


ApiViewSetConstrutor.build_class(
    [
        apps.get_app_config('comissoes')
    ]
)


class _ParticipacaoSerializer(serializers.ModelSerializer):
    parlamentar_id = serializers.IntegerField(source='parlamentar.id')
    nome_parlamentar = serializers.CharField(source='parlamentar.nome_parlamentar')
    nome_completo = serializers.CharField(source='parlamentar.nome_completo')
    cargo_id = serializers.IntegerField(source='cargo.id')
    cargo_nome = serializers.CharField(source='cargo.nome')
    cargo_ordenacao = serializers.IntegerField(source='cargo.id_ordenacao', allow_null=True)

    class Meta:
        model = Participacao
        fields = [
            'id',
            'parlamentar_id',
            'nome_parlamentar',
            'nome_completo',
            'cargo_id',
            'cargo_nome',
            'cargo_ordenacao',
            'titular',
            'data_designacao',
            'data_desligamento',
        ]


class _ComissaoVigenteSerializer(serializers.ModelSerializer):
    tipo_nome = serializers.CharField(source='tipo.nome')
    membros = serializers.SerializerMethodField()

    class Meta:
        model = Comissao
        fields = [
            'id',
            'nome',
            'sigla',
            'tipo_nome',
            'ativa',
            'data_criacao',
            'data_extincao',
            'email',
            'membros',
        ]

    def get_membros(self, comissao):
        hoje = self.context.get('hoje')
        legislatura = self.context.get('legislatura')
        if not legislatura:
            return []

        # Composições cujo período cobre a legislatura vigente
        composicoes = Composicao.objects.filter(
            comissao=comissao,
            periodo__data_inicio__lte=legislatura.data_fim,
        ).filter(
            Q(periodo__data_fim__isnull=True) |
            Q(periodo__data_fim__gte=legislatura.data_inicio)
        )

        # Participações sem data de desligamento ou desligamento futuro
        participacoes = Participacao.objects.filter(
            composicao__in=composicoes,
        ).filter(
            Q(data_desligamento__isnull=True) |
            Q(data_desligamento__gte=hoje)
        ).select_related(
            'parlamentar', 'cargo'
        ).order_by('cargo__id_ordenacao', 'parlamentar__nome_parlamentar')

        return _ParticipacaoSerializer(participacoes, many=True).data


@customize(Comissao)
class _ComissaoViewSet:

    @action(detail=False, url_path='vigentes')
    def vigentes(self, request, *args, **kwargs):
        """
        Retorna as comissões vigentes com seus membros (cargo + vereador)
        da composição dentro da legislatura vigente.
        """
        hoje = timezone.localdate()

        legislatura = Legislatura.objects.filter(
            data_inicio__lte=hoje,
            data_fim__gte=hoje,
        ).first()

        qs = Comissao.objects.filter(
            Q(ativa=True) |
            Q(data_extincao__isnull=True) |
            Q(data_extincao__gte=hoje)
        ).distinct().select_related('tipo').order_by('nome')

        serializer = _ComissaoVigenteSerializer(
            qs,
            many=True,
            context={'hoje': hoje, 'legislatura': legislatura, 'request': request},
        )
        return Response(serializer.data)

    @action(detail=True)
    def materiaemtramitacao(self, request, *args, **kwargs):
        return self.get_materiaemtramitacao(**kwargs)

    @wrapper_queryset_response_for_drf_action(model=MateriaEmTramitacao)
    def get_materiaemtramitacao(self, **kwargs):
        return self.get_queryset().filter(
            unidade_tramitacao_atual__comissao=kwargs['pk'],
            )