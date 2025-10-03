# Módulo TCE - Tribunal de Contas

Módulo completo para integração com o Tribunal de Contas (TCE), implementado conforme especificação funcional e técnica.

## 📋 Funcionalidades Implementadas

### 1. Gestão de Processos TCE
- ✅ Criação e gerenciamento de processos
- ✅ Controle de status (rascunho → validação → pronto para envio → enviado → devolvido → concluído)
- ✅ Gestão de prazos e calendário
- ✅ Dashboard executivo com métricas

### 2. Documentos
- ✅ Upload e versionamento de documentos
- ✅ Validação de formato PDF/A
- ✅ Cálculo de hash SHA-256 para integridade
- ✅ Classificação e metadados
- ✅ Controle de documento principal

### 3. Assinaturas Digitais
- ✅ Suporte a múltiplos signatários
- ✅ Políticas PAdES (B, LT, LTA)
- ✅ Controle de ordem de assinatura
- ✅ Validação de certificados ICP-Brasil (estrutura pronta)
- ✅ Timestamp (TSA)

### 4. Validações Automáticas
- ✅ Validação de PDF/A (estrutura pronta para integração com veraPDF)
- ✅ Validação de metadados obrigatórios
- ✅ Validação de nomeação de arquivos
- ✅ Checklist de conformidade

### 5. Pendências e Devolutivas
- ✅ Recepção de pendências do TCE
- ✅ Classificação por criticidade
- ✅ Gestão de SLA e prazos
- ✅ Quadro Kanban de situações
- ✅ Controle de atrasos

### 6. Envio ao TCE
- ✅ Registro de envios com protocolo
- ✅ Controle de tentativas
- ✅ Recibos e confirmações
- ✅ Logs detalhados

### 7. Linha do Tempo
- ✅ Auditoria completa de eventos
- ✅ Registro de IP e usuário
- ✅ Metadados de ações

### 8. Calendário TCE
- ✅ Eventos e prazos legais
- ✅ Sessões e marcos
- ✅ Eventos recorrentes

## 🏗️ Estrutura do Módulo

```
sapl/tce/
├── __init__.py
├── apps.py              # Configuração do app
├── models.py            # 7 models principais
├── serializers.py       # Serializers DRF
├── views.py             # ViewSets e endpoints
├── urls.py              # Rotas da API
├── admin.py             # Interface administrativa
├── utils.py             # Utilitários de validação
├── migrations/          # Migrations do banco
└── templates/tce/       # Templates (a implementar)
```

## 📊 Modelos de Dados

### TceProcesso
Processo principal com controle de status, prazos e metadados.

### TceDocumento
Documentos anexados com validação PDF/A, hash e versões.

### TceAssinatura
Assinaturas digitais ICP-Brasil com políticas PAdES.

### TcePendencia
Pendências e devolutivas do TCE com gestão de SLA.

### TceEvento
Linha do tempo completa de auditoria.

### TceCalendario
Calendário de prazos e eventos do TCE.

### TceEnvio
Registro de envios com protocolos e recibos.

## 🔌 API REST

Todas as rotas estão disponíveis em `/tce/api/`:

### Processos
- `GET /tce/api/processos/` - Lista processos (com filtros)
- `POST /tce/api/processos/` - Cria processo
- `GET /tce/api/processos/{id}/` - Detalhe do processo
- `PUT/PATCH /tce/api/processos/{id}/` - Atualiza processo
- `GET /tce/api/processos/dashboard/` - Dashboard com métricas
- `POST /tce/api/processos/{id}/validar/` - Valida processo
- `POST /tce/api/processos/{id}/enviar/` - Envia ao TCE
- `POST /tce/api/processos/{id}/receber_devolutiva/` - Webhook para devolutivas

### Documentos
- `GET /tce/api/documentos/` - Lista documentos
- `POST /tce/api/documentos/` - Upload de documento
- `POST /tce/api/documentos/{id}/validar_pdfa/` - Valida PDF/A

### Pendências
- `GET /tce/api/pendencias/` - Lista pendências
- `POST /tce/api/pendencias/{id}/resolver/` - Resolve pendência

### Outros Endpoints
- `/tce/api/assinaturas/` - Gestão de assinaturas
- `/tce/api/eventos/` - Eventos (read-only)
- `/tce/api/calendario/` - Calendário TCE
- `/tce/api/envios/` - Envios (read-only)

## 🔧 Configuração

### 1. Registrar no settings.py
```python
SAPL_APPS = (
    ...
    'sapl.tce',
)
```

### 2. Registrar URLs
```python
# sapl/urls.py
import sapl.tce.urls

urlpatterns = [
    ...
    url(r'^tce/', include(sapl.tce.urls)),
]
```

### 3. Criar migrations e aplicar
```bash
python manage.py makemigrations tce
python manage.py migrate tce
```

### 4. Variáveis de Ambiente (opcional)
```bash
# .env
TCE_ENDPOINT=https://tce.exemplo.gov.br/api/processos
TCE_TOKEN=seu_token_aqui
TCE_CALENDAR_ICS_URL=https://tce.exemplo.gov.br/calendario.ics
PDFA_ENFORCE=true
P7S_POLICY=PAdES-LT
TSA_URL=https://tsa.exemplo.gov.br
OCSP_CRL_CHECK=true
```

## 🧪 Utilização

### Criar um processo
```python
from sapl.tce.models import TceProcesso

processo = TceProcesso.objects.create(
    numero_interno='PROC-001-2025',
    assunto='Prestação de Contas 2024',
    tipo='contas',
    exercicio=2024,
    unidade_gestora='Secretaria de Finanças',
    responsavel=user
)
```

### Upload de documento
```python
from sapl.tce.models import TceDocumento

documento = TceDocumento.objects.create(
    processo=processo,
    nome_arquivo='CONTAS_2024_v1.pdf',
    arquivo=uploaded_file,
    tipo_documento='principal',
    principal=True
)
```

### Validar processo
```python
from sapl.tce.utils import validar_processo

resultado = validar_processo(processo)
if resultado['valido']:
    processo.status = 'pronto_envio'
    processo.save()
```

### Enviar ao TCE
```python
from sapl.tce.utils import enviar_processo_tce

resultado = enviar_processo_tce(processo, usuario=request.user)
if resultado['sucesso']:
    print(f"Protocolo: {resultado['protocolo']}")
```

## 📝 Interface Administrativa

Acesse `/admin/tce/` para gerenciar:
- Processos TCE
- Documentos
- Assinaturas
- Pendências
- Eventos (auditoria)
- Calendário
- Envios

## 🚀 Próximos Passos

### Integrações Recomendadas

1. **PDF/A Validation**
   - Integrar com [veraPDF](https://verapdf.org/)
   - Implementar validação completa de perfis PDF/A

2. **Assinaturas Digitais**
   - Integrar com [PyHanko](https://github.com/MatthiasValvekens/pyHanko)
   - Implementar verificação de cadeia ICP-Brasil
   - Validação OCSP/CRL

3. **Tasks Assíncronas**
   - Implementar filas Celery/Django-Q
   - Validação em background
   - Envios assíncronos

4. **Frontend/Templates**
   - Dashboard interativo
   - Quadro Kanban de pendências
   - Calendário visual
   - Upload drag-and-drop

5. **Relatórios**
   - Exportação em PDF/XLSX
   - Gráficos de evolução
   - Relatórios por unidade gestora

## ⚠️ Observações

### Implementações Simplificadas (Produção)

Algumas funcionalidades estão com implementação simplificada e devem ser integradas em produção:

1. **Validação PDF/A**: Estrutura pronta, requer integração com veraPDF
2. **Assinaturas Digitais**: Estrutura pronta, requer PyHanko para validação completa
3. **Envio ao TCE**: Implementado com simulação, requer integração com API real do TCE
4. **Verificação ICP-Brasil**: Estrutura pronta, requer bibliotecas de criptografia

### Segurança

- ✅ Controle de permissões via Django permissions
- ✅ Auditoria completa de ações
- ✅ Hash SHA-256 para integridade
- ⚠️ Implementar rate limiting para API
- ⚠️ Validação de certificados com HSM/A3

## 📚 Documentação de Referência

- Especificação completa: `modulo_tribunal_de_contas_tce_especificacao_funcional_e_tecnica.md`
- Django REST Framework: https://www.django-rest-framework.org/
- veraPDF: https://verapdf.org/
- PyHanko: https://github.com/MatthiasValvekens/pyHanko

## 🤝 Contribuindo

Para contribuir com o módulo TCE:

1. Seguir os padrões de código do SAPL
2. Adicionar testes unitários
3. Documentar novas funcionalidades
4. Manter compatibilidade com a API REST

## 📄 Licença

Este módulo segue a mesma licença do projeto SAPL.
