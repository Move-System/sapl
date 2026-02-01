# Fluxo de Proposição do Vereador no SAPL

Este documento descreve o processo completo de criação, envio e tramitação de uma proposição por um Vereador no Sistema de Apoio ao Processo Legislativo (SAPL).

## Visão Geral

O fluxo de proposição envolve três atores principais:

| Ator | Papel |
|------|-------|
| **Vereador/Autor** | Cria e envia a proposição |
| **Protocolo/Mesa** | Recebe, valida e incorpora a proposição |
| **Sistema** | Gerencia estados, gera hash e registra histórico |

## Diagrama de Estados

```
┌─────────────────┐
│   ELABORAÇÃO    │ ← Vereador cria/edita proposição
└────────┬────────┘
         │ clica "Enviar"
         ▼
┌─────────────────┐
│    ENVIADA      │ ← Aguardando Protocolo
└────────┬────────┘
         │ Protocolo digita código hash
         ▼
┌─────────────────┐
│  CONFIRMAÇÃO    │ ← Protocolo revisa
└────────┬────────┘
         │
    ┌────┴───────┐
    ▼            ▼
┌────────┐  ┌──────────┐
│DEVOLVER│  │INCORPORAR│
└───┬────┘  └────┬─────┘
    │            │
    ▼            ▼
┌──────────┐  ┌───────────────────┐
│ELABORAÇÃO│  │MATÉRIA LEGISLATIVA│
│(corrigir)│  │   ou DOCUMENTO    │
└──────────┘  └───────────────────┘
```

## Etapas Detalhadas

### 1. Criação da Proposição (Vereador)

**Acesso:** `/proposicao/create`

O Vereador cria uma nova proposição preenchendo:

| Campo | Descrição |
|-------|-----------|
| Tipo | Tipo de proposição (Projeto de Lei, Moção, Requerimento, etc.) |
| Descrição/Ementa | Texto descritivo da proposição |
| Texto | Pode ser: arquivo digital (upload), Texto Articulado ou OnlyOffice |

**Opções de criação de texto:**

- **Arquivo Digital (D):** Upload de arquivo DOCX/DOC/PDF
- **Texto Articulado (T):** Editor estruturado de normas (XML/LexML)
- **OnlyOffice (O):** Editor online de documentos

### 2. Envio da Proposição (Vereador)

**Acesso:** `/proposicao/<id>` → botão "Enviar"

**Código fonte:** `sapl/materia/views.py:912-970`

#### O que acontece ao clicar "Enviar":

1. **Validações:**
   - Proposição não pode ter sido enviada anteriormente
   - Deve possuir pelo menos um tipo de texto associado

2. **Processamento:**
   - Se houver Texto Articulado, ele é **bloqueado para edição**
   - Data de envio é registrada (`data_envio = timestamp atual`)
   - Hash MD5 é gerado para verificação de integridade

3. **Registro:**
   - Histórico é criado com status `E` (Enviada)
   - IP e usuário são registrados

4. **Resposta:**
   - Mensagem de sucesso com número provável da futura matéria
   - Recibo disponibilizado com código de barras/QR

#### Código do hash gerado:

```
Formato: P<hash_md5>/<proposicao_id>
Exemplo: P8f14e45fceea167a5a36dedd4bea2543/26
```

### 3. Geração do Recibo

**Acesso:** `/proposicao/recibo/<id>`

**Código fonte:** `sapl/materia/views.py:1224-1279`

O sistema gera um recibo contendo:

- Código de barras com o hash
- QR Code para leitura rápida
- Informações da proposição (tipo, autor, data)

> **Importante:** Este recibo é usado pelo Protocolo para recuperar a proposição. Não constitui assinatura digital.

### 4. Recebimento pelo Protocolo

**Acesso:** `/proposicao/receber/`

**Código fonte:** `sapl/materia/views.py:617-667`

**Permissão necessária:** `materia.detail_proposicao_enviada`

#### Processo:

1. Operador do Protocolo acessa a área de recebimento
2. Digita ou escaneia o código hash do recibo
3. Sistema valida:
   - Proposição existe e está enviada
   - Hash confere (documento não foi alterado)
4. Redireciona para tela de confirmação

### 5. Confirmação/Incorporação (Protocolo)

**Acesso:** `/proposicao/confirmar/<hash>/<id>`

**Código fonte:** `sapl/materia/views.py:701-800`

O Protocolo visualiza os dados da proposição e tem duas opções:

#### Opção A: Incorporar

Campos do formulário:

| Campo | Obrigatório | Descrição |
|-------|-------------|-----------|
| Número de Matéria | Não | Número sugerido ou automático |
| Regime de Tramitação | Sim* | Como a matéria tramitará |
| Matéria de Vínculo | Condicional | Obrigatório para documentos |
| Gerar Protocolo | Configurável | Se deve criar protocolo administrativo |
| Número de Páginas | Não | Para o protocolo |

*Obrigatório apenas para Matérias Legislativas

**Resultado da incorporação:**

1. Proposição marcada como recebida (`data_recebimento = timestamp`)
2. Criação de **MateriaLegislativa** ou **DocumentoAcessorio**
3. Registro de **Autoria** vinculando o autor
4. Opcionalmente, criação de **Protocolo** administrativo
5. Histórico atualizado com status `R` (Recebida)

#### Opção B: Devolver

**Código fonte:** `sapl/materia/forms.py:2244-2330`

Campos:

| Campo | Obrigatório | Descrição |
|-------|-------------|-----------|
| Justificativa | Sim | Motivo da devolução |
| Observação | Não | Informações adicionais |

**Resultado da devolução:**

1. Proposição marcada como devolvida (`data_devolucao = timestamp`)
2. Datas de envio e recebimento são limpas
3. Texto Articulado é **desbloqueado para edição**
4. Histórico atualizado com status `D` (Devolvida)
5. Vereador pode corrigir e reenviar

### 6. Retorno pelo Autor (Opcional)

**Acesso:** `/proposicao/<id>` → botão "Retornar"

**Código fonte:** `sapl/materia/views.py:971-998`

Se a proposição foi enviada mas **ainda não foi recebida** pelo Protocolo, o Vereador pode retorná-la:

- Data de envio é limpa
- Texto Articulado é desbloqueado
- Histórico registra status `T` (Retornada)

## Modelo de Dados

### Proposição (`sapl/materia/models.py:754-1050`)

```python
class Proposicao(models.Model):
    autor                   # Quem propôs
    tipo                    # Tipo de proposição
    descricao               # Ementa/descrição
    texto_original          # Arquivo digital (se houver)
    texto_articulado        # Texto estruturado (se houver)

    # Controle de fluxo
    data_envio              # Quando foi enviada
    data_recebimento        # Quando foi recebida/incorporada
    data_devolucao          # Quando foi devolvida

    # Usuários envolvidos
    usuario_envio           # Quem enviou
    usuario_recebimento     # Quem recebeu
    usuario_devolucao       # Quem devolveu

    # Resultado
    conteudo_gerado_related # Matéria ou Documento criado
    materia_de_vinculo      # Matéria relacionada

    # Segurança
    hash_code               # MD5 para verificação
    cancelado               # Se foi cancelada
```

### Histórico (`sapl/materia/models.py`)

```python
class HistoricoProposicao(models.Model):
    proposicao    # Referência à proposição
    status        # E=Enviada, R=Recebida, T=Retornada, D=Devolvida
    data_hora     # Timestamp da ação
    user          # Usuário que executou
    ip            # IP do usuário
    observacao    # Justificativa (em devoluções)
```

## Permissões

| Permissão | Descrição |
|-----------|-----------|
| `detail_proposicao_enviada` | Acessar proposições enviadas (Protocolo) |
| `detail_proposicao_devolvida` | Acessar proposições devolvidas |
| `detail_proposicao_incorporada` | Acessar proposições incorporadas |

## Sobre Assinatura Digital

> **Importante:** O SAPL atualmente **não possui integração com assinatura digital** (PKI/ICP-Brasil).

O que existe para segurança:

| Mecanismo | Função |
|-----------|--------|
| Hash MD5 | Verificar integridade do documento |
| Registro de IP | Rastreabilidade de ações |
| Registro de Usuário | Identificação do responsável |
| Histórico completo | Auditoria de mudanças de estado |
| Bloqueio de edição | Impedir alterações após envio |

O hash gerado serve para verificar que o documento não foi alterado entre o envio e o recebimento, mas **não constitui assinatura eletrônica** no sentido jurídico.

## Arquivos do Código-Fonte

| Arquivo | Responsabilidade |
|---------|------------------|
| `sapl/materia/models.py` | Modelos Proposicao, HistoricoProposicao, TipoProposicao |
| `sapl/materia/views.py` | Views de envio, recebimento, confirmação |
| `sapl/materia/forms.py` | Formulários de proposição |
| `sapl/materia/onlyoffice_views.py` | Integração com editor OnlyOffice |
| `sapl/materia/urls.py` | Rotas e URLs |
| `sapl/templates/materia/proposicao_*.html` | Templates de apresentação |

## Resumo do Fluxo

1. **Vereador cria** proposição com texto (upload, Texto Articulado ou OnlyOffice)
2. **Vereador envia** → Sistema gera hash e bloqueia edição
3. **Sistema gera recibo** com código de barras
4. **Protocolo recebe** digitando/escaneando o código hash
5. **Protocolo valida** integridade (hash confere?)
6. **Protocolo decide:**
   - **Incorporar** → Cria Matéria Legislativa ou Documento
   - **Devolver** → Volta para Vereador corrigir
7. **Se incorporado** → Matéria entra em tramitação normal
