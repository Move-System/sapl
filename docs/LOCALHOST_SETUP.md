# Subir o SAPL em localhost

A abordagem recomendada usa **Docker**, pois replica fielmente o ambiente de produção.

Há dois modos de operação:

| Modo | Quando usar |
|---|---|
| **Localhost completo** (banco local) | Desenvolvimento do zero, sem dependência de banco remoto |
| **Banco remoto** | Testar com dados reais de produção/homologação |

---

## Modo 1: Localhost completo (banco PostgreSQL local)

Sobe a aplicação **e** o banco juntos, sem precisar de `.env` nem banco externo.

```bash
cd /root/dev/sapl
docker compose -f docker/docker-compose-local.yml up --build
```

Na primeira vez, rode as migrations dentro do container:

```bash
docker exec -it sapl-dev python manage.py migrate
docker exec -it sapl-dev python manage.py createsuperuser
```

Servidor disponível em: **http://localhost:8000**
Banco disponível em: `localhost:5432` (usuário: `sapl` / senha: `sapl` / banco: `sapl`)

Para parar:

```bash
docker compose -f docker/docker-compose-local.yml down
```

> Os dados do banco ficam no volume Docker `sapl-pgdata` e persistem entre reinicializações.
> Para apagar tudo: `docker compose -f docker/docker-compose-local.yml down -v`

---

## Modo 2: Banco remoto (apontando para banco externo)

O banco é controlado pelo `sapl/.env`. Basta trocar o `DATABASE_URL` e reiniciar o container.

---

## 1) Configurar o `sapl/.env`

Edite `sapl/.env` com as credenciais do banco desejado:

```env
DATABASE_URL=postgresql://usuario:senha@host:5432/banco
SECRET_KEY=<sua-chave-secreta>
DEBUG=True
EMAIL_USE_TLS=True
EMAIL_PORT=587
```

> **Dica:** para trocar de banco, basta editar `DATABASE_URL` e reiniciar — sem alterar nenhum outro arquivo.
> **Atenção:** não rode `migrate` se o banco for de produção.

---

## 2) Subir o ambiente com Docker

```bash
cd /root/dev/sapl
docker compose -f docker/docker-compose-dev.yml --env-file sapl/.env up --build
```

O código-fonte é montado como volume — alterações em `.py` são recarregadas automaticamente.

Servidor disponível em: **http://localhost:8000**

---

## 3) Parar o ambiente

```bash
docker compose -f docker/docker-compose-dev.yml down
```

---

## 4) Rodar comandos Django no container

```bash
docker exec -it sapl-dev python manage.py showmigrations --plan
docker exec -it sapl-dev python manage.py shell
```

---

## Por que Docker em vez de venv + runserver direto?

| | venv + runserver | Docker (recomendado) |
|---|---|---|
| `DEBUG=True` no .env | Não funcionava (settings.py lia `DJANGO_DEBUG`) | ✅ Corrigido, funciona |
| Banco remoto | Funciona se a porta estiver acessível | ✅ Funciona via `extra_hosts: host-gateway` |
| Proximidade com prod | ❌ Diferenças de config e WSGI | ✅ Mesmo Dockerfile |

---

## Alternativa: venv + runserver (sem Docker)

```bash
cd /root/dev/sapl
source .venv/bin/activate
pip install -r requirements/requirements.txt
python manage.py runserver 0.0.0.0:8000
```

> O `settings.py` foi corrigido para aceitar `DEBUG=True` (além do legado `DJANGO_DEBUG=True`).

---

## Problemas comuns

### Container não alcança o banco remoto
O `docker-compose-dev.yml` já configura `extra_hosts: host-gateway`. Se ainda assim falhar:

```bash
nc -zv <host-do-banco> 5432
```

### `DEBUG=True` não ativa o modo debug
O `settings.py` foi corrigido para aceitar tanto `DEBUG` quanto `DJANGO_DEBUG`.
Certifique-se que o valor está sem aspas: `DEBUG=True`.

### Static files não carregam com Gunicorn

```bash
docker exec -it sapl-dev python manage.py collectstatic --noinput
```
