# Instruções de Deploy - Módulo TCE

## 📋 Resumo das Alterações

O módulo TCE foi implementado com funcionalidades de:
- Upload e organização de arquivos por processo/pasta/subpasta
- Verificação de tamanho de arquivos (≤5MB)
- Aplicação de OCR (preparado, mas simulado)
- **Assinatura digital com certificado A1 (.pfx)** - IMPLEMENTADO
- Geração de arquivos .p7s
- Visualização de PDFs

## 🔧 Instalação no Servidor de Produção

### 1. Atualizar o Código

```bash
cd /caminho/do/sapl
git pull origin 3.1.x
```

### 2. Instalar Dependências Python

```bash
# Ativar o virtualenv do SGVP (ajuste o caminho conforme necessário)
source /opt/venv/bin/activate  # ou o caminho do seu venv

# Instalar bibliotecas necessárias
pip install pyhanko==0.31.0
pip install pyhanko-certvalidator==0.29.0
pip install cryptography>=43.0.3
```

**OU** use o arquivo requirements:

```bash
pip install -r /caminho/para/tce_requirements.txt
```

### 3. Executar Migrações do Banco de Dados

```bash
python manage.py migrate
```

**Migrações criadas:**
- `0001_initial.py` - Estrutura inicial (TceProcesso, TcePasta, TceArquivo, etc)
- `0002_tcearquivo_subpasta.py` - Campo subpasta em TceArquivo
- `0003_tcepasta_subpastas_customizadas.py` - Campo para subpastas customizadas

### 4. Coletar Arquivos Estáticos

```bash
python manage.py collectstatic --noinput
```

### 5. Criar Diretórios de Upload

```bash
# Criar diretórios para arquivos TCE
mkdir -p /caminho/do/media/tce/arquivos
mkdir -p /caminho/do/media/tce/reduzidos
mkdir -p /caminho/do/media/tce/ocr
mkdir -p /caminho/do/media/tce/assinados
mkdir -p /caminho/do/media/tce/p7s

# Dar permissões adequadas (ajuste o usuário conforme necessário)
chown -R www-data:www-data /caminho/do/media/tce
chmod -R 755 /caminho/do/media/tce
```

### 6. Reiniciar Serviços

```bash
# Para Apache
sudo systemctl restart apache2

# OU para Nginx + Gunicorn/uWSGI
sudo systemctl restart gunicorn  # ou uwsgi
sudo systemctl restart nginx
```

## 📁 Arquivos Criados/Modificados

### Novos Arquivos:

1. **Modelos:**
   - `/sapl/tce/models.py` - Modelos TceProcesso, TcePasta, TceArquivo, TceAssinatura, TceLog

2. **Views:**
   - `/sapl/tce/admin_views.py` - Views e APIs do módulo TCE

3. **URLs:**
   - `/sapl/tce/urls.py` - Rotas do módulo

4. **Templates:**
   - `/sapl/templates/admin/tce/admin_index.html` - Dashboard TCE
   - `/sapl/templates/admin/tce/processo_detail.html` - Detalhes do processo
   - `/sapl/templates/admin/tce/subpasta_detail.html` - Detalhes da subpasta (com wizard de upload)
   - `/sapl/templates/admin/tce/change_form.html` - Formulário admin
   - `/sapl/templates/admin/tce/change_list.html` - Lista admin
   - `/sapl/templates/admin/tce/app_index.html` - Índice do app

5. **Template Filters:**
   - `/sapl/tce/templatetags/tce_filters.py` - Filtros customizados

6. **Migrações:**
   - `/sapl/tce/migrations/0001_initial.py`
   - `/sapl/tce/migrations/0002_tcearquivo_subpasta.py`
   - `/sapl/tce/migrations/0003_tcepasta_subpastas_customizadas.py`

### Arquivos Modificados:

1. `/sapl/templates/admin/base_site.html` - Navbar do SGVP no admin

## 🔐 Configurações de Segurança

### Permissões de Arquivos

```python
# Em settings.py, verificar:
MEDIA_ROOT = '/caminho/do/media'
MEDIA_URL = '/media/'

# Limite de upload (opcional)
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
```

### Configuração do Servidor Web

**Para Apache (.htaccess ou VirtualHost):**

```apache
# Permitir upload de arquivos PDF e certificados
<Directory /caminho/do/media/tce>
    Options -Indexes
    AllowOverride None
    Require all granted

    # Apenas permitir acesso a arquivos específicos
    <FilesMatch "\.(pdf|p7s)$">
        Require all granted
    </FilesMatch>
</Directory>
```

**Para Nginx:**

```nginx
location /media/tce/ {
    alias /caminho/do/media/tce/;

    # Apenas permitir download de PDFs e p7s
    location ~ \.(pdf|p7s)$ {
        add_header Content-Disposition "inline";
    }

    # Bloquear acesso a outros arquivos
    location ~ \.(pfx|p12)$ {
        deny all;
    }
}
```

## 🧪 Testar a Instalação

### 1. Verificar se as bibliotecas foram instaladas:

```bash
python -c "from pyhanko.sign import signers; print('✓ PyHanko OK')"
python -c "from pyhanko_certvalidator import ValidationContext; print('✓ Certvalidator OK')"
```

### 2. Acessar o módulo:

```
http://seu-servidor.com/tce/admin/
```

### 3. Testar funcionalidades:

1. **Criar um processo** - Dashboard TCE > Novo Processo
2. **Criar pastas/subpastas** - Dentro do processo
3. **Upload de arquivo** - Com wizard de 5 abas
4. **Assinatura digital** - Na aba 4 do wizard (requer certificado .pfx)
5. **Geração .p7s** - Na aba 5 do wizard

## ⚠️ Problemas Conhecidos e Soluções

### Erro: "Biblioteca de assinatura não instalada"

**Solução:**
```bash
pip install pyhanko pyhanko-certvalidator
sudo systemctl restart gunicorn  # ou seu servidor WSGI
```

### Erro de permissão ao fazer upload

**Solução:**
```bash
chown -R www-data:www-data /caminho/do/media/tce
chmod -R 755 /caminho/do/media/tce
```

### Erro 404 ao visualizar arquivo

**Solução:**
Verificar se a rota está registrada em `urls.py`:
```python
path('arquivo/<uuid:arquivo_id>/visualizar/', admin_views.visualizar_arquivo, name='visualizar_arquivo'),
```

### JSONField não encontrado (Django < 3.1)

O código já está preparado com fallback:
```python
try:
    from django.db.models import JSONField
except ImportError:
    from django.contrib.postgres.fields import JSONField
```

## 📊 Monitoramento

### Logs para verificar:

```bash
# Logs do Django
tail -f /var/log/sapl/django.log

# Logs do servidor web
tail -f /var/log/apache2/error.log  # Apache
tail -f /var/log/nginx/error.log    # Nginx
```

### Verificar uploads:

```bash
ls -lah /caminho/do/media/tce/arquivos/
ls -lah /caminho/do/media/tce/assinados/
ls -lah /caminho/do/media/tce/p7s/
```

## 🔄 Rollback (se necessário)

Se precisar reverter as alterações:

```bash
# Reverter migrações
python manage.py migrate tce 0000_initial  # ou zero

# Reverter código
git revert <commit_hash>
git push
```

## 📞 Suporte

Em caso de dúvidas ou problemas:

1. Verificar logs do servidor
2. Testar em ambiente de desenvolvimento primeiro
3. Verificar se todas as dependências foram instaladas
4. Confirmar permissões de arquivos e diretórios

---

**Data de criação:** 03/10/2025
**Versão do SGVP:** 3.1.x
**Última atualização:** Após merge com branch principal
