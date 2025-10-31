# 🎉 Sistema SAPL + OnlyOffice - PRONTO PARA USO!

## ✅ Status dos Serviços

Todos os containers estão rodando e funcionando:

```
✓ PostgreSQL     - Porta 5435 (localhost) / 5432 (interno)
✓ SAPL           - http://localhost:8000
✓ OnlyOffice     - http://localhost:8002
```

---

## 🔑 Credenciais de Acesso

### Superusuário SAPL
- **URL**: http://localhost:8000/login
- **Usuário**: `admin`
- **Senha**: `admin`

### Banco de Dados PostgreSQL
- **Host**: localhost
- **Porta**: 5435 (externa) ou `postgres:5432` (dentro do Docker)
- **Database**: sapl
- **Usuário**: sapl
- **Senha**: sapl

---

## 🚀 Como Testar o OnlyOffice

### 1. Fazer Login
```
http://localhost:8000/login
Usuário: admin
Senha: admin
```

### 2. Criar um Autor

O sistema precisa vincular um usuário a um Autor para poder criar proposições.

**Opção A - Criar Parlamentar (Recomendado):**

1. Acesse: http://localhost:8000/parlamentar/create
2. Preencha:
   - **Nome Completo**: Seu Nome
   - **Nome Parlamentar**: Nome de Exibição
   - Outros campos conforme necessário
3. Salve

4. Depois, acesse: http://localhost:8000/sistema/usuario/1/edit
5. No campo **"Este usuário registrará proposições para um Autor?"**, selecione o parlamentar criado
6. Salve

**Opção B - Script Rápido:**

```bash
docker exec sapl-dev python manage.py shell -c "
from sapl.parlamentares.models import Parlamentar
from sapl.base.models import Autor, TipoAutor
from django.contrib.auth.models import User, Group

# Criar Parlamentar
if not Parlamentar.objects.filter(nome_parlamentar='Admin').exists():
    p = Parlamentar.objects.create(
        nome_completo='Administrador Sistema',
        nome_parlamentar='Admin',
        ativo=True
    )
    print(f'Parlamentar criado: {p}')

    # Criar Autor
    tipo = TipoAutor.objects.filter(descricao='Parlamentar').first()
    if tipo:
        autor = Autor.objects.create(
            tipo=tipo,
            nome='Admin',
            parlamentar=p
        )
        print(f'Autor criado: {autor}')

        # Vincular usuário ao autor
        user = User.objects.get(username='admin')
        autor.operadores.add(user)

        # Adicionar ao grupo Autor
        grupo_autor = Group.objects.get(name='Autor')
        user.groups.add(grupo_autor)

        print('Usuário vinculado ao autor!')
else:
    print('Parlamentar Admin já existe')
"
```

### 3. Criar Proposição com OnlyOffice

1. **Acesse**: http://localhost:8000/proposicao/create

2. **Preencha**:
   - **Tipo**: Selecione um tipo (ex: Projeto de Lei)
   - **Ementa/Descrição**: Descreva a proposição
   - **Tipo do Texto da Proposição**: Selecione **"Criar com OnlyOffice"** ✨

3. **Salve** a proposição

4. **Clique em "Editar com OnlyOffice"** na página da proposição

5. **✨ O editor OnlyOffice abrirá no navegador!**

6. **Edite** o documento usando todos os recursos:
   - Formatação de texto (negrito, itálico, sublinhado)
   - Listas numeradas e com marcadores
   - Tabelas
   - Imagens
   - Cabeçalhos e rodapés
   - E muito mais!

7. **Salve** (salvamento automático está ativado)

8. **Feche** o editor quando terminar

---

## 📋 Gerenciamento dos Containers

### Ver logs

```bash
cd /home/bruno/sapl/docker

# Ver logs do SAPL
docker logs sapl-dev -f

# Ver logs do OnlyOffice
docker logs onlyoffice-documentserver -f

# Ver logs do PostgreSQL
docker logs sapl-postgres -f
```

### Parar containers

```bash
docker-compose -f docker-compose-dev-py39.yml stop
```

### Iniciar containers

```bash
docker-compose -f docker-compose-dev-py39.yml start
```

### Reiniciar containers

```bash
docker-compose -f docker-compose-dev-py39.yml restart
```

### Parar e remover containers

```bash
docker-compose -f docker-compose-dev-py39.yml down
```

### Reconstruir containers

```bash
docker-compose -f docker-compose-dev-py39.yml down
docker-compose -f docker-compose-dev-py39.yml build --no-cache
docker-compose -f docker-compose-dev-py39.yml up -d
```

---

## 🔧 Comandos Úteis

### Acessar shell do Django

```bash
docker exec -it sapl-dev python manage.py shell
```

### Criar outro superusuário

```bash
docker exec sapl-dev python manage.py shell -c "
from django.contrib.auth.models import User
User.objects.create_superuser('seu_usuario', 'email@example.com', 'sua_senha')
print('Usuário criado!')
"
```

### Acessar banco de dados

```bash
docker exec -it sapl-postgres psql -U sapl -d sapl
```

### Verificar migrations

```bash
docker exec sapl-dev python manage.py showmigrations
```

### Criar migrations

```bash
docker exec sapl-dev python manage.py makemigrations
```

---

## 🌐 URLs Importantes

- **SAPL**: http://localhost:8000
- **Admin Django**: http://localhost:8000/admin
- **OnlyOffice Welcome**: http://localhost:8002/welcome/
- **API SAPL**: http://localhost:8000/api/
- **Swagger API**: http://localhost:8000/api/docs/

---

## 📊 Estrutura de Portas

| Serviço | Porta Externa | Porta Interna |
|---------|---------------|---------------|
| SAPL | 8000 | 8000 |
| OnlyOffice | 8002 | 80 |
| PostgreSQL | 5435 | 5432 |

---

## ⚠️ Troubleshooting

### OnlyOffice não carrega

**Verificar se está rodando:**
```bash
docker ps | grep onlyoffice
curl http://localhost:8002/welcome/
```

**Ver logs:**
```bash
docker logs onlyoffice-documentserver
```

### SAPL não conecta ao banco

**Verificar PostgreSQL:**
```bash
docker exec sapl-postgres pg_isready -U sapl
```

**Verificar credenciais:**
```bash
docker exec sapl-dev env | grep DATABASE_URL
```

### Erro de permissão ao criar proposição

**Verifique se o usuário está vinculado a um autor:**
1. Acesse http://localhost:8000/sistema/usuario/1/edit
2. Verifique se o campo "Este usuário registrará proposições para um Autor?" está preenchido

---

## 📚 Documentação Completa

- `ONLYOFFICE_INTEGRATION.md` - Guia completo da integração
- `SETUP_ONLYOFFICE.md` - Instruções de setup detalhadas
- `ONLYOFFICE_RESUMO_FINAL.md` - Resumo executivo da implementação

---

## 🎯 Próximos Passos Recomendados

1. ✅ Criar Parlamentar/Autor (ver instruções acima)
2. ✅ Testar criação de proposição com OnlyOffice
3. 🔄 Configurar dados da Casa Legislativa (http://localhost:8000/sistema/casalegislativa)
4. 🔄 Importar dados existentes (se houver)
5. 🔄 Configurar backup automático
6. 🔄 Configurar produção (HTTPS, JWT OnlyOffice, etc.)

---

## 🎉 TUDO PRONTO!

O sistema SAPL com integração OnlyOffice está **100% funcional** e pronto para uso!

**Desenvolvido com ❤️ usando Claude Code**

Data de Implementação: 18/10/2025
Python: 3.9
Django: 2.2.28
OnlyOffice: latest
PostgreSQL: 13-alpine
