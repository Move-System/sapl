## Resumo das Alterações

- **Home do Vereador**: Novos cards de acesso rápido
- **OnlyOffice**: Correções no salvamento de documentos
- **Listagem de Proposições**: Nova UI minimalista com status visual
- **Detalhes da Proposição**: Layout moderno e intuitivo

---

## 1. Tela Home do Vereador

### Arquivos Alterados
- `sapl/templates/index.html`
- `sapl/base/views.py`

### Mudanças

**Novo card "Matérias Legislativas"**
- Adicionado na seção do vereador (`is_parlamentar`)
- Permite pesquisar projetos de lei e proposições
- Link para `/materia/pesquisar-materia`

**Novo card "Minhas Matérias"**
- Substitui o antigo card "Fluxo de Proposições"
- Filtra automaticamente as matérias pelo autor logado
- Permite ao vereador visualizar e assinar documentos de sua autoria

**Alteração na View**
- `IndexView` agora passa `autor_id` no contexto
- Usado para filtrar matérias por autor na pesquisa

---

## 2. Correções no OnlyOffice

### Arquivos Alterados
- `sapl/materia/onlyoffice_views.py`
- `sapl/templates/materia/onlyoffice_editor.html`
- `sapl/materia/views.py`

### Problema Resolvido
Ao tentar enviar uma proposição, aparecia o erro:
> "Proposição não possui nenhum tipo de Texto associado"

Isso ocorria porque o callback do OnlyOffice não conseguia salvar o documento corretamente.

### Soluções Implementadas

**1. Correção no Callback**
```python
# Antes: só substituía localhost:8001
if 'localhost:8001' in download_url:
    download_url = download_url.replace('localhost:8001', 'onlyoffice:80')

# Depois: substitui qualquer URL externa
download_url = re.sub(r'https?://[^/]+', 'http://onlyoffice:80', download_url)
```

**2. Botão "Salvar e Voltar" no Editor**
- Força o fechamento do editor (triggering callback)
- Aguarda 3 segundos para o callback processar
- Redireciona para a página de detalhes

**3. Mensagem de Erro Melhorada**
- Orienta o usuário a usar o OnlyOffice
- Explica como salvar o documento antes de enviar

**4. Aviso no Template de Detalhes**
- Alerta quando a proposição não tem texto
- Instrui o usuário a criar o documento

---

## 3. Listagem de Proposições (`/proposicao/`)

### Arquivos Alterados
- `sapl/templates/materia/proposicao_list.html`
- `sapl/materia/views.py`

### Nova Interface

**Design Minimalista**
- Layout limpo com max-width de 900px
- Cards com bordas sutis ao invés de sombras pesadas
- Tipografia clara e espaçamento consistente

**Header com Estatísticas**
```
Proposições                    5 total  2 em elaboração  1 enviadas
```

**Cards de Proposição**
Cada card mostra:
- Tipo (ex: Requerimento)
- Status com badge colorido
- Data de envio
- Ementa (truncada em 40 palavras)
- Alerta de devolução (se aplicável)
- Links: Abrir / Editar

**Status com Cores**
| Status | Cor | Descrição |
|--------|-----|-----------|
| Em Elaboração | Cinza | Proposição ainda não enviada |
| Aguardando | Azul | Enviada, aguardando recebimento |
| Incorporada | Verde | Recebida pela Mesa |
| Devolvida | Laranja | Devolvida com justificativa |
| Cancelada | Cinza escuro | Proposição cancelada |

**Paginação**
- 10 itens por página
- Navegação: Anterior / Números / Próxima
- Indicador "Página X de Y"

### Código da View
```python
class ListView(Crud.ListView):
    paginate_by = 10

    def get_context_data(self, **kwargs):
        # Estatísticas
        context['stats'] = {
            'total': qs.count(),
            'elaboracao': qs.filter(data_envio__isnull=True).count(),
            # ...
        }

        # Lista processada com status
        for obj in page_obj.object_list:
            if obj.cancelado:
                status = 'cancelada'
            elif obj.data_devolucao:
                status = 'devolvida'
            # ...

        # Paginação
        context['is_paginated'] = paginator.num_pages > 1
        context['page_obj'] = page_obj
        context['page_range'] = make_pagination(...)
```

---

## 4. Detalhes da Proposição (`/proposicao/{id}`)

### Arquivos Alterados
- `sapl/templates/materia/proposicao_detail.html`

### Nova Interface

**Header**
- Link "Voltar para lista"
- Título: Tipo + Número/Ano ou "Rascunho"
- Badge de status colorido

**Alertas Contextuais**
- **Vermelho**: Proposição devolvida (mostra justificativa)
- **Azul**: Aguardando recebimento
- **Amarelo**: Documento não criado

**Barra de Ações**
Muda conforme o estado da proposição:

*Em Elaboração:*
- Editar Documento (OnlyOffice)
- Enviar Proposição (se tem texto)
- Editar Dados
- Excluir

*Enviada:*
- Ver Recibo
- Retornar Proposição (se não recebida)
- Baixar Documento

**Seções de Conteúdo**

1. **Ementa** - Texto descritivo em destaque

2. **Informações** - Grid com:
   - Tipo
   - Número
   - Data de Envio
   - Data de Recebimento
   - Data de Devolução
   - Status do Documento (Criado/Não criado)

3. **Observação** - Se houver

4. **Vínculos** - Links para:
   - Matéria gerada
   - Matéria anexadora

5. **Info do Sistema** (só admin) - Usuário, IP, Última edição, Hash

**Página de Acesso Negado**
- Ícone de cadeado
- Mensagem clara
- Botão para voltar à lista

---

## Fluxo do Vereador

```
1. Acessar Home
   └── Card "Proposições" → Criar / Listar

2. Criar Proposição
   └── Preencher tipo e ementa
   └── Redirecionado para OnlyOffice

3. Editar Documento (OnlyOffice)
   └── Escrever texto da proposição
   └── Clicar "Salvar e Voltar"

4. Enviar Proposição
   └── Verificar dados
   └── Clicar "Enviar Proposição"
   └── Aguardar recebimento

5. Acompanhar Status
   └── Listagem mostra status atual
   └── Ver detalhes para mais informações
   └── Se devolvida, ver justificativa e corrigir
```

---

## Considerações Técnicas

### Compatibilidade Docker
O OnlyOffice roda em container separado. As URLs são convertidas:
- Browser → OnlyOffice: `localhost:8001`
- SAPL → OnlyOffice: `onlyoffice:80`
- OnlyOffice → SAPL: `sapl-dev:8000`

### Paginação
Usa a função `make_pagination` do CRUD base para gerar o range de páginas com reticências.

### CSS
Estilos inline no template usando o bloco `webpack_loader_chunks_css` para evitar conflitos com o CSS global.

---

## Arquivos Modificados (Resumo)

```
sapl/
├── base/
│   └── views.py                    # IndexView com autor_id
├── materia/
│   ├── views.py                    # ListView e mensagens de erro
│   └── onlyoffice_views.py         # Correção do callback
└── templates/
    ├── index.html                  # Cards do vereador
    └── materia/
        ├── proposicao_list.html    # Nova listagem
        ├── proposicao_detail.html  # Novos detalhes
        └── onlyoffice_editor.html  # Botão salvar e voltar
```

---
