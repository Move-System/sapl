# Configuração do SGVP com Banco de Dados Remoto

Este documento explica como configurar o SGVP para usar um banco de dados PostgreSQL remoto.

> **Atualizado em 13/08/2026.** Duas correções: o host `sgvp.com.br:5432` não responde
> mais — o banco remoto ativo é `demo.legisinc.com.br:5432` (base `demo`) — e as
> credenciais que estavam em claro neste documento foram rejeitadas pelo servidor. Peça as credenciais atuais ao responsável pelo ambiente e
> mantenha-as fora do repositório (`sapl/.env`, que é gitignored, ou variáveis de
> ambiente do host). Para subir só o Django em desenvolvimento, sem o compose completo,
> veja [LOCALHOST_SETUP.md](LOCALHOST_SETUP.md).
>
> **Leia antes a seção [O que o usuário remoto precisa poder fazer](#o-que-o-usuário-remoto-precisa-poder-fazer)**:
> o `start.sh` executa DDL na inicialização, e um usuário só de leitura/escrita de dados
> — como o disponível hoje no `demo` — **derruba o container no boot**. Nesse caso o
> caminho é a cópia local do banco, descrita na seção 4 do
> [LOCALHOST_SETUP.md](LOCALHOST_SETUP.md#4-cópia-local-do-banco-quando-há-migration-pendente).

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
      DATABASE_URL: postgresql://<usuario>:<senha-url-encoded>@demo.legisinc.com.br:5432/demo
      # ... outras variáveis
```

Prefira injetar a `DATABASE_URL` por variável de ambiente do host (ou por um `.env`
gitignored) em vez de escrevê-la no `docker-compose.yaml`, que é versionado.

**IMPORTANTE**: Se a senha contiver caracteres especiais como `@`, eles devem ser codificados:
- `@` → `%40`
- `:` → `%3A`
- `/` → `%2F`

Exemplo: `S3nh@2026` vira `S3nh%402026`

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

Antes de iniciar o SGVP, teste a conexão:

```bash
docker run --rm postgres:17-alpine psql \
  "postgresql://<usuario>:<senha-url-encoded>@demo.legisinc.com.br:5432/demo" \
  -c "\dt"
```

Se listar as tabelas, a conexão está funcionando — mas **conectar não basta**: veja a
seção seguinte antes de subir o compose.

## O que o usuário remoto precisa poder fazer

Conexão bem-sucedida não garante boot. O `docker/startup_scripts/start.sh` roda, nesta
ordem, duas etapas que exigem privilégio além de ler e gravar dados:

| Etapa no `start.sh` | Comando | Privilégio exigido | Se falhar |
|---|---|---|---|
| `configure_pg_timezone` | `ALTER DATABASE … SET timezone` e `ALTER ROLE … SET timezone` | dono do banco / superusuário | `exit 1` — o container morre no boot |
| `migrate_db` | `manage.py migrate --noinput` | `CREATE` no schema `public` (quando há migration pendente) | erro e boot interrompido |

O `configure_pg_timezone` só é pulado se o banco já responder `UTC` em `show time zone`
(linhas 45-49 do `start.sh`). O `demo` responde `America/Sao_Paulo`, então **a etapa não é
pulada** e o `ALTER DATABASE` é tentado de verdade.

Verifique os três pontos antes de subir:

```bash
DB="postgresql://<usuario>:<senha-url-encoded>@demo.legisinc.com.br:5432/demo"
docker run --rm -e PGURL="$DB" postgres:17-alpine sh -c 'psql "$PGURL" \
  -Atc "show time zone;" \
  -c "select has_schema_privilege(current_user, '"'"'public'"'"', '"'"'CREATE'"'"');" \
  -c "select pg_get_userbyid(datdba) as dono_do_banco, current_user as voce
      from pg_database where datname = current_database();"'
```

Situação verificada em 13/08/2026 com o usuário `kasepulvida` no `demo`: timezone
`America/Sao_Paulo`, `CREATE` no schema = `f`, dono do banco = `postgres` (não é o
usuário). Ou seja, **este documento não sobe hoje com essas credenciais** — o boot para no
`ALTER DATABASE`. As saídas:

```
ALTER DATABASE "demo" failed. Need DB owner or superuser.
django.db.utils.ProgrammingError: permission denied for schema public
```

Três caminhos, em ordem de preferência:

1. **Cópia local do banco** — você vira dono e nada disso trava. Procedimento na seção 4
   do [LOCALHOST_SETUP.md](LOCALHOST_SETUP.md#4-cópia-local-do-banco-quando-há-migration-pendente).
2. **Pedir os privilégios ao dono do banco** (`GRANT CREATE ON SCHEMA public` e as
   `ALTER`s de timezone aplicadas por ele) — só faz sentido se o banco remoto for mesmo o
   alvo; lembre que ele é compartilhado.
3. **Rodar só o Django, sem o compose** — o `runserver` não executa o `start.sh`, então
   nenhuma das duas etapas acontece. Serve quando não há migration pendente e você só
   precisa ler/gravar dados. Ver [LOCALHOST_SETUP.md](LOCALHOST_SETUP.md).

### Passo 4: Reconstruir a imagem Docker

```bash
cd ~/dev/sapl/docker
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
│      SGVP       │ → Porta 8000:80
│  (Aplicação)    │
└────────┬────────┘
         │
         ├──→ demo.legisinc.com.br:5432 (PostgreSQL 17 Remoto)
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
docker run --rm postgres:17-alpine psql \
  "postgresql://usuario:senha@host:5432/database" \
  -c "SELECT version();"
```

Use um cliente `psql` de versão maior ou igual à do servidor (o `demo` roda PostgreSQL
17.10); um cliente antigo falha no `pg_dump`/`pg_restore`.

### `ALTER DATABASE "…" failed. Need DB owner or superuser.`

O container morre no boot, antes das migrations. O usuário do `DATABASE_URL` não é dono do
banco nem superusuário, e o banco não está em UTC — então o `configure_pg_timezone` do
`start.sh` tenta o `ALTER DATABASE` e aborta com `exit 1`.
Ver [O que o usuário remoto precisa poder fazer](#o-que-o-usuário-remoto-precisa-poder-fazer).

### `permission denied for schema public`

```
django.db.utils.ProgrammingError: permission denied for schema public
LINE 1: CREATE TABLE "..." ("id" serial NO...
```

Há migration pendente e o usuário não tem `CREATE` no schema `public`. A migration roda em
transação, então a tentativa recusada não deixa resíduo no banco. Confirme com:

```bash
docker exec sapl python3 manage.py showmigrations | grep '\[ \]'
```

Solução: cópia local do banco (seção 4 do
[LOCALHOST_SETUP.md](LOCALHOST_SETUP.md#4-cópia-local-do-banco-quando-há-migration-pendente))
ou `GRANT CREATE ON SCHEMA public` concedido pelo dono do banco.

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

# Reiniciar o SGVP
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
│   ├── Dockerfile                   # Imagem do SGVP
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
- As migrations são aplicadas automaticamente na inicialização (`migrate_db` no `start.sh`)
  — o que também significa que **não há como subir o compose sem tentar migrar**: se houver
  migration pendente e o usuário não tiver `CREATE`, o boot falha
- O timezone do banco é configurado automaticamente para `America/Sao_Paulo` via
  `ALTER DATABASE`/`ALTER ROLE` — exige dono do banco ou superusuário, e o `start.sh` só
  pula essa etapa se o banco já estiver em `UTC`
- Os arquivos de media e data ficam em volumes Docker separados
