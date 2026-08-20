"""
Cliente para o pyHanko Sign Service (microserviço externo de assinatura digital).

Contrato real da API (descoberto via /openapi.json):
  POST /sign  — multipart/form-data
    pdf              : arquivo PDF (binário)
    pfx              : arquivo .pfx/.p12 (binário)
    pfx_password     : senha do PFX
    reason           : motivo (opcional)
    location         : local (opcional)
    signature_page   : página 1-based (opcional)
    signature_left/bottom/width/height : posição em pontos PDF (opcional)

  Resposta 200: Content-Type: application/pdf  →  bytes do PDF assinado
  Resposta 4xx/5xx: JSON com campo "detail"

A partir da fase C3 (AB#1473) o /sign também sabe COMPOR a página de autenticação
(código, URL de verificação, QR e os blocos da grade) — capacidade que antes só o
SAPL tinha. Quem quer delegar a composição usa
`assinar_pdf_com_pagina_autenticacao()`, que manda o bloco de parâmetros do
`auth_page` e devolve os cabeçalhos de resposta junto com o PDF.

Outros endpoints:
  POST /validate-pfx  – valida certificado PFX
  POST /validate      – valida assinaturas de um PDF
  POST /sign/batch    – assina múltiplos PDFs em lote
  GET  /              – health check
"""

import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class AssinaturaAPIError(Exception):
    """Erro retornado pelo microserviço de assinatura."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _api_configurada():
    """Retorna True se a API externa de assinatura está configurada."""
    return bool(getattr(settings, 'ASSINATURA_API_URL', '').strip())


def _montar_headers():
    """Authorization só é adicionado se ASSINATURA_API_KEY estiver preenchido."""
    headers = {}
    api_key = getattr(settings, 'ASSINATURA_API_KEY', '').strip()
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    return headers


def _url(endpoint):
    base = settings.ASSINATURA_API_URL.rstrip('/')
    endpoint = endpoint.lstrip('/')
    return f'{base}/{endpoint}'


class ResultadoAssinatura:
    """
    Resposta do /sign quando a composição da página é delegada ao microserviço.

    Além do PDF, o microserviço devolve em cabeçalhos o que só ele sabe depois de
    compor: o código impresso na página (que o cidadão digita na verificação
    pública) e qual bloco da grade esta assinatura ocupou.
    """

    __slots__ = ('pdf', 'codigo_autenticacao', 'signature_index',
                 'auth_page_aplicada', 'auth_page_suportado')

    def __init__(self, pdf, codigo_autenticacao, signature_index,
                 auth_page_aplicada, auth_page_suportado):
        self.pdf = pdf
        self.codigo_autenticacao = codigo_autenticacao
        self.signature_index = signature_index
        #: True quando ESTA chamada anexou a página de autenticação
        self.auth_page_aplicada = auth_page_aplicada
        #: False quando o microserviço não devolveu os cabeçalhos do auth_page —
        #: ou seja, é uma versão anterior à C2 e ignorou os parâmetros enviados.
        self.auth_page_suportado = auth_page_suportado


def _post_sign(files, data):
    """
    POST /sign com o tratamento de erro comum aos dois modos de uso.

    Retorna o `requests.Response` de sucesso; lança AssinaturaAPIError caso
    contrário. O corpo da resposta é o PDF assinado.
    """
    timeout = getattr(settings, 'ASSINATURA_API_TIMEOUT', 120)

    try:
        response = requests.post(
            _url('sign'),
            files=files,
            data=data,
            headers=_montar_headers(),
            timeout=timeout,
        )
    except requests.exceptions.ConnectionError as exc:
        logger.error(f'[assinatura-api] Falha de conexao: {exc}')
        raise AssinaturaAPIError(
            'Nao foi possivel conectar ao microservico de assinatura. '
            'Verifique se o servico esta disponivel.'
        )
    except requests.exceptions.Timeout:
        raise AssinaturaAPIError(
            f'Timeout ao aguardar resposta do microservico de assinatura '
            f'(limite: {timeout}s).'
        )
    except requests.exceptions.RequestException as exc:
        logger.error(f'[assinatura-api] Erro inesperado: {exc}')
        raise AssinaturaAPIError(f'Erro ao comunicar com o microservico: {exc}')

    if not response.ok:
        try:
            detail = response.json()
            msg = detail.get('detail') or detail.get('error') or str(detail)
        except Exception:
            msg = response.text[:300] or f'HTTP {response.status_code}'
        logger.error(f'[assinatura-api] Erro HTTP {response.status_code}: {msg}')
        raise AssinaturaAPIError(msg, status_code=response.status_code)

    # A API retorna o PDF assinado diretamente como application/pdf
    content_type = response.headers.get('Content-Type', '')
    if 'pdf' not in content_type and len(response.content) < 100:
        raise AssinaturaAPIError(
            f'Resposta inesperada do microservico (Content-Type: {content_type}).'
        )

    return response


def assinar_pdf_com_pagina_autenticacao(
        pdf_bytes, *, certificado_bytes, senha,
        verification_url_base, assinaturas,
        casa_legislativa=None, signer_name=None, signer_role=None,
        codigo_autenticacao=None, brasao_bytes=None, brasao_filename='brasao.png',
        reason=None, location=None):
    """
    Assina delegando ao microserviço a composição da página de autenticação.

    Diferença para `assinar_pdf_via_api`: aqui o SAPL **não** monta a página nem
    calcula a posição do bloco — manda os dados da casa legislativa e o
    microserviço compõe (fase C3 da convergência dos assinadores, AB#1473).
    Por isso nenhum `signature_*` é enviado: quem conhece a grade é o
    microserviço, e mandar coordenada junto faz o `auth_page` e a posição
    explícita disputarem o mesmo campo.

    Parâmetros
    ----------
    verification_url_base : str  — URL pública de verificação SEM o `?codigo=`
                                   (o microserviço acrescenta)
    assinaturas : list[dict]     — blocos a desenhar
                                   ([{nome_assinante, cargo, data_assinatura}])
    casa_legislativa : str       — nome impresso no cabeçalho da página
    signer_name / signer_role    — nome e cargo exibidos (no legislativo, o nome
                                   parlamentar do vereador, não o CN do certificado)
    codigo_autenticacao : str    — código já emitido. OBRIGATÓRIO da segunda
                                   assinatura em diante: o PDF mudou ao ser
                                   assinado e o hash de agora não reproduz o que
                                   está impresso na página. Na primeira, deixe
                                   vazio — o microserviço deriva do próprio PDF.
    brasao_bytes : bytes         — brasão da câmara. Mande em TODAS as assinaturas
                                   da mesma matéria: ele desloca a grade em 3 mm e
                                   omiti-lo depois desalinharia os blocos seguintes.

    Retorna: ResultadoAssinatura.
    Lança: AssinaturaAPIError em caso de erro.
    """
    if not _api_configurada():
        raise AssinaturaAPIError(
            'Microserviço de assinatura não configurado (ASSINATURA_API_URL vazio).'
        )

    files = {
        'pdf': ('documento.pdf', pdf_bytes, 'application/pdf'),
        'pfx': ('certificado.pfx', certificado_bytes, 'application/octet-stream'),
    }
    if brasao_bytes:
        files['brasao'] = (brasao_filename, brasao_bytes, 'application/octet-stream')

    data = {
        'pfx_password': senha,
        'auth_page': 'auto',
        'verification_url_base': verification_url_base,
        'assinaturas': json.dumps(assinaturas or [], ensure_ascii=False),
    }
    if casa_legislativa:
        data['casa_legislativa'] = casa_legislativa
    if signer_name:
        data['signer_name'] = signer_name
    if signer_role:
        data['signer_role'] = signer_role
    if codigo_autenticacao:
        data['codigo_autenticacao'] = codigo_autenticacao
    if reason:
        data['reason'] = reason
    if location:
        data['location'] = location

    response = _post_sign(files, data)

    headers = response.headers
    # A ausência do cabeçalho é o sinal de que o microserviço IGNOROU o auth_page
    # (versão anterior à C2). Quem chama precisa saber: sem a composição, o PDF
    # sai sem página de autenticação e sem código verificável.
    auth_page_suportado = 'X-Auth-Page-Applied' in headers

    try:
        signature_index = int(headers.get('X-Signature-Index', ''))
    except (TypeError, ValueError):
        signature_index = None

    resultado = ResultadoAssinatura(
        pdf=response.content,
        codigo_autenticacao=(headers.get('X-Codigo-Autenticacao') or '').strip(),
        signature_index=signature_index,
        auth_page_aplicada=(headers.get('X-Auth-Page-Applied', '').strip().lower()
                            == 'true'),
        auth_page_suportado=auth_page_suportado,
    )
    logger.info(
        '[assinatura-api] PDF assinado com pagina de autenticacao composta pelo '
        f'microservico (bloco={resultado.signature_index}, '
        f'pagina_anexada={resultado.auth_page_aplicada}).'
    )
    return resultado


def assinar_pdf_via_api(pdf_bytes, *, certificado_bytes, senha,
                        reason=None, location=None,
                        signature_page=None,
                        signature_left=None, signature_bottom=None,
                        signature_width=None, signature_height=None):
    """
    Envia o PDF ao pyHanko Sign Service e retorna o PDF assinado como bytes.

    Modo "posição explícita": o PDF já chega composto e o chamador diz onde o
    carimbo vai. Para delegar a composição da página de autenticação ao
    microserviço, use `assinar_pdf_com_pagina_autenticacao`.

    Parâmetros
    ----------
    pdf_bytes : bytes           — PDF a assinar
    certificado_bytes : bytes   — arquivo .pfx/.p12
    senha : str                 — senha do certificado
    reason : str                — motivo (exibido na assinatura visual)
    location : str              — local (exibido na assinatura visual)
    signature_page : int        — página 1-based (None = última)
    signature_left/bottom/width/height : float — coordenadas em pontos PDF

    Retorna: bytes do PDF assinado.
    Lança: AssinaturaAPIError em caso de erro.
    """
    if not _api_configurada():
        raise AssinaturaAPIError(
            'Microserviço de assinatura não configurado (ASSINATURA_API_URL vazio).'
        )

    files = {
        'pdf': ('documento.pdf', pdf_bytes, 'application/pdf'),
        'pfx': ('certificado.pfx', certificado_bytes, 'application/octet-stream'),
    }
    data = {'pfx_password': senha}

    if reason:
        data['reason'] = reason
    if location:
        data['location'] = location
    if signature_page is not None:
        data['signature_page'] = str(signature_page)
    if signature_left is not None:
        data['signature_left'] = str(signature_left)
    if signature_bottom is not None:
        data['signature_bottom'] = str(signature_bottom)
    if signature_width is not None:
        data['signature_width'] = str(signature_width)
    if signature_height is not None:
        data['signature_height'] = str(signature_height)

    response = _post_sign(files, data)

    logger.info('[assinatura-api] PDF assinado com sucesso pelo microservico.')
    return response.content


def assinar_pdf_lote_via_api(itens, *, certificado_bytes, senha,
                             reason=None, location=None,
                             download_workers=8):
    """
    Assina múltiplos PDFs em uma única chamada POST /sign/batch e baixa os
    resultados em paralelo via download_url do S3.

    Parâmetros
    ----------
    itens : list[dict]  — cada item deve ter:
        'id'              : identificador (qualquer hashable — preservado no resultado)
        'pdf_bytes'       : bytes do PDF a assinar
        'signature_page'  : int 1-based (opcional, mesmo para todos)
        'signature_left'  : float (opcional)
        'signature_bottom': float (opcional)
        'signature_width' : float (opcional)
        'signature_height': float (opcional)
    certificado_bytes : bytes  — arquivo .pfx/.p12 (compartilhado por todos)
    senha : str                — senha do certificado
    reason, location : str     — metadados da assinatura
    download_workers : int     — threads para baixar resultados do S3 (default 8)

    Retorna: list[dict] na mesma ordem de `itens`, com campos:
        'id'        : o mesmo id do item de entrada
        'ok'        : True / False
        'pdf_bytes' : bytes do PDF assinado (apenas quando ok=True)
        'error'     : mensagem de erro (apenas quando ok=False)
    """
    if not _api_configurada():
        raise AssinaturaAPIError(
            'Microserviço de assinatura não configurado (ASSINATURA_API_URL vazio).'
        )

    timeout = getattr(settings, 'ASSINATURA_API_TIMEOUT', 120)

    # ── 1. Enviar todos os PDFs em uma única chamada /sign/batch ─────────────
    # O campo 'signature_page/left/bottom/width/height' é único para o lote —
    # usamos os valores do primeiro item (todos partilham a mesma posição).
    primeiro = itens[0] if itens else {}
    data = {'pfx_password': senha}
    if reason:
        data['reason'] = reason
    if location:
        data['location'] = location
    if primeiro.get('signature_page') is not None:
        data['signature_page'] = str(primeiro['signature_page'])
    if primeiro.get('signature_left') is not None:
        data['signature_left'] = str(primeiro['signature_left'])
    if primeiro.get('signature_bottom') is not None:
        data['signature_bottom'] = str(primeiro['signature_bottom'])
    if primeiro.get('signature_width') is not None:
        data['signature_width'] = str(primeiro['signature_width'])
    if primeiro.get('signature_height') is not None:
        data['signature_height'] = str(primeiro['signature_height'])

    # multipart: múltiplos campos 'pdfs' + um 'pfx'
    files = [('pfx', ('certificado.pfx', certificado_bytes, 'application/octet-stream'))]
    for idx, item in enumerate(itens):
        filename = f'doc{idx + 1}.pdf'
        files.append(('pdfs', (filename, item['pdf_bytes'], 'application/pdf')))

    try:
        response = requests.post(
            _url('sign/batch'),
            files=files,
            data=data,
            headers=_montar_headers(),
            timeout=timeout,
        )
    except requests.exceptions.ConnectionError as exc:
        logger.error(f'[assinatura-api/batch] Falha de conexão: {exc}')
        raise AssinaturaAPIError(
            'Não foi possível conectar ao microserviço de assinatura.'
        )
    except requests.exceptions.Timeout:
        raise AssinaturaAPIError(
            f'Timeout ao aguardar resposta do microserviço (limite: {timeout}s).'
        )
    except requests.exceptions.RequestException as exc:
        raise AssinaturaAPIError(f'Erro ao comunicar com o microserviço: {exc}')

    if not response.ok:
        try:
            detail = response.json()
            msg = detail.get('detail') or str(detail)
        except Exception:
            msg = response.text[:300] or f'HTTP {response.status_code}'
        logger.error(f'[assinatura-api/batch] Erro HTTP {response.status_code}: {msg}')
        raise AssinaturaAPIError(msg, status_code=response.status_code)

    try:
        batch_result = response.json()
    except Exception:
        raise AssinaturaAPIError('Resposta do /sign/batch não é JSON válido.')

    resultados_api = batch_result.get('results', [])
    if len(resultados_api) != len(itens):
        raise AssinaturaAPIError(
            f'Resposta do /sign/batch retornou {len(resultados_api)} itens, '
            f'esperado {len(itens)}.'
        )

    logger.info(f'[assinatura-api/batch] {len(resultados_api)} PDFs assinados. Baixando...')

    # ── 2. Baixar PDFs assinados em paralelo via download_url ─────────────────
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _baixar(idx_url):
        idx, url = idx_url
        try:
            r = requests.get(url, timeout=60)
            if not r.ok:
                return idx, None, f'Erro ao baixar PDF assinado: HTTP {r.status_code}'
            if not r.content[:5] == b'%PDF-':
                return idx, None, 'Conteúdo baixado não é um PDF válido.'
            return idx, r.content, None
        except Exception as exc:
            return idx, None, str(exc)

    urls_indexadas = [
        (idx, res['download_url'])
        for idx, res in enumerate(resultados_api)
    ]

    resultados_finais = [None] * len(itens)
    with ThreadPoolExecutor(max_workers=download_workers) as executor:
        futures = {executor.submit(_baixar, item): item for item in urls_indexadas}
        for future in as_completed(futures):
            idx, pdf_bytes, error = future.result()
            item_id = itens[idx]['id']
            if error:
                logger.error(f'[assinatura-api/batch] item {idx} (id={item_id}): {error}')
                resultados_finais[idx] = {'id': item_id, 'ok': False, 'error': error}
            else:
                resultados_finais[idx] = {'id': item_id, 'ok': True, 'pdf_bytes': pdf_bytes}

    return resultados_finais


def validar_pfx_via_api(certificado_bytes, senha):
    """
    Valida um certificado PFX no microservico.
    Retorna dict com informacoes do certificado ou lanca AssinaturaAPIError.
    """
    if not _api_configurada():
        raise AssinaturaAPIError('ASSINATURA_API_URL nao configurado.')

    files = {'pfx': ('certificado.pfx', certificado_bytes, 'application/octet-stream')}
    data = {'pfx_password': senha}
    timeout = getattr(settings, 'ASSINATURA_API_TIMEOUT', 120)

    try:
        response = requests.post(
            _url('validate-pfx'),
            files=files,
            data=data,
            headers=_montar_headers(),
            timeout=timeout,
        )
    except requests.exceptions.RequestException as exc:
        raise AssinaturaAPIError(f'Erro ao comunicar com o microservico: {exc}')

    if not response.ok:
        try:
            detail = response.json()
            msg = detail.get('detail') or str(detail)
        except Exception:
            msg = response.text[:300] or f'HTTP {response.status_code}'
        raise AssinaturaAPIError(msg, status_code=response.status_code)

    try:
        return response.json()
    except Exception:
        return {}


def verificar_health():
    """
    Verifica se o microservico esta disponivel (GET /).
    Retorna (ok: bool, mensagem: str).
    """
    if not _api_configurada():
        return False, 'ASSINATURA_API_URL nao configurado.'

    try:
        response = requests.get(
            _url('/'),
            headers=_montar_headers(),
            timeout=10,
        )
        if response.ok:
            return True, 'Microservico disponivel.'
        return False, f'Microservico respondeu com HTTP {response.status_code}.'
    except requests.exceptions.RequestException as exc:
        return False, f'Falha de conexao: {exc}'
