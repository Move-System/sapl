from django.utils import timezone

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
