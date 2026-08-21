"""
Management command: notificar_pendentes_assinatura

Envia e-mail diario a cada autor que possui materias com assinatura digital
pendente (texto_original preenchido, pdf_assinado vazio).

Uso:
    python manage.py notificar_pendentes_assinatura

Agendar (crontab) -- exemplo para rodar todo dia as 8h:
    0 8 * * * cd /app && python manage.py notificar_pendentes_assinatura >> /var/log/sapl_notif_assinatura.log 2>&1

Opcoes:
    --dry-run      Lista os destinatarios e contagens sem enviar e-mails.
    --max-materias Numero maximo de materias listadas por e-mail (padrao: 20).
"""
import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

DEFAULT_MAX_MATERIAS = 20


class Command(BaseCommand):
    help = 'Envia e-mail diario aos autores com materias pendentes de assinatura digital'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Apenas lista os destinatarios sem enviar e-mails.',
        )
        parser.add_argument(
            '--max-materias',
            type=int,
            default=DEFAULT_MAX_MATERIAS,
            help='Maximo de materias listadas por e-mail (padrao: 20).',
        )

    def handle(self, *args, **options):
        # Imports aqui dentro para evitar problemas no bootstrap do Django
        from django.core.mail import EmailMultiAlternatives, get_connection
        from django.db.models import Q
        from django.template import loader
        from django.urls import reverse

        from sapl.base.models import CasaLegislativa, OperadorAutor
        from sapl.materia.models import MateriaLegislativa
        from sapl.settings import EMAIL_SEND_USER
        from sapl.utils import mail_service_configured

        dry_run = options['dry_run']
        max_mat = options['max_materias']

        if not dry_run and not mail_service_configured():
            self.stderr.write(self.style.ERROR(
                'Servico de e-mail nao configurado. '
                'Verifique EMAIL_HOST no arquivo .env.'
            ))
            return

        casa = CasaLegislativa.objects.first()
        if not casa:
            self.stderr.write(self.style.ERROR('Casa Legislativa nao configurada.'))
            return

        casa_nome = '{} de {} - {}'.format(casa.nome, casa.municipio, casa.uf)
        base_url = 'https://{}'.format(casa.endereco_web) if getattr(casa, 'endereco_web', None) else ''

        # Base queryset: materias pendentes de assinatura
        qs_pendentes = MateriaLegislativa.objects.filter(
            texto_original__isnull=False,
        ).exclude(
            texto_original=''
        ).filter(
            Q(pdf_assinado__isnull=True) | Q(pdf_assinado='')
        ).select_related('tipo').order_by('-data_apresentacao', '-id')

        # Apenas OperadorAutores com e-mail cadastrado
        operadores = (
            OperadorAutor.objects
            .select_related('autor', 'user')
            .filter(user__email__gt='')
        )

        if not operadores.exists():
            self.stdout.write(self.style.WARNING(
                'Nenhum OperadorAutor com e-mail encontrado. Nada a enviar.'
            ))
            return

        url_pesquisa_base = reverse('sapl.materia:pesquisar_materia')

        enviados = 0
        sem_pendencias = 0

        connection = None if dry_run else get_connection()
        if connection:
            connection.open()

        try:
            for op in operadores:
                autor = op.autor
                user = op.user
                email = (user.email or '').strip()

                if not email:
                    continue

                # Materias pendentes deste autor
                materias_qs = qs_pendentes.filter(autoria__autor=autor).distinct()
                total = materias_qs.count()

                if total == 0:
                    sem_pendencias += 1
                    continue

                materias_listadas = list(materias_qs[:max_mat])
                total_omitidas = max(0, total - max_mat)

                url_pesquisa = (
                    '{}?autoria__autor={}&status_assinatura=pendente'.format(
                        url_pesquisa_base, autor.pk
                    )
                )

                context = {
                    'casa_legislativa': casa_nome,
                    'nome_autor': autor.nome,
                    'total': total,
                    'materias': materias_listadas,
                    'total_omitidas': total_omitidas,
                    'base_url': base_url,
                    'url_pesquisa': url_pesquisa,
                }

                subject = '[SGVP] {} materia(s) aguardando sua assinatura digital'.format(total)

                if dry_run:
                    self.stdout.write(self.style.SUCCESS(
                        '[DRY-RUN] -> {} ({}): {} pendente(s)'.format(email, autor.nome, total)
                    ))
                    for m in materias_listadas:
                        self.stdout.write(
                            '    * {} {}/{} -- {}'.format(
                                m.tipo.sigla, m.numero, m.ano, m.ementa[:60]
                            )
                        )
                    if total_omitidas:
                        self.stdout.write('    ... e mais {} outra(s).'.format(total_omitidas))
                    continue

                # Renderiza templates
                txt_body = loader.get_template('email/pendentes_assinatura.txt').render(context)
                html_body = loader.get_template('email/pendentes_assinatura.html').render(context)

                try:
                    msg = EmailMultiAlternatives(
                        subject=subject,
                        body=txt_body,
                        from_email=EMAIL_SEND_USER,
                        to=[email],
                        connection=connection,
                    )
                    msg.attach_alternative(html_body, 'text/html')
                    msg.send()
                    enviados += 1
                    logger.info(
                        '[notificar_pendentes_assinatura] E-mail enviado para '
                        '{} ({}) -- {} pendente(s).'.format(email, autor.nome, total)
                    )
                    self.stdout.write(self.style.SUCCESS(
                        'E-mail enviado para {} ({}) -- {} pendente(s).'.format(
                            email, autor.nome, total
                        )
                    ))
                except Exception as exc:
                    logger.error(
                        '[notificar_pendentes_assinatura] Falha ao enviar para '
                        '{}: {}'.format(email, exc)
                    )
                    self.stderr.write(self.style.ERROR(
                        'Falha ao enviar para {}: {}'.format(email, exc)
                    ))

        finally:
            if connection:
                connection.close()

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                '\nConcluido: {} e-mail(s) enviado(s). '
                '{} autor(es) sem pendencias (nao notificados).'.format(
                    enviados, sem_pendencias
                )
            ))
