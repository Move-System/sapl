# Setup OnlyOffice - Implementação Concluída ✅

## Situação Atual

✅ **Integração OnlyOffice implementada com sucesso!**
✅ **Containers rodando com Python 3.9!**
⚠️ Necessário configurar conexão com banco de dados PostgreSQL

## Problemas Encontrados e Soluções

Várias dependências no `requirements.txt` tinham versões incompatíveis com Python 3.6. As seguintes correções foram aplicadas:

1. ✅ `psycopg2-binary`: 2.9.9 → 2.9.8
2. ✅ `Pillow`: 10.3.0 → 8.4.0
3. ✅ `WeasyPrint`: 66 → 53.4
4. ✅ `reportlab`: 3.6.13 → 3.6.8

## Solução Implementada: Python 3.9 ✅

Foi criado um novo Docker Compose com Python 3.9 que resolve todos os problemas de compatibilidade!

### Arquivos Criados:
- `docker/Dockerfile.dev-py39` - Dockerfile com Python 3.9
- `docker/docker-compose-dev-py39.yml` - Docker Compose atualizado

### Como Usar:

```bash
cd /home/bruno/sapl/docker

# Parar containers antigos (se estiverem rodando)
docker-compose -f docker-compose-dev.yml down

# Subir com Python 3.9
docker-compose -f docker-compose-dev-py39.yml up -d
```

### Portas Utilizadas:
- **8000**: SGVP
- **8002**: OnlyOffice Document Server (alterado de 8001 para evitar conflito)

### Configurar Banco de Dados:

O container está tentando conectar em `postgresql://sapl:sapl@host.docker.internal:5432/sapl`

**Opção 1 - Usar banco existente:**
```bash
# Edite docker-compose-dev-py39.yml e ajuste DATABASE_URL
DATABASE_URL: postgresql://usuario:senha@host:porta/database
```

**Opção 2 - Criar banco PostgreSQL no Docker:**
```bash
# Adicione ao docker-compose-dev-py39.yml:
  postgres:
    image: postgres:13
    container_name: sapl-postgres
    environment:
      POSTGRES_DB: sapl
      POSTGRES_USER: sapl
      POSTGRES_PASSWORD: sapl
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

# Depois altere DATABASE_URL para:
DATABASE_URL: postgresql://sapl:sapl@postgres:5432/sapl
```

## Testando a Integração OnlyOffice

Após os containers subirem com sucesso:

1. **Verifique se o OnlyOffice está rodando**:
   ```bash
   curl http://localhost:8001/welcome/
   ```

   Ou abra no navegador: http://localhost:8001/welcome/

2. **Acesse o SGVP**:
   ```bash
   # Abra no navegador
   http://localhost:8000
   ```

3. **Teste a criação de proposição**:
   - Faça login como um parlamentar/autor
   - Acesse `/proposicao/create`
   - Selecione "Criar com OnlyOffice"
   - Salve a proposição
   - Clique em "Editar com OnlyOffice"

## Arquivos Modificados

Todos os arquivos da integração OnlyOffice foram criados/modificados:

### Novos Arquivos:
- `sapl/materia/onlyoffice_views.py` - Views do OnlyOffice
- `sapl/templates/materia/onlyoffice_editor.html` - Template do editor
- `ONLYOFFICE_INTEGRATION.md` - Documentação completa
- `SETUP_ONLYOFFICE.md` - Este arquivo

### Arquivos Modificados:
- `docker/docker-compose-dev.yml` - Adicionado serviço OnlyOffice
- `sapl/settings.py` - Configurações OnlyOffice
- `sapl/materia/urls.py` - Rotas OnlyOffice
- `sapl/materia/forms.py` - Opção "Criar com OnlyOffice"
- `sapl/templates/materia/proposicao_detail.html` - Botão do editor
- `requirements/requirements.txt` - Dependências ajustadas

## Suporte

Se encontrar problemas:

1. Verifique os logs do Docker:
   ```bash
   docker logs sapl-dev
   docker logs onlyoffice-documentserver
   ```

2. Consulte a documentação completa em `ONLYOFFICE_INTEGRATION.md`

3. Verifique se todas as portas estão disponíveis:
   - 8000: SGVP
   - 8001: OnlyOffice

## Próximos Passos

Após os containers subirem com sucesso:

1. Migrar o banco de dados se necessário
2. Criar um usuário parlamentar de teste
3. Vincular usuário a um autor
4. Testar criação de proposição com OnlyOffice
5. Configurar JWT para produção (opcional)
