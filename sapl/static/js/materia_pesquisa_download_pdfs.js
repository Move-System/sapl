/*
 * Adiciona botões de download ao lado do link "Texto Original" 
 * na tela de resultados de pesquisa de matérias.
 * Também adiciona botão para baixar todos os PDFs em lote.
 */

(function () {
  function downloadFile(url, filename) {
    // Usa fetch para baixar o arquivo como blob e forçar download
    return fetch(url)
      .then(response => {
        if (!response.ok) {
          throw new Error('Erro ao baixar arquivo');
        }
        return response.blob();
      })
      .then(blob => {
        // Cria URL temporária do blob
        const blobUrl = window.URL.createObjectURL(blob);
        
        // Cria link temporário e força download
        const link = document.createElement('a');
        link.href = blobUrl;
        link.download = filename || 'documento.pdf';
        link.style.display = 'none';
        
        document.body.appendChild(link);
        link.click();
        
        // Limpa recursos
        document.body.removeChild(link);
        window.URL.revokeObjectURL(blobUrl);
      })
      .catch(error => {
        console.error('Erro ao baixar PDF:', error);
        throw error;
      });
  }

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  async function downloadAllPDFs() {
    const btn = document.getElementById('btn-download-todos-pdfs');
    if (!btn) return;

    // Coleta todos os links de "Texto Original"
    const strongElements = Array.from(document.querySelectorAll('strong'));
    const pdfList = [];

    strongElements.forEach((strong) => {
      const link = strong.querySelector('a');
      if (!link || link.textContent.trim() !== 'Texto Original') return;

      const pdfAssinadoUrl = link.getAttribute('data-pdf-assinado');
      const textoOriginalUrl = link.getAttribute('href');
      const pdfUrl = pdfAssinadoUrl || textoOriginalUrl;

      if (!pdfUrl) return;

      let filename = pdfUrl.split('/').pop() || 'texto_original.pdf';
      if (pdfAssinadoUrl && !filename.includes('assinado')) {
        const parts = filename.split('.');
        if (parts.length > 1) {
          parts[parts.length - 2] += '_assinado';
          filename = parts.join('.');
        }
      }

      pdfList.push({ url: pdfUrl, filename: filename });
    });

    if (pdfList.length === 0) {
      alert('Nenhum PDF encontrado para download.');
      return;
    }

    // Desabilita o botão e mostra progresso
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Baixando...';

    let downloaded = 0;
    let errors = 0;

    for (const pdf of pdfList) {
      try {
        await downloadFile(pdf.url, pdf.filename);
        downloaded++;
        btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Baixando ${downloaded}/${pdfList.length}...`;
        // Delay entre downloads para não sobrecarregar o navegador
        await sleep(500);
      } catch (error) {
        errors++;
        console.error(`Erro ao baixar ${pdf.filename}:`, error);
      }
    }

    // Restaura o botão
    btn.disabled = false;
    btn.innerHTML = originalText;

    // Mostra mensagem de conclusão
    if (errors === 0) {
      alert(`✅ Download concluído! ${downloaded} PDF(s) baixado(s) com sucesso.`);
    } else {
      alert(`⚠️ Download concluído com erros!\n${downloaded} PDF(s) baixado(s)\n${errors} erro(s)`);
    }
  }

  function injectButtons() {
    // Busca todos os elementos <strong> que contêm link "Texto Original"
    const strongElements = Array.from(document.querySelectorAll('strong'));
    
    strongElements.forEach((strong) => {
      const link = strong.querySelector('a');
      if (!link || link.textContent.trim() !== 'Texto Original') return;
      
      // evita duplicação
      if (strong.nextSibling && strong.nextSibling.nodeType === Node.ELEMENT_NODE 
          && strong.nextSibling.hasAttribute('data-sapl-download-pdf-btn')) return;

      // Prioriza PDF assinado se existir, senão usa texto original
      const pdfAssinadoUrl = link.getAttribute('data-pdf-assinado');
      const textoOriginalUrl = link.getAttribute('href');
      const pdfUrl = pdfAssinadoUrl || textoOriginalUrl;
      
      if (!pdfUrl) return;

      // extrai nome do arquivo da URL e adiciona sufixo se for assinado
      let filename = pdfUrl.split('/').pop() || 'texto_original.pdf';
      if (pdfAssinadoUrl && !filename.includes('assinado')) {
        const parts = filename.split('.');
        if (parts.length > 1) {
          parts[parts.length - 2] += '_assinado';
          filename = parts.join('.');
        }
      }

      // cria botão com ícone FontAwesome
      const btn = document.createElement('a');
      btn.setAttribute('data-sapl-download-pdf-btn', '1');
      btn.className = 'btn btn-sm btn-outline-primary ml-1';
      
      // Define título e estilo diferente se for PDF assinado
      if (pdfAssinadoUrl) {
        btn.title = 'Baixar PDF Assinado';
        btn.classList.add('btn-success'); // Verde para PDF assinado
        btn.classList.remove('btn-outline-primary');
      } else {
        btn.title = 'Baixar PDF';
      }
      
      btn.href = 'javascript:void(0);';
      btn.innerHTML = '<i class="fas fa-download"></i>';
      
      // evento de click para forçar download
      btn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        downloadFile(pdfUrl, filename);
        return false;
      });

      // insere logo após o </strong>
      strong.parentNode.insertBefore(document.createTextNode(' '), strong.nextSibling);
      strong.parentNode.insertBefore(btn, strong.nextSibling);

      // Botões "Baixar Todos" quando há documentos acessórios
      const materiaPk = link.getAttribute('data-materia-pk');
      if (materiaPk) {
        // Botão PDF unificado
        const pdfBtn = document.createElement('a');
        pdfBtn.setAttribute('data-sapl-download-all-btn', '1');
        pdfBtn.className = 'btn btn-sm btn-info ml-1';
        pdfBtn.title = 'Baixar todos em PDF único';
        pdfBtn.href = '/materia/pdf-completo/' + materiaPk;
        pdfBtn.innerHTML = '<i class="fas fa-file-pdf"></i>';
        strong.parentNode.insertBefore(document.createTextNode(' '), btn.nextSibling);
        strong.parentNode.insertBefore(pdfBtn, btn.nextSibling.nextSibling);

        // Botão ZIP
        const zipBtn = document.createElement('a');
        zipBtn.setAttribute('data-sapl-download-all-btn', '1');
        zipBtn.className = 'btn btn-sm btn-info ml-1';
        zipBtn.title = 'Baixar todos em ZIP';
        zipBtn.href = '/materia/zip-completo/' + materiaPk;
        zipBtn.innerHTML = '<i class="fas fa-file-archive"></i>';
        strong.parentNode.insertBefore(document.createTextNode(' '), pdfBtn.nextSibling);
        strong.parentNode.insertBefore(zipBtn, pdfBtn.nextSibling.nextSibling);
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectButtons);
  } else {
    injectButtons();
  }

  // Adiciona listener para o botão de download em lote
  document.addEventListener('DOMContentLoaded', function() {
    const btnDownloadAll = document.getElementById('btn-download-todos-pdfs');
    if (btnDownloadAll) {
      btnDownloadAll.addEventListener('click', function(e) {
        e.preventDefault();
        downloadAllPDFs();
      });
    }
  });
})();
