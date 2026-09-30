"""Tramitação disparada pela assinatura de um documento acessório (AB#1575).

O Procurador Jurídico assina o parecer quando termina de escrevê-lo, e hoje
alguém precisa lembrar de abrir a matéria e tramitá-la à mão para o status de
espera da sessão. A assinatura é o sinal certo para automatizar isso: é
deliberada, datada, tem autor e valor jurídico — ao contrário da criação do
documento acessório, que acontece com o parecer ainda em branco.

O que dispara e o que resulta são parâmetros de Configurações da Aplicação, não
constantes de código: cada Casa nomeia seus tipos e status de um jeito. Com
qualquer um dos três em branco nada acontece.
"""

import logging

from django.db import transaction
from django.utils import timezone


logger = logging.getLogger(__name__)


# Motivos de não ter tramitado. Quem chama decide se mostra ao usuário.
SEM_CONFIGURACAO = 'sem_configuracao'
TIPO_NAO_DISPARA = 'tipo_nao_dispara'
SEM_TRAMITACAO_ANTERIOR = 'sem_tramitacao_anterior'
SEM_UNIDADE_DE_ORIGEM = 'sem_unidade_de_origem'
JA_ESTA_NO_STATUS = 'ja_esta_no_status'
DATA_INCONSISTENTE = 'data_inconsistente'
ERRO = 'erro'
CRIADA = 'criada'


def _config():
    from sapl.base.models import AppConfig
    return AppConfig.objects.first()


def tramitar_por_assinatura(documento_acessorio, user=None, ip=''):
    """Cria a tramitação automática de uma matéria cujo parecer foi assinado.

    Devolve `(tramitacao_ou_None, motivo)`. **Nunca levanta exceção**: quando
    esta função roda a assinatura já foi gravada, e uma falha aqui não pode
    desfazer nem mascarar o ato de assinar — no máximo deixa o status para o
    operador ajustar à mão, como era antes.
    """
    try:
        return _tramitar(documento_acessorio, user, ip)
    except Exception as e:
        # Assinar é o ato principal; tramitar é a comodidade em cima dele.
        logger.error(
            'Falha na tramitação automática do documento acessório %s: %s',
            getattr(documento_acessorio, 'pk', '?'), e, exc_info=True)
        return None, ERRO


@transaction.atomic
def _tramitar(documento_acessorio, user, ip):
    from sapl.materia.models import Tramitacao

    config = _config()
    if not config:
        return None, SEM_CONFIGURACAO

    tipo_gatilho_id = config.tramitacao_automatica_tipo_documento_id
    status = config.tramitacao_automatica_status
    unidade_destino = config.tramitacao_automatica_unidade_destino

    if not (tipo_gatilho_id and status and unidade_destino):
        return None, SEM_CONFIGURACAO

    if documento_acessorio.tipo_id != tipo_gatilho_id:
        return None, TIPO_NAO_DISPARA

    materia = documento_acessorio.materia

    ultima = materia.tramitacao_set.order_by(
        '-data_tramitacao', '-id').first()

    # Sem histórico não há de onde derivar a unidade de origem, e inventar uma
    # seria fabricar tramitação que ninguém registrou. Fica para a mão humana.
    if not ultima:
        logger.info(
            'Documento acessório %s assinado, mas a matéria %s não tem '
            'tramitação anterior: status não alterado.',
            documento_acessorio.pk, materia.pk)
        return None, SEM_TRAMITACAO_ANTERIOR

    if not ultima.unidade_tramitacao_destino_id:
        logger.info(
            'Documento acessório %s assinado, mas a última tramitação da '
            'matéria %s não tem unidade de destino: status não alterado.',
            documento_acessorio.pk, materia.pk)
        return None, SEM_UNIDADE_DE_ORIGEM

    # Idempotência: reassinar (ou multiassinar) não empilha tramitações.
    if ultima.status_id == status.pk:
        return None, JA_ESTA_NO_STATUS

    hoje = timezone.localdate()

    # O TramitacaoForm exige data crescente e não futura. Aqui não há form, mas
    # a invariante é do domínio, não da tela: com data suja, não inventamos.
    if ultima.data_tramitacao and ultima.data_tramitacao > hoje:
        logger.warning(
            'Documento acessório %s assinado, mas a última tramitação da '
            'matéria %s está datada no futuro (%s): status não alterado.',
            documento_acessorio.pk, materia.pk, ultima.data_tramitacao)
        return None, DATA_INCONSISTENTE

    tramitacao = Tramitacao.objects.create(
        status=status,
        materia=materia,
        data_tramitacao=hoje,
        unidade_tramitacao_local=ultima.unidade_tramitacao_destino,
        unidade_tramitacao_destino=unidade_destino,
        urgente=ultima.urgente,
        texto=str(_texto_da_acao(documento_acessorio)),
        user=user,
        ip=ip or '',
    )

    _replicar_efeitos_do_fluxo_manual(tramitacao, materia, status)

    logger.info(
        'Tramitação automática criada para a matéria %s (status "%s") a partir '
        'da assinatura do documento acessório %s.',
        materia.pk, status, documento_acessorio.pk)

    return tramitacao, CRIADA


def _texto_da_acao(documento_acessorio):
    return 'Tramitação automática: {} assinado digitalmente.'.format(
        documento_acessorio.tipo)


def _replicar_efeitos_do_fluxo_manual(tramitacao, materia, status):
    """Faz o que o `TramitacaoForm.save()` faz além de gravar a tramitação.

    Sem isto a matéria tramitada pelo gatilho ficaria diferente da tramitada à
    mão: `em_tramitacao` desatualizado e anexadas paradas para trás.
    """
    from sapl.base.models import AppConfig as BaseAppConfig
    from sapl.materia.models import MateriaLegislativa, Tramitacao
    from sapl.utils import lista_anexados

    materia.em_tramitacao = False if status.indicador == 'F' else True
    materia.save()

    if not BaseAppConfig.attr('tramitacao_materia'):
        return

    anexadas = lista_anexados(materia)
    novas = []
    for anexada in anexadas:
        ultima_da_anexada = anexada.tramitacao_set.select_related(
            'unidade_tramitacao_destino').order_by(
            '-data_tramitacao', '-id').first()
        if (ultima_da_anexada and
                ultima_da_anexada.unidade_tramitacao_destino_id !=
                tramitacao.unidade_tramitacao_local_id):
            continue
        anexada.em_tramitacao = False if status.indicador == 'F' else True
        novas.append(Tramitacao(
            status=tramitacao.status,
            materia=anexada,
            data_tramitacao=tramitacao.data_tramitacao,
            unidade_tramitacao_local=tramitacao.unidade_tramitacao_local,
            unidade_tramitacao_destino=tramitacao.unidade_tramitacao_destino,
            urgente=tramitacao.urgente,
            turno=tramitacao.turno,
            texto=tramitacao.texto,
            user=tramitacao.user,
            ip=tramitacao.ip,
        ))

    if novas:
        Tramitacao.objects.bulk_create(novas)
        MateriaLegislativa.objects.bulk_update(anexadas, ['em_tramitacao'])
