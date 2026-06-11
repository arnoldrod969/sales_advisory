from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from conseil_vente.models import ImportCatalogue
from scripts.import_nirgescom import (
    charger_sous_familles,
    importer_articles,
    importer_familles_et_sous_familles,
)


class Command(BaseCommand):
    help = 'Importe un catalogue Nirgescom depuis un fichier XLS, XLSX ou CSV.'

    def add_arguments(self, parser):
        parser.add_argument('--fichier', required=True, help='Chemin vers le catalogue à importer')
        parser.add_argument('--fichier-sf', help='Chemin optionnel vers le CSV des sous-familles')
        parser.add_argument('--images-dir', help='Répertoire optionnel des images produits')
        parser.add_argument('--importe-par', default='système', help='Nom de l’utilisateur à tracer')
        parser.add_argument('--import-log-id', type=int, help='Identifiant ImportCatalogue existant à réutiliser')

    def handle(self, *args, **options):
        chemin_catalogue = Path(options['fichier']).expanduser()
        if not chemin_catalogue.exists():
            raise CommandError(f'Fichier catalogue introuvable : {chemin_catalogue}')

        chemin_sf = options.get('fichier_sf')
        if chemin_sf:
            chemin_sf = Path(chemin_sf).expanduser()
            if not chemin_sf.exists():
                raise CommandError(f'Fichier sous-familles introuvable : {chemin_sf}')

        images_dir = options.get('images_dir')
        if images_dir:
            images_dir = str(Path(images_dir).expanduser())

        log_import = None
        import_log_id = options.get('import_log_id')
        if import_log_id:
            try:
                log_import = ImportCatalogue.objects.get(pk=import_log_id)
            except ImportCatalogue.DoesNotExist as exc:
                raise CommandError(f'ImportCatalogue #{import_log_id} introuvable') from exc

        try:
            if chemin_sf:
                index_sf = importer_familles_et_sous_familles(str(chemin_sf))
            else:
                index_sf = charger_sous_familles()

            bilan = importer_articles(
                chemin_xls=str(chemin_catalogue),
                index_sf=index_sf,
                repertoire_images=images_dir,
                importe_par=options['importe_par'],
                log_import=log_import,
            )
        except Exception as exc:
            if log_import is not None:
                log_import.statut = 'erreur'
                log_import.erreurs = str(exc)
                log_import.save(update_fields=['statut', 'erreurs'])
            raise
        finally:
            try:
                chemin_catalogue.unlink()
            except FileNotFoundError:
                pass

            if chemin_sf:
                try:
                    chemin_sf.unlink()
                except FileNotFoundError:
                    pass

        self.stdout.write(
            self.style.SUCCESS(
                f'Import terminé: {bilan.nb_articles_crees} créés, '
                f'{bilan.nb_articles_mis_a_jour} mis à jour, {bilan.nb_articles_ignores} ignorés.'
            )
        )
