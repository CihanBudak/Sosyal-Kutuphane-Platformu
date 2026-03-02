from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # Django Yönetici Paneli (Admin Panel) URL'i
    path('admin/', admin.site.urls),
    
    # Kargo uygulamasının tüm URL'leri
    path('', include('kargo.urls')),
]