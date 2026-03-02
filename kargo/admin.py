from django.contrib import admin
from .models import Istasyon, KargoAraci, Kargo, Rota, RotaDetay

# Tüm modelleri admin paneline kaydet
admin.site.register(Istasyon)
admin.site.register(KargoAraci)
admin.site.register(Kargo)
admin.site.register(Rota)
admin.site.register(RotaDetay)