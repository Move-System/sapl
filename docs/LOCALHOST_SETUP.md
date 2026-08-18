# Subir o SAPL em localhost (banco remoto ou cópia local)

Passo a passo para subir o ambiente local usando o Postgres já disponível em
`demo.legisinc.com.br:5432` (base `demo`) — ou uma cópia local dele, quando a tarefa
exigir migration.

> Validado em 13/08/2026 em Ubuntu 26.04. O host `sgvp.com.br:5432`, citado em
> versões anteriores deste documento, não responde mais — use `demo.legisinc.com.br`.

**Antes de tudo, responda uma pergunta: esta tarefa precisa de migration?**
Se precisar, o banco remoto não serve — o usuário de acesso não tem permissão de DDL —
e você vai precisar da cópia local descrita na [seção 4](#4-cópia-local-do-banco-quando-há-migration-pendente).
A [seção 3](#3-decidir-remoto-direto-ou-cópia-local) mostra como descobrir isso em dois comandos.

## 1) Preparar o ambiente Python

O projeto roda em **Python 3.12 + Django 2.2**. Django 2.2 não funciona em Python 3.13+,
então escolha o caminho conforme o seu sistema.

### Opção A — Docker (recomendado; obrigatório em Ubuntu 24.04+)

Distribuições recentes (Ubuntu 26.04, por exemplo) já não oferecem Python 3.12 no apt.
Nesse caso use a imagem `python:3.12-slim-bookworm`, com as mesmas dependências de
sistema do `docker/Dockerfile.dev`:

```bash
cd ~/dev/sapl
docker build -f docker/Dockerfile.dev -t sapl:dev .
```

> **Atenção**: o `Dockerfile.dev` instala `requirements/dev-requirements.txt`, que hoje
> tem um conflito de dependências — `django-debug-toolbar` está pinado em `2.2.1` no
> `requirements.txt` e em `3.2.4` no `dev-requirements.txt`, e o pip não resolve.
> Até isso ser corrigido, copie o `Dockerfile.dev` trocando a última linha do
> `pip install` para `requirements/requirements.txt` e construa a partir da cópia:

```bash
sed 's|dev-requirements.txt|requirements.txt|' docker/Dockerfile.dev > /tmp/Dockerfile.localhost
docker build -f /tmp/Dockerfile.localhost -t sapl:localhost .
```

### Opção B — virtualenv (se o sistema tiver Python 3.12)

```bash
cd ~/dev/sapl
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements/requirements.txt
```

## 2) Configurar variáveis de ambiente

Crie `sapl/.env` (o arquivo é gitignored) com os valores do banco remoto:

```env
DATABASE_URL=postgresql://<usuario>:<senha-url-encoded>@demo.legisinc.com.br:5432/demo
SECRET_KEY=<sua-chave-secreta>
DEBUG=True
DJANGO_DEBUG=True
EMAIL_USE_TLS=True
EMAIL_PORT=587
```

> **`DJANGO_DEBUG`, não `DEBUG`**: o `settings.py` lê o modo debug do Django de
> `DJANGO_DEBUG` (linha 38). A variável `DEBUG` só controla o log de conexão do banco.
> Defina as duas.
>
> **Senha com caractere especial** precisa ser URL-encoded no `DATABASE_URL`:
> `@` → `%40`, `:` → `%3A`, `/` → `%2F`. Ex.: `S3nh@2026` vira `S3nh%402026`.
> Sem isso o parser da URL quebra no lugar errado e a autenticação falha.

Peça as credenciais atuais ao responsável pelo ambiente — as que estavam neste
documento e no `CONFIGURACAO_BD_REMOTO.md` foram rejeitadas pelo servidor em 12/08/2026.

## 3) Decidir: remoto direto ou cópia local?

Esta é a decisão que define o resto do setup. O critério é **se há migration pendente**:

```bash
docker run --rm -v "$PWD":/sapl-dev -w /sapl-dev sapl:localhost \
  python manage.py showmigrations | grep '\[ \]'
```

(o `settings.py` lê o `sapl/.env` do próprio volume montado, não precisa de `--env-file`;
se a `DATABASE_URL` já apontar para o banco local da seção 4, acrescente `--network sapl-net`)

- **Não imprimiu nada** (todas `[X]`) → siga usando o banco remoto direto. Pule para a seção 5.
  A aplicação grava dados normalmente; o que falta ao usuário é só permissão de DDL.
- **Imprimiu alguma migration** → você precisa de DDL, e o remoto vai recusar. **Faça a cópia
  local (seção 4).**

Para confirmar a permissão de DDL antes de tentar (opcional):

```bash
DB=$(grep '^DATABASE_URL=' sapl/.env | cut -d= -f2-)
docker run --rm -e PGURL="$DB" postgres:17-alpine \
  sh -c 'psql "$PGURL" -Atc "select has_schema_privilege(current_user, '"'"'public'"'"', '"'"'CREATE'"'"');"'
```

`f` significa sem permissão de criar tabela. Foi o resultado do usuário `kasepulvida` em
`demo.legisinc.com.br` em 13/08/2026 — o `migrate` falha com:

```
django.db.utils.ProgrammingError: permission denied for schema public
```

A migration roda em transação, então uma tentativa recusada não deixa resíduo no banco.

> **Nunca rode `migrate` num banco remoto compartilhado ou de produção** sem autorização
> do dono do banco. A alternativa "peça um `GRANT CREATE ON SCHEMA public`" existe, mas
> aplica o schema novo num banco que outras pessoas usam — prefira a cópia local.

## 4) Cópia local do banco (quando há migration pendente)

Copia o banco que você está apontando hoje — `demo` ou qualquer outro — para um Postgres
local, onde você tem liberdade total de `migrate`, reset e escrita, sem tocar no remoto.
São ~1 min para 61 MB. Os comandos leem a origem do próprio `sapl/.env`, então valem para
qualquer banco de origem.

**4.1 — Dump da origem** (só precisa de `SELECT`; o usuário remoto tem):

```bash
DB=$(grep '^DATABASE_URL=' sapl/.env | cut -d= -f2-)
docker run --rm -e PGURL="$DB" -v /tmp:/dump postgres:17-alpine \
  sh -c 'pg_dump "$PGURL" --no-owner --no-privileges --format=custom --file=/dump/origem.dump'
```

`--no-owner --no-privileges` descarta os donos e ACLs do servidor de origem, que não
existem na sua máquina.

**4.2 — Postgres local numa rede Docker própria:**

```bash
docker network create sapl-net
docker run -d --name sapl-postgres --network sapl-net -p 5433:5432 \
  -e POSTGRES_USER=sapl -e POSTGRES_PASSWORD=sapl -e POSTGRES_DB=demo \
  postgres:17-alpine
```

A rede é o que permite o container do SAPL enxergar o banco pelo hostname `sapl-postgres`.
A porta `5433` no host é só para você abrir um cliente SQL (DBeaver, psql) de fora.

**4.3 — Restaurar:**

```bash
docker cp /tmp/origem.dump sapl-postgres:/tmp/origem.dump
docker exec sapl-postgres pg_restore -U sapl -d demo \
  --no-owner --no-privileges /tmp/origem.dump
docker exec sapl-postgres psql -U sapl -d demo -Atc \
  "select count(*) from information_schema.tables where table_schema='public';"
```

A contagem deve bater com a da origem (163 tabelas no `demo` em 13/08/2026).

**4.4 — Apontar o `.env` para o banco local**, mantendo a URL remota comentada para voltar
depois:

```env
# DATABASE_URL_REMOTO=postgresql://<usuario>:<senha>@demo.legisinc.com.br:5432/demo
DATABASE_URL=postgresql://sapl:sapl@sapl-postgres:5432/demo
```

> Se preferir guardar um backup do `.env`, **não deixe o arquivo dentro do repositório**:
> o `.gitignore` cobre `sapl/.env`, mas não variações como `.env.bak`, e a senha do remoto
> vazaria no commit. Guarde fora da árvore do projeto.

**4.5 — Conectar o container do SAPL à rede e aplicar a migration:**

```bash
docker network connect sapl-net sapl-localhost
docker restart sapl-localhost
docker exec sapl-localhost python manage.py migrate
docker exec sapl-localhost python manage.py showmigrations | grep '\[ \]'   # sem saída
```

Se o container ainda não existe, crie-o já com `--network sapl-net` (seção 5).

**Para voltar ao banco remoto**: reponha a `DATABASE_URL` remota no `.env` e reinicie o
container. Os containers locais podem ficar parados (`docker stop sapl-postgres`) e serem
reaproveitados depois; para refazer a cópia do zero, `docker rm -f sapl-postgres` e repita
os passos 4.2 e 4.3.

## 5) Subir o servidor Django

### Docker

```bash
docker run -d --name sapl-localhost -p 8001:8001 \
  -v "$PWD":/sapl-dev -w /sapl-dev sapl:localhost \
  python manage.py runserver 0.0.0.0:8001
```

Se estiver usando a cópia local do banco (seção 4), acrescente `--network sapl-net` para o
container enxergar o `sapl-postgres`.

O repositório é montado como volume, então o autoreload pega as edições no código.

```bash
docker logs -f sapl-localhost   # acompanhar o log
docker restart sapl-localhost   # reiniciar
docker rm -f sapl-localhost     # derrubar
```

### virtualenv

```bash
python manage.py runserver 0.0.0.0:8001
```

Se preferir sem autoreload: `python manage.py runserver 0.0.0.0:8001 --noreload`.

## 6) Verificar

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8001/        # 200
curl -s http://localhost:8001/ | grep -o '<title>[^<]*</title>'
```

Acesse <http://localhost:8001> — o título deve ser
`SGVP - Câmara Municipal de Franco da Rocha`. Use os usuários já cadastrados no banco
(os mesmos do remoto, se você fez a cópia da seção 4) para logar.
