from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin

from .models import AffectationPDV, PointDeVente


class PointDeVenteMiddleware(MiddlewareMixin):
    """
    Injecte le point de vente actif dans la session pour les vendeurs.
    Les administrateurs conservent un choix manuel de point de vente.
    """

    URLS_EXCLUES = (
        '/admin/',
        '/login/',
        '/logout/',
        '/non-affecte/',
        '/choisir-pdv/',
    )

    def process_request(self, request):
        if not request.user.is_authenticated:
            return

        if any(request.path.startswith(prefix) for prefix in self.URLS_EXCLUES):
            return

        session_key = 'point_de_vente_id'

        try:
            pdv_session_id = request.session.get(session_key)
        except Exception:
            pdv_session_id = None

        if request.user.is_staff or request.user.is_superuser:
            if pdv_session_id and not PointDeVente.objects.filter(id=pdv_session_id, actif=True).exists():
                try:
                    del request.session[session_key]
                except Exception:
                    pass
            return

        pdv = AffectationPDV.get_pdv_actif(request.user)

        if pdv is None:
            try:
                if session_key in request.session:
                    del request.session[session_key]
            except Exception:
                pass
            return redirect('conseil_vente:non_affecte')

        if pdv_session_id != pdv.id:
            try:
                request.session[session_key] = pdv.id
            except Exception:
                pass
