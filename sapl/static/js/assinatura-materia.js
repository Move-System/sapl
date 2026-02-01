/**
 * Módulo JavaScript para Assinatura Digital de Matérias Legislativas
 * Gerencia o fluxo de assinatura com certificados A1 e A3
 */

(function(global) {
    'use strict';

    var AssinaturaMateria = {
        /**
         * Configurações
         */
        config: {
            materiaId: null,
            csrfToken: null,
            urls: {
                assinarA1: '/materia/{pk}/assinar/a1/',
                assinarA3Preparar: '/materia/{pk}/assinar/a3/preparar/',
                assinarA3Finalizar: '/materia/{pk}/assinar/a3/finalizar/',
                pdfAssinado: '/materia/{pk}/pdf-assinado/',
                verificarAssinatura: '/materia/{pk}/verificar-assinatura/',
                detectarA3: '/materia/assinatura/detectar-a3/'
            },
            portasA3: [
                { nome: 'Assinador SERPRO', porta: 10443, protocolo: 'https' },
                { nome: 'Web PKI Local', porta: 5000, protocolo: 'http' }
            ]
        },

        /**
         * Inicializa o módulo
         * @param {number} materiaId - ID da matéria legislativa
         * @param {string} csrfToken - Token CSRF para requisições POST
         */
        init: function(materiaId, csrfToken) {
            this.config.materiaId = materiaId;
            this.config.csrfToken = csrfToken || this._getCSRFToken();
            return this;
        },

        /**
         * Obtém o token CSRF do cookie
         */
        _getCSRFToken: function() {
            var name = 'csrftoken';
            var cookieValue = null;
            if (document.cookie && document.cookie !== '') {
                var cookies = document.cookie.split(';');
                for (var i = 0; i < cookies.length; i++) {
                    var cookie = cookies[i].trim();
                    if (cookie.substring(0, name.length + 1) === (name + '=')) {
                        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                        break;
                    }
                }
            }
            return cookieValue;
        },

        /**
         * Gera URL substituindo {pk} pelo ID da matéria
         */
        _getUrl: function(urlKey) {
            return this.config.urls[urlKey].replace('{pk}', this.config.materiaId);
        },

        /**
         * Assina com certificado A1
         * @param {File} certificadoFile - Arquivo .pfx ou .p12
         * @param {string} senha - Senha do certificado
         * @param {function} onProgress - Callback de progresso (opcional)
         * @returns {Promise}
         */
        assinarComA1: function(certificadoFile, senha, onProgress) {
            var self = this;

            return new Promise(function(resolve, reject) {
                if (!certificadoFile) {
                    reject({ error: 'Arquivo do certificado não informado' });
                    return;
                }

                if (!senha) {
                    reject({ error: 'Senha do certificado não informada' });
                    return;
                }

                var formData = new FormData();
                formData.append('certificado', certificadoFile);
                formData.append('senha', senha);

                var xhr = new XMLHttpRequest();
                xhr.open('POST', self._getUrl('assinarA1'), true);
                xhr.setRequestHeader('X-CSRFToken', self.config.csrfToken);

                xhr.upload.onprogress = function(e) {
                    if (e.lengthComputable && onProgress) {
                        var percentComplete = (e.loaded / e.total) * 50;
                        onProgress(percentComplete, 'Enviando certificado...');
                    }
                };

                xhr.onload = function() {
                    if (xhr.status >= 200 && xhr.status < 300) {
                        try {
                            var response = JSON.parse(xhr.responseText);
                            if (response.success) {
                                resolve(response);
                            } else {
                                reject(response);
                            }
                        } catch (e) {
                            reject({ error: 'Erro ao processar resposta do servidor' });
                        }
                    } else {
                        try {
                            var errorResponse = JSON.parse(xhr.responseText);
                            reject(errorResponse);
                        } catch (e) {
                            reject({ error: 'Erro na comunicação com o servidor' });
                        }
                    }
                };

                xhr.onerror = function() {
                    reject({ error: 'Erro de rede ao comunicar com o servidor' });
                };

                xhr.send(formData);
            });
        },

        /**
         * Detecta aplicações de assinatura A3 rodando localmente
         * @returns {Promise} - Resolve com informações da aplicação encontrada
         */
        detectarAplicacaoA3: function() {
            var self = this;
            var portas = this.config.portasA3;

            return new Promise(function(resolve, reject) {
                var tentativas = 0;
                var encontrado = false;

                portas.forEach(function(app) {
                    var url = app.protocolo + '://localhost:' + app.porta + '/';

                    // Tenta conectar usando fetch com timeout
                    var controller = new AbortController();
                    var timeoutId = setTimeout(function() {
                        controller.abort();
                    }, 3000);

                    fetch(url, {
                        method: 'GET',
                        mode: 'no-cors',
                        signal: controller.signal
                    })
                    .then(function() {
                        clearTimeout(timeoutId);
                        if (!encontrado) {
                            encontrado = true;
                            resolve({
                                success: true,
                                app: app,
                                message: 'Aplicação ' + app.nome + ' detectada na porta ' + app.porta
                            });
                        }
                    })
                    .catch(function() {
                        clearTimeout(timeoutId);
                        tentativas++;
                        if (tentativas >= portas.length && !encontrado) {
                            reject({
                                success: false,
                                error: 'Nenhuma aplicação de assinatura A3 detectada'
                            });
                        }
                    });
                });

                // Timeout global
                setTimeout(function() {
                    if (!encontrado) {
                        reject({
                            success: false,
                            error: 'Timeout ao detectar aplicação A3'
                        });
                    }
                }, 5000);
            });
        },

        /**
         * Prepara a assinatura A3 obtendo o hash do PDF
         * @returns {Promise}
         */
        prepararAssinaturaA3: function() {
            var self = this;

            return fetch(this._getUrl('assinarA3Preparar'), {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.config.csrfToken,
                    'Content-Type': 'application/json'
                }
            })
            .then(function(response) {
                return response.json();
            })
            .then(function(data) {
                if (data.success) {
                    return data;
                } else {
                    throw data;
                }
            });
        },

        /**
         * Finaliza a assinatura A3 enviando a assinatura do token
         * @param {string} signatureBase64 - Assinatura em base64
         * @param {string} certificateBase64 - Certificado em base64
         * @returns {Promise}
         */
        finalizarAssinaturaA3: function(signatureBase64, certificateBase64) {
            var self = this;

            return fetch(this._getUrl('assinarA3Finalizar'), {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.config.csrfToken,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    signature: signatureBase64,
                    certificate: certificateBase64
                })
            })
            .then(function(response) {
                return response.json();
            })
            .then(function(data) {
                if (data.success) {
                    return data;
                } else {
                    throw data;
                }
            });
        },

        /**
         * Verifica a assinatura do PDF da matéria
         * @returns {Promise}
         */
        verificarAssinatura: function() {
            return fetch(this._getUrl('verificarAssinatura'), {
                method: 'GET',
                headers: {
                    'X-CSRFToken': this.config.csrfToken
                }
            })
            .then(function(response) {
                return response.json();
            });
        },

        /**
         * Retorna a URL do PDF assinado
         * @returns {string}
         */
        getUrlPdfAssinado: function() {
            return this._getUrl('pdfAssinado');
        },

        /**
         * Baixa o PDF assinado
         */
        baixarPdfAssinado: function() {
            window.open(this.getUrlPdfAssinado(), '_blank');
        }
    };

    // Expor globalmente
    global.AssinaturaMateria = AssinaturaMateria;

})(typeof window !== 'undefined' ? window : this);
