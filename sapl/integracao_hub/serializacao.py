import hashlib
import logging
import os
from datetime import datetime

from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone

from sapl.base.models import Autor, OperadorAutor
from sapl.materia.models import MateriaLegislativa
from sapl.materia.views_assinatura import (
    _construir_url_verificacao_base, _obter_nome_casa_legislativa)
from sapl.parlamentares.models import Parlamentar, Votante

logger = logging.getLogger(__name__)


def _iso(valor):
    if valor is None:
        return None
    if hasattr(valor, 'tzinfo'):
        if timezone.is_aware(valor):
            valor = timezone.localtime(valor)
        return valor.isoformat()
    return valor.isoformat()


#: Formatos em que `data_assinatura` é gravado hoje. `views_assinatura` usa os
#: dois (`%H:%M:%S` na maioria dos pontos, `%H:%M` em 389/599) e ambos chegam
#: aqui pelo acervo antigo.
_FORMATOS_DATA_ASSINATURA = ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M')


def _data_da_assinatura(info):
    """A data de um ato de assinatura, SEMPRE em ISO-8601 com offset.

    O contrato promete ISO; o acervo entrega duas coisas. `data` já nasce ISO
    (`views_assinatura:1552/1983`, via `self_reported_timestamp`), mas é a
    minoria: 1198 dos 1207 registros medidos em 22/08/2026 têm só
    `data_assinatura`, em `%d/%m/%Y`. O consumidor parseia como ISO e estoura —
    e um estouro aqui congelava a fonte inteira (ver PollerSapl).

    Normalizar AQUI, e não nos seis pontos de gravação, é deliberado:
    `data_assinatura` alimenta a tela de verificação pública
    (`views_assinatura:864/2096/2136`). Mudar o que se grava mudaria o que o
    cidadão vê e obrigaria a migrar 964 matérias; normalizar na fronteira
    conserta o acervo inteiro sem tocar em dado nem em exibição.

    Sem data utilizável devolve None — o consumidor recai em `assinado_em`,
    que é o fallback que ele já tem.
    """
    iso = info.get('data')
    if iso:
        return iso

    bruta = (info.get('data_assinatura') or '').strip()
    if not bruta:
        return None

    for formato in _FORMATOS_DATA_ASSINATURA:
        try:
            ingenua = datetime.strptime(bruta, formato)
        except ValueError:
            continue
        # Foi `timezone.localtime` que gravou — então é hora local da casa, e é
        # como hora local que ela tem que ser reinterpretada. Assumir UTC aqui
        # deslocaria toda a série pelo offset do fuso.
        return timezone.make_aware(
            ingenua, timezone.get_current_timezone()).isoformat()

    logger.warning(
        'integracao_hub: data_assinatura %r não casa com nenhum formato '
        'conhecido — assinatura serializada sem data (o consumidor recai em '
        'assinado_em)', bruta)
    return None


def _materia_da_proposicao(proposicao):
    """A matéria gerada vem da generic FK, não de um campo direto.

    O `materia_gerada` que aparece no models.py está DENTRO de uma docstring
    (código morto) — o vínculo real é `conteudo_gerado_related`
    (content_type + object_id), que aponta para MateriaLegislativa OU para
    DocumentoAcessorio. Só a matéria interessa ao contrato canônico.
    """
    conteudo = proposicao.conteudo_gerado_related
    if not isinstance(conteudo, MateriaLegislativa):
        return None
    materia = conteudo
    return {
        'id': materia.pk,
        'tipo': {
            'id': materia.tipo_id,
            'sigla': materia.tipo.sigla if materia.tipo else None,
            'descricao': materia.tipo.descricao if materia.tipo else None,
        },
        'numero': materia.numero,
        'ano': materia.ano,
        'numero_protocolo': materia.numero_protocolo,
    }


def serializar_proposicao(proposicao):
    """Shape SAPL-nativo (spec, princípio 2): o hub traduz para o canônico."""
    return {
        'id': proposicao.pk,
        'ano': proposicao.ano,
        'numero_proposicao': proposicao.numero_proposicao,
        'tipo': {
            'id': proposicao.tipo_id,
            'descricao': proposicao.tipo.descricao if proposicao.tipo else None,
        },
        'autor': proposicao.autor_id,
        # Nome para exibição no acervo do consumidor (refinamento do histórico §3.2):
        # nunca usado para resolver identidade — contrato §3.2.
        'autor_nome': proposicao.autor.nome if proposicao.autor else None,
        'ementa': proposicao.descricao,
        'rascunho': proposicao.data_envio is None,
        'cancelado': proposicao.cancelado,
        'data_envio': _iso(proposicao.data_envio),
        'data_recebimento': _iso(proposicao.data_recebimento),
        'data_devolucao': _iso(proposicao.data_devolucao),
        'justificativa_devolucao': proposicao.justificativa_devolucao or '',
        'materia': _materia_da_proposicao(proposicao),
    }


def serializar_tramitacao(tramitacao):
    status = tramitacao.status
    return {
        'id': tramitacao.pk,
        'materia': tramitacao.materia_id,
        'data_tramitacao': _iso(tramitacao.data_tramitacao),
        'timestamp': _iso(tramitacao.timestamp),
        'texto': tramitacao.texto or '',
        'urgente': tramitacao.urgente,
        'unidade_destino': tramitacao.unidade_tramitacao_destino_id,
        'status': {
            'id': status.pk,
            'sigla': status.sigla,
            'descricao': status.descricao,
            'indicador': status.indicador,
        } if status else None,
    }


def _sha256_do_arquivo(campo):
    conteudo = campo.read()
    campo.seek(0)
    return hashlib.sha256(conteudo).hexdigest()


def _bloco_documento(campo, request, nome_rota, materia_pk, hash_sha256=None):
    """Bloco do documento, ou `None` quando o binario nao esta no MEDIA.

    Referencia no banco sem arquivo em disco (dump restaurado sem a media,
    volume trocado) fazia `.size`/`.read()` levantar OSError e derrubar a
    resposta INTEIRA do poll com 500. O cursor ficava parado no mesmo item e a
    fonte travava para sempre — uma materia podre bloqueando todas as outras.
    Aqui o item continua na lista (o leitor avanca o cursor) e so o documento
    vem nulo, com o buraco gritando no log.
    """
    try:
        tamanho = campo.size
        digest = hash_sha256 if hash_sha256 is not None else _sha256_do_arquivo(campo)
    except OSError:
        logger.warning(
            'materia %s: pdf ausente no MEDIA (%s) — item entregue sem '
            'documento para o cursor nao travar', materia_pk, campo.name)
        return None
    return {
        'nome': os.path.basename(campo.name),
        'mime': 'application/pdf',
        'tamanho_bytes': tamanho,
        'url': _url_absoluta(request, nome_rota, materia_pk),
        'hash_sha256': digest,
    }


def _normalizar_assinatura_info(info):
    # Mesma normalização da sprint (views_assinatura): dict legado vira lista.
    if info is None:
        return []
    if isinstance(info, dict):
        return [info]
    return info


def _url_absoluta(request, nome_rota, materia_id):
    return request.build_absolute_uri(
        reverse(nome_rota, kwargs={'materia_id': materia_id}))


# A regra de pendência mora em `sapl.materia.pendencias` — fonte única, também
# usada pelo SAPL web (badge, tela de pendentes, filtro da pesquisa, e-mail
# diário). Ficou duas vezes no repo por um tempo, e as duas divergiram: aqui era
# por autor (certo), lá era por documento — o app do AMU mostrava a pendência do
# coautor que a tela do SAPL escondia. Reexportado com os nomes antigos para não
# mexer em quem já importa daqui.
from sapl.materia.pendencias import (  # noqa: E402  (reexport)
    _operadores_do_autor, autores_pendentes as _autores_pendentes,
    resolver_titular)


def serializar_pendencia(alvo, request):
    """Item de `assinaturas-pendentes` (§3): só existe com o PDF-alvo materializado."""
    materia = alvo.materia
    # `verification_url_base` e `casa_legislativa` viajam com a pendência porque
    # SÓ O SAPL sabe a URL pública desta casa e o nome dela. Sem eles o AMU assina
    # sem a página de autenticação — e o documento sai divergente do assinado aqui,
    # que é exatamente o que a convergência dos assinadores (AB#1473) elimina.
    #
    # Reusamos as funções de `views_assinatura` em vez de remontar a URL aqui: elas
    # são a forma canônica que o próprio SAPL usa ao chamar o microserviço. Duplicar
    # a montagem é o caminho conhecido para as duas divergirem na primeira mudança.
    return {
        # Keyset da fonte: cursor composto `(gerado_em, id)`, o mesmo de
        # assinaturas-concluidas. O `id` e o da MATERIA, nao o do registro de
        # pendencia — emitir alvo.pk faria o hub pedir uma pagina que a view
        # nunca entende, relendo a mesma primeira pagina para sempre.
        'id': materia.pk,
        # A DATA e o que salva materia que materializa TARDE. Com keyset so por
        # id, alvo criado depois com id abaixo do cursor era pulado para
        # sempre, calado: em 22/08/2026 as 861 materias DOCX de Franco (todas
        # com id < 1076, cursor em 1078) iam sumir inteiras no dia em que a
        # conversao voltasse a funcionar. `gerado_em` e auto_now, entao a
        # retificacao tambem reapresenta a materia sozinha — que e o
        # comportamento desejado de qualquer forma (§5.1).
        'gerado_em': _iso(alvo.gerado_em),
        'materia': {
            'id': materia.pk,
            'numero': materia.numero,
            'ano': materia.ano,
            'ementa': materia.ementa,
        },
        'autores_pendentes': _autores_pendentes(materia),
        'documento': _bloco_documento(
            alvo.arquivo, request, 'integracao_hub_documento_alvo',
            materia.pk, hash_sha256=alvo.hash_sha256),
        # ── Estado da cadeia (ADR-0013, extensao entre sistemas) ─────────────
        #
        # `documento` acima e sempre o ALVO BASE — e tem que continuar sendo:
        # e contra ele que o receiver confere `hash_alvo_esperado` na checagem
        # de retificacao (§5.1). Mas quando a materia JA TEM assinatura, o alvo
        # nao e o que se deve assinar agora: assinar o alvo em branco produz um
        # PDF que substitui as assinaturas anteriores em vez de somar.
        #
        # O encadeamento do amu-backend resolve isso olhando a pendencia irma
        # ASSINADA no banco DELE — o que so funciona se a assinatura anterior
        # tambem tiver sido feita pelo app, ou se o `DocumentoAssinado` da
        # assinatura feita AQUI ja tiver chegado la. Assinatura feita no SAPL
        # com o poll atrasado cai fora das duas hipoteses.
        #
        # Por isso a pendencia passa a se descrever inteira: quantas assinaturas
        # ja existem, qual documento encadear e com que codigo. O consumidor
        # nao precisa ter visto o evento anterior para acertar — e um consumidor
        # antigo ignora os campos novos e segue como antes.
        'assinaturas_existentes': [
            a.get('signed_by')
            for a in _normalizar_assinatura_info(materia.assinatura_info)],
        'codigo_autenticacao': materia.codigo_autenticacao or None,
        'documento_encadeado': _bloco_documento(
            materia.pdf_assinado, request,
            'integracao_hub_documento_assinado', materia.pk
        ) if materia.pdf_assinado else None,
        'verification_url_base': _construir_url_verificacao_base(
            request, 'materia', materia.pk),
        'casa_legislativa': _obter_nome_casa_legislativa(),
    }


def _autor_do_signed_by(username, ids_da_autoria):
    """Resolve signed_by → autor_id (contrato documento-assinado).

    signed_by é o VEREADOR TITULAR, então a resolução espelha `resolver_titular`
    ao contrário: username → Votante → Parlamentar → Autor (content_type
    parlamentar), preferindo o autor que está na autoria da matéria (é a
    pendência dele que a assinatura fecha). Fallback via OperadorAutor cobre
    registros antigos assinados localmente antes desta regra. Sem casamento na
    autoria, devolve o melhor palpite (best-effort de exibição); None se nada
    resolver — o consumidor ainda tem o signed_by.
    """
    ct_parlamentar = ContentType.objects.get_for_model(Parlamentar)
    parlamentar_ids = list(
        Votante.objects.filter(user__username=username)
        .values_list('parlamentar_id', flat=True))
    autores_titular = list(
        Autor.objects.filter(content_type=ct_parlamentar,
                             object_id__in=parlamentar_ids)
        .values_list('id', flat=True)) if parlamentar_ids else []
    for autor_id in autores_titular:
        if autor_id in ids_da_autoria:
            return autor_id

    autores_operador = list(
        OperadorAutor.objects.filter(user__username=username)
        .order_by('id').values_list('autor_id', flat=True))
    for autor_id in autores_operador:
        if autor_id in ids_da_autoria:
            return autor_id

    if autores_titular:
        return autores_titular[0]
    return autores_operador[0] if autores_operador else None


def serializar_materia_assinada(materia, request):
    assinaturas_info = _normalizar_assinatura_info(materia.assinatura_info)
    ids_da_autoria = set(
        materia.autoria_set.values_list('autor_id', flat=True))

    assinaturas = []
    for info in assinaturas_info:
        username = info.get('signed_by')
        assinaturas.append({
            'signed_by': username,
            # A sprint grava nome_assinante/data_assinatura; o POST da
            # integração grava nome/data — o contrato enxerga um shape só.
            # Shape só na CHAVE não basta: o formato também tem que convergir,
            # e é o que `_data_da_assinatura` garante (sempre ISO ou None).
            'nome': info.get('nome') or info.get('nome_assinante'),
            'data': _data_da_assinatura(info),
            'tipo_certificado': info.get('tipo_certificado'),
            'autor_id': _autor_do_signed_by(username, ids_da_autoria),
            # Rastro operacional (quem disparou o ato) — separado da autoria
            # jurídica (signed_by). Ausente nos registros da sprint.
            'operado_por': info.get('operado_por'),
        })

    return {
        # Keyset da fonte: o hub le `id` no topo para o desempate do cursor
        # composto (assinado_em, id).
        'id': materia.pk,
        'materia': {
            'id': materia.pk,
            'numero': materia.numero,
            'ano': materia.ano,
        },
        'documento_assinado': _bloco_documento(
            materia.pdf_assinado, request,
            'integracao_hub_documento_assinado', materia.pk),
        'codigo_autenticacao': materia.codigo_autenticacao,
        'assinado_em': _iso(materia.assinado_em),
        'assinaturas': assinaturas,
    }
