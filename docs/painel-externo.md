# Envio da pauta a painel de votação externo

Casas que votam num painel de terceiros podem enviar a pauta da sessão
plenária (matérias do Expediente e da Ordem do Dia) a esse painel com um
clique, sem redigitar nada. O SAPL entrega a pauta; o painel implementa o
recebimento descrito aqui.

## Como ligar

Em **Sistema → Configurações da Aplicação**, seção **Painel de Votação
Externo**:

| Campo | O que informar |
| --- | --- |
| Enviar a pauta da sessão a painel de votação externo? | Sim. O padrão é Não |
| URL do painel de votação externo | Endereço **completo** do endpoint que recebe a pauta |
| Chave de acesso ao painel externo (API key) | Chave fornecida pelo painel, enviada no header `X-API-KEY` |

Para ligar, URL e chave são obrigatórias. A chave salva nunca é exibida de
volta: deixar o campo em branco ao salvar mantém a chave atual. Ela também não
aparece em `/api/base/appconfig/`.

Para o SGVP, a URL é `https://<endereço-do-sgvp>/api/integracaoLegisSessao`.

A URL precisa de domínio completo (`painel.exemplo.leg.br`) ou IP
(`http://10.0.0.5:8080/...`): o validador recusa nome de host sem domínio,
como `http://painel:8080/`.

## Como enviar

Na tela da sessão plenária, o botão **Enviar pauta ao painel** aparece só com
a integração ligada e para quem tem a permissão de alterar sessão plenária
(`sessao.change_sessaoplenaria`). A tela mostra o que o painel respondeu.

Reenviar é seguro do lado do SAPL: o painel recebe sempre a pauta inteira e
identifica a sessão pelo campo `sessao`.

## O que o SAPL envia

`POST` na URL configurada, timeout de 15 segundos:

```
Content-Type: application/json
X-API-KEY: <chave configurada>
```

```json
{
  "sessao": 123,
  "sessao_nome": "10ª Sessão Ordinária da 1ª Sessão Legislativa da 20ª Legislatura",
  "tipo_sessao": {"id": 1, "nome": "Ordinária"},
  "expediente": [
    {"materia": {"id_materia": 455, "tipo_votacao": "Leitura", "...": "mesmos campos da matéria abaixo"}}
  ],
  "ordem_dia": [
    {
      "numero_ordem": 1,
      "materia": {
        "id_materia": 456,
        "nome_documento": "PL 12/2026 - Projeto de Lei",
        "autoria": [{"id": 7, "nome": "Vereador Exemplo"}],
        "tipo_materia": {"id": 1, "nome": "Projeto de Lei"},
        "ementa": "Dispõe sobre ...",
        "status": "",
        "status_sessao": "",
        "status_tramitacao": "Aguardando votação",
        "fase_materia": "Único",
        "quorum": null,
        "tipo_votacao": "Nominal",
        "pdf_url": "https://sapl.exemplo.leg.br/media/...",
        "pdf_assinado": false,
        "pdf_assinado_url": null,
        "tramitacao_pdf_url": "https://sapl.exemplo.leg.br/relatorios/456/tramitacao"
      }
    }
  ]
}
```

| Campo | Significado |
| --- | --- |
| `sessao` | id da sessão plenária no SAPL; use como chave para criar ou atualizar a sessão no painel |
| `tipo_sessao.id`, `tipo_materia.id` | ids do SAPL; o painel mantém o mapeamento para os tipos dele |
| `status` / `status_sessao` | resultado já registrado na sessão (nome do resultado da votação, `Retirado`, `Leitura`) ou vazio |
| `status_tramitacao`, `fase_materia` | status e turno da última tramitação até a data da sessão |
| `quorum` | `quorum_minimo_votacao` do tipo de matéria, quando informado |
| `tipo_votacao` | `Simbólica`, `Nominal`, `Secreta` ou `Leitura` |
| `pdf_url` | PDF assinado, texto original ou, na falta deles, os documentos acessórios em PDF reunidos |

Para conferir a pauta sem enviar: `GET /api/sessao/sessaoplenaria/{id}/materias/`
(só com a integração ligada).

## O que o SAPL espera de volta

Qualquer `2xx` é sucesso. Se o corpo for JSON com `message` ou `detail`, o
texto aparece para o operador, inclusive nas recusas (`4xx`/`5xx`), que o SAPL
devolve à tela como `502`. Falha de rede ou timeout aparece como mensagem
genérica; o detalhe vai para o log do SAPL.

## Migração do `.env`

Até a versão anterior, a URL e a chave vinham de `SESSAO_MATERIAS_API_URL` e
`SESSAO_MATERIAS_API_KEY`. A migração `base/0067` copia esses valores para a
tela (anexando `/api/integracaoLegisSessao` à URL) e liga o envio quando há
chave. Depois do deploy, confira a tela e remova as variáveis do `.env`: o
código não as lê mais.
