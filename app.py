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
import logging
import ccxt

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuración de exchange - Usamos KuCoin que es más global
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
rsi_data = pd.DataFrame()
last_update_time = datetime.utcnow()
data_lock = threading.Lock()
data_ready = False

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
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(alpha=1/period, adjust=False).mean()
    ma_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))

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
        logger.error(f"Error obteniendo datos para {symbol} {timeframe}: {str(e)}")
        return None

def calculate_rsi_for_symbol(symbol):
    """Calcula todos los RSI para un símbolo"""
    try:
        asset_data = {}
        volumes = []
        
        # Obtener datos para cada timeframe
        for tf in ['15m', '30m', '1h', '2h', '4h', '1d', '1w']:
            df = fetch_ohlcv(symbol, tf)
            if df is not None and not df.empty:
                rsi = compute_rsi(df['close'], current_config['rsi_period'])
                asset_data[tf] = rsi.iloc[-1]
                
                # Usar volumen del timeframe de 1h como referencia
                if tf == '1h':
                    volumes = df['volume'].tail(24).mean()
            else:
                asset_data[tf] = 50
                volumes = 0
        
        asset_data['symbol'] = symbol
        asset_data['volume'] = volumes
        return asset_data
    except Exception as e:
        logger.error(f"Error procesando {symbol}: {str(e)}")
        return None

def fetch_all_data():
    """Obtiene y procesa todos los datos de las criptomonedas"""
    global rsi_data, last_update_time, data_ready
    
    logger.info("Iniciando actualización de datos...")
    start_time = time.time()
    
    try:
        results = []
        
        # Procesar cada símbolo con un pequeño retraso para evitar rate limits
        for symbol in symbols:
            try:
                # Pequeña pausa para evitar sobrecargar la API
                time.sleep(0.5)
                
                result = calculate_rsi_for_symbol(symbol)
                if result:
                    results.append(result)
                    logger.info(f"Datos de {symbol} obtenidos")
            except Exception as e:
                logger.error(f"Error procesando {symbol}: {str(e)}")
        
        if results:
            df = pd.DataFrame(results)
            
            # Calcular categorías de volumen
            if len(df) > 0:
                volumes = df['volume'].values
                if len(volumes) > 0:
                    high_thresh = np.percentile(volumes, 70) if len(volumes) > 1 else volumes[0] * 2
                    low_thresh = np.percentile(volumes, 30) if len(volumes) > 1 else volumes[0] / 2
                    df['volume_cat'] = df.apply(lambda row: 
                        'Alto' if row['volume'] >= high_thresh else 
                        'Bajo' if row['volume'] <= low_thresh else 
                        'Medio', axis=1)
                else:
                    df['volume_cat'] = ['Medio'] * len(results)
            else:
                df['volume_cat'] = ['Medio'] * len(results)
            
            with data_lock:
                rsi_data = df
                last_update_time = datetime.utcnow()
                data_ready = True
            logger.info(f"Datos actualizados con éxito. Monedas: {len(results)}/{len(symbols)}")
        else:
            logger.warning("No se obtuvieron datos para ninguna moneda")
            data_ready = False
    except Exception as e:
        logger.error(f"Error crítico en fetch_all_data: {str(e)}")
        data_ready = False
    
    elapsed = time.time() - start_time
    logger.info(f"Tiempo total de actualización: {elapsed:.2f} segundos")
    return data_ready

def create_plot():
    """Crea el gráfico Plotly"""
    global rsi_data
    
    # Crear figura
    fig = go.Figure()
    
    if rsi_data.empty:
        fig.add_annotation(
            text="No se pudieron cargar datos. Intente actualizar más tarde.",
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
    
    # Filtrar datos
    plot_data = rsi_data.copy()
    if current_config['volume_filter'] != 'Todas':
        plot_data = plot_data[plot_data['volume_cat'] == current_config['volume_filter']]
    
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
        title=dict(text=f"{title}<br>{now}", font=dict(size=24)),
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
            tickfont=dict(size=14)
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
            tickfont=dict(size=14)
        ),
        template="plotly_white",
        showlegend=False,
        height=700,
        margin=dict(l=80, r=80, b=100, t=120, pad=20)
    )
    
    return fig

# Ruta principal
@app.route('/')
def index():
    global data_ready
    
    # Si los datos no están listos, mostrar página de carga
    if not data_ready:
        return render_template('loading.html')
    
    fig = create_plot()
    graph_html = fig.to_html(full_html=False, include_plotlyjs='cdn')
    return render_template('index.html', graph_html=graph_html, 
                           current_config=current_config,
                           last_update=last_update_time.strftime("%Y-%m-%d %H:%M:%S UTC"))

# Ruta para forzar actualización
@app.route('/refresh')
def refresh():
    threading.Thread(target=fetch_all_data).start()
    return jsonify({"status": "Actualización iniciada"})

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
        threading.Thread(target=fetch_all_data).start()
    
    # Crear nuevo gráfico
    fig = create_plot()
    graph_html = fig.to_html(full_html=False, include_plotlyjs=False)
    
    return jsonify({
        'success': True,
        'graph_html': graph_html,
        'last_update': last_update_time.strftime("%Y-%m-%d %H:%M:%S UTC")
    })

# Programar actualizaciones periódicas
scheduler = None
if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    try:
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            fetch_all_data, 
            'interval', 
            minutes=15,
            max_instances=1
        )
        scheduler.start()
        logger.info("Scheduler de actualización iniciado")
    except Exception as e:
        logger.error(f"Error iniciando scheduler: {e}")

# Iniciar la aplicación
if __name__ == '__main__':
    # Iniciar la carga de datos
    threading.Thread(target=fetch_all_data).start()
    
    # Obtener puerto de entorno o usar 5000 por defecto
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
