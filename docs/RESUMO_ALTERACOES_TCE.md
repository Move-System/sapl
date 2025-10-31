# Resumo das Alterações - Módulo TCE

## 🎯 O que foi implementado

Sistema completo de gestão de documentos para prestação de contas ao TCE (Tribunal de Contas do Estado) com:

### Funcionalidades Principais:
1. ✅ **Gestão de Processos** - Criar processos por período (trimestral, anual, etc)
2. ✅ **Organização em Pastas** - 3 categorias padrão + pastas customizadas
3. ✅ **Subpastas Dinâmicas** - Estrutura hierárquica com subpastas customizáveis
4. ✅ **Upload com Wizard** - 5 etapas para preparação de documentos
5. ✅ **Verificação de Tamanho** - Validação ≤5MB
6. ✅ **OCR** - Preparado (simulado no frontend)
7. ✅ **Assinatura Digital Real** - Com certificado A1 (.pfx) usando PyHanko
8. ✅ **Geração .p7s** - Arquivo de assinatura destacada
9. ✅ **Visualização de PDFs** - Inline no navegador
10. ✅ **Logs e Auditoria** - Rastreamento completo de ações

---

## 📦 Para o Servidor de Produção

### **Comando Rápido (Instalação Automática):**

```bash
cd /caminho/do/sapl
./scripts/install_tce_module.sh
```

### **OU Manual:**

```bash
# 1. Atualizar código
git pull origin 3.1.x

# 2. Ativar virtualenv
source /opt/venv/bin/activate

# 3. Instalar dependências
pip install pyhanko==0.31.0 pyhanko-certvalidator==0.29.0

# 4. Migrar banco
python manage.py migrate

# 5. Criar diretórios
mkdir -p media/tce/{arquivos,assinados,p7s,ocr,reduzidos}
chown -R www-data:www-data media/tce
chmod -R 755 media/tce

# 6. Coletar estáticos
python manage.py collectstatic --noinput

# 7. Reiniciar serviço
sudo systemctl restart gunicorn  # ou apache2/nginx
```

---

## 🔑 Dependências NOVAS Instaladas

### Python:
- ✅ `pyhanko==0.31.0` - Assinatura digital de PDFs
- ✅ `pyhanko-certvalidator==0.29.0` - Validação de certificados
- ✅ `cryptography>=43.0.3` - Criptografia
- ✅ `tzlocal>=5.0.0` - Timezone
- ✅ `uritools>=5.0.0` - Manipulação de URIs

### Frontend (CDN):
- ✅ Font Awesome 6.5.1 - Ícones
- ✅ SweetAlert2 - Alertas modernos
- ✅ Bootstrap (já existente) - UI

---

## 📁 Arquivos Principais Criados

### Backend:
```
sapl/tce/
├── models.py                    # 5 modelos (Processo, Pasta, Arquivo, Assinatura, Log)
├── admin_views.py               # 10+ views e APIs
├── urls.py                      # Rotas do módulo
├── admin.py                     # Admin Django
└── migrations/
    ├── 0001_initial.py
    ├── 0002_tcearquivo_subpasta.py
    └── 0003_tcepasta_subpastas_customizadas.py
```

### Frontend:
```
sapl/templates/admin/tce/
├── admin_index.html             # Dashboard principal
├── processo_detail.html         # Detalhes do processo
├── subpasta_detail.html        # Upload wizard (5 abas)
├── change_form.html            # Formulário admin
├── change_list.html            # Lista admin
└── app_index.html              # Índice do app
```

### Template Filters:
```
sapl/tce/templatetags/
└── tce_filters.py              # Filtros customizados
```

---

## 🔄 Migrações do Banco de Dados

### 3 Migrações Criadas:

1. **0001_initial** - Estrutura base:
   - TceProcesso (processos TCE)
   - TcePasta (categorias/pastas)
   - TceArquivo (arquivos PDF/XML)
   - TceAssinatura (assinaturas digitais)
   - TceLog (auditoria)

2. **0002_tcearquivo_subpasta** - Campo para subpastas

3. **0003_tcepasta_subpastas_customizadas** - Subpastas customizadas (JSON em TextField)

### Executar:
```bash
python manage.py migrate tce
```

---

## 🌐 URLs Adicionadas

```python
/tce/admin/                                    # Dashboard
/tce/processo/<uuid>/                          # Detalhes do processo
/tce/processo/<uuid>/pasta/<uuid>/<subpasta>/ # Detalhes da subpasta
/tce/arquivo/<uuid>/visualizar/                # Visualizar PDF
/tce/api/arquivos/upload/                      # Upload
/tce/api/arquivos/<uuid>/assinar/              # Assinar
/tce/api/arquivos/<uuid>/gerar-p7s/            # Gerar .p7s
/tce/api/arquivos/<uuid>/delete/               # Deletar
/tce/api/pastas/criar/                         # Criar pasta
/tce/api/subpastas/adicionar/                  # Adicionar subpasta
```

---

## ✅ Checklist de Deploy

- [ ] Git pull executado
- [ ] Dependências Python instaladas (`pyhanko`, `pyhanko-certvalidator`)
- [ ] Migrações executadas (`python manage.py migrate`)
- [ ] Diretórios de mídia criados (`media/tce/`)
- [ ] Permissões configuradas (755, owner www-data)
- [ ] Arquivos estáticos coletados (`collectstatic`)
- [ ] Servidor web reiniciado
- [ ] Teste de acesso: `http://servidor/tce/admin/`
- [ ] Teste de upload de arquivo
- [ ] Teste de assinatura digital (com certificado .pfx)

---

## 🧪 Como Testar

1. **Acessar:** `http://seu-servidor/tce/admin/`
2. **Criar processo:** Clicar em "Novo Processo TCE"
3. **Entrar no processo:** Ver pastas e subpastas
4. **Upload:** Clicar em "Adicionar Arquivos" em uma subpasta
5. **Wizard (5 abas):**
   - Aba 1: Selecionar PDF
   - Aba 2: Verificar tamanho
   - Aba 3: Aplicar OCR (simulado)
   - Aba 4: **Assinar digitalmente** (usar certificado .pfx + senha)
   - Aba 5: Gerar .p7s
6. **Finalizar:** Arquivo aparece na lista
7. **Visualizar:** Clicar no ícone 👁️ para ver o PDF assinado

---

## 🚨 Problemas Comuns

### "Biblioteca de assinatura não instalada"
```bash
pip install pyhanko pyhanko-certvalidator
sudo systemctl restart gunicorn
```

### Erro de permissão ao fazer upload
```bash
chown -R www-data:www-data /caminho/do/media/tce
chmod -R 755 /caminho/do/media/tce
```

### Arquivo não aparece após upload
- Verificar logs: `/var/log/sapl/` ou `/var/log/apache2/error.log`
- Verificar se diretórios existem: `ls -la media/tce/`
- Verificar se migrações foram aplicadas: `python manage.py showmigrations tce`

---

## 📊 Estrutura de Dados

### Hierarquia:
```
TceProcesso (Prestação de Contas - 3º Tri/2025)
  └── TcePasta (Gestão Administrativa)
      └── Subpasta (Atos de pessoal)
          └── TceArquivo (documento.pdf)
              ├── arquivo_assinado.pdf
              ├── documento.p7s
              └── TceAssinatura (dados do certificado)
```

### Campos Principais:

**TceProcesso:**
- titulo, ano, periodo, status
- numero_protocolo (TCE)
- data_envio, recibo_tce

**TceArquivo:**
- arquivo (original)
- arquivo_assinado (com assinatura)
- arquivo_p7s (destacado)
- tamanho_ok, ocr_ok, assinado, p7s_gerado
- certificado_info (JSON)

---

## 📝 Logs e Monitoramento

### Verificar logs:
```bash
# Django
tail -f /var/log/sapl/django.log

# Servidor web
tail -f /var/log/apache2/error.log  # ou nginx/error.log

# Verificar uploads
ls -lah media/tce/arquivos/
ls -lah media/tce/assinados/
```

### Django shell:
```python
python manage.py shell

from sapl.tce.models import *

# Ver processos
TceProcesso.objects.all()

# Ver arquivos
TceArquivo.objects.all()

# Ver assinaturas
TceAssinatura.objects.all()
```

---

## 📞 Documentação Completa

- 📄 `INSTRUCOES_DEPLOY_TCE.md` - Instruções detalhadas
- 🔧 `scripts/install_tce_module.sh` - Script de instalação automática
- 📋 `RESUMO_ALTERACOES_TCE.md` - Este arquivo

---

**Desenvolvido em:** Outubro/2025
**Branch:** 3.1.x
**Status:** ✅ Pronto para produção
