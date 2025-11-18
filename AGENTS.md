# AGENTS.md - AI Agent Activity Log

This document tracks significant changes and improvements made to the SAPL (Sistema de Apoio ao Processo Legislativo) project through AI-assisted development sessions.

## About This Document

This file records commits and changes that were made with assistance from AI agents or automated tools. It serves as a historical record of AI-driven development activities and helps maintain transparency about which parts of the codebase have been touched by automated assistance.

## Last Updated
- **Date**: 2025-11-18
- **Last Analyzed Commit**: acd23f5

---

## Recent Changes

### October 31, 2025 - UX and Visual Consistency Improvements

**Commit**: `acd23f5` by rangelbruno <brunojp.rangel@gmail.com>  
**Message**: feat(ux): melhora experiência do usuário e consistência visual do projeto

This appears to be a major initial commit that established the foundation of the SAPL project with comprehensive infrastructure and features:

#### Key Areas Added/Modified:

**Infrastructure & Configuration**
- Complete Docker setup with multiple compose files for different environments (dev, production)
- Kubernetes deployment configurations (k8s)
- Nginx configuration for production deployment
- Solr integration for full-text search capabilities
- CI/CD pipeline configuration (.drone.yml)
- Environment configuration templates

**Frontend Development**
- Modern frontend build system with webpack
- Vue.js components for various modules (compilacao, painel, parlamentar)
- SCSS styling architecture with Bootstrap integration
- TinyMCE integration for rich text editing
- Image cropping functionality
- Responsive design implementation

**Core Modules**
- **API Module**: RESTful API with Django Rest Framework
  - Multiple specialized view files for different domains (audiencia, materia, norma, sessao, parlamentares, etc.)
  - Pagination, permissions, and serialization logic
  - Health check endpoints
  
- **Base Module**: Core application functionality
  - User authentication and authorization
  - Email utilities
  - Audit logging system
  - Search indexing
  - Template tags and context processors

- **Materia Module**: Legislative matter management
  - Matter creation, tracking, and tramitation
  - Document accessories
  - Proposals (proposições) system
  - OnlyOffice integration for document editing
  - Author management and multi-authorship support

- **Norma Module**: Legal norms management
  - Juridical norms CRUD operations
  - Norm relationships and citations
  - Statistics tracking
  - LexML integration for legal document standards

- **Sessao Module**: Legislative session management
  - Plenary session management
  - Voting system (nominal and symbolic)
  - Agenda (ordem do dia) and expedient management
  - Attendance tracking
  - Session minutes and proceedings

- **Parlamentares Module**: Parliament member management
  - Legislator profiles and mandates
  - Party affiliations and coalitions
  - Parliamentary fronts (frentes parlamentares)
  - Mesa diretora (directive board) composition

- **Comissoes Module**: Committee management
  - Committee creation and composition
  - Committee meetings and documentation
  - Matter assignments to committees

- **Audiencia Module**: Public hearing management
  - Public hearing scheduling and documentation
  - Attachments and related materials

- **Protocolo Administrativo Module**: Administrative protocol
  - Document protocol and tracking
  - Administrative document management
  - Tramitation workflow

- **Compilacao Module**: Text compilation system
  - Legislative text articulation
  - Version control for legal texts
  - Amendment tracking and consolidation

- **TCE Module**: Court of Accounts integration
  - Specialized functionality for TCE compliance
  - Process and document management for auditing

**Additional Features**
- **Reporting System**: Comprehensive PDF generation for various document types
  - Session reports, matter reports, norm reports
  - Statistical reports
  - Custom label/etiquette printing

- **Search Integration**: Haystack/Solr integration for full-text search across:
  - Legislative matters
  - Juridical norms  
  - Session proceedings
  - Accessory documents

- **Rules & Permissions**: Granular permission system
  - Role-based access control (groups)
  - Per-module permission definitions
  - Anonymous user restrictions

- **LexML Integration**: Brazilian legal document standard compliance
  - OAI-PMH server for metadata harvesting
  - Standardized legal document identifiers

**Testing & Quality Assurance**
- Comprehensive test suites for all major modules
- Test fixtures and factories
- Integration tests for complex workflows
- Test coverage configuration

**Documentation**
- Extensive documentation in docs/ directory
  - Installation guides
  - Deployment instructions
  - Feature documentation (OnlyOffice, TCE, etc.)
  - User guides and help pages
  - API documentation

**Internationalization**
- Translation files for multiple languages (en, es, pt_BR)
- i18n support throughout the application

**Database**
- Extensive Django migrations for all modules
- Database view definitions for complex queries
- Fixtures for initial data population

**Scripts & Utilities**
- Database management scripts
- Migration utilities
- Deployment automation
- Development helpers
- Data integrity checks

**Static Assets**
- Complete frontend asset pipeline
- Icon sets and images
- CSS/SCSS frameworks
- JavaScript libraries and utilities

This commit represents a substantial foundation for a legislative management system with enterprise-level features, proper separation of concerns, comprehensive testing, and production-ready deployment configurations.

---

## Commit Analysis Methodology

This file is generated by analyzing git commit history and identifying changes that may have been assisted by AI agents or automated tools. The analysis includes:

1. Examining commit messages for patterns indicating AI assistance
2. Reviewing file changes and their scope
3. Identifying large-scale refactoring or generation patterns
4. Tracking commits that reference AI tools or agent sessions

---

## Notes

- This is a new file created to track AI-assisted development activities
- All commits listed here were analyzed from the git history
- The file will be updated regularly as new AI-assisted changes are made
- For complete commit history, refer to: `git log`

---

## Project Information

**Project**: SAPL - Sistema de Apoio ao Processo Legislativo  
**Repository**: https://github.com/interlegis/sapl  
**Branch**: 3.1.x (development branch)

**Technology Stack**:
- Backend: Python/Django
- Frontend: Vue.js, jQuery, Bootstrap
- Database: PostgreSQL
- Search: Apache Solr
- Deployment: Docker, Nginx, Gunicorn

---

*This document is maintained automatically and manually. Last update: 2025-11-18*
