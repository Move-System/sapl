# Subir o SAPL apontando para o banco remoto (localhost)

Passo a passo para subir o ambiente local usando o Postgres já disponível em `legisinc.com.br:5432`.

## 1) Preparar o ambiente Python

```bash
cd /root/dev/sapl
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements/requirements.txt
```

## 2) Configurar variáveis de ambiente

Edite `sapl/.env` com os valores do banco remoto:

```env
DATABASE_URL=postgresql://kemuel:kasepulvida@legisinc.com.br:5432/sapl
SECRET_KEY=<sua-chave-secreta>
DEBUG=True
EMAIL_USE_TLS=True
EMAIL_PORT=587
```

> Observação: não rode `migrate` contra esse banco se ele for de produção.

## 3) Testar conexão (opcional)

```bash
python manage.py showmigrations --plan
```

## 4) Subir o servidor Django

```bash
python manage.py runserver 0.0.0.0:8001
```

Se preferir sem autoreload: `python manage.py runserver 0.0.0.0:8001 --noreload`.
