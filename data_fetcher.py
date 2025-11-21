def extract_tickers_from_yandex(query: str, max_results: int = 10) -> list:
    """
    Yandex Finance arama API'si veya web scraping ile BIST hisse kodlarını çeker.
    query: Fon adı, şirket adı veya kısmi kod.
    Döndürür: ['THYAO.IS', 'ASELS.IS', ...]
    Not: Yandex'in resmi bir public API'si yoktur, bu fonksiyon HTML scraping ile çalışır.
    """
    url = f'https://yandex.com/quotes/search?text={query}'
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'lxml')
    tickers = []
    for a in soup.select('a.QuotesListItem__link'):
        text = a.get_text(strip=True)
        # BIST kodları genellikle büyük harf ve 3-5 karakter
        m = re.search(r'([A-Z]{3,5})', text)
        if m:
            code = m.group(1)
            if not code.endswith('.IS'):
                code = code + '.IS'
            tickers.append(code)
        if len(tickers) >= max_results:
            break
    return list(set(tickers))
def extract_tickers_from_fintables(url: str) -> list:
    """
    Fintables portföy tablosundan BIST hisse kodlarını otomatik tespit eder.
    Döndürür: ['THYAO.IS', 'ASELS.IS', ...]
    """
    df = parse_fintables_holdings(url)
    # Hisse kodu kolonunu bul
    hisse_col = None
    for c in df.columns:
        if 'hisse' in str(c).lower() or 'kod' in str(c).lower():
            hisse_col = c
            break
    if hisse_col is None:
        raise ValueError('Hisse kodu kolonu bulunamadı')
    tickers = []
    for val in df[hisse_col].dropna().unique():
        code = str(val).strip().upper()
        # BIST kodu ise .IS ekle
        if not code.endswith('.IS'):
            code = code + '.IS'
        tickers.append(code)
    return tickers

def update_fund_sources_with_tickers(json_path: str = 'fund_sources.json'):
    """
    fund_sources.json dosyasındaki her fon için tickers alanı yoksa veya boşsa, Fintables sayfasından otomatik doldurur.
    """
    if not os.path.exists(json_path):
        raise FileNotFoundError(f'{json_path} bulunamadı')
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    changed = False
    for fon, cfg in data.items():
        if not cfg.get('tickers') or not isinstance(cfg['tickers'], list) or len(cfg['tickers']) == 0:
            url = cfg.get('fintables_url')
            if url:
                try:
                    tickers = extract_tickers_from_fintables(url)
                    data[fon]['tickers'] = tickers
                    changed = True
                    print(f"{fon} için tickers otomatik dolduruldu: {tickers}")
                except Exception as e:
                    print(f"{fon} için tickers çekilemedi: {e}")
    if changed:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f'{json_path} güncellendi.')
    else:
        print('Değişiklik yok, tickers zaten dolu.')
import datetime
import pandas as pd
import requests
from typing import List
import json
import os
import re
from bs4 import BeautifulSoup

try:
    # optional import; may fail if playwright not installed
    from playwright.sync_api import sync_playwright
    _HAS_PLAYWRIGHT = True
except Exception:
    _HAS_PLAYWRIGHT = False

def get_price_history_yfinance(tickers: List[str], days: int = 30):
    """
    Basit yfinance wrapper. `yfinance` paketinin yüklü olması gerekir.

    Döndürür: DataFrame with columns ['Date', 'Ticker', 'Close']
    """
    try:
        import yfinance as yf
    except Exception as e:
        raise RuntimeError("yfinance yüklü değil. requirements.txt'i güncelleyin ve yükleyin.") from e

    end = datetime.datetime.now().date()
    start = end - datetime.timedelta(days=days)

    # yfinance.download returns wide dataframe; tidy it
    data = yf.download(tickers, start=start.strftime("%Y-%m-%d"), end=(end + datetime.timedelta(days=1)).strftime("%Y-%m-%d"), progress=False)

    # Eğer tekil ticker verilmişse kolon yapısı farklı olabilir
    if isinstance(tickers, str) or (isinstance(tickers, list) and len(tickers) == 1):
        # data['Close'] is series-like
        close = data['Close'].reset_index()
        close['Ticker'] = tickers if isinstance(tickers, str) else tickers[0]
        close = close.rename(columns={'Date': 'Tarih', 'Close': 'Kapanis'})
        return close[['Tarih', 'Ticker', 'Kapanis']]

    # Çoklu ticker -> columns are MultiIndex
    if ('Close' in data.columns.levels[0]) if hasattr(data.columns, 'levels') else ('Close' in data.columns):
        # Tidy close prices
        close = data['Close'].stack().reset_index()
        close.columns = ['Tarih', 'Ticker', 'Kapanis']
        return close[['Tarih', 'Ticker', 'Kapanis']]

    # Fallback: try to extract 'Adj Close' or last column
    try:
        close = data.xs('Adj Close', axis=1, level=0).stack().reset_index()
        close.columns = ['Tarih', 'Ticker', 'Kapanis']
        return close[['Tarih', 'Ticker', 'Kapanis']]
    except Exception:
        # As a last resort, return the dataframe as-is
        return data.reset_index()


def parse_fintables_holdings(url: str) -> pd.DataFrame:
    """
    Basit Fintables parser: verilen URL'deki HTML tablolarını `pandas.read_html` ile çeker,
    olası 'Hisse' / '% pay' sütunlarını arar ve en uygun tabloyu döndürür.

    Not: Bu fonksiyon genel amaçlıdır ve tüm sayfa yapıları için garanti vermez.
    Eğer sayfa JavaScript ile dinamik içerik yüklüyorsa pandas.read_html çalışmayacaktır.
    """
    # Basit GET ile sayfayı al
    resp = requests.get(url, headers={"User-Agent": "fon-tracer-bot/1.0 (+https://github.com)"}, timeout=15)
    resp.raise_for_status()

    tables = pd.read_html(resp.text)
    if not tables:
        # Eğer statik HTML ile tablo bulunamadıysa ve Playwright yüklüyse, JS-rendered sayfayı deneyelim
        if _HAS_PLAYWRIGHT:
            try:
                return parse_fintables_with_playwright(url)
            except Exception:
                raise ValueError("Sayfada tablo bulunamadı veya tablo statik HTML içinde değil.")
        else:
            raise ValueError("Sayfada tablo bulunamadı veya tablo statik HTML içinde değil. Playwright yüklü değilse dinamik sayfalar için yükleyin.")

    # Aranan anahtarlar
    keywords = ['Hisse', 'Hisse Kodu', 'Hisse Adı', '%', 'Pay', 'Pay Oranı']

    def score_table(df: pd.DataFrame) -> int:
        s = 0
        cols = [str(c) for c in df.columns]
        for k in keywords:
            for c in cols:
                if k.lower() in c.lower():
                    s += 1
        return s

    scored = [(score_table(t), idx) for idx, t in enumerate(tables)]
    scored.sort(reverse=True)

    best_score, best_idx = scored[0]
    if best_score == 0:
        # hiçbir anahtar bulunmadı — yine de ilk tabloyu döndür
        return tables[0]

    df_best = tables[best_idx]

    # Basit normalize: sütun adlarını olası hedef isimlere çevir
    rename_map = {}
    for c in df_best.columns:
        cn = str(c).lower()
        if 'hisse' in cn or 'kod' in cn:
            rename_map[c] = 'Hisse'
        if '%' in cn or 'pay' in cn:
            rename_map[c] = 'Pay Oranı (%)'
    df_best = df_best.rename(columns=rename_map)

    return df_best


def parse_fintables_with_playwright(url: str, timeout: int = 20000) -> pd.DataFrame:
    """
    Playwright kullanarak sayfayı render edip HTML içinden tabloları alır.
    Bu fonksiyon sync Playwright API'sini kullanır.

    Gereksinimler:
    - `playwright` Python paketi yüklü olmalı
    - Tarayıcılar `playwright install` ile yüklenmiş olmalı
    """
    if not _HAS_PLAYWRIGHT:
        raise RuntimeError("Playwright yüklü değil. requirements.txt'e ekleyip `pip install -r requirements.txt` ve `playwright install` çalıştırın.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=timeout)
        # Beklenmedik JS yüklemeleri için kısa bekleme veriyoruz
        page.wait_for_load_state('networkidle', timeout=timeout)
        html = page.content()
        browser.close()

    tables = pd.read_html(html)
    if not tables:
        raise ValueError("Playwright ile render sonrası bile tablo bulunamadı.")
    # Aynı mantıkla en iyi tabloyu seç
    keywords = ['Hisse', 'Hisse Kodu', 'Hisse Adı', '%', 'Pay', 'Pay Oranı']

    def score_table(df: pd.DataFrame) -> int:
        s = 0
        cols = [str(c) for c in df.columns]
        for k in keywords:
            for c in cols:
                if k.lower() in c.lower():
                    s += 1
        return s

    scored = [(score_table(t), idx) for idx, t in enumerate(tables)]
    scored.sort(reverse=True)

    best_score, best_idx = scored[0]
    if best_score == 0:
        return tables[0]

    return tables[best_idx]


if __name__ == '__main__':
    print('data_fetcher module - örnek kullanım için fonksiyonları çağırın.')
