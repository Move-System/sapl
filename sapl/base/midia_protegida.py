"""Controle de acesso aos arquivos de mídia (AB#1583).

O SAPL servia `/media/` direto pelo nginx, por alias, sem autenticação. Como
todo campo de arquivo é renderizado na tela como `<a href="{{ value.url }}">`,
qualquer pessoa com a URL — inclusive um robô que a tenha indexado — baixava o
arquivo sem passar pelo Django. Em Franco da Rocha isso expôs processos ainda
em tramitação, que sequer tinham ido a plenário.

Esconder o link não resolveria: a URL continua válida para quem já a tem. Por
isso o acesso passa a ser decidido aqui, e o nginx só entrega o byte depois do
`X-Accel-Redirect` — o arquivo deixa de ser alcançável por fora.

A regra tem três faixas:

1. **Público sempre** — brasão da Casa, logo de partido, norma publicada, ata e
   pauta de sessão, audiência pública. São peças de transparência: fechá-las
   criaria problema legal, além de quebrar o cabeçalho de todas as páginas.
2. **Público depois do plenário** — matéria legislativa e seus documentos
   acessórios. Enquanto a matéria não foi a plenário, só usuário logado vê.
3. **Sempre restrito** — todo o resto. Proposição, documento administrativo,
   arquivo do TCE, justificativa de ausência (que pode conter atestado médico).
   É o padrão: modelo que ninguém classificou cai aqui, de propósito.
"""

import logging
import os
import posixpath

from django.conf import settings
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.encoding import iri_to_uri


logger = logging.getLogger(__name__)


# Localização interna no nginx que efetivamente entrega o arquivo. Precisa
# estar marcada como `internal`, senão o controle daqui vira enfeite.
LOCALIZACAO_INTERNA = '/midia-protegida/'


# Faixa 1: arquivos públicos por desenho. A chave é o `model_name`, que o
# `texto_upload_path` grava como terceiro segmento do caminho.
MODELOS_PUBLICOS = frozenset({
    'casalegislativa',        # brasão — aparece no cabeçalho de toda página
    'partido',                # logo do partido
    'normajuridica',          # norma publicada é pública por obrigação legal
    'anexonormajuridica',
    'sessaoplenaria',         # pauta, ata e anexos da sessão
    'audienciapublica',       # o nome do modelo já diz
    'anexoaudienciapublica',
    'reuniao',                # pauta e ata de reunião de comissão
})


# Faixa 2: liberados ao público depois que a matéria foi a plenário.
MODELOS_LIBERADOS_PELO_PLENARIO = frozenset({
    'materialegislativa',
    'documentoacessorio',
})


def _model_name_do_caminho(caminho):
    """Extrai o `model_name` de `sapl/<publico|privado>/<model_name>/...`."""
    partes = caminho.split('/')
    if len(partes) >= 3 and partes[0] == 'sapl':
        return partes[2]
    return ''


def _materia_foi_a_plenario(materia_id):
    """A matéria entrou na pauta de uma sessão cuja data já passou.

    `data_ordem__lte=hoje` é deliberado: a pauta costuma ser montada dias antes
    da sessão, e liberar na montagem exporia justamente o que o cliente não
    quer que apareça antes do plenário.
    """
    from sapl.sessao.models import ExpedienteMateria, OrdemDia

    hoje = timezone.localdate()
    filtro = {'materia_id': materia_id, 'data_ordem__lte': hoje}

    return (ExpedienteMateria.objects.filter(**filtro).exists() or
            OrdemDia.objects.filter(**filtro).exists())


def _materia_do_arquivo(model_name, caminho):
    """Descobre a qual matéria o arquivo pertence, ou None.

    A busca é pelo caminho gravado no próprio campo, e não por parsing da URL,
    porque `texto_upload_path` tem duas formas (com e sem `pk_first`) e a
    posição da pk muda entre elas.

    `documentoacessorio` existe em dois apps — `materia` e `comissoes` — e
    ambos gravam na mesma pasta. Procurar primeiro no de matéria e tratar o
    não-encontrado como restrito resolve a colisão pelo lado seguro.
    """
    from sapl.materia.models import DocumentoAcessorio, MateriaLegislativa

    if model_name == 'materialegislativa':
        materia = MateriaLegislativa.objects.filter(
            Q(texto_original=caminho) | Q(pdf_assinado=caminho)
        ).only('id').first()
        return materia.id if materia else None

    documento = DocumentoAcessorio.objects.filter(
        Q(arquivo=caminho) | Q(pdf_assinado=caminho)
    ).only('materia_id').first()
    return documento.materia_id if documento else None


def pode_acessar(user, caminho):
    """Decide se `user` pode baixar o arquivo em `caminho`.

    `caminho` é relativo a MEDIA_ROOT, no mesmo formato gravado no FileField
    (ex.: `sapl/public/materialegislativa/2026/1219/texto.pdf`).
    """
    model_name = _model_name_do_caminho(caminho)

    if model_name in MODELOS_PUBLICOS:
        return True

    # Quem está logado enxerga tudo que a própria tela já lhe mostraria; o
    # controle fino de cada módulo continua sendo das views, não daqui.
    if user and user.is_authenticated:
        return True

    if model_name in MODELOS_LIBERADOS_PELO_PLENARIO:
        materia_id = _materia_do_arquivo(model_name, caminho)
        if materia_id is None:
            # Arquivo órfão, ou o documento acessório de comissão que divide a
            # pasta com o de matéria. Sem conseguir provar que é público, não é.
            return False
        return _materia_foi_a_plenario(materia_id)

    return False


def _caminho_seguro(caminho):
    """Normaliza e recusa qualquer tentativa de sair de MEDIA_ROOT."""
    caminho = posixpath.normpath(caminho.replace('\\', '/')).lstrip('/')
    if not caminho or caminho == '.' or caminho.startswith('..'):
        raise Http404()
    return caminho


def servir_midia(request, path):
    """Entrega um arquivo de mídia, se a regra de acesso permitir.

    Em produção quem lê o disco é o nginx, via `X-Accel-Redirect`: o Django só
    autoriza. Isso importa porque a Casa sobe PDFs de mais de 100 MB, e passar
    esse conteúdo pelo processo Python seria desperdício de memória.
    """
    caminho = _caminho_seguro(path)

    if not pode_acessar(request.user, caminho):
        usuario = getattr(request.user, 'username', 'anonimo')
        logger.info(
            'Acesso negado ao arquivo %s para o usuário %s.', caminho, usuario)

        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())

        from django.core.exceptions import PermissionDenied
        raise PermissionDenied()

    if settings.DEBUG:
        # Em desenvolvimento não há nginx na frente para honrar o cabeçalho.
        from django.views.static import serve
        return serve(request, caminho, document_root=settings.MEDIA_ROOT)

    if not os.path.exists(os.path.join(settings.MEDIA_ROOT, caminho)):
        raise Http404()

    resposta = HttpResponse(status=200)
    resposta['X-Accel-Redirect'] = iri_to_uri(LOCALIZACAO_INTERNA + caminho)
    # Deixa o nginx deduzir o tipo pela extensão; um valor aqui o sobrescreve.
    del resposta['Content-Type']
    return resposta
