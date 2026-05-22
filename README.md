# JD Original — Outil d'aide à la vente

Application web interne de conseil beauté pour les points de vente **JD Original** (JD Cosmetics SARL, Yaoundé).

---

## Présentation

L'outil guide le vendeur en 3 étapes :

1. **Problématique beauté** du client (peau grasse, anti-âge, cheveux secs…)
2. **Profil client** (classe sociale / gamme de prix souhaitée)
3. **Recommandations produits** issues du catalogue, avec photos et prix en FCFA

Chaque conseil est tracé en base par point de vente. L'outil fonctionne également en **mode hors ligne** (PWA) si la connexion au serveur est perdue.

---

## Stack technique

| Composant | Technologie |
|---|---|
| Backend | Django 4.x (Python 3.10+) |
| Base de données | MySQL 8.0 |
| Interface vendeur | HTML / CSS / JS (PWA, Bootstrap-free) |
| Back-office | Django Admin (customisé) |
| Serveur de production | Gunicorn (Ubuntu) / Waitress (Windows) |
| Import catalogue | Export XLS Nirgescom + CSV sous-familles |

---

## Structure du projet

```
jd_conseil_vente/
├── config/
│   ├── settings.py          # Configuration Django (DB, images, etc.)
│   └── urls.py              # Routes principales
├── conseil_vente/
│   ├── models.py            # Modèles de données
│   ├── admin.py             # Back-office Django Admin
│   ├── views.py             # Vues interface vendeur + API JSON
│   ├── urls.py              # Routes de l'application
│   ├── middleware.py        # Association compte ↔ point de vente
│   └── fixtures/
│       └── initial_data.json  # Données initiales (classes, problématiques, PDV)
├── scripts/
│   ├── import_nirgescom.py  # Import catalogue depuis XLS Nirgescom
│   └── setup_initial.py     # Setup groupes, permissions, comptes vendeurs
├── templates/
│   ├── admin/conseil_vente/
│   │   └── import_catalogue.html
│   └── conseil_vente/
│       ├── interface_vendeur.html
│       └── login.html
├── static/conseil_vente/
│   ├── sw.js                # Service Worker (mode hors ligne)
│   └── manifest.json        # PWA manifest
├── media/
│   └── nirgescom/           # Images produits (DSC_XXXX.jpg / .png)
└── manage.py
```

---

## Déploiement recommandé

Le mode recommandé pour Ubuntu 22.04 est désormais **Docker Compose**.

### 1. Préparer l'environnement

```bash
cp .env.example .env
```

Puis adapter au minimum :

- `DJANGO_SECRET_KEY`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DB_PASSWORD`
- `DB_ROOT_PASSWORD`
- `APP_PORT`

### 2. Lancer la stack

```bash
docker compose up -d --build
```

La stack démarre :

- `db` : MySQL 8
- `web` : Django + Gunicorn
- `proxy` : Nginx

### 3. Initialiser l'application

```bash
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py shell < scripts/setup_initial.py
```

### 4. Accès

```text
http://IP_DU_SERVEUR:APP_PORT/
http://IP_DU_SERVEUR:APP_PORT/admin/
```

Les volumes Docker persistants conservent :

- la base MySQL
- les fichiers `media/`
- les fichiers `staticfiles/`

---

## Installation rapide

### 1. Prérequis

- Python 3.10+
- MySQL 8.0+
- pip

### 2. Environnement virtuel

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Ubuntu
source venv/bin/activate
```

### 3. Dépendances

```bash
pip install django mysqlclient pillow gunicorn
pip install django-crispy-forms crispy-bootstrap5
pip install pandas xlrd openpyxl
```

### 4. Base de données MySQL

```sql
CREATE DATABASE jd_conseil_vente CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'jd_user'@'localhost' IDENTIFIED BY 'MotDePasseFort!';
GRANT ALL PRIVILEGES ON jd_conseil_vente.* TO 'jd_user'@'localhost';
FLUSH PRIVILEGES;
```

### 5. Configuration manuelle

Le projet lit maintenant la configuration depuis des variables d'environnement.
Exemple minimal hors Docker :

```bash
export DJANGO_SECRET_KEY="change-me"
export DJANGO_DEBUG="False"
export DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,IP_DU_SERVEUR"
export DB_NAME="jd_conseil_vente"
export DB_USER="jd_user"
export DB_PASSWORD="MotDePasseFort!"
export DB_HOST="localhost"
export DB_PORT="3306"
export MEDIA_ROOT="$(pwd)/media"
export NIRGESCOM_IMAGES_DIR="$(pwd)/media/nirgescom"
```

### 6. Migrations et données initiales

```bash
python manage.py makemigrations conseil_vente
python manage.py migrate
python manage.py createsuperuser
mkdir -p conseil_vente/fixtures/
python manage.py shell < scripts/setup_initial.py
```

### 7. Lancement

```bash
# Développement
python manage.py runserver 0.0.0.0:8000

# Production (Ubuntu)
python manage.py collectstatic --noinput
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3

# Production (Windows)
pip install waitress
waitress-serve --port=8000 config.wsgi:application
```

---

## Import du catalogue Nirgescom

L'import se fait depuis l'interface admin, sans ligne de commande :

1. Se connecter sur `http://IP_SERVEUR:8000/admin/`
2. Aller dans **Imports catalogue** → **Importer catalogue**
3. Uploader le fichier `cataloguemokolo_bon.xls`
4. Uploader optionnellement le fichier `sous_fam_JD_parfumerie.csv`
5. Vérifier le bilan

L'import est **idempotent** : relancer plusieurs fois ne crée pas de doublons. La clé de correspondance est la référence Nirgescom de chaque article (`ref_nirgescom`).

### Gestion des images produits

Deux modes coexistent :

1. **Import catalogue** : le fichier XLS renseigne `image_nom`
2. **Administration article** : l'image peut être téléversée directement dans la fiche `Article`

Priorité d'affichage :

1. image téléversée via l'administration
2. image résolue via `image_nom`
3. placeholder visuel

En production Docker, les images téléversées sont conservées dans le volume `media_data`.

### Format du fichier XLS attendu

| Colonne | Contenu |
|---|---|
| `Code` | Référence Nirgescom (ex: `1003150013-`) |
| `Designation` | Nom de l'article |
| `Detail` | Prix de vente FCFA |
| `Achat` | Prix d'achat (confidentiel) |
| `Revient` | Prix de revient (confidentiel) |
| `image` | Nom du fichier image sans extension (ex: `DSC_8469`) |

---

## Rôles et permissions

| Groupe | Accès |
|---|---|
| **Administrateur SI** | Tout (superuser Django) |
| **Responsable catalogue** | Familles, sous-familles, articles, imports |
| **Responsable commercial** | Problématiques, recommandations, statistiques |
| **Vendeur** | Interface vendeur uniquement — pas d'accès admin |

Les comptes vendeurs génériques sont créés automatiquement par `setup_initial.py` avec le mot de passe temporaire `JD2026!` — **à changer immédiatement**.

---

## Mode hors ligne (PWA)

Si la connexion au serveur est perdue en cours d'utilisation :

- Un bandeau orange s'affiche indiquant la date des dernières données
- Les recommandations déjà consultées restent accessibles depuis le cache navigateur
- Les conseils validés hors ligne sont mis en file d'attente locale (`localStorage`)
- La synchronisation s'effectue automatiquement à la reconnexion

> Le mode hors ligne ne nécessite aucune configuration supplémentaire.
> Le Service Worker est enregistré automatiquement au premier chargement.

---

## Variables de configuration notables

| Variable | Fichier | Description |
|---|---|---|
| `NIRGESCOM_IMAGES_DIR` | `settings.py` | Chemin local vers les images produits |
| `NIRGESCOM_IMAGES_URL` | `settings.py` | URL publique correspondante |
| `NIRGESCOM_IMAGE_EXTENSIONS` | `settings.py` | Extensions testées (`.jpg`, `.JPG`, `.png`, `.PNG`) |
| `PDV_PAR_USERNAME` | `middleware.py` | Mapping compte vendeur ↔ point de vente |
| `DEBUG` | `settings.py` | `False` obligatoire en production |
| `ALLOWED_HOSTS` | `settings.py` | Ajouter l'IP du serveur en production |

---

## Sauvegarde

```bash
# Exporter la base (à planifier hebdomadairement)
mysqldump -u jd_user -p jd_conseil_vente > sauvegarde_$(date +%Y%m%d).sql

# Restaurer
mysql -u jd_user -p jd_conseil_vente < sauvegarde_20260501.sql
```

---

## Documentation

- `docs/Guide_Deploiement_JD_Conseil_Vente.docx` — Guide complet d'installation pas à pas
- `docs/Guide_Entretien_Cadrage_JD_Conseil_Vente.docx` — Guide d'entretien de cadrage fonctionnel

---

## Développement

**Auteur :** KENGNE Arnold Rodrigue — Assistant SI, JD Cosmetics SARL  
**Période :** Mai – Juillet 2026  
**Contexte :** Objectif 9 (Obj9) — CDC DCR2, échéance 30/06/2026

---

## Roadmap

- [x] Modèles de données et migrations
- [x] Import catalogue Nirgescom (XLS + CSV)
- [x] Back-office Django Admin avec gestion des rôles
- [x] Interface vendeur (PWA, mode hors ligne)
- [x] Traçabilité des conseils par point de vente
- [x] Guide de déploiement
- [ ] Configuration des recommandations (données métier à saisir)
- [ ] Tests en boutique (recette fonctionnelle)
- [ ] Déploiement serveur central multi-boutiques (Phase 2)
- [ ] Comptes nominatifs vendeurs (Phase 2)
"# sales_advisory" 
