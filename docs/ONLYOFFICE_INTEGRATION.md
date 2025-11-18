# Integração OnlyOffice Document Server no Legisinc

## Visão Geral

A integração com o OnlyOffice Document Server permite que os parlamentares criem e editem proposições diretamente no navegador usando um editor de texto completo, similar ao Microsoft Word ou LibreOffice Writer.

## Configuração

### 1. Iniciar o OnlyOffice via Docker

O OnlyOffice já está configurado no `docker-compose-dev.yml`. Para iniciar:

```bash
cd /home/bruno/sapl/docker
docker-compose -f docker-compose-dev.yml up -d
```

Isso irá:
- Subir o container `sapl-dev` na porta 8000
- Subir o container `onlyoffice-documentserver` na porta 8001

### 2. Verificar se o OnlyOffice está rodando

Acesse: `http://localhost:8001/welcome/`

Se você ver a página de boas-vindas do OnlyOffice, está funcionando!

### 3. Variáveis de Ambiente

As seguintes variáveis de ambiente estão configuradas em `sapl/settings.py`:

- `ONLYOFFICE_URL`: URL do servidor OnlyOffice (padrão: `http://localhost:8001`)
- `ONLYOFFICE_JWT_SECRET`: Chave secreta para JWT (opcional, para segurança adicional)
- `ONLYOFFICE_JWT_ENABLED`: Se o JWT está habilitado (padrão: False)

### 4. Instalar Dependências Python

```bash
pip install -r requirements/requirements.txt
```

Isso instalará:
- `python-docx==1.1.0` - Para criar documentos Word em branco
- `PyJWT==2.8.0` - Para autenticação JWT (opcional)
- `requests==2.31.0` - Para fazer requests HTTP

## Como Usar

### Criando uma Proposição com OnlyOffice

1. **Acesse** `/proposicao/create`

2. **Preencha** os dados básicos:
   - Tipo de Proposição
   - Ementa/Descrição

3. **Selecione** a opção "Criar com OnlyOffice" no campo "Tipo do Texto da Proposição"

4. **Salve** a proposição (ainda sem texto)

5. **Na página de detalhes da proposição**, clique no botão "Editar com OnlyOffice"

6. **O editor será aberto** no navegador, pronto para uso

7. **Digite o texto** da proposição usando todos os recursos do editor:
   - Formatação de texto (negrito, itálico, sublinhado)
   - Parágrafos e espaçamento
   - Listas numeradas e com marcadores
   - Tabelas
   - Imagens
   - Cabeçalhos e rodapés
   - E muito mais!

8. **O documento é salvo automaticamente** enquanto você edita

9. **Quando terminar**, feche o editor e volte para a página da proposição

10. **O arquivo estará disponível** no campo "Texto Original"

### Editando uma Proposição Existente

1. Acesse a proposição em `/proposicao/{id}/`

2. Se a proposição **ainda não foi enviada**, você verá o botão "Editar com OnlyOffice"

3. Clique no botão para abrir o editor

4. Edite o documento

5. As alterações são salvas automaticamente

### Enviando a Proposição

Após criar/editar o texto com OnlyOffice:

1. Volte para a página de detalhes da proposição
2. Clique em "Enviar"
3. O documento será enviado junto com a proposição

## Arquitetura

### Endpoints Criados

- **`/proposicao/{pk}/onlyoffice/editor`** - Renderiza a página com o editor
- **`/proposicao/{pk}/onlyoffice/config`** - Retorna configuração JSON para o editor
- **`/proposicao/{pk}/onlyoffice/download`** - Endpoint para o OnlyOffice baixar o documento
- **`/proposicao/{pk}/onlyoffice/callback`** - Callback para salvar o documento editado

### Fluxo de Edição

```
┌──────────────┐
│   Usuário    │
└──────┬───────┘
       │ 1. Acessa editor
       ▼
┌──────────────────┐
│  Legisinc (Django)   │
└──────┬───────────┘
       │ 2. Retorna HTML com script do OnlyOffice
       ▼
┌──────────────────┐
│  Navegador       │
└──────┬───────────┘
       │ 3. Carrega config via /onlyoffice/config
       ▼
┌──────────────────┐
│  Legisinc (Django)   │
└──────┬───────────┘
       │ 4. Retorna configuração JSON
       ▼
┌──────────────────┐
│  Navegador       │◄────────────┐
└──────┬───────────┘             │
       │ 5. Inicializa editor    │
       │                         │
       ▼                         │
┌──────────────────┐             │
│ OnlyOffice Server│             │
└──────┬───────────┘             │
       │ 6. Baixa documento      │
       │    via /download        │
       │                         │
       ▼                         │
┌──────────────────┐             │
│  Legisinc (Django)   │─────────────┘
└──────┬───────────┘
       │ 7. Retorna documento (ou documento em branco)
       ▼
┌──────────────────┐
│ OnlyOffice Server│
└──────┬───────────┘
       │ 8. Usuário edita
       │ 9. AutoSave
       ▼
┌──────────────────┐
│  Legisinc (Django)   │
│  /callback       │
└──────┬───────────┘
       │ 10. Salva documento no banco
       ▼
┌──────────────────┐
│   Proposição     │
│  texto_original  │
└──────────────────┘
```

### Segurança

- **Autenticação**: Apenas usuários autenticados podem acessar o editor
- **Autorização**: Apenas operadores do autor da proposição podem editar
- **Bloqueio após envio**: Proposições enviadas não podem mais ser editadas
- **JWT (Opcional)**: Pode ser habilitado para maior segurança

## Troubleshooting

### OnlyOffice não carrega

**Problema**: A página do editor mostra "Erro ao carregar o editor"

**Solução**:
1. Verifique se o container está rodando: `docker ps | grep onlyoffice`
2. Verifique os logs: `docker logs onlyoffice-documentserver`
3. Verifique se a porta 8001 está acessível: `curl http://localhost:8001/welcome/`

### Documento não salva

**Problema**: Edições não são salvas

**Solução**:
1. Verifique os logs do Django para ver se o callback está sendo chamado
2. Verifique se a URL de callback está acessível pelo OnlyOffice
3. Se estiver usando Docker, verifique se os containers estão na mesma rede

### Erro de permissão

**Problema**: "Você não tem permissão para editar esta proposição"

**Solução**:
1. Verifique se o usuário está vinculado ao autor da proposição
2. Verifique em `/sistema/usuario/{id}/edit` se o campo "Autor" está preenchido

## Configuração de Produção

Para ambiente de produção:

1. **Habilite JWT**:
   ```bash
   ONLYOFFICE_JWT_ENABLED=True
   ONLYOFFICE_JWT_SECRET="sua-chave-secreta-forte-aqui"
   ```

2. **Use HTTPS**:
   - Configure um certificado SSL para o OnlyOffice
   - Atualize `ONLYOFFICE_URL` para usar `https://`

3. **Configure recursos**:
   - O OnlyOffice pode consumir bastante memória
   - Recomendado: mínimo 4GB RAM para o container

4. **Backup**:
   - Os documentos são salvos no campo `texto_original` da proposição
   - Certifique-se de fazer backup regular do banco de dados e arquivos de mídia

## Recursos Adicionais

- [Documentação OnlyOffice](https://api.onlyoffice.com/editors/basic)
- [OnlyOffice Document Server no Docker](https://github.com/ONLYOFFICE/Docker-DocumentServer)
