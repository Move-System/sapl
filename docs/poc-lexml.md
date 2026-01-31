# POC do provedor LexML no SGVP (explicado de forma simples)

Pense no LexML como uma grande biblioteca que quer receber copias digitais das leis que voce publica no SGVP. O SGVP ja fala esse idioma (OAI-PMH); basta preencher alguns formularios e mostrar o endereco certo para o coletor do LexML.

## Escopo rapido da POC
- SGVP entrega dados em formato LexML sem programacao extra.
- Basta preencher dados da Casa, cadastrar provedor/publicador e ter ao menos uma norma.
- Endpoint `.../sistema/lexml/oai` responde aos verbos `Identify` e `ListRecords`.

## Quem e quem (em termos bem simples)
- **SGVP**: o site da Casa que guarda as normas.
- **LexML**: a biblioteca nacional que vai buscar os dados.
- **Casa Legislativa**: dados institucionais (nome, cidade, UF, site, email).
- **Tipo de Norma**: o "tipo de livro" (lei, resolucao, regimento etc.).
- **Norma Juridica**: o "livro" com numero, ano, data, texto e resumo.
- **Provedor / Publicador**: cartoes de visita fornecidos pelo time do LexML (ids e XML).

## Preparacao do ambiente
- SGVP 3.1+ rodando (dev ou staging). Exemplos: `./manage.py runserver 0.0.0.0:8000` ou `docker-compose -f dist/docker-compose.yml up -d`.
- Dependencias instaladas: `pip install -r requirements/requirements.txt`.
- Banco migrado e usuario administrador ativo.
- `Casa Legislativa.endereco_web` e o host usado nos identificadores; configure o mesmo host em `ALLOWED_HOSTS` e nos testes do navegador.

## Implantacao passo a passo (modo receita)
1) **Suba o SGVP**: escolha execucao local ou container e confirme acesso ao admin.  
2) **Casa Legislativa**: em `Sistema -> Casa Legislativa`, preencha nome, sigla, municipio, UF, endereco_web e email.  
3) **Esfera Federacao**: em `Sistema -> Parametros -> Configuracoes da Aplicacao`, escolha `M` (Municipal) ou `E` (Estadual).  
4) **Tipos de Norma Juridica**: em `Tabelas Auxiliares -> Norma Juridica -> Tipo de Norma Juridica`, ajuste o campo `Equivalente LexML` (ex.: `lei`, `lei.organica`, `resolucao`, `regimento.interno`).  
5) **Norma Juridica de exemplo**: cadastre ao menos uma norma com `numero`, `ano`, `data`, `esfera_federacao`, tipo com equivalente LexML, `ementa` e, se possivel, `texto_integral` (PDF ou DOC). O formulario grava `timestamp` automaticamente; para dados antigos, abra e salve de novo.  
6) **Provedor**: em `Sistema -> LexML -> Provedor`, preencha `id_provedor`, `nome`, responsavel, email e cole o XML que o LexML enviou. O SGVP valida contra `sapl/templates/lexml/schema.xsd` e aponta erros de schema.  
7) **Publicador**: em `Sistema -> LexML -> Publicador`, preencha `id_publicador`, `nome`, `sigla`, `tipo` e responsavel.  
8) **Teste interno**: acesse `http://localhost:8000/sistema/lexml/oai?verb=Identify` e `ListRecords` (com `metadataPrefix=oai_lexml`) para ver se a resposta chega em XML.  
9) **Compartilhe a baseURL**: envie ao time LexML o `baseURL` gerado (o mesmo usado no XML de provedor) para que eles habilitem o coletor externo.

## XML de exemplo (ajuste IDs e dominio)
```xml
<ConfiguracaoProvedor dataGeracao="2024-01-01T00:00:00">
  <Provedor idProvedor="123" nome="Camara Exemplo" tipo="Provedor" baseURL="https://seu.dominio/sistema/lexml/oai">
    <Administrador idResponsavel="1" email="contato@dominio.gov.br"/>
    <Publicador idPublicador="456" nome="Camara Exemplo" sigla="CE">
      <Responsavel idResponsavel="1" email="contato@dominio.gov.br"/>
      <Perfil localidade="BR;DF;Brasilia"/>
    </Publicador>
  </Provedor>
  <RepositorioOAILexML baseURL="https://www.lexml.gov.br/oai"/>
  <RepositorioOAILexML baseURL="https://seu.dominio/sistema/lexml/oai"/>
  <RepositorioOAILexML baseURL="https://seu.dominio/sistema/oai"/>
  <RepositorioOAILexML baseURL="https://seu.dominio/oai"/>
  <RepositorioOAILexML baseURL="http://seu.dominio/sistema/lexml/oai"/>
</ConfiguracaoProvedor>
```

## Comandos para testar e demonstrar
- Identify: `curl "http://localhost:8000/sistema/lexml/oai?verb=Identify"`
- ListRecords (padrao): `curl "http://localhost:8000/sistema/lexml/oai?verb=ListRecords&metadataPrefix=oai_lexml&batch_size=10"`
- ListRecords filtrando por data: `curl "http://localhost:8000/sistema/lexml/oai?verb=ListRecords&metadataPrefix=oai_lexml&from=2023-01-01T00:00:00Z&batch_size=50"`

O que aparece no `ListRecords`:
- `Item` com link do conteudo (PDF/HTML) e outro `Item` para o metadado.
- `DocumentoIndividual` com URN montada a partir da Casa, tipo, data e numero/ano.
- `Epigrafe`, `Ementa` e opcionalmente `Indexacao`.

## Uso diario na rotina LexML
- Cadastre novas normas sempre com `numero`, `ano`, `data`, esfera e tipo com `Equivalente LexML`; anexe o `texto_integral` quando existir.  
- Se atualizar metadados de normas antigas, salve novamente para atualizar o `timestamp` que o coletor usa no filtro por data.  
- Mantenha apenas um provedor e um publicador ativos e corretos; revise o XML sempre que o LexML mandar atualizacao.  
- Valide periodicamente chamando `Identify` e `ListRecords` para checar disponibilidade externa (use o host oficial, nao apenas localhost).  
- Se o coletor do LexML reportar falhas, verifique `sapl.log` e se o `endereco_web` esta batendo com o dominio publicado.  
- Quando trocar certificados/HTTPS, confira se a `baseURL` no XML do provedor esta coerente e acessivel.

## Roteiro de falas simples (colinha)
1) "O SGVP e nosso site. O LexML e a biblioteca. Vamos fazer eles conversarem."  
2) "Preenchi os dados da Casa e disse se ela e Municipal ou Estadual."  
3) "Escolhi o tipo de lei e marquei o equivalente LexML, que define como a URN e montada."  
4) "Cadastrei o Provedor e o Publicador com o XML que o time do LexML enviou; o sistema checa se esta correto."  
5) "Aqui esta uma norma de exemplo com PDF e resumo."  
6) "Chamando Identify, o SGVP mostra quem ele e e qual e a baseURL."  
7) "Chamando ListRecords, vemos o XML LexML com a URN e os links para o conteudo."  
8) "Esse mesmo endereco pode ser usado pelo coletor do LexML para sincronizar as normas."  

## Checklist final (confira antes da demo ou producao)
- [ ] Casa Legislativa preenchida (nome, sigla, municipio, UF, endereco_web, email).  
- [ ] Esfera Federacao escolhida em Parametros.  
- [ ] Tipos de Norma com `Equivalente LexML` definido.  
- [ ] Pelo menos 1 Norma com data, numero, ano, esfera e `timestamp` salvo.  
- [ ] Provedor e Publicador cadastrados com XML validado.  
- [ ] `Identify` e `ListRecords` retornando 200 e XML legivel (usando host publico).  
