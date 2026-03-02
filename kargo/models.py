from django.db import models
from django.contrib.auth.models import User

# --- 1. İLÇE / İSTASYON MODELİ ---
class Istasyon(models.Model):
    """Kocaeli'deki kargo alım/teslim istasyonlarını (ilçeleri) temsil eder."""
    
    ILCELER = [
        ('BA', 'Başiskele'), ('CA', 'Çayırova'), ('DA', 'Darıca'),
        ('DE', 'Derince'), ('DI', 'Dilovası'), ('GE', 'Gebze'),
        ('GO', 'Gölcük'), ('KA', 'Kandıra'), ('KM', 'Karamürsel'),
        ('KT', 'Kartepe'), ('KO', 'Körfez'), ('IZ', 'İzmit'),
    ]
    
    ad = models.CharField(max_length=50, choices=ILCELER, unique=True, verbose_name="İlçe/İstasyon Adı")
    latitude = models.FloatField(verbose_name="Enlem")
    longitude = models.FloatField(verbose_name="Boylam")

    def __str__(self):
        return self.get_ad_display() 

    class Meta:
        verbose_name_plural = "İstasyonlar"

# --- 2. KARGO ARACI MODELİ ---
class KargoAraci(models.Model):
    """Kargo taşıyacak araçların kapasite ve maliyet bilgileri."""
    plaka = models.CharField(max_length=10, unique=True, verbose_name="Araç Plakası")
    kapasite_kg = models.IntegerField(verbose_name="Kargo Kapasitesi (kg)")
    kiralama_maliyeti = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Kiralama Maliyeti (Birim)") 
    yakit_tuketimi_km_basi = models.DecimalField(max_digits=5, decimal_places=2, default=1.0, verbose_name="Yol Maliyeti (km başına)") 

    def __str__(self):
        return f"{self.plaka} ({self.kapasite_kg} kg)"

    class Meta:
        verbose_name_plural = "Kargo Araçları"

# --- 3. KARGO MODELİ ---
class Kargo(models.Model):
    """Kullanıcılardan gelen kargo talepleri."""
    kaynak_istasyon = models.ForeignKey(Istasyon, on_delete=models.PROTECT, related_name='giden_kargolar', verbose_name="Kaynak İstasyon")
    agirlik_kg = models.FloatField(verbose_name="Ağırlık (kg)")
    adet = models.IntegerField(verbose_name="Kargo Adedi")
    talep_tarihi = models.DateTimeField(auto_now_add=True, verbose_name="Talep Tarihi")
    
    gonderen_kullanici = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Gönderen Kullanıcı") 
    
    rotaya_atanmis = models.BooleanField(default=False, verbose_name="Rotaya Atandı mı?")

    # --- KRİTİK BAĞLANTI ALANI ---
    # Django'nun görmesi için 'help_text' ekledim, bu değişikliği kesin algılar.
    rota = models.ForeignKey(
        'Rota', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='tasinan_kargolar', 
        verbose_name="Atanan Rota",
        help_text="Otomatik atanır."
    )

    def __str__(self):
        return f"Kargo Talep No: {self.id} - {self.kaynak_istasyon.get_ad_display()}"

    class Meta:
        verbose_name_plural = "Kargolar"

# --- 4. ROTA VE SEFER MODELLERİ (Optimizasyon Sonuçları) ---
class Rota(models.Model):
    """Bir araca atanan tam sefer planı."""
    arac = models.ForeignKey(KargoAraci, on_delete=models.PROTECT, verbose_name="Atanan Araç")
    sefer_tarihi = models.DateField(auto_now_add=True, verbose_name="Sefer Tarihi")
    toplam_mesafe_km = models.FloatField(default=0, verbose_name="Toplam Mesafe (km)")
    
    toplam_maliyet = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Toplam Maliyet (Kira + Yol)")

    def __str__(self):
        return f"Rota ID: {self.id} - Araç: {self.arac.plaka}"

    class Meta:
        verbose_name = "Rota"
        verbose_name_plural = "Rotas" 

class RotaDetay(models.Model):
    """Rotadaki her bir istasyonun ziyaret sırası."""
    rota = models.ForeignKey(Rota, on_delete=models.CASCADE, related_name='detaylar')
    istasyon = models.ForeignKey(Istasyon, on_delete=models.PROTECT, verbose_name="Ziyaret Edilecek İstasyon")
    ziyaret_sirasi = models.IntegerField(verbose_name="Ziyaret Sırası")

    def __str__(self):
        return f"Rota {self.rota.id} - Sıra {self.ziyaret_sirasi}: {self.istasyon.get_ad_display()}"

    class Meta:
        ordering = ['ziyaret_sirasi']
        verbose_name_plural = "Rota Detayları"