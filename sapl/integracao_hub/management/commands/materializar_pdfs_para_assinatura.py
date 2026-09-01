import hashlib
import logging
import os
import time

import requests as http_requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone

from sapl.integracao_hub.models import (BatimentoLaco,
                                        DocumentoParaAssinatura,
                                        MateriaComFalhaMaterializacao,
                                        MateriaParaMaterializar,
                                        PassadaMaterializacao)
from sapl.materia.models import MateriaLegislativa

logger = logging.getLogger(__name__)

# Depois de quanto tempo uma passada `em_andamento` é considerada órfã e tem o
# lock liberado. Precisa folgar sobre a passada mais longa plausível: um acervo
# de ~900 matérias a ~4s de conversão cada roda em torno de 1h. Abaixo disso o
# destravamento automático arriscaria derrubar uma passada viva; muito acima,
# um `kill -9` deixaria a rotina travada por um turno inteiro.
HORAS_ATE_CONSIDERAR_ORFA = 6


class _RequisicaoDeSistema:
    """Substituto mínimo de request para reusar `_gerar_pdf_da_materia` fora do HTTP.

    A rotina da sprint só usa o request em dois pontos do caminho DOCX:
    `build_onlyoffice_url` (que prefere `SAPL_INTERNAL_URL` e só cai no request
    sem ela — aqui caímos em `SITE_URL`) e `generate_file_key` (pk do usuário,
    que num cron não existe — 0 identifica o sistema). O caminho PDF não toca
    o request. Reuso em vez de cópia: a conversão OnlyOffice tem UM dono (§5.1).
    """

    class _UsuarioDeSistema:
        pk = 0

    user = _UsuarioDeSistema()

    def build_absolute_uri(self, caminho):
        base = getattr(settings, 'SITE_URL', '') or ''
        return base.rstrip('/') + caminho


def _origem_servida_confere(materia, hash_origem):
    """A URL entregue ao OnlyOffice serve MESMO o documento que acabamos de ler?

    `SAPL_INTERNAL_URL` e configuracao de operador e nao ha de onde deduzi-la: so
    quem opera sabe qual URL o servidor do OnlyOffice alcanca. O risco nao e ela
    ser fixa — e ela apontar para OUTRA instancia sem ninguem perceber. Ai o
    `hash_origem` sai do arquivo local e o PDF-alvo sai do arquivo do outro SAPL,
    e como e justamente esse hash que dispara a retificacao (§5.1), o alvo
    defasado nunca mais e regenerado: assina-se um PDF que nao corresponde ao
    texto da materia.

    Baixar a propria URL e comparar o sha256 fecha isso sem exigir adivinhacao:
    seja qual for o valor configurado, ele so passa se servir este documento.
    Retorna (ok, motivo).
    """
    from django.urls import reverse
    from sapl.utils import build_onlyoffice_url
    url = build_onlyoffice_url(
        _RequisicaoDeSistema(),
        reverse('sapl.materia:materia_onlyoffice_download',
                kwargs={'pk': materia.pk}))
    try:
        resposta = http_requests.get(url, timeout=60)
    except Exception as exc:  # noqa — rede e diagnostico, nao excecao de dominio
        return False, ('a URL entregue ao OnlyOffice nao respondeu (%s) — '
                       'confira SAPL_INTERNAL_URL' % type(exc).__name__)
    if resposta.status_code != 200:
        return False, ('a URL entregue ao OnlyOffice respondeu %s — o servidor '
                       'dele tambem nao vai conseguir baixar'
                       % resposta.status_code)
    if hashlib.sha256(resposta.content).hexdigest() != hash_origem:
        return False, ('a URL entregue ao OnlyOffice serve OUTRO documento — '
                       'SAPL_INTERNAL_URL aponta para outra instancia do SAPL. '
                       'Converter assim gera um PDF-alvo que nao corresponde ao '
                       'texto desta materia')
    return True, None


def _base_url_de_sistema():
    """URL que o OnlyOffice usa para BAIXAR o documento de origem, no caminho cron.

    `build_onlyoffice_url` prefere `SAPL_INTERNAL_URL` e so cai no request sem
    ela — e no cron o "request" e o `_RequisicaoDeSistema`, que monta a partir de
    `SITE_URL`. Sem nenhuma das duas, a URL sai SEM HOST, o OnlyOffice nao
    consegue baixar e TODA materia DOCX falha na conversao. Descoberto em
    22/08/2026 num acervo real: 0 de 861 DOCX materializaram, cada uma virando um
    logger.error que ninguem le, enquanto os 7 PDF passavam (PDF nao converte, so
    copia bytes) e davam a impressao de que a rotina estava viva.
    """
    return (getattr(settings, 'SAPL_INTERNAL_URL', '')
            or getattr(settings, 'SITE_URL', '') or '')


class Command(BaseCommand):
    help = ('Materializa o PDF-alvo da assinatura (refinamento §5/§5.1): varre '
            'matérias protocoladas com texto_original, gera o PDF uma única '
            'vez e, em retificação do texto, regenera o alvo e ZERA o processo '
            'de assinatura (decisão do arquiteto, 19/08/2026). Idempotente — '
            'feito para cron.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--intervalo',
            type=int,
            default=0,
            metavar='SEGUNDOS',
            help=('Segundos entre VARREDURAS COMPLETAS do acervo. 0 (padrao) '
                  'roda uma varredura e sai — o modo para invocacao manual. '
                  'Maior que zero fica em laco, que e como o container sobe a '
                  'rotina (start.sh): sem isso a materializacao vira passo '
                  'manual e materia protocolada NUNCA vira pendencia no app, '
                  'em silencio. No laco, entre uma varredura e outra, o tick '
                  'curto (--tick) processa a fila de prioridade (ADR 0014).'))
        parser.add_argument(
            '--tick',
            type=int,
            default=15,
            metavar='SEGUNDOS',
            help=('Cadencia do laco entre varreduras: a cada tick a fila de '
                  'prioridade (materias marcadas pelo post_save no momento do '
                  'protocolo/retificacao) e processada — e o que faz a materia '
                  'recem-protocolada virar pendencia em segundos, nao em '
                  'minutos. Tick vazio nao grava passada nem toca o banco alem '
                  'de um SELECT na fila.'))
        parser.add_argument(
            '--fila',
            action='store_true',
            help=('Processa a fila de prioridade UMA vez e sai, sem varredura. '
                  'Modo de teste/diagnostico do tick.'))
        parser.add_argument(
            '--somente-novos',
            action='store_true',
            help=('Gera apenas o PDF-alvo AUSENTE; nunca entra na retificacao. '
                  'E o modo da passada de recuperacao: quando um acervo inteiro '
                  'materializa de uma vez (o dia em que a conversao DOCX volta '
                  'a funcionar), retificar em lote apagaria assinatura ja feita '
                  '— e a decisao de zerar assinatura (§5.1) foi tomada para o '
                  'ato isolado de retificar um texto, nao para uma varredura. '
                  'A retificacao adiada aparece no resumo e roda no ciclo '
                  'normal, uma a uma.'))
        parser.add_argument(
            '--disparada-por',
            default='',
            metavar='USUARIO',
            help=('Quem pediu esta passada. Preenchido pelo botao "Rodar '
                  'agora" do painel; vazio no laco. E rastro operacional, nao '
                  'controle de acesso — a tela ja gateia por pode_integrar.'))

    def handle(self, *args, **options):
        # Erro de CONFIGURACAO morre aqui, alto e cedo — nao vira 861 falhas por
        # materia num log que ninguem le. Vale para a passada unica e para o laco:
        # o container que sobe sem isso nunca materializa nada.
        if not _base_url_de_sistema():
            raise CommandError(
                'materializar_pdfs: nem SAPL_INTERNAL_URL nem SITE_URL estao '
                'configuradas. A conversao DOCX->PDF passa pelo OnlyOffice, que '
                'BAIXA o documento de origem por URL absoluta — sem host ele '
                'responde erro e NENHUMA materia DOCX vira pendencia de '
                'assinatura. Configure SAPL_INTERNAL_URL com uma URL deste SAPL '
                'que o servidor do OnlyOffice alcance.')

        intervalo = options['intervalo']
        tick = max(1, options['tick'])
        somente_novos = options['somente_novos']
        disparada_por = options['disparada_por']
        if options['fila']:
            self._passada_prioritaria(somente_novos, disparada_por)
            return
        if intervalo <= 0:
            self._passada_registrada(somente_novos, disparada_por)
            return

        # Instância única do LAÇO (ADR 0015): batimento fresco de outro
        # processo = já existe laço vivo, este sai. O lock de passada impedia
        # conversão dupla; isto impede dois laços residentes disputando — o
        # cenário que a autossupervisão cria quando dois workers do gunicorn
        # decidem ressuscitar o laço no mesmo segundo.
        batimento = BatimentoLaco.objects.first()
        if batimento and batimento.fresco and batimento.pid != os.getpid():
            self.stdout.write(
                'materializar_pdfs: ja existe laco vivo (pid %s, batimento '
                '%s) — este processo sai' % (batimento.pid, batimento.visto_em))
            return

        self._batendo = True
        self._tick = tick
        self._iniciado_em = timezone.now()
        # A versao do codigo em disco no momento da subida. Quando um deploy
        # troca o arquivo, o laco RESIDENTE continuaria rodando o codigo velho
        # para sempre — entao ele se encerra e deixa a autossupervisao (ou o
        # supervisor) ressuscita-lo ja atualizado.
        try:
            self._versao_codigo = os.path.getmtime(__file__)
        except OSError:
            self._versao_codigo = None

        self.stdout.write(
            'materializar_pdfs: laco — varredura completa a cada %ss, fila de '
            'prioridade a cada %ss (Ctrl-C para sair)' % (intervalo, tick))
        # A proxima varredura conta a partir do FIM da anterior: uma varredura
        # que leva uma hora num acervo grande nao pode emendar na seguinte com
        # so um tick de folga.
        proxima_varredura = 0.0
        while True:
            self._bater()
            if self._codigo_mudou_no_disco():
                self.stdout.write(
                    'materializar_pdfs: codigo novo no disco — laco sai para '
                    'renascer atualizado (autossupervisao/supervisor sobem '
                    'outro)')
                logger.info(
                    'materializar_pdfs: laco encerrado por deploy detectado')
                return
            try:
                if time.monotonic() >= proxima_varredura:
                    try:
                        self._passada_registrada(somente_novos, disparada_por)
                    finally:
                        # Reagenda mesmo quando a varredura estoura: sem isso a
                        # varredura quebrada re-rodaria a cada tick, martelando
                        # o acervo inteiro a cada 15s em vez de a cada 300s.
                        proxima_varredura = time.monotonic() + intervalo
                else:
                    self._passada_prioritaria(somente_novos)
            except Exception as exc:  # noqa — o laco NUNCA morre: se morrer,
                # a materializacao para de vez e ninguem percebe ate a materia
                # nao aparecer para assinar.
                logger.exception('materializar_pdfs: passada falhou: %s', exc)
            time.sleep(tick)

    # Estado do modo laço (ADR 0015). Fora do laço (passada manual, botão da
    # tela, --fila) nada disso é tocado: `_batendo` False faz `_bater` ser um
    # no-op e o batimento continua contando só a vida do laço residente.
    _batendo = False
    _tick = 15
    _iniciado_em = None
    _versao_codigo = None
    _ultimo_batimento_monotonic = 0.0

    def _bater(self):
        """Grava o batimento (singleton pk=1), no máximo a cada 10s.

        Chamado a cada iteração do laço E a cada matéria da varredura: uma
        varredura de uma hora sem batimento pareceria laço morto e faria a
        autossupervisão subir um segundo processo.
        """
        if not self._batendo:
            return
        agora = time.monotonic()
        if (self._ultimo_batimento_monotonic
                and agora - self._ultimo_batimento_monotonic < 10):
            return
        self._ultimo_batimento_monotonic = agora
        try:
            BatimentoLaco.objects.update_or_create(pk=1, defaults={
                'visto_em': timezone.now(),
                'iniciado_em': self._iniciado_em,
                'pid': os.getpid(),
                'tick_segundos': self._tick})
        except Exception as exc:  # noqa — batimento é sinal vital, não trabalho:
            # falhar em gravá-lo não pode derrubar a materialização em si.
            logger.warning('materializar_pdfs: falha ao gravar batimento: %s',
                           exc)

    def _codigo_mudou_no_disco(self):
        """Deploy trocou o arquivo do comando? Então este laço está defasado."""
        if self._versao_codigo is None:
            return False
        try:
            return os.path.getmtime(__file__) != self._versao_codigo
        except OSError:
            # Arquivo sumiu do caminho = deploy em curso: melhor renascer.
            return True

    def _fechar_orfas(self):
        """Libera o lock de passada cujo processo morreu sem fechar a linha.

        `kill`, reboot ou OOM deixam `em_andamento=True` para sempre, e como
        esse campo é o índice único que serializa as passadas, a rotina inteira
        ficaria travada — a MESMA falha muda que este painel existe para acabar.
        Fecha marcando `abandonada`, para os contadores incompletos não passarem
        por resultado real na tela.
        """
        limite = timezone.now() - timezone.timedelta(
            hours=HORAS_ATE_CONSIDERAR_ORFA)
        orfas = PassadaMaterializacao.objects.filter(
            em_andamento=True, iniciada_em__lt=limite)
        for orfa in orfas:
            orfa.em_andamento = None
            orfa.terminada_em = timezone.now()
            orfa.abandonada = True
            orfa.save(update_fields=['em_andamento', 'terminada_em',
                                     'abandonada'])
            logger.warning(
                'materializar_pdfs: passada %s abandonada (aberta desde %s) — '
                'lock liberado', orfa.pk, orfa.iniciada_em)

    def _passada_prioritaria(self, somente_novos=False, disparada_por=''):
        """Só as matérias marcadas pelo evento — o caminho dos segundos (ADR 0014).

        Fila vazia é o caso de quase todo tick: sai sem gravar passada nem
        disputar o lock. Com fila, roda como passada normal (mesmo lock, mesma
        linha na tela) restrita às marcadas — se a varredura completa estiver no
        meio, o lock dispensa esta passada e as marcas ficam para o próximo
        tick.
        """
        marcas = list(MateriaParaMaterializar.objects
                      .select_related('materia')
                      .order_by('marcada_em', 'materia_id'))
        if not marcas:
            return None
        return self._passada_registrada(somente_novos, disparada_por,
                                        marcas=marcas)

    def _passada_registrada(self, somente_novos=False, disparada_por='',
                            marcas=None):
        """Envelope da passada: abre a linha, roda, fecha — sempre fecha.

        A linha existe para a tela responder "quando rodou, o que fez, e por que
        falhou" sem ninguém abrir shell. E o `em_andamento` único garante que
        laço, tick de prioridade e botão nunca convertam o mesmo documento ao
        mesmo tempo.
        """
        self._fechar_orfas()

        if marcas is not None:
            disparo = PassadaMaterializacao.DISPARO_PRIORIDADE
        elif disparada_por:
            disparo = PassadaMaterializacao.DISPARO_MANUAL
        else:
            disparo = PassadaMaterializacao.DISPARO_LACO
        try:
            # `atomic` aqui não é transação de negócio: sem ele a IntegrityError
            # do índice único envenena a transação corrente e o rollback leva
            # junto o que vier depois.
            with transaction.atomic():
                passada = PassadaMaterializacao.objects.create(
                    disparo=disparo,
                    disparada_por=disparada_por,
                    somente_novos=somente_novos)
        except IntegrityError:
            self.stdout.write(
                'materializar_pdfs: ja ha uma passada em andamento — esta '
                'foi dispensada')
            logger.info('materializar_pdfs: passada dispensada (lock ocupado)')
            return None

        try:
            self._passada(somente_novos, passada, marcas)
        finally:
            passada.em_andamento = None
            passada.terminada_em = timezone.now()
            passada.save()
        return passada

    def _pares_da_fila(self, marcas):
        """(matéria, marca) das marcadas ainda elegíveis; as demais desmarcam.

        A matéria pode ter saído do filtro entre o evento e o tick (protocolo
        anulado pelo protocoloadm, texto removido) — processá-la seria erro,
        deixar a marca seria fila que nunca esvazia.
        """
        pares = []
        for marca in marcas:
            materia = marca.materia
            if not materia.numero_protocolo or not materia.texto_original:
                self._desmarcar(marca)
                continue
            pares.append((materia, marca))
        return pares

    def _desmarcar(self, marca):
        """Tira da fila SÓ se a marca não avançou depois da leitura.

        Retificação que chega no meio da conversão remarca com `marcada_em`
        novo — o filtro deixa essa marca viva e o próximo tick regenera sobre
        o texto novo. Sem o filtro, o evento se perderia até a varredura.
        """
        MateriaParaMaterializar.objects.filter(
            pk=marca.pk, marcada_em__lte=marca.marcada_em).delete()

    def _passada(self, somente_novos=False, passada=None, marcas=None):
        if marcas is None:
            materias = (MateriaLegislativa.objects
                        .filter(numero_protocolo__isnull=False,
                                texto_original__isnull=False)
                        .exclude(texto_original='')
                        .order_by('id'))
            pares = ((materia, None) for materia in materias.iterator())
        else:
            pares = self._pares_da_fila(marcas)

        gerados = retificados = pulados = falhas = adiados = 0
        motivos = {}
        for materia, marca in pares:
            self._bater()  # varredura longa não pode parecer laço morto
            try:
                resultado, motivo = self._materializar(materia, somente_novos)
            except Exception as exc:  # noqa — uma matéria não trava as demais (§5.1)
                logger.exception(
                    'materializar_pdfs: falha inesperada na matéria %s: %s',
                    materia.pk, exc)
                falhas += 1
                motivos[type(exc).__name__] = motivos.get(
                    type(exc).__name__, 0) + 1
                self._registrar_falha(materia, type(exc).__name__)
                # Falha também desmarca: a falha já está registrada para a tela
                # e a varredura completa retenta — manter a marca faria o tick
                # martelar o OnlyOffice a cada 15s com o ambiente quebrado.
                if marca is not None:
                    self._desmarcar(marca)
                continue
            if marca is not None:
                self._desmarcar(marca)
            if resultado == 'gerado':
                gerados += 1
                self._limpar_falha(materia)
            elif resultado == 'retificado':
                retificados += 1
                self._limpar_falha(materia)
            elif resultado == 'falha':
                falhas += 1
                motivos[motivo] = motivos.get(motivo, 0) + 1
                self._registrar_falha(materia, motivo)
            elif resultado == 'adiado':
                # Adiada não é falha: o alvo existe e funciona, só está
                # defasado. Não mexe na linha de falha — nem cria, nem apaga.
                adiados += 1
            else:
                pulados += 1
                self._limpar_falha(materia)

        if passada is not None:
            passada.gerados = gerados
            passada.retificados = retificados
            passada.em_dia = pulados
            passada.falhas = falhas
            passada.adiados = adiados
            passada.motivos = motivos
            passada.save(update_fields=['gerados', 'retificados', 'em_dia',
                                        'falhas', 'adiados', 'motivos'])

        self.stdout.write(
            'materializar_pdfs: %s gerados, %s retificados, %s em dia, '
            '%s falhas' % (gerados, retificados, pulados, falhas))

        # Adiada nao e "em dia": e trabalho pendente que este modo se recusou a
        # fazer. Some do resumo comum e vira surpresa quando alguem estranhar
        # que o alvo nao acompanhou o texto.
        if adiados:
            self.stdout.write(
                'materializar_pdfs: %s retificacao(oes) ADIADA(S) por '
                '--somente-novos — o texto mudou e o PDF-alvo segue defasado. '
                'Rodar sem a flag para regenerar (zera a assinatura da materia, '
                '§5.1).' % adiados)

        # Falha em MASSA por um motivo so nao e materia podre avulsa: e o
        # ambiente parado. O contador sozinho nao dizia isso — `2 gerados, 873
        # falhas` passava por linha de rotina, e as 873 eram todas o MESMO erro.
        # Agrupar por motivo transforma 873 logger.error dispersos em uma linha
        # que se le e se age. Em 22/08/2026 essas 873 eram um unico `codigo -8`.
        self._relatar_motivos(motivos, falhas)

    def _registrar_falha(self, materia, motivo):
        """Grava a matéria travada AGORA — a segunda pergunta do operador.

        `update_or_create` de propósito: o painel mostra o estado atual, não um
        histórico de tentativas. Com um acervo inteiro falhando a cada ciclo,
        histórico cresceria sozinho e afogaria justamente o que importa.
        """
        MateriaComFalhaMaterializacao.objects.update_or_create(
            materia=materia, defaults={'motivo': motivo or 'motivo não informado'})

    def _limpar_falha(self, materia):
        """Sucesso apaga a marca: a lista da tela é 'travadas agora'."""
        MateriaComFalhaMaterializacao.objects.filter(materia=materia).delete()

    def _relatar_motivos(self, motivos, falhas):
        if not motivos:
            return
        motivo, quantas = max(motivos.items(), key=lambda par: par[1])
        # Uma falha isolada e ruido esperado (§5.1); o que precisa gritar e o
        # motivo unico que derruba um lote inteiro.
        if quantas < 2:
            return
        aviso = ('materializar_pdfs: %s de %s falhas pelo MESMO motivo: %s'
                 % (quantas, falhas, motivo))
        # O -8 do OnlyOffice e "token invalido", e a leitura natural (URL ruim)
        # manda consertar a variavel errada: JWT desligado AQUI e exatamente o
        # que produz -8 quando o SERVIDOR do OnlyOffice exige token.
        if 'codigo -8' in motivo or 'código -8' in motivo:
            if not getattr(settings, 'ONLYOFFICE_JWT_ENABLED', False):
                aviso += (
                    ' | -8 e erro de TOKEN, nao de URL: o servidor em %s exige '
                    'JWT e ONLYOFFICE_JWT_ENABLED esta False. Configure '
                    'ONLYOFFICE_JWT_ENABLED=True e ONLYOFFICE_JWT_SECRET com o '
                    'mesmo segredo do servidor do OnlyOffice.'
                    % getattr(settings, 'ONLYOFFICE_URL', '<ausente>'))
        # O -4 e o OPOSTO do -8: nao e token, e DOWNLOAD. E a leitura natural
        # ("a URL deve estar errada") manda conferir a variavel do jeito errado,
        # porque a URL costuma funcionar — de dentro. `_origem_servida_confere`
        # baixa a URL do PROPRIO SAPL e por isso passa limpo; ela nunca teve
        # como provar que o servidor do OnlyOffice, que e outra maquina, alcanca
        # o mesmo endereco. Em 25/08/2026 eram 861 falhas com SAPL_INTERNAL_URL
        # apontando para um endereco que so existia dentro da VPS.
        elif 'codigo -4' in motivo or 'código -4' in motivo:
            aviso += (
                ' | -4 e erro de DOWNLOAD, nao de token: o servidor do '
                'OnlyOffice em %s nao conseguiu BAIXAR o documento de origem. '
                'SAPL_INTERNAL_URL (hoje %r) precisa ser uma URL que AQUELE '
                'servidor alcance — endereco interno (localhost, 127.0.0.1, IP '
                'privado) funciona daqui e nao de la. Use https: em http o '
                'nginx responde 301 e redirect nao seguido tambem vira -4.'
                % (getattr(settings, 'ONLYOFFICE_URL', '<ausente>'),
                   _base_url_de_sistema() or '<ausente>'))
        self.stderr.write(aviso)
        logger.error(aviso)

    def _materializar(self, materia, somente_novos=False):
        materia.texto_original.open('rb')
        try:
            conteudo_origem = materia.texto_original.read()
        finally:
            materia.texto_original.close()
        hash_origem = hashlib.sha256(conteudo_origem).hexdigest()

        alvo = DocumentoParaAssinatura.objects.filter(materia=materia).first()
        if alvo is not None and alvo.hash_origem == hash_origem:
            return 'em dia', None  # idempotência: nada mudou desde a geração

        # A passada de recuperação não retifica — e decide isso ANTES de gastar
        # a conversão, não depois. Alvo defasado é um problema; apagar
        # assinatura já feita, em lote e sem ninguém pedir, é um problema pior e
        # irreversível. A decisão de zerar (§5.1) foi tomada para o ato isolado
        # de retificar um texto, não para uma varredura de acervo inteiro.
        if alvo is not None and somente_novos:
            logger.info(
                'materializar_pdfs: matéria %s precisa de retificação — ADIADA '
                'por --somente-novos (sem conversão)', materia.pk)
            return 'adiado', None

        # Reuso da rotina da sprint: PDF copia os bytes, DOCX converte no
        # OnlyOffice — a conversão acontece UMA vez, aqui, fora do caminho
        # quente das requisições (§5.1).
        # Só o caminho DOCX passa pelo OnlyOffice; PDF copia bytes e não depende
        # de URL nenhuma. Conferir a origem servida antes de gastar a conversão.
        if not materia.texto_original.name.lower().endswith('.pdf'):
            ok, motivo = _origem_servida_confere(materia, hash_origem)
            if not ok:
                logger.error(
                    'materializar_pdfs: matéria %s — %s', materia.pk, motivo)
                return 'falha', motivo

        from sapl.materia.views_assinatura import _gerar_pdf_da_materia
        pdf_bytes, erro = _gerar_pdf_da_materia(
            materia, _RequisicaoDeSistema())
        if erro:
            logger.error(
                'materializar_pdfs: matéria %s não convertida (%s) — segue '
                'visível só na tela do SAPL até o próximo ciclo', materia.pk,
                erro)
            return 'falha', erro

        nome = 'materia_%s_alvo.pdf' % materia.pk
        hash_alvo = hashlib.sha256(pdf_bytes).hexdigest()

        with transaction.atomic():
            if alvo is None:
                alvo = DocumentoParaAssinatura(
                    materia=materia, hash_sha256=hash_alvo,
                    hash_origem=hash_origem)
                alvo.arquivo.save(nome, ContentFile(pdf_bytes), save=True)
                logger.info(
                    'materializar_pdfs: PDF-alvo da matéria %s gerado (%s)',
                    materia.pk, hash_alvo)
                return 'gerado', None

            # RETIFICAÇÃO (§5.1, decisão do arquiteto 19/08): texto_original
            # mudou depois da conversão → o alvo está defasado. Regenera E zera
            # o processo de assinatura — mesmo efeito da rotina
            # `materia_remover_assinatura` que o SAPL já tem. Assinatura sobre
            # texto retificado é impossível por construção.
            alvo.arquivo.delete(save=False)
            alvo.hash_sha256 = hash_alvo
            alvo.hash_origem = hash_origem
            alvo.arquivo.save(nome, ContentFile(pdf_bytes), save=True)

            if materia.pdf_assinado:
                materia.pdf_assinado.delete(save=False)
            materia.pdf_assinado = None
            materia.assinatura_info = None
            materia.assinado_em = None
            materia.assinado_por = None
            materia.codigo_autenticacao = None
            # O post_save de MateriaLegislativa alimenta a fila de prioridade
            # (ADR 0014); este save é a PRÓPRIA materialização zerando a
            # assinatura — remarcar aqui criaria um ciclo fila→passada→fila.
            materia._materializacao_em_curso = True
            try:
                materia.save()
            finally:
                materia._materializacao_em_curso = False

        logger.info(
            'materializar_pdfs: matéria %s RETIFICADA — alvo regenerado (%s) '
            'e assinaturas zeradas', materia.pk, hash_alvo)
        return 'retificado', None
