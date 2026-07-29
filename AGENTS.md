# AGENTS.md

## Fonte oficial de conhecimento (knowledge/) — leia antes de qualquer tarefa

Este repositório consome o Knowledge Workspace da Move System como **submodule em `knowledge/`**.
Pasta vazia? `git submodule update --init`. Docs novas? `git -C knowledge pull origin main`.

Este repo pertence ao produto **SAPL (fork Interlegis, rebrandeado SGVP)** e roda na stack **Python 3.12 + Django 2.2**.
A ordem de leitura obrigatória está em `knowledge/AGENTS.md`. Atalhos:

- `knowledge/governance/indexes/Mapa_Repos_Produtos.md` — o mapa dos 7 repositórios
- `knowledge/engineering/stacks/stack-django-python.md` — convenções DESTA stack (não aplique padrão de outra)
- `knowledge/domain/Glossario_Legislativo.md` — obrigatório antes de mexer em proposição/matéria/protocolo/tramitação
- `knowledge/governance/knowledge-architecture/Dicionario_Siglas.md` — siglas (ADR, PRD, spec…)

### Regras anti-alucinação (Claude Code, Codex, Cursor — qualquer agente)

1. **Não invente** regra de negócio, contrato de API, endpoint, campo ou nome de entidade: verifique no `knowledge/` e no código antes de afirmar.
2. Não encontrou nem na doc nem no código? **Diga "não está documentado" e pergunte** — nunca presuma.
3. Toda decisão relevante **cita o documento que a governou** (ADR, spec, glossário) — princípio de honestidade epistêmica da `knowledge/ai-framework/constitution/AI_Constitution.md`.
4. Conflito entre doc local deste repo e o `knowledge/`? **O `knowledge/` prevalece** — sinalize a divergência em vez de escolher em silêncio.
5. Decisão nova tomada durante a tarefa → **registrar no `knowledge/`** (ADR ou spec), não só no código.


Convenções completas do repositório: ver `CLAUDE.md` (se existir) e o perfil de stack no `knowledge/`.
