"""
O lote que delega a composicao ao microservico (AB#1473).

Regressao do autografo 77/2026 da Camara de Franco da Rocha: o lote compunha a
pagina de autenticacao por conta propria e mandava ao `/sign/batch` a coordenada do
bloco JUNTO COM o numero da pagina. O numero veio errado uma vez e o carimbo foi
parar no corpo do documento, por cima do Art. 14.

O teste que vale por todos e
`test_nenhum_signature_star_e_enviado`: enquanto ninguem daqui escolher a pagina,
ninguem daqui erra a pagina.
"""

from unittest.mock import patch

import pytest

from sapl.materia.assinatura_api_client import (
    AssinaturaAPIError,
    ResultadoAssinatura,
    assinar_lote_com_pagina_autenticacao,
)


def _item(pk, codigo=None):
    return {
        'id': pk,
        'pdf_bytes': b'%PDF-1.4 fake',
        'verification_url_base': f'https://sapl.exemplo.leg.br/materia/{pk}/verificar',
        'assinaturas': [{
            'nome_assinante': 'Vereador Joao Souza',
            'cargo': 'Vereador(a)',
            'data_assinatura': '11/09/2026 10:05',
        }],
        'codigo_autenticacao': codigo,
    }


def _resultado(codigo='6D22F3EFCE74DA9B', pagina_anexada=True, suportado=True):
    return ResultadoAssinatura(
        pdf=b'%PDF-1.4 assinado',
        codigo_autenticacao=codigo,
        signature_index=0,
        auth_page_aplicada=pagina_anexada,
        auth_page_suportado=suportado,
    )


@pytest.fixture
def api_configurada():
    with patch(
        'sapl.materia.assinatura_api_client._api_configurada', return_value=True
    ):
        yield


def test_nenhum_signature_star_e_enviado(api_configurada):
    """
    A causa raiz do carimbo sobre o Art. 14. Se um `signature_page`/`signature_left`
    voltar a sair daqui, o SAPL voltou a escolher a posicao — e a poder erra-la.
    """
    with patch(
        'sapl.materia.assinatura_api_client.assinar_pdf_com_pagina_autenticacao',
        return_value=_resultado(),
    ) as chamada:
        assinar_lote_com_pagina_autenticacao(
            [_item(1)], certificado_bytes=b'pfx', senha='senha',
        )

    _args, kwargs = chamada.call_args
    proibidos = [k for k in kwargs if k.startswith('signature_')]
    assert proibidos == [], (
        f'o lote voltou a mandar posicao ao microservico: {proibidos}'
    )


def test_cada_documento_leva_a_propria_url_e_o_proprio_codigo(api_configurada):
    """
    O que o `/sign/batch` nao conseguia fazer: os parametros da composicao sao por
    documento, e um campo do lote inteiro nao os comporta.
    """
    with patch(
        'sapl.materia.assinatura_api_client.assinar_pdf_com_pagina_autenticacao',
        return_value=_resultado(),
    ) as chamada:
        assinar_lote_com_pagina_autenticacao(
            [_item(1), _item(2, codigo='AAAA1111BBBB2222')],
            certificado_bytes=b'pfx', senha='senha',
        )

    primeiro, segundo = chamada.call_args_list
    assert primeiro.kwargs['verification_url_base'].endswith('/materia/1/verificar')
    assert segundo.kwargs['verification_url_base'].endswith('/materia/2/verificar')
    # Na primeira assinatura o codigo sai do proprio PDF, do lado de la.
    assert primeiro.kwargs['codigo_autenticacao'] is None
    # Da segunda em diante ele ja esta impresso na pagina e tem de ser devolvido.
    assert segundo.kwargs['codigo_autenticacao'] == 'AAAA1111BBBB2222'


def test_o_codigo_so_volta_quando_a_pagina_foi_anexada(api_configurada):
    """
    Pagina que ja existia nao emite codigo novo — gravar o que veio no cabecalho
    sobrescreveria o codigo impresso no documento.
    """
    with patch(
        'sapl.materia.assinatura_api_client.assinar_pdf_com_pagina_autenticacao',
        side_effect=[
            _resultado(pagina_anexada=True),
            _resultado(codigo='OUTRO', pagina_anexada=False),
        ],
    ):
        resultados = assinar_lote_com_pagina_autenticacao(
            [_item(1), _item(2, codigo='6D22F3EFCE74DA9B')],
            certificado_bytes=b'pfx', senha='senha',
        )

    assert resultados[0]['codigo_autenticacao'] == '6D22F3EFCE74DA9B'
    assert resultados[1]['codigo_autenticacao'] is None


def test_um_documento_que_falha_nao_derruba_os_outros(api_configurada):
    with patch(
        'sapl.materia.assinatura_api_client.assinar_pdf_com_pagina_autenticacao',
        side_effect=[
            AssinaturaAPIError('certificado vencido'),
            _resultado(),
        ],
    ):
        resultados = assinar_lote_com_pagina_autenticacao(
            [_item(1), _item(2)], certificado_bytes=b'pfx', senha='senha',
        )

    assert [r['id'] for r in resultados] == [1, 2], 'a ordem de entrada e preservada'
    assert resultados[0]['ok'] is False
    assert 'certificado vencido' in resultados[0]['error']
    assert resultados[1]['ok'] is True


def test_microservico_sem_auth_page_e_recusado(api_configurada):
    """
    Sem os cabecalhos do auth_page o microservico ignorou a composicao: o PDF sairia
    sem pagina de autenticacao e sem codigo verificavel. Gravar isso e pior que falhar.
    """
    with patch(
        'sapl.materia.assinatura_api_client.assinar_pdf_com_pagina_autenticacao',
        return_value=_resultado(suportado=False),
    ):
        resultados = assinar_lote_com_pagina_autenticacao(
            [_item(1)], certificado_bytes=b'pfx', senha='senha',
        )

    assert resultados[0]['ok'] is False
    assert 'X-Auth-Page-Applied' in resultados[0]['error']


def test_api_nao_configurada_falha_antes_de_assinar_qualquer_coisa():
    with patch(
        'sapl.materia.assinatura_api_client._api_configurada', return_value=False
    ):
        with pytest.raises(AssinaturaAPIError, match='ASSINATURA_API_URL'):
            assinar_lote_com_pagina_autenticacao(
                [_item(1)], certificado_bytes=b'pfx', senha='senha',
            )
