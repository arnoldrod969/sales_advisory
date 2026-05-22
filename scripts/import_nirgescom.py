"""
Import du catalogue Nirgescom depuis un fichier XLS.

Usage (depuis la racine du projet Django) :
    python manage.py shell < scripts/import_nirgescom.py

Ou mieux, intégré comme management command (recommandé) :
    python manage.py import_catalogue --fichier=cataloguemokolo_bon.xls
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime

# ─── Dépendances ─────────────────────────────────────────────────────────────
# pip install xlrd pandas

import pandas as pd
from django.conf import settings

from conseil_vente.models import (
    Famille, SousFamille, Article, ImportCatalogue
)

logger = logging.getLogger(__name__)


# ─── Mapping familles provisoire ─────────────────────────────────────────────
# À remplacer par les libellés officiels quand disponibles
FAMILLES_PROVISOIRES = {
    100: 'Soins du corps & visage',
    110: 'Soins du corps & visage (marques B)',
    120: 'Soins visage spécialisés',
    130: 'Soins capillaires',
    140: 'Parfums & Déodorants',
    150: 'Maquillage & Accessoires',
    160: 'Hygiène buccale & bain',
    170: 'Hygiène générale & accessoires',
    200: 'Soins dépigmentants',
    300: 'Gamme naturelle & bio',
    400: 'Soins premium',
}


# ─── Extensions image à tester dans l'ordre ──────────────────────────────────
IMAGE_EXTENSIONS = ['.jpg', '.JPG', '.png', '.PNG', '.jpeg', '.JPEG']


def normaliser_ref_article(ref_nirgescom: str) -> str:
    """Nettoie la reference article en supprimant le tiret final parasite."""
    return str(ref_nirgescom).strip().rstrip('-').strip()


def trouver_extension_image(nom_base: str, repertoire: str) -> str | None:
    """
    Cherche le fichier image dans le répertoire en testant les extensions.
    Retourne l'extension trouvée, ou None si aucun fichier ne correspond.
    """
    if not repertoire or not nom_base:
        return None
    for ext in IMAGE_EXTENSIONS:
        chemin = Path(repertoire) / f'{nom_base}{ext}'
        if chemin.exists():
            return ext
    return None


def charger_sous_familles() -> dict:
    """
    Charge depuis la BDD toutes les sous-familles indexées par leur code.
    """
    return {sf.code: sf for sf in SousFamille.objects.select_related('famille').all()}


def lier_sous_famille(ref_nirgescom: str, index_sf: dict) -> SousFamille | None:
    """
    Déduit la sous-famille à partir des 6 premiers chiffres du code article.
    Ex: '1003150013-' → préfixe '100315' → cherche code_sf '100315'
    """
    # Nettoyer le code (retirer le tiret final si présent)
    code_clean = normaliser_ref_article(ref_nirgescom)
    # Prendre les 6 premiers chiffres
    if len(code_clean) >= 6:
        prefix = code_clean[:6]
        return index_sf.get(prefix)
    return None


def importer_familles_et_sous_familles(chemin_csv: str) -> dict:
    """
    Importe les familles et sous-familles depuis le CSV Nirgescom.
    Retourne l'index {code_sf: SousFamille} mis à jour.
    """
    df = pd.read_csv(
        chemin_csv,
        header=None,
        encoding='utf-8',
        on_bad_lines='skip'
    )
    df.columns = ['code_sf', 'code_famille', 'libelle', 'actif',
                  'col4', 'col5', 'col6', 'col7', 'created_at', 'updated_at']
    df = df[['code_sf', 'code_famille', 'libelle', 'actif']].copy()
    df['code_sf']      = df['code_sf'].astype(str).str.strip()
    df['code_famille'] = df['code_famille'].astype(int)
    df['libelle']      = df['libelle'].astype(str).str.strip().str.title()

    # Créer ou mettre à jour les familles
    familles_creees = 0
    for code_fam in df['code_famille'].unique():
        libelle = FAMILLES_PROVISOIRES.get(int(code_fam), f'Famille {code_fam}')
        _, created = Famille.objects.update_or_create(
            code=str(code_fam),
            defaults={'nom': libelle}
        )
        if created:
            familles_creees += 1

    logger.info(f'Familles : {familles_creees} créées')

    # Indexer les familles
    familles_index = {f.code: f for f in Famille.objects.all()}

    # Créer ou mettre à jour les sous-familles
    sf_creees = 0
    for _, row in df.iterrows():
        fam = familles_index.get(str(int(row['code_famille'])))
        if not fam:
            continue
        _, created = SousFamille.objects.update_or_create(
            code=row['code_sf'],
            defaults={
                'famille': fam,
                'nom':     row['libelle'],
                'actif':   bool(row['actif']),
            }
        )
        if created:
            sf_creees += 1

    logger.info(f'Sous-familles : {sf_creees} créées')
    return charger_sous_familles()


def importer_articles(
    chemin_xls: str,
    index_sf: dict,
    repertoire_images: str = None,
    importe_par: str = 'système'
) -> ImportCatalogue:
    """
    Importe les articles depuis le fichier XLS Nirgescom.

    Paramètres
    ----------
    chemin_xls          : chemin vers le fichier XLS
    index_sf            : dict {code_sf: SousFamille} pour lier les articles
    repertoire_images   : chemin local vers le dossier des images (optionnel)
                          Si None, on stocke juste le nom de base sans vérifier
    importe_par         : label de la personne/système qui lance l'import

    Retourne
    --------
    L'objet ImportCatalogue créé avec le bilan de l'opération
    """
    nom_fichier = Path(chemin_xls).name
    log_import  = ImportCatalogue.objects.create(
        nom_fichier=nom_fichier,
        source='nirgescom',
        statut='en_cours',
        importe_par=importe_par
    )

    df = pd.read_excel(chemin_xls, engine='xlrd')

    # Garder uniquement les colonnes utiles
    colonnes_utiles = ['Code', ' Designation', 'Stock', 'Achat', 'Detail', 'Revient', 'image']
    df = df[colonnes_utiles].copy()
    df.columns = ['code', 'designation', 'stock', 'achat', 'detail', 'revient', 'image']

    # Nettoyages de base
    df['code']        = df['code'].astype(str).map(normaliser_ref_article)
    df['designation'] = df['designation'].astype(str).str.strip()
    df['image']       = df['image'].astype(str).str.strip().replace('nan', '')

    # Filtrer les lignes sans code valide (headers, totaux, lignes vides)
    df = df[df['code'].str.match(r'^\d{4,}')]
    df = df[df['designation'].str.len() > 2]
    df = df[df['detail'].notna()]
    df = df[df['detail'].astype(float) > 0]

    nb_total     = len(df)
    nb_crees     = 0
    nb_maj       = 0
    nb_ignores   = 0
    lignes_erreur = []

    log_import.nb_articles_total = nb_total
    log_import.save(update_fields=['nb_articles_total'])

    for idx, row in df.iterrows():
        try:
            ref = normaliser_ref_article(row['code'])
            if not ref:
                nb_ignores += 1
                continue

            # Trouver la sous-famille depuis le code
            sous_famille = lier_sous_famille(ref, index_sf)

            # Gérer l'image
            image_nom = str(row['image']).strip() if row['image'] else ''

            # Si un répertoire est fourni, on vérifie l'existence du fichier
            # et on stocke le nom avec extension
            if image_nom and repertoire_images:
                ext = trouver_extension_image(image_nom, repertoire_images)
                if ext:
                    image_nom_stocke = f'{image_nom}{ext}'
                else:
                    # Fichier pas encore présent — on garde le nom de base
                    image_nom_stocke = image_nom
            else:
                image_nom_stocke = image_nom

            # Prix
            prix_detail  = float(row['detail'])  if pd.notna(row['detail'])  else 0
            prix_achat   = float(row['achat'])   if pd.notna(row['achat'])   else None
            prix_revient = float(row['revient']) if pd.notna(row['revient']) else None

            defaults = {
                'designation':   row['designation'],
                'sous_famille':  sous_famille,
                'prix_detail':   prix_detail,
                'prix_achat':    prix_achat,
                'prix_revient':  prix_revient,
                'image_nom':     image_nom_stocke,
                'actif':         True,
            }

            _, created = Article.objects.update_or_create(
                ref_nirgescom=ref,
                defaults=defaults
            )

            if created:
                nb_crees += 1
            else:
                nb_maj += 1

        except Exception as e:
            nb_ignores += 1
            lignes_erreur.append(f'Ligne {idx} ({row.get("code", "?")}): {e}')
            logger.warning(f'Erreur ligne {idx}: {e}')

    # Bilan
    statut = 'succes'
    if lignes_erreur and nb_crees + nb_maj == 0:
        statut = 'erreur'
    elif lignes_erreur:
        statut = 'partiel'

    log_import.statut                 = statut
    log_import.nb_articles_crees      = nb_crees
    log_import.nb_articles_mis_a_jour = nb_maj
    log_import.nb_articles_ignores    = nb_ignores
    log_import.erreurs                = '\n'.join(lignes_erreur[:100])  # max 100 lignes d'erreur
    log_import.save()

    logger.info(
        f'Import terminé — {nb_crees} créés, {nb_maj} mis à jour, '
        f'{nb_ignores} ignorés, statut: {statut}'
    )
    return log_import


# ─── Point d'entrée (usage direct via shell Django) ──────────────────────────

def lancer_import(
    chemin_xls: str,
    chemin_csv_sf: str,
    repertoire_images: str = None,
    importe_par: str = 'Arnold'
):
    """
    Lance l'import complet : familles + sous-familles + articles.

    Exemple d'appel depuis le shell Django :
        from scripts.import_nirgescom import lancer_import
        lancer_import(
            chemin_xls='data/cataloguemokolo_bon.xls',
            chemin_csv_sf='data/sous_fam_JD_parfumerie.csv',
            repertoire_images='/chemin/vers/images',
        )
    """
    print(f'[{datetime.now():%H:%M:%S}] Étape 1/2 — Import familles & sous-familles...')
    index_sf = importer_familles_et_sous_familles(chemin_csv_sf)
    print(f'  → {len(index_sf)} sous-familles chargées')

    print(f'[{datetime.now():%H:%M:%S}] Étape 2/2 — Import articles...')
    bilan = importer_articles(
        chemin_xls=chemin_xls,
        index_sf=index_sf,
        repertoire_images=repertoire_images,
        importe_par=importe_par
    )

    print(f'\n{"─"*50}')
    print(f'Import terminé — {bilan.get_statut_display()}')
    print(f'  Articles traités : {bilan.nb_articles_total}')
    print(f'  Créés            : {bilan.nb_articles_crees}')
    print(f'  Mis à jour       : {bilan.nb_articles_mis_a_jour}')
    print(f'  Ignorés          : {bilan.nb_articles_ignores}')
    if bilan.erreurs:
        print(f'\n  Premières erreurs :')
        for ligne in bilan.erreurs.split('\n')[:5]:
            print(f'    {ligne}')
    print(f'{"─"*50}')
    return bilan
