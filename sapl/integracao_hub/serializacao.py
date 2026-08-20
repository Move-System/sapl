import hashlib
import os

from django.urls import reverse
from django.utils import timezone

from sapl.base.models import OperadorAutor
from sapl.materia.models import MateriaLegislativa


def _iso(valor):
    if valor is None:
        return None
    if hasattr(valor, 'tzinfo'):
        if timezone.is_aware(valor):
            valor = timezone.localtime(valor)
        return valor.isoformat()
    return valor.isoformat()


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


def _autores_pendentes(materia):
    """Pendência é POR AUTOR (refinamento §2), derivada — não é tabela.

    pendente(autor, matéria) = autor ∈ autoria ∧ autor ∉
    assinatura_info.signed_by (username resolvido via OperadorAutor). Autor sem
    operador nunca aparece em signed_by, logo segue pendente — é o hub quem
    corta autor sem par no mapa de identidade (§3).
    """
    assinados = {
        a.get('signed_by')
        for a in _normalizar_assinatura_info(materia.assinatura_info)}
    pendentes = []
    for autoria in materia.autoria_set.all():
        usernames = {
            operador.user.username
            for operador in autoria.autor.operadorautor_set.all()}
        if not (usernames & assinados):
            pendentes.append(autoria.autor_id)
    return pendentes


def serializar_pendencia(alvo, request):
    """Item de `assinaturas-pendentes` (§3): só existe com o PDF-alvo materializado."""
    materia = alvo.materia
    return {
        'materia': {
            'id': materia.pk,
            'numero': materia.numero,
            'ano': materia.ano,
            'ementa': materia.ementa,
        },
        'autores_pendentes': _autores_pendentes(materia),
        'documento': {
            'nome': os.path.basename(alvo.arquivo.name),
            'mime': 'application/pdf',
            'tamanho_bytes': alvo.arquivo.size,
            'url': _url_absoluta(
                request, 'integracao_hub_documento_alvo', materia.pk),
            'hash_sha256': alvo.hash_sha256,
        },
    }


def _autor_do_signed_by(username, ids_da_autoria, mapa_operadores):
    """Resolve signed_by → autor_id via OperadorAutor (contrato documento-assinado).

    Um usuário pode operar mais de um autor: preferimos o autor que está na
    autoria da matéria (é a pendência dele que a assinatura fecha); sem
    interseção, devolve o primeiro operado; sem operador, None — o consumidor
    ainda tem o signed_by.
    """
    autores = mapa_operadores.get(username, [])
    for autor_id in autores:
        if autor_id in ids_da_autoria:
            return autor_id
    return autores[0] if autores else None


def serializar_materia_assinada(materia, request):
    assinaturas_info = _normalizar_assinatura_info(materia.assinatura_info)
    usernames = {a.get('signed_by') for a in assinaturas_info if a.get('signed_by')}
    mapa_operadores = {}
    for operador in (OperadorAutor.objects
                     .filter(user__username__in=usernames)
                     .select_related('user').order_by('id')):
        mapa_operadores.setdefault(
            operador.user.username, []).append(operador.autor_id)
    ids_da_autoria = set(
        materia.autoria_set.values_list('autor_id', flat=True))

    assinaturas = []
    for info in assinaturas_info:
        username = info.get('signed_by')
        assinaturas.append({
            'signed_by': username,
            # A sprint grava nome_assinante/data_assinatura; o POST da
            # integração grava nome/data — o contrato enxerga um shape só.
            'nome': info.get('nome') or info.get('nome_assinante'),
            'data': info.get('data') or info.get('data_assinatura'),
            'tipo_certificado': info.get('tipo_certificado'),
            'autor_id': _autor_do_signed_by(
                username, ids_da_autoria, mapa_operadores),
        })

    return {
        'materia': {
            'id': materia.pk,
            'numero': materia.numero,
            'ano': materia.ano,
        },
        'documento_assinado': {
            'nome': os.path.basename(materia.pdf_assinado.name),
            'mime': 'application/pdf',
            'tamanho_bytes': materia.pdf_assinado.size,
            'url': _url_absoluta(
                request, 'integracao_hub_documento_assinado', materia.pk),
            'hash_sha256': _sha256_do_arquivo(materia.pdf_assinado),
        },
        'codigo_autenticacao': materia.codigo_autenticacao,
        'assinado_em': _iso(materia.assinado_em),
        'assinaturas': assinaturas,
    }
