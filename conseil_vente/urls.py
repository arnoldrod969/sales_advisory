from django.urls import path
from . import views

app_name = 'conseil_vente'

urlpatterns = [
    path('',                        views.interface_vendeur,        name='interface'),
    path('choisir-pdv/',            views.choisir_pdv,              name='choisir_pdv'),
    path('non-affecte/',            views.non_affecte,              name='non_affecte'),
    path('conseils/<int:conseil_id>/imprimer/', views.imprimer_conseil, name='imprimer_conseil'),
    path('api/recommandations/',    views.api_recommandations,      name='api_recommandations'),
    path('api/recommandations/counts/', views.api_recommandation_counts, name='api_recommandation_counts'),
    path('api/conseil/',            views.api_enregistrer_conseil,  name='api_conseil'),
    path('api/sync/',               views.api_sync_hors_ligne,      name='api_sync'),
]
