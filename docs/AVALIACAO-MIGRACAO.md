# Avaliação técnica — SAPL: Dokploy, S3 e saída para o SGVP Legislativo

Levantamento feito sobre `Move-System/sapl` (branch `3.1.x`, versão declarada `3.1.164-RC5`),
`Move-System/sgvp-legislativo-backend` (`c7c24be`) e `Move-System/sgvp-legislativo-frontend` (`0d9b141`).

Três perguntas respondidas:

1. Dá para rodar o SAPL em ambiente gerenciado tipo Dokploy?
2. Dá para mover documentos e gestão documental para S3 "sem impacto nenhum"?
3. Quanto falta para tirar o cliente Franco do SAPL e colocá-lo no SGVP Legislativo?

---

## 0. Antes de tudo: credencial de produção exposta

`docker/docker-compose.yaml:48`

```
DATABASE_URL: postgresql://bruno:Sapl%402025@legisinc.com.br:5432/sapl
```

O repositório `Move-System/sapl` é **público**. Isso é usuário, senha, host e banco de um
Postgres acessível pela internet, versionado em claro. Rotacionar a senha e restringir o
`pg_hba`/firewall vem antes de qualquer discussão de arquitetura. Remover do arquivo não
basta — o valor continua no histórico do Git.

Outros valores fracos no mesmo arquivo (`ADMIN_PASSWORD: interlegis`, `JWT_SECRET:
your-secret-key-change-this`) são defaults de exemplo, mas se foram usados em produção
valem o mesmo tratamento.

---

## 1. SAPL em Dokploy

### O que o sistema é, na prática

| Dimensão | Situação |
|---|---|
| Framework | Django **2.2.28** — fim de suporte em abril/2022 |
| Runtime | Python 3.12, sustentado por dois *monkey-patches* em `sapl/settings.py` (`utc_tzinfo_factory` e normalização de engine do `dj-database-url` 0.5) |
| Tamanho | ~72 mil linhas Python, 496 migrations, 130 models, 14 apps de negócio |
| Processo | Container único: `nginx` + `gunicorn` (socket unix), orquestrados por `docker/startup_scripts/start.sh` |
| Dependências externas | PostgreSQL, Solr 8.11 (ZooKeeper embutido), OnlyOffice DocumentServer, SMTP, reCAPTCHA |
| Estado local no container | `media/` (todos os documentos), `data/secret.key`, `/var/tmp/django_cache`, `sapl.log` |

### Veredito: roda em Dokploy, sim — com sete ajustes concretos

**A favor**

- `docker/Dockerfile` já é multi-stage e funcional; `collectstatic` roda no build.
- Os artefatos do frontend Vue estão commitados (`sapl/static/sapl/frontend/`, 200 arquivos, e
  `frontend/webpack-stats.json`). O build **não precisa de Node** — isso simplifica muito o pipeline.
- Configuração inteiramente por variável de ambiente (`python-decouple`).
- Já existem `/health`, `/ready`, `/version` (`sapl/api/views_health.py`).
- Solr é **opcional**: com `USE_SOLR=False` o Haystack fica com engine vazia e o waffle
  `SOLR_SWITCH` esconde a busca textual nos filtros de matéria, norma e sessão.

**Ajustes necessários**

1. **O healthcheck provavelmente responde 403 hoje.**
   `sapl/endpoint_restriction_middleware.py` bloqueia `/health`, `/ready` e `/metrics` comparando
   `REMOTE_ADDR` com uma lista literal que contém CIDRs (`'10.0.0.0/8'`, `'172.16.0.0/12'`) —
   **sem nenhum parsing de rede**. Um IP `172.18.0.4` nunca vai casar com a string `'172.16.0.0/12'`.
   Pior: como o gunicorn atende em socket unix, o `REMOTE_ADDR` que chega ao Django não é o IP real
   do cliente. O Traefik do Dokploy vai marcar o serviço como não saudável.
   Correção: usar `ipaddress.ip_network` e ler `X-Forwarded-For` (o nginx já envia).

2. **Proxy duplo.** A imagem embute nginx e o Dokploy já tem Traefik na frente.
   Funciona (Traefik → nginx:80 → gunicorn), mas falta em `settings.py`:
   `SECURE_PROXY_SSL_HEADER`, `USE_X_FORWARDED_HOST`, e `ALLOWED_HOSTS` está em `['*']`.
   Com HTTPS terminando no Traefik, o Django continua achando que a requisição é HTTP.

3. **Volumes obrigatórios.** `/var/interlegis/sapl/media` (os documentos) e
   `/var/interlegis/sapl/data`. O `start.sh` gera o `SECRET_KEY` e grava em `data/secret.key`;
   sem persistir esse volume, **cada deploy derruba todas as sessões** e invalida links de
   recuperação de senha. Melhor ainda: fixar `SECRET_KEY` como variável de ambiente no Dokploy
   e parar de depender do arquivo.

4. **Migrations no boot.** `start.sh` roda `makemigrations tce` + `migrate` a cada start.
   Com uma réplica, tudo bem. Com duas, é corrida. Manter réplica única ou extrair o migrate
   para um passo de deploy.

5. **Cache em disco local.** `CACHES` aponta para `FileBasedCache` em `/var/tmp/django_cache`,
   que não é volume. O callback do OnlyOffice usa esse cache para coordenar o salvamento
   (`cache.set(f'proposicao_saved_{pk}')` em `sapl/materia/onlyoffice_views.py`). Com mais de
   uma réplica, o editor passa a salvar de forma inconsistente. Escalar horizontalmente exige Redis.

6. **Logs vão para arquivo, não para stdout.** `sapl.log` rotativo (15 MB × 10) dentro do
   container — invisível no painel do Dokploy. `LOGGING_CONSOLE_VERBOSE=True` ajuda, mas o
   handler de arquivo continua.

7. **`ADMIN_PASSWORD` é obrigatório** ou o container encerra (`start.sh:226`).

### Dimensionamento

| Serviço | Memória mínima realista |
|---|---|
| OnlyOffice DocumentServer | 2 GB (bundle com Postgres, Redis e RabbitMQ internos) |
| Solr 8.11 + ZooKeeper embutido | 1 GB |
| SAPL (3 workers gthread × 8 threads, teto de 300 MB/worker) | 1,5 GB |
| PostgreSQL | 1 GB |

**4 vCPU / 8 GB** para uma casa legislativa com conforto. **4 GB** só abrindo mão do Solr
(a busca passa a ser por metadados, não pelo conteúdo dos PDFs).

Ainda: o compose usa `postgres:10.5-alpine`, sem suporte desde 2022. Subir para 14 ou 15 —
lembrando que `configure_pg_timezone()` no `start.sh` executa `ALTER DATABASE ... SET timezone`
e `ALTER ROLE`, o que exige owner e superusuário respectivamente. Em Postgres gerenciado isso
falha e derruba o boot (`exit 1`); vale tornar esse passo tolerante a falha.

### Rede OnlyOffice ↔ SAPL

São **duas URLs distintas** e as duas precisam existir:

- `ONLYOFFICE_URL` — o navegador do usuário carrega o editor daqui. Precisa de domínio público.
- `SAPL_INTERNAL_URL` — o DocumentServer busca e devolve o documento por aqui. Precisa resolver
  dentro da rede do Dokploy (nome do serviço).

Na prática, o OnlyOffice precisa de subdomínio próprio no Dokploy.

**Esforço para deixar redondo: 1 a 2 dias**, incluindo o fix do healthcheck, os ajustes de proxy
e um `docker-compose.dokploy.yml` enxuto.

---

## 2. Documentos no S3

### Resposta curta

É possível. **"Sem impacto nenhum" não é verdade** — não é trocar uma variável de ambiente.

### Por quê

O SAPL não usa `django-storages` (não está em `requirements/requirements.txt`). O `MEDIA_ROOT`
é filesystem local e o nginx serve `/media/` direto do disco. Acima disso, existem
**43 pontos de código** que acessam o disco diretamente — via `.path` de `FileField` ou montando
caminhos com `MEDIA_ROOT`. `Storage.path()` levanta `NotImplementedError` em S3: cada um desses
pontos é uma quebra em tempo de execução.

Concentração:

| Arquivo | Ocorrências |
|---|---|
| `sapl/materia/views.py` | 26 |
| `sapl/materia/views_assinatura.py` | 23 |
| `sapl/base/search_indexes.py` | 8 |
| `sapl/utils.py` | 7 |
| `sapl/utils_template.py` | 5 |
| `sapl/tce/admin_views.py` | 5 |
| demais (13 arquivos) | 1–4 cada |

### Fluxos que quebram, nominalmente

- **Assinatura digital** (`views_assinatura.py`) — o pyhanko abre e regrava os PDFs por caminho.
- **OnlyOffice** — `open(proposicao.texto_original.path, 'rb')` para entregar o `.docx` ao editor.
- **Hash de proposição** — `gerar_hash_arquivo()` (`sapl/utils.py:813`) faz `open(arquivo)` sobre
  um caminho. É esse hash que valida o link de confirmação da proposição.
- **ZIP "baixar todos os documentos"** — `sapl/materia/views.py:3507` em diante.
- **Indexação no Solr** — `sapl/base/search_indexes.py:39` extrai o texto do arquivo por caminho.
- **Relatórios e etiquetas em PDF** — embutem o logotipo via `casa.logotipo.path`.
- **`OverwriteStorage`** (`sapl/utils.py:1212`) — faz `os.remove(MEDIA_ROOT/name)`.
- **`clear_thumbnails_cache`** (`sapl/utils.py:182`) — varre o diretório pai do arquivo.
- **Validador de tipo de arquivo** — usa `value.path` quando o valor não é um upload novo.

Some-se `easy_thumbnails` + `image_cropping` na foto do parlamentar: funcionam com S3, mas com
ida-e-volta de rede a cada geração de miniatura.

### O que a migração conserta de brinde

Hoje `location /media/` no nginx serve **tudo**, inclusive `sapl/private/...`, que é onde ficam
documentos administrativos e proposições (`texto_upload_path` em `sapl/utils.py:873` decide o
prefixo `private`/`public`). Não há controle de acesso: quem souber a URL baixa o arquivo.

No mesmo tema, `onlyoffice_download` (`sapl/materia/onlyoffice_views.py:114`) só verifica
permissão **se houver usuário autenticado** — uma requisição anônima cai fora do `if` e recebe
o documento. Vale corrigir independentemente do S3.

Com S3 + URL pré-assinada, os dois problemas passam a ser controlados por padrão.

### Plano em três camadas

| Camada | Trabalho | Esforço |
|---|---|---|
| 1. Compatibilidade de código | Adicionar `django-storages[boto3]`, `DEFAULT_FILE_STORAGE` por env, e um helper `abrir_arquivo(fieldfile)` / `caminho_local_temporario(fieldfile)` que baixa para tempfile quando o storage não é local. Trocar os 43 pontos por esse helper. | 2–3 dias de código, mecânico |
| 2. Entrega da mídia | Substituir `/media/` do nginx por view Django que emite 302 para URL pré-assinada, com checagem de permissão para o prefixo `private/`. | 1–2 dias |
| 3. Migração dos bytes | `aws s3 sync` / `rclone` do volume `media` para o bucket **preservando os caminhos**. | 0,5 dia + tempo de cópia |

**A boa notícia da camada 3:** as chaves gravadas no banco são relativas (`sapl/public/...`,
`sapl/private/...`). Preservando a estrutura de pastas no bucket, **nenhum dado do banco muda**.

**Total realista: 1 a 2 semanas** de desenvolvimento e validação. A janela de corte é curta:
sync incremental, depois sync final e troca da variável de ambiente.

O custo está concentrado em `views_assinatura.py` e `materia/views.py` — os fluxos onde um erro
não aparece em teste automatizado, e sim quando um vereador tenta assinar um projeto.

### Alternativa mais barata

Se o objetivo for apenas tirar disco do servidor, montar o bucket como volume via
**rclone mount**, **s3fs** ou **JuiceFS**: zero mudança de código. O preço é latência e risco
em escrita concorrente — exatamente onde OnlyOffice e assinatura vivem. Serve como paliativo,
não como destino.

### Recomendação

Se o Franco vai para o SGVP em menos de um ano, **não** investir duas semanas em S3 no SAPL.
Fazer o paliativo de montagem, ou simplesmente um volume maior, e concentrar o esforço na
migração. O SGVP já nasce S3-nativo.

---

## 3. Franco: sair do SAPL, entrar no SGVP Legislativo

### O que o SGVP já é

| Dimensão | Situação |
|---|---|
| Backend | Spring Boot 3.5 / Java 25, Gradle 9.5, Flyway, Testcontainers |
| Frontend | Vite + React 18 + TypeScript, ligado à API (localStorage só para token e tema) |
| Tamanho | 572 arquivos Java, ~43 mil linhas, 54 controllers, 42 migrations de tenant, ~95 tabelas |
| Multi-tenancy | Schema por tenant, com provisionamento e console de super-admin |
| Armazenamento | **S3 nativo desde a V7**, com URLs pré-assinadas para upload e download |
| Integrações | OnlyOffice, assinatura digital via microserviço, certificados por usuário |

Cobertura já entregue: proposições, protocolo com numeração sob lock anti-corrida, matérias e
tramitação, autores, vereadores/legislaturas/partidos/bancadas/blocos/frentes, documentos
acessórios, audiências públicas, parametrização regimental, auditoria — e **comissões com
profundidade que o SAPL não tem**: composição, eleição de mesa, rodízio e impedimento de
relatoria, pareceres, reuniões conjuntas, quórum, votação, voto em separado, pedido de vista,
recursos, diligências, atas e decisões impressas no modelo da Casa.

### O que falta para substituir o SAPL

| # | Lacuna | Situação no SGVP | Estimativa |
|---|---|---|---|
| 1 | **Normas Jurídicas** | Ausente por completo. Nenhuma tabela, nenhuma classe. No SAPL são 11 models: `NormaJuridica`, tipos, assuntos, `LegislacaoCitada`, vínculos, anexos, estatísticas. É o acervo da Casa. | 3–5 semanas |
| 2 | **Sessão plenária completa** | Existe cabeçalho + pauta + presenças + iniciar/encerrar. Faltam: Expediente e Ordem do Dia como entidades com resultado, **`RegistroVotacao` + `VotoParlamentar`** (nominal, simbólica, secreta), oradores, mesa da sessão, ocorrências, considerações finais, justificativa de ausência, retirada de pauta, registro de leitura, correspondências, ata gerada. A tela `Votacao.tsx` é maquete — `useState` puro, sem persistência nem endpoint. | 4–6 semanas |
| 3 | **Protocolo administrativo** | O SGVP tem protocolo *legislativo*. Falta o administrativo: `DocumentoAdministrativo`, `TramitacaoAdministrativo`, `Anexado`, `VinculoDocAdminMateria`, acompanhamento. | 2–3 semanas |
| 4 | **Relatórios e estatísticas** | `Relatorios.tsx` usa dados-semente. O SAPL tem dezenas de relatórios PDF em `sapl/relatorios/templates/` (etiqueta, espelho, pauta, ordem do dia, protocolo, resumo de sessão). | 3–4 semanas para o conjunto que o Franco usa |
| 5 | **Painel eletrônico** | Ausente. `painel` + `Cronometro` no SAPL: votação projetada no plenário em tempo real. | 2 semanas (depende do item 2) |
| 6 | **Portal público** | `PortalHome` e `PortalConsulta` usam dados-semente. Falta consulta cidadã real e acompanhamento de matéria por e-mail. | 2 semanas |
| 7 | **LexML / OAI-PMH** | Ausente. `LexmlProvedor` e `LexmlPublicador` — interoperabilidade com a rede Interlegis. | 1–2 semanas |
| 8 | **Busca no conteúdo dos PDFs** | Ausente (no SAPL é o Solr). Postgres FTS resolve razoavelmente bem. | 1 semana |
| 9 | **Textos articulados / Compilação** | Ausente. 7 models no SAPL (`Dispositivo`, `Vide`, `Nota`, `Publicacao`). Consolidação de leis artigo a artigo. | 6+ semanas — **provavelmente escopo a descartar** |
| 10 | **Módulo TCE** | Ausente. Customização deste fork: processos, pastas, arquivos, assinatura, OCR. | 2–3 semanas, **se o Franco usar** |

### A migração de dados em si

Os dois modelos não se falam:

| | SAPL | SGVP |
|---|---|---|
| Chaves | inteiros sequenciais | **UUID** |
| Organização | schema `public`, ~130 tabelas | schema por tenant, ~95 tabelas |
| Tipos | tabelas de domínio Django | enums Postgres (`tipo_sessao`, `parte_pauta`) + tabelas parametrizáveis |
| Arquivos | `media/sapl/{public,private}/...` no disco | `{tenant}/{pasta}/{uuid}-{nome}` no S3 |

Não existe caminho automático. É um **ETL sob medida**: extrair do Postgres do SAPL, mapear,
inserir no schema do tenant, mantendo uma tabela de-para (`id_sapl` → `uuid`) para reconstruir
as relações.

Ordem de dependência obrigatória:

```
parâmetros e tipos → legislaturas e partidos → vereadores → autores e usuários
→ comissões e composições → matérias → autorias → tramitações
→ documentos acessórios → proposições → sessões → arquivos (S3)
```

Riscos que exigem decisão de produto, não só código:

- **Numeração.** O SGVP gera o número da matéria por regra configurável no momento da
  incorporação. Importar histórico exige *bypass* do gerador, preservando os números originais —
  e depois realinhar o contador para não colidir com o próximo número real.
- **Autoria múltipla** — modelagens diferentes dos dois lados.
- **Tramitações órfãs** — unidades de tramitação do SAPL que não têm equivalente no de-para.
- **Assinaturas.** Os PDFs assinados continuam válidos como arquivo, mas o vínculo de
  verificação e o QR Code de autenticidade do SAPL não migram. Precisa de decisão: reemitir,
  manter o SAPL como verificador histórico, ou aceitar a perda.

**Esforço do ETL: 3–5 semanas** para uma casa, mais **1–2 semanas** de conciliação com o
cliente (contagem por tipo e ano, amostragem de documentos abertos um a um).

### Somando

Assumindo que o Franco **não** usa compilação de textos articulados nem o módulo TCE:

```
normas 4 + sessão 5 + protocolo adm. 2,5 + relatórios 3,5
+ painel 2 + portal 2 + lexml 1,5 + busca 1     ≈ 21,5 semanas-dev
+ ETL e validação                                ≈  5,5 semanas
                                                   ─────────────
                                                   ~27 semanas-dev
```

- **Dois desenvolvedores em paralelo: 4 a 5 meses.**
- **Um desenvolvedor: 6 a 7 meses.**
- **Com escopo cortado** (sem painel eletrônico, sem LexML, relatórios só os cinco mais usados):
  **3 meses com dois devs.**

### O próximo passo, antes de dimensionar de verdade

Rodar contagem no banco de produção do Franco. Três consultas derrubam ou confirmam as lacunas
mais caras de uma vez:

```sql
SELECT 'normas',          count(*) FROM norma_normajuridica
UNION ALL SELECT 'doc_administrativos', count(*) FROM protocoloadm_documentoadministrativo
UNION ALL SELECT 'votacoes',            count(*) FROM sessao_registrovotacao
UNION ALL SELECT 'textos_articulados',  count(*) FROM compilacao_textoarticulado
UNION ALL SELECT 'processos_tce',       count(*) FROM tce_tceprocesso
UNION ALL SELECT 'materias',            count(*) FROM materia_materialegislativa
UNION ALL SELECT 'sessoes',             count(*) FROM sessao_sessaoplenaria;
```

Se `compilacao_textoarticulado` e `tce_tceprocesso` vierem zerados, saem 8 semanas da conta.
Se `sessao_registrovotacao` vier zerado, o Franco não usa votação eletrônica e saem mais 6.

### Estratégia recomendada: coexistência, não big-bang

1. O SGVP assume o **fluxo novo** a partir de uma data de corte — proposição, protocolo,
   matéria, comissões, sessão.
2. O SAPL vira **consulta somente-leitura** do acervo histórico, congelado, atrás do mesmo
   domínio (ou pelo `viewer-sapl` que já existe no portfólio).
3. O histórico migra **por ondas**: parâmetros e vereadores primeiro; matérias dos últimos
   N anos em seguida; normas quando o módulo existir.

Isso tira o SAPL do caminho crítico sem esperar paridade de 100% — que, honestamente, nunca
chega, porque sempre sobra um relatório que só uma pessoa usa e só ela sabe que existe.

---

## Resumo executivo

| Pergunta | Resposta | Esforço |
|---|---|---|
| **Dokploy?** | Sim. Sete ajustes, sendo um bloqueante (healthcheck com CIDR não avaliado). Servidor de 4 vCPU / 8 GB. | 1–2 dias |
| **S3 sem impacto?** | Possível, mas não sem impacto: 43 pontos de código acessam o disco diretamente. O banco não muda. Conserta de brinde a exposição dos documentos "privados". | 1–2 semanas |
| **Franco no SGVP?** | Falta bastante: normas, sessão plenária completa, protocolo administrativo, relatórios, painel, portal, LexML. Comissões já estão mais completas que no SAPL. | 4–5 meses com 2 devs, incluindo ETL |

**Ações imediatas, na ordem:**

1. Rotacionar a credencial de `docker/docker-compose.yaml:48`.
2. Corrigir `onlyoffice_download` (download anônimo de proposição).
3. Rodar as contagens no banco do Franco para fechar o escopo real da migração.
