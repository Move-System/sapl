import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.generic import TemplateView
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from drfautoapi.drfautoapi import ApiViewSetConstrutor

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def recria_token(request, pk):
    Token.objects.filter(user_id=pk).delete()
    token = Token.objects.create(user_id=pk)

    return Response({"message": "Token recriado com sucesso!", "token": token.key})


class ApiDocView(TemplateView):
    template_name = 'api/api_doc.html'


@api_view(['GET'])
@permission_classes([])
def api_doc_data(request):
    """Retorna metadados de todos os endpoints da API para a pagina de documentacao."""
    apps_data = {}

    for app_config, models_dict in ApiViewSetConstrutor._built_sets.items():
        app_label = app_config.label
        models_data = {}

        for model, viewset_class in models_dict.items():
            model_name = model._meta.model_name

            # Determine allowed HTTP methods
            allowed = getattr(viewset_class, 'http_method_names',
                              ['get', 'post', 'put', 'patch', 'delete', 'head', 'options'])
            relevant_methods = {'get': 'GET', 'post': 'POST', 'put': 'PUT',
                                'patch': 'PATCH', 'delete': 'DELETE'}
            methods = [relevant_methods[m] for m in allowed if m in relevant_methods]

            # Discover custom @action endpoints
            actions = []
            for attr_name in dir(viewset_class):
                attr = getattr(viewset_class, attr_name, None)
                if attr and hasattr(attr, 'mapping'):
                    url_path = getattr(attr, 'url_path', attr_name)
                    detail = getattr(attr, 'detail', False)
                    action_methods = [m.upper() for m in attr.mapping.keys() if m != '']
                    if not action_methods:
                        action_methods = ['GET']

                    if detail:
                        action_url = f'{app_label}/{model_name}/{{pk}}/{url_path}/'
                    else:
                        action_url = f'{app_label}/{model_name}/{url_path}/'

                    actions.append({
                        'name': attr_name,
                        'url': action_url,
                        'detail': detail,
                        'methods': action_methods,
                    })

            models_data[model_name] = {
                'url': f'{app_label}/{model_name}',
                'methods': methods,
                'verbose_name': str(model._meta.verbose_name),
                'verbose_name_plural': str(model._meta.verbose_name_plural),
                'actions': actions,
            }

        if models_data:
            apps_data[app_label] = models_data

    return Response({'apps': apps_data})


SaplApiViewSetConstrutor = ApiViewSetConstrutor
SaplApiViewSetConstrutor.import_modules([
    'sapl.api.views_audiencia',
    'sapl.api.views_base',
    'sapl.api.views_comissoes',
    'sapl.api.views_compilacao',
    'sapl.api.views_materia',
    'sapl.api.views_norma',
    'sapl.api.views_painel',
    'sapl.api.views_parlamentares',
    'sapl.api.views_protocoloadm',
    'sapl.api.views_sessao',
])


"""
1. ApiViewSetConstrutor constroi uma rest_framework.viewsets.ModelViewSet
     para todos os models de todas as app_configs passadas no list 
2. Define DjangoFilterBackend como ferramenta de filtro dos campos
3. Define Serializer como a seguir:
    3.1   - Define um Serializer genérico para cada módel
    3.1.1 - se existir um DEFAULT_SERIALIZER_MODULE em settings,
            recupera Serializer customizados no módulo DEFAULT_SERIALIZER_MODULE
    3.2 - Para todo model é opcional a existência de {model}Serializer.
          Caso não seja definido um Serializer customizado, utiliza-se o genérico
    3.3 - Caso exista GLOBAL_SERIALIZER_MIXIN definido, 
          utiliza este Serializer para construir o genérico de 3.1
4. Define um FilterSet como a seguir:
    4.1 -   Define um FilterSet genérico para cada módel
    4.1.1 - se existir um DEFAULT_FILTER_MODULE em settings,
            recupera o FilterSet customizado no módulo DEFAULT_FILTER_MODULE
    4.2 - Para todo model é opcional a existência de {model}FilterSet.
          Caso não seja definido um FilterSet customizado, utiliza-se o genérico
    4.3 - Caso exista GLOBAL_FILTERSET_MIXIN definido, 
          utiliza este FilterSet para construir o genérico de 4.1
    4.4 - Caso não exista GLOBAL_FILTERSET_MIXIN, será aplicado 
          drfautoapi.drjautoapi.ApiFilterSetMixin que inclui parametro para:
          - order_by: através do parâmetro "o"
          - amplia os lookups aceitos pelo FilterSet default 
            para os aceitos pelo django sem a necessidade de criar 
            fields específicos em um FilterSet customizado.

5. ApiViewSetConstrutor não cria padrões e/ou exige conhecimento alem dos
    exigidos pela DRF.

6. As rotas são criadas seguindo nome da app e nome do model
    http://localhost:9000/api/{applabel}/{model_name}/
    e seguem as variações definidas em:
    https://www.django-rest-framework.org/api-guide/routers/#defaultrouter


**ApiViewSetConstrutor._built_sets** é um dict de dicts de models conforme:
    {
        ...

        'audiencia': {
            'tipoaudienciapublica': TipoAudienciaPublicaViewSet,
            'audienciapublica': AudienciaPublicaViewSet,
            'anexoaudienciapublica': AnexoAudienciaPublicaViewSet

            ...

            },

        ...

        'base': {
            'casalegislativa': CasaLegislativaViewSet,
            'appconfig': AppConfigViewSet,

            ...

        }

        ...

    }
"""
