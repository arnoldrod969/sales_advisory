from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.core.validators import MinValueValidator
from django.db.models import Q
from django.utils import timezone


# ─── CATALOGUE ───────────────────────────────────────────────────────────────

class Famille(models.Model):
    code        = models.CharField(max_length=10, unique=True, help_text='Code Nirgescom (ex: 100)')
    nom         = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name        = 'Famille'
        verbose_name_plural = 'Familles'
        ordering            = ['code']

    def __str__(self):
        return f'{self.code} — {self.nom}'


class SousFamille(models.Model):
    code        = models.CharField(max_length=10, unique=True, help_text='Code Nirgescom (ex: 100101)')
    famille     = models.ForeignKey(Famille, on_delete=models.CASCADE, related_name='sous_familles')
    nom         = models.CharField(max_length=150)
    actif       = models.BooleanField(default=True)

    class Meta:
        verbose_name        = 'Sous-famille'
        verbose_name_plural = 'Sous-familles'
        ordering            = ['code']

    def __str__(self):
        return f'{self.code} — {self.nom}'


class Article(models.Model):
    ref_nirgescom = models.CharField(
        max_length=30, unique=True, db_index=True,
        help_text='Code article Nirgescom (ex: 1003150013-)'
    )
    sous_famille  = models.ForeignKey(
        SousFamille, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='articles'
    )
    designation   = models.CharField(max_length=255)
    prix_detail   = models.DecimalField(
        max_digits=12, decimal_places=0,
        validators=[MinValueValidator(0)],
        help_text='Prix de vente en FCFA'
    )
    # Données sensibles — masquées dans l'interface vendeur
    prix_achat    = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        help_text='Prix d\'achat — confidentiel'
    )
    prix_revient  = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        help_text='Prix de revient — confidentiel'
    )
    # Image
    image_nom     = models.CharField(
        max_length=100, blank=True,
        help_text='Nom du fichier image sans extension (ex: DSC_8469)'
    )
    image_upload = models.ImageField(
        upload_to='articles/',
        blank=True,
        null=True,
        help_text='Image téléversée depuis l\'administration'
    )
    actif         = models.BooleanField(default=True)
    date_import   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Article'
        verbose_name_plural = 'Articles'
        ordering            = ['designation']

    def __str__(self):
        return f'{self.designation} — {int(self.prix_detail):,} FCFA'.replace(',', ' ')

    def get_image_url(self, base_url=None):
        """
        Retourne l'URL de l'image si disponible.
        base_url : préfixe configurable depuis les settings
        """
        if self.image_upload:
            return self.image_upload.url
        if not self.image_nom:
            return None
        if base_url:
            return f'{base_url.rstrip("/")}/{self.image_nom}'
        return self.image_nom


# ─── CONSEIL ─────────────────────────────────────────────────────────────────

class Problematique(models.Model):
    libelle     = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    icone       = models.CharField(
        max_length=10, blank=True,
        help_text='Emoji ou code icône affiché dans l\'interface vendeur'
    )
    ordre       = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name        = 'Problématique beauté'
        verbose_name_plural = 'Problématiques beauté'
        ordering            = ['ordre', 'libelle']

    def __str__(self):
        return self.libelle


class ClasseSociale(models.Model):
    libelle     = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    ordre       = models.PositiveSmallIntegerField(
        default=0,
        help_text='Ordre d\'affichage (du moins cher au plus cher)'
    )

    class Meta:
        verbose_name        = 'Classe sociale'
        verbose_name_plural = 'Classes sociales'
        ordering            = ['ordre']

    def __str__(self):
        return self.libelle


class Recommandation(models.Model):
    problematique  = models.ForeignKey(
        Problematique, on_delete=models.CASCADE, related_name='recommandations'
    )
    classe_sociale = models.ForeignKey(
        ClasseSociale, on_delete=models.CASCADE, related_name='recommandations'
    )
    article        = models.ForeignKey(
        Article, on_delete=models.CASCADE, related_name='recommandations'
    )
    ordre          = models.PositiveSmallIntegerField(
        default=0,
        help_text='Ordre d\'affichage du produit (0 = premier affiché)'
    )

    class Meta:
        verbose_name        = 'Recommandation'
        verbose_name_plural = 'Recommandations'
        ordering            = ['problematique', 'classe_sociale', 'ordre']
        unique_together     = [('problematique', 'classe_sociale', 'article')]

    def __str__(self):
        return f'{self.problematique} × {self.classe_sociale} → {self.article.designation}'


# ─── POINTS DE VENTE & TRAÇABILITÉ ───────────────────────────────────────────

class PointDeVente(models.Model):
    nom      = models.CharField(max_length=150)
    ville    = models.CharField(max_length=100, default='Yaoundé')
    adresse  = models.TextField(blank=True)
    actif    = models.BooleanField(default=True)

    class Meta:
        verbose_name        = 'Point de vente'
        verbose_name_plural = 'Points de vente'
        ordering            = ['nom']

    def __str__(self):
        return f'{self.nom} ({self.ville})'


class AffectationPDV(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='affectations_pdv'
    )
    point_de_vente = models.ForeignKey(
        PointDeVente,
        on_delete=models.CASCADE,
        related_name='affectations_utilisateurs'
    )
    date_debut = models.DateField(default=timezone.localdate)
    date_fin = models.DateField(null=True, blank=True)
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Affectation point de vente'
        verbose_name_plural = 'Affectations points de vente'
        ordering = ['-actif', '-date_debut', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=Q(actif=True),
                name='unique_affectation_active_par_utilisateur',
            ),
        ]

    def __str__(self):
        statut = 'active' if self.actif and self.date_fin is None else 'cloturee'
        return f'{self.user} -> {self.point_de_vente} ({statut})'

    def clean(self):
        """Empeche plusieurs affectations actives pour un meme utilisateur."""
        super().clean()
        if not self.actif:
            return

        conflit = (
            type(self).objects
            .filter(user=self.user, actif=True)
            .exclude(pk=self.pk)
            .exists()
        )
        if conflit:
            raise ValidationError({
                'actif': "Cet utilisateur a deja une affectation active.",
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @classmethod
    def get_pdv_actif(cls, user):
        """Retourne le point de vente actif de l'utilisateur, sinon None."""
        if not user or not getattr(user, 'is_authenticated', False):
            return None

        affectation = (
            cls.objects
            .select_related('point_de_vente')
            .filter(
                user=user,
                actif=True,
                date_fin__isnull=True,
                point_de_vente__actif=True,
            )
            .order_by('-date_debut', '-id')
            .first()
        )
        return affectation.point_de_vente if affectation else None

    def cloturer(self, date_fin=None):
        """Cloture l'affectation en cours en conservant l'historique."""
        if not self.actif and self.date_fin is not None:
            return self

        self.date_fin = date_fin or timezone.localdate()
        self.actif = False
        self.save(update_fields=['date_fin', 'actif'])
        return self

    @classmethod
    def affecter(cls, user, pdv):
        """Cloture l'ancienne affectation active puis cree la nouvelle."""
        if user is None or not getattr(user, 'pk', None):
            raise ValueError("L'utilisateur est obligatoire.")
        if pdv is None or not getattr(pdv, 'pk', None):
            raise ValueError("Le point de vente est obligatoire.")
        if not pdv.actif:
            raise ValueError("Impossible d'affecter un utilisateur a un point de vente inactif.")

        aujourd_hui = timezone.localdate()

        with transaction.atomic():
            affectations_actives = list(
                cls.objects
                .select_for_update()
                .filter(user=user, actif=True)
                .order_by('-date_debut', '-id')
            )

            affectation_existante = next(
                (
                    affectation
                    for affectation in affectations_actives
                    if affectation.point_de_vente_id == pdv.id and affectation.date_fin is None
                ),
                None,
            )
            if affectation_existante:
                return affectation_existante

            for affectation in affectations_actives:
                affectation.cloturer(date_fin=aujourd_hui)

            return cls.objects.create(
                user=user,
                point_de_vente=pdv,
                date_debut=aujourd_hui,
                actif=True,
            )


class ConseilEffectue(models.Model):
    point_de_vente  = models.ForeignKey(
        PointDeVente, on_delete=models.CASCADE, related_name='conseils'
    )
    problematique   = models.ForeignKey(
        Problematique, on_delete=models.SET_NULL,
        null=True, related_name='conseils'
    )
    classe_sociale  = models.ForeignKey(
        ClasseSociale, on_delete=models.SET_NULL,
        null=True, related_name='conseils'
    )
    compte_generique = models.CharField(
        max_length=100, blank=True,
        help_text='Identifiant du compte utilisé (générique ou nominatif)'
    )
    date_conseil    = models.DateTimeField(auto_now_add=True)
    # En mode hors ligne, le conseil est créé localement puis synchronisé
    synchronise     = models.BooleanField(
        default=True,
        help_text='False = créé hors ligne, en attente de synchronisation'
    )

    class Meta:
        verbose_name        = 'Conseil effectué'
        verbose_name_plural = 'Conseils effectués'
        ordering            = ['-date_conseil']

    def __str__(self):
        return f'{self.point_de_vente} — {self.date_conseil:%d/%m/%Y %H:%M}'


class ConseilArticle(models.Model):
    conseil = models.ForeignKey(
        ConseilEffectue, on_delete=models.CASCADE, related_name='articles'
    )
    article = models.ForeignKey(
        Article, on_delete=models.CASCADE, related_name='dans_conseils'
    )

    class Meta:
        verbose_name        = 'Article conseillé'
        verbose_name_plural = 'Articles conseillés'
        unique_together     = [('conseil', 'article')]

    def __str__(self):
        return f'{self.conseil} → {self.article.designation}'


# ─── IMPORT CATALOGUE ────────────────────────────────────────────────────────

class ImportCatalogue(models.Model):

    STATUT_CHOICES = [
        ('en_cours',  'En cours'),
        ('succes',    'Succès'),
        ('erreur',    'Erreur'),
        ('partiel',   'Succès partiel'),
    ]

    SOURCE_CHOICES = [
        ('nirgescom', 'Export Nirgescom (XLS)'),
        ('odoo',      'Export Odoo (CSV)'),
        ('manuel',    'Saisie manuelle'),
    ]

    nom_fichier         = models.CharField(max_length=255)
    source              = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='nirgescom')
    statut              = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_cours')
    nb_articles_total   = models.IntegerField(default=0)
    nb_articles_crees   = models.IntegerField(default=0)
    nb_articles_mis_a_jour = models.IntegerField(default=0)
    nb_articles_ignores = models.IntegerField(default=0)
    erreurs             = models.TextField(
        blank=True,
        help_text='Log des erreurs ligne par ligne'
    )
    date_import         = models.DateTimeField(auto_now_add=True)
    importe_par         = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name        = 'Import catalogue'
        verbose_name_plural = 'Imports catalogue'
        ordering            = ['-date_import']

    def __str__(self):
        return f'{self.nom_fichier} — {self.get_statut_display()} ({self.date_import:%d/%m/%Y})'
