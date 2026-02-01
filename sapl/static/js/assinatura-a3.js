/**
 * Módulo JavaScript para Assinatura Digital com Certificado A3
 * Gerencia a comunicação com aplicações de assinatura local (token USB/smartcard)
 */

(function(global) {
    'use strict';

    var AssinaturaA3 = {
        /**
         * Configurações das aplicações suportadas
         */
        aplicacoes: {
            serpro: {
                nome: 'Assinador SERPRO',
                porta: 10443,
                protocolo: 'https',
                endpoints: {
                    listarCertificados: '/certificados',
                    assinar: '/assinar',
                    verificar: '/verificar'
                }
            },
            webpki: {
                nome: 'Lacuna Web PKI',
                porta: 5000,
                protocolo: 'http',
                endpoints: {
                    listarCertificados: '/api/certificates',
                    assinar: '/api/sign',
                    verificar: '/api/verify'
                }
            }
        },

        /**
         * Aplicação detectada
         */
        appDetectada: null,

        /**
         * Detecta qual aplicação de assinatura está rodando
         * @returns {Promise}
         */
        detectar: function() {
            var self = this;
            var apps = Object.keys(this.aplicacoes);

            return new Promise(function(resolve, reject) {
                var tentativas = 0;

                apps.forEach(function(appKey) {
                    var app = self.aplicacoes[appKey];
                    var url = app.protocolo + '://localhost:' + app.porta + app.endpoints.listarCertificados;

                    // Usando timeout com AbortController
                    var controller = new AbortController();
                    var timeoutId = setTimeout(function() {
                        controller.abort();
                    }, 3000);

                    fetch(url, {
                        method: 'GET',
                        mode: 'cors',
                        credentials: 'omit',
                        signal: controller.signal
                    })
                    .then(function(response) {
                        clearTimeout(timeoutId);
                        if (response.ok) {
                            self.appDetectada = {
                                key: appKey,
                                config: app
                            };
                            resolve({
                                success: true,
                                app: app.nome,
                                key: appKey
                            });
                        } else {
                            throw new Error('Resposta não OK');
                        }
                    })
                    .catch(function(error) {
                        clearTimeout(timeoutId);
                        tentativas++;
                        if (tentativas >= apps.length) {
                            reject({
                                success: false,
                                error: 'Nenhuma aplicação de assinatura A3 detectada. Certifique-se de que a aplicação está em execução.'
                            });
                        }
                    });
                });
            });
        },

        /**
         * Testa se uma aplicação específica está respondendo
         * @param {string} appKey - Chave da aplicação (serpro, webpki)
         * @returns {Promise<boolean>}
         */
        testarConexao: function(appKey) {
            var app = this.aplicacoes[appKey];
            if (!app) {
                return Promise.resolve(false);
            }

            var url = app.protocolo + '://localhost:' + app.porta + '/';

            return fetch(url, {
                method: 'GET',
                mode: 'no-cors'
            })
            .then(function() {
                return true;
            })
            .catch(function() {
                return false;
            });
        },

        /**
         * Lista os certificados disponíveis no token/smartcard
         * @returns {Promise}
         */
        listarCertificados: function() {
            var self = this;

            if (!this.appDetectada) {
                return Promise.reject({
                    error: 'Nenhuma aplicação detectada. Execute detectar() primeiro.'
                });
            }

            var app = this.appDetectada.config;
            var url = app.protocolo + '://localhost:' + app.porta + app.endpoints.listarCertificados;

            return fetch(url, {
                method: 'GET',
                mode: 'cors',
                credentials: 'omit',
                headers: {
                    'Accept': 'application/json'
                }
            })
            .then(function(response) {
                if (!response.ok) {
                    throw new Error('Erro ao listar certificados');
                }
                return response.json();
            })
            .then(function(data) {
                // Normaliza o formato dos certificados
                return self._normalizarCertificados(data);
            });
        },

        /**
         * Normaliza o formato dos certificados para um formato comum
         * @param {Object} data - Dados retornados pela API
         * @returns {Array}
         */
        _normalizarCertificados: function(data) {
            var certificados = [];

            if (Array.isArray(data)) {
                certificados = data;
            } else if (data.certificados) {
                certificados = data.certificados;
            } else if (data.certificates) {
                certificados = data.certificates;
            }

            return certificados.map(function(cert) {
                return {
                    id: cert.id || cert.thumbprint || cert.serial,
                    subject: cert.subject || cert.subjectName || cert.nome,
                    issuer: cert.issuer || cert.issuerName || cert.emissor,
                    validFrom: cert.validFrom || cert.notBefore || cert.validade_inicio,
                    validTo: cert.validTo || cert.notAfter || cert.validade_fim,
                    thumbprint: cert.thumbprint || cert.hash,
                    raw: cert
                };
            });
        },

        /**
         * Assina dados com o certificado selecionado
         * @param {string} certificadoId - ID/thumbprint do certificado
         * @param {string} dados - Dados a serem assinados (base64 ou hash)
         * @param {string} algoritmo - Algoritmo de hash (sha256, sha384, sha512)
         * @returns {Promise}
         */
        assinar: function(certificadoId, dados, algoritmo) {
            var self = this;

            if (!this.appDetectada) {
                return Promise.reject({
                    error: 'Nenhuma aplicação detectada.'
                });
            }

            var app = this.appDetectada.config;
            var url = app.protocolo + '://localhost:' + app.porta + app.endpoints.assinar;

            var payload = {
                certificateId: certificadoId,
                data: dados,
                algorithm: algoritmo || 'sha256'
            };

            // Adapta payload para formato específico de cada aplicação
            if (this.appDetectada.key === 'serpro') {
                payload = {
                    certificado: certificadoId,
                    dados: dados,
                    algoritmo: algoritmo || 'SHA256'
                };
            }

            return fetch(url, {
                method: 'POST',
                mode: 'cors',
                credentials: 'omit',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                body: JSON.stringify(payload)
            })
            .then(function(response) {
                if (!response.ok) {
                    throw new Error('Erro ao assinar');
                }
                return response.json();
            })
            .then(function(data) {
                return {
                    success: true,
                    signature: data.signature || data.assinatura,
                    certificate: data.certificate || data.certificado
                };
            });
        },

        /**
         * Retorna informações sobre a aplicação detectada
         * @returns {Object|null}
         */
        getAplicacaoDetectada: function() {
            return this.appDetectada;
        },

        /**
         * Retorna lista de aplicações suportadas
         * @returns {Array}
         */
        getAplicacoesSuportadas: function() {
            var self = this;
            return Object.keys(this.aplicacoes).map(function(key) {
                return {
                    key: key,
                    nome: self.aplicacoes[key].nome,
                    porta: self.aplicacoes[key].porta
                };
            });
        },

        /**
         * Fluxo completo de assinatura A3
         * @param {string} hashPdf - Hash SHA256 do PDF em hexadecimal
         * @param {function} onProgress - Callback de progresso
         * @returns {Promise}
         */
        assinarPdf: function(hashPdf, onProgress) {
            var self = this;

            return new Promise(function(resolve, reject) {
                // Etapa 1: Detectar aplicação
                if (onProgress) onProgress(10, 'Detectando aplicação de assinatura...');

                self.detectar()
                .then(function(deteccao) {
                    if (onProgress) onProgress(30, 'Aplicação detectada: ' + deteccao.app);

                    // Etapa 2: Listar certificados
                    return self.listarCertificados();
                })
                .then(function(certificados) {
                    if (!certificados || certificados.length === 0) {
                        throw { error: 'Nenhum certificado encontrado no token' };
                    }

                    if (onProgress) onProgress(50, 'Certificados encontrados: ' + certificados.length);

                    // Por enquanto, usa o primeiro certificado
                    // Em produção, deveria mostrar seletor para o usuário
                    var certificado = certificados[0];

                    if (onProgress) onProgress(70, 'Assinando com: ' + certificado.subject);

                    // Etapa 3: Assinar
                    return self.assinar(certificado.id, hashPdf, 'sha256');
                })
                .then(function(resultado) {
                    if (onProgress) onProgress(100, 'Assinatura concluída!');
                    resolve(resultado);
                })
                .catch(function(error) {
                    reject(error);
                });
            });
        }
    };

    // Expor globalmente
    global.AssinaturaA3 = AssinaturaA3;

})(typeof window !== 'undefined' ? window : this);
