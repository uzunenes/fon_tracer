import sqlite3
import pandas as pd
import random
import os
import json
from datetime import datetime, timedelta
from typing import List, Optional

from data_fetcher import get_price_history_yfinance, parse_fintables_holdings

class FundDBManager:
    def __init__(self, db_name="fon_takip.db"):
        self.db_name = db_name
        self.initialize_db()

    def get_connection(self):
        return sqlite3.connect(self.db_name, check_same_thread=False)

    def initialize_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS portfoy_hareketleri (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tarih DATE NOT NULL,
                    fon_adi TEXT NOT NULL,
                    hisse_kodu TEXT NOT NULL,
                    pay_orani REAL,
                    tahmini_lot INTEGER,
                    kaynak TEXT
                )
            ''')
            conn.commit()

            # Price history table for yfinance data
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tarih DATE NOT NULL,
                    ticker TEXT NOT NULL,
                    close REAL
                )
            ''')
            conn.commit()

            # Unique index to allow upserts based on date+fund+stock
            cursor.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS ux_portfoy_unique ON portfoy_hareketleri(tarih, fon_adi, hisse_kodu)
            ''')
            conn.commit()

            # Unique index for price history
            cursor.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS ux_price_unique ON price_history(tarih, ticker)
            ''')
            conn.commit()

        # Zorunlu: gerçek veri ile çalışılmasını sağla.
        # Eğer veritabanı boşsa `fund_sources.json` bulunup otomatik çekme denenir.
        if self.is_db_empty():
            sources = self.load_fund_sources()
            if sources:
                try:
                    self.auto_populate_from_sources(sources)
                except Exception as e:
                    raise RuntimeError(f"Gerçek veri çekilirken hata oluştu: {e}")
            else:
                raise RuntimeError(
                    "Veritabanı boş. Uygulama yalnızca gerçek veri ile çalışacak şekilde yapılandırıldı."
                    " Lütfen proje köküne 'fund_sources.json' ekleyin veya veritabanını manuel doldurun."
                )

    def is_db_empty(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM portfoy_hareketleri")
            return cursor.fetchone()[0] == 0

    def seed_mock_data(self):
        fonlar = ["ATLAS PORTFÖY", "TERA PORTFÖY", "HEDEF PORTFÖY", "MAC PORTFÖY"]
        hisseler = ["THYAO", "ASELS", "KCHOL", "GARAN", "ASTOR", "TUPRS"]
        mock_data = []
        start_date = datetime.now() - timedelta(days=60)

        for i in range(61):
            current_date = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            for fon in fonlar:
                selected_stocks = random.sample(hisseler, 3)
                for stock in selected_stocks:
                    base_rate = 5.0
                    variation = random.uniform(-0.5, 1.5)
                    final_rate = round(base_rate + variation, 2)
                    kaynak = "KAP (%5+)" if final_rate >= 5.0 else "Aylık Rapor"
                    mock_data.append((current_date, fon, stock, final_rate, int(final_rate * 20000), kaynak))

        with self.get_connection() as conn:
            conn.cursor().executemany('''
                INSERT INTO portfoy_hareketleri (tarih, fon_adi, hisse_kodu, pay_orani, tahmini_lot, kaynak)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', mock_data)
            conn.commit()

    def get_filtered_data(self, selected_funds, days):
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        query = "SELECT * FROM portfoy_hareketleri WHERE date(tarih) >= date(?)"
        params = [start_date.strftime("%Y-%m-%d")]

        if selected_funds:
            placeholders = ', '.join(['?'] * len(selected_funds))
            query += f" AND fon_adi IN ({placeholders})"
            params.extend(selected_funds)

        query += " ORDER BY tarih ASC"

        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params)

        return df.rename(columns={
            "tarih": "Tarih", "fon_adi": "Fon Adı", "hisse_kodu": "Hisse",
            "pay_orani": "Pay Oranı (%)", "tahmini_lot": "Tahmini Lot", "kaynak": "Kaynak"
        })

    def get_all_funds(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT fon_adi FROM portfoy_hareketleri ORDER BY fon_adi")
            return [row[0] for row in cursor.fetchall()]

        def load_fund_sources(self, path: str = 'fund_sources.json') -> dict:
            """
            `fund_sources.json` beklenen yapısı:
            {
                "ATLAS PORTFÖY": {
                    "fintables_url": "https://www.fintables.com/xxxx",
                    "tickers": ["THYAO.IS", "ASELS.IS"]
                },
                ...
            }
            """
            if not os.path.exists(path):
                return {}
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)

        def auto_populate_from_sources(self, sources: dict, days: int = 30) -> None:
            """
            sources dict'inden çekim yapar ve veritabanını doldurur.
            """
            for fon, cfg in sources.items():
                fintables_url = cfg.get('fintables_url')
                tickers = cfg.get('tickers', [])

                if fintables_url:
                    try:
                        self.fetch_and_store_fintables(fintables_url, fon_adi=fon, kaynak='Fintables')
                    except Exception as e:
                        print(f"Fintables çekim hatası ({fon}): {e}")

                if tickers:
                    try:
                        self.fetch_and_store_prices(tickers, days=days, kaynak='yfinance')
                    except Exception as e:
                        print(f"Fiyat çekim hatası ({fon} -> {tickers}): {e}")

    # -----------------
    # Upsert / Import helpers
    # -----------------
    def upsert_holdings_df(self, df: pd.DataFrame, kaynak: str = "External") -> None:
        """
        Beklenen kolonlar: 'Tarih', 'Fon Adı', 'Hisse', 'Pay Oranı (%)', optional 'Tahmini Lot'
        Eğer kolon isimleri farklıysa çağıran taraf normalleştirmeli.
        """
        required = ['Tarih', 'Fon Adı', 'Hisse', 'Pay Oranı (%)']
        for c in required:
            if c not in df.columns:
                raise ValueError(f"Eksik kolon: {c}")

        rows = []
        for _, r in df.iterrows():
            tarih = pd.to_datetime(r['Tarih']).strftime('%Y-%m-%d')
            fon = str(r['Fon Adı'])
            hisse = str(r['Hisse'])
            pay = float(r.get('Pay Oranı (%)', 0) or 0)
            lot = int(r.get('Tahmini Lot', 0) or 0)
            rows.append((tarih, fon, hisse, pay, lot, kaynak))

        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.executemany('''
                INSERT OR REPLACE INTO portfoy_hareketleri (tarih, fon_adi, hisse_kodu, pay_orani, tahmini_lot, kaynak)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', rows)
            conn.commit()

    def fetch_and_store_fintables(self, url: str, fon_adi: Optional[str] = None, kaynak: str = 'Fintables') -> pd.DataFrame:
        """
        Fintables sayfasını parse edip veriyi veritabanına yazar.
        `fon_adi` verilirse tabloya bu fon adı atanır; verilmezse tabloda 'Fon Adı' kolonu aranır.
        Döndürür: Normalleştirilmiş DataFrame.
        """
        df = parse_fintables_holdings(url)

        # Normalize sütun adları -> hedef isimler
        # Eğer zaten var ise bırak
        cols = {c: c for c in df.columns}
        for c in df.columns:
            lc = str(c).lower()
            if 'hisse' in lc or 'kod' in lc:
                cols[c] = 'Hisse'
            if '%' in lc or 'pay' in lc:
                cols[c] = 'Pay Oranı (%)'
            if 'tarih' in lc or 'date' in lc:
                cols[c] = 'Tarih'
            if 'fon' in lc:
                cols[c] = 'Fon Adı'

        df = df.rename(columns=cols)

        if 'Fon Adı' not in df.columns:
            if fon_adi:
                df['Fon Adı'] = fon_adi
            else:
                # Eğer fon adı yoksa genel bir placeholder ekle
                df['Fon Adı'] = 'UNKNOWN_FUND'

        # Bazı tablolarda Pay Oranı yüzde sembolü ile gelebilir -> temizle
        if 'Pay Oranı (%)' in df.columns:
            df['Pay Oranı (%)'] = df['Pay Oranı (%)'].astype(str).str.replace('%', '').str.replace(',', '.').astype(float)

        # Tahmini Lot yoksa 0 ekle
        if 'Tahmini Lot' not in df.columns:
            df['Tahmini Lot'] = 0

        # Tarih yoksa bugünün tarihi ata
        if 'Tarih' not in df.columns:
            df['Tarih'] = datetime.now().strftime('%Y-%m-%d')

        # Sıralı ve gerekli sütunları koru
        df = df[['Tarih', 'Fon Adı', 'Hisse', 'Pay Oranı (%)', 'Tahmini Lot']]

        # Upsert
        self.upsert_holdings_df(df, kaynak=kaynak)
        return df

    def fetch_and_store_prices(self, tickers: List[str], days: int = 30, kaynak: str = 'yfinance') -> pd.DataFrame:
        """
        yfinance ile fiyat geçmişini alır, `price_history` tablosuna upsert eder ve DataFrame döndürür.
        """
        df = get_price_history_yfinance(tickers, days=days)

        # Beklenen kolonlar: 'Tarih', 'Ticker', 'Kapanis'
        if 'Tarih' not in df.columns or 'Ticker' not in df.columns:
            raise ValueError('get_price_history_yfinance beklenen formatta döndürmedi')

        rows = []
        for _, r in df.iterrows():
            tarih = pd.to_datetime(r['Tarih']).strftime('%Y-%m-%d')
            ticker = str(r['Ticker'])
            close = float(r.get('Kapanis', r.get('Close', 0) or 0))
            rows.append((tarih, ticker, close))

        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.executemany('''
                INSERT OR REPLACE INTO price_history (tarih, ticker, close)
                VALUES (?, ?, ?)
            ''', rows)
            conn.commit()

        return df