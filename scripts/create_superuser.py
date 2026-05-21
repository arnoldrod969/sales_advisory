import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth.models import User

if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@jd-cosmetics.com', 'admin123')
    print("[OK] Superuser 'admin' cree (password: admin123)")
else:
    print("[-] Superuser 'admin' existe deja")
