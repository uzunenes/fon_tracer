import streamlit as st
import pandas as pd
import plotly.express as px
from db_manager import FundDBManager

# --- SAYFA AYARLARI ---
st.set_page_config(
    page_title="Fon Portföy Takip Sistemi (v1.0)",
    page_icon="📈",
    layout="wide"
)

# --- CSS ÖZELLEŞTİRME (Opsiyonel Görsellik) ---
st.markdown("""
<style>
    .metric-card {background-color: #f0f2f6; padding: 15px; border-radius: 10px;}
</style>
""", unsafe_allow_html=True)

# --- BACKEND BAĞLANTISI ---
@st.cache_resource
def get_db_manager():
    """
    Veritabanı yöneticisini cache'ler. Böylece her tıklamada
    yeniden DB oluşturup performansı düşürmez.
    """
    return FundDBManager()

db = get_db_manager()

# --- SIDEBAR (SOL MENÜ) ---
st.sidebar.header("⚙️ Kontrol Paneli")
st.sidebar.info("Faz 1: Simülasyon Modu Aktif")

# Fon Seçimi
mevcut_fonlar = db.get_all_funds()
secilen_fonlar = st.sidebar.multiselect(
    "Takip Edilecek Fonlar",
    options=mevcut_fonlar,
    default=mevcut_fonlar[:2] if mevcut_fonlar else None
)

# Tarih Aralığı
gun_sayisi = st.sidebar.slider("Analiz Süresi (Gün)", 7, 90, 30)

st.sidebar.markdown("---")
st.sidebar.caption("Geliştirici: Enes Uzun")

# --- ANA EKRAN ---
st.title("📊 Yatırım Fonu Hisse Takip Sistemi")
st.markdown(f"""
Bu dashboard, fonların **%5 ve üzeri** paya sahip olduğu hisselerdeki günlük değişimleri izler.
""")

if secilen_fonlar:
    # Veriyi veritabanından çek
    df = db.get_filtered_data(secilen_fonlar, gun_sayisi)

    # -- Üst İstatistikler --
    col1, col2, col3 = st.columns(3)
    col1.metric("Seçilen Fon", len(secilen_fonlar))
    col2.metric("İlgili Hisse Sayısı", df["Hisse"].nunique())
    col3.metric("Toplam Veri Kaydı", len(df))
    st.divider()

    # -- Tablar --
    tab1, tab2, tab3 = st.tabs(["📈 Trend Analizi", "📋 Veri Tablosu", "ℹ️ Mimari"])

    with tab1:
        st.subheader("Fon Pozisyon Değişim Grafiği")
        if not df.empty:
            fig = px.line(
                df,
                x="Tarih",
                y="Pay Oranı (%)",
                color="Hisse",
                line_dash="Fon Adı",
                markers=True,
                hover_data=["Tahmini Lot", "Kaynak"],
                title=f"Son {gun_sayisi} Günlük Pay Değişimi"
            )
            fig.update_layout(height=500)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Seçilen kriterlere uygun veri bulunamadı.")

    with tab2:
        st.subheader("Detaylı Portföy Dökümü")

        # Kaynak sütununa göre satır renklendirme fonksiyonu
        def highlight_source(val):
            color = '#d4edda' if 'Aylık' in str(val) else ''
            return f'background-color: {color}'

        st.dataframe(
            df.style.map(highlight_source, subset=['Kaynak']),
            use_container_width=True,
            height=400
        )

        # Excel İndirme
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "📥 Excel/CSV Olarak İndir",
            data=csv,
            file_name='fon_takip_verisi.csv',
            mime='text/csv',
            type="primary"
        )

    with tab3:
        st.markdown("""
        ### 🏗 Sistem Mimarisi (Faz 1)
        Şu an **MVP (Minimum Viable Product)** aşamasındasınız.

        1. **Backend:** Python + SQLite (Serverless Veritabanı)
        2. **Frontend:** Streamlit
        3. **Veri Kaynağı:** Simülasyon (Mock Data Generator)

        **Faz 2 Planı:**
        - `yfinance` entegrasyonu ile gerçek hisse fiyatları.
        - KAP Scraper botu ile gerçek pay oranları.
        """)

else:
    st.warning("👈 Lütfen sol menüden en az bir FON seçiniz.")