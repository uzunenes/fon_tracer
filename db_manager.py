import sqlite3
import pandas as pd
import random
from datetime import datetime, timedelta

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

        if self.is_db_empty():
            self.seed_mock_data()

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