# Guia de Implantação do provedor LexML no SGVP

Este guia resume o que é necessário para expor o provedor OAI-PMH do LexML que já vem embutido no SGVP (código em `sapl/lexml`). Ele parte do pressuposto de que você já instalou o SGVP 3.1+ (via `docs/instalacao31.rst`) e vai publicá-lo em produção (veja `docs/deploy.rst` para Nginx+Gunicorn).

## Pré-requisitos
- Python 3 com as dependências instaladas: `pip install -r requirements/requirements.txt` (usa `pyoai`, `lxml` e demais libs já listadas).
- Banco PostgreSQL com o SGVP configurado e migrado.
- Acesso administrativo ao sistema para cadastrar dados do LexML.
- Identificadores enviados pelo LexML (id do provedor, id do publicador e o XML de configuração validado).

## 1. Preparar o serviço do SGVP
- Gere o arquivo `.env` e configure `DEBUG=False`, banco, e demais variáveis usadas pelo Django.
- Colete estáticos para uso pelo Nginx: `./manage.py collectstatic --no-input --clear`.
- Suba a aplicação via Gunicorn/Nginx (modelos em `docker/.gunicorn_start.sh` e `docs/deploy.rst`). Certifique-se de que o domínio público configurado no Nginx corresponde ao valor que a Casa Legislativa usará em `endereco_web`; ele é usado para montar os identificadores OAI.

## 2. Configurações institucionais obrigatórias
O provedor LexML consome dados das seguintes telas:
- **Casa Legislativa** (`Sistema -> Casa Legislativa`): preencher `nome`, `sigla`, `municipio`, `uf`, `endereco_web` e `email`. Essas informações alimentam o `Identify`, a montagem do prefixo OAI e da URN.
- **Parâmetros da Aplicação** (`Sistema -> Parâmetros -> Configurações da Aplicação`): defina `Esfera Federação` (`M` ou `E`). O filtro de normas e a URN dependem disso.
- **Tipos de Norma Jurídica** (`Tabelas Auxiliares -> Norma Jurídica -> Tipo Norma Jurídica`): configure o campo `Equivalente LexML` com um dos valores aceitos (`lei`, `lei.organica`, `resolucao`, `regimento.interno`, etc.).
- **Normas Jurídicas**: cada norma deve ter `esfera_federacao`, `numero`, `ano`, `data`, `tipo` com equivalente LexML e `timestamp` preenchido (o formulário já grava o timestamp; para dados antigos, reabra e salve). Se houver `texto_integral`, ele será publicado como conteúdo; caso contrário, será apontado o link HTML da norma.

## 3. Cadastrar dados fornecidos pelo LexML
As telas ficam em `Sistema -> LexML`:
- **Provedor** (`/sistema/lexml/provedor/`): cadastre `id_provedor`, `nome`, dados do responsável e **cole o XML** enviado pelo LexML. O formulário valida o XML contra `sapl/templates/lexml/schema.xsd`; qualquer erro de schema ou formatação bloqueia o salvamento.
- **Publicador** (`/sistema/lexml/publicador/`): cadastre `id_publicador`, `nome`, `sigla`, `tipo` e dados do responsável.

O provedor OAI usa sempre o primeiro registro de cada tabela (`LexmlProvedor` e `LexmlPublicador`), portanto mantenha apenas um registro ativo e atualizado.

## 4. Endpoint OAI-PMH exposto
- URL: `https://<seu-dominio>/sistema/lexml/oai`
- `metadataPrefix` suportado: `oai_lexml`.
- Verbos principais:
  - `Identify` – retorna os dados da Casa Legislativa e o XML do provedor.
  - `ListRecords` – retorna os registros das normas como LexML, respeitando `from`, `until` (datas ISO 8601) e `batch_size` (padrão 10) para paginação.
- A URN e o identificador OAI são gerados a partir de `casa.sigla`, domínio de `casa.endereco_web`, tipo equivalente LexML, ano/número da norma e datas de publicação/vigência quando informadas.

## 5. Testes rápidos
Com o servidor rodando:
```bash
curl "http://localhost:8000/sistema/lexml/oai?verb=Identify"
curl "http://localhost:8000/sistema/lexml/oai?verb=ListRecords&metadataPrefix=oai_lexml&batch_size=50"
```

Para inspecionar pelo shell (usa o mesmo servidor interno em `sapl/lexml/OAIServer.py`):
```bash
./manage.py shell_plus <<'PY'
from sapl.lexml.OAIServer import OAIServerFactory, get_config
server = OAIServerFactory(get_config('http://127.0.0.1:8000/', 10))
print(server.handleRequest({'verb': 'ListRecords', 'metadataPrefix': 'oai_lexml'}).decode('utf-8'))
PY
```

## 6. Checklist de prontidão
- [ ] Casa Legislativa completa com `endereco_web` e `email`.
- [ ] `Esfera Federação` definida em Parâmetros da Aplicação.
- [ ] Tipos de Norma com `Equivalente LexML` configurado.
- [ ] Normas com `timestamp`, `esfera_federacao`, `data`, `numero` e `ano` corretos.
- [ ] Provedor e Publicador cadastrados; XML validado.
- [ ] `Identify` e `ListRecords` respondendo 200 e entregando XML válido.
