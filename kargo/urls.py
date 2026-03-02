from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # 1. YÖNETİCİ PANELİ (Ana Sayfa)
    path('', views.kargo_optimisation_view, name='optimisation_view'),

    # 2. PERSONEL PANELİ (İşçilerin gireceği sayfa)
    path('personel/', views.kullanici_panel_view, name='kullanici_panel_view'),

    # 3. GİRİŞ YAPMA EKRANI (Login)
    path('giris/', auth_views.LoginView.as_view(template_name='kargo/giris_yap.html'), name='login'),
    
    # 4. ÇIKIŞ YAPMA (Logout) - İsteğe bağlı
    path('cikis/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

    path('dashboard/', views.dashboard_view, name='dashboard_view'),
]