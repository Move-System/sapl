# Skill: Mapear Estrutura do Projeto

Esta skill analisa e documenta a estrutura completa do projeto atual, gerando um arquivo de referência arquitetural.

## Instruções de Execução

### 1. Análise Inicial
Execute os seguintes comandos para mapear o projeto:

```bash
# Nome do projeto (baseado no diretório)
basename $(pwd)

# Detectar tecnologias
ls -la | head -20
```

### 2. Detectar Tecnologias
Verifique a existência dos seguintes arquivos para identificar as tecnologias:
- `package.json` → Node.js/JavaScript
- `composer.json` → PHP/Laravel
- `requirements.txt` ou `Pipfile` ou `pyproject.toml` → Python
- `Gemfile` → Ruby
- `go.mod` → Go
- `Cargo.toml` → Rust
- `Dockerfile` ou `docker-compose.yml` → Docker
- `manage.py` → Django
- `settings.py` no diretório principal → Django
- `artisan` → Laravel

### 3. Mapear Estrutura de Diretórios
Use o comando tree ou find para mapear toda a estrutura:

```bash
# Estrutura completa (excluindo node_modules, __pycache__, .git, venv, etc.)
find . -type d \( -name "node_modules" -o -name "__pycache__" -o -name ".git" -o -name "venv" -o -name ".venv" -o -name "vendor" -o -name ".tox" -o -name "*.egg-info" -o -name "build" -o -name "dist" -o -name ".pytest_cache" -o -name ".mypy_cache" \) -prune -o -type f -print | head -500
```

### 4. Identificar Componentes Principais
Procure pelos seguintes padrões:

**Backend:**
- Controllers/Views: `**/controllers/**`, `**/views/**`, `**/api/**`
- Models: `**/models/**`, `**/entities/**`
- Services: `**/services/**`, `**/usecases/**`
- Repositories: `**/repositories/**`, `**/dao/**`
- Migrations: `**/migrations/**`, `**/database/migrations/**`
- Routes: `**/routes/**`, `**/urls.py`, `routes/web.php`
- Middleware: `**/middleware/**`
- Jobs/Tasks: `**/jobs/**`, `**/tasks/**`, `**/celery/**`

**Frontend:**
- Components: `**/components/**`, `**/src/components/**`
- Pages: `**/pages/**`, `**/views/**`
- Stores: `**/stores/**`, `**/store/**`, `**/redux/**`
- Assets: `**/assets/**`, `**/static/**`, `**/public/**`
- Styles: `**/styles/**`, `**/css/**`, `**/scss/**`

**Infraestrutura:**
- Config: `**/config/**`, `**/settings/**`
- Docker: `Dockerfile`, `docker-compose*.yml`
- CI/CD: `.github/workflows/**`, `.gitlab-ci.yml`, `Jenkinsfile`
- Environment: `.env*`, `*.env`

### 5. Gerar Arquivo de Estrutura

Crie o arquivo `.claude/context/estrutura-projeto.md` com o seguinte formato:

```markdown
# Estrutura do Projeto: [NOME_DO_PROJETO]

> Última atualização: [DATA_ATUAL]

## Tecnologias Detectadas
- [Lista de tecnologias identificadas]

## Árvore de Diretórios
[Estrutura em formato tree]

## Organização das Pastas Principais

### Backend
[Descrição da organização do backend]

### Frontend
[Descrição da organização do frontend]

### Infraestrutura
[Descrição dos arquivos de infra]

## Fluxo do Backend
[Explicar: rotas → controllers → services → repositories → models]

## Fluxo do Frontend
[Explicar: páginas → componentes → stores → libs]

## Microserviços
[Se existirem, descrever a organização]

## Pontos Críticos
[Listar pontos de atenção no projeto]

## Sugestões de Organização
[Se aplicável, sugerir melhorias]
```

### 6. Finalização
Após gerar o arquivo, exiba a mensagem:

**"Estrutura atualizada. Todas as skills já podem usar este arquivo como referência arquitetural."**

---

## Notas Importantes

- Esta skill SEMPRE sobrescreve o arquivo anterior
- O arquivo gerado serve como "cérebro estrutural" para outras skills
- Outras skills devem ler `.claude/context/estrutura-projeto.md` antes de criar módulos ou fazer alterações
- Mantenha o arquivo atualizado executando esta skill periodicamente
