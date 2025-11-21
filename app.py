import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import json
import time
import plotly.express as px

# --- AYARLAR ---
st.set_page_config(page_title="Fon Takip Radarı 3000", layout="wide", page_icon="🦈")

# Config Yükle
def load_config():
    # Demo amaçlı config'i burada tanımlıyorum. Normalde dosyadan okuruz.
    return {
        "base_url": "https://fintables.com/sirketler/{SYMBOL}/sirket-bilgileri",
        "headers": {'User-Agent': 'Mozilla/5.0'},
        "target_funds": ["TERA", "ATLAS", "HEDEF", "DENİZ"], # Aranan Fonlar
        "watchlist": ["TRHOL", "IZFAS", "SMRVA", "GLRYH", "PEKGY", "TURSG"], # Takip Listesi
        "selector": "div.flex.flex-col.overflow-x-auto.overflow-y-hidden" # Tablo kutusu
    }

# --- 1. MODÜL: FINTABLES SCRAPING (Lot Bulucu) ---
def get_whale_data(config):
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total = len(config['watchlist'])
    
    for i, symbol in enumerate(config['watchlist']):
        status_text.text(f"🔍 Taranıyor: {symbol}...")
        progress_bar.progress((i + 1) / total)
        
        url = config['base_url'].format(SYMBOL=symbol)
        try:
            resp = requests.get(url, headers=config['headers'])
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, 'html.parser')
                table = soup.select_one(config['selector'])
                
                if table:
                    rows = table.select("table tbody tr")
                    for row in rows:
                        cols = row.select("td")
                        if len(cols) >= 3:
                            name = cols[0].text.strip()
                            lot_txt = cols[1].text.strip()
                            ratio_txt = cols[2].text.strip()
                            
                            # Hedef Fon Kontrolü
                            for fund in config['target_funds']:
                                if fund in name.upper():
                                    # Lot Temizleme (3.055.350 -> 3055350)
                                    lot_clean = float(lot_txt.replace('.', '').replace(',', '.'))
                                    
                                    results.append({
                                        "Hisse": symbol,
                                        "Fon Adı": name,
                                        "Lot (Adet)": lot_clean,
                                        "Pay Oranı": ratio_txt
                                    })
        except Exception as e:
            st.error(f"Hata ({symbol}): {e}")
        
        time.sleep(0.5) # Fintables banlamasın diye minik bekleme

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(results)

# --- 2. MODÜL: CANLI BORSA VERİSİ (Fiyat Bulucu) ---
def enrich_with_market_data(df):
    if df.empty:
        return df
    
    st.info("📡 Canlı piyasa verileri çekiliyor (Yahoo Finance)...")
    
    # Hisse kodlarına .IS ekle (Yahoo formatı: TRHOL.IS)
    symbols = [f"{s}.IS" for s in df['Hisse'].unique()]
    
    # Toplu veri çek
    tickers = yf.Tickers(" ".join(symbols))
    
    current_prices = {}
    daily_changes = {}
    
    for s in symbols:
        try:
            info = tickers.tickers[s].info
            # 'currentPrice' yoksa 'regularMarketPrice' dene
            price = info.get('currentPrice') or info.get('regularMarketPrice') or 0
            
            # Günlük Değişim (%)
            prev_close = info.get('previousClose') or price
            if prev_close:
                change = ((price - prev_close) / prev_close) * 100
            else:
                change = 0
                
            clean_symbol = s.replace('.IS', '')
            current_prices[clean_symbol] = price
            daily_changes[clean_symbol] = change
        except:
            pass
            
    # DataFrame'e Ekle
    df['Canlı Fiyat'] = df['Hisse'].map(current_prices)
    df['Günlük Değ. %'] = df['Hisse'].map(daily_changes)
    
    # Portföy Değeri Hesapla (Lot * Fiyat)
    df['Portföy Değeri (TL)'] = df['Lot (Adet)'] * df['Canlı Fiyat']
    
    return df

# --- ARAYÜZ (FRONTEND) ---
def main():
    st.title("🦈 Hisse & Fon Balina Radarı")
    st.markdown("Bu panel **Fintables**'dan sahiplik verisini, **Canlı Borsa**'dan fiyat verisini birleştirir.")
    
    col1, col2 = st.columns([1, 3])
    
    with col1:
        st.subheader("⚙️ Ayarlar")
        config = load_config()
        st.write("**Hedef Fonlar:**")
        st.code("\n".join(config['target_funds']))
        st.write("**İzleme Listesi:**")
        st.code(", ".join(config['watchlist']))
        
        btn_scan = st.button("🚀 Taramayı Başlat", type="primary")

    with col2:
        if btn_scan:
            # 1. Adım: Balinaları Bul
            df_whales = get_whale_data(config)
            
            if not df_whales.empty:
                # 2. Adım: Fiyatları Çek ve Zenginleştir
                df_final = enrich_with_market_data(df_whales)
                
                # --- METRİKLER ---
                total_value = df_final['Portföy Değeri (TL)'].sum()
                st.metric(label="💰 Toplam Tespit Edilen Varlık", value=f"{total_value:,.0f} TL")
                
                # --- ANA TABLO ---
                st.subheader("📋 Detaylı Pozisyon Raporu")
                
                # Tabloyu Formatla
                st.dataframe(
                    df_final.style.format({
                        "Lot (Adet)": "{:,.0f}",
                        "Canlı Fiyat": "{:.2f} ₺",
                        "Portföy Değeri (TL)": "{:,.0f} ₺",
                        "Günlük Değ. %": "{:.2f}%"
                    }).background_gradient(subset=['Günlük Değ. %'], cmap='RdYlGn'),
                    use_container_width=True
                )
                
                # --- GRAFİKLER ---
                col_chart1, col_chart2 = st.columns(2)
                
                with col_chart1:
                    fig_pie = px.pie(df_final, values='Portföy Değeri (TL)', names='Hisse', title='Hisse Bazlı Dağılım')
                    st.plotly_chart(fig_pie, use_container_width=True)
                
                with col_chart2:
                    fig_bar = px.bar(df_final, x='Fon Adı', y='Portföy Değeri (TL)', color='Hisse', title='Fon Bazlı Büyüklük')
                    st.plotly_chart(fig_bar, use_container_width=True)
                    
            else:
                st.warning("Seçilen hisselerde, belirtilen fonlara ait %5 üzeri bir kayıt bulunamadı.")
        else:
            st.info("Sol taraftaki butona basarak analizi başlatın.")

if __name__ == "__main__":
    main()