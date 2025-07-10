from flask import Flask, render_template, jsonify, request
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import plotly.graph_objs as go
import threading
import os
import logging
import ccxt
import queue

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuración de exchange - Usamos KuCoin
exchange = ccxt.kucoin({
    'enableRateLimit': True,
    'timeout': 30000,
    'options': {
        'defaultType': 'spot'
    }
})

# Top 60 criptomonedas por capitalización (símbolos de trading)
symbols = [
    'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 
    'XRP/USDT', 'ADA/USDT', 'DOGE/USDT', 'AVAX/USDT',
    'DOT/USDT', 'LINK/USDT', 'MATIC/USDT', 'SHIB/USDT',
    'LTC/USDT', 'UNI/USDT', 'ATOM/USDT', 'XLM/USDT',
    'ETC/USDT', 'FIL/USDT', 'APT/USDT', 'ARB/USDT',
    'NEAR/USDT', 'OP/USDT', 'VET/USDT', 'QNT/USDT',
    'RUNE/USDT', 'ALGO/USDT', 'GRT/USDT', 'AAVE/USDT',
    'AXS/USDT', 'XTZ/USDT', 'STX/USDT', 'EGLD/USDT',
    'THETA/USDT', 'EOS/USDT', 'FLOW/USDT', 'SAND/USDT',
    'MANA/USDT', 'APE/USDT', 'CRV/USDT', 'KAVA/USDT',
    'IMX/USDT', 'RNDR/USDT', 'MINA/USDT', 'MKR/USDT',
    'SNX/USDT', 'COMP/USDT', 'ZEC/USDT', 'DASH/USDT',
    'ENJ/USDT', 'IOTA/USDT', 'KSM/USDT', 'XMR/USDT',
    'NEO/USDT', 'GALA/USDT', 'CHZ/USDT', 'LDO/USDT',
    'WAVES/USDT', 'ROSE/USDT', 'ONE/USDT', 'HNT/USDT'
]

# Variables globales
crypto_data = {}  # Diccionario para almacenar datos por símbolo
last_update_time = datetime.utcnow()
data_lock = threading.Lock()
data_queue = queue.Queue()
initial_data_ready = threading.Event()  # Evento para indicar que hay datos iniciales

current_config = {
    'timeframe': ('15m', '1h'),
    'volume_filter': 'Todas',
    'rsi_period': 14,
    'lower_x': 30,
    'upper_x': 70,
    'lower_y': 30,
    'upper_y': 70
}

# Mapeo de timeframes
TIMEFRAME_MAP = {
    '15m': '15m',
    '30m': '30m',
    '1h': '1h',
    '2h': '2h',
    '4h': '4h',
    '1d': '1d',
    '1w': '1w'
}

# Funciones de cálculo
def compute_rsi(series, period=14):
    """Calcula el RSI para una serie de precios"""
    if len(series) < 2:
        return 50
    
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    
    ma_up = up.ewm(alpha=1/period, adjust=False).mean()
    ma_down = down.ewm(alpha=1/period, adjust=False).mean()
    
    # Evitar división por cero
    rs = ma_up / ma_down
    rsi = 100 - (100 / (1 + rs))
    return rsi

def fetch_ohlcv(symbol, timeframe, limit=100):
    """Obtiene datos OHLCV del exchange"""
    try:
        tf = TIMEFRAME_MAP[timeframe]
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=limit)
        if not ohlcv:
            return None
            
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        logger.warning(f"Error obteniendo datos para {symbol} {timeframe}: {str(e)}")
        return None

def calculate_rsi_for_symbol(symbol):
    """Calcula todos los RSI para un símbolo"""
    asset_data = {
        'symbol': symbol,
        '15m': 50, '30m': 50, '1h': 50, '2h': 50, 
        '4h': 50, '1d': 50, '1w': 50,
        'volume': 0,
        'status': 'loaded'
    }
    
    try:
        volumes = 0
        
        # Obtener datos para cada timeframe
        for tf in ['15m', '30m', '1h', '2h', '4h', '1d', '1w']:
            df = fetch_ohlcv(symbol, tf)
            if df is not None and not df.empty:
                rsi_series = compute_rsi(df['close'], current_config['rsi_period'])
                
                if rsi_series is not None and not rsi_series.empty:
                    asset_data[tf] = rsi_series.iloc[-1]
                
                # Usar volumen del timeframe de 1h como referencia
                if tf == '1h':
                    volumes = df['volume'].mean() if not df.empty else 0
        
        asset_data['volume'] = volumes
        return asset_data
    except Exception as e:
        logger.warning(f"Error procesando {symbol}: {str(e)}")
        # Devolver datos predeterminados para este símbolo
        return asset_data

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
            
            result = calculate_rsi_for_symbol(symbol)
            if result:
                with data_lock:
                    crypto_data[symbol] = result
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
                elif volume <= low_thresh:
                    crypto_data[symbol]['volume_cat'] = 'Bajo'
                else:
                    crypto_data[symbol]['volume_cat'] = 'Medio'
        else:
            for symbol in crypto_data:
                crypto_data[symbol]['volume_cat'] = 'Medio'
    
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

def create_plot():
    """Crea el gráfico Plotly con los datos disponibles"""
    plot_data = get_plot_data()
    
    # Crear figura
    fig = go.Figure()
    
    if plot_data.empty:
        fig.add_annotation(
            text="No hay datos disponibles. Intente actualizar más tarde.",
            x=0.5, y=0.5, 
            showarrow=False, 
            font=dict(size=24, color="red")
        )
        fig.update_layout(
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            height=700
        )
        return fig
    
    # Obtener ejes
    x_time, y_time = current_config['timeframe']
    
    # Crear trazas
    traces = []
    for i, row in plot_data.iterrows():
        symbol = row['symbol']
        coin_name = symbol.split('/')[0]
        
        color = 'gold' if coin_name == 'BTC' else \
                'green' if row['volume_cat'] == 'Alto' else \
                'blue' if row['volume_cat'] == 'Medio' else 'red'
        
        size = 50 if coin_name == 'BTC' else 30
        
        if coin_name == 'BTC':
            textfont = dict(size=18, color='darkorange', family='Arial', weight='bold')
        else:
            textfont = dict(size=14, color='black', weight='bold')
        
        # Verificar si existen los valores RSI
        if x_time in row and y_time in row and not pd.isna(row[x_time]) and not pd.isna(row[y_time]):
            traces.append(go.Scatter(
                x=[row[x_time]],
                y=[row[y_time]],
                mode='markers+text',
                marker=dict(
                    size=size,
                    color=color,
                    line=dict(width=2, color='black')
                ),
                text=coin_name,
                textposition='top center',
                textfont=textfont,
                name=coin_name,
                hoverinfo='text',
                hovertext=f"{coin_name}<br>RSI {x_time}: {row[x_time]:.2f}%<br>RSI {y_time}: {row[y_time]:.2f}%<br>Volumen: ${row['volume']:,.0f} ({row['volume_cat']})"
            ))
    
    # Si no hay trazas, mostrar mensaje
    if not traces:
        fig.add_annotation(
            text="Datos insuficientes para mostrar el gráfico",
            x=0.5, y=0.5, 
            showarrow=False, 
            font=dict(size=24, color="red")
        )
    else:
        # Añadir trazas a la figura
        fig = go.Figure(data=traces)
        
        # Añadir líneas de referencia
        fig.add_shape(type="line", 
                      x0=current_config['lower_x'], y0=0, 
                      x1=current_config['lower_x'], y1=100,
                      line=dict(color="Green", width=3, dash="dash"))
        fig.add_shape(type="line", 
                      x0=current_config['upper_x'], y0=0, 
                      x1=current_config['upper_x'], y1=100,
                      line=dict(color="Red", width=3, dash="dash"))
        fig.add_shape(type="line", 
                      x0=0, y0=current_config['lower_y'], 
                      x1=100, y1=current_config['lower_y'],
                      line=dict(color="Green", width=3, dash="dash"))
        fig.add_shape(type="line", 
                      x0=0, y0=current_config['upper_y'], 
                      x1=100, y1=current_config['upper_y'],
                      line=dict(color="Red", width=3, dash="dash"))
        
        # Añadir zonas
        fig.add_hrect(y0=current_config['upper_y'], y1=100,
                      line_width=0, fillcolor="red", opacity=0.15)
        fig.add_hrect(y0=0, y1=current_config['lower_y'],
                      line_width=0, fillcolor="green", opacity=0.15)
        fig.add_vrect(x0=current_config['upper_x'], x1=100,
                      line_width=0, fillcolor="red", opacity=0.15)
        fig.add_vrect(x0=0, x1=current_config['lower_x'],
                      line_width=0, fillcolor="green", opacity=0.15)
    
    # Configurar layout
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M (UTC)")
    title = f"RSI ({current_config['timeframe'][0]} vs {current_config['timeframe'][1]}) | Período: {current_config['rsi_period']} | Filtro: {current_config['volume_filter']}"
    
    fig.update_layout(
        title=dict(text=f"{title}<br>{now}", font=dict(size=20)),
        xaxis_title=f"RSI {current_config['timeframe'][0]} (Límites: {current_config['lower_x']}/{current_config['upper_x']})",
        yaxis_title=f"RSI {current_config['timeframe'][1]} (Límites: {current_config['lower_y']}/{current_config['upper_y']})",
        xaxis=dict(
            range=[0, 100],
            tickmode='array',
            tickvals=list(range(0, 101, 10)),
            ticktext=[f"{x}%" for x in range(0, 101, 10)],
            showgrid=True,
            gridwidth=1,
            gridcolor='lightgray',
            zeroline=False,
            tickfont=dict(size=12)
        ),
        yaxis=dict(
            range=[0, 100],
            tickmode='array',
            tickvals=list(range(0, 101, 10)),
            ticktext=[f"{y}%" for y in range(0, 101, 10)],
            showgrid=True,
            gridwidth=1,
            gridcolor='lightgray',
            zeroline=False,
            tickfont=dict(size=12)
        ),
        template="plotly_white",
        showlegend=False,
        height=700,
        margin=dict(l=80, r=80, b=100, t=100, pad=10)
    )
    
    return fig

# Ruta principal
@app.route('/')
def index():
    # Iniciar carga de datos si es la primera vez
    if not crypto_data:
        threading.Thread(target=fetch_crypto_data).start()
    
    # Esperar hasta que haya al menos algunos datos
    initial_data_ready.wait(timeout=10)
    
    fig = create_plot()
    graph_html = fig.to_html(full_html=False, include_plotlyjs='cdn')
    
    # Obtener contador de símbolos cargados
    with data_lock:
        loaded_count = len(crypto_data)
    
    return render_template('index.html', 
                           graph_html=graph_html, 
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

# Ruta para actualizar el gráfico
@app.route('/update_graph')
def update_graph():
    fig = create_plot()
    graph_html = fig.to_html(full_html=False, include_plotlyjs=False)
    
    with data_lock:
        loaded_count = len(crypto_data)
    
    return jsonify({
        'graph_html': graph_html,
        'loaded_count': loaded_count
    })

# API para actualizar configuración
@app.route('/update_config', methods=['POST'])
def update_config():
    data = request.get_json()
    param = data.get('param')
    value = data.get('value')
    
    # Mapa de timeframes
    timeframe_map = {
        '15m_1h': ('15m', '1h'),
        '30m_2h': ('30m', '2h'),
        '1h_4h': ('1h', '4h'),
        '4h_1d': ('4h', '1d'),
        '1d_1w': ('1d', '1w')
    }
    
    # Determinar si se necesita recargar datos
    need_data_reload = False
    
    with data_lock:
        config = current_config.copy()
        
        if param == 'timeframe':
            config['timeframe'] = timeframe_map.get(value, ('15m', '1h'))
        elif param == 'volume_filter':
            config['volume_filter'] = value
        elif param == 'period':
            config['rsi_period'] = int(value)
            need_data_reload = True
        elif param == 'lower_x':
            config['lower_x'] = int(value)
        elif param == 'upper_x':
            config['upper_x'] = int(value)
        elif param == 'lower_y':
            config['lower_y'] = int(value)
        elif param == 'upper_y':
            config['upper_y'] = int(value)
        
        # Actualizar config global
        current_config.update(config)
    
    # Forzar recálculo si se cambió periodo
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
