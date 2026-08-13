import logging
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from sapl.base.models import Autor
from sapl.materia.forms import ProposicaoForm
from sapl.materia.models import Proposicao, Tramitacao
from sapl.utils import get_client_ip

from .models import EventoRecebido
from .serializacao import serializar_proposicao, serializar_tramitacao

LIMITE_PADRAO = 100
LIMITE_MAXIMO = 500


class PodeIntegrar(BasePermission):
    """Usuário de integração dedicado, com a permissão própria do app (spec §3/§6)."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.has_perm('integracao_hub.pode_integrar'))


class ThrottleIntegracao(UserRateThrottle):
    # Auto-contido no app para manter o toque no core em duas linhas (spec §1).
    scope = 'integracao_hub'
    rate = '300/min'


class IntegracaoHubView(APIView):
    authentication_classes = (TokenAuthentication,)
    permission_classes = (PodeIntegrar,)
    throttle_classes = (ThrottleIntegracao,)


class RecepcaoProposicaoView(IntegracaoHubView):
    """Componente A da spec: recepção de proposição SAPL-nativa vinda do hub.

    Regra de negócio pelo caminho oficial: a criação passa pelo ProposicaoForm,
    com o autor fixado na instância antes do save() — o form numera a proposição
    pela sequência do autor. A proposição nasce RASCUNHO (data_envio nula); o
    envio ao protocolo acontece pelo fluxo nativo, quando o autor decidir.
    """

    logger = logging.getLogger(__name__)
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        try:
            chave = uuid.UUID(str(request.data.get('chave_idempotencia', '')))
        except ValueError:
            return self._erro('chave_idempotencia ausente ou não é um UUID')

        recebido = EventoRecebido.objects.filter(
            chave_idempotencia=chave).first()
        if recebido:
            self.logger.info(
                'integracao_hub: evento %s reentregue — devolvendo proposição '
                'existente %s', chave, recebido.proposicao_id)
            return Response({'proposicao_id': recebido.proposicao_id},
                            status=status.HTTP_200_OK)

        autor = Autor.objects.filter(pk=request.data.get('autor')).first()
        if autor is None:
            return self._erro(
                'autor %s inexistente no SAPL — conferir o mapa de identidade '
                'no hub' % request.data.get('autor'))

        arquivos = request.FILES.getlist('arquivos')
        if len(arquivos) > 1:
            return self._erro(
                'a proposição no SAPL comporta um único texto_original; '
                'recebidos %d arquivos' % len(arquivos))

        form = ProposicaoForm(
            data=self._dados_do_form(request),
            files={'texto_original': arquivos[0]} if arquivos else None)
        form.instance.autor = autor

        if not form.is_valid():
            return self._erro('proposição inválida', erros=form.errors)

        try:
            with transaction.atomic():
                proposicao = form.save()
                EventoRecebido.objects.create(
                    chave_idempotencia=chave, proposicao=proposicao)
        except IntegrityError:
            # Entrega concorrente do mesmo evento: quem perdeu a corrida
            # devolve a proposição de quem ganhou.
            recebido = EventoRecebido.objects.filter(
                chave_idempotencia=chave).first()
            if recebido is None:
                raise
            return Response({'proposicao_id': recebido.proposicao_id},
                            status=status.HTTP_200_OK)

        self.logger.info(
            'integracao_hub: evento %s criou a proposição %s (autor %s)',
            chave, proposicao.pk, autor.pk)
        return Response({'proposicao_id': proposicao.pk},
                        status=status.HTTP_201_CREATED)

    def _dados_do_form(self, request):
        observacao = ''
        if request.data.get('texto'):
            observacao = request.data['texto']
        if request.data.get('justificativa'):
            observacao += '\n\nJustificativa: %s' % \
                request.data['justificativa']
        return {
            'tipo': request.data.get('tipo'),
            'descricao': request.data.get('ementa'),
            'observacao': observacao.strip(),
            'tipo_texto': 'D' if request.FILES.getlist('arquivos') else '',
            'user': request.user.pk,
            'ip': get_client_ip(request),
            'ultima_edicao': timezone.now(),
        }

    def _erro(self, detalhe, erros=None):
        corpo = {'detalhe': detalhe}
        if erros is not None:
            corpo['erros'] = erros
        return Response(corpo, status=status.HTTP_422_UNPROCESSABLE_ENTITY)


class PollView(IntegracaoHubView):
    """Base das consultas da volta (spec §4, fallback nomeado do app isolado).

    A API genérica não expõe rascunho ao usuário de integração (get_queryset
    do _ProposicaoViewSet filtra por autor); estas consultas vivem atrás da
    permissão própria e devolvem ordenação estável para o cursor do hub.
    """

    def _limite(self, request):
        try:
            limite = int(request.query_params.get('limite', LIMITE_PADRAO))
        except ValueError:
            return LIMITE_PADRAO
        return max(1, min(limite, LIMITE_MAXIMO))

    def _id_gt(self, request):
        try:
            return int(request.query_params.get('id_gt', 0))
        except ValueError:
            return None

    def _desde(self, request):
        valor = request.query_params.get('desde', '')
        desde = parse_datetime(valor)
        if desde and timezone.is_naive(desde):
            desde = timezone.make_aware(desde)
        return desde

    def _resposta(self, itens, serializar):
        return Response({'resultados': [serializar(i) for i in itens]})


class ProposicoesCadastradasPollView(PollView):
    """Inserts de proposição por cursor de id — inclui rascunhos (spec §4)."""

    def get(self, request, *args, **kwargs):
        id_gt = self._id_gt(request)
        if id_gt is None:
            return Response({'detalhe': 'id_gt deve ser inteiro'},
                            status=status.HTTP_400_BAD_REQUEST)
        itens = (Proposicao.objects
                 .filter(id__gt=id_gt, cancelado=False)
                 .select_related('tipo', 'autor', 'content_type')
                 .order_by('id')[:self._limite(request)])
        return self._resposta(itens, serializar_proposicao)


class PollPorDataView(PollView):
    campo_cursor = None

    def get(self, request, *args, **kwargs):
        desde = self._desde(request)
        if desde is None:
            return Response(
                {'detalhe': 'desde deve ser um datetime ISO-8601'},
                status=status.HTTP_400_BAD_REQUEST)
        filtro = {'%s__gte' % self.campo_cursor: desde, 'cancelado': False}
        itens = (Proposicao.objects
                 .filter(**filtro)
                 .select_related('tipo', 'autor', 'content_type')
                 .order_by(self.campo_cursor, 'id')[:self._limite(request)])
        return self._resposta(itens, serializar_proposicao)


class ProposicoesEnviadasPollView(PollPorDataView):
    campo_cursor = 'data_envio'


class ProposicoesRecebidasPollView(PollPorDataView):
    campo_cursor = 'data_recebimento'


class ProposicoesDevolvidasPollView(PollPorDataView):
    campo_cursor = 'data_devolucao'


class TramitacoesPollView(PollView):
    """Tramitação é insert-only na v1 (spec §4.1.3) — cursor de id basta."""

    def get(self, request, *args, **kwargs):
        id_gt = self._id_gt(request)
        if id_gt is None:
            return Response({'detalhe': 'id_gt deve ser inteiro'},
                            status=status.HTTP_400_BAD_REQUEST)
        itens = (Tramitacao.objects
                 .filter(id__gt=id_gt)
                 .select_related('status')
                 .order_by('id')[:self._limite(request)])
        return self._resposta(itens, serializar_tramitacao)
