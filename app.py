import os
import threading
import time
import schedule
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
import pandas as pd
import numpy as np
import ccxt
import logging
import random
import queue

app = Flask(__name__)

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuración
TIME_INTERVAL = 15  # minutos
CRYPTO_LIMIT = 120
TIMEFRAMES = ['30m', '1h', '2h', '4h', '1d', '1w']
DEFAULT_TIMEFRAME = '1h'  # Timeframe por defecto

# Almacenamiento de datos
crypto_data = {}
last_update_time = datetime.utcnow()
data_lock = threading.Lock()
data_queue = queue.Queue()
initial_data_ready = threading.Event()

current_config = {
    'timeframe': '1h',
    'volume_filter': 'Todas'
}

# Lista manual de los 120 cryptos más populares (no memecoins)
symbols = [
    'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 
    'XRP/USDT', 'ADA/USDT', 'AVAX/USDT', 'DOT/USDT', 
    'LINK/USDT', 'MATIC/USDT', 'SHIB/USDT', 'LTC/USDT', 
    'UNI/USDT', 'ATOM/USDT', 'XLM/USDT', 'ETC/USDT', 
    'FIL/USDT', 'APT/USDT', 'ARB/USDT', 'NEAR/USDT', 
    'OP/USDT', 'VET/USDT', 'QNT/USDT', 'RUNE/USDT', 
    'ALGO/USDT', 'GRT/USDT', 'AAVE/USDT', 'AXS/USDT', 
    'XTZ/USDT', 'STX/USDT', 'EGLD/USDT', 'THETA/USDT', 
    'EOS/USDT', 'FLOW/USDT', 'SAND/USDT', 'MANA/USDT', 
    'APE/USDT', 'CRV/USDT', 'KAVA/USDT', 'IMX/USDT', 
    'RNDR/USDT', 'MINA/USDT', 'MKR/USDT', 'SNX/USDT', 
    'COMP/USDT', 'ZEC/USDT', 'DASH/USDT', 'ENJ/USDT', 
    'IOTA/USDT', 'KSM/USDT', 'XMR/USDT', 'NEO/USDT', 
    'GALA/USDT', 'CHZ/USDT', 'LDO/USDT', 'WAVES/USDT', 
    'ROSE/USDT', 'ONE/USDT', 'HNT/USDT', 'FTM/USDT',
    'HBAR/USDT', 'EGLD/USDT', 'ZIL/USDT', 'IOST/USDT',
    'CELO/USDT', 'KLAY/USDT', 'BAT/USDT', 'ONT/USDT',
    'ICX/USDT', 'SC/USDT', 'ZRX/USDT', 'ANKR/USDT',
    'RVN/USDT', 'NANO/USDT', 'OXT/USDT', 'STORJ/USDT',
    'SKL/USDT', 'COTI/USDT', 'POLY/USDT', 'REQ/USDT',
    'UMA/USDT', 'BAND/USDT', 'NMR/USDT', 'OGN/USDT',
    'CVC/USDT', 'MTL/USDT', 'RLC/USDT', 'SXP/USDT',
    'SNT/USDT', 'DENT/USDT', 'HOT/USDT', 'KEY/USDT',
    'VTHO/USDT', 'PERL/USDT', 'DATA/USDT', 'OCEAN/USDT',
    'BTS/USDT', 'LSK/USDT', 'ARDR/USDT', 'STMX/USDT',
    'POWR/USDT', 'DGB/USDT', 'BEAM/USDT', 'XVG/USDT',
    'WAN/USDT', 'LRC/USDT', 'NKN/USDT', 'REP/USDT',
    'CKB/USDT', 'TROY/USDT', 'DUSK/USDT', 'CTSI/USDT'
]

# Inicializar exchange SIN API keys (solo para datos públicos)
exchange = ccxt.kucoin({
    'enableRateLimit': True,
    'timeout': 30000,
    'options': {
        'defaultType': 'spot'
    }
})

# Funciones de cálculo
def calculate_rsi(series, period=14):
    """Calcula el RSI para una serie de precios"""
    if len(series) < 2:
        return 50
    
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    
    ma_up = up.ewm(alpha=1/period, adjust=False).mean()
    ma_down = down.ewm(alpha=1/period, adjust=False).mean()
    
    rs = ma_up / ma_down
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(series, fast=8, slow=21, signal=5):
    ema_fast = series.ewm(span=fast).mean()
    ema_slow = series.ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    return macd_line - signal_line

def fetch_ohlcv(symbol, timeframe, limit=100):
    """Obtiene datos OHLCV del exchange"""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv:
            return None
            
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        logger.warning(f"Error obteniendo datos para {symbol} {timeframe}: {str(e)}")
        return None

def calculate_trend_meters(df):
    try:
        # TM1: MACD Crossover Fast (8,21,5)
        macd_hist = calculate_macd(df['close'])
        tm1 = 1 if macd_hist.iloc[-1] > 0 else 0
        
        # TM2: RSI13 > 50
        rsi13 = calculate_rsi(df['close'], 13)
        tm2 = 1 if rsi13.iloc[-1] > 50 else 0
        
        # TM3: RSI5 > 50
        rsi5 = calculate_rsi(df['close'], 5)
        tm3 = 1 if rsi5.iloc[-1] > 50 else 0
        
        # RSI14 para probabilidad
        rsi14 = calculate_rsi(df['close'], 14).iloc[-1]
        
        # Volumen promedio
        avg_volume = df['volume'].mean()
        
        return tm1, tm2, tm3, rsi14, avg_volume
    except Exception as e:
        logger.error(f"Error calculando indicadores: {str(e)}")
        return 0, 0, 0, 50, 0

def fetch_crypto_data():
    """Obtiene y procesa datos de criptomonedas en segundo plano"""
    global crypto_data, last_update_time
    
    logger.info("Iniciando actualización de datos...")
    start_time = time.time()
    symbols_processed = 0
    
    # Procesar todos los símbolos con manejo de errores robusto
    for symbol in symbols:
        try:
            # Pequeña pausa para evitar rate limits
            time.sleep(0.2)
            
            df = fetch_ohlcv(symbol, current_config['timeframe'])
            if df is not None and len(df) > 50:
                tm1, tm2, tm3, rsi14, avg_volume = calculate_trend_meters(df)
                
                with data_lock:
                    crypto_data[symbol] = {
                        'symbol': symbol,
                        'tm1': tm1,
                        'tm2': tm2,
                        'tm3': tm3,
                        'rsi14': rsi14,
                        'volume': avg_volume,
                        'last_close': df['close'].iloc[-1],
                        'is_btc': 'BTC/USDT' in symbol
                    }
                    symbols_processed += 1
                
                # Enviar progreso a la cola
                data_queue.put({
                    'symbol': symbol,
                    'count': symbols_processed,
                    'total': len(symbols)
                })
                
                # Si es el primer símbolo, señalar que hay datos iniciales
                if symbols_processed == 1:
                    initial_data_ready.set()
            else:
                logger.warning(f"No se obtuvieron datos para {symbol}")
        except Exception as e:
            logger.error(f"Error crítico procesando {symbol}: {str(e)}")
    
    # Calcular categorías de volumen después de tener todos los datos
    with data_lock:
        volumes = [data['volume'] for data in crypto_data.values()]
        if volumes:
            high_thresh = np.percentile(volumes, 70) if len(volumes) > 1 else volumes[0] * 2
            low_thresh = np.percentile(volumes, 30) if len(volumes) > 1 else volumes[0] / 2
            
            for symbol, data in crypto_data.items():
                volume = data['volume']
                if volume >= high_thresh:
                    crypto_data[symbol]['volume_cat'] = 'Alto'
                    crypto_data[symbol]['color'] = 'green'
                elif volume <= low_thresh:
                    crypto_data[symbol]['volume_cat'] = 'Bajo'
                    crypto_data[symbol]['color'] = 'red'
                else:
                    crypto_data[symbol]['volume_cat'] = 'Medio'
                    crypto_data[symbol]['color'] = 'blue'
                
                # Clasificar por condiciones de trading
                if data['tm1'] and data['tm2'] and data['tm3']:
                    if data['rsi14'] < 30:
                        crypto_data[symbol]['zone'] = 'Long Alta Prob'
                        crypto_data[symbol]['zone_color'] = '#006400'
                    else:
                        crypto_data[symbol]['zone'] = 'Long Media Prob'
                        crypto_data[symbol]['zone_color'] = '#32CD32'
                elif not data['tm1'] and not data['tm2'] and not data['tm3']:
                    if data['rsi14'] > 70:
                        crypto_data[symbol]['zone'] = 'Short Alta Prob'
                        crypto_data[symbol]['zone_color'] = '#8B008B'
                    else:
                        crypto_data[symbol]['zone'] = 'Short Media Prob'
                        crypto_data[symbol]['zone_color'] = '#FF69B4'
                else:
                    crypto_data[symbol]['zone'] = 'Neutral'
                    crypto_data[symbol]['zone_color'] = 'white'
        else:
            for symbol in crypto_data:
                crypto_data[symbol]['volume_cat'] = 'Medio'
                crypto_data[symbol]['color'] = 'blue'
                crypto_data[symbol]['zone'] = 'Neutral'
                crypto_data[symbol]['zone_color'] = 'white'
    
    last_update_time = datetime.utcnow()
    elapsed = time.time() - start_time
    logger.info(f"Datos actualizados en {elapsed:.2f} segundos. Símbolos: {symbols_processed}/{len(symbols)}")

def get_plot_data():
    """Obtiene datos para el gráfico, filtrados según configuración"""
    with data_lock:
        # Crear lista de datos
        data_list = [data for data in crypto_data.values()]
        
        if not data_list:
            return pd.DataFrame()
        
        df = pd.DataFrame(data_list)
        
        # Filtrar por volumen si es necesario
        if current_config['volume_filter'] != 'Todas':
            df = df[df['volume_cat'] == current_config['volume_filter']]
        
        return df

# Ruta principal
@app.route('/')
def index():
    # Iniciar carga de datos si es la primera vez
    if not crypto_data:
        threading.Thread(target=fetch_crypto_data).start()
    
    # Esperar hasta que haya al menos algunos datos
    initial_data_ready.wait(timeout=10)
    
    # Obtener contador de símbolos cargados
    with data_lock:
        loaded_count = len(crypto_data)
    
    return render_template('index.html', 
                           current_config=current_config,
                           last_update=last_update_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                           loaded_count=loaded_count,
                           total_count=len(symbols))

# Ruta para verificar estado de datos
@app.route('/data_status')
def data_status():
    # Verificar si hay actualizaciones de progreso
    progress = None
    while not data_queue.empty():
        progress = data_queue.get_nowait()
    
    with data_lock:
        loaded_count = len(crypto_data)
    
    return jsonify({
        'loaded': loaded_count,
        'total': len(symbols),
        'progress': progress
    })

# Ruta para obtener datos del gráfico
@app.route('/graph_data')
def graph_data():
    plot_data = get_plot_data()
    
    if plot_data.empty:
        return jsonify({'data': []})
    
    # Preparar datos para el frontend
    data_points = []
    for _, row in plot_data.iterrows():
        # Distribución aleatoria en X con clustering por zona
        cluster = {
            'Long Alta Prob': 0.2,
            'Long Media Prob': 0.4,
            'Neutral': 0.6,
            'Short Media Prob': 0.8,
            'Short Alta Prob': 1.0
        }.get(row['zone'], 0.5)
        
        x = cluster + (random.random() * 0.3 - 0.15)  # Aleatoriedad dentro del cluster
        
        data_points.append({
            'x': x,
            'y': row['rsi14'],
            'symbol': row['symbol'].replace('/USDT', ''),
            'zone': row['zone'],
            'color': row['color'],
            'is_btc': row['is_btc'],
            'volume_cat': row['volume_cat'],
            'last_close': row['last_close'],
            'rsi14': row['rsi14'],
            'volume': row['volume'],
            'tm1': row['tm1'],
            'tm2': row['tm2'],
            'tm3': row['tm3']
        })
    
    return jsonify({
        'data': data_points,
        'last_update': last_update_time.strftime("%Y-%m-%d %H:%M:%S UTC")
    })

# API para actualizar configuración
@app.route('/update_config', methods=['POST'])
def update_config():
    data = request.get_json()
    param = data.get('param')
    value = data.get('value')
    
    # Determinar si se necesita recargar datos
    need_data_reload = False
    
    with data_lock:
        if param == 'timeframe':
            current_config['timeframe'] = value
            need_data_reload = True
        elif param == 'volume_filter':
            current_config['volume_filter'] = value
    
    # Forzar recálculo si se cambió timeframe
    if need_data_reload:
        # Limpiar datos existentes y recargar
        with data_lock:
            crypto_data.clear()
        threading.Thread(target=fetch_crypto_data).start()
    
    return jsonify({'success': True})

# Iniciar la aplicación
if __name__ == '__main__':
    # Iniciar la carga de datos en un hilo separado
    threading.Thread(target=fetch_crypto_data).start()
    
    # Obtener puerto de entorno o usar 5000 por defecto
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
else:
    # Para entornos WSGI como Render
    threading.Thread(target=fetch_crypto_data).start()
