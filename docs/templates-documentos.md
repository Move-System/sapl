# Templates de Documentos - SAPL

## Visão Geral

O sistema de Templates de Documentos permite que administradores configurem modelos padrão com cabeçalho, rodapé e formatação pré-definidos. Quando um usuário cria um novo documento via OnlyOffice (proposição, matéria legislativa, norma, etc.), o sistema automaticamente aplica o template correspondente.

## Arquitetura

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Admin SAPL     │────▶│  CRUD Templates  │────▶│ OnlyOffice      │
│                 │     │                  │     │ (Edita .docx)   │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                                                          ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Usuário Comum  │────▶│  Criar Documento │────▶│ Aplica Template │
│                 │     │  (Matéria, etc)  │     │ (cabeç/rodapé)  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

## Como Acessar

### Menu Principal
1. Acesse o SAPL como administrador
2. Vá em **Sistema** → **Tabelas Auxiliares**
3. Na seção **Configurações Gerais**, clique em **Templates de Documentos**

### URL Direta
```
/sistema/template-documento/
```

## Criando um Template

### Passo 1: Acessar a Criação
1. Acesse `/sistema/template-documento/`
2. Clique em **Adicionar Template de Documento**

### Passo 2: Preencher o Formulário

| Campo | Descrição | Obrigatório | Exemplo |
|-------|-----------|-------------|---------|
| **Nome** | Nome identificador do template | Sim | "Template Oficial Câmara" |
| **Tipo de Conteúdo** | Tipo de documento que usará este template | Sim | Matéria Legislativa |
| **Tipo Específico** | Vincular a um tipo específico | Não | TipoMateriaLegislativa |
| **ID do Tipo** | ID do tipo específico | Não | 1 (Projeto de Lei) |
| **Descrição** | Descrição do template | Não | "Template com brasão e rodapé padrão" |
| **Arquivo** | Arquivo .docx inicial | **Não** | template.docx |
| **Ativo** | Se o template está disponível para uso | Sim | ✓ |
| **Padrão** | Se é o template padrão para este tipo | Não | ✓ |

> **Nota:** O campo **Arquivo** é opcional. Se não enviar um arquivo, o sistema criará automaticamente um documento em branco com cabeçalho e rodapé de exemplo.

### Passo 3: Editar no OnlyOffice
Após salvar, você será **automaticamente redirecionado** para o editor OnlyOffice onde poderá:
- Configurar o **cabeçalho** (logo, nome da casa legislativa)
- Configurar o **rodapé** (numeração de página, data)
- Definir **estilos** de fonte e formatação padrão
- Adicionar **elementos fixos** que aparecerão em todos os documentos

### Passo 4: Salvar
O OnlyOffice salva automaticamente. Quando terminar, clique em **Voltar** para retornar ao SAPL.

### Editando um Template Existente
Na tela de **Detalhes** do template, você encontrará dois botões:
- **Editar no OnlyOffice** - Abre o editor para modificar cabeçalho, rodapé e formatação
- **Editar Dados** - Modifica os campos do formulário (nome, tipo, etc.)

Na tela de **Edição de Dados**, há um alerta no topo com link direto para o OnlyOffice.

## Tipos de Conteúdo Suportados

| Tipo | Descrição | Usado em |
|------|-----------|----------|
| `proposicao` | Proposições | Módulo Matéria → Proposições |
| `materia` | Matérias Legislativas | Módulo Matéria → Matérias |
| `docacessorio` | Documentos Acessórios | Anexos de Matérias |
| `docadm` | Documentos Administrativos | Módulo Protocolo Administrativo |
| `norma` | Normas Jurídicas | Módulo Normas |

## Hierarquia de Templates

O sistema busca templates na seguinte ordem de prioridade:

1. **Template Específico**: Vinculado ao tipo exato (ex: "Projeto de Lei")
2. **Template Genérico**: Apenas com tipo de conteúdo (ex: "Matéria Legislativa")
3. **Documento em Branco**: Se nenhum template for encontrado

### Exemplo Prático

Se você criar:
- Template A: Matéria Legislativa (genérico)
- Template B: Matéria Legislativa → Projeto de Lei (específico)

Ao criar um **Projeto de Lei**, o sistema usará o **Template B**.
Ao criar um **Requerimento**, o sistema usará o **Template A**.

## Configurando Templates Específicos

Para vincular um template a um tipo específico:

### 1. Identificar o Tipo
Primeiro, descubra o ID do tipo desejado. Por exemplo, para TipoMateriaLegislativa:
- Acesse `/materia/tipo-materia-legislativa/`
- Anote o ID do tipo (visível na URL ao editar)

### 2. Configurar no Template
No formulário de criação/edição do template:
- **Tipo Específico**: Selecione o ContentType correspondente
  - `materia | tipomaterialegislativa` para tipos de matéria
  - `materia | tipoproposicao` para tipos de proposição
  - `protocoloadm | tipodocumentoadministrativo` para tipos de doc. administrativo
  - `norma | tiponormajuridica` para tipos de norma
- **ID do Tipo Específico**: Digite o ID anotado

## Estrutura Técnica

### Arquivos Criados

| Arquivo | Descrição |
|---------|-----------|
| `sapl/base/models.py` | Modelo `DocumentTemplate` |
| `sapl/base/forms.py` | Formulário `DocumentTemplateForm` |
| `sapl/base/views.py` | CRUD `DocumentTemplateCrud` |
| `sapl/base/urls.py` | URLs do CRUD e OnlyOffice |
| `sapl/base/onlyoffice_template_views.py` | Views OnlyOffice para templates |
| `sapl/utils_template.py` | Funções utilitárias |
| `sapl/base/migrations/0061_documenttemplate.py` | Migration do banco |
| `sapl/templates/base/layouts.yaml` | Layout do formulário |
| `sapl/templates/menu_tabelas_auxiliares.yaml` | Link no menu |
| `sapl/templates/base/documenttemplate_detail.html` | Template da tela de detalhes |
| `sapl/templates/base/documenttemplate_form.html` | Template da tela de edição |

### URLs Disponíveis

| URL | Descrição |
|-----|-----------|
| `/sistema/template-documento/` | Lista de templates |
| `/sistema/template-documento/create` | Criar template |
| `/sistema/template-documento/{pk}` | Detalhes do template |
| `/sistema/template-documento/{pk}/edit` | Editar template |
| `/sistema/template-documento/{pk}/delete` | Excluir template |
| `/sistema/template-documento/{pk}/onlyoffice/editor` | Editor OnlyOffice |

### Modelo de Dados

```python
class DocumentTemplate(models.Model):
    nome = CharField(max_length=100)
    descricao = TextField(blank=True)
    tipo_conteudo = CharField(choices=TIPO_CONTEUDO_TEMPLATE)

    # GenericFK para tipo específico (opcional)
    content_type = ForeignKey(ContentType, null=True, blank=True)
    object_id = PositiveIntegerField(null=True, blank=True)
    tipo_especifico = GenericForeignKey()

    arquivo = FileField(upload_to='templates/')
    ativo = BooleanField(default=True)
    padrao = BooleanField(default=False)
    data_criacao = DateTimeField(auto_now_add=True)
    data_modificacao = DateTimeField(auto_now=True)
```

## Boas Práticas

### 1. Nomenclatura
Use nomes descritivos que identifiquem claramente o propósito:
- ✅ "Template Oficial - Projetos de Lei"
- ✅ "Modelo Padrão Câmara - Requerimentos"
- ❌ "Template 1"

### 2. Organização
- Crie um template **genérico** para cada tipo de conteúdo
- Crie templates **específicos** apenas quando necessário
- Mantenha apenas **um template padrão** por tipo

### 3. Cabeçalho e Rodapé
No OnlyOffice, configure:
- **Cabeçalho**: Brasão, nome da casa legislativa, endereço
- **Rodapé**: Número da página, data, informações de contato

### 4. Manutenção
- Revise os templates periodicamente
- Desative templates obsoletos em vez de excluí-los
- Mantenha backup dos arquivos .docx

## Solução de Problemas

### Template não está sendo aplicado
1. Verifique se o template está **Ativo**
2. Verifique se o **Tipo de Conteúdo** está correto
3. Se é específico, verifique se o **ID do Tipo** está correto

### Cabeçalho/rodapé não aparecem
1. Edite o template no OnlyOffice
2. Verifique se o cabeçalho/rodapé foram salvos corretamente
3. O OnlyOffice salva automaticamente, mas aguarde alguns segundos

### Erro ao criar template
1. Verifique se o arquivo é um **.docx** válido
2. Verifique se você tem permissão de administrador
3. Consulte os logs do sistema para mais detalhes

## Permissões Necessárias

Para gerenciar templates, o usuário precisa das permissões:
- `base.add_documenttemplate` - Criar templates
- `base.change_documenttemplate` - Editar templates
- `base.delete_documenttemplate` - Excluir templates
- `base.view_documenttemplate` - Visualizar templates

Essas permissões são automaticamente concedidas ao grupo **Operador Geral** e administradores.
