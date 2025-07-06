from flask import Flask, render_template, jsonify, request
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import plotly.graph_objs as go
import threading
import os
import requests
import json
from apscheduler.schedulers.background import BackgroundScheduler
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# Top 60 criptomonedas
symbols = [
    'bitcoin', 'ethereum', 'binancecoin', 'solana', 
    'ripple', 'cardano', 'dogecoin', 'avalanche-2',
    'polkadot', 'chainlink', 'matic-network', 'shiba-inu',
    'litecoin', 'uniswap', 'cosmos', 'stellar',
    'ethereum-classic', 'filecoin', 'aptos', 'arbitrum',
    'near', 'optimism', 'vechain', 'quant-network',
    'thorchain', 'algorand', 'the-graph', 'aave',
    'axie-infinity', 'tezos', 'stacks', 'elrond-erd-2',
    'theta-token', 'eos', 'flow', 'the-sandbox',
    'decentraland', 'apecoin', 'curve-dao-token', 'kava',
    'immutable-x', 'render-token', 'mina-protocol', 'maker',
    'havven', 'compound-governance-token', 'zcash', 'dash',
    'enjincoin', 'iota', 'kusama', 'monero',
    'neo', 'gala', 'chiliz', 'lido-dao',
    'waves', 'oasis-network', 'harmony', 'helium'
]

COINGECKO_API = "https://api.coingecko.com/api/v3"

# Variables globales
rsi_data = pd.DataFrame()
last_update_time = datetime.utcnow()
data_lock = threading.Lock()
cached_data = None

current_config = {
    'timeframe': ('15m', '1h'),
    'volume_filter': 'Todas',
    'rsi_period': 14,
    'lower_x': 30,
    'upper_x': 70,
    'lower_y': 30,
    'upper_y': 70
}

# Funciones optimizadas
def fetch_all_volumes():
    try:
        url = f"{COINGECKO_API}/coins/markets"
        params = {
            'vs_currency': 'usd',
            'ids': ','.join(symbols),
            'per_page': 250
        }
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        return {coin['id']: coin['total_volume'] for coin in data}
    except Exception as e:
        print(f"Error fetching volumes: {e}")
        return {}

def get_historical_data(coin_id, days=30):
    try:
        url = f"{COINGECKO_API}/coins/{coin_id}/market_chart"
        params = {'vs_currency': 'usd', 'days': days, 'interval': 'daily'}
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        
        if 'prices' in data and data['prices']:
            df = pd.DataFrame(data['prices'], columns=['ts', 'price'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms')
            df.set_index('ts', inplace=True)
            return df
    except Exception as e:
        print(f"Error fetching {coin_id}: {str(e)[:100]}")
    return None

def compute_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(com=period-1, adjust=False).mean()
    ma_down = down.ewm(com=period-1, adjust=False).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))

def calculate_timeframe_rsi(df, timeframe, period=14):
    # Implementación existente...
    pass

def fetch_all_data():
    global rsi_data, last_update_time
    
    print("Iniciando actualización de datos...")
    start_time = time.time()
    
    # Obtener todos los volúmenes
    volumes_map = fetch_all_volumes()
    
    # Obtener datos históricos en paralelo
    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(
                get_historical_data, 
                coin_id, 
                30
            ): coin_id for coin_id in symbols
        }
        
        for future in as_completed(futures):
            coin_id = futures[future]
            try:
                df = future.result()
                if df is not None:
                    results.append((coin_id, df, volumes_map.get(coin_id, 0)))
            except Exception as e:
                print(f"Error processing {coin_id}: {e}")
    
    # Procesar resultados
    rsi_results = []
    for coin_id, df, volume in results:
        try:
            asset_data = {}
            for tf in ['15m', '30m', '1h', '2h', '4h', '1d', '1w']:
                asset_data[tf] = calculate_timeframe_rsi(df, tf, current_config['rsi_period'])
            
            symbol_name = coin_id.upper() if coin_id == 'btc' else coin_id.replace('-', ' ').title()
            asset_data['symbol'] = f"{symbol_name}/USDT"
            asset_data['volume'] = volume
            rsi_results.append(asset_data)
        except Exception as e:
            print(f"Error processing {coin_id}: {e}")
    
    if rsi_results:
        df = pd.DataFrame(rsi_results)
        
        # Calcular categorías de volumen
        if len(df) > 0:
            volumes = df['volume'].values
            high_thresh = np.percentile(volumes, 70) if len(volumes) > 0 else 0
            low_thresh = np.percentile(volumes, 30) if len(volumes) > 0 else 0
            df['volume_cat'] = df.apply(lambda row: 
                'Alto' if row['volume'] >= high_thresh else 
                'Bajo' if row['volume'] <= low_thresh else 
                'Medio', axis=1)
        else:
            df['volume_cat'] = ['Medio'] * len(rsi_results)
        
        with data_lock:
            rsi_data = df
            last_update_time = datetime.utcnow()
    
    elapsed = time.time() - start_time
    print(f"Datos actualizados en {elapsed:.2f} segundos")
    print(f"Criptos obtenidas: {len(rsi_results)}/{len(symbols)}")
    return True

# Resto del código (create_plot, rutas, etc.) igual...

# Iniciar la aplicación
if __name__ == '__main__':
    # Carga inicial en segundo plano
    threading.Thread(target=fetch_all_data).start()
    
    # Obtener puerto de entorno
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
