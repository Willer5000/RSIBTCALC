import os
import time
import threading
import logging
from datetime import datetime
from flask import Flask, render_template, jsonify, request
import pandas as pd
import numpy as np
import plotly.graph_objs as go
import ccxt
from apscheduler.schedulers.background import BackgroundScheduler
import queue

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Top 90 criptomonedas
symbols = [
    'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT', 
    'ADA/USDT', 'DOGE/USDT', 'AVAX/USDT', 'DOT/USDT', 'LINK/USDT',
    'MATIC/USDT', 'SHIB/USDT', 'LTC/USDT', 'UNI/USDT', 'ATOM/USDT',
    'XLM/USDT', 'ETC/USDT', 'FIL/USDT', 'APT/USDT', 'ARB/USDT',
    'NEAR/USDT', 'OP/USDT', 'VET/USDT', 'QNT/USDT', 'RUNE/USDT',
    'ALGO/USDT', 'GRT/USDT', 'AAVE/USDT', 'AXS/USDT', 'XTZ/USDT',
    'STX/USDT', 'EGLD/USDT', 'THETA/USDT', 'EOS/USDT', 'FLOW/USDT',
    'SAND/USDT', 'MANA/USDT', 'APE/USDT', 'CRV/USDT', 'KAVA/USDT',
    'IMX/USDT', 'RNDR/USDT', 'MINA/USDT', 'MKR/USDT', 'SNX/USDT',
    'COMP/USDT', 'ZEC/USDT', 'DASH/USDT', 'ENJ/USDT', 'IOTA/USDT',
    'KSM/USDT', 'XMR/USDT', 'NEO/USDT', 'GALA/USDT', 'CHZ/USDT',
    'LDO/USDT', 'WAVES/USDT', 'ROSE/USDT', 'ONE/USDT', 'HNT/USDT',
    'FTM/USDT', 'DYDX/USDT', 'SUSHI/USDT', 'MAGIC/USDT', 'AUDIO/USDT',
    'ENS/USDT', 'GMT/USDT', 'BLUR/USDT', 'PEPE/USDT', 'LQTY/USDT',
    'SSV/USDT', 'TRX/USDT', 'XEC/USDT', 'INJ/USDT', 'STG/USDT',
    'HBAR/USDT', 'ICP/USDT', 'CRO/USDT', 'KLAY/USDT', 'RPL/USDT',
    'GMX/USDT', 'CFX/USDT', 'TWT/USDT', '1INCH/USDT', 'FXS/USDT',
    'KAS/USDT', 'BSV/USDT', 'BCH/USDT', 'ZIL/USDT', 'FET/USDT'
]

# Variables globales
crypto_data = {}
last_update_time = datetime.utcnow()
data_lock = threading.Lock()
data_queue = queue.Queue()
initial_data_ready = threading.Event()
current_config = {
    'timeframe': ('15m', '1h'),
    'volume_filter': 'Todas',
    'rsi_period': 14,
    'lower_x': 30,
    'upper_x': 70,
    'lower_y': 30,
    'upper_y': 70,
    'single_coin': 'Todas',
    'sma1_period': 5,   # Nuevo parámetro SMA1
    'sma2_period': 20    # Nuevo parámetro SMA2
}

# Configuración de exchange
exchange = ccxt.kucoin({
    'enableRateLimit': True,
    'timeout': 30000
})

# Funciones de cálculo
def compute_rsi(series, period=14):
    if len(series) < 2:
        return 50
    
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    
    ma_up = up.ewm(alpha=1/period, adjust=False).mean()
    ma_down = down.ewm(alpha=1/period, adjust=False).mean()
    
    rs = ma_up / ma_down
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def fetch_ohlcv(symbol, timeframe, limit=50):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if ohlcv:
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            return df
        return None
    except Exception as e:
        logger.warning(f"Error obteniendo datos para {symbol} ({timeframe}): {str(e)}")
        return None

def calculate_trend(df, sma1_period=5, sma2_period=20):
    """Calcula la tendencia con SMA personalizables"""
    if len(df) < max(sma1_period, sma2_period):
        return "Lateral"
    
    df['SMA1'] = df['close'].rolling(window=sma1_period).mean()
    df['SMA2'] = df['close'].rolling(window=sma2_period).mean()
    
    if df['SMA1'].iloc[-1] > df['SMA2'].iloc[-1]:
        return "Alcista"
    elif df['SMA1'].iloc[-1] < df['SMA2'].iloc[-1]:
        return "Bajista"
    else:
        return "Lateral"

def calculate_rsi_for_symbol(symbol):
    asset_data = {
        'symbol': symbol,
        'rsi1': 50,
        'rsi2': 50,
        'volume': 0,
        'trend': "Lateral"
    }
    
    try:
        tf1, tf2 = current_config['timeframe']
        
        # Obtener datos para el primer timeframe
        df1 = fetch_ohlcv(symbol, tf1, limit=50)
        if df1 is not None and not df1.empty:
            asset_data['rsi1'] = compute_rsi(df1['close'], current_config['rsi_period'])
            # Usar SMA personalizables
            asset_data['trend'] = calculate_trend(
                df1, 
                current_config['sma1_period'], 
                current_config['sma2_period']
            )
            asset_data['volume'] = df1['volume'].iloc[-1] if not df1.empty else 0
        
        # Obtener datos para el segundo timeframe
        df2 = fetch_ohlcv(symbol, tf2, limit=50)
        if df2 is not None and not df2.empty:
            asset_data['rsi2'] = compute_rsi(df2['close'], current_config['rsi_period'])
        
        return asset_data
    except Exception as e:
        logger.warning(f"Error procesando {symbol}: {str(e)}")
        return asset_data

def fetch_crypto_data():
    global crypto_data, last_update_time
    
    logger.info("Iniciando actualización de datos...")
    start_time = time.time()
    new_data = {}
    
    # Procesar símbolos con notificación de progreso
    for i, symbol in enumerate(symbols):
        try:
            result = calculate_rsi_for_symbol(symbol)
            if result:
                new_data[symbol] = result
            
            # Enviar progreso a la cola
            data_queue.put({
                'symbol': symbol,
                'count': i + 1,
                'total': len(symbols)
            })
            
            # Pequeña pausa para evitar rate limits
            time.sleep(0.1)
        except Exception as e:
            logger.error(f"Error crítico en {symbol}: {str(e)}")
    
    # Calcular categorías de volumen
    volumes = [data['volume'] for data in new_data.values()]
    if volumes:
        high_thresh = np.percentile(volumes, 70) if len(volumes) > 1 else volumes[0] * 2
        low_thresh = np.percentile(volumes, 30) if len(volumes) > 1 else volumes[0] / 2
        
        for symbol, data in new_data.items():
            volume = data['volume']
            if volume >= high_thresh:
                new_data[symbol]['volume_cat'] = 'Alto'
            elif volume <= low_thresh:
                new_data[symbol]['volume_cat'] = 'Bajo'
            else:
                new_data[symbol]['volume_cat'] = 'Medio'
    
    # Actualizar datos globales
    with data_lock:
        crypto_data = new_data
        last_update_time = datetime.utcnow()
    
    elapsed = time.time() - start_time
    logger.info(f"Datos actualizados en {elapsed:.2f} segundos. Símbolos: {len(crypto_data)}/{len(symbols)}")
    initial_data_ready.set()

def get_plot_data():
    with data_lock:
        if not crypto_data:
            return pd.DataFrame()
        
        # Convertir a lista para DataFrame
        data_list = list(crypto_data.values())
        df = pd.DataFrame(data_list)
        
        # Filtrar por volumen si es necesario
        if current_config['volume_filter'] != 'Todas':
            df = df[df['volume_cat'] == current_config['volume_filter']]
        
        # Filtrar por moneda individual si es necesario
        if current_config['single_coin'] != 'Todas':
            df = df[(df['symbol'] == current_config['single_coin']) | (df['symbol'] == 'BTC/USDT')]
        
        return df

def create_plot():
    plot_data = get_plot_data()
    fig = go.Figure()
    
    if plot_data.empty:
        fig.add_annotation(
            text="Cargando datos...",
            x=0.5, y=0.5, 
            showarrow=False, 
            font=dict(size=24, color="blue")
        )
        fig.update_layout(
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            height=700
        )
        return fig
    
    # Mapeo de tendencia a símbolos de marcador
    trend_to_marker = {
        "Alcista": "triangle-up",
        "Bajista": "triangle-down",
        "Lateral": "circle"
    }
    
    # Crear trazas
    for i, row in plot_data.iterrows():
        symbol = row['symbol']
        coin_name = symbol.split('/')[0]
        
        # Asignar color por volumen
        if row['volume_cat'] == 'Alto':
            color = 'green'
        elif row['volume_cat'] == 'Medio':
            color = 'blue'
        else:
            color = 'red'
        
        # Bitcoin será naranja
        if coin_name == 'BTC':
            color = 'darkorange'
        
        # Tamaño del marcador
        size = 15 if coin_name == 'BTC' else 10
        
        # Símbolo del marcador según tendencia
        marker_symbol = trend_to_marker.get(row['trend'], "circle")
        
        # Texto para el tooltip
        hover_text = (f"{coin_name}<br>"
                     f"RSI X: {row['rsi1']:.2f}<br>"
                     f"RSI Y: {row['rsi2']:.2f}<br>"
                     f"Volumen: ${row['volume']:,.0f} ({row['volume_cat']})<br>"
                     f"Tendencia: {row['trend']}")
        
        fig.add_trace(go.Scatter(
            x=[row['rsi1']],
            y=[row['rsi2']],
            mode='markers+text',
            marker=dict(
                symbol=marker_symbol,
                size=size,
                color=color,
                line=dict(width=1, color='black')
            ),
            text=coin_name,
            textposition='top center',
            textfont=dict(
                size=10 if coin_name != 'BTC' else 12,
                color='black',
                weight='bold'
            ),
            name=coin_name,
            hoverinfo='text',
            hovertext=hover_text
        ))
    
    # Añadir líneas de referencia
    fig.add_shape(type="line", 
                  x0=current_config['lower_x'], y0=0, 
                  x1=current_config['lower_x'], y1=100,
                  line=dict(color="Green", width=2, dash="dash"))
    fig.add_shape(type="line", 
                  x0=current_config['upper_x'], y0=0, 
                  x1=current_config['upper_x'], y1=100,
                  line=dict(color="Red", width=2, dash="dash"))
    fig.add_shape(type="line", 
                  x0=0, y0=current_config['lower_y'], 
                  x1=100, y1=current_config['lower_y'],
                  line=dict(color="Green", width=2, dash="dash"))
    fig.add_shape(type="line", 
                  x0=0, y0=current_config['upper_y'], 
                  x1=100, y1=current_config['upper_y'],
                  line=dict(color="Red", width=2, dash="dash"))
    
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
            ticktext=[f"{x}" for x in range(0, 101, 10)],
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
            ticktext=[f"{y}" for y in range(0, 101, 10)],
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
    if not crypto_data:
        threading.Thread(target=fetch_crypto_data).start()
    
    # Esperar datos iniciales
    initial_data_ready.wait(timeout=10)
    
    fig = create_plot()
    graph_html = fig.to_html(full_html=False, include_plotlyjs='cdn')
    
    with data_lock:
        loaded_count = len(crypto_data)
    
    return render_template('index.html', 
                           graph_html=graph_html, 
                           current_config=current_config,
                           last_update=last_update_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                           loaded_count=loaded_count,
                           total_count=len(symbols),
                           symbols=symbols)

# Ruta para verificar estado de datos
@app.route('/data_status')
def data_status():
    progress = None
    if not data_queue.empty():
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
    
    timeframe_map = {
        '1m_5m': ('1m', '5m'),
        '3m_15m': ('3m', '15m'),
        '5m_30m': ('5m', '30m'),
        '15m_1h': ('15m', '1h'),
        '30m_2h': ('30m', '2h'),
        '1h_4h': ('1h', '4h'),
        '4h_1d': ('4h', '1d'),
        '1d_1w': ('1d', '1w')
    }
    
    need_refresh = False
    
    with data_lock:
        if param == 'timeframe':
            current_config['timeframe'] = timeframe_map.get(value, ('15m', '1h'))
        elif param == 'volume_filter':
            current_config['volume_filter'] = value
        elif param == 'period':
            current_config['rsi_period'] = int(value)
            need_refresh = True
        elif param == 'lower_x':
            current_config['lower_x'] = int(value)
        elif param == 'upper_x':
            current_config['upper_x'] = int(value)
        elif param == 'lower_y':
            current_config['lower_y'] = int(value)
        elif param == 'upper_y':
            current_config['upper_y'] = int(value)
        elif param == 'coin-filter':
            current_config['single_coin'] = value
        # Nuevos parámetros SMA
        elif param == 'sma1':
            current_config['sma1_period'] = int(value)
        elif param == 'sma2':
            current_config['sma2_period'] = int(value)
    
    # Si se cambió un parámetro que requiere recálculo
    if need_refresh:
        threading.Thread(target=fetch_crypto_data).start()
    
    return jsonify({'success': True})

# Función para actualizar datos periódicamente
def scheduled_update():
    logger.info("Ejecutando actualización programada de datos...")
    fetch_crypto_data()

# Iniciar la aplicación
if __name__ == '__main__':
    # Iniciar la carga de datos
    threading.Thread(target=fetch_crypto_data).start()
    
    # Programar actualizaciones cada 5 minutos
    scheduler = BackgroundScheduler()
    scheduler.add_job(scheduled_update, 'interval', minutes=5)
    scheduler.start()
    
    # Obtener puerto de entorno o usar 5000 por defecto
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
else:
    # Para entornos WSGI
    threading.Thread(target=fetch_crypto_data).start()
    scheduler = BackgroundScheduler()
    scheduler.add_job(scheduled_update, 'interval', minutes=5)
    scheduler.start()
