import logging
import hashlib
import uuid

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from django.core.files.base import ContentFile
from django.http import FileResponse, Http404

from sapl.base.models import Autor
from sapl.materia.forms import ProposicaoForm
from sapl.materia.models import (MateriaLegislativa, Proposicao,
                                 Tramitacao)
from sapl.utils import get_client_ip

from .models import (AnexoProposicao, AssinaturaRecebida,
                     DocumentoParaAssinatura, EventoRecebido)
from .serializacao import (resolver_titular,
                           serializar_materia_assinada,
                           serializar_pendencia,
                           serializar_proposicao,
                           serializar_tramitacao)

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

        # Anexos do app são GERAIS (foto, vídeo — evidência da demanda), não o texto
        # oficial (decisão do arquiteto, 17/08/2026). O texto_original continua sendo do
        # fluxo próprio do SAPL; o que chega aqui vira AnexoProposicao, só gravação por ora.
        arquivos = request.FILES.getlist('arquivos')

        form = ProposicaoForm(data=self._dados_do_form(request))
        form.instance.autor = autor

        if not form.is_valid():
            return self._erro('proposição inválida', erros=form.errors)

        try:
            with transaction.atomic():
                proposicao = form.save()
                EventoRecebido.objects.create(
                    chave_idempotencia=chave, proposicao=proposicao)
                for arquivo in arquivos:
                    self._gravar_anexo(proposicao, arquivo)
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
            # Sem 'D': anexo geral não é texto digital da proposição — o documento
            # oficial nasce no fluxo do SAPL (Editar Documento / template).
            'tipo_texto': '',
            'user': request.user.pk,
            'ip': get_client_ip(request),
            'ultima_edicao': timezone.now(),
        }

    def _gravar_anexo(self, proposicao, arquivo):
        conteudo = arquivo.read()
        arquivo.seek(0)
        AnexoProposicao.objects.create(
            proposicao=proposicao,
            arquivo=arquivo,
            nome_original=arquivo.name or 'sem-nome',
            mime=getattr(arquivo, 'content_type', '') or '',
            tamanho_bytes=len(conteudo),
            hash_sha256=hashlib.sha256(conteudo).hexdigest())

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
    """Paginação por chave composta (data, id).

    Com o cursor só de data e `>=`, uma página inteira de registros com o MESMO
    timestamp devolvia sempre o mesmo valor de cursor: ele não avançava e a fonte
    relia a mesma página para sempre, sem erro e sem nunca progredir. Chave composta
    elimina o empate como classe de problema — `id_gt` desempata dentro do mesmo
    instante (refinamento da reconciliação §1.1).
    """

    campo_cursor = None

    def get(self, request, *args, **kwargs):
        desde = self._desde(request)
        if desde is None:
            return Response(
                {'detalhe': 'desde deve ser um datetime ISO-8601'},
                status=status.HTTP_400_BAD_REQUEST)
        id_gt = self._id_gt(request)
        if id_gt is None:
            return Response({'detalhe': 'id_gt deve ser inteiro'},
                            status=status.HTTP_400_BAD_REQUEST)

        # (campo > desde) OU (campo = desde E id > id_gt) — keyset, sem pular nem repetir.
        depois_do_instante = Q(**{'%s__gt' % self.campo_cursor: desde})
        no_mesmo_instante = (Q(**{self.campo_cursor: desde}) & Q(id__gt=id_gt))

        itens = (Proposicao.objects
                 .filter(depois_do_instante | no_mesmo_instante, cancelado=False)
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


class InventarioView(PollView):
    """Lista de conferência para a reconciliação do hub (refinamento §3).

    Devolve **ids**, não objetos: é para o hub comparar com o que ele conhece e
    descobrir o que ficou de fora, não uma segunda via dos dados. O corte é por id
    porque `Proposicao` não tem campo de criação — o que existe são as datas de
    estado (envio, recebimento, devolução), e nenhuma delas serve para "quando
    apareceu". Mesmo filtro dos polls (`cancelado=False`), senão a reconciliação
    apontaria para sempre as canceladas como ausentes.

    O SAPL continua sem conhecer o canônico (spec §1, princípio 2): ele só diz o
    que tem.
    """

    def get(self, request, *args, **kwargs):
        id_gt = self._id_gt(request)
        if id_gt is None:
            return Response({'detalhe': 'id_gt deve ser inteiro'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            tramitacao_id_gt = int(
                request.query_params.get('tramitacao_id_gt', id_gt))
        except ValueError:
            return Response({'detalhe': 'tramitacao_id_gt deve ser inteiro'},
                            status=status.HTTP_400_BAD_REQUEST)

        limite = self._limite(request)
        proposicoes = list(
            Proposicao.objects.filter(id__gt=id_gt, cancelado=False)
            .order_by('id').values_list('id', flat=True)[:limite])
        # Tramitacao vem com a materia junto porque a conferencia do hub NAO e por
        # id de tramitacao: o hub so integra tramitacao de materia que ele conhece
        # (proposicao que virou materia depois do marco). Devolver so o id fazia o
        # hub contar como lacuna toda tramitacao do acervo — falso positivo eterno,
        # visto em 14/08: 500 "ausentes" que na verdade eram historico.
        tramitacoes = [
            {'id': t['id'], 'materia': t['materia_id']}
            for t in Tramitacao.objects.filter(id__gt=tramitacao_id_gt)
            .order_by('id').values('id', 'materia_id')[:limite]]

        return Response({
            'proposicoes': proposicoes,
            'tramitacoes': tramitacoes,
            # Diz se a pagina encheu: o hub sabe que precisa pedir a proxima faixa
            # em vez de concluir que o resto simplesmente nao existe.
            'truncado': len(proposicoes) >= limite or len(tramitacoes) >= limite,
        })


class AssinaturasPendentesPollView(PollView):
    """Fonte de poll da pendência de assinatura — cursor composto `(gerado_em, id)`.

    SÓ devolve matéria com o PDF-alvo já materializado (§5.1): DOCX ainda não
    convertido não sai do SAPL — segue visível apenas na tela local. Item com
    `autores_pendentes` vazio é ruído inofensivo, nunca loop: o cursor avança
    igual.

    **Por que a data entrou no cursor (22/08/2026).** Esta fonte era keyset puro
    por `materia_id`, e a materialização é justamente o passo que pode acontecer
    MUITO depois do protocolo. Alvo criado hoje para uma matéria antiga nasce com
    id abaixo do cursor e nunca mais é lido — sem erro, sem WARN, e a
    reconciliação não cobre assinatura. No acervo de Franco isso valia o acervo
    inteiro: 861 matérias DOCX paradas por conversão quebrada, TODAS com id <
    1076, contra um cursor em 1078. No dia em que a conversão voltasse a
    funcionar, as 861 materializariam de uma vez e sumiriam todas.

    Ordenar por `gerado_em` mata isso na raiz: quem materializa tarde entra pela
    data, não pelo id. E como `gerado_em` é `auto_now`, a retificação
    reapresenta a matéria sozinha — o app precisa saber que o alvo mudou (§5.1),
    e o dedupe do hub (marcador = hash do documento) mata a releitura do mesmo
    estado.

    `desde` ausente mantém o keyset antigo por id, para o hub de versão anterior
    continuar funcionando durante a subida. Some quando as duas pontas estiverem
    na nova versão.
    """

    def get(self, request, *args, **kwargs):
        id_gt = self._id_gt(request)
        if id_gt is None:
            return Response({'detalhe': 'id_gt deve ser inteiro'},
                            status=status.HTTP_400_BAD_REQUEST)

        alvos = (DocumentoParaAssinatura.objects
                 .select_related('materia')
                 .prefetch_related(
                     'materia__autoria_set__autor__operadorautor_set__user'))

        if 'desde' in request.query_params:
            desde = self._desde(request)
            if desde is None:
                return Response(
                    {'detalhe': 'desde deve ser um datetime ISO-8601'},
                    status=status.HTTP_400_BAD_REQUEST)
            depois_do_instante = Q(gerado_em__gt=desde)
            no_mesmo_instante = Q(gerado_em=desde) & Q(materia_id__gt=id_gt)
            alvos = (alvos.filter(depois_do_instante | no_mesmo_instante)
                     .order_by('gerado_em', 'materia_id'))
        else:
            alvos = alvos.filter(materia_id__gt=id_gt).order_by('materia_id')

        alvos = alvos[:self._limite(request)]
        return Response({'resultados': [
            serializar_pendencia(alvo, request) for alvo in alvos]})


class AssinaturasConcluidasPollView(PollView):
    """Matérias com `pdf_assinado` — cursor composto (assinado_em, id).

    Mesmo keyset das fontes por data (proposicoes-enviadas): `(campo > desde)
    OU (campo = desde E id > id_gt)` — empate de timestamp não trava o cursor
    (refinamento da reconciliação §1.1). Multiassinatura reapresenta a matéria
    porque `assinado_em` avança a cada ato — o dedupe do hub mata a releitura
    do mesmo estado (marcador = hash do documento).
    """

    def get(self, request, *args, **kwargs):
        desde = self._desde(request)
        if desde is None:
            return Response(
                {'detalhe': 'desde deve ser um datetime ISO-8601'},
                status=status.HTTP_400_BAD_REQUEST)
        id_gt = self._id_gt(request)
        if id_gt is None:
            return Response({'detalhe': 'id_gt deve ser inteiro'},
                            status=status.HTTP_400_BAD_REQUEST)

        depois_do_instante = Q(assinado_em__gt=desde)
        no_mesmo_instante = Q(assinado_em=desde) & Q(id__gt=id_gt)
        itens = (MateriaLegislativa.objects
                 .filter(depois_do_instante | no_mesmo_instante)
                 .exclude(pdf_assinado__isnull=True)
                 .exclude(pdf_assinado='')
                 .order_by('assinado_em', 'id')[:self._limite(request)])
        return Response({'resultados': [
            serializar_materia_assinada(m, request) for m in itens]})


class DocumentoAssinaturaView(IntegracaoHubView):
    """Serve os bytes do PDF ao hub (token + pode_integrar) — refinamento §5.

    O hub baixa daqui e confere o sha256 do poll antes de repassar: o
    Authorization nunca vaza para o consumidor final (padrão dos anexos).
    """

    campo = None  # 'alvo' | 'assinado'

    def get(self, request, materia_id, *args, **kwargs):
        if self.campo == 'alvo':
            alvo = DocumentoParaAssinatura.objects.filter(
                materia_id=materia_id).first()
            arquivo = alvo.arquivo if alvo else None
        else:
            materia = MateriaLegislativa.objects.filter(
                pk=materia_id).first()
            arquivo = materia.pdf_assinado if (
                materia and materia.pdf_assinado) else None
        if not arquivo:
            raise Http404
        return FileResponse(
            arquivo.open('rb'), content_type='application/pdf')


class DocumentoAlvoView(DocumentoAssinaturaView):
    campo = 'alvo'


class DocumentoAssinadoView(DocumentoAssinaturaView):
    campo = 'assinado'


class RecepcaoAssinaturaView(IntegracaoHubView):
    """Recebe do hub o PDF assinado pelo app (refinamento §5, F2).

    Idempotente por chave (padrão do EventoRecebido); o hash do alvo é
    conferido ANTES de gravar — retificação no meio do caminho (alvo
    regenerado entre o poll e a entrega) devolve 409 e a assinatura sobre
    binário defasado é impossível por construção. A gravação usa o MESMO
    formato da sprint (`assinatura_info`, nome-padrão do arquivo): para a
    tela do SAPL, indistinguível de assinatura local.
    """

    logger = logging.getLogger(__name__)
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        try:
            chave = uuid.UUID(str(request.data.get('chave_idempotencia', '')))
        except ValueError:
            return self._erro('chave_idempotencia ausente ou não é um UUID')

        recebida = AssinaturaRecebida.objects.filter(
            chave_idempotencia=chave).first()
        if recebida:
            self.logger.info(
                'integracao_hub: assinatura %s reentregue — devolvendo '
                'resposta original (matéria %s)', chave, recebida.materia_id)
            return Response(
                {'materia_id': recebida.materia_id,
                 'hash_assinado': recebida.hash_assinado},
                status=status.HTTP_200_OK)

        materia = MateriaLegislativa.objects.filter(
            pk=request.data.get('materia')).first()
        if materia is None:
            return self._erro(
                'materia %s inexistente no SAPL' % request.data.get('materia'))

        autor = Autor.objects.filter(pk=request.data.get('autor')).first()
        if autor is None:
            return self._erro(
                'autor %s inexistente no SAPL — conferir o mapa de identidade '
                'no hub' % request.data.get('autor'))
        if not materia.autoria_set.filter(autor=autor).exists():
            return self._erro(
                'autor %s não está na autoria da matéria %s — a pendência '
                'nunca existiu para ele' % (autor.pk, materia.pk))

        # Autoria jurídica = SEMPRE o vereador titular (ato pessoal e
        # indelegável). O assessor pode OPERAR o ato, mas nunca aparece como
        # signatário. Titular indeterminável falha visível — melhor que gravar
        # a assinatura no nome errado.
        titular = resolver_titular(autor)
        if titular is None:
            return self._erro(
                'autor %s com titular indeterminável (múltiplos operadores e '
                'nenhum/ambíguo Votante do parlamentar) — cadastrar o Votante '
                'titular no SAPL' % autor.pk)

        arquivo = request.FILES.get('pdf_assinado')
        if arquivo is None:
            return self._erro('arquivo pdf_assinado ausente')

        alvo = DocumentoParaAssinatura.objects.filter(materia=materia).first()
        hash_esperado = (request.data.get('hash_alvo_esperado') or '').lower()
        if alvo is None or alvo.hash_sha256 != hash_esperado:
            # Retificação no meio do caminho: o alvo de hoje não é o binário
            # que o app exibiu/assinou (§5.1). O hub relê a pendência nova.
            return Response(
                {'detalhe': 'hash do PDF-alvo divergente — alvo retificado '
                            'após a solicitação',
                 'hash_atual': alvo.hash_sha256 if alvo else None},
                status=status.HTTP_409_CONFLICT)

        conteudo = arquivo.read()
        hash_assinado = hashlib.sha256(conteudo).hexdigest()
        agora = timezone.now()

        # Rastro operacional: quem DISPAROU o ato (o vereador ou um assessor
        # agindo por ele). Registro interno, NÃO altera a autoria. O evento do
        # app ainda não carrega a identidade do assessor logado; até lá recai
        # sobre o próprio titular (ver nota no PR).
        operado_por = (request.data.get('operado_por')
                       or titular.username)

        try:
            with transaction.atomic():
                nome = 'materia_%s_assinado_%s.pdf' % (
                    materia.pk, int(agora.timestamp()))
                materia.pdf_assinado.save(
                    nome, ContentFile(conteudo), save=False)

                # APPEND no formato da sprint — multiassinatura incremental.
                assinaturas = self._normalizar(materia.assinatura_info)
                assinaturas.append({
                    'signed_by': titular.username,
                    'nome': request.data.get('nome') or autor.nome,
                    'data': agora.isoformat(),
                    'tipo_certificado':
                        request.data.get('tipo_certificado') or '',
                    'operado_por': operado_por,
                })
                materia.assinatura_info = assinaturas
                materia.assinado_em = agora
                materia.assinado_por = titular
                if not materia.codigo_autenticacao:
                    # Primeira assinatura gera o código público de verificação,
                    # como no fluxo local — a partir dos bytes do ALVO (é o
                    # documento que a página de autenticação identifica).
                    from sapl.materia.views_assinatura import \
                        _gerar_codigo_autenticacao
                    alvo.arquivo.open('rb')
                    try:
                        materia.codigo_autenticacao = \
                            _gerar_codigo_autenticacao(alvo.arquivo.read())
                    finally:
                        alvo.arquivo.close()
                materia.save()

                AssinaturaRecebida.objects.create(
                    chave_idempotencia=chave, materia=materia,
                    hash_assinado=hash_assinado, operado_por=operado_por)
        except IntegrityError:
            # Entrega concorrente da mesma chave: devolve o que já foi gravado.
            recebida = AssinaturaRecebida.objects.filter(
                chave_idempotencia=chave).first()
            if recebida is None:
                raise
            return Response(
                {'materia_id': recebida.materia_id,
                 'hash_assinado': recebida.hash_assinado},
                status=status.HTTP_200_OK)

        self.logger.info(
            'integracao_hub: assinatura %s gravada na matéria %s '
            '(signed_by=%s, autor=%s, operado_por=%s)', chave, materia.pk,
            titular.username, autor.pk, operado_por)
        return Response(
            {'materia_id': materia.pk, 'hash_assinado': hash_assinado},
            status=status.HTTP_201_CREATED)

    def _normalizar(self, info):
        if info is None:
            return []
        if isinstance(info, dict):
            return [info]
        return list(info)

    def _erro(self, detalhe):
        return Response({'detalhe': detalhe},
                        status=status.HTTP_422_UNPROCESSABLE_ENTITY)
