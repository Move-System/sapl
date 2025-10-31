# Fluxo de Proposições no SAPL

## Visão Geral

O fluxo de proposições permite que **parlamentares** criem propostas legislativas (proposições) e as enviem para o **protocolo legislativo**. Após análise, o protocolo pode **incorporar** a proposição (transformando-a em matéria legislativa) ou **devolver** para correção.

---

## 1. Conceitos Fundamentais

### 1.1 O que é uma Proposição?

Uma **Proposição** é uma proposta inicial feita por um autor (geralmente um parlamentar) que **ainda não foi oficialmente incorporada** ao processo legislativo. É um estágio preliminar antes de se tornar uma **Matéria Legislativa**.

**Características:**
- Criada pelo parlamentar/autor
- Pode ser editada enquanto não for enviada
- Não tramita (ainda não é oficial)
- Não pode ser votada
- Possui número sequencial próprio

### 1.2 O que é uma Matéria Legislativa?

Uma **Matéria Legislativa** é a proposição que foi **oficialmente recebida e incorporada** ao processo legislativo da casa. Após a incorporação, a matéria pode tramitar, ser votada e seguir todo o fluxo legislativo.

**Características:**
- Criada pelo operador de protocolo ao incorporar proposição
- Possui número oficial (PL nº 1/2025, por exemplo)
- Tramita entre unidades
- Pode ser incluída em sessões e votada
- Possui protocolo (se configurado)

### 1.3 Diferença entre Proposição e Matéria Legislativa

| Característica | Proposição | Matéria Legislativa |
|----------------|------------|---------------------|
| **Status** | Proposta preliminar | Oficialmente incorporada |
| **Tramitação** | Não tramita | Tramita entre unidades |
| **Votação** | Não pode ser votada | Pode ser votada |
| **Criador** | Autor (Parlamentar) | Operador de Protocolo |
| **Edição** | Pode ser editada pelo autor | Editada por operadores autorizados |
| **Numeração** | Sequencial de proposições | Numeração oficial legislativa |

---

## 2. Atores do Sistema

### 2.1 Parlamentar
- Membro eleito da casa legislativa
- Possui cadastro completo (dados pessoais, foto, biografia, mandatos)
- Ao ser cadastrado, **automaticamente** um **Autor** é criado para ele

### 2.2 Autor
- Abstração que representa quem pode criar proposições
- Pode ser:
  - Um Parlamentar
  - Um Órgão
  - Uma Comissão
  - Cidadão (dependendo da configuração)
- Quando um Parlamentar é criado, um Autor é criado automaticamente

### 2.3 Usuário do Sistema
- Login para acessar o sistema
- Pode estar vinculado a um ou mais Autores (através de **OperadorAutor**)
- Quando vinculado a um Autor, entra automaticamente no grupo "Autor"

### 2.4 Operador de Autor (OperadorAutor)
- Vínculo entre um **usuário** e um **autor**
- Permite que um usuário opere em nome de um autor
- Um usuário pode ser operador de múltiplos autores
- Um autor pode ter múltiplos operadores

### 2.5 Grupo "Autor"
- Grupo de permissões do Django
- Usuários deste grupo podem:
  - Criar proposições
  - Editar suas próprias proposições
  - Enviar proposições
  - Retornar proposições enviadas (cancelar envio)
  - Ver proposições devolvidas

### 2.6 Operador de Protocolo/Matéria
- Responsável por receber e processar proposições
- Pode:
  - Receber proposições (via código ou lista)
  - Incorporar proposições (transformar em matéria)
  - Devolver proposições (com justificativa)
  - Gerar protocolos
- Grupos: **Operador de Protocolo Administrativo** ou **Operador Geral**

---

## 3. Estados de uma Proposição

### 3.1 Rascunho (Não Enviada)
- **Datas**: `data_envio = NULL`, `data_recebimento = NULL`, `data_devolucao = NULL`
- **Quem vê**: Apenas o autor/operador que criou
- **Ações possíveis**: Editar, Excluir, Enviar

### 3.2 Pendente (Enviada, aguardando recebimento)
- **Datas**: `data_envio != NULL`, `data_recebimento = NULL`, `data_devolucao = NULL`
- **Quem vê**: Autor e Operadores de Protocolo
- **URL**: `/proposicao/pendente/`
- **Ações possíveis**:
  - **Autor**: Retornar (cancelar envio)
  - **Operador**: Receber ou Devolver

### 3.3 Devolvida
- **Datas**: `data_envio = NULL`, `data_recebimento = NULL`, `data_devolucao != NULL`
- **Justificativa**: Preenchida pelo operador
- **Quem vê**: Autor
- **URL**: `/proposicao/devolvida/`
- **Ações possíveis**: Autor pode corrigir e reenviar

### 3.4 Incorporada (Recebida)
- **Datas**: `data_envio != NULL`, `data_recebimento != NULL`, `data_devolucao = NULL`
- **Vinculação**: Vinculada a uma Matéria Legislativa ou Documento Acessório
- **Quem vê**: Todos com permissão
- **URL**: `/proposicao/recebida/`
- **Resultado**: Matéria Legislativa criada

---

## 4. Fluxo Completo Passo a Passo

### ETAPA 1: Criar Parlamentar com Usuário

#### 1.1 Criar o Parlamentar
1. **URL**: `/parlamentar/create`
2. **Quem pode**: Administradores ou Operadores com permissão
3. **Dados principais**:
   - Nome Completo
   - Nome Parlamentar
   - CPF, RG
   - Sexo
   - Data de nascimento
   - Foto (opcional)
   - Biografia (opcional)
4. **Resultado**:
   - Parlamentar criado
   - **Autor criado automaticamente** vinculado ao parlamentar

#### 1.2 Criar Usuário no Sistema
1. **URL**: `/sistema/usuario/create`
2. **Dados**:
   - Username (login): `joao.silva`
   - Email: `joao.silva@camara.gov.br`
   - Senha: Senha forte
   - Nome completo: João da Silva
3. **Resultado**: Usuário criado, mas ainda sem permissões

#### 1.3 Vincular Usuário ao Autor
1. **URL**: `/sistema/usuario/{id}/edit`
2. No campo **"Autor"**, selecione o autor do parlamentar
3. Clique em **"Salvar"**
4. **Resultado**:
   - Usuário adicionado ao grupo "Autor"
   - Registro **OperadorAutor** criado vinculando usuário → autor
   - Usuário agora pode criar proposições em nome do parlamentar

---

### ETAPA 2: Parlamentar Cria e Envia Proposição

#### 2.1 Login como Parlamentar
- Acesse: `http://seu-sapl.com/login/`
- Username: `joao.silva`
- Senha: (senha definida)

#### 2.2 Criar Nova Proposição
1. **URL**: `/proposicao/create`
2. **Formulário**:

   **Campos principais**:
   - **Tipo de Proposição**: Projeto de Lei, Emenda, Requerimento, Moção, etc.
   - **Ementa/Descrição**: Descrição resumida da proposição
   - **Matéria de Vinculação** (opcional): Se for documento acessório de matéria existente

   **Opções de texto**:
   - **Texto Original**: Upload de arquivo (PDF, DOC, ODT)
   - **OU Texto Articulado**: Usar editor interno do sistema (artigos, parágrafos, incisos)

3. **Ações**:
   - **Salvar**: Proposição fica como rascunho
   - **Salvar e Adicionar Outro**: Salva e abre formulário novo

4. **Resultado**:
   - Proposição criada com número sequencial
   - Status: **Rascunho** (pode editar)
   - URL de detalhes: `/proposicao/{id}/`

#### 2.3 Editar Proposição (enquanto rascunho)
1. **URL**: `/proposicao/{id}/edit`
2. Altere qualquer campo
3. Salve novamente
4. **Importante**: Só pode editar enquanto não enviada

#### 2.4 Enviar Proposição
1. Acesse: `/proposicao/{id}/`
2. Revise todos os dados
3. Clique em **"Enviar Proposição"** (ou `?action=send`)
4. **Confirme** o envio

5. **O que acontece**:
   - `data_envio` = timestamp atual
   - `usuario_envio` = usuário logado
   - Texto articulado é travado (se houver)
   - **Código de recebimento** é gerado (hash)
   - Número provável de matéria é estimado
   - Status muda para: **Pendente**

6. **Recibo**:
   - URL: `/proposicao/recibo/{id}`
   - Contém código hash para recebimento
   - Pode ser impresso
   - Entregar ao protocolo

#### 2.5 Retornar Proposição (cancelar envio)
- **Quando**: Antes de ser recebida pelo protocolo
- **Como**: Acessar `/proposicao/{id}/?action=return`
- **Resultado**:
  - `data_envio` = NULL
  - Proposição volta ao estado de rascunho
  - Pode ser editada novamente

#### 2.6 Ver Minhas Proposições
- **URL**: `/proposicao/`
- Lista todas proposições do autor logado
- Filtra por status: Rascunho, Pendente, Devolvida, Incorporada

---

### ETAPA 3: Operador Recebe e Incorpora Proposição

#### 3.1 Login como Operador de Protocolo
- Grupos: **Operador de Protocolo Administrativo** ou **Operador Geral**

#### 3.2 Ver Proposições Pendentes
1. **URL**: `/proposicao/pendente/`
2. **Visualização**: Lista de proposições enviadas aguardando recebimento
3. **Informações mostradas**:
   - Data de envio
   - Autor
   - Tipo de proposição
   - Ementa/Descrição
   - Link para receber

#### 3.3 Receber Proposição

**Opção A: Via Código Hash do Recibo**
1. **URL**: `/proposicao/receber/`
2. **Inserir**: Código hash do recibo
3. **Validação**: Sistema valida se:
   - Proposição existe
   - Está em estado "enviada"
   - Hash confere
4. **Redirecionamento**: `/proposicao/confirmar/P{hash}/{id}`

**Opção B: Via Lista de Pendentes**
1. Acesse: `/proposicao/pendente/`
2. Clique na proposição desejada
3. Clique em **"Receber Proposição"**
4. Redirecionamento para tela de confirmação

#### 3.4 Tela de Confirmação/Incorporação

**URL**: `/proposicao/confirmar/P{hash}/{id}`

**Apresenta duas opções:**

---

##### OPÇÃO A: INCORPORAR

**Formulário de Incorporação**:

1. **Dados da Proposição** (somente leitura):
   - Tipo de proposição
   - Data de envio
   - Autor
   - Ementa
   - Texto/Arquivo

2. **Configurações de Incorporação**:

   **Se for Matéria Legislativa** (Projeto de Lei, Emenda, etc.):
   - **Regime de Tramitação**: Obrigatório
     - Urgente
     - Normal
     - Prioridade
   - **Gerar Protocolo?**: Sim/Não (se configuração permitir escolha)
   - **Número de Páginas**: Se gerar protocolo
   - **Observação do Protocolo**: Texto livre

   **Se for Documento Acessório**:
   - Vinculação a matéria existente
   - Tipo de documento

3. **Matéria de Vinculação** (opcional):
   - Se a proposição deve ser anexada a matéria existente
   - Pesquisa por tipo, número e ano
   - Sistema mostra ementa para confirmar

4. **Ao clicar em "Incorporar"**:

   **Sistema cria**:
   - **MateriaLegislativa** com:
     - Tipo (baseado no tipo da proposição)
     - Número sequencial
     - Ano atual
     - Ementa da proposição
     - Regime de tramitação selecionado
     - Texto original copiado

   - **Autoria** automática:
     - Autor da proposição → Autor da matéria
     - Marcado como primeiro autor

   - **Protocolo** (se configurado):
     - Número sequencial
     - Data de recebimento
     - Tipo: Matéria Legislativa
     - Número de páginas

   **Atualiza Proposição**:
   - `data_recebimento` = timestamp atual
   - `usuario_recebimento` = operador logado
   - Vincula à matéria criada
   - Status: **Incorporada**

   **Histórico**:
   - Registro em **HistoricoProposicao** com status 'R' (Recebida)

5. **Resultado**:
   - Mensagem de sucesso
   - Link para a matéria criada
   - Matéria pode ser acessada em `/materia/{id}/`

---

##### OPÇÃO B: DEVOLVER

**Formulário de Devolução**:

1. **Campo obrigatório**:
   - **Justificativa de Devolução**: Texto explicando motivo
     - Exemplos:
       - "Falta fundamentação legal"
       - "Documento em formato incorreto"
       - "Proposição duplicada"
       - "Necessita correção de redação"

2. **Ao clicar em "Devolver"**:

   **Atualiza Proposição**:
   - `data_devolucao` = timestamp atual
   - `usuario_devolucao` = operador logado
   - `justificativa_devolucao` = texto informado
   - `data_envio` = NULL
   - `data_recebimento` = NULL
   - Status: **Devolvida**

   **Histórico**:
   - Registro em **HistoricoProposicao** com status 'D' (Devolvida)

3. **Resultado**:
   - Proposição volta para o autor
   - Autor pode visualizar em `/proposicao/devolvida/`
   - Autor pode corrigir e reenviar

---

### ETAPA 4: Matéria Tramita e Vai para Votação

#### 4.1 Matéria Incorporada
- **URL de listagem**: `/materia/` ou `/materia/pesquisar-materia`
- **URL de detalhes**: `/materia/{id}/`
- **Informações**:
  - Tipo, Número, Ano
  - Ementa
  - Autores (incluindo autor da proposição original)
  - Regime de tramitação
  - Status atual
  - Protocolo (se gerado)
  - Texto original
  - Link para proposição original

#### 4.2 Despacho Inicial
1. **URL**: `/materia/{id}/despachoinicial/create`
2. **Dados**:
   - Comissão que receberá
   - Prazo de análise
3. **Resultado**: Matéria despachada para comissão

#### 4.3 Primeira Tramitação
1. **URL**: `/materia/{id}/tramitacao/create`
2. **Dados**:
   - Unidade de origem (Protocolo)
   - Unidade de destino (ex: Comissão de Justiça)
   - Data de tramitação
   - Status de tramitação (ex: "Em análise")
   - Urgente? Sim/Não
   - Turno (1º, 2º, Único)
   - Texto da ação
3. **Resultado**: Matéria tramitada para unidade

#### 4.4 Tramitação em Lote
- **URL**: `/materia/tramitacao-em-lote`
- Permite tramitar múltiplas matérias simultaneamente
- Útil para despachar várias matérias para mesma comissão

#### 4.5 Análise em Comissão
1. Comissão analisa matéria
2. Designa relator: `/materia/{id}/relatoria/create`
3. Relator elabora parecer
4. Comissão vota parecer

#### 4.6 Inclusão em Sessão Plenária
1. **URL**: `/sessao/{id}/adicionar-varias-materias-ordem-dia/`
2. Seleciona matérias para ordem do dia
3. Define ordem de votação
4. **Resultado**: Matéria incluída na pauta da sessão

#### 4.7 Votação
1. Durante sessão plenária: `/sessao/{id}/`
2. Acessa ordem do dia: `/sessao/{id}/matordemdia/`
3. **Tipos de votação**:
   - **Simbólica**: `/sessao/{id}/matordemdia/votsimb/{ordem}/{materia}`
   - **Nominal**: `/sessao/{id}/matordemdia/votnom/{ordem}/{materia}`
   - **Secreta**: `/sessao/{id}/matordemdia/votsec/{ordem}/{materia}`

4. **Resultados possíveis**:
   - Aprovada
   - Rejeitada
   - Aprovada com emendas
   - Retirada de pauta
   - Adiada

#### 4.8 Criação de Norma Jurídica
- Se matéria aprovada e sancionada
- **URL**: `/norma/create`
- Vincula à matéria legislativa original
- Gera Lei, Decreto, Resolução, etc.

---

## 5. URLs e Telas Importantes

### 5.1 URLs de Proposição (Para Autores/Parlamentares)

| Ação | URL | Descrição |
|------|-----|-----------|
| Listar minhas proposições | `/proposicao/` | Lista todas proposições do autor logado |
| Criar proposição | `/proposicao/create` | Formulário de nova proposição |
| Ver detalhes | `/proposicao/{id}/` | Detalhes e ações disponíveis |
| Editar proposição | `/proposicao/{id}/edit` | Editar proposição não enviada |
| Excluir proposição | `/proposicao/{id}/delete` | Excluir proposição não enviada |
| Enviar proposição | `/proposicao/{id}/?action=send` | Enviar para protocolo |
| Retornar proposição | `/proposicao/{id}/?action=return` | Cancelar envio |
| Recibo | `/proposicao/recibo/{id}` | Imprimir recibo com código |
| Devolvidas | `/proposicao/devolvida/` | Proposições devolvidas pelo protocolo |

### 5.2 URLs de Proposição (Para Operadores de Protocolo)

| Ação | URL | Descrição |
|------|-----|-----------|
| Receber proposição | `/proposicao/receber/` | Inserir código do recibo |
| Confirmar/Incorporar | `/proposicao/confirmar/P{hash}/{id}` | Tela de incorporação ou devolução |
| Pendentes | `/proposicao/pendente/` | Proposições aguardando recebimento |
| Recebidas/Incorporadas | `/proposicao/recebida/` | Proposições já incorporadas |

### 5.3 URLs de Matéria Legislativa

| Ação | URL | Descrição |
|------|-----|-----------|
| Listar matérias | `/materia/` | Lista todas matérias |
| Pesquisar matéria | `/materia/pesquisar-materia` | Pesquisa avançada |
| Ver detalhes | `/materia/{id}/` | Detalhes completos da matéria |
| Editar matéria | `/materia/{id}/edit` | Editar dados da matéria |
| Adicionar tramitação | `/materia/{id}/tramitacao/create` | Nova tramitação |
| Tramitação em lote | `/materia/tramitacao-em-lote` | Tramitar várias matérias |
| Despacho inicial | `/materia/{id}/despachoinicial/create` | Despachar para comissão |
| Adicionar autoria | `/materia/{id}/autoria/create` | Adicionar mais autores |
| Documento acessório | `/materia/{id}/documentoacessorio/create` | Anexar documento |
| Relatoria | `/materia/{id}/relatoria/create` | Designar relator |

### 5.4 URLs de Configuração

| Ação | URL | Descrição |
|------|-----|-----------|
| Tipos de Proposição | `/sistema/materia/tipoproposicao/` | Configurar tipos de proposição |
| Tipos de Matéria | `/sistema/materia/tipo/` | Configurar tipos de matéria |
| Regime de Tramitação | `/sistema/materia/regimetramitacao/` | Configurar regimes |
| Tipos de Autor | `/sistema/base/tipoautor/` | Configurar tipos de autor |
| Autores | `/sistema/base/autor/` | Gerenciar autores |
| Parlamentares | `/parlamentar/` | Gerenciar parlamentares |
| Usuários | `/sistema/usuario/` | Gerenciar usuários do sistema |
| Vincular Operador | `/sistema/base/autor/{id}/operadorautor/` | Vincular usuário a autor |
| Configurações App | `/sistema/app-config/1/edit` | Configurações gerais do sistema |

---

## 6. Configurações do Sistema (AppConfig)

### 6.1 Configurações de Proposição

Acessadas em: `/sistema/app-config/1/edit`

#### **Sequência de Numeração de Proposição**
- **'A'**: Sequencial por ano para cada autor
  - Autor 1: Proposição 1/2025, 2/2025, 3/2025...
  - Autor 2: Proposição 1/2025, 2/2025, 3/2025...
- **'B'**: Sequencial por ano independente do autor
  - Todos autores: Proposição 1/2025, 2/2025, 3/2025...

#### **Receber Recibo de Proposição**
- **True**: Protocolo DEVE usar código do recibo para receber
- **False**: Protocolo pode receber direto da lista de pendentes

#### **Proposição - Incorporação Obrigatória**
- **'O'**: Sempre gerar protocolo ao incorporar
- **'C'**: Perguntar se quer gerar protocolo (Operador escolhe)
- **'N'**: Nunca gerar protocolo ao incorporar

#### **Escolher Número da Matéria**
- **True**: Autor pode sugerir número da matéria
- **False**: Número atribuído automaticamente pelo sistema

---

## 7. Permissões e Grupos

### 7.1 Grupo "Autor"

**Permissões**:
- `materia.list_proposicao`: Listar proposições
- `materia.detail_proposicao`: Ver detalhes de proposição
- `materia.add_proposicao`: Criar proposição
- `materia.change_proposicao`: Editar proposição
- `materia.delete_proposicao`: Excluir proposição
- `materia.list_historicoproposicao`: Ver histórico
- `materia.detail_historicoproposicao`: Ver detalhes do histórico

**Restrições**:
- Só pode ver/editar suas próprias proposições
- Não pode ver proposições de outros autores
- Não pode incorporar proposições

### 7.2 Grupo "Operador de Protocolo Administrativo"

**Permissões**:
- `materia.detail_proposicao_enviada`: Ver proposições pendentes
- `materia.detail_proposicao_devolvida`: Ver proposições devolvidas
- `materia.detail_proposicao_incorporada`: Ver proposições incorporadas
- `protocoloadm.add_protocolo`: Criar protocolos
- `protocoloadm.change_protocolo`: Editar protocolos
- `materia.add_materialegislativa`: Criar matérias (ao incorporar)

**Ações permitidas**:
- Receber proposições
- Incorporar proposições (criar matérias)
- Devolver proposições
- Gerar protocolos

### 7.3 Grupo "Operador de Matéria"

**Permissões**:
- CRUD completo em matérias legislativas
- Tramitação de matérias
- Documentos acessórios
- Relatorias
- Despachos

---

## 8. Exemplos Práticos

### 8.1 Criar Parlamentar com Usuário

**Passo 1: Criar Parlamentar**
1. Acesse: `http://seu-sapl.com/parlamentar/create`
2. Preencha:
   - Nome Completo: "João da Silva"
   - Nome Parlamentar: "João Silva"
   - Sexo: Masculino
   - CPF: 123.456.789-00
   - Data Nascimento: 01/01/1980
3. Salve
4. **Resultado**: Parlamentar criado + Autor criado automaticamente

**Passo 2: Verificar Autor**
1. Acesse: `http://seu-sapl.com/sistema/base/autor/`
2. Localize: "João da Silva" (tipo: Parlamentar)
3. Anote o ID (ex: 25)

**Passo 3: Criar Usuário**
1. Acesse: `http://seu-sapl.com/sistema/usuario/create`
2. Preencha:
   - Username: `joao.silva`
   - Email: `joao.silva@camara.gov.br`
   - Nome: "João da Silva"
   - Senha: `Senha@Forte123`
3. Salve

**Passo 4: Vincular Usuário ao Autor**
1. Acesse: `http://seu-sapl.com/sistema/usuario/{id_usuario}/edit`
2. No campo **"Autor"**, selecione: "João da Silva"
3. Salve
4. **Resultado**:
   - Usuário no grupo "Autor"
   - OperadorAutor criado
   - Pode criar proposições

---

### 8.2 Criar e Enviar Proposição

**Passo 1: Login**
1. Login: `joao.silva` / `Senha@Forte123`

**Passo 2: Criar Proposição**
1. Acesse: `http://seu-sapl.com/proposicao/create`
2. Preencha:
   - **Tipo**: Projeto de Lei
   - **Ementa**: "Dispõe sobre horário de funcionamento do comércio aos domingos"
   - **Texto Original**: Upload arquivo `projeto_lei_comercio.pdf`
3. Clique em **"Salvar"**

**Passo 3: Revisar**
1. Sistema redireciona para `/proposicao/{id}/`
2. Revise todos os dados
3. Se necessário, clique em **"Editar"** e corrija

**Passo 4: Enviar**
1. Clique em **"Enviar Proposição"**
2. Confirme
3. **Código gerado**: `P9a8b7c6d5e4f3g2h1i0_separador_123`

**Passo 5: Imprimir Recibo**
1. Acesse: `http://seu-sapl.com/proposicao/recibo/{id}`
2. Imprima ou salve PDF
3. Entregue ao protocolo

---

### 8.3 Receber e Incorporar (Operador)

**Passo 1: Login como Operador**
- Login: `operador_protocoloadm` / `interlegis`

**Passo 2: Ver Pendentes**
1. Acesse: `http://seu-sapl.com/proposicao/pendente/`
2. Veja lista de proposições enviadas

**Passo 3: Receber via Código**
1. Acesse: `http://seu-sapl.com/proposicao/receber/`
2. Cole código: `P9a8b7c6d5e4f3g2h1i0_separador_123`
3. Clique em **"Receber"**

**Passo 4: Incorporar**
1. Na tela de confirmação:
   - **Regime de Tramitação**: Normal
   - **Gerar Protocolo**: Sim
   - **Número de Páginas**: 3
   - **Observação**: "Proposição recebida via protocolo digital"
2. Clique em **"Incorporar"**

**Passo 5: Resultado**
- **Matéria criada**: PL nº 1/2025
- **Protocolo gerado**: Protocolo nº 150/2025
- **Autoria**: João da Silva (primeiro autor)
- **Status**: Incorporada
- **Link**: `http://seu-sapl.com/materia/{id}/`

**Passo 6: Acessar Matéria**
1. Clique no link da matéria
2. Veja todos dados
3. Pode iniciar tramitação

---

### 8.4 Devolver Proposição

**Passo 1: Receber Proposição**
1. Login como operador
2. Acesse: `http://seu-sapl.com/proposicao/receber/`
3. Insira código ou selecione da lista

**Passo 2: Devolver**
1. Na tela de confirmação
2. Clique em **"Devolver"**
3. **Justificativa**: "Documento apresentado em formato incorreto. Favor enviar em PDF/A conforme Resolução 123/2024"
4. Clique em **"Devolver"**

**Passo 3: Resultado**
- Proposição volta para autor
- Status: **Devolvida**
- Autor vê em `/proposicao/devolvida/`

**Passo 4: Autor Corrige**
1. Login como autor
2. Acesse: `http://seu-sapl.com/proposicao/devolvida/`
3. Vê proposição e justificativa
4. Clica em **"Editar"**
5. Corrige formato do arquivo
6. Salva
7. **Envia novamente**

---

## 9. Troubleshooting (Problemas Comuns)

### 9.1 "Usuário não consegue criar proposições"

**Causa**: Usuário não está vinculado a um Autor

**Solução**:
1. Verifique se usuário está no grupo "Autor": `/sistema/usuario/{id}/edit`
2. Verifique se existe OperadorAutor: `/sistema/base/autor/{id_autor}/operadorautor/`
3. Se não existe, crie o vínculo

### 9.2 "Proposição não aparece para receber"

**Causa**: Proposição não foi enviada

**Solução**:
1. Autor deve acessar `/proposicao/{id}/`
2. Clicar em "Enviar Proposição"
3. Verificar se `data_envio` está preenchida

### 9.3 "Erro ao incorporar proposição"

**Causas possíveis**:
- Regime de tramitação não selecionado (obrigatório)
- Tipo de proposição não vinculado a tipo de matéria

**Solução**:
1. Acesse: `/sistema/materia/tipoproposicao/`
2. Edite o tipo de proposição
3. Verifique campo **"Tipo Correspondente"**
4. Deve apontar para um tipo de matéria (ex: Projeto de Lei)

### 9.4 "Parlamentar criado mas não aparece como autor"

**Causa**: Falha na criação automática do autor

**Solução**:
1. Acesse: `/sistema/base/autor/create`
2. Crie manualmente:
   - **Tipo**: Parlamentar
   - **Parlamentar**: Selecione o parlamentar
   - **Nome**: Nome do parlamentar
3. Salve

### 9.5 "Não consigo retornar proposição enviada"

**Causa**: Proposição já foi recebida pelo protocolo

**Solução**:
- Após recebimento, proposição não pode ser retornada
- Se necessário correção, operador deve **devolver** com justificativa
- Autor corrige e reenvia

### 9.6 "Código de recebimento inválido"

**Causa**: Código digitado incorretamente ou proposição já recebida

**Solução**:
1. Verifique se código foi copiado corretamente (copiar do recibo)
2. Verifique se proposição já está em `/proposicao/recebida/`
3. Se problema persistir, use lista de pendentes

---

## 10. Diagrama de Fluxo

```
┌─────────────────────────────────────────────────────────────────┐
│                    FLUXO DE PROPOSIÇÕES                         │
└─────────────────────────────────────────────────────────────────┘

┌──────────────┐
│ PARLAMENTAR  │
└──────┬───────┘
       │
       │ 1. Cria Proposição
       │    /proposicao/create
       ▼
┌──────────────┐
│ PROPOSIÇÃO   │
│ (Rascunho)   │
└──────┬───────┘
       │
       │ 2. Envia Proposição
       │    ?action=send
       ▼
┌──────────────┐
│ PROPOSIÇÃO   │◄──────────┐
│ (Pendente)   │           │ 5. Retorna (cancela)
└──────┬───────┘           │    ?action=return
       │                   │
       │ 3. Recebe         │
       │    /proposicao/receber/
       ▼                   │
┌──────────────┐           │
│  OPERADOR    │───────────┘
│  PROTOCOLO   │
└──────┬───────┘
       │
       │ 4. Decide
       │
   ┌───┴───┐
   │       │
   │       │
   ▼       ▼
┌──────┐ ┌──────┐
│INCOR-│ │DEVOL-│
│PORAR │ │VER   │
└───┬──┘ └───┬──┘
    │        │
    │        │ 6. Justifica
    │        │    Volta para autor
    │        ▼
    │   ┌──────────────┐
    │   │ PROPOSIÇÃO   │
    │   │ (Devolvida)  │
    │   └──────────────┘
    │        │
    │        │ 7. Corrige e reenvia
    │        │
    │ 8. Cria Matéria
    │    Cria Autoria
    │    Gera Protocolo
    ▼
┌──────────────┐
│   MATÉRIA    │
│ LEGISLATIVA  │
└──────┬───────┘
       │
       │ 9. Tramita
       ▼
┌──────────────┐
│  COMISSÕES   │
│  PARECERES   │
└──────┬───────┘
       │
       │ 10. Inclui em Sessão
       ▼
┌──────────────┐
│   SESSÃO     │
│  PLENÁRIA    │
└──────┬───────┘
       │
       │ 11. Vota
       ▼
┌──────────────┐
│   RESULTADO  │
│ (Aprovada/   │
│  Rejeitada)  │
└──────────────┘
```

---

## 11. Checklist de Configuração Inicial

Antes de usar o fluxo de proposições, configure:

- [ ] **Casa Legislativa**: `/sistema/casa-legislativa/`
- [ ] **Legislatura**: `/sistema/parlamentar/legislatura/`
- [ ] **Partidos**: `/sistema/parlamentar/partido/`
- [ ] **Tipos de Proposição**: `/sistema/materia/tipoproposicao/`
  - [ ] Vincular cada tipo a um "Tipo Correspondente" (tipo de matéria)
- [ ] **Tipos de Matéria**: `/sistema/materia/tipo/`
- [ ] **Regimes de Tramitação**: `/sistema/materia/regimetramitacao/`
- [ ] **Tipos de Autor**: `/sistema/base/tipoautor/`
- [ ] **Unidades de Tramitação**: `/sistema/materia/unidadetramitacao/`
- [ ] **Configurações App**: `/sistema/app-config/1/edit`
  - [ ] Sequência numeração proposição
  - [ ] Receber recibo obrigatório?
  - [ ] Gerar protocolo obrigatório?
- [ ] **Parlamentares**: `/parlamentar/create`
- [ ] **Usuários**: `/sistema/usuario/create`
- [ ] **Vincular Usuários a Autores**: `/sistema/usuario/{id}/edit`

---

## 12. Resumo Executivo

### Para o Parlamentar/Autor:
1. ✍️ **Crie** sua proposição com ementa e texto
2. 📝 **Revise** quantas vezes precisar (enquanto não enviar)
3. 📤 **Envie** quando estiver pronta
4. 🎫 **Guarde** o código de recebimento
5. ⏳ **Aguarde** o protocolo processar
6. 🔄 Se **devolvida**, corrija e reenvie

### Para o Operador de Protocolo:
1. 📥 **Receba** proposições via código ou lista
2. 🔍 **Analise** se está correta
3. ✅ **Incorpore** gerando matéria OU
4. ❌ **Devolva** com justificativa
5. ⚙️ **Configure** regime, protocolo, etc.

### Para o Operador de Matéria:
1. 📋 **Tramite** matérias entre unidades
2. 👥 **Despache** para comissões
3. 📅 **Inclua** em sessões plenárias
4. 🗳️ **Registre** votações
5. 📜 **Gere** normas jurídicas (se aprovadas)

---

**Documento criado em**: 2025-10-02
**Versão SAPL**: 3.1.164-RC5
