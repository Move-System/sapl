"""
Regra canônica de pendência de assinatura — uma só, para todas as telas.

Pendência é **por autor**, não por documento. Uma matéria com dois autores em
que só o primeiro assinou continua pendente para o segundo: o `pdf_assinado` já
está preenchido, mas falta a assinatura dele.

Era exatamente isso que quebrava. O SAPL web perguntava "o documento tem PDF
assinado?" em quatro lugares diferentes (contador do menu, tela de pendentes,
filtro da pesquisa, e-mail diário) e, na primeira assinatura, a matéria sumia
para os demais coautores. O hub (`integracao_hub`) já fazia certo, por autor —
ou seja, o app do AMU mostrava a pendência que o SAPL escondia.

Este módulo é a fonte única dessa regra. O `integracao_hub.serializacao`
reexporta daqui em vez de manter a segunda cópia.

    pendente(autor, matéria) ⟺ autor ∈ autoria(matéria)
                               ∧ titular(autor) ∉ assinatura_info.signed_by

Sem autor no contexto (pesquisa livre com "Status de Assinatura: pendente") não
há a quem atribuir a pendência. Aí vale a forma agregada — "ainda falta
assinatura de autor" — comparando quantas assinaturas o PDF tem com quantos
autores a matéria tem. Nos casos normais as duas formas coincidem; a agregada é
a aproximação assumida, e continua sendo estritamente melhor que a antiga
("nenhuma assinatura ainda").
"""
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Titular do autor
# =============================================================================

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
    from sapl.parlamentares.models import Parlamentar

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


def autores_do_usuario(user):
    """Autores que este usuário opera (lista — um assessor pode operar vários).

    O código antigo usava `OperadorAutor.objects.get(user=...)`, que estoura
    MultipleObjectsReturned justamente para o assessor de mais de um vereador —
    e, como a chamada estava dentro de um `except Exception`, o contador zerava
    em silêncio em vez de somar os dois.
    """
    from sapl.base.models import OperadorAutor

    if user is None or not getattr(user, 'is_authenticated', False):
        return []
    return [op.autor for op in OperadorAutor.objects
            .select_related('autor').filter(user=user).order_by('id')]


# =============================================================================
# Pendência por autor
# =============================================================================

def autores_pendentes(materia):
    """IDs dos autores que ainda não assinaram esta matéria (regra canônica).

    Titular indeterminável conta como pendente (não dá para confirmar que
    assinou) — a matéria fica visível e o erro aparece no ato de assinar, não
    some calada.
    """
    from sapl.materia.views_assinatura import _normalizar_assinatura_info

    assinados = {
        a.get('signed_by')
        for a in _normalizar_assinatura_info(materia.assinatura_info)}
    pendentes = []
    for autoria in materia.autoria_set.select_related('autor'):
        titular = resolver_titular(autoria.autor)
        if titular is None or titular.username not in assinados:
            pendentes.append(autoria.autor_id)
    return pendentes


def _q_assinada_por(username):
    """Q que casa matéria já assinada por `username` no `assinatura_info`.

    Duas formas porque o campo tem dois formatos no banco: a lista de hoje e o
    dict único do formato legado (o mesmo motivo de `_normalizar_assinatura_info`
    existir). Em jsonb, `@> '[{...}]'` casa a lista e `@> '{...}'` casa o dict —
    o OR cobre os dois sem migração de dados.
    """
    from django.db.models import Q

    return (Q(assinatura_info__contains=[{'signed_by': username}]) |
            Q(assinatura_info__contains={'signed_by': username}))


def _com_texto_original(qs):
    """Só faz sentido cobrar assinatura de matéria que tem texto para assinar."""
    return qs.filter(texto_original__isnull=False).exclude(texto_original='')


def _q_pendente_para_autor(autor):
    from django.db.models import Q

    condicao = Q(autoria__autor=autor)
    titular = resolver_titular(autor)
    if titular is not None:
        condicao &= ~_q_assinada_por(titular.username)
    else:
        # Titular indeterminável: não dá para afirmar que assinou. Fica pendente.
        logger.info(
            f'[pendencias] Titular indeterminavel para o autor {autor.pk} '
            f'({autor.nome}): as materias dele seguem pendentes.'
        )
    return condicao


def _anotar_contagens(qs):
    """Anota nº de assinaturas no PDF e nº de autores da matéria.

    O nº de assinaturas sai do próprio `assinatura_info` em SQL (jsonb), com
    guarda de tipo: `jsonb_array_length` estoura em dict legado e em NULL, e
    esses dois casos valem 1 e 0 respectivamente.
    """
    from django.db.models import Count, IntegerField, OuterRef, Subquery
    from django.db.models.expressions import RawSQL
    from django.db.models.functions import Coalesce

    from sapl.materia.models import Autoria, MateriaLegislativa

    tabela = MateriaLegislativa._meta.db_table
    n_assinaturas = RawSQL(
        'CASE '
        'WHEN "{t}"."assinatura_info" IS NULL THEN 0 '
        'WHEN jsonb_typeof("{t}"."assinatura_info") = \'array\' '
        'THEN jsonb_array_length("{t}"."assinatura_info") '
        'ELSE 1 END'.format(t=tabela),
        [],
        output_field=IntegerField(),
    )
    n_autores = (Autoria.objects
                 .filter(materia=OuterRef('pk'))
                 .order_by()
                 .values('materia')
                 .annotate(c=Count('autor_id', distinct=True))
                 .values('c'))
    return qs.annotate(
        _n_assinaturas=n_assinaturas,
        _n_autores=Coalesce(
            Subquery(n_autores, output_field=IntegerField()), 0),
    )


def _q_agregada_pendente():
    """`assinaturas < max(autores, 1)` — a forma sem autor no contexto.

    O `max(..., 1)` preserva o comportamento antigo para matéria sem autoria
    cadastrada: sem nenhuma assinatura, ela continua aparecendo como pendente
    em vez de sumir da pesquisa.
    """
    from django.db.models import F, IntegerField, Q, Value
    from django.db.models.functions import Greatest

    return Q(_n_assinaturas__lt=Greatest(
        F('_n_autores'), Value(1), output_field=IntegerField()))


def filtrar_pendentes(qs, autores=None):
    """Matérias pendentes de assinatura.

    autores : lista de Autor (ou None). Com autores, aplica a regra canônica
              por autor; sem eles, a forma agregada.
    """
    from django.db.models import Q

    qs = _com_texto_original(qs)

    if autores:
        condicao = Q()
        for autor in autores:
            condicao |= _q_pendente_para_autor(autor)
        return qs.filter(condicao).distinct()

    return _anotar_contagens(qs).filter(_q_agregada_pendente()).distinct()


def filtrar_assinadas(qs, autores=None):
    """Complemento exato de `filtrar_pendentes` — nada cai entre as duas."""
    from django.db.models import Q

    if autores:
        condicao = Q()
        for autor in autores:
            condicao |= _q_pendente_para_autor(autor)
        return (_com_texto_original(qs)
                .filter(autoria__autor__in=autores)
                .exclude(condicao)
                .distinct())

    return (_anotar_contagens(_com_texto_original(qs))
            .exclude(_q_agregada_pendente())
            .distinct())


def pendentes_para_usuario(qs, user):
    """Pendências deste usuário logado (via os autores que ele opera)."""
    autores = autores_do_usuario(user)
    if not autores:
        return qs.none()
    return filtrar_pendentes(qs, autores=autores)


# =============================================================================
# Cache do contador do menu
# =============================================================================

CACHE_KEY = 'pendencias_assinatura_user_{}'
CACHE_TTL = 120


def invalidar_cache_pendencias(materia=None, user=None):
    """Zera o contador de todo mundo afetado por uma assinatura.

    Só limpar a chave de quem assinou não bastava: a assinatura de um autor
    muda a contagem dos OUTROS coautores (a matéria deixa de ser pendente para
    ele e continua para eles), e eles ficavam com o número velho até o TTL.
    """
    from django.core.cache import cache
    from sapl.base.models import OperadorAutor

    user_ids = set()
    if user is not None and getattr(user, 'pk', None):
        user_ids.add(user.pk)

    if materia is not None:
        try:
            autor_ids = list(materia.autoria_set.values_list('autor_id', flat=True))
            user_ids.update(
                OperadorAutor.objects.filter(autor_id__in=autor_ids)
                .values_list('user_id', flat=True))
        except Exception as exc:  # cache é acessório: nunca derruba a assinatura
            logger.warning(f'[pendencias] Falha ao invalidar cache: {exc}')

    if user_ids:
        cache.delete_many([CACHE_KEY.format(pk) for pk in user_ids])
