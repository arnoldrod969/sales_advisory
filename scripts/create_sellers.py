import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth.models import User, Group
from conseil_vente.models import PointDeVente

g = Group.objects.get(name='Vendeur')

for pdv in PointDeVente.objects.filter(actif=True):
    slug = pdv.nom.split('—')[-1].strip().lower().replace(' ', '_')
    username = f'vendeur_{slug}'[:30]
    if not User.objects.filter(username=username).exists():
        user = User.objects.create_user(
            username=username,
            password='JD2026!',
            first_name='Vendeur',
            last_name=pdv.nom,
            is_staff=False,
        )
        user.groups.add(g)
        print(f"  [OK] Compte '{username}' cree pour {pdv.nom}")
    else:
        print(f"  [-] Compte '{username}' existe deja")

print(f"\nTotal vendeurs: {User.objects.filter(groups=g).count()}")
