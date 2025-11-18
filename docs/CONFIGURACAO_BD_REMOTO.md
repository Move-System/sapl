# Configuração do Legisinc com Banco de Dados Remoto

Este documento explica como configurar o Legisinc para usar um banco de dados PostgreSQL remoto.

## Problemas Corrigidos

### 1. Erro 404 ao acessar http://localhost:8000/

**Causa**: O gunicorn não estava iniciando por dois motivos:
- Permissões incorretas no arquivo de migration do TCE
- Configuração duplicada do socket Unix no gunicorn

**Soluções aplicadas**:

#### a) Correção do arquivo gunicorn.conf.py
Arquivo: `docker/startup_scripts/gunicorn.conf.py`

**Antes:**
```python
SOCKFILE = f"unix:{DJANGODIR}/run/gunicorn.sock"
bind = f"unix:{SOCKFILE}"  # Resulta em: unix:unix:/var/interlegis/sapl/run/gunicorn.sock
```

**Depois:**
```python
SOCKFILE = f"{DJANGODIR}/run/gunicorn.sock"
bind = f"unix:{SOCKFILE}"  # Correto: unix:/var/interlegis/sapl/run/gunicorn.sock
```

#### b) Correção de permissões de migrations
Caso encontre erro de permissão em arquivos de migration, execute:
```bash
docker exec sapl chmod 644 /var/interlegis/sapl/sapl/*/migrations/*.py
```

## Configuração do Banco de Dados Remoto

### Passo 1: Editar o docker-compose.yaml

Arquivo: `docker/docker-compose.yaml`

Adicione a variável `DATABASE_URL` nas variáveis de ambiente do serviço `sapl`:

```yaml
  sapl:
    build:
      context: ../
      dockerfile: ./docker/Dockerfile
    container_name: sapl
    restart: always
    environment:
      ADMIN_PASSWORD: interlegis
      ADMIN_EMAIL: email@dominio.net
      DEBUG: 'False'
      DATABASE_URL: postgresql://bruno:Sapl%402025@legisinc.com.br:5432/sapl
      # ... outras variáveis
```

**IMPORTANTE**: Se a senha contiver caracteres especiais como `@`, eles devem ser codificados:
- `@` → `%40`
- `:` → `%3A`
- `/` → `%2F`

Exemplo: `Sapl@2025` vira `Sapl%402025`

### Passo 2: Remover dependência do banco local

No mesmo arquivo, remova `sapldb` das dependências:

**Antes:**
```yaml
    depends_on:
      - sapldb
      - saplsolr
      - onlyoffice
```

**Depois:**
```yaml
    depends_on:
      - saplsolr
      - onlyoffice
```

### Passo 3: Testar a conexão com o banco remoto

Antes de iniciar o Legisinc, teste a conexão:

```bash
docker run --rm postgres:10.5-alpine psql \
  "postgresql://bruno:Sapl%402025@legisinc.com.br:5432/sapl" \
  -c "\dt"
```

Se listar as tabelas, a conexão está funcionando!

### Passo 4: Reconstruir a imagem Docker

```bash
cd /home/bruno/sapl/docker
docker-compose build sapl
```

### Passo 5: Iniciar os containers

```bash
docker-compose up -d
```

### Passo 6: Verificar os logs

```bash
docker logs sapl -f
```

Aguarde até ver:
```
[YYYY-MM-DDThh:mm:ss-03:00] Starting gunicorn...
[YYYY-MM-DDThh:mm:ss-03:00] Starting nginx...
```

### Passo 7: Testar o acesso

```bash
curl -I http://localhost:8000/
```

Deve retornar: `HTTP/1.1 200 OK`

## Acessando o Sistema

### URL
http://localhost:8000/

### Usuários disponíveis

O sistema cria automaticamente dois usuários locais:

- **Usuário**: `interlegis` | **Senha**: `interlegis` (ou valor de ADMIN_PASSWORD)
- **Usuário**: `admin` | **Senha**: `interlegis` (ou valor de ADMIN_PASSWORD)

Se estiver usando um banco remoto existente, use os usuários já cadastrados nesse banco.

## Estrutura dos Containers

```
┌─────────────────┐
│      Legisinc       │ → Porta 8000:80
│  (Aplicação)    │
└────────┬────────┘
         │
         ├──→ legisinc.com.br:5432 (PostgreSQL Remoto)
         │
         ├──→ SOLR (Porta 8983)
         │
         └──→ OnlyOffice (Porta 8002)
```

## Solução de Problemas

### Gunicorn não inicia (sem socket criado)

```bash
# Verificar logs detalhados
docker exec sapl cat /var/log/sapl/error.log

# Verificar permissões
docker exec sapl ls -la /var/interlegis/sapl/run/
```

### Erro de conexão com banco de dados

```bash
# Verificar variáveis de ambiente
docker exec sapl env | grep DATABASE_URL

# Testar conexão manualmente
docker run --rm postgres:10.5-alpine psql \
  "postgresql://usuario:senha@host:5432/database" \
  -c "SELECT version();"
```

### Erro 404 no nginx

```bash
# Verificar se o socket existe
docker exec sapl ls -la /var/interlegis/sapl/run/gunicorn.sock

# Se não existir, verificar por que o gunicorn não iniciou
docker logs sapl 2>&1 | grep -i error
```

## Comandos Úteis

```bash
# Ver status dos containers
docker-compose ps

# Reiniciar o Legisinc
docker-compose restart sapl

# Ver logs em tempo real
docker logs sapl -f

# Parar todos os containers
docker-compose down

# Iniciar todos os containers
docker-compose up -d

# Reconstruir e iniciar
docker-compose up -d --build sapl

# Executar comando no container
docker exec -it sapl bash
```

## Estrutura de Arquivos Importantes

```
sapl/
├── docker/
│   ├── docker-compose.yaml          # Configuração principal
│   ├── Dockerfile                   # Imagem do Legisinc
│   └── startup_scripts/
│       ├── gunicorn.conf.py         # Configuração do gunicorn
│       ├── start.sh                 # Script de inicialização
│       └── create_admin.py          # Criação de usuários admin
├── sapl/
│   └── settings.py                  # Configurações Django
└── requirements/
    └── requirements.txt             # Dependências Python
```

## Notas Finais

- O banco de dados local (container `postgres`) não é mais necessário quando usando banco remoto
- As migrations são aplicadas automaticamente na inicialização
- O timezone do banco é configurado automaticamente para `America/Sao_Paulo`
- Os arquivos de media e data ficam em volumes Docker separados
