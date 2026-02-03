/*
 * Adiciona botões de download ao lado do link "Texto Original" 
 * na tela de resultados de pesquisa de matérias.
 */

(function () {
  function downloadFile(url, filename) {
    // Usa fetch para baixar o arquivo como blob e forçar download
    fetch(url)
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
        // Fallback: abre em nova aba se o download falhar
        window.open(url, '_blank');
      });
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

      const pdfUrl = link.getAttribute('href');
      if (!pdfUrl) return;

      // extrai nome do arquivo da URL
      const filename = pdfUrl.split('/').pop() || 'texto_original.pdf';

      // cria botão com ícone FontAwesome
      const btn = document.createElement('a');
      btn.setAttribute('data-sapl-download-pdf-btn', '1');
      btn.className = 'btn btn-sm btn-outline-primary ml-1';
      btn.title = 'Baixar PDF';
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
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectButtons);
  } else {
    injectButtons();
  }
})();
