/**
 * materia_impressao_em_massa.js
 *
 * Impressão / download em massa de matérias legislativas.
 *
 * Funcionalidades:
 *  - Ativa modo de seleção ao clicar em "Imprimir Selecionados" (barra de ações)
 *  - Exibe checkbox em cada linha de resultado
 *  - Toolbar flutuante mostra contagem e ações (Imprimir / Baixar PDF / Limpar)
 *  - Botão "Todos" seleciona/desseleciona todos da página atual
 *  - Ao clicar Imprimir: chama /materia/pdf-multiplos/?ids=... → abre PDF no
 *    browser para impressão direta via window.print() em novo tab
 *  - Ao clicar Baixar PDF: mesmo endpoint mas força download via blob
 */

(function () {
  'use strict';

  var URL_PDF_MULTIPLOS = '/materia/pdf-multiplos/';
  var MAX_SELECAO = 200;

  var modoAtivo = false;

  // ── Elementos ────────────────────────────────────────────────────────────
  var btnImprimirSelecionados = null; // botão na barra de ações (topo)
  var btnSelecionarTodos = null;
  var toolbar = null;
  var toolbarCount = null;
  var toolbarBtnImprimir = null;
  var toolbarBtnDownload = null;
  var toolbarBtnLimpar = null;
  var toolbarLoading = null;

  // ── Inicialização ─────────────────────────────────────────────────────────
  function init() {
    btnImprimirSelecionados = document.getElementById('btn-imprimir-selecionados');
    btnSelecionarTodos = document.getElementById('btn-selecionar-todos-print');
    toolbar = document.getElementById('print-toolbar');
    toolbarCount = document.getElementById('print-toolbar-count');
    toolbarBtnImprimir = document.getElementById('print-toolbar-btn-imprimir');
    toolbarBtnDownload = document.getElementById('print-toolbar-btn-download');
    toolbarBtnLimpar = document.getElementById('print-toolbar-btn-limpar');
    toolbarLoading = document.getElementById('print-toolbar-loading');

    if (!btnImprimirSelecionados || !toolbar) return; // não está na página de resultados

    // Botões já visíveis no novo layout — garante estado inicial correto
    btnImprimirSelecionados.style.display = '';
    if (btnSelecionarTodos) btnSelecionarTodos.style.display = 'none'; // aparece só quando modo ativo

    btnImprimirSelecionados.addEventListener('click', function () {
      if (!modoAtivo) {
        ativarModo();
      } else {
        var ids = getIdsSelecionados();
        if (ids.length === 0) {
          mostrarAlerta('Selecione ao menos um documento para imprimir.');
          return;
        }
        abrirPDF(ids, true);
      }
    });

    btnSelecionarTodos.addEventListener('click', function () {
      if (!modoAtivo) { ativarModo(); }
      var checks = document.querySelectorAll('.print-chk');
      var todasMarcadas = Array.from(checks).every(function (c) { return c.checked; });
      checks.forEach(function (c) { c.checked = !todasMarcadas; });
      atualizarContagem();
    });

    toolbarBtnImprimir.addEventListener('click', function () {
      var ids = getIdsSelecionados();
      if (ids.length === 0) { mostrarAlerta('Selecione ao menos um documento.'); return; }
      abrirPDF(ids, true);
    });

    toolbarBtnDownload.addEventListener('click', function () {
      var ids = getIdsSelecionados();
      if (ids.length === 0) { mostrarAlerta('Selecione ao menos um documento.'); return; }
      baixarPDF(ids);
    });

    toolbarBtnLimpar.addEventListener('click', function () {
      desativarModo();
    });

    // Delegação de eventos nos checkboxes (gerados dinamicamente)
    document.addEventListener('change', function (e) {
      if (e.target && e.target.classList.contains('print-chk')) {
        atualizarContagem();
      }
    });

    // Clique na linha inteira (quando modo ativo) seleciona o checkbox
    document.addEventListener('click', function (e) {
      if (!modoAtivo) return;
      var row = e.target.closest('.materia-row');
      if (!row) return;
      // Evita toggle duplo se clicou direto no checkbox ou num link
      if (e.target.classList.contains('print-chk')) return;
      if (e.target.closest('a')) return;
      var chk = row.querySelector('.print-chk');
      if (chk) {
        chk.checked = !chk.checked;
        atualizarContagem();
      }
    });
  }

  // ── Modo de seleção ───────────────────────────────────────────────────────
  function ativarModo() {
    modoAtivo = true;
    // Mostra checkboxes em todas as linhas
    document.querySelectorAll('.print-select-col').forEach(function (el) {
      el.style.display = 'inline-block';
    });
    // Estilo visual nas linhas
    document.querySelectorAll('.materia-row').forEach(function (row) {
      row.style.cursor = 'pointer';
    });
    // Atualiza botão de ações — destaca em vermelho sólido
    btnImprimirSelecionados.classList.replace('btn-outline-danger', 'btn-danger');
    // Mostra badge e botão Todos
    var badge = document.getElementById('badge-print-total');
    if (badge) badge.style.display = '';
    if (btnSelecionarTodos) btnSelecionarTodos.style.display = '';

    toolbar.style.display = 'block';
    atualizarContagem();
  }

  function desativarModo() {
    modoAtivo = false;
    // Desmarca todos e oculta checkboxes
    document.querySelectorAll('.print-chk').forEach(function (c) { c.checked = false; });
    document.querySelectorAll('.print-select-col').forEach(function (el) {
      el.style.display = 'none';
    });
    document.querySelectorAll('.materia-row').forEach(function (row) {
      row.style.cursor = '';
      row.classList.remove('table-active');
    });
    // Restaura botão para outline
    btnImprimirSelecionados.classList.replace('btn-danger', 'btn-outline-danger');
    // Oculta badge e botão Todos
    var badge = document.getElementById('badge-print-total');
    if (badge) { badge.style.display = 'none'; badge.textContent = '0'; }
    if (btnSelecionarTodos) btnSelecionarTodos.style.display = 'none';

    toolbar.style.display = 'none';
    ocultarAlertaToolbar();
  }

  // ── Contagem ──────────────────────────────────────────────────────────────
  function getIdsSelecionados() {
    return Array.from(document.querySelectorAll('.print-chk:checked'))
      .map(function (c) { return parseInt(c.getAttribute('data-materia-id'), 10); })
      .slice(0, MAX_SELECAO);
  }

  function atualizarContagem() {
    var ids = getIdsSelecionados();
    var n = ids.length;

    // Badge na toolbar flutuante
    if (toolbarCount) toolbarCount.textContent = n;

    // Badge no botão de ações
    var badge = document.getElementById('badge-print-total');
    if (badge) badge.textContent = n;

    // Destaque visual nas linhas selecionadas
    document.querySelectorAll('.materia-row').forEach(function (row) {
      var chk = row.querySelector('.print-chk');
      if (chk && chk.checked) {
        row.classList.add('table-active');
      } else {
        row.classList.remove('table-active');
      }
    });

    // Aviso de limite
    if (n >= MAX_SELECAO) {
      mostrarAlertaToolbar('Limite de ' + MAX_SELECAO + ' documentos atingido. Desmarque alguns para selecionar outros.');
    } else {
      ocultarAlertaToolbar();
    }
  }

  // ── PDF: imprimir ─────────────────────────────────────────────────────────
  function abrirPDF(ids, imprimir) {
    setLoading(true);
    var url = URL_PDF_MULTIPLOS + '?ids=' + ids.join(',');

    // Abre em nova aba; quando carregado o browser oferece impressão
    var win = window.open(url, '_blank');
    if (!win) {
      // Pop-up bloqueado — fallback: link direto
      var a = document.createElement('a');
      a.href = url;
      a.target = '_blank';
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }
    // Aguarda pequeno delay e remove loading (não temos evento de "carregou" na outra aba)
    setTimeout(function () { setLoading(false); }, 2000);
  }

  // ── PDF: baixar como arquivo ──────────────────────────────────────────────
  function baixarPDF(ids) {
    setLoading(true);
    var url = URL_PDF_MULTIPLOS + '?ids=' + ids.join(',');

    fetch(url, { credentials: 'same-origin' })
      .then(function (resp) {
        if (!resp.ok) {
          return resp.json().then(function (d) {
            throw new Error(d.error || ('Erro HTTP ' + resp.status));
          });
        }
        return resp.blob();
      })
      .then(function (blob) {
        var blobUrl = window.URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = blobUrl;
        a.download = 'materias_selecionadas.pdf';
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(blobUrl);
        setLoading(false);
      })
      .catch(function (err) {
        setLoading(false);
        mostrarAlerta('Erro ao gerar PDF: ' + err.message);
      });
  }

  // ── Helpers UI ────────────────────────────────────────────────────────────
  function setLoading(on) {
    if (!toolbarLoading) return;
    toolbarLoading.style.display = on ? 'block' : 'none';
    if (toolbarBtnImprimir) toolbarBtnImprimir.disabled = on;
    if (toolbarBtnDownload) toolbarBtnDownload.disabled = on;
  }

  function mostrarAlerta(msg) {
    // Toast simples usando Bootstrap alert
    var div = document.createElement('div');
    div.className = 'alert alert-warning alert-dismissible fade show';
    div.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;min-width:300px;max-width:500px;';
    div.innerHTML = '<i class="fas fa-exclamation-triangle"></i> ' + escHtml(msg) +
      '<button type="button" class="close" data-dismiss="alert"><span>&times;</span></button>';
    document.body.appendChild(div);
    setTimeout(function () {
      if (div.parentNode) div.parentNode.removeChild(div);
    }, 5000);
  }

  function mostrarAlertaToolbar(msg) {
    var existing = document.getElementById('print-toolbar-limit-alert');
    if (existing) return;
    var div = document.createElement('div');
    div.id = 'print-toolbar-limit-alert';
    div.className = 'alert alert-warning py-1 px-2 mt-2 mb-0 small';
    div.innerHTML = '<i class="fas fa-exclamation-triangle"></i> ' + escHtml(msg);
    if (toolbar) toolbar.appendChild(div);
  }

  function ocultarAlertaToolbar() {
    var el = document.getElementById('print-toolbar-limit-alert');
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  function escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── Arranque ──────────────────────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
