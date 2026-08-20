import hashlib
import os

from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone

from sapl.base.models import Autor, OperadorAutor
from sapl.materia.models import MateriaLegislativa
from sapl.parlamentares.models import Parlamentar, Votante


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


def _operadores_do_autor(autor):
    return list(autor.operadorautor_set.select_related('user').order_by('id'))


def resolver_titular(autor):
    """User do VEREADOR TITULAR do autor, ou None se indeterminável.

    Assinatura é ato pessoal e indelegável: o certificado ICP é do vereador, e
    o assessor NUNCA assina no lugar dele — só opera (rastro operacional à
    parte). A identidade jurídica do signatário é sempre o titular.

    O vínculo estrutural parlamentar→user é o **Votante** do Parlamentar que o
    Autor representa (content_type=parlamentar). No dado real de Franco, o autor
    CESINHA tem operadores {cesinha, Juciana} mas votante {cesinha}: o votante
    isola o titular da assessora — casar username com o nome do autor seria
    coincidência frágil, o Votante é o vínculo confiável.

    Regras:
    - parlamentar com exatamente 1 votante → titular (o caso normal);
    - parlamentar sem votante cadastrado → cai no operador único; se houver
      mais de um operador e nenhum votante, o titular é INDETERMINÁVEL (None) —
      o chamador falha visível, melhor que atribuir a autoria ao assessor;
    - parlamentar com >1 votante → ambíguo → None;
    - autor não-parlamentar (órgão, comissão) → sem conceito de votante: só o
      operador único resolve, senão None.
    """
    related = autor.autor_related
    if isinstance(related, Parlamentar):
        votantes = {v.user_id: v.user
                    for v in related.votante_set.select_related('user')}
        if len(votantes) == 1:
            return next(iter(votantes.values()))
        if len(votantes) > 1:
            return None  # titular ambíguo — não adivinha
        # sem votante: só resolve se houver um operador único
    operadores = _operadores_do_autor(autor)
    if len(operadores) == 1:
        return operadores[0].user
    return None


def _autores_pendentes(materia):
    """Pendência é POR AUTOR (refinamento §2), derivada — não é tabela.

    pendente(autor, matéria) = autor ∈ autoria ∧ titular(autor) ∉
    assinatura_info.signed_by. O titular é o vereador (via Votante), não um
    operador qualquer: é a assinatura DELE que fecha a pendência. Titular
    indeterminável conta como pendente (não dá para confirmar que assinou) — a
    matéria fica visível e o erro aparece no ato de assinar, não some calada.
    """
    assinados = {
        a.get('signed_by')
        for a in _normalizar_assinatura_info(materia.assinatura_info)}
    pendentes = []
    for autoria in materia.autoria_set.select_related('autor'):
        titular = resolver_titular(autoria.autor)
        if titular is None or titular.username not in assinados:
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
            'nome': info.get('nome') or info.get('nome_assinante'),
            'data': info.get('data') or info.get('data_assinatura'),
            'tipo_certificado': info.get('tipo_certificado'),
            'autor_id': _autor_do_signed_by(username, ids_da_autoria),
            # Rastro operacional (quem disparou o ato) — separado da autoria
            # jurídica (signed_by). Ausente nos registros da sprint.
            'operado_por': info.get('operado_por'),
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
