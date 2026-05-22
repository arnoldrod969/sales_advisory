from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.db.models import Count
from django.urls import reverse
import json
import os

from .models import (
    Problematique, ClasseSociale, Recommandation,
    PointDeVente, ConseilEffectue, ConseilArticle, Article, AffectationPDV
)


def _get_image_url(image_nom):
    """Résout l'URL d'une image article depuis son nom de base."""
    if not image_nom:
        return None
    images_url  = getattr(settings, 'NIRGESCOM_IMAGES_URL', '/media/nirgescom/')
    images_dir  = getattr(settings, 'NIRGESCOM_IMAGES_DIR', None)
    extensions  = getattr(settings, 'NIRGESCOM_IMAGE_EXTENSIONS',
                          ['.jpg', '.JPG', '.png', '.PNG'])

    for ext in extensions:
        if image_nom.lower().endswith(ext.lower()):
            return f'{images_url.rstrip("/")}/{image_nom}'

    if images_dir:
        for ext in extensions:
            if os.path.exists(os.path.join(images_dir, f'{image_nom}{ext}')):
                return f'{images_url.rstrip("/")}/{image_nom}{ext}'

    return None


def _get_article_image_url(article):
    """Priorise l'image téléversée, sinon retombe sur l'image Nirgescom."""
    if getattr(article, 'image_upload', None):
        try:
            return article.image_upload.url
        except ValueError:
            pass
    return _get_image_url(article.image_nom)


def _utilisateur_peut_choisir_pdv(user):
    """Retourne True si l'utilisateur peut choisir manuellement un PDV."""
    return user.is_staff or user.is_superuser


@login_required
def interface_vendeur(request):
    """Page principale de l'interface vendeur."""
    try:
        pdv_id = request.session.get('point_de_vente_id')
    except Exception:
        pdv_id = None

    point_de_vente = None
    if pdv_id:
        point_de_vente = PointDeVente.objects.filter(id=pdv_id, actif=True).first()

    if _utilisateur_peut_choisir_pdv(request.user) and point_de_vente is None:
        return redirect('conseil_vente:choisir_pdv')

    if not _utilisateur_peut_choisir_pdv(request.user) and point_de_vente is None:
        return redirect('conseil_vente:non_affecte')

    problematiques = Problematique.objects.filter(
        recommandations__isnull=False
    ).distinct().order_by('ordre', 'libelle')

    classes_sociales = ClasseSociale.objects.all().order_by('ordre')

    context = {
        'problematiques':  problematiques,
        'classes_sociales': classes_sociales,
        'point_de_vente':  point_de_vente,
    }
    return render(request, 'conseil_vente/interface_vendeur.html', context)


@login_required
def choisir_pdv(request):
    """Permet a un administrateur de choisir le point de vente actif de sa session."""
    if not _utilisateur_peut_choisir_pdv(request.user):
        pdv = AffectationPDV.get_pdv_actif(request.user)
        if pdv is not None:
            try:
                request.session['point_de_vente_id'] = pdv.id
            except Exception:
                pass
        return redirect('conseil_vente:interface')

    if request.method == 'POST':
        pdv = get_object_or_404(
            PointDeVente.objects.filter(actif=True),
            pk=request.POST.get('point_de_vente_id'),
        )
        try:
            request.session['point_de_vente_id'] = pdv.id
        except Exception:
            pass
        return redirect('conseil_vente:interface')

    try:
        pdv_actuel_id = request.session.get('point_de_vente_id')
    except Exception:
        pdv_actuel_id = None

    context = {
        'points_de_vente': PointDeVente.objects.filter(actif=True).order_by('nom'),
        'pdv_actuel_id': pdv_actuel_id,
    }
    return render(request, 'conseil_vente/choisir_pdv.html', context)


@login_required
def non_affecte(request):
    """Affiche un message clair si le vendeur n'a aucune affectation active."""
    return render(request, 'conseil_vente/non_affecte.html', status=403)


@login_required
@require_GET
def api_recommandations(request):
    """
    API JSON — retourne les articles recommandés pour une
    combinaison problématique × classe sociale.
    """
    pb_id = request.GET.get('problematique_id')
    cs_id = request.GET.get('classe_sociale_id')

    if not pb_id or not cs_id:
        return JsonResponse({'erreur': 'Paramètres manquants'}, status=400)

    recos = (
        Recommandation.objects
        .filter(
            problematique_id=pb_id,
            classe_sociale_id=cs_id,
            article__actif=True
        )
        .select_related('article__sous_famille__famille')
        .order_by('ordre')
    )

    articles = []
    for reco in recos:
        a = reco.article
        articles.append({
            'id':           a.id,
            'ref':          a.ref_nirgescom,
            'nom':          a.designation,
            'prix':         int(a.prix_detail),
            'sous_famille': str(a.sous_famille) if a.sous_famille else '',
            'image_url':    _get_article_image_url(a),
        })

    return JsonResponse({'articles': articles})


@login_required
@require_GET
def api_recommandation_counts(request):
    """Retourne le nombre de produits recommandes par classe sociale pour une problematique."""
    pb_id = request.GET.get('problematique_id')
    if not pb_id:
        return JsonResponse({'erreur': 'Paramètre problematique_id manquant'}, status=400)

    counts = {
        str(item['classe_sociale_id']): item['total']
        for item in (
            Recommandation.objects
            .filter(problematique_id=pb_id, article__actif=True)
            .values('classe_sociale_id')
            .annotate(total=Count('id'))
        )
    }
    return JsonResponse({'counts': counts})


@login_required
@require_POST
def api_enregistrer_conseil(request):
    """
    API JSON — enregistre un conseil effectué en base.
    Corps attendu :
    {
      "problematique_id": 1,
      "classe_sociale_id": 2,
      "article_ids": [10, 15, 22],
      "point_de_vente_id": 3,   // optionnel si en session
      "hors_ligne": false
    }
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'erreur': 'JSON invalide'}, status=400)

    pb_id  = data.get('problematique_id')
    cs_id  = data.get('classe_sociale_id')
    art_ids = data.get('article_ids', [])
    pdv_id = data.get('point_de_vente_id') or request.session.get('point_de_vente_id')
    hors_ligne = data.get('hors_ligne', False)

    if not pb_id or not cs_id or not pdv_id:
        return JsonResponse({'erreur': 'Champs obligatoires manquants'}, status=400)

    try:
        pdv  = PointDeVente.objects.get(id=pdv_id, actif=True)
        pb   = Problematique.objects.get(id=pb_id)
        cs   = ClasseSociale.objects.get(id=cs_id)
    except (PointDeVente.DoesNotExist, Problematique.DoesNotExist, ClasseSociale.DoesNotExist) as e:
        return JsonResponse({'erreur': str(e)}, status=404)

    conseil = ConseilEffectue.objects.create(
        point_de_vente=pdv,
        problematique=pb,
        classe_sociale=cs,
        compte_generique=request.user.username,
        synchronise=not hors_ligne,
    )

    # Lier les articles présentés
    articles = Article.objects.filter(id__in=art_ids, actif=True)
    ConseilArticle.objects.bulk_create([
        ConseilArticle(conseil=conseil, article=a)
        for a in articles
    ])

    return JsonResponse({
        'succes':     True,
        'conseil_id': conseil.id,
        'nb_articles': articles.count(),
        'print_url': reverse('conseil_vente:imprimer_conseil', args=[conseil.id]),
    })


@login_required
@require_POST
def api_sync_hors_ligne(request):
    """
    Synchronise les conseils créés hors ligne et stockés localement.
    Corps attendu : {"conseils": [ {...}, {...} ]}
    Même structure que api_enregistrer_conseil pour chaque item.
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'erreur': 'JSON invalide'}, status=400)

    conseils_data = data.get('conseils', [])
    syncs_ok  = 0
    syncs_ko  = 0

    for item in conseils_data:
        try:
            pdv = PointDeVente.objects.get(
                id=item['point_de_vente_id'], actif=True
            )
            pb  = Problematique.objects.get(id=item['problematique_id'])
            cs  = ClasseSociale.objects.get(id=item['classe_sociale_id'])

            conseil = ConseilEffectue.objects.create(
                point_de_vente=pdv,
                problematique=pb,
                classe_sociale=cs,
                compte_generique=request.user.username,
                synchronise=True,
            )
            articles = Article.objects.filter(
                id__in=item.get('article_ids', []), actif=True
            )
            ConseilArticle.objects.bulk_create([
                ConseilArticle(conseil=conseil, article=a)
                for a in articles
            ])
            syncs_ok += 1
        except Exception:
            syncs_ko += 1

    return JsonResponse({'syncs_ok': syncs_ok, 'syncs_ko': syncs_ko})


@login_required
@require_GET
def imprimer_conseil(request, conseil_id):
    """Affiche un bon de commande imprimable pour un conseil validé."""
    conseil = get_object_or_404(
        ConseilEffectue.objects.select_related(
            'point_de_vente', 'problematique', 'classe_sociale'
        ).prefetch_related('articles__article__sous_famille__famille'),
        pk=conseil_id,
    )

    articles = [
        item.article
        for item in conseil.articles.all()
    ]
    total = sum(int(article.prix_detail) for article in articles)

    context = {
        'conseil': conseil,
        'articles': articles,
        'total': total,
    }
    return render(request, 'conseil_vente/imprimer_conseil.html', context)
