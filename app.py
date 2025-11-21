import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
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

# Fon Seçimi (sadece fund_sources.json'da linki olanlar)
import json
def get_funds_with_links(json_path='fund_sources.json'):
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return [fon for fon, cfg in data.items() if cfg.get('fintables_url')]
    except Exception:
        return []

fonlar_linkli = get_funds_with_links()
secilen_fonlar = st.sidebar.multiselect(
    "Takip Edilecek Fonlar",
    options=fonlar_linkli,
    default=fonlar_linkli[:2] if fonlar_linkli else None
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
            # Görünüm seçeneği: Mobilde okunması kolay 'Top Movers' varsayılan
            view = st.selectbox("Görünüm", ["Top Movers", "Trend Çizgi"], index=0)

            if view == "Top Movers":
                # Her hisse için periyod başı / sonu değerlerine göre değişim hesapla
                grp = df.sort_values("Tarih").groupby("Hisse")
                first = grp.first()["Pay Oranı (%)"]
                last = grp.last()["Pay Oranı (%)"]
                # Sıfıra bölmeyi önlemek için 0 değerlerini NaN yap
                first = first.replace(0, np.nan)
                change = ((last - first) / first) * 100
                change = change.dropna()

                if change.empty:
                    st.info("Yeterli veri yok — Top Movers hesaplanamıyor.")
                else:
                    top_gainers = change.sort_values(ascending=False).head(5)
                    top_losers = change.sort_values(ascending=True).head(5)

                    df_gainers = pd.DataFrame({"Hisse": top_gainers.index, "Değişim (%)": top_gainers.values})
                    df_losers = pd.DataFrame({"Hisse": top_losers.index, "Değişim (%)": top_losers.values})

                    col_gain, col_loss = st.columns(2)

                    with col_gain:
                        st.markdown("**En Çok Yükselenler (Son dönem)**")
                        fig_gain = px.bar(
                            df_gainers,
                            x="Değişim (%)",
                            y="Hisse",
                            orientation='h',
                            color="Değişim (%)",
                            color_continuous_scale='Greens',
                            text=df_gainers["Değişim (%)"].round(2)
                        )
                        fig_gain.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10))
                        fig_gain.update_traces(textposition='auto')
                        st.plotly_chart(fig_gain, use_container_width=True, config={"displayModeBar": False})

                    with col_loss:
                        st.markdown("**En Çok Düşenler (Son dönem)**")
                        fig_loss = px.bar(
                            df_losers,
                            x="Değişim (%)",
                            y="Hisse",
                            orientation='h',
                            color="Değişim (%)",
                            color_continuous_scale='Reds',
                            text=df_losers["Değişim (%)"].round(2)
                        )
                        fig_loss.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10))
                        fig_loss.update_traces(textposition='auto')
                        st.plotly_chart(fig_loss, use_container_width=True, config={"displayModeBar": False})

            else:
                # Orijinal detaylı çizgi grafiği (mobil için de responsive)
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
                fig.update_traces(marker=dict(size=6))
                fig.update_layout(
                    height=450,
                    autosize=True,
                    template="plotly_white",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    margin=dict(l=20, r=20, t=60, b=20),
                    title=dict(text=f"Son {gun_sayisi} Günlük Pay Değişimi", x=0.5, xanchor='center', font=dict(size=14)),
                    hovermode="x unified"
                )

                st.plotly_chart(
                    fig,
                    use_container_width=True,
                    config={"responsive": True, "displayModeBar": False}
                )
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