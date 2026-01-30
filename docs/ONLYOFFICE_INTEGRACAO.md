## Configuração do Docker

### docker-compose-dev.yml

O OnlyOffice é executado como um container Docker separado. Adicione ao arquivo `docker/docker-compose-dev.yml`:

```yaml
version: '3.7'

services:
  sapl-dev:
    container_name: sapl-dev
    image: sapl:dev
    build:
      context: ../
      dockerfile: ./docker/Dockerfile.dev
    command: python3 manage.py runserver 0:8000
    volumes:
      - ..:/sapl-dev
    ports:
      - "8000:8000"
    environment:
      SECRET_KEY: '$dkhxm-$zvxdox$g2-&w^1i!_z1juq0xwox6e3#gy6w_88!3t^'
      DEBUG: 'True'
      DATABASE_URL: postgresql://sapl:sapl@host.docker.internal:5432/sapl
      TZ: America/Sao_Paulo
      ONLYOFFICE_URL: 'http://onlyoffice:80'
    depends_on:
      - onlyoffice

  onlyoffice:
    container_name: onlyoffice-documentserver
    image: onlyoffice/documentserver:latest
    ports:
      - "8001:80"
    environment:
      - JWT_ENABLED=false
      - JWT_SECRET=your-secret-key-change-this
    volumes:
      - onlyoffice_data:/var/www/onlyoffice/Data
      - onlyoffice_log:/var/log/onlyoffice
      - onlyoffice_fonts:/usr/share/fonts/truetype/custom
    restart: unless-stopped

volumes:
  onlyoffice_data:
  onlyoffice_log:
  onlyoffice_fonts:
```

### Portas Utilizadas

| Serviço | Porta Interna | Porta Externa | Descrição |
|---------|---------------|---------------|-----------|
| SAPL | 8000 | 8000 | Aplicação Django |
| OnlyOffice | 80 | 8001 | Document Server |

### Comunicação entre Containers

- **Navegador → OnlyOffice**: `http://localhost:8001` (porta externa)
- **OnlyOffice → SAPL**: `http://sapl-dev:8000` (nome do container na rede Docker)
- **SAPL → OnlyOffice**: `http://onlyoffice:80` (nome do container na rede Docker)

---

## Configuração do Django

### settings.py

Adicione as seguintes configurações ao `sapl/settings.py`:

```python
# OnlyOffice Document Server Configuration
ONLYOFFICE_URL = config('ONLYOFFICE_URL', default='http://localhost:8001')
ONLYOFFICE_JWT_SECRET = config('ONLYOFFICE_JWT_SECRET', default='')
ONLYOFFICE_JWT_ENABLED = config('ONLYOFFICE_JWT_ENABLED', cast=bool, default=False)
```

### Variáveis de Ambiente

| Variável | Descrição | Valor Padrão |
|----------|-----------|--------------|
| `ONLYOFFICE_URL` | URL do OnlyOffice Document Server | `http://localhost:8001` |
| `ONLYOFFICE_JWT_SECRET` | Chave secreta para autenticação JWT | (vazio) |
| `ONLYOFFICE_JWT_ENABLED` | Habilitar autenticação JWT | `False` |

---

## Tipos de Documentos Suportados

A integração OnlyOffice está disponível para os seguintes tipos de documentos:

| Tipo de Documento | Modelo Django | Campo de Arquivo | App |
|-------------------|---------------|------------------|-----|
| Proposição | `Proposicao` | `texto_original` | materia |
| Matéria Legislativa | `MateriaLegislativa` | `texto_original` | materia |
| Documento Acessório | `DocumentoAcessorio` | `arquivo` | materia |
| Documento Administrativo | `DocumentoAdministrativo` | `texto_integral` | protocoloadm |
| Norma Jurídica | `NormaJuridica` | `texto_integral` | norma |

---

## Arquitetura da Implementação

### Estrutura de Views

Cada módulo possui 4 endpoints para integração com OnlyOffice:

1. **editor**: Renderiza a página com o editor OnlyOffice
2. **config**: Retorna configuração JSON para inicializar o editor
3. **download**: Permite que o OnlyOffice baixe o documento
4. **callback**: Recebe notificações de salvamento do OnlyOffice

### URLs Implementadas

#### Proposição (já existia)
```
/proposicao/<pk>/onlyoffice/editor
/proposicao/<pk>/onlyoffice/config
/proposicao/<pk>/onlyoffice/download
/proposicao/<pk>/onlyoffice/callback
```

#### Matéria Legislativa
```
/materia/<pk>/onlyoffice/editor
/materia/<pk>/onlyoffice/config
/materia/<pk>/onlyoffice/download
/materia/<pk>/onlyoffice/callback
```

#### Documento Acessório
```
/materia/documentoacessorio/<pk>/onlyoffice/editor
/materia/documentoacessorio/<pk>/onlyoffice/config
/materia/documentoacessorio/<pk>/onlyoffice/download
/materia/documentoacessorio/<pk>/onlyoffice/callback
```

#### Documento Administrativo
```
/docadm/<pk>/onlyoffice/editor
/docadm/<pk>/onlyoffice/config
/docadm/<pk>/onlyoffice/download
/docadm/<pk>/onlyoffice/callback
```

#### Norma Jurídica
```
/norma/<pk>/onlyoffice/editor
/norma/<pk>/onlyoffice/config
/norma/<pk>/onlyoffice/download
/norma/<pk>/onlyoffice/callback
```

---

## Arquivos Criados/Modificados

### Arquivos Criados

#### Views OnlyOffice

| Arquivo | Descrição |
|---------|-----------|
| `sapl/protocoloadm/onlyoffice_views.py` | Views para Documento Administrativo |
| `sapl/norma/onlyoffice_views.py` | Views para Norma Jurídica |
| `sapl/materia/onlyoffice_materia_views.py` | Views para Matéria Legislativa e Documento Acessório |

#### Templates

| Arquivo | Descrição |
|---------|-----------|
| `sapl/templates/onlyoffice/onlyoffice_editor.html` | Template genérico do editor |
| `sapl/templates/materia/documentoacessorio_detail.html` | Detail com botão OnlyOffice |

### Arquivos Modificados

#### URLs

| Arquivo | Modificação |
|---------|-------------|
| `sapl/protocoloadm/urls.py` | Adicionados 4 endpoints OnlyOffice |
| `sapl/norma/urls.py` | Adicionados 4 endpoints OnlyOffice |
| `sapl/materia/urls.py` | Adicionados 8 endpoints OnlyOffice (matéria + doc acessório) |

#### Templates (botão OnlyOffice)

| Arquivo | Modificação |
|---------|-------------|
| `sapl/templates/protocoloadm/documentoadministrativo_detail.html` | Botão "Editar com OnlyOffice" |
| `sapl/templates/norma/normajuridica_detail.html` | Botão "Editar com OnlyOffice" |
| `sapl/templates/materia/materialegislativa_detail.html` | Botão "Editar com OnlyOffice" |

#### Formulário de Proposição

| Arquivo | Modificação |
|---------|-------------|
| `sapl/materia/forms.py` | Opção "Criar com OnlyOffice" sempre visível |
| `sapl/materia/views.py` | Redirecionamento para OnlyOffice após salvar |
| `sapl/templates/materia/proposicao_form.html` | Layout melhorado |

---

## Fluxo de Funcionamento

### 1. Abertura do Editor

```
Usuário clica em "Editar com OnlyOffice"
    ↓
GET /documento/<pk>/onlyoffice/editor
    ↓
Renderiza template com iframe do OnlyOffice
    ↓
JavaScript busca configuração via AJAX
    ↓
GET /documento/<pk>/onlyoffice/config
    ↓
Retorna JSON com URLs e configurações
    ↓
OnlyOffice inicializa e busca documento
    ↓
GET /documento/<pk>/onlyoffice/download
    ↓
Retorna arquivo .docx (ou documento em branco)
```

### 2. Salvamento do Documento

```
Usuário edita documento no OnlyOffice
    ↓
OnlyOffice faz autosave/forcesave
    ↓
POST /documento/<pk>/onlyoffice/callback
    ↓
Body: { "status": 2, "url": "http://..." }
    ↓
SAPL baixa documento da URL fornecida
    ↓
Salva no campo de arquivo do modelo
    ↓
Retorna { "error": 0 }
```

### 3. Status do Callback

| Status | Significado | Ação |
|--------|-------------|------|
| 1 | Documento sendo editado | Nenhuma |
| 2 | Documento pronto para salvar | Baixar e salvar |
| 4 | Documento fechado sem alterações | Nenhuma |
| 6 | Documento salvo (forcesave) | Baixar e salvar |

---

## Problemas Conhecidos e Soluções

### 1. OnlyOffice não consegue baixar o documento

**Sintoma**: Editor carrega mas mostra erro ao abrir documento.

**Causa**: OnlyOffice não consegue acessar a URL de download do SAPL.

**Solução**: As URLs precisam ser convertidas para usar o nome do container Docker:

```python
# No código das views:
host = request.get_host()
download_url = download_url.replace(f'http://{host}', 'http://sapl-dev:8000')
download_url = download_url.replace(f'https://{host}', 'http://sapl-dev:8000')
```

### 2. Callback não salva o documento

**Sintoma**: Edições são perdidas ao fechar o editor.

**Causa**: SAPL não consegue baixar o documento da URL fornecida pelo OnlyOffice.

**Solução**: Converter a URL do callback para acessar via rede Docker:

```python
# Na função de callback:
if 'localhost:8001' in download_url:
    download_url = download_url.replace('localhost:8001', 'onlyoffice:80')
```

### 3. Erro de JWT

**Sintoma**: OnlyOffice rejeita requisições com erro de token.

**Causa**: JWT está habilitado no OnlyOffice mas não configurado no SAPL.

**Solução**:
- Opção 1: Desabilitar JWT no OnlyOffice (`JWT_ENABLED=false`)
- Opção 2: Configurar mesmo segredo em ambos:
  ```yaml
  # docker-compose.yml
  environment:
    - JWT_ENABLED=true
    - JWT_SECRET=sua-chave-secreta
  ```
  ```python
  # settings.py ou .env
  ONLYOFFICE_JWT_ENABLED=True
  ONLYOFFICE_JWT_SECRET=sua-chave-secreta
  ```

### 4. Opção OnlyOffice não aparece no formulário de Proposição

**Sintoma**: Ao criar proposição, não aparece a opção "Criar com OnlyOffice".

**Causa**: A opção estava condicionada à configuração `texto_articulado_proposicao`.

**Solução**: Modificado `sapl/materia/forms.py` para sempre mostrar as opções de tipo de texto:

```python
# Sempre incluir tipo_texto para permitir escolher entre Arquivo Digital e OnlyOffice
if 'tipo_texto' not in self._meta.fields:
    self._meta.fields.append('tipo_texto')

# Ajustar choices baseado na configuração
if not self.texto_articulado_proposicao:
    self.fields['tipo_texto'].choices = [
        ('D', _('Arquivo Digital')),
        ('O', _('Criar com OnlyOffice'))
    ]
```

### 5. Container OnlyOffice não inicia

**Sintoma**: Container fica reiniciando ou não responde.

**Causa**: OnlyOffice requer recursos significativos (mínimo 2GB RAM).

**Solução**:
- Verificar logs: `docker logs onlyoffice-documentserver`
- Aumentar recursos do Docker Desktop
- Aguardar inicialização completa (~2-3 minutos na primeira vez)

### 6. Documento em branco não é criado

**Sintoma**: Erro ao abrir editor para documento sem arquivo.

**Causa**: Biblioteca `python-docx` não instalada.

**Solução**: Adicionar ao `requirements.txt`:
```
python-docx
```

---

## Melhorias no Formulário de Proposição

### Alterações Visuais

O template `sapl/templates/materia/proposicao_form.html` foi completamente reformulado para melhorar a experiência do usuário.

#### 1. Botão "Novo Tipo"

**Antes**: Colado ao select, sem espaçamento adequado.

**Depois**: Posicionado ao lado do label com flexbox:

```css
#div_id_tipo .tipo-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
}
```

#### 2. Opções de Tipo de Texto

**Antes**: Radio buttons simples, difíceis de clicar.

**Depois**: Cards visuais com hover e seleção destacada:

```css
#div_id_tipo_texto .form-check label {
    padding: 14px 20px;
    background: white;
    border: 2px solid #dee2e6;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s ease;
}

#div_id_tipo_texto .form-check label.checked {
    border-color: #007bff;
    background: #e7f1ff;
    box-shadow: 0 0 0 1px #007bff;
}
```

#### 3. Layout dos Campos

**Antes**: Campos divididos em colunas (5 + 7).

**Depois**: Campos ocupam largura total (12 colunas).

```python
# forms.py
fields.append(to_column((InlineRadios('tipo_texto'), 12)))
fields.append(to_column(('texto_original', 12)))
```

#### 4. Botões do Formulário

**Antes**: Desalinhados.

**Depois**: Alinhados com flexbox e separados visualmente:

```css
.form-group.row.justify-content-between {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 20px 0;
    margin-top: 20px;
    border-top: 1px solid #e9ecef;
}
```

#### 5. Feedback de Busca de Matéria

**Antes**: Apenas texto.

**Depois**: Alertas coloridos com ícones:

```javascript
if (data.pagination.total_entries === 1) {
    $(".ementa_materia")
        .html('<strong><i class="fa fa-check-circle text-success"></i> Matéria encontrada:</strong> ' + data.results[0].ementa)
        .addClass('alert-info');
} else {
    $(".ementa_materia")
        .html('<i class="fa fa-exclamation-triangle"></i> <em>Matéria não encontrada</em>')
        .addClass('alert-warning');
}
```

---

## Testando a Integração

### 1. Iniciar os containers

```bash
cd docker
docker-compose -f docker-compose-dev.yml up -d
```

### 2. Verificar status

```bash
# SAPL
curl http://localhost:8000

# OnlyOffice (aguardar ~2 min na primeira vez)
curl http://localhost:8001/healthcheck
```

### 3. Testar no navegador

1. Acessar `http://localhost:8000`
2. Fazer login
3. Navegar até um documento (Proposição, Matéria, Norma, etc.)
4. Clicar em "Editar com OnlyOffice"
5. Editar o documento
6. Fechar e verificar se foi salvo

### 4. Verificar logs

```bash
# Logs do SAPL
docker logs -f sapl-dev

# Logs do OnlyOffice
docker logs -f onlyoffice-documentserver
```

