# ⚡ Teste Rápido OnlyOffice - 5 Minutos

## 🎯 Objetivo
Testar a criação de uma proposição usando o editor OnlyOffice integrado.

---

## ✅ Pré-requisitos (Verificar)

```bash
cd /home/bruno/sapl/docker

# Verificar se os containers estão rodando
docker ps | grep -E "sapl-dev|onlyoffice|sapl-postgres"
```

Você deve ver 3 containers rodando:
- `sapl-dev`
- `onlyoffice-documentserver`
- `sapl-postgres`

---

## 🚀 Passo a Passo

### 1️⃣ Criar Autor (OBRIGATÓRIO - Só precisa fazer uma vez)

Execute este script para criar automaticamente:

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

    # Criar Autor
    tipo = TipoAutor.objects.filter(descricao='Parlamentar').first()
    autor = Autor.objects.create(
        tipo=tipo,
        nome='Admin',
        parlamentar=p
    )

    # Vincular usuário ao autor
    user = User.objects.get(username='admin')
    autor.operadores.add(user)

    # Adicionar ao grupo Autor
    grupo_autor = Group.objects.get(name='Autor')
    user.groups.add(grupo_autor)

    print('✅ Autor criado e vinculado com sucesso!')
else:
    print('⚠️  Autor já existe')
"
```

### 2️⃣ Acessar o SAPL

1. Abra o navegador: **http://localhost:8000/login**
2. Faça login:
   - **Usuário**: `admin`
   - **Senha**: `admin`

### 3️⃣ Criar Proposição

1. Acesse: **http://localhost:8000/proposicao/create**

2. Preencha:
   - **Tipo**: Selecione qualquer tipo (ex: "Projeto de Lei")
   - **Ementa**: "Teste de integração OnlyOffice"
   - **Tipo do Texto da Proposição**: **"Criar com OnlyOffice"** ⭐

3. Clique em **"Salvar"**

### 4️⃣ Abrir Editor OnlyOffice

1. Após salvar, você será redirecionado para a página da proposição

2. Clique no botão **"Editar com OnlyOffice"** (azul)

3. O editor OnlyOffice abrirá no navegador! 🎉

### 5️⃣ Testar Edição

1. **Digite** algum texto no editor

2. **Teste** as funcionalidades:
   - Negrito, itálico, sublinhado
   - Listas numeradas
   - Tabelas
   - Cores de texto

3. **Aguarde** ~3 segundos (salvamento automático)

4. **Feche** a aba do editor

5. **Recarregue** a página da proposição

6. **Clique** em "Texto Original" para ver o documento salvo!

---

## 🎬 Comandos Completos (Copiar e Colar)

```bash
# 1. Ir para o diretório do Docker
cd /home/bruno/sapl/docker

# 2. Verificar containers
docker ps | grep -E "sapl|onlyoffice|postgres"

# 3. Criar autor (copie todo o comando abaixo)
docker exec sapl-dev python manage.py shell -c "
from sapl.parlamentares.models import Parlamentar
from sapl.base.models import Autor, TipoAutor
from django.contrib.auth.models import User, Group

if not Parlamentar.objects.filter(nome_parlamentar='Admin').exists():
    p = Parlamentar.objects.create(
        nome_completo='Administrador Sistema',
        nome_parlamentar='Admin',
        ativo=True
    )
    tipo = TipoAutor.objects.filter(descricao='Parlamentar').first()
    autor = Autor.objects.create(tipo=tipo, nome='Admin', parlamentar=p)
    user = User.objects.get(username='admin')
    autor.operadores.add(user)
    grupo_autor = Group.objects.get(name='Autor')
    user.groups.add(grupo_autor)
    print('✅ Autor criado!')
else:
    print('⚠️  Autor já existe')
"

# 4. Abrir navegador (Linux/WSL)
xdg-open http://localhost:8000/login 2>/dev/null || echo "Abra manualmente: http://localhost:8000/login"
```

---

## ❗ Problemas Comuns

### "Você não tem permissão para criar proposição"

**Solução**: Execute o script de criação de autor (Passo 1)

### "OnlyOffice não carrega"

**Verificar**:
```bash
# OnlyOffice está rodando?
docker ps | grep onlyoffice

# Acessível?
curl http://localhost:8002/welcome/
```

### "Erro ao salvar documento"

**Verificar logs**:
```bash
docker logs sapl-dev -f
docker logs onlyoffice-documentserver -f
```

---

## 📸 Como Deve Parecer

### Tela de Criação
- Campo "Tipo do Texto da Proposição" deve ter 3 opções:
  - Arquivo Digital
  - Texto Articulado
  - **Criar com OnlyOffice** ⭐

### Página da Proposição
- Deve ter botão azul: **"Editar com OnlyOffice"**

### Editor OnlyOffice
- Interface similar ao Microsoft Word
- Barra de ferramentas completa
- Área de edição de texto

---

## ✅ Checklist de Sucesso

- [ ] Containers rodando (3 containers)
- [ ] Login funcionando (admin/admin)
- [ ] Autor criado e vinculado
- [ ] Proposição criada com opção OnlyOffice
- [ ] Editor OnlyOffice abre no navegador
- [ ] Consegue editar o texto
- [ ] Documento salva automaticamente
- [ ] Texto Original disponível para download

---

## 🎉 Sucesso!

Se todos os passos funcionarem, a integração OnlyOffice está **100% funcional**!

---

**Tempo estimado**: 5 minutos
**Dificuldade**: Fácil
**Pré-requisitos**: Docker rodando
