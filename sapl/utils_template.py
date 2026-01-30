"""
Utilitários para aplicar templates de documentos aos novos documentos
criados via OnlyOffice.
"""
import logging
from io import BytesIO

logger = logging.getLogger(__name__)


def criar_documento_com_template(tipo_conteudo, tipo_especifico, dados):
    """
    Cria um novo documento usando um template existente.

    1. Busca template adequado via DocumentTemplate.get_template_for()
    2. Carrega .docx do template com python-docx
    3. Mantém cabeçalho/rodapé, limpa ou adapta o corpo
    4. Adiciona dados iniciais do documento
    5. Retorna BytesIO com documento pronto

    Args:
        tipo_conteudo: string com o tipo (proposicao, materia, docacessorio, docadm, norma)
        tipo_especifico: objeto do tipo específico (TipoMateriaLegislativa, TipoProposicao, etc.)
                        ou None para usar template genérico
        dados: dicionário com dados do documento:
            - titulo: título ou identificação do documento
            - descricao: descrição, ementa ou assunto
            - tipo_display: nome do tipo para exibição (opcional)

    Returns:
        BytesIO com o documento pronto ou None se não houver template
    """
    try:
        from docx import Document
        from docx.shared import Pt
        from sapl.base.models import DocumentTemplate

        # Busca o template mais adequado
        template = DocumentTemplate.get_template_for(tipo_conteudo, tipo_especifico)

        if not template or not template.arquivo:
            logger.debug(f"Nenhum template encontrado para {tipo_conteudo}")
            return None

        logger.info(f"Usando template '{template.nome}' para {tipo_conteudo}")

        # Carrega o documento do template
        try:
            doc = Document(template.arquivo.path)
        except Exception as e:
            logger.error(f"Erro ao carregar template {template.pk}: {e}")
            return None

        # Limpa o corpo do documento mantendo cabeçalho e rodapé
        # Remove todos os parágrafos existentes
        for paragraph in doc.paragraphs:
            p = paragraph._element
            p.getparent().remove(p)

        # Remove todas as tabelas existentes
        for table in doc.tables:
            t = table._element
            t.getparent().remove(t)

        # Adiciona o conteúdo inicial do novo documento
        titulo = dados.get('titulo', 'Documento')
        descricao = dados.get('descricao', '')
        tipo_display = dados.get('tipo_display', tipo_conteudo.title())

        # Adiciona título
        doc.add_heading(titulo, level=0)

        # Adiciona informações do documento
        if descricao:
            if tipo_conteudo in ['proposicao', 'materia', 'norma']:
                doc.add_paragraph(f'Ementa: {descricao}')
            else:
                doc.add_paragraph(f'Assunto: {descricao}')

        doc.add_paragraph('')

        # Texto orientativo
        doc.add_paragraph(f'Digite o texto do documento abaixo:')
        doc.add_paragraph('')
        doc.add_paragraph('')

        # Salva em memória
        file_stream = BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)

        return file_stream

    except ImportError:
        logger.error("python-docx não está instalado")
        return None
    except Exception as e:
        logger.error(f"Erro ao criar documento com template: {e}")
        return None


def criar_documento_em_branco(titulo, descricao, tipo_documento='Documento'):
    """
    Cria um documento em branco básico quando não há template disponível.
    Fallback para manter compatibilidade com o comportamento anterior.

    Args:
        titulo: título ou identificação do documento
        descricao: descrição, ementa ou assunto
        tipo_documento: tipo para exibição (ex: 'Proposição', 'Matéria Legislativa')

    Returns:
        BytesIO com o documento ou None em caso de erro
    """
    try:
        from docx import Document
        from io import BytesIO

        doc = Document()
        doc.add_heading(titulo, 0)

        if descricao:
            doc.add_paragraph(f'Ementa: {descricao}')

        doc.add_paragraph('')
        doc.add_paragraph(f'Digite o texto do documento abaixo:')
        doc.add_paragraph('')

        file_stream = BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)

        return file_stream

    except ImportError:
        logger.error("python-docx não está instalado")
        return None
    except Exception as e:
        logger.error(f"Erro ao criar documento em branco: {e}")
        return None


def aplicar_template_existente(documento_path, tipo_conteudo, tipo_especifico=None):
    """
    Aplica cabeçalho e rodapé de um template a um documento existente.

    Útil para documentos que já foram criados mas precisam ter o
    cabeçalho/rodapé atualizado.

    Args:
        documento_path: caminho para o documento .docx existente
        tipo_conteudo: string com o tipo (proposicao, materia, etc.)
        tipo_especifico: objeto do tipo específico ou None

    Returns:
        BytesIO com o documento atualizado ou None se não houver template
    """
    try:
        from docx import Document
        from sapl.base.models import DocumentTemplate
        from copy import deepcopy

        # Busca o template
        template = DocumentTemplate.get_template_for(tipo_conteudo, tipo_especifico)

        if not template or not template.arquivo:
            logger.debug(f"Nenhum template encontrado para aplicar")
            return None

        # Carrega o template e o documento existente
        template_doc = Document(template.arquivo.path)
        doc = Document(documento_path)

        # Copia cabeçalho do template para o documento
        if template_doc.sections:
            template_section = template_doc.sections[0]

            for section in doc.sections:
                # Copia cabeçalho
                if template_section.header:
                    for para in section.header.paragraphs:
                        p = para._element
                        p.getparent().remove(p)

                    for para in template_section.header.paragraphs:
                        new_para = section.header.add_paragraph()
                        new_para.text = para.text
                        new_para.style = para.style
                        new_para.alignment = para.alignment

                # Copia rodapé
                if template_section.footer:
                    for para in section.footer.paragraphs:
                        p = para._element
                        p.getparent().remove(p)

                    for para in template_section.footer.paragraphs:
                        new_para = section.footer.add_paragraph()
                        new_para.text = para.text
                        new_para.style = para.style
                        new_para.alignment = para.alignment

        # Salva em memória
        file_stream = BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)

        return file_stream

    except ImportError:
        logger.error("python-docx não está instalado")
        return None
    except Exception as e:
        logger.error(f"Erro ao aplicar template a documento existente: {e}")
        return None
