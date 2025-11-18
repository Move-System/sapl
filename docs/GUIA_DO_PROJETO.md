# Legisinc

## Visão Geral

O **Legisinc** é um sistema web completo para gerenciamento de processos legislativos em casas legislativas municipais, estaduais e federais. Desenvolvido pelo Interlegis (Senado Federal), o sistema abrange todo o ciclo de vida legislativo, desde o cadastro de parlamentares até a votação e publicação de normas jurídicas.

**Versão Atual**: 3.1.164-RC5

---

## Arquitetura e Tecnologias

### Backend
- **Framework**: Django 2.2 (Python)
- **Banco de Dados**: PostgreSQL 10.5
- **Busca Textual**: Apache Solr 8.11
- **API REST**: Django REST Framework com DRF Spectacular (OpenAPI)
- **Autenticação**: Token-based + Session Authentication

### Frontend
- **Framework JavaScript**: Vue.js 2.7.9
- **UI Framework**: Bootstrap 4.6.2 com Bootstrap-Vue
- **Editor de Texto**: TinyMCE 7.2
- **Build Tool**: Webpack 5 com Vue CLI 5
- **Utilitários**: jQuery 3.6, Axios, Moment.js, Lodash

### Infraestrutura
- **Containerização**: Docker + Docker Compose
- **Servidor Web**: Nginx + Gunicorn
- **Monitoramento**: Django Prometheus
- **Cache**: File-based Cache

### Estrutura de Containers
```yaml
- sapldb (PostgreSQL)    -> Porta 5433
- saplsolr (Solr)        -> Porta 8983
- sapl (Aplicação)       -> Porta 8000
```

---

## Módulos Principais

O Legisinc está organizado em 9 módulos principais:

### 1. **Base** (`sapl.base`)
- Configurações gerais do sistema
- Gestão de usuários e permissões
- Casa legislativa
- Autores (pessoas e entidades que podem propor matérias)
- Pesquisa textual
- Auditoria

### 2. **Parlamentares** (`sapl.parlamentares`)
- Cadastro de parlamentares
- Legislaturas e sessões legislativas
- Partidos políticos e coligações
- Mandatos e filiações partidárias
- Mesa diretora
- Frentes parlamentares e blocos
- Dependentes

### 3. **Matéria Legislativa** (`sapl.materia`)
- Proposições (antes de serem protocoladas)
- Matérias legislativas (projetos de lei, emendas, requerimentos, etc.)
- Tramitação de matérias
- Autoria e relatoria
- Documentos acessórios
- Acompanhamento de matérias

### 4. **Sessão Plenária** (`sapl.sessao`)
- Sessões ordinárias e extraordinárias
- Composição da mesa
- Presença de parlamentares
- Expediente e ordem do dia
- Oradores e pronunciamentos
- Votações (nominal, simbólica, secreta, em bloco)
- Atas e resumos

### 5. **Norma Jurídica** (`sapl.norma`)
- Normas aprovadas (leis, decretos, resoluções, etc.)
- Vinculação entre normas
- Autoria de normas
- Anexos e documentos relacionados

### 6. **Comissões** (`sapl.comissoes`)
- Comissões permanentes e temporárias
- Composição de comissões
- Reuniões de comissão
- Pauta de reuniões
- Matérias em tramitação nas comissões

### 7. **Protocolo Administrativo** (`sapl.protocoloadm`)
- Documentos administrativos
- Protocolo de documentos
- Tramitação administrativa

### 8. **Audiências Públicas** (`sapl.audiencia`)
- Gestão de audiências públicas
- Anexos e documentação

### 9. **Compilação** (`sapl.compilacao`)
- Textos articulados (compilação de normas)
- Perfis estruturais
- Versionamento de textos normativos

---

## Como Usar o Sistema: Fluxos Principais

### 1. Cadastro de Parlamentares

**Objetivo**: Registrar os parlamentares que compõem a casa legislativa

**Fluxo**:
```
1. Acesse: /parlamentar/create
2. Preencha os dados pessoais (nome, CPF, data de nascimento, etc.)
3. Após salvar, adicione:
   - Filiação partidária: /parlamentar/<id>/filiacao/create
   - Mandato: /parlamentar/<id>/mandato/create
   - Dependentes (opcional): /parlamentar/<id>/dependente/create
4. Visualize: /parlamentar/<id>/
```

**Telas Relacionadas**:
- Listar parlamentares: `/parlamentar/`
- Pesquisar: `/parlamentar/pesquisar-parlamentar/`
- Matérias do parlamentar: `/parlamentar/<id>/materias`

---

### 2. Criação de Matéria Legislativa

**Objetivo**: Protocolar e tramitar projetos de lei e outros documentos legislativos

**Fluxo**:
```
1. Acesse: /materia/create
2. Preencha:
   - Tipo de matéria (Projeto de Lei, Emenda, Requerimento, etc.)
   - Número e ano
   - Data de apresentação
   - Ementa (resumo do conteúdo)
   - Texto integral (arquivo ou texto articulado)
3. Adicione a autoria: /materia/<id>/autoria/create
4. Faça o despacho inicial: /materia/<id>/despachoinicial/create
5. Registre a tramitação: /materia/<id>/tramitacao/create
6. Anexe documentos: /materia/<id>/documentoacessorio/create
7. Visualize: /materia/<id>/
```

**Telas Relacionadas**:
- Listar matérias: `/materia/`
- Pesquisar: `/materia/pesquisar-materia`
- Tramitação em lote: `/materia/tramitacao-em-lote`
- Acompanhar matéria: `/materia/<id>/acompanhar-materia/`

---

### 3. Realização de Sessão Plenária

**Objetivo**: Registrar sessões ordinárias/extraordinárias e realizar votações

**Fluxo**:
```
1. Acesse: /sessao/create
2. Preencha:
   - Tipo de sessão
   - Número
   - Legislatura
   - Data e hora
3. Configure a mesa diretora: /sessao/<id>/mesa
4. Registre a presença: /sessao/<id>/presenca
5. Adicione matérias ao expediente: /sessao/<id>/adicionar-varias-materias-expediente/
6. Adicione matérias à ordem do dia: /sessao/<id>/adicionar-varias-materias-ordem-dia/
7. Registre oradores: /sessao/<id>/orador/create
8. Realize votações:
   - Votação nominal: /sessao/<id>/matordemdia/votnom/<ordem>/<materia>
   - Votação simbólica: /sessao/<id>/matordemdia/votsimb/<ordem>/<materia>
   - Votação secreta: /sessao/<id>/matordemdia/votsec/<ordem>/<materia>
9. Gere o resumo/ata: /sessao/<id>/resumo
10. Visualize: /sessao/<id>/
```

**Telas Relacionadas**:
- Listar sessões: `/sessao/`
- Pauta da sessão: `/sessao/pauta-sessao/<id>/`
- Presença ordem do dia: `/sessao/<id>/presencaordemdia`

---

### 4. Publicação de Norma Jurídica

**Objetivo**: Registrar leis, decretos e resoluções aprovadas

**Fluxo**:
```
1. Acesse: /norma/create
2. Preencha:
   - Tipo de norma (Lei, Decreto, Resolução, etc.)
   - Número e ano
   - Data de publicação
   - Ementa
   - Texto integral (upload de arquivo PDF ou DOC)
3. Adicione autoria: /norma/<id>/autorianorma/create
4. Vincule à matéria que originou (se aplicável)
5. Relacione com outras normas: /norma/<id>/normarelacionada/create
6. Anexe documentos: /norma/<id>/anexonormajuridica/create
7. Visualize: /norma/<id>/
```

**Telas Relacionadas**:
- Listar normas: `/norma/`
- Pesquisar: `/norma/pesquisar`

---

### 5. Gestão de Comissões

**Objetivo**: Gerenciar comissões permanentes e temporárias

**Fluxo**:
```
1. Acesse: /comissao/create
2. Preencha:
   - Nome da comissão
   - Tipo (permanente/temporária)
   - Período de funcionamento
3. Defina a composição: /comissao/<id>/composicao/create
   - Adicione parlamentares e seus cargos (presidente, vice, etc.)
4. Agende reuniões: /comissao/<id>/reuniao/create
5. Monte a pauta: /comissao/<id>/pauta/add
6. Visualize matérias em tramitação: /comissao/<id>/materias-em-tramitacao
7. Visualize: /comissao/<id>/
```

**Telas Relacionadas**:
- Listar comissões: `/comissao/`
- Tipos de comissão: `/sistema/comissao/tipo/`

---

## Configurações Iniciais Necessárias

Antes de começar a usar o sistema para criar dados, é necessário configurar:

### 1. Casa Legislativa
- Acesse: `/sistema/casa-legislativa/`
- Configure: nome, endereço, CNPJ, logomarca, etc.

### 2. Legislatura
- Acesse: `/sistema/parlamentar/legislatura/`
- Crie a legislatura atual (número, data início, data fim, data eleição)

### 3. Sessão Legislativa
- Acesse: `/sistema/parlamentar/sessao-legislativa/`
- Crie sessões legislativas para a legislatura

### 4. Partidos
- Acesse: `/sistema/parlamentar/partido/`
- Cadastre os partidos políticos

### 5. Tipos de Matéria
- Acesse: `/sistema/materia/tipo/`
- Configure os tipos (Projeto de Lei, Emenda, Requerimento, etc.)

### 6. Tipos de Norma
- Acesse: `/sistema/norma/tipo/`
- Configure os tipos (Lei, Decreto, Resolução, etc.)

### 7. Tipos de Sessão
- Acesse: `/sistema/sessao/tipo/`
- Configure os tipos de sessão plenária

### 8. Tipos de Comissão
- Acesse: `/sistema/comissao/tipo/`
- Configure os tipos de comissão

---

## Estrutura de Diretórios

```
sapl/
├── docker/                    # Configurações Docker
│   ├── docker-compose.yaml   # Orquestração de containers
│   └── Dockerfile            # Imagem do Legisinc
├── frontend/                  # Código frontend (Vue.js)
│   ├── src/
│   │   ├── __global/         # Estilos e componentes globais
│   │   ├── apps/             # Aplicações Vue (compilação, painel, etc.)
│   │   └── styles/           # SCSS
│   └── webpack-stats.json    # Build manifest
├── sapl/                      # Código backend (Django)
│   ├── api/                  # API REST
│   ├── base/                 # Módulo base
│   ├── parlamentares/        # Módulo parlamentares
│   ├── materia/              # Módulo matéria legislativa
│   ├── sessao/               # Módulo sessão plenária
│   ├── norma/                # Módulo norma jurídica
│   ├── comissoes/            # Módulo comissões
│   ├── protocoloadm/         # Módulo protocolo administrativo
│   ├── compilacao/           # Módulo compilação
│   ├── audiencia/            # Módulo audiências
│   ├── templates/            # Templates Django
│   ├── static/               # Arquivos estáticos
│   ├── settings.py           # Configurações Django
│   └── urls.py               # Rotas principais
├── README.rst                # Documentação geral
└── package.json              # Dependências frontend
```

---

## Ambiente de Desenvolvimento

### Iniciar o Sistema (Docker)

```bash
cd /home/bruno/sapl/docker
docker-compose up -d
```

Acessar: http://localhost:8000

### Credenciais Padrão
- **Usuário**: admin
- **Senha**: interlegis (configurável via `ADMIN_PASSWORD` no docker-compose.yaml)

### Build do Frontend

```bash
cd /home/bruno/sapl
yarn build
```

---

## API REST

O Legisinc disponibiliza uma API REST completa para integração com outros sistemas.

- **Documentação**: http://localhost:8000/api/docs/
- **Schema OpenAPI**: http://localhost:8000/api/schema/
- **Autenticação**: Token-based (requer `Authorization: Token <token>`)

### Principais Endpoints
- `/api/materia/materialegislativa/` - Matérias legislativas
- `/api/parlamentares/parlamentar/` - Parlamentares
- `/api/sessao/sessaoplenaria/` - Sessões plenárias
- `/api/norma/normajuridica/` - Normas jurídicas
- `/api/comissoes/comissao/` - Comissões

---

## Recursos Especiais

### 1. Busca Textual (Solr)
- Indexação automática de documentos
- Pesquisa full-text em matérias, normas e documentos
- Configurável via variável `USE_SOLR=True`

### 2. Textos Articulados
- Editor de leis estruturadas (artigos, parágrafos, incisos)
- Versionamento de textos
- Comparação de versões (diff)

### 3. Painel Eletrônico
- Exibição em tempo real de votações
- Painel de presença
- URL: `/painel/`

### 4. Acompanhamento de Matérias
- Cidadãos podem acompanhar matérias via email
- Requer configuração de reCaptcha

### 5. Relatórios
- Relatórios de matérias, normas, sessões
- Exportação em PDF
- URL: `/relatorios/`

---

## Tipos de Usuários e Permissões

O Legisinc possui um sistema robusto de controle de acesso com **11 grupos de usuários** diferentes, cada um com permissões específicas para módulos e funcionalidades.

### Grupos de Usuários Principais

#### 1. **Operador Geral** (Superusuário Legisinc)
**Acesso**: Todos os módulos e funcionalidades
- Configurações do sistema
- Gestão de usuários
- Todas as operações de todos os outros grupos
- Tabelas auxiliares
- Auditoria

**Telas Principais**:
- `/sistema/` - Painel administrativo completo
- `/sistema/casa-legislativa/` - Configuração da casa
- `/sistema/usuario/` - Gestão de usuários
- Acesso total a todos os módulos

---

#### 2. **Operador de Matéria**
**Acesso**: Módulo de Matéria Legislativa
- Criar, editar, excluir matérias
- Gerenciar tramitação
- Adicionar autoria e relatoria
- Documentos acessórios
- Impressos

**Telas Principais**:
- `/materia/` - Listar matérias
- `/materia/create` - Criar matéria
- `/materia/<id>/tramitacao/` - Tramitação
- `/materia/<id>/autoria/` - Autoria
- `/materia/tramitacao-em-lote` - Tramitação em lote

---

#### 3. **Operador de Sessão Plenária**
**Acesso**: Módulo de Sessão Plenária
- Criar e gerenciar sessões
- Registrar presença
- Gerenciar expediente e ordem do dia
- Realizar votações
- Gerar atas e resumos

**Telas Principais**:
- `/sessao/` - Listar sessões
- `/sessao/create` - Criar sessão
- `/sessao/<id>/presenca` - Presença
- `/sessao/<id>/matordemdia/` - Ordem do dia
- `/sessao/<id>/votacao` - Votações

---

#### 4. **Operador de Norma Jurídica**
**Acesso**: Módulo de Norma Jurídica + Compilação
- Criar, editar, excluir normas
- Vincular normas relacionadas
- Gerenciar textos articulados
- Compilação de normas
- Dispositivos e vigência

**Telas Principais**:
- `/norma/` - Listar normas
- `/norma/create` - Criar norma
- `/norma/<id>/normarelacionada/` - Normas relacionadas
- `/compilacao/` - Textos articulados

---

#### 5. **Operador de Protocolo Administrativo**
**Acesso**: Protocolo + Documentos Administrativos
- Protocolar documentos
- Anular protocolos
- Visualizar matérias e proposições
- Tramitação administrativa

**Telas Principais**:
- `/protocoloadm/protocolo/` - Gerenciar protocolos
- `/protocoloadm/documentoadministrativo/` - Documentos
- `/proposicao/recebida/` - Proposições recebidas

---

#### 6. **Operador de Comissões**
**Acesso**: Módulo de Comissões
- Criar e gerenciar comissões
- Definir composição
- Agendar reuniões
- Gerenciar pautas
- Matérias em tramitação

**Telas Principais**:
- `/comissao/` - Listar comissões
- `/comissao/create` - Criar comissão
- `/comissao/<id>/composicao/` - Composição
- `/comissao/<id>/reuniao/` - Reuniões

---

#### 7. **Operador Administrativo**
**Acesso**: Documentos Administrativos
- Gerenciar documentos administrativos
- Anexar documentos
- Tramitação administrativa
- Vinculação com matérias

**Telas Principais**:
- `/protocoloadm/documentoadministrativo/` - Documentos
- `/protocoloadm/documentoadministrativo/<id>/tramitacao/` - Tramitação

---

#### 8. **Operador de Audiência**
**Acesso**: Módulo de Audiências Públicas
- Criar e gerenciar audiências
- Anexar documentos
- Tipos de audiência

**Telas Principais**:
- `/audiencia/` - Listar audiências
- `/audiencia/create` - Criar audiência
- `/audiencia/<id>/anexo/` - Anexos

---

#### 9. **Operador de Painel**
**Acesso**: Painel Eletrônico
- Controlar painel de votações
- Gerenciar cronômetro
- Exibição de dados em tempo real

**Telas Principais**:
- `/painel/` - Painel eletrônico
- `/painel/cronometro/` - Cronômetro

---

#### 10. **Autor** (Parlamentares e Proponentes)
**Acesso**: Apenas suas próprias proposições
- Criar proposições
- Editar proposições próprias
- Visualizar histórico
- Textos articulados próprios

**Telas Principais**:
- `/proposicao/` - Suas proposições
- `/proposicao/create` - Criar proposição
- `/proposicao/<id>/` - Editar (apenas próprias)

**Restrição**: Só pode ver/editar proposições que ele mesmo criou

---

#### 11. **Votante** (Parlamentares em Sessão)
**Acesso**: Votação em sessões
- Votar em matérias
- Registrar voto (nominal, simbólico, secreto)

**Permissão Especial**: `can_vote`

---

### Usuários Padrão Criados no Sistema

O sistema cria automaticamente usuários de teste com senha padrão `interlegis`:

| Usuário | Grupo | Senha |
|---------|-------|-------|
| `admin` | Superusuário Django | `interlegis` |
| `operador_geral` | Operador Geral | `interlegis` |
| `operador_materia` | Operador de Matéria | `interlegis` |
| `operador_sessao` | Operador de Sessão | `interlegis` |
| `operador_norma` | Operador de Norma | `interlegis` |
| `operador_protocoloadm` | Operador de Protocolo | `interlegis` |
| `operador_comissoes` | Operador de Comissões | `interlegis` |
| `operador_administrativo` | Operador Administrativo | `interlegis` |
| `operador_painel` | Operador de Painel | `interlegis` |

---

### Permissões por Tipo de Operação

O Legisinc usa 5 radicais de permissão para cada entidade:

- **`.list_`** - Listar registros (visualizar lista)
- **`.detail_`** - Ver detalhes de um registro específico
- **`.add_`** - Adicionar novos registros
- **`.change_`** - Editar registros existentes
- **`.delete_`** - Excluir registros

---

### Acesso à API REST

#### Endpoints Públicos (sem autenticação)
Qualquer pessoa pode consultar via API:
- Parlamentares (`/api/parlamentares/parlamentar/`)
- Comissões (`/api/comissoes/comissao/`)
- Sessões (`/api/sessao/sessaoplenaria/`)
- Matérias (`/api/materia/materialegislativa/`)
- Normas (`/api/norma/normajuridica/`)

**Operações permitidas**: `GET` (list e detail apenas)

#### Endpoints Privados (requer autenticação)
Requer token de autenticação:
- Documentos Administrativos
- Protocolos
- Proposições
- Operações de modificação (`POST`, `PUT`, `PATCH`, `DELETE`)

**Autenticação**: `Authorization: Token <token>`

---

### Acesso de Usuários Anônimos (Não Logados)

Usuários não autenticados podem:
- Consultar dados públicos via API
- Acompanhar matérias (adicionar/remover acompanhamento via email)
- Acompanhar documentos

**Restrições**:
- Não podem criar/editar/excluir
- Requer configuração de reCaptcha para acompanhamento

---

### Matriz de Permissões por Módulo

| Módulo | Operador Geral | Op. Matéria | Op. Sessão | Op. Norma | Op. Protocolo | Op. Comissões | Op. Admin | Op. Audiência | Op. Painel | Autor |
|--------|:--------------:|:-----------:|:----------:|:---------:|:-------------:|:-------------:|:---------:|:-------------:|:----------:|:-----:|
| **Matéria Legislativa** | ✅ | ✅ | - | - | 👁️ | - | - | - | - | - |
| **Sessão Plenária** | ✅ | - | ✅ | - | - | - | - | - | - | - |
| **Norma Jurídica** | ✅ | - | - | ✅ | - | - | - | - | - | - |
| **Protocolo** | ✅ | - | - | - | ✅ | - | - | - | - | - |
| **Comissões** | ✅ | - | - | - | - | ✅ | - | - | - | - |
| **Doc. Administrativo** | ✅ | - | - | - | 👁️ | - | ✅ | - | - | - |
| **Audiência Pública** | ✅ | - | - | - | - | - | - | ✅ | - | - |
| **Painel Eletrônico** | ✅ | - | - | - | - | - | - | - | ✅ | - |
| **Proposições** | ✅ | - | - | - | 👁️ | - | - | - | - | ✅ |
| **Compilação** | ✅ | - | - | ✅ | - | - | - | - | - | - |
| **Configurações** | ✅ | - | - | - | - | - | - | - | - | - |

**Legenda**:
- ✅ = Acesso completo (criar, editar, excluir, visualizar)
- 👁️ = Apenas visualização
- \- = Sem acesso

---

### Recomendações de Uso

Para usar o sistema eficientemente, recomendamos atribuir usuários aos grupos conforme suas funções:

1. **Administrador da Casa**: `Operador Geral`
2. **Secretaria Legislativa**: `Operador de Matéria` + `Operador de Sessão`
3. **Assessoria Jurídica**: `Operador de Norma`
4. **Setor de Protocolo**: `Operador de Protocolo Administrativo`
5. **Secretaria de Comissões**: `Operador de Comissões`
6. **Parlamentares**: `Autor` + `Votante`
7. **Operador de TI/Suporte**: `Operador Geral`
8. **Público Externo**: Sem login (acesso via API pública)

---

## Observações Importantes

1. **Ordem de Cadastro**: Para criar dados no sistema, siga esta ordem:
   - Configurações do sistema (casa legislativa, legislatura)
   - Partidos e tipos (matéria, norma, sessão)
   - Parlamentares
   - Matérias legislativas
   - Sessões plenárias
   - Normas jurídicas

2. **Permissões**: O sistema possui controle granular de permissões. Configure grupos de usuários em `/sistema/grupo/`

3. **Backup**: Recomenda-se backup regular do banco PostgreSQL:
   ```bash
   docker exec postgres pg_dump -U sapl sapl > backup.sql
   ```

4. **Logs**: Arquivos de log em `sapl.log` na raiz do projeto

---

## Suporte e Documentação

- **Discord**: https://discord.gg/fzXSbhZbcy
- **Issues**: https://github.com/interlegis/sapl/issues
- **Wiki**: https://colab.interlegis.leg.br/wiki/ProjetoSapl
- **Perguntas Frequentes**: https://github.com/interlegis/sapl/wiki/Perguntas-Frequentes

---

*Documento gerado em: 2025-10-02*
