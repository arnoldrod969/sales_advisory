from django.contrib import admin
from django import forms
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.urls import path, reverse
from django.shortcuts import redirect, render
from django.contrib import messages
from django.contrib.admin.helpers import ActionForm
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
import os
from pathlib import Path
import zipfile

from .models import (
    Famille, SousFamille, Article,
    Problematique, ClasseSociale, Recommandation,
    PointDeVente, ConseilEffectue, ConseilArticle,
    ImportCatalogue, AffectationPDV,
)

# ─── En-tête admin ────────────────────────────────────────────────────────────
admin.site.site_header = 'JD Cosmetics — Outil conseil vente'
admin.site.site_title  = 'Admin JD Conseil'
admin.site.index_title = 'Tableau de bord'


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def badge(texte, couleur):
    """Génère un badge coloré HTML pour les list_display."""
    couleurs = {
        'vert':   ('#d4edda', '#155724'),
        'rouge':  ('#f8d7da', '#721c24'),
        'orange': ('#fff3cd', '#856404'),
        'gris':   ('#e2e3e5', '#383d41'),
        'bleu':   ('#cce5ff', '#004085'),
    }
    bg, fg = couleurs.get(couleur, couleurs['gris'])
    return format_html(
        '<span style="background:{};color:{};padding:2px 8px;border-radius:12px;'
        'font-size:11px;font-weight:500">{}</span>',
        bg, fg, texte
    )


def get_article_image_url(article):
    """Construit l'URL d'image article en testant les extensions disponibles."""
    if getattr(article, 'image_upload', None):
        try:
            return article.image_upload.url
        except ValueError:
            pass

    if not article.image_nom:
        return None

    images_dir = getattr(settings, 'NIRGESCOM_IMAGES_DIR', None)
    images_url = getattr(settings, 'NIRGESCOM_IMAGES_URL', '/media/nirgescom/')
    extensions = getattr(settings, 'NIRGESCOM_IMAGE_EXTENSIONS', ['.jpg', '.JPG', '.png', '.PNG'])

    nom = article.image_nom
    for ext in extensions:
        if nom.lower().endswith(ext.lower()):
            return f'{images_url.rstrip("/")}/{nom}'

    if images_dir:
        for ext in extensions:
            chemin = os.path.join(images_dir, f'{nom}{ext}')
            if os.path.exists(chemin):
                return f'{images_url.rstrip("/")}/{nom}{ext}'

    return None


# ─── CATALOGUE ────────────────────────────────────────────────────────────────

class SousFamilleInline(admin.TabularInline):
    model       = SousFamille
    extra       = 0
    fields      = ('code', 'nom', 'actif')
    readonly_fields = ('code',)
    can_delete  = False
    show_change_link = True


@admin.register(Famille)
class FamilleAdmin(admin.ModelAdmin):
    list_display  = ('code', 'nom', 'nb_sous_familles', 'nb_articles')
    search_fields = ('code', 'nom')
    ordering      = ('code',)
    inlines       = [SousFamilleInline]

    def nb_sous_familles(self, obj):
        n = obj.sous_familles.count()
        return format_html('<b>{}</b>', n)
    nb_sous_familles.short_description = 'Sous-familles'

    def nb_articles(self, obj):
        n = Article.objects.filter(sous_famille__famille=obj).count()
        return n
    nb_articles.short_description = 'Articles'


@admin.register(SousFamille)
class SousFamilleAdmin(admin.ModelAdmin):
    list_display  = ('code', 'nom', 'famille', 'nb_articles', 'statut_actif')
    list_filter   = ('famille', 'actif')
    search_fields = ('code', 'nom', 'famille__nom')
    ordering      = ('code',)

    def nb_articles(self, obj):
        return obj.articles.filter(actif=True).count()
    nb_articles.short_description = 'Articles actifs'

    def statut_actif(self, obj):
        return badge('Actif', 'vert') if obj.actif else badge('Inactif', 'gris')
    statut_actif.short_description = 'Statut'


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    change_list_template = 'admin/conseil_vente/article/change_list.html'
    list_display   = (
        'ref_nirgescom', 'designation_tronquee', 'sous_famille',
        'prix_vente_fcfa', 'apercu_image', 'statut_actif'
    )
    list_filter    = ('actif', 'sous_famille__famille', 'sous_famille')
    search_fields  = ('ref_nirgescom', 'designation')
    ordering       = ('designation',)
    actions        = ('supprimer_articles_selectionnes',)
    readonly_fields = (
        'ref_nirgescom', 'date_import', 'apercu_image_detail',
        'prix_achat_affiche', 'prix_revient_affiche'
    )

    fieldsets = (
        ('Identification', {
            'fields': ('ref_nirgescom', 'designation', 'sous_famille', 'actif')
        }),
        ('Prix', {
            'fields': ('prix_detail', 'prix_achat_affiche', 'prix_revient_affiche'),
            'description': '⚠️ Prix d\'achat et de revient visibles uniquement par les administrateurs.'
        }),
        ('Image', {
            'fields': ('image_nom', 'image_upload', 'apercu_image_detail'),
            'description': 'Téléversez une image ici ou utilisez l\'outil d\'upload groupé depuis la liste des articles.'
        }),
        ('Métadonnées', {
            'fields': ('date_import',),
            'classes': ('collapse',)
        }),
    )

    def get_fieldsets(self, request, obj=None):
        """Masque les prix sensibles pour les non-superusers."""
        fieldsets = super().get_fieldsets(request, obj)
        if not request.user.is_superuser:
            return [
                (name, opts) for name, opts in fieldsets
                if name != 'Prix' or True  # on garde Prix mais on cache les champs sensibles
            ]
        return fieldsets

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj:
            readonly += ['ref_nirgescom']
        if not request.user.is_superuser:
            readonly += ['prix_achat_affiche', 'prix_revient_affiche']
        return readonly

    def designation_tronquee(self, obj):
        d = obj.designation
        return d[:60] + '…' if len(d) > 60 else d
    designation_tronquee.short_description = 'Désignation'

    def prix_vente_fcfa(self, obj):
        montant = f'{int(obj.prix_detail):,}'.replace(',', ' ')
        return format_html('<b>{} FCFA</b>', montant)
    prix_vente_fcfa.short_description = 'Prix vente'

    def prix_achat_affiche(self, obj):
        if obj.prix_achat:
            montant = f'{int(obj.prix_achat):,}'.replace(',', ' ')
            return format_html('{} FCFA', montant)
        return '—'
    prix_achat_affiche.short_description = 'Prix achat (confidentiel)'

    def prix_revient_affiche(self, obj):
        if obj.prix_revient:
            montant = f'{int(obj.prix_revient):,}'.replace(',', ' ')
            return format_html('{} FCFA', montant)
        return '—'
    prix_revient_affiche.short_description = 'Prix revient (confidentiel)'

    def apercu_image(self, obj):
        if not obj.image_nom and not obj.image_upload:
            return '—'
        img_url = self._get_image_url(obj)
        if img_url:
            return format_html(
                '<img src="{}" style="height:36px;width:36px;object-fit:cover;'
                'border-radius:4px;border:1px solid #dee2e6">',
                img_url
            )
        return format_html(
            '<span style="font-size:11px;color:#6c757d">{}</span>',
            obj.image_nom[:15]
        )
    apercu_image.short_description = 'Image'

    def apercu_image_detail(self, obj):
        if not obj.image_nom and not obj.image_upload:
            return 'Aucune image'
        img_url = self._get_image_url(obj)
        if img_url:
            return format_html(
                '<img src="{}" style="max-height:200px;max-width:200px;'
                'object-fit:contain;border-radius:8px;border:1px solid #dee2e6;padding:4px">',
                img_url
            )
        return format_html('Fichier : <code>{}</code> (image non trouvée dans le répertoire)', obj.image_nom or 'upload indisponible')
    apercu_image_detail.short_description = 'Aperçu image'

    def _get_image_url(self, obj):
        return get_article_image_url(obj)

    def statut_actif(self, obj):
        return badge('Actif', 'vert') if obj.actif else badge('Inactif', 'gris')
    statut_actif.short_description = 'Statut'

    def supprimer_articles_selectionnes(self, request, queryset):
        nb = queryset.count()
        if nb == 0:
            self.message_user(request, 'Aucun article sélectionné.', level=messages.WARNING)
            return

        with transaction.atomic():
            queryset.delete()

        self.message_user(request, f'{nb} article(s) supprimé(s) avec succès.', level=messages.SUCCESS)
    supprimer_articles_selectionnes.short_description = 'Supprimer les articles sélectionnés'

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'supprimer-catalogue/',
                self.admin_site.admin_view(self.supprimer_catalogue_view),
                name='conseil_vente_article_supprimer_catalogue',
            ),
            path(
                'upload-images/',
                self.admin_site.admin_view(self.upload_images_view),
                name='conseil_vente_article_upload_images',
            ),
        ]
        return custom + urls

    def supprimer_catalogue_view(self, request: HttpRequest):
        """Supprime tout le catalogue article apres confirmation explicite."""
        context = {
            **self.admin_site.each_context(request),
            'title': 'Suppression massive du catalogue',
            'opts': self.model._meta,
        }

        if request.method == 'POST':
            confirmation = request.POST.get('confirmation', '').strip().upper()
            if confirmation != 'SUPPRIMER':
                self.message_user(
                    request,
                    'Tapez SUPPRIMER pour confirmer la suppression massive du catalogue.',
                    level=messages.WARNING,
                )
                return render(request, 'admin/conseil_vente/article/supprimer_catalogue.html', context)

            nb = Article.objects.count()
            with transaction.atomic():
                Article.objects.all().delete()

            self.message_user(request, f'{nb} article(s) supprimé(s) du catalogue.', level=messages.SUCCESS)
            return redirect('admin:conseil_vente_article_changelist')

        return render(request, 'admin/conseil_vente/article/supprimer_catalogue.html', context)

    def upload_images_view(self, request: HttpRequest):
        """Associe en lot des images aux articles via image_nom ou reference article."""
        context = {
            **self.admin_site.each_context(request),
            'title': 'Upload groupé des images articles',
            'opts': self.model._meta,
            'upload_url': reverse('admin:conseil_vente_article_upload_images'),
        }

        if request.method == 'POST':
            fichiers = request.FILES.getlist('images')
            archive = request.FILES.get('archive_zip')
            if not fichiers and archive is None:
                self.message_user(request, 'Sélectionnez des images ou un fichier ZIP.', level=messages.WARNING)
                return render(request, 'admin/conseil_vente/article/upload_images.html', context)

            articles = list(Article.objects.all())
            index_image_nom = {}
            index_ref = {}

            for article in articles:
                if article.image_nom:
                    stem = Path(article.image_nom).stem.strip().lower()
                    if stem:
                        index_image_nom.setdefault(stem, article)
                ref = article.ref_nirgescom.strip().lower().rstrip('-')
                if ref:
                    index_ref.setdefault(ref, article)

            uploads = []
            uploads.extend((fichier.name, fichier) for fichier in fichiers)

            if archive is not None:
                if not archive.name.lower().endswith('.zip'):
                    self.message_user(request, 'Le fichier archive doit être au format .zip.', level=messages.ERROR)
                    return render(request, 'admin/conseil_vente/article/upload_images.html', context)
                try:
                    with zipfile.ZipFile(archive) as zf:
                        for info in zf.infolist():
                            if info.is_dir():
                                continue
                            nom = Path(info.filename).name
                            if not nom:
                                continue
                            suffixe = Path(nom).suffix.lower()
                            if suffixe not in {'.jpg', '.jpeg', '.png'}:
                                continue
                            uploads.append((nom, ContentFile(zf.read(info.filename), name=nom)))
                except zipfile.BadZipFile:
                    self.message_user(request, 'Archive ZIP invalide.', level=messages.ERROR)
                    return render(request, 'admin/conseil_vente/article/upload_images.html', context)

            traites = 0
            sans_match = []
            doublons = []
            deja_vus = set()

            for nom_fichier, fichier in uploads:
                stem = Path(nom_fichier).stem.strip().lower()
                if stem in deja_vus:
                    doublons.append(nom_fichier)
                    continue
                deja_vus.add(stem)

                article = index_image_nom.get(stem) or index_ref.get(stem)
                if article is None:
                    sans_match.append(nom_fichier)
                    continue

                if article.image_upload:
                    try:
                        if default_storage.exists(article.image_upload.name):
                            default_storage.delete(article.image_upload.name)
                    except Exception:
                        pass

                article.image_upload.save(nom_fichier, fichier, save=True)
                traites += 1

            if traites:
                self.message_user(request, f'{traites} image(s) associée(s) avec succès.', level=messages.SUCCESS)
            if sans_match:
                apercu = ', '.join(sans_match[:8])
                suffixe = '' if len(sans_match) <= 8 else f' ... (+{len(sans_match) - 8})'
                self.message_user(
                    request,
                    f'Aucune correspondance trouvée pour : {apercu}{suffixe}',
                    level=messages.WARNING,
                )
            if doublons:
                apercu = ', '.join(doublons[:8])
                suffixe = '' if len(doublons) <= 8 else f' ... (+{len(doublons) - 8})'
                self.message_user(
                    request,
                    f'Fichiers dupliqués ignorés : {apercu}{suffixe}',
                    level=messages.WARNING,
                )

            return redirect('admin:conseil_vente_article_upload_images')

        return render(request, 'admin/conseil_vente/article/upload_images.html', context)


# ─── CONSEIL ─────────────────────────────────────────────────────────────────

@admin.register(Problematique)
class ProblematiqueAdmin(admin.ModelAdmin):
    list_display  = ('icone', 'libelle', 'ordre', 'nb_recommandations')
    search_fields = ('libelle',)
    ordering      = ('ordre', 'libelle')

    def nb_recommandations(self, obj):
        return obj.recommandations.count()
    nb_recommandations.short_description = 'Recommandations'


@admin.register(ClasseSociale)
class ClasseSocialeAdmin(admin.ModelAdmin):
    list_display = ('libelle', 'ordre', 'description')
    ordering     = ('ordre',)


class RecommandationInline(admin.TabularInline):
    model   = Recommandation
    extra   = 3
    fields  = ('article', 'ordre')
    ordering = ('ordre',)
    autocomplete_fields = ('article',)


@admin.register(Recommandation)
class RecommandationAdmin(admin.ModelAdmin):
    change_list_template = 'admin/conseil_vente/recommandation/change_list.html'
    list_display        = ('problematique', 'classe_sociale', 'article_nom', 'article_prix', 'ordre')
    list_filter         = ('problematique', 'classe_sociale')
    search_fields       = ('article__designation', 'problematique__libelle')
    ordering            = ('problematique', 'classe_sociale', 'ordre')
    autocomplete_fields = ('article',)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'affectation-multiple/',
                self.admin_site.admin_view(self.affectation_multiple_view),
                name='conseil_vente_recommandation_affectation_multiple',
            ),
        ]
        return custom + urls

    def affectation_multiple_view(self, request: HttpRequest):
        """Permet d'affecter plusieurs produits a une combinaison problematique x classe sociale."""
        problematiques = Problematique.objects.order_by('ordre', 'libelle')
        classes_sociales = ClasseSociale.objects.order_by('ordre', 'libelle')
        familles = Famille.objects.order_by('code')
        sous_familles = SousFamille.objects.select_related('famille').filter(actif=True).order_by('code')

        problematique_id = request.POST.get('problematique_id') or request.GET.get('problematique_id')
        classe_sociale_id = request.POST.get('classe_sociale_id') or request.GET.get('classe_sociale_id')

        recommandations_existantes = []
        articles_payload = []
        resume_selection = None

        if problematique_id and classe_sociale_id:
            resume_selection = {
                'problematique': Problematique.objects.filter(pk=problematique_id).first(),
                'classe_sociale': ClasseSociale.objects.filter(pk=classe_sociale_id).first(),
            }

            recommandations_existantes = list(
                Recommandation.objects
                .filter(
                    problematique_id=problematique_id,
                    classe_sociale_id=classe_sociale_id,
                )
                .select_related('article__sous_famille__famille')
                .order_by('ordre', 'article__designation')
            )

            articles = (
                Article.objects
                .filter(actif=True)
                .select_related('sous_famille__famille')
                .order_by('designation')
            )
            articles_selectionnes = {recommandation.article_id for recommandation in recommandations_existantes}

            for article in articles:
                articles_payload.append({
                    'id': article.id,
                    'designation': article.designation,
                    'ref_nirgescom': article.ref_nirgescom,
                    'prix_detail': f'{int(article.prix_detail):,}'.replace(',', ' '),
                    'famille_id': article.sous_famille.famille_id if article.sous_famille else '',
                    'famille_nom': article.sous_famille.famille.nom if article.sous_famille else 'Sans famille',
                    'sous_famille_id': article.sous_famille_id or '',
                    'sous_famille_nom': article.sous_famille.nom if article.sous_famille else 'Sans sous-famille',
                    'image_url': get_article_image_url(article),
                    'selectionne': article.id in articles_selectionnes,
                })

        if request.method == 'POST':
            if not problematique_id or not classe_sociale_id:
                self.message_user(
                    request,
                    'Sélectionnez une problématique et une classe sociale.',
                    level=messages.WARNING,
                )
            else:
                article_ids = []
                for value in request.POST.getlist('article_ids'):
                    try:
                        article_ids.append(int(value))
                    except (TypeError, ValueError):
                        continue

                with transaction.atomic():
                    Recommandation.objects.filter(
                        problematique_id=problematique_id,
                        classe_sociale_id=classe_sociale_id,
                    ).delete()

                    Recommandation.objects.bulk_create([
                        Recommandation(
                            problematique_id=problematique_id,
                            classe_sociale_id=classe_sociale_id,
                            article_id=article_id,
                            ordre=index,
                        )
                        for index, article_id in enumerate(article_ids, start=1)
                    ])

                self.message_user(
                    request,
                    f'{len(article_ids)} produit(s) enregistrés pour cette combinaison.',
                    level=messages.SUCCESS,
                )
                return redirect(
                    f'{reverse("admin:conseil_vente_recommandation_affectation_multiple")}'
                    f'?problematique_id={problematique_id}&classe_sociale_id={classe_sociale_id}'
                )

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': 'Affectation multiple des recommandations',
            'problematiques': problematiques,
            'classes_sociales': classes_sociales,
            'familles': familles,
            'sous_familles': sous_familles,
            'problematique_id': str(problematique_id or ''),
            'classe_sociale_id': str(classe_sociale_id or ''),
            'articles': articles_payload,
            'recommandations_existantes': recommandations_existantes,
            'resume_selection': resume_selection,
        }
        return render(request, 'admin/conseil_vente/recommandation/affectation_multiple.html', context)

    def article_nom(self, obj):
        return obj.article.designation[:50]
    article_nom.short_description = 'Article'

    def article_prix(self, obj):
        montant = f'{int(obj.article.prix_detail):,}'.replace(',', ' ')
        return format_html('{} FCFA', montant)
    article_prix.short_description = 'Prix'


# ─── POINTS DE VENTE ─────────────────────────────────────────────────────────

class AffectationPDVHistoriqueInline(admin.TabularInline):
    model = AffectationPDV
    extra = 0
    fields = ('point_de_vente', 'date_debut', 'date_fin', 'actif')
    readonly_fields = ('point_de_vente', 'date_debut', 'date_fin', 'actif')
    can_delete = False
    show_change_link = True
    ordering = ('-date_debut',)
    verbose_name = 'Historique d\'affectation'
    verbose_name_plural = 'Historique des affectations'

    def has_add_permission(self, request, obj=None):
        return False


class UtilisateursActuelsPDVInline(admin.TabularInline):
    model = AffectationPDV
    fk_name = 'point_de_vente'
    extra = 0
    fields = ('user', 'date_debut')
    readonly_fields = ('user', 'date_debut')
    can_delete = False
    verbose_name = 'Utilisateur actuellement affecte'
    verbose_name_plural = 'Utilisateurs actuellement affectes'

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(actif=True, date_fin__isnull=True)
            .select_related('user')
        )

    def has_add_permission(self, request, obj=None):
        return False


class AffectationPDVActionForm(ActionForm):
    point_de_vente = forms.ModelChoiceField(
        queryset=PointDeVente.objects.none(),
        required=False,
        label='Nouveau point de vente',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['point_de_vente'].queryset = PointDeVente.objects.filter(actif=True).order_by('nom')


@admin.register(AffectationPDV)
class AffectationPDVAdmin(admin.ModelAdmin):
    list_display = ('user', 'point_de_vente', 'date_debut', 'date_fin', 'statut_affectation')
    list_filter = ('actif', 'point_de_vente', 'date_debut')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'point_de_vente__nom')
    autocomplete_fields = ('user', 'point_de_vente')
    ordering = ('-date_debut', '-id')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'point_de_vente')

    def statut_affectation(self, obj):
        if obj.actif and obj.date_fin is None:
            return badge('Active', 'vert')
        return badge('Cloturee', 'gris')
    statut_affectation.short_description = 'Statut'

@admin.register(PointDeVente)
class PointDeVenteAdmin(admin.ModelAdmin):
    list_display = ('nom', 'ville', 'nb_conseils', 'statut_actif')
    search_fields = ('nom', 'ville')
    list_editable = ('actif',) if False else ()  # activé manuellement si besoin
    inlines = [UtilisateursActuelsPDVInline]

    def nb_conseils(self, obj):
        return obj.conseils.count()
    nb_conseils.short_description = 'Conseils tracés'

    def statut_actif(self, obj):
        return badge('Actif', 'vert') if obj.actif else badge('Inactif', 'gris')
    statut_actif.short_description = 'Statut'


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    inlines = [AffectationPDVHistoriqueInline]
    actions = ['affecter_a_un_nouveau_pdv']
    action_form = AffectationPDVActionForm

    def affecter_a_un_nouveau_pdv(self, request, queryset):
        pdv_id = request.POST.get('point_de_vente')
        if not pdv_id:
            self.message_user(
                request,
                "Selectionnez d'abord un point de vente dans la liste d'actions.",
                level=messages.WARNING,
            )
            return

        pdv = PointDeVente.objects.filter(pk=pdv_id, actif=True).first()
        if pdv is None:
            self.message_user(
                request,
                "Le point de vente selectionne est introuvable ou inactif.",
                level=messages.ERROR,
            )
            return

        compteur = 0
        for user in queryset:
            AffectationPDV.affecter(user, pdv)
            compteur += 1

        self.message_user(
            request,
            f"{compteur} utilisateur(s) affecte(s) a {pdv.nom}.",
            level=messages.SUCCESS,
        )
    affecter_a_un_nouveau_pdv.short_description = 'Affecter a un nouveau PDV'


class ConseilArticleInline(admin.TabularInline):
    model     = ConseilArticle
    extra     = 0
    fields    = ('article',)
    readonly_fields = ('article',)
    can_delete = False


@admin.register(ConseilEffectue)
class ConseilEffectueAdmin(admin.ModelAdmin):
    list_display    = (
        'date_conseil', 'point_de_vente', 'problematique',
        'classe_sociale', 'nb_articles_conseilles', 'statut_synchro'
    )
    list_filter     = ('point_de_vente', 'problematique', 'classe_sociale', 'synchronise')
    search_fields   = ('point_de_vente__nom', 'compte_generique')
    readonly_fields = ('date_conseil', 'point_de_vente', 'problematique',
                       'classe_sociale', 'compte_generique', 'synchronise')
    inlines         = [ConseilArticleInline]

    def has_add_permission(self, request):
        return False  # Les conseils sont créés par l'interface vendeur uniquement

    def nb_articles_conseilles(self, obj):
        return obj.articles.count()
    nb_articles_conseilles.short_description = 'Produits présentés'

    def statut_synchro(self, obj):
        if obj.synchronise:
            return badge('Synchronisé', 'vert')
        return badge('Hors ligne', 'orange')
    statut_synchro.short_description = 'Synchro'


# ─── IMPORT CATALOGUE ────────────────────────────────────────────────────────

@admin.register(ImportCatalogue)
class ImportCatalogueAdmin(admin.ModelAdmin):
    change_list_template = 'admin/conseil_vente/importcatalogue/change_list.html'
    list_display    = (
        'date_import', 'nom_fichier', 'source_badge',
        'statut_badge', 'nb_articles_total',
        'nb_articles_crees', 'nb_articles_mis_a_jour',
        'nb_articles_ignores', 'importe_par'
    )
    list_filter     = ('statut', 'source')
    readonly_fields = (
        'nom_fichier', 'source', 'statut', 'nb_articles_total',
        'nb_articles_crees', 'nb_articles_mis_a_jour', 'nb_articles_ignores',
        'erreurs', 'date_import', 'importe_par', 'detail_erreurs'
    )
    ordering        = ('-date_import',)

    def has_add_permission(self, request):
        return False  # L'import se lance depuis la vue dédiée

    def has_change_permission(self, request, obj=None):
        return False  # Logs en lecture seule

    def source_badge(self, obj):
        couleurs = {'nirgescom': 'bleu', 'odoo': 'vert', 'manuel': 'gris'}
        return badge(obj.get_source_display(), couleurs.get(obj.source, 'gris'))
    source_badge.short_description = 'Source'

    def statut_badge(self, obj):
        couleurs = {
            'en_cours': 'orange',
            'succes':   'vert',
            'erreur':   'rouge',
            'partiel':  'orange',
        }
        return badge(obj.get_statut_display(), couleurs.get(obj.statut, 'gris'))
    statut_badge.short_description = 'Statut'

    def detail_erreurs(self, obj):
        if not obj.erreurs:
            return 'Aucune erreur'
        lignes = obj.erreurs.split('\n')
        html   = '<br>'.join(f'<code style="font-size:11px">{l}</code>' for l in lignes[:20])
        if len(lignes) > 20:
            html += f'<br><em>... et {len(lignes)-20} autres erreurs</em>'
        return mark_safe(html)
    detail_erreurs.short_description = 'Détail des erreurs'

    # ── Vue d'import personnalisée ────────────────────────────────────────────
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'lancer-import/',
                self.admin_site.admin_view(self.vue_import),
                name='conseil_vente_import_catalogue'
            ),
        ]
        return custom + urls

    def vue_import(self, request: HttpRequest):
        """
        Vue simple qui lance l'import depuis un formulaire dans l'admin.
        Accessible via le bouton 'Importer catalogue' sur la liste.
        """
        from django.shortcuts import render

        context = {
            **self.admin_site.each_context(request),
            'title':          'Importer le catalogue Nirgescom',
            'opts':           self.model._meta,
            'nirgescom_dir':  getattr(settings, 'NIRGESCOM_IMAGES_DIR', 'Non configuré'),
            'repertoire_images_override': '',
        }

        if request.method == 'POST' and request.FILES.get('fichier_xls'):
            import tempfile, shutil
            from pathlib import Path

            fichier = request.FILES['fichier_xls']
            fichier_sf = request.FILES.get('fichier_sf')
            repertoire_images_override = request.POST.get('repertoire_images_override', '').strip()
            context['repertoire_images_override'] = repertoire_images_override

            # Sauvegarder temporairement les fichiers uploadés
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xls') as tmp_xls:
                for chunk in fichier.chunks():
                    tmp_xls.write(chunk)
                chemin_xls = tmp_xls.name

            chemin_sf = None
            if fichier_sf:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as tmp_sf:
                    for chunk in fichier_sf.chunks():
                        tmp_sf.write(chunk)
                    chemin_sf = tmp_sf.name

            try:
                from scripts.import_nirgescom import lancer_import, importer_articles, charger_sous_familles

                images_dir = repertoire_images_override or getattr(settings, 'NIRGESCOM_IMAGES_DIR', None)

                if chemin_sf:
                    from scripts.import_nirgescom import importer_familles_et_sous_familles
                    index_sf = importer_familles_et_sous_familles(chemin_sf)
                else:
                    index_sf = charger_sous_familles()

                bilan = importer_articles(
                    chemin_xls=chemin_xls,
                    index_sf=index_sf,
                    repertoire_images=images_dir,
                    importe_par=request.user.username,
                )

                msg = (
                    f'Import terminé — {bilan.nb_articles_crees} créés, '
                    f'{bilan.nb_articles_mis_a_jour} mis à jour, '
                    f'{bilan.nb_articles_ignores} ignorés.'
                )
                niveau = messages.SUCCESS if bilan.statut == 'succes' else messages.WARNING
                self.message_user(request, msg, niveau)

            except Exception as e:
                self.message_user(request, f'Erreur lors de l\'import : {e}', messages.ERROR)
            finally:
                os.unlink(chemin_xls)
                if chemin_sf and os.path.exists(chemin_sf):
                    os.unlink(chemin_sf)

            return redirect(
                reverse('admin:conseil_vente_importcatalogue_changelist')
            )

        return render(request, 'admin/conseil_vente/import_catalogue.html', context)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['import_url'] = reverse('admin:conseil_vente_import_catalogue')
        return super().changelist_view(request, extra_context=extra_context)
