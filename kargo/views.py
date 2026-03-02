from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.contrib import messages
from .models import Istasyon, KargoAraci, Kargo, Rota, RotaDetay
import math
import folium
import requests
from dataclasses import dataclass

# --- SABİTLER ---
BASE_LATITUDE = 40.7656
BASE_LONGITUDE = 29.9405

@dataclass
class RentalArac:
    """Veritabanında olmayan geçici kiralık araçlar için yapı"""
    id: str
    plaka: str
    kapasite_kg: int
    yakit_tuketimi_km_basi: float
    kiralama_maliyeti: float

# --- 1. YARDIMCI FONKSİYONLAR ---

def haversine_distance(lat1, lon1, lat2, lon2):
    if lat1 == lat2 and lon1 == lon2: return 2.5
    R = 6371
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_route_geometry(start_lat, start_lon, end_lat, end_lon):
    if start_lat == end_lat and start_lon == end_lon:
        return [[start_lat, start_lon], [start_lat + 0.001, start_lon + 0.001], [start_lat, start_lon]]
    url = f"http://router.project-osrm.org/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}?overview=full&geometries=geojson"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        if data['code'] == 'Ok':
            coords = data['routes'][0]['geometry']['coordinates']
            return [[c[1], c[0]] for c in coords]
    except:
        pass
    return [[start_lat, start_lon], [end_lat, end_lon]]

# --- 2. OPTİMİZASYON ALGORİTMASI ---

# GÜNCELLEME: kiralama_yasak parametresi eklendi
def optimize_routes(kargolar, araclar, istasyonlar, optimizasyon_turu='agirlik', kiralama_yasak=False):
    
    # ADIM A: ELDEKİ ARAÇLARI HAZIRLA (Kapasiteye göre Büyük > Küçük)
    available_araclar = sorted(list(araclar), key=lambda x: x.kapasite_kg, reverse=True)
    
    # ADIM B: KARGOLARI AMACA GÖRE SIRALA
    sorted_kargolar = list(kargolar)
    
    if optimizasyon_turu == 'adet':
        # Küçük paketleri öne al -> Çok adet taşı (Knapsack Mantığına Yakın)
        sorted_kargolar.sort(key=lambda x: x.agirlik_kg, reverse=False)
    else:
        # Büyük paketleri öne al -> Çok ağırlık taşı (Varsayılan)
        sorted_kargolar.sort(key=lambda x: x.agirlik_kg, reverse=True)

    arac_rotalari = {}

    def create_rota_dict(arac_obj, is_rental=False):
        return {
            'obj': arac_obj, 'kargolar': [], 'yuk': 0, 
            'kapasite': arac_obj.kapasite_kg, 'is_rental': is_rental
        }

    # ADIM C: MEVCUT FİLOYU DOLDUR
    for arac in available_araclar:
        if not sorted_kargolar: break

        current_entry = create_rota_dict(arac)
        
        # Bin Packing (Kutulama)
        for kargo in sorted_kargolar[:]:
            if (current_entry['yuk'] + kargo.agirlik_kg) <= current_entry['kapasite']:
                current_entry['kargolar'].append(kargo)
                current_entry['yuk'] += kargo.agirlik_kg
                sorted_kargolar.remove(kargo)
        
        if current_entry['kargolar']:
            arac_rotalari[f"db_{arac.id}"] = current_entry

    # ADIM D: FİLO YETMEDİ Mİ? KİRALIKLARI DEVREYE AL (Sonsuz Döngü)
    rental_counter = 1
    
    while sorted_kargolar:
        # --- KRİTİK EKLEME: Kiralama Yasaksa Buradan Çık ---
        if kiralama_yasak:
            break
        # ---------------------------------------------------

        rental_id = f"rental_{rental_counter}"
        
        # Proje Kuralı: Kiralık araç her zaman 500 kg / 200 Birim
        new_rental = RentalArac(
            id=rental_id, 
            plaka=f"34 KRL {rental_counter} (KİRALIK)", 
            kapasite_kg=500, 
            yakit_tuketimi_km_basi=1.0, 
            kiralama_maliyeti=200.0
        )
        
        current_entry = create_rota_dict(new_rental, is_rental=True)
        
        # Kiralık aracı doldur
        yuklendi_mi = False
        for kargo in sorted_kargolar[:]:
            if (current_entry['yuk'] + kargo.agirlik_kg) <= current_entry['kapasite']:
                current_entry['kargolar'].append(kargo)
                current_entry['yuk'] += kargo.agirlik_kg
                sorted_kargolar.remove(kargo)
                yuklendi_mi = True
        
        if not yuklendi_mi and sorted_kargolar:
             zorlu_kargo = sorted_kargolar.pop(0)
             current_entry['kargolar'].append(zorlu_kargo)
             current_entry['yuk'] += zorlu_kargo.agirlik_kg
        
        arac_rotalari[rental_id] = current_entry
        rental_counter += 1

    # ADIM E: ROTA ve MALİYET HESAPLAMA
    all_stations = {istasyon.ad: istasyon for istasyon in istasyonlar}
    
    for key, rota_data in arac_rotalari.items():
        if not rota_data['kargolar']: continue
        
        ziyaret_edilecekler = set(kargo.kaynak_istasyon.ad for kargo in rota_data['kargolar'])
        ziyaret_edilecek_list = [all_stations[ilce] for ilce in ziyaret_edilecekler]
        
        current_lat, current_lon = BASE_LATITUDE, BASE_LONGITUDE
        ziyaret_sirasi = []
        toplam_mesafe = 0
        
        while ziyaret_edilecek_list:
            nearest_istasyon = None
            min_distance = float('inf')
            for istasyon in ziyaret_edilecek_list:
                dist = haversine_distance(current_lat, current_lon, istasyon.latitude, istasyon.longitude) 
                if dist < min_distance:
                    min_distance = dist
                    nearest_istasyon = istasyon
            
            toplam_mesafe += min_distance
            ziyaret_sirasi.append(nearest_istasyon)
            current_lat, current_lon = nearest_istasyon.latitude, nearest_istasyon.longitude 
            ziyaret_edilecek_list.remove(nearest_istasyon)

        toplam_mesafe += haversine_distance(current_lat, current_lon, BASE_LATITUDE, BASE_LONGITUDE)
        
        rota_data['ziyaret_sirasi'] = ziyaret_sirasi
        rota_data['toplam_mesafe'] = round(toplam_mesafe, 2)
        arac = rota_data['obj']
        yakit_maliyeti = float(arac.yakit_tuketimi_km_basi) * toplam_mesafe
        kira = float(arac.kiralama_maliyeti)
        rota_data['maliyet'] = round(yakit_maliyeti + kira, 2)

    return arac_rotalari

# --- 3. GÜVENLİK ---
def admin_check(user): return user.is_superuser

# --- 4. VIEWS ---

@user_passes_test(admin_check, login_url='/personel/') 
def kargo_optimisation_view(request):
    # 1. KARGO EKLEME
    if request.method == 'POST' and request.POST.get('action') == 'kargo_ekle':
        istasyon_id = request.POST.get('istasyon_id')
        agirlik = request.POST.get('agirlik')
        if istasyon_id and agirlik:
            try:
                istasyon = Istasyon.objects.get(id=istasyon_id)
                Kargo.objects.create(kaynak_istasyon=istasyon, agirlik_kg=agirlik, adet=1)
                messages.success(request, f"✅ {istasyon.ad} için kargo eklendi.")
            except: pass
        return redirect(request.path)

    # 2. OPTİMİZASYON BAŞLATMA
    if request.method == 'POST' and request.POST.get('action') == 'optimize':
        secilen_tur = request.POST.get('optimizasyon_turu', 'agirlik')
        
        # --- YENİ KISIM: Kiralama Checkbox Kontrolü ---
        # HTML'den 'kiralama_yasak' verisi 'on' gelirse True, yoksa False
        kiralama_durumu = request.POST.get('kiralama_yasak')
        kiralama_yasak_modu = True if kiralama_durumu == 'on' else False
        
        # Tüm kargoları sıfırla (Temiz sayfa)
        Kargo.objects.all().update(rotaya_atanmis=False)
        
        kargolar_qs = Kargo.objects.filter(rotaya_atanmis=False).select_related('kaynak_istasyon')
        araclar_qs = KargoAraci.objects.all()
        istasyonlar_qs = Istasyon.objects.all()

        if kargolar_qs.exists():
            # Algoritmaya checkbox durumunu gönderiyoruz
            arac_rotalari = optimize_routes(
                kargolar_qs, 
                araclar_qs, 
                istasyonlar_qs, 
                optimizasyon_turu=secilen_tur, 
                kiralama_yasak=kiralama_yasak_modu
            )
            
            with transaction.atomic():
                # Eski rotaları temizle
                RotaDetay.objects.all().delete()
                Rota.objects.all().delete()
                
                for key, rota_data in arac_rotalari.items():
                    if rota_data['kargolar']:
                        if rota_data['is_rental']:
                            referans_arac = araclar_qs.order_by('kapasite_kg').first() 
                        else:
                            referans_arac = rota_data['obj']
                        
                        yeni_rota = Rota.objects.create(
                            arac=referans_arac,
                            toplam_mesafe_km=rota_data['toplam_mesafe'],
                            toplam_maliyet=rota_data['maliyet'],
                        )
                        for idx, ist in enumerate(rota_data['ziyaret_sirasi']):
                            RotaDetay.objects.create(rota=yeni_rota, istasyon=ist, ziyaret_sirasi=idx + 1)
                        for kargo in rota_data['kargolar']:
                            kargo.rotaya_atanmis = True
                            kargo.rota = yeni_rota
                            kargo.save()
            
            # Mesajı duruma göre özelleştir
            if kiralama_yasak_modu:
                messages.success(request, "🚀 Optimizasyon tamamlandı (Sınırlı Araç Modu). Artan kargolar beklemede.")
            else:
                messages.success(request, "🚀 Optimizasyon tamamlandı (Sınırsız/Kiralık Araç Modu).")
        else:
            messages.warning(request, "⚠️ Atanacak kargo yok.")
        
        return redirect(request.path)

    rotalar_qs = Rota.objects.all().select_related('arac').prefetch_related('detaylar__istasyon', 'tasinan_kargolar')
    kalan_kargolar_qs = Kargo.objects.filter(rotaya_atanmis=False)
    istasyonlar_qs = Istasyon.objects.all()
    toplam_maliyet = sum(r.toplam_maliyet for r in rotalar_qs)

    m = folium.Map(location=[BASE_LATITUDE, BASE_LONGITUDE], zoom_start=10)
    colors = ['red', 'blue', 'green', 'purple', 'orange']
    folium.Marker([BASE_LATITUDE, BASE_LONGITUDE], icon=folium.Icon(color='black', icon='home')).add_to(m)

    for i, rota in enumerate(rotalar_qs):
        color = colors[i % len(colors)]
        points = []
        detaylar = list(rota.detaylar.all().order_by('ziyaret_sirasi'))
        
        plaka_goster = rota.arac.plaka
        yakit = float(rota.toplam_mesafe_km) * 1.0
        maliyet = float(rota.toplam_maliyet)
        
        if (maliyet - yakit) > 150:
            plaka_goster = f"KİRALIK ({rota.arac.plaka})"

        if detaylar:
            points.extend(get_route_geometry(BASE_LATITUDE, BASE_LONGITUDE, detaylar[0].istasyon.latitude, detaylar[0].istasyon.longitude))
            for j in range(len(detaylar)-1):
                start, end = detaylar[j].istasyon, detaylar[j+1].istasyon
                points.extend(get_route_geometry(start.latitude, start.longitude, end.latitude, end.longitude))
                folium.Marker([start.latitude, start.longitude], icon=folium.Icon(color=color), popup=start.ad).add_to(m)
            last = detaylar[-1].istasyon
            folium.Marker([last.latitude, last.longitude], icon=folium.Icon(color=color), popup=last.ad).add_to(m)
            points.extend(get_route_geometry(last.latitude, last.longitude, BASE_LATITUDE, BASE_LONGITUDE))
        
        folium.PolyLine(points, color=color, weight=5, opacity=0.8, tooltip=f"{plaka_goster} - {rota.toplam_maliyet} TL").add_to(m)

    context = {'rotalar': rotalar_qs, 'toplam_maliyet': round(toplam_maliyet, 2), 'map_html': m._repr_html_(), 'kalan_kargolar': kalan_kargolar_qs, 'istasyonlar': istasyonlar_qs}
    return render(request, 'kargo/optimisation_result.html', context)

def dashboard_view(request):
    rotalar = Rota.objects.all().select_related('arac')
    return render(request, 'kargo/dashboard.html', {'rotalar': rotalar})

# PERSONEL PANELİ (GERİ EKLENDİ VE DÜZELTİLDİ)
@login_required(login_url='/giris/')
def kullanici_panel_view(request):
    map_html = None
    aranan_kargo = None
    
    # A) KARGO EKLEME
    if request.method == 'POST' and request.POST.get('action') == 'kargo_ekle':
        istasyon_id = request.POST.get('istasyon_id')
        agirlik = request.POST.get('agirlik')
        if istasyon_id and agirlik:
            try:
                istasyon = Istasyon.objects.get(id=istasyon_id)
                yeni_kargo = Kargo.objects.create(
                    kaynak_istasyon=istasyon, agirlik_kg=agirlik, adet=1, rotaya_atanmis=False
                )
                messages.success(request, f"✅ Kayıt Başarılı! Takip Numaranız (ID): {yeni_kargo.id}")
            except Exception as e:
                messages.error(request, f"Hata: {str(e)}")
        return redirect(request.path)

    # B) KARGO SORGULAMA
    elif request.method == 'POST' and request.POST.get('action') == 'kargo_sorgula':
        kargo_id = request.POST.get('kargo_id')
        if kargo_id:
            try:
                aranan_kargo = Kargo.objects.get(id=kargo_id)
                if aranan_kargo.rotaya_atanmis:
                    ilgili_rota = Rota.objects.filter(detaylar__istasyon=aranan_kargo.kaynak_istasyon).first()
                    if ilgili_rota:
                        m = folium.Map(location=[BASE_LATITUDE, BASE_LONGITUDE], zoom_start=10)
                        full_path_points = []
                        detaylar = list(ilgili_rota.detaylar.all().order_by('ziyaret_sirasi'))
                        
                        if detaylar:
                             full_path_points.extend(get_route_geometry(BASE_LATITUDE, BASE_LONGITUDE, detaylar[0].istasyon.latitude, detaylar[0].istasyon.longitude))
                             for j in range(len(detaylar) - 1):
                                start, end = detaylar[j].istasyon, detaylar[j+1].istasyon
                                full_path_points.extend(get_route_geometry(start.latitude, start.longitude, end.latitude, end.longitude))
                                folium.Marker([start.latitude, start.longitude], popup=start.ad, icon=folium.Icon(color='blue')).add_to(m)
                             last = detaylar[-1].istasyon
                             folium.Marker([last.latitude, last.longitude], popup=last.ad, icon=folium.Icon(color='blue')).add_to(m)
                             full_path_points.extend(get_route_geometry(last.latitude, last.longitude, BASE_LATITUDE, BASE_LONGITUDE))
                        
                        folium.PolyLine(full_path_points, color='blue', weight=5, tooltip=ilgili_rota.arac.plaka).add_to(m)
                        map_html = m._repr_html_()
                        messages.info(request, f"Kargo bulundu. Araç: {ilgili_rota.arac.plaka}")
                    else:
                        messages.warning(request, "Kargo rotada ama teknik gösterim hatası.")
                else:
                    messages.warning(request, "⚠️ Bu kargo henüz yola çıkmadı (Yönetici Onayı Bekliyor).")
            except Kargo.DoesNotExist:
                messages.error(request, "Bu ID ile kargo bulunamadı.")

    istasyonlar = Istasyon.objects.all()
    context = {'istasyonlar': istasyonlar, 'map_html': map_html, 'aranan_kargo': aranan_kargo}
    return render(request, 'kargo/kullanici_panel.html', context)